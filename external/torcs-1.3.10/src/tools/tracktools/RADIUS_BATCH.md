# Resumable whole-track radius batches

`torcs-batch-repair-track-radii` orchestrates the existing audit, repair,
side validators, trackgen, accc, and map/label tools. Each track is completed
as one unit. Unsupported tracks and failed candidates are reported and the
queue continues; there is no per-track interactive approval step.

Run from the TORCS solution directory in the `torcs-tracktools` environment.
The native fitter currently requires the Windows x64 runtime and matching
private track PDB described in [RADIUS_REPAIR.md](RADIUS_REPAIR.md).

## Small batch

```powershell
conda run --no-capture-output -n torcs-tracktools torcs-batch-repair-track-radii `
  --runtime-dir runtime --work-dir runtime/radius-batches/pilot-20260925 `
  --track road/saxony-anhalt-circuit `
  --track road/montseny-circuit-flowkiller `
  --track road/pelican-bay-oval --jobs 2
```

Without `--deploy`, this runs the complete fitting, validation and asset
generation pipeline in staging. To deploy successful staged tracks without
refitting or regenerating them:

```powershell
conda run --no-capture-output -n torcs-tracktools torcs-batch-repair-track-radii `
  --runtime-dir runtime --work-dir runtime/radius-batches/pilot-20260925 `
  --resume --deploy --jobs 2
```

Or include `--deploy` on the initial command for an unattended repair/deploy
batch. Use `--all` instead of `--track` to queue the full affected collection.
The work directory must be new for a new batch and outside `runtime/tracks`.
Use `--resume` without a selection to continue all unfinished jobs. Add repeated
`--track category/name` options to retry only a subset of the original batch;
the consolidated report still includes the other jobs and their exceptions.

For a rejected fit, `--curve-radius <metres>` forwards the existing fitter's
radius setting (positive, at most 4000 m). Changing it starts a fresh fitting
attempt instead of reusing incompatible parameters. When omitted, resume keeps
the last attempt's radius; new fits default to 3000 m. An accepted saved fit with
a different explicitly requested radius is rejected rather than silently reused.

Use `--resume --diagnose` without `--deploy` to measure failed tracks' original
native closure and write `diagnostics.md`, comparing original versus rejected
seams and preservation errors. This performs no fitting or asset replacement.

## State, concurrency and exceptions

- `manifest.json` is updated atomically as tracks advance and contains one
  consolidated summary, source/DLL hashes, fit measurements, native closure,
  current phase, errors, and staged-file hashes.
- `summary.md` is the concise final track/status/closure/exception table for
  reviewing the batch without opening every individual report.
- Track status is `staged`, `deployed`, `already_clear`, `blocked`, or `failed`.
  Blocked/failed tracks cause a nonzero final exit code, but do not stop other
  jobs. The manifest identifies the exceptions for later targeted work.
- `--jobs` supports 1–4 independent fitting/generation workers (default 2).
  Each native fitting job runs in its own process. ACC merges are serialized
  because accc/stripe use shared runtime temporary files. OS locks also prevent
  two batch processes from concurrently repairing the same track or merging.
- `--timeout` is the per-command timeout in seconds (default 1800). Timed-out
  process trees are terminated so a lingering stripe process cannot continue
  writing shared merge files. Logs are retained per track and phase.
- An interrupted/rejected fit resumes from its report/checkpoint in a new
  attempt directory. Valid fitted candidates are reused after generation
  failures. Staged assets are hash-verified before deployment. Deployed and
  already-clear tracks are skipped on subsequent resumes.
- Changed source XML or a changed track DLL stops that track/resume rather than
  silently applying stale parameters. Use a new batch for later source edits.
- Reused candidate XML must match the SHA-256 in its accepted fit report (or the
  stored manifest hash for older reports). A candidate with no validation hash
  is rejected rather than silently trusted after an interruption. Revalidate
  such a legacy candidate with `torcs-repair-track-radii --validate-candidate`
  in a new work directory; retain the old backup and reports.

## Validation and deployment

The runner requires all radii to be at most 4000 m, the fitter's full geometry
checks to pass, side validators to report no anomalies or proposed reductions,
and `trackgen -z` to pass its printed road-edge/heading closure limits with the
same pit count. It supports standard `<name>.ac` / `<name>.acc` visual targets;
nonstandard hand-authored scene targets require manual asset review.
Pit-aware candidates also preserve native entry/exit marker lengths and flags,
and both physical boundaries within the existing road-geometry limits. Details
and nominal lap-station reporting are described in [RADIUS_REPAIR.md](RADIUS_REPAIR.md).

Before any live replacement, every original input file is checked against the
fitter's complete backup. A new file that appeared at a replacement destination
after the snapshot is also rejected, so a newly created user asset cannot be
silently overwritten. A persistent copy of `before.zip`, the original XML,
and reports is placed under `source/radius-batch-<batch-id>/` in the track.
Only generated models, raceline, menu map, labels, and the accepted XML are
replaced. XML is installed last. Terrain heightmaps, relief source data, other
assets and hand-edited README text are retained.
The installed XML is checked again with native `trackgen -z` before the
deployment is committed; a failed live closure/pit-count check rolls it back.

An explicitly reviewed, pre-existing clearance warning can be retained with
`--accept-existing-clearance CATEGORY/TRACK:SEGMENT` (repeat for multiple named
conditions). This is not a general bypass: the runner computes a fresh baseline
report, requires the affected XML block to be byte-identical, and requires all
geometric clearance fields to match exactly (only list indices may change).
Physical clearance must remain positive. New or worsened warnings, edited
sections, overlaps, and the normal fitting/closure gates are still rejected.
The accepted condition and its original-block hash are recorded in the manifest
and the track's `accepted-clearance.json`, alongside the baseline report.

Each file replacement is atomic. A deployment journal supports rollback of a
partial bundle and recovery after an interruption. A caught deployment failure
restores the original affected files; an interrupted deployment is recovered
on resume before that track is processed. A completed bundle is recognized by
its hashes if the interruption occurred before the manifest update.

After a batch, inspect its consolidated report and perform representative
in-game spot checks. Only the exception list needs track-by-track investigation.

## Completed September 25, 2026 collection

The initial inventory found 57 affected tracks / 645 oversized sections among
114 live track XMLs. All 57 tracks were repaired and deployed: the three initial
reference tracks, three stabilization tracks, and 51 tracks in
`runtime/radius-batches/remaining-20260925/manifest.json` (ID `1fa952a09cda`).
The final read-only `completed-audit.json` in that batch directory reports
114 scanned, zero affected tracks/segments, and no errors.

The final eight exercised implicit-flat profiles and pit-aware splitting.
Harbor Thunder and Dunevoort passed using a 2000 m SCS radius; the shorter padded
two-arc fallback also supports Harbor Thunder's near-straight loaded pose.
All original geometry acceptance limits remained in effect. Every deployed
track has its backup/reports and passed the live closure check. The previously
reviewed, unchanged Los Arcos clearance condition remains recorded explicitly.
