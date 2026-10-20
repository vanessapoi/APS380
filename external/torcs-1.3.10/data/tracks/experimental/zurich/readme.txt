Zurich

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n zurich -i ../data/tracks/experimental/zurich -o ../data/tracks/experimental/zurich -a -q
  trackgen -c experimental -n zurich -i ../data/tracks/experimental/zurich -o ../data/tracks/experimental/zurich -r -q
  accc -g ../data/tracks/experimental/zurich/zurich.acc -l0 ../data/tracks/experimental/zurich/zurich.ac -l1 ../data/tracks/experimental/zurich/zurich-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/zurich/zurich.xml --polyline data/tracks/experimental/zurich/source/centerline.json --overlay data/tracks/experimental/zurich/source/xml-centerline-fit.svg --report data/tracks/experimental/zurich/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/zurich/zurich.xml --output data/tracks/experimental/zurich/zurich.png --svg-output data/tracks/experimental/zurich/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/zurich/zurich.xml --output data/tracks/experimental/zurich/source/segments-labeled.svg

Third-party data:
- Track layout reference: "Zurich E Prix Layout" by Cammellovolante, via Wikimedia Commons, licensed under Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0).
  Source: https://commons.wikimedia.org/wiki/File:Zurich_E_Prix_Layout.png — License: https://creativecommons.org/licenses/by-sa/4.0/
