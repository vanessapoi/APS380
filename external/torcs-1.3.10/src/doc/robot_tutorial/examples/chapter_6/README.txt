TUTORIAL 6 — THE COMPLETE TUTORIAL DRIVER

This folder contains every helper source required by the driver. No source
files or installed modules from Chapters 1–5 are required to build or load it.
You still need a working TORCS development checkout and its normal dependencies.

Place the folder at src/drivers/tutorial6 relative to the TORCS source root.
Linux: make -C src/drivers/tutorial6 install
Windows: use tutorial6.vcxproj and the tutorial's Visual Studio setup instructions.
The DLL/so and tutorial6.xml are installed by the supplied build rules.

First exercise: Tutorial 6 alone, CG Speedway number 1, Quick Race, six laps.
Defaults: 60 litres starting fuel; fuel/damage strategy, full racing controls.
For the route exercise, enable DEMONSTRATION_STOP in pit.cpp and rebuild.
It requests one stop after a completed lap, normally for tyre service only.

Strategy exercise: in pit.cpp set DEMONSTRATION_STOP=false; in tutorial6.cpp
set STARTING_FUEL=4.0. Run twelve laps on the same track to observe automatic
refuelling. STINT_LAPS=0 fuels to finish, bounded by tank capacity; set it to 3
for a repeated-stop exercise. Restore the racing defaults afterward.

Files: tutorial6.cpp wires the callbacks and control ownership; pit.cpp handles
the pit visit and strategy; spline.cpp evaluates cubic Hermite intervals.
The other helpers retain the speed, steering, traffic and recovery components
developed in the preceding chapters, included here under local names.

Leave the active session before rebuilding, then start a new session.
See Chapter 6 and its mathematical companion for assumptions, limitations,
experiments, platform details and community help.

Copyright (C) 2026 Bernhard Wymann. Source/build files: GPL version 2 or later.
The archive includes COPYING. In a source checkout, COPYING is at the TORCS root.
