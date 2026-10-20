#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : polyline_to_torcs.py
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

"""Convert cached centerline polyline to a simplified TORCS segment chain.

This implementation follows a sequential fit strategy:
1) start at the first source sample,
2) propose one new segment (str/lft/rgt),
3) optimize its parameters against local endpoint/tangent/shape error,
4) accept only if local error is reasonable,
5) move forward and repeat.

After fitting, the script runs a simplification pass and emits JSON + XML.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import time
from dataclasses import dataclass

from torcs_track_tools.core.polyline import to_xy_dicts

try:
    import numpy as np
    from skimage.measure import approximate_polygon
except ImportError:  # pragma: no cover - dependencies are declared for normal tool use.
    np = None
    approximate_polygon = None


@dataclass
class Pose:
    x: float
    y: float
    heading: float


@dataclass
class FittedSegment:
    name: str
    seg_type: str  # str|lft|rgt
    length: float
    arc_deg: float
    radius: float
    end_radius: float
    z_end: float
    i0: int
    i1: int


@dataclass
class FitState:
    # Current source cursor (inclusive index in sampled source points).
    idx: int
    # Current model pose at the cursor.
    pose: Pose
    # Built segments so far.
    segments: list[FittedSegment]
    # Reconstructed model points from origin to cursor.
    model_points: list[dict]
    # Objective terms.
    rmse: float
    max_dev: float
    head_err_deg: float
    score: float


BeamCandidate = tuple[int, str, float, float, float, float, float, Pose]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sequential polyline -> TORCS segment conversion")
    parser.add_argument("--input", required=True, help="Input centerline cache JSON")
    parser.add_argument("--output-json", required=True, help="Output segment JSON")
    parser.add_argument("--output-xml", required=True, help="Output segment XML snippet")
    parser.add_argument("--output-svg", default="", help="Optional output overlay SVG path")
    parser.add_argument("--resample-step", type=float, default=3.0, help=argparse.SUPPRESS)
    parser.add_argument("--straight-heading-deg", type=float, default=2.0, help=argparse.SUPPRESS)
    parser.add_argument("--min-seg-len", type=float, default=10.0, help="Minimum segment length in meters")
    parser.add_argument("--max-seg-len", type=float, default=220.0, help=argparse.SUPPRESS)
    parser.add_argument("--length-round", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--arc-round", type=float, default=0.1, help=argparse.SUPPRESS)
    parser.add_argument("--fit-pos-threshold", type=float, default=3.0, help=argparse.SUPPRESS)
    parser.add_argument("--fit-head-threshold", type=float, default=1.5, help=argparse.SUPPRESS)
    parser.add_argument("--beam-width", type=int, default=6, help=argparse.SUPPRESS)
    parser.add_argument("--span-stride", type=int, default=2, help=argparse.SUPPRESS)
    parser.add_argument("--global-sample-count", type=int, default=120, help=argparse.SUPPRESS)
    parser.add_argument("--max-beam-iters", type=int, default=1200, help=argparse.SUPPRESS)
    parser.add_argument("--verbose-progress", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--preserve-tail-seam",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--drift-rmse-growth", type=float, default=0.8, help=argparse.SUPPRESS)
    parser.add_argument("--drift-maxdev-growth", type=float, default=2.0, help=argparse.SUPPRESS)
    parser.add_argument("--reject-pos-mult", type=float, default=3.0, help=argparse.SUPPRESS)
    parser.add_argument("--reject-head-mult", type=float, default=3.0, help=argparse.SUPPRESS)
    parser.add_argument("--cleanup-small-wiggles", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-simplify", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cleanup-max-arc-deg", type=float, default=1.2, help=argparse.SUPPRESS)
    parser.add_argument("--cleanup-max-len-m", type=float, default=45.0, help=argparse.SUPPRESS)
    parser.add_argument("--cleanup-neighbor-ratio", type=float, default=0.35, help=argparse.SUPPRESS)
    parser.add_argument("--cleanup-rmse-growth", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--cleanup-maxdev-growth", type=float, default=3.0, help=argparse.SUPPRESS)
    parser.add_argument("--preserve-curvature-anchors", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--anchor-curvature-deg", type=float, default=24.0, help=argparse.SUPPRESS)
    parser.add_argument("--anchor-window", type=int, default=2, help=argparse.SUPPRESS)
    parser.add_argument("--anchor-min-spacing-m", type=float, default=18.0, help=argparse.SUPPRESS)
    parser.add_argument("--corner-fit", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--corner-tolerance", type=float, default=4.0, help=argparse.SUPPRESS)
    parser.add_argument("--corner-trim-max", type=float, default=14.0, help=argparse.SUPPRESS)
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.98,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--max-adaptive-attempts",
        type=int,
        default=6,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(value / step) * step


def norm_angle(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def heading(a: dict, b: dict) -> float:
    return math.atan2(b["y"] - a["y"], b["x"] - a["x"])


def dist(a: dict, b: dict) -> float:
    return math.hypot(b["x"] - a["x"], b["y"] - a["y"])


def resample(poly: list[dict], step: float) -> list[dict]:
    out = [poly[0]]
    carry = 0.0
    for i in range(1, len(poly)):
        a = poly[i - 1]
        b = poly[i]
        L = dist(a, b)
        if L < 1e-9:
            continue
        ux = (b["x"] - a["x"]) / L
        uy = (b["y"] - a["y"]) / L
        d = step - carry
        while d <= L + 1e-9:
            out.append({"x": a["x"] + ux * d, "y": a["y"] + uy * d, "way_name": b.get("way_name", "")})
            d += step
        carry = L - (d - step)
    if dist(out[-1], poly[-1]) > 0.3 * step:
        out.append(poly[-1])
    return out


def source_arc_len(points: list[dict], i0: int, i1: int) -> float:
    total = 0.0
    for i in range(i0, i1):
        total += dist(points[i], points[i + 1])
    return total


def source_loop_len(points: list[dict]) -> float:
    if len(points) < 2:
        return 0.0
    return source_arc_len(points, 0, len(points) - 1) + dist(points[-1], points[0])


def curvature_at(points: list[dict], idx: int, window: int) -> float:
    if idx <= 0 or idx >= len(points) - 1:
        return 0.0
    w = max(1, window)
    i0 = max(0, idx - w)
    i1 = min(len(points) - 1, idx + w)
    if i0 == idx or i1 == idx:
        return 0.0
    h0 = heading(points[i0], points[idx])
    h1 = heading(points[idx], points[i1])
    return abs(math.degrees(norm_angle(h1 - h0)))


def find_curvature_anchors(points: list[dict], threshold_deg: float, window: int, min_spacing_m: float) -> set[int]:
    if len(points) < 5 or threshold_deg <= 0.0:
        return set()
    candidates: list[tuple[int, float]] = []
    for i in range(1, len(points) - 1):
        curv = curvature_at(points, i, window)
        if curv >= threshold_deg:
            candidates.append((i, curv))
    selected: list[int] = []
    for idx, _curv in sorted(candidates, key=lambda item: item[1], reverse=True):
        if all(source_arc_len(points, min(idx, other), max(idx, other)) >= min_spacing_m for other in selected):
            selected.append(idx)
    return set(sorted(selected))


def sample_by_arc(points: list[dict], count: int) -> list[dict]:
    if len(points) <= 1:
        return points[:]
    arr = [{"x": points[0]["x"], "y": points[0]["y"], "s": 0.0}]
    total = 0.0
    for i in range(1, len(points)):
        total += dist(points[i - 1], points[i])
        arr.append({"x": points[i]["x"], "y": points[i]["y"], "s": total})

    out = []
    k = 1
    for i in range(count):
        t = total * i / max(1, count - 1)
        while k < len(arr) and arr[k]["s"] < t:
            k += 1
        if k >= len(arr):
            out.append({"x": arr[-1]["x"], "y": arr[-1]["y"]})
            continue
        a = arr[k - 1]
        b = arr[k]
        u = 0.0 if b["s"] == a["s"] else (t - a["s"]) / (b["s"] - a["s"])
        out.append({"x": a["x"] + u * (b["x"] - a["x"]), "y": a["y"] + u * (b["y"] - a["y"]), "s": t})
    return out


def dominant_way_name(points: list[dict], i0: int, i1: int) -> str:
    counts: dict[str, int] = {}
    for i in range(i0, i1 + 1):
        n = points[i].get("way_name") or "Segment"
        counts[n] = counts.get(n, 0) + 1
    return max(counts, key=counts.get)


def base_segment_name(name: str) -> str:
    """Strip only deterministic numeric suffixes, preserving hyphenated names."""
    return re.sub(r"-\d+$", "", name)


def estimate_boundary_radius(
    points: list[dict],
    idx: int,
    seg_type: str,
    fallback_radius: float,
    length_round: float,
) -> float:
    # Estimate local radius near a boundary index from heading change.
    if seg_type not in ("lft", "rgt"):
        return 0.0

    w = 3
    i0 = max(1, idx - w)
    i1 = min(len(points) - 2, idx + w)
    if i1 <= i0:
        return fallback_radius

    h0 = heading(points[i0 - 1], points[i0])
    h1 = heading(points[i1], points[i1 + 1])
    turn = norm_angle(h1 - h0)
    seg_len = source_arc_len(points, i0, i1 + 1)
    if seg_len < 1e-6:
        return fallback_radius

    kappa = turn / seg_len
    if seg_type == "lft" and kappa <= 1e-6:
        return fallback_radius
    if seg_type == "rgt" and kappa >= -1e-6:
        return fallback_radius

    r = 1.0 / max(1e-6, abs(kappa))
    r = round_to_step(r, length_round)
    r = max(6.0, min(10000.0, r))
    return r


def simulate_segment(
    pose: Pose,
    seg_type: str,
    length: float,
    turn_rad: float,
    end_radius: float | None = None,
) -> tuple[Pose, list[dict], float, float]:
    # Returns end pose, sampled points on segment, radius, arc_deg.
    pts = [{"x": pose.x, "y": pose.y}]
    if seg_type == "str" or abs(turn_rad) < 1e-10:
        end = Pose(
            x=pose.x + length * math.cos(pose.heading),
            y=pose.y + length * math.sin(pose.heading),
            heading=pose.heading,
        )
        pts.append({"x": end.x, "y": end.y})
        return end, pts, 0.0, 0.0

    sign = 1.0 if turn_rad > 0 else -1.0
    radius = length / abs(turn_rad)

    # Variable-radius approximation: integrate short arc pieces using
    # linearly interpolated radius from start to end.
    if end_radius is not None and abs(end_radius - radius) > 1e-6:
        avg_r = max(1e-6, 0.5 * (radius + end_radius))
        n = max(2, int(math.ceil(max(length, avg_r * abs(turn_rad)) / 3.0)))
        dtheta = turn_rad / n
        h = pose.heading
        x = pose.x
        y = pose.y
        for j in range(n):
            t_mid = (j + 0.5) / n
            r_mid = radius + (end_radius - radius) * t_mid
            ds = abs(r_mid * dtheta)
            x += ds * math.cos(h + 0.5 * dtheta)
            y += ds * math.sin(h + 0.5 * dtheta)
            h += dtheta
            pts.append({"x": x, "y": y})
        end = Pose(x=x, y=y, heading=h)
        return end, pts, radius, abs(math.degrees(turn_rad))

    cx = pose.x - sign * radius * math.sin(pose.heading)
    cy = pose.y + sign * radius * math.cos(pose.heading)
    n = max(2, int(math.ceil(length / 3.0)))
    da = turn_rad / n
    h = pose.heading
    x = pose.x
    y = pose.y
    for _ in range(n):
        h += da
        x = cx + sign * radius * math.sin(h)
        y = cy - sign * radius * math.cos(h)
        pts.append({"x": x, "y": y})
    end = Pose(x=x, y=y, heading=h)
    return end, pts, radius, abs(math.degrees(turn_rad))


def sample_line_error(model_pts: list[dict], source_pts: list[dict]) -> float:
    # Compare two short polylines by arc-position interpolation on source.
    if len(source_pts) < 2 or len(model_pts) < 2:
        return 0.0

    # Build source cumulative arc.
    src = [{"x": source_pts[0]["x"], "y": source_pts[0]["y"], "s": 0.0}]
    total = 0.0
    for i in range(1, len(source_pts)):
        total += dist(source_pts[i - 1], source_pts[i])
        src.append({"x": source_pts[i]["x"], "y": source_pts[i]["y"], "s": total})

    errs = []
    for j, p in enumerate(model_pts):
        t = total * j / max(1, len(model_pts) - 1)
        k = 1
        while k < len(src) and src[k]["s"] < t:
            k += 1
        if k >= len(src):
            q = src[-1]
        else:
            a = src[k - 1]
            b = src[k]
            u = 0.0 if b["s"] == a["s"] else (t - a["s"]) / (b["s"] - a["s"])
            q = {"x": a["x"] + u * (b["x"] - a["x"]), "y": a["y"] + u * (b["y"] - a["y"])}
        errs.append(math.hypot(p["x"] - q["x"], p["y"] - q["y"]))
    return math.sqrt(sum(e * e for e in errs) / len(errs))


def global_path_error(model_pts: list[dict], src_pts: list[dict], sample_count: int = 120) -> tuple[float, float]:
    # Compare whole covered prefix from origin without rigid transform.
    if len(model_pts) < 2 or len(src_pts) < 2:
        return 0.0, 0.0
    n = max(40, min(max(40, int(sample_count)), len(src_pts)))
    ms = sample_by_arc(model_pts, n)
    ss = sample_by_arc(src_pts, n)
    errs = [math.hypot(ms[i]["x"] - ss[i]["x"], ms[i]["y"] - ss[i]["y"]) for i in range(n)]
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
    return rmse, max(errs)


def closure_pose_error(end_pose: Pose, start_pose: Pose) -> tuple[float, float]:
    pos_err = math.hypot(end_pose.x - start_pose.x, end_pose.y - start_pose.y)
    head_err = abs(math.degrees(norm_angle(end_pose.heading - start_pose.heading)))
    return pos_err, head_err


def reconstruct_from_segments(start_pose: Pose, segments: list[FittedSegment]) -> list[dict]:
    pts = [{"x": start_pose.x, "y": start_pose.y}]
    pose = start_pose
    for s in segments:
        turn = 0.0 if s.seg_type == "str" else math.radians(s.arc_deg) * (1.0 if s.seg_type == "lft" else -1.0)
        end, seg_pts, _, _ = simulate_segment(
            pose,
            s.seg_type,
            s.length,
            turn,
            None if s.seg_type == "str" else s.end_radius,
        )
        pts.extend(seg_pts[1:])
        pose = end
    return pts


def end_pose_from_segments(start_pose: Pose, segments: list[FittedSegment]) -> Pose:
    pose = start_pose
    for s in segments:
        turn = 0.0 if s.seg_type == "str" else math.radians(s.arc_deg) * (1.0 if s.seg_type == "lft" else -1.0)
        pose, _, _, _ = simulate_segment(
            pose,
            s.seg_type,
            s.length,
            turn,
            None if s.seg_type == "str" else s.end_radius,
        )
    return pose


def append_closure_helpers(
    segments: list[FittedSegment],
    start_pose: Pose,
    length_round: float,
    arc_round: float,
) -> tuple[list[FittedSegment], dict]:
    # Closure helper synthesis is currently disabled. It introduced large seam
    # distortions on some tracks and was less reliable than preserving end-pose
    # during fitting/simplification.
    end_pose = end_pose_from_segments(start_pose, segments) if segments else start_pose
    close_pos_err, close_head_err = closure_pose_error(end_pose, start_pose)
    return segments, {
        "applied": False,
        "disabled": True,
        "position_error_m": close_pos_err,
        "heading_error_deg": close_head_err,
        "helpers": [],
    }


def write_svg(path: pathlib.Path, src: list[dict], rec: list[dict]) -> None:
    pts = src + rec
    min_x = min(p["x"] for p in pts)
    max_x = max(p["x"] for p in pts)
    min_y = min(p["y"] for p in pts)
    max_y = max(p["y"] for p in pts)
    w = 1400.0
    h = 1400.0
    pad = 30.0
    sx = (w - 2 * pad) / max(1e-6, max_x - min_x)
    sy = (h - 2 * pad) / max(1e-6, max_y - min_y)
    s = min(sx, sy)

    def mp(pt: dict) -> str:
        x = pad + (pt["x"] - min_x) * s
        y = h - (pad + (pt["y"] - min_y) * s)
        return f"{x:.2f},{y:.2f}"

    src_poly = " ".join(mp(p) for p in src)
    rec_poly = " ".join(mp(p) for p in rec)
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{int(w)}" height="{int(h)}" viewBox="0 0 {int(w)} {int(h)}">
  <rect x="0" y="0" width="{int(w)}" height="{int(h)}" fill="#111217"/>
  <polyline points="{src_poly}" fill="none" stroke="#ff5a5a" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>
  <polyline points="{rec_poly}" fill="none" stroke="#f4f4f4" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
  <rect x="20" y="20" width="410" height="78" rx="8" fill="#00000088"/>
  <text x="34" y="50" fill="#ff5a5a" font-family="Consolas, monospace" font-size="20">Source centerline</text>
  <text x="34" y="78" fill="#f4f4f4" font-family="Consolas, monospace" font-size="20">Sequential fitted centerline</text>
</svg>
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def fit_single_segment(
    points: list[dict],
    pose: Pose,
    i0: int,
    i1: int,
    straight_heading_deg: float,
    length_round: float,
    arc_round: float,
) -> tuple[str, float, float, float, float, float, Pose]:
    # Returns seg_type, length, radius, end_radius, arc_deg, score, end_pose.
    src_end = points[i1]
    src_h_start = heading(points[i0], points[i0 + 1])
    src_h_end = heading(points[i1 - 1], points[i1])
    src_turn = norm_angle(src_h_end - src_h_start)
    src_len = source_arc_len(points, i0, i1)

    candidates: list[tuple[str, float, float, float, float, float, Pose]] = []

    # Straight candidate.
    if abs(math.degrees(src_turn)) <= max(0.5, straight_heading_deg * 1.2):
        dx = src_end["x"] - pose.x
        dy = src_end["y"] - pose.y
        L = max(2.0, dx * math.cos(pose.heading) + dy * math.sin(pose.heading))
        L = round_to_step(L, length_round)
        end, model_pts, _, _ = simulate_segment(pose, "str", L, 0.0)
        end_err = math.hypot(end.x - src_end["x"], end.y - src_end["y"])
        head_err = abs(math.degrees(norm_angle(end.heading - src_h_end)))
        shape_err = sample_line_error(model_pts, points[i0 : i1 + 1])
        score = end_err + 1.2 * shape_err + 0.6 * head_err
        candidates.append(("str", L, 0.0, 0.0, 0.0, score, end))

    # Turn candidates with small local search around source turn/length.
    turn_sign = 1.0 if src_turn >= 0 else -1.0
    for turn_scale in (0.8, 1.0, 1.2):
        turn = turn_sign * max(math.radians(0.4), abs(src_turn) * turn_scale)
        for len_scale in (0.9, 1.0, 1.1):
            L = max(2.0, src_len * len_scale)
            L = round_to_step(L, length_round)
            arc_deg = round_to_step(abs(math.degrees(turn)), arc_round)
            turn_q = math.radians(max(0.4, arc_deg)) * turn_sign
            start_radius = L / max(1e-6, abs(turn_q))
            end_radius = estimate_boundary_radius(
                points,
                i1,
                "lft" if turn_q > 0 else "rgt",
                start_radius,
                length_round,
            )
            end, model_pts, radius, arc = simulate_segment(
                pose,
                "lft" if turn_q > 0 else "rgt",
                L,
                turn_q,
                end_radius=end_radius,
            )
            end_err = math.hypot(end.x - src_end["x"], end.y - src_end["y"])
            head_err = abs(math.degrees(norm_angle(end.heading - src_h_end)))
            shape_err = sample_line_error(model_pts, points[i0 : i1 + 1])
            radius_change_penalty = 0.001 * abs(end_radius - radius)
            score = end_err + 1.0 * shape_err + 0.8 * head_err + radius_change_penalty
            candidates.append(("lft" if turn_q > 0 else "rgt", L, radius, end_radius, arc, score, end))

    best = min(candidates, key=lambda c: c[5])
    return best


def beam_span_values(
    st_idx: int,
    remaining: int,
    min_n: int,
    max_n: int,
    span_stride: int,
    tail_gate_idx: int,
    tail_max_n: int,
    anchors: list[int],
) -> list[int]:
    n_lo = min(min_n, max(2, remaining))
    n_hi = min(max_n, remaining)
    if st_idx >= tail_gate_idx:
        n_hi = min(n_hi, tail_max_n)
    if n_hi <= 2:
        return []

    span_values = list(range(n_lo, n_hi + 1, max(1, span_stride)))
    if span_values[-1] != n_hi:
        span_values.append(n_hi)
    next_anchor = next((a for a in anchors if a > st_idx), None)
    if next_anchor is not None and next_anchor <= st_idx + n_hi and next_anchor - st_idx >= n_lo:
        anchor_n = next_anchor - st_idx
        span_values = [n for n in span_values if n <= anchor_n]
        if anchor_n >= n_lo and anchor_n not in span_values:
            span_values.append(anchor_n)
        span_values = sorted(set(span_values))
    return span_values


def shortlisted_beam_candidates(
    points: list[dict],
    st: FitState,
    span_values: list[int],
    straight_heading_deg: float,
    length_round: float,
    arc_round: float,
    beam_width: int,
) -> list[BeamCandidate]:
    raw_candidates: list[BeamCandidate] = []
    for n in span_values:
        i1 = st.idx + n
        seg_type, seg_len, seg_rad, seg_end_rad, seg_arc, local_score, end_pose = fit_single_segment(
            points,
            st.pose,
            st.idx,
            i1,
            straight_heading_deg,
            length_round,
            arc_round,
        )
        raw_candidates.append((i1, seg_type, seg_len, seg_rad, seg_end_rad, seg_arc, local_score, end_pose))

    shortlist_size = min(len(raw_candidates), max(12, beam_width * 4))
    return sorted(raw_candidates, key=lambda c: (c[6], -c[0]))[:shortlist_size]


def beam_candidate_model_points(st: FitState, seg_type: str, seg_len: float, seg_end_rad: float, seg_arc: float) -> list[dict]:
    _, seg_pts, _, _ = simulate_segment(
        st.pose,
        seg_type,
        seg_len,
        0.0 if seg_type == "str" else math.radians(seg_arc) * (1.0 if seg_type == "lft" else -1.0),
        None if seg_type == "str" else seg_end_rad,
    )
    return st.model_points + seg_pts[1:]


def beam_candidate_errors(points: list[dict], model_pts: list[dict], end_pose: Pose, i1: int, global_sample_count: int) -> tuple[float, float, float, float]:
    src_prefix = points[: i1 + 1]
    rmse, max_dev = global_path_error(model_pts, src_prefix, sample_count=global_sample_count)
    src_h_end = heading(points[i1 - 1], points[i1])
    head_err = abs(math.degrees(norm_angle(end_pose.heading - src_h_end)))
    pos_err = math.hypot(end_pose.x - points[i1]["x"], end_pose.y - points[i1]["y"])
    return rmse, max_dev, head_err, pos_err


def beam_candidate_score(
    rmse: float,
    max_dev: float,
    head_err: float,
    pos_err: float,
    i1: int,
    point_count: int,
    end_pose: Pose,
    start_pose: Pose,
    fit_pos_threshold: float,
    fit_head_threshold: float,
) -> float:
    score = 1.3 * rmse + 0.45 * max_dev + 0.55 * head_err + 0.15 * pos_err
    completion = i1 / max(1, point_count - 1)
    if completion >= 0.85:
        close_pos_err, close_head_err = closure_pose_error(end_pose, start_pose)
        ramp = ((completion - 0.85) / 0.15) ** 2
        score += ramp * (0.35 * close_pos_err + 1.8 * close_head_err)
    if pos_err > fit_pos_threshold:
        score += 0.8 * (pos_err - fit_pos_threshold)
    if head_err > fit_head_threshold:
        score += 0.5 * (head_err - fit_head_threshold)
    return score


def beam_candidate_rejected(
    st: FitState,
    rmse: float,
    max_dev: float,
    pos_err: float,
    head_err: float,
    fit_pos_threshold: float,
    fit_head_threshold: float,
    drift_rmse_growth: float,
    drift_maxdev_growth: float,
    reject_pos_mult: float,
    reject_head_mult: float,
) -> bool:
    if st.segments:
        if rmse > st.rmse + drift_rmse_growth:
            return True
        if max_dev > max(st.max_dev + drift_maxdev_growth, fit_pos_threshold * 5.0):
            return True
    return pos_err > fit_pos_threshold * reject_pos_mult or head_err > fit_head_threshold * reject_head_mult


def beam_candidate_segment(
    points: list[dict],
    st: FitState,
    i1: int,
    seg_type: str,
    seg_len: float,
    seg_rad: float,
    seg_end_rad: float,
    seg_arc: float,
    length_round: float,
    arc_round: float,
    name_count: dict[str, int],
) -> FittedSegment:
    base_name = dominant_way_name(points, st.idx, i1)
    count = name_count.get(base_name, 0) + 1
    seg_name = base_name if count == 1 else f"{base_name}-{count}"
    return FittedSegment(
        name=seg_name,
        seg_type=seg_type,
        length=round_to_step(seg_len, length_round),
        arc_deg=0.0 if seg_type == "str" else round_to_step(seg_arc, arc_round),
        radius=0.0 if seg_type == "str" else round_to_step(seg_rad, length_round),
        end_radius=0.0 if seg_type == "str" else round_to_step(seg_end_rad, length_round),
        z_end=0.0,
        i0=st.idx,
        i1=i1,
    )


def score_beam_candidate(
    points: list[dict],
    start_pose: Pose,
    st: FitState,
    candidate: BeamCandidate,
    global_sample_count: int,
    fit_pos_threshold: float,
    fit_head_threshold: float,
    drift_rmse_growth: float,
    drift_maxdev_growth: float,
    reject_pos_mult: float,
    reject_head_mult: float,
    length_round: float,
    arc_round: float,
    name_count: dict[str, int],
) -> FitState | None:
    i1, seg_type, seg_len, seg_rad, seg_end_rad, seg_arc, _local_score, end_pose = candidate
    model_pts = beam_candidate_model_points(st, seg_type, seg_len, seg_end_rad, seg_arc)
    rmse, max_dev, head_err, pos_err = beam_candidate_errors(points, model_pts, end_pose, i1, global_sample_count)
    if beam_candidate_rejected(st, rmse, max_dev, pos_err, head_err, fit_pos_threshold, fit_head_threshold, drift_rmse_growth, drift_maxdev_growth, reject_pos_mult, reject_head_mult):
        return None
    score = beam_candidate_score(rmse, max_dev, head_err, pos_err, i1, len(points), end_pose, start_pose, fit_pos_threshold, fit_head_threshold)
    seg = beam_candidate_segment(points, st, i1, seg_type, seg_len, seg_rad, seg_end_rad, seg_arc, length_round, arc_round, name_count)
    return FitState(
        idx=i1,
        pose=end_pose,
        segments=st.segments + [seg],
        model_points=model_pts,
        rmse=rmse,
        max_dev=max_dev,
        head_err_deg=head_err,
        score=score,
    )


def next_beam_states(expanded: list[FitState], beam_width: int) -> list[FitState]:
    bucket: dict[int, FitState] = {}
    for st in sorted(expanded, key=lambda s: (s.score, -s.idx)):
        prev = bucket.get(st.idx)
        if prev is None or st.score < prev.score:
            bucket[st.idx] = st
    candidates = sorted(bucket.values(), key=lambda s: (s.score, -s.idx))
    return candidates[:beam_width]


def select_best_beam_state(beam: list[FitState], best_complete: FitState | None, point_count: int) -> FitState:
    if best_complete is not None:
        return best_complete
    complete = [st for st in beam if st.idx >= point_count - 2]
    if complete:
        return min(complete, key=lambda s: s.score)
    return max(beam, key=lambda s: (s.idx, -s.score))


def finalize_beam_segments(best: FitState) -> list[FittedSegment]:
    final: list[FittedSegment] = []
    name_count: dict[str, int] = {}
    for segment in best.segments:
        base = base_segment_name(segment.name)
        count = name_count.get(base, 0) + 1
        name_count[base] = count
        segment.name = base if count == 1 else f"{base}-{count}"
        final.append(segment)
    return final


def update_beam_progress(
    beam: list[FitState],
    best_frontier_idx: int,
    stagnation: int,
    it: int,
    max_iters: int,
    point_count: int,
    verbose_progress: bool,
    t0: float,
) -> tuple[int, int, bool]:
    frontier_idx = max(st.idx for st in beam)
    if frontier_idx > best_frontier_idx:
        best_frontier_idx = frontier_idx
        stagnation = 0
    else:
        stagnation += 1
    if stagnation >= 80:
        if verbose_progress:
            print(
                f"Beam early stop due to stagnation at iteration {it + 1}, "
                f"frontier={best_frontier_idx}/{point_count - 1}"
            )
        return best_frontier_idx, stagnation, True

    if verbose_progress and ((it + 1) % 25 == 0 or it == 0):
        elapsed = time.perf_counter() - t0
        print(
            f"Beam iteration {it + 1}/{max_iters}: "
            f"frontier={frontier_idx}/{point_count - 1}, "
            f"states={len(beam)}, elapsed={elapsed:.1f}s"
        )
    return best_frontier_idx, stagnation, False


def expand_beam_state(
    points: list[dict],
    start_pose: Pose,
    st: FitState,
    min_n: int,
    max_n: int,
    span_stride: int,
    tail_gate_idx: int,
    tail_max_n: int,
    anchors: list[int],
    straight_heading_deg: float,
    length_round: float,
    arc_round: float,
    beam_width: int,
    global_sample_count: int,
    fit_pos_threshold: float,
    fit_head_threshold: float,
    drift_rmse_growth: float,
    drift_maxdev_growth: float,
    reject_pos_mult: float,
    reject_head_mult: float,
    name_count: dict[str, int],
    best_complete: FitState | None,
) -> tuple[list[FitState], FitState | None]:
    remaining = len(points) - 1 - st.idx
    span_values = beam_span_values(st.idx, remaining, min_n, max_n, span_stride, tail_gate_idx, tail_max_n, anchors)
    if not span_values:
        return [st], best_complete

    states = []
    for candidate in shortlisted_beam_candidates(points, st, span_values, straight_heading_deg, length_round, arc_round, beam_width):
        next_state = score_beam_candidate(
            points,
            start_pose,
            st,
            candidate,
            global_sample_count,
            fit_pos_threshold,
            fit_head_threshold,
            drift_rmse_growth,
            drift_maxdev_growth,
            reject_pos_mult,
            reject_head_mult,
            length_round,
            arc_round,
            name_count,
        )
        if next_state is None:
            continue
        states.append(next_state)
        if next_state.idx >= len(points) - 2 and (best_complete is None or next_state.score < best_complete.score):
            best_complete = next_state
    return states, best_complete


def expand_beam(
    points: list[dict],
    start_pose: Pose,
    beam: list[FitState],
    min_n: int,
    max_n: int,
    span_stride: int,
    tail_gate_idx: int,
    tail_max_n: int,
    anchors: list[int],
    straight_heading_deg: float,
    length_round: float,
    arc_round: float,
    beam_width: int,
    global_sample_count: int,
    fit_pos_threshold: float,
    fit_head_threshold: float,
    drift_rmse_growth: float,
    drift_maxdev_growth: float,
    reject_pos_mult: float,
    reject_head_mult: float,
    name_count: dict[str, int],
    best_complete: FitState | None,
) -> tuple[list[FitState], FitState | None]:
    expanded: list[FitState] = []
    for st in beam:
        states, best_complete = expand_beam_state(
            points,
            start_pose,
            st,
            min_n,
            max_n,
            span_stride,
            tail_gate_idx,
            tail_max_n,
            anchors,
            straight_heading_deg,
            length_round,
            arc_round,
            beam_width,
            global_sample_count,
            fit_pos_threshold,
            fit_head_threshold,
            drift_rmse_growth,
            drift_maxdev_growth,
            reject_pos_mult,
            reject_head_mult,
            name_count,
            best_complete,
        )
        expanded.extend(states)
    return expanded, best_complete


def beam_fit(
    points: list[dict],
    step: float,
    straight_heading_deg: float,
    min_seg_len: float,
    max_seg_len: float,
    length_round: float,
    arc_round: float,
    fit_pos_threshold: float,
    fit_head_threshold: float,
    beam_width: int,
    span_stride: int,
    global_sample_count: int,
    max_beam_iters: int,
    verbose_progress: bool,
    drift_rmse_growth: float,
    drift_maxdev_growth: float,
    reject_pos_mult: float,
    reject_head_mult: float,
    preserve_tail_seam: bool,
    curvature_anchors: set[int] | None = None,
) -> list[FittedSegment]:
    # Global-prefix beam search.
    #
    # Performance note: computing a full replay/global error for every tested span
    # is too expensive on larger tracks. We first rank candidates by the local
    # segment-fit score from `fit_single_segment`, then run the expensive global
    # prefix scoring only on a small shortlist per beam state.
    name_count: dict[str, int] = {}

    if len(points) < 3:
        return []

    start_pose = Pose(points[0]["x"], points[0]["y"], heading(points[0], points[1]))
    init_state = FitState(
        idx=0,
        pose=start_pose,
        segments=[],
        model_points=[{"x": start_pose.x, "y": start_pose.y}],
        rmse=0.0,
        max_dev=0.0,
        head_err_deg=0.0,
        score=0.0,
    )

    beam = [init_state]
    best_complete: FitState | None = None
    min_n = max(2, int(math.ceil(min_seg_len / step)))
    max_n = max(min_n + 1, int(math.floor(max_seg_len / step)))
    tail_gate_idx = int(0.85 * max(1, len(points) - 1)) if preserve_tail_seam else len(points)
    tail_max_n = max(min_n + 1, int(math.ceil(max_n * 0.6))) if preserve_tail_seam else max_n
    anchors = sorted(curvature_anchors or set())

    max_iters = max(80, min(max_beam_iters, len(points) * 2))
    best_frontier_idx = 0
    stagnation = 0
    t0 = time.perf_counter()
    for it in range(max_iters):
        if any(st.idx >= len(points) - 2 for st in beam):
            break
        expanded, best_complete = expand_beam(
            points,
            start_pose,
            beam,
            min_n,
            max_n,
            span_stride,
            tail_gate_idx,
            tail_max_n,
            anchors,
            straight_heading_deg,
            length_round,
            arc_round,
            beam_width,
            global_sample_count,
            fit_pos_threshold,
            fit_head_threshold,
            drift_rmse_growth,
            drift_maxdev_growth,
            reject_pos_mult,
            reject_head_mult,
            name_count,
            best_complete,
        )
        if not expanded:
            break

        beam = next_beam_states(expanded, beam_width)
        best_frontier_idx, stagnation, stop = update_beam_progress(beam, best_frontier_idx, stagnation, it, max_iters, len(points), verbose_progress, t0)
        if stop:
            break

    best = select_best_beam_state(beam, best_complete, len(points))
    return finalize_beam_segments(best)


def can_merge_local_turn_segments(p: FittedSegment, s: FittedSegment, length_round: float) -> bool:
    if s.seg_type != p.seg_type or s.seg_type not in ("lft", "rgt"):
        return False
    radius_bridge_ok = abs(p.end_radius - s.radius) <= 3.0 * length_round
    slope_prev = p.end_radius - p.radius
    slope_next = s.end_radius - s.radius
    slope_ok = abs(slope_prev - slope_next) <= 6.0 * length_round
    start_radius_close = abs(s.radius - p.radius) <= 10.0 * length_round
    return radius_bridge_ok and slope_ok and start_radius_close


def merge_local_segment_pair(p: FittedSegment, s: FittedSegment, length_round: float, arc_round: float) -> bool:
    if s.seg_type == p.seg_type == "str":
        p.length = round_to_step(p.length + s.length, length_round)
        p.i1 = s.i1
        return True
    if can_merge_local_turn_segments(p, s, length_round):
        p.arc_deg = round_to_step(p.arc_deg + s.arc_deg, arc_round)
        p.length = round_to_step(p.length + s.length, length_round)
        p.end_radius = s.end_radius
        p.i1 = s.i1
        return True
    return False


def merge_local_segments(segments: list[FittedSegment], length_round: float, arc_round: float) -> list[FittedSegment]:
    out = [segments[0]]
    for s in segments[1:]:
        if merge_local_segment_pair(out[-1], s, length_round, arc_round):
            continue
        out.append(s)
    return out


def can_merge_global_turn_pair(a: FittedSegment, b: FittedSegment, length_round: float, seam_idx_gate: int) -> bool:
    if a.seg_type != b.seg_type or a.seg_type not in ("lft", "rgt"):
        return False
    if a.i0 >= seam_idx_gate or b.i1 >= seam_idx_gate:
        return False
    return abs(a.end_radius - b.radius) <= 4.0 * length_round


def merge_global_turn_pair(a: FittedSegment, b: FittedSegment, length_round: float, arc_round: float) -> FittedSegment:
    return FittedSegment(
        name=a.name,
        seg_type=a.seg_type,
        length=round_to_step(a.length + b.length, length_round),
        arc_deg=round_to_step(a.arc_deg + b.arc_deg, arc_round),
        radius=a.radius,
        end_radius=b.end_radius,
        z_end=b.z_end,
        i0=a.i0,
        i1=b.i1,
    )


def simplification_baseline(
    start_pose: Pose,
    segments: list[FittedSegment],
    src_points: list[dict],
    sample_count: int,
) -> tuple[float, float, float, float]:
    base_model = reconstruct_from_segments(start_pose, segments)
    base_rmse, base_max = global_path_error(base_model, src_points, sample_count=sample_count)
    base_end_pose = end_pose_from_segments(start_pose, segments)
    base_close_pos, base_close_head = closure_pose_error(base_end_pose, start_pose)
    return base_rmse, base_max, base_close_pos, base_close_head


def evaluate_global_turn_merge(
    out: list[FittedSegment],
    i: int,
    start_pose: Pose,
    src_points: list[dict],
    sample_count: int,
    length_round: float,
    arc_round: float,
    seam_idx_gate: int,
    base_rmse: float,
    base_max: float,
    base_close_pos: float,
    base_close_head: float,
) -> tuple[list[FittedSegment], float, float, float] | None:
    a = out[i]
    b = out[i + 1]
    if not can_merge_global_turn_pair(a, b, length_round, seam_idx_gate):
        return None

    merged = merge_global_turn_pair(a, b, length_round, arc_round)
    candidate = out[:i] + [merged] + out[i + 2 :]
    model = reconstruct_from_segments(start_pose, candidate)
    rmse, max_dev = global_path_error(model, src_points, sample_count=sample_count)
    end_a = model[-2]
    end_b = model[-1]
    end_pose = Pose(end_b["x"], end_b["y"], heading(end_a, end_b))
    close_pos_err, close_head_err = closure_pose_error(end_pose, start_pose)

    if rmse > base_rmse + 0.20:
        return None
    if max_dev > base_max + 0.75:
        return None
    if close_pos_err > base_close_pos + 1.0:
        return None
    if close_head_err > base_close_head + 0.25:
        return None

    obj = rmse + 0.20 * max_dev + 0.60 * close_pos_err + 3.0 * close_head_err
    return candidate, rmse, max_dev, obj


def find_best_global_turn_merge(
    out: list[FittedSegment],
    start_pose: Pose,
    src_points: list[dict],
    sample_count: int,
    length_round: float,
    arc_round: float,
    seam_idx_gate: int,
    base_rmse: float,
    base_max: float,
    base_close_pos: float,
    base_close_head: float,
) -> tuple[list[FittedSegment], float, float] | None:
    best_obj = float("inf")
    best_state: tuple[list[FittedSegment], float, float] | None = None
    for i in range(len(out) - 1):
        result = evaluate_global_turn_merge(
            out,
            i,
            start_pose,
            src_points,
            sample_count,
            length_round,
            arc_round,
            seam_idx_gate,
            base_rmse,
            base_max,
            base_close_pos,
            base_close_head,
        )
        if result is None:
            continue
        candidate, rmse, max_dev, obj = result
        if obj < best_obj:
            best_obj = obj
            best_state = (candidate, rmse, max_dev)
    return best_state


def merge_global_turn_segments(
    out: list[FittedSegment],
    length_round: float,
    arc_round: float,
    src_points: list[dict],
    start_pose: Pose,
    sample_count: int,
) -> list[FittedSegment]:
    base_rmse, base_max, base_close_pos, base_close_head = simplification_baseline(start_pose, out, src_points, sample_count)
    seam_idx_gate = int(0.85 * max(1, len(src_points) - 1))
    while True:
        best_state = find_best_global_turn_merge(
            out,
            start_pose,
            src_points,
            sample_count,
            length_round,
            arc_round,
            seam_idx_gate,
            base_rmse,
            base_max,
            base_close_pos,
            base_close_head,
        )
        if best_state is None:
            break
        out, base_rmse, base_max = best_state
        base_end_pose = end_pose_from_segments(start_pose, out)
        base_close_pos, base_close_head = closure_pose_error(base_end_pose, start_pose)
    return out


def simplify_segments(
    segments: list[FittedSegment],
    length_round: float,
    arc_round: float,
    src_points: list[dict],
    start_pose: Pose,
) -> list[FittedSegment]:
    if not segments:
        return []

    simplify_sample_count = 60

    # Pass 1: deterministic local merges.
    out = merge_local_segments(segments, length_round, arc_round)

    # Pass 2: greedy global-error-aware turn merging.
    if len(out) < 3:
        return out

    return merge_global_turn_segments(out, length_round, arc_round, src_points, start_pose, simplify_sample_count)


def turn_length_from_arc(radius: float, arc_deg: float) -> float:
    return abs(radius) * math.radians(abs(arc_deg))


def build_cleanup_turn_replacement(
    name: str,
    seg_type: str,
    total_len: float,
    net_arc: float,
    length_round: float,
    arc_round: float,
    z_end: float,
    i0: int,
    i1: int,
) -> FittedSegment:
    if abs(net_arc) < max(0.1, arc_round):
        return FittedSegment(name, "str", round_to_step(total_len, length_round), 0.0, 0.0, 0.0, z_end, i0, i1)
    radius = max(1.0, total_len / math.radians(abs(net_arc)))
    return FittedSegment(
        name=name,
        seg_type=seg_type,
        length=round_to_step(total_len, length_round),
        arc_deg=round_to_step(net_arc, arc_round),
        radius=round_to_step(radius, length_round),
        end_radius=round_to_step(radius, length_round),
        z_end=z_end,
        i0=i0,
        i1=i1,
    )


def is_turn_segment(segment: FittedSegment) -> bool:
    return segment.seg_type in ("lft", "rgt")


def is_cleanup_small_turn(segment: FittedSegment, max_arc_deg: float, max_len_m: float) -> bool:
    return is_turn_segment(segment) and abs(segment.arc_deg) <= max_arc_deg and segment.length <= max_len_m


def straight_wiggle_replacement(
    a: FittedSegment,
    b: FittedSegment,
    c: FittedSegment,
    length_round: float,
    max_arc_deg: float,
    max_len_m: float,
) -> FittedSegment | None:
    if is_cleanup_small_turn(b, max_arc_deg, max_len_m) and a.seg_type == c.seg_type == "str":
        return FittedSegment(
            name=a.name,
            seg_type="str",
            length=round_to_step(a.length + b.length + c.length, length_round),
            arc_deg=0.0,
            radius=0.0,
            end_radius=0.0,
            z_end=c.z_end,
            i0=a.i0,
            i1=c.i1,
        )
    return None


def opposite_turn_wiggle_replacement(
    a: FittedSegment,
    b: FittedSegment,
    c: FittedSegment,
    length_round: float,
    arc_round: float,
    max_arc_deg: float,
    max_len_m: float,
    neighbor_ratio: float,
) -> FittedSegment | None:
    if not (is_cleanup_small_turn(b, max_arc_deg, max_len_m) and a.seg_type == c.seg_type and is_turn_segment(a) and b.seg_type != a.seg_type):
        return None
    surrounding_arc = abs(a.arc_deg) + abs(c.arc_deg)
    if surrounding_arc <= 1e-9 or abs(b.arc_deg) > surrounding_arc * neighbor_ratio:
        return None
    return build_cleanup_turn_replacement(
        a.name,
        a.seg_type,
        a.length + b.length + c.length,
        a.arc_deg + c.arc_deg - b.arc_deg,
        length_round,
        arc_round,
        c.z_end,
        a.i0,
        c.i1,
    )


def edge_turn_wiggle_replacement(
    a: FittedSegment,
    b: FittedSegment,
    c: FittedSegment,
    length_round: float,
    arc_round: float,
    max_arc_deg: float,
    max_len_m: float,
    neighbor_ratio: float,
) -> FittedSegment | None:
    if not (a.seg_type == c.seg_type and is_turn_segment(a) and is_turn_segment(b) and b.seg_type != a.seg_type):
        return None
    edge_arc = abs(a.arc_deg) + abs(c.arc_deg)
    if edge_arc > max_arc_deg * 2.0 + 1e-9 or a.length > max_len_m or c.length > max_len_m:
        return None
    if abs(b.arc_deg) <= 1e-9 or edge_arc > abs(b.arc_deg) * neighbor_ratio:
        return None
    return build_cleanup_turn_replacement(
        a.name,
        b.seg_type,
        a.length + b.length + c.length,
        b.arc_deg - a.arc_deg - c.arc_deg,
        length_round,
        arc_round,
        c.z_end,
        a.i0,
        c.i1,
    )


def small_wiggle_replacement(
    a: FittedSegment,
    b: FittedSegment,
    c: FittedSegment,
    length_round: float,
    arc_round: float,
    max_arc_deg: float,
    max_len_m: float,
    neighbor_ratio: float,
) -> FittedSegment | None:
    replacement = straight_wiggle_replacement(a, b, c, length_round, max_arc_deg, max_len_m)
    if replacement is not None:
        return replacement
    replacement = opposite_turn_wiggle_replacement(a, b, c, length_round, arc_round, max_arc_deg, max_len_m, neighbor_ratio)
    if replacement is not None:
        return replacement
    return edge_turn_wiggle_replacement(a, b, c, length_round, arc_round, max_arc_deg, max_len_m, neighbor_ratio)


def cleanup_small_wiggles(
    segments: list[FittedSegment],
    length_round: float,
    arc_round: float,
    src_points: list[dict],
    start_pose: Pose,
    max_arc_deg: float,
    max_len_m: float,
    neighbor_ratio: float,
    rmse_growth: float,
    maxdev_growth: float,
) -> tuple[list[FittedSegment], dict]:
    if len(segments) < 3:
        return segments, {"applied": False, "removals": 0}

    sample_count = 80
    out = list(segments)
    base_model = reconstruct_from_segments(start_pose, out)
    base_rmse, base_max = global_path_error(base_model, src_points, sample_count=sample_count)
    removals = 0

    def acceptable(candidate: list[FittedSegment]) -> tuple[bool, float, float]:
        model = reconstruct_from_segments(start_pose, candidate)
        rmse, max_dev = global_path_error(model, src_points, sample_count=sample_count)
        return rmse <= base_rmse + rmse_growth and max_dev <= base_max + maxdev_growth, rmse, max_dev

    changed = True
    while changed:
        changed = False
        for i in range(1, len(out) - 1):
            a = out[i - 1]
            b = out[i]
            c = out[i + 1]

            replacement = small_wiggle_replacement(a, b, c, length_round, arc_round, max_arc_deg, max_len_m, neighbor_ratio)
            if replacement is None:
                continue
            candidate = out[: i - 1] + [replacement] + out[i + 2 :]

            ok, rmse, max_dev = acceptable(candidate)
            if not ok:
                continue
            out = candidate
            base_rmse = rmse
            base_max = max_dev
            removals += 1
            changed = True
            break

    return out, {"applied": removals > 0, "removals": removals, "rmse": base_rmse, "max_dev": base_max}


def validate_segment_order(segments: list[FittedSegment]) -> None:
    if not segments:
        return
    prev_i0 = segments[0].i0
    prev_i1 = segments[0].i1
    if prev_i1 < prev_i0:
        raise RuntimeError(f"Invalid segment source range: {segments[0].name} [{prev_i0}, {prev_i1}]")
    for seg in segments[1:]:
        if seg.i1 < seg.i0:
            raise RuntimeError(f"Invalid segment source range: {seg.name} [{seg.i0}, {seg.i1}]")
        if seg.i0 < prev_i0 or seg.i1 < prev_i1:
            raise RuntimeError(
                "Segment order regression after fitting/simplification: "
                f"{seg.name} [{seg.i0}, {seg.i1}] after [{prev_i0}, {prev_i1}]"
            )
        if seg.i0 < prev_i1:
            raise RuntimeError(
                "Segment overlap/order violation after fitting/simplification: "
                f"{seg.name} starts at {seg.i0} before previous end {prev_i1}"
            )
        prev_i0 = seg.i0
        prev_i1 = seg.i1


def point_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def point_unit(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    d = max(1e-9, point_distance(a, b))
    return (b[0] - a[0]) / d, (b[1] - a[1]) / d


def simplify_corner_controls(points: list[dict], tolerance: float) -> list[tuple[float, float]]:
    coords = np.array([[p["x"], p["y"]] for p in points], dtype=float)
    controls_np = approximate_polygon(np.vstack([coords, coords[0]]), tolerance=tolerance)
    if len(controls_np) > 1 and float(np.linalg.norm(controls_np[0] - controls_np[-1])) < 1e-6:
        controls_np = controls_np[:-1]
    return [(float(x), float(y)) for x, y in controls_np]


def build_corner_geometry(
    controls: list[tuple[float, float]],
    trim_max: float,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], list[float], list[float]]:
    entries: list[tuple[float, float]] = []
    exits: list[tuple[float, float]] = []
    deltas: list[float] = []
    radii: list[float] = []
    n = len(controls)
    for i in range(n):
        p = controls[(i - 1) % n]
        c = controls[i]
        q = controls[(i + 1) % n]
        hin = math.atan2(c[1] - p[1], c[0] - p[0])
        hout = math.atan2(q[1] - c[1], q[0] - c[0])
        delta = norm_angle(hout - hin)
        abs_delta = abs(delta)
        if abs_delta < math.radians(3.0):
            trim = 0.0
            radius = 0.0
        else:
            trim = min(trim_max, 0.35 * point_distance(p, c), 0.35 * point_distance(c, q))
            radius = trim / max(1e-6, math.tan(abs_delta * 0.5))
        uin = point_unit(p, c)
        uout = point_unit(c, q)
        entries.append((c[0] - uin[0] * trim, c[1] - uin[1] * trim))
        exits.append((c[0] + uout[0] * trim, c[1] + uout[1] * trim))
        deltas.append(delta)
        radii.append(radius)
    return entries, exits, deltas, radii


def corner_segment_name(segments: list[FittedSegment]) -> str:
    return f"image-centerline-{len(segments) + 1}"


def append_corner_straight(
    segments: list[FittedSegment],
    straight_len: float,
    length_round: float,
    source_idx: int,
) -> int:
    if straight_len <= 1.0:
        return source_idx
    segments.append(
        FittedSegment(
            corner_segment_name(segments),
            "str",
            round_to_step(straight_len, length_round),
            0.0,
            0.0,
            0.0,
            0.0,
            source_idx,
            source_idx + 1,
        )
    )
    return source_idx + 1


def append_corner_turn(
    segments: list[FittedSegment],
    delta: float,
    radius: float,
    length_round: float,
    arc_round: float,
    source_idx: int,
) -> int:
    if radius <= 1.0 or abs(delta) < math.radians(3.0):
        return source_idx
    arc_deg = abs(math.degrees(delta))
    length = radius * abs(delta)
    segments.append(
        FittedSegment(
            corner_segment_name(segments),
            "lft" if delta > 0 else "rgt",
            round_to_step(length, length_round),
            round_to_step(arc_deg, arc_round),
            round_to_step(radius, length_round),
            round_to_step(radius, length_round),
            0.0,
            source_idx,
            source_idx + 1,
        )
    )
    return source_idx + 1


def build_corner_segments(
    controls: list[tuple[float, float]],
    entries: list[tuple[float, float]],
    exits: list[tuple[float, float]],
    deltas: list[float],
    radii: list[float],
    length_round: float,
    arc_round: float,
) -> tuple[Pose, list[FittedSegment]]:
    n = len(controls)
    start = exits[0]
    start_heading = math.atan2(controls[1][1] - controls[0][1], controls[1][0] - controls[0][0])
    start_pose = Pose(start[0], start[1], start_heading)
    segments: list[FittedSegment] = []
    source_idx = 0
    for step_idx in range(1, n + 1):
        i = step_idx % n
        prev_exit = exits[(i - 1) % n]
        entry = entries[i]
        source_idx = append_corner_straight(segments, point_distance(prev_exit, entry), length_round, source_idx)
        source_idx = append_corner_turn(segments, deltas[i], radii[i], length_round, arc_round, source_idx)
    return start_pose, segments


def scale_corner_segments(segments: list[FittedSegment], scale: float, length_round: float) -> None:
    if abs(scale - 1.0) <= 1e-9:
        return
    for segment in segments:
        segment.length = round_to_step(segment.length * scale, length_round)
        if segment.seg_type != "str":
            segment.radius = round_to_step(segment.radius * scale, length_round)
            segment.end_radius = round_to_step(segment.end_radius * scale, length_round)


def corner_fit_info(controls: list[tuple[float, float]], tolerance: float, trim_max: float, scale: float, model_len: float, target_len: float) -> dict:
    return {
        "corner_controls": len(controls),
        "corner_tolerance": tolerance,
        "corner_trim_max": trim_max,
        "corner_length_scale": scale,
        "corner_unscaled_length_m": model_len,
        "corner_target_length_m": target_len,
    }


def generate_corner_fit_segments(
    points: list[dict],
    tolerance: float,
    trim_max: float,
    length_round: float,
    arc_round: float,
    target_length_m: float | None = None,
) -> tuple[Pose, list[FittedSegment], dict]:
    if np is None or approximate_polygon is None:
        raise SystemExit("--corner-fit requires numpy and scikit-image; update the torcs-tracktools environment")
    if len(points) < 4:
        raise SystemExit("--corner-fit requires at least four source points")

    controls = simplify_corner_controls(points, tolerance)
    if len(controls) < 4:
        raise SystemExit("--corner-fit simplified the source to fewer than four controls; lower --corner-tolerance")

    entries, exits, deltas, radii = build_corner_geometry(controls, trim_max)
    start_pose, segments = build_corner_segments(controls, entries, exits, deltas, radii, length_round, arc_round)
    model = reconstruct_from_segments(start_pose, segments)
    model_len = source_loop_len(model)
    target_len = target_length_m if target_length_m and target_length_m > 0.0 else source_loop_len(points)
    scale = target_len / model_len if model_len > 1e-9 else 1.0
    scale_corner_segments(segments, scale, length_round)
    return start_pose, segments, corner_fit_info(controls, tolerance, trim_max, scale, model_len, target_len)


def segments_to_json_obj(segments: list[FittedSegment]) -> list[dict]:
    out = []
    for s in segments:
        obj = {
            "name": s.name,
            "type": s.seg_type,
            "z_end": s.z_end,
            "source_i0": s.i0,
            "source_i1": s.i1,
        }
        if s.seg_type == "str":
            obj["lg"] = s.length
        else:
            obj["radius"] = s.radius
            if abs(s.end_radius - s.radius) > 0.05:
                obj["end_radius"] = s.end_radius
            obj["arc"] = s.arc_deg
            obj["length"] = s.length
        out.append(obj)
    return out


def segments_to_xml(segments: list[FittedSegment]) -> str:
    lines: list[str] = []
    for s in segments:
        lines.append(f'\t\t\t<section name="{s.name}">')
        lines.append(f'\t\t\t\t<attstr name="type" val="{s.seg_type}"/>')
        if s.seg_type == "str":
            lines.append(f'\t\t\t\t<attnum name="lg" unit="m" val="{s.length:.1f}"/>')
        else:
            lines.append(f'\t\t\t\t<attnum name="radius" unit="m" val="{s.radius:.1f}"/>')
            if abs(s.end_radius - s.radius) > 0.05:
                lines.append(f'\t\t\t\t<attnum name="end radius" unit="m" val="{s.end_radius:.1f}"/>')
            lines.append(f'\t\t\t\t<attnum name="arc" unit="deg" val="{s.arc_deg:.1f}"/>')
        lines.append(f'\t\t\t\t<attnum name="z end" unit="m" val="{s.z_end:.1f}"/>')
        lines.append('\t\t\t</section>')
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def initial_fit_settings(args: argparse.Namespace) -> dict:
    return {
        "min_seg_len": args.min_seg_len,
        "max_seg_len": args.max_seg_len,
        "beam_width": max(2, args.beam_width),
        "span_stride": max(1, args.span_stride),
        "drift_rmse_growth": max(0.2, args.drift_rmse_growth),
        "drift_maxdev_growth": max(0.5, args.drift_maxdev_growth),
        "reject_pos_mult": max(1.5, args.reject_pos_mult),
        "reject_head_mult": max(1.5, args.reject_head_mult),
    }


def run_corner_fit_mode(sampled: list[dict], args: argparse.Namespace, source_length: float) -> tuple[Pose, list[FittedSegment], list[FittedSegment], dict, dict, float, list[dict]]:
    start_pose, simplified, corner_info = generate_corner_fit_segments(
        sampled,
        args.corner_tolerance,
        args.corner_trim_max,
        args.length_round,
        args.arc_round,
        source_length,
    )
    corner_info["applied"] = True
    fitted = list(simplified)
    coverage = 1.0
    adaptive_attempts = [
        {
            "attempt": 1,
            "source_coverage_ratio": coverage,
            "fitted_segment_count": len(fitted),
            "simplified_segment_count": len(simplified),
            "corner_fit": dict(corner_info),
        }
    ]
    return start_pose, fitted, simplified, {"applied": False, "removals": 0}, {"applied": False}, coverage, adaptive_attempts


def adaptive_curvature_anchors(sampled: list[dict], args: argparse.Namespace) -> set[int]:
    if not args.preserve_curvature_anchors:
        return set()
    anchors = find_curvature_anchors(sampled, args.anchor_curvature_deg, args.anchor_window, args.anchor_min_spacing_m)
    if anchors:
        print(f"Curvature anchors: {len(anchors)}")
    return anchors


def adaptive_attempt_record(
    attempt: int,
    settings: dict,
    coverage: float,
    fitted: list[FittedSegment],
    simplified: list[FittedSegment],
    cleanup_info: dict,
    helper_info: dict,
    curvature_anchors: set[int],
) -> dict:
    return {
        "attempt": attempt,
        "minimum_segment_length_m": settings["min_seg_len"],
        "maximum_segment_length_m": settings["max_seg_len"],
        "beam_width": settings["beam_width"],
        "span_stride": settings["span_stride"],
        "drift_rmse_growth": settings["drift_rmse_growth"],
        "drift_maxdev_growth": settings["drift_maxdev_growth"],
        "reject_pos_mult": settings["reject_pos_mult"],
        "reject_head_mult": settings["reject_head_mult"],
        "source_coverage_ratio": coverage,
        "fitted_segment_count": len(fitted),
        "simplified_segment_count": len(simplified),
        "small_wiggle_cleanup": dict(cleanup_info),
        "closure_helpers_applied": bool(helper_info.get("applied", False)),
        "curvature_anchor_count": len(curvature_anchors),
    }


def relax_adaptive_settings(settings: dict) -> None:
    settings["min_seg_len"] = max(8.0, settings["min_seg_len"] * 0.82)
    settings["max_seg_len"] = max(settings["min_seg_len"] + 40.0, settings["max_seg_len"] * 0.92)
    settings["beam_width"] = min(30, settings["beam_width"] + 2)
    settings["span_stride"] = max(1, settings["span_stride"] - 1)
    settings["drift_rmse_growth"] = min(3.0, settings["drift_rmse_growth"] + 0.30)
    settings["drift_maxdev_growth"] = min(8.0, settings["drift_maxdev_growth"] + 0.70)
    settings["reject_pos_mult"] = min(8.0, settings["reject_pos_mult"] + 0.50)
    settings["reject_head_mult"] = min(8.0, settings["reject_head_mult"] + 0.50)


def run_adaptive_attempt(
    sampled: list[dict],
    start_pose: Pose,
    args: argparse.Namespace,
    settings: dict,
    curvature_anchors: set[int],
) -> tuple[list[FittedSegment], list[FittedSegment], dict, dict, float]:
    fitted = beam_fit(
        sampled,
        step=args.resample_step,
        straight_heading_deg=args.straight_heading_deg,
        min_seg_len=settings["min_seg_len"],
        max_seg_len=settings["max_seg_len"],
        length_round=args.length_round,
        arc_round=args.arc_round,
        fit_pos_threshold=args.fit_pos_threshold,
        fit_head_threshold=args.fit_head_threshold,
        beam_width=settings["beam_width"],
        span_stride=settings["span_stride"],
        global_sample_count=max(40, args.global_sample_count),
        max_beam_iters=max(80, args.max_beam_iters),
        verbose_progress=args.verbose_progress,
        drift_rmse_growth=settings["drift_rmse_growth"],
        drift_maxdev_growth=settings["drift_maxdev_growth"],
        reject_pos_mult=settings["reject_pos_mult"],
        reject_head_mult=settings["reject_head_mult"],
        preserve_tail_seam=args.preserve_tail_seam,
        curvature_anchors=curvature_anchors,
    )
    validate_segment_order(fitted)
    simplified = list(fitted) if args.skip_simplify else simplify_segments(fitted, args.length_round, args.arc_round, sampled, start_pose)
    validate_segment_order(simplified)
    cleanup_info: dict = {"applied": False, "removals": 0}
    if args.cleanup_small_wiggles:
        simplified, cleanup_info = cleanup_small_wiggles(
            simplified,
            args.length_round,
            args.arc_round,
            sampled,
            start_pose,
            args.cleanup_max_arc_deg,
            args.cleanup_max_len_m,
            args.cleanup_neighbor_ratio,
            args.cleanup_rmse_growth,
            args.cleanup_maxdev_growth,
        )
        validate_segment_order(simplified)
    simplified, helper_info = append_closure_helpers(simplified, start_pose, args.length_round, args.arc_round)
    validate_segment_order(simplified)
    last_i1 = simplified[-1].i1 if simplified else 0
    coverage = last_i1 / max(1, len(sampled) - 1)
    return fitted, simplified, cleanup_info, helper_info, coverage


def run_adaptive_fit_mode(sampled: list[dict], start_pose: Pose, args: argparse.Namespace, settings: dict) -> tuple[list[FittedSegment], list[FittedSegment], dict, dict, set[int], float, list[dict]]:
    curvature_anchors = adaptive_curvature_anchors(sampled, args)
    adaptive_attempts: list[dict] = []
    fitted: list[FittedSegment] = []
    simplified: list[FittedSegment] = []
    cleanup_info: dict = {"applied": False, "removals": 0}
    helper_info: dict = {"applied": False}
    coverage = 0.0
    max_attempts = max(1, args.max_adaptive_attempts)
    for attempt in range(1, max_attempts + 1):
        fitted, simplified, cleanup_info, helper_info, coverage = run_adaptive_attempt(sampled, start_pose, args, settings, curvature_anchors)
        adaptive_attempts.append(adaptive_attempt_record(attempt, settings, coverage, fitted, simplified, cleanup_info, helper_info, curvature_anchors))
        if coverage >= args.min_coverage or args.allow_partial:
            break
        print(
            "Warning: source coverage too low "
            f"({coverage * 100.0:.1f}% on attempt {attempt}/{max_attempts}); "
            "adjusting fit parameters and retrying."
        )
        relax_adaptive_settings(settings)
    return fitted, simplified, cleanup_info, helper_info, curvature_anchors, coverage, adaptive_attempts


def build_output_object(
    in_path: pathlib.Path,
    args: argparse.Namespace,
    settings: dict,
    polyline: list[dict],
    sampled: list[dict],
    fitted: list[FittedSegment],
    simplified: list[FittedSegment],
    coverage: float,
    root_mean_square_error: float,
    max_dev: float,
    helper_info: dict,
    cleanup_info: dict,
    adaptive_attempts: list[dict],
    curvature_anchors: set[int],
) -> dict:
    return {
        "schema": 3,
        "source": str(in_path),
        "settings": {
            "resample_step": args.resample_step,
            "straight_heading_deg": args.straight_heading_deg,
            "minimum_segment_length_m": settings["min_seg_len"],
            "maximum_segment_length_m": settings["max_seg_len"],
            "length_round": args.length_round,
            "arc_round": args.arc_round,
            "fit_pos_threshold": args.fit_pos_threshold,
            "fit_head_threshold": args.fit_head_threshold,
            "beam_width": settings["beam_width"],
            "span_stride": settings["span_stride"],
            "drift_rmse_growth": settings["drift_rmse_growth"],
            "drift_maxdev_growth": settings["drift_maxdev_growth"],
            "reject_pos_mult": settings["reject_pos_mult"],
            "reject_head_mult": settings["reject_head_mult"],
            "preserve_tail_seam": bool(args.preserve_tail_seam),
            "cleanup_small_wiggles": args.cleanup_small_wiggles,
            "skip_simplify": args.skip_simplify,
            "cleanup_max_arc_deg": args.cleanup_max_arc_deg,
            "cleanup_max_len_m": args.cleanup_max_len_m,
            "cleanup_neighbor_ratio": args.cleanup_neighbor_ratio,
            "preserve_curvature_anchors": args.preserve_curvature_anchors,
            "anchor_curvature_deg": args.anchor_curvature_deg,
            "anchor_window": args.anchor_window,
            "anchor_min_spacing_m": args.anchor_min_spacing_m,
            "curvature_anchor_count": len(curvature_anchors),
            "minimum_coverage_ratio": args.min_coverage,
        },
        "adaptive_attempts": adaptive_attempts,
        "counts": {
            "input_points": len(polyline),
            "resampled_points": len(sampled),
            "fitted_segments": len(fitted),
            "simplified_segments": len(simplified),
        },
        "fit_metrics": {
            "global_root_mean_square_error_m": root_mean_square_error,
            "global_maximum_deviation_m": max_dev,
            "source_coverage_ratio": coverage,
        },
        "closure_helpers": helper_info,
        "small_wiggle_cleanup": cleanup_info,
        "segments": segments_to_json_obj(simplified),
    }


def main() -> int:
    args = parse_args()
    in_path = pathlib.Path(args.input)
    out_json = pathlib.Path(args.output_json)
    out_xml = pathlib.Path(args.output_xml)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_xml.parent.mkdir(parents=True, exist_ok=True)

    data = json.loads(in_path.read_text(encoding="utf-8"))
    polyline = data.get("polyline")
    if not polyline:
        raise SystemExit("Input JSON has no 'polyline' field")

    xy = to_xy_dicts(polyline, name_output_key="way_name", name_keys=("way_name",))
    sampled = resample(xy, args.resample_step)
    settings = initial_fit_settings(args)
    start_pose = Pose(sampled[0]["x"], sampled[0]["y"], heading(sampled[0], sampled[1]))
    if args.corner_fit:
        start_pose, fitted, simplified, cleanup_info, helper_info, coverage, adaptive_attempts = run_corner_fit_mode(
            sampled, args, float(data.get("length_m", 0.0) or 0.0)
        )
        curvature_anchors: set[int] = set()
    else:
        fitted, simplified, cleanup_info, helper_info, curvature_anchors, coverage, adaptive_attempts = run_adaptive_fit_mode(sampled, start_pose, args, settings)

    if not args.allow_partial and coverage < args.min_coverage:
        last_i1 = simplified[-1].i1 if simplified else 0
        raise SystemExit(
            "Fit did not cover enough of the source path after adaptive retries: "
            f"coverage={coverage * 100.0:.1f}% (last source index {last_i1}/{len(sampled) - 1}). "
            "Try a lower minimum segment length, lower span stride, higher beam width, or pass --allow-partial for diagnostics."
        )

    # Global fit metrics from origin, useful to detect accumulation drift.
    model_pts = reconstruct_from_segments(start_pose, simplified)
    root_mean_square_error, max_dev = global_path_error(
        model_pts,
        sampled,
        sample_count=max(40, args.global_sample_count),
    )

    if args.output_svg:
        write_svg(pathlib.Path(args.output_svg), sampled, model_pts)

    out_obj = build_output_object(
        in_path,
        args,
        settings,
        polyline,
        sampled,
        fitted,
        simplified,
        coverage,
        root_mean_square_error,
        max_dev,
        helper_info,
        cleanup_info,
        adaptive_attempts,
        curvature_anchors,
    )

    # Keep geographic source coordinates in the intermediate JSON so XML
    # assembly can choose a different start segment without losing the datum.
    import hashlib

    from torcs_track_tools.core.track_georeference import geographic_polyline, reference_at_pose

    try:
        out_obj["georeference_source"] = {"polyline": geographic_polyline(data)}
        out_obj["georeference_start"] = reference_at_pose(data, start_pose.x, start_pose.y, start_pose.heading)
        out_obj["georeference_snippet_sha256"] = hashlib.sha256(segments_to_xml(simplified).encode("utf-8")).hexdigest()
    except ValueError:
        pass
    out_json.write_text(json.dumps(out_obj, indent=2), encoding="utf-8")
    out_xml.write_text(segments_to_xml(simplified), encoding="utf-8")

    print(f"Input points: {len(polyline)}")
    print(f"Resampled points: {len(sampled)}")
    print(f"Fitted segments: {len(fitted)}")
    print(f"Simplified segments: {len(simplified)}")
    print(f"Global root mean square error: {root_mean_square_error:.2f} m")
    print(f"Global maximum deviation: {max_dev:.2f} m")
    print(f"Source coverage: {coverage * 100.0:.1f}%")
    print(f"Wrote JSON: {out_json}")
    print(f"Wrote XML: {out_xml}")
    if args.output_svg:
        print(f"Wrote scalable vector graphics: {args.output_svg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
