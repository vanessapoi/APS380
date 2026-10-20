# Trackgen Regression Tests

This directory contains isolated track fixtures, reference AC files, and tools
for checking changes to `trackgen`. The tests catch crashes, timeouts, unexpected
geometry changes, invalid AC structure, non-finite coordinates, duplicate
triangles, and collapsed terrain surfaces.

## Scope

The XML files under `source/` are test fixtures. They are intentionally
independent of the playable tracks under `data/tracks/` and `runtime/tracks/`.
Changes made for a regression fixture must remain under `test/trackgen/` unless
a separate track-data change is explicitly intended and reviewed.

Generated files belong under `generated/` or in an external report directory.
Do not commit temporary reports or unreviewed generated output.

## Directory Layout

| Path | Purpose |
| --- | --- |
| `data/` | Resources required while processing fixture XML files |
| `source/` | Track inputs and reviewed reference AC files |
| `generated/` | Disposable output from the current `trackgen` build |
| `generate.sh` | Simple shell runner for all fixtures |
| `run_regression.py` | Monitored runner with timeouts, logs, filtering, and JSON reporting |
| `validate_ac.py` | Structural and geometric validator for generated terrain AC files |
| `validate_crossing_seams.py` | 3D crossing-part perimeter checks against track and terrain edges |
| `compare_ac.py` | Comparison with reviewed references, ignoring CRLF/LF differences by default |
| `clean.sh` | Removes generated AC files |
| `test_trackgen_tools.py` | Unit tests for the Python tools |

## Requirements

- A built `trackgen` executable.
- Python 3 for the monitored runner and AC validator. They use only the Python
  standard library.
- A shell with Bash support for `generate.sh` and `clean.sh`.

Run the examples below from the solution root unless noted otherwise.

## Automatic Crossing Checks

The C++ crossing tests exercise plan detection, elevation and clearance
rejection, closed-loop adjacency, deterministic multiple crossings, renderer
endpoint reuse, socket/floor topology, bridge-underside triangulation, connected
terrain-domain discovery, and relief-segment clipping. Portal checks exercise
sampling from 0.5 to 20 m, both oblique crossing directions, aligned endpoints,
curves, width steps, slopes/banking, and zero socket gap. Object-split checks
cover coplanar vertical extensions and aligned oblique returns. Shared portal edges
must have two incident faces with opposite winding. After building
`Release|x64`, run:

```powershell
x64/Release/trackcrossing_test.exe
```

`road/wheel-2` is the primary single-crossing trackgen fixture. Generate it with
the monitored runner:

```powershell
python test/trackgen/run_regression.py `
  --trackgen runtime/trackgen.exe `
  --report-dir trackgen-report `
  --track road/wheel-2
```

The run should report one candidate and one accepted crossing. Review
`test/trackgen/generated/road/wheel-2/wheel-2-trk.ac` and confirm that the track
group contains one `TRKCROSS0` group with `TRKBRIDGE0`, `TRKSOCKET_R0`,
`TRKSOCKET_L0`, `TRKFLOOR_R0`, and `TRKFLOOR_L0` children. Check that surfaces
are finite and non-degenerate, the bridge underside faces downward, socket walls
face the lower track, and track-facing seams exactly reuse normal track vertices.

The bridge and socket children are groups, with the following polygon parts:

```text
TRKCROSS0
  TRKBRIDGE0
    TRKBRIDGE_UNDERSIDE0
    TRKBRIDGE_R0             (right fascia plus coplanar vertical extensions)
    TRKBRIDGE_L0             (left fascia plus coplanar vertical extensions)
  TRKSOCKET_R0
    TRKSOCKET_WALL_R0
    TRKFILLER_RR0
    TRKFILLER_LR0
  TRKSOCKET_L0
    TRKSOCKET_WALL_L0
    TRKFILLER_RL0
    TRKFILLER_LL0
  TRKFLOOR_R0
  TRKFLOOR_L0
```

Filler letters mean **upper-track side, lower-track side**, not entry/exit.
Usually each filler contains one inclined triangle. A return fully coplanar
with the fascia is included in that fascia instead; an aligned oblique return
can retain two triangles in its filler. Named empty filler/floor objects are
retained for a stable hierarchy (for example at aligned corners or zero gap).
There are eleven polygon objects per crossing, independently of road sampling.

### Crossing texture checks

The four default materials are `bridge-underside`, `bridge-side`, `bridge-socket`,
and `bridge-floor`. They select the corresponding PNGs, using 14 x 7 m nominal
tiles for the structural parts and 4 x 4 m tiles for the ground connectors.
Fascia includes the coplanar vertical closure extensions; the other portal
fillers use the socket material. See
[`EASYMESH.md`](../../src/tools/trackgen/EASYMESH.md#crossing-materials-and-texture-coordinates)
for the surface selectors, independent V sizing, fitting, and fallback rules.

The C++ texture tests check physical scales, cropping, proportional enlargement,
underside orientation, shared floor phase, filler/socket anchoring, surface
overrides, invalid/missing sizes, version-3 lookup, and geometry preservation.
Portal tests also reject collapsed UV triangles, including curved, sloped,
width-step, fine-sampling, and aligned-corner cases. In exported models, check:

- Finite, non-collapsed texture coordinates.
- Underside U within [0, 1], with repetition allowed along V (the span).
- Fascia/socket/filler V within [0, 1], including the closing geometry.
- Four-metre floor tiling in both directions, not stretched to strip width.
- Vertical weathering on walls and sensible local projection on inclined returns.

`validate_ac.py` validates terrain structure in `*-msh.ac`. A sibling
`*-trk.ac` is authoritative when present; only when it is absent does validation
fall back to crossing objects in the combined `.ac` file. Projected terrain
triangles must not overlap `TRKBRIDGE*`, `TRKSOCKET*`, `TRKFILLER*`, or `TRKFLOOR*`
triangles. The JSON result records whether this crossing-overlap check completed.
A successful validation does not replace the focused C++ tests and visual review
of the generated crossing.

### Crossing seam validation

Run the crossing-part perimeter check on the three crossing fixtures:

```powershell
python test/trackgen/validate_crossing_seams.py `
  test/trackgen/generated/road/multi-cross-7/multi-cross-7-trk.ac `
  test/trackgen/generated/road/over-under-2/over-under-2-trk.ac `
  test/trackgen/generated/road/wheel-2/wheel-2-trk.ac
```

Each input requires its sibling `*-msh.ac`. The checker rejects collapsed or
duplicate crossing triangles and non-manifold edges within each crossing part,
then checks every part's perimeter against visible track/crossing/terrain edges.
It measures coverage in 3D with a 0.1 mm tolerance for serialized coordinates;
subdivided matching edges are accepted, and internal gaps remain failures.
Degenerate road-strip triangles cannot count as closure. This is a crossing seam
check, not a watertightness requirement for the entire open road/terrain model.
Use `--report existing-directory/seams.json` to save the diagnostics.

The original portal-closure regression was checked against its pre-change baseline:

| Fixture | Accepted crossings | Terrain domains | Added closure triangles |
| --- | ---: | ---: | ---: |
| `multi-cross-7` | 7 | 9 | 56 |
| `over-under-2` | 2 | 4 | 16 |
| `wheel-2` | 1 | 3 | 8 |

All 40 formerly open socket-end edges are closed. For the original fixture
settings, terrain output is byte-identical and all pre-existing track/crossing
triangles are unchanged. Disposable copies with 5 m steps, 2 m steps, and zero
socket gap also pass seam and terrain-overlap validation for all three fixtures.
The reviewed reference AC files include the role-specific materials and mapping.
Compared with the earlier untextured object split, the six crossing
`.ac`/`-trk.ac` files change only texture names and UVs, preserving geometry,
winding, part ownership, and ordinary track appearance. All 123 AC files across
the 41 fixtures match their reviewed references after CRLF/LF normalization.
All 41 terrain meshes pass validation. The nine sampling/gap variants
above also pass seam, terrain-overlap, protected-axis and UV-area checks.
Sampling variants belong under
`generated/`; update references only after separately reviewing their changes.

## Monitored Regression Runner

The monitored runner executes each track in a separate process. A crash or
timeout is recorded without preventing later tracks from running. Standard
output and standard error are saved per track, while `report.json` is updated
after every state change.

Windows example:

```powershell
python test/trackgen/run_regression.py `
  --trackgen runtime/trackgen.exe `
  --report-dir trackgen-report
```

Linux example:

```bash
python3 test/trackgen/run_regression.py \
  --trackgen /path/to/trackgen \
  --report-dir trackgen-report
```

Run selected tracks by repeating `--track` with `category/name` labels:

```powershell
python test/trackgen/run_regression.py `
  --trackgen runtime/trackgen.exe `
  --report-dir trackgen-report `
  --timeout 60 `
  --track road/brondehach `
  --track road/wheel-2
```

The runner is synchronous and a full run can take several minutes. Run it
directly from a terminal. It exits with status `0` only when every selected
track passes. Use `python test/trackgen/run_regression.py --help` for all
options.

Each report result has one of these statuses:

| Status | Meaning |
| --- | --- |
| `passed` | `trackgen` exited with status 0 |
| `failed` | `trackgen` returned a non-zero exit status or crashed |
| `timed_out` | The per-track timeout expired |
| `launch_failed` | The executable could not be started |

## AC Validation

`validate_ac.py` scans generated `*-msh.ac` terrain files. It verifies:

- AC3D object hierarchy and record structure.
- Finite vertices and texture coordinates.
- Vertex reference bounds.
- Exactly three distinct references per terrain surface.
- No duplicate terrain triangles within an object.
- Non-zero triangle area above the configured threshold.
- No accumulated projected overlap for a terrain/crossing object pair above the
  configured tolerance.

Validate every generated terrain mesh:

```powershell
python test/trackgen/validate_ac.py `
  --report trackgen-report/validation.json
```

Validate selected tracks:

```powershell
python test/trackgen/validate_ac.py `
  --track road/brondehach `
  --track road/wheel-2
```

The validator exits with status `0` only when every requested mesh exists and
passes. The `--minimum-area` option controls the minimum doubled triangle area.
The `--maximum-crossing-overlap` option defaults to `1e-5` square metres per
terrain/crossing object pair. This allows AC3D decimal serialization noise while
preventing finer triangulation from hiding a continuous terrain sliver. Use
`python test/trackgen/validate_ac.py --help` for all options.

## Shell Workflow

On systems with Bash, the original runner remains available:

```bash
test/trackgen/generate.sh /path/to/trackgen
```

Unlike the Python runner, `generate.sh` does not provide per-track timeouts,
separate logs, or an incremental JSON report.

To remove generated AC files, run `clean.sh` from this directory:

```bash
cd test/trackgen
./clean.sh
```

## Updating References

1. Build the intended `trackgen` configuration.
2. Run the regression suite into `generated/`.
3. Run `validate_ac.py` on the generated terrain meshes.
4. Run the reference comparison:

```powershell
python test/trackgen/compare_ac.py `
  --report trackgen-report/comparison.json
```

The comparator reports missing, extra, and changed AC files and exits non-zero
for any content difference. By default it compares bytes with CRLF normalized
to LF in memory on both sides; it does not rewrite generated or reference files.
Other whitespace, lone CRs, numeric formatting, and missing final newlines still
count as differences. `LINE_ENDINGS_ONLY` counts files that match only after
normalization; JSON retains the original byte-level SHA-256 digests and marks
those matches with `lineEndingsOnly`. Add `--strict` for byte-for-byte comparison
including line endings. Use repeated `--track category/name` arguments to compare
a subset. Review intentional content changes manually before updating references.

5. Compare changed files under `source/` and `generated/`.
6. Manually review every intentional geometry change.
7. Copy only accepted generated AC files into the matching `source/` fixture.
8. Rerun generation, validation, and comparison before committing the new references.

Large AC diffs are expected when triangulation changes, but they must not be
accepted solely because `trackgen` returned success.

## Tool Tests

Run the Python unit tests without launching `trackgen`:

```powershell
python -m unittest discover -s test/trackgen -p "test_*.py"
```
