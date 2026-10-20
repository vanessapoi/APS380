Brickyard Park Oval

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n brickyard-park-oval -i ../data/tracks/experimental/brickyard-park-oval -o ../data/tracks/experimental/brickyard-park-oval -a -q
  trackgen -c experimental -n brickyard-park-oval -i ../data/tracks/experimental/brickyard-park-oval -o ../data/tracks/experimental/brickyard-park-oval -r -q
  accc -g ../data/tracks/experimental/brickyard-park-oval/brickyard-park-oval.acc -l0 ../data/tracks/experimental/brickyard-park-oval/brickyard-park-oval.ac -l1 ../data/tracks/experimental/brickyard-park-oval/brickyard-park-oval-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/brickyard-park-oval/brickyard-park-oval.xml --polyline data/tracks/experimental/brickyard-park-oval/source/centerline.json --overlay data/tracks/experimental/brickyard-park-oval/source/xml-centerline-fit.svg --report data/tracks/experimental/brickyard-park-oval/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/brickyard-park-oval/brickyard-park-oval.xml --output data/tracks/experimental/brickyard-park-oval/brickyard-park-oval.png --svg-output data/tracks/experimental/brickyard-park-oval/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/brickyard-park-oval/brickyard-park-oval.xml --output data/tracks/experimental/brickyard-park-oval/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, banking, terrain heightmap, and generated geometry are derived from U.S. Geological Survey 3D Elevation Program 1 meter DEM data, project IN_Central_MarionCo_2016,
  tile USGS_one_meter_x56y441_IN_Central_MarionCo_2016, accessed 2026-05-24. USGS elevation data is public domain.
