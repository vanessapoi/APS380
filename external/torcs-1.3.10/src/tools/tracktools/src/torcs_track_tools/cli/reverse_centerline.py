#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : reverse_centerline.py
#     created              : 27 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Reverse cached centerline traversal while preserving source metadata."""

from __future__ import annotations

import argparse
import json
import pathlib


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reverse a cached TORCS centerline JSON polyline")
    parser.add_argument("--input", required=True, help="Input centerline cache JSON")
    parser.add_argument("--output", required=True, help="Output reversed centerline cache JSON")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output")
    return parser.parse_args()


def point_xy(point: dict) -> tuple[float, float]:
    if "x" in point and "y" in point:
        return float(point["x"]), float(point["y"])
    return float(point["lon"]), float(point["lat"])


def signed_area(points: list[dict]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i, point in enumerate(points):
        x1, y1 = point_xy(point)
        x2, y2 = point_xy(points[(i + 1) % len(points)])
        area += x1 * y2 - x2 * y1
    return 0.5 * area


def reverse_centerline_cache(obj: dict) -> dict:
    polyline = obj.get("polyline")
    if not isinstance(polyline, list) or not polyline:
        raise ValueError("Input JSON has no non-empty 'polyline' list")

    out = dict(obj)
    out["polyline"] = list(reversed(polyline))

    raw_source = out.get("source", {})
    source = dict(raw_source) if isinstance(raw_source, dict) else {"original_source": raw_source}
    source["reversed_by_tracktools"] = True
    if "type" in source:
        source["original_type"] = source["type"]
    source["type"] = "tracktools-reversed-centerline"
    out["source"] = source

    area = signed_area(out["polyline"])
    out["orientation"] = {
        "signed_area": area,
        "direction": "ccw" if area > 0 else "cw",
    }
    return out


def main() -> int:
    args = parse_args()
    input_path = pathlib.Path(args.input)
    output_path = pathlib.Path(args.output)
    if output_path.exists() and not args.force:
        raise SystemExit(f"Output already exists, use --force to overwrite: {output_path}")

    obj = json.loads(input_path.read_text(encoding="utf-8"))
    out = reverse_centerline_cache(obj)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"Wrote reversed centerline: {output_path}")
    print(f"Polyline points: {len(out['polyline'])}")
    print(f"Orientation: {out['orientation']['direction']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
