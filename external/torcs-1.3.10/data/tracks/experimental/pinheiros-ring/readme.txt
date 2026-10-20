Pinheiros Ring

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.


Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n pinheiros-ring -i ../data/tracks/experimental/pinheiros-ring -o ../data/tracks/experimental/pinheiros-ring -a -q
  trackgen -c experimental -n pinheiros-ring -i ../data/tracks/experimental/pinheiros-ring -o ../data/tracks/experimental/pinheiros-ring -r -q
  accc -g ../data/tracks/experimental/pinheiros-ring/pinheiros-ring.acc -l0 ../data/tracks/experimental/pinheiros-ring/pinheiros-ring.ac -l1 ../data/tracks/experimental/pinheiros-ring/pinheiros-ring-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/pinheiros-ring/pinheiros-ring.xml --polyline data/tracks/experimental/pinheiros-ring/source/centerline.json --overlay data/tracks/experimental/pinheiros-ring/source/xml-centerline-fit.svg --report data/tracks/experimental/pinheiros-ring/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/pinheiros-ring/pinheiros-ring.xml --output data/tracks/experimental/pinheiros-ring/pinheiros-ring.png --svg-output data/tracks/experimental/pinheiros-ring/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/pinheiros-ring/pinheiros-ring.xml --output data/tracks/experimental/pinheiros-ring/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Elevation source data derived from GeoSampa / Prefeitura do Município de São Paulo contour layers and MDT_2020 grid metadata, licensed under
  Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)
