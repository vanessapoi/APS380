# Olethros driver tests

This suite tests the production Olethros driver. See
[the implementation guide](../../../src/drivers/olethros/README.md) and
[the test design notes](ENGINEERING.md).

## Layout and test types

- `unit/`: C++ component tests for production geometry, bending-energy gradients,
  feasible descent and full usable width on 5–30 m roads,
  brain serialization, per-bot timing, collision/overtaking decisions, pit-state
  transitions, pit-path isolation and exactly-once controller updates.
  Synthetic inputs are built in memory; persistence uses temporary files.
  No race executable, Olethros plugin, installed track, saved brain, or
  `test-results` capture is required.
- `integration/`: Windows process-level race runner and focused behavioral
  checks. `test_runner.py` contains **unit tests of the harness**, not races.
- `fixtures/classic-reference.csv`: two-lap reference values for Olethros 7
  (index 6) with clean brains, and the inventory of 28 classic tracks used by
  `--classic`. Timing comparisons complement the behavioral checks.

All commands below use the solution root (`torcs/torcs`) as working directory.

## Build and run C++ component tests

`TORCS.sln` includes `olethros_test` under **testsuite / drivers**, enabled in
Debug/Release for both Win32 and x64. The test executable is written to
`<Platform>/<Configuration>/olethros_test.exe` relative to the solution root.

```powershell
powershell -Command "& 'C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe' test\drivers\olethros\olethros_test.vcxproj /p:Configuration=Release /p:Platform=x64 /p:SolutionDir='C:\Users\berni\Development\code\torcs\torcs\' 2>&1"
x64/Release/olethros_test.exe
```

Adjust the absolute solution path for another checkout. The test executable
compiles the production controller, helpers, optimizer and learning implementation
with Google Test. Project references build the existing `robottools` and `tgf`
dependencies; their DLLs and `txml.dll` are copied next to the test executable.
SG/UL remain static dependencies. The Olethros racing plugin is built separately.

The controller fixture initializes a closed stadium and car parameters in memory.
Each controller test redirects TORCS's local directory to a private temporary
directory and restores it after driver shutdown. Ordinary cases initialize with
no saved brain and use race control/teardown policy so no brain is saved. A
practice-persistence case runs three successive Driver lifetimes, checking that
each loads the preceding session's learned steering correction and saves further
learning. Tests invoke the production
`update()`, `drive()`, side-steering and overtaking code. They cover both callback
orders, an order change, speed-history adaptation and the once-per-tick shared
observation cache. Opponent cases mirror both sides and permute the candidate list;
pit cases cover both sides, start-line wrapping, service and timeout. They also
check that the pit-exit target is independent of racing-line weight, lookahead
past the exit holds the spline endpoint, and learned road steering or nearby cars
cannot displace pit guidance. A blocking car must still trigger braking without
starting a passing maneuver. Controller cases cover acceleration, braking, low
speed, pits and reverse recovery with below/at/above-threshold wheel slip. The
coverage matrix is in ENGINEERING.md.

Focused controller and projected-width tests:

```powershell
x64/Release/olethros_test.exe --gtest_filter=*CardataWidthTest*:*DriverTimingTest*:*ControllerTest*:*SideCollisionTest*:*OvertakingTest*
x64/Release/olethros_test.exe --gtest_filter=*PitTransitionTest*:*ControllerPipelineTest*
```

## Test the Python harness

```powershell
conda run --no-capture-output -n torcs-tracktools python -m unittest discover -s test/drivers/olethros/integration -p test_*.py
```

These tests use synthetic logs and temporary brains, including timeout/error/
interrupt recovery, corruption rejection and missing-evidence failures.

The C++ persistence tests also cover every byte truncation of a representative
brain, invalid tags/dimensions, nonfinite values in all arrays, preservation of
prior state and failed file replacement. A separate real-module lifecycle check
does not start a race or read/write a brain:

```powershell
conda run --no-capture-output -n torcs-tracktools python test/drivers/olethros/integration/check_lifecycle.py
```

It constructs/shuts down ten slots for 1000 cycles and checks module unload with
unclaimed pre-race instances. Registration descriptors are process-owned in this
small harness; it is not a heap-leak measurement.

For an isolated component AddressSanitizer build, add `/p:EnableASAN=true`,
`/p:LinkIncremental=false` and separate `/p:OutDir` and `/p:IntDir` directories
to the component-project command. The ASan runtime DLL must be on PATH when the
test executable runs. This does not instrument the installed racing DLL, and
Windows ASan does not provide a general leak detector.

## Run real races

Build the Release x64 Olethros module first using the repository build workflow.
Close interactive TORCS before running tests, and do not launch it until the
runner finishes restoring the brain. A lock serializes runners; the application
does not participate in that lock.

```powershell
conda run --no-capture-output -n torcs-tracktools python test/drivers/olethros/integration/run_olethros_regression.py --track dirt/dirt-2 --track road/lone-star-circuit-full --laps 3 --brain-state clean
conda run --no-capture-output -n torcs-tracktools python test/drivers/olethros/integration/run_olethros_regression.py --track dirt/dirt-2 --laps 3 --brain-state persisted
conda run --no-capture-output -n torcs-tracktools python test/drivers/olethros/integration/run_olethros_regression.py --classic --laps 2 --brain-state clean --compare-reference
conda run --no-capture-output -n torcs-tracktools python test/drivers/olethros/integration/run_olethros_regression.py --track road/forza --opponent-idx 7 --laps 2 --brain-state clean
conda run --no-capture-output -n torcs-tracktools python test/drivers/olethros/integration/run_olethros_regression.py --track oval/d-speedway --track oval/michigan --laps 6 --session practice --brain-state clean
conda run --no-capture-output -n torcs-tracktools python test/drivers/olethros/integration/run_olethros_regression.py --track oval/d-speedway --laps 6 --session practice --brain-state persisted
conda run --no-capture-output -n torcs-tracktools python test/drivers/olethros/integration/run_olethros_regression.py --track oval/a-speedway --laps 6 --session practice --brain-state clean
```

To check **all installed tracks**, omit `--track`, `--category` and `--classic`:

```powershell
conda run --no-capture-output -n torcs-tracktools python test/drivers/olethros/integration/run_olethros_regression.py --olethros-idx 6 --laps 2 --brain-state clean --timeout 120
```

**Known result:** the clean three-lap Dirt 2 scenario currently has a recorded
failure because a lap-two pit visit overlaps its required straight window.
The measured straight windows pass. See the
[open issue](ENGINEERING.md#current-verification-and-open-issue) when interpreting
that command's result.

`--session practice` runs actual single-bot practice, including radius learning
and shutdown saving. It validates the practice result's driver identity and
consecutive, finite per-lap records instead of a race ranking. The brain transaction
restores the original file after practice too. Race remains the default; opponents
and exact historical reference comparisons require race mode.

`--compare-reference` returns failure if the selected recorded lap/time/top-speed
fields differ. This comparison is platform/car/setup dependent; investigate
differences instead of automatically accepting or regenerating the reference.
It requires a single bot (index 6).
The checked-in numbers describe the preceding heuristic optimizer; the new
bending-energy optimizer intentionally changes racing lines, so exact comparison
is historical evidence rather than the current acceptance target. The fixture
has not been regenerated to conceal those differences.
The reference CSV is loaded only for `--classic` or `--compare-reference`;
other runs and ordinary `--list` commands do not depend on it.

`--opponent-idx` is repeatable and adds distinct Olethros indices 0..9 after the
focused bot (`--olethros-idx`, default 6). Each bot must complete the requested
laps and supply its own complete telemetry. Track-specific straight/seam thresholds
apply to the focused bot. The runner isolates every selected bot's brain through
one transaction group, including restoration if a later brain cannot be acquired.

The runner isolates brain files while the driver follows its session load/save
policy. It preserves every selected bot/track brain:

- `clean`: move it aside for the race, allowing a normal missing-file load.
- `persisted`: provide a copy of the original; an absent or rejected brain is an error.
- On success, failure or timeout, restore the original file (or its absence),
  verifying its SHA-256. In-run learning is unchanged in both modes.

The runner writes and flushes a temporary journal, then atomically publishes it
as `*.brain.regression.json` before moving a brain. An interruption before
publication leaves the original brain in place. After publication, the journal
and any adjacent `*.brain.regression-backup` support recovery. Close TORCS, then run:

```powershell
conda run --no-capture-output -n torcs-tracktools python test/drivers/olethros/integration/run_olethros_regression.py --recover-brain "C:\path\to\track.brain.regression.json"
```

Do not delete the backup/journal manually to bypass a failed digest check.
Malformed or unreadable journals produce a diagnostic and preserve the journal,
brain and backup for inspection.
Windows local-directory resolution uses the same shell API as TORCS, not an
assumed `LOCALAPPDATA` environment redirect.

## Acceptance and results

Every race requires fresh result XML, requested lap completion and finite
recorded controls/states. Missing required telemetry fails. The runner enables
the read-only `OLETHROS_DIAGNOSTICS` flag for its child process.

- `OlethrosSession` supplies each bot's track length; `OlethrosBrain` must report
  `loaded` for persisted runs or `missing` for clean races.
- Each `OlethrosTick` has a bot ID, consecutive callback number, time, engine
  interval, recovery flag, gear and speed. Race intervals must be positive.
  Controls and state must match that tick.
- Normal driving requires exactly one target. Speed plans are required in forward
  gears; braking plans are required outside fast backwards driving. Recovery has
  its own explicit record requirements.
- Shutdown emits `OlethrosEnd` with the total callback count. Missing entire ticks,
  truncated traces, duplicate records, and records from another bot fail.
  The end marker closes that bot's recognized telemetry stream; other bots may
  continue reporting afterward.

- Dirt 2: each complete 1520–1600 m straight window must gain at least 5 m/s and
  average at least 75% throttle. Clean runs may not hide the window with a pit
  visit; persisted runs report pit windows and require an unmasked observation.
- Lone Star Full: every required returning crossing covers the last 25 m and
  first 12 m, has complete planner records, no pit masking, at least 40 m/s
  speed/target and no more than 1% brake. The standing start is excluded.
- D-Speedway with only Olethros 7: laps 2 onward must cover 1400–2000 m of the
  constant 900 m bend with at least 70 m/s, at most 1% brake, planned radius at
  least 200 m and at most 3 m lateral excursion. Missing telemetry or a pit visit
  fails the window. This detects the observed weaving/phantom-corner slowdown.
- A-Speedway with only Olethros 7: laps 2 onward must cover 900–1030 m of the
  opposite straight, where the lateral target is constant, with at most 0.2 m
  lateral excursion and 0.02 steering-command change between consecutive ticks.
  Missing telemetry or a pit visit fails the window. This detects compass-heading
  wrap kicks without counting intended corner-transition movement as weaving.
- Other tracks: completion/finite-control coverage only, unless reference
  comparison is explicitly requested. Damage is not a universal failure gate.

Results go to a fresh directory under `test-results/olethros/`: logs, result XML,
generated race configuration, settings, brain digests keyed by bot index,
per-driver race results (`*.drivers.json`), per-bot behavioral reports and summary
CSV. The CSV remains one aggregate result per track, with the focused bot's summary
fields. These are disposable outputs, never prerequisites for the tests.

Default output directories include a unique suffix so runs started in the same
second do not collide. An explicit `--out-dir` must not already exist. Each track's
artifacts share a readable stem plus a hash of its category/name, distinguishing
names that have the same sanitized spelling.

A process-launch error is recorded as a failed result and the batch continues.
`summary.csv` is also written when an unexpected later exception or interrupt
stops the batch, preserving results already completed; that exception still
propagates to the caller.
