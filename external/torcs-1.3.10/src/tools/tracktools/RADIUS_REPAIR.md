# Large-radius audit and local repair

These utilities preserve the September 2026 Mogyorod pilot. They start with the
**current track XML**, so manual changes remain authoritative. Keep the existing
compatible track loader: replacing the data is optional track maintenance, not
a substitute for preserving loader behaviour.

## Inventory (cross-platform, read-only)

From the TORCS solution directory:

```powershell
conda run -n torcs-tracktools torcs-audit-track-radii --tracks-root runtime/tracks --report radius-audit.json
```

The default threshold is 4000 metres (`--limit` overrides it). The scan visits
only `category/name/name.xml`, excluding historical `source/` XMLs. It handles
modern and legacy segment lists, start/end radii, and common radius units.
The JSON includes each segment name, radii in metres, local child sections, and
direct pit references, plus explicit banking attributes. A radius above the limit is a screening result, not a
claim that the track is broken. Malformed files are reported and produce a
nonzero exit status after the rest of the collection is scanned.

Add `--preflight` to classify the remaining tracks as `eligible_for_fitting` or
`blocked`, with per-segment reasons from the repair tool's own schema/reference
checks. A track is eligible only if every audited segment is supported. This is
a read-only batch-planning aid; eligibility does not guarantee that numerical
fitting or final geometry checks will pass. Use the default 4000 m threshold
when planning complete-track repairs. Preflight requires that exact threshold;
a higher custom screening limit could otherwise omit a blocked oversized curve.

The maximum radius is shared with layout generation as
`core.geometry.MAX_TORCS_RADIUS_M`. Closure defaults and radius-repair movement
tolerances live in `core/defaults.py`; audit, fit validation, pit validation and
batch finalization use those definitions. Distance-unit factors are also shared
with the map tooling and match TORCS's legacy feet conversion. Numeric examples
in this document describe the current defaults.

## Local repair pilot (Windows x64 development builds)

Install the optional fitting dependency and command entry points:

```powershell
conda run -n torcs-tracktools python -m pip install -e "src/tools/tracktools[repair]"
```

Requirements: an x64 TORCS runtime and its **matching private track PDB**, plus
Windows DbgHelp (the x64 Windows SDK debugger library is preferred when installed).
The probe obtains structure offsets from that PDB and checks scalar/array sizes;
there are no manually pinned `tTrack`/`tTrackSeg` offsets. It fails if suitable
symbols are unavailable. This is a local development utility, not an installer
runtime feature. Run via `conda run` so SciPy's native dependencies are available.

```powershell
conda run --no-capture-output -n torcs-tracktools torcs-repair-track-radii `
  --input runtime/tracks/road/mogyorod-circuit/mogyorod-circuit.xml `
  --runtime-dir runtime `
  --segment Hungaroring-22 --segment Hungaroring-65 `
  --work-dir C:/track-work/mogyorod-radius-pilot
```

This example refers to the **pre-repair** Mogyorod XML. Those two sections have
already been repaired in the accepted live track; repeating it against the live
version is intentionally rejected. To reproduce the pilot, extract its
`source/radius-repair-20260925/before.zip` into a scratch directory, use that XML
as `--input`, and pass `--resource-dir` pointing at the live track directory to
resolve the saved XML's external entities. The work directory must be new and
outside the input track tree. `--symbols-dir` overrides the default
`<runtime-parent>/src/modules/track/Release` search directory.

### Straight–curve–straight mode

Use `--method scs` to retain a shallow curve's original turn direction using a
straight, a bounded-radius curve, and a final straight. `--curve-radius` sets
the middle curve's radius (default 3000 m; must be positive and at most 4000 m).
The fitter requires a resolved loaded turn and positive straight lengths; it
reports an unsuitable pose rather than silently choosing another layout.

For example, the remaining post-curb sections of the Mogyorod pilot can be
completed from their pre-completion XML with:

```powershell
conda run --no-capture-output -n torcs-tracktools torcs-repair-track-radii `
  --input runtime/tracks/road/mogyorod-circuit/mogyorod-circuit.xml `
  --runtime-dir runtime --method scs --curve-radius 3000 `
  --segment Hungaroring-10 --segment Hungaroring-20 `
  --work-dir C:/track-work/mogyorod-completion
```

The first straight keeps the original name, the middle curve is named
`:radius-turn`, and the final straight is named `:radius-out`. The elevation
cubic is split at the actual part-length fractions, with continuous heights
and grades at both joins. Pass the same `--method` when validating a saved
candidate. The method and requested middle radius are recorded in the report.

### Whole-track selection and mixed methods

`--all-over-limit` uses the existing radius audit to select every curve above
4000 m in the input XML. It is mutually exclusive with `--segment`.
`--method auto` chooses straight–curve–straight when the loaded endpoint pose
admits positive straights, otherwise the two-arc fit. The chosen method for each
section is recorded in `methods` in the JSON report. Auto mode gives endpoint
heading a stronger fitting weight so small heading errors do not accumulate
across a whole track. Explicit `biarc` and `scs` retain their original settings.

```powershell
conda run --no-capture-output -n torcs-tracktools torcs-repair-track-radii `
  --input runtime/tracks/road/maple-island-raceway/maple-island-raceway.xml `
  --runtime-dir runtime --all-over-limit --method auto `
  --work-dir C:/track-work/maple-island-complete
```

Use the pre-repair XML for reproductions; already repaired tracks have no
oversized sections. Auto validation recognizes each replacement's names.
Unsupported selected data stops the job; no oversized section is silently skipped.

Auto mode can also use `sbbs` (straight–biarc–straight) when a full-length biarc
cannot match the loaded endpoint with radii at most 4000 m. Its two arcs occupy
the middle eighth of the fitted length, leaving equal straight pads. Names are
the original name, `:radius-in`, `:radius-turn`, and `:radius-out`. This permits
near-straight legacy sections with very small lateral offsets to be repaired
without relaxing the endpoint or whole-track preservation checks.

Auto mode preserves the source curve's native angular subdivision count, so
changing the radius does not inadvertently change the float exit-heading grid.
For long shallow bends it distributes SCS turns across multiple cells instead
of concentrating the entire heading change into one short curve. These cells
use numbered `:radius-turn-N` / `:radius-pad-N` names and retain the original
endpoint/profile checks. Reports record the selected cell and subdivision counts.

For long runs, `fit-progress.json` is atomically updated after each fitted section.
Use `--resume-report <report.json-or-fit-progress.json>` with the same input,
selection, method, curve-radius setting and seed, plus a new work directory.
The input XML and DLL hashes must match. Reports also record the exact candidate
XML SHA-256, so a batch can safely recover a completed fit even if interrupted
before recording that hash in its manifest. Saved endpoints are rechecked, poor
fits are refined, and the complete final candidate is always validated again.
`--polish-closure` optionally adjusts tiny turn-angle increments in the last
eight selected repairs and the final selected SCS straight lengths to approach
the original seam pose; unselected XML is
never adjusted. Always verify final closure with `trackgen -z`, whose printed
float-angle normalization can differ slightly from the Python report.
If the original XML already has an out-of-tolerance gap, the target is projected
inside the existing closure limits rather than preserving that bad gap. Small
length corrections may be distributed among differently oriented selected
straights to correct both axes. No geometry acceptance limits are widened.

During fitting, the native probe uses the loader-assigned segment IDs to obtain
endpoints efficiently. Tests compare this fast path exactly with full snapshots;
the final acceptance checks still inspect the complete loaded geometry.

### Supported sections

The fitter accepts constant-radius spline curves with explicit `z start`, `z end`, start/end profile
tangents, and metres/degrees/percent units. Constant `Left Border`/`Right Border`
resets with explicit metre width, `plan` style and surface are supported in
both methods; an optional nonnegative metre height is also supported. Constant
`curb` borders are supported with explicit height, width and surface. Left/right
side widths are replayed in original segment order using the v4 loader's
`start width -> width -> end width` defaults. Linear tapers are subdivided at
the replacement stations; inherited surfaces, banking-type declarations and
comments are retained. Constant side and border XML is copied verbatim.
Validation checks taper endpoints/continuity and that no non-width content
changed. This preserves resets after preceding curbs and state for following
segments. Tapered borders, walls,
additional attributes, variable radii, existing replacement names,
and references from pit start/end, cameras or other sections require manual
treatment and are rejected. Pit entry/exit references have the support below.
Other track sections, including manually edited curbs/pits/materials, are
preserved byte-for-byte apart from the explicitly validated pit exit reference.

Tracks with omitted elevation fields are supported only when every segment's
supplied height/grade/tangent is zero, with no banking or edge-height overrides
and no explicit non-spline profile. The fitter materializes zero heights and
tangents only in selected replacements and verifies the native road is flat.
Ambiguous/non-flat inherited profiles remain unsupported.

### Pit entry and exit markers

The v4 loader resolves pit entry to the first generated subdivision of the named
section, and exit to the last. SCS fitting splits off an original-length marker
from the corresponding straight pad, leaving exactly one native marker segment.
Entry retains its original name; exit points to `:radius-out`. Only that exit
attribute is rewritten; all other pit XML remains byte-identical. Insufficient
padding, non-SCS fits, and other external references are rejected.

Native snapshots include entry, exit, pit start and pit end, with both physical
boundaries, length, lap station and race flags. Validation checks marker length
within 2 mm and unchanged flags. Physical road-edge boundaries use the existing
selected-road limits (15 cm XY / 2 cm Z), or 2 mm for untouched road. Thus both
AI conventions—using the start or end of the exit segment—retain their marker
interval. Recomputed absolute lap stations are reported separately: preceding
repaired road can change nominal lap length without moving a marker physically.

Banked input must specify both banking endpoints in degrees, strictly between
-90 and 90, plus the common endpoint profile tangents. The original loader
constructs separate Hermite splines for the two road edges. The repair splits
those cubics, writes the new boundary bank angles, and uses independent left/right
tangents at each join. It does not linearly interpolate banking angles or reimport
the DEM. Shared tangent attributes are omitted from banked replacement parts
because they would override the individual edge tangents in the loader.
Endpoint banking/edge grades, join continuity and sampled edge heights are checked.

By default (`--method biarc`), two equal-length tangent-connected arcs are fitted to the **actual loaded**
start/end poses. This matters because enormous-radius float calculations can
produce endpoints substantially different from ideal double-precision circles.
The first part keeps its name; the second gains `:radius-out`. Endpoint heights
and endpoint grades are retained and the cubic elevation profile is split with
a common midpoint height/grade. The deterministic refinement seed is recorded
in the report (`--seed`, default 22). Different loaders may yield different fits.

### Outputs and acceptance

- `before.zip`: complete input track directory snapshot; `before.xml`: input XML.
- `trial.xml`: throwaway loader input with relocated external-entity paths.
- `report.json`: source/DLL/candidate hashes, seed, parameters, radii, sampled movement,
  road-edge closure, origin shift, native pit-marker measurements, pit count and
  fixed-wall run count.
- `candidate.xml` on success, or `candidate-rejected.xml` on a failed geometric
  gate, with a nonzero exit status. The live track is never overwritten.

Acceptance checks: all replacement radii at most 4000 m; unchanged XML outside
selected blocks (except the validated pit exit reference); original endpoint heights/grades; local sampled XY movement at
most 10 cm and Z movement at most 2 cm; sampled road-edge XY movement at most
15 cm and Z movement at most 2 cm; outer side edges use the same sampled limits;
unaffected logical-segment endpoints
and road vertices within 2 mm; normalized origin, untouched outer side vertices
and native extents within 2 mm; unchanged pit count
and fixed-wall run count; road-edge closure
within 0.5 mm X, 1 mm Y, 0.05 mm Z and 0.0001 degrees. Local profile comparisons
sample the loader's piecewise geometry at 501 corresponding normalized stations;
they are not a proof of continuous surface identity. The wall-run diagnostic
uses simuv2's split conditions, not a full physics collision simulation.

To re-check a candidate without fitting, supply `--validate-candidate path.xml`
with the original `--input`, the same selected segments and a new work directory.

## Finalize a reviewed candidate

1. Review the XML diff and movement report, especially any nominal lap-length
   change. Keep the input snapshot and original generated assets.
2. Run side-clearance and side-overlap validators with `--dry-run`.
3. Run `trackgen -z` against the candidate; regenerate road/terrain, raceline,
   and merged ACC together in staging. For trackgen, `-i` and `-o` name
   **directories**, and the XML must be named `<track-name>.xml`.
4. Regenerate the labeled SVG and menu map. Inspect the staged model, then copy
   the accepted XML and corresponding generated assets into the live track.
5. Repeat closure validation on the deployed track and perform in-game practice
   and visual checks before proceeding to the next track.

The tools stop after candidate generation/validation. Finalization uses the
existing trackgen/accc/map tools so hand-edited assets can be reviewed explicitly.
For unattended whole-track orchestration, see [RADIUS_BATCH.md](RADIUS_BATCH.md).

## Accepted Mogyorod reference

The original 702514.779 m and 3040368.718 m radii were replaced with approximately
3553/3517 m and 467/467 m arc pairs. The 119 other original segment sections were
unchanged. Maximum sampled local movement was 1.1/6.8 cm in plan and 5/1 mm in
height. Trackgen retained the original closure (X 0.000366 m, Y -0.000793 m),
20 pits and one continuous pit wall. Reported length decreased about 0.90 m
because the old nominal segment length differed from its loaded geometry.
The user accepted the in-game result. These measurements document the pilot;
the reusable tool always measures its own candidate rather than assuming them.

## Tests and quality checks

From `src/tools/tracktools/`, run `python scripts/quality.py` for the complete
quality report. Focused tests are in `test_radius_repair.py`,
`test_radius_repair_cli.py`, `test_radius_repair_scs.py`, `test_radius_profiles.py`, `test_radius_pits.py`, and
`test_track_loader_probe.py` under `tests/`.
They cover XML/profile preservation, both fitting directions, candidate
rejection, backups, concurrent input edits, and loader wall-run diagnostics.
The native integration tests also load a small synthetic track through the
actual DLL/PDB and verify that snapshots survive subsequent loader calls.
They also verify planar border resets after a curb on both sides through the
actual loader, including the following unsplit segment.
Banked profile tests verify both road-edge cubics mathematically and through
the native loader, and check constant-curb/side preservation and auto selection.
Those integration tests are skipped when a Windows x64 development build is
unavailable; the portable tests still run.
