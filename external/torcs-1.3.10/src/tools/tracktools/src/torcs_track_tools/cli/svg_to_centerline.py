#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : svg_to_centerline.py
#     created              : 14 Aug 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Extract and scale a closed SVG layout for TORCS centerline fitting."""

from __future__ import annotations

import argparse
import json
import math
import pathlib

from defusedxml import ElementTree as ET  # type: ignore[import-untyped]

from torcs_track_tools.core.svg_geometry import Point, SvgCandidate, extract_candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract a closed SVG path, polyline, or polygon as a TORCS centerline")
    parser.add_argument("--input", required=True, help="Input SVG path")
    parser.add_argument("--output", required=True, help="Output centerline JSON")
    parser.add_argument("--length-m", required=True, type=float, help="Target closed-loop length in meters")
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--group-id", default="", help="Restrict candidates to this SVG group id")
    selector.add_argument("--element-id", default="", help="Extract this SVG path, polyline, polygon, or group id")
    parser.add_argument("--candidate-index", type=int, default=-1, help="Zero-based candidate index from the report; default selects the longest closed candidate")
    parser.add_argument("--curve-tolerance", type=float, default=0.5, help="Curve flattening tolerance in SVG user units")
    parser.add_argument("--resample-step", type=float, default=3.0, help="Target output point spacing in meters")
    parser.add_argument("--reverse", action="store_true", help="Reverse racing direction while preserving the selected start")
    start = parser.add_mutually_exclusive_group()
    start.add_argument("--keep-start", action="store_true", help="Keep the SVG subpath's first point as station zero")
    start.add_argument("--start", default="", help="Station zero near transformed SVG coordinates x,y")
    parser.add_argument("--start-window", type=int, default=8, help="Curvature window used to choose a smooth default station zero")
    parser.add_argument("--keep-svg-y", action="store_true", help="Keep SVG down-positive Y instead of converting to Cartesian up-positive Y")
    parser.add_argument("--preview-svg", default="", help="Optional extraction preview SVG")
    parser.add_argument("--report", default="", help="Optional extraction diagnostics JSON")
    return parser.parse_args()


def distance(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def closed_length(points: list[Point]) -> float:
    return sum(distance(points[index], points[(index + 1) % len(points)]) for index in range(len(points)))


def signed_area(points: list[Point]) -> float:
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1], strict=True))


def resample_closed(points: list[Point], step: float) -> list[Point]:
    total = closed_length(points)
    count = max(8, int(round(total / step)))
    if count > 1_000_000:
        raise SystemExit(f"Requested resampling would create {count} points; limit is 1000000")
    closed = points + [points[0]]
    cumulative = [0.0]
    for start, end in zip(closed, closed[1:], strict=False):
        cumulative.append(cumulative[-1] + distance(start, end))
    output = []
    segment = 0
    for index in range(count):
        station = total * index / count
        while segment + 1 < len(cumulative) and cumulative[segment + 1] < station:
            segment += 1
        span = max(1e-12, cumulative[segment + 1] - cumulative[segment])
        amount = (station - cumulative[segment]) / span
        start, end = closed[segment], closed[segment + 1]
        output.append((start[0] + amount * (end[0] - start[0]), start[1] + amount * (end[1] - start[1])))
    return output


def heading_delta(before: Point, point: Point, after: Point) -> float:
    first = math.atan2(point[1] - before[1], point[0] - before[0])
    second = math.atan2(after[1] - point[1], after[0] - point[0])
    return abs(math.atan2(math.sin(second - first), math.cos(second - first)))


def smooth_start_index(points: list[Point], window: int) -> int:
    if len(points) < 8:
        return 0
    span = max(2, min(window, len(points) // 8))
    if len(points) * (2 * span + 1) > 20_000_000:
        raise SystemExit("Smooth-start search exceeds the 20000000 point-window operation limit; reduce --start-window or increase --resample-step")
    best_index = 0
    best_score = math.inf
    for index in range(len(points)):
        score = sum(heading_delta(points[(offset - 1) % len(points)], points[offset % len(points)], points[(offset + 1) % len(points)]) for offset in range(index - span, index + span + 1))
        chord = distance(points[(index - span) % len(points)], points[(index + span) % len(points)])
        score -= chord * 0.001
        if score < best_score:
            best_score = score
            best_index = index
    return best_index


def parse_start(value: str) -> Point:
    try:
        x, y = (float(part.strip()) for part in value.split(",", 1))
    except (TypeError, ValueError) as exc:
        raise SystemExit("--start must be transformed SVG coordinates x,y") from exc
    if not math.isfinite(x) or not math.isfinite(y):
        raise SystemExit("--start coordinates must be finite")
    return x, y


def choose_candidate(candidates: list[SvgCandidate], index: int) -> tuple[SvgCandidate, list[SvgCandidate], int, int]:
    closed = [candidate for candidate in candidates if candidate.closed and len(candidate.points) >= 3 and candidate.length > 0.0]
    if not closed:
        raise SystemExit("SVG selection contains no usable closed path, polyline, or polygon")
    if index >= 0:
        if index >= len(candidates):
            raise SystemExit(f"--candidate-index {index} is out of range for {len(candidates)} candidates")
        selected = candidates[index]
        if selected not in closed:
            raise SystemExit(f"--candidate-index {index} does not identify a usable closed candidate")
        return selected, closed, index, closed.index(selected)
    selected = max(closed, key=lambda candidate: candidate.length)
    return selected, closed, candidates.index(selected), closed.index(selected)


def rotate_to_requested_start(points: list[Point], requested: Point) -> tuple[list[Point], int, Point, float]:
    best = (math.inf, 0, 0.0, points[0])
    for index, (start, end) in enumerate(zip(points, points[1:] + points[:1], strict=True)):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length2 = dx * dx + dy * dy
        amount = 0.0 if length2 <= 1e-18 else max(0.0, min(1.0, ((requested[0] - start[0]) * dx + (requested[1] - start[1]) * dy) / length2))
        projected = (start[0] + amount * dx, start[1] + amount * dy)
        candidate = (distance(projected, requested), index, amount, projected)
        if candidate[0] < best[0]:
            best = candidate
    snap_distance, index, amount, projected = best
    next_index = (index + 1) % len(points)
    if amount <= 1e-9:
        rotated = points[index:] + points[:index]
        start_index = index
    elif amount >= 1.0 - 1e-9:
        rotated = points[next_index:] + points[:next_index]
        start_index = next_index
    else:
        rotated = [projected, *points[next_index:], *points[:next_index]]
        start_index = next_index
    return rotated, start_index, projected, snap_distance


def prepare_points(candidate: SvgCandidate, args: argparse.Namespace) -> tuple[list[Point], dict]:
    source = list(candidate.points)
    selected_start = source[0]
    start_snap_distance = 0.0
    if args.start:
        requested = parse_start(args.start)
        source, start_index, selected_start, start_snap_distance = rotate_to_requested_start(source, requested)
    else:
        start_index = 0
    if args.reverse:
        source = [source[0], *reversed(source[1:])]
    cartesian = [(x, y if args.keep_svg_y else -y) for x, y in source]
    source_length = closed_length(cartesian)
    if source_length <= 1e-9:
        raise SystemExit("Selected SVG loop has zero length")
    scale = args.length_m / source_length
    origin = cartesian[0]
    meters = [((x - origin[0]) * scale, (y - origin[1]) * scale) for x, y in cartesian]
    meters = resample_closed(meters, args.resample_step)
    correction = args.length_m / closed_length(meters)
    meters = [(x * correction, y * correction) for x, y in meters]
    if not all(math.isfinite(value) for point in meters for value in point):
        raise SystemExit("SVG conversion produced non-finite output coordinates")
    rotated_start = 0
    if not args.keep_start and not args.start:
        rotated_start = smooth_start_index(meters, args.start_window)
        meters = meters[rotated_start:] + meters[:rotated_start]
    return meters, {
        "source_length_svg_units": source_length,
        "scale_m_per_svg_unit": scale,
        "effective_scale_m_per_svg_unit": scale * correction,
        "length_correction": correction,
        "source_start_index": start_index,
        "selected_start_svg": {"x": selected_start[0], "y": selected_start[1]},
        "start_snap_distance_svg_units": start_snap_distance,
        "rotated_smooth_start_index": rotated_start,
        "output_length_m": closed_length(meters),
    }


def candidate_report(candidate: SvgCandidate, index: int) -> dict:
    return {
        "index": index,
        "tag": candidate.tag,
        "element_id": candidate.element_id,
        "class": candidate.element_class,
        "element_index": candidate.element_index,
        "subpath_index": candidate.subpath_index,
        "closed": candidate.closed,
        "point_count": len(candidate.points),
        "length_svg_units": candidate.length,
    }


def write_preview(path: pathlib.Path, points: list[Point], length_m: float) -> None:
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    pad = max(max_x - min_x, max_y - min_y, 1.0) * 0.05
    width = max_x - min_x + 2.0 * pad
    height = max_y - min_y + 2.0 * pad

    def mapped(point: Point) -> str:
        return f"{point[0] - min_x + pad:.2f},{height - (point[1] - min_y + pad):.2f}"

    polyline = " ".join(mapped(point) for point in points + [points[0]])
    start = mapped(points[0]).split(",")
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 {width:.2f} {height:.2f}">
  <rect width="100%" height="100%" fill="#0f172a"/>
  <polyline id="centerline" points="{polyline}" fill="none" stroke="#ef4444" stroke-width="{max(width, height) * 0.004:.2f}" stroke-linecap="round" stroke-linejoin="round"/>
  <circle id="start" cx="{start[0]}" cy="{start[1]}" r="{max(width, height) * 0.009:.2f}" fill="#22c55e"/>
  <text x="{pad:.2f}" y="{pad:.2f}" fill="#e2e8f0" font-family="monospace" font-size="{max(width, height) * 0.018:.2f}">length={length_m:.2f} m, points={len(points)}</text>
</svg>
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def main() -> int:  # noqa: CCR001 - validation and output assembly are intentionally kept together
    args = parse_args()
    if not math.isfinite(args.length_m) or args.length_m <= 0.0:
        raise SystemExit("--length-m must be positive")
    if not math.isfinite(args.curve_tolerance) or args.curve_tolerance <= 0.0:
        raise SystemExit("--curve-tolerance must be positive")
    if not math.isfinite(args.resample_step) or args.resample_step <= 0.0:
        raise SystemExit("--resample-step must be positive")
    if args.candidate_index < -1:
        raise SystemExit("--candidate-index must be -1 or greater")
    if args.start_window < 1:
        raise SystemExit("--start-window must be positive")
    if args.start_window > 1000:
        raise SystemExit("--start-window must not exceed 1000")
    input_path = pathlib.Path(args.input)
    try:
        if input_path.stat().st_size > 64 * 1024 * 1024:
            raise SystemExit("Input SVG exceeds the 64 MiB authoring limit")
        root = ET.parse(input_path).getroot()
        if root is None:
            raise ValueError("SVG document has no root element")
        candidates = extract_candidates(root, args.group_id or args.element_id, args.curve_tolerance)
    except OSError as exc:
        raise SystemExit(f"Could not read SVG: {exc}") from exc
    except (ET.ParseError, ValueError) as exc:
        raise SystemExit(f"Could not extract SVG geometry: {exc}") from exc
    selected, closed, selected_index, selected_closed_index = choose_candidate(candidates, args.candidate_index)
    points, stats = prepare_points(selected, args)
    area = signed_area(points)
    output = {
        "schema": 2,
        "source": {
            "type": "svg-to-centerline",
            "input_svg": str(input_path),
            "group_id": args.group_id,
            "element_id": args.element_id,
            "candidate_index": selected_index,
            "closed_candidate_index": selected_closed_index,
            "target_length_m": args.length_m,
        },
        "orientation": {"signed_area": area, "direction": "ccw" if area > 0.0 else "cw"},
        "length_m": stats["output_length_m"],
        "extraction": {
            "candidate_count": len(candidates),
            "closed_candidate_count": len(closed),
            "curve_tolerance_svg_units": args.curve_tolerance,
            "resample_step_m": args.resample_step,
            "reverse": args.reverse,
            "keep_svg_y": args.keep_svg_y,
            "selected": {**candidate_report(selected, selected_index), "closed_candidate_index": selected_closed_index},
            **stats,
        },
        "polyline": [{"x": x, "y": y, "way_name": "svg-centerline"} for x, y in points],
    }
    output_path = pathlib.Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    report = {
        "input_svg": str(input_path),
        "output": str(output_path),
        "selected_candidate_index": selected_index,
        "selected_closed_candidate_index": selected_closed_index,
        "output_point_count": len(points),
        "output_length_m": stats["output_length_m"],
        "orientation": output["orientation"],
        "candidates": [candidate_report(candidate, index) for index, candidate in enumerate(candidates)],
    }
    if args.report:
        report_path = pathlib.Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.preview_svg:
        write_preview(pathlib.Path(args.preview_svg), points, stats["output_length_m"])
    print(f"Wrote centerline: {output_path}")
    print(f"Selected candidate {selected_index} (closed {selected_closed_index} of {len(closed)}), points={len(points)}, length={stats['output_length_m']:.3f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
