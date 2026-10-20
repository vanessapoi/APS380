# Robot Tutorial {#robot_tutorial}

![Tux reading the Robot Tutorial beside a red racing car](images/robottux2.jpg)

*Welcome illustration: © 2003 Jean-Christophe Durieu.*

## Welcome {#robot_tutorial_welcome}

Watching a race is fun. Watching a driver you have programmed take its first
corner is something else! This tutorial helps you build your own TORCS robot,
understand its decisions, and improve it by experimenting in the simulator.

A **robot** is a program that drives a car. You will write it in C++ and build
it as a **plugin**, a small program that TORCS can load. TORCS calls functions in
your robot, supplies information about the car and the race, and reads back
your steering, accelerator, brake, and gear commands. The simulator handles
the vehicle physics; your robot decides how to drive.

There is plenty to explore. A controller that follows a straight may struggle
in a corner. Driving quickly introduces braking and traction problems. Add
opponents, fuel, damage, and pit stops, and even a simple racing environment
becomes an interesting programming playground.

## What you will build {#robot_tutorial_goals}

The setup and first chapter take you from a stationary car to one that follows the
track's centerline. You will learn where the driving information comes from,
how a steering decision is calculated, and how to build and run your changes.
The example intentionally starts small: first gear, modest throttle, and a
simple steering correction.

The driving sequence takes you through recovery, speed control, steering,
sharing the track, and pit stops. Custom car setups, textures, and implementing
multiple robots in one module belong to the optional appendices.

## Before you start {#robot_tutorial_prerequisites}

You need:

- A TORCS source checkout and a working development build, including game data.
  Running a prebuilt game alone does not provide all the headers and libraries
  needed to compile a plugin.
- A C++ compiler: GCC on Linux or Visual Studio 2022 with the C++ tools and
  Windows SDK on Windows. The example uses C++14, matching the current Windows
  solution's language setting.
- Basic familiarity with functions, structures, pointers, and compiling code.
  Advanced C++ or prior vehicle-dynamics knowledge is unnecessary.
- The `car1-stock1` car and the `g-track-1` road track, displayed as
  **CG Speedway number 1**. These are the initial reference combination.

Start with [Getting Ready](setup.md) and choose your platform. It takes you
through building a stationary robot and selecting it in Practice. Then follow
Chapter 1 to make it drive. Keep your platform's rebuild instructions handy:
you will reuse that short step after each experiment.

## How to work through the tutorial {#robot_tutorial_method}

Read the explanation, try the supplied example (a **checkpoint**), and watch
what the car does. Change one thing at a time. Predict the effect, then compare
your prediction with what you observe. If a result surprises you, sketch the
car and track on paper. Understanding an unsuccessful experiment is part of
the exercise.

Each checkpoint has a complete source example. You can type the driving code
yourself or use the supplied version to recover when you get lost. The simple
algorithms are teaching examples; their limitations provide the motivation for
the next improvements.

A coding agent can help explain an expression, investigate a build failure,
or implement a small experiment. Give it the current tutorial and TORCS
interfaces, ask for one change at a time, and evaluate the resulting behaviour
in the simulator. A compiling driver is only the start of that evaluation.

## Contents {#robot_tutorial_contents}

- @subpage robot_tutorial_setup
- @subpage robot_tutorial_chapter_1
- @subpage robot_tutorial_chapter_2
- @subpage robot_tutorial_chapter_3
- @subpage robot_tutorial_chapter_4
- @subpage robot_tutorial_chapter_5
- @subpage robot_tutorial_chapter_6
- @subpage robot_tutorial_appendix_a
- @subpage robot_tutorial_appendix_b
- @subpage robot_tutorial_appendix_c
- @subpage robot_tutorial_credits

The source examples and illustrations are included with the tutorial, so it
can be read and used offline.

## Questions and feedback {#robot_tutorial_feedback}

**Stuck, or found something confusing?**

Ask in the [TORCS Discord](https://discord.com/invite/qyPc6MjbyD) or on the
[TORCS-users mailing list](https://lists.sourceforge.net/lists/listinfo/torcs-users).
For the mailing list, subscribe before posting.

Tell us which step you reached, whether you use Windows or Linux, and what
happened. If an error appeared, include its text. You do not need to know what
caused the problem to ask for help.

**Teaching with this tutorial?**

We would love to hear which explanations worked, where students got stuck, and
what would make the tutorial easier to use in class.

**Tried an interesting experiment?**

Share what you changed and how your robot behaved!
