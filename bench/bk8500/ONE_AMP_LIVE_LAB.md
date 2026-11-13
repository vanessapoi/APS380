# Supervised PSU-to-BK8500 commissioning up to 1 A

No battery, PSU bias, charging circuit or PSU commands. The binary driver and
legacy `replay.py` remain unchanged (replay still caps at 0.10 A).

## Mapping and unchanged control policies

With the same fixed reference as the original 3 A profile (default 2 A magnitude):

    original_load = clamp(-original_charging_positive_cell_A / reference_A * 3, 0, 3)
    target = original_load * selected_current_cap_A / 3

At a 1 A cap this preserves shape at one-third amplitude, without future samples
or online normalization. Regeneration targets zero; applied current ramps down,
not instantaneously. A cap does not guarantee driving demand reaches that cap.
Use the original profile's recorded reference when comparing another profile.

Selected envelope: 4.5..5.5 V, <=1 A, 5.5 W, 1 Hz, 0.02 A/s, tracking tolerance
0.01 A / 2 s. Telemetry expiry 0.5 s, I/O timeout 0.25 s, cycle budget 0.8 s,
latest-only mailbox, quantized elapsed-ACK slew, fault latch and reset are unchanged.
The existing measured-current guard retains its 2 mA readback tolerance; this is
not authorization for extra physical current. A full 0-to-1 A ramp takes >=50 s.

## Read existing MAX protections without changing them

Set `$bkPort` and `$bkSerial` from the verified device identification; these
are operator-specific values and are intentionally not stored in this guide.

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/off_preflight.py --device hardware --port $bkPort --baud 9600 --address 0 --confirm-ttl --expected-serial $bkSerial --inspect-only
```

This queries identity, measured V/I/P, input status and MAX V/I/P; it sends NO
mode, current, remote, protection or input writes. Start with input OFF. PASS
means inspection succeeded, not that protection suitability has been assessed.

Legacy live mode retains exact MAX matching and its default physical 0.10 A cap.
`--extended-psu-only` permits <=1 A and reads each actual MAX at initialization
and ARM, requiring software maximum <= observed MAX <= separately approved MAX
ceiling. No MAX values or PSU settings are written. Higher actual MAX values are
not automatically suitable just because software commands are capped.

## Separate current-draw approval record

Prepare an ignored `.local/bk8500-live-1A-approved.json` from the existing
approval template and verified equipment records; leave unknown values unknown.
No completed approval record is distributed. Do not overwrite a low-current record.
The full existing approval validator (including electrical checks, wiring rating,
name/reference, source ratings and no-battery attestations) remains active.
Extended current draw additionally requires actual scope recording:

- `extended_psu_only_commissioning_approved: true`.
- `approved_load_max_voltage_V`, `approved_load_max_current_A`,
  `approved_load_max_power_W`: ceilings covering the reviewed, unchanged MAX
  readbacks. CLI ceilings must not exceed these approved ceilings.
- Current/power approval covering the selected stage, up to 1 A / 5.5 W.

Previous successful 0.10 A replay is not validation of 1 A operation. The draft
does not invent new approval identifiers, numeric wiring ratings or extended
scope approval. Until completed from actual records, hardware CLI rejects it
before serial access. OFF-only inspection has no such administrative blockers.

## Mock-only driving

The 30 V / 3 A / 90 W below are explicitly simulated MAX values, not physical
BK8500 readbacks or settings to apply to the real instrument.

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs keyboard --keyboard-profile 5s --dashboard --extended-psu-only --duration 300 --max-current-A 1 --reference-current-A 2 --max-power-W 5.5 --slew-A-per-s 0.02 --tracking-tolerance-A 0.01 --control-hz 1 --protection-voltage-ceiling-V 30 --protection-current-ceiling-A 3 --protection-power-ceiling-W 90
```

Start Race > Practice > New Race. Wait for READY / RECEIVING, then type `ARM`.
Use `--keyboard-profile 3s` or `8s` to select a preserved alternative; G29
bypasses these keyboard presets.
G29 uses `--torcs g29` and preserves its saved profile. Close other TORCS instances.

## Supervised physical command (never auto-armed)

From repository-root interactive PowerShell, only after completing the actual
record and reviewing observed protections:

```powershell
$setup = Get-Content -LiteralPath .local/bk8500-live-1A-approved.json -Raw | ConvertFrom-Json
$stageCurrent = 0.10
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py `
  --device hardware --torcs keyboard --keyboard-profile 5s --dashboard --extended-psu-only `
  --port $bkPort --baud 9600 --address 0 `
  --approval .local/bk8500-live-1A-approved.json --duration 300 `
  --max-current-A $stageCurrent --reference-current-A 2 `
  --voltage-min-V 4.5 --voltage-max-V 5.5 --max-power-W 5.5 `
  --control-hz 1 --slew-A-per-s 0.02 --tracking-tolerance-A 0.01 `
  --protection-voltage-ceiling-V $setup.approved_load_max_voltage_V `
  --protection-current-ceiling-A $setup.approved_load_max_current_A `
  --protection-power-ceiling-W $setup.approved_load_max_power_W
```

This opens graphical TORCS and the original dashboard, starting input OFF.
Review identity and actual protection/zero/voltage checks, then start Practice
and wait for stable RECEIVING. The sole physical ARM path remains the exact
terminal phrase `ARM <approval_reference>`, entered by the operator when ready.
Preflight/freshness is repeated before input ON. There is no physical GUI ARM,
automatic ARM, retry, or enable on RESET.

Start at 0.10 A. After successful tracking review and verified DISARM/QUIT,
restart at 0.25, 0.50 and finally 1.00 A within the recorded scope. Keep the
reference, slew and source settings fixed. Observe the actual demand: modest
driving may not exercise the cap. Record PSU CV behavior manually; load readback
does not establish PSU mode. No software command changes the PSU settings.

`DISARM`: OFF/zero verification, then READY if healthy. `STOP`: latched emergency
fault. `RESET`: verify shutdown and return READY, never re-arm. `QUIT` or Ctrl+C:
attempt OFF/zero and exit. Telemetry loss faults after existing expiry; resumed
data does not clear the latch. If shutdown is unverified, use the established
independent physical OFF/PSU stopping procedure. Software is not a hardware E-stop.

## Display, logs and validation

The existing BK8500 dashboard retains current graphs and MOCK/REAL labels.
Instruments adds original signed/0..3 A demand, mapped target, command, setting
readback, measured I/V/P, tracking error, TORCS source time and data age.

Sessions save `.local/bk8500-live/<timestamp>/`: config/manifest, telemetry,
`instruments/control.jsonl`, summary, `load_tracking.csv`/`.png`, and `trial.json`.
CSV adds `original_eload_demand_A` and `eload_range_scale`; existing timestamp,
latency, measurement and error fields remain. Retained stopped/fault readings
are not live: consult the separate verified shutdown result.

Mock evidence: `.local/bk8500-1A-validation/live-ai/` (65 s), 3,178 valid packets,
no missing/invalid/reordered packets, 62 RUNNING cycles, no faults, commands
0.0011..0.0392 A, peak mock tracking error 0.0473 mA, max cycle 382.4 ms.
Telemetry/control/process/artifacts and OFF/zero shutdown passed. This AI run
had no regenerative cycles; separate deterministic mock tests exercise regen,
rapid reversal, exactly 1 A saturation, ramp-to-zero, communication faults,
protection mismatches and explicit recovery. `interruption-final/` had 15 cycles
then TELEMETRY_EXPIRED, verified OFF/zero and fault-response PASS; normal trial
acceptance correctly remained FAIL.

An initial overlapping AI launch hit a shared-profile file lock. Final runs were
sequential; do not overlap AI launches. This exposed an uninitialized fault-report
timestamp on startup failure; it is fixed and regression-tested. Physical 1 A,
full-range tracking and physical stopping remain separate lab checks. Subsequent
physical results over the actually exercised range are summarized in
[the validation review](../../docs/bk8500-validation.md). No home result
establishes physical safety or real instrument accuracy.
