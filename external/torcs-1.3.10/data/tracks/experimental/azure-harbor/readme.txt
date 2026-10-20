Azure Harbor

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n azure-harbor -i ../data/tracks/experimental/azure-harbor -o ../data/tracks/experimental/azure-harbor -a -q
  trackgen -c experimental -n azure-harbor -i ../data/tracks/experimental/azure-harbor -o ../data/tracks/experimental/azure-harbor -r -q
  accc -g ../data/tracks/experimental/azure-harbor/azure-harbor.acc -l0 ../data/tracks/experimental/azure-harbor/azure-harbor.ac -l1 ../data/tracks/experimental/azure-harbor/azure-harbor-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/azure-harbor/azure-harbor.xml --polyline data/tracks/experimental/azure-harbor/source/centerline.json --overlay data/tracks/experimental/azure-harbor/source/xml-centerline-fit.svg --report data/tracks/experimental/azure-harbor/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/azure-harbor/azure-harbor.xml --output data/tracks/experimental/azure-harbor/azure-harbor.png --svg-output data/tracks/experimental/azure-harbor/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/azure-harbor/azure-harbor.xml --output data/tracks/experimental/azure-harbor/source/segments-labeled.svg

  The covered Boulevard Louis II tunnel road profile is manually derived from
  portal elevations because the bare-earth terrain raster represents the
  ground above the tunnel rather than the road surface below it. Terrain above
  the tunnel remains derived from RGE ALTI. The exposed Boulevard Louis II-6
  through -7 braking approach has a manual smooth descent to a level Nouvelle
  Chicane floor.

  Raster cross-road samples affected by urban walls and terrain slopes were
  filtered after visual review. Inward banking is retained up to 4 degrees;
  outward-hanging banking is levelled. The reclaimed harbor road from Circuit
  de Monaco-15 through Circuit de Monaco-26, including Route de la Piscine, is
  manually held nearly level.

  The real harbor pit lane is curved beyond TORCS side-pit constraints. The
  generated 20-box pit lane keeps its approximate location while straightening
  a 300 m central Boulevard Albert 1er host. Pit structures are placed on the
  left side to avoid overlap with the circuit.

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, and generated terrain geometry are derived from RGE ALTI (C) IGN, approximately 2 m WMS
  extraction from ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES, licensed under Licence Ouverte / Open Licence 2.0, accessed 2026-08-13.
