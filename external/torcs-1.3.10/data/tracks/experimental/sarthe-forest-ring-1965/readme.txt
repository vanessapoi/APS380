Sarthe Forest Ring 1965

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n sarthe-forest-ring-1965 -i ../data/tracks/experimental/sarthe-forest-ring-1965 -o ../data/tracks/experimental/sarthe-forest-ring-1965 -a -q
  trackgen -c experimental -n sarthe-forest-ring-1965 -i ../data/tracks/experimental/sarthe-forest-ring-1965 -o ../data/tracks/experimental/sarthe-forest-ring-1965 -r -q
  accc -g ../data/tracks/experimental/sarthe-forest-ring-1965/sarthe-forest-ring-1965.acc -l0 ../data/tracks/experimental/sarthe-forest-ring-1965/sarthe-forest-ring-1965.ac -l1 ../data/tracks/experimental/sarthe-forest-ring-1965/sarthe-forest-ring-1965-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/sarthe-forest-ring-1965/sarthe-forest-ring-1965.xml --polyline data/tracks/experimental/sarthe-forest-ring-1965/source/centerline.json --overlay data/tracks/experimental/sarthe-forest-ring-1965/source/xml-centerline-fit.svg --report data/tracks/experimental/sarthe-forest-ring-1965/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/sarthe-forest-ring-1965/sarthe-forest-ring-1965.xml --output data/tracks/experimental/sarthe-forest-ring-1965/sarthe-forest-ring-1965.png --svg-output data/tracks/experimental/sarthe-forest-ring-1965/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/sarthe-forest-ring-1965/sarthe-forest-ring-1965.xml --output data/tracks/experimental/sarthe-forest-ring-1965/source/segments-labeled.svg

Layout
  The Maison Blanche trial adds 15 m to the existing rightward kink using a bounded
  quintic smootherstep deformation. Source points outside the original labels 57-62
  station range are unchanged.

Geographic alignment
  The local drawing was rigidly aligned to OpenStreetMap relation 2126739,
  "Circuit des 24 Heures du Mans".
  
Elevation and terrain
  The historic Mulsanne approach hump is a documented manual reconstruction based on
  period-footage evidence that shows the crest near the signed 500 m approach marker.
  It is not claimed to be a direct LiDAR measurement. The correction fades to the
  modern terrain by 80 m laterally.

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track layout reference: "Le Mans Circuit de la Sarthe 1932-1967" by Hmdwgf, via Wikimedia Commons, licensed under Creative Commons Attribution-ShareAlike 3.0 Unported (CC BY-SA 3.0).
  Source: https://commons.wikimedia.org/wiki/File:Le_Mans_Circuit_de_la_Sarthe_1932-1967.png — License: https://creativecommons.org/licenses/by-sa/3.0/    
- Track elevations, terrain heightmap, and generated geometry are derived from IGN / Geoplateforme LiDAR HD MNT 0.50 m data, served
  via https://data.geopf.fr/wms-r layer IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93, licensed under Licence Ouverte / Open Licence 2.0,
  accessed 18 May 2026.

