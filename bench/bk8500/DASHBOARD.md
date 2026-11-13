# Original APS380 dashboard with the standalone live controller

Use a VS Code **PowerShell Terminal**, not Output/Debug Console. Close another
TORCS instance first. `--dashboard` reuses `LiveDisplay` with the standalone
controller's single receiver/worker. Do not start a second dashboard receiver.

## Home: mock only

```powershell
# Replace this example with your repository root.
Set-Location 'C:\path\to\APS380'
$low = @('--max-current-A','0.10','--reference-current-A','0.05','--max-power-W','0.6','--slew-A-per-s','0.02','--tracking-tolerance-A','0.01','--control-hz','1')
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs keyboard --duration 300 --dashboard @low
```

Select Race > Practice > New Race in TORCS. The independent smoothed-keyboard
profile is reused. For G29 replace `--torcs keyboard` with `--torcs g29`; this
reads the saved G29 profile without rewriting its configuration. Physical wheel
operation still requires operator testing.

READY means preflight succeeded; RECEIVING means telemetry is arriving. Input
stays OFF until **Arm mock** in the dashboard, or exact `ARM` then Enter at
`BK8500>` in the terminal. The worker still verifies telemetry and interlocks.
`HELP` repeats commands. `DISARM` verifies OFF/zero and reinitializes; `STOP`
latches an emergency-stop fault; `RESET` verifies shutdown and returns READY
without arming. `QUIT`, Ctrl+C or closing the dashboard shuts down the trial.
Console EOF requests STOP. These controls do not replace independent hardware OFF.

The console shows transitions immediately and, without a dashboard, a RUNNING
summary every five seconds. `--status-interval-s 10` changes this interval.
With a dashboard it prints transitions only. `--json-status` opts into JSON at
that same policy. Full cycle logs remain recorded regardless of console output.
`--no-console` with mock dashboard allows the Arm mock button; without dashboard
or `--auto-arm-mock` it is monitoring-only. Automatic arming is mock-only.

The original signed battery-demand graph remains: negative = discharge,
positive = charge. Native pack SOC is simulated. The **BK8500 branch current**
tab separately plots limited load target, applied command, setting readback and
measured load current, with its own 0-to-configured-limit axis. MOCK/REAL labels
identify the selected source. Regeneration maps to zero load target; slew
limiting means applied current does not instantly reach zero. Load current is
not battery current. PSU current, cell voltage/current/temperature/SOC are not
measured here. The original prototype mock PSU/eLoad mode remains available;
it cannot run as a second instrument controller in this dashboard.

The standalone controller's slew limit uses actual elapsed time since the ACK
of the last current-setting write, including unchanged writes (verified zero at
ARM for the first step).
Each affordable change is rounded **down** to whole 0.1 mA driver units, in both
directions. Delayed cycles cannot bank a catch-up jump larger than one nominal
step. Rates allowing less than one quantum per nominal period are rejected;
reduce the configured control frequency to make such a rate representable.
An individual short interval can still hold the preceding setting if it cannot
afford a quantum. This bounds software
setpoint changes, not physical electrical settling or current slew. Fault and
shutdown OFF/zero commands bypass ramping. If a new hard ceiling and the ramp
have no common representable setting, the controller faults and disables the
load rather than violating either operating bound. Existing measured-power and
voltage faults continue to take priority. JSONL/CSV include the previous setting,
reference ACK time, elapsed interval and unquantized slew budget for auditing.

Measurement age is shown. FAULT/disarm readings are marked RETAINED, NOT LIVE;
last verified shutdown is separate evidence. READY preflight readings are
snapshots, not continuously polled. No RUNNING cycles means NOT ASSESSED.

Default output: `.local/bk8500-live/<timestamp>/`, including `load_tracking.csv`,
`load_tracking.png`, `instruments/control.jsonl`, `instruments/summary.json`,
`telemetry/`, `trial.json`, `config.json` and `manifest.json`.

## Reproducible mock checks

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs ai --duration 20 --telemetry-port 0 --dashboard --auto-arm-mock --no-console @low
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs ai --duration 18 --telemetry-port 0 --dashboard --auto-arm-mock --no-console --inject-telemetry-loss-after 12 --expect-telemetry-fault @low
```

The second intentionally fails normal-operation acceptance; separate
`fault_response_passed` requires the expected telemetry fault and verified
OFF/zero. It terminates only its own TORCS child.

## Future supervised hardware (not authorized/run at home)

First complete every setup/protection/approval step in
[LOW_CURRENT_LIVE_LAB.md](LOW_CURRENT_LIVE_LAB.md). This command opens COM10 and
performs preflight commands; it is **not read-only identification**. It requires
a completed local approval file, interactive terminal and separate authorization.

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device hardware --torcs keyboard --port COM10 --baud 9600 --address 0 --approval .local/bk8500-live-low-approved.json --duration 180 --dashboard @low
```

Input remains OFF until the operator types `ARM <approval_reference>` with the
exact approved reference. There is no hardware Arm button. Dashboard Disarm,
STOP and Reset remain available; Reset does not arm. Hardware automation,
no-console and physical live limits above 0.10 A remain rejected. REAL readbacks
do not turn the signed battery graph/SOC into measured battery data. PSU control
and cell sensing remain absent. This GUI path is validated with mock devices
and fake hardware labels only. Proven physical recorded-profile replay remains
distinct from not-yet-verified physical live control.

## Shutdown/troubleshooting

The load is stopped/verified before terminating healthy TORCS telemetry. Check
`trial.json` / `instrument.shutdown_verified`; a retained input-ON cycle is not
the shutdown readback. If shutdown cannot be verified, use independent physical
OFF before investigating. No software control guarantees physical safety.

UDP 10054 is expected only after explicit shutdown or a confirmed zero exit of
this launcher's child. Running/abnormally exited peers, other network errors,
stale telemetry, gaps and instrument faults remain failures. Listen-only mode
cannot infer a remote peer's clean exit.

If no window opens, verify `--dashboard` and the same Python's Tk installation:

```powershell
& .\.venv-bench\Scripts\python.exe -B -c "import tkinter; r=tkinter.Tk(); r.title('Tk check'); r.after(2000,r.destroy); r.mainloop()"
```

Restricted runners can lack access to Tcl resources even when desktop Tk works.
Desktop-capable tests of both the original and new GUI must run as well as
headless tests. GUI startup/callback errors cause cleanup and FAIL; there is no
silent hardware-arming fallback. Never run two receivers on the same UDP port
or two controllers against one serial instrument.

## Validation of this presentation change (November 12, 2026)

- 61 bench tests, 165 starter tests and four keyboard/Mac setup tests passed.
  Original and new Tk widget tests passed in a desktop-capable runner, without
  skips. Restricted-runner Tk resource access remains an environment limitation.
- Existing native executables: 18 EV, 15 publisher, nine HUD and 31 keyboard
  checks passed. No native source or vehicle/control configuration was changed.
- Actual TORCS + dashboard + low-current mock: 1,010 valid samples, 20 cycles,
  all normal-operation categories PASS; maximum mock tracking error 0.066 mA.
- Scripted native keyboard fixture + dashboard: 773 samples, 14 cycles including
  four regenerative-demand cycles; target covered 0..0.10 A and normal acceptance
  passed. This fixture injects test-only key states, not OS input or G29 devices.
- Explicit ARM in an owned interactive test terminal with the dashboard open
  reached RUNNING (three cycles); verified OFF/zero on duration shutdown.
- Deliberate native telemetry interruption: 601 samples, 12 cycles, latched
  TELEMETRY_EXPIRED; normal acceptance FAIL as intended, fault-response PASS and
  verified mock OFF/zero. No instrument fault was hidden as normal shutdown.
- Original prototype mock PSU/eLoad dashboard passed a separate 12-second
  actual-native smoke check. A test-only preparation override avoided the legacy
  launcher's default profile rewrite. All 39 protected file hashes remained
  identical, including saved G29 files, keyboard rates, battery calculations,
  prototype configuration/control and the physical serial driver.
- Deterministic tests cover 10054 after clean exit before launcher polling,
  intentional shutdown, running/unknown peer and abnormal exit. Other UDP errors
  remain failures. A fresh manual TORCS-close reproduction is not claimed.

Evidence is local/ignored under `.local/bk8500-ux-validation/` (including
`audit.json`) and `.local/bk8500-ux-*-tests.log`. These are short smoke checks,
not full-course completion or physical instrument/settling/safety validation.
