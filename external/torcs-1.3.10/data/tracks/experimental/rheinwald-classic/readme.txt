Rheinwald Classic

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n rheinwald-classic -i ../data/tracks/experimental/rheinwald-classic -o ../data/tracks/experimental/rheinwald-classic -a -q
  trackgen -c experimental -n rheinwald-classic -i ../data/tracks/experimental/rheinwald-classic -o ../data/tracks/experimental/rheinwald-classic -r -q
  accc -g ../data/tracks/experimental/rheinwald-classic/rheinwald-classic.acc -l0 ../data/tracks/experimental/rheinwald-classic/rheinwald-classic.ac -l1 ../data/tracks/experimental/rheinwald-classic/rheinwald-classic-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/rheinwald-classic/rheinwald-classic.xml --polyline data/tracks/experimental/rheinwald-classic/source/centerline.json --overlay data/tracks/experimental/rheinwald-classic/source/xml-centerline-fit.svg --report data/tracks/experimental/rheinwald-classic/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/rheinwald-classic/rheinwald-classic.xml --output data/tracks/experimental/rheinwald-classic/rheinwald-classic.png --svg-output data/tracks/experimental/rheinwald-classic/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/rheinwald-classic/rheinwald-classic.xml --output data/tracks/experimental/rheinwald-classic/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Road elevation, filtered banking, generated terrain heightmap, and relief guide geometry are derived from LGL Baden-Wuerttemberg Open GeoData DGM025 data.
  Dataset: Digitales Gelaendemodell DGM025, 0.25 m GeoTIFF tiles, ETRS89/UTM, DHHN2016 heights.
  Provider: Landesamt fuer Geoinformation und Landentwicklung Baden-Wuerttemberg (LGL), Open GeoData Portal.
  Data license: Datenlizenz Deutschland - Namensnennung - Version 2.0. Access date: 2026-06-21
