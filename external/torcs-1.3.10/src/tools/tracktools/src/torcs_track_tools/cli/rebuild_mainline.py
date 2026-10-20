#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : rebuild_mainline.py
#     created              : 20 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Build a playable no-pit TORCS track layout from cached source geometry.

This is the high-level orchestrator used by the normal authoring workflow.  It
keeps source discovery, segment fitting, XML assembly, closure, and optional
post-processing as separate stages so each intermediate artifact can be inspected
and reused.

Pipeline:
1) Prepare the cached source centerline, optionally reversing race direction and
   repairing a noisy loop seam for the fitter.
2) Fit TORCS ``str``/``lft``/``rgt`` segments with the DP-biarc drafter by
   default.  The older sequential polyline fitter remains an explicit fallback.
3) Apply each candidate start rotation to the track XML/template while preserving
   metadata, surfaces, and graphics setup.
4) Run ``trackgen -z`` through the selected closure solver and keep only a
   candidate whose report satisfies the closure gates.
5) Run side-clearance cleanup on the closed mainline so tight-turn side offsets
   do not cross the turn center.
6) Run side-overlap cleanup so distant side envelopes do not overlap across
   narrow infield gaps.
7) If ``--place-curbs`` is set, run ``place_curbs`` on the staged XML.  If the
   outside pass split any segments, re-close that curbed XML with the geometric
   closer and write a separate curbed closure report.
8) Promote the staged XML to the live track only after every requested stage has
   succeeded; failed closure, side-clearance, or curb post-processing leaves the
   existing live XML untouched.

Profiles are preferred over low-level knobs.  OSM/GPS sources usually use the
standard profile; raster/drawing sources use ``drawing`` or ``drawing-detail``
to preserve visual intent without exposing the fitter internals to routine use.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable

from torcs_track_tools.core.defaults import (
    DEFAULT_LICENSE,
    DEFAULT_TARGET_ANG_DEG,
    DEFAULT_TARGET_DX_M,
    DEFAULT_TARGET_DY_M,
    DEFAULT_TARGET_DZ_M,
    PLACEHOLDER_AUTHORS,
)

DEFAULT_MAX_BASELINE_ANG = 10.0
DEFAULT_EXPAND_CANDIDATES_OBJECTIVE = 28.0
DP_EXPAND_CANDIDATES_OBJECTIVE = 0.12
SEGMENT_FITTER_DP_BIARC = "dp-biarc"
SEGMENT_FITTER_POLYLINE = "polyline"
CLOSURE_SOLVER_LEGACY = "legacy"
CLOSURE_SOLVER_GEOMETRIC = "geometric"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild TORCS mainline from cached centerline")
    parser.add_argument(
        "--profile",
        choices=["standard", "drawing", "drawing-detail"],
        default="standard",
        help="Fit preset; drawing-detail preserves small raster-map kinks/chicanes",
    )
    parser.add_argument("--input", required=True, help="Input centerline cache JSON")
    parser.add_argument(
        "--segment-fitter",
        choices=[SEGMENT_FITTER_DP_BIARC, SEGMENT_FITTER_POLYLINE],
        default=SEGMENT_FITTER_DP_BIARC,
        help="Segment fitting backend; polyline is the legacy fallback",
    )
    parser.add_argument("--template-xml", default="", help="Template/full track XML path (defaults to bundled generic road-track template)")
    parser.add_argument("--output-track-xml", required=True, help="Output track XML path (can be same as template)")
    parser.add_argument("--runtime-dir", default="", help="TORCS runtime directory (auto-detect from output track path if omitted)")
    parser.add_argument("--category", default="", help="Track category for trackgen/closure")
    parser.add_argument("--name", default="", help="Track short name for trackgen/closure")
    parser.add_argument("--track-name", default="", help="Optional Header/name override during apply")
    parser.add_argument(
        "--segment-name-prefix",
        default="",
        help="Optional prefix for generic output segment names; omit to preserve source-derived names",
    )
    parser.add_argument("--author", default="", help="Required real track author for generated track XML")
    parser.add_argument("--license", default=DEFAULT_LICENSE, help="Track license statement; defaults to GPL version 2 or later")
    parser.add_argument("--description", default="", help="Optional Header/description override during apply")
    parser.add_argument("--segments-json", default="", help="Override output path for fitted segments JSON")
    parser.add_argument("--segments-xml", default="", help="Override output path for fitted segments XML")
    parser.add_argument("--fit-svg", default="", help="Optional fit overlay SVG path from the selected segment fitter")
    parser.add_argument(
        "--closure-solver",
        choices=[CLOSURE_SOLVER_LEGACY, CLOSURE_SOLVER_GEOMETRIC],
        default=CLOSURE_SOLVER_LEGACY,
        help="Closure backend; geometric uses the terminal-lever closer",
    )
    parser.add_argument("--closure-config", default="", help="Override output path for closure config JSON")
    parser.add_argument("--closure-report", default="", help="Override output path for closure report JSON")
    parser.add_argument("--comparison-svg", default="", help="Optional final source-vs-closed XML overlay SVG path for geometric closure")
    parser.add_argument("--comparison-report", default="", help="Optional final source-vs-closed XML comparison JSON path for geometric closure")
    parser.add_argument("--resample-step", type=float, default=4.0, help=argparse.SUPPRESS)
    parser.add_argument("--straight-heading-deg", type=float, default=2.0, help=argparse.SUPPRESS)
    parser.add_argument("--min-seg-len", type=float, default=12.0, help="Optional segment-minimum override; prefer profiles for normal workflows")
    parser.add_argument("--max-seg-len", type=float, default=180.0, help=argparse.SUPPRESS)
    parser.add_argument("--max-dev", type=float, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--length-round", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--arc-round", type=float, default=0.1, help=argparse.SUPPRESS)
    parser.add_argument("--fit-pos-threshold", type=float, default=3.0, help=argparse.SUPPRESS)
    parser.add_argument("--fit-head-threshold", type=float, default=1.5, help=argparse.SUPPRESS)
    parser.add_argument("--beam-width", type=int, default=6, help=argparse.SUPPRESS)
    parser.add_argument("--span-stride", type=int, default=2, help=argparse.SUPPRESS)
    parser.add_argument("--global-sample-count", type=int, default=120, help=argparse.SUPPRESS)
    parser.add_argument("--max-beam-iters", type=int, default=1200, help=argparse.SUPPRESS)
    parser.add_argument("--drift-rmse-growth", type=float, default=0.8, help=argparse.SUPPRESS)
    parser.add_argument("--drift-maxdev-growth", type=float, default=2.0, help=argparse.SUPPRESS)
    parser.add_argument("--reject-pos-mult", type=float, default=3.0, help=argparse.SUPPRESS)
    parser.add_argument("--reject-head-mult", type=float, default=3.0, help=argparse.SUPPRESS)
    parser.add_argument("--cleanup-small-wiggles", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--corner-fit", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--corner-tolerance", type=float, default=4.0, help=argparse.SUPPRESS)
    parser.add_argument("--corner-trim-max", type=float, default=14.0, help=argparse.SUPPRESS)
    parser.add_argument("--min-coverage", type=float, default=0.98, help=argparse.SUPPRESS)
    parser.add_argument("--max-adaptive-attempts", type=int, default=6, help=argparse.SUPPRESS)
    parser.add_argument("--initial-start-candidates", type=int, default=2, help=argparse.SUPPRESS)
    parser.add_argument("--max-start-candidates", type=int, default=8, help=argparse.SUPPRESS)
    parser.add_argument("--exhaustive-candidates", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--expand-candidates-objective",
        type=float,
        default=DEFAULT_EXPAND_CANDIDATES_OBJECTIVE,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--timing-report", default="", help="Optional timing/counter report path")
    parser.add_argument("--no-fit-cache", action="store_true", help="Disable per-fit-family segment cache reuse")
    parser.add_argument("--reverse-input", action="store_true", help="Build reversed race direction from source order")
    parser.add_argument(
        "--no-adjust-side-clearance",
        dest="adjust_side_clearance",
        action="store_false",
        default=True,
        help="Skip automatic tight-turn inner side-width post-processing",
    )
    parser.add_argument("--side-clearance-margin", type=float, default=0.5, help=argparse.SUPPRESS)
    parser.add_argument("--side-clearance-taper-length", type=float, default=35.0, help=argparse.SUPPRESS)
    parser.add_argument("--side-clearance-min-side-width", type=float, default=0.5, help=argparse.SUPPRESS)
    parser.add_argument(
        "--no-adjust-side-overlap",
        dest="adjust_side_overlap",
        action="store_false",
        default=True,
        help="Skip automatic distant side-overlap post-processing",
    )
    parser.add_argument("--side-overlap-target-gap", type=float, default=2.0, help=argparse.SUPPRESS)
    parser.add_argument("--side-overlap-sample-step", type=float, default=2.0, help=argparse.SUPPRESS)
    parser.add_argument("--side-overlap-min-progress-separation", type=float, default=60.0, help=argparse.SUPPRESS)
    parser.add_argument("--side-overlap-taper-length", type=float, default=45.0, help=argparse.SUPPRESS)
    parser.add_argument("--side-overlap-min-side-width", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument(
        "--place-curbs",
        action="store_true",
        help="After mainline closure and side-clearance cleanup, place safe curbs and re-close if outside splitting changed geometry",
    )
    parser.add_argument(
        "--curb-placement",
        choices=["inside", "outside", "both"],
        default="both",
        help="Curb placement pass used with --place-curbs; both is the normal visual-check mode",
    )
    parser.add_argument("--curb-report", default="", help="Override output path for the curb placement report JSON")
    parser.add_argument("--curb-closure-report", default="", help="Override output path for post-curb geometric closure report JSON")
    parser.add_argument("--allow-partial", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose-progress", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--straight-step", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--arc-step", type=float, default=0.1, help=argparse.SUPPRESS)
    parser.add_argument("--min-straight-step", type=float, default=1e-5, help=argparse.SUPPRESS)
    parser.add_argument("--min-arc-step", type=float, default=1e-6, help=argparse.SUPPRESS)
    parser.add_argument("--target-dx", type=float, default=DEFAULT_TARGET_DX_M, help=argparse.SUPPRESS)
    parser.add_argument("--target-dy", type=float, default=DEFAULT_TARGET_DY_M, help="Handoff threshold for |Delta Y|; default matches trackgen's sub-millimeter quantum")
    parser.add_argument("--target-dz", type=float, default=DEFAULT_TARGET_DZ_M, help=argparse.SUPPRESS)
    parser.add_argument("--target-ang", type=float, default=DEFAULT_TARGET_ANG_DEG, help=argparse.SUPPRESS)
    parser.add_argument(
        "--max-baseline-ang",
        type=float,
        default=DEFAULT_MAX_BASELINE_ANG,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--max-closure-iters", type=int, default=18, help=argparse.SUPPRESS)
    parser.add_argument("--closure-timeout", type=float, default=360.0, help=argparse.SUPPRESS)
    parser.add_argument("--plateau-iters", type=int, default=18, help=argparse.SUPPRESS)
    parser.add_argument("--phase-iters", type=int, default=12, help=argparse.SUPPRESS)
    parser.add_argument("--linear-polish", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them")
    args = parser.parse_args()
    apply_fitter_defaults(args)
    apply_profile_defaults(args)
    validate_args(args)
    return args


def cli_arg_present(name: str) -> bool:
    return any(arg == name or arg.startswith(name + "=") for arg in sys.argv[1:])


def apply_fitter_defaults(args: argparse.Namespace) -> None:
    if args.segment_fitter == SEGMENT_FITTER_DP_BIARC:
        if not cli_arg_present("--linear-polish"):
            args.linear_polish = True
        if not cli_arg_present("--expand-candidates-objective"):
            args.expand_candidates_objective = DP_EXPAND_CANDIDATES_OBJECTIVE
        return
    if args.segment_fitter != SEGMENT_FITTER_POLYLINE:
        return
    legacy_defaults = {
        "--resample-step": ("resample_step", 3.0),
        "--min-seg-len": ("min_seg_len", 10.0),
        "--max-seg-len": ("max_seg_len", 220.0),
    }
    for flag, (attr, value) in legacy_defaults.items():
        if not cli_arg_present(flag):
            setattr(args, attr, value)


def apply_profile_defaults(args: argparse.Namespace) -> None:
    if args.profile not in ("drawing", "drawing-detail"):
        return
    if args.segment_fitter == SEGMENT_FITTER_DP_BIARC:
        drawing_defaults = {
            "--resample-step": ("resample_step", 4.0),
            "--min-seg-len": ("min_seg_len", 10.0 if args.profile == "drawing-detail" else 12.0),
            "--max-seg-len": ("max_seg_len", 180.0),
        }
        for flag, (attr, value) in drawing_defaults.items():
            if not cli_arg_present(flag):
                setattr(args, attr, value)
        return
    drawing_defaults = {
        "--resample-step": ("resample_step", 5.0),
        "--straight-heading-deg": ("straight_heading_deg", 5.0),
        "--min-seg-len": ("min_seg_len", 12.0 if args.profile == "drawing-detail" else 20.0),
        "--max-seg-len": ("max_seg_len", 220.0),
        "--fit-pos-threshold": ("fit_pos_threshold", 6.0),
        "--fit-head-threshold": ("fit_head_threshold", 3.0),
        "--beam-width": ("beam_width", 10),
        "--span-stride": ("span_stride", 1),
        "--max-beam-iters": ("max_beam_iters", 2600),
        "--drift-rmse-growth": ("drift_rmse_growth", 2.0),
        "--drift-maxdev-growth": ("drift_maxdev_growth", 5.0),
        "--reject-pos-mult": ("reject_pos_mult", 6.0),
        "--reject-head-mult": ("reject_head_mult", 6.0),
        "--target-dy": ("target_dy", 0.002),
    }
    for flag, (attr, value) in drawing_defaults.items():
        if not cli_arg_present(flag):
            setattr(args, attr, value)
    if not cli_arg_present("--cleanup-small-wiggles"):
        args.cleanup_small_wiggles = True


def validate_args(args: argparse.Namespace) -> None:
    if args.segment_fitter == SEGMENT_FITTER_DP_BIARC and args.corner_fit:
        raise SystemExit("--corner-fit is only supported with --segment-fitter polyline")


def validate_author(author: str) -> str:
    clean = author.strip()
    if clean.lower() in PLACEHOLDER_AUTHORS:
        raise SystemExit("A real track author is required; placeholder authors such as OpenCode are not allowed")
    return clean


def default_description(track_name: str) -> str:
    clean = track_name.strip()
    if clean:
        return f"{clean} track layout generated for TORCS."
    return "Track layout generated for TORCS."


def write_track_readme(
    track_dir: pathlib.Path,
    track_name: str,
    category: str,
    author: str,
    license_text: str,
    description: str,
    commands: list[str],
) -> pathlib.Path:
    year = datetime.date.today().year
    readme = track_dir / "readme.txt"
    shipped_commands = commands[:1]
    command_lines = "\n".join(f"  {cmd}" for cmd in shipped_commands) if shipped_commands else "  No command history captured."
    detail_note = "Detailed local intermediate command history is kept in source/rebuild-mainline-timing.json."
    text = (
        f"{track_name}\n"
        "\n"
        f"Category: {category}\n"
        f"Description: {description}\n"
        "\n"
        f"Copyright (C) {year} by {author}\n"
        f"License: {license_text}\n"
        "\n"
        "Generation commands:\n"
        f"{command_lines}\n"
        f"{detail_note}\n"
        "\n"
        "Third-party assets:\n"
        "  None documented at generation time. If additional textures, models, sounds, "
        "or other third-party assets are added later, document their author, license, "
        "and redistribution terms here.\n"
    )
    readme.write_text(text, encoding="utf-8")
    return readme


def update_promoted_xml_header_file_name(track_xml: pathlib.Path) -> None:
    text = track_xml.read_text(encoding="utf-8")
    updated = re.sub(
        r"(\n\s*file\s+:\s*)[^\n]+",
        lambda match: f"{match.group(1)}{track_xml.name}",
        text,
        count=1,
    )
    if updated != text:
        track_xml.write_text(updated, encoding="utf-8")


def derive_runtime_context(xml_path: pathlib.Path) -> tuple[pathlib.Path, str, str]:
    parts = list(xml_path.parts)
    parts_l = [p.lower() for p in parts]
    if "tracks" not in parts_l:
        raise RuntimeError("Could not auto-detect runtime/category/name from output track path")
    i = parts_l.index("tracks")
    if i + 3 >= len(parts):
        raise RuntimeError("Track path must be .../tracks/<category>/<name>/<name>.xml")
    return pathlib.Path(*parts[:i]), parts[i + 1], parts[i + 2]


def starts_with_runtime(path: pathlib.Path) -> bool:
    return not path.is_absolute() and bool(path.parts) and path.parts[0].lower() == "runtime"


def has_nested_runtime(path: pathlib.Path) -> bool:
    parts_l = [p.lower() for p in path.parts]
    return any(a == "runtime" and b == "runtime" for a, b in zip(parts_l, parts_l[1:], strict=False))


def validate_path_style(input_path: pathlib.Path, output_path: pathlib.Path, runtime_dir: pathlib.Path) -> None:
    cwd = pathlib.Path.cwd()
    if cwd.name.lower() == "runtime" and (starts_with_runtime(input_path) or starts_with_runtime(output_path)):
        raise SystemExit(
            "Path style mismatch: current directory is the TORCS runtime directory, "
            "but --input or --output-track-xml starts with 'runtime/'. "
            "Use tracks/<category>/<name>/... from runtime/, or run from the repository root."
        )

    resolved_paths = []
    for path in (input_path, output_path, runtime_dir):
        resolved_paths.append(path if path.is_absolute() else cwd / path)
    for path in resolved_paths:
        if has_nested_runtime(path):
            raise SystemExit(
                f"Refusing nested runtime path: {path}. "
                "Use runtime/tracks/... from the repository root or tracks/... from runtime/."
            )


def run_or_print(cmd: list[str], dry_run: bool) -> None:
    print("COMMAND:", subprocess.list2cmdline(cmd))
    if dry_run:
        return
    subprocess.run(cmd, check=True)


def print_stage_status(stage: str, status: str) -> None:
    print(f"STATUS {stage}: {status}")


def bundled_template_path(script_dir: pathlib.Path) -> pathlib.Path:
    return script_dir.parent / "templates" / "road-track-template.xml"


def tool_script(script_dir: pathlib.Path, name: str) -> pathlib.Path:
    return script_dir / name


def find_att(section: ET.Element, tag: str, name: str) -> ET.Element | None:
    for child in section:
        if child.tag == tag and child.get("name") == name:
            return child
    return None


def get_attnum(section: ET.Element, name: str, default: float = 0.0) -> float:
    att = find_att(section, "attnum", name)
    if att is None:
        return default
    try:
        return float(att.get("val", str(default)))
    except ValueError:
        return default


def get_seg_type(section: ET.Element) -> str:
    att = find_att(section, "attstr", "type")
    return att.get("val", "") if att is not None else ""


def norm_angle(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def simulate_segment_end(x: float, y: float, h: float, seg: ET.Element) -> tuple[float, float, float]:
    seg_type = get_seg_type(seg)
    if seg_type == "str":
        lg = get_attnum(seg, "lg", 0.0)
        return x + lg * math.cos(h), y + lg * math.sin(h), h
    if seg_type in ("lft", "rgt"):
        radius = max(1e-6, abs(get_attnum(seg, "radius", 0.0)))
        arc = math.radians(get_attnum(seg, "arc", 0.0))
        sign = 1.0 if seg_type == "lft" else -1.0
        cx = x - sign * radius * math.sin(h)
        cy = y + sign * radius * math.cos(h)
        h2 = h + sign * arc
        x2 = cx + sign * radius * math.sin(h2)
        y2 = cy - sign * radius * math.cos(h2)
        return x2, y2, h2
    return x, y, h


def end_pose_error(segs: list[ET.Element]) -> tuple[float, float]:
    x = y = h = 0.0
    for seg in segs:
        x, y, h = simulate_segment_end(x, y, h, seg)
    return math.hypot(x, y), abs(math.degrees(norm_angle(h)))


def parse_segments_snippet(snippet_path: pathlib.Path) -> list[ET.Element]:
    raw = snippet_path.read_text(encoding="utf-8").strip()
    root = ET.fromstring(f"<wrapper>\n{raw}\n</wrapper>")
    return [child for child in root if child.tag == "section"]


def serialize_segments_snippet(segs: list[ET.Element]) -> str:
    lines: list[str] = []
    for seg in segs:
        text = ET.tostring(seg, encoding="unicode")
        lines.append("\t\t\t" + text.replace("\n", "\n\t\t\t"))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def reverse_segment_direction(seg: ET.Element) -> ET.Element:
    out = ET.fromstring(ET.tostring(seg, encoding="unicode"))
    type_att = find_att(out, "attstr", "type")
    if type_att is not None:
        if type_att.get("val") == "lft":
            type_att.set("val", "rgt")
        elif type_att.get("val") == "rgt":
            type_att.set("val", "lft")
    radius_att = find_att(out, "attnum", "radius")
    end_radius_att = find_att(out, "attnum", "end radius")
    if radius_att is not None and end_radius_att is not None:
        radius_val = radius_att.get("val", "")
        radius_att.set("val", end_radius_att.get("val", ""))
        end_radius_att.set("val", radius_val)
    return out


def reverse_segments_xml(input_xml: pathlib.Path, output_xml: pathlib.Path) -> None:
    segs = parse_segments_snippet(input_xml)
    reversed_segs = [reverse_segment_direction(seg) for seg in reversed(segs)]
    output_xml.write_text(serialize_segments_snippet(reversed_segs), encoding="utf-8")


def reverse_segments_json(input_json: pathlib.Path, output_json: pathlib.Path) -> None:
    obj = json.loads(input_json.read_text(encoding="utf-8"))
    segments = obj.get("segments") if isinstance(obj, dict) else obj
    if not isinstance(segments, list):
        shutil.copyfile(input_json, output_json)
        return
    out: list[dict] = []
    for item in reversed(segments):
        seg = dict(item)
        if seg.get("type") == "lft":
            seg["type"] = "rgt"
        elif seg.get("type") == "rgt":
            seg["type"] = "lft"
        if "radius" in seg and "end_radius" in seg:
            seg["radius"], seg["end_radius"] = seg["end_radius"], seg["radius"]
        if "source_i0" in seg and "source_i1" in seg:
            seg["source_i0"], seg["source_i1"] = seg["source_i1"], seg["source_i0"]
        out.append(seg)
    if isinstance(obj, dict):
        obj = dict(obj)
        obj["segments"] = out
        obj["reversed_by_tracktools"] = True
        output_json.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    else:
        output_json.write_text(json.dumps(out, indent=2), encoding="utf-8")


def start_candidate_names(segments_xml: pathlib.Path, max_candidates: int = 8) -> list[str]:
    segs = parse_segments_snippet(segments_xml)
    scored: list[tuple[float, str]] = []
    n = len(segs)
    for i, seg in enumerate(segs):
        if get_seg_type(seg) != "str":
            continue
        name = seg.get("name", "")
        if not name or name.startswith("Closure Helper"):
            continue
        lg = get_attnum(seg, "lg", 0.0)
        if lg < 20.0:
            continue
        rotated = segs[i:] + segs[:i]
        pos_err, head_err_deg = end_pose_error(rotated)
        prev_arc = abs(get_attnum(segs[(i - 1) % n], "arc", 0.0))
        next_arc = abs(get_attnum(segs[(i + 1) % n], "arc", 0.0))
        keep_start_bonus = -0.5 if i == 0 else 0.0
        score = 8.0 * head_err_deg + pos_err + 0.5 * (prev_arc + next_arc) - 0.01 * min(lg, 300.0) + keep_start_bonus
        scored.append((score, name))
    scored.sort(key=lambda item: item[0])
    names: list[str] = []
    for _, name in scored:
        if name not in names:
            names.append(name)
        if len(names) >= max_candidates:
            break
    return names


def baseline_objective(metrics: dict) -> float:
    return abs(metrics["delta_x"]) + abs(metrics["delta_y"]) + 10.0 * abs(metrics["delta_ang_deg"])


def baseline_limit_args(max_baseline_ang: float) -> list[str]:
    return ["--max-baseline-ang", str(max_baseline_ang)]


def default_track_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.replace("_", "-").split("-") if part)


def candidate_validation_batches(candidates: list[str], initial_count: int, exhaustive: bool) -> list[list[str]]:
    if exhaustive:
        return [candidates] if candidates else []
    first_count = max(1, min(initial_count, len(candidates)))
    batches = [candidates[:first_count]]
    if first_count < len(candidates):
        batches.append(candidates[first_count:])
    return batches


def should_expand_before_closure(ready: list[dict], batch_index: int, batch_count: int, objective_threshold: float) -> bool:
    if objective_threshold <= 0.0 or batch_index >= batch_count or not ready:
        return False
    best_objective = min(result["objective"] for result in ready)
    return best_objective > objective_threshold


def choose_fit_input_from_seam_report(original_input: str, prepared_input: pathlib.Path, report_path: pathlib.Path) -> str:
    if not report_path.exists():
        return str(prepared_input)
    obj = json.loads(report_path.read_text(encoding="utf-8"))
    if not bool(obj.get("repair_applied", False)):
        return original_input
    return str(prepared_input)


def build_fit_input_candidates(
    args: argparse.Namespace,
    prep_source_input: pathlib.Path,
    prepared_input: pathlib.Path,
    seam_report: pathlib.Path,
) -> list[tuple[str, str, bool]]:
    fit_inputs: list[tuple[str, str, bool]] = []
    stable_fit_input = choose_fit_input_from_seam_report(str(prep_source_input), prepared_input, seam_report)
    fit_inputs.append(("stable", stable_fit_input, False))
    prepared_str = str(prepared_input)
    if pathlib.Path(stable_fit_input).resolve() != prepared_input.resolve() and prepared_input.exists():
        if args.segment_fitter == SEGMENT_FITTER_POLYLINE:
            # Prepared-tail has been the successful fallback for noisy repaired
            # seams in the legacy fitter; try it before the one-sided variants.
            fit_inputs.append(("prepared-tail", prepared_str, True))
        fit_inputs.append(("prepared", prepared_str, False))
    if args.segment_fitter == SEGMENT_FITTER_POLYLINE:
        fit_inputs.append(("tail", stable_fit_input, True))
    return fit_inputs


def file_sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fit_cache_key(args: argparse.Namespace, fit_input: pathlib.Path, preserve_tail: bool) -> dict:
    return {
        "schema": 2,
        "segment_fitter": args.segment_fitter,
        "input": str(fit_input.resolve()),
        "input_sha256": file_sha256(fit_input),
        "preserve_tail": preserve_tail,
        "params": {
            "resample_step": args.resample_step,
            "max_dev": args.max_dev,
            "straight_heading_deg": args.straight_heading_deg,
            "min_seg_len": args.min_seg_len,
            "max_seg_len": args.max_seg_len,
            "length_round": args.length_round,
            "arc_round": args.arc_round,
            "fit_pos_threshold": args.fit_pos_threshold,
            "fit_head_threshold": args.fit_head_threshold,
            "beam_width": args.beam_width,
            "span_stride": args.span_stride,
            "global_sample_count": args.global_sample_count,
            "max_beam_iters": args.max_beam_iters,
            "drift_rmse_growth": args.drift_rmse_growth,
            "drift_maxdev_growth": args.drift_maxdev_growth,
            "reject_pos_mult": args.reject_pos_mult,
            "reject_head_mult": args.reject_head_mult,
            "min_coverage": args.min_coverage,
            "max_adaptive_attempts": args.max_adaptive_attempts,
            "allow_partial": args.allow_partial,
            "corner_fit": args.corner_fit,
            "corner_tolerance": args.corner_tolerance,
            "corner_trim_max": args.corner_trim_max,
        },
    }


def fit_cache_valid(meta_path: pathlib.Path, expected_key: dict, outputs: list[pathlib.Path]) -> bool:
    if not all(path.exists() for path in outputs):
        return False
    if not meta_path.exists():
        return False
    try:
        return json.loads(meta_path.read_text(encoding="utf-8")) == expected_key
    except (OSError, json.JSONDecodeError):
        return False


def write_rebuild_timing(timing: dict, timing_report: pathlib.Path, run_started: float, status: str) -> None:
    timing["status"] = status
    timing["elapsed_seconds"] = time.perf_counter() - run_started
    timing_report.parent.mkdir(parents=True, exist_ok=True)
    timing_report.write_text(json.dumps(timing, indent=2), encoding="utf-8")


def timed_rebuild_run(
    cmd: list[str],
    dry_run: bool,
    stage: str,
    timing: dict,
    timing_report: pathlib.Path,
    run_started: float,
    timeout_s: float | None = None,
) -> None:
    command_text = subprocess.list2cmdline(cmd)
    print("COMMAND:", command_text)
    timing["commands"].append(command_text)
    start = time.perf_counter()
    if dry_run:
        timing["stages"].append({"stage": stage, "elapsed_seconds": 0.0, "dry_run": True, "status": "planned"})
        write_rebuild_timing(timing, timing_report, run_started, "running")
        return
    timing["counters"]["python_subprocesses"] += 1
    try:
        subprocess.run(cmd, check=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        timing["stages"].append({"stage": stage, "elapsed_seconds": time.perf_counter() - start, "dry_run": False, "status": "timeout"})
        write_rebuild_timing(timing, timing_report, run_started, "running")
        raise exc
    except subprocess.CalledProcessError as exc:
        timing["stages"].append(
            {
                "stage": stage,
                "elapsed_seconds": time.perf_counter() - start,
                "dry_run": False,
                "status": "failed",
                "returncode": exc.returncode,
            }
        )
        write_rebuild_timing(timing, timing_report, run_started, "running")
        raise exc
    timing["stages"].append({"stage": stage, "elapsed_seconds": time.perf_counter() - start, "dry_run": False, "status": "ok"})
    write_rebuild_timing(timing, timing_report, run_started, "running")


def timed_rebuild_run_check_false(cmd: list[str], stage: str, timing: dict, timing_report: pathlib.Path, run_started: float) -> subprocess.CompletedProcess:
    command_text = subprocess.list2cmdline(cmd)
    print("COMMAND:", command_text)
    timing["commands"].append(command_text)
    start = time.perf_counter()
    timing["counters"]["python_subprocesses"] += 1
    proc = subprocess.run(cmd, check=False)
    timing["stages"].append(
        {
            "stage": stage,
            "elapsed_seconds": time.perf_counter() - start,
            "returncode": proc.returncode,
            "dry_run": False,
            "status": "ok" if proc.returncode == 0 else "failed",
        }
    )
    write_rebuild_timing(timing, timing_report, run_started, "running")
    return proc


def cleanup_rebuild_trackgen_lock(runtime_dir: pathlib.Path, category: str, name: str) -> None:
    lock_path = runtime_dir / f".trackgen-{category}-{name}.lock"
    try:
        lock_path.unlink()
        print(f"Removed stale trackgen lock: {lock_path}")
    except FileNotFoundError:
        pass


def append_skipped_stage(timing: dict, write_timing: Callable[[str], None], stage: str, dry_run: bool, reason: str | None = None) -> None:
    print_stage_status(stage, "skipped")
    entry = {"stage": stage, "elapsed_seconds": 0.0, "dry_run": dry_run, "status": "skipped"}
    if reason is not None:
        entry["reason"] = reason
    timing["stages"].append(entry)
    write_timing("running")


def run_rebuild_side_clearance_adjustment(
    args: argparse.Namespace,
    py: str,
    adjust_side_clearance_script: pathlib.Path,
    side_clearance_report: pathlib.Path,
    track_xml: pathlib.Path,
    dry_run: bool,
    timing: dict,
    write_timing: Callable[[str], None],
    timed_run: Callable[..., None],
) -> None:
    if not args.adjust_side_clearance:
        append_skipped_stage(timing, write_timing, "adjust-side-clearance", dry_run)
        return
    adjust_cmd = [
        py,
        str(adjust_side_clearance_script),
        "--input",
        str(track_xml),
        "--output",
        str(track_xml),
        "--clearance-margin",
        str(args.side_clearance_margin),
        "--taper-length",
        str(args.side_clearance_taper_length),
        "--min-side-width",
        str(args.side_clearance_min_side_width),
        "--report",
        str(side_clearance_report),
    ]
    timed_run(adjust_cmd, dry_run, "adjust-side-clearance")
    print_stage_status("adjust-side-clearance", "planned" if dry_run else "ok")


def run_rebuild_side_overlap_adjustment(
    args: argparse.Namespace,
    py: str,
    adjust_side_overlap_script: pathlib.Path,
    side_overlap_report: pathlib.Path,
    track_xml: pathlib.Path,
    dry_run: bool,
    timing: dict,
    write_timing: Callable[[str], None],
    timed_run: Callable[..., None],
) -> None:
    if not args.adjust_side_overlap:
        append_skipped_stage(timing, write_timing, "adjust-side-overlap", dry_run)
        return
    adjust_cmd = [
        py,
        str(adjust_side_overlap_script),
        "--input",
        str(track_xml),
        "--output",
        str(track_xml),
        "--target-gap",
        str(args.side_overlap_target_gap),
        "--sample-step",
        str(args.side_overlap_sample_step),
        "--min-progress-separation",
        str(args.side_overlap_min_progress_separation),
        "--taper-length",
        str(args.side_overlap_taper_length),
        "--min-side-width",
        str(args.side_overlap_min_side_width),
        "--report",
        str(side_overlap_report),
    ]
    timed_run(adjust_cmd, dry_run, "adjust-side-overlap")
    print_stage_status("adjust-side-overlap", "planned" if dry_run else "ok")


def build_geometric_close_cmd(
    args: argparse.Namespace,
    py: str,
    geometric_close_script: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    track_xml: pathlib.Path,
    source_polyline: str | pathlib.Path,
    report_path: pathlib.Path,
    comparison_svg_path: pathlib.Path,
    comparison_report_path: pathlib.Path,
) -> list[str]:
    return [
        py,
        str(geometric_close_script),
        "--track-xml",
        str(track_xml),
        "--runtime-dir",
        str(runtime_dir),
        "--category",
        category,
        "--name",
        name,
        "--report",
        str(report_path),
        "--source-polyline",
        str(source_polyline),
        "--comparison-svg",
        str(comparison_svg_path),
        "--comparison-report",
        str(comparison_report_path),
        "--target-dx",
        str(args.target_dx),
        "--target-dy",
        str(args.target_dy),
        "--target-dz",
        str(args.target_dz),
        "--target-ang",
        str(args.target_ang),
    ]


def run_rebuild_curb_placement(
    args: argparse.Namespace,
    py: str,
    place_curbs_script: pathlib.Path,
    curb_report: pathlib.Path,
    track_xml: pathlib.Path,
    dry_run: bool,
    timed_run: Callable[..., None],
) -> bool:
    if not args.place_curbs:
        return False

    curb_cmd = [
        py,
        str(place_curbs_script),
        "--input",
        str(track_xml),
        "--output",
        str(track_xml),
        "--placement",
        args.curb_placement,
        "--report",
        str(curb_report),
    ]
    timed_run(curb_cmd, dry_run, "place-curbs")
    print_stage_status("place-curbs", "planned" if dry_run else "ok")

    if dry_run:
        return args.curb_placement in ("outside", "both")
    if args.curb_placement == "inside":
        return False
    if not curb_report.exists():
        return True
    try:
        report_obj = json.loads(curb_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return bool(report_obj.get("outside_splits"))


def run_rebuild_curb_postprocess(
    args: argparse.Namespace,
    py: str,
    place_curbs_script: pathlib.Path,
    geometric_close_script: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    curb_report: pathlib.Path,
    curb_closure_report: pathlib.Path,
    curb_comparison_svg: pathlib.Path,
    curb_comparison_report: pathlib.Path,
    track_xml: pathlib.Path,
    source_polyline: str | pathlib.Path,
    dry_run: bool,
    timing: dict,
    write_timing: Callable[[str], None],
    timed_run: Callable[..., None],
) -> None:
    if not args.place_curbs:
        return

    needs_reclose = run_rebuild_curb_placement(args, py, place_curbs_script, curb_report, track_xml, dry_run, timed_run)
    if not needs_reclose:
        append_skipped_stage(timing, write_timing, "close-loop-curbs", dry_run, reason="no-outside-splits")
        return

    curb_close_cmd = build_geometric_close_cmd(
        args,
        py,
        geometric_close_script,
        runtime_dir,
        category,
        name,
        track_xml,
        source_polyline,
        curb_closure_report,
        curb_comparison_svg,
        curb_comparison_report,
    )
    timing["counters"]["closure_attempts"] += 1
    timed_run(curb_close_cmd, dry_run, "close-loop-curbs", timeout_s=args.closure_timeout)
    print_stage_status("close-loop-curbs", "planned" if dry_run else "ok")


def build_reverse_centerline_cmd(args: argparse.Namespace, py: str, reverse_script: pathlib.Path, reversed_input: pathlib.Path) -> list[str]:
    return [py, str(reverse_script), "--input", args.input, "--output", str(reversed_input), "--force"]


def build_prepare_loop_cmd(
    py: str,
    prep_script: pathlib.Path,
    prep_source_input: pathlib.Path,
    prepared_input: pathlib.Path,
    seam_report: pathlib.Path,
    seam_overlay: pathlib.Path,
) -> list[str]:
    return [
        py,
        str(prep_script),
        "--input",
        str(prep_source_input),
        "--output",
        str(prepared_input),
        "--report",
        str(seam_report),
        "--overlay",
        str(seam_overlay),
    ]


def build_fit_cmd(
    args: argparse.Namespace,
    py: str,
    fit_script: pathlib.Path,
    prepared_input: pathlib.Path,
    segments_json: pathlib.Path,
    segments_xml: pathlib.Path,
    fit_svg: pathlib.Path,
) -> list[str]:
    fit_cmd = [
        py,
        str(fit_script),
        "--input",
        str(prepared_input),
        "--output-json",
        str(segments_json),
        "--output-xml",
        str(segments_xml),
        "--output-svg",
        str(fit_svg),
        "--resample-step",
        str(args.resample_step),
        "--min-seg-len",
        str(args.min_seg_len),
        "--max-seg-len",
        str(args.max_seg_len),
    ]
    if args.segment_fitter == SEGMENT_FITTER_DP_BIARC:
        if args.max_dev is not None:
            fit_cmd.extend(["--max-dev", str(args.max_dev)])
        return fit_cmd

    fit_cmd.extend(
        [
            "--straight-heading-deg",
            str(args.straight_heading_deg),
            "--length-round",
            str(args.length_round),
            "--arc-round",
            str(args.arc_round),
            "--fit-pos-threshold",
            str(args.fit_pos_threshold),
            "--fit-head-threshold",
            str(args.fit_head_threshold),
            "--beam-width",
            str(args.beam_width),
            "--span-stride",
            str(args.span_stride),
            "--global-sample-count",
            str(args.global_sample_count),
            "--max-beam-iters",
            str(args.max_beam_iters),
            "--drift-rmse-growth",
            str(args.drift_rmse_growth),
            "--drift-maxdev-growth",
            str(args.drift_maxdev_growth),
            "--reject-pos-mult",
            str(args.reject_pos_mult),
            "--reject-head-mult",
            str(args.reject_head_mult),
            "--min-coverage",
            str(args.min_coverage),
            "--max-adaptive-attempts",
            str(args.max_adaptive_attempts),
        ]
    )
    if args.allow_partial:
        fit_cmd.append("--allow-partial")
    if args.verbose_progress:
        fit_cmd.append("--verbose-progress")
    if args.cleanup_small_wiggles:
        fit_cmd.append("--cleanup-small-wiggles")
    if args.corner_fit:
        fit_cmd.extend(["--corner-fit", "--corner-tolerance", str(args.corner_tolerance), "--corner-trim-max", str(args.corner_trim_max)])
    return fit_cmd


def build_apply_cmd(
    args: argparse.Namespace,
    py: str,
    apply_script: pathlib.Path,
    template_xml: pathlib.Path,
    segments_xml: pathlib.Path,
    staging_track_xml: pathlib.Path,
    name: str,
    license_text: str,
    description: str,
) -> list[str]:
    apply_cmd = [
        py,
        str(apply_script),
        "--template-xml",
        str(template_xml),
        "--segments-xml",
        str(segments_xml),
        "--output-xml",
        str(staging_track_xml),
        "--graphic-description",
        f"{name}.ac",
        "--track-name",
        args.track_name or default_track_name(name),
    ]
    if args.segment_name_prefix:
        apply_cmd.extend(["--segment-name-prefix", args.segment_name_prefix])
    if args.author:
        apply_cmd.extend(["--author", args.author])
    apply_cmd.extend(["--license", license_text])
    if args.category:
        apply_cmd.extend(["--category", args.category])
    apply_cmd.extend(["--description", description])
    return apply_cmd


def build_select_controls_cmd(
    py: str,
    close_script: pathlib.Path,
    staging_track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    closure_config: pathlib.Path,
) -> list[str]:
    return [
        py,
        str(close_script),
        "--track-xml",
        str(staging_track_xml),
        "--runtime-dir",
        str(runtime_dir),
        "--category",
        category,
        "--name",
        name,
        "--config",
        str(closure_config),
        "--select-only",
    ]


def build_legacy_close_cmd(
    args: argparse.Namespace,
    py: str,
    close_script: pathlib.Path,
    staging_track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    closure_config: pathlib.Path,
    closure_report: pathlib.Path,
) -> list[str]:
    close_cmd = [
        py,
        str(close_script),
        "--track-xml",
        str(staging_track_xml),
        "--runtime-dir",
        str(runtime_dir),
        "--category",
        category,
        "--name",
        name,
        "--config",
        str(closure_config),
        "--report",
        str(closure_report),
        "--straight-step",
        str(args.straight_step),
        "--arc-step",
        str(args.arc_step),
        "--min-straight-step",
        str(args.min_straight_step),
        "--min-arc-step",
        str(args.min_arc_step),
        "--target-dx",
        str(args.target_dx),
        "--target-dy",
        str(args.target_dy),
        "--target-dz",
        str(args.target_dz),
        "--target-ang",
        str(args.target_ang),
        "--max-iters",
        str(args.max_closure_iters),
        "--plateau-iters",
        str(args.plateau_iters),
        "--phase-iters",
        str(args.phase_iters),
        *baseline_limit_args(args.max_baseline_ang),
    ]
    if args.linear_polish:
        close_cmd.append("--linear-polish")
    return close_cmd


def evaluate_candidate_baseline(
    args: argparse.Namespace,
    py: str,
    close_script: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    closure_config: pathlib.Path,
    closure_report: pathlib.Path,
    fit_label: str,
    fit_input: str,
    idx: int,
    start_name: str,
    candidate_xml: pathlib.Path,
    candidate_report: pathlib.Path,
    timing: dict,
    run_check_false: Callable[[list[str], str], subprocess.CompletedProcess],
) -> tuple[dict | None, bool]:
    if args.closure_solver == CLOSURE_SOLVER_GEOMETRIC:
        result = {
            "fit_label": fit_label,
            "fit_input": fit_input,
            "index": idx,
            "start": start_name,
            "xml": str(candidate_xml),
            "report": str(closure_report),
            "baseline_ready": True,
            "returncode": 0,
            "metrics": {},
            "objective": 0.0,
        }
        print(f"Candidate {fit_label}/{idx} start={start_name}: queued for geometric closure")
        return result, False

    baseline_cmd = [
        py,
        str(close_script),
        "--track-xml",
        str(candidate_xml),
        "--runtime-dir",
        str(runtime_dir),
        "--category",
        category,
        "--name",
        name,
        "--config",
        str(closure_config),
        "--report",
        str(candidate_report),
        *baseline_limit_args(args.max_baseline_ang),
        "--baseline-only",
    ]
    proc = run_check_false(baseline_cmd, f"baseline-{fit_label}-{idx}")
    timing["counters"]["baseline_checks"] += 1
    if not candidate_report.exists():
        return None, False
    report_obj = json.loads(candidate_report.read_text(encoding="utf-8"))
    metrics = report_obj.get("final_metrics", {})
    if not metrics:
        return None, False
    result = {
        "fit_label": fit_label,
        "fit_input": fit_input,
        "index": idx,
        "start": start_name,
        "xml": str(candidate_xml),
        "report": str(candidate_report),
        "baseline_ready": bool(report_obj.get("baseline_ready", False)),
        "returncode": proc.returncode,
        "metrics": metrics,
        "objective": baseline_objective(metrics),
    }
    print(
        f"Candidate {fit_label}/{idx} start={start_name}: ready={result['baseline_ready']} "
        f"dx={metrics['delta_x']:.6f} dy={metrics['delta_y']:.6f} "
        f"ang={metrics['delta_ang_deg']:.6f} obj={result['objective']:.6f}"
    )
    skip_family = idx == 1 and not result["baseline_ready"] and abs(metrics["delta_ang_deg"]) > args.max_baseline_ang
    if skip_family:
        print(
            f"Skipping remaining {fit_label} candidates: baseline angle "
            f"{metrics['delta_ang_deg']:.6f} exceeds {args.max_baseline_ang:.6f} deg"
        )
    return result, skip_family


def try_candidate_closure(
    args: argparse.Namespace,
    winner: dict,
    fit_label: str,
    staging_track_xml: pathlib.Path,
    close_cmd: list[str],
    select_cmd: list[str],
    geometric_close_cmd: Callable[..., list[str]],
    timed_run: Callable[..., None],
    cleanup_trackgen_lock: Callable[[], None],
    timing: dict,
) -> bool:
    if args.closure_solver == CLOSURE_SOLVER_GEOMETRIC:
        print(f"Trying geometric closure candidate {winner['fit_label']}/{winner['index']} ({winner['start']})")
        candidate_close_cmd = geometric_close_cmd(staging_track_xml, winner["fit_input"])
    else:
        print(
            f"Trying closure candidate {winner['fit_label']}/{winner['index']} ({winner['start']}) "
            f"with objective {winner['objective']:.6f}"
        )
        candidate_close_cmd = close_cmd
    try:
        if args.closure_solver == CLOSURE_SOLVER_LEGACY:
            timed_run(select_cmd, args.dry_run, f"select-controls-{fit_label}-{winner['index']}")
            print_stage_status("select-controls", "ok")
        timing["counters"]["closure_attempts"] += 1
        timed_run(candidate_close_cmd, args.dry_run, f"close-loop-{fit_label}-{winner['index']}", timeout_s=args.closure_timeout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        cleanup_trackgen_lock()
        print_stage_status("close-loop", "failed")
        print(f"Candidate did not close: {winner['fit_label']}/{winner['start']}")
        return False

    print_stage_status("close-loop", "ok")
    return True


def finish_closed_candidate_rebuild(
    args: argparse.Namespace,
    staging_track_xml: pathlib.Path,
    output_track_xml: pathlib.Path,
    winner: dict,
    run_side_clearance_adjustment: Callable[[pathlib.Path, bool], None],
    run_side_overlap_adjustment: Callable[[pathlib.Path, bool], None],
    run_curb_postprocess: Callable[[pathlib.Path, str | pathlib.Path, bool], None],
    cleanup_trackgen_lock: Callable[[], None],
    write_timing: Callable[[str], None],
    track_name: str,
    category: str,
    author: str,
    license_text: str,
    description: str,
    timing: dict,
    timing_report: pathlib.Path,
    fit_started: float,
    fit_summary: dict,
    validated_count: int,
) -> int:
    try:
        run_side_clearance_adjustment(staging_track_xml, args.dry_run)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print_stage_status("adjust-side-clearance", "failed")
        print_stage_status("promote", "skipped")
        print(f"Side-clearance adjustment failed. Live track XML was not modified: {output_track_xml}")
        write_timing("failed")
        return 1
    try:
        run_side_overlap_adjustment(staging_track_xml, args.dry_run)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print_stage_status("adjust-side-overlap", "failed")
        print_stage_status("promote", "skipped")
        print(f"Side-overlap adjustment failed. Live track XML was not modified: {output_track_xml}")
        write_timing("failed")
        return 1
    try:
        run_curb_postprocess(staging_track_xml, winner["fit_input"], args.dry_run)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        cleanup_trackgen_lock()
        print_stage_status("curb-postprocess", "failed")
        print_stage_status("promote", "skipped")
        print(f"Curb placement or post-curb closure failed. Live track XML was not modified: {output_track_xml}")
        write_timing("failed")
        return 1

    output_track_xml.parent.mkdir(parents=True, exist_ok=True)
    from torcs_track_tools.core.track_georeference import refresh_reference

    refresh_reference(staging_track_xml, pathlib.Path(winner["fit_input"]))
    shutil.copyfile(staging_track_xml, output_track_xml)
    update_promoted_xml_header_file_name(output_track_xml)
    readme = write_track_readme(output_track_xml.parent, track_name, category, author, license_text, description, timing["commands"])
    print_stage_status("promote", "ok")
    print(f"Promoted staged rebuild to live track XML: {output_track_xml}")
    print(f"Wrote track README: {readme}")
    fit_summary["elapsed_seconds"] = time.perf_counter() - fit_started
    fit_summary["validated_candidates"] = validated_count
    timing["fit_families"].append(fit_summary)
    write_timing("ok")
    print(f"Wrote timing report: {timing_report}")
    print("Mainline rebuild completed.")
    return 0


def fit_family_paths(args: argparse.Namespace, source_dir: pathlib.Path, fit_label: str) -> argparse.Namespace:
    artifact_label = f"{args.segment_fitter}-{fit_label}"
    fit_segments_json = source_dir / f"segments-{artifact_label}.json"
    fit_segments_xml = source_dir / f"segments-{artifact_label}.xml"
    reverse_fitted_segments = args.reverse_input and args.segment_fitter == SEGMENT_FITTER_POLYLINE
    return argparse.Namespace(
        artifact_label=artifact_label,
        fit_segments_json=fit_segments_json,
        fit_segments_xml=fit_segments_xml,
        family_segments_json=source_dir / f"segments-{artifact_label}-reversed.json" if reverse_fitted_segments else fit_segments_json,
        family_segments_xml=source_dir / f"segments-{artifact_label}-reversed.xml" if reverse_fitted_segments else fit_segments_xml,
        family_fit_svg=source_dir / f"fit-overlay-{artifact_label}.svg",
        family_cache_meta=source_dir / f"segments-{artifact_label}.cache.json",
        reverse_fitted_segments=reverse_fitted_segments,
    )


def build_family_fit_cmd(args: argparse.Namespace, fit_cmd: list[str], fit_input: str, paths: argparse.Namespace, preserve_tail: bool) -> list[str]:
    family_fit_cmd = list(fit_cmd)
    family_fit_cmd[family_fit_cmd.index("--input") + 1] = fit_input
    family_fit_cmd[family_fit_cmd.index("--output-json") + 1] = str(paths.fit_segments_json)
    family_fit_cmd[family_fit_cmd.index("--output-xml") + 1] = str(paths.fit_segments_xml)
    family_fit_cmd[family_fit_cmd.index("--output-svg") + 1] = str(paths.family_fit_svg)
    if args.segment_fitter == SEGMENT_FITTER_POLYLINE:
        family_fit_cmd = [item for item in family_fit_cmd if item != "--preserve-tail-seam"]
    if preserve_tail and args.segment_fitter == SEGMENT_FITTER_POLYLINE:
        family_fit_cmd.append("--preserve-tail-seam")
    return family_fit_cmd


def run_or_use_fit_cache(
    args: argparse.Namespace,
    fit_label: str,
    fit_input: str,
    preserve_tail: bool,
    paths: argparse.Namespace,
    family_fit_cmd: list[str],
    timing: dict,
    timed_run: Callable[..., None],
) -> bool:
    cache_key = fit_cache_key(args, pathlib.Path(fit_input), preserve_tail)
    cache_outputs = [paths.fit_segments_json, paths.fit_segments_xml]
    cache_hit = not args.no_fit_cache and fit_cache_valid(paths.family_cache_meta, cache_key, cache_outputs)
    if cache_hit:
        print(f"Using cached fit for {fit_label}: {paths.fit_segments_xml}")
        timing["stages"].append({"stage": f"fit-{fit_label}", "elapsed_seconds": 0.0, "cache_hit": True, "dry_run": False})
    else:
        timed_run(family_fit_cmd, args.dry_run, f"fit-{fit_label}")
        if not args.dry_run:
            paths.family_cache_meta.write_text(json.dumps(cache_key, indent=2), encoding="utf-8")
        timing["counters"]["fit_families_run"] += 1
    return cache_hit


def prepare_family_outputs(args: argparse.Namespace, paths: argparse.Namespace, segments_json: pathlib.Path, segments_xml: pathlib.Path, fit_svg: pathlib.Path) -> None:
    if paths.reverse_fitted_segments:
        reverse_segments_json(paths.fit_segments_json, paths.family_segments_json)
        reverse_segments_xml(paths.fit_segments_xml, paths.family_segments_xml)
    if args.dry_run:
        return
    shutil.copyfile(paths.family_segments_json, segments_json)
    shutil.copyfile(paths.family_segments_xml, segments_xml)
    if paths.family_fit_svg.exists():
        shutil.copyfile(paths.family_fit_svg, fit_svg)


def run_fit_family(
    args: argparse.Namespace,
    source_dir: pathlib.Path,
    fit_cmd: list[str],
    segments_json: pathlib.Path,
    segments_xml: pathlib.Path,
    fit_svg: pathlib.Path,
    fit_index: int,
    fit_label: str,
    fit_input: str,
    preserve_tail: bool,
    timing: dict,
    timed_run: Callable[..., None],
) -> tuple[dict, pathlib.Path, float]:
    fit_started = time.perf_counter()
    fit_summary = {"label": fit_label, "input": fit_input, "preserve_tail": preserve_tail, "candidate_results": []}
    paths = fit_family_paths(args, source_dir, fit_label)
    family_fit_cmd = build_family_fit_cmd(args, fit_cmd, fit_input, paths, preserve_tail)
    print(f"Fit input candidate {fit_index} ({fit_label}): {fit_input}")
    cache_hit = run_or_use_fit_cache(args, fit_label, fit_input, preserve_tail, paths, family_fit_cmd, timing, timed_run)
    prepare_family_outputs(args, paths, segments_json, segments_xml, fit_svg)
    fit_summary["cache_hit"] = cache_hit
    print_stage_status(f"fit-{fit_label}", "ok")
    current_segments_xml = paths.family_segments_xml if not args.dry_run else segments_xml
    return fit_summary, current_segments_xml, fit_started


def candidate_artifact_paths(source_dir: pathlib.Path, output_stem: str, fit_label: str, idx: int) -> tuple[pathlib.Path, pathlib.Path]:
    candidate_xml = source_dir / f"{output_stem}-mainline-{fit_label}-candidate-{idx}.xml"
    candidate_report = source_dir / f"closure-report-mainline-{fit_label}-candidate-{idx}.json"
    return candidate_xml, candidate_report


def build_start_candidate_apply_cmd(apply_cmd: list[str], current_segments_xml: pathlib.Path, candidate_xml: pathlib.Path, start_name: str) -> list[str]:
    candidate_apply_cmd = list(apply_cmd)
    candidate_apply_cmd[candidate_apply_cmd.index("--segments-xml") + 1] = str(current_segments_xml)
    candidate_apply_cmd[candidate_apply_cmd.index("--output-xml") + 1] = str(candidate_xml)
    candidate_apply_cmd.extend(["--start-segment", start_name])
    return candidate_apply_cmd


def evaluate_rebuild_start_candidate(
    args: argparse.Namespace,
    py: str,
    close_script: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    closure_config: pathlib.Path,
    closure_report: pathlib.Path,
    fit_label: str,
    fit_input: str,
    idx: int,
    start_name: str,
    candidate_xml: pathlib.Path,
    candidate_report: pathlib.Path,
    current_segments_xml: pathlib.Path,
    apply_cmd: list[str],
    timing: dict,
    timed_run: Callable[..., None],
    timed_run_check_false: Callable[[list[str], str], subprocess.CompletedProcess],
) -> tuple[dict | None, bool]:
    candidate_apply_cmd = build_start_candidate_apply_cmd(apply_cmd, current_segments_xml, candidate_xml, start_name)
    timed_run(candidate_apply_cmd, args.dry_run, f"apply-{fit_label}-{idx}")
    timing["counters"]["candidate_applies"] += 1
    return evaluate_candidate_baseline(
        args,
        py,
        close_script,
        runtime_dir,
        category,
        name,
        closure_config,
        closure_report,
        fit_label,
        fit_input,
        idx,
        start_name,
        candidate_xml,
        candidate_report,
        timing,
        timed_run_check_false,
    )


def validate_candidate_batch(
    args: argparse.Namespace,
    py: str,
    close_script: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    closure_config: pathlib.Path,
    closure_report: pathlib.Path,
    fit_label: str,
    fit_input: str,
    candidates: list[str],
    batch: list[str],
    current_segments_xml: pathlib.Path,
    output_track_xml: pathlib.Path,
    source_dir: pathlib.Path,
    apply_cmd: list[str],
    timing: dict,
    timed_run: Callable[..., None],
    timed_run_check_false: Callable[[list[str], str], subprocess.CompletedProcess],
) -> tuple[list[dict], list[dict], int, bool]:
    results: list[dict] = []
    ready: list[dict] = []
    validated_count = 0
    skip_family = False
    for start_name in batch:
        idx = candidates.index(start_name) + 1
        validated_count += 1
        candidate_xml, candidate_report = candidate_artifact_paths(source_dir, output_track_xml.stem, fit_label, idx)
        result, skip_family = evaluate_rebuild_start_candidate(
            args,
            py,
            close_script,
            runtime_dir,
            category,
            name,
            closure_config,
            closure_report,
            fit_label,
            fit_input,
            idx,
            start_name,
            candidate_xml,
            candidate_report,
            current_segments_xml,
            apply_cmd,
            timing,
            timed_run,
            timed_run_check_false,
        )
        if result is not None:
            results.append(result)
            if result["baseline_ready"]:
                ready.append(result)
        if skip_family:
            break
    return results, ready, validated_count, skip_family


def print_candidate_expansion_message(ready: list[dict], fit_label: str, objective_threshold: float) -> None:
    best_objective = min(result["objective"] for result in ready)
    print(
        f"Best {fit_label} baseline objective {best_objective:.6f} exceeds "
        f"{objective_threshold:.6f}; expanding candidate search before strict closure."
    )


def try_ready_candidate_rebuild(
    args: argparse.Namespace,
    ready: list[dict],
    fit_label: str,
    staging_track_xml: pathlib.Path,
    output_track_xml: pathlib.Path,
    close_cmd: list[str],
    select_cmd: list[str],
    geometric_close_cmd: Callable[..., list[str]],
    timed_run: Callable[..., None],
    cleanup_trackgen_lock: Callable[[], None],
    run_side_clearance_adjustment: Callable[[pathlib.Path, bool], None],
    run_side_overlap_adjustment: Callable[[pathlib.Path, bool], None],
    run_curb_postprocess: Callable[[pathlib.Path, str | pathlib.Path, bool], None],
    write_timing: Callable[[str], None],
    track_name: str,
    category: str,
    author: str,
    license_text: str,
    description: str,
    timing: dict,
    timing_report: pathlib.Path,
    fit_started: float,
    fit_summary: dict,
    validated_count: int,
) -> int | None:
    print_stage_status("apply", "ok")
    ready.sort(key=lambda result: result["objective"])
    for winner in ready:
        shutil.copyfile(winner["xml"], staging_track_xml)
        if not try_candidate_closure(args, winner, fit_label, staging_track_xml, close_cmd, select_cmd, geometric_close_cmd, timed_run, cleanup_trackgen_lock, timing):
            continue
        return finish_closed_candidate_rebuild(
            args,
            staging_track_xml,
            output_track_xml,
            winner,
            run_side_clearance_adjustment,
            run_side_overlap_adjustment,
            run_curb_postprocess,
            cleanup_trackgen_lock,
            write_timing,
            track_name,
            category,
            author,
            license_text,
            description,
            timing,
            timing_report,
            fit_started,
            fit_summary,
            validated_count,
        )
    return None


def finalize_fit_family_summary(fit_summary: dict, timing: dict, fit_started: float, validated_count: int) -> None:
    fit_summary["elapsed_seconds"] = time.perf_counter() - fit_started
    fit_summary["validated_candidates"] = validated_count
    timing["fit_families"].append(fit_summary)


def finish_failed_candidate_rebuild(all_results: list[dict], output_track_xml: pathlib.Path, write_timing: Callable[[str], None], timing_report: pathlib.Path) -> int:
    print_stage_status("promote", "skipped")
    if all_results:
        best_failed = min(all_results, key=lambda r: r["objective"])
        print(
            "No baseline-ready candidate closed. Best candidate: "
            f"{best_failed['fit_label']}/{best_failed['start']} ({best_failed['xml']})"
        )
    print(f"Live track XML was not modified: {output_track_xml}")
    write_timing("failed")
    print(f"Wrote timing report: {timing_report}")
    return 1


def prepare_fit_family_candidates(args: argparse.Namespace, current_segments_xml: pathlib.Path, fit_label: str) -> tuple[list[str], list[list[str]]]:
    candidates = start_candidate_names(current_segments_xml, max(1, args.max_start_candidates))
    if not candidates:
        raise SystemExit("No candidate start straights found in fitted segments")
    print(f"Start candidates ({fit_label}): " + ", ".join(candidates))
    return candidates, candidate_validation_batches(candidates, args.initial_start_candidates, args.exhaustive_candidates)


def close_ready_batch(
    args: argparse.Namespace,
    ready: list[dict],
    fit_label: str,
    batch_index: int,
    batch_count: int,
    staging_track_xml: pathlib.Path,
    output_track_xml: pathlib.Path,
    close_cmd: list[str],
    select_cmd: list[str],
    geometric_close_cmd: Callable[..., list[str]],
    timed_run: Callable[..., None],
    cleanup_trackgen_lock: Callable[[], None],
    run_side_clearance_adjustment: Callable[[pathlib.Path, bool], None],
    run_side_overlap_adjustment: Callable[[pathlib.Path, bool], None],
    run_curb_postprocess: Callable[[pathlib.Path, str | pathlib.Path, bool], None],
    write_timing: Callable[[str], None],
    track_name: str,
    category: str,
    author: str,
    license_text: str,
    description: str,
    timing: dict,
    timing_report: pathlib.Path,
    fit_started: float,
    fit_summary: dict,
    validated_count: int,
) -> int | None:
    if not ready:
        return None
    if should_expand_before_closure(ready, batch_index, batch_count, args.expand_candidates_objective):
        print_candidate_expansion_message(ready, fit_label, args.expand_candidates_objective)
        return None
    rebuild_result = try_ready_candidate_rebuild(
        args,
        ready,
        fit_label,
        staging_track_xml,
        output_track_xml,
        close_cmd,
        select_cmd,
        geometric_close_cmd,
        timed_run,
        cleanup_trackgen_lock,
        run_side_clearance_adjustment,
        run_side_overlap_adjustment,
        run_curb_postprocess,
        write_timing,
        track_name,
        category,
        author,
        license_text,
        description,
        timing,
        timing_report,
        fit_started,
        fit_summary,
        validated_count,
    )
    if rebuild_result is not None:
        return rebuild_result
    ready.clear()
    if batch_index < batch_count:
        print(f"No candidate in initial {fit_label} batch closed; expanding candidate search.")
    return None


def run_rebuild_fit_family(
    args: argparse.Namespace,
    py: str,
    source_dir: pathlib.Path,
    fit_cmd: list[str],
    output_track_xml: pathlib.Path,
    segments_json: pathlib.Path,
    segments_xml: pathlib.Path,
    fit_svg: pathlib.Path,
    apply_cmd: list[str],
    close_cmd: list[str],
    select_cmd: list[str],
    close_script: pathlib.Path,
    closure_config: pathlib.Path,
    closure_report: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    staging_track_xml: pathlib.Path,
    timing: dict,
    timed_run: Callable[..., None],
    timed_run_check_false: Callable[[list[str], str], subprocess.CompletedProcess],
    geometric_close_cmd: Callable[..., list[str]],
    cleanup_trackgen_lock: Callable[[], None],
    run_side_clearance_adjustment: Callable[[pathlib.Path, bool], None],
    run_side_overlap_adjustment: Callable[[pathlib.Path, bool], None],
    run_curb_postprocess: Callable[[pathlib.Path, str | pathlib.Path, bool], None],
    write_timing: Callable[[str], None],
    author: str,
    license_text: str,
    description: str,
    timing_report: pathlib.Path,
    fit_index: int,
    fit_label: str,
    fit_input: str,
    preserve_tail: bool,
) -> tuple[int | None, list[dict]]:
    fit_summary, current_segments_xml, fit_started = run_fit_family(
        args,
        source_dir,
        fit_cmd,
        segments_json,
        segments_xml,
        fit_svg,
        fit_index,
        fit_label,
        fit_input,
        preserve_tail,
        timing,
        timed_run,
    )
    candidates, batches = prepare_fit_family_candidates(args, current_segments_xml, fit_label)
    family_results: list[dict] = []
    ready: list[dict] = []
    validated_count = 0
    for batch_index, batch in enumerate(batches, start=1):
        batch_results, batch_ready, batch_validated_count, skip_family = validate_candidate_batch(
            args,
            py,
            close_script,
            runtime_dir,
            category,
            name,
            closure_config,
            closure_report,
            fit_label,
            fit_input,
            candidates,
            batch,
            current_segments_xml,
            output_track_xml,
            source_dir,
            apply_cmd,
            timing,
            timed_run,
            timed_run_check_false,
        )
        validated_count += batch_validated_count
        family_results.extend(batch_results)
        fit_summary["candidate_results"].extend(batch_results)
        ready.extend(batch_ready)
        if skip_family:
            break
        rebuild_result = close_ready_batch(
            args,
            ready,
            fit_label,
            batch_index,
            len(batches),
            staging_track_xml,
            output_track_xml,
            close_cmd,
            select_cmd,
            geometric_close_cmd,
            timed_run,
            cleanup_trackgen_lock,
            run_side_clearance_adjustment,
            run_side_overlap_adjustment,
            run_curb_postprocess,
            write_timing,
            args.track_name or default_track_name(name),
            category,
            author,
            license_text,
            description,
            timing,
            timing_report,
            fit_started,
            fit_summary,
            validated_count,
        )
        if rebuild_result is not None:
            return rebuild_result, family_results
    finalize_fit_family_summary(fit_summary, timing, fit_started, validated_count)
    return None, family_results


def run_rebuild_candidate_pipeline(
    args: argparse.Namespace,
    py: str,
    prep_source_input: pathlib.Path,
    prepared_input: pathlib.Path,
    seam_report: pathlib.Path,
    source_dir: pathlib.Path,
    fit_cmd: list[str],
    output_track_xml: pathlib.Path,
    segments_json: pathlib.Path,
    segments_xml: pathlib.Path,
    fit_svg: pathlib.Path,
    apply_cmd: list[str],
    close_cmd: list[str],
    select_cmd: list[str],
    close_script: pathlib.Path,
    closure_config: pathlib.Path,
    closure_report: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    staging_track_xml: pathlib.Path,
    timing: dict,
    timed_run: Callable[..., None],
    timed_run_check_false: Callable[[list[str], str], subprocess.CompletedProcess],
    geometric_close_cmd: Callable[..., list[str]],
    cleanup_trackgen_lock: Callable[[], None],
    run_side_clearance_adjustment: Callable[[pathlib.Path, bool], None],
    run_side_overlap_adjustment: Callable[[pathlib.Path, bool], None],
    run_curb_postprocess: Callable[[pathlib.Path, str | pathlib.Path, bool], None],
    write_timing: Callable[[str], None],
    author: str,
    license_text: str,
    description: str,
    timing_report: pathlib.Path,
) -> int:
    fit_inputs = build_fit_input_candidates(args, prep_source_input, prepared_input, seam_report)
    all_results: list[dict] = []
    for fit_index, (fit_label, fit_input, preserve_tail) in enumerate(fit_inputs, start=1):
        rebuild_result, family_results = run_rebuild_fit_family(
            args,
            py,
            source_dir,
            fit_cmd,
            output_track_xml,
            segments_json,
            segments_xml,
            fit_svg,
            apply_cmd,
            close_cmd,
            select_cmd,
            close_script,
            closure_config,
            closure_report,
            runtime_dir,
            category,
            name,
            staging_track_xml,
            timing,
            timed_run,
            timed_run_check_false,
            geometric_close_cmd,
            cleanup_trackgen_lock,
            run_side_clearance_adjustment,
            run_side_overlap_adjustment,
            run_curb_postprocess,
            write_timing,
            author,
            license_text,
            description,
            timing_report,
            fit_index,
            fit_label,
            fit_input,
            preserve_tail,
        )
        all_results.extend(family_results)
        if rebuild_result is not None:
            return rebuild_result

    return finish_failed_candidate_rebuild(all_results, output_track_xml, write_timing, timing_report)


def build_rebuild_scripts(args: argparse.Namespace, script_dir: pathlib.Path) -> argparse.Namespace:
    return argparse.Namespace(
        fit_script=tool_script(script_dir, "draft_segments.py" if args.segment_fitter == SEGMENT_FITTER_DP_BIARC else "polyline_to_torcs.py"),
        prep_script=tool_script(script_dir, "prepare_loop_polyline.py"),
        reverse_script=tool_script(script_dir, "reverse_centerline.py"),
        apply_script=tool_script(script_dir, "apply_segments.py"),
        adjust_side_clearance_script=tool_script(script_dir, "adjust_side_clearance.py"),
        adjust_side_overlap_script=tool_script(script_dir, "adjust_side_overlap.py"),
        place_curbs_script=tool_script(script_dir, "place_curbs.py"),
        close_script=tool_script(script_dir, "close_loop.py"),
        geometric_close_script=tool_script(script_dir, "close_loop_geometric.py"),
    )


def build_rebuild_paths(args: argparse.Namespace, script_dir: pathlib.Path) -> argparse.Namespace:
    output_track_xml = pathlib.Path(args.output_track_xml)
    template_xml = pathlib.Path(args.template_xml) if args.template_xml else bundled_template_path(script_dir)
    source_dir = output_track_xml.parent / "source"
    reversed_input = source_dir / "centerline-reversed.json"
    rebuild_input = pathlib.Path(args.input)
    prep_source_input = reversed_input if args.reverse_input and args.segment_fitter == SEGMENT_FITTER_DP_BIARC else rebuild_input
    prepared_input = source_dir / "centerline-prepared.json"
    seam_report = source_dir / "centerline-prepared-seam-report.json"
    seam_overlay = source_dir / "centerline-prepared-seam-overlay.svg"
    segments_json = pathlib.Path(args.segments_json) if args.segments_json else source_dir / "segments.json"
    segments_xml = pathlib.Path(args.segments_xml) if args.segments_xml else source_dir / "segments.xml"
    fit_svg = pathlib.Path(args.fit_svg) if args.fit_svg else source_dir / "fit-overlay.svg"
    closure_config = pathlib.Path(args.closure_config) if args.closure_config else source_dir / "closure-config-mainline.json"
    closure_report = pathlib.Path(args.closure_report) if args.closure_report else source_dir / "closure-report-mainline.json"
    comparison_svg = pathlib.Path(args.comparison_svg) if args.comparison_svg else closure_report.with_name(closure_report.stem + "-overlay.svg")
    comparison_report = pathlib.Path(args.comparison_report) if args.comparison_report else closure_report.with_name(closure_report.stem + "-overlay.json")
    curb_report = pathlib.Path(args.curb_report) if args.curb_report else source_dir / "curb-placement-report.json"
    curb_closure_report = pathlib.Path(args.curb_closure_report) if args.curb_closure_report else source_dir / "closure-report-curbs-geometric.json"
    timing_report = pathlib.Path(args.timing_report) if args.timing_report else source_dir / "rebuild-mainline-timing.json"
    return argparse.Namespace(
        output_track_xml=output_track_xml,
        template_xml=template_xml,
        source_dir=source_dir,
        reversed_input=reversed_input,
        rebuild_input=rebuild_input,
        prep_source_input=prep_source_input,
        prepared_input=prepared_input,
        seam_report=seam_report,
        seam_overlay=seam_overlay,
        segments_json=segments_json,
        segments_xml=segments_xml,
        fit_svg=fit_svg,
        closure_config=closure_config,
        closure_report=closure_report,
        comparison_svg=comparison_svg,
        comparison_report=comparison_report,
        side_clearance_report=source_dir / "side-clearance-report.json",
        side_overlap_report=source_dir / "side-overlap-report.json",
        curb_report=curb_report,
        curb_closure_report=curb_closure_report,
        curb_comparison_svg=curb_closure_report.with_name(curb_closure_report.stem + "-overlay.svg"),
        curb_comparison_report=curb_closure_report.with_name(curb_closure_report.stem + "-overlay.json"),
        timing_report=timing_report,
        staging_track_xml=source_dir / f"{output_track_xml.stem}-mainline-staging.xml",
    )


def init_rebuild_timing(args: argparse.Namespace, paths: argparse.Namespace) -> dict:
    return {
        "schema": 1,
        "track": {"category": "", "name": ""},
        "elapsed_seconds": 0.0,
        "counters": {
            "python_subprocesses": 0,
            "fit_families_run": 0,
            "candidate_applies": 0,
            "baseline_checks": 0,
            "closure_attempts": 0,
        },
        "stages": [],
        "fit_families": [],
        "segment_fitter": args.segment_fitter,
        "closure_solver": args.closure_solver,
        "reverse_input": bool(args.reverse_input),
        "side_clearance_adjustment": {
            "enabled": bool(args.adjust_side_clearance),
            "report": str(paths.side_clearance_report),
        },
        "side_overlap_adjustment": {
            "enabled": bool(args.adjust_side_overlap),
            "report": str(paths.side_overlap_report),
        },
        "curb_placement": {
            "enabled": bool(args.place_curbs),
            "placement": args.curb_placement,
            "report": str(paths.curb_report),
            "closure_report": str(paths.curb_closure_report),
        },
        "commands": [subprocess.list2cmdline(["torcs-rebuild-mainline", *sys.argv[1:]])],
    }


def resolve_rebuild_runtime_context(args: argparse.Namespace, output_track_xml: pathlib.Path) -> tuple[pathlib.Path, str, str]:
    if args.runtime_dir and args.category and args.name:
        return pathlib.Path(args.runtime_dir), args.category, args.name
    runtime_dir, category, name = derive_runtime_context(output_track_xml)
    if args.runtime_dir:
        runtime_dir = pathlib.Path(args.runtime_dir)
    if args.category:
        category = args.category
    if args.name:
        name = args.name
    return runtime_dir, category, name


def validate_rebuild_template(template_xml: pathlib.Path) -> None:
    if not template_xml.exists():
        raise SystemExit(f"Template XML not found: {template_xml}")


def validate_rebuild_inputs(
    args: argparse.Namespace,
    rebuild_input: pathlib.Path,
    output_track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
) -> None:
    validate_path_style(rebuild_input, output_track_xml, runtime_dir)
    if not args.dry_run and not rebuild_input.exists():
        raise SystemExit(f"Input centerline cache not found: {rebuild_input}")
    if not args.dry_run and not ((runtime_dir / "trackgen.exe").exists() or (runtime_dir / "trackgen").exists()):
        raise SystemExit(f"trackgen executable not found in runtime directory: {runtime_dir}")


def print_rebuild_summary(
    args: argparse.Namespace,
    source_dir: pathlib.Path,
    rebuild_input: pathlib.Path,
    reversed_input: pathlib.Path,
    template_xml: pathlib.Path,
    staging_track_xml: pathlib.Path,
    output_track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
) -> None:
    print(f"Source dir: {source_dir}")
    print(f"Input centerline: {rebuild_input}")
    if args.reverse_input:
        print(f"Reversed centerline artifact: {reversed_input}")
    print(f"Template XML: {template_xml}")
    print(f"Staging XML: {staging_track_xml}")
    print(f"Final output XML: {output_track_xml}")
    print(f"Runtime dir: {runtime_dir}")
    print(f"Track context: category={category} name={name}")
    print(f"Segment fitter: {args.segment_fitter}")
    print(f"Closure solver: {args.closure_solver}")
    print(f"Curb placement: {'enabled (' + args.curb_placement + ')' if args.place_curbs else 'disabled'}")
    if args.dry_run and not args.author.strip():
        print("Author: required for real generation; rerun with --author before writing live XML.")


def run_rebuild_preparation(
    args: argparse.Namespace,
    reverse_cmd: list[str],
    prep_cmd: list[str],
    timed_run: Callable[..., None],
) -> None:
    if args.reverse_input:
        timed_run(reverse_cmd, args.dry_run, "reverse-input")
        print_stage_status("reverse-input", "planned" if args.dry_run else "ok")
    timed_run(prep_cmd, args.dry_run, "prepare-seam")
    print_stage_status("prepare-seam", "planned" if args.dry_run else "ok")


def run_rebuild_dry_plan(
    args: argparse.Namespace,
    fit_cmd: list[str],
    apply_cmd: list[str],
    select_cmd: list[str],
    planned_close_cmd: list[str],
    staging_track_xml: pathlib.Path,
    prepared_input: pathlib.Path,
    timed_run: Callable[..., None],
    run_side_clearance_adjustment: Callable[[pathlib.Path, bool], None],
    run_side_overlap_adjustment: Callable[[pathlib.Path, bool], None],
    run_curb_postprocess: Callable[[pathlib.Path, str | pathlib.Path, bool], None],
    write_timing: Callable[[str], None],
) -> int:
    timed_run(fit_cmd, args.dry_run, "fit")
    print_stage_status("fit", "planned")
    timed_run(apply_cmd, args.dry_run, "apply")
    print_stage_status("apply", "planned")
    if args.closure_solver == CLOSURE_SOLVER_LEGACY:
        timed_run(select_cmd, args.dry_run, "select-controls")
        print_stage_status("select-controls", "planned")
    write_timing("planned")
    timed_run(planned_close_cmd, args.dry_run, "close-loop", timeout_s=args.closure_timeout)
    print_stage_status("close-loop", "planned")
    run_side_clearance_adjustment(staging_track_xml, args.dry_run)
    run_side_overlap_adjustment(staging_track_xml, args.dry_run)
    run_curb_postprocess(staging_track_xml, prepared_input, args.dry_run)
    print_stage_status("promote", "planned")
    write_timing("planned")
    print("Mainline rebuild completed.")
    return 0


def main() -> int:
    run_started = time.perf_counter()
    args = parse_args()
    author = ""
    license_text = args.license.strip() or DEFAULT_LICENSE
    script_dir = pathlib.Path(__file__).resolve().parent
    scripts = build_rebuild_scripts(args, script_dir)
    paths = build_rebuild_paths(args, script_dir)
    fit_script = scripts.fit_script
    prep_script = scripts.prep_script
    reverse_script = scripts.reverse_script
    apply_script = scripts.apply_script
    adjust_side_clearance_script = scripts.adjust_side_clearance_script
    adjust_side_overlap_script = scripts.adjust_side_overlap_script
    place_curbs_script = scripts.place_curbs_script
    close_script = scripts.close_script
    geometric_close_script = scripts.geometric_close_script
    output_track_xml = paths.output_track_xml
    template_xml = paths.template_xml
    source_dir = paths.source_dir
    reversed_input = paths.reversed_input
    rebuild_input = paths.rebuild_input
    prep_source_input = paths.prep_source_input
    prepared_input = paths.prepared_input
    seam_report = paths.seam_report
    seam_overlay = paths.seam_overlay
    segments_json = paths.segments_json
    segments_xml = paths.segments_xml
    fit_svg = paths.fit_svg
    closure_config = paths.closure_config
    closure_report = paths.closure_report
    comparison_svg = paths.comparison_svg
    comparison_report = paths.comparison_report
    side_clearance_report = paths.side_clearance_report
    side_overlap_report = paths.side_overlap_report
    curb_report = paths.curb_report
    curb_closure_report = paths.curb_closure_report
    curb_comparison_svg = paths.curb_comparison_svg
    curb_comparison_report = paths.curb_comparison_report
    timing_report = paths.timing_report
    staging_track_xml = paths.staging_track_xml
    timing = init_rebuild_timing(args, paths)

    def write_timing(status: str) -> None:
        write_rebuild_timing(timing, timing_report, run_started, status)

    def timed_run(cmd: list[str], dry_run: bool, stage: str, timeout_s: float | None = None) -> None:
        timed_rebuild_run(cmd, dry_run, stage, timing, timing_report, run_started, timeout_s=timeout_s)

    def timed_run_check_false(cmd: list[str], stage: str) -> subprocess.CompletedProcess:
        return timed_rebuild_run_check_false(cmd, stage, timing, timing_report, run_started)

    def cleanup_trackgen_lock() -> None:
        cleanup_rebuild_trackgen_lock(runtime_dir, category, name)

    def run_side_clearance_adjustment(track_xml: pathlib.Path, dry_run: bool) -> None:
        run_rebuild_side_clearance_adjustment(
            args,
            py,
            adjust_side_clearance_script,
            side_clearance_report,
            track_xml,
            dry_run,
            timing,
            write_timing,
            timed_run,
        )

    def run_side_overlap_adjustment(track_xml: pathlib.Path, dry_run: bool) -> None:
        run_rebuild_side_overlap_adjustment(
            args,
            py,
            adjust_side_overlap_script,
            side_overlap_report,
            track_xml,
            dry_run,
            timing,
            write_timing,
            timed_run,
        )

    def run_curb_postprocess(track_xml: pathlib.Path, source_polyline: str | pathlib.Path, dry_run: bool) -> None:
        run_rebuild_curb_postprocess(
            args,
            py,
            place_curbs_script,
            geometric_close_script,
            runtime_dir,
            category,
            name,
            curb_report,
            curb_closure_report,
            curb_comparison_svg,
            curb_comparison_report,
            track_xml,
            source_polyline,
            dry_run,
            timing,
            write_timing,
            timed_run,
        )

    validate_rebuild_template(template_xml)
    runtime_dir, category, name = resolve_rebuild_runtime_context(args, output_track_xml)
    timing["track"] = {"category": category, "name": name}
    if not args.dry_run:
        author = validate_author(args.author)
    validate_rebuild_inputs(args, rebuild_input, output_track_xml, runtime_dir)

    py = sys.executable
    description = args.description.strip() or default_description(args.track_name or default_track_name(name))
    reverse_cmd = build_reverse_centerline_cmd(args, py, reverse_script, reversed_input)
    prep_cmd = build_prepare_loop_cmd(py, prep_script, prep_source_input, prepared_input, seam_report, seam_overlay)
    fit_cmd = build_fit_cmd(args, py, fit_script, prepared_input, segments_json, segments_xml, fit_svg)
    apply_cmd = build_apply_cmd(args, py, apply_script, template_xml, segments_xml, staging_track_xml, name, license_text, description)
    select_cmd = build_select_controls_cmd(py, close_script, staging_track_xml, runtime_dir, category, name, closure_config)
    close_cmd = build_legacy_close_cmd(args, py, close_script, staging_track_xml, runtime_dir, category, name, closure_config, closure_report)

    def geometric_close_cmd(
        track_xml: pathlib.Path,
        source_polyline: str | pathlib.Path,
        report_path: pathlib.Path = closure_report,
        comparison_svg_path: pathlib.Path = comparison_svg,
        comparison_report_path: pathlib.Path = comparison_report,
    ) -> list[str]:
        return build_geometric_close_cmd(
            args,
            py,
            geometric_close_script,
            runtime_dir,
            category,
            name,
            track_xml,
            source_polyline,
            report_path,
            comparison_svg_path,
            comparison_report_path,
        )

    planned_close_cmd = close_cmd if args.closure_solver == CLOSURE_SOLVER_LEGACY else geometric_close_cmd(staging_track_xml, prepared_input)

    source_dir.mkdir(parents=True, exist_ok=True)
    print_rebuild_summary(args, source_dir, rebuild_input, reversed_input, template_xml, staging_track_xml, output_track_xml, runtime_dir, category, name)
    run_rebuild_preparation(args, reverse_cmd, prep_cmd, timed_run)
    if args.dry_run:
        return run_rebuild_dry_plan(
            args,
            fit_cmd,
            apply_cmd,
            select_cmd,
            planned_close_cmd,
            staging_track_xml,
            prepared_input,
            timed_run,
            run_side_clearance_adjustment,
            run_side_overlap_adjustment,
            run_curb_postprocess,
            write_timing,
        )
    return run_rebuild_candidate_pipeline(
        args,
        py,
        prep_source_input,
        prepared_input,
        seam_report,
        source_dir,
        fit_cmd,
        output_track_xml,
        segments_json,
        segments_xml,
        fit_svg,
        apply_cmd,
        close_cmd,
        select_cmd,
        close_script,
        closure_config,
        closure_report,
        runtime_dir,
        category,
        name,
        staging_track_xml,
        timing,
        timed_run,
        timed_run_check_false,
        geometric_close_cmd,
        cleanup_trackgen_lock,
        run_side_clearance_adjustment,
        run_side_overlap_adjustment,
        run_curb_postprocess,
        write_timing,
        author,
        license_text,
        description,
        timing_report,
    )


if __name__ == "__main__":
    raise SystemExit(main())
