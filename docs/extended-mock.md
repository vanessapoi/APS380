# Extended Mock capability — simulation only

The optional `extended-5a` capability is separate from the unchanged prototype,
baseline and manual-driving presets. It is not a BK8500 configuration or battery
operating approval. Physical Battery Bias is still unavailable; all deferred
safety findings remain unresolved.

| Setting | Prototype (default) | Extended MOCK ONLY |
|---|---:|---:|
| Maximum discharge magnitude | 2 A | 5 A |
| Maximum charge magnitude | 1 A | 1 A, independently configurable |
| Maximum selectable eLoad capability | 3 A | 6 A |
| PSU configured CC limit | 1 A | 1 A |
| Imposed source contribution | 0..1 A | 0..1 A |
| Signed-target / branch slew | 0.02 A/s | 0.02 A/s |
| Startup READY timeout | 90 s | 90 s |
| Transition timeout | Existing 182 s | Derived by existing budget formula, never below 182 s; 452 s at full range |
| Measurement expiry / maximum observer gap | Existing 0.2 / 0.5 s policies | Unchanged |

## GUI operation

From PowerShell in `APS380`:

```powershell
.venv-bench\Scripts\python.exe -B bench\bk8500\live_torcs.py --control-mode battery-bias --device mock --mock-setup --propulsion-feedback --torcs keyboard --keyboard-profile 8s --duration 1800
```

1. Select **Extended MOCK ONLY (5 A discharge / 6 A load)** in the capability box.
   Selection does not change the other fields.
2. Set discharge magnitude to **5**, charge to **1**, and imposed source to **1**.
3. Set selected eLoad capability to **0..6 A**. The form calculates that same
   required span, but never silently increases the selected capability.
4. Choose initial SOC, SOP ceiling and scale independently. They are not raised
   when selecting Extended Mock or increasing the target limit.
5. Validate and inspect the selected capability and effective timeout. Start,
   enter `ARM`, and wait approximately 50–60 seconds for RUNNING.
6. Use `QUIT` while TORCS remains open to verify native-zero shutdown. Existing
   DISARM, STOP, explicit fault recovery and power-reset controls are unchanged.

To populate the form with the new example, additionally supply:

```powershell
--mock-test-config aps380_torcs_starter\profiles\mock_test_extended_5a.json
```

The example retains **20% SOC, 0.5 A SOP ceiling and scale 0.06**. It grants wider
mock capability; it does not request 5 A. Existing vehicle demand, SOP derating,
current scaling, slew and SOC constraints determine what is actually measured.
Retaining scale 0.06 maps nominal full propulsion to approximately 0.92 A before
derating. No depletion accelerator or new SOC/power equation is introduced.

JSON uses the same schema with optional `"mock_capability": "extended-5a"`.
Without that field, prototype limits and timing are unchanged. The validator
rejects unknown capabilities and infeasible ranges, including charging beyond
measured/imposed source capability. The selected capability, labels, effective
timing and original/limited/applied/measured currents remain separately recorded.

## Timing policy

At 0.02 A/s, neutral to -5 A requires at least 250 seconds, and -5 to +1 A at least
300 seconds plus neutral dwell, response and scheduling overhead. The transition
state machine times the return-to-neutral/hold phase; the later new-direction
ramp is distinct. The mock worker conservatively caps each slew step at one
nominal control period, so wall time can exceed these nominal values.

Only an explicitly selected extended session requests an existing `ControlConfig`
budget calculation with the selected bounds. Its conservative minimum is:

```
steps = ceil(max(discharge, charge) * control_hz / slew)
minimum = (steps + dwell_steps + 2) * (1/control_hz + 4*io_timeout) + settling_timeout
timeout = max(baseline_timeout, floor(minimum) + 1)
```

At 5 A this gives minimum **451.14 s**, timeout **452 s**. This bounds the
instrument model's conservative transaction budget; it is not a promise about
unbounded OS delays. Real timeout violations still fault. No user timeout field,
global timeout increase, physical slew change or relaxed tracking/freshness
threshold is added. Startup still balances around the same 1 A source, not 6 A.

## Validation and limits of evidence

```powershell
.venv-bench\Scripts\python.exe -B scripts\validate_extended_mock.py --output .local\extended-mock\my-validation
```

This runs the existing mock plant over full -5/+1 A endpoints, repeated reversals
and neutral, using a deterministic virtual clock. Instrument time and current
slew are not shortened; no such virtual-clock acceleration is applied to normal
driving. Independent re-integration checks that SOC uses measured mock cell
current and that OCV/SOP update. Separate fault-injection tests cover source
shortfall, missing measurements, timeout enforcement and isolation/output shutdown.

The script then uses actual native TORCS and the real human-driver test fixture,
with identical keyboard inputs delayed until neutral startup completes. It checks
acceleration, lift-off regeneration demand, native command acknowledgements,
reduced actual motor output for reduced SOP, and verified native-zero/mock
shutdown. The default fixture behavior and production G29/keyboard code are
unchanged. The delay exists only in the separately compiled automated test DLL.

Full 5 A current endpoints are demonstrated in the deterministic plant scenario;
the short native driving traces are not claimed to reach measured 5 A. Both test
types are software-only and do not validate a real cell, PSU compliance, thermal
behavior, wiring losses, sensors, PCB protection or physical isolation.

### Recorded validation results

297 starter tests, 110 bench tests, three keyboard-profile tests and 131 native
executable checks passed. The unchanged undelayed keyboard trial also passed
with 702 samples. G29 profile fingerprints were preserved.

The full plant scenario reached -5.000 A and +1.000 A cell readback and 6.000 A
load readback, with maximum measured-versus-applied error approximately 2.014 mA.
Independently counted SOC changed from 80% to 58.4944%; OCV/SOP evolved accordingly.
Source shortfall, sensor loss and forced transition expiry still latched faults
and verified mock isolation/output shutdown.

The two real-time native fixture runs had 3708/3704 matched acknowledgements.
For identical inputs in seconds 67..68, the higher-SOP case delivered peak motor
power 3588.9 W and speed 0.7243 m/s at 68 s; the reduced-SOP case delivered
1.36 W and 0.2400 m/s. Both verified native-zero and mock shutdown. The higher
case recorded 46 lift-off samples requesting net charging; the very-low-power
case had no net charging request during lift-off and is not claimed to do so.
Both trials completed normally. The initial analysis incorrectly required net
lift-off charging in both cases; that overbroad assertion was corrected and the
completed logs were independently reanalyzed, without changing controller safety.

Evidence: `.local/extended-mock/final-validation/summary.json`, `full_range.csv`,
`full_range.png`, `native_comparison.png` and per-case native/instrument logs.
Use `--analyze-existing` with the same output folder to recheck completed logs
without launching TORCS. Short native traces measured much smaller currents;
they are not a real-time 5 A driving demonstration.
