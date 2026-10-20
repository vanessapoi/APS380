Tuscan Ridge Short

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n tuscan-ridge-short -i ../data/tracks/experimental/tuscan-ridge-short -o ../data/tracks/experimental/tuscan-ridge-short -a -q
  trackgen -c experimental -n tuscan-ridge-short -i ../data/tracks/experimental/tuscan-ridge-short -o ../data/tracks/experimental/tuscan-ridge-short -r -q
  accc -g ../data/tracks/experimental/tuscan-ridge-short/tuscan-ridge-short.acc -l0 ../data/tracks/experimental/tuscan-ridge-short/tuscan-ridge-short.ac -l1 ../data/tracks/experimental/tuscan-ridge-short/tuscan-ridge-short-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/tuscan-ridge-short/tuscan-ridge-short.xml --polyline data/tracks/experimental/tuscan-ridge-short/source/centerline.json --overlay data/tracks/experimental/tuscan-ridge-short/source/xml-centerline-fit.svg --report data/tracks/experimental/tuscan-ridge-short/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/tuscan-ridge-short/tuscan-ridge-short.xml --output data/tracks/experimental/tuscan-ridge-short/tuscan-ridge-short.png --svg-output data/tracks/experimental/tuscan-ridge-short/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/tuscan-ridge-short/tuscan-ridge-short.xml --output data/tracks/experimental/tuscan-ridge-short/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, and generated geometry are derived from the Geoportale Nazionale / Ministero dell'Ambiente e della Sicurezza Energetica WCS dataset
  "Modello digitale del terreno - 20 metri" (coverage EL.DTM.20M), accessed 28 May 2026. The WCS GetCapabilities metadata reports no fees and no access constraints.
