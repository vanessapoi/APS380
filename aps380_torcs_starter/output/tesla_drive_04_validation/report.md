# Tesla drive 04: verification and calibration readiness

The recording passes the implemented profile and energy checks. It does not
establish real-Tesla accuracy. No physical parameters were fitted or changed.

- Samples: 4541; duration: 90.80 s.
- Native net pack energy: 385.287 Wh.
- Maximum interval energy closure error: 2.01e-09 Wh.
- Maximum configured electrical-equation residual: 0.00188 W.
- Post-startup contact samples: 0; final damage: 0.
- Longest near-steady interval: 0.40 s; target: 10 s.
- Median motor speed / nominal rolling-speed ratio: 1.0213.

## What is established

The saved simulator configuration matches this recording's profile. Torque and
power obey the configured caps. Pack current, power, energy counters and SOC
are internally consistent. Gearing and nominal tire dimensions produce a
reasonable speed ratio; its departure from 1 may include tire slip/deformation.
It is not an independently measured effective rolling radius.

## What remains uncalibrated

- No independent real-car speed/pack power/voltage measurements for this exact year, trim and motor.
- No verified usable capacity or efficiency/regen maps for this exact configuration.
- Simulation-generated SOC and pack power reproduce configured equations; fitting them cannot validate those assumptions.
- The drive contains no qualifying 10-second near-steady interval.
- Elevation/grade and wheel-level forces are absent from this recording; road load cannot be uniquely identified.

## Sensitivity interpretation

`parameter_sensitivity.csv` holds one-at-a-time scenarios for efficiency,
auxiliaries, nominal voltage and assumed working capacity. These are chosen
stress-test values, not measured bounds or confidence intervals. They replay
the same sampled shaft-work trace, without rerunning vehicle physics or BMS
limits. The difference between configured replay and native energy counters
is reported in `audit.json` to expose sampling approximation.

Changing capacity affects SOC change, not consumed energy in this replay;
changing nominal voltage affects current, not consumed energy. Mass, tire,
road-load, regeneration-control and power-limit changes require new simulator
runs. Do not select a parameter merely because its output looks smoother.

## Next controlled simulator protocol

On a straight, accelerate gently to 30 km/h, hold speed for at least 10 s,
release the accelerator and coast under the current lift-off control, then
brake to rest. Repeat at 50 km/h where track conditions allow. Start from a
known SOC, avoid impacts, and record the same scenario for comparison.
This supports simulator repeatability; physical calibration additionally needs
matched independent real-car or laboratory measurements and track grade.

The previous description of this recording as clean remains correct for
impact/speed-jump screening; it was not evidence of a sustained cruise phase
or of externally validated Tesla behavior.
