Kettle Moraine Raceway

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n kettle-moraine-raceway -i ../data/tracks/experimental/kettle-moraine-raceway -o ../data/tracks/experimental/kettle-moraine-raceway -a -q
  trackgen -c experimental -n kettle-moraine-raceway -i ../data/tracks/experimental/kettle-moraine-raceway -o ../data/tracks/experimental/kettle-moraine-raceway -r -q
  accc -g ../data/tracks/experimental/kettle-moraine-raceway/kettle-moraine-raceway.acc -l0 ../data/tracks/experimental/kettle-moraine-raceway/kettle-moraine-raceway.ac -l1 ../data/tracks/experimental/kettle-moraine-raceway/kettle-moraine-raceway-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/kettle-moraine-raceway/kettle-moraine-raceway.xml --polyline data/tracks/experimental/kettle-moraine-raceway/source/centerline.json --overlay data/tracks/experimental/kettle-moraine-raceway/source/xml-centerline-fit.svg --report data/tracks/experimental/kettle-moraine-raceway/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/kettle-moraine-raceway/kettle-moraine-raceway.xml --output data/tracks/experimental/kettle-moraine-raceway/kettle-moraine-raceway.png --svg-output data/tracks/experimental/kettle-moraine-raceway/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/kettle-moraine-raceway/kettle-moraine-raceway.xml --output data/tracks/experimental/kettle-moraine-raceway/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL)."
- Elevation data: U.S. Geological Survey 3D Elevation Program (3DEP), 1-meter DEM / lidar-derived bare-earth data, WI_Oshkosh_3Rivers_2018_D19, public domain.
