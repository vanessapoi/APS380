# Mock control integration validation

Recorded October 27, 2026. This validates in-memory software behavior only; no
PSU, electronic load, ESP32 or battery was connected. Native TORCS binaries were
reused without changing the EV kernel, publisher, HUD or vehicle profile.

## Evidence and reproduction

The final captures are local, ignored artifacts under `.local/mock-e2e-v2/`:

- `review_normal_ai_01`: default fixed scaling and bounds, armed smoke trial.
- `review_saturation_regen_ai_01`: fixed scale 0.06, local +/-0.02 A native cell
  demand bounds, armed mock coordinator (+1/-0.5 A bounds), 210-second smoke trial.
- `review_interruption_ai_01`: 12 healthy wall seconds, followed by stopping only
  the trial's TORCS process while keeping the receiver/coordinator alive.
- `automated_tests.log`: full Python regression output.

Normal/saturation trials contain `trial.json`, source/binary hashes, exact profile
and scaling configuration, received JSONL, native CSV/XML, derived CSV/plots, and
separate mock transaction/control logs. The interruption trial records both
failed normal-operation acceptance and the independent fault-response verdict.
See [launch instructions and policy](mock-instruments.md).

All normal acceptance results require process health, continuous valid telemetry,
timing, native CSV correspondence, mock communication/tracking/direction/freshness,
and verified disabled outputs/open isolation. A short smoke does not require full
course completion. A successful fault response cannot make normal acceptance pass.

## Final TORCS results

| Trial | Simulation duration | Received/native-matching samples | Result |
|---|---:|---:|---|
| Final normal smoke | 14.98 s | 750 / 750 | Telemetry and instruments passed |
| Final saturation/regeneration | 209.98 s | 10,500 / 10,500 | Telemetry and instruments passed |
| Deliberate interruption | 11.92 s before loss | 597 / 597 | Normal acceptance failed; fault response passed |

Both uninterrupted trials had zero missing/invalid packets and passed timing,
freshness, process-health and shutdown checks. The longer trial received
49.998 samples/s, with 706 negative native pack-power samples. It clipped 2,636
samples (2,063 discharge and 573 charge), retaining the original fixed scale.
The raw current range was -0.081556 to +0.139451 A; limited current was +/-0.02 A.
Every coordinator request matched the source telemetry's limited current exactly.
The applied load-target equation agreed within floating-point precision.

There were 1,949 RUNNING control cycles, including 3 TO_ZERO and 3 HOLD_ZERO
cycles. Net current was below -0.002 A in 127 cycles. Maximum applied-target
tracking error was 0.019997 A, with p95 0.000437 A. Maximum difference from the
newest permitted demand was separately reported as 0.039996 A. One cycle retained
the outgoing direction during the explicit zero ramp; there were no unexpected
directions outside the configured band relative to the applied transition policy.
These figures are not directly comparable with the earlier 112 mA maximum at
different current bounds, and do not establish physical tracking performance.

The final interruption latched STALE_TELEMETRY approximately 0.543 s after the
native process was stopped. Both mock outputs were disabled and isolation opened.
Normal acceptance remained false (stale command stream/process interruption),
while the independent fault-response checks all passed. Last active instrument
measurements remained fresh; telemetry expiry was not mislabeled as stale readback.

All recorded implementation hashes in these final three trials match the final
review source. `.local/mock-e2e-v2/review_results.json` contains the independent
cross-checks. Earlier pilot trials remain available but are not substituted for
these final captures. Nothing was committed or pushed.

## Automated checks

- 135 Python tests ran: 134 passed and one existing desktop test skipped.
- 18 native EV-kernel, 9 publisher and 8 HUD parser checks passed.
- Reversal tests use delayed mock response, measured neutral dwell, latest-demand
  replacement, both current directions and the full +1/-0.5 A configured bounds.
- Tests cover communication failure during reversal, persistent mismatch, stuck
  neutral, unexpected direction, stale commands/readback, recovery, startup
  readback stability, orderly native session end, and acceptance failures.

The skipped Tk test fails at Tcl initialization in this execution environment.
Explicit library paths did not resolve it in the prior review. GUI arm/disarm,
emergency-stop and recovery controls still need a normal desktop verification.

## Interpretation and remaining limits

Tracking error is measured against the slew-limited applied target. The separate
demand error retains the full difference from the newest permitted request.
TO_ZERO deliberately allows the outgoing direction while ramping toward neutral;
it does not issue the opposite direction before the measured zero dwell. The
2 mA direction/neutral bands, 0.2 A/s slew, 0.1 s dwell and timeouts are mock policy,
not measured equipment specifications or approved physical battery protections.

Headless trials do not draw the HUD. HUD protocol/parser regressions passed; a new
visible HUD trial and operator usability confirmation were not performed. Exact
zero demand is covered by automated tests; the native vehicle has auxiliary power.
Full-course completion was not rerun. No physical transient behavior, independent
net-current sensing, current accuracy or protection effectiveness is established.

The pending integration includes interfaces/mocks/control, acceptance helpers,
live receiver/dashboard/launcher integration, standalone and interruption runners,
tests, README/project-context updates and these guides. No generated captures or
binaries should be committed with the source review.

## Pending source inventory

- `aps380_torcs_starter/instrument_interfaces.py`, `mock_instruments.py`,
  `instrument_control.py`: contracts, in-memory devices and control worker.
- `aps380_torcs_starter/trial_acceptance.py`: independent acceptance sections.
- `aps380_torcs_starter/test_instrument_control.py`, `test_trial_acceptance.py`:
  coordination, reversal, fault and reporting regressions.
- `aps380_torcs_starter/torcs_live.py`, `live_display.py`: optional mailbox and
  mock operator controls from the initial integration.
- `scripts/run_tesla_live.py`, `run_mock_instruments.py`,
  `validate_mock_interruption.py`: live, standalone and fault-injection runners.
- `README.md`, `aps380_torcs_starter/PROJECT_CONTEXT.md`,
  `docs/torcs-live.md`, `docs/mock-instruments.md` and this validation record.
