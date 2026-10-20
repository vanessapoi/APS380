Peconic Bay Circuit

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n peconic-bay-circuit -i ../data/tracks/experimental/peconic-bay-circuit -o ../data/tracks/experimental/peconic-bay-circuit -a -q
  trackgen -c experimental -n peconic-bay-circuit -i ../data/tracks/experimental/peconic-bay-circuit -o ../data/tracks/experimental/peconic-bay-circuit -r -q
  accc -g ../data/tracks/experimental/peconic-bay-circuit/peconic-bay-circuit.acc -l0 ../data/tracks/experimental/peconic-bay-circuit/peconic-bay-circuit.ac -l1 ../data/tracks/experimental/peconic-bay-circuit/peconic-bay-circuit-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/peconic-bay-circuit/peconic-bay-circuit.xml --polyline data/tracks/experimental/peconic-bay-circuit/source/centerline.json --overlay data/tracks/experimental/peconic-bay-circuit/source/xml-centerline-fit.svg --report data/tracks/experimental/peconic-bay-circuit/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/peconic-bay-circuit/peconic-bay-circuit.xml --output data/tracks/experimental/peconic-bay-circuit/peconic-bay-circuit.png --svg-output data/tracks/experimental/peconic-bay-circuit/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/peconic-bay-circuit/peconic-bay-circuit.xml --output data/tracks/experimental/peconic-bay-circuit/source/segments-labeled.svg

Third-party data:
- The track layout was derived from OpenHistoricalMap way 198179678 ("Bridgehampton"), which is covered by OpenHistoricalMap's CC0 public-domain dedication.
- Elevation data was sampled from the USGS National Elevation Dataset 1/3 arcsecond GeoTIFF tile n41w073 after local reprojection to UTM18N. USGS-authored
  or produced data and information are considered U.S. public domain.