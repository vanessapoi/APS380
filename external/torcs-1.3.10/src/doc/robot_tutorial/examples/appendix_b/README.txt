Tutorial B — Car Textures and Pit Logos
Copyright (C) 2026 Bernhard Wymann. Code/build/configuration: GPL-2.0-or-later.
Artwork: Free Art License 1.3; see ARTWORK.txt.

Copy this complete folder to src/drivers/tutorialb in a configured TORCS tree.
Linux (source root): make -C src/drivers/tutorialb install
Windows: build tutorialb.vcxproj using the tutorial's Visual Studio instructions.
Both install the driver, configuration, car1-stock1.rgb, logo.rgb and ARTWORK.txt.
Select Tutorial B on CG Speedway number 1, six-lap Quick Race, Normal display.
The driver is the Appendix A checkpoint with its module/configuration names
changed. It retains the full-tank racing baseline, with fuel/damage strategy.

artwork/livery.xcf: editable GIMP source; paint, side panels, details and badges
are separate layers. The UV guide is hidden; keep it hidden for game export.
artwork/decals.svg: editable number badges and lettering used in the XCF's top
decal layer. Editing this SVG alone does not update the XCF or the runtime image.
artwork/logo.svg: editable pit-logo source. Keep the perimeter wall colour and
the main message within the top two-thirds of the image.

Export the car as 1024x1024 RGBA, 8 bits per channel, SGI format, car1-stock1.rgb.
Export the logo as 256x256 RGB, 8 bits per channel, SGI format, logo.rgb.
GIMP supports SGI export; changing an extension is not conversion.
Save editable sources separately. Export, leave the session, install the new
images, and start a new session. No C++ rebuild is needed for image edits.

The car model asks for car1-stock1.rgb. The renderer searches
drivers/tutorialb/1, then drivers/tutorialb, then cars/car1-stock1 for this
body texture. The exported robot index is 1, not its position in the race list.
A single-car side pit prefers drivers/tutorialb/1/logo.rgb, then the module
logo; a shared pit skips individual driver logos and uses the first assigned
car's module-level logo. See the appendix for global fallback paths and UVs.

Keep stock model textures intact. Test body appearance from several cameras,
window transparency, text orientation, and the actual assigned pit sign.
The renderer caches textures during a session; pausing will not reload them.
