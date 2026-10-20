Los Arcos Raceway

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n los-arcos-raceway -i ../data/tracks/experimental/los-arcos-raceway -o ../data/tracks/experimental/los-arcos-raceway -a -q
  trackgen -c experimental -n los-arcos-raceway -i ../data/tracks/experimental/los-arcos-raceway -o ../data/tracks/experimental/los-arcos-raceway -r -q
  accc -g ../data/tracks/experimental/los-arcos-raceway/los-arcos-raceway.acc -l0 ../data/tracks/experimental/los-arcos-raceway/los-arcos-raceway.ac -l1 ../data/tracks/experimental/los-arcos-raceway/los-arcos-raceway-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/los-arcos-raceway/los-arcos-raceway.xml --polyline data/tracks/experimental/los-arcos-raceway/source/centerline.json --overlay data/tracks/experimental/los-arcos-raceway/source/xml-centerline-fit.svg --report data/tracks/experimental/los-arcos-raceway/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/los-arcos-raceway/los-arcos-raceway.xml --output data/tracks/experimental/los-arcos-raceway/los-arcos-raceway.png --svg-output data/tracks/experimental/los-arcos-raceway/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/los-arcos-raceway/los-arcos-raceway.xml --output data/tracks/experimental/los-arcos-raceway/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, banking, terrain heightmap, and generated geometry are derived from elevation data of: Instituto Geográfico Nacional (IGN), Spain, MDT05
  (5-metre digital terrain model), adapted for TORCS. Used under the IGN data-use licence, compatible with Creative Commons Attribution 4.0 International
  (CC BY 4.0): https://www.ign.es/web/ign/portal/politica-datos