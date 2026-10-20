# Optional v4 track georeference

`Georeference` is an optional top-level section. All values refer to the
main road centre at the beginning of the first segment (`track->seg->next`),
the simulated start/finish line. This is not the normalized world origin.

```xml
<section name="Georeference">
  <attnum name="latitude" unit="deg" val="45.1234567"/>
  <attnum name="longitude" unit="deg" val="7.1234567"/>
  <attnum name="altitude" unit="m" val="230.5"/>
  <attnum name="heading" unit="deg" val="90"/>
</section>
```

Latitude/longitude are WGS84 degrees, north/east positive. Altitude is metres
above approximate mean sea level, not ellipsoidal GPS height. Heading is the
forward road tangent clockwise from **true north**, not grid/magnetic north
or the transverse painted line. Each value may be omitted; latitude and
longitude must be supplied together. Zero and negative altitude are valid.
An absent section is normal, including for fantasy tracks.

`tTrack::georeference` stores degrees for latitude/longitude, metres for
altitude, and radians for heading. Its three availability flags distinguish
unknown values from zero. The existing tdble parameter reader has metre-scale
geographic precision. Invalid or incomplete values do not prevent loading.

For a future GPS conversion, subtract the loaded first segment's start-edge
midpoint from world coordinates, rotate horizontal displacement from the
simulated start tangent to the geographic tangent, and convert east/north
metres to geographic displacement. Altitude is reference altitude plus world
z minus reference road z. No runtime conversion is implemented here.

Authoring tools must recompute or invalidate the reference when changing the
start position/direction. A template's location must not be inherited when
replacing its layout. Relative-only elevation does not establish sea-level
altitude. Terrain minimum/maximum altitude attributes are not this datum.

## Authoring tools

`torcs-polyline-to-torcs` retains geographic source coordinates and the actual
fitted start pose in its intermediate segment JSON, tied to the XML snippet by
a SHA-256 fingerprint. `torcs-apply-segments` automatically uses the matching
JSON sidecar, including when a different starting segment is selected. An
explicit `--georeference-source <centerline.json>` also works with other fitters
or older snippets. Unreferenced x/y input produces no location. Projected input
requires an explicit `crs` (top level or inside `source`). Grid bearings are
converted to true bearings.

Mainline rebuild finalizes the reference against its accepted source. Pit
integration removes the old reference after start rotation, and recomputes it
when `--mainline-source` is supplied. Geometric closure invalidates metadata
when rebuilding/reordering the segment list and recomputes it when supplied
`--source-polyline`. Horizontal refresh preserves altitude when the pre-edit
ordered geometry and reference elevation are unchanged; otherwise altitude is
invalidated. Reapply metadata after any other manual start relocation.
Elevation application updates altitude from absolute input profiles and clears
it for relative-only elevation. Banking-only application preserves altitude.

### Enrich an existing track without regenerating it

From the solution root, with the tracktools environment active:

```text
torcs-georeference-track --track-xml runtime/tracks/road/example/example.xml --source runtime/tracks/road/example/source/centerline-prepared.json --report example-georeference.json
torcs-georeference-track --tracks-root runtime/tracks --report georeference-summary.json --write
```

Without `--write` this is a dry run. Batch mode discovers tracks with `source/`
directories. Existing sections are skipped, never silently overwritten.
The equivalent module command is `python -m torcs_track_tools.cli.georeference_track`.

The tool fits final geometry to source coordinates with cyclic start/direction
search and no scale change. Ambiguous or poor fits are rejected (default maximum
paired RMSE 20 m). For deliberately scaled historical layouts, an existing
accepted projected elevation-profile transform can establish the anchor if its
stored `track_plan_sha256` fingerprint matches the ordered live layout. Raster
profile import records this fingerprint independently of elevation/formatting.
Legacy profiles without a fingerprint are not trusted for this fallback: a
`track_xml` path alone cannot prove which geometry was originally fitted.
The transform's scale is recorded in the report and is not introduced into
runtime coordinates. This restriction does not prevent extracting altitude
from the geographic samples in legacy profiles or fitting the source directly.

Altitude extraction supports absolute raster road profiles and DEM corridor
profiles, accounting for source station shifts. It prefers road-surface/raster
profiles to older terrain corridors. If those profiles are misaligned, it can
sample their local DEM directly at the independently recovered geographic
anchor. These are approximate sea-level elevations using the source's vertical
datum; no geoid conversion is performed. Missing evidence leaves altitude absent.

Writes insert only the new section, preserving original XML bytes, entities,
BOM, line endings, and formatting. A `source/georeference-report.json` records
provenance, fit error, altitude method, and before/after XML hashes. Batch results
also report unsupported or missing sources. No trackgen, geometry, raster,
texture, preview, or raceline regeneration is involved.
