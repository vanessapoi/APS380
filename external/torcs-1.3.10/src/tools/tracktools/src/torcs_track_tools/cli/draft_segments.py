#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : draft_segments.py
#     created              : 01 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Draft TORCS track segments from a cached centerline.

This is the default segment drafter used by the mainline rebuild workflow. It
uses a dynamic-programming biarc solver to produce a closure-friendly segment
chain while remaining available as an inspectable standalone stage.

Algorithm outline:

1. Normalize the input centerline into local X/Y meters, then resample it at a
   uniform arc-length step so OSM, image, and GPS-derived sources share one
   fitting representation.
2. Build a smoothed curvature profile and simplify it into coarse straight,
   left, and right events. These events are soft hints, not hard labels; they
   discourage washing out chicanes and long straights without preventing a
   better local fit.
3. Treat each resampled point as a graph node. For every allowed span length,
   create candidate graph edges that exactly connect the start and end poses
   using one constant-radius arc, a variable-radius transition when warranted,
   or a biarc pair.
4. Score each edge with local fit error, max deviation, curvature mismatch,
   source/model length ratio, segment count, and event-crossing penalties.
   Dynamic programming then selects the lowest-cost path around the full loop.
5. Re-evaluate the selected path as a TORCS segment chain, then perform guarded
   near-straight cleanup so closure tooling has real straight controls while
   preserving fit quality.

The drafter only emits a plausible mainline segment list plus diagnostics.
Sub-millimeter closure is still handled later by ``torcs-close-loop`` and
``trackgen`` validation.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
from dataclasses import asdict, dataclass

from torcs_track_tools.core.geometry import (
    MAX_TORCS_RADIUS_M,
    Pose,
    Sample,
    Segment,
    advance_segment,
    biarc_segment_candidates,
    curvature_profile,
    pose_to_pose_arc,
    sample_segment,
    sample_segments,
    segment_length_like,
    variable_pose_to_pose_turn_candidates,
)
from torcs_track_tools.core.polyline import source_point_name, to_xy_dicts


@dataclass(frozen=True)
class DraftResult:
    segment: Segment
    source_i0: int
    source_i1: int
    rmse_m: float
    max_dev_m: float
    end_error_m: float
    heading_error_deg: float
    source_turn_deg: float = 0.0
    radius_error_ratio: float = 0.0
    curvature_sign_error: bool = False
    fallback: bool = False
    curvature_rmse: float = 0.0
    curvature_max_abs: float = 0.0


@dataclass(frozen=True)
class DraftValidation:
    track_length_m: float
    model_length_m: float
    segment_count: int
    segment_density_per_km: float
    min_segment_length_m: float
    median_segment_length_m: float
    short_segment_count: int
    short_segment_total_length_m: float
    fallback_count: int
    fallback_total_length_m: float
    high_error_segment_count: int
    high_error_total_length_m: float
    final_drift_m: float
    final_heading_drift_deg: float
    global_mean_error_m: float
    global_rmse_m: float
    global_max_error_m: float
    max_local_rmse_m: float
    max_local_dev_m: float
    max_end_error_m: float
    max_heading_error_deg: float
    max_curvature_rmse: float
    max_curvature_abs_error: float


@dataclass(frozen=True)
class CurvatureRun:
    kind: str
    i0: int
    i1: int
    median_radius_m: float


@dataclass(frozen=True)
class DPEdge:
    i0: int
    i1: int
    segments: list[Segment]
    cost: float
    rmse_m: float
    max_dev_m: float
    curvature_rmse: float
    fallback: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Draft TORCS segments from a cached centerline using the DP biarc solver")
    parser.add_argument("--input", required=True, help="Input centerline cache JSON")
    parser.add_argument("--output-json", required=True, help="Output draft segment JSON")
    parser.add_argument("--output-xml", required=True, help="Output segment XML snippet")
    parser.add_argument("--output-svg", default="", help="Optional source/model overlay SVG")
    parser.add_argument("--output-curvature-json", default="", help=argparse.SUPPRESS)
    parser.add_argument("--resample-step", type=float, default=4.0, help=argparse.SUPPRESS)
    parser.add_argument("--min-seg-len", type=float, default=12.0, help=argparse.SUPPRESS)
    parser.add_argument("--max-seg-len", type=float, default=180.0, help=argparse.SUPPRESS)
    parser.add_argument("--max-dev", type=float, default=None, help=argparse.SUPPRESS)
    return parser.parse_args()


def base_segment_name(name: str) -> str:
    """Strip only deterministic numeric suffixes, preserving hyphenated names."""
    return re.sub(r"-\d+$", "", name)


def dist(a: dict | Sample, b: dict | Sample) -> float:
    return math.hypot(float(a.x if isinstance(a, Sample) else a["x"]) - float(b.x if isinstance(b, Sample) else b["x"]), float(a.y if isinstance(a, Sample) else a["y"]) - float(b.y if isinstance(b, Sample) else b["y"]))


def heading(a: dict, b: dict) -> float:
    return math.atan2(b["y"] - a["y"], b["x"] - a["x"])


def norm_angle(a: float) -> float:
    while a <= -math.pi:
        a += 2.0 * math.pi
    while a > math.pi:
        a -= 2.0 * math.pi
    return a


def source_turn(points: list[dict], pose: Pose, i0: int, i1: int) -> float:
    if i1 <= i0:
        return 0.0
    return norm_angle(heading(points[i1 - 1], points[i1]) - pose.heading)


def curve_metrics(segment: Segment, src_len: float, src_turn_rad: float) -> tuple[float, bool]:
    src_turn_abs = abs(src_turn_rad)
    if src_turn_abs < math.radians(1.0):
        if segment.kind == "str" or abs(segment.arc_deg) < 1.0:
            return 0.0, False
        return min(10.0, abs(segment.arc_deg) / 10.0), True

    src_sign = 1.0 if src_turn_rad > 0.0 else -1.0
    seg_sign = 0.0 if segment.kind == "str" else (1.0 if segment.kind == "lft" else -1.0)
    sign_error = seg_sign != 0.0 and seg_sign != src_sign
    if segment.kind == "str":
        return 1.0, False

    source_radius = src_len / src_turn_abs
    if source_radius <= 1e-9 or segment.radius <= 1e-9:
        return 10.0, sign_error
    ratio = max(segment.radius, source_radius) / min(segment.radius, source_radius) - 1.0
    return min(10.0, ratio), sign_error


def segment_curvature(segment: Segment) -> float:
    if segment.kind == "str" or segment.radius <= 1e-12:
        return 0.0
    end_radius = segment.radius if segment.end_radius is None else segment.end_radius
    return (1.0 if segment.kind == "lft" else -1.0) / max(1e-12, 0.5 * (segment.radius + end_radius))


def segment_curvature_at_fraction(segment: Segment, fraction: float) -> float:
    if segment.kind == "str" or segment.radius <= 1e-12:
        return 0.0
    end_radius = segment.radius if segment.end_radius is None else segment.end_radius
    radius = segment.radius + (end_radius - segment.radius) * max(0.0, min(1.0, fraction))
    return (1.0 if segment.kind == "lft" else -1.0) / max(1e-12, radius)


def curvature_deviation(segment: Segment, profile: list, i0: int, i1: int) -> tuple[float, float]:
    if not profile or i1 <= i0:
        return 0.0, 0.0
    lo = max(0, i0)
    hi = min(len(profile), i1 + 1)
    span = max(1, i1 - i0)
    values = [sample.curvature - segment_curvature_at_fraction(segment, (idx - i0) / span) for idx, sample in enumerate(profile[lo:hi], start=lo)]
    if not values:
        return 0.0, 0.0
    return math.sqrt(sum(v * v for v in values) / len(values)), max(abs(v) for v in values)


def curvature_kind(curvature: float) -> str:
    if curvature > 0.0:
        return "lft"
    if curvature < 0.0:
        return "rgt"
    return "str"


def curvature_runs(profile: list, min_len: int = 3) -> list[CurvatureRun]:
    if not profile:
        return []
    raw: list[CurvatureRun] = []
    start = 0
    kind = curvature_kind(profile[0].curvature)
    for i in range(1, len(profile)):
        next_kind = curvature_kind(profile[i].curvature)
        if next_kind == kind:
            continue
        raw.append(curvature_run_from_span(profile, kind, start, i - 1))
        start = i
        kind = next_kind
    raw.append(curvature_run_from_span(profile, kind, start, len(profile) - 1))

    merged: list[CurvatureRun] = []
    for run in raw:
        if merged and run.i1 - run.i0 + 1 < min_len:
            prev = merged.pop()
            merged.append(curvature_run_from_span(profile, prev.kind, prev.i0, run.i1))
        else:
            merged.append(run)
    return merged


def curvature_run_from_span(profile: list, kind: str, i0: int, i1: int) -> CurvatureRun:
    radii = [sample.radius for sample in profile[i0 : i1 + 1] if not math.isinf(sample.radius)]
    return CurvatureRun(kind, i0, i1, median_float(radii) if radii else math.inf)


def simplify_curvature_runs(profile: list, runs: list[CurvatureRun], min_length_m: float = 24.0, shallow_radius_m: float = 1200.0, radius_ratio: float = 0.35) -> list[CurvatureRun]:
    if not runs:
        return []
    simplified = []
    for run in runs:
        length = profile[run.i1].s - profile[run.i0].s if profile and run.i1 < len(profile) else float(run.i1 - run.i0)
        kind = "str" if run.kind == "str" or math.isinf(run.median_radius_m) or run.median_radius_m >= shallow_radius_m else run.kind
        current = CurvatureRun(kind, run.i0, run.i1, run.median_radius_m)
        if simplified and length < min_length_m:
            prev = simplified.pop()
            simplified.append(curvature_run_from_span(profile, prev.kind, prev.i0, current.i1))
            continue
        if simplified and should_merge_curvature_runs(simplified[-1], current, radius_ratio):
            prev = simplified.pop()
            simplified.append(curvature_run_from_span(profile, prev.kind, prev.i0, current.i1))
        else:
            simplified.append(current)
    return simplified


def should_merge_curvature_runs(a: CurvatureRun, b: CurvatureRun, radius_ratio: float) -> bool:
    if a.kind == b.kind:
        if a.kind == "str":
            return True
        if math.isinf(a.median_radius_m) or math.isinf(b.median_radius_m):
            return False
        return abs(a.median_radius_m - b.median_radius_m) / max(a.median_radius_m, b.median_radius_m) <= radius_ratio
    return False


def event_boundary_count(events: list[CurvatureRun], i0: int, i1: int) -> int:
    return sum(1 for event in events[:-1] if i0 < event.i1 < i1)


def edge_allows_variable_transition(events: list[CurvatureRun], i0: int, i1: int) -> bool:
    boundaries = [event.i1 for event in events[:-1] if i0 < event.i1 < i1]
    if len(boundaries) != 1:
        return False
    left = boundaries[0] - i0
    right = i1 - boundaries[0]
    return 2 <= left <= 10 and 2 <= right <= 10


def event_crossing_penalty(events: list[CurvatureRun], i0: int, i1: int, segment_count: int) -> float:
    crossings = event_boundary_count(events, i0, i1)
    unmodeled_crossings = max(0, crossings - max(0, segment_count - 1))
    return 6.0 * crossings + 24.0 * unmodeled_crossings


def resample(points: list[dict], step: float) -> list[dict]:
    if len(points) < 2:
        return points
    if dist(points[0], points[-1]) < step * 0.5:
        points = points[:-1]
    closed = points + [points[0]]
    total = sum(dist(closed[i - 1], closed[i]) for i in range(1, len(closed)))
    count = max(8, int(total / step))
    out = []
    seg_i = 1
    seg_start_s = 0.0
    seg_len = dist(closed[0], closed[1])
    for k in range(count):
        target = total * k / count
        while seg_i < len(closed) - 1 and seg_start_s + seg_len < target:
            seg_start_s += seg_len
            seg_i += 1
            seg_len = dist(closed[seg_i - 1], closed[seg_i])
        a = closed[seg_i - 1]
        b = closed[seg_i]
        u = 0.0 if seg_len <= 1e-9 else (target - seg_start_s) / seg_len
        name = source_point_name(a if u < 0.5 else b) or source_point_name(a) or source_point_name(b)
        out.append({"x": a["x"] + (b["x"] - a["x"]) * u, "y": a["y"] + (b["y"] - a["y"]) * u, "name": name})
    return out


def dominant_source_name(points: list[dict], i0: int, i1: int) -> str:
    counts: dict[str, int] = {}
    if not points:
        return ""
    for i in range(max(0, i0), max(i0, i1) + 1):
        name = source_point_name(points[i % len(points)])
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)


def rename_results_from_source(points: list[dict], results: list[DraftResult]) -> list[DraftResult]:
    counts: dict[str, int] = {}
    renamed = []
    for draft_index, result in enumerate(results, start=1):
        source_name = dominant_source_name(points, result.source_i0, result.source_i1)
        if source_name:
            base_name = base_segment_name(source_name)
            count = counts.get(base_name, 0) + 1
            counts[base_name] = count
            name = base_name if count == 1 else f"{base_name}-{count}"
        else:
            name = f"draft-{draft_index}"
        renamed.append(
            DraftResult(
                Segment(name, result.segment.kind, result.segment.length, result.segment.radius, result.segment.arc_deg, result.segment.end_radius, result.segment.profil_steps_length),
                result.source_i0,
                result.source_i1,
                result.rmse_m,
                result.max_dev_m,
                result.end_error_m,
                result.heading_error_deg,
                result.source_turn_deg,
                result.radius_error_ratio,
                result.curvature_sign_error,
                result.fallback,
                result.curvature_rmse,
                result.curvature_max_abs,
            )
        )
    return renamed


def arc_len(points: list[dict], i0: int, i1: int) -> float:
    return sum(dist(points[i - 1], points[i]) for i in range(i0 + 1, i1 + 1))


def segment_length(segment: Segment) -> float:
    return segment_length_like(segment)


def median_float(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def sample_points_by_arc(points: list[dict | Sample], count: int) -> list[dict]:
    arr = [{"x": float(points[0].x if isinstance(points[0], Sample) else points[0]["x"]), "y": float(points[0].y if isinstance(points[0], Sample) else points[0]["y"]), "s": 0.0}]
    total = 0.0
    for i in range(1, len(points)):
        total += dist(points[i - 1], points[i])
        arr.append({"x": float(points[i].x if isinstance(points[i], Sample) else points[i]["x"]), "y": float(points[i].y if isinstance(points[i], Sample) else points[i]["y"]), "s": total})
    out = []
    k = 1
    for i in range(count):
        target = total * i / max(1, count - 1)
        while k < len(arr) and arr[k]["s"] < target:
            k += 1
        if k >= len(arr):
            out.append(arr[-1])
            continue
        a = arr[k - 1]
        b = arr[k]
        u = 0.0 if b["s"] == a["s"] else (target - a["s"]) / (b["s"] - a["s"])
        out.append({"x": a["x"] + (b["x"] - a["x"]) * u, "y": a["y"] + (b["y"] - a["y"]) * u})
    return out


def span_error(source: list[dict], model: list[Sample]) -> tuple[float, float]:
    count = max(8, min(80, max(len(source), len(model))))
    src = sample_points_by_arc(source, count)
    mdl = sample_points_by_arc(model, count)
    errors = [dist(src[i], mdl[i]) for i in range(count)]
    return math.sqrt(sum(e * e for e in errors) / len(errors)), max(errors)


def local_model(pose: Pose, segment: Segment, step: float) -> tuple[Pose, list[Sample]]:
    end, samples = sample_segment(pose, segment, 0.0, step)
    return end, [Sample(pose.x, pose.y, 0.0, pose.heading, segment.name), *samples]


def evaluate_result(points: list[dict], pose: Pose, result: DraftResult, name: str, step: float, profile: list | None = None) -> DraftResult:
    source = points[result.source_i0 : result.source_i1 + 1]
    src_len = arc_len(points, result.source_i0, result.source_i1)
    src_heading = heading(points[result.source_i1 - 1], points[result.source_i1])
    src_turn = source_turn(points, pose, result.source_i0, result.source_i1)
    end, model = local_model(pose, result.segment, step)
    rmse, max_dev = span_error(source, model)
    end_error = math.hypot(end.x - points[result.source_i1]["x"], end.y - points[result.source_i1]["y"])
    heading_error = abs(math.degrees(norm_angle(end.heading - src_heading)))
    radius_error, sign_error = curve_metrics(result.segment, src_len, src_turn)
    curv_rmse, curv_max = curvature_deviation(result.segment, profile or [], result.source_i0, result.source_i1)
    return DraftResult(
        Segment(name, result.segment.kind, result.segment.length, result.segment.radius, result.segment.arc_deg, result.segment.end_radius, result.segment.profil_steps_length),
        result.source_i0,
        result.source_i1,
        rmse,
        max_dev,
        end_error,
        heading_error,
        math.degrees(src_turn),
        radius_error,
        sign_error,
        result.fallback,
        curv_rmse,
        curv_max,
    )


def evaluate_results(points: list[dict], results: list[DraftResult], step: float, profile: list | None = None) -> list[DraftResult]:
    pose = Pose(points[0]["x"], points[0]["y"], heading(points[0], points[1]))
    evaluated: list[DraftResult] = []
    for i, result in enumerate(results, start=1):
        out = evaluate_result(points, pose, result, f"draft-{i}", step, profile)
        evaluated.append(out)
        pose = advance_segment(pose, out.segment)
    return evaluated


def source_pose(points: list[dict], i: int) -> Pose:
    if i <= 0:
        return Pose(points[0]["x"], points[0]["y"], heading(points[0], points[1]))
    if i >= len(points) - 1:
        return Pose(points[i]["x"], points[i]["y"], heading(points[0], points[1]))
    return Pose(points[i]["x"], points[i]["y"], heading(points[i - 1], points[i + 1]))


def profile_pose(points: list[dict], profile: list, i: int) -> Pose:
    if not profile:
        return source_pose(points, i)
    idx = max(0, min(i, len(points) - 1))
    if idx <= 0 or idx >= len(points) - 1:
        return Pose(points[idx]["x"], points[idx]["y"], heading(points[0], points[1]))
    heading_idx = idx
    return Pose(points[idx]["x"], points[idx]["y"], profile[heading_idx].heading)


def merge_edge_segments(segments: list[Segment], name_prefix: str) -> list[Segment]:
    merged: list[Segment] = []
    for segment in segments:
        if segment_length(segment) <= 1e-8:
            continue
        if merged and merged[-1].kind == "str" and segment.kind == "str":
            prev = merged.pop()
            merged.append(Segment(prev.name, "str", length=prev.length + segment.length))
            continue
        merged.append(Segment(f"{name_prefix}-{len(merged) + 1}", segment.kind, segment.length, segment.radius, segment.arc_deg, segment.end_radius, segment.profil_steps_length))
    return merged


def bounded_radius_pose_segments(start: Pose, end: Pose, segment: Segment, max_radius: float = MAX_TORCS_RADIUS_M) -> list[Segment]:
    turn = norm_angle(end.heading - start.heading)
    turn_abs = abs(turn)
    if turn_abs <= 1e-12:
        return [Segment(segment.name, "str", length=math.hypot(end.x - start.x, end.y - start.y))]

    kind = "lft" if turn > 0.0 else "rgt"
    bounded_turn = Segment(f"{segment.name}-turn", kind, radius=max_radius, arc_deg=math.degrees(turn_abs))
    turn_end = advance_segment(start, bounded_turn)
    residual_x = end.x - turn_end.x
    residual_y = end.y - turn_end.y
    start_x = math.cos(start.heading)
    start_y = math.sin(start.heading)
    end_x = math.cos(end.heading)
    end_y = math.sin(end.heading)
    det = start_x * end_y - start_y * end_x
    if abs(det) <= 1e-12:
        return []

    before = (residual_x * end_y - residual_y * end_x) / det
    after = (start_x * residual_y - start_y * residual_x) / det
    if before < -1e-5 or after < -1e-5:
        return []

    pieces = []
    if before > 1e-8:
        pieces.append(Segment(f"{segment.name}-pre", "str", length=before))
    pieces.append(bounded_turn)
    if after > 1e-8:
        pieces.append(Segment(f"{segment.name}-post", "str", length=after))
    return pieces


def radius_bounded_candidate(start: Pose, segments: list[Segment], max_radius: float = MAX_TORCS_RADIUS_M) -> list[Segment]:
    bounded = []
    original_pose = start
    for segment in segments:
        original_end = advance_segment(original_pose, segment)
        end_radius = segment.radius if segment.end_radius is None else segment.end_radius
        if segment.kind == "str" or max(segment.radius, end_radius) <= max_radius:
            pieces = [segment]
        else:
            pieces = bounded_radius_pose_segments(original_pose, original_end, segment, max_radius)
            if not pieces:
                return []
        bounded.extend(pieces)
        original_pose = original_end
    return bounded


def span_radius_hint(profile: list, i0: int, i1: int, kind: str, start_side: bool) -> float | None:
    if not profile or i1 <= i0:
        return None
    width = max(3, (i1 - i0 + 1) // 3)
    lo = i0 if start_side else max(i0, i1 - width + 1)
    hi = min(i1 + 1, i0 + width) if start_side else i1 + 1
    radii = [sample.radius for sample in profile[max(0, lo) : min(len(profile), hi)] if curvature_kind(sample.curvature) == kind and not math.isinf(sample.radius)]
    return median_float(radii) if radii else None


def variable_transition_turn(start: Pose, end: Pose) -> tuple[float, str]:
    turn = norm_angle(end.heading - start.heading)
    return turn, "lft" if turn > 0.0 else "rgt"


def transition_profile_radii(profile: list, i0: int, i1: int, kind: str) -> tuple[list[float], int]:
    samples = profile[max(0, i0) : min(len(profile), i1 + 1)]
    same_radii = [sample.radius for sample in samples if curvature_kind(sample.curvature) == kind and not math.isinf(sample.radius)]
    straight_count = sum(1 for sample in samples if curvature_kind(sample.curvature) == "str")
    return same_radii, straight_count


def radii_suggest_variable_transition(same_radii: list[float], straight_count: int) -> bool:
    if len(same_radii) < 3:
        return False
    if median_float(same_radii) < 180.0 and max(same_radii) < 600.0:
        return False
    radius_ratio = max(same_radii) / max(min(same_radii), 1e-9)
    return straight_count >= 3 or radius_ratio >= 1.6 or max(same_radii) >= 600.0


def transition_straight_radius(start: Pose, end: Pose, turn_abs: float) -> float:
    chord = math.hypot(end.x - start.x, end.y - start.y)
    base_radius = max(2.0, chord / max(1e-6, 2.0 * math.sin(0.5 * turn_abs)))
    return min(MAX_TORCS_RADIUS_M, max(1500.0, base_radius * 4.0))


def clamp_radius_pair(pair: tuple[float, float]) -> tuple[float, float]:
    return max(2.0, min(MAX_TORCS_RADIUS_M, pair[0])), max(2.0, min(MAX_TORCS_RADIUS_M, pair[1]))


def transition_seed_pairs(profile: list, i0: int, i1: int, kind: str, same_radii: list[float], straight_radius: float) -> list[tuple[float, float]]:
    start_hint = span_radius_hint(profile, i0, i1, kind, True) or straight_radius
    end_hint = span_radius_hint(profile, i0, i1, kind, False) or straight_radius
    seeds = [(start_hint, end_hint), (straight_radius, end_hint), (start_hint, straight_radius)]
    if len(same_radii) >= 3:
        seeds.extend([(max(same_radii), min(same_radii)), (min(same_radii), max(same_radii))])
    return seeds


def variable_transition_radius_seeds(profile: list, i0: int, i1: int, start: Pose, end: Pose) -> list[tuple[float, float]]:
    turn, kind = variable_transition_turn(start, end)
    turn_abs = abs(turn)
    if not profile or turn_abs < math.radians(1.0) or turn_abs > math.radians(30.0) or i1 <= i0:
        return []
    same_radii, straight_count = transition_profile_radii(profile, i0, i1, kind)
    if not radii_suggest_variable_transition(same_radii, straight_count):
        return []

    straight_radius = transition_straight_radius(start, end, turn_abs)
    return [clamp_radius_pair(pair) for pair in transition_seed_pairs(profile, i0, i1, kind, same_radii, straight_radius)]


def exact_pose_candidates(start: Pose, end: Pose, name_prefix: str, profile: list | None = None, i0: int = 0, i1: int = 0, allow_variable: bool = True) -> list[list[Segment]]:
    candidates: list[list[Segment]] = []
    single = pose_to_pose_arc(start, end, f"{name_prefix}-1")
    if single is not None:
        candidates.append([single])
    if allow_variable:
        variable_seeds = variable_transition_radius_seeds(profile or [], i0, i1, start, end)
        if variable_seeds:
            candidates.extend([segment] for segment in variable_pose_to_pose_turn_candidates(start, end, f"{name_prefix}-var", variable_seeds))
    candidates.extend(biarc_segment_candidates(start, end, name_prefix))
    bounded = [radius_bounded_candidate(start, candidate) for candidate in candidates if candidate]
    return [merge_edge_segments(candidate, name_prefix) for candidate in bounded if candidate]


def edge_segment_spans(segments: list[Segment], i0: int, i1: int) -> list[tuple[Segment, int, int]]:
    total_len = sum(segment_length(segment) for segment in segments)
    source_span = max(1, i1 - i0)
    cursor = i0
    spans = []
    for idx, segment in enumerate(segments):
        if idx == len(segments) - 1:
            next_cursor = i1
        else:
            fraction = 1.0 / len(segments) if total_len <= 1e-9 else segment_length(segment) / total_len
            next_cursor = min(i1 - (len(segments) - idx - 1), max(cursor + 1, i0 + int(round(source_span * fraction))))
        spans.append((segment, cursor, next_cursor))
        cursor = next_cursor
    return spans


def event_overlap_length_m(profile: list, overlap_i0: int, overlap_i1: int) -> float:
    if profile and overlap_i1 < len(profile):
        return profile[overlap_i1].s - profile[overlap_i0].s
    return float(overlap_i1 - overlap_i0)


def event_mismatch_penalty(segment: Segment, event: CurvatureRun, overlap_m: float) -> float:
    if event.kind == "str":
        return 0.25 * overlap_m
    if segment.kind == "str":
        return 0.10 * overlap_m
    return 0.55 * overlap_m


def segment_event_agreement_penalty(segment: Segment, event: CurvatureRun, profile: list, seg_i0: int, seg_i1: int) -> float:
    overlap_i0 = max(seg_i0, event.i0)
    overlap_i1 = min(seg_i1, event.i1)
    if overlap_i1 <= overlap_i0:
        return 0.0
    overlap_m = event_overlap_length_m(profile, overlap_i0, overlap_i1)
    if overlap_m < 8.0 or segment.kind == event.kind:
        return 0.0
    return event_mismatch_penalty(segment, event, overlap_m)


def event_segment_agreement_penalty(events: list[CurvatureRun], profile: list, i0: int, i1: int, segments: list[Segment]) -> float:
    return sum(
        segment_event_agreement_penalty(segment, event, profile, seg_i0, seg_i1)
        for segment, seg_i0, seg_i1 in edge_segment_spans(segments, i0, i1)
        for event in events
    )


def curvature_variation_penalty(profile: list, i0: int, i1: int, segments: list[Segment], deadband: float = 0.004) -> float:
    if not profile or i1 <= i0:
        return 0.0
    penalty = 0.0
    for _, seg_i0, seg_i1 in edge_segment_spans(segments, i0, i1):
        if seg_i1 <= seg_i0 + 2:
            continue
        lo = max(0, seg_i0)
        hi = min(len(profile), seg_i1 + 1)
        values = [sample.curvature for sample in profile[lo:hi]]
        if not values:
            continue
        variation = max(values) - min(values)
        excess = max(0.0, variation - deadband)
        if excess <= 0.0:
            continue
        length = profile[hi - 1].s - profile[lo].s
        penalty += 36.0 * length * excess
    return penalty


def edge_metrics(points: list[dict], profile: list, i0: int, i1: int, start: Pose, segments: list[Segment], step: float) -> tuple[float, float, float, float, float]:
    source = points[i0 : i1 + 1]
    model = sample_segments(segments, start, step)
    rmse, max_dev = span_error(source, model)
    curv_values = []
    for segment, cursor, next_cursor in edge_segment_spans(segments, i0, i1):
        curv_rmse, _ = curvature_deviation(segment, profile, cursor, next_cursor)
        curv_values.append(curv_rmse)
    curv_rmse = math.sqrt(sum(v * v for v in curv_values) / len(curv_values)) if curv_values else 0.0
    model_len = sum(segment_length(segment) for segment in segments)
    source_len = arc_len(points, i0, i1)
    length_ratio = model_len / max(1e-6, source_len)
    return rmse, max_dev, curv_rmse, model_len, length_ratio


def dp_edge_cost(rmse: float, max_dev: float, curv_rmse: float, model_len: float, length_ratio: float, segment_count: int, max_dev_limit: float) -> float:
    overflow = max(0.0, max_dev - max_dev_limit)
    length_penalty = 25.0 * abs(math.log(max(1e-6, length_ratio)))
    return 0.025 * model_len * rmse + 2.0 * max_dev + 12.0 * overflow * overflow + 250.0 * curv_rmse + length_penalty + 12.0 * segment_count


def make_dp_edge(points: list[dict], profile: list, i0: int, i1: int, step: float, max_dev_limit: float, events: list[CurvatureRun] | None = None) -> DPEdge | None:
    start = profile_pose(points, profile, i0)
    end = profile_pose(points, profile, i1)
    best: DPEdge | None = None
    allow_variable = edge_allows_variable_transition(events or [], i0, i1)
    for segments in exact_pose_candidates(start, end, f"edge-{i0}-{i1}", profile, i0, i1, allow_variable):
        rmse, max_dev, curv_rmse, model_len, length_ratio = edge_metrics(points, profile, i0, i1, start, segments, step)
        cost = dp_edge_cost(rmse, max_dev, curv_rmse, model_len, length_ratio, len(segments), max_dev_limit)
        cost += event_crossing_penalty(events or [], i0, i1, len(segments))
        cost += event_segment_agreement_penalty(events or [], profile, i0, i1, segments)
        cost += curvature_variation_penalty(profile, i0, i1, segments)
        fallback = max_dev > max_dev_limit
        edge = DPEdge(i0, i1, segments, cost, rmse, max_dev, curv_rmse, fallback)
        if best is None or edge.cost < best.cost:
            best = edge
    return best


def edge_to_draft_results(edge: DPEdge, name_start: int) -> list[DraftResult]:
    if len(edge.segments) == 1:
        return [DraftResult(Segment(f"draft-{name_start}", edge.segments[0].kind, edge.segments[0].length, edge.segments[0].radius, edge.segments[0].arc_deg, edge.segments[0].end_radius, edge.segments[0].profil_steps_length), edge.i0, edge.i1, edge.rmse_m, edge.max_dev_m, 0.0, 0.0, fallback=edge.fallback, curvature_rmse=edge.curvature_rmse)]

    results = []
    for idx, (segment, cursor, next_cursor) in enumerate(edge_segment_spans(edge.segments, edge.i0, edge.i1)):
        results.append(DraftResult(Segment(f"draft-{name_start + idx}", segment.kind, segment.length, segment.radius, segment.arc_deg, segment.end_radius, segment.profil_steps_length), cursor, next_cursor, edge.rmse_m, edge.max_dev_m, 0.0, 0.0, fallback=edge.fallback, curvature_rmse=edge.curvature_rmse))
    return results


def near_straight_arc_as_straight(segment: Segment, max_arc_deg: float = 1.0, max_lateral_m: float = 0.5) -> Segment:
    if segment.kind == "str":
        return segment
    arc_rad = math.radians(segment.arc_deg)
    lateral = segment.radius * (1.0 - math.cos(abs(arc_rad)))
    if abs(segment.arc_deg) <= max_arc_deg and lateral <= max_lateral_m:
        return Segment(segment.name, "str", length=segment_length(segment))
    return segment


def signed_segment_arc_deg(segment: Segment) -> float:
    if segment.kind == "lft":
        return segment.arc_deg
    if segment.kind == "rgt":
        return -segment.arc_deg
    return 0.0


def draft_result_for_segment(segment: Segment, source_i0: int, source_i1: int) -> DraftResult:
    return DraftResult(segment, source_i0, source_i1, 0.0, 0.0, 0.0, 0.0)


def append_with_straight_merge(results: list[DraftResult], current: DraftResult) -> None:
    if results and results[-1].segment.kind == "str" and current.segment.kind == "str":
        prev = results.pop()
        merged = Segment(prev.segment.name, "str", length=prev.segment.length + current.segment.length)
        results.append(draft_result_for_segment(merged, prev.source_i0, current.source_i1))
        return
    results.append(current)


def replace_results_span(results: list[DraftResult], start_i: int, count: int, replacement: DraftResult) -> list[DraftResult]:
    out: list[DraftResult] = []
    for i, result in enumerate(results):
        if i == start_i:
            append_with_straight_merge(out, replacement)
        if start_i <= i < start_i + count:
            continue
        append_with_straight_merge(out, result)
    return out


def has_closure_control_straight(results: list[DraftResult], min_length_m: float = 20.0) -> bool:
    return any(result.segment.kind == "str" and segment_length(result.segment) >= min_length_m for result in results)


def add_single_control_straight(work: list[dict], results: list[DraftResult], step: float, profile: list) -> list[DraftResult] | None:
    best_i = -1
    best_score = math.inf
    for i, result in enumerate(results):
        segment = near_straight_arc_as_straight(result.segment, max_arc_deg=0.1, max_lateral_m=0.05)
        if segment.kind != "str" or segment_length(segment) < 20.0:
            continue
        score = abs(result.segment.arc_deg) - 0.0001 * segment_length(segment)
        if score < best_score:
            best_i = i
            best_score = score
    if best_i < 0:
        return None

    adjusted = []
    for i, result in enumerate(results):
        segment = near_straight_arc_as_straight(result.segment, max_arc_deg=0.1, max_lateral_m=0.05) if i == best_i else result.segment
        adjusted.append(
            DraftResult(
                segment,
                result.source_i0,
                result.source_i1,
                result.rmse_m,
                result.max_dev_m,
                result.end_error_m,
                result.heading_error_deg,
                result.source_turn_deg,
                result.radius_error_ratio,
                result.curvature_sign_error,
                result.fallback,
                result.curvature_rmse,
                result.curvature_max_abs,
            )
        )
    return evaluate_results(work, adjusted, step, profile)


def is_near_straight_counterbend(result: DraftResult, nxt: DraftResult | None) -> bool:
    if nxt is None:
        return False
    if result.segment.kind not in ("lft", "rgt") or nxt.segment.kind not in ("lft", "rgt"):
        return False
    if result.segment.kind == nxt.segment.kind:
        return False
    if near_straight_arc_as_straight(result.segment).kind != "str":
        return False
    if near_straight_arc_as_straight(nxt.segment).kind != "str":
        return False
    return abs(signed_segment_arc_deg(result.segment) + signed_segment_arc_deg(nxt.segment)) <= 0.5


def near_straight_cleanup_replacement(results: list[DraftResult], i: int) -> tuple[DraftResult, int] | None:
    result = results[i]
    nxt = results[i + 1] if i + 1 < len(results) else None
    if is_near_straight_counterbend(result, nxt):
        segment = Segment(result.segment.name, "str", length=segment_length(result.segment) + segment_length(nxt.segment))
        return draft_result_for_segment(segment, result.source_i0, nxt.source_i1), 2

    flat_segment = near_straight_arc_as_straight(result.segment, max_arc_deg=0.1, max_lateral_m=0.05)
    if flat_segment.kind == "str" and result.segment.kind != "str":
        return draft_result_for_segment(flat_segment, result.source_i0, result.source_i1), 1
    return None


def validation_allows_near_straight_cleanup(base_validation: DraftValidation, candidate_validation: DraftValidation) -> bool:
    limits = [
        (candidate_validation.final_drift_m, max(2.0, base_validation.final_drift_m + 2.0)),
        (abs(candidate_validation.final_heading_drift_deg), max(2.0, abs(base_validation.final_heading_drift_deg) + 2.0)),
        (candidate_validation.global_rmse_m, base_validation.global_rmse_m * 1.03 + 0.10),
        (candidate_validation.global_max_error_m, base_validation.global_max_error_m * 1.10 + 0.50),
    ]
    return all(value <= limit for value, limit in limits)


def validation_allows_control_straight(base_validation: DraftValidation, control_validation: DraftValidation) -> bool:
    limits = [
        (control_validation.final_drift_m, max(5.0, base_validation.final_drift_m + 5.0)),
        (abs(control_validation.final_heading_drift_deg), max(0.5, abs(base_validation.final_heading_drift_deg) + 0.5)),
        (control_validation.global_rmse_m, base_validation.global_rmse_m * 1.03 + 0.10),
        (control_validation.global_max_error_m, base_validation.global_max_error_m * 1.10 + 0.50),
    ]
    return all(value <= limit for value, limit in limits)


def evaluate_near_straight_replacement(source: list[dict], work: list[dict], accepted: list[DraftResult], step: float, profile: list, base_validation: DraftValidation, i: int, consume: int, replacement: DraftResult) -> list[DraftResult] | None:
    proposed = replace_results_span(accepted, i, consume, replacement)
    candidate = evaluate_results(work, proposed, step, profile)
    candidate_validation = validate_draft(source, candidate)
    if validation_allows_near_straight_cleanup(base_validation, candidate_validation):
        return candidate
    return None


def control_straight_fallback(source: list[dict], work: list[dict], results: list[DraftResult], step: float, profile: list, base_validation: DraftValidation) -> list[DraftResult] | None:
    if has_closure_control_straight(results):
        return None
    control_candidate = add_single_control_straight(work, results, step, profile)
    if control_candidate is None:
        return None
    control_validation = validate_draft(source, control_candidate)
    if validation_allows_control_straight(base_validation, control_validation):
        return control_candidate
    return None


def simplify_near_straight_arcs(source: list[dict], work: list[dict], results: list[DraftResult], step: float, profile: list) -> list[DraftResult]:
    if not results:
        return results
    base_validation = validate_draft(source, results)
    accepted = results
    changed = False
    i = 0
    while i < len(accepted):
        cleanup = near_straight_cleanup_replacement(accepted, i)
        if cleanup is None:
            i += 1
            continue

        replacement, consume = cleanup
        candidate = evaluate_near_straight_replacement(source, work, accepted, step, profile, base_validation, i, consume, replacement)
        if candidate is not None:
            accepted = candidate
            changed = True
            i += 1
        else:
            i += consume

    if changed:
        return accepted

    # This fallback is retained for tracks with no usable straight after guarded
    # cleanup. It intentionally accepts only one tiny flattening, because its
    # purpose is closure control rather than visual simplification.
    control_candidate = control_straight_fallback(source, work, results, step, profile, base_validation)
    if control_candidate is not None:
        return control_candidate
    return results


def dp_segment_step_limits(resample_step: float, min_seg_len: float, max_seg_len: float) -> tuple[int, int]:
    min_n = max(2, int(min_seg_len / max(1e-6, resample_step)))
    return min_n, max(min_n, int(max_seg_len / max(1e-6, resample_step)))


def dp_span_steps(final_i: int, i: int, min_n: int, max_n: int) -> range:
    remaining = final_i - i
    return range(min(min_n, remaining), min(max_n, remaining) + 1)


def relax_dp_edge(best: list[float], prev: list[DPEdge | None], edge: DPEdge | None) -> None:
    if edge is None:
        return
    total = best[edge.i0] + edge.cost
    if total < best[edge.i1]:
        best[edge.i1] = total
        prev[edge.i1] = edge


def relax_dp_edges_from_node(
    work: list[dict],
    profile: list,
    events: list[CurvatureRun],
    best: list[float],
    prev: list[DPEdge | None],
    i: int,
    final_i: int,
    min_n: int,
    max_n: int,
    resample_step: float,
    max_dev: float,
) -> None:
    if math.isinf(best[i]):
        return
    for n in dp_span_steps(final_i, i, min_n, max_n):
        j = i + n
        relax_dp_edge(best, prev, make_dp_edge(work, profile, i, j, resample_step, max_dev, events))


def dp_predecessor_edges(
    work: list[dict],
    profile: list,
    events: list[CurvatureRun],
    resample_step: float,
    min_n: int,
    max_n: int,
    max_dev: float,
) -> list[DPEdge | None]:
    best = [math.inf] * len(work)
    prev: list[DPEdge | None] = [None] * len(work)
    best[0] = 0.0
    final_i = len(work) - 1
    for i in range(final_i):
        relax_dp_edges_from_node(work, profile, events, best, prev, i, final_i, min_n, max_n, resample_step, max_dev)
    return prev


def reconstruct_dp_edges(prev: list[DPEdge | None], final_i: int) -> list[DPEdge]:
    if prev[final_i] is None:
        return []
    edges = []
    cursor = final_i
    while cursor > 0:
        edge = prev[cursor]
        if edge is None:
            return []
        edges.append(edge)
        cursor = edge.i0
    edges.reverse()
    return edges


def draft_results_from_dp_edges(edges: list[DPEdge]) -> list[DraftResult]:
    draft: list[DraftResult] = []
    name = 1
    for edge in edges:
        edge_results = edge_to_draft_results(edge, name)
        draft.extend(edge_results)
        name += len(edge_results)
    return draft


def dp_biarc_draft_segments(
    points: list[dict],
    resample_step: float = 4.0,
    min_seg_len: float = 12.0,
    max_seg_len: float = 180.0,
    max_dev: float = 5.0,
) -> list[DraftResult]:
    sampled = resample(points, resample_step)
    work = sampled + [sampled[0]]
    profile = curvature_profile(work)
    events = simplify_curvature_runs(profile, curvature_runs(profile))
    final_i = len(work) - 1
    min_n, max_n = dp_segment_step_limits(resample_step, min_seg_len, max_seg_len)
    edges = reconstruct_dp_edges(
        dp_predecessor_edges(work, profile, events, resample_step, min_n, max_n, max_dev),
        final_i,
    )
    if not edges:
        return []
    draft = draft_results_from_dp_edges(edges)
    evaluated = evaluate_results(work, draft, resample_step, profile)
    simplified = simplify_near_straight_arcs(sampled, work, evaluated, resample_step, profile)
    return rename_results_from_source(work, simplified)


def segments_to_xml(results: list[DraftResult]) -> str:
    lines: list[str] = []
    for result in results:
        segment = result.segment
        end_radius = segment.radius if segment.end_radius is None else segment.end_radius
        if segment.kind != "str" and max(segment.radius, end_radius) > MAX_TORCS_RADIUS_M:
            raise ValueError(f"segment {segment.name} radius exceeds {MAX_TORCS_RADIUS_M:.0f} m")
        lines.append(f'\t\t\t<section name="{segment.name}">')
        lines.append(f'\t\t\t\t<attstr name="type" val="{segment.kind}"/>')
        if segment.kind == "str":
            lines.append(f'\t\t\t\t<attnum name="lg" unit="m" val="{segment.length:.6f}"/>')
        else:
            lines.append(f'\t\t\t\t<attnum name="radius" unit="m" val="{segment.radius:.3f}"/>')
            if segment.end_radius is not None and abs(segment.end_radius - segment.radius) > 1e-6:
                lines.append(f'\t\t\t\t<attnum name="end radius" unit="m" val="{segment.end_radius:.3f}"/>')
            lines.append(f'\t\t\t\t<attnum name="arc" unit="deg" val="{segment.arc_deg:.8f}"/>')
        lines.append('\t\t\t\t<attnum name="z end" unit="m" val="0.0"/>')
        lines.append("\t\t\t</section>")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def draft_closure_pose(source: list[dict], results: list[DraftResult]) -> tuple[Pose, Pose, float]:
    start = Pose(source[0]["x"], source[0]["y"], heading(source[0], source[1]))
    pose = start
    for result in results:
        pose = advance_segment(pose, result.segment)
    return start, pose, norm_angle(pose.heading - start.heading)


def draft_global_errors(source: list[dict], results: list[DraftResult], start: Pose, sample_count: int) -> list[float]:
    model = sample_segments([result.segment for result in results], start)
    src_samples = sample_points_by_arc(source + [source[0]], sample_count)
    mdl_samples = sample_points_by_arc(model, sample_count)
    return [dist(src_samples[i], mdl_samples[i]) for i in range(sample_count)]


def density_per_km(count: int, length_m: float) -> float:
    return 1000.0 * count / length_m if length_m > 1e-9 else 0.0


def min_float_or_zero(values: list[float]) -> float:
    return min(values) if values else 0.0


def count_and_total_lengths(lengths: list[float], flags: list[bool]) -> tuple[int, float]:
    selected = [length for length, flag in zip(lengths, flags, strict=False) if flag]
    return len(selected), sum(selected)


def validation_result_maxima(results: list[DraftResult]) -> tuple[float, float, float, float, float, float]:
    return (
        max((result.rmse_m for result in results), default=0.0),
        max((result.max_dev_m for result in results), default=0.0),
        max((result.end_error_m for result in results), default=0.0),
        max((result.heading_error_deg for result in results), default=0.0),
        max((result.curvature_rmse for result in results), default=0.0),
        max((result.curvature_max_abs for result in results), default=0.0),
    )


def validate_draft(source: list[dict], results: list[DraftResult], sample_count: int = 240, short_length_m: float = 20.0, high_error_m: float = 8.0) -> DraftValidation:
    start, pose, heading_drift = draft_closure_pose(source, results)
    errors = draft_global_errors(source, results, start, sample_count)
    track_length = arc_len(source + [source[0]], 0, len(source))
    lengths = [segment_length(result.segment) for result in results]
    model_length = sum(lengths)
    short_count, short_total_length = count_and_total_lengths(lengths, [length < short_length_m for length in lengths])
    fallback_count, fallback_length = count_and_total_lengths(lengths, [result.fallback for result in results])
    high_error_count, high_error_length = count_and_total_lengths(lengths, [result.max_dev_m > high_error_m for result in results])
    max_local_rmse, max_local_dev, max_end_error, max_heading_error, max_curvature_rmse, max_curvature_abs = validation_result_maxima(results)
    return DraftValidation(
        track_length,
        model_length,
        len(results),
        density_per_km(len(results), track_length),
        min_float_or_zero(lengths),
        median_float(lengths),
        short_count,
        short_total_length,
        fallback_count,
        fallback_length,
        high_error_count,
        high_error_length,
        math.hypot(pose.x - start.x, pose.y - start.y),
        math.degrees(heading_drift),
        sum(errors) / len(errors),
        math.sqrt(sum(e * e for e in errors) / len(errors)),
        max(errors),
        max_local_rmse,
        max_local_dev,
        max_end_error,
        max_heading_error,
        max_curvature_rmse,
        max_curvature_abs,
    )


def validation_score(validation: DraftValidation) -> float:
    return (
        2.0 * validation.final_drift_m
        + 3.0 * abs(validation.final_heading_drift_deg)
        + validation.global_rmse_m
        + 0.5 * validation.global_max_error_m
    )


def validation_is_catastrophic(validation: DraftValidation) -> bool:
    return validation.final_drift_m > 25.0 or validation.global_rmse_m > 25.0 or validation.global_max_error_m > 60.0


def fallback_diagnostics(results: list[DraftResult], max_rmse: float, max_dev: float, max_end_error: float, max_heading_error_deg: float) -> list[dict]:
    diagnostics = []
    for i, result in enumerate(results, start=1):
        if not result.fallback:
            continue
        reasons = []
        if result.rmse_m > max_rmse:
            reasons.append("rmse")
        if result.max_dev_m > max_dev:
            reasons.append("max_dev")
        if result.end_error_m > max_end_error:
            reasons.append("endpoint")
        if result.heading_error_deg > max_heading_error_deg:
            reasons.append("heading")
        if result.curvature_sign_error:
            reasons.append("curvature_sign")
        diagnostics.append(
            {
                "index": i,
                "name": result.segment.name,
                "kind": result.segment.kind,
                "source_i0": result.source_i0,
                "source_i1": result.source_i1,
                "source_turn_deg": result.source_turn_deg,
                "radius_error_ratio": result.radius_error_ratio,
                "curvature_rmse": result.curvature_rmse,
                "curvature_max_abs": result.curvature_max_abs,
                "rmse_m": result.rmse_m,
                "max_dev_m": result.max_dev_m,
                "end_error_m": result.end_error_m,
                "heading_error_deg": result.heading_error_deg,
                "reasons": reasons or ["fallback_best_available"],
            }
        )
    return diagnostics


def curvature_diagnostics(points: list[dict]) -> list[dict]:
    profile = curvature_profile(points)
    return [
        {
            "x": sample.x,
            "y": sample.y,
            "s": sample.s,
            "heading_deg": math.degrees(sample.heading),
            "curvature": sample.curvature,
            "radius_m": None if math.isinf(sample.radius) else sample.radius,
            "kind": "str" if sample.curvature == 0.0 else ("lft" if sample.curvature > 0.0 else "rgt"),
        }
        for sample in profile
    ]


def curvature_event_diagnostics(points: list[dict]) -> list[dict]:
    profile = curvature_profile(points)
    runs = simplify_curvature_runs(profile, curvature_runs(profile))
    return [
        {
            "kind": run.kind,
            "i0": run.i0,
            "i1": run.i1,
            "s0": profile[run.i0].s,
            "s1": profile[run.i1].s,
            "length_m": profile[run.i1].s - profile[run.i0].s,
            "median_radius_m": None if math.isinf(run.median_radius_m) else run.median_radius_m,
        }
        for run in runs
    ]


def event_segment_mismatches(points: list[dict], results: list[DraftResult], min_overlap: int = 3) -> list[dict]:
    profile = curvature_profile(points)
    events = simplify_curvature_runs(profile, curvature_runs(profile))
    mismatches = []
    for event_i, event in enumerate(events, start=1):
        overlaps = []
        for seg_i, result in enumerate(results, start=1):
            overlap_i0 = max(event.i0, result.source_i0)
            overlap_i1 = min(event.i1, result.source_i1)
            if overlap_i1 - overlap_i0 + 1 < min_overlap:
                continue
            if result.segment.kind != event.kind:
                overlaps.append(
                    {
                        "segment_index": seg_i,
                        "segment_name": result.segment.name,
                        "segment_kind": result.segment.kind,
                        "source_i0": result.source_i0,
                        "source_i1": result.source_i1,
                        "overlap_i0": overlap_i0,
                        "overlap_i1": overlap_i1,
                        "overlap_m": profile[overlap_i1].s - profile[overlap_i0].s,
                        "max_dev_m": result.max_dev_m,
                        "heading_error_deg": result.heading_error_deg,
                        "fallback": result.fallback,
                    }
                )
        if overlaps:
            mismatches.append(
                {
                    "event_index": event_i,
                    "event_kind": event.kind,
                    "event_i0": event.i0,
                    "event_i1": event.i1,
                    "event_length_m": profile[event.i1].s - profile[event.i0].s,
                    "event_median_radius_m": None if math.isinf(event.median_radius_m) else event.median_radius_m,
                    "overlaps": overlaps,
                }
            )
    return mismatches


def write_svg(path: pathlib.Path, source: list[dict], results: list[DraftResult]) -> None:
    model = sample_segments([r.segment for r in results], Pose(source[0]["x"], source[0]["y"], heading(source[0], source[1])))
    all_pts = source + [{"x": p.x, "y": p.y} for p in model]
    min_x = min(p["x"] for p in all_pts)
    max_x = max(p["x"] for p in all_pts)
    min_y = min(p["y"] for p in all_pts)
    max_y = max(p["y"] for p in all_pts)
    width = height = 1400.0
    pad = 30.0
    scale = min((width - 2 * pad) / max(1e-6, max_x - min_x), (height - 2 * pad) / max(1e-6, max_y - min_y))

    def mp(x: float, y: float) -> str:
        return f"{pad + (x - min_x) * scale:.2f},{height - (pad + (y - min_y) * scale):.2f}"

    src_path = " ".join(mp(p["x"], p["y"]) for p in source)
    model_path = " ".join(mp(p.x, p.y) for p in model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" height="{int(height)}" viewBox="0 0 {int(width)} {int(height)}">
  <rect x="0" y="0" width="{int(width)}" height="{int(height)}" fill="#111217"/>
  <polyline points="{src_path}" fill="none" stroke="#ff5a5a" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>
  <polyline points="{model_path}" fill="none" stroke="#f4f4f4" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
</svg>
''',
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    max_dev = args.max_dev if args.max_dev is not None else 5.0
    data = json.loads(pathlib.Path(args.input).read_text(encoding="utf-8"))
    points = to_xy_dicts(data.get("polyline", []), name_output_key="name", name_keys=("way_name", "name"))
    if len(points) < 4:
        raise SystemExit("Input centerline is too short")
    sampled = resample(points, args.resample_step)
    results = dp_biarc_draft_segments(points, args.resample_step, args.min_seg_len, args.max_seg_len, max_dev)
    validation = validate_draft(sampled, results)
    diagnostics = fallback_diagnostics(results, 4.0, max_dev, 8.0, 8.0)
    pathlib.Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.output_json).write_text(json.dumps({"schema": 1, "closure_corrected": False, "validation": asdict(validation), "fallback_diagnostics": diagnostics, "curvature_mismatches": event_segment_mismatches(sampled, results), "segments": [asdict(r) for r in results]}, indent=2), encoding="utf-8")
    catastrophic = validation_is_catastrophic(validation)
    if not catastrophic:
        pathlib.Path(args.output_xml).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.output_xml).write_text(segments_to_xml(results), encoding="utf-8")
    if args.output_svg and not catastrophic:
        write_svg(pathlib.Path(args.output_svg), sampled, results)
    if args.output_curvature_json:
        pathlib.Path(args.output_curvature_json).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.output_curvature_json).write_text(json.dumps({"schema": 1, "events": curvature_event_diagnostics(sampled), "curvature": curvature_diagnostics(sampled)}, indent=2), encoding="utf-8")
    print(
        f"Drafted {validation.segment_count} segments ({validation.fallback_count} fallback segments); "
        f"closure {validation.final_drift_m:.2f}m/{validation.final_heading_drift_deg:.2f}deg; "
        f"global RMSE {validation.global_rmse_m:.2f}m max {validation.global_max_error_m:.2f}m"
    )
    if catastrophic:
        print("Draft validation failed catastrophically; XML/SVG outputs were not written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
