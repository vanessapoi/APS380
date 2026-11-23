# Optional Battery Bias mock experiment configuration

This is a session-only configuration interface, not a hardware approval or cell
protection profile. An optional pre-run Tk setup form is available; runtime
editing is not implemented. Existing commands,
presets, SOC profiles and physical PSU-only BK8500 behavior are unchanged when
`--mock-test-config` is absent. Physical Battery Bias remains unavailable.

**November 23 extension:** an explicit optional `mock_capability: extended-5a`
and GUI capability selector now support a separately timed 5 A mock envelope.
See [Extended Mock](extended-mock.md) for current limits, timing, validation scope
and launch instructions. Omitted selection retains the prototype behavior below.

## Dashboard Mock Experiment Setup

```powershell
.venv-bench\Scripts\python.exe -B bench\bk8500\live_torcs.py --control-mode battery-bias --device mock --mock-setup --propulsion-feedback --torcs keyboard --keyboard-profile 8s --duration 600
```

This opens **APS380 Dashboard — Mock Experiment Setup** before any receiver,
mock controller, output directory or TORCS process is initialized. The existing
live dashboard is constructed after those components, so a pre-run form avoids
rebuilding active controllers or changing settings after ARM.

The default form starts from the working 20% manual-driving example. You may
also supply `--mock-test-config PATH` to populate it from a saved configuration.
Enter SOC as a percentage (20 means 20%); current fields use amperes and scale
is a dimensionless multiplier. The form converts percent to the existing 0..1
API representation. All other validation/resolution is the same function used
by the JSON loader, not a second configuration system.

1. Edit the fields and select **Validate settings** to see effective values.
2. Invalid/infeasible input remains in the form with an error; nothing starts.
3. **Start mock session** revalidates the latest entries, locks them and closes
   the setup window. TORCS and the original dashboard then open.
4. Enter **ARM** in the controller console and wait for RUNNING before driving.
5. Accepted settings are shown read-only under **Safety & Logs** and recorded
   in the existing reports. Restart with the setup form to change settings.

**Cancel** or closing the setup window exits without starting components or
creating a session directory. The session-duration timer starts after setup,
but still includes subsequent TORCS menus and balancing. GUI use requires
explicit arming; `--auto-arm-mock` and `--no-console` are rejected with
`--mock-setup`. Hardware/PSU-only modes reject this flag. Existing commands
without it behave as before.

## Required range and selected capability

The setup form now continuously shows two distinct ranges:

- **Required steady-state eLoad range**: `[PSU contribution - maximum charge,
  PSU contribution + maximum discharge]`, calculated from the editable inputs.
- **Selected mock eLoad capability**: the separate minimum/maximum entries that
  configure the session. These are never automatically enlarged or overwritten.

These readouts are previews; Start uses the same authoritative JSON/GUI resolver.
Negative required minimum means charging exceeds the source contribution and is
shown explicitly, not clipped to zero. Infeasible normal configurations are
rejected with the required and selected ranges in the error. Accepted reports
record the derived range under `effective.required_eload_range_A`. The derived
operating span is not a new instrument minimum: neutral startup and OFF/zero
shutdown retain their existing behavior. Presets and profile files are unchanged.

For example, entering 5 A discharge, 1 A charge and a 1 A source previews 0..6 A,
but the default prototype capability still rejects discharge above 2 A or load
capacity above 3 A. Explicitly select Extended Mock and configure sufficient
load capacity to use the separately validated extension.

### Historical phase-one extended-range review

| Area | Finding for an illustrative -5/+1 A, 1 A source experiment |
|---|---|
| Steady-state coverage | Requires 0..6 A eLoad capacity. Current 0..3 A mock configuration cannot cover it. |
| Current configuration | Both receiver/scaler and coordinator would need session-local -5/+1 A bounds. Global prototype/hardware limits must not change. |
| Slew | Existing signed-target and branch rates are 0.02 A/s; 0 to -5 A takes at least 250 s. -5 to +1 A takes at least 300 s plus dwell/settling/overhead. |
| Transition timeout | Existing 182 s is insufficient to return -5 A to neutral. Timeout governs neutralization/hold, not the whole subsequent new-direction ramp. The current validator's budget for magnitude 5 A would be 451.14 s; a separately assessed mock-only policy would be needed. No timeout is increased here. |
| Startup | With bias unchanged at 1 A and capability minimum 0 A, startup still balances around 1 A, roughly 50–60 s. Increasing capacity alone need not lengthen that ramp. Never replace the startup minimum with a positive derived operating minimum. |
| Scaling/SOP | Larger capability does not generate 5 A demand. Existing scale 0.06 maps nominal full propulsion to roughly 0.92 A before derating. SOP ceiling and scale must remain independent and consistently used; equations require no redesign. |
| Mock plant | Configurable maximum-current constructors could represent 6 A, but the model does not validate physical source compliance, wire losses, heating or real instrument regulation. |
| Tracking/measurements | Larger sign reversals need longer settling evidence and measured-current checks. Preserve freshness, independent channel validation, tolerances and no-backlog behavior; do not relax them to pass. |
| Shutdown | Existing stop opens source/cell isolation and disables both outputs without waiting for operational slew. Extended software tests must cover extreme endpoints, actuator/feedback failures and unverified shutdown reporting. |

Existing deferred High/Medium safety findings remain unresolved. This review
does not validate an extended mock preset, real battery operation, or a hardware
operating envelope. Phase one did not enable 5 A; the later explicit mock-only
implementation is described in [Extended Mock](extended-mock.md).

## Start the working 20% manual-driving example

From PowerShell in the repository's `APS380` directory:

```powershell
.venv-bench\Scripts\python.exe -B bench\bk8500\live_torcs.py --control-mode battery-bias --device mock --mock-test-config aps380_torcs_starter\profiles\mock_test_20_percent_manual.json --propulsion-feedback --torcs keyboard --keyboard-profile 8s --dashboard --duration 600
```

Start driving in TORCS, enter `ARM` in the controller terminal, then wait for
RUNNING before accelerating. Startup balances branches with the cell isolated;
the 1 A example typically needs 50–60 seconds after ARM. `600` is total session
time, including menus and balancing. `QUIT` while TORCS is still open allows the
existing verified native-zero and mock shutdown procedure to finish. `DISARM`,
`STOP`, explicit fault recovery and `RESET POWER` retain their existing behavior.

The example reproduces the mathematical settings of the existing 20% SOC plus
manual-driving preset. It does not modify those original files or defaults.

## Edit one file before each experiment

For personal experiments, copy the example into `.local/` and edit your copy in
VS Code. Select that copy with `--mock-test-config .local\my-mock-test.json`.
All fields below are required; JSON does not allow comments. Optional
`description` is descriptive text only.

```json
{
  "schema_version": 1,
  "purpose": "battery_bias_mock_experiment",
  "initial_soc_fraction": 0.2,
  "maximum_charge_A": 1.0,
  "maximum_discharge_A": 2.0,
  "sop_discharge_ceiling_A": 0.5,
  "mock_psu_contribution_A": 1.0,
  "eload_min_A": 0.0,
  "eload_max_A": 3.0,
  "experiment_scale": 0.06
}
```

| Field | Meaning and version-1 limits |
|---|---|
| `initial_soc_fraction` | 0..1; `0.2` means 20%, not `20` |
| `maximum_charge_A` | Positive target magnitude, 0..1 A |
| `maximum_discharge_A` | Positive target magnitude, 0..2 A by default; 0..5 A only with explicit Extended Mock; converted to a negative signed bound once |
| `sop_discharge_ceiling_A` | 0..`maximum_discharge_A`; estimator ceiling, not a direct current command |
| `mock_psu_contribution_A` | Imposed synthetic source contribution, 0..1 A; not measured current or PSU CC setting |
| `eload_min_A` / `eload_max_A` | Range within 0..3 A by default, 0..6 A only with explicit Extended Mock; maximum at least 1 A for the configured PSU-bias constraint |
| `experiment_scale` | Fixed TORCS-to-cell experiment multiplier, >0 and <=1; larger values request more cell current for the same pack power |

The default capability supports subsets of the prototype envelope. The explicit
Extended Mock capability supplies the separate bounded extension, not arbitrary
larger-current experiments. The PSU CC setpoint/current limit remains
1 A. Capacity, R0, voltage, temperature, reserves, margins, freshness, timing,
slew and protection settings are not editable in this schema. Capacity stays
3.5 Ah in both scaling and SOC/SOP; synthetic V/T and all model assumptions remain
explicitly unvalidated. No accelerated SOC depletion is introduced.

For source contribution `B`, charge magnitude `C`, discharge magnitude `D`, and
load range `[Lmin,Lmax]`, the loader requires:

```
Lmin <= B <= Lmax         neutral balance
B - C >= Lmin            charging coverage
B + D <= Lmax            discharge coverage
```

For example, reducing the source to 0.2 A while keeping a 1 A charge target is
rejected. Reduce the declared charge bound accordingly for a custom normal test.
The existing baseline preset is still available unchanged for intentional
infeasibility/fault testing. Runtime feasibility always uses fresh measured mock
source current, so an unexpected source drop still faults.

Existing configuration validators also enforce fixed startup and transition
timing requirements. The startup estimate is nominal ramp time plus settling
allowance, not an OS scheduling guarantee. The unchanged runtime timeout and
freshness checks still enforce faults if execution falls behind.

Unknown/missing/duplicate fields, booleans in numeric fields, nonfinite values,
hardware-purpose files and unsupported combinations are rejected before creating
services, sockets, run directories or launching TORCS. Do not combine this option
with `--sop-config`, `--mock-preset`, or `--mock-psu-current-A`; ambiguous commands
are rejected. This option is rejected by the physical and PSU-only CLI paths.

## Data flow and reproducibility

The loader creates a new existing control configuration, a copied SOP model and
a copied scaling configuration for one session. The same control bounds go to
the telemetry scaler and mock coordinator. The shared observer retains measured
mock-current Coulomb Counting. The feedback policy uses the receiver's effective
cell scaling for inverse SOP-to-vehicle mapping. No globals or source profiles
are rewritten.

`mode.json` and final `trial.json` include `mock_test_config`: requested inputs,
explicit overrides, complete effective control/model/scaling settings, source
configuration SHA-256 and base-file hashes. Existing telemetry scaling/current
snapshots and instrument configuration logs remain available. Actual measured
current remains in runtime logs, separate from the imposed source contribution
and configured CC limit. Recordings remain under `.local/battery-bias/` unless
`--output` is supplied.

Physical measurement adapters, calibration, validated battery limits and deferred
Battery Bias safety findings remain separate work. A custom mock configuration
cannot authorize physical operation or replace hardware approvals.

The GUI extension passed 287 starter tests and 110 bench tests with Tk available,
plus three profile tests and 131 native checks. Tests cover form initialization,
units, invalid input, stale validation previews, cancellation/window close,
locking, hardware rejection, read-only live display and unchanged legacy paths.
An automated 70-second native TORCS mock run accepted the actual setup form,
opened the existing dashboard, reached RUNNING and verified both mock shutdown
and the final native-zero acknowledgement. Its maximum applied-current tracking
error was approximately 2.00 mA. Evidence is local under
`.local/mock-test-config/native-setup-gui/`.

## Validation evidence

Python suites passed 279 starter tests and 107 bench tests, including strict
schema checks, original-profile preservation, effective scaler consistency,
hardware-path rejection and default behavior. Three keyboard-profile tests and
131 native executable checks passed. No physical instruments were accessed.

Actual native TORCS mock trials passed for the working example (4204 accepted
samples) and a separate variant with 40% SOC, 0.6/0.2 A discharge/charge bounds,
0.4 A SOP ceiling/source contribution, 0..1.5 A load range and scale 0.12
(2236 samples). Both reached RUNNING, verified mock shutdown and received final
native-zero acknowledgements. Maximum applied-current tracking error was about
2.01 mA in each trial. Saved settings matched receiver settings; SOP was
recalculated from recorded SOC, and native acknowledgements matched sent limits.
Local evidence is under `.local/mock-test-config/` and is excluded from Git.
