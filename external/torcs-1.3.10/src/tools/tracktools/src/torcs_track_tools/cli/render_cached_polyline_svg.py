#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : render_cached_polyline_svg.py
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

"""Render a cached fetched centerline polyline JSON as a standalone SVG."""

from __future__ import annotations

import argparse
import json
import pathlib

from torcs_track_tools.core.polyline import to_xy_tuples


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render cached centerline JSON to a simple SVG")
    parser.add_argument("--input", required=True, help="Input cached centerline JSON")
    parser.add_argument("--output", required=True, help="Output SVG path")
    parser.add_argument("--stroke-width", type=float, default=6.0, help="Polyline stroke width")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    in_path = pathlib.Path(args.input)
    out_path = pathlib.Path(args.output)
    obj = json.loads(in_path.read_text(encoding="utf-8"))
    points = obj.get("polyline") or []
    if not points:
        raise SystemExit("Input JSON has no 'polyline' field")

    xy = to_xy_tuples(points)
    xs = [x for x, _ in xy]
    ys = [y for _, y in xy]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    width = max(1.0, maxx - minx)
    height = max(1.0, maxy - miny)
    pad = 20.0
    view_w = width + 2.0 * pad
    view_h = height + 2.0 * pad
    poly = " ".join(f"{x - minx + pad:.2f},{view_h - (y - miny + pad):.2f}" for x, y in xy)

    svg = "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1200" viewBox="0 0 {view_w:.2f} {view_h:.2f}">',
            '<rect width="100%" height="100%" fill="#0f172a"/>',
            f'<polyline fill="none" stroke="#38bdf8" stroke-width="{args.stroke_width:.2f}" points="{poly}"/>',
            "</svg>",
        ]
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg, encoding="utf-8")
    print(f"Wrote SVG: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
