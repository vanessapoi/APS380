Forza Classic 1938

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n forza-classic-1938 -i ../data/tracks/experimental/forza-classic-1938 -o ../data/tracks/experimental/forza-classic-1938 -a -q
  trackgen -c experimental -n forza-classic-1938 -i ../data/tracks/experimental/forza-classic-1938 -o ../data/tracks/experimental/forza-classic-1938 -r -q
  accc -g ../data/tracks/experimental/forza-classic-1938/forza-classic-1938.acc -l0 ../data/tracks/experimental/forza-classic-1938/forza-classic-1938.ac -l1 ../data/tracks/experimental/forza-classic-1938/forza-classic-1938-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/forza-classic-1938/forza-classic-1938.xml --polyline data/tracks/experimental/forza-classic-1938/source/centerline.json --overlay data/tracks/experimental/forza-classic-1938/source/xml-centerline-fit.svg --report data/tracks/experimental/forza-classic-1938/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/forza-classic-1938/forza-classic-1938.xml --output data/tracks/experimental/forza-classic-1938/forza-classic-1938.png --svg-output data/tracks/experimental/forza-classic-1938/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/forza-classic-1938/forza-classic-1938.xml --output data/tracks/experimental/forza-classic-1938/source/segments-labeled.svg

Historical reconstruction notes:
  The 1938 Florio Course was nominally listed as 7.000 km for race administration. The complete georeferenced OpenHistoricalMap
  centerline and the generated physical TORCS centerline are approximately 6.7 km; the geometry was not distorted to force the
  nominal accounting distance. Curva Sud uses the original 1922 earth-embankment banking, not the steeper reinforced-concrete
  banking built in 1955. The reconstruction uses a documented 320 m curve radius and a maximum 2.6 m rise across an approximately 12m
  roadbed, giving 12.2 degrees maximum banking. Exact historical transition lengths are not documented, so smooth cosine transitions
  are used. Current terrain data cannot reproduce the demolished road surface. Later-earthwork artifacts over Curva Sud were removed
  with a localized robust elevation filter before the historical banking profile was applied.
  Manual road elevation correction (2026-09-25): removed the bridge-crossing hump at the junction of Curva del Serraglio-8 and -9.
  The current XML uses one cubic Hermite profile across Serraglio-7 through -9 (111.564235 m), preserving the original outer endpoint
  heights (-2.8754 m, -2.7007 m) and grades (-1.7185%, -0.0134%). Internal endpoint heights and tangents were sampled from that cubic;
  the former -1.5693 m crest is now -3.07478231 m. The resulting shallow low point is -3.119429 m and the grade range
  is -1.7185% to +0.786332%. This is a local reconstruction correction, not a surveyed historical elevation.

Third-party data:
- The historical centerline is derived from OpenHistoricalMap relation 2799521, Monza Circuit 1935-1938, provided under the
  OpenHistoricalMap CC0 public-domain dedication. OpenHistoricalMap relation: https://www.openhistoricalmap.org/relation/2799521
- Historical dimensions are based on archived Autodromo Nazionale Monza history pages for 1922-1928 and 1929-1939.
  Official history archive: https://web.archive.org/web/20080611175248/http://www.monzanet.it/eng/storia_1922_28.aspx
- Track terrain and surviving-road elevations are derived from the MASE Piano Straordinario di Telerilevamento "DTM LiDAR con risoluzione
  a terra 1 metro - Regione Lombardia" dataset, layer EL.LIDAR.LOMBARDIA.1x1.DTM, licensed under CC BY 4.0 and accessed 2026-08-15. Raw
  source tiles are not part of the shippable track package.
  MASE dataset metadata: https://www.pcn.minambiente.it/geoportal/rest/document?id=m_amte%3A299FN3%3Ae02c7579-8031-4563-fca5-e2f1523fa7d4
