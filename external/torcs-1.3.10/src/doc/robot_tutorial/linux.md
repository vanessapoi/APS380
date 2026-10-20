# Getting Ready on Linux {#robot_tutorial_linux}

**Goal:** build your first robot, select it in Practice, and see it hold still.

## Before you start {#robot_tutorial_linux_before}

You need a working TORCS development build with game data installed and a C++
compiler. Complete the project's `./configure`, `make`, `make install`, and
`make datainstall` workflow first. Use an installation prefix writable by your
development account. Confirm that you can launch the game normally.

Open a terminal in the **TORCS source root**: the directory containing
`configure`, `Make-config`, and `src/`. In a double-nested checkout this is
`torcs/torcs/`. Run all build commands below from that directory.

## Copy your robot {#robot_tutorial_linux_copy}

Copy the supplied starter to your working driver directory:

```sh
test ! -e src/drivers/tutorial1 &&
    cp -R src/doc/robot_tutorial/examples/chapter_1 src/drivers/tutorial1
```

If `src/drivers/tutorial1` already exists, use your existing copy. Keep the name
`tutorial1` for now. Edit files in this working copy, rather than the
documentation's reference copy.

## Build and install {#robot_tutorial_linux_build}

```sh
make -C src/drivers/tutorial1 CHECKPOINT=skeleton install
```

This builds the stationary checkpoint and installs it into your configured
TORCS installation. The Makefile uses the exported headers and libraries from
your development build.
Wait until the command finishes and the terminal is ready for another command.
If you see an error, use the help section below before starting the game.

## See your robot in TORCS {#robot_tutorial_linux_practice}

Launch that TORCS installation. If its launcher is in `PATH`, use:

```sh
torcs
```

Otherwise, use the full path to your installed launcher, such as
`/home/yourname/torcs/bin/torcs`.

1. Open **Practice**.
2. Select the road track **CG Speedway number 1** (`g-track-1`).
3. Select **Tutorial 1** as the driver. It uses the `car1-stock1` car.
4. Start the session.

**Your car should stay still. That is success!** The skeleton deliberately
holds the brakes. You now know how to build a robot and get TORCS to load it.

**Next: [Chapter 1 — Make It Drive](chapter_1.md).** Come back to the short
rebuild instructions below when the chapter asks you to try the driving code.

## Rebuild after a change {#robot_tutorial_linux_rebuild}

Leave the Practice session and return to the menu. TORCS unloads the driver
when the session ends, so you can keep the game open. Then run this from the
source root:

```sh
make -C src/drivers/tutorial1 CHECKPOINT=driving install
```

This selects `driving.cpp` instead of `skeleton.cpp`. Start a new Practice session
with the same driver and track; TORCS loads the rebuilt module. Use this command
again after each edit to `driving.cpp`.

[Continue making your robot drive](@ref robot_tutorial_1_driving_build).

## Continue with Chapter 2 {#robot_tutorial_linux_chapter_2}

From the source root, copy the new example into its own working directory:

```sh
test ! -e src/drivers/tutorial2 &&
    cp -R src/doc/robot_tutorial/examples/chapter_2 src/drivers/tutorial2
```

If that directory already exists, use your existing copy. Leave the current
Practice session and return to the menu, then build and install:

```sh
make -C src/drivers/tutorial2 install
```

Select **Tutorial 2** on **CG Speedway number 1** in a new Practice session.
This example deliberately makes a small driving mistake at the start.
[Chapter 2 — Get Back on Track](chapter_2.md) explains what to watch for.

After edits to `recovery.cpp` or `practice.cpp`, save and use the same build command.
The Chapter 1 driver remains available as **Tutorial 1**.

## Continue with Chapter 3 {#robot_tutorial_linux_chapter_3}

From the source root, copy the new example into its own working directory:

```sh
test ! -e src/drivers/tutorial3 &&
    cp -R src/doc/robot_tutorial/examples/chapter_3 src/drivers/tutorial3
```

If it already exists, use your working copy. Leave the current Practice session,
then build and install:

```sh
make -C src/drivers/tutorial3 install
```

Select **Tutorial 3** on **CG Speedway number 1** in a new Practice session.
[Chapter 3 — Choose Your Speed](chapter_3.md) explains what to observe.
After changes to `speed.cpp` or `braking.cpp`, save and use the same build command.
The earlier drivers remain available for comparison.

## Continue with Chapter 4 {#robot_tutorial_linux_chapter_4}

From the source root, copy the steering example into its own working directory:

```sh
test ! -e src/drivers/tutorial4 &&
    cp -R src/doc/robot_tutorial/examples/chapter_4 src/drivers/tutorial4
```

If it already exists, use your working copy. Leave the current Practice session,
then build and install:

```sh
make -C src/drivers/tutorial4 install
```

Select **Tutorial 4** on **CG Speedway number 1** in a new Practice session.
[Chapter 4 — Steering and Trajectory](chapter_4.md) explains the comparison.
Edit `steering4.cpp` for lookahead experiments and `speed4.cpp` for later speed
experiments. Save and use the same build command after each change.

## Continue with Chapter 5 {#robot_tutorial_linux_chapter_5}

This chapter adds traffic decisions and a reference pace driver. Assemble a new
working folder from its files and the supplied Chapter 4 helper sources. From
the source root:

```sh
test ! -e src/drivers/tutorial5 &&
    cp -R src/doc/robot_tutorial/examples/chapter_5 src/drivers/tutorial5 &&
    for helper in geometry4 steering4 speed4 braking4 recovery4; do
        cp src/doc/robot_tutorial/examples/chapter_4/$helper.h \
           src/doc/robot_tutorial/examples/chapter_4/$helper.cpp \
           src/drivers/tutorial5/ || break
    done
```

If the folder already exists, use your working copy. Copy the helpers from the
supplied examples so earlier experiments do not change this chapter's baseline.
The assembled folder contains everything needed to compile both modules.

Leave the current session, then build and install both drivers:

```sh
make -C src/drivers/tutorial5 install &&
    make -C src/drivers/tutorial5 ROBOT=tutorial5pace install
```

Follow [Chapter 5's Quick Race instructions](@ref robot_tutorial_5_start).
The drivers appear as **Tutorial 5** and **Tutorial Pace**. Each module controls
one car; no multiple-robot registration is required.

For the main experiments, edit `traffic5.cpp`. `tutorial5pace.cpp` contains the
reference opponent's speed cap. Use the same two build commands after edits.

## Continue with Chapter 6 {#robot_tutorial_linux_chapter_6}

The final checkpoint contains every helper source. From the source root:

```sh
test ! -e src/drivers/tutorial6 &&
    cp -R src/doc/robot_tutorial/examples/chapter_6 src/drivers/tutorial6
```

If the directory already exists, use your working copy. Leave the active session,
then build and install:

```sh
make -C src/drivers/tutorial6 install
```

Follow [Chapter 6's six-lap Quick Race exercise](@ref robot_tutorial_6_start).
Select **Tutorial 6**; the earlier tutorial modules are not needed for the solo
exercise. The optional traffic exercise can use Tutorial Pace or an ordinary
opponent. Edit `tutorial6.cpp` for starting fuel and `pit.cpp` for the pit/strategy
settings, then use the same rebuild command.

The downloadable `tutorial6.zip` contains the same complete folder. If using
that download, extract its `tutorial6` directory under `src/drivers/` before
building; it needs no helper-copy step.

## Continue with Appendix A {#robot_tutorial_linux_appendix_a}

From the source root, create a separate working copy of the complete example:

```sh
test ! -e src/drivers/tutoriala &&
    cp -R src/doc/robot_tutorial/examples/appendix_a src/drivers/tutoriala
```

If it exists, use your existing working copy. Alternatively extract the download's
`tutoriala` folder under `src/drivers/`. Leave the active session, then build and
install:

```sh
make -C src/drivers/tutoriala install
```

This installs the module and `tutoriala.xml`, `default.xml`, and `g-track-1.xml`.
Select **Tutorial A** for [Appendix A's baseline race](@ref robot_tutorial_a_start).
Edit `default.xml` or `g-track-1.xml` in your working copy for the experiments.
Save, leave the session, and use the same install command before starting a new
session. XML-only changes need deployment, not recompilation. The command's
installation output shows the actual configured data destination, ending in
`drivers/tutoriala/`.

Editing the installed XML directly also works for a quick experiment, but the
next installation replaces it from your working copy. Preserve your changes there.
When adding a new track file, add its name to `SHIP` in `tutoriala.mk`.

## Continue with Appendix B {#robot_tutorial_linux_appendix_b}

The complete example includes both exported images and editable artwork. From
the source root:

```sh
test ! -e src/drivers/tutorialb &&
    cp -R src/doc/robot_tutorial/examples/appendix_b src/drivers/tutorialb
```

Use your existing working copy if the folder already exists. Alternatively
extract the download's `tutorialb` folder under `src/drivers/`. Leave the current
session, then build and install:

```sh
make -C src/drivers/tutorialb install
```

Select **Tutorial B** for the [graphical appearance exercise](@ref robot_tutorial_b_start).
The installation copies `car1-stock1.rgb` and `logo.rgb` beside the driver's XML
in the game's **data** directory, under `drivers/tutorialb/`. The compiled module
is installed separately. Read the command's output for the configured destination.

For painting, edit the sources in `artwork/`, export the two runtime images into
your working folder, leave the session, and run the same install command. Images
are copied even when the C++ objects are up to date. Start a new session to see
them. The editable XCF and SVGs stay in the working folder and download; the game
only needs their exported SGI images.

The supplied images use the module-level directory. If you later add individual
index folders, extend the installation rules for those files and directories.

## Continue with Appendix C {#robot_tutorial_linux_appendix_c}

From the source root, create a working copy of the complete final checkpoint:

```sh
test ! -e src/drivers/tutorialc &&
    cp -R src/doc/robot_tutorial/examples/appendix_c src/drivers/tutorialc
```

Use your existing working copy if it already exists, or extract the download's
`tutorialc` folder under `src/drivers/`. Leave the active session, then build and
install the single module:

```sh
make -C src/drivers/tutorialc install
```

The build includes `driver.cpp` and installs shared configuration and the team
logo. It also recurses into `1/` and `2/` to install each robot's settings and
body texture. Keep those directories and their Makefiles together when copying
the checkpoint.

Select **Tutorial C Red**, **Tutorial C Teal**, or both for
[Appendix C's exercises](@ref robot_tutorial_c_start). Both entries come from the
same module; build it once. C++ changes affect the shared implementation and need
rebuilding. Individual XML/image edits need installation and a new session, using
the same command. Add new individual runtime files to that directory's `SHIP`
list. The editable artwork remains in the source folder and archive.

## If something goes wrong {#robot_tutorial_linux_help}

| Symptom | What to check |
| --- | --- |
| Build cannot find headers or libraries | The initial TORCS development setup may be incomplete. Ask your teacher or the community for help and include the error text. |
| Installation fails with a permissions error | Ask your teacher or the person who prepared TORCS to check that your account can install its rebuilt driver. |
| Tutorial 1 is missing | Run the same TORCS installation that you installed into; check that the `car1-stock1` game data is present. |
| The old behaviour persists | Save the file in `src/drivers/tutorial1/`, leave the session, check that the rebuild succeeds, and start a new Practice session. |

Still stuck? [Questions and feedback](@ref robot_tutorial_feedback) explains
where to ask. You do not need to diagnose the problem first.

For installation troubleshooting, the module is installed beneath the library
directory's `drivers/tutorial1/`, and its XML beneath the game-data directory's
`drivers/tutorial1/`. The configured paths are in `Make-config`.
The normal launcher unloads drivers between sessions; the developer `-k`
option disables this, so do not use it for the tutorial's rebuild loop.
