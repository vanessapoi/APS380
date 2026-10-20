Costa do Sol Circuit

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n costa-do-sol-cicuit -i ../data/tracks/experimental/costa-do-sol-cicuit -o ../data/tracks/experimental/costa-do-sol-cicuit -a -q
  trackgen -c experimental -n costa-do-sol-cicuit -i ../data/tracks/experimental/costa-do-sol-cicuit -o ../data/tracks/experimental/costa-do-sol-cicuit -r -q
  accc -g ../data/tracks/experimental/costa-do-sol-cicuit/costa-do-sol-cicuit.acc -l0 ../data/tracks/experimental/costa-do-sol-cicuit/costa-do-sol-cicuit.ac -l1 ../data/tracks/experimental/costa-do-sol-cicuit/costa-do-sol-cicuit-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/costa-do-sol-cicuit/costa-do-sol-cicuit.xml --polyline data/tracks/experimental/costa-do-sol-cicuit/source/centerline.json --overlay data/tracks/experimental/costa-do-sol-cicuit/source/xml-centerline-fit.svg --report data/tracks/experimental/costa-do-sol-cicuit/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/costa-do-sol-cicuit/costa-do-sol-cicuit.xml --output data/tracks/experimental/costa-do-sol-cicuit/costa-do-sol-cicuit.png --svg-output data/tracks/experimental/costa-do-sol-cicuit/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/costa-do-sol-cicuit/costa-do-sol-cicuit.xml --output data/tracks/experimental/costa-do-sol-cicuit/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, relief terrain, and generated geometry are derived from Direcao-Geral do Territorio Dados LiDAR de Portugal continental, MDT-50cm, 2024.
  The DGT LiDAR dataset is listed on dados.gov.pt under Creative Commons Attribution 4.0 (CC BY 4.0).
