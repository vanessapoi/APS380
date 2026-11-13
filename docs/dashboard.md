# APS380 Tk dashboard

The existing `LiveDisplay` is reused by every launcher. This is a presentation
change only: no model equations, observers, telemetry, controllers, instrument
drivers, limits, arming rules, isolation or fault logic are changed.

## Layout

| Tab | Available data and plots |
|---|---|
| Vehicle | Native simulated speed, actual motor output, signed pack power, simulated pack SOC, acknowledged propulsion fraction; motor/pack power plot |
| Battery | Separate estimated Cell SOC, net cell current, cell V/T and source/age labels; original signed requested/limited/applied/mock-measured current graph |
| SOC & SOP | Cell SOC, candidate OCV, estimated discharge SOP/current; four plots for Cell SOC, mock net current, SOP and requested/native-applied propulsion availability |
| Instruments | Existing targets, applied commands, setting readbacks, branch currents, voltage, power, input state and timestamps as each workflow supplies them |
| Safety & Logs | Telemetry quality, controller/fault state, isolation, last shutdown verification, recording state, existing controls and scrollable detailed diagnostics |
| BK8500 current | Present only for the standalone BK controller; preserves its existing target/applied/setting/measured current plot, explicitly labeled MOCK or REAL and not battery current |

The top status strip remains visible on all tabs. The plot window control on
SOC & SOP selects 30/60/90 seconds of available history; no samples are fabricated
outside the receiver's bounded buffer. New plots use host elapsed timestamps
and auto-scaled Y axes, so small SOC/SOP changes can be visible. The original
battery graph retains its simulation-time axis and configured directional bounds.

Only the selected tab's plots redraw. Extrema-preserving decimation bounds Tk
line sizes without changing logged data; gaps, invalid model states and observer
resets break traces. The display normally refreshes at 10 Hz while the separate
receiver continues logging approximately 50 Hz telemetry. Closed/stale streams
retain historical plots and explicitly mark retained values; they do not become
new measurements. Displayed ages continue increasing while cached data is held.

## Source boundaries

- **TORCS:** native pack SOC/V/I, motor/pack power and speed are SIMULATED.
  Native pack current/power is positive for draw. Pack SOC is never shown as
  Cell SOC. Propulsion availability is shown only when native acknowledgements
  are actually supplied; absent feedback is NOT CONNECTED, not an invented 100%.
- **Prototype mock coordinator:** branch readbacks and known mock isolation
  provide modeled net current, positive for charging (`PSU - eLoad`). Cell SOC,
  cell voltage and temperature are not inferred from demand or branch voltage.
  The coordinator has no separate PSU-command log field; the dashboard says
  NOT AVAILABLE rather than duplicating its setting as an independent command.
- **Fixed-SOC Rint:** Cell SOC and temperature are held MOCK inputs, candidate
  OCV is a model output, R0 remains ASSUMED and SOP remains ESTIMATED. Candidate
  OCV is never relabeled measured cell voltage.
- **Live mock SOC/Rint:** Cell SOC is ESTIMATED / MOCK counted; cached immutable
  measurement records identify imposed MOCK voltage/temperature, mock measured
  net current, sequence and age. UI refresh never calls `observer.snapshot()`
  (which can latch a fault), integrates current or reads a device.
- **Standalone BK8500:** readbacks are MOCK or REAL according to the existing
  controller. These are load-branch V/I/P and input/setting readbacks, not cell
  current or measured cell SOC. The manually operated PSU is NOT CONNECTED /
  unmeasured. READY preflight values are snapshots, not continuously polled data.
- **Missing sensors:** physical cell V/I/T/SOC, ESP32 sensing and physical
  isolation/protection are NOT CONNECTED unless actually reported by a future
  integration. No physical measurement transport is added by this dashboard.

The UI only reads existing cached snapshots and fields. Quality labels are
presentation, never new protection thresholds. Existing controller state and
faults remain authoritative; future/old cached data is visibly unavailable or
retained rather than silently shown as live zero.

## Existing controls are preserved

Mock modes retain Arm mock, Disarm, Emergency stop and fault recovery. The
propulsion demo retains its existing reset/zero controls. REAL BK8500 mode
retains only the existing Disarm, Emergency stop and Reset fault controls;
**there is no physical ARM button**. Hardware arming still requires the exact
existing authorization in the supervised terminal. Reset does not arm the load.
No physical driver or safety implementation is changed or operated here.

## Launch using existing workflows

Run PowerShell from the repository root after the existing native build. Keep
physical instruments disconnected for these mock commands.

```powershell
# Original keyboard dashboard with prototype mock PSU/eLoad (explicit mock arm).
& .\scripts\launch_tesla_keyboard.ps1 -SkipBuild -MockInstruments -MockArm

# Fixed-SOC Rint (no physical devices).
& .\.venv-bench\Scripts\python.exe -B scripts/run_vehicle_power_limit.py --policy rint --sop-config aps380_torcs_starter/profiles/rint_sop_mock_example.json --mode keyboard --duration 300 --skip-build

# Live mock measured current -> Cell SOC -> Rint -> TORCS.
& .\.venv-bench\Scripts\python.exe -B scripts/run_vehicle_power_limit.py --policy rint-live-mock --sop-config aps380_torcs_starter/profiles/rint_sop_live_mock_example.json --mode keyboard --duration 300 --skip-build

# Standalone low-current BK8500 MOCK; input remains OFF until explicit mock ARM.
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs keyboard --dashboard --duration 300 --max-current-A 0.10 --reference-current-A 0.05 --max-power-W 0.6 --slew-A-per-s 0.02 --tracking-tolerance-A 0.01 --control-hz 1
```

For existing G29 driving, use the existing launcher's G29 option (`--mode g29`
for power-policy launchers, `--torcs g29` for standalone BK). The dashboard does
not write input profiles or calibrations. Do not run two simulators together.

The original Stop trial and save button still delegates shutdown/reporting to
its launcher. JSONL recording state and log path are visible under Safety &
Logs; CSVs, plots and final reports are generated by the existing workflow on
stop. No new recording format or separate application is introduced.

## Automated validation and screenshots

```powershell
& .\.venv-bench\Scripts\python.exe -B -m unittest discover -s aps380_torcs_starter -p test_dashboard.py -v
& .\.venv-bench\Scripts\python.exe -B scripts/validate_dashboard.py --screenshots --output .local/dashboard-review/new-run
```

Use a new output folder, actual Windows Tk access and the existing TORCS build.
The validation runs original prototype, standalone BK mock, fixed Rint, live
Rint and SOC-demo workflows sequentially, then deliberately interrupts telemetry
in a standalone BK mock run. The latter must fail normal-operation acceptance
and pass fault-response/shutdown checks separately. It checks approximately 50 Hz
telemetry, logs/report/shutdown compatibility, evolving displayed SOC, draw
timing and protected source/profile fingerprints. Screenshot capture is optional
and uses Windows/Pillow window-buffer capture (Pillow 13 in this validation),
not desktop rectangles: DPI scaling and other apps covering the dashboard do
not crop or contaminate the image. Omit `--screenshots` if the installed Pillow
does not support window capture. Images and observations stay under
ignored `.local/`. No physical instrument or wheel is accessed.

Unit tests also cover missing/stale/retained data, measured-vs-requested current,
OCV-vs-measured-voltage separation, retained REAL-label stop/reset controls using
fake monitors only, spike preservation, plot gaps/resets, inactive-tab redraw
isolation and 5000-row history. Passing UI tests is not physical lab validation.
