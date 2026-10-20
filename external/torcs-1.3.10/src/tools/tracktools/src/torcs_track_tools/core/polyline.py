# /***************************************************************************
#
#     file                 : polyline.py
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

"""Shared cached-polyline projection helpers."""

from __future__ import annotations

import math

LON_METERS_AT_EQUATOR = 111320.0
LAT_METERS = 110540.0


def source_point_name(point: dict, keys: tuple[str, ...] = ("way_name", "name")) -> str:
    for key in keys:
        value = str(point.get(key, "")).strip()
        if value:
            return value
    return ""


def xy_from_latlon(point: dict, ref: dict) -> tuple[float, float]:
    lat0 = math.radians(float(ref["lat"]))
    x = (float(point["lon"]) - float(ref["lon"])) * LON_METERS_AT_EQUATOR * math.cos(lat0)
    y = (float(point["lat"]) - float(ref["lat"])) * LAT_METERS
    return x, y


def lonlat_from_xy(xy: tuple[float, float], ref: dict) -> tuple[float, float]:
    lat0 = math.radians(float(ref["lat"]))
    lon = float(ref["lon"]) + xy[0] / (LON_METERS_AT_EQUATOR * math.cos(lat0))
    lat = float(ref["lat"]) + xy[1] / LAT_METERS
    return lat, lon


def to_xy_tuples(points: list[dict], ref: dict | None = None) -> list[tuple[float, float]]:
    if not points:
        return []
    if "x" in points[0] and "y" in points[0]:
        return [(float(p["x"]), float(p["y"])) for p in points]
    coord_ref = ref or points[0]
    return [xy_from_latlon(p, coord_ref) for p in points]


def to_xy_dicts(
    points: list[dict],
    ref: dict | None = None,
    name_output_key: str | None = None,
    name_keys: tuple[str, ...] = ("way_name",),
) -> list[dict]:
    xy = to_xy_tuples(points, ref)
    out = []
    for point, (x, y) in zip(points, xy, strict=True):
        item = {"x": x, "y": y}
        if name_output_key is not None:
            item[name_output_key] = source_point_name(point, name_keys)
        out.append(item)
    return out


def from_xy_tuple(xy: tuple[float, float], coord_ref: dict, meta_ref: dict | None = None) -> dict:
    source_ref = meta_ref or coord_ref
    if "x" in coord_ref and "y" in coord_ref:
        return {
            "x": xy[0],
            "y": xy[1],
            "way_id": source_ref.get("way_id", 0),
            "way_name": source_ref.get("way_name", "seam-repair"),
            "member_role": source_ref.get("member_role", ""),
        }
    lat, lon = lonlat_from_xy(xy, coord_ref)
    return {
        "lat": lat,
        "lon": lon,
        "way_id": source_ref.get("way_id", 0),
        "way_name": source_ref.get("way_name", "seam-repair"),
        "member_role": source_ref.get("member_role", ""),
    }
