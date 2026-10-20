# /***************************************************************************
#
#     file                 : test_reverse_centerline.py
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

from torcs_track_tools.cli.reverse_centerline import reverse_centerline_cache, signed_area


def test_reverse_centerline_reverses_polyline_and_orientation() -> None:
    obj = {
        "schema": 2,
        "source": {"type": "osm-overpass-circuit"},
        "polyline": [
            {"lat": 0.0, "lon": 0.0},
            {"lat": 0.0, "lon": 1.0},
            {"lat": 1.0, "lon": 1.0},
            {"lat": 1.0, "lon": 0.0},
        ],
    }

    original_area = signed_area(obj["polyline"])
    reversed_obj = reverse_centerline_cache(obj)

    assert reversed_obj["polyline"] == list(reversed(obj["polyline"]))
    assert reversed_obj["orientation"]["signed_area"] == -original_area
    assert reversed_obj["orientation"]["direction"] == "cw"
    assert reversed_obj["source"]["reversed_by_tracktools"]
    assert reversed_obj["source"]["original_type"] == "osm-overpass-circuit"
    assert reversed_obj["source"]["type"] == "tracktools-reversed-centerline"


def test_reverse_centerline_accepts_xy_points() -> None:
    obj = {
        "polyline": [
            {"x": 0.0, "y": 0.0},
            {"x": 1.0, "y": 0.0},
            {"x": 0.0, "y": 1.0},
        ]
    }

    reversed_obj = reverse_centerline_cache(obj)

    assert reversed_obj["orientation"]["direction"] == "cw"


def test_reverse_centerline_preserves_string_source_metadata() -> None:
    obj = {
        "source": "image-centerline",
        "polyline": [
            {"x": 0.0, "y": 0.0},
            {"x": 1.0, "y": 0.0},
            {"x": 0.0, "y": 1.0},
        ],
    }

    reversed_obj = reverse_centerline_cache(obj)

    assert reversed_obj["source"]["original_source"] == "image-centerline"
    assert reversed_obj["source"]["reversed_by_tracktools"]
    assert reversed_obj["source"]["type"] == "tracktools-reversed-centerline"
