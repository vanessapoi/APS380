# G29 human-driver telemetry

The TORCS human driver records simulation time (seconds), total vehicle speed
(m/s), and final throttle and brake commands to CSV at approximately 50 Hz.
Both automatic and manual transmission callbacks record after control updates.
Countdown samples are skipped. Files are flushed after every row and closed at
race end or driver shutdown.

Launch the Release/x64 build with the working directory set to
`external/torcs-1.3.10/runtime`, then start Practice with a human player.
Player 1 writes `aps380_g29_telemetry.csv` in that directory; other human
players use `aps380_g29_telemetry_playerN.csv`.
**Each new race replaces that player's previous recording.** Copy recordings
into the Python project's data folder before starting another session.

## First recorded profile

`aps380_torcs_starter/data/g29_20261020_200536.csv` contains 4,293 samples over
94.612 seconds with strictly increasing timestamps. Braking is present in
379 samples above 0.05, with a maximum command of 0.871092. Maximum speed is
44.74675 m/s (161.09 km/h).

The recording still contains extreme speed differences, including a minimum
derived acceleration of approximately -60.594 m/s². Collision/reset attribution
cannot be established from these four columns. The raw data is preserved;
these events need investigation or clean-segment selection before quantitative
interpretation of power and energy.

From `aps380_torcs_starter`, reproduce the profile with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py --input data/g29_20261020_200536.csv --config config_torcs.json --output-dir output/g29_20261020_200536
```

The output folder contains `current_profile.csv`, `current_profile.png`, and
`model_parameters.json`. The configured offline limits clamp the command to
-1 A through +4 A; 1,787 samples (41.6%) are saturated. These are model
demonstration limits, not validated hardware operating limits.

Validation: the modified human module built successfully in Release/x64 and
was copied into the runtime driver folder. The recording passed the existing
Python reader and model processing, and the resulting plot was inspected.

## Screening and comparison

Run `.\.venv\Scripts\python.exe analyze_g29.py` from the Python project to
reproduce `output/g29_screening/`. The script audits intervals with absolute
derived acceleration above 20 m/s² and groups adjacent flagged intervals.
This diagnostic threshold does not identify collisions or validate vehicle
physics. The largest spike occurs at 36.674 s with zero brake command;
many later extreme decelerations coincide with braking.

Manual inspection selected 44.614–53.594 s (450 samples; original CSV rows
2049–2498) as a lower-speed candidate containing acceleration, brief
near-steady motion, and braking to rest. The extraction preserves contiguous
source samples, timestamps, and numeric strings; no interpolation, smoothing,
or removal of interior rows is applied. The script verifies the extracted
data against the original and records a source SHA-256 hash in `audit.json`.

| Metric | Full recording | Screened candidate |
| --- | --- | --- |
| Duration | 94.612 s | 8.980 s |
| Acceleration range | -60.594 to +13.465 m/s² | -15.076 to +7.966 m/s² |
| Peak requested cell current | 15.826 A | 1.880 A |
| Minimum requested cell current | -1.548 A | -1.548 A |
| Samples clipped by configured limits | 41.63% | 3.56% |

Selection changes the driving conditions and duration: lower clipping is not
proof of improved model accuracy. The candidate still brakes strongly, its
near-steady phase is short, and total speed includes lateral/vertical motion
whereas the model assumes longitudinal motion. A controlled straight-line
test with gentler braking remains necessary for target-EV interpretation.
The model's regeneration estimate is not measured TORCS battery energy.

Outputs include the unchanged segment CSV, regenerated current profile,
model parameters, flagged-event CSV, comparison CSV, provenance audit, and
`screening.png` showing full-recording context and the selected driving inputs.
The plot was inspected and all 19 existing Python tests passed.
