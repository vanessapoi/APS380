# Autonomous TORCS validation driver

`aps380_ai` drives CG Road Circuit 1 with the configured Tesla-reference car.
It follows the track centerline using look-ahead steering and controls speed
with feedforward plus feedback. It requires no G29 input or training data.

The driver waits for suitable straights and executes this protocol:

1. Accelerate and settle at 30 km/h; hold qualifying conditions for 12 s.
2. Find another suitable straight, settle at 50 km/h, and hold for 12 s.
3. Release the accelerator with no brake command to test regeneration.
4. Use the neutral pedal point and friction brake to stop, isolating friction
   braking from regenerative braking.
5. Remain stopped for 6 s, then resume following the track at 30 km/h.
6. Complete the two-lap race without damage or leaving the road.

The driver aborts on damage or road departure; the runner also has a wall-clock
timeout. The runner checks the recorded native telemetry rather than trusting
the requested targets or the driver's own progress counters. A qualifying hold
requires speed within 0.2 m/s (0.72 km/h) of its target, absolute measured
acceleration no greater than 0.15 m/s², lateral speed below 0.3 m/s, no contact,
and at least 20 m of straight road ahead. A sample gap over 50 ms breaks the
hold. Separate short holds are never added together. A 12-second controller
target leaves margin for the independent 10-second acceptance gate.

## Run automatically

Close TORCS before the first build so the simulator DLL can be replaced.
From PowerShell in the repository root:

```powershell
.\aps380_torcs_starter\.venv\Scripts\python.exe scripts\run_tesla_ai.py
```

This builds the Release/x64 simulator and standalone `aps380_ai` project,
configures an isolated `.local/tesla-ai-profile`, and runs two headless races.
The manual G29 profile is preserved. The standalone driver is built by this
runner; it does not require editing the main Visual Studio solution.
Once built, use `--skip-build` to repeat tests. Use `--runs N` for 1–10 runs;
one run alone is not a repeatability assessment.

Each batch is saved under
`aps380_torcs_starter/output/tesla_ai_validation/YYYYMMDD_HHMMSS/` with:

- `report.md` and `summary.json`: pass/fail gates, speed-hold durations, energy
  repeatability, and profile/driver/binary hashes.
- Each `run_NN` folder: driver command trace, native EV CSV, effective car XML,
  frozen vehicle profile, TORCS log and protocol plot.
- `analysis/` and `validation/`: normal pack analysis and readiness/sensitivity
  reports, using the same captured data and settings.

## Watch the driver

After running the command above at least once:

```powershell
.\scripts\launch_tesla_ai.ps1
```

Choose **Race > Practice > New Race/Start Race**. The isolated Practice profile
selects the APS380 validation driver, the custom EV, and CG Road Circuit 1.
The AI controls the car; a wheel is unnecessary. Visible sessions create
separate driver and native EV telemetry files under `runtime/telemetry`.
Use `scripts/launch_tesla.ps1` to return to the human G29 experiment.

## Motor-control refinement: profile v2

The v1 model applied minimum positive motor torque immediately above a 5%
pedal threshold, while producing lift-off regeneration below it. That jump
could prevent low-load steady driving. Profile v2 introduces a continuous
neutral point: positive torque rises continuously above neutral, and lift-off
torque grows continuously as the pedal is released below neutral. Full pedal
and fully released limits are preserved. The model now also enforces available
battery energy at shaft speeds below 1 rad/s. Regression checks cover these
boundaries. This is a reduced-order control law, not Tesla firmware.

The profile ID changed to v2. Older human recordings keep their frozen v1
profiles, raw data and analyses. Do not substitute the new profile when
processing those older files.

## Validation scope

The completed autonomous trials verify course following, steady driving,
regenerative and friction-braking separation, stopping, internal battery
equations and repeatability for the configured simulator. The unit checks
also cover motor/power and battery-energy boundaries. These gates do not
validate a real Tesla's efficiency maps, usable capacity, BMS/temperature
behavior, steering/tire response, or pedal calibration. Independent measurements
for the same vehicle variant are still required for those claims.
