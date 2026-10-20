Tutorial C — Multiple Robots in One Module
Copyright (C) 2026 Bernhard Wymann. Code/build/configuration: GPL-2.0-or-later.
Artwork: Free Art License 1.3; see ARTWORK.txt.

This is a complete checkpoint. Copy the folder to src/drivers/tutorialc in a
configured TORCS source tree. No helper-copy or artwork-generation step is needed.
Linux (source root): make -C src/drivers/tutorialc install
Windows: build tutorialc.vcxproj using the tutorial's platform instructions.
Both deploy one module plus the shared files and individual directories 1 and 2.

Select Tutorial C Red (registered index 1, number 81), Tutorial C Teal (index 2,
number 82), or both on CG Speedway number 1. Begin with a six-lap Quick Race.
The full-tank racing baseline is inherited from Appendix B; no stop is forced.
Each selected index owns one TutorialDriver instance. It owns its settings,
speed/recovery/traffic/pit controllers and fuel observations. Track/car pointers
are borrowed from the engine. The registration callback does not reset instances.
rbShutdown releases only the selected instance; rbEndRace is not relied upon.
Register each robot once in a race; duplicating the same module/index is not a
way to create another independent instance.

Configuration precedence, per key:
  built-in/car defaults -> default.xml -> <track>.xml
  -> <index>/default.xml -> <index>/<track>.xml
Private section: Tutorial C (with nested Strategy). Sparse files retain earlier
values. Only the supplied physical whitelist is forwarded to the engine.
The final no-supported-side-pits fuel fallback still applies.

First isolation exercise: put 4 l starting fuel and demonstration stop=no into
2/g-track-1.xml only. Red retains its module defaults. Save, leave the session,
install and start a new session. Settings changes need no C++ recompilation.
Reverse the two drivers in the race selection to check that indices are stable.

The driver texture files are 1/car1-stock1.rgb and 2/car1-stock1.rgb. Editable
sources are artwork/1 and artwork/2. The shared pit sign is logo.rgb at module
level, with source artwork/logo.svg. The two XML entries use Tutorial C Team.
A shared box also requires the race's cars-per-pit setting to allow sharing.
Pit occupancy is engine-owned; independent strategy does not imply a team
reservation or scheduling protocol. See the appendix's shared-pit exercise.
