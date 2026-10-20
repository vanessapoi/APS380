Lone Star Circuit National

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n lone-star-circuit-national -i ../data/tracks/experimental/lone-star-circuit-national -o ../data/tracks/experimental/lone-star-circuit-national -a -q
  trackgen -c experimental -n lone-star-circuit-national -i ../data/tracks/experimental/lone-star-circuit-national -o ../data/tracks/experimental/lone-star-circuit-national -r -q
  accc -g ../data/tracks/experimental/lone-star-circuit-national/lone-star-circuit-national.acc -l0 ../data/tracks/experimental/lone-star-circuit-national/lone-star-circuit-national.ac -l1 ../data/tracks/experimental/lone-star-circuit-national/lone-star-circuit-national-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/lone-star-circuit-national/lone-star-circuit-national.xml --polyline data/tracks/experimental/lone-star-circuit-national/source/centerline.json --overlay data/tracks/experimental/lone-star-circuit-national/source/xml-centerline-fit.svg --report data/tracks/experimental/lone-star-circuit-national/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/lone-star-circuit-national/lone-star-circuit-national.xml --output data/tracks/experimental/lone-star-circuit-national/lone-star-circuit-national.png --svg-output data/tracks/experimental/lone-star-circuit-national/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/lone-star-circuit-national/lone-star-circuit-national.xml --output data/tracks/experimental/lone-star-circuit-national/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, generated geometry, and road banking are derived from USGS National Map 3DEP Bare Earth DEM Dynamic ImageServer
  data, accessed 28 May 2026. USGS-authored or produced data are U.S. Public Domain.
