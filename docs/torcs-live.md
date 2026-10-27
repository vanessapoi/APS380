> Current CELL convention: negative discharge, positive charge. Native PACK
> telemetry keeps positive draw. Prototype PSU CC = 1.0 A, eLoad CC = 0 to 3.0 A,
> battery current = -2.0 to +1.0 A, configured in `prototype_current_config.py`.
> Rebuild graphics/client for APS380HUD2; APS380HUD1 is rejected. Raw telemetry
> UDP remains version 1. Historical validation reports retain their original signs.

# Real-time native TORCS telemetry

See [recorded trial results and limitations](torcs-live-validation.md) for the completed AI/manual telemetry captures and operator-confirmation boundary.

The Windows simulator optionally publishes native EV telemetry over nonblocking loopback UDP. Python validates the stream, calculates fixed-scale cell demand, supplies an in-game HUD and optional desktop display, and saves timing and CSV-comparison reports. The return link carries visual feedback only: it does not command hardware or change vehicle physics.

## Run

Close other TORCS sessions before building. From the repository root in your Windows PowerShell terminal:

```powershell
# Manual G29: start Race > Practice, then drive in the TORCS window.
.\scripts\launch_tesla_live.ps1 -Mode g29 -Duration 300

# Autonomous, paced course: approximately 7.5 minutes of wall time.
.\scripts\launch_tesla_live.ps1 -Mode ai -Duration 500

# Reuse an already-built simulator:
.\scripts\launch_tesla_live.ps1 -Mode g29 -Duration 300 -SkipBuild

# Show metrics inside TORCS without the separate desktop monitor:
.\scripts\launch_tesla_live.ps1 -Mode g29 -Duration 300 -SkipBuild -NoDesktop

# Visible AI HUD demonstration: start Race > Practice in TORCS.
.\scripts\launch_tesla_live.ps1 -Mode ai -Duration 180 -SkipBuild -VisibleAi -NoDesktop

# Automated AI test without the desktop display:
& .\aps380_torcs_starter\.venv\Scripts\python.exe scripts/run_tesla_live.py `
  --mode ai --duration 500 --skip-build --no-ui
```

The default output is a unique folder under `.local/live-trials/`. `--output-dir` selects a new explicit folder; existing folders are refused. The launcher preserves the manual G29 preferences and uses a separate AI profile. The monitor and TORCS are separate windows: focus TORCS for wheel/pedal input. Closing the monitor or pressing **Stop trial and save timing report** stops the trial's own simulator process and saves results. A duration timeout also stops it; it does not represent completion of the AI course.

Tk must be available in the interactive Python installation. Restricted/headless execution environments can use `--no-ui`; they do not test the desktop display. The receiver and disk logging run in their own thread, independently of display updates.

For an independently launched simulator, use `--mode listen --port 50001`; enable publishing and visual feedback in the simulator process with environment variable `APS380_LIVE_PORT=50001`. Both are otherwise disabled. Addresses are restricted to `127.0.0.1`. TORCS has a nonblocking ephemeral socket for visual feedback, with no vehicle-control command interface.

## In-game metrics and warnings

The HUD shows speed, pedals, native pack power/voltage/current/simulated SOC and net energy, motor power/torque/RPM, fixed-scale requested and clipped cell current, directional bounds, utilization, excess current, nominal cell basis, fixed scaling factor, stream age/rate/errors, damage and collisions. Cell voltage/current/temperature are not measured: the displayed cell basis and demand are model quantities.

Warnings compare **unclipped, fixed-scale cell demand** against the configured bound for its direction. Negative CELL demand uses the discharge bound; positive CELL demand uses the charge bound. Raw native PACK telemetry retains positive draw. Amber starts at 90% utilization. Demand above a bound produces a red banner, red screen border and faint steady red tint while preserving the road view. The banner identifies discharge or regenerative charging. A one-second minimum visual hold prevents flicker; the numeric values continue updating. These thresholds are display policy, not additional battery ratings.

Missing, invalid, ended or stale feedback replaces the current target with an unavailable indication. TORCS independently rejects old feedback (over 0.5 seconds), mismatched game sessions/cars and malformed values. Python also reports continuity and stream state. The last-known vehicle quantities are labeled accordingly. A paused simulation and lost telemetry can both cause stale feedback.

The default experiment remains fixed scale 0.06 with charging-positive cell bounds -2/+1 A. Visual alarms do not reduce acceleration or enforce physical protection. The final limited current remains a software result unless the optional in-memory mock coordinator is enabled. No physical PSU/eLoad commands are available. Bench measurements, approved limits, independent protection and vehicle power derating require later work.

The launcher builds both the graphics static library and its consuming `client.dll`, in addition to the simulator. Close TORCS before rebuilding. `-SkipBuild` is appropriate only after installing the updated binaries. Python must remain running for live scaling feedback even with `-NoDesktop`.

## Fixed experiment configuration

`aps380_torcs_starter/profiles/live_scaling_demo.json` explicitly declares simulation-only operation. It selects 3.65 V and 3.5 Ah from the EVE INR18650/35V nominal/typical datasheet values, not measured effective capacity. The fixed experiment factor is **0.06**; centralized prototype bounds are **-2 A and +1 A**, illustrative experiment settings rather than approved hardware ratings. None of these values is recalculated from live peaks. A future drive can exceed a chosen target and invoke final clipping.

Pack energy is resolved from the exact captured Tesla profile (`unvalidated.capacity_Wh`, currently 50 kWh). No 75 kWh legacy default is silently substituted. The Tesla model, capacity and efficiencies retain their existing unvalidated status. The new configuration does not change the vehicle-profile bytes or historical captures.

Pass `--config path/to/experiment.json` to select another explicit fixed configuration. Cell parameters use the existing `scale_to_cell(native_pack_power_W, cell_parameters)` path. No speed-derived power, repeated efficiency conversion or live automatic normalization is applied.

## Data and timing contract

Version-1 JSON envelopes contain session identity, sequence number, sender QPC time, publisher send-error count, event (`sample` or `ended`) and `csv`. The CSV string contains the same 21 fields and precision as the native EV recorder, including car/profile identity, motor/pack electrical quantities, simulated SOC, energy counters, movement, damage and collision information. Windows process ID, high-resolution clock ticks and car index distinguish sessions.

The simulator formats each sample once and uses it for both UDP and CSV. Sending does not depend on successful CSV creation. Publishing follows the existing approximately 20 ms simulation cadence and is nonblocking. It does not wait for Python or retry old packets. Failed sends are counted; sequence gaps remain visible. Socket setup/cleanup follows simulator initialization/shutdown. Non-Windows builds retain no-op publisher hooks.

Python checks schema, identity, finite numbers, electrical equations, energy closure, increasing timestamps, sequence ordering, sender age and session changes before exposing demand. Duplicate, late, invalid and retired-session packets are rejected. A validated simulation gap above the configured limit explicitly rebases counters, marks the boundary sample unavailable, then permits the next continuous sample; it is not interpolated. No physical actuation is possible in any state.

Waiting, receiving, invalid, gap, ended and stale states are distinct. A pause without physics updates and a lost telemetry stream both display **STALE (pause or lost stream)** and make the displayed demand unavailable. State transitions are logged, including recovery. The display never presents an old demand as a fresh target.

Host receipt time and simulation time are separate. Sender-to-receiver age is reported only after a runtime check verifies that Python `perf_counter` and Windows QPC share an origin on this machine. Otherwise latency is unavailable. The report records host inter-arrival gaps, processing time, receive rate, wall duration and simulation/wall ratio.

For headless AI, `APS380_LIVE_REALTIME=1` explicitly paces physics to wall clock; the default headless runner remains unchanged. GUI G29 trials use TORCS's existing pacing and leave this extra pacing disabled. The active G29 pacing metric excludes host intervals exceeding the stale threshold; full wall duration, raw ratio and excluded interval count remain reported, so pauses are not hidden.

## Artifacts and acceptance

- `received.jsonl`: received samples, validation failures and state transitions, with receipt/processing timing.
- `live_profile.csv` / `.png`: native pack data and requested/limited cell demand.
- `vehicle_profile.json`, `scaling_config.json`: exact configuration snapshots.
- `implementation_manifest.json`: source and simulator DLL hashes at startup.
- `timing_report.json` / `.md`: timing distributions, losses, errors, current range and fixed parameters.
- `drive.csv` / `.xml`: corresponding native capture, when exactly one new capture was created.
- `trial.json` / `trial_report.md`: CSV agreement and explicit pass/fail gates; AI protocol results or G29 telemetry observations.

Only one simulator should run during a capture audit. If more than one new CSV exists, the audit refuses to guess which one belongs to the trial. Every received CSV sample must match an original native CSV row exactly. Effective XML and profile consistency are also checked.

Current software acceptance requires at least 10 simulation seconds, no invalid packets, packet loss, stale intervals, publisher send errors or continuity breaks, 40–55 received samples/s, pacing within 5%, processing p95 below 10 ms, verified sender-age p95 below 50 ms and CSV agreement. Intentional pauses remain visible and now fail uninterrupted-trial acceptance. Historical captures used the earlier documented loss/pause gates. These are software criteria, not measured hardware requirements.

Use `--acceptance smoke` for a short integration trial. Headless AI defaults to `full-course`, which additionally requires the completed course protocol, including contiguous 10-second 30/50 km/h holds. Intentional launcher-owned duration/operator stops are recorded separately from unexpected process failures. `trial.json` separates telemetry, process, optional mock instrument control and full-course results; smoke does not mark an unfinished course complete. G29 telemetry still requires operator confirmation of physical control use. Optional mock-only control and its fault acceptance are described in [mock instrument integration](mock-instruments.md).

For a manual trial: gently accelerate, hold near 30 km/h for at least 10 seconds where practical, release the accelerator to observe regeneration, apply friction brakes, pause for 2–3 seconds and resume. End the trial with the monitor's Stop button or exit TORCS. Inspect errors and timing rather than treating an opened window as a passed test.

## Tests and limits

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B -m unittest discover -s aps380_torcs_starter -p 'test*.py'
```

Tests cover packet validation, signs/limits, fixed scaling, rejected-state immutability, session resets, stale recovery, gap rebasing, actual UDP receipt/logging, frozen native replay and desktop refresh. Desktop tests skip with a reason when Tk is unavailable. Frozen replay uses a synthetic replay clock and is explicitly not real-time timing evidence.

The standalone Windows publisher checks can be built with Visual Studio MSBuild using `scripts/tests/live_publisher_test.vcxproj` (Release/x64), then run from `.local/live-tests/live_publisher_test.exe`. They exercise the actual header used by the simulator, including delivery, escaping, disabled mode, no receiver and optional pacing.

The native HUD parser checks use `scripts/tests/hud_feedback_test.vcxproj` (Release/x64) and `.local/hud-tests/hud_feedback_test.exe`. Python feedback tests cover directional warnings, asymmetric/zero bounds, visual hold, unclipped versus clipped values, stale/reset behavior and actual UDP registration/render acknowledgements. Reports include `visual_hud_feedback` counts; acknowledgements establish that drawing code ran, not that an operator noticed the warning.

This implements simulator-to-PC monitoring and scaling, not the complete physical battery loop. PSU/eLoad drivers, measured cell acquisition, physical current tracking, validated SOC/SOP, independent protection and external TORCS power derating remain separate work. The UI labels simulated pack SOC and shows physical-cell measurements as not connected.
