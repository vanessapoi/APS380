# Recorded real-time validation

The native Windows simulator publisher and Python fixed-scale pipeline were exercised with the autonomous course and a manual-profile G29 session. Both captures passed their software gates. Physical cell operation and real Tesla calibration were not tested.

Artifacts are local and are not included in source control:

- `.local/live-trials/ai_realtime_01/`
- `.local/live-trials/g29_realtime_01/`

Each contains `trial.json`, `trial_report.md`, `timing_report.json`, `timing_report.md`, received JSONL, derived CSV/plot and frozen vehicle/scaling configurations. Native CSV/XML snapshots verify correspondence. The G29 folder additionally contains the startup implementation manifest and operator-confirmation record.

| Metric | Paced autonomous course | Manual-profile G29 capture |
|---|---:|---:|
| Simulation duration | 442.08 s | 135.96 s |
| Receive wall duration | 442.010 s | 139.096 s |
| Received samples | 22,105 | 6,799 |
| Matching native CSV samples | 22,105 | 6,799 |
| Sequence loss / invalid packets | 0 / 0 | 0 / 0 |
| Average receive rate | 50.008 Hz | 48.873 Hz including pause |
| Simulation/wall ratio | 1.000158 | 0.977456 including pause |
| Active simulation/wall ratio | Not separately reported | 1.000022 |
| Sender-to-receiver p95 | 0.203 ms | 1.975 ms |
| Sender-to-receiver maximum | 0.840 ms | 68.556 ms |
| Receiver processing p95 | 0.222 ms | 0.552 ms |
| Cell-current demand range | -0.128723 to +0.139673 A | -0.212940 to +0.923434 A |
| Final current clipping | 0 samples | 0 samples |

Both runs used fixed experiment scale 0.06, nominal cell basis 3.65 V / 3.5 Ah, 50 kWh captured pack capacity, and illustrative -1/+1 A final bounds. The native vehicle profile SHA-256 was `267ef7c913e575545959e4b99cac44473e0c3d6cbef531cd098822f70a8b452f`. The simulator DLL SHA-256 was `dd9982208d15e28f509cd3b410bb5ef15dcf157550824036d027f1f7fcf09c73`.

## Autonomous course

The independent protocol audit passed 13.96 s of qualifying 30 km/h hold, 12.00 s at 50 km/h, 6 s stopped, regeneration without friction brake, isolated friction braking and course completion. It found no post-startup contacts, damage or speed jumps. Net simulated pack energy was 558.040480 Wh. The native trace covers the established two-lap race; the protocol audit independently verifies at least one complete track distance.

This capture was started before startup source-manifest and state-transition logging were added. Its frozen profile/configuration, raw transport data, matching native CSV and simulator DLL identity remain available. Later additions are exercised by the manual capture and tests; do not infer a startup Python source hash for this first run.

## Manual trial boundary

The logged transitions were WAITING, RECEIVING, STALE, RECEIVING, STALE and ENDED. The largest host inter-arrival interval was 3.159 s. Exactly one stale interval between accepted samples is excluded from the active pacing ratio; full wall time and raw timing remain visible. No packets were missing during the pause. The terminal stale-to-ended transition occurred after sample transmission ceased.

Telemetry recorded throttle up to 1.0, brake up to 0.562509, motion and regenerative pack power. However, when asked to confirm the physical controls and visual pause/resume behavior, the operator replied **“we don't know.”** Therefore physical steering/pedal operation and subjective display usability remain **unconfirmed**. The monitor was closed after the native session had ended to save the report; the launcher then stopped its own remaining TORCS menu process. That intentional process termination is recorded separately from software gate results.

Minor start instructions, current-sign labels and the rate readout were clarified after this capture and verified by the desktop test. This does not constitute another operator-confirmed G29 test.

## Verification scope

- Release/x64 simulator built and installed. One pre-existing code-page warning in `transmission.h` remained; build succeeded.
- 87 Python tests passed, including desktop refresh, frozen native replay, real loopback UDP, invalid packets, stale recovery, restart, continuity and unchanged legacy workflows.
- Nine standalone C++ publisher checks passed: disabled/invalid-port behavior, loopback delivery, JSON quoting, sequence/end messages, missing-receiver behavior and wall-clock pacing.

Timing is measured on this machine under these workloads, not a guaranteed worst-case latency or an instrument settling specification. The 68.556 ms manual-trial age outlier remains in the report despite the passing p95 gate. Hardware current tracking, sensor accuracy, physical SOC/SOP and battery-dependent TORCS power feedback remain unimplemented.

## In-game HUD and visual feedback

The subsequent visible AI trial is saved under `.local/hud-validation/visible_ai_01/`. It exercised the installed graphics/client implementation over 94.22 simulation seconds, receiving 4,712 samples. All 4,712 matched the native CSV, with zero invalid or missing packets. All software gates passed, including the additional in-game rendering acknowledgement gate. The receive rate was approximately 48.25 Hz including a pause; simulation/wall ratio was 0.9650, and active ratio 1.000004.

TORCS acknowledged 476 HUD draws: 334 normal, 33 near-limit, 100 discharge alerts and 9 unavailable states. Renderer acknowledgements prove the drawing path executed; operator notice and usability still require a manual trial. Regenerative charge alerts were covered by unit tests, not observed in this visible AI run. A normal HUD screenshot is saved at `.local/hud-validation/menu2.png`.

This trial deliberately used a local **0.02 A** charge/discharge bound to provoke warnings. It did not change the default experiment's -1/+1 A bounds or establish a battery rating. Fixed scale remained 0.06. The trial was stopped after the visualization interval; full autonomous course completion was not assessed. Additional red-screenshot attempts (`visible_ai_red_02` and `visible_ai_red_03`) remained at menus without telemetry; they are not passing driving trials or additional validation evidence. No red screenshot was obtained.

After the HUD changes, **93 Python tests passed**, including the desktop refresh test and six driver-feedback tests. **Eight native HUD parser checks** and **nine native publisher checks passed**. Release/x64 graphics and client builds succeeded and the updated runtime `client.dll` was installed. Tests cover charge/discharge direction, separate bounds, zero bounds, numerical boundaries, held warnings, stale/reset handling, actual UDP exchange and malformed native feedback. The visual return channel has no vehicle actuation or hardware command interface.
