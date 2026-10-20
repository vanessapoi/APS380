Yellow Sea Circuit

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n yellow-sea-circuit -i ../data/tracks/experimental/yellow-sea-circuit -o ../data/tracks/experimental/yellow-sea-circuit -a -q
  trackgen -c experimental -n yellow-sea-circuit -i ../data/tracks/experimental/yellow-sea-circuit -o ../data/tracks/experimental/yellow-sea-circuit -r -q
  accc -g ../data/tracks/experimental/yellow-sea-circuit/yellow-sea-circuit.acc -l0 ../data/tracks/experimental/yellow-sea-circuit/yellow-sea-circuit.ac -l1 ../data/tracks/experimental/yellow-sea-circuit/yellow-sea-circuit-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/yellow-sea-circuit/yellow-sea-circuit.xml --polyline data/tracks/experimental/yellow-sea-circuit/source/centerline.json --overlay data/tracks/experimental/yellow-sea-circuit/source/xml-centerline-fit.svg --report data/tracks/experimental/yellow-sea-circuit/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/yellow-sea-circuit/yellow-sea-circuit.xml --output data/tracks/experimental/yellow-sea-circuit/yellow-sea-circuit.png --svg-output data/tracks/experimental/yellow-sea-circuit/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/yellow-sea-circuit/yellow-sea-circuit.xml --output data/tracks/experimental/yellow-sea-circuit/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, and generated geometry are derived from Copernicus DEM GLO-30 Public, Copernicus DEM 2021 release, tile N34E126.
  The product is a 30 m digital surface model in EPSG:4326 with metric elevation values. Accessed 2026-08-15
  from https://registry.opendata.aws/copernicus-dem/ under the Copernicus DEM license.
