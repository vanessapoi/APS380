# Separate keyboard and G29 driving

Run commands in PowerShell from the repository root, `APS380`. These commands
operate TORCS and optional in-memory instruments only.

## Keyboard: gradual pedals

```powershell
& .\scripts\launch_tesla_keyboard.ps1 -NoDesktop
```

This builds the changed human driver and existing simulator components, prepares
`.local/tesla-keyboard-profile`, and opens graphical TORCS. Start **Race > Practice
> New Race**, using the prepared Tesla human driver. Up/Down arrows operate
throttle/brake; Left/Right arrows retain the existing keyboard steering algorithm.
The automatic transmission, ABS and ASR remain as configured by the Tesla setup.
They can affect the final applied pedal values after the input ramp.

This launch hides the separate Python dashboard to work even when Tk is missing;
TORCS graphics and its telemetry/HUD remain enabled. Omit `-NoDesktop` to try the
existing dashboard if Tk works in your Python environment. This task did not fix
or validate the missing `init.tcl` installation. Close TORCS to stop the trial.
The launcher has a one-hour trial limit.

To include the original mock PSU/eLoad coordinator:

```powershell
& .\scripts\launch_tesla_keyboard.ps1 -NoDesktop -MockInstruments -MockArm
```

`-MockArm` explicitly arms only in-memory mock instruments. Default launch does
not arm instruments. After the first build, `-SkipBuild` can skip recompilation.

The equivalent Python command exposes the usual trial/logging options:

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B scripts/run_tesla_live.py --mode keyboard --duration 600 --no-ui --mock-instruments --mock-arm
```

## G29: existing configuration

```powershell
& .\scripts\launch_tesla.ps1
```

This is the existing graphical launcher, unchanged. It opens
`.local/tesla-profile`, retaining saved G29 axes, calibration and mappings. No
keyboard preparation runs in this path. The existing `--mode g29` live launcher
and its original setup behavior are also unchanged.

Keyboard preparation reads a copy of the existing Tesla profile and writes its
own directory only. The default `%LOCALAPPDATA%\torcs` settings are also untouched.
Do not recalibrate the wheel in the keyboard profile expecting those changes to
update G29: these are independent copies. Do not run two simulators at once.

## Adjust one configuration file

Edit `aps380_torcs_starter/profiles/keyboard_driving.json`, then relaunch keyboard
mode. Changes are applied at profile preparation and read at the new race;
editing the JSON during a race does not update active controls.

| Setting | Default fraction/s | Full-range time |
|---|---:|---:|
| `throttle_rise_per_s` | 0.3333333333333333 | 3 s from 0 to 100% |
| `throttle_fall_per_s` | 0.6666666666666666 | 1.5 s from 100 to 0% |
| `brake_rise_per_s` | 1.0 | 1 s from 0 to 100% |
| `brake_fall_per_s` | 2.0 | 0.5 s from 100 to 0% |

Rates use simulation time and must be finite, positive, at most 100. Larger
values respond faster. Release ramps deliberately retain some throttle or brake
briefly after the key is released; account for that while driving. Pedal values
are clamped to 0..1. Partial presses/releases reverse smoothly from the current
value. Pausing does not accumulate a wall-clock ramp; a new race resets it.

TORCS previously applied a hard-coded 10 fractions/s rise for digital pedals
after the first race second, with immediate release. There are no existing
configuration fields for independent rise/fall rates. The source addition
therefore requires the profile flag `aps380 keyboard pedal ramp=yes` **and** a
keyboard-mapped pedal. Analog axes, joystick/mouse buttons and non-opted-in
profiles bypass it and retain their original code paths. Steering is untouched.
Vehicle physics, signed current scaling, telemetry protocol and instrument
control/slew algorithms are unchanged.

## Standalone BK8500 mock controller

After building the human module with the keyboard launcher above, this optional
runner also accepts the separate profile:

```powershell
& .\.venv-bench\Scripts\python.exe -B bench/bk8500/live_torcs.py --device mock --torcs keyboard --duration 600 --reference-current-A 0.05
```

Start the race and type `ARM` in its terminal once READY/RECEIVING. `DISARM` and
`QUIT` stop mock current. This does not open a serial port. Its original G29 and
AI options and instrument-control calculations are unchanged.

The original launcher saves normal telemetry, profiles, manifest and mock logs
under `.local/live-trials/`. Keyboard trials additionally save
`keyboard_driving.json` and hash the keyboard-specific sources/human binary.
The standalone runner retains its normal `.local/bk8500-live/` outputs.

## Validation -- October 29, 2026

All tests used mock instruments. The saved workspace G29 and default TORCS
profiles were hashed before/after: **34 files byte-for-byte unchanged**.

- Existing Python suite: **163 passed, 1 Tk test skipped** (`init.tcl` missing).
- Bench suite: **40 passed**; existing portable setup: **2 passed**.
- New profile/configuration checks: **2 passed**.
- Native regression: **18 EV + 15 publisher + 9 HUD passed**.
- New native pedal checks: **31 passed**, including press/release, alternative
  rates, clamps, timestep independence and input-type/opt-in gates.
- Six actual TORCS headless trials with the final 3 s / 1.5 s accelerator settings:
  **4,222 valid samples total**, zero missing
  or invalid packets, no coordinator faults, and verified mock shutdown.
  Five trials used the original prototype; one used the standalone controller.
- The analog opt-out and opt-in trials had **673 matching input samples** with
  identical final applied throttle and brake (tolerance 1e-9).

The scripted comparison runs legacy keyboard, new keyboard, a slower JSON
setting, analog bypass off/on, and the standalone mock load. It uses a separate
test-only robot DLL compiling the actual human source. Headless TORCS rejects
type=human, so the fixture is declared type=robot, substitutes headless GUI/input
registration, and supplies the actual robot callback interval to the human code.
No operating-system key events or physical input polling are performed. The
fixture DLL is removed from the runtime after validation; `human.dll` is never
replaced by the fixture.

```powershell
& .\aps380_torcs_starter\.venv\Scripts\python.exe -B scripts/validate_keyboard.py
```

Final pre-commit evidence is in `.local/keyboard-final-validation/integration/`, including
`comparison.png`, `summary.json`, source/binary hashes, exact input traces,
telemetry and instrument reports. The plot shows gradual applied pedal edges
and the resulting signed current-demand curves. Before/after speeds differ
because the pedal histories differ; it is not a matched-speed electrical test.
For this short script, the largest adjacent current-demand change fell from
0.730 A to 0.0129 A; peak speed also changed from 11.22 to 4.78 m/s, so this is
illustrative behavior rather than a general current-smoothing guarantee.
Maximum prototype measured-versus-applied tracking error was about 20.13 mA;
standalone error was 1.632 mA, within their unchanged mock policies.

An initial test-fixture attempt was rejected as a human console driver. The next
attempt exposed the human/robot callback-interval difference; the fixture was
corrected, then all six trials and comparison assertions passed. Those earlier
captures remain local and are not reported as successful comparisons.

The operator reports successful manual keyboard/GUI testing with the final
settings. Post-change manual G29 driving, Mac native compilation of the changed
human module, and the skipped Tk widget test remain unverified here.
Automated fake-axis results establish software bypass behavior,
not physical wheel calibration or hardware safety. No instruments, physics,
battery mapping or instrument slew policy were changed or physically exercised.
