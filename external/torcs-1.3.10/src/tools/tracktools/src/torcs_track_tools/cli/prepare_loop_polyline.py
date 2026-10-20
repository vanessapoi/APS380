#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : prepare_loop_polyline.py
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

"""Prepare a fetched loop polyline for fitting by smoothing the seam locally.

Fetched closed loops often have their first/last sample at an arbitrary OSM way
boundary.  If that boundary is noisy, duplicated, or tangent-discontinuous, the
segment fitter starts at the worst possible location.  This helper trims a few
points around the seam, inserts a short bridge only when heading/gap thresholds
say it is needed, and writes diagnostics so the original source is still
auditable.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib

from torcs_track_tools.core.polyline import from_xy_tuple, to_xy_tuples


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a fetched closed-loop polyline for stable fitting")
    parser.add_argument("--input", required=True, help="Input cached centerline JSON")
    parser.add_argument("--output", required=True, help="Output prepared centerline JSON")
    parser.add_argument("--report", default="", help="Optional seam diagnostics JSON")
    parser.add_argument("--overlay", default="", help="Optional seam overlay SVG")
    parser.add_argument("--trim-points", type=int, default=2, help="Points to trim from each side of the seam before reconnecting")
    parser.add_argument("--tangent-window", type=int, default=5, help="Point window size for tangent estimation")
    parser.add_argument("--bridge-step", type=float, default=3.0, help="Target spacing for seam bridge samples in meters")
    parser.add_argument("--repair-heading-threshold", type=float, default=5.0, help="Only repair seam when raw heading mismatch exceeds this (deg)")
    parser.add_argument("--repair-gap-threshold", type=float, default=20.0, help="Only repair seam when trimmed seam gap exceeds this (m)")
    return parser.parse_args()


def norm_angle(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def heading(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def loop_length(xy: list[tuple[float, float]]) -> float:
    return sum(dist(xy[i - 1], xy[i]) for i in range(1, len(xy)))


def tangent_from_window(xy: list[tuple[float, float]], start_idx: int, forward: bool, window: int) -> tuple[float, float]:
    step = 1 if forward else -1
    i = start_idx
    tx = 0.0
    ty = 0.0
    used = 0
    for _ in range(max(1, window)):
        j = i + step
        if j < 0 or j >= len(xy):
            break
        dx = xy[j][0] - xy[i][0]
        dy = xy[j][1] - xy[i][1]
        L = math.hypot(dx, dy)
        if L > 1e-9:
            tx += dx / L
            ty += dy / L
            used += 1
        i = j
    if used == 0:
        return (1.0, 0.0)
    L = math.hypot(tx, ty)
    if L < 1e-9:
        return (1.0, 0.0)
    return (tx / L, ty / L)


def choose_break_index(xy: list[tuple[float, float]], trim: int) -> int:
    best_idx = 0
    best_score = -1e30
    n = len(xy)
    for i in range(max(1, trim + 1), min(n - 1, n - trim - 1)):
        h0 = heading(xy[i - 1], xy[i])
        h1 = heading(xy[i], xy[i + 1])
        turn = abs(math.degrees(norm_angle(h1 - h0)))
        seg_prev = dist(xy[i - 1], xy[i])
        seg_next = dist(xy[i], xy[i + 1])
        seam_span = dist(xy[i - trim], xy[i + trim])
        score = min(seg_prev, seg_next) - 8.0 * turn - 0.5 * seam_span
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx


def rotate_points(points: list[dict], idx: int) -> list[dict]:
    return points[idx:] + points[:idx]


def hermite_bridge(p0: tuple[float, float], p1: tuple[float, float], t0: tuple[float, float], t1: tuple[float, float], samples: int) -> list[tuple[float, float]]:
    gap = dist(p0, p1)
    scale = max(gap, 1.0)
    # Check if tangents point in nearly opposite directions (near-180 heading mismatch).
    dot = t0[0] * t1[0] + t0[1] * t1[1]
    if dot < -0.3:
        # Tangents oppose each other; flip m1 to create a C-curve instead of S-curve.
        m1 = (t0[0] * scale, t0[1] * scale)
    else:
        m1 = (t1[0] * scale, t1[1] * scale)
    m0 = (t0[0] * scale, t0[1] * scale)
    out = []
    for i in range(1, max(2, samples)):
        u = i / max(2, samples)
        h00 = 2 * u * u * u - 3 * u * u + 1
        h10 = u * u * u - 2 * u * u + u
        h01 = -2 * u * u * u + 3 * u * u
        h11 = u * u * u - u * u
        x = h00 * p0[0] + h10 * m0[0] + h01 * p1[0] + h11 * m1[0]
        y = h00 * p0[1] + h10 * m0[1] + h01 * p1[1] + h11 * m1[1]
        out.append((x, y))
    return out


def seam_repair_is_useful(raw_heading_mismatch: float, prepared_heading_mismatch: float, threshold: float) -> bool:
    return prepared_heading_mismatch <= threshold or prepared_heading_mismatch <= raw_heading_mismatch * 0.75


def write_overlay(path: pathlib.Path, raw_xy: list[tuple[float, float]], repaired_xy: list[tuple[float, float]]) -> None:
    xs = [p[0] for p in raw_xy] + [p[0] for p in repaired_xy]
    ys = [p[1] for p in raw_xy] + [p[1] for p in repaired_xy]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    w = max(1.0, maxx - minx)
    h = max(1.0, maxy - miny)
    pad = 20.0
    vw = w + 2 * pad
    vh = h + 2 * pad

    def poly(xy: list[tuple[float, float]]) -> str:
        return " ".join(f"{x - minx + pad:.2f},{vh - (y - miny + pad):.2f}" for x, y in xy)

    svg = "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1200" viewBox="0 0 {vw:.2f} {vh:.2f}">',
            '<rect width="100%" height="100%" fill="#111827"/>',
            f'<polyline fill="none" stroke="#ef4444" stroke-width="4" points="{poly(raw_xy)}"/>',
            f'<polyline fill="none" stroke="#22c55e" stroke-width="3" points="{poly(repaired_xy)}"/>',
            '</svg>',
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def main() -> int:
    args = parse_args()
    in_path = pathlib.Path(args.input)
    out_path = pathlib.Path(args.output)
    report_path = pathlib.Path(args.report) if args.report else out_path.with_name(out_path.stem + "-seam-report.json")
    overlay_path = pathlib.Path(args.overlay) if args.overlay else out_path.with_name(out_path.stem + "-seam-overlay.svg")

    obj = json.loads(in_path.read_text(encoding="utf-8"))
    raw_points = obj.get("polyline") or []
    if len(raw_points) < 8:
        raise SystemExit("Polyline too short for seam preparation")

    coord_ref = raw_points[0]
    raw_xy_full = to_xy_tuples(raw_points, coord_ref)
    first_gap = dist(raw_xy_full[0], raw_xy_full[-1])
    duplicate_end = first_gap <= 1e-6
    work_points = raw_points[:-1] if duplicate_end else raw_points[:]
    raw_xy = to_xy_tuples(work_points, coord_ref)

    h_raw_in = heading(raw_xy[-2], raw_xy[-1])
    h_raw_out = heading(raw_xy[0], raw_xy[1])
    raw_heading_mismatch = abs(math.degrees(norm_angle(h_raw_out - h_raw_in)))
    trim = max(1, min(args.trim_points, max(1, len(raw_xy) // 8)))
    break_idx = choose_break_index(raw_xy, trim)
    rotated_points = rotate_points(work_points, break_idx)
    rotated_xy = to_xy_tuples(rotated_points, coord_ref)
    seam_gap = dist(rotated_xy[-trim - 1], rotated_xy[trim])

    should_repair = raw_heading_mismatch > args.repair_heading_threshold and seam_gap > args.repair_gap_threshold
    bridge_samples = 0
    method = "identity-duplicate-trim"

    if should_repair:
        end_anchor = rotated_xy[-trim - 1]
        start_anchor = rotated_xy[trim]
        t_end = tangent_from_window(rotated_xy, len(rotated_xy) - trim - 1, forward=True, window=args.tangent_window)
        t_start = tangent_from_window(rotated_xy, trim, forward=True, window=args.tangent_window)
        bridge_xy = hermite_bridge(end_anchor, start_anchor, t_end, t_start, max(3, int(math.ceil(seam_gap / max(0.5, args.bridge_step)))))
        bridge_samples = len(bridge_xy)
        method = "rotated-seam-local-hermite"
        repaired_points = rotated_points[trim:-trim] if trim < len(rotated_points) // 2 else rotated_points[:]
        repaired_xy = to_xy_tuples(repaired_points, coord_ref)
        if trim < len(rotated_points) // 2:
            seam_ref = rotated_points[trim]
            bridge_points = [from_xy_tuple(pt, coord_ref, seam_ref) for pt in bridge_xy]
            repaired_points = rotated_points[trim:-trim] + bridge_points
            repaired_xy = to_xy_tuples(repaired_points, coord_ref)
        else:
            repaired_points = rotated_points + [rotated_points[0]]
            repaired_xy = to_xy_tuples(repaired_points, coord_ref)
    else:
        repaired_points = work_points[:]
        repaired_xy = raw_xy[:]

    h_new_in = heading(repaired_xy[-2], repaired_xy[-1])
    h_new_out = heading(repaired_xy[0], repaired_xy[1])
    new_heading_mismatch = abs(math.degrees(norm_angle(h_new_out - h_new_in)))

    # Do-no-harm fallback: if seam repair makes heading continuity worse,
    # keep the raw duplicate-trimmed loop instead.
    if should_repair and not seam_repair_is_useful(raw_heading_mismatch, new_heading_mismatch, args.repair_heading_threshold):
        should_repair = False
        method = "identity-duplicate-trim"
        bridge_samples = 0
        repaired_points = work_points[:]
        repaired_xy = raw_xy[:]
        new_heading_mismatch = raw_heading_mismatch

    out_obj = dict(obj)
    out_obj["schema"] = max(3, int(obj.get("schema", 2)))
    out_obj["source_preparation"] = {
        "method": method,
        "duplicate_end_removed": duplicate_end,
        "break_index": break_idx,
        "trim_points": trim,
        "bridge_samples": bridge_samples,
        "repair_applied": should_repair,
        "raw_seam_gap_m": seam_gap,
        "raw_heading_mismatch_deg": raw_heading_mismatch,
        "prepared_heading_mismatch_deg": new_heading_mismatch,
    }
    out_obj["polyline"] = repaired_points

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_obj, indent=2), encoding="utf-8")

    report = {
        "raw_point_count": len(raw_points),
        "prepared_point_count": len(repaired_points),
        "loop_length_m": loop_length(raw_xy),
        "duplicate_end_removed": duplicate_end,
        "break_index": break_idx,
        "trim_points": trim,
        "bridge_samples": bridge_samples,
        "repair_applied": should_repair,
        "raw_heading_mismatch_deg": raw_heading_mismatch,
        "prepared_heading_mismatch_deg": new_heading_mismatch,
        "seam_gap_after_trim_m": seam_gap,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_overlay(overlay_path, raw_xy_full, repaired_xy)

    print(f"Wrote prepared polyline: {out_path}")
    print(f"Wrote seam report: {report_path}")
    print(f"Wrote seam overlay: {overlay_path}")
    print(f"Raw heading mismatch: {raw_heading_mismatch:.3f} deg")
    print(f"Prepared heading mismatch: {new_heading_mismatch:.3f} deg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
