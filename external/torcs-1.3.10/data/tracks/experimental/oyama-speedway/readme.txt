Oyama Speedway

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n oyama-speedway -i ../data/tracks/experimental/oyama-speedway -o ../data/tracks/experimental/oyama-speedway -a -q
  trackgen -c experimental -n oyama-speedway -i ../data/tracks/experimental/oyama-speedway -o ../data/tracks/experimental/oyama-speedway -r -q
  accc -g ../data/tracks/experimental/oyama-speedway/oyama-speedway.acc -l0 ../data/tracks/experimental/oyama-speedway/oyama-speedway.ac -l1 ../data/tracks/experimental/oyama-speedway/oyama-speedway-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/oyama-speedway/oyama-speedway.xml --polyline data/tracks/experimental/oyama-speedway/source/centerline.json --overlay data/tracks/experimental/oyama-speedway/source/xml-centerline-fit.svg --report data/tracks/experimental/oyama-speedway/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/oyama-speedway/oyama-speedway.xml --output data/tracks/experimental/oyama-speedway/oyama-speedway.png --svg-output data/tracks/experimental/oyama-speedway/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/oyama-speedway/oyama-speedway.xml --output data/tracks/experimental/oyama-speedway/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, generated terrain relief, and the road-surface banking profile are derived from Geospatial Information Authority
  of Japan (GSI), GSI DEM5A elevation tiles (dem5a_png), licensed under the Public Data License 1.0 (PDL 1.0).
  Accessed 25 May 2026; processed and adapted for TORCS. Source and terms: https://www.gsi.go.jp/ENGLISH/page_e30286.html
