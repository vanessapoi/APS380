South Downs Raceway

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n south-downs-raceway -i ../data/tracks/experimental/south-downs-raceway -o ../data/tracks/experimental/south-downs-raceway -a -q
  trackgen -c experimental -n south-downs-raceway -i ../data/tracks/experimental/south-downs-raceway -o ../data/tracks/experimental/south-downs-raceway -r -q
  accc -g ../data/tracks/experimental/south-downs-raceway/south-downs-raceway.acc -l0 ../data/tracks/experimental/south-downs-raceway/south-downs-raceway.ac -l1 ../data/tracks/experimental/south-downs-raceway/south-downs-raceway-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/south-downs-raceway/south-downs-raceway.xml --polyline data/tracks/experimental/south-downs-raceway/source/centerline.json --overlay data/tracks/experimental/south-downs-raceway/source/xml-centerline-fit.svg --report data/tracks/experimental/south-downs-raceway/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/south-downs-raceway/south-downs-raceway.xml --output data/tracks/experimental/south-downs-raceway/south-downs-raceway.png --svg-output data/tracks/experimental/south-downs-raceway/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/south-downs-raceway/south-downs-raceway.xml --output data/tracks/experimental/south-downs-raceway/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, banking, terrain heightmap, relief terrain, and generated
  geometry are derived primarily from Environment Agency / Defra LIDAR Tiles DTM
  2016 0.5 m last-return data surveyed on 25 November 2016 for tile SU8505. The
  source is EPSG:27700 and elevations are metres referenced to Ordnance Survey
  Great Britain (Newlyn), transformed with OSTN15 and OSGM15. The 2022 LIDAR
  Composite DTM 1 m product fills the landscape outside the 2016 survey footprint.
  Both were downloaded from
  https://environment.data.gov.uk/tiles/collections/survey on 15 August 2026.
  The data is used under the Open Government Licence v3.0.