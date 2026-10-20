Seneca Lake Circuit Short

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n seneca-lake-circuit-short -i ../data/tracks/experimental/seneca-lake-circuit-short -o ../data/tracks/experimental/seneca-lake-circuit-short -a -q
  trackgen -c experimental -n seneca-lake-circuit-short -i ../data/tracks/experimental/seneca-lake-circuit-short -o ../data/tracks/experimental/seneca-lake-circuit-short -r -q
  accc -g ../data/tracks/experimental/seneca-lake-circuit-short/seneca-lake-circuit-short.acc -l0 ../data/tracks/experimental/seneca-lake-circuit-short/seneca-lake-circuit-short.ac -l1 ../data/tracks/experimental/seneca-lake-circuit-short/seneca-lake-circuit-short-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/seneca-lake-circuit-short/seneca-lake-circuit-short.xml --polyline data/tracks/experimental/seneca-lake-circuit-short/source/centerline.json --overlay data/tracks/experimental/seneca-lake-circuit-short/source/xml-centerline-fit.svg --report data/tracks/experimental/seneca-lake-circuit-short/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/seneca-lake-circuit-short/seneca-lake-circuit-short.xml --output data/tracks/experimental/seneca-lake-circuit-short/seneca-lake-circuit-short.png --svg-output data/tracks/experimental/seneca-lake-circuit-short/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/seneca-lake-circuit-short/seneca-lake-circuit-short.xml --output data/tracks/experimental/seneca-lake-circuit-short/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, banking, terrain heightmap, and generated geometry are derived from USGS 3D Elevation Program 1 meter DEM data from The National Map,
  tile USGS_1M_18_x34y469_NY_FingerLakes_2020_A20.tif, accessed 2026-05-25. USGS data are public domain in the United States.


