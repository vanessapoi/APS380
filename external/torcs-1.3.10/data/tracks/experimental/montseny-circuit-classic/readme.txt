Montseny Circuit Classic

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n montseny-circuit-classic -i ../data/tracks/experimental/montseny-circuit-classic -o ../data/tracks/experimental/montseny-circuit-classic -a -q
  trackgen -c experimental -n montseny-circuit-classic -i ../data/tracks/experimental/montseny-circuit-classic -o ../data/tracks/experimental/montseny-circuit-classic -r -q
  accc -g ../data/tracks/experimental/montseny-circuit-classic/montseny-circuit-classic.acc -l0 ../data/tracks/experimental/montseny-circuit-classic/montseny-circuit-classic.ac -l1 ../data/tracks/experimental/montseny-circuit-classic/montseny-circuit-classic-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/montseny-circuit-classic/montseny-circuit-classic.xml --polyline data/tracks/experimental/montseny-circuit-classic/source/centerline.json --overlay data/tracks/experimental/montseny-circuit-classic/source/xml-centerline-fit.svg --report data/tracks/experimental/montseny-circuit-classic/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/montseny-circuit-classic/montseny-circuit-classic.xml --output data/tracks/experimental/montseny-circuit-classic/montseny-circuit-classic.png --svg-output data/tracks/experimental/montseny-circuit-classic/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/montseny-circuit-classic/montseny-circuit-classic.xml --output data/tracks/experimental/montseny-circuit-classic/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Elevation data: Institut Cartogràfic i Geològic de Catalunya (ICGC), WCS del Model d’Elevacions del Terreny, licensed under
  Creative Commons Attribution 4.0 International (CC BY 4.0).
