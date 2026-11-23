# Low-SOC Rint propulsion demonstration (mock only)

The existing measured mock current -> Coulomb Counter -> candidate OCV -> Rint
SOP -> Python/native propulsion feedback already implements this behavior.
No estimator, vehicle physics, control profile, instrument slew, hardware driver
or physical protection setting was changed for this demonstration.

## What the unchanged model predicts

SOC `z` is a fraction, not a percentage. The candidate OCV reference converts
that fraction to the percent units required by its polynomial internally.
For the existing live-mock profile:

```
z_guard = max(0, z - 0.02)
U_guard = OCV(z_guard) - 0.05 V
R_guard = 0.05 + 0.01 = 0.06 ohm
I_voltage = max(0, (U_guard - 2.5 V) / R_guard)
I_budget = max(0, 3600 * 3.5 Ah * (z_guard - 0.10) / 10 s)
I_allow = min(0.5 A, I_voltage, I_budget)
I_power = min(I_allow, U_guard / (2 * R_guard))
SOP = (U_guard - I_power * R_guard) * I_power
```

Temperature must be inside the assumed 23..27 C model interval; the synthetic
temperature is 25 C. The reserve, margins, resistance, capacity, voltage floor,
temperature qualification and OCV fit remain **unvalidated mock assumptions**.
The horizon constrains charge budget only; Rint does not predict polarization or
thermal dynamics over that horizon. The synthetic sensor voltage is separate
from candidate OCV. No physical battery SOC or SOP is measured here.

| SOC % | Candidate OCV V | Allowable A | SOP W | Propulsion % | Binding constraint |
|---:|---:|---:|---:|---:|---|
| 80 | 4.0744 | 0.500 | 1.9902 | 58.99 | Current |
| 40 | 3.7121 | 0.500 | 1.8075 | 53.56 | Current |
| 20 | 3.5408 | 0.500 | 1.7198 | 50.96 | Current |
| 12.04 | 3.4424 | 0.500 | 1.6649 | 49.33 | Current |
| 12.02 | 3.4421 | 0.252 | 0.8428 | 24.90 | SOC budget |
| 12.001 | 3.4418 | 0.0126 | 0.0423 | 1.12 | SOC budget |
| 12 | 3.4418 | 0 | 0 | 0 | SOC reserve |
| 10 | 3.4091 | 0 | 0 | 0 | SOC reserve |
| 5 | 3.3062 | 0 | 0 | 0 | SOC reserve |

The 0.5 A cap masks a voltage-limited knee: even at zero SOC, the candidate
voltage constraint would permit over 10 A. Do not interpret that as a real-cell
capability. The current cap is active above approximately 12.03968%; the narrow
SOC-budget transition ends at 12% (10% reserve plus 2% uncertainty margin).
At 10% this model intentionally permits no propulsion. No arbitrary SOC lookup
table or exaggerated resistance was added to force a voltage knee.

Vehicle conversion remains the existing equivalent-energy experiment mapping:
`k = 1.533e-5 cell W / pack W`, `P_pack = SOP/k`,
`P_motor = min(202000, max(0, 0.92*(P_pack - 300)))`,
`fraction = P_motor/202000` (rounded down for transmission).
This is not a validated physical pack topology. Native TORCS applies the
fraction to positive propulsion availability; regeneration is preserved.
The 300 W auxiliary allowance can remove propulsion just before SOP reaches zero.

## Run it yourself

Open PowerShell in the repository's `APS380` folder. Close other TORCS sessions
before starting a comparison. Output folders below must not already exist.
All commands below use mocks; none select a serial port or a physical driver.

Offline table/plot, then identical scripted native keyboard-input comparisons:

```powershell
.venv-bench\Scripts\python.exe -B scripts\analyze_low_soc.py --output .local\low-soc-sweep-new
.venv-bench\Scripts\python.exe -B scripts\validate_bias_power.py --soc-comparison --output .local\low-soc-native-new
```

The comparison uses the existing native human-driver fixture. It checks identical
applied throttle/brake samples in simulation seconds 7..8, native ACKs, measured
mock current integration and SOP recalculation, lower actual motor output/speed,
native zero shutdown and mock isolation/output shutdown. `summary.json`, raw
telemetry, instrument logs and `comparison.png` are saved under the output.
Small passive vehicle movement at zero propulsion is not motor output.

For more comfortable manual driving, the separate 20% initial-SOC profile starts
at approximately 50.96% propulsion availability (candidate OCV 3.541 V, SOP
1.720 W, allowable discharge current 0.5 A). Its model parameters, 10% reserve
and 2% SOC uncertainty margin match the default exactly. SOC depletion is not
accelerated: decreases are gradual during a short session, with the stronger
reserve derating only appearing near 12%. Existing profiles are preserved.

```powershell
.venv-bench\Scripts\python.exe -B bench\bk8500\live_torcs.py --control-mode battery-bias --device mock --mock-preset manual-driving --propulsion-feedback --torcs keyboard --keyboard-profile 8s --dashboard --duration 180 --sop-config aps380_torcs_starter\profiles\rint_sop_20_percent_mock.json
```

`--mock-preset manual-driving` imposes a 1.0 A **synthetic source contribution**.
With the existing eLoad range 0..3 A, the steady-state feasible cell range is
`1.0 - [0,3] = [-2,+1] A`, matching the existing configured directional limits.
The 20% SOC profile, Rint discharge cap and all model equations are unchanged.
This does not predict how much a physical PSU in CV will deliver.

Startup still keeps the cell isolated, slews the load toward the measured source
current, and qualifies fresh neutral branch balance before RUNNING. At unchanged
0.02 A/s branch slew, balancing a 1 A source takes roughly 50 seconds plus settling;
wait for RUNNING. The duration includes menus/startup. Use a longer `--duration`
if desired; the preset never automatically arms or changes the duration.

The default `--mock-preset baseline` retains the original 0.2 A contribution and
its infeasible-regeneration fault tests. `--mock-psu-current-A` remains an explicit
override for either preset; preset name, override flag and effective contribution
are recorded in `mode.json`. Actual measured source current remains the basis of
all feasibility checks. If it falls below the charging demand, the controller
still faults; neither clipping nor tolerance relaxation hides that condition.
The manual preset changes no hardware configurations, approvals or safety limits.

Manual-preset validation: 272 starter tests, 104 bench tests, three keyboard
profile tests and 131 native executable checks passed. New tests cover isolated
neutral startup with charging already requested, repeated -0.4712/+0.21294 A
driving demands, steady-state -2/+1 A endpoints, and a source-readback drop back
to 0.2 A that must still produce `INFEASIBLE_CURRENT`. The latest recorded manual
session's demand trace was replayed three times with the 1 A synthetic source:
no faults, approximately 2.01 mA maximum applied-current tracking error and
verified mock shutdown. A separate 180-second actual native TORCS AI run reached
RUNNING after 54.27 seconds with source/load balanced at approximately 1 A,
accepted 9009 packets without loss/invalid data, and verified mock shutdown plus
the final native-zero acknowledgement. That AI run only exercised small charging
requests (peak +0.00696 A); large lift-off cases are supported by the recorded
replay and endpoint tests, not claimed as reproduced by the AI driver. Local
evidence is under `.local/bias-manual-preset/`. Manual input feel remains a user
test; these are mock validations and not physical Battery Bias authorization.

For manual keyboard driving near the reserve with the existing 8-second profile:

```powershell
.venv-bench\Scripts\python.exe -B bench\bk8500\live_torcs.py --control-mode battery-bias --device mock --propulsion-feedback --torcs keyboard --keyboard-profile 8s --dashboard --duration 180 --sop-config aps380_torcs_starter\profiles\rint_sop_near_reserve_mock.json
```

Type `ARM` and Enter in the terminal (or use existing mock ARM control). Wait for
RUNNING. Near-reserve SOC starts at 12.02%, giving about 24.9% propulsion, then
changes from **measured mock cell current**, not target current. Default signed
cell current is charging-positive: discharge lowers SOC; charge raises it.
The counter uses the unchanged real 3.5 Ah assumption and actual timestamps:
no accelerated-depletion factor was introduced. Low initial SOC makes the
existing narrow reserve transition visible without waiting hours.

To demonstrate zero SOP at 10%, substitute
`aps380_torcs_starter\profiles\rint_sop_low_soc_mock.json`.
For the original 80% initial SOC, substitute
`aps380_torcs_starter\profiles\rint_sop_live_mock_example.json`.
Profiles are separate files; the default remains unchanged. G29 can use the same
SOP profile via `--torcs g29` without `--keyboard-profile`; its controls are unchanged.

`DISARM` removes availability. `STOP` latches the existing mock emergency fault.
For fault recovery: `RESET`, `ARM`, wait for RUNNING, then `RESET POWER` explicitly.
`QUIT` ends the run and verifies shutdown. All prior mock-only restrictions and
independent physical safety requirements remain; deferred High/Medium Battery
Bias review findings remain unresolved.

Automated single-session example:

```powershell
.venv-bench\Scripts\python.exe -B bench\bk8500\live_torcs.py --control-mode battery-bias --device mock --propulsion-feedback --torcs ai --duration 60 --telemetry-port 0 --auto-arm-mock --no-console --sop-config aps380_torcs_starter\profiles\rint_sop_near_reserve_mock.json --output .local\low-soc-evolution-new
.venv-bench\Scripts\python.exe -B scripts\analyze_low_soc.py --output .local\low-soc-analysis-new --session .local\low-soc-evolution-new
```

## November 20 validation

All five native comparison cases passed. Peak motor output in the matched
window was 2259, 1980, 1615, 667 and 0 W at 80%, 40%, 20%, 12.02% and 10% SOC.
Speed at 8 s was 0.7167, 0.6298, 0.5855, 0.2689 and 0.0938 m/s respectively.
These are low-speed fixture measurements, not rated-power or on-road validation.

In a separate 60-second native AI run, SOC decreased from 12.0200% to 12.01626%,
SOP fell from 0.8428 to 0.6859 W, and positive native-applied availability fell
from 24.9013% to 20.2405%. Startup and intentional shutdown include native zero
samples. Tracking error stayed below 2 mA; telemetry/instrument acceptance and
verified mock/native-zero shutdown passed. No synthetic fast-forward was used.

The recent timing regression also passed all nine checks using actual TORCS/Tk:
250/320 ms mock acquisition pauses and slow GUI refresh, explicit exclusion of
unobserved SOC intervals, genuine measurement-loss fault/zero propulsion,
verified mock shutdown and explicit recovery. A separate 10%-SOC launcher trial
passed with valid RUNNING zero-SOP acknowledgements. Acceptance now recognizes
that valid zero-power operation; startup-only zero, stale/invalid models and
unacknowledged commands still fail.

Local evidence is under `.local/low-soc/`; it is intentionally excluded from Git.
Full starter/bench/profile suites passed 269/103/3 tests; native executables
passed 131 checks. Physical hardware was not accessed or validated by these tests.
