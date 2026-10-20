#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : close_loop.py
#     created              : 19 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Close TORCS track loops using a deterministic phased workflow.

High-level idea (mirrors manual closure practice):
1) Fix heading closure first (`Delta Ang`) using a late control turn arc.
2) Fix lateral closure (`Delta Y`) with a diagonal straight; if needed use turn radius.
3) Fix longitudinal closure (`Delta X`) with a dedicated straight.
4) Repeat A->B->C while keeping earlier solved dimensions locked.

The solver stores selected controls in a config file so subsequent runs are stable
and reproducible for the same track.

The default Y gate is 0.001 m because trackgen often quantizes the final lateral
residual to +/-0.000977 m.  Delta X and Delta Ang remain tighter closure gates.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import pathlib
import re
import sys
import time
from contextlib import contextmanager

from torcs_track_tools.core.defaults import DEFAULT_TARGET_ANG_DEG, DEFAULT_TARGET_DX_M, DEFAULT_TARGET_DY_M, DEFAULT_TARGET_DZ_M
from torcs_track_tools.core.trackgen import TrackgenRunner, TrackgenStats

OPEN_SECTION_RE = re.compile(r"<section\s+name=\"([^\"]+)\">", re.IGNORECASE)
ATT_RE = re.compile(r"<att(?:num|str)\s+name=\"([^\"]+)\"[^>]*\bval=\"([^\"]*)\"[^>]*/>", re.IGNORECASE)
TRACKGEN_CALLS = 0
TRACKGEN_SECONDS = 0.0
TRACKGEN_CACHE_HITS = 0
TRACKGEN_CACHE: dict[tuple[str, str, str], tuple[dict, str]] = {}
TRACKGEN_STATS = TrackgenStats()
TRACKGEN_PHASE = "unknown"
TRACKGEN_PHASE_STATS: dict[str, dict[str, float | int]] = {}
PROJECTED_SLOPES: dict[tuple[str, str, str, str], float] = {}
SELF_INTERSECTION_CHECKS = 0
SELF_INTERSECTION_SECONDS = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Close TORCS loop by tuning locked closure control segments",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Recommended workflow:\n"
            "  1) Select and lock controls first (one-time per track baseline):\n"
            "     torcs-close-loop --track-xml <track.xml> --runtime-dir <runtime> --category <cat> --name <track> --config <closure-config.json> --select-only\n"
            "\n"
            "  2) Run closure optimization with locked controls:\n"
            "     torcs-close-loop --track-xml <track.xml> --runtime-dir <runtime> --category <cat> --name <track> --config <closure-config.json> --report <closure-report.json>\n"
            "\n"
            "  3) If the baseline changed significantly, reselect controls:\n"
            "     torcs-close-loop ... --select-only --force-reselect"
        ),
    )
    parser.add_argument("--profile", choices=["mainline", "post-pit"], default="mainline", help="Closure preset; post-pit enables Pit10-friendly defaults")
    parser.add_argument("--track-xml", required=True, help="Track XML file path")
    parser.add_argument("--runtime-dir", required=True, help="TORCS runtime directory containing trackgen.exe")
    parser.add_argument("--category", required=True, help="Track category for trackgen")
    parser.add_argument("--name", required=True, help="Track short name for trackgen")
    parser.add_argument("--config", required=True, help="Closure config JSON path")
    parser.add_argument("--report", default="", help="Optional report JSON path")
    parser.add_argument("--select-only", action="store_true", help="Only select and write locked control segments")
    parser.add_argument("--baseline-only", action="store_true", help="Only run trackgen -z and write baseline readiness report")
    parser.add_argument("--force-reselect", action="store_true", help="Reselect controls even if config exists")
    parser.add_argument("--max-iters", type=int, default=80, help=argparse.SUPPRESS)
    parser.add_argument("--straight-step", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--arc-step", type=float, default=0.1, help=argparse.SUPPRESS)
    parser.add_argument("--min-straight-step", type=float, default=1e-5, help=argparse.SUPPRESS)
    parser.add_argument("--min-arc-step", type=float, default=1e-6, help=argparse.SUPPRESS)
    parser.add_argument("--target-dx", type=float, default=DEFAULT_TARGET_DX_M, help=argparse.SUPPRESS)
    parser.add_argument("--target-dy", type=float, default=DEFAULT_TARGET_DY_M, help="Handoff threshold for |Delta Y|; default matches trackgen's sub-millimeter quantum")
    parser.add_argument("--target-dz", type=float, default=DEFAULT_TARGET_DZ_M, help=argparse.SUPPRESS)
    parser.add_argument("--target-ang", type=float, default=DEFAULT_TARGET_ANG_DEG, help=argparse.SUPPRESS)
    parser.add_argument("--plateau-iters", type=int, default=18, help=argparse.SUPPRESS)
    parser.add_argument("--phase-iters", type=int, default=12, help=argparse.SUPPRESS)
    parser.add_argument("--max-baseline-dx", type=float, default=20.0, help=argparse.SUPPRESS)
    parser.add_argument("--max-baseline-dy", type=float, default=20.0, help=argparse.SUPPRESS)
    parser.add_argument("--max-baseline-ang", type=float, default=2.0, help=argparse.SUPPRESS)
    parser.add_argument(
        "--allow-x-structure-fallback",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--runtime-x-reselect",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--linear-polish",
        action="store_true",
        help="Enable three-control linear correction before broad closure loop",
    )
    parser.add_argument("--linear-polish-rounds", type=int, default=3, help=argparse.SUPPRESS)
    parser.add_argument("--linear-polish-candidates", type=int, default=1000, help=argparse.SUPPRESS)
    parser.add_argument("--linear-max-arc-delta", type=float, default=0.01, help=argparse.SUPPRESS)
    parser.add_argument("--linear-max-straight-delta", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    apply_profile_defaults(args)
    return args


def cli_arg_present(name: str) -> bool:
    return any(arg == name or arg.startswith(name + "=") for arg in sys.argv[1:])


def apply_profile_defaults(args: argparse.Namespace) -> None:
    if args.profile != "post-pit":
        return
    if not cli_arg_present("--linear-polish"):
        args.linear_polish = True
    if not cli_arg_present("--target-dy"):
        args.target_dy = DEFAULT_TARGET_DY_M


def norm_angle(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def find_matching_section_end(text: str, open_start: int) -> int:
    open_match = OPEN_SECTION_RE.match(text, open_start)
    if not open_match:
        raise RuntimeError("Section open tag expected at index")
    i = open_match.end()
    depth = 1
    token_re = re.compile(r"</section>|<section\s+name=\"[^\"]+\">", re.IGNORECASE)
    while True:
        m = token_re.search(text, i)
        if not m:
            raise RuntimeError("Unbalanced section tags")
        token = m.group(0)
        if token.lower().startswith("<section"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.end()
        i = m.end()


def locate_track_segments_block(text: str) -> tuple[int, int]:
    m = re.search(r"<section\s+name=\"Track Segments\">", text, re.IGNORECASE)
    if not m:
        raise RuntimeError("Track Segments section not found")
    start = m.start()
    end = find_matching_section_end(text, start)
    return start, end


def parse_top_level_segments(text: str) -> list[dict]:
    b0, b1 = locate_track_segments_block(text)
    block = text[b0:b1]
    open_match = OPEN_SECTION_RE.search(block)
    if not open_match:
        return []
    inner_start = open_match.end()
    i = inner_start
    depth = 0
    segs: list[dict] = []
    token_re = re.compile(r"</section>|<section\s+name=\"([^\"]+)\">", re.IGNORECASE)
    while True:
        m = token_re.search(block, i)
        if not m:
            break
        token = m.group(0)
        if token.lower().startswith("<section"):
            if depth == 0:
                seg_start = m.start()
                seg_end = find_matching_section_end(block, seg_start)
                seg_text = block[seg_start:seg_end]
                name = m.group(1)
                attrs = {k: v for k, v in ATT_RE.findall(seg_text)}
                segs.append(
                    {
                        "name": name,
                        "attrs": attrs,
                        "raw": seg_text,
                        "global_start": b0 + seg_start,
                        "global_end": b0 + seg_end,
                    }
                )
                i = seg_end
                continue
            depth += 1
        else:
            if depth > 0:
                depth -= 1
            else:
                break
        i = m.end()
    for idx, seg in enumerate(segs):
        seg["index"] = idx
    return segs


def track_segments_fingerprint(segs: list[dict]) -> str:
    payload = [
        {
            "name": seg["name"],
            "attrs": sorted(seg["attrs"].items()),
        }
        for seg in segs
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def phase_stats(name: str) -> dict[str, float | int]:
    if name not in TRACKGEN_PHASE_STATS:
        TRACKGEN_PHASE_STATS[name] = {"calls": 0, "seconds": 0.0, "cache_hits": 0}
    return TRACKGEN_PHASE_STATS[name]


@contextmanager
def trackgen_phase(name: str):
    global TRACKGEN_PHASE
    old_phase = TRACKGEN_PHASE
    TRACKGEN_PHASE = name
    try:
        yield
    finally:
        TRACKGEN_PHASE = old_phase


def config_matches_track(config: dict, args: argparse.Namespace, track_xml: pathlib.Path, segs: list[dict]) -> bool:
    if config.get("schema") != 1:
        return False
    if config.get("category") != args.category or config.get("name") != args.name:
        return False
    if config.get("track_xml") != str(track_xml):
        return False
    if config.get("track_segments_sha256") != track_segments_fingerprint(segs):
        return False
    controls = config.get("controls", {})
    if not isinstance(controls, dict):
        return False
    names = {seg["name"] for seg in segs}
    for key in ("primary_straight", "primary_turn"):
        if controls.get(key) not in names:
            return False
    for key in ("backup_straight", "x_straight", "y_turn"):
        value = controls.get(key, "")
        if value and value not in names:
            return False
    return True


def to_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def unique_name(existing: set[str], base: str) -> str:
    if base not in existing:
        return base
    i = 2
    while True:
        cand = f"{base}-{i}"
        if cand not in existing:
            return cand
        i += 1


def simulate_segments(segs: list[dict]) -> None:
    x = 0.0
    y = 0.0
    h = 0.0
    for seg in segs:
        attrs = seg["attrs"]
        t = attrs.get("type", "")
        seg["sim_x0"] = x
        seg["sim_y0"] = y
        seg["sim_h0"] = h
        if t == "str":
            lg = to_float(attrs.get("lg"), 0.0)
            x += lg * math.cos(h)
            y += lg * math.sin(h)
        elif t in ("lft", "rgt"):
            radius = max(1e-6, abs(to_float(attrs.get("radius"), 0.0)))
            arc_deg = to_float(attrs.get("arc"), 0.0)
            a = math.radians(arc_deg)
            sign = 1.0 if t == "lft" else -1.0
            cx = x - sign * radius * math.sin(h)
            cy = y + sign * radius * math.cos(h)
            h = h + sign * a
            x = cx + sign * radius * math.sin(h)
            y = cy - sign * radius * math.cos(h)
        seg["sim_x1"] = x
        seg["sim_y1"] = y
        seg["sim_h1"] = h


def sample_centerline_points(segs: list[dict]) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    x = 0.0
    y = 0.0
    h = 0.0
    pts.append((x, y))
    for seg in segs:
        attrs = seg["attrs"]
        t = attrs.get("type", "")
        if t == "str":
            lg = to_float(attrs.get("lg"), 0.0)
            x += lg * math.cos(h)
            y += lg * math.sin(h)
            pts.append((x, y))
        elif t in ("lft", "rgt"):
            radius = max(1e-6, abs(to_float(attrs.get("radius"), 0.0)))
            arc_deg = to_float(attrs.get("arc"), 0.0)
            a = math.radians(arc_deg)
            sign = 1.0 if t == "lft" else -1.0
            cx = x - sign * radius * math.sin(h)
            cy = y + sign * radius * math.cos(h)
            seg_len = radius * abs(a)
            n = max(4, int(math.ceil(seg_len / 5.0)))
            da = a / n
            for _ in range(n):
                h = h + sign * da
                x = cx + sign * radius * math.sin(h)
                y = cy - sign * radius * math.cos(h)
                pts.append((x, y))
    return pts


def segments_intersect(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    def orient(p, q, r) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    return ((o1 > 0) != (o2 > 0)) and ((o3 > 0) != (o4 > 0))


def planar_edges(points: list[tuple[float, float]]) -> list[tuple[float, float, float, float, int, tuple[float, float], tuple[float, float]]]:
    edges: list[tuple[float, float, float, float, int, tuple[float, float], tuple[float, float]]] = []
    for i in range(len(points) - 1):
        a = points[i]
        b = points[i + 1]
        edges.append((min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]), i, a, b))
    edges.sort(key=lambda edge: edge[0])
    return edges


def edge_pair_is_adjacent(i: int, j: int, last_edge_index: int) -> bool:
    return abs(i - j) <= 1 or {i, j} == {0, last_edge_index}


def edge_y_ranges_overlap(min_ay: float, max_ay: float, min_by: float, max_by: float) -> bool:
    return not (max_by < min_ay or min_by > max_ay)


def planar_edges_self_intersect(
    edges: list[tuple[float, float, float, float, int, tuple[float, float], tuple[float, float]]],
    last_edge_index: int,
) -> bool:
    for pos, (_min_ax, max_ax, min_ay, max_ay, i, a, b) in enumerate(edges):
        for min_bx, _max_bx, min_by, max_by, j, c, d in edges[pos + 1 :]:
            if min_bx > max_ax:
                break
            if not edge_y_ranges_overlap(min_ay, max_ay, min_by, max_by):
                continue
            if edge_pair_is_adjacent(i, j, last_edge_index):
                continue
            if segments_intersect(a, b, c, d):
                return True
    return False


def has_planar_self_intersection(track_xml: pathlib.Path) -> bool:
    global SELF_INTERSECTION_CHECKS, SELF_INTERSECTION_SECONDS
    start = time.perf_counter()
    SELF_INTERSECTION_CHECKS += 1
    segs = parse_top_level_segments(track_xml.read_text(encoding="utf-8"))
    pts = sample_centerline_points(segs)
    try:
        return planar_edges_self_intersect(planar_edges(pts), len(pts) - 2)
    finally:
        SELF_INTERSECTION_SECONDS += time.perf_counter() - start


def is_pit_segment_name(name: str) -> bool:
    return "pit" in name.lower()


def control_straights(segs: list[dict]) -> list[dict]:
    straights = [s for s in segs if s["attrs"].get("type") == "str" and not is_pit_segment_name(s["name"])]
    return [s for s in straights if to_float(s["attrs"].get("lg"), 0.0) >= 20.0]


def control_turns(segs: list[dict]) -> list[dict]:
    return [s for s in segs if s["attrs"].get("type") in ("lft", "rgt") and not is_pit_segment_name(s["name"])]


def straight_control_score(s: dict, start_heading: float = 0.0) -> tuple[float, float]:
    h = float(s.get("sim_h0", 0.0))
    a = abs(math.degrees(norm_angle(h - start_heading)))
    a = min(a, 180.0 - a)
    closeness = -abs(a - 45.0)
    length = to_float(s["attrs"].get("lg"), 0.0)
    return closeness, length


def control_turn_radius(s: dict) -> float:
    return max(1e-6, abs(to_float(s["attrs"].get("radius"), 1e9)))


def control_turn_arc(s: dict) -> float:
    return abs(to_float(s["attrs"].get("arc"), 0.0))


def choose_primary_turn(turns: list[dict]) -> dict:
    tier_a = [t for t in turns if control_turn_arc(t) >= 4.0 and control_turn_radius(t) < 300.0]
    if tier_a:
        return max(tier_a, key=lambda s: (s["index"], -control_turn_radius(s)))
    tier_b = [t for t in turns if control_turn_arc(t) >= 2.0]
    if tier_b:
        return min(tier_b, key=lambda s: (control_turn_radius(s), -s["index"]))
    tier_c = [t for t in turns if control_turn_arc(t) >= 1.0]
    if tier_c:
        return min(tier_c, key=lambda s: (control_turn_radius(s), -s["index"]))
    return min(turns, key=lambda s: (control_turn_radius(s), -s["index"]))


def choose_backup_straight(straights: list[dict], primary_straight: dict, primary_turn: dict) -> dict | None:
    prior_straights = [s for s in straights if s["index"] < primary_turn["index"] and s["name"] != primary_straight["name"]]
    return max(prior_straights, key=straight_control_score) if prior_straights else None


def x_straight_score(s: dict) -> tuple[float, float, float]:
    h = float(s.get("sim_h0", 0.0))
    x_align = abs(math.cos(h))
    y_coupling = -abs(math.sin(h))
    length = to_float(s["attrs"].get("lg"), 0.0)
    helper_bonus = 1.0 if s["name"] == "Closure Start" else 0.0
    return helper_bonus, x_align, y_coupling, length


def choose_x_straight(straights: list[dict], primary_straight: dict) -> str:
    x_candidates = [s for s in straights if s["name"] != primary_straight["name"]]
    return max(x_candidates, key=x_straight_score)["name"] if x_candidates else ""


def non_pit_turns(segs: list[dict]) -> list[dict]:
    return [s for s in segs if s["attrs"].get("type") in ("lft", "rgt") and "pit" not in s["name"].lower()]


def turn_probe_radius(s: dict) -> float:
    return max(1e-6, abs(to_float(s["attrs"].get("radius"), 1e9)))


def turn_probe_arc(s: dict) -> float:
    return abs(to_float(s["attrs"].get("arc"), 0.0))


def turn_probe_order(s: dict) -> tuple[float, float, int]:
    return -min(turn_probe_arc(s), 30.0), turn_probe_radius(s), -s.get("index", 0)


def turn_probe_shortlist_names(turns: list[dict], primary_name: str, limit: int = 8) -> list[str]:
    shortlist_names = []
    if primary_name:
        shortlist_names.append(primary_name)
    for s in sorted(turns, key=turn_probe_order):
        if s["name"] not in shortlist_names:
            shortlist_names.append(s["name"])
        if len(shortlist_names) >= limit:
            break
    return shortlist_names


def pick_controls(segs: list[dict]) -> dict:
    if not segs:
        raise RuntimeError("No track segments found")
    simulate_segments(segs)
    straights = control_straights(segs)
    if not straights:
        raise RuntimeError("No suitable straight segment found for closure control")

    primary_straight = max(straights, key=straight_control_score)

    turns = control_turns(segs)
    if not turns:
        raise RuntimeError("No suitable turn segment found for closure control")

    # Turn selection policy:
    # 1) Prefer turns with arc >= 4 deg and radius < 300 m (high authority)
    # 2) Else prefer smallest-radius turns with arc >= 2 deg
    # 3) Else prefer smallest-radius turns with arc >= 1 deg
    # 4) Else fall back to smallest-radius turn
    # Within each tier, prefer turns later in the lap (closer to start line).
    primary_turn = choose_primary_turn(turns)
    backup_straight = choose_backup_straight(straights, primary_straight, primary_turn)

    # Additional straight for X-only correction: prefer long straights aligned
    # with the global X axis so Phase C can move X with minimal Y coupling.
    x_straight = choose_x_straight(straights, primary_straight)

    return {
        "primary_straight": primary_straight["name"],
        "primary_turn": primary_turn["name"],
        "backup_straight": backup_straight["name"] if backup_straight else "",
        "x_straight": x_straight,
        "y_turn": primary_turn["name"],
    }


def angular_probe_score(cand_metrics: dict, baseline_metrics: dict) -> float | None:
    base_ang = abs(baseline_metrics["delta_ang_deg"])
    base_y = abs(baseline_metrics["delta_y"])
    base_x = abs(baseline_metrics["delta_x"])
    ang_impr = base_ang - abs(cand_metrics["delta_ang_deg"])
    if ang_impr <= 0.0:
        return None
    y_worsen = max(0.0, abs(cand_metrics["delta_y"]) - base_y)
    x_worsen = max(0.0, abs(cand_metrics["delta_x"]) - base_x)
    return ang_impr - 0.35 * y_worsen - 0.10 * x_worsen


def choose_turn_by_probe(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    shortlist_names: list[str],
    baseline_metrics: dict,
    initial_name: str,
) -> str:
    best_name = initial_name
    best_score = -1e30
    for seg_name in shortlist_names:
        arc_val = read_attnum_value(base_text, seg_name, "arc")
        for delta in (0.1, -0.1):
            cand_arc = arc_val + delta
            if cand_arc <= 1e-6 or cand_arc >= 359.999999:
                continue
            cand_metrics = probe_attnum_metrics(track_xml, base_text, seg_name, "arc", cand_arc, runtime_dir, category, name)
            score = None if cand_metrics is None else angular_probe_score(cand_metrics, baseline_metrics)
            if score is not None and score > best_score:
                best_score = score
                best_name = seg_name
    return best_name


def refine_turn_controls_by_probe(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    segs: list[dict],
    controls: dict,
    baseline_metrics: dict,
) -> dict:
    turns = non_pit_turns(segs)
    if not turns:
        return controls

    primary_name = controls.get("primary_turn", "")
    base_text = track_xml.read_text(encoding="utf-8")
    best_name = choose_turn_by_probe(
        track_xml,
        runtime_dir,
        category,
        name,
        base_text,
        turn_probe_shortlist_names(turns, primary_name),
        baseline_metrics,
        primary_name,
    )

    track_xml.write_text(base_text, encoding="utf-8")
    if best_name:
        controls["primary_turn"] = best_name
        controls["y_turn"] = best_name
    return controls


def probe_attnum_metrics(
    track_xml: pathlib.Path,
    base_text: str,
    seg_name: str,
    att_name: str,
    cand_val: float,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
) -> dict | None:
    cand_text = replace_attnum_value(base_text, seg_name, att_name, cand_val)
    track_xml.write_text(cand_text, encoding="utf-8")
    try:
        cand_metrics, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
        if has_planar_self_intersection(track_xml):
            return None
    except RuntimeError:
        return None
    return cand_metrics


def y_probe_score(cand_metrics: dict, baseline_metrics: dict) -> float | None:
    base_ang = abs(baseline_metrics["delta_ang_deg"])
    base_y = abs(baseline_metrics["delta_y"])
    base_x = abs(baseline_metrics["delta_x"])
    y_impr = base_y - abs(cand_metrics["delta_y"])
    if y_impr <= 0.0:
        return None
    ang_worsen = max(0.0, abs(cand_metrics["delta_ang_deg"]) - base_ang)
    x_worsen = max(0.0, abs(cand_metrics["delta_x"]) - base_x)
    return y_impr - 40.0 * ang_worsen - 0.10 * x_worsen


def y_straight_probe_order(s: dict) -> tuple[float, int]:
    return -to_float(s["attrs"].get("lg"), 0.0), s.get("index", 0)


def y_turn_probe_order(s: dict) -> tuple[float, float]:
    return abs(to_float(s["attrs"].get("radius"), 1e9)), -abs(to_float(s["attrs"].get("arc"), 0.0))


def choose_y_straight_by_probe(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    straights: list[dict],
    baseline_metrics: dict,
    initial_name: str,
) -> str:
    best_straight = initial_name
    best_score = -1e30
    for s in sorted(straights, key=y_straight_probe_order)[:10]:
        seg_name = s["name"]
        lg_val = read_attnum_value(base_text, seg_name, "lg")
        for delta in (1.0, -1.0):
            cand_metrics = probe_attnum_metrics(track_xml, base_text, seg_name, "lg", lg_val + delta, runtime_dir, category, name)
            score = None if cand_metrics is None else y_probe_score(cand_metrics, baseline_metrics)
            if score is not None and score > best_score:
                best_score = score
                best_straight = seg_name
    return best_straight


def choose_y_turn_by_probe(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    turns: list[dict],
    baseline_metrics: dict,
    initial_name: str,
) -> str:
    best_turn = initial_name
    best_score = -1e30
    for s in sorted(turns, key=y_turn_probe_order)[:10]:
        seg_name = s["name"]
        rad_val = read_attnum_value(base_text, seg_name, "radius")
        for delta in (1.0, -1.0):
            cand_val = rad_val + delta
            if cand_val < 2.0:
                continue
            cand_metrics = probe_attnum_metrics(track_xml, base_text, seg_name, "radius", cand_val, runtime_dir, category, name)
            score = None if cand_metrics is None else y_probe_score(cand_metrics, baseline_metrics)
            if score is not None and score > best_score:
                best_score = score
                best_turn = seg_name
    return best_turn


def non_pit_straights(segs: list[dict], min_length: float = 20.0) -> list[dict]:
    straights = [s for s in segs if s["attrs"].get("type") == "str" and "pit" not in s["name"].lower()]
    return [s for s in straights if to_float(s["attrs"].get("lg"), 0.0) >= min_length]


def x_control_probe_order(s: dict) -> tuple[float, float, int]:
    helper_bonus = 1.0 if s["name"] == "Closure Start" else 0.0
    return -helper_bonus, -to_float(s["attrs"].get("lg"), 0.0), s.get("index", 0)


def x_probe_metrics(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    base_text: str,
    straights: list[dict],
    probe_step: float,
    limit: int,
) -> list[tuple[str, dict]]:
    results = []
    for s in sorted(straights, key=x_control_probe_order)[:limit]:
        seg_name = s["name"]
        lg_val = read_attnum_value(base_text, seg_name, "lg")
        for delta in (probe_step, -probe_step):
            cand_metrics = probe_attnum_metrics(track_xml, base_text, seg_name, "lg", lg_val + delta, runtime_dir, category, name)
            if cand_metrics is not None:
                results.append((seg_name, cand_metrics))
    return results


def x_probe_improvement(cand_metrics: dict, current_metrics: dict, desired_sign: float) -> float | None:
    dx_delta = cand_metrics["delta_x"] - current_metrics["delta_x"]
    if dx_delta * desired_sign <= 0.0:
        return None
    x_impr = abs(current_metrics["delta_x"]) - abs(cand_metrics["delta_x"])
    return x_impr if x_impr > 0.0 else None


def x_refine_probe_score(cand_metrics: dict, baseline_metrics: dict, desired_sign: float) -> float | None:
    x_impr = x_probe_improvement(cand_metrics, baseline_metrics, desired_sign)
    if x_impr is None:
        return None
    y_worsen = max(0.0, abs(cand_metrics["delta_y"]) - abs(baseline_metrics["delta_y"]))
    ang_worsen = max(0.0, abs(cand_metrics["delta_ang_deg"]) - abs(baseline_metrics["delta_ang_deg"]))
    return x_impr - 0.35 * y_worsen - 40.0 * ang_worsen


def x_runtime_probe_score(cand_metrics: dict, current_metrics: dict, desired_sign: float, ang_lock: float, y_lock: float) -> float | None:
    if abs(cand_metrics["delta_ang_deg"]) > ang_lock or abs(cand_metrics["delta_y"]) > y_lock:
        return None
    return x_probe_improvement(cand_metrics, current_metrics, desired_sign)


def best_scored_x_control(candidates: list[tuple[str, dict]], initial_name: str, score_fn) -> str:
    best_name = initial_name
    best_score = -1e30
    for seg_name, cand_metrics in candidates:
        score = score_fn(cand_metrics)
        if score is not None and score > best_score:
            best_score = score
            best_name = seg_name
    return best_name


def refine_y_controls_by_probe(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    segs: list[dict],
    controls: dict,
    baseline_metrics: dict,
) -> dict:
    straights = control_straights(segs)
    turns = control_turns(segs)
    base_text = track_xml.read_text(encoding="utf-8")
    best_straight = choose_y_straight_by_probe(
        track_xml,
        runtime_dir,
        category,
        name,
        base_text,
        straights,
        baseline_metrics,
        controls.get("primary_straight", ""),
    )
    best_turn = choose_y_turn_by_probe(
        track_xml,
        runtime_dir,
        category,
        name,
        base_text,
        turns,
        baseline_metrics,
        controls.get("y_turn", controls.get("primary_turn", "")),
    )

    track_xml.write_text(base_text, encoding="utf-8")
    if best_straight:
        controls["primary_straight"] = best_straight
    if best_turn:
        controls["y_turn"] = best_turn
    return controls


def refine_x_controls_by_probe(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    segs: list[dict],
    controls: dict,
    baseline_metrics: dict,
) -> dict:
    straights = non_pit_straights(segs)
    if not straights:
        return controls

    base_text = track_xml.read_text(encoding="utf-8")
    desired_sign = -1.0 if baseline_metrics["delta_x"] > 0.0 else 1.0
    initial_name = controls.get("x_straight", controls.get("backup_straight", controls.get("primary_straight", "")))
    candidates = x_probe_metrics(track_xml, runtime_dir, category, name, base_text, straights, 1.0, 12)
    best_name = best_scored_x_control(candidates, initial_name, lambda m: x_refine_probe_score(m, baseline_metrics, desired_sign))

    track_xml.write_text(base_text, encoding="utf-8")
    if best_name:
        controls["x_straight"] = best_name
    return controls


def choose_runtime_x_control(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    current_metrics: dict,
    fallback_name: str,
    ang_lock: float,
    y_lock: float,
    probe_step: float,
) -> str:
    segs = parse_top_level_segments(track_xml.read_text(encoding="utf-8"))
    straights = non_pit_straights(segs)
    if not straights:
        return fallback_name

    base_text = track_xml.read_text(encoding="utf-8")
    desired_sign = -1.0 if current_metrics["delta_x"] > 0.0 else 1.0
    candidates = x_probe_metrics(track_xml, runtime_dir, category, name, base_text, straights, probe_step, 14)
    best_name = best_scored_x_control(
        candidates,
        fallback_name,
        lambda m: x_runtime_probe_score(m, current_metrics, desired_sign, ang_lock, y_lock),
    )

    track_xml.write_text(base_text, encoding="utf-8")
    return best_name


def replace_attnum_value(text: str, seg_name: str, att_name: str, value: float) -> str:
    seg_open_re = re.compile(rf"(<section\s+name=\"{re.escape(seg_name)}\">)", re.IGNORECASE)
    m = seg_open_re.search(text)
    if not m:
        raise RuntimeError(f"Segment not found: {seg_name}")
    seg_start = m.start(1)
    seg_end = find_matching_section_end(text, seg_start)
    seg_text = text[seg_start:seg_end]
    att_re = re.compile(rf'(<attnum\s+name=\"{re.escape(att_name)}\"[^>]*\bval=\")([^\"]+)(\"[^>]*/>)', re.IGNORECASE)
    if not att_re.search(seg_text):
        raise RuntimeError(f"Attribute '{att_name}' not found in segment '{seg_name}'")
    seg_new = att_re.sub(lambda mm: f"{mm.group(1)}{value:.8f}{mm.group(3)}", seg_text, count=1)
    return text[:seg_start] + seg_new + text[seg_end:]


def read_attnum_value(text: str, seg_name: str, att_name: str) -> float:
    seg_open_re = re.compile(rf"<section\s+name=\"{re.escape(seg_name)}\">", re.IGNORECASE)
    m = seg_open_re.search(text)
    if not m:
        raise RuntimeError(f"Segment not found: {seg_name}")
    seg_start = m.start()
    seg_end = find_matching_section_end(text, seg_start)
    seg_text = text[seg_start:seg_end]
    att_re = re.compile(rf'<attnum\s+name=\"{re.escape(att_name)}\"[^>]*\bval=\"([^\"]+)\"', re.IGNORECASE)
    mm = att_re.search(seg_text)
    if not mm:
        raise RuntimeError(f"Attribute '{att_name}' not found in segment '{seg_name}'")
    return float(mm.group(1))


def replace_segment_raw(text: str, seg_name: str, new_raw: str) -> str:
    segs = parse_top_level_segments(text)
    target = next((s for s in segs if s["name"] == seg_name), None)
    if target is None:
        raise RuntimeError(f"Segment not found: {seg_name}")
    return text[: target["global_start"]] + new_raw + text[target["global_end"] :]


def split_turn_with_straight_insert(text: str, turn_name: str, straight_name: str, straight_lg: float) -> tuple[str, str]:
    segs = parse_top_level_segments(text)
    target = next((s for s in segs if s["name"] == turn_name), None)
    if target is None:
        raise RuntimeError(f"Turn segment not found: {turn_name}")
    attrs = target["attrs"]
    t = attrs.get("type", "")
    if t not in ("lft", "rgt"):
        raise RuntimeError(f"Segment is not a turn: {turn_name}")
    arc = abs(to_float(attrs.get("arc"), 0.0))
    if arc <= 1e-6:
        raise RuntimeError(f"Turn has no arc: {turn_name}")
    if "end radius" in attrs:
        raise RuntimeError(f"Turn has end radius (not supported for split): {turn_name}")

    original_raw = target["raw"]
    existing = {s["name"] for s in segs}
    pre_name = unique_name(existing, f"{turn_name}-xpre")

    def replace_section_name(raw: str, new_name: str) -> str:
        return re.sub(r'(<section\s+name=")([^"]+)(">)', rf"\1{new_name}\3", raw, count=1, flags=re.IGNORECASE)

    def replace_attnum(raw: str, name: str, value: float) -> str:
        patt = re.compile(rf'(<attnum\s+name="{re.escape(name)}"[^>]*\bval=")([^"]+)("[^>]*/>)', re.IGNORECASE)
        if not patt.search(raw):
            raise RuntimeError(f"Attribute '{name}' not found in segment '{turn_name}'")
        return patt.sub(lambda m: f"{m.group(1)}{value:.8f}{m.group(3)}", raw, count=1)

    pre_arc = arc * 0.5
    post_arc = arc - pre_arc

    pre_raw = replace_section_name(original_raw, pre_name)
    pre_raw = replace_attnum(pre_raw, "arc", pre_arc)

    post_raw = replace_attnum(original_raw, "arc", post_arc)

    straight_raw = (
        f'\t\t\t<section name="{straight_name}\">\n'
        f'\t\t\t\t<attstr name="type" val="str" />\n'
        f'\t\t\t\t<attnum name="z end" unit="m" val="0.0" />\n'
        f'\t\t\t\t<attnum name="lg" val="{straight_lg:.8f}" unit="m" />\n'
        f'\t\t\t</section>'
    )

    merged = pre_raw + "\n" + straight_raw + "\n" + post_raw
    return replace_segment_raw(text, turn_name, merged), pre_name


def find_x_comp_turn_candidates(segs: list[dict]) -> list[dict]:
    simulate_segments(segs)
    pit_idxs = {s["index"] for s in segs if "pit" in s["name"].lower()}
    blocked = set(pit_idxs)
    for i in pit_idxs:
        blocked.add(max(0, i - 1))
        blocked.add(min(len(segs) - 1, i + 1))

    out: list[dict] = []
    for s in segs:
        if s["index"] in blocked:
            continue
        attrs = s["attrs"]
        t = attrs.get("type", "")
        if t not in ("lft", "rgt"):
            continue
        if "pit" in s["name"].lower():
            continue
        if "end radius" in attrs:
            continue
        radius = abs(to_float(attrs.get("radius"), 0.0))
        arc = abs(to_float(attrs.get("arc"), 0.0))
        if radius < 300.0 or arc < 0.3:
            continue
        sign = 1.0 if t == "lft" else -1.0
        mid_h = float(s.get("sim_h0", 0.0)) + sign * math.radians(arc) * 0.5
        c = math.cos(mid_h)
        score = abs(c) * min(radius, 8000.0) + arc
        out.append({"seg": s, "mid_cos": c, "score": score})
    out.sort(key=lambda it: it["score"], reverse=True)
    return out


def run_trackgen_z(runtime_dir: pathlib.Path, category: str, name: str, track_xml_under_test: pathlib.Path | None = None) -> tuple[dict, str]:
    global TRACKGEN_CACHE_HITS, TRACKGEN_CALLS, TRACKGEN_SECONDS
    before_calls = TRACKGEN_STATS.calls
    before_seconds = TRACKGEN_STATS.seconds
    before_cache_hits = TRACKGEN_STATS.cache_hits
    runner = TrackgenRunner(runtime_dir, cache=TRACKGEN_CACHE, stats=TRACKGEN_STATS, allow_missing_live_xml=True)
    metrics, out = runner.run_z(category, name, track_xml_under_test)

    call_delta = TRACKGEN_STATS.calls - before_calls
    seconds_delta = TRACKGEN_STATS.seconds - before_seconds
    cache_hit_delta = TRACKGEN_STATS.cache_hits - before_cache_hits
    TRACKGEN_CALLS += call_delta
    TRACKGEN_SECONDS += seconds_delta
    TRACKGEN_CACHE_HITS += cache_hit_delta
    phase = phase_stats(TRACKGEN_PHASE)
    phase["calls"] += call_delta
    phase["seconds"] += seconds_delta
    phase["cache_hits"] += cache_hit_delta
    return metrics, out


def passed(metrics: dict, args: argparse.Namespace) -> bool:
    return (
        abs(metrics["delta_x"]) <= args.target_dx
        and abs(metrics["delta_y"]) <= args.target_dy
        and abs(metrics["delta_z"]) <= args.target_dz
        and abs(metrics["delta_ang_deg"]) <= args.target_ang
    )


def closure_gap(metrics: dict, args: argparse.Namespace) -> float:
    return (
        max(0.0, abs(metrics["delta_x"]) - args.target_dx)
        + max(0.0, abs(metrics["delta_y"]) - args.target_dy)
        + max(0.0, abs(metrics["delta_z"]) - args.target_dz)
        + max(0.0, abs(metrics["delta_ang_deg"]) - args.target_ang)
    )


def phase_objective(metrics: dict, target_key: str) -> float:
    obj = abs(metrics[target_key]) + 50.0 * abs(metrics["delta_z"])
    return obj


def solve_3x3(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    rows = [list(matrix[i]) + [rhs[i]] for i in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        div = rows[col][col]
        rows[col] = [v / div for v in rows[col]]
        for r in range(3):
            if r == col:
                continue
            factor = rows[r][col]
            rows[r] = [rows[r][k] - factor * rows[col][k] for k in range(4)]
    return [rows[i][3] for i in range(3)]


def apply_attnum_deltas(text: str, deltas: list[tuple[str, str, float]]) -> str:
    out = text
    for seg_name, att_name, delta in deltas:
        cur = read_attnum_value(out, seg_name, att_name)
        out = replace_attnum_value(out, seg_name, att_name, cur + delta)
    return out


def metrics_residual_vector(metrics: dict) -> list[float]:
    return [metrics["delta_x"], metrics["delta_y"], metrics["delta_ang_deg"]]


def probe_attnum_sensitivity(
    track_xml: pathlib.Path,
    base_text: str,
    seg_name: str,
    att_name: str,
    delta: float,
    scale: float,
    base_vec: list[float],
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
) -> tuple[str, list[float]] | None:
    try:
        cur = read_attnum_value(base_text, seg_name, att_name)
    except RuntimeError:
        return None
    track_xml.write_text(replace_attnum_value(base_text, seg_name, att_name, cur + delta), encoding="utf-8")
    try:
        probe, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
    except RuntimeError:
        return None
    return (
        seg_name,
        [
            (probe["delta_x"] - base_vec[0]) / scale,
            (probe["delta_y"] - base_vec[1]) / scale,
            (probe["delta_ang_deg"] - base_vec[2]) / scale,
        ],
    )


def collect_attnum_sensitivities(
    track_xml: pathlib.Path,
    base_text: str,
    segs: list[dict],
    att_name: str,
    delta: float,
    scale: float,
    base_vec: list[float],
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
) -> list[tuple[str, list[float]]]:
    sensitivities: list[tuple[str, list[float]]] = []
    for seg in segs:
        sensitivity = probe_attnum_sensitivity(
            track_xml,
            base_text,
            seg["name"],
            att_name,
            delta,
            scale,
            base_vec,
            runtime_dir,
            category,
            name,
        )
        if sensitivity is not None:
            sensitivities.append(sensitivity)
    return sensitivities


def probe_linear_polish_sensitivities(
    track_xml: pathlib.Path,
    base_text: str,
    straights: list[dict],
    turns: list[dict],
    base_vec: list[float],
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
) -> tuple[list[tuple[str, list[float]]], list[tuple[str, list[float]]]]:
    with trackgen_phase("linear-polish-probe"):
        straight_sens = collect_attnum_sensitivities(
            track_xml,
            base_text,
            straights,
            "lg",
            1.0,
            1.0,
            base_vec,
            runtime_dir,
            category,
            name,
        )
        track_xml.write_text(base_text, encoding="utf-8")

        arc_probe_step = 0.001
        turn_sens = collect_attnum_sensitivities(
            track_xml,
            base_text,
            turns,
            "arc",
            arc_probe_step,
            arc_probe_step,
            base_vec,
            runtime_dir,
            category,
            name,
        )
        track_xml.write_text(base_text, encoding="utf-8")
    return straight_sens, turn_sens


def build_linear_polish_candidate(
    turn_name: str,
    turn_vec: list[float],
    s1: tuple[str, list[float]],
    s2: tuple[str, list[float]],
    rhs: list[float],
    args: argparse.Namespace,
) -> tuple[float, list[tuple[str, str, float]]] | None:
    matrix = [
        [turn_vec[0], s1[1][0], s2[1][0]],
        [turn_vec[1], s1[1][1], s2[1][1]],
        [turn_vec[2], s1[1][2], s2[1][2]],
    ]
    sol = solve_3x3(matrix, rhs)
    if sol is None:
        return None
    arc_delta, s1_delta, s2_delta = sol
    if abs(arc_delta) > args.linear_max_arc_delta:
        return None
    if abs(s1_delta) > args.linear_max_straight_delta or abs(s2_delta) > args.linear_max_straight_delta:
        return None
    return (
        abs(arc_delta) * 100.0 + abs(s1_delta) + abs(s2_delta),
        [(turn_name, "arc", arc_delta), (s1[0], "lg", s1_delta), (s2[0], "lg", s2_delta)],
    )


def build_linear_polish_predictions(
    turn_sens: list[tuple[str, list[float]]],
    straight_sens: list[tuple[str, list[float]]],
    base_vec: list[float],
    args: argparse.Namespace,
) -> list[tuple[float, list[tuple[str, str, float]]]]:
    predicted: list[tuple[float, list[tuple[str, str, float]]]] = []
    rhs = [-base_vec[0], -base_vec[1], -base_vec[2]]
    for turn_name, turn_vec in turn_sens:
        for s1, s2 in itertools.combinations(straight_sens, 2):
            candidate = build_linear_polish_candidate(turn_name, turn_vec, s1, s2, rhs, args)
            if candidate is not None:
                predicted.append(candidate)
    return predicted


def try_linear_polish_candidate(
    track_xml: pathlib.Path,
    base_text: str,
    deltas: list[tuple[str, str, float]],
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    args: argparse.Namespace,
) -> tuple[str, dict, float] | None:
    try:
        cand_text = apply_attnum_deltas(base_text, deltas)
        track_xml.write_text(cand_text, encoding="utf-8")
        cand_metrics, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
        if has_planar_self_intersection(track_xml):
            return None
    except RuntimeError:
        return None
    return cand_text, cand_metrics, closure_gap(cand_metrics, args)


def append_linear_polish_history(
    history: list[dict],
    iter_id: int,
    deltas: list[tuple[str, str, float]],
    cand_metrics: dict,
    cand_gap: float,
) -> None:
    history.append(
        {
            "iter": iter_id,
            "phase": "linear-polish",
            "action": ", ".join(f"{seg}.{att} += {delta:.8f}" for seg, att, delta in deltas),
            "metrics": cand_metrics,
            "gap": cand_gap,
        }
    )


def verify_linear_polish_predictions(
    track_xml: pathlib.Path,
    base_text: str,
    metrics: dict,
    base_gap: float,
    predicted: list[tuple[float, list[tuple[str, str, float]]]],
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    args: argparse.Namespace,
    history: list[dict],
    iter_id: int,
) -> tuple[dict, float, str]:
    best_text = base_text
    best_metrics = metrics
    best_gap = base_gap
    with trackgen_phase("linear-polish-verify"):
        for _, deltas in sorted(predicted, key=lambda item: item[0])[: max(1, args.linear_polish_candidates)]:
            result = try_linear_polish_candidate(track_xml, base_text, deltas, runtime_dir, category, name, args)
            if result is None:
                continue
            cand_text, cand_metrics, cand_gap = result
            if cand_gap + 1e-12 < best_gap:
                best_gap = cand_gap
                best_metrics = cand_metrics
                best_text = cand_text
                append_linear_polish_history(history, iter_id, deltas, cand_metrics, cand_gap)
                if passed(cand_metrics, args):
                    break
    return best_metrics, best_gap, best_text


def linear_polish_once(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    metrics: dict,
    args: argparse.Namespace,
    history: list[dict],
    iter_id: int,
) -> tuple[dict, bool]:
    base_text = track_xml.read_text(encoding="utf-8")
    base_gap = closure_gap(metrics, args)
    segs = parse_top_level_segments(base_text)
    straights = control_straights(segs)
    turns = control_turns(segs)
    if len(straights) < 2 or not turns:
        return metrics, False

    base_vec = metrics_residual_vector(metrics)
    straight_sens, turn_sens = probe_linear_polish_sensitivities(track_xml, base_text, straights, turns, base_vec, runtime_dir, category, name)
    predicted = build_linear_polish_predictions(turn_sens, straight_sens, base_vec, args)
    best_metrics, best_gap, best_text = verify_linear_polish_predictions(
        track_xml,
        base_text,
        metrics,
        base_gap,
        predicted,
        runtime_dir,
        category,
        name,
        args,
        history,
        iter_id,
    )

    track_xml.write_text(best_text, encoding="utf-8")
    return best_metrics, best_gap + 1e-12 < base_gap


def try_best_of_three(
    track_xml: pathlib.Path,
    base_text: str,
    seg_name: str,
    att_name: str,
    base_val: float,
    step: float,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    objective,
    is_valid_value=None,
    is_valid_metrics=None,
) -> tuple[str, float, dict, float]:
    candidates: list[tuple[str, float, dict, float]] = []
    for delta in (0.0, step, -step):
        cand_val = base_val + delta
        if is_valid_value is not None and not is_valid_value(cand_val):
            continue
        txt = replace_attnum_value(base_text, seg_name, att_name, cand_val)
        track_xml.write_text(txt, encoding="utf-8")
        metrics, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
        if is_valid_metrics is not None and not is_valid_metrics(metrics):
            continue
        if has_planar_self_intersection(track_xml):
            continue
        candidates.append((txt, cand_val, metrics, objective(metrics)))
    if not candidates:
        track_xml.write_text(base_text, encoding="utf-8")
        metrics, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
        return base_text, base_val, metrics, objective(metrics)
    best = min(candidates, key=lambda x: x[3])
    track_xml.write_text(best[0], encoding="utf-8")
    return best


def write_json(path: pathlib.Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def runtime_stats() -> dict:
    return {
        "trackgen_calls": TRACKGEN_CALLS,
        "trackgen_seconds": TRACKGEN_SECONDS,
        "trackgen_cache_hits": TRACKGEN_CACHE_HITS,
        "trackgen_phases": TRACKGEN_PHASE_STATS,
        "self_intersection_checks": SELF_INTERSECTION_CHECKS,
        "self_intersection_seconds": SELF_INTERSECTION_SECONDS,
    }


def tune_once(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    seg_name: str,
    att_name: str,
    step: float,
    objective,
    history: list[dict],
    iter_id: int,
    phase: str,
    sub_iter: int,
    is_valid_value=None,
    is_valid_metrics=None,
) -> tuple[dict, float, bool]:
    """Run one local +/- step trial and record history.

    Returns: (best_metrics_from_trial, possibly_updated_step, changed_flag)
    """
    text = track_xml.read_text(encoding="utf-8")
    base_val = read_attnum_value(text, seg_name, att_name)
    with trackgen_phase(phase):
        txt_best, val_best, m_best, obj_best = try_best_of_three(
            track_xml,
            text,
            seg_name,
            att_name,
            base_val,
            step,
            runtime_dir,
            category,
            name,
            objective,
            is_valid_value=is_valid_value,
            is_valid_metrics=is_valid_metrics,
        )
    if val_best != base_val:
        track_xml.write_text(txt_best, encoding="utf-8")
        history.append(
            {
                "iter": iter_id,
                "phase": phase,
                "sub_iter": sub_iter,
                "action": f"{seg_name}.{att_name} -> {val_best:.8f}",
                "step": step,
                "metrics": m_best,
                "objective": obj_best,
            }
        )
        return m_best, step, True
    return m_best, step * 0.5, False


def try_projected_delta(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    text: str,
    seg_name: str,
    att_name: str,
    base_val: float,
    step: float,
    max_jump_multiplier: float,
    current_metrics: dict,
    target_key: str,
    slope: float,
    objective,
    is_valid_value=None,
    is_valid_metrics=None,
) -> tuple[str, float, dict, float, float] | None:
    if abs(slope) <= 1e-12:
        return None
    est_delta = -current_metrics[target_key] / slope
    max_jump = abs(step) * max_jump_multiplier
    est_delta = max(-max_jump, min(max_jump, est_delta))
    if abs(est_delta) < max(1e-12, abs(step) * 0.5):
        return None
    cand_val = base_val + est_delta
    if is_valid_value is not None and not is_valid_value(cand_val):
        return None
    cand_text = replace_attnum_value(text, seg_name, att_name, cand_val)
    track_xml.write_text(cand_text, encoding="utf-8")
    cand_metrics, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
    if is_valid_metrics is not None and not is_valid_metrics(cand_metrics):
        return None
    if has_planar_self_intersection(track_xml):
        return None
    return cand_text, cand_val, cand_metrics, objective(cand_metrics), est_delta


def update_projected_slope(slope_key: tuple[str, str, str, str], current_metrics: dict, target_key: str, cand_metrics: dict, delta_val: float) -> float | None:
    delta_metric = cand_metrics[target_key] - current_metrics[target_key]
    if abs(delta_val) > 1e-12 and abs(delta_metric) > 1e-12:
        slope = delta_metric / delta_val
        PROJECTED_SLOPES[slope_key] = slope
        return slope
    return None


def append_tune_projected_history(
    history: list[dict],
    iter_id: int,
    phase: str,
    sub_iter: int,
    seg_name: str,
    att_name: str,
    step: float,
    winner: tuple[str, float, dict, float, str],
) -> None:
    history.append(
        {
            "iter": iter_id,
            "phase": phase,
            "sub_iter": sub_iter,
            "action": f"{seg_name}.{att_name} -> {winner[1]:.8f}",
            "step": step,
            "method": winner[4],
            "metrics": winner[2],
            "objective": winner[3],
        }
    )


def projected_next_step(step: float, base_val: float, winner: tuple[str, float, dict, float, str]) -> float:
    return step if winner[4] == "probe" else max(abs(step), abs(winner[1] - base_val) * 0.5)


def try_cached_projected_winner(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    text: str,
    seg_name: str,
    att_name: str,
    base_val: float,
    base_obj: float,
    step: float,
    max_jump_multiplier: float,
    current_metrics: dict,
    target_key: str,
    objective,
    slope_key: tuple[str, str, str, str],
    is_valid_value=None,
    is_valid_metrics=None,
) -> tuple[str, float, dict, float, str] | None:
    cached_projected = try_projected_delta(
        track_xml,
        runtime_dir,
        category,
        name,
        text,
        seg_name,
        att_name,
        base_val,
        step,
        max_jump_multiplier,
        current_metrics,
        target_key,
        PROJECTED_SLOPES[slope_key],
        objective,
        is_valid_value=is_valid_value,
        is_valid_metrics=is_valid_metrics,
    )
    track_xml.write_text(text, encoding="utf-8")
    if cached_projected is None or cached_projected[3] + 1e-12 >= base_obj:
        return None
    cand_text, cand_val, cand_metrics, cand_obj, est_delta = cached_projected
    update_projected_slope(slope_key, current_metrics, target_key, cand_metrics, est_delta)
    return cand_text, cand_val, cand_metrics, cand_obj, "cached-projected"


def collect_projected_probes(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    text: str,
    seg_name: str,
    att_name: str,
    base_val: float,
    step: float,
    objective,
    is_valid_value=None,
    is_valid_metrics=None,
) -> list[tuple[str, float, dict, float]]:
    probes: list[tuple[str, float, dict, float]] = []
    for delta in (step, -step):
        cand_val = base_val + delta
        if is_valid_value is not None and not is_valid_value(cand_val):
            continue
        cand_text = replace_attnum_value(text, seg_name, att_name, cand_val)
        track_xml.write_text(cand_text, encoding="utf-8")
        cand_metrics, _ = run_trackgen_z(runtime_dir, category, name, track_xml)
        if is_valid_metrics is not None and not is_valid_metrics(cand_metrics):
            continue
        if has_planar_self_intersection(track_xml):
            continue
        probes.append((cand_text, cand_val, cand_metrics, objective(cand_metrics)))
    return probes


def select_projected_winner(
    best_probe: tuple[str, float, dict, float],
    projected: tuple[str, float, dict, float, float] | None,
) -> tuple[str, float, dict, float, str]:
    winner = (best_probe[0], best_probe[1], best_probe[2], best_probe[3], "probe")
    if projected is not None and projected[3] <= winner[3]:
        return projected[0], projected[1], projected[2], projected[3], "projected"
    return winner


def finish_tune_projected(
    track_xml: pathlib.Path,
    current_metrics: dict,
    base_obj: float,
    base_val: float,
    step: float,
    history: list[dict],
    iter_id: int,
    phase: str,
    sub_iter: int,
    seg_name: str,
    att_name: str,
    winner: tuple[str, float, dict, float, str],
) -> tuple[dict, float, bool]:
    if winner[3] + 1e-12 < base_obj and winner[1] != base_val:
        track_xml.write_text(winner[0], encoding="utf-8")
        append_tune_projected_history(history, iter_id, phase, sub_iter, seg_name, att_name, step, winner)
        return winner[2], projected_next_step(step, base_val, winner), True
    return current_metrics, step * 0.5, False


def tune_projected(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    seg_name: str,
    att_name: str,
    step: float,
    objective,
    history: list[dict],
    iter_id: int,
    phase: str,
    sub_iter: int,
    target_key: str,
    current_metrics: dict,
    is_valid_value=None,
    is_valid_metrics=None,
    max_jump_multiplier: float = 8.0,
    use_cached_slope: bool = False,
) -> tuple[dict, float, bool]:
    with trackgen_phase(phase):
        text = track_xml.read_text(encoding="utf-8")
        base_val = read_attnum_value(text, seg_name, att_name)
        base_obj = objective(current_metrics)
        slope_key = (phase, seg_name, att_name, target_key)

        if use_cached_slope and slope_key in PROJECTED_SLOPES:
            cached_winner = try_cached_projected_winner(
                track_xml,
                runtime_dir,
                category,
                name,
                text,
                seg_name,
                att_name,
                base_val,
                base_obj,
                step,
                max_jump_multiplier,
                current_metrics,
                target_key,
                objective,
                slope_key,
                is_valid_value=is_valid_value,
                is_valid_metrics=is_valid_metrics,
            )
            if cached_winner is not None:
                track_xml.write_text(cached_winner[0], encoding="utf-8")
                append_tune_projected_history(history, iter_id, phase, sub_iter, seg_name, att_name, step, cached_winner)
                return cached_winner[2], projected_next_step(step, base_val, cached_winner), True

        probes = collect_projected_probes(
            track_xml,
            runtime_dir,
            category,
            name,
            text,
            seg_name,
            att_name,
            base_val,
            step,
            objective,
            is_valid_value=is_valid_value,
            is_valid_metrics=is_valid_metrics,
        )

        if not probes:
            track_xml.write_text(text, encoding="utf-8")
            return current_metrics, step * 0.5, False

        best_probe = min(probes, key=lambda x: x[3])
        best_text, best_val, best_metrics, best_obj = best_probe

        slope = update_projected_slope(slope_key, current_metrics, target_key, best_metrics, best_val - base_val)

        projected = None
        if slope is not None:
            projected = try_projected_delta(
                track_xml,
                runtime_dir,
                category,
                name,
                text,
                seg_name,
                att_name,
                base_val,
                step,
                max_jump_multiplier,
                current_metrics,
                target_key,
                slope,
                objective,
                is_valid_value=is_valid_value,
                is_valid_metrics=is_valid_metrics,
            )

        track_xml.write_text(text, encoding="utf-8")
        winner = select_projected_winner((best_text, best_val, best_metrics, best_obj), projected)

    return finish_tune_projected(track_xml, current_metrics, base_obj, base_val, step, history, iter_id, phase, sub_iter, seg_name, att_name, winner)


def polish_near_pass(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    category: str,
    name: str,
    controls: dict,
    metrics: dict,
    args: argparse.Namespace,
    history: list[dict],
    start_iter: int,
    arc_step: float,
    x_step: float,
    straight_step: float,
    min_arc: float,
    min_straight: float,
) -> tuple[dict, float, float, float, bool]:
    primary_turn = controls["primary_turn"]
    primary_straight = controls["primary_straight"]
    x_control = controls.get("x_straight") or controls.get("backup_straight") or primary_straight
    changed_any = False

    for polish_round in range(1, 4):
        # Angle micro-polish while holding X/Y near current best.
        ang_dx_lock = max(abs(metrics["delta_x"]) + 0.002, 0.01)
        ang_dy_lock = max(abs(metrics["delta_y"]) + 0.002, 0.01)
        m_best, arc_step, changed = tune_once(
            track_xml=track_xml,
            runtime_dir=runtime_dir,
            category=category,
            name=name,
            seg_name=primary_turn,
            att_name="arc",
            step=max(arc_step, min_arc),
            objective=lambda m: phase_objective(m, "delta_ang_deg"),
            history=history,
            iter_id=start_iter + polish_round,
            phase="A-polish",
            sub_iter=1,
            is_valid_metrics=lambda m, dx_lock=ang_dx_lock, dy_lock=ang_dy_lock: abs(m["delta_x"]) <= dx_lock
            and abs(m["delta_y"]) <= dy_lock,
        )
        metrics = m_best
        changed_any = changed_any or changed
        if passed(metrics, args):
            return metrics, arc_step, x_step, straight_step, True

        # X micro-polish while holding Y/angle near current best.
        x_ang_lock = max(abs(metrics["delta_ang_deg"]) + 0.0002, 0.001)
        x_dy_lock = max(abs(metrics["delta_y"]) + 0.002, 0.01)
        m_best, x_step, changed = tune_once(
            track_xml=track_xml,
            runtime_dir=runtime_dir,
            category=category,
            name=name,
            seg_name=x_control,
            att_name="lg",
            step=max(x_step, min_straight),
            objective=lambda m: phase_objective(m, "delta_x"),
            history=history,
            iter_id=start_iter + polish_round,
            phase="C-polish",
            sub_iter=1,
            is_valid_metrics=lambda m, angle_lock=x_ang_lock, dy_lock=x_dy_lock: abs(m["delta_ang_deg"]) <= angle_lock
            and abs(m["delta_y"]) <= dy_lock,
        )
        metrics = m_best
        changed_any = changed_any or changed
        if passed(metrics, args):
            return metrics, arc_step, x_step, straight_step, True

        # Y micro-polish while holding X/angle near current best.
        y_ang_lock = max(abs(metrics["delta_ang_deg"]) + 0.0002, 0.001)
        y_dx_lock = max(abs(metrics["delta_x"]) + 0.002, 0.01)
        m_best, straight_step, changed = tune_once(
            track_xml=track_xml,
            runtime_dir=runtime_dir,
            category=category,
            name=name,
            seg_name=primary_straight,
            att_name="lg",
            step=max(straight_step, min_straight),
            objective=lambda m: phase_objective(m, "delta_y"),
            history=history,
            iter_id=start_iter + polish_round,
            phase="B-polish",
            sub_iter=1,
            is_valid_metrics=lambda m, angle_lock=y_ang_lock, dx_lock=y_dx_lock: abs(m["delta_ang_deg"]) <= angle_lock
            and abs(m["delta_x"]) <= dx_lock,
        )
        metrics = m_best
        changed_any = changed_any or changed
        if passed(metrics, args):
            return metrics, arc_step, x_step, straight_step, True

    return metrics, arc_step, x_step, straight_step, changed_any


def resolve_report_path(args: argparse.Namespace, config_path: pathlib.Path) -> pathlib.Path:
    if args.report:
        return pathlib.Path(args.report)
    return config_path.with_name(config_path.stem + "-report.json")


def build_selection_config(track_xml: pathlib.Path, args: argparse.Namespace, segs: list[dict], controls: dict) -> dict:
    return {
        "schema": 1,
        "track_xml": str(track_xml),
        "category": args.category,
        "name": args.name,
        "track_segments_sha256": track_segments_fingerprint(segs),
        "controls": controls,
        "steps": {
            "straight": args.straight_step,
            "arc": args.arc_step,
            "x_straight": args.straight_step,
            "radius": args.straight_step,
            "min_straight": args.min_straight_step,
            "min_arc": args.min_arc_step,
        },
    }


def load_or_select_config(
    config_path: pathlib.Path,
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    segs: list[dict],
    metrics: dict,
) -> dict:
    if config_path.exists() and not args.force_reselect:
        loaded_config = json.loads(config_path.read_text(encoding="utf-8"))
        if config_matches_track(loaded_config, args, track_xml, segs):
            return loaded_config
        print(f"Existing selection config is stale, reselecting controls: {config_path}")

    controls = pick_controls(segs)
    with trackgen_phase("select-turn"):
        controls = refine_turn_controls_by_probe(track_xml, runtime_dir, args.category, args.name, segs, controls, metrics)
    with trackgen_phase("select-y"):
        controls = refine_y_controls_by_probe(track_xml, runtime_dir, args.category, args.name, segs, controls, metrics)
    with trackgen_phase("select-x"):
        controls = refine_x_controls_by_probe(track_xml, runtime_dir, args.category, args.name, segs, controls, metrics)

    config = build_selection_config(track_xml, args, segs, controls)
    write_json(config_path, config)
    return config


def is_baseline_ready(metrics: dict, args: argparse.Namespace) -> bool:
    return (
        abs(metrics["delta_x"]) <= args.max_baseline_dx
        and abs(metrics["delta_y"]) <= args.max_baseline_dy
        and abs(metrics["delta_ang_deg"]) <= args.max_baseline_ang
    )


def report_targets(args: argparse.Namespace) -> dict:
    return {
        "delta_x": args.target_dx,
        "delta_y": args.target_dy,
        "delta_z": args.target_dz,
        "delta_ang_deg": args.target_ang,
    }


def report_baseline_limits(args: argparse.Namespace) -> dict:
    return {
        "delta_x": args.max_baseline_dx,
        "delta_y": args.max_baseline_dy,
        "delta_ang_deg": args.max_baseline_ang,
    }


def build_baseline_only_report(metrics: dict, args: argparse.Namespace, baseline_ready: bool) -> dict:
    return {
        "schema": 1,
        "ok": baseline_ready,
        "baseline_ready": baseline_ready,
        "targets": report_targets(args),
        "baseline_limits": report_baseline_limits(args),
        "final_metrics": metrics,
        "stats": runtime_stats(),
        "history": [{"iter": 0, "metrics": metrics, "action": "baseline"}],
    }


def build_baseline_not_ready_report(
    metrics: dict,
    args: argparse.Namespace,
    controls: dict,
    best_gap: float,
    plateau_count: int,
    history: list[dict],
    elapsed: float,
) -> dict:
    return {
        "schema": 1,
        "ok": False,
        "baseline_ready": False,
        "elapsed_seconds": elapsed,
        "controls": controls,
        "targets": report_targets(args),
        "baseline_limits": report_baseline_limits(args),
        "final_metrics": metrics,
        "stats": runtime_stats(),
        "best_gap": best_gap,
        "plateau_count": plateau_count,
        "history": history,
    }


def run_linear_polish_rounds(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    metrics: dict,
    history: list[dict],
    best_gap: float,
    best_metrics: dict,
    best_text: str,
    plateau_count: int,
    ok: bool,
) -> tuple[dict, dict, str, float, int, bool]:
    if ok or not args.linear_polish or args.linear_polish_rounds <= 0:
        return metrics, best_metrics, best_text, best_gap, plateau_count, ok

    for linear_round in range(1, args.linear_polish_rounds + 1):
        metrics, changed = linear_polish_once(
            track_xml=track_xml,
            runtime_dir=runtime_dir,
            category=args.category,
            name=args.name,
            metrics=metrics,
            args=args,
            history=history,
            iter_id=linear_round,
        )
        cur_gap = closure_gap(metrics, args)
        if cur_gap + 1e-12 < best_gap:
            best_gap = cur_gap
            best_metrics = dict(metrics)
            best_text = track_xml.read_text(encoding="utf-8")
            plateau_count = 0
        print(
            f"Linear {linear_round}: dx={metrics['delta_x']:.6f} dy={metrics['delta_y']:.6f} "
            f"dz={metrics['delta_z']:.6f} ang={metrics['delta_ang_deg']:.6f}"
        )
        if passed(metrics, args):
            ok = True
            break
        if not changed:
            break

    return metrics, best_metrics, best_text, best_gap, plateau_count, ok


def build_final_report(
    ok: bool,
    elapsed: float,
    controls: dict,
    args: argparse.Namespace,
    metrics: dict,
    best_gap: float,
    plateau_count: int,
    history: list[dict],
) -> dict:
    return {
        "schema": 1,
        "ok": ok,
        "elapsed_seconds": elapsed,
        "controls": controls,
        "targets": report_targets(args),
        "final_metrics": metrics,
        "stats": runtime_stats(),
        "best_gap": best_gap,
        "plateau_count": plateau_count,
        "history": history,
    }


def run_near_pass_polish(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    controls: dict,
    metrics: dict,
    history: list[dict],
    best_metrics: dict,
    best_text: str,
    best_gap: float,
    ok: bool,
    arc_step: float,
    x_step: float,
    straight_step: float,
    min_arc: float,
    min_straight: float,
) -> tuple[dict, dict, str, float, bool]:
    if ok or best_gap >= 0.05:
        return metrics, best_metrics, best_text, best_gap, ok

    # Once all residuals are small, prefer tiny locked refinements over broad
    # projected jumps.
    track_xml.write_text(best_text, encoding="utf-8")
    metrics = dict(best_metrics)
    metrics, _arc_step, _x_step, _straight_step, _ = polish_near_pass(
        track_xml=track_xml,
        runtime_dir=runtime_dir,
        category=args.category,
        name=args.name,
        controls=controls,
        metrics=metrics,
        args=args,
        history=history,
        start_iter=max(1, args.max_iters) + 100,
        arc_step=arc_step,
        x_step=x_step,
        straight_step=straight_step,
        min_arc=min_arc,
        min_straight=min_straight,
    )
    if passed(metrics, args):
        ok = True
    else:
        cur_gap = closure_gap(metrics, args)
        if cur_gap + 1e-12 < best_gap:
            best_gap = cur_gap
            best_metrics = dict(metrics)
            best_text = track_xml.read_text(encoding="utf-8")
    return metrics, best_metrics, best_text, best_gap, ok


def restore_best_state_if_failed(track_xml: pathlib.Path, metrics: dict, best_metrics: dict, best_text: str, ok: bool) -> dict:
    if ok:
        return metrics
    track_xml.write_text(best_text, encoding="utf-8")
    return best_metrics


def persist_final_outputs(
    config_path: pathlib.Path,
    report_path: pathlib.Path,
    config: dict,
    controls: dict,
    ok: bool,
    elapsed: float,
    args: argparse.Namespace,
    metrics: dict,
    best_gap: float,
    plateau_count: int,
    history: list[dict],
) -> None:
    config["controls"] = controls
    write_json(config_path, config)
    write_json(report_path, build_final_report(ok, elapsed, controls, args, metrics, best_gap, plateau_count, history))


def run_phase_a_angle(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    metrics: dict,
    history: list[dict],
    iter_id: int,
    primary_turn: str,
    arc_step: float,
    min_arc: float,
    valid_turn_arc,
) -> tuple[dict, float, bool]:
    for k in range(max(1, args.phase_iters)):
        m_best, arc_step, changed = tune_projected(
            track_xml=track_xml,
            runtime_dir=runtime_dir,
            category=args.category,
            name=args.name,
            seg_name=primary_turn,
            att_name="arc",
            step=arc_step,
            objective=lambda m: phase_objective(m, "delta_ang_deg"),
            history=history,
            iter_id=iter_id,
            phase="A",
            sub_iter=k + 1,
            target_key="delta_ang_deg",
            current_metrics=metrics,
            is_valid_value=valid_turn_arc,
        )
        metrics = m_best
        if not changed:
            if arc_step > min_arc:
                continue
            break
        if abs(metrics["delta_ang_deg"]) <= args.target_ang:
            break
    return metrics, arc_step, passed(metrics, args)


def run_phase_b_y(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    metrics: dict,
    history: list[dict],
    iter_id: int,
    primary_straight: str,
    y_turn: str,
    straight_step: float,
    radius_step: float,
    valid_turn_radius,
) -> tuple[dict, float, float, float, bool]:
    ang_lock = max(abs(metrics["delta_ang_deg"]), args.target_ang) + 1e-12
    for k in range(max(1, args.phase_iters)):
        m_best, straight_step, changed = tune_once(
            track_xml=track_xml,
            runtime_dir=runtime_dir,
            category=args.category,
            name=args.name,
            seg_name=primary_straight,
            att_name="lg",
            step=straight_step,
            objective=lambda m: phase_objective(m, "delta_y"),
            history=history,
            iter_id=iter_id,
            phase="B",
            sub_iter=k + 1,
            is_valid_metrics=lambda m, angle_lock=ang_lock: abs(m["delta_ang_deg"]) <= angle_lock,
        )
        metrics = m_best
        if not changed:
            break
        if abs(metrics["delta_y"]) <= args.target_dy:
            break

    if abs(metrics["delta_y"]) > args.target_dy and y_turn:
        for k in range(max(1, args.phase_iters // 2)):
            try:
                m_best, radius_step, changed = tune_once(
                    track_xml=track_xml,
                    runtime_dir=runtime_dir,
                    category=args.category,
                    name=args.name,
                    seg_name=y_turn,
                    att_name="radius",
                    step=radius_step,
                    objective=lambda m: phase_objective(m, "delta_y"),
                    history=history,
                    iter_id=iter_id,
                    phase="B-radius",
                    sub_iter=k + 1,
                    is_valid_value=valid_turn_radius,
                    is_valid_metrics=lambda m, angle_lock=ang_lock: abs(m["delta_ang_deg"]) <= angle_lock,
                )
            except RuntimeError:
                break
            metrics = m_best
            if not changed:
                break

    return metrics, straight_step, radius_step, ang_lock, passed(metrics, args)


def phase_c_reset_step(metrics: dict, args: argparse.Namespace, x_step: float, x_step_initial: float, min_straight: float) -> float:
    if abs(metrics["delta_y"]) <= max(args.target_dy * 8.0, 0.01) and x_step < max(min_straight, x_step_initial * 0.25):
        return x_step_initial
    return x_step


def phase_c_select_x_control(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    metrics: dict,
    controls: dict,
    x_straight: str,
    backup_straight: str,
    primary_straight: str,
    x_step: float,
    x_step_initial: float,
) -> tuple[str, str, float]:
    x_fallback_name = x_straight or backup_straight or primary_straight
    x_control = x_fallback_name
    if args.runtime_x_reselect or not x_straight:
        with trackgen_phase("C-x-reselect"):
            x_control = choose_runtime_x_control(
                track_xml=track_xml,
                runtime_dir=runtime_dir,
                category=args.category,
                name=args.name,
                current_metrics=metrics,
                fallback_name=x_fallback_name,
                ang_lock=max(abs(metrics["delta_ang_deg"]) + 0.0002, 0.001),
                y_lock=max(abs(metrics["delta_y"]) + 0.01, 0.05),
                probe_step=max(1.0, x_step_initial),
            )
    if x_control != x_fallback_name:
        controls["x_straight"] = x_control
        return x_control, x_control, x_step_initial
    return x_control, x_straight, x_step


def run_phase_c_tuning_loop(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    metrics: dict,
    history: list[dict],
    iter_id: int,
    x_control: str,
    x_step: float,
    min_straight: float,
    ang_lock: float,
    y_lock: float,
) -> tuple[dict, float, bool]:
    c_changed = False
    for k in range(max(1, args.phase_iters)):
        if abs(metrics["delta_x"]) <= args.target_dx:
            break
        m_best, x_step, changed = tune_projected(
            track_xml=track_xml,
            runtime_dir=runtime_dir,
            category=args.category,
            name=args.name,
            seg_name=x_control,
            att_name="lg",
            step=x_step,
            objective=lambda m: phase_objective(m, "delta_x"),
            history=history,
            iter_id=iter_id,
            phase="C",
            sub_iter=k + 1,
            target_key="delta_x",
            current_metrics=metrics,
            is_valid_metrics=lambda m, angle_lock=ang_lock, lateral_lock=y_lock: abs(m["delta_ang_deg"]) <= angle_lock
            and abs(m["delta_y"]) <= lateral_lock,
            max_jump_multiplier=64.0,
            use_cached_slope=True,
        )
        metrics = m_best
        if changed:
            c_changed = True
        elif x_step > min_straight:
            continue
        else:
            break
        if abs(metrics["delta_x"]) <= args.target_dx:
            break
    return metrics, x_step, c_changed


def run_phase_c_x(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    metrics: dict,
    history: list[dict],
    iter_id: int,
    controls: dict,
    x_straight: str,
    backup_straight: str,
    primary_straight: str,
    x_step: float,
    x_step_initial: float,
    min_straight: float,
    ang_lock: float,
) -> tuple[dict, float, str, bool, bool]:
    y_lock = max(abs(metrics["delta_y"]), args.target_dy) + 1e-12
    x_step = phase_c_reset_step(metrics, args, x_step, x_step_initial, min_straight)
    x_control, x_straight, x_step = phase_c_select_x_control(
        track_xml,
        runtime_dir,
        args,
        metrics,
        controls,
        x_straight,
        backup_straight,
        primary_straight,
        x_step,
        x_step_initial,
    )
    metrics, x_step, c_changed = run_phase_c_tuning_loop(track_xml, runtime_dir, args, metrics, history, iter_id, x_control, x_step, min_straight, ang_lock, y_lock)

    return metrics, x_step, x_straight, c_changed, passed(metrics, args)


def should_run_x_structure_fallback(
    args: argparse.Namespace,
    metrics: dict,
    c_changed: bool,
    c_start_dx: float,
    x_fallback_attempts: int,
    x_fallback_max: int,
) -> bool:
    return (
        args.allow_x_structure_fallback
        and abs(metrics["delta_x"]) > args.target_dx
        and ((not c_changed) or (c_start_dx - abs(metrics["delta_x"]) < 0.05))
        and x_fallback_attempts < x_fallback_max
    )


def probe_x_structure_candidate(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    metrics: dict,
    before_text: str,
    segs_now: list[dict],
    cand: dict,
) -> tuple[dict | None, float]:
    try:
        probe_name = unique_name({s["name"] for s in segs_now}, "x_probe_straight")
        probe_text, _ = split_turn_with_straight_insert(before_text, cand["name"], probe_name, 1.0)
        track_xml.write_text(probe_text, encoding="utf-8")
        with trackgen_phase("C-fallback"):
            probe_m, _ = run_trackgen_z(runtime_dir, args.category, args.name, track_xml)
        slope = probe_m["delta_x"] - metrics["delta_x"]
        if slope * metrics["delta_x"] < -1e-4:
            return cand, max(1.0, min(12.0, abs(metrics["delta_x"] / slope)))
    except RuntimeError:
        pass
    finally:
        track_xml.write_text(before_text, encoding="utf-8")
    return None, 0.0


def choose_x_structure_fallback(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    metrics: dict,
    before_text: str,
    segs_now: list[dict],
) -> tuple[dict | None, float]:
    for item in find_x_comp_turn_candidates(segs_now)[:8]:
        chosen, chosen_need = probe_x_structure_candidate(track_xml, runtime_dir, args, metrics, before_text, segs_now, item["seg"])
        if chosen is not None:
            return chosen, chosen_need
    return None, 0.0


def x_structure_fallback_guard_pass(metrics: dict, m_new: dict) -> bool:
    ang_guard = max(abs(metrics["delta_ang_deg"]) * 6.0, 0.05)
    y_guard = max(abs(metrics["delta_y"]) * 6.0, 12.0)
    return abs(m_new["delta_ang_deg"]) <= ang_guard and abs(m_new["delta_y"]) <= y_guard


def append_x_structure_fallback_history(
    history: list[dict],
    iter_id: int,
    x_fallback_attempts: int,
    chosen: dict,
    pre_name: str,
    x_comp_name: str,
    insert_lg: float,
    metrics: dict,
) -> None:
    history.append(
        {
            "iter": iter_id,
            "phase": "C-fallback",
            "sub_iter": x_fallback_attempts,
            "action": f"split {chosen['name']} -> {pre_name} + {x_comp_name}({insert_lg:.6f}m) + {chosen['name']}",
            "metrics": metrics,
            "objective": abs(metrics["delta_x"]),
        }
    )


def apply_x_structure_fallback(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    metrics: dict,
    history: list[dict],
    iter_id: int,
    controls: dict,
    x_straight: str,
    x_fallback_attempts: int,
    before_text: str,
    chosen: dict,
    insert_lg: float,
    x_comp_name: str,
) -> tuple[dict, str, int, bool]:
    try:
        after_text, pre_name = split_turn_with_straight_insert(before_text, chosen["name"], x_comp_name, insert_lg)
        track_xml.write_text(after_text, encoding="utf-8")
        with trackgen_phase("C-fallback"):
            m_new, _ = run_trackgen_z(runtime_dir, args.category, args.name, track_xml)
        if x_structure_fallback_guard_pass(metrics, m_new):
            controls["x_straight"] = x_comp_name
            x_fallback_attempts += 1
            if args.verbose:
                print(f"Iter {iter_id}: inserted fallback X straight '{x_comp_name}' ({insert_lg:.3f} m) in '{chosen['name']}'")
            append_x_structure_fallback_history(history, iter_id, x_fallback_attempts, chosen, pre_name, x_comp_name, insert_lg, m_new)
            return m_new, x_comp_name, x_fallback_attempts, True
        if args.verbose:
            print(
                f"Iter {iter_id}: rejected fallback insertion in '{chosen['name']}' "
                f"(guard fail: dy={m_new['delta_y']:.6f}, ang={m_new['delta_ang_deg']:.6f})"
            )
    except RuntimeError:
        pass
    track_xml.write_text(before_text, encoding="utf-8")
    return metrics, x_straight, x_fallback_attempts, False


def run_x_structure_fallback(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    metrics: dict,
    history: list[dict],
    iter_id: int,
    controls: dict,
    x_straight: str,
    c_changed: bool,
    c_start_dx: float,
    x_fallback_attempts: int,
    x_fallback_max: int,
) -> tuple[dict, str, int, bool]:
    if not should_run_x_structure_fallback(args, metrics, c_changed, c_start_dx, x_fallback_attempts, x_fallback_max):
        return metrics, x_straight, x_fallback_attempts, c_changed

    before_text = track_xml.read_text(encoding="utf-8")
    segs_now = parse_top_level_segments(before_text)
    chosen, chosen_need = choose_x_structure_fallback(track_xml, runtime_dir, args, metrics, before_text, segs_now)

    if chosen is None:
        return metrics, x_straight, x_fallback_attempts, c_changed

    names_used = {s["name"] for s in segs_now}
    x_comp_name = unique_name(names_used, "x_comp_straight")
    metrics, x_straight, x_fallback_attempts, applied = apply_x_structure_fallback(
        track_xml,
        runtime_dir,
        args,
        metrics,
        history,
        iter_id,
        controls,
        x_straight,
        x_fallback_attempts,
        before_text,
        chosen,
        chosen_need,
        x_comp_name,
    )
    return metrics, x_straight, x_fallback_attempts, c_changed or applied


def update_broad_loop_progress(
    track_xml: pathlib.Path,
    args: argparse.Namespace,
    metrics: dict,
    history: list[dict],
    iter_id: int,
    straight_step: float,
    x_step: float,
    radius_step: float,
    arc_step: float,
    min_straight: float,
    min_arc: float,
    best_gap: float,
    best_metrics: dict,
    best_text: str,
    plateau_count: int,
) -> tuple[dict, str, float, int, bool, bool]:
    print(
        f"Iter {iter_id}: dx={metrics['delta_x']:.6f} dy={metrics['delta_y']:.6f} "
        f"dz={metrics['delta_z']:.6f} ang={metrics['delta_ang_deg']:.6f} "
        f"steps(lgY={straight_step:.6g}, lgX={x_step:.6g}, r={radius_step:.6g}, arc={arc_step:.6g})"
    )

    if passed(metrics, args):
        return best_metrics, best_text, best_gap, plateau_count, True, True

    cur_gap = closure_gap(metrics, args)
    if cur_gap + 1e-12 < best_gap:
        best_gap = cur_gap
        best_metrics = dict(metrics)
        best_text = track_xml.read_text(encoding="utf-8")
        plateau_count = 0
    else:
        plateau_count += 1
        if plateau_count >= max(4, args.plateau_iters):
            history.append({"iter": iter_id, "action": "plateau-stop", "metrics": metrics, "gap": cur_gap})
            return best_metrics, best_text, best_gap, plateau_count, False, True

    if straight_step < min_straight and x_step < min_straight and radius_step < min_straight and arc_step < min_arc:
        return best_metrics, best_text, best_gap, plateau_count, False, True

    return best_metrics, best_text, best_gap, plateau_count, False, False


def handle_baseline_only(report_path: pathlib.Path, metrics: dict, args: argparse.Namespace, baseline_ready: bool) -> int:
    write_json(report_path, build_baseline_only_report(metrics, args, baseline_ready))
    print(
        f"Baseline closure: dx={metrics['delta_x']:.6f} dy={metrics['delta_y']:.6f} "
        f"dz={metrics['delta_z']:.6f} ang={metrics['delta_ang_deg']:.6f}"
    )
    print(f"Wrote report: {report_path}")
    return 0 if baseline_ready else 1


def handle_select_only(config_path: pathlib.Path, config: dict) -> int:
    print(f"Wrote selection config: {config_path}")
    print(json.dumps(config["controls"], indent=2))
    return 0


def close_loop_step_settings(config: dict, args: argparse.Namespace) -> tuple[float, float, float, float, float, float]:
    steps = config.get("steps", {})
    straight_step = float(steps.get("straight", args.straight_step))
    arc_step = float(steps.get("arc", args.arc_step))
    x_step = float(steps.get("x_straight", straight_step))
    radius_step = float(steps.get("radius", straight_step))
    min_straight = float(steps.get("min_straight", args.min_straight_step))
    min_arc = float(steps.get("min_arc", args.min_arc_step))
    return straight_step, arc_step, x_step, radius_step, min_straight, min_arc


def reuse_existing_x_comp_straight(track_xml: pathlib.Path, controls: dict, x_straight: str) -> str:
    if x_straight:
        return x_straight
    segs_now = parse_top_level_segments(track_xml.read_text(encoding="utf-8"))
    x_comp = [s for s in segs_now if s["name"].startswith("x_comp_straight") and s["attrs"].get("type") == "str"]
    if not x_comp:
        return ""
    x_comp = sorted(x_comp, key=lambda s: to_float(s["attrs"].get("lg"), 0.0), reverse=True)
    controls["x_straight"] = x_comp[0]["name"]
    return controls["x_straight"]


def valid_turn_arc_for_type(turn_type: str, v: float) -> bool:
    if turn_type in ("lft", "rgt"):
        return 0.000001 <= v <= 359.999999
    return True


def valid_turn_radius(v: float) -> bool:
    return 2.0 <= v <= 100000.0


def handle_baseline_not_ready(
    config_path: pathlib.Path,
    report_path: pathlib.Path,
    config: dict,
    controls: dict,
    metrics: dict,
    args: argparse.Namespace,
    best_gap: float,
    plateau_count: int,
    history: list[dict],
) -> int:
    history.append(
        {
            "iter": 0,
            "action": "baseline-not-closure-ready",
            "metrics": metrics,
            "limits": {
                "delta_x": args.max_baseline_dx,
                "delta_y": args.max_baseline_dy,
                "delta_ang_deg": args.max_baseline_ang,
            },
        }
    )
    config["controls"] = controls
    t0 = time.perf_counter()
    elapsed = time.perf_counter() - t0
    write_json(config_path, config)
    write_json(report_path, build_baseline_not_ready_report(metrics, args, controls, best_gap, plateau_count, history, elapsed))
    print(f"Wrote report: {report_path}")
    print("Baseline not closure-ready.")
    return 1


def run_broad_closure_loop(
    track_xml: pathlib.Path,
    runtime_dir: pathlib.Path,
    args: argparse.Namespace,
    controls: dict,
    metrics: dict,
    history: list[dict],
    best_gap: float,
    best_metrics: dict,
    best_text: str,
    plateau_count: int,
    primary_straight: str,
    primary_turn: str,
    backup_straight: str,
    x_straight: str,
    y_turn: str,
    straight_step: float,
    arc_step: float,
    x_step: float,
    radius_step: float,
    min_straight: float,
    min_arc: float,
    x_step_initial: float,
    turn_type: str,
) -> tuple[dict, dict, str, float, int, bool, float, float, float, float, str]:
    ok = False
    x_fallback_attempts = 0
    x_fallback_max = 1
    for it in range(1, max(1, args.max_iters) + 1):
        metrics, arc_step, ok = run_phase_a_angle(
            track_xml, runtime_dir, args, metrics, history, it, primary_turn, arc_step, min_arc, lambda v: valid_turn_arc_for_type(turn_type, v)
        )
        if ok:
            break
        metrics, straight_step, radius_step, ang_lock, ok = run_phase_b_y(
            track_xml, runtime_dir, args, metrics, history, it, primary_straight, y_turn, straight_step, radius_step, valid_turn_radius
        )
        if ok:
            break
        c_start_dx = abs(metrics["delta_x"])
        metrics, x_step, x_straight, c_changed, ok = run_phase_c_x(
            track_xml,
            runtime_dir,
            args,
            metrics,
            history,
            it,
            controls,
            x_straight,
            backup_straight,
            primary_straight,
            x_step,
            x_step_initial,
            min_straight,
            ang_lock,
        )
        metrics, x_straight, x_fallback_attempts, c_changed = run_x_structure_fallback(
            track_xml, runtime_dir, args, metrics, history, it, controls, x_straight, c_changed, c_start_dx, x_fallback_attempts, x_fallback_max
        )
        best_metrics, best_text, best_gap, plateau_count, ok, stop_loop = update_broad_loop_progress(
            track_xml,
            args,
            metrics,
            history,
            it,
            straight_step,
            x_step,
            radius_step,
            arc_step,
            min_straight,
            min_arc,
            best_gap,
            best_metrics,
            best_text,
            plateau_count,
        )
        if stop_loop:
            break
    return metrics, best_metrics, best_text, best_gap, plateau_count, ok, straight_step, arc_step, x_step, radius_step, x_straight


def main() -> int:
    args = parse_args()
    track_xml = pathlib.Path(args.track_xml)
    runtime_dir = pathlib.Path(args.runtime_dir)
    config_path = pathlib.Path(args.config)
    report_path = resolve_report_path(args, config_path)

    text = track_xml.read_text(encoding="utf-8")
    segs = parse_top_level_segments(text)

    seg_attrs_by_name = {s["name"]: s["attrs"] for s in segs}
    with trackgen_phase("baseline"):
        metrics, _ = run_trackgen_z(runtime_dir, args.category, args.name, track_xml)

    baseline_ready = is_baseline_ready(metrics, args)

    if args.baseline_only:
        return handle_baseline_only(report_path, metrics, args, baseline_ready)

    config = load_or_select_config(config_path, track_xml, runtime_dir, args, segs, metrics)

    if args.select_only:
        return handle_select_only(config_path, config)

    controls = config["controls"]
    primary_straight = controls["primary_straight"]
    primary_turn = controls["primary_turn"]
    backup_straight = controls.get("backup_straight", "")
    x_straight = controls.get("x_straight", backup_straight)
    y_turn = controls.get("y_turn", primary_turn)

    if x_straight and x_straight not in seg_attrs_by_name:
        x_straight = ""
        controls["x_straight"] = ""

    straight_step, arc_step, x_step, radius_step, min_straight, min_arc = close_loop_step_settings(config, args)
    x_step_initial = x_step

    x_straight = reuse_existing_x_comp_straight(track_xml, controls, x_straight)

    history = [{"iter": 0, "metrics": metrics, "action": "baseline"}]
    print(
        f"Baseline closure: dx={metrics['delta_x']:.6f} dy={metrics['delta_y']:.6f} "
        f"dz={metrics['delta_z']:.6f} ang={metrics['delta_ang_deg']:.6f}"
    )

    t0 = time.perf_counter()
    ok = passed(metrics, args)
    best_text = track_xml.read_text(encoding="utf-8")
    best_metrics = dict(metrics)
    best_gap = closure_gap(metrics, args)
    plateau_count = 0
    turn_type = str(seg_attrs_by_name.get(primary_turn, {}).get("type", "")).lower()

    if not baseline_ready:
        return handle_baseline_not_ready(config_path, report_path, config, controls, metrics, args, best_gap, plateau_count, history)

    metrics, best_metrics, best_text, best_gap, plateau_count, ok = run_linear_polish_rounds(
        track_xml=track_xml,
        runtime_dir=runtime_dir,
        args=args,
        metrics=metrics,
        history=history,
        best_gap=best_gap,
        best_metrics=best_metrics,
        best_text=best_text,
        plateau_count=plateau_count,
        ok=ok,
    )

    if not ok:
        metrics, best_metrics, best_text, best_gap, plateau_count, ok, straight_step, arc_step, x_step, radius_step, x_straight = run_broad_closure_loop(
            track_xml,
            runtime_dir,
            args,
            controls,
            metrics,
            history,
            best_gap,
            best_metrics,
            best_text,
            plateau_count,
            primary_straight,
            primary_turn,
            backup_straight,
            x_straight,
            y_turn,
            straight_step,
            arc_step,
            x_step,
            radius_step,
            min_straight,
            min_arc,
            x_step_initial,
            turn_type,
        )

    metrics, best_metrics, best_text, best_gap, ok = run_near_pass_polish(
        track_xml=track_xml,
        runtime_dir=runtime_dir,
        args=args,
        controls=controls,
        metrics=metrics,
        history=history,
        best_metrics=best_metrics,
        best_text=best_text,
        best_gap=best_gap,
        ok=ok,
        arc_step=arc_step,
        x_step=x_step,
        straight_step=straight_step,
        min_arc=min_arc,
        min_straight=min_straight,
    )

    # Always keep the best reached state, even on failed run.
    metrics = restore_best_state_if_failed(track_xml, metrics, best_metrics, best_text, ok)

    elapsed = time.perf_counter() - t0

    # Persist potentially updated control choices (e.g. inserted X-comp straight)
    # so reruns remain deterministic.
    persist_final_outputs(config_path, report_path, config, controls, ok, elapsed, args, metrics, best_gap, plateau_count, history)
    print(f"Wrote report: {report_path}")
    if ok:
        print("Closure targets satisfied.")
        return 0
    print("Closure targets not met.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
