Skyline Ridge Circuit

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n skyline-ridge-circuit -i ../data/tracks/experimental/skyline-ridge-circuit -o ../data/tracks/experimental/skyline-ridge-circuit -a -q
  trackgen -c experimental -n skyline-ridge-circuit -i ../data/tracks/experimental/skyline-ridge-circuit -o ../data/tracks/experimental/skyline-ridge-circuit -r -q
  accc -g ../data/tracks/experimental/skyline-ridge-circuit/skyline-ridge-circuit.acc -l0 ../data/tracks/experimental/skyline-ridge-circuit/skyline-ridge-circuit.ac -l1 ../data/tracks/experimental/skyline-ridge-circuit/skyline-ridge-circuit-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/skyline-ridge-circuit/skyline-ridge-circuit.xml --polyline data/tracks/experimental/skyline-ridge-circuit/source/centerline.json --overlay data/tracks/experimental/skyline-ridge-circuit/source/xml-centerline-fit.svg --report data/tracks/experimental/skyline-ridge-circuit/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/skyline-ridge-circuit/skyline-ridge-circuit.xml --output data/tracks/experimental/skyline-ridge-circuit/skyline-ridge-circuit.png --svg-output data/tracks/experimental/skyline-ridge-circuit/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/skyline-ridge-circuit/skyline-ridge-circuit.xml --output data/tracks/experimental/skyline-ridge-circuit/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations and terrain heightmap are derived from the NSW 5 metre Digital Elevation Model, tile Bathurst-DEM-AHD_55_5m, accessed via NSW Spatial
  Services Elevation Data Service on 2026-05-14. Source data is Crown copyright, created and managed by DCS Spatial Services, Department of Customer Service,
  and licensed under Creative Commons Attribution 3.0 Australia (CC BY 3.0 AU).
