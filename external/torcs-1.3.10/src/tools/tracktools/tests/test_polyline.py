# /***************************************************************************
#
#     file                 : test_polyline.py
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

import pytest

from torcs_track_tools.core.polyline import from_xy_tuple, to_xy_dicts, to_xy_tuples


def test_to_xy_tuples_accepts_existing_xy_points() -> None:
    assert to_xy_tuples([{"x": "1.5", "y": "-2.0"}]) == [(1.5, -2.0)]


def test_to_xy_dicts_preserves_requested_source_name() -> None:
    out = to_xy_dicts([{"x": 0, "y": 0, "way_name": "Main", "name": "Fallback"}], name_output_key="src", name_keys=("way_name", "name"))

    assert out == [{"x": 0.0, "y": 0.0, "src": "Main"}]


def test_from_xy_tuple_round_trips_latlon_reference() -> None:
    ref = {"lat": 47.0, "lon": 8.0, "way_id": 5, "way_name": "Loop"}
    point = from_xy_tuple((10.0, 20.0), ref)
    xy = to_xy_tuples([point], ref=ref)[0]

    assert xy[0] == pytest.approx(10.0)
    assert xy[1] == pytest.approx(20.0)
    assert point["way_name"] == "Loop"
