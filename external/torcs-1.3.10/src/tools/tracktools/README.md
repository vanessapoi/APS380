# Track Tools {#track_tools}

These command-line tools help you turn a map or drawing of a racing circuit into a TORCS track, and improve tracks you already have. They can follow the circuit's centerline, convert it into TORCS straights and bends, make the lap join up, add curbs and pits, and apply hills and banking from elevation data.

The Python tools produce track XML, intermediate data, and preview images. TORCS's separate `trackgen` program builds the 3D track model; `accc` can combine additional visual layers such as a raceline. You still inspect the previews and test the result in TORCS. These are authoring tools run from a terminal, rather than an interactive track editor.

The usual journey is **map or drawing → track layout → curbs and pits → elevation → 3D generation → in-game check**. You can also use individual tools on an existing track, for example to generate its menu map.

For the underlying XML format and how TORCS represents roads, sides, surfaces, and terrain, see the [Track Manual](../../doc/track_manual.md).

**Contents**

- [Terms Used in This Guide](#terms-used-in-this-guide)
- [Installation](#installation)
- [Quick Workflow](#quick-workflow)
- [How The Scripts Fit Together](#how-the-scripts-fit-together)
- [Elevation And Terrain](#elevation-and-terrain)
- [SVG Centerline Workflow](#svg-centerline-workflow)
- [Centerline Georeferencing Workflow](#centerline-georeferencing-workflow)
- [Image/Drawing Centerline Workflow](#imagedrawing-centerline-workflow)
- [Track Menu Map](#track-menu-map)
- [Real Pitlane Workflow](#real-pitlane-workflow)
- [Finding OSM Data](#finding-osm-data)
- [OSM Filtering Checklist](#osm-filtering-checklist)
- [Common Scenarios](#common-scenarios)
- [Validation Checklist](#validation-checklist)
- [Developer Checks](#developer-checks)

<a name="terms-used-in-this-guide"></a>

## Terms Used in This Guide

**Station** is a position measured in meters along the track's centerline, starting from a chosen zero point and following the loop's direction. Station `800` means “800 meters along the centerline,” not 800 meters in a straight line from the start. It is a distance along the layout in plan view, rather than a distance measured over hills or along a driver's racing line.

**Source stations and XML stations can differ.** A source map may start elsewhere, run in the opposite direction, or have a slightly different lap length from the fitted TORCS track. XML station zero is the beginning of the first track segment, at the simulated start/finish line; source station zero is the start chosen for the source loop. A *station mapping* matches positions between the two, so a hill or banking zone lands at the intended place. Keep that mapping with imported profiles, especially after moving the start line or adding pits.

| Term | Meaning here |
| --- | --- |
| Centerline / mainline | The line around the middle of the racing circuit, excluding the pit lane. A *polyline* stores a line as an ordered list of points. |
| Segment | One straight or bend in the TORCS definition: `str` = straight, `lft` = left turn, `rgt` = right turn. Left and right follow the driving direction. |
| Closure / seam | Making the end of the lap meet the beginning at the same position and direction. The seam is that join. |
| Plan view / heading / pose | The horizontal layout seen from above / the direction a segment faces / its position and direction together. |
| Elevation / banking | Height along the track / the road's sideways tilt. An elevation *profile* describes height at successive stations. |
| Pit host / taper | The main-track segment or sequence beside which pits are placed / a gradual change in side width at an entry or exit. |
| Cache / overlay | Saved source or intermediate data for reuse / a preview drawing showing layouts together so differences are visible. SVG previews open in a web browser. |
| Staging / promotion / live XML | Working on a candidate file / making the checked candidate the active track / the XML currently used by that track. |
| Gate / residual / dry run | A check against an allowed limit / the remaining mismatch, such as a small gap at the seam / a check that reports results without applying edits. |
| Raster / heightmap / relief | A grid of values, such as image pixels or elevations / an image encoding terrain heights / lines that guide terrain generation. |

OpenStreetMap (**OSM**) is a public map database. An OSM *way* is an ordered line of map points; a *relation* groups ways, sometimes covering several circuit variants. OpenHistoricalMap (**OHM**) provides historical map data. *Overpass* is the query service used to retrieve these map objects.

A **DEM** (digital elevation model) stores ground heights. A **DTM** (digital terrain model) describes bare-earth terrain rather than tree tops or roofs; **LiDAR** is laser-survey data from which such models can be made. A **CRS** (coordinate reference system) tells the tools how map coordinates locate points on Earth. *Georeferencing* places a drawing in those real-world coordinates. A *bbox* is the rectangular bounding box enclosing an area. Vertical units and the height reference (*vertical datum*) must be checked separately from the horizontal CRS.

<a name="installation"></a>

## Installation

Choose **one** of Conda, venv, or uv below to install the package dependencies in an isolated environment. The package requires Python **3.12 or newer**; the supplied setup uses 3.12. You also need a working TORCS/`trackgen` installation for layout closure, model generation, and in-game checks; installing this Python package does not build those programs.

Run the setup commands below from `torcs/torcs/src/tools/tracktools/`, where `environment.yml` and `pyproject.toml` live. For authoring, switch to the TORCS project root as described in [Quick Workflow](#quick-workflow).

The examples use **PowerShell** and the Windows `runtime/` tree. A trailing backtick continues a command on the next line; in Bash, use a backslash instead, or put the command on one line. Replace placeholders such as `<name>` and `<chosen-layout>` with your values, without the angle brackets. The `.ps1` setup scripts and `.exe` examples are Windows-specific; use the corresponding executable and data paths for your installation on other platforms.

### Conda

```powershell
conda env create -f environment.yml
conda run -n torcs-tracktools pytest
conda run -n torcs-tracktools torcs-rebuild-mainline --help
```

If the environment already exists, update it after dependency changes:

```powershell
conda env update -n torcs-tracktools -f environment.yml
```

`conda run` executes commands inside an existing environment; it does not install missing dependencies by itself.

### venv

```powershell
scripts\setup-venv.ps1
.venv\Scripts\python -m pytest
.venv\Scripts\torcs-rebuild-mainline --help
```

### uv

```powershell
scripts\setup-uv.ps1
uv run pytest
uv run torcs-rebuild-mainline --help
```

The console commands are declared in `pyproject.toml`, so Conda, venv, and uv should all run the same entry points after the environment has been installed or refreshed. If a command is missing, update/reinstall the editable environment before falling back to `python -m torcs_track_tools.cli.<module> --help`.

The authoring examples below use `conda run -n torcs-tracktools`. With venv, activate the installed environment and omit that prefix, or use the full path to its executable. With uv, run from the TORCS root using `uv run --project src/tools/tracktools <command> ...` so uv finds the package while track paths remain relative to the TORCS root.

<a name="quick-workflow"></a>

## Quick Workflow

Run commands from the TORCS project root, `torcs/torcs/`, unless noted otherwise. The project root is the directory containing `TORCS.sln`; if your checkout has an outer workspace parent, that parent is not the TORCS project root. If you run examples that use `runtime/tracks/...` from the outer folder, they create or read a wrong top-level `runtime/...` tree.

Path rules:

- From `torcs/torcs/`, use `runtime/tracks/<category>/<name>/...` and `--runtime-dir runtime` or an absolute runtime path.
- From `torcs/torcs/runtime/`, use `tracks/<category>/<name>/...` and `--runtime-dir .`.
- From any other working directory, use absolute paths for all file arguments, not a mix of relative `runtime/...` paths and absolute `--runtime-dir`.
- Run `trackgen.exe` from `torcs/torcs/runtime/`; it resolves `tracks/...` relative to the current directory.
- If a command writes files under a top-level `runtime/` sibling of `torcs/`, stop and rerun from `torcs/torcs/` or use absolute paths.

1. **Choose a source.** Keep maps and saved source data in `runtime/tracks/<category>/<name>/source/`.
2. **Extract one racing loop.** For OSM, follow [Finding OSM Data](#finding-osm-data): list the available layouts before fetching the chosen one. For drawings, use the SVG or image workflow below instead. These are alternative starting points, not steps you must all perform.
3. **Inspect the source.** Check the preview for the intended layout, scale, and direction before converting it to TORCS segments.
4. **Build a lap without pits.** Run `torcs-rebuild-mainline --closure-solver geometric`. It fits straights and bends, joins the lap ends, and adjusts side areas that would cross or overlap.
5. **Check the basic layout.** Accept it only if `source/closure-report-mainline.json` has `"ok": true`, side-clearance and side-overlap reports have no unresolved issues, `trackgen -z` reports `pits = 0`, and direction is correct in game.
6. **Add curbs if wanted.** Rebuild with `--place-curbs`. If curb placement splits segments, the tool closes the lap again and writes `source/closure-report-curbs-geometric.json`.
7. **Add pits if wanted.** Use the accepted layout as the starting point; the default is `20` pit slots. Close and check the result again using the pit workflow below.
8. **Add hills and banking.** Follow [Elevation And Terrain](#elevation-and-terrain) after the layout for this pass is accepted. For raster-backed elevation, generate the matching terrain heightmap in the same apply pass unless you only want to change the road.
9. **Generate and drive.** Use `trackgen -q` for fast visual iteration and `trackgen -a -q` for full track-and-terrain milestones. Refresh any raceline/ACC layers and the menu map after relevant changes, then run the final validation checklist.

If direction is wrong in game, rebuild with `--reverse-input` instead of editing XML by hand.

### Rebuild Examples And Closure Details

The default Y closure gate is `0.001m` because `trackgen` commonly reports a sub-millimeter quantized residual such as `0.000977`; keep X and angle gates strict unless there is a documented reason to widen them. The legacy closer remains available for comparison, but the recommended workflow passes `--closure-solver geometric` explicitly.

Normal cached rebuild:

```powershell
conda run -n torcs-tracktools torcs-rebuild-mainline `
  --input runtime/tracks/road/<name>/source/centerline-osm.json `
  --output-track-xml runtime/tracks/road/<name>/<name>.xml `
  --closure-solver geometric
```

Reverse race direction from the source order:

```powershell
conda run -n torcs-tracktools torcs-rebuild-mainline `
  --input runtime/tracks/road/<name>/source/centerline-osm.json `
  --output-track-xml runtime/tracks/road/<name>/<name>.xml `
  --reverse-input `
  --closure-solver geometric
```

Legacy polyline fallback for comparison or recovery:

```powershell
conda run -n torcs-tracktools torcs-rebuild-mainline `
  --input runtime/tracks/road/<name>/source/centerline-osm.json `
  --output-track-xml runtime/tracks/road/<name>/<name>.xml `
  --segment-fitter polyline
```

For OpenHistoricalMap sources, use OHM's Overpass interpreter with `--overpass-url`. Keep OHM caches distinct from regular OSM caches, for example `centerline-ohm.json`:

```powershell
conda run -n torcs-tracktools torcs-fetch-centerline `
  --way-ids <ohm-way-id>[,<ohm-way-id>...] `
  --overpass-url https://overpass-api.openhistoricalmap.org/api/interpreter `
  --output runtime/tracks/road/<name>/source/centerline-ohm.json `
  --force
```

If a coarse historic/OHM trace has good source coverage but a large seam heading mismatch, try a detail-preserving rebuild before changing low-level fitter settings:

```powershell
conda run -n torcs-tracktools torcs-rebuild-mainline `
  --input runtime/tracks/road/<name>/source/centerline-ohm.json `
  --output-track-xml runtime/tracks/road/<name>/<name>.xml `
  --profile drawing-detail `
  --closure-solver geometric `
  --no-fit-cache
```

Only widen hidden baseline gates such as `--max-baseline-ang` for diagnosis or confirmed coarse-source recovery, and still accept the result only when `source/closure-report-mainline.json` has `"ok": true`, side-cleanup reports have no unresolved issues, and `trackgen -z` passes.

<a name="how-the-scripts-fit-together"></a>

## How The Scripts Fit Together

The normal authoring pipeline keeps each concern in a separate script so failed stages are easy to diagnose:

You do not need to call every script yourself: `torcs-rebuild-mainline` runs the core layout stages together. The *DP-biarc drafter* uses dynamic programming to choose a sequence of straight pieces and paired circular arcs that approximates the source. The geometric closer's *terminal lever* is a small adjustable straight at the end of the lap used to remove the remaining longitudinal gap.

| Stage | Script | Purpose |
| --- | --- | --- |
| OSM relation discovery | `torcs-fetch-track-layout` | Lists relation layout candidates and exports the chosen racing loop. |
| Manual OSM way source | `torcs-fetch-centerline` | Fetches explicit way IDs when relation roles are noisy or ambiguous. |
| SVG source extraction | `torcs-svg-to-centerline` | Selects and scales a closed SVG path, polyline, or polygon into centerline JSON. |
| Raster source extraction | `torcs-image-to-centerline` | Extracts and scales one closed loop from a map image. |
| Source georeferencing | `torcs-georeference-centerline` | Aligns a local SVG/raster centerline to a geographic reference or distributed control points. |
| Segment drafting | `torcs-draft-segments` | DP-biarc drafter that approximates source points with TORCS `str`/`lft`/`rgt` segments. |
| Legacy segment fitting | `torcs-polyline-to-torcs` | Older sequential polyline fitter; keep as an explicit fallback with `torcs-rebuild-mainline --segment-fitter polyline`. |
| XML assembly | `torcs-apply-segments` | Replaces only `Main Track/Track Segments` in the target XML/template. |
| No-pit rebuild orchestration | `torcs-rebuild-mainline` | Runs DP drafting, XML assembly, candidate selection, and strict closure. |
| Tight-turn side cleanup | `torcs-adjust-side-clearance` | Reduces effective inner side widths where the side/border offset would cross a turn center; `torcs-rebuild-mainline` runs this by default. |
| Distant side-overlap cleanup | `torcs-adjust-side-overlap` | Reduces and tapers side widths where distant side envelopes overlap across narrow infield gaps; `torcs-rebuild-mainline` runs this by default. |
| Curb placement | `torcs-place-curbs` | Flattens global borders, adds inside curbs to tight/medium turns, and can split segments for raceline-guided outside curbs without touching pit zones. |
| DEM elevation fetch | `torcs-fetch-elevation` | Samples an OSM lat/lon centerline and offset terrain corridors into an elevation cache for road and relief generation. |
| Automatic raster DEM import | `torcs-auto-elevation` | Searches a provider tile API, downloads/caches matching DTM tiles for the wider landscape bbox, imports a road profile, and can optionally apply/render it. |
| Raster preparation | `torcs-prepare-raster` | Inspects local raster tiles, mosaics them, and writes a meter-valued GeoTIFF with optional vertical feet-to-meters scaling. |
| Raster DEM profile import | `torcs-import-elevation-raster` | Samples local GeoTIFF or ESRI ASCII DEM data at the accepted XML centerline after spatially fitting it to the source loop. |
| Raster road-surface import | `torcs-import-road-surface-raster` | Samples a high-resolution raster across the real source road width and derives both center elevation and banking. |
| Manual banking profile import | `torcs-import-banking-zones` | Converts source-station banking zone descriptions into a road-surface profile consumed by `torcs-apply-elevation --apply-banking`. |
| Road-surface profile composition | `torcs-compose-road-surface-profile` | Combines compatible elevation and banking profiles into one canonical road-surface profile. |
| Elevation and terrain | `torcs-apply-elevation` | Applies a smoothed station/elevation profile after pits, writes spline `z`/tangent attributes, and can generate a trackgen terrain heightmap or relief `.ac` without adding plan-view segments. |
| Elevation difference SVG | `torcs-render-elevation-diff-svg` | Renders a plan-view DEM-vs-track SVG with the real/source outline, TORCS outline, and color-coded height differences. |
| Road-surface difference SVG | `torcs-render-road-surface-diff-svg` | Renders a profile-only center/edge/banking diagnostic for applied road-surface profiles. |
| Terrain heightmap difference PNG | `torcs-render-terrain-elevation-diff-png` | Renders a whole-map terrain heightmap-vs-raster PNG using trackgen's PNG row order and blue-white-red height differences. |
| Track menu map | `torcs-render-track-map` | Renders the final XML driving loop as a transparent TORCS menu PNG and optional review SVG with start and direction markers. |
| Batch track menu maps | `torcs-render-track-maps` | Creates missing and overwrites existing menu PNGs for every track beneath a category/track directory tree. |
| Labeled segment SVG | `torcs-render-labeled-segments-svg` | Renders segment types, labels, direct curb markers, and hover details for layout review. |
| Legacy closure solver | `torcs-close-loop` | Uses `trackgen -z` and locked control segments to close a track. |
| Geometric closure solver | `torcs-close-loop2` | Terminal-lever closer used by `torcs-rebuild-mainline --closure-solver geometric`. |
| Pit integration | `torcs-integrate-pitlane` | Adds side pits, preserves a no-pit backup, and stages for post-pit closure. |
| Overlay diagnostics | `torcs-compare-overlay` | Compares source vs generated XML path with metrics and SVG. Use `--align-closed` to match different loop start positions/directions without scaling. |

For normal layout work, prefer the source commands `torcs-fetch-track-layout`, `torcs-svg-to-centerline`, or `torcs-image-to-centerline`, followed by `torcs-georeference-centerline` when a local drawing needs geographic placement, then `torcs-rebuild-mainline` and `torcs-integrate-pitlane`. Elevation workflows use the DEM import/apply commands directly after layout acceptance. Direct closure and side-cleanup scripts are primarily diagnostics. The geometric solver uses its terminal lever for final X correction; use `--segment-fitter polyline` only to compare against or recover with the legacy fitter. Use `--no-adjust-side-clearance` or `--no-adjust-side-overlap` only when diagnosing the raw closed XML before side-width cleanup.

`torcs-render-labeled-segments-svg` uses a uniquely dominant numbered source-name family for compact automatic labels, keeps generated pit or closure names distinct, and falls back to names when compact labels would collide. Use `--label-mode index` for 1-based XML indices or `--label-mode name` for full names. `--zoom-labels` filters automatic source labels or index-mode indices; it is intentionally unavailable in full-name mode. `--label-font-size` accepts a positive finite SVG pixel size.

### Side-Clearance Cleanup

`torcs-adjust-side-clearance` checks tight turns using the effective side width on each segment, including carried state and explicit `width`, `start width`, and `end width` overrides. This matters after pit integration because a widened pit entry or exit corridor can extend through a nearby turn even when the global default side width is safe. The report lists all pit/wall-protected segments in `protected_segments`, and the narrower `hard_protected_segments` set that the tool will not rewrite while tapering. Pit main/host/wall sections stay hard-protected and their anomalies are report-only, but widened pit-entry or pit-exit approach corridors are still checked and can be corrected.

Use a dry-run report to validate a final pitted XML without mutating it:

```powershell
conda run -n torcs-tracktools torcs-adjust-side-clearance `
  --input runtime/tracks/road/<name>/<name>.xml `
  --report runtime/tracks/road/<name>/source/side-clearance-report-pits.json `
  --dry-run
```

Accept only when the final report has `"anomaly_count": 0`. If the dry-run reports anomalies, run the tool without `--dry-run` on the staged XML, then rerun side-clearance dry-run, side-overlap dry-run, `trackgen -z`, and geometry generation before promotion.

### Side-Overlap Cleanup

`torcs-adjust-side-overlap` catches a different problem than tight-turn side clearance: distant side envelopes crossing across narrow infield gaps. `torcs-rebuild-mainline` runs it after `torcs-adjust-side-clearance` and before optional curbs. Non-dry runs fail if final overlap samples remain, so `source/side-overlap-report.json` should have `"status": "ok"` and `"final_overlap_count": 0` before promotion. If the report still fails, inspect the reported segment pairs and fix the layout or side widths explicitly instead of hiding the stage with `--no-adjust-side-overlap`.

### Curb Placement

`torcs-place-curbs` has two placement passes. The inside pass curbs qualifying tight/medium turn segments directly. The outside pass computes a K1999-style raceline, finds near-outside-edge approach/exit zones, snaps to existing segment boundaries when they almost fit, and splits only the remaining straight or constant-radius turn segments that need shorter curb runs.

Useful defaults are intentionally conservative and overridable:

```powershell
conda run -n torcs-tracktools torcs-rebuild-mainline `
  --input runtime/tracks/road/<name>/source/centerline-osm.json `
  --output-track-xml runtime/tracks/road/<name>/<name>.xml `
  --closure-solver geometric `
  --place-curbs
```

For manual tuning on an already staged XML, run the curb tool directly:

```powershell
conda run -n torcs-tracktools torcs-place-curbs `
  --input runtime/tracks/road/<name>/<name>.xml `
  --report runtime/tracks/road/<name>/source/curb-placement-report-pits.json
```

Use `--placement inside`, `--placement outside`, or `--placement both` to isolate a pass. Outside curb run shaping is controlled by `--outside-max-run-m`, `--outside-min-run-m`, `--outside-merge-gap-m`, `--split-boundary-tolerance-m`, `--segment-fit-ratio`, and `--min-split-piece-m`. The outside pass skips protected pit corridors, wall borders, and variable-radius segments with `end radius` instead of splitting them. If curbs are placed before pits, choose pit hosts from the current curbed XML; outside splitting can rename an old host into `-pre`, `-curb`, and `-post` pieces. On an already accepted pitted layout, if outside curb splits disturb closure, rerun the outside pass with `--segment-fit-ratio 0` to assign whole-segment outside curbs without changing geometry, then revalidate with `trackgen -z`, side-clearance dry-run, side-overlap dry-run, and regenerated assets.

### Pit Integration

TORCS side pits are attached beside a sufficiently straight part of the main track, called the pit host. Choose the host and side first; the tool then creates the pit area and its entry/exit width transitions. The [Real Pitlane Workflow](#real-pitlane-workflow) covers placement from map data and manual host selection.

`--host-mode straighten` can include short straight connector fragments between the requested host chain and the surrounding connector arcs; the refitted window is still a turn/straight/turn sequence.

Use `--host-mode straighten` when the intended manual pit host is a mostly straight chain but contains small fitted turns that make the default pose-preserving almost-straight replacement fail. This mode requires `--host-start-segment` and `--host-end-segment`; it replaces the selected chain with a true straight pit host and refits the adjacent connector turns so the overall entry/exit pose remains aligned. Add `--pit-main-align end` when the pit boxes should end at the end of the selected host; the default entry taper is then limited to the spare host length before `pit_main_a` instead of extending into the previous connector turn.

```powershell
conda run -n torcs-tracktools torcs-integrate-pitlane `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --pit-side right `
  --host-start-segment "Main Straight-4" `
  --host-end-segment "Main Straight-10-curb" `
  --host-mode straighten `
  --pit-main-align end `
  --report runtime/tracks/road/<name>/source/pit-integration-report.json `
  --stage-for-closure
```

After staging pits, close the pitted XML with `torcs-close-loop2 --profile post-pit`, then accept it only after `trackgen -z` reports the expected pit count, side-clearance dry-run reports no anomalies, and side-overlap dry-run reports no unresolved overlaps.

<a name="elevation-and-terrain"></a>

## Elevation And Terrain

Run elevation after the layout and any curbs or pits for this pass are accepted. These tools add road heights and slopes without changing the horizontal layout. A road profile controls the driving surface; a terrain heightmap or relief file guides the surrounding landscape. An *offset corridor* samples parallel lines beside the source centerline to capture nearby ground heights.

Choose the route matching your data:

- **Local elevation rasters:** prepare the tiles, then import either centerline heights or the full road surface (heights plus banking).
- **Automatic raster discovery:** the England workflow below downloads suitable Environment Agency terrain tiles.
- **Online elevation samples:** fetch an OSM-based elevation corridor and apply that cache.
- **Manual data:** provide station/elevation points or banking zones. You can combine compatible height and banking profiles.

The bundled road template keeps `Left Side` and `Right Side` banking `level` (flat across their widths). Use `tangent` only when you want the road's sideways tilt to continue across the grass or shoulder.

### Prepare Local Raster Tiles

Prepare local downloaded LiDAR/DEM tiles before importing them. This command writes a normal GeoTIFF mosaic and can convert vertical grid values to meters while preserving the source horizontal CRS. Use `--dry-run --report ...` with no `--output` for inspection only. Use `--vertical-unit m` when the grid values are already meters, `ft` for international feet, or `us-ft` for US survey feet:

```powershell
conda run -n torcs-tracktools torcs-prepare-raster `
  --input runtime/tracks/road/<name>/source/lidar/tiles `
  --recursive `
  --vertical-unit us-ft `
  --output runtime/tracks/road/<name>/source/lidar/lidar-dtm-m.tif `
  --report runtime/tracks/road/<name>/source/lidar/raster-prepare-report.json
```

### Import Road Heights And Banking From A Raster

For high-resolution DTM/LiDAR rasters, prefer importing the full road surface in source coordinates. `--road-width` is the real sampled road width, not `Main Track/width` from TORCS. Check horizontal and vertical units separately before import: a GeoTIFF CRS can correctly describe XY in feet while the grid values are also feet, meters, or another vertical datum/unit. Reprojecting or CRS metadata only solves the horizontal transform; convert the raster values to meters before profile import and terrain heightmap generation, then use the meter-valued raster consistently for profile, apply, and diagnostics. Projected non-meter horizontal CRS units are handled by scale fitting automatically; geographic rasters must be reprojected to a projected CRS before road-surface cross-section import:

```powershell
conda run -n torcs-tracktools torcs-import-road-surface-raster `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --polyline runtime/tracks/road/<name>/source/centerline-osm.json `
  --raster runtime/tracks/road/<name>/source/lidar/lidar-dtm-m.tif `
  --road-width 10.0 `
  --output runtime/tracks/road/<name>/source/road-surface-raster-profile.json `
  --report runtime/tracks/road/<name>/source/road-surface-raster-profile-report.json `
  --overlay runtime/tracks/road/<name>/source/road-surface-raster-profile.svg `
  --sample-step 5
```

Apply the raster road-surface profile directly when both center elevation and banking are acceptable:

```powershell
conda run -n torcs-tracktools torcs-apply-elevation `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --profile runtime/tracks/road/<name>/source/road-surface-raster-profile.json `
  --apply-banking `
  --terrain-elevation-map auto `
  --terrain-elevation-width 1024 `
  --relief-distances 15 `
  --relief-interior-max-distance 0 `
  --relief-sample-step 50 `
  --report runtime/tracks/road/<name>/source/road-surface-raster-apply-report.json
```

Use the default banking width policy when TORCS `Main Track/width` matches the sampled real road width. If the TORCS road width differs and the real edge height delta should be preserved, add `--bank-width-policy edge-delta`; add `--bank-real-width <meters>` only when the profile does not already contain `sampling.real_road_width_m`.

### Import Manual Banking And Combine Profiles

Manual or written banking data can be imported separately and applied without rewriting elevation. Banking zones describe the tilt over ranges of source stations:

```powershell
conda run -n torcs-tracktools torcs-import-banking-zones `
  --polyline runtime/tracks/road/<name>/source/centerline-osm.json `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --zones runtime/tracks/road/<name>/source/banking-zones.json `
  --output runtime/tracks/road/<name>/source/banking-profile-manual.json `
  --report runtime/tracks/road/<name>/source/banking-profile-manual-report.json
```

When applying elevation and banking together, compose compatible source-frame or XML-frame profiles first. The composer preserves the shared station mapping and fails instead of mixing incompatible frames:

```powershell
conda run -n torcs-tracktools torcs-compose-road-surface-profile `
  --elevation-profile runtime/tracks/road/<name>/source/elevation-terrain.json `
  --banking-profile runtime/tracks/road/<name>/source/banking-profile-manual.json `
  --output runtime/tracks/road/<name>/source/road-surface-profile.json `
  --report runtime/tracks/road/<name>/source/road-surface-profile-report.json
```

```powershell
conda run -n torcs-tracktools torcs-apply-elevation `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --profile runtime/tracks/road/<name>/source/road-surface-profile.json `
  --apply-banking `
  --report runtime/tracks/road/<name>/source/road-surface-apply-report.json
```

To change only banking while keeping existing road heights:

```powershell
conda run -n torcs-tracktools torcs-apply-elevation `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --profile runtime/tracks/road/<name>/source/banking-profile-manual.json `
  --apply-banking `
  --banking-profile-only `
  --report runtime/tracks/road/<name>/source/banking-apply-report.json
```

### Check The Applied Road Surface

After applying a road-surface profile, render the profile-only road surface diagnostic before generating final assets:

```powershell
conda run -n torcs-tracktools torcs-render-road-surface-diff-svg `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --profile runtime/tracks/road/<name>/source/road-surface-raster-profile.json `
  --output runtime/tracks/road/<name>/source/road-surface-diff.svg `
  --report runtime/tracks/road/<name>/source/road-surface-diff-report.json `
  --color-mode bank
```

Use the profile that was actually applied: `road-surface-raster-profile.json` for the direct raster workflow, `road-surface-profile.json` for a composed profile, or `banking-profile-manual.json` for banking-only validation.
If the track was applied with `--bank-width-policy edge-delta`, pass the same `--bank-width-policy edge-delta` to the diff command, plus `--bank-real-width <meters>` when the profile lacks `sampling.real_road_width_m`.

### Fetch And Apply Online Elevation Samples

For an OSM-sourced track, fetch a DEM corridor cache from the source centerline. It contains road-center samples and offset terrain lines:

```powershell
conda run -n torcs-tracktools torcs-fetch-elevation `
  --polyline runtime/tracks/road/<name>/source/centerline-osm.json `
  --output runtime/tracks/road/<name>/source/elevation-terrain.json `
  --sample-step 50 `
  --distances 25,80,160 `
  --force
```

Then apply the fetched cache to the accepted pitted XML. The tool keeps the first station at `z = 0`, smooths the road profile, writes segment `z start`, `z end`, `profil start tangent`, and `profil end tangent`, then updates trackgen terrain-generation inputs. It does not split segments or change plan-view closure.

```powershell
conda run -n torcs-tracktools torcs-apply-elevation `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --elevation-cache runtime/tracks/road/<name>/source/elevation-terrain.json `
  --report runtime/tracks/road/<name>/source/elevation-report.json
```

### Supply A Manual Elevation Profile

Each `--point station:elevation` pair uses meters. For example, `--point 800:18` supplies a height of 18 meters at a distance of 800 meters along the XML centerline. With the example's starting height of zero, that is 18 meters above the start. These are profile control points; smoothing can adjust the final road heights. Choose stations appropriate to your lap length and keep the end-to-start transition smooth.

Minimal manual profile example:

```powershell
conda run -n torcs-tracktools torcs-apply-elevation `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --point 0:0 `
  --point 800:18 `
  --point 1600:42 `
  --point 2600:0 `
  --report runtime/tracks/road/<name>/source/elevation-report.json
```

For reusable manual data, pass one or more CSV/JSON profile files with `--profile`. CSV columns can be `station_m,elevation_m,weight`. JSON can be `{"samples": [{"station_m": 0, "elevation_m": 0}, ...]}`. Multiple profiles are normalized relative to their own start elevation and fused by weighted average. Manual profile files only shape the road; `--elevation-cache` also supplies offset terrain heights for relief lines.

### Generate The Surrounding Terrain

Terrain generation modes:

- Tool default mode keeps relief constraints disabled with `--relief-distances none`. It writes an empty `<track>-relief.ac` so existing XML references stay valid, and it removes `elevation map`, `minimum altitude`, and `maximum altitude` unless a terrain heightmap is explicitly requested.
- Accepted raster-backed workflows should use raster heightmap mode by default, unless the task is explicitly road-only. Use `--terrain-elevation-map auto` with a raster-backed `--profile` from `torcs-import-elevation-raster`, `torcs-import-road-surface-raster`, or `torcs-auto-elevation`. It writes `<track>-terrain-elevation.png` beside the XML and updates `Graphic/Terrain Generation/elevation map`, `minimum altitude`, and `maximum altitude`.
- Distance-relief mode uses `--relief-distances 25,80,...` to write AC3D control lines in the `relief file`. These lines guide trackgen terrain meshing; they are not final visible road geometry. Prefer raster heightmaps for broad terrain and only enable relief contours after validation, because invalid or near-loop contours can produce holes or unstable terrain.
- Compact exterior-only relief is useful when a raster heightmap provides broad terrain and full interior/exterior relief makes the generated `.ac` too large or fragile. Use `--terrain-elevation-map auto` with a short exterior distance such as `--relief-distances 15 --relief-interior-max-distance 0 --relief-sample-step 50`, then validate the terrain diff and generated assets.

Trackgen terrain heightmaps are 8-bit grayscale PNGs stretched linearly between `minimum altitude` and `maximum altitude`. Trackgen maps the image over the generated track bounds plus `border margin`. The final road model is vertically normalized by subtracting the road's minimum `z`, so raster heightmap altitudes must include the same `track_z_offset_m` used in the elevation report. `GfImgReadPng` flips file rows into memory, and trackgen maps memory row `0` to terrain `ymin`; therefore PNG files generated for trackgen must store their top file row as `ymax`. If a heightmap is written in normal array row order, the terrain is consumed upside down and can look like a high plateau with the road in a canyon.

Raster terrain example:

```powershell
conda run -n torcs-tracktools torcs-apply-elevation `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --profile runtime/tracks/road/<name>/source/elevation-lidar-profile.json `
  --smooth-window 15 `
  --smooth-step 2 `
  --smooth-iters 1 `
  --terrain-elevation-map auto `
  --terrain-elevation-width 1024 `
  --relief-distances 15 `
  --relief-interior-max-distance 0 `
  --relief-sample-step 50 `
  --report runtime/tracks/road/<name>/source/elevation-report.json
```

Validate the generated terrain heightmap against the source raster before judging the in-game terrain:

```powershell
conda run -n torcs-tracktools torcs-render-terrain-elevation-diff-png `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --profile runtime/tracks/road/<name>/source/elevation-lidar-profile.json `
  --output runtime/tracks/road/<name>/source/terrain-elevation-diff.png `
  --report runtime/tracks/road/<name>/source/terrain-elevation-diff-report.json `
  --color-range 10
```

The terrain PNG diagnostic reports `trackgen_terrain_z - normalized_source_raster_z`. White is near perfect, red means the terrain PNG is too high, blue means it is too low, and black means the source raster has no sample for that pixel. The renderer emulates trackgen's PNG row flip and road `z` normalization, so it catches row-order and vertical-frame mistakes that are invisible if you inspect the raw PNG directly. With 8-bit heightmaps, small residuals from quantization are normal.

Keep the local source tiles, the raw/normal mosaiced GeoTIFF, the meter-valued mosaic from `torcs-prepare-raster` if vertical conversion was required, and the imported raster profile under `source/` so repeated applies do not need to refetch or remosaic tiles. Regenerating `<track>-terrain-elevation.png` through `torcs-apply-elevation --terrain-elevation-map auto` is still the safest path because the PNG depends on the accepted XML bounds, `border margin`, road `track_z_offset_m`, min/max altitude, row order, and any pit flattening. A standalone PNG writer would need to read the same raster-backed profile or apply report, require metric vertical values, and update the XML heightmap attributes atomically; do not hand-tile DEM data into a PNG without those values.

#### Relief Control Details

- Relief object names start with `interior-` or `exterior-`; trackgen classifies the object from that name prefix. The matching `data` text is retained as metadata but does not drive classification.
- DEM corridor distances are measured from the source centerline. Edge-relative relief contours sample the cache at their actual centerline distance, including the local road, side, and border width.
- Generated relief uses open `SURF 0x22` breaklines. `torcs-apply-elevation` rejects closed lines instead of emitting `SURF 0x21` polygons, which trackgen can interpret as terrain holes.
- Candidate contour winding determines the interior/exterior side before the contour is opened into a breakline. Wrong orientation or self-intersection can cut holes or destabilize the terrain mesh.
- Open near-loop breaklines avoid closed-surface holes but can still destabilize `trackgen` or `accc` if they intersect the road, each other, or the terrain border.

Tune terrain shape with `--terrain-elevation-width`, `--relief-distances`, `--relief-height-falloff`, `--smooth-window`, and `--pit-flatten-strength`. If `--dry-run` is set, the tool writes only the report and leaves XML, relief, and heightmap files untouched.

### Diagnose Road And Terrain Alignment

To diagnose a bad crest, phase error (hills shifted along the lap), or plan-view mismatch, render an elevation-difference SVG after applying elevation:

```powershell
conda run -n torcs-tracktools torcs-render-elevation-diff-svg `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --elevation-cache runtime/tracks/road/<name>/source/elevation-terrain.json `
  --map-elevation-cache runtime/tracks/road/<name>/source/elevation-terrain.json `
  --output runtime/tracks/road/<name>/source/elevation-diff.svg `
  --report runtime/tracks/road/<name>/source/elevation-diff-report.json `
  --profile-output runtime/tracks/road/<name>/source/elevation-planfit-profile.json `
  --color-range 5 `
  --sample-step 5
```

The SVG draws the real/source road outline in dashed green, the generated TORCS outline in dark strokes, and every sampled TORCS centerline point as a blue-white-red difference marker. The reported difference is `track_z - DEM_z`: white is near perfect, red means the track is too high, and blue means the track is too low. Use `--elevation-cache` for the DEM data being compared, and optionally `--map-elevation-cache` for a wider or coarser DEM corridor rendered as the background height map. The background defaults to the center DEM line only; use `--map-lines all` only when offset terrain corridors are known clean. The tool searches circular source-loop shifts during the plan-view fit, so a source start point that differs from the XML start does not by itself hide misalignment. When `--profile-output` is set, it also writes a direct station/elevation JSON profile sampled from the fitted DEM at the accepted XML centerline; apply that profile with `torcs-apply-elevation --profile ...` when landmark station warping puts hills in the wrong place.

To keep relief terrain with a plan-fit profile, pass a terrain-only copy of the same DEM cache as `--elevation-cache`, set its top-level `weight` to `0.0`, and name it as a derivative such as `<cache-stem>-terrainonly.json` or `<cache-stem>-terrain-only.json`. `torcs-apply-elevation` resolves the profile's `elevation_source` and cache paths canonically, rejects ambiguous or unrelated matches, and applies the fit's station shift, direction, scale, and centerline zero to matching relief lines. The apply report records this under `terrain_source_alignment`, including `source_shift_m`, `source_reversed`, `scale`, and `zero_offset_m`.

If generated relief terrain looks like a canyon or plateau but the road-vs-DEM diff is reasonable, compare the relief `.ac` vertical range to generated road and terrain object ranges before changing the road profile. A large average terrain-road offset usually indicates the relief cache is in the wrong station or zero frame.

### Discover Elevation Rasters Automatically In England

For England tracks with an OSM or other georeferenced source polyline, `torcs-auto-elevation` can do the raster discovery and import automatically. The EA LiDAR provider searches the Environment Agency/Defra tile API, prefers bare-earth DTM products, downloads matching tiles into a cache, mosaics multiple rasters when necessary, and imports a road profile from the accepted XML centerline. The search area is the source/track bbox plus `--landscape-margin-m`, which defaults to `1000`; this intentionally caches a wider landscape raster even when the current road profile only samples the centerline:

```powershell
conda run -n torcs-tracktools torcs-auto-elevation `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --polyline runtime/tracks/road/<name>/source/centerline-osm.json `
  --output-dir runtime/tracks/road/<name>/source/elevation-auto `
  --landscape-margin-m 1000 `
  --apply `
  --diff
```

The automatic command writes `tile-search.json`, downloaded tile zips under `downloads/`, extracted rasters under `tiles/`, `elevation-ea-lidar-profile.json`, `elevation-ea-lidar-profile-report.json`, `elevation-ea-lidar-profile.svg`, and `auto-elevation-report.json` in the output directory. With `--apply`, it calls `torcs-apply-elevation` using the imported profile and writes `elevation-report.json`; with `--diff`, it writes `elevation-diff.svg` and `elevation-diff-report.json`. For accepted raster-backed elevation, rerun `torcs-apply-elevation` with `--profile <generated-profile> --terrain-elevation-map auto` plus the compact relief flags from the raster terrain example, then render `torcs-render-terrain-elevation-diff-png`. If the source polyline uses local `x/y` coordinates instead of `lat/lon`, pass `--polyline-crs`; EA rasters default to `--provider-crs EPSG:27700`. After applying elevation, regenerate base geometry with `trackgen -q`; if raceline layers are in use, rerun `trackgen -r`; if `Graphic/3d description` points to a merged `.acc`, rerun `accc -g` so the final visual model is not stale.

### Import Centerline Heights From A Local Raster

For higher-resolution local DEM data, import a raster profile instead of calling an online elevation API. Prefer bare-earth DTM data such as Environment Agency LiDAR Composite DTM `1m`/`2m`; OS Terrain 5 can be a fallback where LiDAR is unavailable. GeoTIFFs usually carry their own CRS for horizontal coordinates, but the raster grid's vertical unit must still be verified from product metadata, tile names, or known local elevation ranges. ESRI ASCII grids need `--raster-crs`, for example `EPSG:27700` for British National Grid. The source polyline is used only to fit the accepted XML centerline into raster coordinates; the output profile stations come from the XML, so this avoids OSM way-name station warping:

If official/government LiDAR catalogs expose direct object-storage URLs that return `HTTP 403` or `AccessDenied`, do not immediately fall back to coarse DEM data. Download the required tiles from the official portal, keep them under `runtime/tracks/<category>/<name>/source/<elevation-dir>/tiles/`, prepare a meter-valued mosaic with `torcs-prepare-raster`, and import that mosaic with `torcs-import-elevation-raster`. In the track `readme.txt`, describe generated elevations, terrain heightmaps, relief, and geometry as `derived from` the official dataset and note the manual-download/access issue; do not imply raw tiles are shipped unless they are packaged.

```powershell
conda run -n torcs-tracktools torcs-import-elevation-raster `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --polyline runtime/tracks/road/<name>/source/centerline-osm.json `
  --raster runtime/tracks/road/<name>/source/lidar/lidar-dtm-m.tif `
  --output runtime/tracks/road/<name>/source/elevation-lidar-profile.json `
  --report runtime/tracks/road/<name>/source/elevation-lidar-profile-report.json `
  --overlay runtime/tracks/road/<name>/source/elevation-lidar-profile.svg `
  --sample-step 5
```

Then apply the imported profile with a smaller smoothing window than coarse DEM data so short crests are not flattened or shifted. For accepted raster-backed elevation, include the raster terrain flags from the terrain example above in this same pass unless the task is explicitly road-only:

```powershell
conda run -n torcs-tracktools torcs-apply-elevation `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --profile runtime/tracks/road/<name>/source/elevation-lidar-profile.json `
  --smooth-window 15 `
  --smooth-step 2 `
  --smooth-iters 1 `
  --terrain-elevation-map auto `
  --terrain-elevation-width 1024 `
  --relief-distances 15 `
  --relief-interior-max-distance 0 `
  --relief-sample-step 50 `
  --report runtime/tracks/road/<name>/source/elevation-report.json
```

<a name="svg-centerline-workflow"></a>

## SVG Centerline Workflow

Use `torcs-svg-to-centerline` when the source layout is vector geometry. It supports SVG paths, polylines, and polygons; all standard path commands; nested transforms; unitless, pixel, and absolute-unit SVG viewports; root percentage dimensions; local `<use>` references; published-length scaling; direction reversal; and explicit station-zero placement. Nested percentage viewports are rejected because they require parent-viewport layout that this authoring importer does not infer.

For a simple SVG containing one closed loop:

```powershell
conda run -n torcs-tracktools torcs-svg-to-centerline `
  --input runtime/tracks/road/<name>/source/layout.svg `
  --output runtime/tracks/road/<name>/source/centerline-svg.json `
  --length-m <published-length-m> `
  --preview-svg runtime/tracks/road/<name>/source/svg-centerline-preview.svg `
  --report runtime/tracks/road/<name>/source/svg-centerline-report.json
```

For an Illustrator or map SVG with several eras, labels, or decorative paths, restrict extraction to a semantic group or element:

```powershell
conda run -n torcs-tracktools torcs-svg-to-centerline `
  --input runtime/tracks/road/<name>/source/layout.svg `
  --output runtime/tracks/road/<name>/source/centerline-svg.json `
  --length-m <published-length-m> `
  --group-id <layout-group-id> `
  --preview-svg runtime/tracks/road/<name>/source/svg-centerline-preview.svg `
  --report runtime/tracks/road/<name>/source/svg-centerline-report.json
```

The default selects the longest visible closed candidate. `--element-id` selects one element or group, and `--candidate-index` selects an index from the report. Use `--reverse` to change racing direction, `--keep-start` to preserve the SVG subpath start, or `--start x,y` to project station zero onto the loop near transformed SVG coordinates. Without either start option, the tool rotates station zero to a smooth low-curvature location. `--curve-tolerance` is measured after SVG transforms.

The output uses local metric coordinates and is not georeferenced merely because the SVG resembles a real circuit. For DEM/LiDAR work, preserve a separately aligned geographic source and record its CRS and transform evidence. Centerline-to-reference georeferencing remains a separate workflow.

Rebuild SVG-derived sources with the drawing profile, or `drawing-detail` when small kinks and chicanes must survive:

```powershell
conda run -n torcs-tracktools torcs-rebuild-mainline `
  --input runtime/tracks/road/<name>/source/centerline-svg.json `
  --output-track-xml runtime/tracks/road/<name>/<name>.xml `
  --profile drawing `
  --closure-solver geometric
```

<a name="centerline-georeferencing-workflow"></a>

## Centerline Georeferencing Workflow

Use `torcs-georeference-centerline` after SVG or raster extraction when the local loop needs trustworthy geographic coordinates for alignment evidence, DEM/LiDAR discovery, or raster sampling. The command never treats agreement with generated TORCS XML as georeferencing.

When a geographic OSM/GPS loop represents substantially the same layout, use automatic closed-loop alignment. Rigid fitting preserves a source already scaled to a published length; use `--transform similarity` only when source scale is genuinely unknown:

```powershell
conda run -n torcs-tracktools torcs-georeference-centerline `
  --input runtime/tracks/road/<name>/source/centerline-svg.json `
  --reference runtime/tracks/road/<name>/source/centerline-osm.json `
  --allow-reference-reverse `
  --output runtime/tracks/road/<name>/source/centerline-georeferenced.json `
  --overlay runtime/tracks/road/<name>/source/georeference-overlay.svg `
  --report runtime/tracks/road/<name>/source/georeference-report.json
```

For historical layouts that differ from the modern reference, use named, distributed control points instead of forcing a whole-loop match:

```powershell
conda run -n torcs-tracktools torcs-georeference-centerline `
  --input runtime/tracks/road/<name>/source/centerline-svg.json `
  --reference runtime/tracks/road/<name>/source/centerline-osm.json `
  --control-points runtime/tracks/road/<name>/source/georeference-controls.json `
  --output runtime/tracks/road/<name>/source/centerline-georeferenced.json `
  --overlay runtime/tracks/road/<name>/source/georeference-overlay.svg `
  --report runtime/tracks/road/<name>/source/georeference-report.json
```

The control file contains `reference_crs`, optional reference metadata, and at least three entries with `source: {x, y}` and `reference: {lat, lon}` or projected `{x, y}` coordinates. Approximate coordinates are snapped to the local and reference loops. Controls must cover different sides of the circuit; two, clustered, or nearly collinear controls require `--allow-weak-control-set` and produce review status. Large snaps are rejected by `--max-source-snap` and `--max-reference-snap-m` instead of being hidden by a low post-snap residual.

The default `EPSG:4326` latitude/longitude output can be consumed directly by elevation commands. A non-default `--output-crs` is recorded in the cache, but current elevation commands still require the same CRS explicitly through `--polyline-crs`. The metric fitting CRS is selected automatically; an explicit `--fit-crs` must use meter units. The report records fit/output/reference CRS, transform parameters, reference station shift or reversed correspondence, control snap distances, residuals, distribution metrics, and status. Rejected runs write the report and overlay but remove the requested centerline output. Always inspect `georeference-overlay.svg`; low residuals do not prove that selected landmarks or the reference source are historically correct.

<a name="imagedrawing-centerline-workflow"></a>

## Image/Drawing Centerline Workflow

Use `torcs-image-to-centerline` when no usable OSM centerline exists and the source is a raster track map, screenshot, scan, or hand drawing. The tool extracts the main colored loop, scales it to a user-provided real length, and writes the same local `x/y` centerline JSON consumed by `torcs-rebuild-mainline`.

Use the `clean-map` profile for high-contrast maps with a clear single track line:

```powershell
conda run -n torcs-tracktools torcs-image-to-centerline `
  --input runtime/tracks/road/<name>/source/track-map.png `
  --output runtime/tracks/road/<name>/source/centerline-image.json `
  --length-m 14100 `
  --profile clean-map `
  --track-color red `
  --preview-svg runtime/tracks/road/<name>/source/image-centerline-preview.svg
```

Use the `antialias-ridge` profile for antialiased scans or maps where the clean-map profile produces visible stair-step wiggles. It is slower, but usually gives a better centerline because it links Steger-style subpixel ridge candidates instead of integer pixel centers:

```powershell
conda run -n torcs-tracktools torcs-image-to-centerline `
  --input runtime/tracks/road/<name>/source/track-map.png `
  --output runtime/tracks/road/<name>/source/centerline-image-ridge-link.json `
  --length-m 14100 `
  --profile antialias-ridge `
  --track-color red `
  --preview-svg runtime/tracks/road/<name>/source/image-centerline-ridge-link-preview.svg
```

Use the `skimage-map` profile for thick or jagged raster track strokes that benefit from `scikit-image` morphology and skeletonization:

```powershell
conda run -n torcs-tracktools torcs-image-to-centerline `
  --input runtime/tracks/road/<name>/source/track-map.png `
  --output runtime/tracks/road/<name>/source/centerline-image-skimage.json `
  --length-m 14100 `
  --profile skimage-map `
  --track-color custom --rgb 0,220,255 `
  --preview-svg runtime/tracks/road/<name>/source/image-centerline-skimage-preview.svg
```

Then rebuild from the generated source with the drawing profile. This keeps more detail than the default OSM-oriented profile while filtering short raster wiggles from straights and wide bends:

```powershell
conda run -n torcs-tracktools torcs-rebuild-mainline `
  --input runtime/tracks/road/<name>/source/centerline-image.json `
  --output-track-xml runtime/tracks/road/<name>/<name>.xml `
  --profile drawing `
  --closure-solver geometric
```

If a small chicane or kink is washed out by the drawing profile, use the detail-preserving drawing profile instead of weakening source smoothing globally:

```powershell
conda run -n torcs-tracktools torcs-rebuild-mainline `
  --input runtime/tracks/road/<name>/source/centerline-image-ridge-link.json `
  --output-track-xml runtime/tracks/road/<name>/<name>.xml `
  --profile drawing-detail `
  --closure-solver geometric
```

Stable extraction options:

- `--profile clean-map`: stable default for clean high-contrast track drawings.
- `--profile antialias-ridge`: stable default for antialiased red-line maps and scans where skeleton extraction is visibly jagged.
- `--profile skimage-map`: uses `numpy` and `scikit-image` for morphology and skeletonization of thick or jagged drawing strokes.
- `--track-color red`: select red pixels directly; best for many published track maps.
- `--track-color custom --rgb r,g,b`: select another known line color.
- `--track-color dark|light --threshold <0..255>`: use grayscale thresholding for black/white drawings.
- `--crop x,y,w,h`: remove title blocks, legends, or alternate layouts before extraction.
- `--color-tolerance <value>`: widen/narrow color matching when anti-aliasing is present.
- `--red-hue-tolerance-deg <value>` and `--min-saturation <value>`: tune HSV red extraction for antialiased red-line maps.
- `--reverse`: flip the extracted direction if the preview or in-game direction is wrong.

Always inspect the preview SVG before rebuilding. If the map has branches, pit lanes, alternate layouts, red labels, or heavy decoration, crop or adjust thresholds until the preview shows one clean closed loop.

Low-level ridge diagnostics remain available only where needed for troubleshooting. Failed stabilization, control-spline, and upscale experiments are not part of the supported raster workflow.

For large image-derived tracks, use `trackgen -q` during repeated visual iterations and reserve `trackgen -a -q` for final full generation. Plain `trackgen -q` regenerates the track AC much faster and still reports closure metrics.

<a name="track-menu-map"></a>

## Track Menu Map

Use `torcs-render-track-map` after the final XML plan-view geometry is accepted. The command reconstructs the loop from the current XML segment order. Its combined white start/direction marker crosses the start line and bends into a filled arrow on the left side of travel, pointing in the racing direction. The PNG uses the standard TORCS 1024x1024 transparent RGBA presentation and omits labels and pit highlighting so it remains clear in the track-selection menu. Both modern `Main Track/Track Segments` and legacy `Main Track/segments` XML are supported without modifying the input files.

Run these examples from `torcs/torcs/`:

```powershell
conda run -n torcs-tracktools torcs-render-track-map `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --output runtime/tracks/road/<name>/<name>.png `
  --svg-output runtime/tracks/road/<name>/source/track-map.svg
```

The renderer fits the actual track stroke and combined marker outline into the image, preserving aspect ratio. The default visible margin is `max(2, size/128)` pixels (8px at 1024, 2px at 256), with an additional 3px rendering allowance for antialiasing. Marker space is reserved only where it protrudes, rather than on every side. Elongated tracks naturally leave more space along their shorter dimension.

Both commands accept:

- `--size`: square image size, a power of two from 64 through 1024; default 1024.
- `--margin`: minimum visible artwork-to-edge gap in pixels; defaults to the size-dependent value above. Even `--margin 0` retains the antialiasing allowance. Excessive margins that leave no room for the artwork are rejected.
- `--sample-step`: centerline sampling step in meters; default 2.

The optional single-track review SVG uses a neutral dark background and contains a `track` polyline and a `start-marker` group using the same fitted geometry as the PNG.

### Regenerate All Menu Maps

```powershell
conda run -n torcs-tracktools torcs-render-track-maps --tracks-root runtime/tracks
```

The batch command visits `<tracks-root>/<category>/<name>/` directories in sorted order, reads `<name>.xml`, and writes `<name>.png` alongside it. Missing PNGs are created and existing PNGs are overwritten; nested source directories and auxiliary XML files are not scanned. Each PNG is rendered in a temporary directory beside its destination and verified before replacing it, so a failed render leaves the previous map intact. Replacements preserve existing file permissions; new maps use normal file-creation permissions (respecting the process umask on POSIX). Batch rendering generates PNGs only; use the single-track command for review SVGs.

Output reports `CREATED`, `UPDATED`, or `FAILED` for each track, followed by created/overwritten/failed counts. Missing XML, invalid geometry, and write failures are reported per track while the batch continues. Exit status is 0 only when all tracks succeed, otherwise nonzero. A missing or empty tracks root is an error. Fix the reported tracks and rerun the command to refresh the collection.

After updating an existing editable installation, refresh the console entry points if the new command is unavailable:

```powershell
conda run -n torcs-tracktools python -m pip install --no-deps -e src/tools/tracktools
```

Alternatively, invoke `python -m torcs_track_tools.cli.render_track_maps` with the same arguments through the Conda environment.

<a name="real-pitlane-workflow"></a>

## Real Pitlane Workflow

Use this after the no-pit mainline is accepted and validated in game. Keep pit lanes out of the mainline source cache; fetch pit lanes separately into `source/pitlane-osm.json`.

Fetch a known pitlane way or ordered way list:

```powershell
conda run -n torcs-tracktools torcs-fetch-centerline `
  --way-ids <pit-way-id>[,<pit-way-id>...] `
  --output runtime/tracks/road/<name>/source/pitlane-osm.json `
  --force
```

Run report-only feasibility first and inspect the SVG overlay:

```powershell
conda run -n torcs-tracktools torcs-integrate-pitlane `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --pit-source runtime/tracks/road/<name>/source/pitlane-osm.json `
  --mainline-source runtime/tracks/road/<name>/source/centerline-osm.json `
  --real-placement-report-only `
  --report runtime/tracks/road/<name>/source/pit-real-placement-report.json `
  --real-placement-overlay runtime/tracks/road/<name>/source/pit-real-placement-overlay.svg
```

Proceed only when `real_placement.status` is `real-placement-ok`. The report records side consistency, projected span, and the selected low-curvature pit-main window. Rejections such as `real-placement-rejected-curvature` are expected for pit lanes that TORCS cannot represent cleanly as a side pit over a sufficiently straight host window. Feasibility is not a mutation guarantee: if the chosen window resolves to an `almost` host that cannot preserve the original endpoint pose, integration stops and you should use a manual exact host instead of loosening the pose gate.

Integrate from the accepted real placement:

```powershell
conda run -n torcs-tracktools torcs-integrate-pitlane `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --pit-source runtime/tracks/road/<name>/source/pitlane-osm.json `
  --mainline-source runtime/tracks/road/<name>/source/centerline-osm.json `
  --real-placement-overlay runtime/tracks/road/<name>/source/pit-real-placement-overlay.svg `
  --report runtime/tracks/road/<name>/source/pit-integration-report.json `
  --stage-for-closure
```

The integrator preserves a no-pit backup at `runtime/tracks/road/<name>/source/<name>-no-pits.xml` before the first edit, uses the reported pit side by default, and restores side/border materials after pit entry, pit main, and pit exit so TORCS state carry-over does not leak pit materials around the rest of the track. If the edited XML is already a staging file under `source/`, the backup stays in that same `source/` directory; it should not create `source/source/`.

Close and validate the pitted XML. Prefer the geometric closer with `--profile post-pit` on a staging XML, then promote the staging XML only after the report has `"ok": true`, the XML still starts at `pit_main_b`, `trackgen -z` reports the expected pit count, and side-clearance and side-overlap dry-runs are clean.

```powershell
Copy-Item runtime/tracks/road/<name>/<name>.xml runtime/tracks/road/<name>/source/<name>-pits-geometric-staging.xml -Force
conda run -n torcs-tracktools torcs-close-loop2 `
  --profile post-pit `
  --track-xml runtime/tracks/road/<name>/source/<name>-pits-geometric-staging.xml `
  --runtime-dir runtime `
  --category road `
  --name <name> `
  --report runtime/tracks/road/<name>/source/closure-report-pits-geometric.json `
  --source-polyline runtime/tracks/road/<name>/source/centerline-prepared.json `
  --comparison-svg runtime/tracks/road/<name>/source/closure-report-pits-geometric-overlay.svg `
  --comparison-report runtime/tracks/road/<name>/source/closure-report-pits-geometric-overlay.json
```

The `post-pit` profile preserves the Pit10 start-line convention by keeping `pit_main_b` as the first track segment when it is present and by appending a tiny terminal X lever at the absolute end of the segment list. It defaults to a documented `target-dy = 0.002` tolerance for known `trackgen` millimeter-scale quantization after pit-start rotation; pass an explicit stricter `--target-dy` only when the track closes cleanly under that limit. If direct `--profile post-pit` closure stalls on an otherwise sound pitted XML, use a two-step staging fallback: close the same pitted staging XML once without `--profile post-pit`, then run the geometric closer again with `--profile post-pit` on that pre-closed staging XML. Promote only the second result, after it reports `"ok": true`, starts at `pit_main_b`, and final `trackgen -z` reports the expected pit count. If the geometric closer is unavailable or still fails, use the legacy `torcs-close-loop --profile post-pit` workflow as a fallback diagnostic.

Final checks:

```powershell
.\trackgen.exe -c road -n <name> -z
.\trackgen.exe -c road -n <name> -a -q
```

Run these final `trackgen` commands with `workdir=torcs/torcs/runtime` so `tracks/...` resolves against the runtime tree.

Accept the pitted track only after `pits = 20` unless intentionally overridden, the closure report has `"ok": true`, the side-clearance dry-run reports no anomalies, the side-overlap dry-run reports no unresolved overlaps, and the in-game pit entry/exit plus side/border material transitions look correct.

Automatic synthetic host selection uses these modes:

- `exact`: one existing straight with enough length; safest automatic host.
- `almost`: a contiguous near-straight chain. This is accepted only when the replacement preserves the original chain endpoint pose within the configured tolerance. For a `straight -> shallow turn -> straight` chain, the tool splits the original shallow turn around the pit main instead of replacing it with synthetic correction turns.
- `lengthen` / `inject`: fallback modes that still require strict closure and in-game validation before handoff.

`torcs-integrate-pitlane` safety gates check absolute final `trackgen -z` closure when safety is enabled. For the staged workflow above, `--stage-for-closure` intentionally skips immediate safety gates, then the geometric post-pit closer performs closure on the staging XML. Accept only if final `trackgen -z` passes.

If an `almost` manual host reports a large pose error, the proposed pit straight does not rejoin the original chain at the same endpoint even if total length and heading look plausible. Prefer a different exact host or an intentional local layout refit around the pit area; do not relax the pose gate unless the final staged XML is closed, overlap-safe, and validated in game.

### Manual Pit Host Selection

Use manual host selection when OSM pitlane data is unavailable, ambiguous, rejected, produces a non-pose-preserving `almost` host, or the track is fictional/legacy. In manual mode the user-provided `--pit-side` is authoritative and OSM real-placement selection is skipped.

Single host segment:

```powershell
conda run -n torcs-tracktools torcs-integrate-pitlane `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --pit-side right `
  --host-segment "Main Straight" `
  --report runtime/tracks/road/<name>/source/pit-integration-report.json `
  --stage-for-closure
```

Contiguous host chain:

```powershell
conda run -n torcs-tracktools torcs-integrate-pitlane `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --pit-side left `
  --host-start-segment "Entry Straight" `
  --host-end-segment "Exit Straight" `
  --report runtime/tracks/road/<name>/source/pit-integration-report.json `
  --stage-for-closure
```

Rules for manual mode:

- Use either `--host-segment` or `--host-start-segment` plus `--host-end-segment`; do not mix both forms.
- Host chain selection may wrap the current XML start line. For manual `--host-start-segment`/`--host-end-segment` chains where the end appears before the start in XML order, the integrator rotates the segment list to make the selected host linear before pit insertion.
- `--pit-main-align center` is the default and splits spare host length before and after the pit main. Use `--pit-main-align end` to place all spare length before `pit_main_a`, so the pit main ends at the host end; unless `--entry-taper-length` is explicitly passed, the entry taper is capped to that spare host section and will not reach into the previous turn. Use `--pit-main-align start` for the symmetric case where the pit main starts at the host start and the default exit taper is capped to the spare post-host section.
- Close and validate with the same geometric `--profile post-pit` staging close, side-clearance dry-run, side-overlap dry-run, `trackgen -z`, and `trackgen -a -q` steps used for real-placement pits.

Wrapping example: if the intended host starts near the end of the current XML order and continues after the XML start, keep the real driving order in the arguments:

```powershell
conda run -n torcs-tracktools torcs-integrate-pitlane `
  --track-xml runtime/tracks/road/<name>/<name>.xml `
  --pit-side left `
  --host-start-segment "Late Main Straight" `
  --host-end-segment "Early Main Straight" `
  --report runtime/tracks/road/<name>/source/pit-integration-report.json `
  --stage-for-closure
```

The report records this as `manual_wrap_rotation`. Final pitted XML is still rotated to `pit_main_b` after insertion.

<a name="finding-osm-data"></a>

## Finding OSM Data

Prefer relation-based layout discovery first. List candidates before fetching when a relation may include multiple layouts, pit lanes, shortcuts, or service roads:

```powershell
conda run -n torcs-tracktools torcs-fetch-track-layout `
  --name "Le Mans" `
  --list-layouts
```

Then fetch the selected racing layout. Use a label shown by `--list-layouts`, for example `main`, `all`, `unlabeled`, `forward`, or another relation role:

```powershell
conda run -n torcs-tracktools torcs-fetch-track-layout `
  --name "Le Mans" `
  --layout <chosen-layout> `
  --output runtime/tracks/road/le-mans/source/centerline-osm.json `
  --force
```

Other useful lookup modes:

```powershell
conda run -n torcs-tracktools torcs-fetch-track-layout --relation-id 2126739 --list-layouts
conda run -n torcs-tracktools torcs-fetch-track-layout --relation-id 2126739 --layout <chosen-layout> --output <cache.json>
conda run -n torcs-tracktools torcs-fetch-track-layout --lat 47.95 --lon 0.22 --list-layouts
```

Use direct way IDs when the relation contains pit lanes, shortcuts, kart tracks, service roads, or multiple layouts that cannot be separated by role:

```powershell
conda run -n torcs-tracktools torcs-fetch-centerline `
  --way-ids 25245509,34405892,1358131505 `
  --output runtime/tracks/road/example/source/centerline-osm.json `
  --force
```

### How Users Can Help

If automatic OSM discovery is ambiguous, useful user-provided data is:

- OpenStreetMap relation ID for the circuit.
- Exact OSM circuit name.
- Centerline way IDs in approximate driving order.
- Way IDs to exclude, especially pit lanes, shortcut variants, kart loops, service roads, and alternate chicanes.
- Expected real-world length and expected racing direction.

Manual discovery options:

- Open `https://www.openstreetmap.org`, enable the map data layer, click the centerline, and record `Relation <id>` or `Way <id>`.
- Use Overpass Turbo with a bounding box around the track:

```overpass
[out:json][timeout:60];
way["highway"="raceway"](south,west,north,east);
out ids tags geom;
```

Relation-oriented query by location:

```overpass
[out:json][timeout:60];
relation["leisure"="track"]["sport"="motor"](around:5000,lat,lon);
out tags;
>;
out geom;
```

<a name="osm-filtering-checklist"></a>

## OSM Filtering Checklist

Before fitting, inspect the cache summary and reject noisy sources early:

- Endpoint gap should be near `0.0 m` for a closed-loop mainline.
- Overlap diagnostics should normally be `0`.
- Length should be plausible for the requested layout.
- Pit-lane ways should be excluded from the mainline cache.
- Shortcut layouts, alternate chicanes, kart tracks, and service roads should be excluded unless explicitly requested.
- If relation roles include multiple layouts, use `--list-layouts`, then try `--layout main`, `--layout all`, or a specific role before hand-curating way IDs.

<a name="common-scenarios"></a>

## Common Scenarios

| Scenario | Action |
| --- | --- |
| Track races in the wrong direction | Rebuild with `--reverse-input`; do not reverse XML by hand. |
| Relation includes pit lane | Refetch/filter OSM; keep pits out of no-pit mainline conversion. |
| Relation includes shortcuts or alternate layouts | Use `--list-layouts` or manually curated `--way-ids`. |
| Fit is slow after reversing | Ensure current tools are installed; avoid `--no-fit-cache` unless the cached DP draft is suspected stale. |
| Closure reports a sub-millimeter Y residual such as `0.000977` | This is within the default `0.001 m` Y gate; mention the residual in the summary and keep other axes strict. |
| Direct pitted `--profile post-pit` close stalls | Pre-close the pitted staging XML once with geometric closure without `--profile post-pit`, then close that staging XML again with `--profile post-pit`; promote only the final pit-start-preserving XML. |
| Pit host names changed after curbs | Re-read the current XML and select from the post-curb segment names; outside curbs can split hosts into `-pre`, `-curb`, and `-post` pieces. |
| Outside curb splits disturb closure | Prefer whole-segment outside curb assignment with `--segment-fit-ratio 0`, then rerun `trackgen -z`, side-clearance dry-run, side-overlap dry-run, base generation, raceline generation, and ACC merge. |
| Pits, curbs, or elevation changed after raceline merge | Regenerate the base `.ac`, rerun `trackgen -r`, and rerun `accc -g`; do not keep an `.acc` merged against stale XML geometry. |
| Almost pit host has a large pose error | Use an exact host or locally refit the surrounding track geometry so the pit straight is part of the intended layout; do not accept large pose errors as a shortcut. |
| Baseline angle is above 2 degrees but closure seems plausible | `torcs-rebuild-mainline` defaults to a wider baseline gate; final promotion still requires strict closure targets. |
| A previous run was killed | Check and remove stale `runtime/.trackgen-<category>-<name>.lock` if present. |
| `trackgen` cannot find `tracks/.../<name>.xml` | Run `trackgen` from `runtime/`, or pass tools a correct `--runtime-dir`. |
| Closure config names segments that no longer exist | Rerun closure with `--force-reselect` rather than editing the JSON manually. |
| TORCS lists throwaway `zz-*` tracks | Remove local verification folders from `runtime/tracks/...` before manual testing. |
| Menu warns about missing `<name>.png` | Generate `<name>.png` with `torcs-render-track-map`. |

<a name="validation-checklist"></a>

## Validation Checklist

Accept generated live XML only after:

- `closure-report-mainline.json` has `"ok": true`.
- Final `Delta X`, `Delta Y`, `Delta Z`, and `Delta Ang` are within the reported targets.
- Side-clearance and side-overlap reports have no unresolved issues for the final live XML.
- `pits` is `0` for no-pit mainline rebuilds.
- In-game direction matches expected racing direction.
- The final XML has a current `<name>.png` generated by `torcs-render-track-map`, with matching start and direction markers.
- Visual road geometry and drivable/collision edges agree after `trackgen -a -q` generation.
- If `Graphic/3d description` points to a merged `.acc`, the final `.acc` was regenerated after the last XML, elevation, pit, or curb change and still includes all intended layers, such as raceline.
- Generated runtime artifacts are normally ignored/local; commit tracked tool/docs/source changes only unless intentionally packaging track assets.

<a name="developer-checks"></a>

## Developer Checks

These checks are for changes to the Python tools themselves. Track authors can use the workflow reports and in-game validation above. Run the local quality suite from `torcs/torcs/src/tools/tracktools/` when you want tests plus coverage and code metrics in one pass:

```powershell
scripts\run-quality.ps1
```

If PowerShell blocks local scripts, run the same suite with a per-process policy bypass:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-quality.ps1
```

The quality runner writes reports under `build/quality/`, including branch coverage HTML/JSON/XML, `radon` cyclomatic complexity, maintainability index, `xenon` thresholds, cognitive complexity, `bandit`, and `vulture` output. By default `ruff`, pytest, a 75% line coverage floor, and a 65% branch coverage floor are hard gates; advisory tools are summarized but do not fail the command unless `--strict-advisory` is passed. Raise `--coverage-fail-under <percent>` and `--branch-fail-under <percent>` only after adding characterization tests and confirming the new baseline is stable.
