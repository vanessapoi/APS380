# Mock vehicle propulsion availability

The previous `driver_feedback.py` / HUD protocol displays current-limit alerts;
it does not command motor limits. The BK8500 branch-current clamp also does not
limit TORCS propulsion. This opt-in demonstration adds that separate capability.
It does not implement physical battery SOP, a validated OCV-SOC limit or hardware
protection. No instrument drivers are imported by the new launcher.

An additional selectable [Rint SOP mock policy](rint-sop.md) now replaces the
arbitrary SOC band only when explicitly requested with `--policy rint` and a
mock parameter file. The default demonstration and fixed-fraction modes remain.

## Launch from VS Code PowerShell at the repository root

Close another TORCS instance before building/running. The native simulator is
built by default; Visual Studio/MSBuild requirements are unchanged. After a
successful build, `--skip-build` reuses the native DLL.

```powershell
# Keyboard, simulated policy SOC 22.5% -> 70% propulsion availability.
& .\.venv-bench\Scripts\python.exe -B scripts/run_vehicle_power_limit.py --mode keyboard --demo-soc 0.225 --duration 300
# Existing saved G29 configuration; no recalibration or rewriting.
& .\.venv-bench\Scripts\python.exe -B scripts/run_vehicle_power_limit.py --mode g29 --demo-soc 0.225 --duration 300 --skip-build
# Fixed test override: repeat with 1.0, 0.7, 0.5 or 0.2.
& .\.venv-bench\Scripts\python.exe -B scripts/run_vehicle_power_limit.py --mode ai --fraction 0.5 --duration 20 --skip-build --no-console
```

Keyboard/G29 open graphical TORCS: select Race > Practice > New Race. The original
APS380 dashboard opens too. AI mode drives headlessly while retaining the
dashboard; `--no-ui --no-console` permits unattended mock tests. The existing
keyboard smoothing and steering configuration are reused. Physical G29 behavior
still needs operator verification; automated fixtures never poll physical input.

Policy defaults: `--soc-low 0.10 --soc-full 0.30 --minimum-fraction 0.20`.
Between 10% and 30% simulated SOC, availability rises linearly from 20% to 100%:

```text
fraction = minimum + (1-minimum)*clamp((sim_SOC-low_SOC)/(full_SOC-low_SOC),0,1)
```

Without `--demo-soc`, the source is native **simulated pack SOC**, not measured
cell SOC. An override changes only the demo policy input; native pack energy/SOC
remains separately visible. `--fraction` overrides the policy for fixed tests.
The 20% floor is an arbitrary demonstration choice, not a safe depleted-cell
limit. Existing native empty-pack protection still applies independently.

Fractions scale available positive propulsion torque/power, then the unchanged
pedal law and energy constraints determine delivered power. They do not mean
the motor must consume exactly that fraction at every instant. Lift-off regen,
friction braking, negative shaft work while rolling backwards, auxiliary draw,
current signs, pack/cell scaling, keyboard ramps and G29 input remain unchanged.

## Native interface and recovery

Only this launcher's child receives `APS380_MOCK_POWER_LIMIT=1`. Do not set it
globally or add it to BK8500 launches. Default simulation ignores power commands
and retains a fraction of one. The explicit mode fails closed if its telemetry
channel cannot open. Existing native CSV/profile identity and HUD wire format
are unchanged; optional JSON `power_limit` acknowledgements are added only in
the opt-in mode.

Python replies to the native telemetry datagram's return endpoint from the same
receiver socket. Native accepts commands only from its configured loopback
telemetry peer's IP/port. Each car/race has its own existing session identifier.

```text
APS380POWER1 <session_id> <sequence> <sender_monotonic_s> <fraction> <reset_0_or_1>
```

- ASCII, at most 512 bytes, no extra tokens; fraction finite in [0,1].
- Sequence integer 0..1,000,000,000; duplicates/replays do not refresh expiry.
- Shared monotonic clock is required (verified by the Python launcher on this
  Windows setup). Reject age >250 ms or a sender >1 ms in the future.
- Native polls nonblocking, at most 32 datagrams per physics step. Python sends
  one current command per valid telemetry sample (normally approximately 50 Hz),
  with no queued future commands. Unknown peers/sessions cannot control this car.
- A valid explicit reset activates a waiting mode. The launcher sends one initial
  reset as part of the user's opt-in; it does not auto-retry a lost reset.
- More than 500 ms without fresh accepted feedback latches `FAULT_STALE`, with
  applied fraction zero. Malformed/out-of-range trusted feedback latches
  `FAULT_INVALID`. A late heartbeat cannot erase an expired interval.
- Ordinary fresh messages cannot recover either fault. Type `RESET` in the
  launch terminal or click **Reset propulsion feedback**. Reset must have a new
  sequence and a timestamp after fault detection. Pre-fault/in-flight resets
  cannot release the latch. Release the accelerator before requesting recovery;
  a reset restores the requested availability and may increase propulsion.
- A changed race session requires a new explicit RESET. A lost initial reset
  also requires RESET. Native acknowledgements show `WAITING`, `ACTIVE` or the
  latched fault and the last accepted commanded/applied fractions.
- **Zero propulsion**, QUIT or Ctrl+C requests zero and waits up to one second
  for fresh native applied-zero confirmation before stopping the launched child.
  Confirmation must acknowledge the sequence of the new zero request; a retained
  earlier zero value is not sufficient.
  Zero propulsion is terminal for that demo run; restart to resume. If the
  receiver/peer has failed, zero confirmation may be unavailable; this is reported
  as FAIL, and the native expiry still applies while physics is running.

This endpoint/session binding is not cryptographic authentication. It assumes a
trusted local machine and is not suitable for remote or physical safety control.
Zero propulsion is not an emergency brake, contactor or electrical isolation.
Regeneration can remain active when the accelerator is released. A frozen
physics process does not advance; expiry is evaluated before resumed propulsion.
No mock result establishes physical battery safety.

Missing native acknowledgement support (for example an old simulator DLL), or an
invalid acknowledgement, stops the launched trial promptly and reports FAIL;
the launcher cannot claim that an unsupported simulator applied a zero command.

## Dashboard and evidence

The original dashboard shows Python requested, native last commanded and native
applied availability, policy name/source, simulated policy SOC and feedback age.
Native pack SOC remains simulated. Existing PSU/eLoad dashboard modes are not
replaced; this launcher owns no instruments and does not add live hardware mode.

Default artifacts: `.local/vehicle-power-trials/<timestamp>/`: policy/mode config,
source/native hashes, native log, original telemetry CSV/JSONL/plot and `trial.json`.
Vehicle-limit columns are additive only in the opt-in capture. The report scans
the full saved stream (not just the rolling GUI history) for faults. Fault tests
remain distinct from normal-operation acceptance.

Reproduce the matched-input and fault experiments after building:

```powershell
& .\.venv-bench\Scripts\python.exe -B scripts/validate_vehicle_power.py --output .local/vehicle-power-validation/my-comparison
```

The existing isolated human-code fixture supplies identical key states with
existing keyboard smoothing; it never injects OS input or replaces `human.dll`.
Five approximately 14-second actual TORCS runs compare disabled/default, 100%,
70%, 50% and 20%. All also exercise the original mock PSU/eLoad coordinator.
The native fault trial pauses only feedback (telemetry continues), resumes normal
heartbeats without reset, explicitly resets, injects an invalid fraction, resets
again and verifies zero shutdown. Saved G29/default-profile hashes are checked.

Observed comparison on November 12, 2026, identical controls over 51 samples in
the 1..2 s window; 702 valid telemetry samples per driving run:

| Fraction | Speed at 2 s (m/s) | Mean acceleration 1..2 s (m/s2) | Peak motor power first 2 s (kW) |
|---|---:|---:|---:|
| Disabled/default | 3.2231 | 2.6478 | 25.757 |
| 100% | 3.2231 | 2.6478 | 25.757 |
| 70% | 2.1820 | 1.7946 | 12.082 |
| 50% | 1.4974 | 1.2329 | 7.259 |
| 20% | 0.5441 | 0.4422 | 1.532 |

Motor power ratios differ from the configured fractions because RPM also changes
as the car accelerates more slowly. Native kernel tests additionally compare
identical RPM/pedal/energy states and verify exact fractional propulsion power
and unchanged regen/braking. These are short controlled experiments, not a full
lap, calibrated Tesla behavior, physical wheel validation or hardware SOP.
Local captures are `.local/vehicle-power-validation/comparison/`.

Validation also passed 174 starter tests (including nine new policy/feedback/Tk
tests), 73 BK8500 tests and four setup tests. Native checks passed: 58 new
kernel/protocol/UDP checks plus the existing 18 EV, 15 publisher, nine HUD and
31 keyboard checks. A dashboard SOC-policy trial applied 70% and verified zero
shutdown; a default BK8500 mock run accepted 609 samples/12 cycles with no
power-limit extension or faults and verified OFF/zero. All 39 protected profile,
driver, input and calculation hashes remained identical. Short tests do not
establish full-course, physical G29, Mac build or physical battery safety.
