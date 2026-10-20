# /***************************************************************************
#
#     file                 : overlay.py
#     created              : 04 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Shared source-vs-TORCS overlay reconstruction helpers."""

from __future__ import annotations

import math
import pathlib
import xml.etree.ElementTree as ET
from collections.abc import Iterable

from torcs_track_tools.core.polyline import to_xy_dicts


def to_xy(points: list[dict]) -> list[dict]:
    return to_xy_dicts(points, name_output_key="src", name_keys=("way_name",))


def parse_track_root(xml_text: str) -> ET.Element | None:
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError:
        try:
            return ET.fromstring(xml_text.replace("&default-surfaces;", "<__default_surfaces__/>"))
        except ET.ParseError:
            return None


def track_segments_section(root: ET.Element) -> ET.Element | None:
    for section in root.iter("section"):
        if section.get("name") == "Track Segments":
            return section
    return None


def segment_attrs(segment: ET.Element) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for att in segment:
        if att.tag in ("attnum", "attstr") and att.get("name"):
            attrs[att.get("name", "")] = att.get("val", "")
    return attrs


def parse_segment(name: str, attrs: dict[str, str]) -> dict | None:
    seg_type = attrs.get("type", "")
    if seg_type == "str":
        if "lg" not in attrs:
            return None
        return {"name": name, "type": "str", "lg": float(attrs["lg"])}
    if seg_type not in ("lft", "rgt") or "radius" not in attrs or "arc" not in attrs:
        return None
    obj = {
        "name": name,
        "type": seg_type,
        "radius": float(attrs["radius"]),
        "arc": float(attrs["arc"]),
    }
    if "end radius" in attrs:
        obj["end_radius"] = float(attrs["end radius"])
    return obj


def parse_track_segments(xml_text: str) -> list[dict]:
    root = parse_track_root(xml_text)
    if root is None:
        return []

    seg_parent = track_segments_section(root)
    if seg_parent is None:
        return []

    segs: list[dict] = []
    for seg in [c for c in seg_parent if c.tag == "section"]:
        name = seg.get("name") or "Segment"
        obj = parse_segment(name, segment_attrs(seg))
        if obj is not None:
            segs.append(obj)
    return segs


def append_straight_points(pts: list[dict], x: float, y: float, h: float, s: float, seg: dict, step: float) -> tuple[float, float, float, float]:
    n = max(1, int(math.ceil(seg["lg"] / step)))
    ds = seg["lg"] / n
    for _ in range(n):
        x += ds * math.cos(h)
        y += ds * math.sin(h)
        s += ds
        pts.append({"x": x, "y": y, "s": s, "seg": seg["name"]})
    return x, y, h, s


def append_variable_radius_curve_points(
    pts: list[dict],
    x: float,
    y: float,
    h: float,
    s: float,
    seg: dict,
    sign: float,
    radius: float,
    end_radius: float,
    d_arc: float,
    n: int,
) -> tuple[float, float, float, float]:
    for i in range(n):
        t_mid = (i + 0.5) / n
        r_mid = radius + (end_radius - radius) * t_mid
        ds = abs(r_mid * d_arc)
        x += ds * math.cos(h + sign * 0.5 * d_arc)
        y += ds * math.sin(h + sign * 0.5 * d_arc)
        h += sign * d_arc
        s += ds
        pts.append({"x": x, "y": y, "s": s, "seg": seg["name"]})
    return x, y, h, s


def append_constant_radius_curve_points(
    pts: list[dict],
    x: float,
    y: float,
    h: float,
    s: float,
    seg: dict,
    sign: float,
    radius: float,
    d_arc: float,
    n: int,
) -> tuple[float, float, float, float]:
    cx = x - sign * radius * math.sin(h)
    cy = y + sign * radius * math.cos(h)
    for _ in range(n):
        h += sign * d_arc
        x = cx + sign * radius * math.sin(h)
        y = cy - sign * radius * math.cos(h)
        s += radius * d_arc
        pts.append({"x": x, "y": y, "s": s, "seg": seg["name"]})
    return x, y, h, s


def append_curve_points(pts: list[dict], x: float, y: float, h: float, s: float, seg: dict, step: float) -> tuple[float, float, float, float]:
    sign = 1.0 if seg["type"] == "lft" else -1.0
    arc = math.radians(seg["arc"])
    radius = float(seg["radius"])
    end_radius = float(seg.get("end_radius", radius))
    n = max(1, int(math.ceil(max(radius * arc, 1e-6) / step)))
    d_arc = arc / n
    if abs(end_radius - radius) > 1e-6:
        return append_variable_radius_curve_points(pts, x, y, h, s, seg, sign, radius, end_radius, d_arc, n)
    return append_constant_radius_curve_points(pts, x, y, h, s, seg, sign, radius, d_arc, n)


def torcs_points(segments: list[dict], step: float = 3.0) -> list[dict]:
    x = 0.0
    y = 0.0
    h = 0.0
    s = 0.0
    pts = [{"x": x, "y": y, "s": s, "seg": segments[0]["name"] if segments else "start"}]
    for seg in segments:
        if seg["type"] == "str":
            x, y, h, s = append_straight_points(pts, x, y, h, s, seg, step)
            continue
        x, y, h, s = append_curve_points(pts, x, y, h, s, seg, step)
    return pts


def sample_by_arc(points: list[dict], count: int) -> tuple[list[dict], float]:
    arr = [{"x": points[0]["x"], "y": points[0]["y"], "s": 0.0, "seg": points[0].get("seg", "")}]
    total = 0.0
    for i in range(1, len(points)):
        ds = math.hypot(points[i]["x"] - points[i - 1]["x"], points[i]["y"] - points[i - 1]["y"])
        total += ds
        arr.append({"x": points[i]["x"], "y": points[i]["y"], "s": total, "seg": points[i].get("seg", "")})

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
        t = 0.0 if b["s"] == a["s"] else (target - a["s"]) / (b["s"] - a["s"])
        out.append(
            {
                "x": a["x"] + t * (b["x"] - a["x"]),
                "y": a["y"] + t * (b["y"] - a["y"]),
                "s": target,
                "seg": a.get("seg") or b.get("seg", ""),
            }
        )
    return out, total


def rigid_fit(source: list[dict], target: list[dict]) -> dict:
    n = len(source)
    sx = sum(p["x"] for p in source) / n
    sy = sum(p["y"] for p in source) / n
    tx = sum(p["x"] for p in target) / n
    ty = sum(p["y"] for p in target) / n
    a = 0.0
    b = 0.0
    for i in range(n):
        ux = source[i]["x"] - sx
        uy = source[i]["y"] - sy
        vx = target[i]["x"] - tx
        vy = target[i]["y"] - ty
        a += ux * vx + uy * vy
        b += ux * vy - uy * vx
    theta = math.atan2(b, a)
    c = math.cos(theta)
    s = math.sin(theta)
    ox = tx - (c * sx - s * sy)
    oy = ty - (s * sx + c * sy)
    return {"theta": theta, "c": c, "s": s, "ox": ox, "oy": oy}


def transform(points: Iterable[dict], fit: dict) -> list[dict]:
    out = []
    for p in points:
        out.append(
            {
                "x": fit["c"] * p["x"] - fit["s"] * p["y"] + fit["ox"],
                "y": fit["s"] * p["x"] + fit["c"] * p["y"] + fit["oy"],
                "s": p.get("s", 0.0),
                "seg": p.get("seg", ""),
            }
        )
    return out


def nearest_polyline_distance(p: dict, poly: list[dict], closed: bool = False) -> float:
    best = float("inf")
    edge_count = max(0, len(poly) - 1)
    if closed and len(poly) > 2 and math.hypot(poly[0]["x"] - poly[-1]["x"], poly[0]["y"] - poly[-1]["y"]) > 1e-9:
        edge_count += 1
    for i in range(edge_count):
        a = poly[i]
        b = poly[(i + 1) % len(poly)]
        vx = b["x"] - a["x"]
        vy = b["y"] - a["y"]
        wx = p["x"] - a["x"]
        wy = p["y"] - a["y"]
        vv = vx * vx + vy * vy
        t = 0.0 if vv < 1e-9 else max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
        qx = a["x"] + t * vx
        qy = a["y"] + t * vy
        d = math.hypot(p["x"] - qx, p["y"] - qy)
        if d < best:
            best = d
    return best


def write_svg(path: pathlib.Path, src: list[dict], torcs: list[dict]) -> None:
    all_pts = src + torcs
    min_x = min(p["x"] for p in all_pts)
    max_x = max(p["x"] for p in all_pts)
    min_y = min(p["y"] for p in all_pts)
    max_y = max(p["y"] for p in all_pts)
    pad = 30.0
    width = 1400.0
    height = 1400.0
    sx = (width - 2 * pad) / max(1e-6, max_x - min_x)
    sy = (height - 2 * pad) / max(1e-6, max_y - min_y)
    scale = min(sx, sy)

    def map_pt(p: dict) -> str:
        x = pad + (p["x"] - min_x) * scale
        y = height - (pad + (p["y"] - min_y) * scale)
        return f"{x:.2f},{y:.2f}"

    src_path = " ".join(map_pt(p) for p in src)
    torcs_path = " ".join(map_pt(p) for p in torcs)
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" height="{int(height)}" viewBox="0 0 {int(width)} {int(height)}">
  <rect x="0" y="0" width="{int(width)}" height="{int(height)}" fill="#111217"/>
  <polyline points="{src_path}" fill="none" stroke="#ff5a5a" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>
  <polyline points="{torcs_path}" fill="none" stroke="#f4f4f4" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
  <rect x="20" y="20" width="310" height="78" rx="8" fill="#00000088"/>
  <text x="34" y="50" fill="#ff5a5a" font-family="Consolas, monospace" font-size="20">Source centerline</text>
  <text x="34" y="78" fill="#f4f4f4" font-family="Consolas, monospace" font-size="20">TORCS centerline</text>
</svg>
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
