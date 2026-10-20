Brondehach Classic

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n brondehach-classic -i ../data/tracks/experimental/brondehach-classic -o ../data/tracks/experimental/brondehach-classic -a -q
  trackgen -c experimental -n brondehach-classic -i ../data/tracks/experimental/brondehach-classic -o ../data/tracks/experimental/brondehach-classic -r -q
  accc -g ../data/tracks/experimental/brondehach-classic/brondehach-classic.acc -l0 ../data/tracks/experimental/brondehach-classic/brondehach-classic.ac -l1 ../data/tracks/experimental/brondehach-classic/brondehach-classic-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/brondehach-classic/brondehach-classic.xml --polyline data/tracks/experimental/brondehach-classic/source/centerline.json --overlay data/tracks/experimental/brondehach-classic/source/xml-centerline-fit.svg --report data/tracks/experimental/brondehach-classic/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/brondehach-classic/brondehach-classic.xml --output data/tracks/experimental/brondehach-classic/brondehach-classic.png --svg-output data/tracks/experimental/brondehach-classic/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/brondehach-classic/brondehach-classic.xml --output data/tracks/experimental/brondehach-classic/source/segments-labeled.svg

Third-party data:
  The historic plan view is derived from "Brands Hatch 1960-1975.svg" by
  John Chapman (Wikimedia Commons user Pyrope), licensed under Creative
  Commons Attribution-ShareAlike 4.0. Changes include vector-path extraction,
  georeferencing, resampling, published-length scaling, TORCS segment fitting,
  and pit-host reconstruction. Plan-view-derived geometry is distributed under
  CC BY-SA 4.0. Source: https://commons.wikimedia.org/wiki/File:Brands_Hatch_1960-1975.svg

  Geographic alignment and pit-location reference data are derived from
  OpenStreetMap contributors. The modern racing loop is relation 7218462 and
  the pit reference is way 4906930. OSM is used as a coordinate scaffold, not
  as the historic driving layout. The underlying data is provided under ODbL.

  Road elevations, filtered banking, terrain heightmap, and generated terrain
  are derived from Environment Agency National LIDAR Programme DTM 2018 1 m
  data, survey polygon P_10781, tiles TQ5560 and TQ5565, in EPSG:27700 with
  elevations in metres ODN. The data was accessed from the Defra Data Services
  Platform on 2026-08-14 and is licensed under the Open Government Licence
  v3.0. Attribution: Environment Agency copyright and/or database right 2022.
  Raw development tiles are kept under source/ and are not part of the normal
  shippable top-level track package.

Layout preparation:
  The modern SVG layer fits the OSM scaffold at 2.51 m correspondence RMSE.
  The unscaled BNG footprint is retained for LiDAR sampling. A separate loop
  is scaled to the published 4265 m length for TORCS plan-view fitting.

Mainline and curbs:

Pit lane:
  The full modern OSM pit trace was rejected because its 559 m entry/exit span
  includes 11.93 degrees of mainline turn. The 1974 pit location is represented
  on the left side of the start straight by straightening the wrapping draft-80
  to draft-4 host. The left placement avoids overlap with the nearby mainline;
  its minimum estimated side-envelope gap is 8.982 m. Adjacent connector refit
  error is 0.0021 m and effectively zero degrees.

Elevation and banking:
  Raw short banking spikes down to -22.29 degrees were rejected as raster or
  alignment artifacts. Accepted banking is -5.66 to +7.08 degrees; maximum
  generated road grade is 11.10 percent. Terrain-map diff RMSE is 0.052 m.
