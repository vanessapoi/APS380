Selangor Heat Circuit

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n selangor-heat-circuit -i ../data/tracks/experimental/selangor-heat-circuit -o ../data/tracks/experimental/selangor-heat-circuit -a -q
  trackgen -c experimental -n selangor-heat-circuit -i ../data/tracks/experimental/selangor-heat-circuit -o ../data/tracks/experimental/selangor-heat-circuit -r -q
  accc -g ../data/tracks/experimental/selangor-heat-circuit/selangor-heat-circuit.acc -l0 ../data/tracks/experimental/selangor-heat-circuit/selangor-heat-circuit.ac -l1 ../data/tracks/experimental/selangor-heat-circuit/selangor-heat-circuit-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/selangor-heat-circuit/selangor-heat-circuit.xml --polyline data/tracks/experimental/selangor-heat-circuit/source/centerline.json --overlay data/tracks/experimental/selangor-heat-circuit/source/xml-centerline-fit.svg --report data/tracks/experimental/selangor-heat-circuit/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/selangor-heat-circuit/selangor-heat-circuit.xml --output data/tracks/experimental/selangor-heat-circuit/selangor-heat-circuit.png --svg-output data/tracks/experimental/selangor-heat-circuit/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/selangor-heat-circuit/selangor-heat-circuit.xml --output data/tracks/experimental/selangor-heat-circuit/source/segments-labeled.svg

Third-party assets:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, and generated geometry are derived from Copernicus DEM GLO-30 Public, Copernicus DEM 2021 release, tile N02E101.
  The product is a 30 m digital surface model in EPSG:4326 with metric elevation values. Accessed 2026-08-15 from https://registry.opendata.aws/copernicus-dem/
  under the Copernicus DEM license.
