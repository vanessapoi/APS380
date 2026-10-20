Doha Desert Ring

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n doha-desert-ring -i ../data/tracks/experimental/doha-desert-ring -o ../data/tracks/experimental/doha-desert-ring -a -q
  trackgen -c experimental -n doha-desert-ring -i ../data/tracks/experimental/doha-desert-ring -o ../data/tracks/experimental/doha-desert-ring -r -q
  accc -g ../data/tracks/experimental/doha-desert-ring/doha-desert-ring.acc -l0 ../data/tracks/experimental/doha-desert-ring/doha-desert-ring.ac -l1 ../data/tracks/experimental/doha-desert-ring/doha-desert-ring-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/doha-desert-ring/doha-desert-ring.xml --polyline data/tracks/experimental/doha-desert-ring/source/centerline.json --overlay data/tracks/experimental/doha-desert-ring/source/xml-centerline-fit.svg --report data/tracks/experimental/doha-desert-ring/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/doha-desert-ring/doha-desert-ring.xml --output data/tracks/experimental/doha-desert-ring/doha-desert-ring.png --svg-output data/tracks/experimental/doha-desert-ring/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/doha-desert-ring/doha-desert-ring.xml --output data/tracks/experimental/doha-desert-ring/source/segments-labeled.svg

Third-party data:
- The geographic path data is derived from OpenStreetMap contributors,
  principally racing-loop way 152483595 and F1 pit-lane ways 1037707300
  and 196193732. It has been modified to fit TORCS geometry and pit-host
  constraints. The underlying base data is provided under the Open Database
  License (ODbL): https://www.openstreetmap.org/copyright
- Track elevations, terrain heightmap, and generated geometry are derived
  from the Copernicus DEM GLO-30 2021 DSM tile N25 E051, accessed 2026-08-15.
  The source has approximately 30 m posting and is used for broad grades and
  terrain only, not banking. Product information and license:
  https://registry.opendata.aws/copernicus-dem/
  Required attribution: (C) DLR e.V. 2010-2014 and (C) Airbus Defence and
  Space GmbH 2014-2018 provided under COPERNICUS by the European Union and
  ESA; all rights reserved.
