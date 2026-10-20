Georgia Ridge Short

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n georgia-ridge-short -i ../data/tracks/experimental/georgia-ridge-short -o ../data/tracks/experimental/georgia-ridge-short -a -q
  trackgen -c experimental -n georgia-ridge-short -i ../data/tracks/experimental/georgia-ridge-short -o ../data/tracks/experimental/georgia-ridge-short -r -q
  accc -g ../data/tracks/experimental/georgia-ridge-short/georgia-ridge-short.acc -l0 ../data/tracks/experimental/georgia-ridge-short/georgia-ridge-short.ac -l1 ../data/tracks/experimental/georgia-ridge-short/georgia-ridge-short-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/georgia-ridge-short/georgia-ridge-short.xml --polyline data/tracks/experimental/georgia-ridge-short/source/centerline.json --overlay data/tracks/experimental/georgia-ridge-short/source/xml-centerline-fit.svg --report data/tracks/experimental/georgia-ridge-short/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/georgia-ridge-short/georgia-ridge-short.xml --output data/tracks/experimental/georgia-ridge-short/georgia-ridge-short.png --svg-output data/tracks/experimental/georgia-ridge-short/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/georgia-ridge-short/georgia-ridge-short.xml --output data/tracks/experimental/georgia-ridge-short/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, banking, and generated geometry are derived from USGS 3D Elevation Program 1 meter DEM data,
  GA_Statewide_2018_B18_DRRA tiles USGS_1M_17_x23y379 and USGS_1M_17_x24y379, accessed 25 May 2026.
