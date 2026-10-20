Forza Flowkiller

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n forza-flowkiller -i ../data/tracks/experimental/forza-flowkiller -o ../data/tracks/experimental/forza-flowkiller -a -q
  trackgen -c experimental -n forza-flowkiller -i ../data/tracks/experimental/forza-flowkiller -o ../data/tracks/experimental/forza-flowkiller -r -q
  accc -g ../data/tracks/experimental/forza-flowkiller/forza-flowkiller.acc -l0 ../data/tracks/experimental/forza-flowkiller/forza-flowkiller.ac -l1 ../data/tracks/experimental/forza-flowkiller/forza-flowkiller-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/forza-flowkiller/forza-flowkiller.xml --polyline data/tracks/experimental/forza-flowkiller/source/centerline.json --overlay data/tracks/experimental/forza-flowkiller/source/xml-centerline-fit.svg --report data/tracks/experimental/forza-flowkiller/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/forza-flowkiller/forza-flowkiller.xml --output data/tracks/experimental/forza-flowkiller/forza-flowkiller.png --svg-output data/tracks/experimental/forza-flowkiller/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/forza-flowkiller/forza-flowkiller.xml --output data/tracks/experimental/forza-flowkiller/source/segments-labeled.svg

Third-party data:
- The geographic path data of this track is partially derived from OpenStreetMap contributors. It has been significantly modified and extended manually.
  The underlying base data is provided under the Open Database License (ODbL).
- Track elevations, terrain heightmap, and banking are derived from the MASE Piano Straordinario di Telerilevamento "DTM LiDAR con risoluzione a
  terra 1 metro - Regione Lombardia" dataset, layer EL.LIDAR.LOMBARDIA.1x1.DTM, licensed under CC BY 4.0 and accessed 2026-08-15. The downloaded source
  has 1 m ground resolution, meter-valued elevations, and stated vertical accuracy of 0.30 m. Raw source tiles are not part of the shippable track package.
  MASE dataset metadata: https://www.pcn.minambiente.it/geoportal/rest/document?id=m_amte%3A299FN3%3Ae02c7579-8031-4563-fca5-e2f1523fa7d4
  MASE distribution and license: https://gn.mase.gov.it/portale/distribuzione-dati-pst
