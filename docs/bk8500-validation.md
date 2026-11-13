# BK8500 live control and input-device review

This summary records the November 13, 2026 software and physical-session review.
Raw experimental recordings, completed approvals, device identifiers and generated
plots remain local. Aggregate results below are physical instrument readbacks,
not mock predictions or independently calibrated electrical measurements.

## Completed implementation

- Existing binary driver and portable 0.10 A replay remain unchanged.
- Separate OFF-only preflight can verify OFF/zero/CC/protections with no ARM path.
  `--inspect-only` instead queries identity, OFF-state measurements and actual
  protection settings without writes or an exact-MAX acceptance requirement.
- Live extended PSU-only mode is opt-in and capped at 1 A. Default physical
  ceiling remains 0.10 A; no physical automation or GUI ARM is introduced.
- Existing MAX settings are read, never changed. Extended mode checks software
  envelope <= observed MAX <= recorded approved protection ceiling, both at
  initialization and before supervised terminal ARM.
- Freshness, elapsed-ACK quantized slew, setpoint verification, tracking fault
  policy and verified/unverified shutdown reporting remain active.
- Keyboard presets: 3 s, 5 s (default), 8 s rise. All retain 1.5 s release,
  1 s brake rise and 0.5 s brake release; analog G29 input bypasses them.
- Dashboard and CSV distinguish original signed demand, original 0..3 A branch
  demand, scaled target, applied command, returned setting and measured current.

## Two physical manual sessions

Both were PSU-to-load experiments with no battery: 1 A software ceiling, 5.5 W
software power ceiling, 1 Hz and unchanged 0.02 A/s slew. A ceiling is not proof
that the full operating range was exercised.

| Metric | Earlier 3 s keyboard session | Later 8 s keyboard session |
|---|---:|---:|
| Complete RUNNING cycles | 144 | 140 |
| Measured minus commanded MAE | 0.850 mA | 0.784 mA |
| RMSE | 1.291 mA | 1.050 mA |
| Maximum absolute error | 6.8 mA | 4.4 mA |
| Measured minus unslewed target MAE | 70.3 mA | 85.8 mA |
| Peak command | 0.3229 A | 0.4561 A |
| Peak measured current | 0.322 A | 0.455 A |
| Average measured current | 0.08468 A | 0.13764 A |
| Scaled target maximum | 0.4617 A | 0.4617 A |
| Packets received | 9,157 | 8,910 |
| Missing / invalid / reordered | 0 / 0 / 0 | 0 / 0 / 0 |
| Instrument faults | None | None |
| Verified OFF / zero shutdown | Yes | Yes |
| Overall normal-operation acceptance | FAIL: pre-ARM pause | PASS |

All setting readbacks matched their commands. The earlier session contained a
1.325 s sender/receiver pause before ARM; it resolved before physical control.
The later session had no stale intervals. One partial cycle during later operator
shutdown is not a completed measurement and is excluded from tracking metrics.
The separate shutdown record, not retained pre-stop current, verifies input OFF.

The 0.02 A/s ramp remains the major demand-following constraint: it was binding
in 62.5% and 66.4% of the respective cycles, with no logged slew-budget violations.
Neither session demonstrates physical 1 A tracking. Fixed reference scaling
produced a maximum target near 0.462 A; the load was not failing to reach 1 A.

## Keyboard versus G29

The manual inputs differed. Higher speed and mean current in the later session
cannot be attributed solely to the 8 s setting; holding any preset eventually
requests full throttle. Existing identical-key native fixture comparisons are
controlled software evidence, not physical matched-input A/B results.

G29 proportional joystick-axis mapping, saved calibration and analog bypass are
implemented. Fake-axis opt-in/opt-out traces matched; saved G29 files were
preserved. The reviewed physical eLoad sessions used keyboards, not the wheel.
Physical released/full-scale endpoints, low-input stability, independent pedals,
steering and agreement with applied telemetry remain final-device checks.
Raw physical axes are not currently logged, only final applied throttle/brake.

Prioritize G29 validation with existing mappings, then electrical slew evaluation
using the final device. Keep keyboard presets as fallbacks. Faster slew values
are mock counterfactuals only; no approval or threshold is silently expanded.

## SOC/SOP boundaries

TORCS simulated pack SOC exists in these captures. Physical cell SOC, OCV and SOP
do not: there was no battery. The existing prototype mock Cell SOC -> Rint SOP ->
native propulsion feedback is already implemented separately; reuse its modules
when composing future sensing/instrument integration. Do not integrate eLoad
branch current as physical net battery current or rebuild the estimators.

## Reproduce offline analysis

Install `bench/bk8500/live-requirements.txt`. Choose actual local session paths;
the tool never imports serial or opens an instrument transport. Its optional
slew comparison reuses only pure control helpers and an in-memory device.

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/analyze_session.py `
  --run-dir .local/bk8500-live/SESSION `
  --compare .local/bk8500-live/PREVIOUS_SESSION `
  --output .local/analysis/SESSION `
  --slew-rates 0.02 0.05 0.10 0.20
```

Outputs: Markdown report, current/driving/SOC figures, metrics and input hashes.
Config approval contents and local absolute paths are not copied into reports.
Completed RUNNING samples are joined to source telemetry by session/sequence;
partial/stopped records and conflicting mock/hardware provenance are rejected.
Whole-session acceptance is retained even if actuator tracking is good.
Default mock response is an unvalidated 40 ms assumption; `--mock-response-s`
supports explicit sensitivity studies. Faster mock results do not establish
physical bandwidth, safety or a hardware settling time.

See [keyboard instructions](keyboard-driving.md),
[extended live commissioning](../bench/bk8500/ONE_AMP_LIVE_LAB.md) and
[existing live mock SOC/SOP integration](live-cell-state.md).

## Final software review

The pre-publication regression rerun passed 97 bench tests (one Tk-dependent
skip), 187 starter tests (five existing environment-dependent skips), three
keyboard-profile tests, two portable-setup tests, and 131 native assertions.
Six actual TORCS headless fixture trials passed (4,222 valid samples total),
including the original prototype mock coordinator, standalone mock controller,
press/release and alternate ramp checks, and 673 matching analog-bypass samples.
Saved G29/default profiles were byte-preserved. The additional 8 s preset had
already passed a native 714-sample / 14-cycle 0.02 A/s standalone mock capture.
The portable offline analyzer reproduced both physical MAEs in the table from
local files without serial access. Desktop Tk rendering remains skipped here;
none of these software results extends physical safety or calibration evidence.
