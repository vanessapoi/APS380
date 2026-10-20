#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : render_seam_debug_svg.py
#     created              : 23 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Render a seam-local debug SVG in the start-segment frame."""

from __future__ import annotations

import argparse
import math
import pathlib
import xml.etree.ElementTree as ET


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render seam-local SVG in start-segment frame")
    parser.add_argument("--track-xml", required=True, help="Track XML path")
    parser.add_argument("--output", required=True, help="Output SVG path")
    parser.add_argument("--window-m", type=float, default=120.0, help="Arc-length window from seam on each side")
    return parser.parse_args()


def get_attr(section: ET.Element, name: str, default: str = "") -> str:
    for child in section:
        if child.tag in ("attstr", "attnum") and child.get("name") == name:
            return child.get("val", default)
    return default


def parse_track_segments(track_xml: pathlib.Path) -> list[ET.Element]:
    txt = track_xml.read_text(encoding="utf-8").replace("&default-surfaces;", "<d/>")
    root = ET.fromstring(txt)
    ts = next((s for s in root.iter("section") if s.get("name") == "Track Segments"), None)
    if ts is None:
        raise SystemExit("Track Segments section not found")
    return [c for c in ts if c.tag == "section"]


def sample_centerline_points(segs: list[ET.Element]) -> tuple[list[tuple[float, float]], list[float]]:
    pts: list[tuple[float, float]] = [(0.0, 0.0)]
    arc: list[float] = [0.0]
    x = 0.0
    y = 0.0
    h = 0.0
    total = 0.0
    for seg in segs:
        t = get_attr(seg, "type", "")
        if t == "str":
            lg = float(get_attr(seg, "lg", "0") or 0.0)
            x += lg * math.cos(h)
            y += lg * math.sin(h)
            total += lg
            pts.append((x, y))
            arc.append(total)
        elif t in ("lft", "rgt"):
            r = abs(float(get_attr(seg, "radius", "0") or 0.0))
            a = math.radians(float(get_attr(seg, "arc", "0") or 0.0))
            sign = 1.0 if t == "lft" else -1.0
            cx = x - sign * r * math.sin(h)
            cy = y + sign * r * math.cos(h)
            seg_len = r * abs(a)
            n = max(8, int(math.ceil(seg_len / 4.0)))
            da = a / n
            for _ in range(n):
                h += sign * da
                x = cx + sign * r * math.sin(h)
                y = cy - sign * r * math.cos(h)
                total += seg_len / n
                pts.append((x, y))
                arc.append(total)
    return pts, arc


def transform_point(pt: tuple[float, float], origin: tuple[float, float], heading: float) -> tuple[float, float]:
    dx = pt[0] - origin[0]
    dy = pt[1] - origin[1]
    c = math.cos(heading)
    s = math.sin(heading)
    return (dx * c + dy * s, -dx * s + dy * c)


def main() -> int:
    args = parse_args()
    segs = parse_track_segments(pathlib.Path(args.track_xml))
    pts, arc = sample_centerline_points(segs)
    if len(pts) < 3:
        raise SystemExit("Not enough centerline samples")

    start = pts[0]
    start_heading = math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0])
    total_len = arc[-1]
    window = max(10.0, float(args.window_m))

    first_pts = [transform_point(pts[i], start, start_heading) for i, s in enumerate(arc) if s <= window]
    last_pts = [transform_point(pts[i], start, start_heading) for i, s in enumerate(arc) if s >= total_len - window]

    all_pts = first_pts + last_pts + [(0.0, 0.0)]
    minx = min(p[0] for p in all_pts)
    maxx = max(p[0] for p in all_pts)
    miny = min(p[1] for p in all_pts)
    maxy = max(p[1] for p in all_pts)
    pad = 20.0
    view_w = max(200.0, maxx - minx + 2 * pad)
    view_h = max(200.0, maxy - miny + 2 * pad)

    def map_pt(p: tuple[float, float]) -> str:
        x = p[0] - minx + pad
        y = view_h - (p[1] - miny + pad)
        return f"{x:.2f},{y:.2f}"

    first_poly = " ".join(map_pt(p) for p in first_pts)
    last_poly = " ".join(map_pt(p) for p in last_pts)
    origin = map_pt((0.0, 0.0))
    end_pt = transform_point(pts[-1], start, start_heading)
    end_marker = map_pt(end_pt)

    svg = "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 {view_w:.2f} {view_h:.2f}">',
            '<rect width="100%" height="100%" fill="#111217"/>',
            f'<polyline points="{first_poly}" fill="none" stroke="#f8fafc" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>',
            f'<polyline points="{last_poly}" fill="none" stroke="#fb7185" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>',
            f'<circle cx="{origin.split(",")[0]}" cy="{origin.split(",")[1]}" r="6" fill="#22c55e"/>',
            f'<circle cx="{end_marker.split(",")[0]}" cy="{end_marker.split(",")[1]}" r="6" fill="#f59e0b"/>',
            f'<line x1="{map_pt((minx,0.0)).split(",")[0]}" y1="{map_pt((0.0,0.0)).split(",")[1]}" x2="{map_pt((maxx,0.0)).split(",")[0]}" y2="{map_pt((0.0,0.0)).split(",")[1]}" stroke="#2563eb" stroke-width="2" stroke-dasharray="8 6"/>',
            f'<line x1="{map_pt((0.0,miny)).split(",")[0]}" y1="{map_pt((0.0,miny)).split(",")[1]}" x2="{map_pt((0.0,maxy)).split(",")[0]}" y2="{map_pt((0.0,maxy)).split(",")[1]}" stroke="#16a34a" stroke-width="2" stroke-dasharray="8 6"/>',
            '<text x="24" y="34" fill="#f8fafc" font-family="Consolas, monospace" font-size="20">Start-frame seam debug</text>',
            f'<text x="24" y="60" fill="#f8fafc" font-family="Consolas, monospace" font-size="18">White: first {window:.0f} m, Red: last {window:.0f} m</text>',
            f'<text x="24" y="86" fill="#f8fafc" font-family="Consolas, monospace" font-size="18">End in start frame: dx={end_pt[0]:.3f} m, dy={end_pt[1]:.3f} m</text>',
            '</svg>',
        ]
    )

    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg, encoding="utf-8")
    print(f"Wrote SVG: {out_path}")
    print(f"End pose in start frame: dx={end_pt[0]:.6f} dy={end_pt[1]:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
