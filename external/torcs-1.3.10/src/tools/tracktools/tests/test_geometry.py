# /***************************************************************************
#
#     file                 : test_geometry.py
#     created              : 01 May 2026
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

from torcs_track_tools.core.geometry import (
    Pose,
    Segment,
    advance_segment,
    biarc_segments,
    curvature_profile,
    pose_to_pose_arc,
    sample_segment,
    sample_segments,
    segment_to_point,
    torcs_step_count,
    turn_length,
    variable_pose_to_pose_turn_candidates,
    variable_turn_step_length,
)


def test_straight_advances_along_heading() -> None:
    pose = advance_segment(Pose(1.0, 2.0, math.pi / 2.0), Segment("straight", "str", length=10.0))

    assert pose.x == pytest.approx(1.0)
    assert pose.y == pytest.approx(12.0)
    assert pose.heading == pytest.approx(math.pi / 2.0)


def test_constant_left_quarter_turn_matches_circle_geometry() -> None:
    pose = advance_segment(Pose(0.0, 0.0, 0.0), Segment("turn", "lft", radius=10.0, arc_deg=90.0))

    assert pose.x == pytest.approx(10.0)
    assert pose.y == pytest.approx(10.0)
    assert pose.heading == pytest.approx(math.pi / 2.0)


def test_constant_right_quarter_turn_matches_circle_geometry() -> None:
    pose = advance_segment(Pose(0.0, 0.0, 0.0), Segment("turn", "rgt", radius=10.0, arc_deg=90.0))

    assert pose.x == pytest.approx(10.0)
    assert pose.y == pytest.approx(-10.0)
    assert pose.heading == pytest.approx(-math.pi / 2.0)


def test_variable_turn_uses_torcs_radius_step_correction() -> None:
    arc = math.radians(90.0)
    steps = torcs_step_count(turn_length(10.0, arc, 20.0), 3.0)
    cur_length, dradius = variable_turn_step_length(10.0, 20.0, arc, steps)
    angle = 0.0
    radius = 10.0
    for _ in range(steps):
        angle += cur_length / radius
        radius += dradius

    assert steps == 8
    assert angle == pytest.approx(arc)


def test_variable_turn_final_heading_matches_requested_arc() -> None:
    pose = advance_segment(Pose(0.0, 0.0, 0.0), Segment("turn", "lft", radius=10.0, end_radius=20.0, arc_deg=90.0, profil_steps_length=3.0))

    assert pose.x > 10.0
    assert pose.y > 10.0
    assert pose.heading == pytest.approx(math.pi / 2.0)


def test_variable_pose_to_pose_turn_candidates_recover_transition_turn() -> None:
    start = Pose(0.0, 0.0, 0.0)
    source = Segment("source", "lft", radius=80.0, end_radius=240.0, arc_deg=35.0)
    end = advance_segment(start, source)

    candidates = variable_pose_to_pose_turn_candidates(start, end, "var", seeds=[(80.0, 240.0)])

    assert candidates
    pose = advance_segment(start, candidates[0])
    assert pose.x == pytest.approx(end.x, abs=0.05)
    assert pose.y == pytest.approx(end.y, abs=0.05)
    assert pose.heading == pytest.approx(end.heading)
    assert candidates[0].end_radius is not None


def test_sample_segments_preserves_cumulative_distance() -> None:
    samples = sample_segments(
        [
            Segment("a", "str", length=10.0),
            Segment("b", "lft", radius=10.0, arc_deg=90.0, profil_steps_length=3.0),
        ],
        step=5.0,
    )

    assert samples[-1].s == pytest.approx(10.0 + 10.0 * math.radians(90.0))
    assert samples[-1].heading == pytest.approx(math.pi / 2.0)


def test_sample_segment_returns_torcs_step_count_for_turns() -> None:
    segment = Segment("turn", "lft", radius=10.0, end_radius=20.0, arc_deg=90.0, profil_steps_length=3.0)
    _, samples = sample_segment(Pose(0.0, 0.0, 0.0), segment)

    assert len(samples) == 8


def test_segment_to_point_solves_quarter_turn_endpoint() -> None:
    segment = segment_to_point(Pose(0.0, 0.0, 0.0), 10.0, 10.0, "arc")

    assert segment is not None
    assert segment.kind == "lft"
    assert segment.radius == pytest.approx(10.0)
    assert segment.arc_deg == pytest.approx(90.0)


def test_pose_to_pose_arc_solves_endpoint_and_heading() -> None:
    segment = pose_to_pose_arc(Pose(0.0, 0.0, 0.0), Pose(10.0, 10.0, math.pi / 2.0), "arc")

    assert segment is not None
    end = advance_segment(Pose(0.0, 0.0, 0.0), segment)
    assert end.x == pytest.approx(10.0)
    assert end.y == pytest.approx(10.0)
    assert end.heading == pytest.approx(math.pi / 2.0)


def test_biarc_segments_preserve_straight_pose() -> None:
    segments = biarc_segments(Pose(0.0, 0.0, 0.0), Pose(20.0, 0.0, 0.0), "b")

    assert segments is not None
    pose = Pose(0.0, 0.0, 0.0)
    for segment in segments:
        pose = advance_segment(pose, segment)
    assert pose.x == pytest.approx(20.0)
    assert pose.y == pytest.approx(0.0)
    assert pose.heading == pytest.approx(0.0)


def test_biarc_segments_hit_offset_equal_tangent_pose() -> None:
    segments = biarc_segments(Pose(0.0, 0.0, 0.0), Pose(40.0, 10.0, 0.0), "b")

    assert segments is not None
    pose = Pose(0.0, 0.0, 0.0)
    for segment in segments:
        pose = advance_segment(pose, segment)
    assert pose.x == pytest.approx(40.0)
    assert pose.y == pytest.approx(10.0)
    assert pose.heading == pytest.approx(0.0)


def test_biarc_segments_hit_asymmetric_pose() -> None:
    end_pose = Pose(35.0, 20.0, math.radians(35.0))
    segments = biarc_segments(Pose(0.0, 0.0, 0.0), end_pose, "b")

    assert segments is not None
    pose = Pose(0.0, 0.0, 0.0)
    for segment in segments:
        pose = advance_segment(pose, segment)
    assert pose.x == pytest.approx(end_pose.x)
    assert pose.y == pytest.approx(end_pose.y)
    assert pose.heading == pytest.approx(end_pose.heading)


def test_curvature_profile_reports_zero_for_straight() -> None:
    points = [{"x": float(i) * 5.0, "y": 0.0} for i in range(20)]

    profile = curvature_profile(points, deadband=1.0 / 500.0)

    assert max(abs(sample.curvature) for sample in profile) == 0.0


def test_curvature_profile_estimates_left_arc_radius() -> None:
    radius = 40.0
    points = []
    for i in range(41):
        angle = math.radians(90.0 * i / 40.0)
        points.append({"x": radius * math.sin(angle), "y": radius - radius * math.cos(angle)})

    profile = curvature_profile(points, window=3, median_radius=1, smooth_radius=1, deadband=0.0)
    middle = profile[10:-10]

    assert sum(sample.curvature for sample in middle) / len(middle) == pytest.approx(1.0 / radius, rel=0.1)
    assert sum(sample.radius for sample in middle) / len(middle) == pytest.approx(radius, rel=0.1)


def test_curvature_profile_uses_circular_window_for_closed_loop() -> None:
    radius = 40.0
    points = []
    for i in range(48):
        angle = 2.0 * math.pi * i / 48.0
        points.append({"x": radius * math.cos(angle), "y": radius * math.sin(angle)})
    points.append(points[0])

    forward = curvature_profile(points, window=3, median_radius=1, smooth_radius=1, deadband=0.0)
    reversed_profile = curvature_profile(list(reversed(points)), window=3, median_radius=1, smooth_radius=1, deadband=0.0)

    assert forward[0].curvature == pytest.approx(1.0 / radius, rel=0.15)
    assert sum(sample.curvature for sample in forward[:-1]) / (len(forward) - 1) == pytest.approx(1.0 / radius, rel=0.15)
    assert sum(sample.curvature for sample in reversed_profile[:-1]) / (len(reversed_profile) - 1) == pytest.approx(-1.0 / radius, rel=0.15)


def test_curvature_profile_denoises_short_sign_spikes() -> None:
    points = []
    for i in range(40):
        points.append({"x": float(i) * 5.0, "y": 0.4 if i == 20 else 0.0})

    profile = curvature_profile(points, window=3, median_radius=3, smooth_radius=2, deadband=1.0 / 500.0)

    assert max(abs(sample.curvature) for sample in profile[5:-5]) == 0.0
