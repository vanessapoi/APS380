# /***************************************************************************
#
#     file                 : test_osm_ordering.py
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

from torcs_track_tools.cli import fetch_centerline, fetch_track_layout
from torcs_track_tools.core.osm import order_osm_ways, osm_detect_near_overlaps, osm_signed_area


def point(lat: float, lon: float) -> dict:
    return {"lat": lat, "lon": lon}


def named_point(lat: float, lon: float, way_name: str) -> dict:
    return {"lat": lat, "lon": lon, "way_name": way_name}


def way(way_id: int, geometry: list[dict]) -> dict:
    return {"id": way_id, "geometry": geometry, "tags": {"name": f"way-{way_id}"}}


def layout(label: str, role: str, length_m: float, score: float, closure_gap_m: float = 0.0) -> dict:
    return {"label": label, "role": role, "length_m": length_m, "score": score, "closure_gap_m": closure_gap_m}


def test_order_osm_ways_orders_open_chain_and_reverses_matches() -> None:
    p0 = point(47.0, 8.0)
    p1 = point(47.0, 8.001)
    p2 = point(47.0, 8.002)
    p3 = point(47.0, 8.003)
    ways = [way(30, [p2, p3]), way(20, [p2, p1]), way(10, [p0, p1])]

    ordered, info = order_osm_ways(ways)

    assert [item["id"] for item in ordered] == [10, 20, 30]
    assert ordered[1]["geometry"] == [p1, p2]
    assert info["fallback_used"] is False
    assert info["bad_join"] is False
    assert info["joins"][0]["matched_endpoint"] is True
    assert info["joins"][0]["reversed"] is True


def test_order_osm_ways_reports_deterministic_disconnected_fallback() -> None:
    ways = [way(20, [point(48.0, 9.0), point(48.0, 9.001)]), way(10, [point(47.0, 8.0), point(47.0, 8.001)])]

    ordered, info = order_osm_ways(ways)

    assert [item["id"] for item in ordered] == [10, 20]
    assert info["fallback_used"] is True
    assert info["bad_join"] is True
    assert info["joins"][0]["matched_endpoint"] is False


def test_fetch_cli_order_wrappers_use_shared_ordering() -> None:
    ways = [way(20, [point(47.0, 8.001), point(47.0, 8.002)]), way(10, [point(47.0, 8.0), point(47.0, 8.001)])]

    assert fetch_centerline.order_ways(ways) == order_osm_ways(ways)
    assert fetch_track_layout.order_ways(ways) == order_osm_ways(ways)


def test_fetch_cli_diagnostics_use_shared_osm_helpers() -> None:
    assert fetch_centerline.detect_near_overlaps is osm_detect_near_overlaps
    assert fetch_track_layout.detect_near_overlaps is osm_detect_near_overlaps
    assert fetch_centerline.signed_area is osm_signed_area
    assert fetch_track_layout.signed_area is osm_signed_area


def test_osm_detect_near_overlaps_reports_parallel_run() -> None:
    first = [named_point(47.0, 8.0 + i * 0.00001, "first") for i in range(4)]
    gap = [named_point(47.0, 8.001 + i * 0.00001, "gap") for i in range(3)]
    second = [named_point(47.0, 8.0 + i * 0.00001, "second") for i in range(4)]

    report = osm_detect_near_overlaps(first + gap + second, min_index_separation=5, distance_threshold_m=0.25, min_run_length=4)

    assert report["count"] == 1
    assert report["runs"][0]["i0"] == 0
    assert report["runs"][0]["j0"] == 7
    assert report["runs"][0]["run_length_points"] == 4
    assert report["runs"][0]["way_a"] == "first"
    assert report["runs"][0]["way_b"] == "second"


def test_osm_signed_area_reports_loop_orientation() -> None:
    ccw = [point(47.0, 8.0), point(47.0, 8.001), point(47.001, 8.001), point(47.001, 8.0)]

    assert osm_signed_area(ccw) > 0.0
    assert osm_signed_area(list(reversed(ccw))) < 0.0


def test_pick_layout_handles_explicit_all_and_named_layouts() -> None:
    candidates = [layout("role:club", "club", 1000.0, 1.0), layout("all-members", "all", 1200.0, 0.5)]

    assert fetch_track_layout.pick_layout(candidates, "all")["label"] == "all-members"
    assert fetch_track_layout.pick_layout(candidates, "club")["label"] == "role:club"


def test_pick_layout_guards_against_tiny_default_selection() -> None:
    candidates = [layout("role:main", "main", 300.0, 10.0), layout("all-members", "all", 1000.0, 0.5, closure_gap_m=20.0)]

    assert fetch_track_layout.pick_layout(candidates, "main")["label"] == "all-members"


def test_build_layout_candidates_preserves_role_and_pit_filtering() -> None:
    p0 = point(47.0, 8.0)
    p1 = point(47.0, 8.001)
    p2 = point(47.0, 8.002)
    p3 = point(47.0, 8.003)
    p4 = point(47.0, 8.004)
    way_by_id = {
        10: way(10, [p0, p1]),
        20: way(20, [p1, p2]),
        30: way(30, [p2, p3]),
        40: way(40, [p3, p4]),
    }
    relation = {
        "members": [
            {"type": "way", "ref": 10, "role": "main"},
            {"type": "way", "ref": 20, "role": ""},
            {"type": "way", "ref": 30, "role": "pit_lane"},
            {"type": "way", "ref": 40, "role": "club"},
        ]
    }

    candidates = fetch_track_layout.build_layout_candidates(
        relation,
        way_by_id,
        include_roles={"main", "pit_lane"},
    )
    by_label = {candidate["label"]: candidate for candidate in candidates}

    assert "role:main" in by_label
    assert "role:unlabeled" in by_label
    assert "custom-roles" in by_label
    assert "role:main+unlabeled" in by_label
    assert "all-except-pit-like" in by_label
    assert "all-members" in by_label
    assert by_label["role:main"]["ordered_ways"][0]["member_role"] == "main"
    assert [way["member_role"] for way in by_label["custom-roles"]["ordered_ways"]] == ["main", "pit_lane"]
    assert [way["member_role"] for way in by_label["role:main+unlabeled"]["ordered_ways"]] == ["main", "unlabeled"]
    assert 30 not in by_label["all-except-pit-like"]["way_ids"]
    assert by_label["all-members"]["way_ids"] == [10, 20, 30, 40]
