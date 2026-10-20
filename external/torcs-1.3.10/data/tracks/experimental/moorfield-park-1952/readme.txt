Moorfield Park 1952

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n moorfield-park-1952 -i ../data/tracks/experimental/moorfield-park-1952 -o ../data/tracks/experimental/moorfield-park-1952 -a -q
  trackgen -c experimental -n moorfield-park-1952 -i ../data/tracks/experimental/moorfield-park-1952 -o ../data/tracks/experimental/moorfield-park-1952 -r -q
  accc -g ../data/tracks/experimental/moorfield-park-1952/moorfield-park-1952.acc -l0 ../data/tracks/experimental/moorfield-park-1952/moorfield-park-1952.ac -l1 ../data/tracks/experimental/moorfield-park-1952/moorfield-park-1952-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/moorfield-park-1952/moorfield-park-1952.xml --polyline data/tracks/experimental/moorfield-park-1952/source/centerline.json --overlay data/tracks/experimental/moorfield-park-1952/source/xml-centerline-fit.svg --report data/tracks/experimental/moorfield-park-1952/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/moorfield-park-1952/moorfield-park-1952.xml --output data/tracks/experimental/moorfield-park-1952/moorfield-park-1952.png --svg-output data/tracks/experimental/moorfield-park-1952/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/moorfield-park-1952/moorfield-park-1952.xml --output data/tracks/experimental/moorfield-park-1952/source/segments-labeled.svg

Manual elevation corrections:
- Two humps around Becketts were reduced to 0.15 m above the smooth local road elevation trend by editing the live XML z/tangent values.
- The pit lane is manually placed after Woodcote on the right side of the
  Woodcote-to-Copse straight, based on the historic reference image context.
 
Third-party data:
- Track layout based on "Silverstone 1952.jpg" by Jiří Žemlička (2005), released into the public domain by the author,
  adapted for TORCS. Source: https://commons.wikimedia.org/wiki/File:Silverstone_1952.jpg  
- Approximate WGS84 coordinates in source/centerline-image-straights-georef.json
  are derived by correlating the image layout to OpenHistoricalMap contributor
  data and the provided circuit-evolution reference image. The OHM data is used
  only as a coordinate scaffold for later elevation and terrain generation, not
  as the driving layout geometry. The underlying OHM base data is provided under
  the Open Database License (ODbL).
- Track elevations, terrain heightmap, and generated terrain are derived from
  Environment Agency / Defra LIDAR Composite DTM 2022 1 m data, accessed via
  the public survey tile API on 2026-05-17 and licensed under the Open
  Government Licence v3.0. The shared raster cache is kept under the
  Moorfield Park source/elevation-shared-ea-lidar directory.

