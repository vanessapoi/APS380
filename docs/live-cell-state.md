# Live mock Cell SOC and Rint SOP

This opt-in software loop reuses the prototype mock PSU/eLoad coordinator,
`CellMeasurement`, `CoulombCounter`, `RintPolicy` and native propulsion feedback.
There is no physical instrument option or serial import. The default SOC
demonstration and fixed-SOC Rint workflows remain separate and unchanged.

## Data flow

```text
TORCS UDP → signed cell scaling → prototype mock coordinator
  → fresh branch readbacks + known mock isolation → CellSample
  → existing CoulombCounter → evolving Cell SOC → existing RintPolicy
  → existing scaling inversion → APS380POWER1 → native propulsion
```

The unchanged coordinator worker publishes once per new readback pair. A locked
observer snapshot is consumed at telemetry rate; no command/sample queue or
repeated integration at that faster rate is introduced. The optional sink
performs no device I/O. An observer fault requests the existing mock emergency
stop once per observer generation and stops propulsion feedback; native expiry
and explicit recovery are preserved.

`CellSample` wraps the existing immutable `CellMeasurement` with stream session,
sequence, receipt time, source, quality, isolation state and V/T provenance.
All times are host perf_counter seconds. SOC uses measurement elapsed time,
not simulation time. The adapter timestamps at the later branch acquisition
and bounds their skew. Sequential branch readbacks are not an independently
synchronized physical cell-current measurement.

Current is charging-positive: **I_cell = PSU readback − eLoad readback**.
Requested, limited and applied commands are never SOC measurements. Open mock
isolation means modeled cell-path current is zero even while startup branches
balance. The counter retains its linear intersample-current and unity charging
efficiency assumptions; exact intersample isolation switching is not recovered.

Voltage and temperature are imposed synthetic values, labeled
`imposed_mock_voltage` and `imposed_mock_temperature`. Initial SOC is an explicit
mock assertion, not rested-OCV initialization. Capacity, R0 and model margins
remain unvalidated assumptions. This is not a circuit/thermal model or physical
protection system.

## Quality, startup and reset

The example uses age ≤0.2 s, readback skew ≤0.05 s and integration gaps ≤0.5 s.
These are mock acquisition choices, not measured hardware timing. Missing,
duplicate or reordered sequences, changed sessions, reversed/nonincreasing
times, future/stale values, retained/faulted branch readbacks and isolation
contradictions latch unavailability. Cached readbacks never refresh freshness.
SOC clipping is recorded and latches unavailability because the absolute charge
reference is compromised. Unknown intervals are never filled or bridged.

Before fresh data, zero propulsion is commanded while WAITING; no valid model
or successful SOC tracking is claimed. The coordinator starts DISARMED. Use
the existing **Arm mock** dashboard button or terminal `ARM` to establish the
unchanged balanced-isolated startup. A run without valid updates cannot pass.

For explicit recovery:

1. `DISARM`; inspect the cause and verified mock shutdown.
2. `RECOVER` invokes existing coordinator fault-recovery interlocks; it does not
   arm or clear Cell SOC state. Wait for fresh telemetry after recovery before
   arming; a demand timestamp older than recovery deliberately faults with
   `NEW_DEMAND_REQUIRED_AFTER_DISARM_OR_RECOVERY`. Automated tests must observe
   this condition rather than bypass the interlock.
3. `RESET CELL` explicitly reasserts the configured mock initial SOC, discards
   the unknown interval and waits for a new post-reset measurement. Generation
   increments; no lost charge is reconstructed.
4. `ARM` establishes new mock readbacks. Once cell state is VALID, `RESET`
   explicitly recovers propulsion. Fresh data alone does not recover a fault.

`ESTOP` invokes the existing mock emergency stop. Reasserting mock initial SOC
is not a valid physical recovery procedure; future measured-state operation
requires an independently justified initialization.

## Launch from repository root

After the existing native build, keyboard driving with the original dashboard:

```powershell
& .\.venv-bench\Scripts\python.exe -B scripts/run_vehicle_power_limit.py --policy rint-live-mock --sop-config aps380_torcs_starter/profiles/rint_sop_live_mock_example.json --mode keyboard --duration 300 --skip-build
```

Start Practice and explicitly arm the mock coordinator. Use `--mode g29` for
the existing saved G29 profile. Controls, smoothing, instrument slew limits and
physical BK8500 driver are unchanged. Omit `--skip-build` if native rebuilding
is needed; close other TORCS instances first.

Automated AI validation without hardware, with explicit mock-only arming:

```powershell
& .\.venv-bench\Scripts\python.exe -B scripts/run_vehicle_power_limit.py --policy rint-live-mock --sop-config aps380_torcs_starter/profiles/rint_sop_live_mock_example.json --mode ai --duration 20 --skip-build --mock-arm --no-ui --no-console
```

`--policy demo` remains the default. `--policy rint --sop-config
aps380_torcs_starter/profiles/rint_sop_mock_example.json` retains fixed mock SOC.
`--mock-arm` is rejected outside the new live-mock policy.

Outputs retain telemetry CSV/JSONL and SOP diagnostics, add prototype instrument
logs and `cell_measurements.jsonl`, and save configs/source hashes and trial
acceptance. Retained estimates are explicitly marked. Normal shutdown freezes
acquisition before intentional instrument OFF, verifies mock shutdown, requests
and acknowledges native zero, then stops telemetry. The observer report is a
pre-shutdown snapshot. Dashboard SOC reads **MOCK Coulomb Counted**, distinct
from native pack SOC; OCV is candidate, R0 assumed, temperature mock, SOP estimated.

## Reproducible validation

```powershell
& .\.venv-bench\Scripts\python.exe -B -m unittest discover -s aps380_torcs_starter -p test_live_cell_state.py -v
& .\.venv-bench\Scripts\python.exe -B scripts/validate_live_cell_state.py --output .local/live-cell-state-validation/new-run
```

Use a new output directory. The actual-TORCS validation independently integrates
logged readbacks, matches native ACKs to earlier command sequences, checks
evolving SOC/OCV/SOP/availability and writes a four-panel graph. A separate
measurement-stream interruption keeps telemetry running and verifies observer
expiry, mock OFF/isolation, native stale-zero latching and zero shutdown.
Fault-response acceptance is separate from successful normal operation.

For final end-to-end acceptance including charging/discharging, matched-input
motor-output comparisons, stale/missing/invalid/reordered measurement faults,
explicit recovery and both real Tk dashboards, run with desktop/Tk access:

```powershell
& .\.venv-bench\Scripts\python.exe -B scripts/validate_live_cell_state.py --comprehensive --output .local/live-cell-final-review/new-run
```

This takes several minutes and runs one simulator at a time. Scripted key states
are supplied through the existing isolated human-driver fixture, never OS input
or a physical wheel. Saved G29 and keyboard settings are fingerprinted. All
current, voltage, temperature, capacity and resistance choices remain mock-only.
The resulting `matched_power.png` compares actual motor output and speed, not
only requested limits. Reports distinguish deliberate fault-response success
from normal operation. Tk refresh logs verify evolving displayed SOC and mock
labels; they do not constitute manual operator confirmation or physical testing.

Still missing: ESP32 acquisition, independently measured net current,
calibrated V/I/T/capacity/R0, charge SOP, standalone BK8500 composition,
physical PSU coordination and independent protection. Mock results establish
neither physical closed-loop operation nor real battery safety.
