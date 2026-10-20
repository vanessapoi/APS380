Sunset Airfield

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n sunset-airfield -i ../data/tracks/experimental/sunset-airfield -o ../data/tracks/experimental/sunset-airfield -a -q
  trackgen -c experimental -n sunset-airfield -i ../data/tracks/experimental/sunset-airfield -o ../data/tracks/experimental/sunset-airfield -r -q
  accc -g ../data/tracks/experimental/sunset-airfield/sunset-airfield.acc -l0 ../data/tracks/experimental/sunset-airfield/sunset-airfield.ac -l1 ../data/tracks/experimental/sunset-airfield/sunset-airfield-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/sunset-airfield/sunset-airfield.xml --polyline data/tracks/experimental/sunset-airfield/source/centerline.json --overlay data/tracks/experimental/sunset-airfield/source/xml-centerline-fit.svg --report data/tracks/experimental/sunset-airfield/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/sunset-airfield/sunset-airfield.xml --output data/tracks/experimental/sunset-airfield/sunset-airfield.png --svg-output data/tracks/experimental/sunset-airfield/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/sunset-airfield/sunset-airfield.xml --output data/tracks/experimental/sunset-airfield/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Road elevations and the generated terrain heightmap are derived from the U.S. Geological Survey 3D Elevation Program (3DEP) 1 m bare-earth
  DEM USGS_1M_17_x46y304_FL_Peninsular_FDEM_2018_D19_DRRA, which is USGS/U.S. USGS 3DEP elevation data is public domain; no copyright restriction
  applies to the DEM source data or derivatives, though attribution to USGS is recommended
