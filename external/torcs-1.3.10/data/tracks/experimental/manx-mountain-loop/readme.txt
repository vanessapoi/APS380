Manx Mountain Loop

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

This TORCS track is inspired by the public-road mountain course on the Isle of
Man. The constant road width is 9 m. It has bounded inside and raceline-guided
outside curbs, 20 right-side pit boxes, Copernicus-derived elevation and broad
terrain and manually added two-degree banking in significant turns.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n manx-mountain-loop -i ../data/tracks/experimental/manx-mountain-loop -o ../data/tracks/experimental/manx-mountain-loop -a -q
  trackgen -c experimental -n manx-mountain-loop -i ../data/tracks/experimental/manx-mountain-loop -o ../data/tracks/experimental/manx-mountain-loop -r -q
  accc -g ../data/tracks/experimental/manx-mountain-loop/manx-mountain-loop.acc -l0 ../data/tracks/experimental/manx-mountain-loop/manx-mountain-loop.ac -l1 ../data/tracks/experimental/manx-mountain-loop/manx-mountain-loop-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/manx-mountain-loop/manx-mountain-loop.xml --polyline data/tracks/experimental/manx-mountain-loop/source/centerline.json --overlay data/tracks/experimental/manx-mountain-loop/source/xml-centerline-fit.svg --report data/tracks/experimental/manx-mountain-loop/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/manx-mountain-loop/manx-mountain-loop.xml --output data/tracks/experimental/manx-mountain-loop/manx-mountain-loop.png --svg-output data/tracks/experimental/manx-mountain-loop/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/manx-mountain-loop/manx-mountain-loop.xml --output data/tracks/experimental/manx-mountain-loop/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
  The source was fetched through public Overpass API endpoints on 2026-08-09. The checkpoint-constrained extraction uses OSM A2, A1, A3, and A18
  road geometry. Its source length is approximately 60.510 km compared with the documented 60.718 km course length. A checkpoint-induced Ballacraine spur
  and a dead-end Governor's Road stub were removed. The exact historic Governor's Dip remains deferred for a later detailed-source pass.
- Elevation source: Copernicus DEM GLO-30 digital surface model, tile Copernicus_DSM_COG_10_N54_00_W005_00_DEM, downloaded on 2026-08-10 and
  reprojected from EPSG:4326 to EPSG:27700 at 30 m spacing. The track elevation, terrain heightmap, and generated geometry are derived from this dataset.
  Copernicus GLO-30 attribution: Produced using Copernicus WorldDEM-30 (C) DLR e.V. 2010-2014 and (C) Airbus Defence and Space GmbH 2014-2018 provided
  under COPERNICUS by the European Union and ESA
