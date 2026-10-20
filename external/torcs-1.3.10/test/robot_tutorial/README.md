# Tutorial racing-controller regression checks

## Maintenance entry points

Run from the TORCS source root (the directory containing `src/`, `test/` and `export/`).
Python 3.10+ is required. Documentation checks use Doxygen 1.14.
Native runners require a prepared TORCS build for their specific OS (see below).
Browser checks require Node.js 20 or newer and Playwright Chromium.
The paths below are placeholders; supply paths for your checkout/installation.
Create an artifact parent outside the source tree first. Each runner creates a
fresh child there and reports its location. Never use Python `-O`: assertions are
part of these checks.

| Entry point | Platform / purpose |
| --- | --- |
| `check_documentation.py` | Documentation, archives, snapshots and manifests; `--build` is Linux-only |
| `check_windows.py` | Windows Release/x64 documented builds, deployment and headless smoke races |
| `run_races.py` | Linux instrumented race/physics scenarios |
| `check_racing_controls.py` | Linux C++ control/parser instrumentation |
| `test_verification.py` | Portable verification-infrastructure tests |

Native entry points reject the wrong OS. `maintenance.py` owns shared reporting,
command capture, hashes and archive checks; `race_support.py` owns portable race
XML, driver ordering and result parsing. Neither selects an OS or runtime layout.
Both race runners reuse `scenarios.json`; Windows selects supported smoke cases
and has its own result checks rather than claiming Linux telemetry coverage.

### Windows builds, deployment and smoke races

Prepare a **Release/x64** TORCS build and game data, with VS2022 C++ tools,
MSBuild, exported headers/libraries and matching `runtime/wtorcs.exe`. Run the
game and a race once to initialize the Windows profile. It must use `track` /
`simuv2` and have no local `drivers/tutorial*` overrides for tested modules.
The runner checks these prerequisites and does not change user settings.

From the source root, using an existing artifact parent:

```powershell
python -B test/robot_tutorial/check_windows.py --work-root C:/artifacts
```

In this workspace, `conda run --no-capture-output -n torcs-tracktools python -B`
can replace `python -B`. `--runtime <path>` selects another matching Release/x64
runtime; build dependencies still come from this checkout. `--timeout 180`
sets the per-race timeout. `--checks build`, `--checks deployment`, and
`--checks races` select subsets; default `all` runs everything. Every mode builds
fresh DLLs and never reuses binaries from an earlier verification run.

Coverage:
- Executes PowerShell blocks selected by section anchor from `windows.md`:
  VS discovery, Chapters 2–6, Appendices A–C, Chapter 5 helper assembly and its
  separate pace module. Requires zero build warnings/errors.
- Reuses exact-content/manifest checks for all four downloads.
- Checks installed XML/textures/notices; deletes private fixture assets and
  proves A/B/C's up-to-date builds reinstall them without compilation/relinking.
  Also executes the documented standalone asset-copy commands.
- Runs eleven native headless `g-track-1` cases: Chapter 2 recovery; Chapters 3/4;
  Chapter 5 with pace; Chapter 6 baseline and rebuilt pit demonstration; A/B;
  C Red/Teal/both. Requires fresh results, correct identities, primary-driver lap
  completion and finite positive motion. Later chapters require zero recorded
  damage/penalty; Chapter 2's deliberate mistake is exempt. The demo must record
  exactly one pit stop; other cases must record none.

Isolation and evidence:
- Sources, build outputs, installed tutorial assets and copied executable/DLLs
  live in a fresh artifact child. Existing working copies/installed drivers are
  untouched. Directory junctions reference build dependencies and common game
  data/modules for reading only; no symlink privilege/Developer Mode is needed.
- Windows `wtorcs.exe` has no Linux-style `-l/-L/-D` overrides. It reads the
  existing profile. Each race uses a fresh unique results-directory junction
  into the artifact tree, removed in `finally`. No existing settings/results
  are overwritten. An interrupted Python process can leave its uniquely named
  `win-...` junction behind.
- `report.json`, executed `.ps1` blocks, logs, source/binary/config hashes,
  scenario definitions and fresh race XML/results are retained on success or
  failure. Failed checks exit nonzero; unrequested stages are labeled explicitly.
- Compiler scratch has its own directory, separate from retained build outputs,
  avoiding MSBuild's temporary-output warning (MSB8029).

Chapter 1, GUI rendering/menu reload, Debug/Win32, all-track performance and Linux
instrumented traffic/pit stress experiments are outside this runner.

### Verification infrastructure tests

```text
python -B test/robot_tutorial/test_verification.py
```

Runs on either OS without building TORCS. Covers race ordering/configuration,
result identity, failure/timeout evidence and negative Windows result checks
(missing drivers/laps, damage, penalties, nonfinite values, missing pit stop).

### Documentation and builds

```text
python3 -B test/robot_tutorial/check_documentation.py --work-root <artifacts> --build
```

Omit `--build` for documentation-only work. It still performs fresh Doxygen,
source/package/snapshot/figure checks and Windows project inspection. `--build`
adds eleven Linux builds in copied directories, without installing modules.
Generated HTML and logs are in the reported child directory; existing installed
documentation and old results are never used as runtime evidence.

### Browser checks

In `test/robot_tutorial/browser/`:

```bash
npm ci
npx playwright install chromium
```

Then from the TORCS source root:

```text
node test/robot_tutorial/browser/check.cjs --html <fresh-html> --work-root <artifacts>
```

This checks all tutorial pages, offline math and existing API formulas, real
clipboard contents, `file://` buttons, navigation, image loading and SVG bounds.
`package-lock.json` pins the browser tooling. `node_modules` is ignored by Git.

### Linux native race scenarios

```text
python3 -B test/robot_tutorial/run_races.py --binary <torcs-bin> --lib-root <lib-root> --data-root <data-root> --work-root <artifacts>
```

`lib-root` contains `drivers/`, `modules/` and `lib/`; `data-root` contains `cars/`, `tracks/`
and `drivers/`. The binary, libraries and data must belong to a compatible build.
Native scenarios select `simuv2`. Other physics modules need separate validation.
The default runs `ch6-g1`, `ch6-e2` and `pit-fuel`. Use repeated `--scenario <name>` for
focused checks, or `--scenario all`. Exact names appear in `--help` and [scenarios.json](scenarios.json);
the groups below are abbreviated:

- `intro-driving`; `ch3-g1/e2`; `ch4-g1/e2`; `ch5-pace`; `ch6-g1/e2`.
- `pit-demo/fuel/pace/left/wrap/none/last/occupied`; `appendix-a/b`.
- `multi-red/teal/pair/reversed/shared/strategy`; `bt2-stress`.
- `motion-pass-left/right` and `motion-return-left/right`.

The four motion cases are three-second physical experiments with seeded vehicle
states on a private flat track. They verify cancelled in-flight manoeuvres,
steering response, lateral clearance and actual drift on both sides. They require
the `simuv2` private headers to match the loaded `simuv2` binary. A tagged fixture
completion message establishes success; these cases do not claim race completion.

The runner builds private instrumented modules and creates independent library,
data and profile roots per scenario. It sets cwd to the chosen data root and
uses explicit `-L`/`-D`/`-l` paths. No `make install` or normal profile edits occur.
Race results, source copies, binary/configuration fingerprints and telemetry are
retained under that run. Whole-run maximum damage/contact flags catch collisions
even if a later pit stop repairs the damage. Negative main-road clearance during
pit travel is recorded but is not a failed racing-road-clearance measurement.
Speeds are m/s. Contact/penalty counters count flagged updates, not distinct
incidents. Shared-pit cases check actual assignment identity and exclusive service;
individual fuel overrides are checked against the observed starting fuel.
The first contact logs vehicle poses and available controller modes for diagnosis;
mode `-1` means that controller's private state was not exposed by the fixture.

**Known limitation:** `bt2-stress` can reproduce side-by-side contact on `e-track-2`.
It returns failure when contact occurs, including under `--scenario all`. Keep its
evidence; do not turn this into an unconditional expected pass or infer resolution
from a single clean run. See [RACING_REVIEW.txt](../../src/doc/robot_tutorial/RACING_REVIEW.txt).

The scenarios above execute Linux instrumentation. Use `check_windows.py` for
Windows execution; manifest inspection alone is not Windows execution. The
[maintenance skill](../../../../.opencode/skills/torcs-robot-tutorial-maintenance/SKILL.md)
documents workflow and lessons.

## Unit-level control and pit checks

From a configured Linux TORCS source root, with the TORCS libraries built:

```bash
python3 test/robot_tutorial/check_racing_controls.py
```

If testing installed libraries instead of `export/lib`:

```bash
python3 test/robot_tutorial/check_racing_controls.py --lib-dir /path/to/torcs/lib
```

Requires `g++`, Python 3, exported TORCS headers, and `librobottools`/`libtgf`/`libtxml`.
The runner builds standalone assertion executables in a fresh artifact directory, with assertions
enabled, for Chapters 3/4/5/6 and Appendices A/B/C. It does not install modules.
Use `--work-root <artifacts>` to choose the parent (default: system temporary dir).
The four pit-capable checkpoints additionally run [pit_math_checks.cpp](pit_math_checks.cpp): 1,273
spline/route/fuel comparisons each, plus invalid knots, mirrored/first/last/wrapped
routes, actual-vs-requested refuelling, tank bounds, occupancy, reversal and merge
state checks. All Python runners retain `report.json` and command logs on failure.
Add `--data-root <installed-data-root>` to run Appendix A's reference-car settings
tests: layer precedence, units, bounds, explicit zero-stint override, private
settings isolation, thirty fresh reloads, missing/malformed files and parser
buffers. Add `--valgrind` to check that suite for definite/indirect leaks and memory
errors. Without `--data-root`, the report explicitly marks this suite unrequested.

### Behavior matrix

- **All checkpoints:** clear straight above 32 m/s; full throttle and brake authority;
    gearing-derived bound; upcoming-bend braking; active aerodynamic cornering
    and braking; stopped-car hold.
- **All checkpoints, FWD/RWD/AWD:** free rolling and driven slip at standstill,
    10 m/s and 40 m/s. FWD/RWD also test non-driven slip independently.
- **Chapter 5 onward:** traffic-target delegation retains full pedal authority;
    a fast rear car 200 m away blocks a six-second merge, and a stopped leader
    250 m ahead is observed and reduces the speed target. Mirrored holding
    cases ensure a fallback does not steer back into an adjacent car's bounds.
- **Chapter 6 onward:** default service fuels toward the race finish, not an
    artificial three-lap stint.

These checks do not replace native race validation. After control changes, run
the supplied reference car on `g-track-1` and `e-track-2`, check actual full-throttle
acceleration and speeds above the former ceiling, and inspect lap time, road
position, damage and penalties. Exercise traffic, demonstration and fuel-driven
pit visits, shared pits, mirrored/wrapped routes and occupied boxes separately.

Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
