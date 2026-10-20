Ardennes Ridge

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n ardennes-ridge -i ../data/tracks/experimental/ardennes-ridge -o ../data/tracks/experimental/ardennes-ridge -a -q
  trackgen -c experimental -n ardennes-ridge -i ../data/tracks/experimental/ardennes-ridge -o ../data/tracks/experimental/ardennes-ridge -r -q
  accc -g ../data/tracks/experimental/ardennes-ridge/ardennes-ridge.acc -l0 ../data/tracks/experimental/ardennes-ridge/ardennes-ridge.ac -l1 ../data/tracks/experimental/ardennes-ridge/ardennes-ridge-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/ardennes-ridge/ardennes-ridge.xml --polyline data/tracks/experimental/ardennes-ridge/source/centerline.json --overlay data/tracks/experimental/ardennes-ridge/source/xml-centerline-fit.svg --report data/tracks/experimental/ardennes-ridge/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/ardennes-ridge/ardennes-ridge.xml --output data/tracks/experimental/ardennes-ridge/ardennes-ridge.png --svg-output data/tracks/experimental/ardennes-ridge/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/ardennes-ridge/ardennes-ridge.xml --output data/tracks/experimental/ardennes-ridge/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Elevation source: Service public de Wallonie (SPW) - Relief de la Wallonie - Modele Numerique de Terrain (MNT) 2021-2022 (2024-01-23),
  https://geodata.wallonie.be/id/a004e570-99d6-4fe5-b83d-49b774409278, licensed under CC-BY 4.0.
