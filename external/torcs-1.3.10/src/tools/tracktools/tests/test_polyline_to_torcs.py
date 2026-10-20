# /***************************************************************************
#
#     file                 : test_polyline_to_torcs.py
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

from torcs_track_tools.cli.polyline_to_torcs import (
    FittedSegment,
    Pose,
    base_segment_name,
    can_merge_global_turn_pair,
    cleanup_small_wiggles,
    generate_corner_fit_segments,
    reconstruct_from_segments,
    simplify_segments,
    source_loop_len,
)


def test_base_segment_name_preserves_hyphenated_names() -> None:
    assert base_segment_name("Hangar-Straight") == "Hangar-Straight"


def test_base_segment_name_strips_only_terminal_numeric_suffix() -> None:
    assert base_segment_name("Hangar-Straight-2") == "Hangar-Straight"


def test_cleanup_small_wiggles_merges_opposite_turn_artifact() -> None:
    segments = [
        FittedSegment("a", "lft", 100.0, 8.0, 716.0, 716.0, 0.0, 0, 20),
        FittedSegment("wiggle", "rgt", 15.0, 0.8, 1074.0, 1074.0, 0.0, 20, 23),
        FittedSegment("c", "lft", 100.0, 8.0, 716.0, 716.0, 0.0, 23, 43),
    ]
    src_points = [{"x": float(i) * 5.0, "y": 0.0} for i in range(44)]

    cleaned, info = cleanup_small_wiggles(
        segments,
        length_round=1.0,
        arc_round=0.1,
        src_points=src_points,
        start_pose=Pose(0.0, 0.0, 0.0),
        max_arc_deg=1.2,
        max_len_m=45.0,
        neighbor_ratio=0.35,
        rmse_growth=1000.0,
        maxdev_growth=1000.0,
    )

    assert info["removals"] == 1
    assert len(cleaned) == 1
    assert cleaned[0].seg_type == "lft"


def test_cleanup_small_wiggles_keeps_real_opposite_turn() -> None:
    segments = [
        FittedSegment("a", "lft", 100.0, 5.0, 1146.0, 1146.0, 0.0, 0, 20),
        FittedSegment("real", "rgt", 80.0, 4.0, 1146.0, 1146.0, 0.0, 20, 36),
        FittedSegment("c", "lft", 100.0, 5.0, 1146.0, 1146.0, 0.0, 36, 56),
    ]
    src_points = [{"x": float(i) * 5.0, "y": 0.0} for i in range(57)]

    cleaned, info = cleanup_small_wiggles(
        segments,
        length_round=1.0,
        arc_round=0.1,
        src_points=src_points,
        start_pose=Pose(0.0, 0.0, 0.0),
        max_arc_deg=5.0,
        max_len_m=100.0,
        neighbor_ratio=0.35,
        rmse_growth=1000.0,
        maxdev_growth=1000.0,
    )

    assert info["removals"] == 0
    assert cleaned == segments


def test_cleanup_small_wiggles_merges_edge_artifacts_around_dominant_turn() -> None:
    segments = [
        FittedSegment("entry", "lft", 30.0, 0.8, 2149.0, 2149.0, 0.0, 0, 6),
        FittedSegment("turn", "rgt", 175.0, 32.7, 307.0, 307.0, 0.0, 6, 41),
        FittedSegment("exit", "lft", 35.0, 1.6, 1253.0, 1253.0, 0.0, 41, 48),
    ]
    src_points = [{"x": float(i) * 5.0, "y": 0.0} for i in range(49)]

    cleaned, info = cleanup_small_wiggles(
        segments,
        length_round=1.0,
        arc_round=0.1,
        src_points=src_points,
        start_pose=Pose(0.0, 0.0, 0.0),
        max_arc_deg=1.2,
        max_len_m=45.0,
        neighbor_ratio=0.35,
        rmse_growth=1000.0,
        maxdev_growth=1000.0,
    )

    assert info["removals"] == 1
    assert len(cleaned) == 1
    assert cleaned[0].seg_type == "rgt"
    assert cleaned[0].arc_deg == 30.3


def test_cleanup_small_wiggles_keeps_real_edge_chicane() -> None:
    segments = [
        FittedSegment("entry", "lft", 80.0, 8.6, 533.0, 533.0, 0.0, 0, 16),
        FittedSegment("turn", "rgt", 85.0, 22.3, 218.0, 218.0, 0.0, 16, 33),
        FittedSegment("exit", "lft", 20.0, 11.6, 99.0, 99.0, 0.0, 33, 37),
    ]
    src_points = [{"x": float(i) * 5.0, "y": 0.0} for i in range(38)]

    cleaned, info = cleanup_small_wiggles(
        segments,
        length_round=1.0,
        arc_round=0.1,
        src_points=src_points,
        start_pose=Pose(0.0, 0.0, 0.0),
        max_arc_deg=1.2,
        max_len_m=45.0,
        neighbor_ratio=0.35,
        rmse_growth=1000.0,
        maxdev_growth=1000.0,
    )

    assert info["removals"] == 0
    assert cleaned == segments


def test_simplify_segments_merges_compatible_local_neighbors() -> None:
    segments = [
        FittedSegment("straight-a", "str", 10.0, 0.0, 0.0, 0.0, 0.0, 0, 2),
        FittedSegment("straight-b", "str", 5.0, 0.0, 0.0, 0.0, 0.0, 2, 3),
        FittedSegment("turn-a", "lft", 20.0, 3.0, 100.0, 101.0, 0.0, 3, 6),
        FittedSegment("turn-b", "lft", 30.0, 4.0, 101.5, 102.0, 0.0, 6, 10),
    ]
    src_points = [{"x": float(i) * 10.0, "y": 0.0} for i in range(11)]

    simplified = simplify_segments(segments, length_round=1.0, arc_round=0.1, src_points=src_points, start_pose=Pose(0.0, 0.0, 0.0))

    assert len(simplified) == 2
    assert simplified[0].name == "straight-a"
    assert simplified[0].length == 15.0
    assert simplified[0].i1 == 3
    assert simplified[1].name == "turn-a"
    assert simplified[1].length == 50.0
    assert simplified[1].arc_deg == 7.0
    assert simplified[1].end_radius == 102.0
    assert simplified[1].i1 == 10


def test_global_turn_merge_gate_preserves_seam_tail_and_radius_bridge() -> None:
    a = FittedSegment("a", "lft", 25.0, 4.0, 100.0, 100.0, 0.0, 10, 20)
    b = FittedSegment("b", "lft", 25.0, 4.0, 103.5, 103.5, 0.0, 20, 30)

    assert can_merge_global_turn_pair(a, b, length_round=1.0, seam_idx_gate=40)
    assert not can_merge_global_turn_pair(a, b, length_round=1.0, seam_idx_gate=30)
    assert not can_merge_global_turn_pair(a, b, length_round=0.5, seam_idx_gate=40)
    assert not can_merge_global_turn_pair(a, FittedSegment("c", "rgt", 25.0, 4.0, 100.0, 100.0, 0.0, 20, 30), 1.0, 40)


def test_zurich_style_corner_fit_preserves_declared_length_and_chicane_controls() -> None:
    points_xy = [
        (0.0, 0.0),
        (450.0, 35.0),
        (530.0, 70.0),
        (560.0, 55.0),
        (595.0, 75.0),
        (690.0, 120.0),
        (660.0, 185.0),
        (720.0, 165.0),
        (780.0, 260.0),
        (580.0, 360.0),
        (500.0, 250.0),
        (120.0, 240.0),
        (0.0, 200.0),
    ]
    src_points = [{"x": x, "y": y, "way_name": "zurich-test"} for x, y in points_xy]

    start_pose, segments, info = generate_corner_fit_segments(
        src_points,
        tolerance=3.0,
        trim_max=4.0,
        length_round=1.0,
        arc_round=0.1,
        target_length_m=2460.0,
    )
    model = reconstruct_from_segments(start_pose, segments)

    assert info["corner_controls"] >= 10
    assert any(seg.seg_type == "lft" for seg in segments)
    assert any(seg.seg_type == "rgt" for seg in segments)
    assert abs(source_loop_len(model) - 2460.0) < 5.0
