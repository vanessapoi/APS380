Rivazza Valley Circuit

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n rivazza-valley-circuit -i ../data/tracks/experimental/rivazza-valley-circuit -o ../data/tracks/experimental/rivazza-valley-circuit -a -q
  trackgen -c experimental -n rivazza-valley-circuit -i ../data/tracks/experimental/rivazza-valley-circuit -o ../data/tracks/experimental/rivazza-valley-circuit -r -q
  accc -g ../data/tracks/experimental/rivazza-valley-circuit/rivazza-valley-circuit.acc -l0 ../data/tracks/experimental/rivazza-valley-circuit/rivazza-valley-circuit.ac -l1 ../data/tracks/experimental/rivazza-valley-circuit/rivazza-valley-circuit-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/rivazza-valley-circuit/rivazza-valley-circuit.xml --polyline data/tracks/experimental/rivazza-valley-circuit/source/centerline.json --overlay data/tracks/experimental/rivazza-valley-circuit/source/xml-centerline-fit.svg --report data/tracks/experimental/rivazza-valley-circuit/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/rivazza-valley-circuit/rivazza-valley-circuit.xml --output data/tracks/experimental/rivazza-valley-circuit/rivazza-valley-circuit.png --svg-output data/tracks/experimental/rivazza-valley-circuit/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/rivazza-valley-circuit/rivazza-valley-circuit.xml --output data/tracks/experimental/rivazza-valley-circuit/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Elevation source: Regione Emilia-Romagna Geoportale WCS DTM RER 2022, 0.5 m LiDAR-derived DTM, CC BY 4.0. Local cutout: source/elevation-rer2022/dtm-rer2022-imola-1m.tif.
  Terrain fill source: Regione Emilia-Romagna Geoportale WCS DTM 5x5 ultima edizione, CC BY 4.0. Used only to replace zero/nodata cells in the 0.5 m DTM cutout for terrain
  generation.
