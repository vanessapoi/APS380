#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : close_loop_geometric.py
#     created              : 02 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Geometric TORCS loop closer using terminal-lever correction.

This is intentionally separate from close_loop.py.  The algorithm is:
1) Put a straight closure lever at the end of the segment list.
2) Solve heading and lateral closure with one turn arc and one non-parallel straight.
3) Fix longitudinal closure by changing only the terminal straight length.

The terminal lever is the important constraint: after heading/Y are correct,
trackgen's remaining X error is almost pure distance along the start tangent.
Correcting it at the end of the loop changes closure without moving the start
line or re-opening the lateral/heading solve.

The default Y gate is 0.001 m because trackgen commonly reports the final
sub-millimeter residual as +/-0.000977 m.  X and heading stay stricter; widening
only Y avoids rejecting a loop that is already at trackgen's reporting quantum.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import pathlib
import re
import sys
import time

from torcs_track_tools.cli.close_loop import (
    has_planar_self_intersection,
    locate_track_segments_block,
    parse_top_level_segments,
    read_attnum_value,
    replace_attnum_value,
    simulate_segments,
    split_turn_with_straight_insert,
    to_float,
    unique_name,
)
from torcs_track_tools.core.defaults import DEFAULT_TARGET_ANG_DEG, DEFAULT_TARGET_DX_M, DEFAULT_TARGET_DY_M, DEFAULT_TARGET_DZ_M
from torcs_track_tools.core.overlay import (
    nearest_polyline_distance,
    rigid_fit,
    transform,
)
from torcs_track_tools.core.overlay import (
    parse_track_segments as parse_overlay_track_segments,
)
from torcs_track_tools.core.overlay import (
    to_xy as overlay_to_xy,
)
from torcs_track_tools.core.overlay import (
    torcs_points as overlay_torcs_points,
)
from torcs_track_tools.core.overlay import (
    write_svg as write_overlay_svg,
)
from torcs_track_tools.core.trackgen import TrackgenRunner, TrackgenStats

SELF_INTERSECTION_CHECKS = 0
SELF_INTERSECTION_SECONDS = 0.0
TRACKGEN_CACHE: dict[tuple[str, str, str], tuple[dict, str]] = {}
TRACKGEN_STATS = TrackgenStats()
TRACKGEN_TIMEOUT_S = 30.0
VERBOSE = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Geometric TORCS loop closer using terminal-lever correction")
    parser.add_argument("--profile", choices=["mainline", "post-pit"], default="mainline", help="Closure preset; post-pit preserves the Pit10 start segment")
    parser.add_argument("--track-xml", required=True, help="Track XML file path")
    parser.add_argument("--runtime-dir", required=True, help="TORCS runtime directory containing trackgen.exe")
    parser.add_argument("--category", required=True, help="Track category for trackgen")
    parser.add_argument("--name", required=True, help="Track short name for trackgen")
    parser.add_argument("--report", required=True, help="Report JSON path")
    parser.add_argument("--source-polyline", default="", help="Optional cached source polyline JSON for final overlay")
    parser.add_argument("--comparison-svg", default="", help="Optional source-vs-final XML overlay SVG path")
    parser.add_argument("--comparison-report", default="", help="Optional source-vs-final XML comparison JSON path")
    parser.add_argument("--comparison-samples", type=int, default=800, help=argparse.SUPPRESS)
    parser.add_argument("--target-dx", type=float, default=DEFAULT_TARGET_DX_M, help=argparse.SUPPRESS)
    parser.add_argument("--target-dy", type=float, default=DEFAULT_TARGET_DY_M, help=argparse.SUPPRESS)
    parser.add_argument("--target-dz", type=float, default=DEFAULT_TARGET_DZ_M, help=argparse.SUPPRESS)
    parser.add_argument("--target-ang", type=float, default=DEFAULT_TARGET_ANG_DEG, help=argparse.SUPPRESS)
    parser.add_argument("--max-cycles", type=int, default=3, help=argparse.SUPPRESS)
    parser.add_argument("--max-yang-iters", type=int, default=8, help=argparse.SUPPRESS)
    parser.add_argument("--min-start-straight", type=float, default=0.1, help=argparse.SUPPRESS)
    parser.add_argument("--insert-straight-length", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--terminal-split-min", type=float, default=10.0, help=argparse.SUPPRESS)
    parser.add_argument("--max-control-delta", type=float, default=30.0, help=argparse.SUPPRESS)
    parser.add_argument("--post-pit-turn-candidates", type=int, default=8, help=argparse.SUPPRESS)
    parser.add_argument("--post-pit-straight-candidates", type=int, default=8, help=argparse.SUPPRESS)
    parser.add_argument("--post-pit-terminal-candidates", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--trackgen-timeout", type=float, default=30.0, help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    apply_profile_defaults(args)
    return args


def cli_arg_present(name: str) -> bool:
    return any(arg == name or arg.startswith(name + "=") for arg in sys.argv[1:])


def apply_profile_defaults(args: argparse.Namespace) -> None:
    if args.profile != "post-pit":
        return
    if not cli_arg_present("--target-dy"):
        args.target_dy = 0.002
    if not cli_arg_present("--insert-straight-length"):
        args.insert_straight_length = 0.1


def log(message: str) -> None:
    if VERBOSE:
        print(message, flush=True)


def runtime_stats() -> dict:
    return {
        "trackgen_calls": TRACKGEN_STATS.calls,
        "trackgen_seconds": TRACKGEN_STATS.seconds,
        "trackgen_cache_hits": TRACKGEN_STATS.cache_hits,
        "self_intersection_checks": SELF_INTERSECTION_CHECKS,
        "self_intersection_seconds": SELF_INTERSECTION_SECONDS,
    }


def run_trackgen_z(runtime_dir: pathlib.Path, category: str, name: str, track_xml_under_test: pathlib.Path) -> tuple[dict, str]:
    runner = TrackgenRunner(
        runtime_dir,
        timeout_s=TRACKGEN_TIMEOUT_S,
        cache=TRACKGEN_CACHE,
        stats=TRACKGEN_STATS,
        allow_missing_live_xml=True,
        log=log,
    )
    return runner.run_z(category, name, track_xml_under_test)


def has_intersection(track_xml: pathlib.Path) -> bool:
    global SELF_INTERSECTION_CHECKS, SELF_INTERSECTION_SECONDS
    start = time.perf_counter()
    SELF_INTERSECTION_CHECKS += 1
    try:
        return has_planar_self_intersection(track_xml)
    finally:
        SELF_INTERSECTION_SECONDS += time.perf_counter() - start


def passed(metrics: dict, args: argparse.Namespace) -> bool:
    return (
        abs(metrics["delta_x"]) <= args.target_dx
        and abs(metrics["delta_y"]) <= args.target_dy
        and abs(metrics["delta_z"]) <= args.target_dz
        and abs(metrics["delta_ang_deg"]) <= args.target_ang
    )


def yang_passed(metrics: dict, args: argparse.Namespace) -> bool:
    return abs(metrics["delta_y"]) <= args.target_dy and abs(metrics["delta_ang_deg"]) <= args.target_ang


def gap(metrics: dict, args: argparse.Namespace) -> float:
    return (
        max(0.0, abs(metrics["delta_x"]) - args.target_dx)
        + max(0.0, abs(metrics["delta_y"]) - args.target_dy)
        + max(0.0, abs(metrics["delta_z"]) - args.target_dz)
        + max(0.0, abs(metrics["delta_ang_deg"]) - args.target_ang)
    )


def yang_score(metrics: dict, args: argparse.Namespace) -> float:
    return max(0.0, abs(metrics["delta_y"]) - args.target_dy) + 25.0 * max(0.0, abs(metrics["delta_ang_deg"]) - args.target_ang)


def write_json(path: pathlib.Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def loop_distance(a: dict, b: dict) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def strip_duplicate_loop_endpoint(points: list[dict]) -> list[dict]:
    if len(points) > 1 and loop_distance(points[0], points[-1]) < 1e-6:
        return points[:-1]
    return points


def sample_closed_by_arc(points: list[dict], count: int) -> tuple[list[dict], float]:
    points = strip_duplicate_loop_endpoint(points)
    if len(points) < 2:
        raise RuntimeError("Polyline is too short for closed-loop sampling")
    closed = points + [points[0]]
    cumulative = [0.0]
    total = 0.0
    for i in range(1, len(closed)):
        total += loop_distance(closed[i - 1], closed[i])
        cumulative.append(total)
    if total <= 1e-9:
        raise RuntimeError("Polyline length is zero")

    out = []
    k = 1
    for i in range(count):
        target = total * i / count
        while k < len(cumulative) - 1 and cumulative[k] < target:
            k += 1
        a = closed[k - 1]
        b = closed[k]
        span = cumulative[k] - cumulative[k - 1]
        t = 0.0 if span <= 1e-12 else (target - cumulative[k - 1]) / span
        out.append(
            {
                "x": a["x"] + t * (b["x"] - a["x"]),
                "y": a["y"] + t * (b["y"] - a["y"]),
                "s": target,
                "seg": a.get("seg") or b.get("seg", ""),
            }
        )
    return out, total


def shifted_cycle(points: list[dict], shift: int) -> list[dict]:
    if not points:
        return []
    shift %= len(points)
    return points[shift:] + points[:shift]


def paired_rmse(a: list[dict], b: list[dict]) -> float:
    return math.sqrt(sum((a[i]["x"] - b[i]["x"]) ** 2 + (a[i]["y"] - b[i]["y"]) ** 2 for i in range(len(a))) / len(a))


def align_closed_loop(source: list[dict], model: list[dict]) -> tuple[list[dict], dict]:
    if len(source) != len(model):
        raise RuntimeError("Alignment inputs must have the same sample count")
    best = None
    for reversed_model in (False, True):
        candidate_model = list(reversed(model)) if reversed_model else model
        for shift in range(len(candidate_model)):
            shifted = shifted_cycle(candidate_model, shift)
            fit = rigid_fit(shifted, source)
            fitted = transform(shifted, fit)
            rmse = paired_rmse(fitted, source)
            if best is None or rmse < best[0]:
                best = (rmse, fitted, fit, shift, reversed_model)
    if best is None:
        raise RuntimeError("Alignment failed to evaluate any loop fit candidates")
    rmse, fitted, fit, shift, reversed_model = best
    return fitted, {
        "paired_rmse_m": rmse,
        "cyclic_shift_samples": shift,
        "reversed": reversed_model,
        "fit_rotation_deg": math.degrees(fit["theta"]),
    }


def write_final_comparison(
    track_xml: pathlib.Path,
    source_polyline: pathlib.Path,
    overlay_path: pathlib.Path,
    report_path: pathlib.Path,
    samples: int,
) -> dict:
    poly_data = json.loads(source_polyline.read_text(encoding="utf-8"))
    src_poly = overlay_to_xy(poly_data.get("polyline", []))
    if len(src_poly) < 3:
        raise RuntimeError("Source polyline too short")

    segs = parse_overlay_track_segments(track_xml.read_text(encoding="utf-8"))
    if not segs:
        raise RuntimeError("No TORCS segments parsed from final XML")

    src_s, src_len = sample_closed_by_arc(src_poly, samples)
    model_s, model_len = sample_closed_by_arc(overlay_torcs_points(segs, step=3.0), samples)
    model_fit, alignment = align_closed_loop(src_s, model_s)

    dists = []
    for p in model_fit:
        dists.append({"s": p.get("s", 0.0), "seg": p.get("seg", ""), "d": nearest_polyline_distance(p, src_poly, closed=True)})
    mean_d = sum(d["d"] for d in dists) / len(dists)
    rmse_d = math.sqrt(sum(d["d"] * d["d"] for d in dists) / len(dists))
    max_d = max(dists, key=lambda item: item["d"])
    top = sorted(dists, key=lambda item: item["d"], reverse=True)[:10]

    write_overlay_svg(overlay_path, src_s, model_fit)
    report = {
        "schema": 1,
        "source_polyline": str(source_polyline),
        "track_xml": str(track_xml),
        "overlay": str(overlay_path),
        "source_length_m": src_len,
        "torcs_length_m": model_len,
        "length_delta_m": model_len - src_len,
        **alignment,
        "mean_deviation_m": mean_d,
        "rmse_deviation_m": rmse_d,
        "max_deviation": max_d,
        "top_deviations": top,
    }
    write_json(report_path, report)
    return report


def rebuild_track_segments_text(text: str, segs: list[dict]) -> str:
    if not segs:
        return text
    first = min(seg["global_start"] for seg in segs)
    last = max(seg["global_end"] for seg in segs)
    from torcs_track_tools.core.track_georeference import invalidate_reference_text

    return invalidate_reference_text(text[:first] + "\n\n".join(seg["raw"] for seg in segs) + text[last:])


def replace_section_name(raw: str, new_name: str) -> str:
    return re.sub(
        r'(<section\s+name=")([^"]+)(">)',
        lambda m: f"{m.group(1)}{new_name}{m.group(3)}",
        raw,
        count=1,
        flags=re.IGNORECASE,
    )


def replace_raw_attnum(raw: str, att_name: str, value: float) -> str:
    patt = re.compile(rf'(<attnum\s+name="{re.escape(att_name)}"[^>]*\bval=")([^"]+)("[^>]*/>)', re.IGNORECASE)
    if not patt.search(raw):
        raise RuntimeError(f"Attribute '{att_name}' not found in segment raw")
    return patt.sub(lambda m: f"{m.group(1)}{value:.8f}{m.group(3)}", raw, count=1)


def straight_raw(name: str, length: float) -> str:
    return (
        f'\t\t\t<section name="{name}">\n'
        f'\t\t\t\t<attstr name="type" val="str" />\n'
        f'\t\t\t\t<attnum name="z end" unit="m" val="0.0" />\n'
        f'\t\t\t\t<attnum name="lg" val="{length:.8f}" unit="m" />\n'
        f'\t\t\t</section>'
    )


def insert_start_straight(text: str, length: float) -> str:
    b0, b1 = locate_track_segments_block(text)
    block = text[b0:b1]
    open_match = re.search(r"<section\s+name=\"Track Segments\">", block, re.IGNORECASE)
    if not open_match:
        raise RuntimeError("Track Segments section not found")
    insert_at = b0 + open_match.end()
    seg_raw = (
        f'\n\t\t\t<section name="Closure Start">\n'
        f'\t\t\t\t<attstr name="type" val="str" />\n'
        f'\t\t\t\t<attnum name="z end" unit="m" val="0.0" />\n'
        f'\t\t\t\t<attnum name="lg" val="{length:.8f}" unit="m" />\n'
        f'\t\t\t</section>\n'
    )
    from torcs_track_tools.core.track_georeference import invalidate_reference_text

    return invalidate_reference_text(text[:insert_at] + seg_raw + text[insert_at:])


def prepare_terminal_x_lever(track_xml: pathlib.Path, args: argparse.Namespace, history: list[dict]) -> tuple[str, str]:
    text = track_xml.read_text(encoding="utf-8")
    segs = parse_top_level_segments(text)
    if not segs:
        raise RuntimeError("No track segments found")

    if args.profile == "post-pit":
        pit_start = next((s for s in segs if s["name"] == "pit_main_b"), None)
        if pit_start is not None and pit_start["index"] != 0:
            segs = segs[pit_start["index"] :] + segs[: pit_start["index"]]
            text = rebuild_track_segments_text(text, segs)
            track_xml.write_text(text, encoding="utf-8")
            history.append({"action": "rotate-start", "segment": "pit_main_b", "profile": "post-pit"})
            segs = parse_top_level_segments(text)
        terminal_name = unique_name({s["name"] for s in segs}, "Closure X Terminal")
        terminal_seg = dict(segs[-1])
        terminal_seg["raw"] = straight_raw(terminal_name, args.insert_straight_length)
        # Keep the X lever at the absolute end; otherwise its length error is
        # carried through the remaining track before the seam is evaluated.
        text = rebuild_track_segments_text(text, segs + [terminal_seg])
        track_xml.write_text(text, encoding="utf-8")
        history.append({"action": "append-terminal-x-lever", "terminal_segment": terminal_name, "after_segment": segs[-1]["name"], "lg": args.insert_straight_length, "profile": "post-pit"})
        return segs[0]["name"], terminal_name

    split_min = max(args.terminal_split_min, args.min_start_straight * 2.0)

    def straight_len(seg: dict) -> float:
        if seg["attrs"].get("type") != "str" or "pit" in seg["name"].lower():
            return 0.0
        return to_float(seg["attrs"].get("lg"), 0.0)

    split_candidates = [s for s in segs if straight_len(s) >= split_min]
    if split_candidates:
        chosen = segs[0] if straight_len(segs[0]) >= split_min else max(split_candidates, key=lambda s: (straight_len(s), -s["index"]))
        if chosen["index"] != 0:
            segs = segs[chosen["index"] :] + segs[: chosen["index"]]
            text = rebuild_track_segments_text(text, segs)
            track_xml.write_text(text, encoding="utf-8")
            history.append({"action": "rotate-start", "segment": chosen["name"]})
            segs = parse_top_level_segments(text)
        first = segs[0]
        length = straight_len(first)
        terminal_name = unique_name({s["name"] for s in segs}, "Closure X Terminal")
        # Split a real straight instead of appending a synthetic stub when possible.
        # Keeping half at the start preserves a usable start line; moving half to
        # the end creates an isolated longitudinal lever for final X correction.
        first_len = length * 0.5
        terminal_len = length - first_len
        start_seg = dict(first)
        start_seg["raw"] = replace_raw_attnum(first["raw"], "lg", first_len)
        terminal_seg = dict(first)
        terminal_seg["raw"] = replace_raw_attnum(replace_section_name(first["raw"], terminal_name), "lg", terminal_len)
        text = rebuild_track_segments_text(text, [start_seg] + segs[1:] + [terminal_seg])
        track_xml.write_text(text, encoding="utf-8")
        history.append(
            {
                "action": "split-terminal-x-lever",
                "start_segment": first["name"],
                "terminal_segment": terminal_name,
                "start_lg": first_len,
                "terminal_lg": terminal_len,
            }
        )
        return first["name"], terminal_name

    usable_straights = [s for s in segs if straight_len(s) >= args.min_start_straight]
    if usable_straights and segs[0]["attrs"].get("type") != "str":
        chosen = max(usable_straights, key=lambda s: (straight_len(s), -s["index"]))
        segs = segs[chosen["index"] :] + segs[: chosen["index"]]
        text = rebuild_track_segments_text(text, segs)
        track_xml.write_text(text, encoding="utf-8")
        history.append({"action": "rotate-start", "segment": chosen["name"]})
        segs = parse_top_level_segments(text)

    terminal_name = unique_name({s["name"] for s in segs}, "Closure X Terminal")
    terminal_seg = dict(segs[-1])
    terminal_seg["raw"] = straight_raw(terminal_name, args.insert_straight_length)
    text = rebuild_track_segments_text(text, segs + [terminal_seg])
    track_xml.write_text(text, encoding="utf-8")
    history.append({"action": "append-terminal-x-lever", "terminal_segment": terminal_name, "lg": args.insert_straight_length})
    return segs[0]["name"], terminal_name


def ensure_starts_on_straight(track_xml: pathlib.Path, args: argparse.Namespace, history: list[dict]) -> str:
    text = track_xml.read_text(encoding="utf-8")
    segs = parse_top_level_segments(text)
    if not segs:
        raise RuntimeError("No track segments found")
    first = segs[0]
    if first["attrs"].get("type") == "str" and to_float(first["attrs"].get("lg"), 0.0) >= args.min_start_straight:
        return first["name"]

    straights = [s for s in segs if s["attrs"].get("type") == "str" and to_float(s["attrs"].get("lg"), 0.0) >= args.min_start_straight]
    if straights:
        simulate_segments(segs)
        chosen = max(straights, key=lambda s: (to_float(s["attrs"].get("lg"), 0.0), -s["index"]))
        idx = chosen["index"]
        rotated = segs[idx:] + segs[:idx]
        track_xml.write_text(rebuild_track_segments_text(text, rotated), encoding="utf-8")
        history.append({"action": "rotate-start", "segment": chosen["name"]})
        return chosen["name"]

    track_xml.write_text(insert_start_straight(text, args.insert_straight_length), encoding="utf-8")
    history.append({"action": "insert-start-straight", "length": args.insert_straight_length})
    return "Closure Start"


def top_angle_turns(segs: list[dict], limit: int = 10) -> list[dict]:
    simulate_segments(segs)
    turns = []
    n = max(1, len(segs))
    for seg in segs:
        attrs = seg["attrs"]
        if attrs.get("type") not in ("lft", "rgt") or "pit" in seg["name"].lower() or "end radius" in attrs:
            continue
        radius = abs(to_float(attrs.get("radius"), 0.0))
        arc = abs(to_float(attrs.get("arc"), 0.0))
        if radius < 2.0 or arc < 0.001:
            continue
        near_start = 1.0 / (1.0 + seg["index"] / n)
        authority = min(arc, 90.0) / math.sqrt(max(radius, 1.0))
        seg["geom_angle_score"] = authority * near_start
        turns.append(seg)
    turns.sort(key=lambda s: s["geom_angle_score"], reverse=True)
    return turns[:limit]


def top_y_straights(segs: list[dict], start_name: str, limit: int = 10) -> list[dict]:
    simulate_segments(segs)
    out = []
    for seg in segs:
        attrs = seg["attrs"]
        if seg["name"] == start_name or attrs.get("type") != "str" or "pit" in seg["name"].lower():
            continue
        length = to_float(attrs.get("lg"), 0.0)
        min_len = 0.01 if seg["name"].startswith("y_comp_straight") else 0.1
        if length < min_len:
            continue
        heading = float(seg.get("sim_h0", 0.0))
        non_parallel = abs(math.sin(heading))
        if non_parallel < 0.05:
            continue
        seg["geom_y_score"] = non_parallel * math.sqrt(max(length, 0.1))
        out.append(seg)
    out.sort(key=lambda s: s["geom_y_score"], reverse=True)
    return out[:limit]


def insert_y_leverage(track_xml: pathlib.Path, start_name: str, args: argparse.Namespace, history: list[dict], straight_lg: float | None = None) -> bool:
    text = track_xml.read_text(encoding="utf-8")
    segs = parse_top_level_segments(text)
    simulate_segments(segs)
    existing = {s["name"] for s in segs}
    candidates = []
    for seg in segs:
        attrs = seg["attrs"]
        if attrs.get("type") not in ("lft", "rgt") or "pit" in seg["name"].lower() or "end radius" in attrs:
            continue
        radius = abs(to_float(attrs.get("radius"), 0.0))
        arc = abs(to_float(attrs.get("arc"), 0.0))
        if radius < 150.0 or arc < 0.5:
            continue
        sign = 1.0 if attrs.get("type") == "lft" else -1.0
        mid_h = float(seg.get("sim_h0", 0.0)) + sign * math.radians(arc) * 0.5
        score = abs(math.sin(mid_h)) * min(radius, 3000.0)
        candidates.append((score, seg))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return False
    name = unique_name(existing, "y_comp_straight")
    length = args.insert_straight_length if straight_lg is None else max(0.01, straight_lg)
    new_text, pre_name = split_turn_with_straight_insert(text, candidates[0][1]["name"], name, length)
    track_xml.write_text(new_text, encoding="utf-8")
    history.append({"action": "insert-y-leverage", "turn": candidates[0][1]["name"], "pre_turn": pre_name, "straight": name, "lg": length})
    return True


def probe_metric_delta(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    base_metrics: dict,
    seg_name: str,
    att_name: str,
    step: float,
) -> list[float] | None:
    try:
        cur = read_attnum_value(base_text, seg_name, att_name)
        track_xml.write_text(replace_attnum_value(base_text, seg_name, att_name, cur + step), encoding="utf-8")
        probe, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
    except RuntimeError:
        track_xml.write_text(base_text, encoding="utf-8")
        return None
    finally:
        track_xml.write_text(base_text, encoding="utf-8")
    return [
        (probe["delta_ang_deg"] - base_metrics["delta_ang_deg"]) / step,
        (probe["delta_y"] - base_metrics["delta_y"]) / step,
        (probe["delta_x"] - base_metrics["delta_x"]) / step,
    ]


def solve_2x2(a: float, b: float, c: float, d: float, rhs0: float, rhs1: float) -> tuple[float, float] | None:
    det = a * d - b * c
    if abs(det) < 1e-12:
        return None
    return ((rhs0 * d - b * rhs1) / det, (a * rhs1 - rhs0 * c) / det)


def solve_3x3(col0: list[float], col1: list[float], col2: list[float], rhs: list[float]) -> tuple[float, float, float] | None:
    rows = [[col0[i], col1[i], col2[i], rhs[i]] for i in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda row: abs(rows[row][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        pivot_value = rows[col][col]
        for j in range(col, 4):
            rows[col][j] /= pivot_value
        for row in range(3):
            if row == col:
                continue
            factor = rows[row][col]
            for j in range(col, 4):
                rows[row][j] -= factor * rows[col][j]
    return rows[0][3], rows[1][3], rows[2][3]


def valid_att_delta(base_text: str, seg_name: str, att_name: str, delta: float, min_straight: float = 0.1) -> bool:
    try:
        cur = read_attnum_value(base_text, seg_name, att_name)
    except RuntimeError:
        return False
    value = cur + delta
    if att_name == "arc":
        return 1e-6 <= value <= 359.999999
    if att_name == "lg":
        if seg_name.startswith("y_comp_straight") or seg_name.startswith("Closure X Terminal"):
            min_straight = min(min_straight, 0.01)
        return value >= min_straight
    return True


def yang_turn_sensitivities(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    metrics: dict,
    angle_candidates: list[dict],
) -> list[tuple[dict, list[float]]]:
    turn_sens = []
    for seg in angle_candidates:
        sens = probe_metric_delta(track_xml, runtime_dir, category, name, base_text, metrics, seg["name"], "arc", 0.001)
        if sens is not None and (abs(sens[0]) > 1e-9 or abs(sens[1]) > 1e-9):
            turn_sens.append((seg, sens))
    return turn_sens


def yang_straight_sensitivities(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    metrics: dict,
    y_candidates: list[dict],
) -> list[tuple[dict, list[float]]]:
    y_sens = []
    for seg in y_candidates:
        sens = probe_metric_delta(track_xml, runtime_dir, category, name, base_text, metrics, seg["name"], "lg", 1.0)
        if sens is not None and abs(sens[1]) > 1e-9:
            y_sens.append((seg, sens))
    return y_sens


def yang_control_candidate(
    base_text: str,
    metrics: dict,
    args: argparse.Namespace,
    turn: dict,
    tv: list[float],
    straight: dict,
    sv: list[float],
) -> dict | None:
    sol = solve_2x2(tv[0], sv[0], tv[1], sv[1], -metrics["delta_ang_deg"], -metrics["delta_y"])
    if sol is None:
        return None
    arc_delta, straight_delta = sol
    if abs(arc_delta) > args.max_control_delta or abs(straight_delta) > args.max_control_delta:
        return None
    if not valid_att_delta(base_text, turn["name"], "arc", arc_delta):
        return None
    if not valid_att_delta(base_text, straight["name"], "lg", straight_delta, args.min_start_straight):
        return None
    det = abs(tv[0] * sv[1] - sv[0] * tv[1])
    normalized_delta = abs(arc_delta) / args.max_control_delta + abs(straight_delta) / args.max_control_delta
    score = (normalized_delta, -det, -turn.get("geom_angle_score", 0.0), -straight.get("geom_y_score", 0.0))
    return {
        "turn": turn["name"],
        "straight": straight["name"],
        "turn_sens": tv,
        "straight_sens": sv,
        "arc_delta": arc_delta,
        "straight_delta": straight_delta,
        "score": score,
    }


def choose_yang_controls(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    start_name: str,
    metrics: dict,
    args: argparse.Namespace,
) -> dict | None:
    base_text = track_xml.read_text(encoding="utf-8")
    segs = parse_top_level_segments(base_text)
    angle_candidates = top_angle_turns(segs)
    y_candidates = top_y_straights(segs, start_name)
    if not y_candidates:
        return None

    turn_sens = yang_turn_sensitivities(track_xml, runtime_dir, category, name, base_text, metrics, angle_candidates)
    y_sens = yang_straight_sensitivities(track_xml, runtime_dir, category, name, base_text, metrics, y_candidates)

    best = None
    for turn, tv in turn_sens:
        for straight, sv in y_sens:
            item = yang_control_candidate(base_text, metrics, args, turn, tv, straight, sv)
            if item is not None and (best is None or item["score"] < best["score"]):
                best = item
    return best


def apply_deltas(text: str, deltas: list[tuple[str, str, float]]) -> str:
    out = text
    for seg_name, att_name, delta in deltas:
        cur = read_attnum_value(out, seg_name, att_name)
        out = replace_attnum_value(out, seg_name, att_name, cur + delta)
    return out


def append_solve_yang_history(history: list[dict], iter_id: int, scale: float, controls: dict, scaled: list[tuple[str, str, float]], metrics: dict) -> None:
    history.append(
        {
            "phase": "solve-yang",
            "iter": iter_id,
            "scale": scale,
            "turn": controls["turn"],
            "y_straight": controls["straight"],
            "deltas": {f"{seg}.{att}": delta for seg, att, delta in scaled},
            "metrics": metrics,
        }
    )


def try_solve_yang_scales(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    base_score: float,
    metrics: dict,
    args: argparse.Namespace,
    history: list[dict],
    iter_id: int,
    controls: dict,
) -> tuple[dict, bool]:
    deltas = [(controls["turn"], "arc", controls["arc_delta"]), (controls["straight"], "lg", controls["straight_delta"])]
    for scale in (1.0, 0.5, 0.25, 0.125, 0.0625):
        scaled = [(seg, att, delta * scale) for seg, att, delta in deltas]
        if not all(valid_att_delta(base_text, seg, att, delta, args.min_start_straight) for seg, att, delta in scaled):
            continue
        cand_text = apply_deltas(base_text, scaled)
        track_xml.write_text(cand_text, encoding="utf-8")
        try:
            cand_metrics, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
            if has_intersection(track_xml):
                continue
        except RuntimeError:
            continue
        cand_score = yang_score(cand_metrics, args)
        if cand_score + 1e-12 < base_score or yang_passed(cand_metrics, args):
            append_solve_yang_history(history, iter_id, scale, controls, scaled, cand_metrics)
            return cand_metrics, True
    return metrics, False


def polish_yang_fallback(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    start_name: str,
    metrics: dict,
    args: argparse.Namespace,
    history: list[dict],
    iter_id: int,
) -> tuple[dict, bool]:
    return polish_yang_axis(track_xml, runtime_dir, category, name, start_name, metrics, args, history, iter_id)


def solve_yang(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    start_name: str,
    metrics: dict,
    args: argparse.Namespace,
    history: list[dict],
) -> tuple[dict, bool]:
    changed_any = False
    for iter_id in range(1, args.max_yang_iters + 1):
        if yang_passed(metrics, args):
            return metrics, changed_any
        base_text = track_xml.read_text(encoding="utf-8")
        base_score = yang_score(metrics, args)
        controls = choose_yang_controls(track_xml, runtime_dir, category, name, start_name, metrics, args)
        if controls is None:
            polished, polished_changed = polish_yang_fallback(track_xml, runtime_dir, category, name, start_name, metrics, args, history, iter_id)
            if polished_changed:
                metrics = polished
                changed_any = True
                continue
            return metrics, changed_any
        metrics, accepted = try_solve_yang_scales(track_xml, runtime_dir, category, name, base_text, base_score, metrics, args, history, iter_id, controls)
        if accepted:
            changed_any = True
        if not accepted:
            track_xml.write_text(base_text, encoding="utf-8")
            polished, polished_changed = polish_yang_fallback(track_xml, runtime_dir, category, name, start_name, metrics, args, history, iter_id)
            if polished_changed:
                metrics = polished
                changed_any = True
                continue
            return metrics, changed_any
    return metrics, changed_any


def polish_yang_work(segs: list[dict], start_name: str, metrics: dict, args: argparse.Namespace) -> list[tuple[str, str, str, int, float]]:
    work: list[tuple[str, str, str, int, float]] = []
    if abs(metrics["delta_y"]) > args.target_dy:
        for seg in top_y_straights(segs, start_name):
            work.append(("y", seg["name"], "lg", 1, 1.0))
    if abs(metrics["delta_ang_deg"]) > args.target_ang:
        for seg in top_angle_turns(segs):
            work.append(("angle", seg["name"], "arc", 0, 0.001))
    return work


def evaluate_polish_yang_candidate(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    args: argparse.Namespace,
    seg_name: str,
    att_name: str,
    scaled_delta: float,
) -> tuple[str, dict, float] | None:
    cand_text = apply_deltas(base_text, [(seg_name, att_name, scaled_delta)])
    track_xml.write_text(cand_text, encoding="utf-8")
    try:
        cand_metrics, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
        if has_intersection(track_xml):
            return None
    except RuntimeError:
        return None
    return cand_text, cand_metrics, yang_score(cand_metrics, args)


def polish_yang_delta(metrics: dict, phase: str, sens: list[float], sens_idx: int) -> float:
    target_value = metrics["delta_y"] if phase == "y" else metrics["delta_ang_deg"]
    return -target_value / sens[sens_idx]


def polish_yang_action(phase: str, iter_id: int, seg_name: str, att_name: str, scaled_delta: float, cand_metrics: dict) -> dict:
    return {"phase": f"polish-{phase}", "iter": iter_id, "segment": seg_name, "attribute": att_name, "delta": scaled_delta, "metrics": cand_metrics}


def try_polish_yang_work_item(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    metrics: dict,
    args: argparse.Namespace,
    iter_id: int,
    work_item: tuple[str, str, str, int, float],
    best_score: float,
) -> tuple[str | None, dict | None, float, dict | None]:
    phase, seg_name, att_name, sens_idx, step = work_item
    sens = probe_metric_delta(track_xml, runtime_dir, category, name, base_text, metrics, seg_name, att_name, step)
    if sens is None or abs(sens[sens_idx]) < 1e-12:
        return None, None, best_score, None
    delta = polish_yang_delta(metrics, phase, sens, sens_idx)
    if abs(delta) > args.max_control_delta or not valid_att_delta(base_text, seg_name, att_name, delta, args.min_start_straight):
        return None, None, best_score, None
    best_text = None
    best_metrics = None
    best_action = None
    for scale in (1.0, 0.5, 0.25, 0.125):
        scaled_delta = delta * scale
        if not valid_att_delta(base_text, seg_name, att_name, scaled_delta, args.min_start_straight):
            continue
        result = evaluate_polish_yang_candidate(track_xml, runtime_dir, category, name, base_text, args, seg_name, att_name, scaled_delta)
        if result is None:
            continue
        cand_text, cand_metrics, cand_score = result
        if cand_score + 1e-12 < best_score or yang_passed(cand_metrics, args):
            best_text = cand_text
            best_metrics = cand_metrics
            best_score = cand_score
            best_action = polish_yang_action(phase, iter_id, seg_name, att_name, scaled_delta, cand_metrics)
            if yang_passed(cand_metrics, args):
                break
    return best_text, best_metrics, best_score, best_action


def polish_yang_axis(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    start_name: str,
    metrics: dict,
    args: argparse.Namespace,
    history: list[dict],
    iter_id: int,
) -> tuple[dict, bool]:
    base_text = track_xml.read_text(encoding="utf-8")
    base_score = yang_score(metrics, args)
    segs = parse_top_level_segments(base_text)

    best_text = base_text
    best_metrics = metrics
    best_score = base_score
    best_action = None
    for work_item in polish_yang_work(segs, start_name, metrics, args):
        cand_text, cand_metrics, best_score, cand_action = try_polish_yang_work_item(
            track_xml, runtime_dir, category, name, base_text, metrics, args, iter_id, work_item, best_score
        )
        if cand_action is not None:
            best_text = cand_text
            best_metrics = cand_metrics
            best_action = cand_action
        if yang_passed(best_metrics, args):
            break

    track_xml.write_text(best_text, encoding="utf-8")
    if best_action is None:
        return metrics, False
    history.append(best_action)
    return best_metrics, True


def terminal_x_candidates(base_text: str, terminal_name: str, delta: float, args: argparse.Namespace) -> list[float]:
    offsets = (0.0, -0.0005, 0.0005, -0.001, 0.001, -0.002, 0.002, -0.004, 0.004, -0.008, 0.008)
    candidates: list[float] = []
    seen: set[float] = set()
    for offset in offsets:
        candidate = delta + offset
        key = round(candidate, 9)
        if key in seen:
            continue
        seen.add(key)
        if valid_att_delta(base_text, terminal_name, "lg", candidate, args.min_start_straight):
            candidates.append(candidate)
    return candidates


def evaluate_terminal_x_candidate(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    terminal_name: str,
    candidate: float,
    args: argparse.Namespace,
) -> tuple[str, dict, float] | None:
    trial_text = apply_deltas(base_text, [(terminal_name, "lg", candidate)])
    track_xml.write_text(trial_text, encoding="utf-8")
    try:
        trial_metrics, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
    except RuntimeError:
        return None
    return trial_text, trial_metrics, gap(trial_metrics, args)


def adjust_terminal_x(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    terminal_name: str,
    metrics: dict,
    args: argparse.Namespace,
    history: list[dict],
) -> tuple[dict, bool, bool]:
    if abs(metrics["delta_x"]) <= args.target_dx:
        return metrics, False, True
    if not yang_passed(metrics, args):
        return metrics, False, False

    base_text = track_xml.read_text(encoding="utf-8")
    # Once Y and heading are inside tolerance, the terminal straight length is
    # the safest X lever. Earlier X edits couple back into candidate rotation and
    # lateral/angle control; the end-of-loop lever keeps the solved start frame
    # stable and made the geometric closer reliable across the benchmark set.
    sens = probe_metric_delta(track_xml, runtime_dir, category, name, base_text, metrics, terminal_name, "lg", 1.0)
    if sens is None or abs(sens[2]) < 1e-9:
        return metrics, False, False

    delta = -metrics["delta_x"] / sens[2]
    candidates = terminal_x_candidates(base_text, terminal_name, delta, args)

    best_text = base_text
    best_metrics = metrics
    best_gap = gap(metrics, args)
    best_delta = None
    log(f"terminal x: {terminal_name} sensitivity={sens[2]:.6f} delta={delta:.8f} candidates={len(candidates)}")
    for candidate in candidates:
        result = evaluate_terminal_x_candidate(track_xml, runtime_dir, category, name, base_text, terminal_name, candidate, args)
        if result is None:
            continue
        trial_text, trial_metrics, trial_gap = result
        if trial_gap + 1e-12 < best_gap or passed(trial_metrics, args):
            best_text = trial_text
            best_metrics = trial_metrics
            best_gap = trial_gap
            best_delta = candidate
            if passed(trial_metrics, args):
                break

    track_xml.write_text(best_text, encoding="utf-8")
    if best_delta is None:
        return metrics, False, False
    history.append({"phase": "solve-x-terminal", "segment": terminal_name, "delta_lg": best_delta, "metrics": best_metrics})
    return best_metrics, True, passed(best_metrics, args)


def terminal_delta_candidates(terminal_lg: float, args: argparse.Namespace) -> list[float]:
    min_terminal_delta = 0.01 - terminal_lg
    max_terminal_delta = max(0.15, args.insert_straight_length)
    terminal_deltas = []
    step = 0.005
    count = int(round((max_terminal_delta - min_terminal_delta) / step))
    for i in range(count + 1):
        terminal_deltas.append(min_terminal_delta + i * step)
    if min_terminal_delta <= 0.0 <= max_terminal_delta:
        terminal_deltas.append(0.0)
    # Try the least-distorting terminal changes first. The post-pit solver can
    # otherwise spend thousands of trackgen calls walking up from the minimum.
    ordered = sorted(set(terminal_deltas), key=lambda delta: (abs(delta), delta))
    limit = max(0, args.post_pit_terminal_candidates)
    return ordered[:limit] if limit else ordered


def usable_post_pit_turn_sensitivities(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    metrics: dict,
    angle_candidates: list[dict],
) -> list[tuple[dict, list[float]]]:
    turn_sens = []
    for seg in angle_candidates:
        sens = probe_metric_delta(track_xml, runtime_dir, category, name, base_text, metrics, seg["name"], "arc", 0.001)
        if sens is not None and (abs(sens[0]) > 1e-9 or abs(sens[1]) > 1e-9 or abs(sens[2]) > 1e-9):
            turn_sens.append((seg, sens))
    return turn_sens


def usable_post_pit_straight_sensitivities(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    metrics: dict,
    straight_candidates: list[dict],
) -> list[tuple[dict, list[float]]]:
    straight_sens = []
    for seg in straight_candidates:
        sens = probe_metric_delta(track_xml, runtime_dir, category, name, base_text, metrics, seg["name"], "lg", 1.0)
        if sens is not None and (abs(sens[1]) > 1e-9 or abs(sens[2]) > 1e-9):
            straight_sens.append((seg, sens))
    return straight_sens


def post_pit_deltas_are_valid(base_text: str, deltas: list[tuple[str, str, float]], args: argparse.Namespace) -> bool:
    arc_delta = deltas[0][2]
    straight_delta1 = deltas[1][2]
    straight_delta2 = deltas[2][2]
    if abs(arc_delta) > args.max_control_delta:
        return False
    if abs(straight_delta1) > args.max_control_delta or abs(straight_delta2) > args.max_control_delta:
        return False
    return all(valid_att_delta(base_text, seg, att, delta, args.min_start_straight) for seg, att, delta in deltas)


def post_pit_candidate_delta_sets(
    base_text: str,
    terminal_name: str,
    metrics: dict,
    args: argparse.Namespace,
    terminal_sens: list[float],
    turn_sens: list[tuple[dict, list[float]]],
    straight_sens: list[tuple[dict, list[float]]],
    terminal_delta: float,
) -> list[tuple[dict, dict, dict, list[tuple[str, str, float]]]]:
    residual = [
        -metrics["delta_ang_deg"] - terminal_sens[0] * terminal_delta,
        -metrics["delta_y"] - terminal_sens[1] * terminal_delta,
        -metrics["delta_x"] - terminal_sens[2] * terminal_delta,
    ]
    candidates = []
    for turn, turn_vec in turn_sens:
        for (straight1, straight_vec1), (straight2, straight_vec2) in itertools.combinations(straight_sens, 2):
            sol = solve_3x3(turn_vec, straight_vec1, straight_vec2, residual)
            if sol is None:
                continue
            arc_delta, straight_delta1, straight_delta2 = sol
            deltas = [
                (turn["name"], "arc", arc_delta),
                (straight1["name"], "lg", straight_delta1),
                (straight2["name"], "lg", straight_delta2),
                (terminal_name, "lg", terminal_delta),
            ]
            if post_pit_deltas_are_valid(base_text, deltas, args):
                candidates.append((turn, straight1, straight2, deltas))
    return candidates


def evaluate_post_pit_candidate(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    metrics: dict,
    args: argparse.Namespace,
    deltas: list[tuple[str, str, float]],
    best_gap: float,
) -> tuple[str, dict, float] | None:
    cand_text = apply_deltas(base_text, deltas)
    track_xml.write_text(cand_text, encoding="utf-8")
    try:
        cand_metrics, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
    except RuntimeError:
        return None
    cand_gap = gap(cand_metrics, args)
    if cand_metrics["pits"] != metrics["pits"]:
        return None
    if cand_gap + 1e-12 >= best_gap and not passed(cand_metrics, args):
        return None
    if has_intersection(track_xml):
        return None
    return cand_text, cand_metrics, cand_gap


def post_pit_action(
    turn: dict,
    straight1: dict,
    straight2: dict,
    terminal_name: str,
    deltas: list[tuple[str, str, float]],
    metrics: dict,
    attempts: int,
) -> dict:
    return {
        "phase": "solve-post-pit-terminal",
        "turn": turn["name"],
        "straights": [straight1["name"], straight2["name"]],
        "terminal": terminal_name,
        "deltas": {f"{seg}.{att}": delta for seg, att, delta in deltas},
        "metrics": metrics,
        "attempts": attempts,
    }


def find_best_post_pit_candidate(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    terminal_name: str,
    terminal_lg: float,
    metrics: dict,
    args: argparse.Namespace,
    terminal_sens: list[float],
    turn_sens: list[tuple[dict, list[float]]],
    straight_sens: list[tuple[dict, list[float]]],
) -> tuple[str, dict, float, dict | None, bool]:
    best_text = base_text
    best_metrics = metrics
    best_gap = gap(metrics, args)
    best_action = None
    attempts = 0
    for terminal_delta in terminal_delta_candidates(terminal_lg, args):
        for turn, straight1, straight2, deltas in post_pit_candidate_delta_sets(base_text, terminal_name, metrics, args, terminal_sens, turn_sens, straight_sens, terminal_delta):
            attempts += 1
            candidate_result = evaluate_post_pit_candidate(track_xml, runtime_dir, category, name, base_text, metrics, args, deltas, best_gap)
            if candidate_result is None:
                continue
            best_text, best_metrics, best_gap = candidate_result
            best_action = post_pit_action(turn, straight1, straight2, terminal_name, deltas, best_metrics, attempts)
            if passed(best_metrics, args):
                return best_text, best_metrics, best_gap, best_action, True
    return best_text, best_metrics, best_gap, best_action, False


def handle_missing_y_straights(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    start_name: str,
    terminal_name: str,
    metrics: dict,
    history: list[dict],
    cycle: int,
) -> tuple[dict, str]:
    if abs(metrics["delta_y"]) <= args.target_dy:
        polished, changed = polish_yang_axis(track_xml, runtime_dir, args.category, args.name, start_name, metrics, args, history, cycle)
        if changed:
            metrics = polished
            if yang_passed(metrics, args):
                metrics, changed, x_ok = adjust_terminal_x(track_xml, runtime_dir, args.category, args.name, terminal_name, metrics, args, history)
                if passed(metrics, args) or not changed or not x_ok:
                    return metrics, "break"
                return metrics, "continue"
    leverage_len = min(args.insert_straight_length, max(0.01, abs(metrics["delta_y"])))
    if not insert_y_leverage(track_xml, start_name, args, history, leverage_len):
        return metrics, "break"
    metrics, _ = run_trackgen_z(runtime_dir, args.category, args.name, track_xml)
    return metrics, "proceed"


def finish_yang_cycle(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    terminal_name: str,
    metrics: dict,
    history: list[dict],
) -> tuple[dict, bool, bool]:
    if not yang_passed(metrics, args):
        return metrics, False, True
    metrics, changed, x_ok = adjust_terminal_x(track_xml, runtime_dir, args.category, args.name, terminal_name, metrics, args, history)
    ok = passed(metrics, args)
    if ok:
        return metrics, True, True
    if not changed or not yang_passed(metrics, args) or not x_ok:
        return metrics, ok, True
    return metrics, ok, False


def solve_geometric_cycles(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    start_name: str,
    terminal_name: str,
    metrics: dict,
    history: list[dict],
) -> tuple[dict, bool]:
    ok = passed(metrics, args)
    if args.profile == "post-pit" and not ok:
        metrics, _, ok = solve_post_pit_terminal(track_xml, runtime_dir, args.category, args.name, start_name, terminal_name, metrics, args, history)
    for cycle in range(1, args.max_cycles + 1):
        if ok:
            break
        segs = parse_top_level_segments(track_xml.read_text(encoding="utf-8"))
        if not top_y_straights(segs, start_name):
            metrics, action = handle_missing_y_straights(track_xml, runtime_dir, args, start_name, terminal_name, metrics, history, cycle)
            if action == "break":
                break
            if action == "continue":
                continue

        metrics, _ = solve_yang(track_xml, runtime_dir, args.category, args.name, start_name, metrics, args, history)
        metrics, ok, stop = finish_yang_cycle(track_xml, runtime_dir, args, terminal_name, metrics, history)
        if stop:
            break
    return metrics, ok


def solve_post_pit_terminal(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    start_name: str,
    terminal_name: str,
    metrics: dict,
    args: argparse.Namespace,
    history: list[dict],
) -> tuple[dict, bool, bool]:
    base_text = track_xml.read_text(encoding="utf-8")
    segs = parse_top_level_segments(base_text)
    angle_candidates = top_angle_turns(segs, max(1, args.post_pit_turn_candidates))
    straight_candidates = [
        s
        for s in top_y_straights(segs, start_name, max(2, args.post_pit_straight_candidates))
        if s["name"] != terminal_name
    ]
    if len(angle_candidates) < 1 or len(straight_candidates) < 2:
        return metrics, False, False

    try:
        terminal_lg = read_attnum_value(base_text, terminal_name, "lg")
    except RuntimeError:
        return metrics, False, False

    terminal_sens = probe_metric_delta(track_xml, runtime_dir, category, name, base_text, metrics, terminal_name, "lg", 1.0)
    if terminal_sens is None or abs(terminal_sens[2]) < 1e-9:
        return metrics, False, False

    turn_sens = usable_post_pit_turn_sensitivities(track_xml, runtime_dir, category, name, base_text, metrics, angle_candidates)
    straight_sens = usable_post_pit_straight_sensitivities(track_xml, runtime_dir, category, name, base_text, metrics, straight_candidates)

    if not turn_sens or len(straight_sens) < 2:
        return metrics, False, False

    best_text, best_metrics, _best_gap, best_action, best_passed = find_best_post_pit_candidate(
        track_xml,
        runtime_dir,
        category,
        name,
        base_text,
        terminal_name,
        terminal_lg,
        metrics,
        args,
        terminal_sens,
        turn_sens,
        straight_sens,
    )
    if best_passed:
        track_xml.write_text(best_text, encoding="utf-8")
        history.append(best_action)
        return best_metrics, True, True

    track_xml.write_text(best_text, encoding="utf-8")
    if best_action is None:
        return metrics, False, False
    history.append(best_action)
    return best_metrics, True, passed(best_metrics, args)


def main() -> int:
    global TRACKGEN_TIMEOUT_S, VERBOSE
    args = parse_args()
    TRACKGEN_TIMEOUT_S = args.trackgen_timeout
    VERBOSE = args.verbose
    track_xml = pathlib.Path(args.track_xml)
    runtime_dir = pathlib.Path(args.runtime_dir)
    report_path = pathlib.Path(args.report)
    history: list[dict] = []
    start_time = time.perf_counter()
    original_xml = track_xml.read_text(encoding="utf-8-sig")

    try:
        start_name, terminal_name = prepare_terminal_x_lever(track_xml, args, history)
        metrics, _ = run_trackgen_z(runtime_dir, args.category, args.name, track_xml)
        history.append({"phase": "baseline", "start": start_name, "terminal": terminal_name, "metrics": metrics})

        metrics, ok = solve_geometric_cycles(track_xml, runtime_dir, args, start_name, terminal_name, metrics, history)

        comparison = None
        if args.source_polyline:
            source_polyline = pathlib.Path(args.source_polyline)
            from torcs_track_tools.core.track_georeference import refresh_reference

            refresh_reference(track_xml, source_polyline, previous_xml=original_xml)
            comparison_svg = pathlib.Path(args.comparison_svg) if args.comparison_svg else report_path.with_name(report_path.stem + "-overlay.svg")
            comparison_report = pathlib.Path(args.comparison_report) if args.comparison_report else report_path.with_name(report_path.stem + "-overlay.json")
            comparison = write_final_comparison(track_xml, source_polyline, comparison_svg, comparison_report, args.comparison_samples)
            print(f"Comparison overlay written: {comparison_svg}")

        report = {
            "schema": 1,
            "solver": "geometric-v1",
            "ok": ok,
            "elapsed_seconds": time.perf_counter() - start_time,
            "targets": {
                "delta_x": args.target_dx,
                "delta_y": args.target_dy,
                "delta_z": args.target_dz,
                "delta_ang_deg": args.target_ang,
            },
            "final_metrics": metrics,
            "gap": gap(metrics, args),
            "stats": runtime_stats(),
            "history": history,
        }
        if comparison is not None:
            report["comparison"] = {
                "overlay": comparison["overlay"],
                "report": str(comparison_report),
                "mean_deviation_m": comparison["mean_deviation_m"],
                "rmse_deviation_m": comparison["rmse_deviation_m"],
                "max_deviation_m": comparison["max_deviation"]["d"],
                "paired_alignment_rmse_m": comparison["paired_rmse_m"],
                "cyclic_shift_samples": comparison["cyclic_shift_samples"],
                "reversed": comparison["reversed"],
            }
        write_json(report_path, report)
        print(f"Wrote report: {report_path}")
        if ok:
            print("Closure targets satisfied.")
            return 0
        print("Closure targets not met.")
        return 1
    except Exception as exc:
        report = {
            "schema": 1,
            "solver": "geometric-v1",
            "ok": False,
            "error": str(exc),
            "elapsed_seconds": time.perf_counter() - start_time,
            "stats": runtime_stats(),
            "history": history,
        }
        write_json(report_path, report)
        print(f"Wrote report: {report_path}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
