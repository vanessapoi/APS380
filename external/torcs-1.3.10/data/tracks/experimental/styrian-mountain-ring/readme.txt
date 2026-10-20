Styrian Mountain Ring

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating accepted track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n styrian-mountain-ring -i ../data/tracks/experimental/styrian-mountain-ring -o ../data/tracks/experimental/styrian-mountain-ring -a -q
  trackgen -c experimental -n styrian-mountain-ring -i ../data/tracks/experimental/styrian-mountain-ring -o ../data/tracks/experimental/styrian-mountain-ring -r -q
  accc -g ../data/tracks/experimental/styrian-mountain-ring/styrian-mountain-ring.acc -l0 ../data/tracks/experimental/styrian-mountain-ring/styrian-mountain-ring.ac -l1 ../data/tracks/experimental/styrian-mountain-ring/styrian-mountain-ring-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es
  Serialize accc runs because stripe uses shared temporary files.

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/styrian-mountain-ring/styrian-mountain-ring.xml --polyline data/tracks/experimental/styrian-mountain-ring/source/centerline.json --overlay data/tracks/experimental/styrian-mountain-ring/source/xml-centerline-fit.svg --report data/tracks/experimental/styrian-mountain-ring/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/styrian-mountain-ring/styrian-mountain-ring.xml --output data/tracks/experimental/styrian-mountain-ring/styrian-mountain-ring.png --svg-output data/tracks/experimental/styrian-mountain-ring/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/styrian-mountain-ring/styrian-mountain-ring.xml --output data/tracks/experimental/styrian-mountain-ring/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, and generated terrain are derived from:
  Airborne Laserscanning-based Digital Terrain Model, Gelaendehoehe_Gesamtmodell (WCS Coverage4).
  Provider: Land Steiermark / GIS-Steiermark.
  Resolution: 1 m bare-earth DTM.
  Horizontal CRS: WGS 84 / UTM zone 33N (EPSG:32633).
  WCS service: https://gis.stmk.gv.at/arcgis/services/OGD/ALSGelaendeinformation_1m_UTM33N/MapServer/WCSServer
  Metadata and download information: https://www.landesentwicklung.steiermark.at/cms/beitrag/12850529/143660187/
  Downloaded subset: Coverage4, x(480500,483200), y(5228800,5231100).
  Accessed: 2026-08-09.
  License: Creative Commons Attribution 4.0 International (CC BY 4.0).
  https://creativecommons.org/licenses/by/4.0/
  Required attribution: Land Steiermark / GIS-Steiermark.
