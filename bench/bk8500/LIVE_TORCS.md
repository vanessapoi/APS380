# Live TORCS to BK8500: PSU-only tracking experiment

This is a separate load test, not battery current simulation. No cell, ESP32,
PSU bias, SOC/SOP feedback or new vehicle derating is involved. Existing TORCS,
mock battery coordinator and legacy 0.10 A replay remain separate.

`live_torcs.py` defaults to an in-memory load. Hardware mode requires a verified
setup/lab-approval JSON and an interactive terminal. Startup commands input OFF,
selects FIXED/CC, zeroes the setpoint and reads back voltage, OFF state and the
instrument's protection limits. **Startup never commands input ON.**

## Current mapping and limits

Keep the original charging-positive cell demand and existing fixed scaling.
Use its **unclamped** value as the input to a separate, fixed bench gain:

```text
scaled_load_demand_A = -original_cell_current_A * 3 / reference_current_A
limited_load_target_A = clamp(scaled_load_demand_A, 0, approved_max_current_A)
power_limited_target_A = min(limited_load_target_A, approved_max_power_W / voltage_readback_V)
command = slew_and_quantize(power_limited_target_A)
```

Negative original CELL current represents discharge and increases load demand.
Positive original CELL current represents regenerative charging and maps to zero
load demand; this PSU-only setup cannot return power to the PSU. The logged
`scaled_load_demand_A` is the candidate *before* nonnegative clipping. Original
signed demand and the original battery-limited demand are retained separately.
There is no `i_p - i_c` mapping and no online peak normalization.

The reference is fixed before a session. Default 2 A maps original -2 A to load
3 A. An illustrative reference of 0.05 A maps original -0.05 A to 3 A, so normal
driving can exercise the full load range. It is an explicit bench amplitude gain,
not calibrated battery/vehicle equivalence. Review a mock capture before choosing
it for hardware. Raw peaks above the reference saturate visibly at the selected
ceiling. Do not reduce or retune it automatically while driving.

The full software range is 0 to 3 A; an approved subset may be selected with
`--max-current-A`. Default slew is 0.5 A/s. A rising full-range step consequently
takes at least six update steps at 1 Hz; instantaneous demand tracking is not
claimed. Power limits can reduce the achievable current below 3 A. Command
readback is checked against the quantized 0.1 mA setting; measured current is
compared against the applied command, and demand lag is logged separately.

These are software experiment policies, not verified physical settling times.
Post-command measurement delay is 0.1 s; tracking errors above 0.05 A persisting
for 2 s fault. These sampling/tolerance settings require lab review for hardware.

## PSU and electrical verification before hardware

The operator reported a GW Instek GPC-3030, an **adjustable output**, and a verified
3.1 A current ceiling. The fixed 5 V output is not being used. Record CH1 or CH2
and use independent mode. A configured 3.1 A limit does not establish a higher
channel rating or prove that 3 A can be supplied at stable voltage. Commands
remain at or below the approved 3 A envelope. Do not increase the source limit
based on these instructions.

A voltage-regulated source feeding a CC eLoad is appropriate in principle:
the PSU supplies the demanded current while maintaining voltage below its limits.
At its current/power limit, the voltage can droop and tracking can fail. Verify
CV operation and the actual voltage on the PSU and load during the supervised
trial. The controller sees load voltage/current/power and can detect envelope or
tracking failures; it **does not read or control this PSU**, nor positively identify
the PSU's CV/CC mode. PSU model/channel/settings in the log are human attestations.

Before any physical ARM, the TA/lab must verify channel voltage/current/power
ratings, terminal voltage and polarity, independent mode, wiring and connectors,
protection/fusing, cooling, source current limit and an accessible independent
emergency stop. For example, 5 V at 3 A is 15 W; use actual voltage and the approved
power envelope, not the PSU current knob alone. Existing 0.10 A evidence does not
validate 3 A operation. No battery or additional source is permitted in this test.

Copy `approval.example.json` to an ignored local file. It intentionally contains
null values and false confirmations, and **cannot authorize hardware operation**.
Fill actual verified ratings and approval with the supervisor; this file is not
proof of approval or a replacement for inspection. `psu_channel_voltage_rating_V`
means the verified permissible operating ceiling, accounting for the actual
channel specification, rather than assuming all channels share the same rating.
The requested current, power, voltage ceiling, slew and update rate must fit the
approved envelope. The source ceiling alone never expands the load command cap.

Configure the load's MAX VOLTAGE, MAX CURRENT and MAX POWER protections to match
the selected controller envelope before launch. The software reads these limits
again at ARM and rejects mismatches; it does not silently rewrite protections.
The example CLI envelope is 4.5 to 5.5 V, 3 A, 18 W; those values are **not lab
approval**. Lower the CLI limits to the actually approved envelope where needed.

References: [GW Instek GPC series](https://www.gwinstek.com/en-US/products/detail/GPC-Series),
[manufacturer-authored GPC-3030 manual](https://www.transcat.ca/media/pdf/GW-Instek-GPC-3030-Manual.pdf),
[BK8500 manual](https://bkpmedia.s3.amazonaws.com/downloads/manuals/en-us/85xx_manual.pdf)
(binary protocol, CC commands, status and maximum protection settings).

## VS Code setup and mock test

Open `C:\Users\anhyo\Desktop\APS380-main\APS380` in VS Code. Use PowerShell in
that repository root. Live control requires Python 3.10+; the old replay remains
Python 3.9 compatible. The existing TORCS build must already be ready. To rebuild
and check it without operating instruments, the original launcher can be used:

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B scripts/run_tesla_live.py --mode ai --duration 15 --acceptance smoke --no-ui
```

The separate bench environment can contain both the existing serial dependency
and the plotting dependency used by the live receiver:

```powershell
Set-Location 'C:\Users\anhyo\Desktop\APS380-main\APS380'
# The bench environment already exists on this computer.
& .\.venv-bench\Scripts\python.exe -m pip install -r bench/bk8500/live-requirements.txt
& .\.venv-bench\Scripts\python.exe -B -m unittest discover -s bench/bk8500 -p 'test_*.py' -v
```

Run actual TORCS AI telemetry into the **mock** load:

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs ai --duration 30 --reference-current-A 0.05 --auto-arm-mock --no-console
```

`--auto-arm-mock` is permitted only for mock testing. A hardware command with
that flag is rejected before importing serial or opening a port.

For manual driving with the mock load:

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs g29 --duration 600 --reference-current-A 0.05
```

Start Practice in TORCS using the existing driving controls. In the PowerShell
terminal, type `ARM` once READY and RECEIVING. `DISARM` turns input OFF and zeroes
the setpoint. `STOP` is a latched software emergency stop; `RESET` verifies
shutdown and returns READY without rearming. `QUIT` ends the run. Telemetry must
be fresh before ARM; pausing TORCS while running faults rather than holding an
old current. The new runner uses console readbacks; the original dashboard and
HUD code/formats are unchanged.

## Future supervised real test -- not executed by implementation validation

1. Complete the electrical checks and obtain lab approval. Confirm the actual
   COM port still belongs to the verified IT-E132/BK8500. Do not connect a battery.
2. Save the completed profile at `.local/bk8500-approved.json`; retain the example
   file unchanged. Use an approval reference meaningful to the lab.
3. Configure the approved source and load protection settings. Check the physical
   OFF/E-stop controls. Keep load input OFF. The PSU remains manually operated.
4. From an interactive VS Code PowerShell terminal, launch the new controller.
   This command opens the serial connection and performs OFF-state preflight,
   **but cannot enable input until the later typed ARM step**:

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device hardware --torcs g29 --port COM10 --approval .local/bk8500-approved.json --duration 600 --max-current-A 3 --max-power-W 18 --voltage-min-V 4.5 --voltage-max-V 5.5 --reference-current-A 0.05
```

5. Start the race. Review READY/RECEIVING and have the supervisor confirm the
   approved setup. Type `ARM your-approval-reference` exactly as printed. Do not
   pipe or script this phrase. It rechecks OFF, FIXED/CC, protection limits,
   zero setting and fresh telemetry before the sole input-ON path.
6. Observe requested/limited/commanded/readback/measured current, voltage, power
   and timing. Test the approved portion of the range, zero demand and load
   changes. Check the PSU's voltage-regulation indicator/readings. If tracking
   fails or voltage droops, stop; do not increase limits to conceal it.
7. Use `DISARM` or `QUIT` for an orderly stop; `STOP` or Ctrl+C requests emergency
   shutdown. Verify the saved shutdown evidence and the actual front-panel OFF
   state, then disable the PSU manually. An EOF/lost console requests STOP.

On telemetry expiry (0.5 s), invalid/session-discontinuous data, unexpected mode,
measurement limits, setting mismatch, persistent tracking error or communication
failure, faults latch and OFF/zero/readback are attempted. The worker checks data
between bounded transactions and polls supervision at about 20 ms while idle;
this is not a hard real-time guarantee. A broken USB link or hung PC can prevent
shutdown. Reports explicitly say unverified in that case. Independent protection
and a physical E-stop must work without Python; this code implements neither.

## Logs, acceptance and rate evaluation

Runs go to a new ignored `.local/bk8500-live/<timestamp>/` directory; `--output`
can select a different new path. It contains:

- `config.json`, `manifest.json`: effective fixed mapping, limits, human approval
  data and tested source/binary hashes; no claimed PSU remote measurement.
- `instruments/control.jsonl`: state transitions, source timestamps/sequences,
  original/limited CELL demand, scaled/limited load demand, commanded/readback/
  measured current, voltage, power, latencies, freshness, faults and shutdown.
- `load_tracking.csv`, `load_tracking.png`: completed RUNNING samples and plots.
- `telemetry/`: existing receiver JSONL/CSV, timing report and live profile plot.
- `trial.json`, `instruments/summary.json`: independent normal-operation,
  process/telemetry/instrument and shutdown outcomes. Course completion is not
  required. Retained fault/stop measurements are marked historical.

Start at 1 Hz. The default mock inserts 64 ms per transaction, based on earlier
bench acknowledgement observations; actual delays are measured, and this is not
a prediction or safety bound for real hardware. Frozen samples expire at 0.5 s;
the newest sample is selected after the pre-command voltage check. Each current
cycle includes several transactions and the post-command sample delay.

Evaluate 2 Hz with a mock first, explicitly selecting a shorter cycle budget:

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs ai --duration 30 --reference-current-A 0.05 --control-hz 2 --max-cycle-s 0.49 --auto-arm-mock --no-console
```

Hardware rate increases require separate approval and measured complete-cycle
timing, not just write acknowledgement timing. The tool rejects rates above 2 Hz.
There is no backlog or catch-up burst after a slow transaction.

A reproducible mock fault-response experiment (roughly four minutes, including
actual native regenerative driving near 194 s):

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs ai --duration 225 --reference-current-A 0.05 --auto-arm-mock --no-console --inject-telemetry-loss-after 220 --expect-telemetry-fault
```

Normal-operation acceptance must FAIL for that deliberate loss; verified fault
response is a separate result. All such injection/automatic-arming flags are
forbidden in hardware mode. Physical dynamic 0..3 A tracking is NOT validated by
mock success or the previous 0..0.10 A hardware runs.

## Executed validation -- October 27, 2026

No real serial port was opened, and no physical input was enabled during this
implementation. The isolated bench environment was prepared with the live
requirements. The final bench suite passed **40 tests**, including the existing
12 replay/protocol tests and 28 new live-controller cases. The existing starter
suite executed **164 tests: 163 passed and one Tk widget test skipped** because
`init.tcl` is unavailable. Native checks passed **18 EV + 15 publisher + 9 HUD**.

Actual TORCS with a mock load and an imposed 64 ms transaction delay produced:

| Trial | Samples / completed control cycles | Largest mock tracking error | Largest cycle |
|---|---:|---:|---:|
| 1 Hz normal driving | 1,256 / 25 | 1.647 mA | 372.1 ms |
| 1 Hz driving, regeneration, deliberate loss | 10,995 / 220 | 1.654 mA | 384.9 ms |
| 2 Hz normal driving | 1,273 / 47 | 0.821 mA | 386.7 ms |

Both normal trials passed telemetry, instrument, process and artifact acceptance.
The long run reached load commands from 0 to 3 A and observed 14 regenerative
samples at the control rate mapping to zero demand. The first verified fault/
shutdown record was about 0.803 s after deliberately stopping TORCS; it includes
shutdown transaction time, not just fault detection latency. OFF, zero setting
and zero mock measured current were verified. Normal-operation acceptance stayed
FAIL for that deliberate fault; fault-response acceptance passed. Course
completion and physical 0..3 A tracking were NOT ASSESSED.

Median update spacing was about 1.005 s and 0.510 s in the long 1 Hz and short
2 Hz runs. The latter demonstrates mock feasibility, not verified hardware 2 Hz
capability. All final capture manifests match the tested controller sources.
The independent audit matched 292 completed control cycles to their original
telemetry samples, fixed gain, limits, settings/readbacks, measured values,
freshness and shutdown evidence. Logs, plots and `audit.json` are under
`.local/bk8500-live-validation/verified-*` and its parent directory.

An earlier long trial correctly faulted on command expiry while telemetry was
healthy. Selecting the newest demand after the pre-command voltage check removed
unnecessary sample age; regression tests verify that this does not erase an
invalid continuity epoch or weaken the 0.5 s expiry check. The earlier failed
capture is retained at `.local/bk8500-live-validation/regen-interruption/`.

Manual graphical driving with this new launcher, the actual PSU's CV behavior,
full-range hardware tracking, physical emergency isolation and hardware update
rates remain unverified. The original telemetry/scaling, native physics and
mock battery coordinator sources were not changed by this extension.

## Integration with Mac-support changes -- October 29, 2026

The Windows working tree was integrated with `origin/main` at `2ec4150`.
Both the original BK8500 bench evidence and Mac-support sections were retained
in `PROJECT_CONTEXT.md`. Windows defaults, the UDP schema, native power physics,
cell scaling and the original prototype coordinator remain unchanged. The shared
platform header retains Winsock/QPC on Windows. The simulator, graphics/client
and AI driver were rebuilt successfully with the combined sources.

Regression results: 40 bench tests passed; 163 starter tests passed and one Tk
test skipped because `init.tcl` is unavailable; two portable setup tests and
42 native checks passed. One complete AI course passed all 11 protocol gates
(442.08 simulated seconds, 4218.36 m). This course check is separate from short
live-integration acceptance.

Actual TORCS with mock instruments produced:

| Trial | Telemetry samples / RUNNING cycles | Result |
|---|---:|---|
| Original prototype, 215 s session | 10,715 / 1,980 | Telemetry and instrument acceptance PASS; discharge and regeneration observed |
| Standalone, 1 Hz with deliberate loss after 220 s | 10,933 / 219 | No fault before interruption; fault-response PASS; normal-operation FAIL as required |
| Standalone, 2 Hz, 25 s | 1,261 / 47 | Telemetry and instrument acceptance PASS |
| Standalone, no ARM, 5 s | Live telemetry / 0 | Stayed OFF; control NOT ASSESSED; verified shutdown |

The standalone long trial exercised 0 to 3 A commands and 14 regenerative
control samples mapping to zero demand. Maximum measured-versus-commanded
error was 1.649 mA at 1 Hz and 0.823 mA at 2 Hz; largest cycles were 386.2 ms
and 382.7 ms. Its first verified fault/shutdown record was 0.749 s after the
deliberate interruption, including shutdown transactions, not just detection.
OFF, zero setpoint and zero mock measured current were verified.

The original prototype retained charging-positive `i_c = i_p - i_e`, fixed
1 A PSU bias and 0 to 3 A eLoad limits. Maximum measured-versus-applied error
in the live run was 20.10 mA (30 mA policy). Demand-versus-measured error reached
130.99 mA during the existing slew/reversal policy; these are different errors.
A separate synthetic profile exercised the -2 A, 0 A and +1 A cell targets,
including enabled 0 A eLoad, and verified expiry shutdown. A separate native
telemetry-interruption trial also passed fault-response checks. Both prototype
outputs were disabled and mock isolation opened. Retained pre-fault readbacks
remain explicitly historical. The synthetic and interruption trials correctly
retain FAIL for normal operation after their deliberately induced faults.

The default-disarmed standalone CLI exits with status 1 because no control
cycles were assessed; the explicit safety test passed by checking NOT ASSESSED,
zero RUNNING cycles, no fault and verified OFF/zero shutdown. This is not
reported as successful current tracking. An independent audit matched all
266 completed standalone control cycles to received source samples, fixed
mapping, limits, freshness, readbacks and current-source/binary manifests.
CSV counts and plots were checked; the long tracking plot was inspected.

Raw evidence, commands, reports and audit results are retained locally under
`.local/integration-validation-20261029/`; the full-course artifacts were moved
from the generated output directory into its `full-course/` subdirectory.
These are ignored local artifacts. No serial port was opened or physical
instrument controlled. Native Mac execution, manual graphical/G29 operation,
the skipped Tk widget test and physical 0 to 3 A tracking remain unverified
by this integration session. Mock timing does not establish hardware safety.
