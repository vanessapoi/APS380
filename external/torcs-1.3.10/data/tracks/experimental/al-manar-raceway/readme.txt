Al Manar Raceway

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n al-manar-raceway -i ../data/tracks/experimental/al-manar-raceway -o ../data/tracks/experimental/al-manar-raceway -a -q
  trackgen -c experimental -n al-manar-raceway -i ../data/tracks/experimental/al-manar-raceway -o ../data/tracks/experimental/al-manar-raceway -r -q
  accc -g ../data/tracks/experimental/al-manar-raceway/al-manar-raceway.acc -l0 ../data/tracks/experimental/al-manar-raceway/al-manar-raceway.ac -l1 ../data/tracks/experimental/al-manar-raceway/al-manar-raceway-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/al-manar-raceway/al-manar-raceway.xml --polyline data/tracks/experimental/al-manar-raceway/source/centerline.json --overlay data/tracks/experimental/al-manar-raceway/source/xml-centerline-fit.svg --report data/tracks/experimental/al-manar-raceway/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/al-manar-raceway/al-manar-raceway.xml --output data/tracks/experimental/al-manar-raceway/al-manar-raceway.png --svg-output data/tracks/experimental/al-manar-raceway/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/al-manar-raceway/al-manar-raceway.xml --output data/tracks/experimental/al-manar-raceway/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Elevation derived from Copernicus DEM GLO-30, produced using Copernicus WorldDEM-30 (C) DLR e.V. 2010-2014 and (C) Airbus Defence and Space GmbH 2014-2018,
  provided under COPERNICUS by the European Union and ESA; no Copernicus programme liability is accepted for its use.

