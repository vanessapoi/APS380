Dunevoort

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n dunevoort -i ../data/tracks/experimental/dunevoort -o ../data/tracks/experimental/dunevoort -a -q
  trackgen -c experimental -n dunevoort -i ../data/tracks/experimental/dunevoort -o ../data/tracks/experimental/dunevoort -r -q
  accc -g ../data/tracks/experimental/dunevoort/dunevoort.acc -l0 ../data/tracks/experimental/dunevoort/dunevoort.ac -l1 ../data/tracks/experimental/dunevoort/dunevoort-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/dunevoort/dunevoort.xml --polyline data/tracks/experimental/dunevoort/source/centerline.json --overlay data/tracks/experimental/dunevoort/source/xml-centerline-fit.svg --report data/tracks/experimental/dunevoort/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/dunevoort/dunevoort.xml --output data/tracks/experimental/dunevoort/dunevoort.png --svg-output data/tracks/experimental/dunevoort/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/dunevoort/dunevoort.xml --output data/tracks/experimental/dunevoort/source/segments-labeled.svg

  Manual post-process: Hugenholtzbocht banking adjusted to a smooth peak of about 19 degrees after AHN sampling under-estimated this banked corner.

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, relief geometry, and most banking are derived from PDOK / Rijkswaterstaat Actueel Hoogtebestand Nederland (AHN4) DTM 0.5 m WCS data,
  licensed CC0 / public domain, accessed 25 May 2026.
