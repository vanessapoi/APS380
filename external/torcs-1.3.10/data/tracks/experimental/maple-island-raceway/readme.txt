Maple Island Raceway

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n maple-island-raceway -i ../data/tracks/experimental/maple-island-raceway -o ../data/tracks/experimental/maple-island-raceway -a -q
  trackgen -c experimental -n maple-island-raceway -i ../data/tracks/experimental/maple-island-raceway -o ../data/tracks/experimental/maple-island-raceway -r -q
  accc -g ../data/tracks/experimental/maple-island-raceway/maple-island-raceway.acc -l0 ../data/tracks/experimental/maple-island-raceway/maple-island-raceway.ac -l1 ../data/tracks/experimental/maple-island-raceway/maple-island-raceway-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/maple-island-raceway/maple-island-raceway.xml --polyline data/tracks/experimental/maple-island-raceway/source/centerline.json --overlay data/tracks/experimental/maple-island-raceway/source/xml-centerline-fit.svg --report data/tracks/experimental/maple-island-raceway/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/maple-island-raceway/maple-island-raceway.xml --output data/tracks/experimental/maple-island-raceway/maple-island-raceway.png --svg-output data/tracks/experimental/maple-island-raceway/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/maple-island-raceway/maple-island-raceway.xml --output data/tracks/experimental/maple-island-raceway/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, and banking are derived from Government of Canada / Natural Resources Canada HRDEM 1 m DTM data for Ville de Montreal, 2015,
  tiles dtm_1m_utm18_e_11_103.tif and dtm_1m_utm18_e_11_104.tif, available under the Open Government Licence - Canada, accessed 2026-05-24.
