#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : osm.py
#     created              : 23 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

from __future__ import annotations

import math


def osm_point_key(point: dict) -> str:
    return f"{point['lat']:.7f},{point['lon']:.7f}"


def osm_point_distance_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    lat_scale = 110540.0
    lon_scale = 111320.0 * math.cos(math.radians((a_lat + b_lat) * 0.5))
    dx = (b_lon - a_lon) * lon_scale
    dy = (b_lat - a_lat) * lat_scale
    return math.hypot(dx, dy)


def osm_signed_area(points: list[dict]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i in range(len(points)):
        a = points[i]
        b = points[(i + 1) % len(points)]
        area += float(a["lon"]) * float(b["lat"]) - float(b["lon"]) * float(a["lat"])
    return 0.5 * area


def osm_points_distance_m(a: dict, b: dict) -> float:
    return osm_point_distance_m(float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"]))


def osm_overlap_run_length(points: list[dict], i: int, j: int, distance_threshold_m: float) -> int:
    run = 1
    while i + run < len(points) and j + run < len(points):
        if osm_points_distance_m(points[i + run], points[j + run]) > distance_threshold_m:
            break
        run += 1
    return run


def osm_near_overlap_run(points: list[dict], i: int, j: int, distance_threshold_m: float, min_run_length: int) -> dict | None:
    if osm_points_distance_m(points[i], points[j]) > distance_threshold_m:
        return None
    run = osm_overlap_run_length(points, i, j, distance_threshold_m)
    if run < min_run_length:
        return None
    return {
        "i0": i,
        "j0": j,
        "run_length_points": run,
        "distance_threshold_m": distance_threshold_m,
        "way_a": points[i].get("way_name", ""),
        "way_b": points[j].get("way_name", ""),
    }


def osm_detect_near_overlaps(
    points: list[dict],
    min_index_separation: int = 10,
    distance_threshold_m: float = 5.0,
    min_run_length: int = 4,
    max_reports: int = 8,
) -> dict:
    runs: list[dict] = []
    n = len(points)
    i = 0
    while i < n:
        found = False
        for j in range(i + min_index_separation, n):
            run = osm_near_overlap_run(points, i, j, distance_threshold_m, min_run_length)
            if run is None:
                continue
            runs.append(run)
            i += int(run["run_length_points"])
            found = True
            break
        if not found:
            i += 1
        if len(runs) >= max_reports:
            break
    return {
        "count": len(runs),
        "distance_threshold_m": distance_threshold_m,
        "min_run_length": min_run_length,
        "runs": runs,
    }


def candidate_osm_ways(ways: list[dict]) -> dict[int, dict]:
    candidates: dict[int, dict] = {}
    for way in ways:
        geom = way.get("geometry") or []
        if len(geom) >= 2:
            candidates[int(way.get("id", 0))] = way
    return candidates


def osm_way_endpoint_counts(candidates: dict[int, dict]) -> dict[str, int]:
    endpoint_count: dict[str, int] = {}
    for way in candidates.values():
        geom = way.get("geometry") or []
        for key in (osm_point_key(geom[0]), osm_point_key(geom[-1])):
            endpoint_count[key] = endpoint_count.get(key, 0) + 1
    return endpoint_count


def osm_way_has_open_endpoint(way: dict, endpoint_count: dict[str, int]) -> bool:
    geom = way.get("geometry") or []
    return endpoint_count.get(osm_point_key(geom[0]), 0) == 1 or endpoint_count.get(osm_point_key(geom[-1]), 0) == 1


def choose_osm_start_way_id(candidates: dict[int, dict], endpoint_count: dict[str, int]) -> int:
    for wid in sorted(candidates):
        if osm_way_has_open_endpoint(candidates[wid], endpoint_count):
            return wid
    return min(candidates)


def oriented_osm_start_way(candidates: dict[int, dict], start_id: int, endpoint_count: dict[str, int]) -> dict:
    first = dict(candidates[start_id])
    first_geom = list(first.get("geometry") or [])
    if endpoint_count.get(osm_point_key(first_geom[-1]), 0) == 1 and endpoint_count.get(osm_point_key(first_geom[0]), 0) != 1:
        first_geom.reverse()
        first["geometry"] = first_geom
    return first


def matching_unused_osm_way(candidates: dict[int, dict], used: set[int], last_end: str) -> tuple[int, dict, bool] | None:
    for wid in sorted(candidates):
        if wid in used:
            continue
        way = candidates[wid]
        geom = list(way.get("geometry") or [])
        if osm_point_key(geom[0]) == last_end:
            return wid, dict(way), False
        if osm_point_key(geom[-1]) == last_end:
            geom.reverse()
            best_way = dict(way)
            best_way["geometry"] = geom
            return wid, best_way, True
    return None


def fallback_unused_osm_way(candidates: dict[int, dict], used: set[int]) -> tuple[int, dict]:
    leftovers = [wid for wid in sorted(candidates) if wid not in used]
    wid = leftovers[0]
    return wid, dict(candidates[wid])


def osm_join_gap_m(last_end_pt: dict, next_way: dict) -> float:
    first_pt = (next_way.get("geometry") or [])[0]
    return osm_point_distance_m(float(last_end_pt["lat"]), float(last_end_pt["lon"]), float(first_pt["lat"]), float(first_pt["lon"]))


def osm_join_record(from_way: dict, to_way: dict, matched: bool, reversed_geom: bool, gap: float) -> dict:
    return {
        "from_way_id": int(from_way.get("id", 0)),
        "to_way_id": int(to_way.get("id", 0)),
        "matched_endpoint": matched,
        "reversed": reversed_geom,
        "gap_m": gap,
    }


def next_ordered_osm_way(candidates: dict[int, dict], ordered: list[dict], used: set[int]) -> tuple[int, dict, dict, bool, bool]:
    last_geom = ordered[-1].get("geometry") or []
    last_end = osm_point_key(last_geom[-1])
    match = matching_unused_osm_way(candidates, used, last_end)
    fallback_used = match is None
    if match is None:
        best_id, best_way = fallback_unused_osm_way(candidates, used)
        reversed_geom = False
    else:
        best_id, best_way, reversed_geom = match
    gap = osm_join_gap_m(last_geom[-1], best_way)
    join = osm_join_record(ordered[-1], best_way, not fallback_used, reversed_geom, gap)
    return best_id, best_way, join, fallback_used, gap > 5.0


def order_osm_ways(ways: list[dict]) -> tuple[list[dict], dict]:
    candidates = candidate_osm_ways(ways)
    if not candidates:
        return [], {"joins": [], "fallback_used": False, "bad_join": False}

    endpoint_count = osm_way_endpoint_counts(candidates)
    start_id = choose_osm_start_way_id(candidates, endpoint_count)
    ordered: list[dict] = [oriented_osm_start_way(candidates, start_id, endpoint_count)]
    used: set[int] = {start_id}
    joins: list[dict] = []
    fallback_used = False
    bad_join = False

    while len(used) < len(candidates):
        best_id, best_way, join, used_fallback, bad_gap = next_ordered_osm_way(candidates, ordered, used)
        fallback_used = fallback_used or used_fallback
        bad_join = bad_join or bad_gap
        joins.append(join)
        ordered.append(best_way)
        used.add(best_id)

    return ordered, {"joins": joins, "fallback_used": fallback_used, "bad_join": bad_join}
