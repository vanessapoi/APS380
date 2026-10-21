# Tesla Model 3 RWD experiment

This experiment targets a 2019 Standard Range Plus RWD reference with a 3D1
motor. It is a reduced-order model, **not a validated Tesla digital twin**.
The old G29 CSV has no car identity or pack-energy measurements and cannot
be relabeled as a Tesla recording. A new drive is required.

## Evidence and outstanding calibration

The single profile in
`aps380_torcs_starter/profiles/tesla_model3_rwd.json` drives both TORCS setup
and Python validation. It separates published values from reference choices
and unvalidated settings, with source links and limitations.

Tesla's [motor specifications](https://www.tesla.cn/ownersmanual/2017_2023_model3/en_cn/GUID-E414862C-CFA1-4A0B-9548-BE21C32CAA58.html)
list a 3D1 rating of 202 kW and 404 Nm, and state that the motor varies by
manufacture date. The precise year/trim/motor pairing still needs confirmation;
these ratings do not supply a complete torque or efficiency map.

Tesla's [subsystem specifications](https://www.tesla.com/ownersmanual/2017_2023_model3/en_us/GUID-E414862C-CFA1-4A0B-9548-BE21C32CAA58.html)
document the single-speed 9:1 reduction, 355 V nominal Li-ion pack, and
320/335 mm non-Performance brake rotors. The motor table's 320 V entry is
not used as the nominal battery voltage. Tesla also documents
[body dimensions](https://www.tesla.com/ownersmanual/2017_2023_model3/en_us/GUID-56562137-FC31-4110-A13C-9A9FC6657BF0.html).

The 1,611 kg curb mass plus 75 kg driver, 18-inch tire choice, 50 kWh working
energy capacity, constant efficiencies, auxiliary load, regeneration limits,
road-load/handling values, and initial 80% SOC are **not validated for a
particular physical car**. SOC is an energy fraction with constant nominal
voltage; there is no electrochemical, temperature, or OEM BMS model. No
thermal derating or measured efficiency map is available. Motor losses at
zero speed are not represented by the constant-efficiency approximation.

The visible body is the existing GPL TORCS `kc-2000gt` asset, identified in the
car selection name as a proxy. Its graphics are not a Tesla model. Dimensions,
motor, gearing, and other configured parameters are replaced for the experiment;
the donor suspension/tire solver and remaining template parameters are not
a certified Tesla handling model. Engine audio is replaced with silence;
road and tire sounds remain.

## Simulator behavior

The EV branch is opt-in via `Electric Powertrain/enabled=yes`; existing
combustion cars retain the original engine path. The experimental EV uses:

- A torque/power-limited electric motor, with no combustion idle or fuel burn.
- One permanently coupled forward gear; reverse selection is disabled for
  this experiment. The generic simulator retains a 0.001 kg fuel sentinel,
  compensated in configured base mass, for compatibility with its race logic.
- Lift-off regeneration, fading below 2 m/s, with a shaft power cap. The brake
  pedal actuates friction brakes. This is an explicit simplified control law,
  not Tesla's actual firmware or a claim to reproduce its pedal calibration.
- A brake override that prevents positive motor torque with significant brake.
- Physics-step electrical energy integration, pack depletion/full-charge
  bounds, and signed shaft work for a vehicle rolling backwards.

Regeneration is derived from motor torque and angular velocity. An impact
can reduce speed without being counted as recovered battery energy. These
are simulated electrical quantities, not measurements from a physical Tesla.

Each race creates a new `runtime/telemetry/aps380_ev_N_carM.csv` and effective
car-parameter XML. An adjacent profile JSON is addressed by ID and content
hash. CSV fields include longitudinal/lateral/vertical speed, damage, latched
collision flags, motor torque/speed/power, pack power/current/energy, SOC, and
cumulative discharge/recovery. The older four-column human recorder remains
available, but it is not the input to this EV analysis.

## Setup and driving

From the repository root, after building Release/x64:

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe scripts\configure_tesla.py
.\scripts\launch_tesla.ps1
```

Setup copies the current calibrated G29 preferences into `.local/tesla-profile`
on first use. It configures human player 1 with automatic transmission, no
auto-reverse, ABS/ASR enabled, and pro skill; Practice has one human driver,
CG Road Circuit 1, no fuel consumption or tire wear, and damage enabled.
The existing Windows user profile and stock car definitions are preserved.
Generated car assets live under the ignored runtime directory and can be
recreated with the setup script. A new permissive EV category avoids the
combustion category's idle/gear limits.

The launcher sets `APS380_TORCS_PROFILE` to the workspace profile; opening
`wtorcs.exe` directly uses the ordinary Windows profile instead.
Choose **Race > Practice**, then start with the configured human driver.
For initial checks, accelerate gently to 20–40 km/h, hold near-steady speed
for at least 10 seconds on a straight, release the accelerator, and then
test friction braking. Avoid impacts; steering is still required at corners.
Finish or pause the race before processing so the file is stable.

```powershell
.\scripts\process_tesla.ps1
```

Processing selects the newest native EV CSV and its captured profile. It
rejects a mismatched car/profile, missing effective parameter XML, invalid
timestamps or numbers, inconsistent electrical quantities, and broken energy
counters. It audits the effective mass, reduction and electrical settings.
It does not clamp or scale to an 18650 cell. Outputs are vehicle-level pack
profiles and energy summaries, with collision/lateral-motion/speed-jump flags.
Energy totals use cumulative physics-step counters, avoiding sampling losses.
Old illustrative cell limits remain confined to the older offline workflow.

## Validation completed

- Release/x64 native simulator and Windows launcher built successfully.
- 14 standalone EV kernel checks cover torque/power limits, positive and
  negative shaft work, battery boundaries, neutral, brake override and low-speed
  regeneration. 10 existing combustion-engine tests pass.
- 25 Python tests pass, including native profile identity, power/current/SOC
  consistency, energy conservation, counter reset detection, and collision
  deceleration without invented recovery.
- A headless AI race created 3,302 native samples over 66.02 seconds; the
  Python processor accepted their profile, effective configuration and energy
  accounting. This AI drive had impacts and lateral motion and is an integration
  smoke test, not performance calibration or human G29 data.

To establish real-car fidelity, obtain a year/trim-specific homologation or
VIN-backed specification and measured coastdown, acceleration, pack-voltage,
efficiency, and regenerative-limit data. Match the controlled TORCS drive to
those observations before describing the result as validated Tesla behavior.
