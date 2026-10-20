#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : compare_overlay.py
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

"""Compare source polyline against TORCS XML centerline and emit overlay/report."""

from __future__ import annotations

import argparse
import json
import math
import pathlib

from torcs_track_tools.core.overlay import (
    nearest_polyline_distance,
    parse_track_segments,
    rigid_fit,
    sample_by_arc,
    to_xy,
    torcs_points,
    transform,
    write_svg,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render source vs TORCS centerline overlay")
    parser.add_argument("--polyline", required=True, help="Input cached centerline JSON")
    parser.add_argument("--track-xml", required=True, help="TORCS track XML path")
    parser.add_argument("--overlay", required=True, help="Output SVG path")
    parser.add_argument("--report", required=True, help="Output JSON report path")
    parser.add_argument("--samples", type=int, default=800, help="Comparison sample count")
    parser.add_argument("--align-closed", action="store_true", help="Align closed loops across different start positions and directions")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.align_closed:
        from torcs_track_tools.cli.close_loop_geometric import write_final_comparison

        report = write_final_comparison(
            pathlib.Path(args.track_xml), pathlib.Path(args.polyline),
            pathlib.Path(args.overlay), pathlib.Path(args.report), args.samples,
        )
        print(f"Mean deviation: {report['mean_deviation_m']:.2f} m")
        print(f"Overlay written: {args.overlay}")
        return 0
    poly_data = json.loads(pathlib.Path(args.polyline).read_text(encoding="utf-8"))
    src_poly = to_xy(poly_data.get("polyline", []))
    if len(src_poly) < 3:
        raise SystemExit("Source polyline too short")

    xml_text = pathlib.Path(args.track_xml).read_text(encoding="utf-8")
    segs = parse_track_segments(xml_text)
    if not segs:
        raise SystemExit("No TORCS segments parsed from XML")

    src_s, src_len = sample_by_arc(src_poly, args.samples)
    torcs_s, torcs_len = sample_by_arc(torcs_points(segs, step=3.0), args.samples)
    fit = rigid_fit(torcs_s, src_s)
    torcs_fit = transform(torcs_s, fit)

    dists = []
    for p in torcs_fit:
        d = nearest_polyline_distance(p, src_poly, closed=True)
        dists.append({"s": p["s"], "seg": p.get("seg", ""), "d": d})

    mean_d = sum(d["d"] for d in dists) / len(dists)
    root_mean_square_error = math.sqrt(sum(d["d"] * d["d"] for d in dists) / len(dists))
    max_d = max(dists, key=lambda x: x["d"])
    top = sorted(dists, key=lambda x: x["d"], reverse=True)[:10]

    overlay_path = pathlib.Path(args.overlay)
    report_path = pathlib.Path(args.report)
    write_svg(overlay_path, src_s, torcs_fit)

    report = {
        "source_length_m": src_len,
        "torcs_length_m": torcs_len,
        "fit_rotation_deg": math.degrees(fit["theta"]),
        "mean_deviation_m": mean_d,
        "root_mean_square_error_deviation_m": root_mean_square_error,
        "rmse_deviation_m": root_mean_square_error,
        "max_deviation": max_d,
        "top_deviations": top,
        "overlay": str(overlay_path),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"TORCS length: {torcs_len:.2f} m")
    print(f"Source length: {src_len:.2f} m")
    print(f"Mean deviation: {mean_d:.2f} m")
    print(f"Root mean square error deviation: {root_mean_square_error:.2f} m")
    print(f"Max deviation: {max_d['d']:.2f} m at s={max_d['s']:.1f} ({max_d['seg']})")
    print(f"Overlay written: {overlay_path}")
    print(f"Report written: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
