# /***************************************************************************
#
#     file                 : test_describe_lrs_fit.py
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

import math

import pytest

from torcs_track_tools.cli import describe_lrs_fit


def test_runs_from_classes_absorbs_tiny_middle_run() -> None:
    classes = [
        {"kind": "str", "i": 1},
        {"kind": "str", "i": 2},
        {"kind": "lft", "i": 3},
        {"kind": "str", "i": 4},
        {"kind": "str", "i": 5},
    ]

    runs = describe_lrs_fit.runs_from_classes(classes, min_len=2.0, step=1.0)

    assert runs == [{"kind": "str", "i0": 1, "i1": 5}]


def test_segments_from_runs_builds_straight_segment() -> None:
    points = [{"x": 0.0, "y": 0.0}, {"x": 5.0, "y": 0.0}, {"x": 10.0, "y": 0.0}]

    segments = describe_lrs_fit.segments_from_runs(points, [{"kind": "str", "i0": 1, "i1": 1}])

    assert segments == [describe_lrs_fit.Segment(kind="str", length=10.0, turn_rad=0.0)]


def test_segments_from_runs_builds_left_curve_segment() -> None:
    radius = 20.0
    points = []
    for i in range(13):
        angle = math.radians(90.0 * i / 12.0)
        points.append({"x": radius * math.sin(angle), "y": radius - radius * math.cos(angle)})

    segments = describe_lrs_fit.segments_from_runs(points, [{"kind": "lft", "i0": 1, "i1": 11}], round_len=0.1, round_arc=0.1)

    assert len(segments) == 1
    assert segments[0].kind == "lft"
    assert math.degrees(segments[0].turn_rad) == pytest.approx(82.5, abs=1.0)
    assert segments[0].length == pytest.approx(radius * math.radians(82.5), rel=0.05)
