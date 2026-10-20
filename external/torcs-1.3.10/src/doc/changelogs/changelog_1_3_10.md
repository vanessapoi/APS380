\page changelog_1_3_10 Changelog TORCS 1.3.10

## Changes since 1.3.9

- Added quiet mode trackgen to avoid long log files (Bernhard).
- MAX_NODES increased in easymesh.cpp, from 15000 to 150000 (Bernhard).
- Added track generation and helper scripts, see tracktools, work in progress. E.g.
  fetching track data from OpenStreetMap, autoclosing track loop, etc. (Bernhard).
- Adopted skills, readme and checklists to enable small llms to help generate
  tracks (Bernhard).
- Skip trackgen window for calculations (-z option) (Bernhard).
- Improved tracktools script to add pits (Bernhard).
- Added tracktools scripts for elevation and banking (Bernhard).
- GUI library refactoring to get rid of "void *" and  related casts (Bernhard).
- Implemented fallback behaviour if the selected track in the racemanager got
  deleted, useful when working on tracks (Bernhard).
- Fixed track selection map previews not recovering after visiting a track without
  a PNG map (Bernhard).  
- Added mouseover warning message for disabled buttons (Bernhard).
- Prevented starting races with an empty driver selection and added menu warnings
  for selecting at least one driver (Bernhard).
- Little refactoring of RtTrackGlobal2Local, unified left and right case, added
  unit tests (Bernhard).
- Reverted experimental penalty ranking back to more FIA alike penalty handling
  (#19, reported by David Bears) (Bernhard).
- Apply pit speed limit if car is going in reverse (Athozus).
- Increased calling rate of human players to 250Hz, to reduce input lag, see
  RCM_MAX_DT_HUMAN, robots are still at 50Hz (Bernhard).
- Update to from autoconf 2.69 to 2.72, needed adoption for
  compatibility (Bernhard).
- Added anti-aliasing (MSAA) setting into display section, defaults to 4x
  (Bernhard).
- Added anisotropic filtering setting into the opengl section, the default is
  16x or the maximum your hardware supports (Bernhard).
- Updated trb1 setups (fast/slow threshold to 9 cm/s, fast damper settings, brake
  pressure and balance) (Bernhard).
- Updated default surface material properties, biggest changes are in curb-5cm-r
  and curb-5cm-l and bumpyness of grass (Bernhard).
- Increased pre race stabilization time from one to three seconds to avoid cars
  bouncing at race start (Bernhard).
- Adjusted excessive curb roughness on some tracks (Bernhard).
- Fixed -Wformat-truncation warnings of new gcc version (Bernhard).
- Fixed -Wstringop-truncation warnings of new gcc version (Bernhard).
- Fixed -Wregister warnings of new gcc version (Bernhard).
- Fixed -Woverloaded-virtual warnings of new gcc version (Bernhard).
- Fixed -Wmaybe-uninitialized warning of new gcc version (Bernhard).
- Fixed -Waddress warning of new gcc version (Bernhard).
- Capping repair and refuel amounts in the pit time calculation to avoid too
  high pit stop times in the race engine (Bernhard).
- Capping repair and refuel amounts in the pit menu, added mouseovers to the
  buttons (Bernhard).
- Replaced the splash screen png with a higher resolution version, this
  was created by Eckhard Jäger (Eckhard, Bernhard).
- Updated trb1 category with new suspension defaults (Bernhard).
- Updated trb3 category with new suspension defaults (Bernhard).
- Improved chasing camera (cGrCarCamBehind, used in some F2 and F3 views), the
  stiffness is now framerate independent and is visually closer to other
  racing games (Bernhard).
- Fixed washed out png image screenshots (Bernhard).
- Fixed gear button neutral fallback for joysticks (Bernhard).
- Improved version 4 track loading and added regression tests (Bernhard).
- Fixed Windows debug realloc copy size, release builds were not affected by
  this (Bernhard).
- Hardened Easymesh sentinel handling (Bernhard).
- Prevented invalid Easymesh node insertion (Bernhard).
- Added trackgen regression tooling (Bernhard).
- Easymesh refactoring and improvements (Bernhard).
- Adopted Easymesh to generate much more regular meshes, new parameter to
  control mesh resolution gradient, see "terrain transition" in the track
  manual (Bernhard).
- Updated trackgen and Easymesh regressions, unit tests (Bernhard).
- Limited terrain refinement on the inside of tight curves (Bernhard).
- Refactoring, only have from Easymesh derived code in easymesh.cpp (Bernhard).
- Added trackgen test fixtures for bridge generation (Bernhard).
- Added initial bridge generation in trackgen for the *-trk model (Bernhard).
- Added terrain domain splitting into multiple domains for tracks with one
  or more crossing bridges and terrain generation per domain (Bernhard).
- Fixed tracktools elevation relief alignment (Bernhard).
- Reduced large-coordinate camera vibration with precise simulation positions
  and rebased rendering, relevant on enormous tracks like IOM TT (Bernhard).
- Limited generated track curve radii in dp-diarc track solver from
  tracktools to 4000m (Bernhard).
- Heavy refactoring of trackgen, unified a lot of code which was duplicated
  and unified left/right cases, polished function signatures (Bernhard).
- Added track menu map renderer to tracktools (Bernhard).
- Added SVG centerline importer to tracktools (Bernhard).
- Added centerline georeferencing tool to tracktools (Bernhard).
- Updated car parameters for F330 P4, 250 GTO and GT 40 (Bernhard).
- Refactor common code in track segment resolution (Bernhard).
- Make olethros compatible with new tracks, pretty big refactoring (Bernhard).
- Updated OpenAL to OpenAL Soft 1.25.2 (Bernhard).
- Cosmetic fix for assertion emitted from updated OpenAL when quitting TORCS
  right out of a paused race, the emited message was confusing (Bernhard).
- Added new textures and surface definitions/defaults for trackgen bridge
  generation (Bernhard).
- Added georeference options to track XML model (Bernhard).
- Added new track categories "test" and "experimental" (Bernhard).
- Regenerated all menu track maps, updateded look (Bernhard).
- Added 73 (!) new tracks in the experimental category (Bernhard).
- Added 2 bridging tracks to the test category (Bernhard).
- Moved old tracks into current subdirectories (Bernhard).
- Updated doxygen configuration, documentation fixes (Bernhard).
- Updated track manual (Bernhard).
- Integrated track toolchain documentation into TORCS documentation and
  track documentation updates (Bernhard).
- Integrated robot tutorial into TORCS documentation and complete rework
  with more focus to usage in teaching (Bernhard).
- Added skill and integration tests for robot tutorial maintenance (Bernhard).
- Fixed parameter parser leaks on parameter read errors, is not relevant with
  shipped correct files (Bernhard).
- Updated installers, version bump to 1.3.10 (Bernhard).
