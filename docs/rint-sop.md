# Rint discharge SOP: literature-motivated mock policy

The separate opt-in [live mock Cell SOC mode](live-cell-state.md) now feeds this
same estimator from Coulomb Counting of qualified prototype mock readbacks.
The fixed-SOC Rint workflow described below remains available and unchanged.

This extends the working vehicle feedback path. It does not authorize physical
cell/instrument operation or establish validated battery safety limits. The
original SOC-band and fixed-fraction policies remain selectable and unchanged.

## Reference and parameter assessment

The supplied *An Enhanced Li-ion Battery Model with Optimized OCV Estimation*
(Oh Sing Ee Jenna et al., PEPSC 2025, DOI
[10.1109/PEPSC67251.2025.11453369](https://doi.org/10.1109/PEPSC67251.2025.11453369))
is identical to the existing repository PDF (SHA-256
`101dd5893d5ac550ef67a950c58137af6fc94d27b6d3328ce3c1668916d5c919`).
Its equation (15), PDF page 3, is already implemented in `cell_soc.py`:

```text
s = 100*z                       z: SOC fraction, s: SOC percent
U(z) = 6.634e-10*s^5 - 2.012e-7*s^4 + 2.221e-5*s^3
       - 0.001107*s^2 + 0.03365*s + 3.163      [V]
```

It names EVE-INR18650/35V cells and tests near 25 C. The printed polynomial is
monotonic over z=0..1, with image 3.163..4.182 V; it is not a fit down to the
2.50 V loaded cutoff. Do not extrapolate it or invert loaded voltage as OCV.
The prior [paper review](ocv-paper-review.md) still applies: the stated 6.8 mA /
five-minute / 10% procedure is inconsistent, and Table III repeats polynomial
MSE values as RMSE. The reported fit error is not an uncertainty bound for our
cell. Raw independent validation data and DC resistance parameters are absent.

The existing `documentation/18650.pdf`, printed specifications page 1 (PDF page
4), identifies typical capacity 3500 mAh, minimum capacity 3400 mAh, nominal
3.65 V and 2.50 V discharge cutoff. Its listed 10.2 A maximum-discharge condition
is marked not for cycle life; it is not our approved experiment current. The
datasheet's 1 kHz AC impedance measurement is not a DC/pulse R0 identification.
Published temperature conditions do not validate this OCV fit across that range.

| Quantity | Available evidence | Implementation treatment |
|---|---|---|
| OCV(SOC) | Candidate published relation, approximately 25 C | Reuse existing bounded reference; physically unvalidated |
| Capacity | Datasheet 3.5 Ah typical / 3.4 Ah minimum | Example uses typical value, not measured effective capacity |
| Voltage cutoff | Datasheet 2.50 V under discharge | Explicit mock choice, not lab approval |
| DC R0(SOC,T,SOH) | No experimental map | Mandatory explicit assumption; no hidden default |
| Discharge current limit | No approved cell envelope in software | Explicit mock setting; does not change instrument limits |
| Temperature dependence | No identified OCV/R0/thermal map | Reject outside assumed model qualification, not physical protection |
| SOC/error bounds | No independently validated live cell estimate/bounds | Supplied mock SOC and explicit assumed margins |
| Dynamic parameters | No RC, hysteresis or thermal identification | Not implemented or claimed |

Academic basis:

- Malysz, Ye, Gu, Yang and Emadi, *Battery State-of-Power Peak Current Calculation
  and Verification Using an Asymmetric Parameter Equivalent Circuit Model*, IEEE
  TVT 65(6), 4512-4522 (2016), DOI 10.1109/TVT.2015.2443975.
  [Author-hosted paper](https://intelligentpower.engr.uga.edu/wp-content/uploads/2019/10/Pawel2016Battery.pdf).
  Equations (12)-(14) describe SOC-current and ohmic voltage constraints. The
  following dynamic methods require additional identified states/parameters and
  a prediction horizon. This implementation uses the simpler instantaneous case.
- Nejad, Gladwin and Stone, *A systematic review of lumped-parameter equivalent
  circuit models for real-time estimation of lithium-ion battery states*, JPS
  316, 183-196 (2016), DOI 10.1016/j.jpowsour.2016.03.042.
  [Accepted manuscript](https://eprints.whiterose.ac.uk/id/eprint/113902/1/03493R2.pdf).
  Sections 3 and 4.2 discuss SOP and Rint; the simple circuit omits dynamics and
  can give uncertain SOP estimates. Pulse-derived effective resistance depends
  on duration and should not silently be substituted for instantaneous R0.

These references justify the method, not transfer of their cell parameters.

## Implemented equations and scope

All discharge currents below are **positive magnitudes**. Existing signed cell
telemetry is unchanged: discharge negative, charging positive. SOC is fractional
at every API boundary; only the candidate polynomial internally uses percent.

```text
z_low = max(0, z - assumed_SOC_margin)
U_guard = OCV(z_low) - assumed_OCV_margin_V
R_guard = assumed_R0 + assumed_R0_margin

V_terminal(I) = U_guard - I*R_guard
I_voltage = max(0, (U_guard - V_min)/R_guard)
I_SOC = max(0, 3600*Q_Ah*(z_low-z_reserve)/horizon_s)
I_allowable = min(I_configured, I_voltage, I_SOC)
```

The stated horizon applies only to removable charge with an assumed effective
discharge capacity. Voltage is quasi-static at the current guarded SOC. There
is no claim of sustained voltage over that horizon, polarization, hysteresis or
temperature prediction. The sample 10 s value is a demonstration assumption.

For ordinary voltage limits (V_min >= U_guard/2), maximum allowed current also
maximizes allowed power. For arbitrary test inputs the parabola has a peak, so
the implementation separately reports:

```text
I_at_SOP = min(I_allowable, U_guard/(2*R_guard))
P_SOP = (U_guard - I_at_SOP*R_guard)*I_at_SOP
```

This avoids returning a smaller supposed maximum by evaluating past the power
peak. At/below the SOC reserve, a zero current cap, or OCV below the voltage
floor, the permissible discharge is zero. Temperature outside the explicitly
assumed range invalidates the model. The candidate reference's existing 25 +/-2 C
qualification is itself an engineering assumption, not validated thermal limits.

Assumed uncertainty margins reduce OCV/SOC and increase resistance. They are not
statistical confidence intervals, fitted error distributions or guarantees. The
model never labels the current reference/configuration physically validated.

## Converting cell SOP to native propulsion availability

Use the receiver's actual `CellParameters` and captured vehicle profile:

```text
k = nominal_cell_voltage * nominal_cell_capacity_Ah / pack_capacity_Wh
    * experiment_scale
P_cell_discharge = k * P_pack_draw
P_pack_allowable = P_SOP / k
P_motor_allowable = clamp(eta_drive*(P_pack_allowable - P_aux), 0, P_motor_rated)
availability = P_motor_allowable / P_motor_rated
```

Currently k = 3.65*3.5/50000*0.06 = 1.533e-5, eta_drive=0.92,
P_aux=300 W and P_motor_rated=202000 W. These are the exact existing simulation
choices, not validated Tesla efficiencies or a real cell series/parallel count.
The adapter calls existing `scale_to_cell(1)` to obtain k rather than duplicating
or changing its signs/calculations. Protocol fractions round down to nine decimal
places so formatting cannot increase this ceiling.

The existing native fraction scales the entire positive torque/power envelope,
therefore delivered motor power stays below this ceiling at all positive RPM.
It can be conservative at low RPM; it is not a new constant-power torque law.
Dividing by already-derated delivered power would instead produce an unstable
feedback ratio. Requested unlimited motor power is reconstructed using the
existing torque envelope/pedal law, with braking and speed constraints; actual
delivered motor power remains separately logged.

If SOP cannot cover scaled auxiliary load, propulsion is zero and that condition
is flagged. Native auxiliaries are not switched off, so total pack draw cannot
then satisfy a zero battery budget. This is propulsion derating, not isolation.
Likewise legacy scaled current uses nominal 3.65 V; it is not a physical Rint
terminal-current measurement and need not equal the positive modeled I_allowable.

## Launch and dashboard

No hardware mode is added. From the repository root, with TORCS closed:

```powershell
& .\.venv-bench\Scripts\python.exe -B scripts/run_vehicle_power_limit.py --policy rint --sop-config aps380_torcs_starter/profiles/rint_sop_mock_example.json --mode keyboard --duration 300 --skip-build
```

The previously built vehicle-feedback native DLL is required. Omit `--skip-build`
to rebuild it. For the existing G29 profile change only `--mode g29`; controls,
calibration and smoothing remain unchanged. The example contains a **synthetic
50 mOhm R0** and explicit margins, chosen only for mock testing; no EVE parameter
identification is implied. Edit a copy under ignored `.local/` for other mock
cases. The launcher requires `--sop-config`; `--fraction`/`--demo-soc` cannot
silently override an Rint run. The default `--policy demo` behavior is retained.

The dashboard labels supplied mock cell SOC/temperature, candidate OCV, assumed
R0, estimated current/SOP, requested unlimited motor power and applied native
fraction. There are no physically measured cell quantities in this mode. The
mock cell SOC input is separate from native pack SOC and is not an online cell
SOC observer. Existing measured-current SOC replay remains a separate workflow.

Invalid model data stops feedback; native 500 ms expiry still latches zero
propulsion. Restoring valid model state alone cannot resume feedback: explicit
RESET is required, and native fault recovery remains unchanged. Known low-SOC
or current-budget exhaustion commands zero without treating a valid constrained
estimate as a communication fault. Native malformed-command, replay/session,
timeout, reset and zero-shutdown acknowledgement behavior is reused unchanged.

Outputs retain original CSV/JSONL and add `sop_*` diagnostic fields, copied mock
configuration and source hashes. No measurements are synthesized as real data.

The supplied mock cell SOC/temperature are held inputs, not fresh physical
measurements or a new online SOC observer. Before measured state integration,
add measurement age/quality checks and independently validate the existing SOC
counter and voltage/current/temperature acquisition chain.

## Validation and lab work still required

`scripts/validate_rint_sop.py --output .local/rint-sop-validation/new-comparison`
uses actual TORCS with the existing isolated human-code fixture and mock PSU/
eLoad coordinator. It compares the same key inputs/initial conditions with 1.0,
0.5 and 0.2 A **assumed** cell-current caps. A separate invalid-temperature model
test verifies native zero, no automatic recovery, explicit reset and shutdown.

Observed mock results (same controls over 51 matching samples in the 1..2 s
window; 2105 valid telemetry samples across the three driving runs):

| Assumed current cap | Estimated cell SOP | Vehicle availability | Speed at 2 s | Peak motor power first 2 s |
|---|---:|---:|---:|---:|
| 1.0 A | 3.950 W | 100% | 3.223 m/s | 25.757 kW |
| 0.5 A | 1.990 W | 58.99% | 1.796 m/s | 9.480 kW |
| 0.2 A | 0.800 W | 23.62% | 0.681 m/s | 1.435 kW |

Power ratios differ from the fractions because motor RPM changes during
acceleration. Native applied fractions and motor ceilings were also checked.
The invalid-model run passed fault-response acceptance with zero positive motor
power, valid telemetry, explicit recovery and zero shutdown. Normal operation
remained FAIL for that deliberate fault. A graphical run used mock cell SOC 50%
while native pack SOC remained separate. All 192 starter tests (18 new SOP
tests), 73 BK8500 tests, four setup tests and 131 existing native checks passed.
Native code/protocol/DLL hashes matched the working limiter, and all 39 protected
instrument, input, profile and scaling hashes remained identical. These are
Windows mock results, not EVE cell validation. Local evidence is under
`.local/rint-sop-validation/`.

Before physical SOP use, independently establish rested SOC/OCV points, effective
discharge capacity, DC pulse R0 over SOC/temperature/age, voltage/current sensing
bias and timing, terminal-voltage residuals under dynamic load and the required
prediction horizon. Identify RC/relaxation or duration-specific effective
resistance if finite-duration power is required. Establish temperature dependence
and approved electrical/thermal limits with independent protection. Quantify
SOC/OCV/R0/model uncertainty against held-out measurements. Neither paper RMSE
nor a passing mock test supplies those bounds. Do not run pulses or physical
current from this documentation without a separately approved lab procedure.
