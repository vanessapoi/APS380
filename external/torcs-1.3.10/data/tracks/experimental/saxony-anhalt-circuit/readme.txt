Saxony Anhalt Circuit

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n saxony-anhalt-circuit -i ../data/tracks/experimental/saxony-anhalt-circuit -o ../data/tracks/experimental/saxony-anhalt-circuit -a -q
  trackgen -c experimental -n saxony-anhalt-circuit -i ../data/tracks/experimental/saxony-anhalt-circuit -o ../data/tracks/experimental/saxony-anhalt-circuit -r -q
  accc -g ../data/tracks/experimental/saxony-anhalt-circuit/saxony-anhalt-circuit.acc -l0 ../data/tracks/experimental/saxony-anhalt-circuit/saxony-anhalt-circuit.ac -l1 ../data/tracks/experimental/saxony-anhalt-circuit/saxony-anhalt-circuit-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/saxony-anhalt-circuit/saxony-anhalt-circuit.xml --polyline data/tracks/experimental/saxony-anhalt-circuit/source/centerline.json --overlay data/tracks/experimental/saxony-anhalt-circuit/source/xml-centerline-fit.svg --report data/tracks/experimental/saxony-anhalt-circuit/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/saxony-anhalt-circuit/saxony-anhalt-circuit.xml --output data/tracks/experimental/saxony-anhalt-circuit/saxony-anhalt-circuit.png --svg-output data/tracks/experimental/saxony-anhalt-circuit/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/saxony-anhalt-circuit/saxony-anhalt-circuit.xml --output data/tracks/experimental/saxony-anhalt-circuit/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, banking, terrain heightmap, and generated geometry are derived from Landesamt fuer Vermessung und Geoinformation Sachsen-Anhalt DGM1 1 m
  bare-earth elevation data, 2025 tiles, ETRS89 / UTM zone 32N (EPSG:25832), DHHN2016/NHN. Licensed under Datenlizenz Deutschland - Namensnennung 2.0 (dl-de/by-2-0), accessed 2026-08-08.
  Attribution: (C) GeoBasis-DE / LVermGeo ST
  Product: https://www.lvermgeo.sachsen-anhalt.de/de/gdp-dgm1.html
  License: https://www.govdata.de/dl-de/by-2-0
