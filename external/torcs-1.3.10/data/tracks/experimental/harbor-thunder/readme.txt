Harbor Thunder

Category: experimental

Copyright (C) 2026 by Bernhard Wymann

Copyleft: this work of art is free, you can redistribute
it and/or modify it according to terms of the Free Art license.
You will find a specimen of this license on the site
Copyleft Attitude http://artlibre.org as well as on other sites.

Regenerating track models:
  From the solution runtime directory, with trackgen, accc, stripe, and the shared
  texture/surface pool installed. The input/output directory is the tracked package:
  trackgen -c experimental -n harbor-thunder -i ../data/tracks/experimental/harbor-thunder -o ../data/tracks/experimental/harbor-thunder -a -q
  trackgen -c experimental -n harbor-thunder -i ../data/tracks/experimental/harbor-thunder -o ../data/tracks/experimental/harbor-thunder -r -q
  accc -g ../data/tracks/experimental/harbor-thunder/harbor-thunder.acc -l0 ../data/tracks/experimental/harbor-thunder/harbor-thunder.ac -l1 ../data/tracks/experimental/harbor-thunder/harbor-thunder-trk-raceline.ac -d3 1000 -d2 500 -d1 300 -S 300 -es

Refreshing review SVGs and the menu map:
  From the solution root with torcs-tracktools installed:
  torcs-compare-overlay --align-closed --track-xml data/tracks/experimental/harbor-thunder/harbor-thunder.xml --polyline data/tracks/experimental/harbor-thunder/source/centerline.json --overlay data/tracks/experimental/harbor-thunder/source/xml-centerline-fit.svg --report data/tracks/experimental/harbor-thunder/source/xml-centerline-fit-report.json
  torcs-render-track-map --track-xml data/tracks/experimental/harbor-thunder/harbor-thunder.xml --output data/tracks/experimental/harbor-thunder/harbor-thunder.png --svg-output data/tracks/experimental/harbor-thunder/source/track-map.svg
  torcs-render-labeled-segments-svg --track-xml data/tracks/experimental/harbor-thunder/harbor-thunder.xml --output data/tracks/experimental/harbor-thunder/source/segments-labeled.svg

Third-party data:
- The plan view is derived from "Helsinki_Thunder_track_map--1997_version.svg" by
  Will Pittenger, licensed under Creative Commons Attribution-Share Alike 3.0 Unported
  https://commons.wikimedia.org/wiki/File:Helsinki_Thunder_track_map--1997_version.svg