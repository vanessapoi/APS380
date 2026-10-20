Sherry Hills Raceway

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n sherry-hills-raceway -i ../data/tracks/experimental/sherry-hills-raceway -o ../data/tracks/experimental/sherry-hills-raceway -a -q
  trackgen -c experimental -n sherry-hills-raceway -i ../data/tracks/experimental/sherry-hills-raceway -o ../data/tracks/experimental/sherry-hills-raceway -r -q
  accc -g ../data/tracks/experimental/sherry-hills-raceway/sherry-hills-raceway.acc -l0 ../data/tracks/experimental/sherry-hills-raceway/sherry-hills-raceway.ac -l1 ../data/tracks/experimental/sherry-hills-raceway/sherry-hills-raceway-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/sherry-hills-raceway/sherry-hills-raceway.xml --polyline data/tracks/experimental/sherry-hills-raceway/source/centerline.json --overlay data/tracks/experimental/sherry-hills-raceway/source/xml-centerline-fit.svg --report data/tracks/experimental/sherry-hills-raceway/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/sherry-hills-raceway/sherry-hills-raceway.xml --output data/tracks/experimental/sherry-hills-raceway/sherry-hills-raceway.png --svg-output data/tracks/experimental/sherry-hills-raceway/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/sherry-hills-raceway/sherry-hills-raceway.xml --output data/tracks/experimental/sherry-hills-raceway/source/segments-labeled.svg

Third-party assets:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, banking, terrain heightmap, and generated geometry are derived from Instituto Geografico Nacional de Espana (IGN), PNOA-LiDAR
  third coverage. The 2026 MDT50cm v1 bare-earth product was generated from 2024 Andalucia LiDAR and is licensed under IGN terms compatible with
  CC BY 4.0. Accessed 2026-08-12.
  Product resolution: 0.5 m bare-earth DTM
  Horizontal CRS: ETRS89 / UTM zone 29N (EPSG:3041 axis order)
  Vertical values: metric orthometric elevations
  Product page: https://centrodedescargas.cnig.es/CentroDescargas/modelo-digital-terreno-mdt50cm
  License: https://centrodedescargas.cnig.es/CentroDescargas/politica-datos
