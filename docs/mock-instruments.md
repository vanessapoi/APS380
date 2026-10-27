# Mock prototype PSU and electronic-load control

This implementation is **mock only**: no physical PSU, eLoad, ESP32 or battery
connection exists. Operating values are experimental software settings, not
verified hardware safety ratings. Independent hardware protection remains a
separate requirement. The coordinator rejects devices without its mock marker.

## Current prototype configuration

`aps380_torcs_starter/prototype_current_config.py` is the single source for the
immutable `PrototypeCurrentConfig` / `ControlConfig` defaults:

| Setting | Prototype value |
|---|---:|
| PSU fixed CC setpoint | 1.0 A |
| PSU allowed current | 0 to 1.0 A |
| eLoad CC setpoints, including enabled zero | 0 to 3.0 A |
| Battery current | -2.0 to +1.0 A |
| Current slew | 0.2 A/s |
| Neutral tolerance / continuous dwell | 0.002 A / 0.1 s |
| Tracking tolerance / timeout | 0.03 A / 0.6 s |
| Reversal deadline | Automatically budgeted; 20 s at defaults |
| Worker rate | 10 Hz |
| Command / measurement expiry | 0.5 / 0.2 s |
| I/O timeout / initial READY deadline | 0.02 / 30 s |

The reversal deadline includes the configured current interval, slew steps,
neutral dwell, settling allowance, worker period and four bounded I/O transactions
per cycle. Returning from -2 A to zero needs 10 s of nominal slew steps; bounded
communication adds wall time. Explicit shorter deadlines are rejected. These are
mock policy budgets, not measured physical settling times. Communication expiry
and overcurrent supervision remain independent.
The final-design 2 A PSU, 12 A eLoad and earlier 0.5 A bias are not prototype
settings. No positive-only shifting or online normalization is implemented.

**Cell current is charging-positive:** negative means discharge; positive means
charge. Branch currents are nonnegative magnitudes under their defined directions:

`i_cell = i_PSU_measured - i_eLoad_measured`

`i_eLoad_target = i_PSU_measured - i_cell_applied`

At measured PSU current 1 A: cell -2 A requires load 3 A; neutral requires load
1 A; cell +1 A requires load 0 A. A zero eLoad setpoint is valid while enabled;
it is not DISARMED. Both outputs are disabled and isolation opened on stop/fault.
The PSU setpoint is configured during arming and stays fixed throughout RUNNING.
Fresh readback, not the configured limit, determines eLoad demand. Unexpected
setpoint changes and CV/loss of required CC operation fault. `MockPSU` retains
its CV envelope only for fault injection; CV cannot qualify startup or RUNNING.

## Startup, feasibility and faults

READY enables the isolated branches and balances at zero net cell current.
No live positive/negative demand is applied, nor is its operational feasibility
checked against the first rising PSU sample. Both branch currents and PSU bias
must settle; fresh readbacks, fresh validated demand, and continuous neutral dwell
precede isolation closing and RUNNING. The next cycle applies the newest demand.
The existing latest-value mailbox and independent worker never queue old demands.

The battery-limited target is bounded by configured signed cell limits. Its
feasible interval is also intersected with
`[PSU_actual - eLoad_max, PSU_actual - eLoad_min]`. Infeasible demands fault before
sending a new load command. Only explicitly logged floating-point adjustment
within `numeric_tolerance_A` (1e-9 A) may snap an endpoint; this is not a physical
measurement allowance. PSU underdelivery can make the +1 A charging endpoint
unachievable. Do not substitute the nominal PSU setpoint to hide this.

A reversal slews to zero, verifies measured neutral dwell, then consumes the
latest direction. Expiry, session changes, invalid/stale measurements, unexpected
direction, communication failure, CC failure, measured battery overcurrent and
emergency stop latch faults. Battery overcurrent is checked both before and after
new load commands; compensation cannot hide a previously observed excursion.
The mock local isolation trip disables both branches even if transport is broken.
Recovery verifies disabled, communicating instruments and open isolation, returns
to DISARMED, and requires a fresh sample and separate arming. Valid native ENDED
disarms normally; new telemetry never automatically rearms control.

## Data, displays and compatibility

Native TORCS pack power/current remain **positive for draw**, unchanged in CSV and
UDP. `scale_to_cell()` converts once into charging-positive cell power/current.
No controller, mailbox or HUD performs a second conversion. Native pack SOC and
vehicle physics are unchanged. Measured-cell SOC replay now adds integrated
charging-positive current; this does not connect SOC/SOP to the live coordinator.

New data carry `current_schema_version: 2`, `cell_current_convention:
charging_positive`, and an explicit native pack convention. Original native power
and current, cell target, limited target, applied target, mock-measured current,
branch setpoints/readbacks, ages, source sequence and saturation remain distinct.
The dashboard and saved live plot show target/limited/applied/mock-measured data.
Tracking error compares mock measured with applied; demand error compares measured
with limited. Large slew-induced lag remains visible separately from tracking.

Historical recordings are unchanged. Old derived cell currents were discharge-
positive: do not interpret them as schema 2. The original `data/mock_cell_soc.csv`
is retained as legacy input; use `mock_cell_soc_charging_positive.csv` with the
updated replay configuration. Replay requires an explicit current convention.
HUD payload **APS380HUD2** uses charging-positive CELL signs and unchanged native
PACK signs. Its parser rejects APS380HUD1, avoiding silent sign disagreement.
Rebuild graphics/client after updating; an old binary cannot display V2 feedback.

Instrument snapshots after disarm/fault are marked `measurements_retained` and
`measurement_context` (`retained_after_disarm` or `retained_pre_fault`). Nested
status/readbacks are historical; the separate verified isolation/output state and
`mock_cell_current_A` describe shutdown. Snapshot acquisition ages remain visible.

## Run mock experiments

From the repository root in PowerShell:

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B scripts/run_mock_instruments.py --arm-mock
```

This takes about 37 seconds and covers a saturated discharge target, neutral, and
full configured charging. Synthetic native power goes through the same scaling
boundary. Deliberate terminal telemetry loss must latch an expiry fault and verify
shutdown. Results are under `.local/mock-instruments/`; no TORCS is launched.

For the graphical TORCS demonstration, rebuild using the existing launcher:

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B scripts/run_tesla_live.py --mode g29 --duration 300 --mock-instruments
```

Start Practice and drive using configured controls. Mocks start DISARMED; use Arm
mock. Dashboard buttons retain Disarm, Emergency stop and Clear fault. Clearing a
fault does not arm. `--skip-build` is appropriate only after rebuilding HUD V2.
Normal logs, raw recordings and instrument JSONL remain under the trial directory.
Optional narrower charging limits use `--mock-charge-limit`; the immutable control
configuration is saved in the trial. Prototype defaults come from the module above.

For native AI startup during net regeneration and deliberate telemetry loss:

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B scripts/validate_mock_interruption.py --arm-on-regeneration --healthy-seconds 30
```

This waits DISARMED for negative native pack power, then arms during positive CELL
charging demand. It verifies both directions before stopping TORCS and keeping
supervision active until expiry. Pre-interruption integration and fault response
are reported separately; normal uninterrupted-operation acceptance must fail.

Reports retain PASS / FAIL / NOT ASSESSED. No RUNNING samples means tracking is
unassessed; requested arming without RUNNING fails acceptance. A successful final
shutdown cannot erase a previous fault. Smoke acceptance does not require full-
course completion. All raw current limits, source timing and native CSV checks
remain active.

## Windows UDP shutdown

Expected launcher shutdown stops HUD replies before ending its native peer. Only
reset 10054 after that explicit boundary is recorded as expected; unexpected reset
or other errors remain receiver failures. Deliberate telemetry-loss trials do not
mark the interruption orderly before fault detection. See the
[Microsoft recvfrom reference](https://learn.microsoft.com/en-us/windows/win32/api/winsock/nf-winsock-recvfrom)
for the Windows UDP reset behavior. No global reset suppression is used.

## Tests

```powershell
$env:MPLCONFIGDIR = Join-Path (Get-Location) '.local/matplotlib'
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B -m unittest discover -s aps380_torcs_starter -p 'test*.py'
```

Mock results do not validate real CC capability, compliance voltage, low-voltage
load operation, measurement synchronization, battery limits or hardware isolation.
No physical instrument commands or new vehicle derating are supplied.

## Review corrections - October 27, 2026

Live scaling and instrument control now share the effective centralized config,
including narrower CLI charging limits; conflicting JSON bounds are rejected.
The mailbox requires explicit schema 2 and charging-positive metadata. Acceptance
requires complete RUNNING evidence and independently checks the readback mapping,
CC modes, fixed PSU setpoint, path state and current direction. Reversal deadlines
include bounded transaction time, and configurable nonzero branch minima cannot
prematurely fail isolated startup. Prototype defaults still permit enabled 0 A.

TORCS previously published one grid-initialization sample at time zero before
its countdown, causing an initial gap of about 3.3 s. Recording and optional
pacing now start at active race time; EV physics remain unchanged. Stale detection
and acceptance are unchanged. New reports retain sender/host gaps and terminal
silence evidence rather than exempting it. Historical trial `20261027_124417_714560`
also has a genuine terminal interruption and a TELEMETRY_EXPIRED instrument fault;
its failure was not solely the startup telemetry gate. Historical files remain
unchanged and retain their original current convention.

Review evidence is saved under `.local/prototype-review/`, with focused regression
tests in `test_review_regressions.py`. The final Python suite executed 164 tests:
163 passed and one Tk test skipped because `init.tcl` is unavailable. Native tests
passed 18 EV kernel, 15 publisher and 9 HUD checks. Actual headless integration
tests and an independent source-to-command audit are recorded in that directory.
GUI layout, manual controls and in-game rendering still require desktop testing.

## Prototype validation before this review - October 27, 2026

- Python: **154 tests executed, 153 passed, one Tk widget initialization test
  skipped** because this environment lacks a usable `init.tcl`. A separate
  dashboard presentation test passes without Tk and checks signs, branch values,
  applied/measured targets and retained-data labeling.
- Native: **18 EV kernel + 9 publisher + 9 HUD checks passed**. Graphics/client
  and the HUD test were rebuilt; native EV simulation sources were not changed.
- `.local/prototype-current-validation/smoke`: 15-second actual TORCS AI smoke,
  746 native/received samples, zero missing/invalid packets, all normal acceptance
  gates passed, verified orderly mock shutdown, max tracking error 0.004992 A.
- `.local/prototype-current-validation/regen-interruption`: actual TORCS AI ran
  223.78 simulation seconds; all 11,190 samples matched native CSV with zero
  missing/invalid packets. Arming during native regeneration produced a positive
  cell target (+0.001104 A); balanced isolated startup took about 0.530 s. Both
  cell-current signs tracked. Maximum RUNNING tracking error was 0.020085 A.
  Deliberate interruption latched STALE_TELEMETRY about 0.553 s after interruption,
  disabled both outputs and opened isolation. Pre-interruption integration and
  fault-response checks passed; uninterrupted normal-operation acceptance failed
  as required for this deliberate fault.
- `.local/prototype-current-validation/endpoints`: a synthetic mock experiment
  reached applied/measured -2 A, neutral and +1 A. PSU commands stayed at 1 A;
  load setpoints spanned 0 to 3 A, with **68 RUNNING cycles at enabled 0 A**. Terminal
  telemetry expiry verified both outputs disabled and isolation open. Maximum
  tracking error was 0.020132 A. As expected, instantaneous demand lag during the
  large steps reached about 2 A under the retained 0.2 A/s slew; this is recorded
  separately and does not represent accurate instantaneous profile reproduction.
- `current_mapping_audit.json` independently verifies cell signs against native
  pack power, source sequences, readback-based KCL mapping, fixed PSU setpoint,
  branch command limits and shutdown. Actual TORCS trial manifests match the
  source/binary files tested.

These were headless trials. Full graphical dashboard layout/HUD rendering was
not manually revalidated, and physical hardware capability/safety was not assessed.

## Historical validation before charging-positive migration

The following preserved results describe schema 1 / discharge-positive CELL
current and the previous operating policy. They are not current prototype values.

## Recorded validation: October 27, 2026

The startup fix was exercised with the existing built Windows TORCS simulator,
unchanged vehicle physics and fixed scaling, using only in-memory instruments:

- `.local/mock-startup-validation/smoke`: a 15-second headless smoke test passed
  every normal-operation gate. All 749 received samples matched native CSV,
  with zero missing/invalid packets, about 49.98 Hz reception, 136 RUNNING cycles,
  and maximum applied-target tracking error 0.004529 A. Final state DISARMED,
  both outputs disabled, isolation open and shutdown verified.
- `.local/mock-startup-validation/regen-interruption`: the new
  `--arm-on-regeneration --healthy-seconds 30` trial armed at simulation time
  193.78 s with a -0.001659 A request and only 0.000492 A PSU readback. READY kept
  isolation open and applied target zero; RUNNING began about 0.540 s later with
  balanced branches. Both positive and negative requests were tracked. Across
  223.78 simulation seconds all 11,190 received samples matched native CSV,
  with zero missing/invalid packets and about 50.00 Hz reception. Maximum
  RUNNING tracking error was 0.020095 A (below the 0.03 A acceptance bound), with
  no unexpected direction faults. Maximum difference from the instantaneous
  permitted demand was 0.111944 A during slew/neutral-transition lag; this remains
  separately reported as `demand_error_A` and is not the applied-target tracking
  error. Deliberately stopping TORCS latched
  TELEMETRY_EXPIRED about 0.502 s after interruption, disabled both mock outputs
  and opened isolation. Pre-interruption integration and fault response passed;
  uninterrupted normal-operation acceptance correctly failed.
- `target_readback_audit.json` independently matched all 423 demand-bearing
  READY/RUNNING records across those trials to their native source sequence,
  unchanged scaling, directional clamp, readback-based eLoad target, branch net
  current and isolation-dependent mock cell current. Both implementation
  manifests matched the tested source/binary files after the trials.
- Python: 143 tests executed, 142 passed and one Tk widget test skipped because
  this test environment could not find a usable `init.tcl`. Native projects
  built successfully and passed 18 EV kernel, 9 publisher and 8 HUD checks.

The actual trials were headless; graphical dashboard refresh and HUD rendering
were not revalidated here. Reset 10054 was not naturally triggered in these trials
(zero expected-reset records); expected/unexpected reset classification and other
shutdown errors were exercised through injected socket errors. Full-course
completion and physical instrument/battery safety were not assessed. No physical
backend, Positive-Only Shift, native physics change, commit or push was included.
