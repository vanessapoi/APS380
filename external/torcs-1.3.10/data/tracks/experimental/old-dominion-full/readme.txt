Old Dominion Full

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n old-dominion-full -i ../data/tracks/experimental/old-dominion-full -o ../data/tracks/experimental/old-dominion-full -a -q
  trackgen -c experimental -n old-dominion-full -i ../data/tracks/experimental/old-dominion-full -o ../data/tracks/experimental/old-dominion-full -r -q
  accc -g ../data/tracks/experimental/old-dominion-full/old-dominion-full.acc -l0 ../data/tracks/experimental/old-dominion-full/old-dominion-full.ac -l1 ../data/tracks/experimental/old-dominion-full/old-dominion-full-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/old-dominion-full/old-dominion-full.xml --polyline data/tracks/experimental/old-dominion-full/source/centerline.json --overlay data/tracks/experimental/old-dominion-full/source/xml-centerline-fit.svg --report data/tracks/experimental/old-dominion-full/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/old-dominion-full/old-dominion-full.xml --output data/tracks/experimental/old-dominion-full/old-dominion-full.png --svg-output data/tracks/experimental/old-dominion-full/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/old-dominion-full/old-dominion-full.xml --output data/tracks/experimental/old-dominion-full/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, banking, terrain heightmap, and generated geometry are derived from USGS 3DEP project VA_FEMA-NRCS_SouthCentral_2017_D17 1 m bare-earth
  DEM tiles 17_x65y405 and 17_x66y405. The data is in NAD83 / UTM zone 17N (EPSG:26917), with NAVD88 elevations in metres, and is public domain. Accessed
  2026-08-16 through The National Map.
