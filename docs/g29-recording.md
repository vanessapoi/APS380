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
