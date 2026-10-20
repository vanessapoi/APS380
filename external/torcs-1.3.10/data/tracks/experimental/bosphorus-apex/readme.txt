Bosphorus Apex

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n bosphorus-apex -i ../data/tracks/experimental/bosphorus-apex -o ../data/tracks/experimental/bosphorus-apex -a -q
  trackgen -c experimental -n bosphorus-apex -i ../data/tracks/experimental/bosphorus-apex -o ../data/tracks/experimental/bosphorus-apex -r -q
  accc -g ../data/tracks/experimental/bosphorus-apex/bosphorus-apex.acc -l0 ../data/tracks/experimental/bosphorus-apex/bosphorus-apex.ac -l1 ../data/tracks/experimental/bosphorus-apex/bosphorus-apex-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es
  Serialize accc runs because stripe uses shared temporary files.

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/bosphorus-apex/bosphorus-apex.xml --polyline data/tracks/experimental/bosphorus-apex/source/centerline.json --overlay data/tracks/experimental/bosphorus-apex/source/xml-centerline-fit.svg --report data/tracks/experimental/bosphorus-apex/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/bosphorus-apex/bosphorus-apex.xml --output data/tracks/experimental/bosphorus-apex/bosphorus-apex.png --svg-output data/tracks/experimental/bosphorus-apex/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/bosphorus-apex/bosphorus-apex.xml --output data/tracks/experimental/bosphorus-apex/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, and generated geometry are derived
  from GEDTM30 v1.2, Global Ensemble Digital Terrain Model 30 m, by Yufeng Ho
  and Tom Hengl, licensed CC BY 4.0 and accessed 2026-08-12.
  Dataset DOI: https://doi.org/10.5069/G9BV7DT1
  Publication: https://doi.org/10.7717/peerj.19673
