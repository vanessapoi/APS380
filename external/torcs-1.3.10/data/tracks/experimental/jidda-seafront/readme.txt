Jidda Seafront

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n jidda-seafront -i ../data/tracks/experimental/jidda-seafront -o ../data/tracks/experimental/jidda-seafront -a -q
  trackgen -c experimental -n jidda-seafront -i ../data/tracks/experimental/jidda-seafront -o ../data/tracks/experimental/jidda-seafront -r -q
  accc -g ../data/tracks/experimental/jidda-seafront/jidda-seafront.acc -l0 ../data/tracks/experimental/jidda-seafront/jidda-seafront.ac -l1 ../data/tracks/experimental/jidda-seafront/jidda-seafront-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/jidda-seafront/jidda-seafront.xml --polyline data/tracks/experimental/jidda-seafront/source/centerline.json --overlay data/tracks/experimental/jidda-seafront/source/xml-centerline-fit.svg --report data/tracks/experimental/jidda-seafront/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/jidda-seafront/jidda-seafront.xml --output data/tracks/experimental/jidda-seafront/jidda-seafront.png --svg-output data/tracks/experimental/jidda-seafront/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/jidda-seafront/jidda-seafront.xml --output data/tracks/experimental/jidda-seafront/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, and generated geometry are derived
  from the Copernicus DEM GLO-30 2021 DSM tile N21 E039, accessed 2026-08-09.
  The source has approximately 30 m posting and is used for broad grades and
  terrain only, not banking. Product information and license:
  https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM
