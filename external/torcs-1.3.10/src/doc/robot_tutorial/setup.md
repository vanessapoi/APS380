# Getting Ready {#robot_tutorial_setup}

First, get a small robot to appear in TORCS. It will hold still while you learn
how to build and run it. Then Chapter 1 will teach it to drive.

**Choose your platform:**

- @subpage robot_tutorial_linux
- @subpage robot_tutorial_windows

Follow just that page. Both paths lead to Chapter 1: **Make It Drive**.

## Before the lesson — for teachers {#robot_tutorial_teachers}

Prepare and test the development environment before class. Installing the game
alone is not enough: students also need the tools and files used to build a
robot. The platform pages assume that this initial TORCS development setup is
already working.

Try the following using a **student account**, not just an administrator account:

1. Follow the setup page and build the supplied stationary robot.
2. Select **Tutorial 1** on **CG Speedway number 1** in Practice.
3. Follow Chapter 1, build the driving version, and make the first throttle edit.
4. Check that saving, rebuilding, and starting a new Practice session work.

Students need permission to edit their working files and install their rebuilt
driver. Give each student or pair a separate working copy so their experiments
do not overwrite one another.

For a first lesson, the learning goals are to explain the difference between
heading and position, change a driving command, and compare a prediction with
the car's behaviour. Asking pairs to record **change / prediction / observation**
provides a simple discussion exercise; a faster lap is not the only success.

For Chapter 3, prepare Tutorial 3 and watch a few laps before class. The main
chapter uses basic algebra and square roots; calculus is confined to the
optional analytical derivation. Students can use the supplied formulas and
make predictions without completing that derivation first.

For Chapter 4, prepare Tutorial 4 and compare it with Tutorial 3 at the same
speed settings. Keep a sketch of a bend handy: ask students to distinguish
distance along the centerline from the straight direction toward a target.
The main chapter introduces just the geometry needed for steering; the optional
companion develops vectors, lines, projections, and rotations. For the longer
lookahead experiment, check E-Track 2 as well as the initial reference track.
Discuss road departures even when a run records no damage.

For Chapter 5, build both Tutorial 5 and Tutorial Pace, then configure the
three-lap Quick Race described in the chapter. Try following before passing.
Keep the same driver order for comparisons. Students should distinguish a
car's current speed from the speed it could drive on clear road, and a target
offset from the actual path of its whole body. Leave time to watch the return
after a pass; getting the nose ahead is only part of the manoeuvre.

For Chapter 6, prepare the complete checkpoint and observe one deliberate pit
stop before introducing fuel strategy. Then try the twelve-lap, four-litre
strategy exercise. The full spline derivation is optional: students can use
the helper first, then explore endpoint values, slopes, and interval scaling.
Ask them to distinguish a smooth offset graph, a feasible world-space route,
and the actual motion of the car. Finish by tracing which component owns the
controls during racing, recovery, service, and rejoining.

For an optional configuration lesson, use [Appendix A](appendix_a.md). Students
can change XML without recompiling, distinguish car setup from controller tuning,
and compare one-variable experiments. Ask them to record the installed file,
units, predicted effect, and observed behavior as well as lap times.

[Appendix B](appendix_b.md) offers an artwork exercise using the same complete
driver. Students can work on colour, numbers, and a pit sign, then demonstrate
the source-to-export-to-install workflow and explain a texture seam or lookup
failure. GIMP edits the supplied XCF; an SVG editor edits the vector lettering.

[Appendix C](appendix_c.md) completes the ownership lesson with two robots in one
module. Ask students to run the second robot alone, reverse the field, change one
robot's configuration, and explain which effects are shared-world interactions
and which would indicate incorrectly shared controller state.

If preparing the environment is a stumbling block,
[ask the TORCS community for help](@ref robot_tutorial_feedback). Tell us which
platform you plan to use and which setup step is unclear.

Return to the [Robot Tutorial](index.md).
