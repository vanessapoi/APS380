# Test design and rationale

Olethros uses a regular planning mesh, a constrained bending-energy optimizer and an
adaptive controller. These tests cover numerical behavior, state-update ordering,
persistence and selected driving scenarios. Build and run commands are in the
[test README](README.md).

## Why these cases matter

1. **Tiny intervals.** A 15 mm interval in Lone Star produced an overflowing
   curvature-cost exponential in the former optimizer. Regular sampling removes
   native intervals from the optimization scale. The replacement objective has
   no exponentials; analytic circle-energy tests include 5 mm radii, and the
   independent gradient test checks central differences.
2. **Subdivision-dependent geometry.** Uniform periodic samples, stable anchored
   arc evaluation, native-ID mapping and physical grade support prevent tiny
   native intervals from becoming optimization or differentiation scales.
   Equivalent stadium geometry with different native splits exercises the live
   optimized path and runtime targets across the start line.
3. **Coarse initialization.** Starting fine refinement at the centerline
   weakened the racing line. A component test reconstructs the coarse
   seed and periodic interpolation, then compares the final refinement.
4. **Position-dependent curvature.** Holding an entrance radius of about 70.8 m
   over Dirt 2's 150 m straight caused a plateau at about 25.6 m/s and 20% throttle.
   Runtime queries use actual station. Both manufactured geometry and real
   straight-window checks cover this independently of lap completion.
5. **Scan-density-dependent braking.** Regular stations must not hide a stronger
   future braking demand. The driver takes the maximum demand and includes every
   native boundary, including short surface patches. Component tests cover the
   scan union; the Lone Star race check protects returning seam behavior.
6. **Persistence isolation.** Every session attempts to load a brain; practice and
   qualifying save at shutdown. Three successive practice Driver lifetimes check
   a missing initial brain, reload of nonzero steering learning and further saved
   updates. Controller fixtures redirect the TORCS local directory to temporary
   storage; process tests isolate files in the runner. Serialization tests check
   nonzero learned values through save/reload, preserve prior state on rejection, and distinguish
   missing, valid, incompatible and unreadable files.
7. **Per-bot timing and shared bookkeeping.** Assigning a per-bot `dt` inside the
   shared-cache guard leaves later callbacks with a zero or stale interval.
   Each bot takes the engine robot timestep; Cardata refresh is shared and runs
   once per simulation time. Tests exercise actual `drive()`
   speed-history updates as well as the local alone timer.
8. **Signed projected widths.** Summing signed sine/cosine components could
   cancel a car's extent or make it negative. Both axes contribute their
   absolute projected extent, checked against analytic rectangle cases.
9. **Opponent selection.** A selected opponent's gap, width and catch time must
   stay associated with that opponent. Mixing measurements from different cars
   makes avoidance depend on list order. Tests add a distinct, irrelevant car
   and reverse the list in both left/right scenarios.
10. **Incomplete runtime evidence.** Per-bot callback IDs and a final shutdown
    count make whole-record and whole-tick loss detectable. Required records
    depend on explicit recovery/gear/direction observations. Brain loading reports
    its result so rejected state cannot masquerade as a persisted run.
11. **Pit state and brake demand.** Pit derives the maneuver from request
    and occupancy before steering. Service and timeout clearing transition to exit
    immediately. An under-limit lane tick cannot fall through to `NONE`.
12. **Repeated control-state updates.** Target preparation advances avoidance and
    lookahead once. Pure steering and track feedback share the resulting base
    demand; the pedal pipeline contains one TCL update. Repeated calculations
    must not advance avoidance or filter memory an extra time.
13. **Pit-path ownership.** Pit displacement is measured from the road centerline
    throughout service and exit. Adding it to a racing-line weight of 0.2 or 0.8
    on a 30 m road moves the target 9 m away from its intended route. Tests vary
    those weights after service, supply nonzero learned road steering and nearby
    opponents, and look beyond the final spline knot at two speeds. The pit
    target and steering must retain the prescribed route; a blocking opponent
    must still trigger braking without starting a pass.
14. **Wide-road optimizer instability.** Olethros 7's original D-Speedway plan
    had 325 opposite-turn samples out of 857 and a peak curvature of 0.02068/m
    (48.35 m radius) on a road whose minimum native radius is 300 m. Clean
    practice reproduced weaving and repeated braking, independently of saved
    learning. A 10 m-reference step-scaling experiment identified width-sensitive
    instability but was rejected as the final fix. The replacement minimizes an
    explicit discrete bending energy, with exact derivatives, a coupled banded
    Gauss–Newton solve, physical bounds and cost-checked line search.
    Tests verify strict descent, removal of a wavy seed, rigid transformations,
    variable widths, and full outer-edge use on 5/10/18/30 m circular roads at
    2/4/8 m sampling, in both directions and at two headings. The analytic
    minimum prevents a centerline-only or artificially narrowed plan from passing.
15. **Slip coordinates and heading wrap.** The steering drift correction used
    world velocity heading instead of body-relative slip. A-Speedway's opposite
    straight repeatedly crosses the +/-pi heading boundary: the old 0.01 gain
    turned that into an approximately 0.0628 control jump. Body-relative
    `atan2(speed_y, speed_x)` removes the compass bias and the forward-driving
    discontinuity. Controller tests rotate pose/velocity/target together, mirror
    slip near both borders, check aligned/stationary motion and exercise the
    exact wrap case (which failed before the fix with a 0.062812 jump).
    The runtime check uses the 900–1030 m constant-target window. An initial
    wider 850–1080 m window also included corner settling/preparation; with the
    existing brain that intended motion exceeded 0.2 m, so it was unsuitable as
    a pure weaving check. The final window still rejects the old wrap kicks.

## Controller regression matrix

| Production path | Covered cases |
|---|---|
| `Driver::update`, `isAlone` | Both initial callback orders; order changes; varying positive engine intervals; zero/negative intervals; engine interval different from shared cache age |
| Shared `Cardata` refresh | Source observation changed between same-tick callbacks stays cached, then refreshes on the next tick |
| `Driver::drive` speed history | Both callback orders; two positive timestep sizes; nonzero adaptive updates for both bots |
| `SingleCardata::update` width | 0, +/-30, +/-90 and 180 degrees; each repeated with a rotated track heading |
| `filterSColl` | Left/right nearby opponent; irrelevant opposite-side car with a different width; both list permutations; ignored opponents |
| `getOffset` | Left/right passing; 1 s catch, exact 2 s threshold and 4 s recent-collision fallback; irrelevant candidate before/after the selected car; expired collision memory at the threshold; ignored opponents |
| Pit state and lane target | Both sides; wrapping/nonwrapping entry; distant request, approach, exact entry, under-limit lane, braking, service, exit, timeout and no assigned pit; exit target independent of racing-line weight; final-knot hold below/above pit speed target |
| Pit steering and opponents | Both sides and entry-wrap cases; nonzero road learning cannot alter pit steering; alongside opponents cannot shift steering or offset; blocking opponents still cause braking without passing |
| Target/feedback pipeline | Frozen-target steering queries; side-collision offset retained; base steering distinguished from the final filtered command in learning |
| Drift steering coordinates | Compass rotation with zero/mirrored slip at center and both borders; velocity-heading wrap; aligned/stationary motion and countersteering symmetry |
| TCL/pedal pipeline | Acceleration, braking, low speed, pit driving and recovery, each at 0, 2 and 5 m/s slip; pedal mutual exclusion |
| Gear selection | Highest gear in six/eight-speed transmissions; downshifting from the highest gear; ordinary torque/redline upshifts; launch and first gear |
| Setup path selection | Practice/qualifying/race paths with bare and qualified track filenames; default setup for unknown session types |
| Practice persistence | Three successive sessions for bot index 6; missing initial brain, retained steering prediction and further learning saved through real Driver shutdown |

The fixture exercises the production controller with in-memory inputs and TORCS
support libraries; it does not simulate vehicle motion or establish race results.

Harness tests additionally cover journal-write/flush/publication failures,
malformed recovery metadata, process-launch failures, preservation of completed
batch results, reference-fixture independence, artifact-name collisions,
positive tick intervals and per-bot end ordering. Lifecycle callbacks are checked
for null pointers before invocation.

## Current verification and open issue

Latest recorded checks in Release x64:

| Check | Result | Verified |
|---|---|---|
| Component and driver builds | Zero warnings/errors | 2026-09-13 |
| C++ component suite | 100 tests pass, including optimizer derivatives, width/sampling matrix, slip coordinates and persistence | 2026-09-13 |
| Python harness suite | 41 tests pass, including practice results and oval/heading-wrap behavioral gates | 2026-09-13 |
| A-Speedway, clean practice, six laps | In the 850–1080 m diagnostic window, lap-six lateral excursion fell from 0.773 m to 0.075 m; in the 900–1030 m constant-target window, from 0.577 m to 0.011 m | 2026-09-13 |
| A-Speedway, existing brain, six practice laps | Passes the constant-target steering window and brain adoption/restoration checks | 2026-09-13 |
| D-Speedway, clean practice, six laps | Flying laps 40.478–40.494 s, no damage; 1400–2000 m windows have no braking and 0.23–0.35 m lateral excursion | 2026-09-13 |
| D-Speedway, existing brain, six practice laps | Passes with brain adoption and restoration confirmed | 2026-09-13 |
| Michigan and B-Speedway, clean practice, six laps | Completion and finite telemetry pass | 2026-09-13 |
| Temporary 5 m-wide D-Speedway, clean practice, three laps | Flying speed >=84.27 m/s, no braking or damage, lateral positions -0.743..0.985 m | 2026-09-13 |
| Classic set before the slip-coordinate fix, clean races, two laps | All 28 complete; 27 behavioral passes, Dirt 2 fails its pit-masked window on lap one | 2026-09-13 |
| All installed tracks after the slip-coordinate fix, Olethros 7, clean races, two laps | All 112 complete both laps and pass all enabled checks, including Dirt 2 | 2026-09-13 |
| DLL lifecycle | 1000 ten-driver construction/shutdown cycles and unload with unclaimed slots pass | 2026-09-13 |
| Lone Star Full, clean brain, three laps | New optimizer passes returning-seam checks | 2026-09-13 |
| Dirt 2, persisted brain, three laps (before optimizer replacement) | Passes, with brain adoption confirmed, one completed pit stop and the pit window reported | 2026-09-13 |
| Forza, bots 6 and 7, two laps (before optimizer replacement) | Both bots pass completion and telemetry checks | 2026-09-13 |
| Dirt 2, clean brain, three laps | Completes the race and one pit stop but fails the unmasked-straight requirement on lap two | 2026-09-13 |

**Open issue:** the clean Dirt 2 run makes a lap-two pit visit that overlaps the
1520–1600 m acceleration window. The measured first- and third-lap windows gain
about 10.5–10.6 m/s at approximately full throttle. The cause of the pit visit has
not been isolated. The run therefore fails the clean-state acceptance criterion
despite satisfactory acceleration in the observed windows.

Brain restoration checks pass for all selected bots in these race scenarios.
The runner writes per-bot results and telemetry reports under
`test-results/olethros/`; reproduce the scenarios with the commands in the
[test README](README.md#run-real-races).

## Scope and limitations

The optimizer accepts only feasible energy-decreasing steps, but does not
guarantee a global minimum or minimum lap time. Native learning is indexed by
native segments. The tests cover the listed
scenarios, not every car/physics configuration or cross-platform bitwise result.

`fixtures/classic-reference.csv` provides two-lap reference values for Olethros 7
with fresh brains. Timing comparisons and behavioral checks serve different
purposes: matching a lap summary alone does not establish correct acceleration,
braking or opponent handling.

The new optimizer changes these historical timings. In the initial two-lap
classic run, before the subsequent slip-coordinate fix,
most tracks improved, but Dirt 1 was 70.17 s versus 66.54 s and Olethros Road 1
was 309.26 s versus 282.79 s. Dirt 2 was 175.94 s versus 154.14 s and its first
straight window was masked by a pit visit. These are recorded differences/open
behavioral concerns, not a claim that the new geometric objective is faster
everywhere. The older persisted-Dirt-2 and multi-bot Forza records above predate
this solver; the clean three-lap Dirt 2 check has also been rerun on the final code.
After the slip-coordinate fix, Dirt 2 passes the two-lap scenario but still
fails the three-lap scenario because its lap-two pit visit masks the straight.
Lone Star's clean three-lap seam check continues to pass.
