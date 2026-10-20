Pelican Bay Oval

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n pelican-bay-oval -i ../data/tracks/experimental/pelican-bay-oval -o ../data/tracks/experimental/pelican-bay-oval -a -q
  trackgen -c experimental -n pelican-bay-oval -i ../data/tracks/experimental/pelican-bay-oval -o ../data/tracks/experimental/pelican-bay-oval -r -q
  accc -g ../data/tracks/experimental/pelican-bay-oval/pelican-bay-oval.acc -l0 ../data/tracks/experimental/pelican-bay-oval/pelican-bay-oval.ac -l1 ../data/tracks/experimental/pelican-bay-oval/pelican-bay-oval-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/pelican-bay-oval/pelican-bay-oval.xml --polyline data/tracks/experimental/pelican-bay-oval/source/centerline.json --overlay data/tracks/experimental/pelican-bay-oval/source/xml-centerline-fit.svg --report data/tracks/experimental/pelican-bay-oval/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/pelican-bay-oval/pelican-bay-oval.xml --output data/tracks/experimental/pelican-bay-oval/pelican-bay-oval.png --svg-output data/tracks/experimental/pelican-bay-oval/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/pelican-bay-oval/pelican-bay-oval.xml --output data/tracks/experimental/pelican-bay-oval/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Road elevation, banking, and terrain heightmap data are derived from USGS_OPR_FL_Peninsular_2018_D18 DEM tiles distributed by the U.S. Geological Survey;
  USGS-authored or produced data are U.S. Public Domain.
