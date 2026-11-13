# First physical live TORCS-to-BK8500 test: PSU only, 0..0.10 A

For the separate opt-in up-to-1 A extension with unchanged existing MAX settings,
see [ONE_AMP_LIVE_LAB.md](ONE_AMP_LIVE_LAB.md). This original procedure retains
its own exact protection matching and 0.10 A envelope.

This procedure builds on the working original BK8500 driver and physical replay
tests. It does not authorize a hardware run. Obtain the supervisor's approval
and separately authorize the physical stage in the lab. No battery, ESP32,
second source or battery-bias circuit is involved. The PSU remains manual.

## Established starting point

The original 8500 communicated through the confirmed
IT-E132/compatible TTL interface. Windows used COM10, 9600 baud, address 0,
8N1, DTR/RTS asserted, Python 3.12 and pySerial 3.5. The portable replay sent
0..0.10 A requests and received actual V/I/P, then verified OFF/zero shutdown.
Two Windows sequences reported maximum current differences of 1 mA. A recorded
TORCS segment was also physically replayed on Mac (1.9 mA maximum difference).
These were approximately 1 Hz replay tests, not live TORCS hardware control.
See `README.md`, `instrument.py`, `replay.py`, committed `evidence/2026-10-27/`
and local `.local/bk8500-validation/physical-synthetic*`.

Reuse `instrument.py`; do not recreate its packet/checksum/unit handling or
assume an Ethernet/SCPI interface. COM10 is the last verified port, not a
permanent assignment. The recorded Windows PSU setting was user-reported 5 V,
1 A ceiling, with 5.18 V at the load. That historical ceiling is not approval for
the next test. A current ceiling is not the current the source must deliver.

## Candidate commissioning configuration

These are selected software test parameters, not verified hardware ratings or
settling times. The supervisor must approve or reduce the electrical envelope.

| Parameter | Initial selection |
|---|---:|
| Maximum commanded load current | 0.100 A |
| Original discharge-current reference mapped to full range | 0.050 A |
| Complete control update rate | 1 Hz |
| Maximum commanded slew | 0.020 A/s using elapsed ACK time and conservative 0.1 mA steps |
| Tracking tolerance / persistent-error timeout | 0.010 A / 2 s |
| Load voltage window | 4.5..5.5 V |
| Maximum reported power / load MAX POWER | 0.600 W |
| Command expiry | 0.5 s, unchanged |
| Per-transaction timeout / cycle budget | 0.25 s / 0.8 s, unchanged |

The causal mapping is:

```text
raw_load_A = -original_charging_positive_cell_A / reference_current_A * max_current_A
limited_load_A = clamp(raw_load_A, 0, max_current_A)
```

With the table values, -0.025 A requests 0.050 A, -0.050 A requests 0.100 A,
and larger discharge demands are clipped to 0.100 A. Neutral and regenerative
charging demand request zero. Applied current ramps toward that target rather
than jumping. This is nonnegative eLoad branch current, not net battery current.
Original signed demand and its original battery clip are logged separately.

The hardware CLI now rejects current caps above 0.10 A before importing serial.
Default 0..3 A mock experiments and prototype limits remain available and
unchanged. Their success does not authorize higher physical currents.

## Home: mock-only commands

Use VS Code PowerShell at the repository root. Keep instruments disconnected.
Use the already prepared `.venv-bench`; if needed, its dependencies are listed
in `live-requirements.txt`. The native simulator and human driver must already
be built. These commands do not rebuild or recalibrate the wheel.

Keyboard driving, with the existing independent smoothed-keyboard profile:

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs keyboard --duration 300 --max-current-A 0.10 --reference-current-A 0.05 --max-power-W 0.6 --slew-A-per-s 0.02 --tracking-tolerance-A 0.01 --control-hz 1
```

Start Race > Practice > New Race. Once the console shows READY and RECEIVING,
type `ARM`. `DISARM` verifies OFF/zero; `STOP` latches a software emergency stop;
`RESET` verifies shutdown and returns READY without rearming; `QUIT` closes.

For G29, use exactly the same mock command with `--torcs g29`. This path now
reads `.local/tesla-profile` directly and does not call its setup writer. Keyboard
mode prepares only `.local/tesla-keyboard-profile`. Steering, analog calibration,
keyboard ramp rates, battery scaling and instrument-coordinator policies are
not rewritten. Physical G29 driving is a manual check, not established by fake
axis tests. Add `--dashboard` to reuse the original APS380 graphs with a separate
MOCK/REAL BK8500 load-current tab; see [DASHBOARD.md](DASHBOARD.md). The HUD and
original prototype mock PSU/eLoad dashboard functionality remain available.

Reproducible live AI smoke check without hardware:

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs ai --duration 30 --telemetry-port 0 --max-current-A 0.10 --reference-current-A 0.05 --max-power-W 0.6 --slew-A-per-s 0.02 --tracking-tolerance-A 0.01 --control-hz 1 --auto-arm-mock --no-console
```

Mock-only native telemetry-interruption check:

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs ai --duration 18 --telemetry-port 0 --max-current-A 0.10 --reference-current-A 0.05 --max-power-W 0.6 --slew-A-per-s 0.02 --tracking-tolerance-A 0.01 --auto-arm-mock --no-console --inject-telemetry-loss-after 12 --expect-telemetry-fault
```

The interruption must fail normal-operation acceptance and pass the separate
fault-response check only if OFF/zero is verified. Automatic arming and fault
injection are rejected in hardware mode.

## Lab: checks while the load remains OFF

1. The supervisor verifies the actual PSU model/channel, independent mode,
   source voltage/current/power ratings, local current limit, CV behavior,
   polarity, leads/connectors, cooling, protection and accessible physical OFF/
   emergency-stop action. Confirm no battery or other source is connected.
   Verify the TTL adapter and port against the already proven setup.
2. Keep the BK8500 input OFF. Configure and verify the approved PSU manually.
   Confirm both actual terminal/readback voltages; the software does not read or
   command this PSU. Do not assume its configured current ceiling guarantees CV
   operation or stable current tracking. Stop on an unexplained discrepancy.
3. The following identification command sends only identity/measurement queries.
   It does not set mode/current or turn the input ON. Check the returned identity,
   voltage and `input_on=false` before continuing. Change COM10 only if verified.

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/replay.py --identify --port COM10 --baud 9600 --address 0 --confirm-ttl
```

4. For the candidate envelope above, manually set/verify load MAX VOLTAGE 5.5 V,
   MAX CURRENT 0.10 A, MAX POWER 0.6 W. The live preflight reads these maxima
   through the existing driver and requires matching values; it does not change
   protections. If the instrument cannot represent them, rejects a query, or
   reports something different, remain OFF and retain the diagnostic log. Do not
   bypass the checks. These newer readback queries still need physical validation.
5. Create a blank, non-authorizing form in an ignored local approval file, and fill
   actual verified information with the supervisor:

```powershell
if (Test-Path -LiteralPath .local/bk8500-live-low-approved.json) { throw 'Keep the existing approval file; review it with the supervisor.' }
$fields = @('approved_by', 'approval_reference', 'psu_model', 'psu_output', 'source_limit_kind',
    'verified_source_current_ceiling_A', 'verified_output_voltage_V',
    'psu_channel_voltage_rating_V', 'psu_channel_current_rating_A', 'psu_channel_power_rating_W',
    'wiring_current_rating_A', 'approved_current_A', 'approved_voltage_max_V',
    'approved_power_W', 'approved_control_hz', 'approved_slew_A_per_s')
$checks = @('no_battery', 'ttl_verified', 'wiring_polarity_and_ratings_verified',
    'independent_protection_and_estop_verified', 'psu_settings_verified', 'supervised_lab_approval')
$blankApproval = [ordered]@{}
foreach ($field in $fields) { $blankApproval[$field] = $null }
foreach ($check in $checks) { $blankApproval[$check] = $false }
New-Item -ItemType Directory -Path .local -Force | Out-Null
$approvalText = $blankApproval | ConvertTo-Json
$approvalPath = Join-Path (Get-Location) '.local/bk8500-live-low-approved.json'
[System.IO.File]::WriteAllText($approvalPath, $approvalText, [System.Text.UTF8Encoding]::new($false))
```

The form's null values and false confirmations deliberately cannot authorize
hardware. Do not overwrite an existing approval file. Record the actual channel
(`CH1_independent`/`CH2_independent` as applicable), source-limit kind and actual
ratings/ceilings, plus the lab-approved current, voltage, power, slew and rate.
Set the confirmations only after inspection/approval. The JSON is an attestation,
not authentication, remote PSU verification or independent protection.

## Separately authorized physical live stage

### Step 4B: independent OFF-only preflight

Set `$bkSerial` to the serial from verified identification.
Use this one-shot check before the live stage. It does not launch TORCS, receive
telemetry, offer ARM, or authorize current draw. Approval names/references and a
numeric wiring rating are not required for this OFF-only check. An optional
`--setup-record` preserves factual information and unknown fields without
interpreting them as permission to enable the input. Full live operation retains
the existing approval validator and supervised ARM requirements unchanged.

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/off_preflight.py --device hardware --port COM10 --baud 9600 --address 0 --confirm-ttl --expected-serial $bkSerial --setup-record .local/bk8500-live-low-approved.json
```

This is an active OFF-state check, not a query-only identification command:
it identifies the instrument, selects remote FIXED/CC, commands input OFF and
zero current, checks voltage/current/status and reads protections. The command
contains today's explicitly verified port and serial; use the verified identity
for any future setup. It never changes PSU settings or load protection settings.
Its restricted device interface forbids input ON and nonzero current, including
during the reused shutdown sequence. Its fixed envelope is 0.10 A, 4.5..5.5 V,
0.6 W, 1 Hz and 0.02 A/s; no control loop or slew test is performed.

Expect `result: PASS`, matching identity, verified protections of 5.5 V / 0.10 A /
0.6 W, `input_on: false`, zero setting and `shutdown.verified: true`. Current-draw
tracking is explicitly not assessed. Reports default to
`.local/bk8500-off-preflight/<UTC timestamp>.json`. A failure exits nonzero; an
unverified shutdown must be treated as unverified, with independent physical
stopping available. Do not bypass mismatches or interpret PASS as ARM approval.

Mock-only check, requiring no serial port or approval data:

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/off_preflight.py --device mock
```

### Live control (separate from OFF-only preflight)

After approval and explicit authorization, from an interactive terminal:

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device hardware --torcs keyboard --port COM10 --baud 9600 --address 0 --approval .local/bk8500-live-low-approved.json --duration 180 --max-current-A 0.10 --reference-current-A 0.05 --max-power-W 0.6 --slew-A-per-s 0.02 --tracking-tolerance-A 0.01 --control-hz 1
```

This opens the port and performs OFF/zero/FIXED/CC/protection preflight. It starts
with input OFF and does not arm automatically. G29 uses the same command with
`--torcs g29`; close the other simulator first.

1. Start the race; review READY, RECEIVING, initial zero setting, voltage and
   protection readbacks. If any check fails, stay OFF and investigate.
2. With the supervisor present, type `ARM <approval_reference>` using the exact
   reference from the approved file. Do not pipe/script it. Only this arm path
   issues input ON, after repeating preflight and checking fresh telemetry.
3. Start with zero/low demand, then gentle acceleration, release/regen and
   moderate demand. Observe original/scaled/limited demand, commanded setting,
   returned setting, measured current, voltage, power, latency and status.
   Expect a ramp of at most 20 mA per update and a 100 mA command cap. Record PSU
   CV behavior manually; eLoad readback cannot positively identify PSU mode.
4. Stop on unexpected current/voltage/power/direction, communication trouble or
   physical heating. No current above 0.10 A is authorized by this procedure.
   The existing measured-current guard has a 2 mA readback tolerance; that is
   software policy, not permission for extra physical current. Do not increase
   limits/tolerances or shorten delays to conceal a failure.
5. With supervisor approval, pause telemetry to exercise the existing 0.5 s
   expiry fault. Verify actual front-panel OFF and zero current. A latched fault
   must not rearm itself when data resumes. RESET alone does not arm.
6. Type DISARM/QUIT for orderly shutdown. Verify the saved OFF/zero readback and
   the physical front panel, then manually switch off the PSU. A broken USB
   link/PC can prevent software OFF; use independent physical stopping. Do not
   unplug an energized link as an assumed safe shutdown mechanism.

Do not use legacy `replay.py --run` for this stage expecting an ARM prompt:
that explicitly authorized replay command enables input as part of its run.
The live runner uses a separate explicit interactive ARM.

## Evidence and acceptance

Outputs default to a unique `.local/bk8500-live/<timestamp>/` directory.

- `config.json` and `manifest.json`: selected range/gain, limits, mode and hashes.
- `instruments/control.jsonl`: state/faults, ACK result, source session/sequence,
  TORCS simulation time, host command/ACK/readback/measurement-receipt times,
  UTC record time, freshness, measured V/I/P, observed/verified protections and
  verified or unverified shutdown. Stopped/fault readbacks are marked retained.
- `load_tracking.csv` / `.png`: completed RUNNING cycles with separate original,
  original battery-limited, mapped/limited/power-limited, commanded, returned
  setting and measured current, error and latency fields.
- `telemetry/`: existing native CSV/JSONL and timing/plots, unchanged protocol.
- `trial.json` and `instruments/summary.json`: telemetry, instrument, process,
  artifact and shutdown acceptance. Plot/report failures stay FAIL and retain
  the instrument result instead of erasing final trial evidence.

ACK means the existing driver's checksum/status validation returned successfully;
it is not proof current has settled. Host receipt times are not synchronized
instrument ADC timestamps. Shutdown is independently reported; communication
failure can leave it unverified. Zero RUNNING cycles do not establish tracking.
The nested telemetry report's `hardware_commands_sent=false` describes only the
receiver. Use outer `hardware_control_selected`,
`hardware_commands_may_have_been_sent`, `hardware_input_on_acknowledged`, and
instrument events to assess this application's physical-control path.

Accept a healthy short trial only with fresh valid telemetry, correct acknowledged
settings, current tracking within the approved policy, no unexpected faults,
cycle timing within budget and verified OFF/zero shutdown. A completed racing
course is not required. Deliberate fault tests retain normal-operation FAIL
separately from fault-response acceptance.

Remaining physical acceptance includes the new protection readbacks, low-current
live ARM/streaming, current settling and CV behavior, timing under real USB load,
operator emergency stopping and communication-loss behavior. The previous
0..0.10 A replay proves the existing communication/control foundation, not these
new live-loop properties. No home/mock result establishes physical safety.

## Home validation -- November 12, 2026

No instrument was connected or accessed. The saved G29/default TORCS settings,
keyboard ramp JSON, scaling code, prototype policy/coordinator and working binary
driver matched their before/after hashes (39 protected files).

- 52 bench tests passed, including 12 new low-current/readiness regressions.
- Existing starter suite: 163 passed, one Tk widget test skipped (`init.tcl`).
- Two keyboard-profile and two portable-setup tests passed.
- Existing native checks: 18 EV + 15 publisher + 9 HUD + 31 keyboard passed.
- Actual headless TORCS AI to the mock live runner: 1,509 valid samples and 30
  complete cycles, commanded range 0.0025..0.1000 A; largest mock tracking error
  0.0650 mA and largest cycle 370.5 ms. Normal acceptance and shutdown passed.
- Two actual headless human-code fixture runs exercised scripted keyboard and
  fake G29 axes, each with 714 valid samples and 14 complete low-current cycles.
  Regeneration requested zero load; current caps, tracking and shutdown passed.
  These use the existing separate test robot, not OS input or a physical wheel.
- A deliberate native telemetry interruption had 597 valid samples and 12 cycles
  before latching STALE_TELEMETRY. OFF/zero was verified; fault-response passed
  while normal-operation acceptance correctly remained FAIL.
- Offline tests verify rejected ACKs, setting mismatch, measured-current errors,
  communication loss/unverified shutdown, stale input, explicit recovery, hardware
  automation/high-current rejection, CSV timestamps and report preservation after
  an injected plotting failure. No zero-cycle run is called tracking success.

Evidence is under `.local/bk8500-readiness-validation/`, including `audit.json`,
the test logs, `final-live-ai/`, `final-interruption/` and `human-modes/`.
Source/binary manifests and all 70 completed cycles across the final captures
were checked. Mock errors are model results, not predictions of physical accuracy.

The saved November 4 manual capture had approximately 0.58..0.79 s stream gaps
and a stale-data fault. These headless home tests do not establish graphical
timing or its root cause. Let the graphical race finish loading and confirm
stable RECEIVING before ARM; unexpected graphical stalls must remain visible
faults. The 0.5 s expiry policy is unchanged. Real USB timing, new protection
queries and physical live tracking remain lab checks. Subsequent desktop Tk and
manual mock dashboard checks are documented in `DASHBOARD.md`; their success
does not validate the physical live controller.
