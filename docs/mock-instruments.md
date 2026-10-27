# Mock PSU and electronic-load control

This is an in-memory software experiment. There are no hardware transports,
instrument commands, physical battery measurements, or physical protection claims.
The coordinator rejects devices without the mock-only marker. No PSU model is
assumed, and `MockBK8500` does not implement the BK binary serial protocol.

## Run the standalone experiment

From the repository root in PowerShell:

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B scripts/run_mock_instruments.py --arm-mock --charge-limit 0.5 --control-hz 10
```

This takes about five seconds. Synthetic pack powers pass through the existing
`scale_to_cell()` function. The requested discharge exceeds 1 A and is clipped
to **1.0 A**; neutral and charging phases follow. Charging is separately bounded
by `--charge-limit`. This is a synthetic demonstration, not a recorded TORCS drive.
The final deliberate telemetry loss must latch FAULT and verify both mock outputs
disabled and isolation open. That expected terminal fault is the success condition.

Output defaults to a unique `.local/mock-instruments/` directory. `--output-dir`
must name a new directory. Files are `demand.jsonl`, `instruments.jsonl`,
`config.json`, and `summary.json`. Instrument logs include command transactions,
setpoints, measured branch currents, mode, source sequence, saturation, feasible
range, tracking error, isolation, state, and shutdown verification. A stale
last control result may remain in a fault record for diagnosis. Such records have
`measurements_retained: true` and `measurement_context: retained_pre_fault`
(or `retained_after_disarm`). Acquisition/source timestamps and dynamically
calculated `measurement_age_at_snapshot_s` identify their age. Nested historical
instrument status can still say output enabled; use the separate verified
`isolation.outputs_disabled` shutdown result for the current mock output state.
`mock_cell_current_A` becomes zero when isolation opens. The dashboard labels
retained readbacks as not live.

## Use existing live TORCS telemetry

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B scripts/run_tesla_live.py --mode g29 --duration 300 --skip-build --mock-instruments
```

Start Race > Practice in TORCS as usual. Mock control starts **DISARMED**.
The desktop monitor adds Arm mock, Disarm, Emergency stop, and Clear fault buttons.
Clear fault returns to DISARMED; arm separately and provide a new telemetry sample.
Closing the monitor shuts down both mocks and opens isolation. Original telemetry
JSONL/CSV, scaling, motor calculations, dashboard metrics and HUD behavior remain.
Mock logs are separate, under the trial's `mock_instruments/` directory; the final
mock report is also included in `trial.json`. The HUD remains visual-only and does
not show instrument state or affect vehicle physics.

For headless use, explicit mock arming is available:

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B scripts/run_tesla_live.py --mode ai --duration 30 --acceptance smoke --skip-build --no-ui --mock-instruments --mock-arm --mock-charge-limit 0.5 --mock-control-hz 10
```

`--skip-build` requires the existing built TORCS runtime. Without it, the existing
launcher builds native components. `listen` mode can also use these flags with a
chosen port. There is no new native build requirement for mock instruments.

## Control contract

- `instrument_interfaces.py` defines current instruments, PSU/load roles,
  timestamped measurements/status, timeout errors, and isolation status.
- `mock_instruments.py` supplies adjustable response time, communication delay,
  persistent communication/timeout injection, measurement-age injection, and an
  imposed PSU CV current envelope. This is not an electrochemical/circuit model.
- `instrument_control.py` owns the state machine, directional limits, current
  mapping, tracking checks, latest-value mailbox and independent worker.

`I_cell = I_eLoad - I_PSU`, positive discharge and negative charging. The load
target is **actual PSU current readback + applied cell target**, never simply
the PSU current setting. The mock PSU bias is 0.5 A and each instrument has a
2 A capability by default. Thus -0.5 A requires full PSU bias; a deeper charging
request, or a CV transition reducing PSU current, can make it infeasible. The
coordinator logs requested, permitted and applied targets and the feasible range,
and latches INFEASIBLE_CURRENT rather than
silently pretending the target was achieved. Directional bounds first clamp the
requested net current; infeasibility within those bounds is a separate fault.
Feasibility permits only the configured neutral tolerance (0.002 A by default)
at branch-current boundaries to avoid treating an asymptotically settled mock
PSU as a materially insufficient source. Instrument setpoints remain clamped to
their capabilities, and measured tracking/direction limits remain enforced.

READY means explicitly armed, branch outputs enabled, cell isolation still open.
Its explicit BALANCING phase always commands **zero net current**, using actual
PSU readback as the eLoad target. It can balance while waiting for telemetry but
cannot connect without fresh validated demand. Live positive/negative demand
does not influence balancing and operational feasibility is not tested against
the first rising PSU sample. Both measured branch currents must stabilize within
the neutral tolerance, net current must be within that tolerance, and the CC PSU
must approach its bias (or report its stable imposed CV envelope). Fresh readbacks
and demand are checked again after I/O; the criteria must hold continuously for
`neutral_hold_s` before closing isolation and entering RUNNING at zero applied
current. The next cycle consumes the newest demand through the existing slew and
sign-transition policy. A genuinely infeasible operational demand still faults;
failed startup faults at `ready_timeout_s`. In RUNNING,
tracking mismatch has a bounded settling allowance; measured directional excess
trips immediately beyond the configured numerical/measurement tolerance. Neutral
demand balances energized branches and is not disarming. CC/CV transitions are
reported in measurements, and every cycle recomputes the load target from readback.

Only one demand is retained. A 10 Hz default worker consumes validated demand from
the approximately 50 Hz receiver without instrument I/O in that receiver. Slow
iterations are not replayed. Defaults are 0.5 s command expiry, 0.2 s measurement
expiry, 0.02 s per-operation I/O timeout, 0.6 s tracking timeout, and 30 s initial
READY waiting timeout. These are software experiment settings, not hardware
requirements. Ages are checked again after I/O; readback skew is logged. This
does not establish simultaneous physical sampling or real instrument bandwidth.

Faults latch on expired/unavailable telemetry, session changes, stale/invalid
measurements, communication failure, infeasible current, tracking error, and
emergency stop. A validated native ENDED event disarms normally; new telemetry
cannot automatically rearm it. Telemetry invalidation during I/O prevents connection.
The mock local isolation trip disables both branches even when transport commands
fail; failed output-disable transactions remain in the log. Recovery verifies
fresh communicating disabled instruments and open isolation, returns to DISARMED,
and rejects pre-recovery demand. Disarming alone cannot clear a fault.

The displayed net cell current is mock truth derived from the two branch models
and isolation state, **not independent ESP32 sensing**. Physical implementation
still needs actual drivers, calibrated net-current acquisition, timestamp/skew
validation, reviewed startup/transition sequencing, approved cell limits, ESP32
supervision, and independent hardware isolation/protection. Do not enable physical
operation by changing the mock marker.

## Tests

```powershell
$env:MPLCONFIGDIR = Join-Path (Get-Location) '.local/matplotlib'
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B -m unittest discover -s aps380_torcs_starter -p 'test*.py'
```

`test_instrument_control.py` uses deterministic clocks for directional demand,
clipping, sign changes, CC/CV, response delay, expiry during I/O, stale measurements,
tracking faults, communication failures, emergency stop and explicit recovery.
Actual loopback UDP verifies the receiver-to-worker integration and unchanged cell
scaling; worker tests verify command expiry and logged shutdown. No tests connect
to instruments.

## Reversal policy and acceptance

The permitted demand remains the existing limited current input, with the
coordinator's directional bounds applied. The **applied target** slews at at most
0.2 A/s by default. A reversal first slews to zero, then requires measured net
current within +/-0.002 A continuously for 0.1 s before issuing the newest demand
in the opposite direction. A command received during this interval replaces the
previous demand; it cannot reset the transition deadline or queue a reversal.
The transition timeout is 6 s. TRACK, TO_ZERO and HOLD_ZERO are explicit logged
phases within RUNNING; READY uses BALANCING. Zero demand uses the same neutral qualification.

These rates, tolerances and dwell times are **mock policy settings**, not
physical-instrument specifications or cell safety limits. The controller faults
on unexpected current direction outside its 0.002 A band, persistent tracking
error, or failure to establish neutral. Communication/expiry faults remain active
during every transition. Before closing isolation at startup it also requires
stable readback and tracking; a small initial applied target cannot bypass this.

`tracking_error_A` compares measured net current with the applied target.
`demand_error_A` compares it with the latest permitted demand, so deliberate ramp
or neutral-hold lag is visible rather than hidden as perfect tracking. The strict
normal-trial acceptance gate requires all RUNNING tracking samples within 0.03 A,
even though the controller allows up to 0.6 s to trip on persistent mismatch.

`--acceptance smoke` checks process health, uninterrupted telemetry, numerical and
timing checks, CSV agreement, mock communication, tracking, direction, freshness
and final shutdown. It does not require full-course completion. Headless AI still
defaults to `full-course` unless smoke is explicitly selected. A launcher-owned
duration/operator stop is recorded as intentional; an independently observed
nonzero process exit is a failure. Packet loss and stale intervals fail acceptance.

`trial.json` separates `acceptance.telemetry`, `.process`, `.instruments` and
`.full_course`. Full-course completion is unassessed when a smoke test is stopped
early. Instrument results retain faults and failed communications even after
recovery; final disabled outputs/open isolation cannot erase a prior fault. The
summary includes command/measurement ages, tracking and demand error distributions,
state, worker error, faults, saturation and transition cycles, and shutdown checks.
Each section/check has an explicit PASS, FAIL or NOT ASSESSED status. JSON `checks`
retain booleans for assessed checks and use `null` for unassessed checks. Tracking
and direction cannot pass without RUNNING samples. With requested arming, missing
RUNNING evidence fails overall acceptance; an intentionally disarmed trial may
pass its shutdown checks while `control_status` remains NOT ASSESSED. Retained
readback snapshots do not count as fresh measurement evidence. Detected faults
still fail the relevant check even if no RUNNING samples were recorded.

Deliberate telemetry interruption can be verified independently:

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B scripts/validate_mock_interruption.py --healthy-seconds 12
```

This starts its own headless TORCS process, verifies RUNNING, stops that process,
and keeps reception/control alive until expiry. Normal-operation acceptance must
be false. The script succeeds only if the separate `fault_response` checks prove
a latched expiry fault, disabled outputs and open isolation. It requires the
existing native runtime and never accesses physical instruments.

To reproduce startup while regenerative demand is already present, then exercise
both directions before the deliberate interruption:

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B scripts/validate_mock_interruption.py --arm-on-regeneration --healthy-seconds 30
```

This stays DISARMED until native negative current is received (up to 240 seconds
on the existing AI course), explicitly arms, then drives another 30 seconds.
`arm_source`, `pre_interruption_integration` and `fault_response` in `trial.json`
separate startup/directional tracking from the deliberately failed normal-stream
acceptance after interruption. If regeneration or both tracked directions are
not observed, this validation does not pass.

For deliberate saturation, copy `profiles/live_scaling_demo.json` to a local
experiment configuration and lower its charge/discharge bounds, for example to
0.02 A. Pass it with `--config`; keep `experiment_scale` at 0.06. These reduced
bounds are test stimuli, not changes to approved hardware ratings. Allow about
210 s on the established course to observe native regenerative pack power.

## Windows UDP shutdown

The launcher marks expected shutdown and stops HUD sends before closing mocks
and terminating its native peer. Only Windows UDP reset 10054 after this explicit
boundary is recorded as `expected_shutdown_reset`; it is counted in the timing
report. The same reset during operation, and other errors during shutdown, remain
logged `receiver_error` failures, invalidate demand and retain RECEIVER_ERROR as
the final receiver state. A deliberate telemetry-loss test leaves the receiver
active until expiry; it does not mark the interruption as an orderly stop.

Windows can report an earlier UDP send's ICMP Port Unreachable response through
`recvfrom` as WSAECONNRESET; see the
[Microsoft recvfrom reference](https://learn.microsoft.com/en-us/windows/win32/api/winsock/nf-winsock-recvfrom).
The reset regression tests inject this OS error explicitly. Headless native trials
do not exercise graphical HUD drawing or prove that every GUI shutdown race has
occurred.

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
