Tutorial A - Custom Car Setups and Driver Parameters
Copyright (C) 2026 Bernhard Wymann. Sources/build examples: GPL-2.0-or-later.

This directory is complete. Copy it to src/drivers/tutoriala in a configured
TORCS source tree, or extract the archive's tutoriala folder there.
Linux: make -C src/drivers/tutoriala install (from the TORCS source root).
Windows: build tutoriala.vcxproj using the tutorial's platform setup instructions.
Select Tutorial A, car1-stock1, CG Speedway number 1, six-lap Quick Race.

settings.cpp reads drivers/tutoriala/default.xml, then <track internal name>.xml
relative to the running game's data directory. These are our driver's rules.
Linux installation copies the XML files to the configured game data directory;
Windows copies them to the selected runtime/drivers/tutoriala directory.
For XML edits: save, leave the session, install the edited files, start a new
session. No C++ rebuild is needed; the normal install/build command also copies
XML. Editing the installed XML directly works, but the next install replaces it.

The supplied defaults reproduce Chapter 6's full-tank racing configuration.
Demonstration stops are disabled; stint laps=0 means fuel to finish.
g-track-1.xml is deliberately a sparse, empty override. Add Car/initial fuel=4 l
and Tutorial A/Strategy/demonstration stop=no for the 12-lap strategy exercise.
For tuning, change one value at a time and record more than lap time.

Private numeric limits are enforced in settings.cpp. Physical fuel/wing values
are checked against the engine's merged car/category bounds. Invalid values
retain the earlier value. Missing/wrong-type keys also retain the earlier value;
unknown names are ignored. XML is not a dimensionally typed configuration schema.
Debug builds provide Tutorial A loading/settings/effective console messages;
normal Release builds suppress GfOut. Invalid numeric values use GfError and
remain visible. Check the deployed XML and fuel display if edits seem absent.

Use the chapter's driving exercises when changing the settings or track.
