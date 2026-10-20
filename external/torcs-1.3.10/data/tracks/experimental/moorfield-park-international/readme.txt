Moorfield Park International

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n moorfield-park-international -i ../data/tracks/experimental/moorfield-park-international -o ../data/tracks/experimental/moorfield-park-international -a -q
  trackgen -c experimental -n moorfield-park-international -i ../data/tracks/experimental/moorfield-park-international -o ../data/tracks/experimental/moorfield-park-international -r -q
  accc -g ../data/tracks/experimental/moorfield-park-international/moorfield-park-international.acc -l0 ../data/tracks/experimental/moorfield-park-international/moorfield-park-international.ac -l1 ../data/tracks/experimental/moorfield-park-international/moorfield-park-international-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/moorfield-park-international/moorfield-park-international.xml --polyline data/tracks/experimental/moorfield-park-international/source/centerline.json --overlay data/tracks/experimental/moorfield-park-international/source/xml-centerline-fit.svg --report data/tracks/experimental/moorfield-park-international/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/moorfield-park-international/moorfield-park-international.xml --output data/tracks/experimental/moorfield-park-international/moorfield-park-international.png --svg-output data/tracks/experimental/moorfield-park-international/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/moorfield-park-international/moorfield-park-international.xml --output data/tracks/experimental/moorfield-park-international/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, and generated terrain are derived from
  Environment Agency / Defra LIDAR Composite DTM 2022 1 m data, accessed via
  the public survey tile API on 2026-05-17 and licensed under the Open
  Government Licence v3.0.