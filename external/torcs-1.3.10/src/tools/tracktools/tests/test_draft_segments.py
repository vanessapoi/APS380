# /***************************************************************************
#
#     file                 : test_draft_segments.py
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

import json
import math

import pytest

import torcs_track_tools.cli.draft_segments as draft_segments
from torcs_track_tools.cli.draft_segments import (
    CurvatureRun,
    DraftResult,
    DraftValidation,
    bounded_radius_pose_segments,
    curvature_deviation,
    curvature_runs,
    curvature_variation_penalty,
    curve_metrics,
    dominant_source_name,
    dp_biarc_draft_segments,
    dp_edge_cost,
    event_boundary_count,
    event_crossing_penalty,
    event_segment_agreement_penalty,
    event_segment_mismatches,
    exact_pose_candidates,
    fallback_diagnostics,
    has_closure_control_straight,
    heading,
    main,
    make_dp_edge,
    near_straight_arc_as_straight,
    rename_results_from_source,
    resample,
    segment_curvature,
    segment_length,
    segments_to_xml,
    simplify_curvature_runs,
    simplify_near_straight_arcs,
    source_turn,
    validate_draft,
    validation_is_catastrophic,
    validation_score,
)
from torcs_track_tools.core.geometry import Pose, Segment, advance_segment, curvature_profile, sample_segment
from torcs_track_tools.core.polyline import to_xy_dicts


def test_curve_metrics_flags_wrong_turn_direction() -> None:
    radius_error, sign_error = curve_metrics(Segment("seg", "rgt", radius=20.0, arc_deg=45.0), 20.0, math.radians(45.0))

    assert radius_error >= 0.0
    assert sign_error


def test_segment_curvature_reports_signed_inverse_radius() -> None:
    assert segment_curvature(Segment("left", "lft", radius=50.0, arc_deg=10.0)) == pytest.approx(1.0 / 50.0)
    assert segment_curvature(Segment("right", "rgt", radius=25.0, arc_deg=10.0)) == pytest.approx(-1.0 / 25.0)
    assert segment_curvature(Segment("straight", "str", length=10.0)) == 0.0


def test_segment_length_reports_straight_and_arc_lengths() -> None:
    assert segment_length(Segment("str", "str", length=10.0)) == pytest.approx(10.0)
    assert segment_length(Segment("arc", "lft", radius=10.0, arc_deg=90.0)) == pytest.approx(10.0 * math.pi / 2.0)
    assert segment_length(Segment("transition", "lft", radius=80.0, end_radius=120.0, arc_deg=10.0)) == pytest.approx(100.0 * math.radians(10.0))


def test_segments_to_xml_writes_variable_radius() -> None:
    result = DraftResult(Segment("transition", "lft", radius=80.0, end_radius=240.0, arc_deg=35.0), 0, 1, 0.0, 0.0, 0.0, 0.0)

    xml = segments_to_xml([result])

    assert 'name="end radius"' in xml
    assert 'val="240.000"' in xml


def test_segments_to_xml_rejects_unbounded_radius() -> None:
    segment = Segment("near-straight", "rgt", radius=4274473.569, arc_deg=0.001233)
    result = DraftResult(segment, 0, 1, 0.0, 0.0, 0.0, 0.0)

    with pytest.raises(ValueError, match="radius exceeds 4000 m"):
        segments_to_xml([result])

    transition = Segment("transition", "lft", radius=3000.0, end_radius=5000.0, arc_deg=5.0)
    result = DraftResult(transition, 0, 1, 0.0, 0.0, 0.0, 0.0)

    with pytest.raises(ValueError, match="radius exceeds 4000 m"):
        segments_to_xml([result])


def test_exact_pose_candidates_include_high_radius_transition() -> None:
    start = Pose(0.0, 0.0, 0.0)
    source = Segment("source", "lft", radius=300.0, end_radius=900.0, arc_deg=20.0)
    end = advance_segment(start, source)
    _, samples = sample_segment(start, source, step=4.0)
    points = [{"x": start.x, "y": start.y}, *[{"x": sample.x, "y": sample.y} for sample in samples]]
    profile = curvature_profile(points, window=3, median_radius=1, smooth_radius=1, deadband=0.0)

    candidates = exact_pose_candidates(start, end, "edge", profile, 0, len(points) - 1)

    assert any(len(candidate) == 1 and candidate[0].end_radius is not None for candidate in candidates)


def test_curvature_deviation_compares_segment_to_source_profile() -> None:
    points = []
    radius = 40.0
    for i in range(21):
        angle = math.radians(60.0 * i / 20.0)
        points.append({"x": radius * math.sin(angle), "y": radius - radius * math.cos(angle)})
    from torcs_track_tools.core.geometry import curvature_profile

    profile = curvature_profile(points, window=3, median_radius=1, smooth_radius=1, deadband=0.0)

    rmse, max_abs = curvature_deviation(Segment("seg", "lft", radius=radius, arc_deg=60.0), profile, 4, 16)

    assert rmse < 0.005
    assert max_abs < 0.01


def test_curvature_runs_groups_denoised_profile_by_sign() -> None:
    points = []
    for i in range(20):
        points.append({"x": float(i) * 5.0, "y": 0.0})
    radius = 40.0
    base_x = points[-1]["x"]
    for i in range(1, 21):
        angle = math.radians(60.0 * i / 20.0)
        points.append({"x": base_x + radius * math.sin(angle), "y": radius - radius * math.cos(angle)})
    from torcs_track_tools.core.geometry import curvature_profile

    runs = curvature_runs(curvature_profile(points, window=3, median_radius=1, smooth_radius=1, deadband=1.0 / 1000.0))

    assert any(run.kind == "str" for run in runs)
    assert any(run.kind == "lft" and run.median_radius_m == pytest.approx(radius, rel=0.25) for run in runs)


def test_simplify_curvature_runs_turns_shallow_curves_into_straights() -> None:
    points = [{"x": float(i) * 4.0, "y": 0.0} for i in range(20)]
    from torcs_track_tools.core.geometry import curvature_profile

    profile = curvature_profile(points)
    runs = [type("Run", (), {"kind": "lft", "i0": 0, "i1": len(profile) - 1, "median_radius_m": 2000.0})()]

    simplified = simplify_curvature_runs(profile, runs)

    assert len(simplified) == 1
    assert simplified[0].kind == "str"


def test_simplify_curvature_runs_merges_short_noise_run() -> None:
    points = [{"x": float(i) * 4.0, "y": 0.0} for i in range(20)]
    from torcs_track_tools.core.geometry import curvature_profile

    profile = curvature_profile(points)
    runs = [
        type("Run", (), {"kind": "rgt", "i0": 0, "i1": 8, "median_radius_m": 100.0})(),
        type("Run", (), {"kind": "lft", "i0": 9, "i1": 10, "median_radius_m": 80.0})(),
    ]

    simplified = simplify_curvature_runs(profile, runs, min_length_m=20.0)

    assert len(simplified) == 1
    assert simplified[0].i1 == 10


def test_event_segment_mismatches_reports_wrong_segment_kind() -> None:
    radius = 40.0
    points = []
    for i in range(31):
        angle = math.radians(60.0 * i / 30.0)
        points.append({"x": radius * math.sin(angle), "y": radius - radius * math.cos(angle)})
    results = [DraftResult(Segment("draft-1", "rgt", radius=radius, arc_deg=60.0), 0, 30, 0.0, 0.0, 0.0, 0.0)]

    mismatches = event_segment_mismatches(points, results)

    assert mismatches
    assert mismatches[0]["event_kind"] == "lft"
    assert mismatches[0]["overlaps"][0]["segment_kind"] == "rgt"


def test_event_crossing_penalty_discourages_washing_out_chicanes() -> None:
    events = [
        CurvatureRun("rgt", 0, 10, 80.0),
        CurvatureRun("lft", 11, 20, 60.0),
        CurvatureRun("rgt", 21, 30, 80.0),
    ]

    assert event_boundary_count(events, 0, 30) == 2
    assert event_crossing_penalty(events, 0, 30, 1) > event_crossing_penalty(events, 0, 30, 3)


def test_event_segment_agreement_penalty_discourages_counter_bends() -> None:
    points = [{"x": float(i) * 4.0, "y": 0.0} for i in range(11)]
    profile = curvature_profile(points)
    straight_event = [CurvatureRun("str", 0, 10, math.inf)]
    left_event = [CurvatureRun("lft", 0, 10, 80.0)]

    straight = [Segment("seg", "str", length=40.0)]
    anticipation = [Segment("seg", "rgt", radius=500.0, arc_deg=5.0)]
    opposite = [Segment("seg", "rgt", radius=80.0, arc_deg=20.0)]

    assert event_segment_agreement_penalty(straight_event, profile, 0, 10, anticipation) > event_segment_agreement_penalty(straight_event, profile, 0, 10, straight)
    assert event_segment_agreement_penalty(left_event, profile, 0, 10, opposite) > event_segment_agreement_penalty(straight_event, profile, 0, 10, anticipation)


def test_curvature_variation_penalty_prefers_splitting_changing_curvature() -> None:
    radius0 = 300.0
    radius1 = 80.0
    points = []
    pose = Pose(0.0, 0.0, 0.0)
    for i in range(25):
        radius = radius0 + (radius1 - radius0) * i / 24.0
        segment = Segment("step", "lft", radius=radius, arc_deg=1.0)
        points.append({"x": pose.x, "y": pose.y})
        pose = advance_segment(pose, segment)
    points.append({"x": pose.x, "y": pose.y})
    profile = curvature_profile(points, window=2, median_radius=1, smooth_radius=1, deadband=0.0)

    whole = curvature_variation_penalty(profile, 0, len(points) - 1, [Segment("wide", "lft", radius=150.0, arc_deg=25.0)])
    split = curvature_variation_penalty(profile, 0, len(points) - 1, [Segment("a", "lft", radius=220.0, arc_deg=12.0), Segment("b", "lft", radius=100.0, arc_deg=13.0)])

    assert whole > 0.0
    assert split < whole


def test_dp_edge_cost_has_meaningful_segment_penalty() -> None:
    simple = dp_edge_cost(1.0, 2.0, 0.0, 50.0, 1.0, 1, 10.0)
    split = dp_edge_cost(1.0, 2.0, 0.0, 50.0, 1.0, 2, 10.0)

    assert split - simple == pytest.approx(12.0)


def test_near_straight_arc_as_straight_converts_tiny_counter_bend() -> None:
    segment = near_straight_arc_as_straight(Segment("seg", "rgt", radius=5000.0, arc_deg=0.5))

    assert segment.kind == "str"
    assert segment.length == pytest.approx(5000.0 * math.radians(0.5))


def test_near_straight_arc_as_straight_converts_negligible_long_arc() -> None:
    segment = near_straight_arc_as_straight(Segment("seg", "rgt", radius=100000.0, arc_deg=0.05), max_arc_deg=0.1, max_lateral_m=0.05)

    assert segment.kind == "str"


def test_bounded_radius_pose_segments_repairs_sulby_precision_hazard() -> None:
    segment = Segment("Sulby Main Road-14", "lft", radius=22845040.680, arc_deg=0.00022573)
    start = Pose(0.0, 0.0, 0.0)
    end = advance_segment(start, segment)

    bounded = bounded_radius_pose_segments(start, end, segment)

    assert [piece.kind for piece in bounded] == ["str", "lft", "str"]
    assert bounded[1].radius == 4000.0
    bounded_end = start
    for piece in bounded:
        bounded_end = advance_segment(bounded_end, piece)
    assert bounded_end.x == pytest.approx(end.x, abs=1e-6)
    assert bounded_end.y == pytest.approx(end.y, abs=1e-6)
    assert bounded_end.heading == pytest.approx(end.heading, abs=1e-12)


def test_radius_bounded_segments_preserves_meaningful_turn_and_length() -> None:
    segment = Segment("broad", "lft", radius=10000.0, arc_deg=5.0)
    start = Pose(0.0, 0.0, 0.0)
    end = advance_segment(start, segment)

    bounded = bounded_radius_pose_segments(start, end, segment)

    assert [piece.kind for piece in bounded] == ["str", "lft", "str"]
    assert bounded[1].radius == 4000.0
    assert bounded[1].arc_deg == pytest.approx(segment.arc_deg)
    assert sum(segment_length(piece) for piece in bounded) == pytest.approx(segment_length(segment), rel=0.001)
    bounded_end = start
    for piece in bounded:
        bounded_end = advance_segment(bounded_end, piece)
    assert bounded_end.x == pytest.approx(end.x, abs=1e-8)
    assert bounded_end.y == pytest.approx(end.y, abs=1e-8)
    assert bounded_end.heading == pytest.approx(end.heading, abs=1e-12)


def test_bounded_radius_pose_segments_preserves_right_turn_endpoint() -> None:
    segment = Segment("broad-right", "rgt", radius=10000.0, arc_deg=5.0)
    start = Pose(100.0, -50.0, math.radians(30.0))
    end = advance_segment(start, segment)

    bounded = bounded_radius_pose_segments(start, end, segment)

    assert [piece.kind for piece in bounded] == ["str", "rgt", "str"]
    bounded_end = start
    for piece in bounded:
        bounded_end = advance_segment(bounded_end, piece)
    assert bounded_end.x == pytest.approx(end.x, abs=1e-8)
    assert bounded_end.y == pytest.approx(end.y, abs=1e-8)
    assert bounded_end.heading == pytest.approx(end.heading, abs=1e-12)


def test_has_closure_control_straight_requires_long_straight() -> None:
    assert has_closure_control_straight([DraftResult(Segment("seg", "str", length=25.0), 0, 1, 0.0, 0.0, 0.0, 0.0)])
    assert not has_closure_control_straight([DraftResult(Segment("seg", "str", length=12.0), 0, 1, 0.0, 0.0, 0.0, 0.0)])
    assert not has_closure_control_straight([DraftResult(Segment("seg", "lft", radius=100000.0, arc_deg=0.05), 0, 1, 0.0, 0.0, 0.0, 0.0)])


def test_simplify_near_straight_arcs_keeps_accepted_cleanup_when_later_candidate_rejected(monkeypatch) -> None:
    source = [{"x": float(i), "y": 0.0} for i in range(6)]
    results = [
        DraftResult(Segment("good", "lft", radius=100000.0, arc_deg=0.05), 0, 1, 0.0, 0.0, 0.0, 0.0),
        DraftResult(Segment("control", "str", length=30.0), 1, 2, 0.0, 0.0, 0.0, 0.0),
        DraftResult(Segment("separator", "lft", radius=20.0, arc_deg=10.0), 2, 3, 0.0, 0.0, 0.0, 0.0),
        DraftResult(Segment("bad-left", "lft", radius=3000.0, arc_deg=1.0), 3, 4, 0.0, 0.0, 0.0, 0.0),
        DraftResult(Segment("bad-right", "rgt", radius=3000.0, arc_deg=1.0), 4, 5, 0.0, 0.0, 0.0, 0.0),
    ]

    def validation_for(candidate: list[DraftResult]) -> DraftValidation:
        has_rejected_bad_merge = any(result.segment.kind == "str" and result.source_i0 == 3 and result.source_i1 == 5 for result in candidate)
        return DraftValidation(
            track_length_m=0.0,
            model_length_m=0.0,
            segment_count=len(candidate),
            segment_density_per_km=0.0,
            min_segment_length_m=0.0,
            median_segment_length_m=0.0,
            short_segment_count=0,
            short_segment_total_length_m=0.0,
            fallback_count=0,
            fallback_total_length_m=0.0,
            high_error_segment_count=0,
            high_error_total_length_m=0.0,
            final_drift_m=3.0 if has_rejected_bad_merge else 0.0,
            final_heading_drift_deg=0.0,
            global_mean_error_m=0.0,
            global_rmse_m=0.0,
            global_max_error_m=0.0,
            max_local_rmse_m=0.0,
            max_local_dev_m=0.0,
            max_end_error_m=0.0,
            max_heading_error_deg=0.0,
            max_curvature_rmse=0.0,
            max_curvature_abs_error=0.0,
        )

    monkeypatch.setattr(draft_segments, "evaluate_results", lambda _work, candidate, _step, _profile: candidate)
    monkeypatch.setattr(draft_segments, "validate_draft", lambda _source, candidate: validation_for(candidate))

    simplified = simplify_near_straight_arcs(source, source, results, 4.0, [])

    assert [(result.segment.kind, result.source_i0, result.source_i1) for result in simplified] == [
        ("str", 0, 2),
        ("lft", 2, 3),
        ("lft", 3, 4),
        ("rgt", 4, 5),
    ]


def test_near_straight_arc_as_straight_keeps_real_turn() -> None:
    segment = near_straight_arc_as_straight(Segment("seg", "rgt", radius=80.0, arc_deg=10.0))

    assert segment.kind == "rgt"


def test_source_turn_uses_exit_tangent_against_pose() -> None:
    points = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 10.0, "y": 10.0}]

    assert math.degrees(source_turn(points, Pose(0.0, 0.0, 0.0), 0, 2)) == pytest.approx(90.0)


def test_validate_draft_reports_closure_and_global_error() -> None:
    points = [
        {"x": 0.0, "y": 0.0},
        {"x": 10.0, "y": 0.0},
        {"x": 10.0, "y": 10.0},
        {"x": 0.0, "y": 10.0},
    ]
    results = [DraftResult(Segment("draft-1", "str", length=10.0), 0, 1, 0.0, 0.0, 0.0, 0.0)]

    validation = validate_draft(points, results)

    assert validation.segment_count == 1
    assert validation.track_length_m == pytest.approx(40.0)
    assert validation.model_length_m == pytest.approx(10.0)
    assert validation.segment_density_per_km == pytest.approx(25.0)
    assert validation.short_segment_count == 1
    assert validation.short_segment_total_length_m == pytest.approx(10.0)
    assert validation.final_drift_m == pytest.approx(10.0)
    assert validation.global_max_error_m > 0.0


def test_validate_draft_reports_fallback_and_high_error_lengths() -> None:
    points = [{"x": 0.0, "y": 0.0}, {"x": 50.0, "y": 0.0}, {"x": 50.0, "y": 50.0}, {"x": 0.0, "y": 50.0}]
    results = [DraftResult(Segment("draft-1", "str", length=30.0), 0, 1, 1.0, 9.0, 0.0, 0.0, fallback=True)]

    validation = validate_draft(points, results, high_error_m=8.0)

    assert validation.fallback_count == 1
    assert validation.fallback_total_length_m == pytest.approx(30.0)
    assert validation.high_error_segment_count == 1
    assert validation.high_error_total_length_m == pytest.approx(30.0)


def test_validation_score_penalizes_heading_drift() -> None:
    points = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 10.0, "y": 10.0}, {"x": 0.0, "y": 10.0}]
    validation = validate_draft(points, [DraftResult(Segment("draft-1", "lft", radius=10.0, arc_deg=90.0), 0, 2, 0.0, 0.0, 0.0, 0.0)])

    assert validation_score(validation) > validation.global_rmse_m


def test_validation_is_catastrophic_flags_bad_global_error() -> None:
    points = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 10.0, "y": 10.0}, {"x": 0.0, "y": 10.0}]
    validation = validate_draft(points, [DraftResult(Segment("draft-1", "str", length=1000.0), 0, 1, 0.0, 0.0, 0.0, 0.0)])

    assert validation_is_catastrophic(validation)


def test_fallback_diagnostics_reports_failed_limits() -> None:
    results = [DraftResult(Segment("draft-1", "str", length=10.0), 0, 1, 5.0, 11.0, 9.0, 10.0, fallback=True)]

    diagnostics = fallback_diagnostics(results, 4.0, 10.0, 8.0, 8.0)

    assert diagnostics[0]["reasons"] == ["rmse", "max_dev", "endpoint", "heading"]


def test_resample_removes_duplicate_closed_endpoint() -> None:
    points = [
        {"x": 0.0, "y": 0.0},
        {"x": 10.0, "y": 0.0},
        {"x": 10.0, "y": 10.0},
        {"x": 0.0, "y": 10.0},
        {"x": 0.0, "y": 0.0},
    ]

    sampled = resample(points, 5.0)

    assert len(sampled) == 8
    assert sampled[0] != sampled[-1]


def test_to_xy_preserves_osm_way_name() -> None:
    points = [
        {"lat": 1.0, "lon": 2.0, "way_name": "Main Straight"},
        {"lat": 1.0, "lon": 2.001, "way_name": "Main Straight"},
    ]

    converted = to_xy_dicts(points, name_output_key="name", name_keys=("way_name", "name"))

    assert converted[0]["name"] == "Main Straight"


def test_rename_results_from_source_uses_gap_free_basename_counts() -> None:
    points = [
        {"x": 0.0, "y": 0.0, "name": "Main Straight"},
        {"x": 10.0, "y": 0.0, "name": "Main Straight"},
        {"x": 20.0, "y": 0.0, "name": "Main Straight-7"},
        {"x": 30.0, "y": 0.0, "name": "Back Section"},
        {"x": 40.0, "y": 0.0, "name": "Back Section"},
    ]
    results = [
        DraftResult(Segment("draft-1", "str", length=10.0), 0, 1, 0.0, 0.0, 0.0, 0.0),
        DraftResult(Segment("draft-2", "str", length=10.0), 1, 2, 0.0, 0.0, 0.0, 0.0),
        DraftResult(Segment("draft-3", "str", length=10.0), 3, 4, 0.0, 0.0, 0.0, 0.0),
    ]

    renamed = rename_results_from_source(points, results)

    assert [result.segment.name for result in renamed] == ["Main Straight", "Main Straight-2", "Back Section"]


def test_rename_results_from_source_falls_back_to_draft_names() -> None:
    points = [
        {"x": 0.0, "y": 0.0},
        {"x": 10.0, "y": 0.0},
        {"x": 20.0, "y": 0.0},
    ]
    results = [
        DraftResult(Segment("old-1", "str", length=10.0), 0, 1, 0.0, 0.0, 0.0, 0.0),
        DraftResult(Segment("old-2", "str", length=10.0), 1, 2, 0.0, 0.0, 0.0, 0.0),
    ]

    renamed = rename_results_from_source(points, results)

    assert [result.segment.name for result in renamed] == ["draft-1", "draft-2"]


def test_dominant_source_name_ignores_empty_names() -> None:
    points = [{"name": ""}, {"name": "Main"}, {"name": "Main"}, {"name": "Other"}]

    assert dominant_source_name(points, 0, 3) == "Main"


def test_make_dp_edge_builds_exact_pose_candidate() -> None:
    points = [{"x": float(i) * 5.0, "y": 0.0} for i in range(8)]
    from torcs_track_tools.core.geometry import curvature_profile

    profile = curvature_profile(points)
    edge = make_dp_edge(points, profile, 0, 7, 5.0, 10.0)

    assert edge is not None
    assert edge.i0 == 0
    assert edge.i1 == 7
    assert edge.max_dev_m < 1e-6


def test_dp_biarc_draft_segments_returns_chain_for_square() -> None:
    points = [
        {"x": 0.0, "y": 0.0},
        {"x": 80.0, "y": 0.0},
        {"x": 80.0, "y": 80.0},
        {"x": 0.0, "y": 80.0},
    ]

    results = dp_biarc_draft_segments(points, resample_step=5.0, min_seg_len=10.0, max_seg_len=80.0, max_dev=20.0)

    assert results
    assert all(result.source_i1 >= result.source_i0 for result in results)
    assert validate_draft(resample(points, 5.0), results).segment_count == len(results)


def test_dp_biarc_draft_segments_uses_source_names() -> None:
    points = [
        {"x": 0.0, "y": 0.0, "way_name": "Circuit"},
        {"x": 80.0, "y": 0.0, "way_name": "Circuit"},
        {"x": 80.0, "y": 80.0, "way_name": "Circuit"},
        {"x": 0.0, "y": 80.0, "way_name": "Circuit"},
    ]

    results = dp_biarc_draft_segments(points, resample_step=5.0, min_seg_len=10.0, max_seg_len=80.0, max_dev=20.0)

    assert results[0].segment.name == "Circuit"
    assert all(result.segment.name == "Circuit" or result.segment.name.startswith("Circuit-") for result in results)


def test_main_writes_outputs(tmp_path, monkeypatch) -> None:
    input_path = tmp_path / "centerline.json"
    output_json = tmp_path / "segments.json"
    output_xml = tmp_path / "segments.xml"
    input_path.write_text(
        json.dumps(
            {
                "polyline": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 80.0, "y": 0.0},
                    {"x": 80.0, "y": 80.0},
                    {"x": 0.0, "y": 80.0},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-draft-segments",
            "--input",
            str(input_path),
            "--output-json",
            str(output_json),
            "--output-xml",
            str(output_xml),
        ],
    )

    assert main() == 0
    assert output_json.exists()
    assert output_xml.exists()


def test_heading_reports_positive_y_as_left_turn_reference() -> None:
    assert heading({"x": 0.0, "y": 0.0}, {"x": 0.0, "y": 1.0}) == math.pi / 2.0
