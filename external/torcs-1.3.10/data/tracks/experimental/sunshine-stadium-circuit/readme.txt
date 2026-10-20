Sunshine Stadium Circuit

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n sunshine-stadium-circuit -i ../data/tracks/experimental/sunshine-stadium-circuit -o ../data/tracks/experimental/sunshine-stadium-circuit -a -q
  trackgen -c experimental -n sunshine-stadium-circuit -i ../data/tracks/experimental/sunshine-stadium-circuit -o ../data/tracks/experimental/sunshine-stadium-circuit -r -q
  accc -g ../data/tracks/experimental/sunshine-stadium-circuit/sunshine-stadium-circuit.acc -l0 ../data/tracks/experimental/sunshine-stadium-circuit/sunshine-stadium-circuit.ac -l1 ../data/tracks/experimental/sunshine-stadium-circuit/sunshine-stadium-circuit-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/sunshine-stadium-circuit/sunshine-stadium-circuit.xml --polyline data/tracks/experimental/sunshine-stadium-circuit/source/centerline.json --overlay data/tracks/experimental/sunshine-stadium-circuit/source/xml-centerline-fit.svg --report data/tracks/experimental/sunshine-stadium-circuit/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/sunshine-stadium-circuit/sunshine-stadium-circuit.xml --output data/tracks/experimental/sunshine-stadium-circuit/sunshine-stadium-circuit.png --svg-output data/tracks/experimental/sunshine-stadium-circuit/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/sunshine-stadium-circuit/sunshine-stadium-circuit.xml --output data/tracks/experimental/sunshine-stadium-circuit/source/segments-labeled.svg

Third-party assets:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, banking, terrain heightmap, and generated geometry are derived from
  U.S. Geological Survey 3D Elevation Program 1 meter bare-earth DEM tile
  USGS_1M_17_x57y288_FL_MiamiDade_D23, acquired 2023-12-27 through 2024-05-29
  and accessed 2026-08-14. The raster uses EPSG:26917 and NAVD88 metric heights.
  USGS 3DEP data is public domain.
  https://www.sciencebase.gov/catalog/item/69423b62d4be02297efc2c65
