# /***************************************************************************
#     file                 : repair_track_radii.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""Stage a local radius-repair candidate using a matching Windows development loader."""

import argparse
import hashlib
import json
import math
import zipfile
from pathlib import Path
from xml.parsers.expat import ExpatError

from torcs_track_tools.core.artifact_io import file_sha256, read_json, write_json
from torcs_track_tools.core.defaults import DEFAULT_RADIUS_FIT_SEED, DEFAULT_REPAIR_CURVE_RADIUS_M
from torcs_track_tools.core.geometry import MAX_TORCS_RADIUS_M
from torcs_track_tools.core.radius_audit import audit_track
from torcs_track_tools.core.radius_repair import fit, selected_sections, validate
from torcs_track_tools.core.track_loader_probe import TrackLoaderProbe


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Current authoritative track XML")
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--resource-dir", type=Path, help="Original track directory for resolving entities in a relocated/saved XML")
    parser.add_argument("--symbols-dir", type=Path, help="Matching private track PDB directory (defaults to src/modules/track/Release)")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--segment", action="append", help="Select explicitly; repeat for multiple curves")
    selection.add_argument("--all-over-limit", action="store_true", help=f"Select every curve above {MAX_TORCS_RADIUS_M:g} m using the radius audit")
    parser.add_argument("--work-dir", type=Path, required=True, help="New directory outside the source track tree")
    reuse = parser.add_mutually_exclusive_group()
    reuse.add_argument("--validate-candidate", type=Path, help="Validate a previously fitted XML instead of fitting")
    reuse.add_argument("--resume-report", type=Path, help="Reuse a matching fit report/checkpoint in a new work directory")
    parser.add_argument("--seed", type=int, default=DEFAULT_RADIUS_FIT_SEED)
    parser.add_argument("--polish-closure", action="store_true", help="Polish final quantized heading using only selected repair sections")
    parser.add_argument("--method", choices=("biarc", "scs", "sbbs", "auto"), default="biarc",
                        help="biarc: two arcs; scs: straight–curve–straight; sbbs: padded arcs; auto: choose from loaded pose")
    parser.add_argument("--curve-radius", type=float, default=DEFAULT_REPAIR_CURVE_RADIUS_M,
                        help=f"Curve radius in metres for scs, in (0, {MAX_TORCS_RADIUS_M:g}]")
    return parser


def snapshot_input(source, work, names, method="biarc", curve_radius=DEFAULT_REPAIR_CURVE_RADIUS_M):
    if work.is_relative_to(source.parent):
        raise ValueError("Work directory must be outside the source track tree")
    if work.exists():
        raise ValueError("Work directory must be new; previous candidates/backups are never overwritten")
    original = source.read_bytes()
    sections = selected_sections(original.decode("utf-8"), names, method, curve_radius)
    work.mkdir(parents=True)
    (work / "before.xml").write_bytes(original)
    with zipfile.ZipFile(work / "before.zip", "w", zipfile.ZIP_DEFLATED) as backup:
        for path in sorted(source.parent.rglob("*")):
            if path.is_file():
                backup.write(path, path.relative_to(source.parent))
    return original, sections


def write_result(work, candidate, report):
    name = "candidate.xml" if report["accepted"] else "candidate-rejected.xml"
    data = candidate.encode("utf-8")
    report["candidate_sha256"] = hashlib.sha256(data).hexdigest()
    (work / name).write_bytes(data)
    write_json(work/"report.json", report)
    print(json.dumps(report, indent=2))
    print(f"Staged {work / name}; source track and live assets were not modified.")
    return int(not report["accepted"])


def run(args):
    probe = None
    try:
        source, work, runtime = args.input.resolve(), args.work_dir.resolve(), args.runtime_dir.resolve()
        names = args.segment if args.segment else [s["name"] for s in audit_track(source)["segments"]]
        original, sections = snapshot_input(source, work, names, args.method, args.curve_radius)
        identity = report_identity(args, source, runtime, original)
        resume = load_resume(args.resume_report, identity, names)
        text = original.decode("utf-8")
        symbols = args.symbols_dir.resolve() if args.symbols_dir else runtime.parent / "src/modules/track/Release"
        resources = args.resource_dir.resolve() if args.resource_dir else None
        probe = TrackLoaderProbe(runtime, symbols, source, work / "trial.xml", resources)
        if args.validate_candidate:
            candidate = args.validate_candidate.read_bytes().decode("utf-8")
            baseline, parameters = probe.load(text), None
        else:
            def progress(parameters, selected):
                checkpoint = {**identity, "segments": names, "parameters": parameters,
                              "methods": {name: selected[name]["method"] for name in parameters}}
                write_json(work/"fit-progress.json", checkpoint)
            candidate, parameters, baseline = fit(text, sections, probe, args.seed, resume, progress, args.polish_closure)
        report = validate(text, candidate, sections, baseline, probe.load(candidate))
        report.update({**identity, "segments": names, "parameters": parameters,
                       "sampling": {name: {key: meta[key] for key in ("cells", "curve_steps") if key in meta} for name, meta in sections.items()},
                       "methods": {name: meta["method"] for name, meta in sections.items()}})
        if source.read_bytes() != original:
            report["accepted"] = False
            report["failures"].append("Source changed during the run")
        return write_result(work, candidate, report)
    finally:
        if probe:
            probe.close()


def report_identity(args, source, runtime, original):
    return {"source": str(source), "source_sha256": hashlib.sha256(original).hexdigest(),
            "track_dll_sha256": file_sha256(runtime/"modules/track/track.dll"),
            "seed": args.seed, "method": args.method,
            "polish_closure": args.polish_closure,
            "curve_radius_m": args.curve_radius if args.method in ("scs", "auto") else None}


def load_resume(path, identity, names):
    if path is None:
        return None
    report = read_json(path)
    for key in ("source_sha256", "track_dll_sha256", "method", "curve_radius_m", "seed"):
        if report.get(key) != identity[key]:
            raise ValueError(f"Resume report does not match {key}")
    selected = report.get("segments", list(report.get("methods", {})))
    if selected != names:
        raise ValueError("Resume report has a different segment selection/order")
    validate_resume_parameters(report, names)
    report["parameters"] = {name: [float(v) for v in values] for name, values in report["parameters"].items()}
    return report


def validate_resume_parameters(report, names):
    parameters = report.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("Resume report has no fitted parameters")
    for name, values in parameters.items():
        if name not in names or report.get("methods", {}).get(name) not in ("biarc", "scs", "sbbs"):
            raise ValueError("Resume report contains an unsupported segment/method")
        if not valid_parameter_vector(values):
            raise ValueError("Resume report contains invalid parameters")


def valid_parameter_vector(values):
    if not isinstance(values, list) or len(values) != 3:
        return False
    try:
        return all(math.isfinite(float(v)) for v in values)
    except (ValueError, TypeError):
        return False


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, OSError, RuntimeError, KeyError, ImportError, SyntaxError, ExpatError) as error:
        parser.exit(1, f"Radius repair failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
