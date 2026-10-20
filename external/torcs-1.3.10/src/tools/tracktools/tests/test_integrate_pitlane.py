# /***************************************************************************
#
#     file                 : test_integrate_pitlane.py
#     created              : 28 Apr 2026
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
import xml.etree.ElementTree as ET
from argparse import Namespace

import pytest

import torcs_track_tools.cli.integrate_pitlane as integrate_pitlane


def straight_segment(name: str, length: float) -> ET.Element:
    seg = ET.Element("section", {"name": name})
    ET.SubElement(seg, "attstr", {"name": "type", "val": "str"})
    ET.SubElement(seg, "attnum", {"name": "lg", "unit": "m", "val": str(length)})
    return seg


def turn_segment(name: str, seg_type: str, radius: float, arc: float) -> ET.Element:
    seg = ET.Element("section", {"name": name})
    ET.SubElement(seg, "attstr", {"name": "type", "val": seg_type})
    ET.SubElement(seg, "attnum", {"name": "radius", "unit": "m", "val": str(radius)})
    ET.SubElement(seg, "attnum", {"name": "arc", "unit": "deg", "val": str(arc)})
    return seg


def safety_args(tmp_path, **overrides) -> Namespace:
    values = {
        "runtime_dir": str(tmp_path),
        "category": "road",
        "name": "unit",
        "overlay_polyline": "",
        "overlay_script": "",
        "no_rollback_on_fail": False,
        "dry_run": False,
        "max_delta_ang_deg_increase": 0.1,
        "max_delta_x_increase_m": 0.1,
        "max_delta_y_increase_m": 0.1,
        "max_final_delta_x_m": 0.1,
        "max_final_delta_y_m": 0.1,
        "max_final_delta_ang_deg": 0.1,
        "max_length_drift_ratio": 0.001,
        "max_rmse_increase_m": 0.1,
        "max_mean_dev_increase_m": 0.1,
    }
    values.update(overrides)
    return Namespace(**values)


def test_stage_for_closure_disables_immediate_safety(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    track_xml.write_text("<params></params>", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-integrate-pitlane",
            "--track-xml",
            str(track_xml),
            "--stage-for-closure",
        ],
    )

    args = integrate_pitlane.parse_args()

    assert args.stage_for_closure
    assert not args.enforce_safety


def test_default_pit_widths_preserve_fifteen_meter_corridor(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    track_xml.write_text("<params></params>", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["torcs-integrate-pitlane", "--track-xml", str(track_xml)])

    args = integrate_pitlane.parse_args()

    assert args.entry_exit_side_width + integrate_pitlane.NORMAL_BORDER_WIDTH == 15.0
    assert args.pit_side_width + 0.5 == 15.0


def test_xml_helpers_preserve_defaults_and_cleanup_legacy_attrs() -> None:
    seg = turn_segment("turn", "lft", 100.0, 15.0)
    ET.SubElement(seg, "attnum", {"name": "broken", "val": "not-a-number"})
    ET.SubElement(seg, "attnum", {"name": "stale", "val": "12"})

    assert integrate_pitlane.get_attnum(seg, "broken", 7.0) == pytest.approx(7.0)
    assert integrate_pitlane.segment_length(ET.Element("section", {"name": "unknown"})) == pytest.approx(0.0)

    integrate_pitlane.remove_attnum(seg, "stale")
    assert integrate_pitlane._find_att(seg, "attnum", "stale") is None

    straight = integrate_pitlane.clone_as_straight(seg, "straight", 25.0)
    assert integrate_pitlane.get_attstr(straight, "type") == "str"
    assert integrate_pitlane.get_attnum(straight, "lg") == pytest.approx(25.0)
    assert integrate_pitlane._find_att(straight, "attnum", "radius") is None
    assert integrate_pitlane._find_att(straight, "attnum", "arc") is None

    turn = integrate_pitlane.clone_as_turn(straight, "turn-2", "rgt", 80.0, 12.0)
    assert integrate_pitlane.get_attstr(turn, "type") == "rgt"
    assert integrate_pitlane.get_attnum(turn, "radius") == pytest.approx(80.0)
    assert integrate_pitlane.get_attnum(turn, "arc") == pytest.approx(12.0)
    assert integrate_pitlane._find_att(turn, "attnum", "lg") is None

    zero_radius_turn = turn_segment("bad", "lft", 0.0, 10.0)
    assert integrate_pitlane.segment_curvature(zero_radius_turn) == pytest.approx(1e9)


def test_host_mode_is_public_in_help(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["torcs-integrate-pitlane", "--help"])

    try:
        integrate_pitlane.parse_args()
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("Expected argparse help to exit")

    output = capsys.readouterr().out
    assert "--host-mode" in output
    assert "straighten" in output
    assert "refit adjacent" in output
    assert "connectors" in output
    assert "--pit-main-align" in output


def test_pit_main_alignment_controls_spare_distribution() -> None:
    center_pieces, _, _ = integrate_pitlane.split_host_to_pit_segments(
        straight_segment("host", 400.0), 400.0, 300.0, 8.0, set(), align="center"
    )
    start_pieces, _, _ = integrate_pitlane.split_host_to_pit_segments(
        straight_segment("host", 400.0), 400.0, 300.0, 8.0, set(), align="start"
    )
    end_pieces, _, _ = integrate_pitlane.split_host_to_pit_segments(
        straight_segment("host", 400.0), 400.0, 300.0, 8.0, set(), align="end"
    )

    assert [p.get("name") for p in center_pieces] == ["pit_host_pre", "pit_main_a", "pit_main_b", "pit_host_post"]
    assert [integrate_pitlane.segment_length(p) for p in center_pieces] == [50.0, 150.0, 150.0, 50.0]
    assert [p.get("name") for p in start_pieces] == ["pit_main_a", "pit_main_b", "pit_host_post"]
    assert [integrate_pitlane.segment_length(p) for p in start_pieces] == [150.0, 150.0, 100.0]
    assert [p.get("name") for p in end_pieces] == ["pit_host_pre", "pit_main_a", "pit_main_b"]
    assert [integrate_pitlane.segment_length(p) for p in end_pieces] == [100.0, 150.0, 150.0]


def test_pit_main_align_end_caps_default_entry_to_host_pre(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "pit-report.json"
    track_xml.write_text(
        """
<params>
  <section name="Main Track">
    <section name="Pits">
      <attstr name="type" val="none"/>
    </section>
    <section name="Track Segments">
      <section name="approach">
        <attstr name="type" val="lft"/>
        <attnum name="radius" unit="m" val="100"/>
        <attnum name="arc" unit="deg" val="30"/>
      </section>
      <section name="host">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="400"/>
      </section>
      <section name="exit">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="200"/>
      </section>
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-integrate-pitlane",
            "--track-xml",
            str(track_xml),
            "--pit-side",
            "left",
            "--host-segment",
            "host",
            "--pit-main-align",
            "end",
            "--dry-run",
            "--report",
            str(report_json),
        ],
    )

    assert integrate_pitlane.main() == 0

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["pit"]["pit_main_align"] == "end"
    assert report["pit"]["pit_host_pre_length_m"] == 100.0
    assert report["pit"]["pit_host_post_length_m"] == 0.0
    assert report["pit"]["entry_taper_requested_length_m"] == 120.0
    assert report["pit"]["entry_taper_target_length_m"] == 100.0
    assert report["pit"]["entry_taper_selected_length_m"] == 100.0
    assert report["pit"]["entry_taper_auto_limited"]
    assert report["pit"]["entry_segment"] == "pit_host_pre"
    assert report["pit"]["exit_taper_target_length_m"] == 120.0
    assert report["pit"]["exit_taper_selected_length_m"] == 200.0


def test_pit_main_align_end_allows_explicit_entry_taper_to_reach_previous_segment(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "pit-report.json"
    track_xml.write_text(
        """
<params>
  <section name="Main Track">
    <section name="Pits">
      <attstr name="type" val="none"/>
    </section>
    <section name="Track Segments">
      <section name="approach">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="80"/>
      </section>
      <section name="host">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="400"/>
      </section>
      <section name="exit">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="200"/>
      </section>
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-integrate-pitlane",
            "--track-xml",
            str(track_xml),
            "--host-segment",
            "host",
            "--pit-main-align",
            "end",
            "--entry-taper-length",
            "120",
            "--dry-run",
            "--report",
            str(report_json),
        ],
    )

    assert integrate_pitlane.main() == 0

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["pit"]["pit_host_pre_length_m"] == 100.0
    assert report["pit"]["entry_taper_target_length_m"] == 120.0
    assert report["pit"]["entry_taper_selected_length_m"] == 180.0
    assert not report["pit"]["entry_taper_auto_limited"]
    assert report["pit"]["entry_segment"] == "approach"


def test_pit_main_align_start_caps_default_exit_to_host_post(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "pit-report.json"
    track_xml.write_text(
        """
<params>
  <section name="Main Track">
    <section name="Pits">
      <attstr name="type" val="none"/>
    </section>
    <section name="Track Segments">
      <section name="approach">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="200"/>
      </section>
      <section name="host">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="400"/>
      </section>
      <section name="after">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="80"/>
      </section>
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-integrate-pitlane",
            "--track-xml",
            str(track_xml),
            "--host-segment",
            "host",
            "--pit-main-align",
            "start",
            "--dry-run",
            "--report",
            str(report_json),
        ],
    )

    assert integrate_pitlane.main() == 0

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["pit"]["pit_main_align"] == "start"
    assert report["pit"]["pit_host_pre_length_m"] == 0.0
    assert report["pit"]["pit_host_post_length_m"] == 100.0
    assert report["pit"]["entry_taper_target_length_m"] == 120.0
    assert report["pit"]["entry_taper_selected_length_m"] == 200.0
    assert report["pit"]["exit_taper_requested_length_m"] == 120.0
    assert report["pit"]["exit_taper_target_length_m"] == 100.0
    assert report["pit"]["exit_taper_selected_length_m"] == 100.0
    assert report["pit"]["exit_taper_auto_limited"]
    assert report["pit"]["exit_segment"] == "pit_host_post"


def test_connector_straightening_refits_adjacent_turns_for_pit_host() -> None:
    pre = turn_segment("Deer Leap-2", "lft", 221.840, 12.85482915)
    post = turn_segment("Old Hall Corner-2", "rgt", 241.205, 14.71348596)
    host_chain = [
        turn_segment("Deer Leap-3", "lft", 276.412, 10.33229456),
        straight_segment("Deer Leap-4", 52.013697),
        turn_segment("Deer Leap-5", "lft", 675.780, 1.69549763),
        turn_segment("Deer Leap-6", "lft", 484.159, 2.36638099),
        straight_segment("Deer Leap-7", 72.018965),
        turn_segment("Deer Leap-8", "lft", 558.188, 4.92549182),
        turn_segment("Old Hall Corner-pre", "rgt", 21847.893, 0.03073904741),
        turn_segment("Old Hall Corner-curb", "rgt", 21847.893, 0.09517895259),
    ]
    names_used = {seg.get("name", "") for seg in [pre, *host_chain, post]}

    pieces, host_name, meta = integrate_pitlane.fit_connector_straightening(pre, host_chain, post, 300.0, names_used)

    assert host_name == "pit_host_straight"
    assert len(pieces) == 3
    assert integrate_pitlane.get_attstr(pieces[1], "type") == "str"
    assert integrate_pitlane.get_attnum(pieces[1], "lg") == 300.0
    assert meta["pose_error"]["xy_m"] < 0.01
    assert meta["pose_error"]["ang_deg"] < 0.001
    assert meta["entry_connector"]["new_arc_deg"] > meta["entry_connector"]["old_arc_deg"]
    assert meta["exit_connector"]["new_arc_deg"] < meta["exit_connector"]["old_arc_deg"]


def test_manual_straighten_scans_straight_fragments_to_connector_arcs(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "pit-report.json"
    segs = [
        turn_segment("entry-arc", "lft", 200.0, 10.0),
        straight_segment("entry-fragment", 20.0),
        straight_segment("pit-candidate", 400.0),
        straight_segment("exit-fragment", 30.0),
        turn_segment("exit-arc", "rgt", 200.0, 10.0),
    ]
    track_xml.write_text(
        """
<params>
  <section name="Main Track">
    <section name="Pits">
      <attstr name="type" val="none"/>
    </section>
    <section name="Track Segments">
      {segments}
    </section>
  </section>
</params>
""".strip().format(segments="\n".join(ET.tostring(seg, encoding="unicode") for seg in segs)),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-integrate-pitlane",
            "--track-xml",
            str(track_xml),
            "--host-start-segment",
            "pit-candidate",
            "--host-end-segment",
            "pit-candidate",
            "--host-mode",
            "straighten",
            "--dry-run",
            "--report",
            str(report_json),
        ],
    )

    assert integrate_pitlane.main() == 0

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["connector_straightening"]["requested_host_chain_start"] == "pit-candidate"
    assert report["connector_straightening"]["requested_host_chain_end"] == "pit-candidate"
    assert report["connector_straightening"]["host_chain_start"] == "entry-fragment"
    assert report["connector_straightening"]["host_chain_end"] == "exit-fragment"
    assert report["connector_straightening"]["scanned_pre_straights"] == ["entry-fragment"]
    assert report["connector_straightening"]["scanned_post_straights"] == ["exit-fragment"]
    assert report["connector_straightening"]["straight_length_m"] > 400.0
    assert report["host_selection"]["straightened_host"] == "pit_host_straight"


def test_previous_turn_index_skipping_straights_requires_a_turn() -> None:
    segs = [straight_segment("a", 100.0), straight_segment("b", 100.0)]

    with pytest.raises(SystemExit, match="curved connector before"):
        integrate_pitlane.previous_turn_index_skipping_straights(segs, 0)


def test_real_placement_accepts_straight_consistent_pitlane() -> None:
    segs = [straight_segment("pit straight", 400.0)]
    pit_xy = [(50.0, 20.0), (200.0, 20.0), (350.0, 20.0)]

    result = integrate_pitlane.real_placement_feasibility(
        segs=segs,
        pit_xy=pit_xy,
        pit_main_length=300.0,
        max_chain_turn_deg=4.0,
        min_side_consistency=0.8,
    )

    assert result["status"] == "real-placement-ok"
    assert result["pit_side"] == "left"
    assert result["checks"]["span_long_enough"]
    assert result["checks"]["curvature_ok"]
    assert result["checks"]["side_consistent"]


def test_real_placement_can_project_in_source_coordinate_frame() -> None:
    segs = [turn_segment("unrelated xml bend", "lft", 50.0, 90.0)]
    mainline_xy = [(0.0, 0.0), (400.0, 0.0)]
    pit_xy = [(50.0, -20.0), (200.0, -20.0), (350.0, -20.0)]

    result = integrate_pitlane.real_placement_feasibility(
        segs=segs,
        pit_xy=pit_xy,
        pit_main_length=300.0,
        max_chain_turn_deg=4.0,
        min_side_consistency=0.8,
        mainline_xy=mainline_xy,
    )

    assert result["status"] == "real-placement-ok"
    assert result["projection_frame"] == "source"
    assert result["pit_side"] == "right"


def test_real_placement_uses_shorter_reversed_source_span() -> None:
    segs = [straight_segment("main", 1000.0)]
    mainline_xy = [(0.0, 0.0), (1000.0, 0.0)]
    pit_xy = [(800.0, 20.0), (500.0, 20.0), (200.0, 20.0)]

    result = integrate_pitlane.real_placement_feasibility(
        segs=segs,
        pit_xy=pit_xy,
        pit_main_length=300.0,
        max_chain_turn_deg=4.0,
        min_side_consistency=0.8,
        mainline_xy=mainline_xy,
    )

    assert result["source_direction"] == "reversed"
    assert result["projected_span_m"] == 600.0
    assert result["status"] == "real-placement-ok"


def test_project_point_to_samples_can_use_closing_edge() -> None:
    samples, _ = integrate_pitlane.sample_polyline_centerline(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        closed=False,
    )

    open_projection = integrate_pitlane.project_point_to_samples((-1.0, 5.0), samples, closed=False)
    closed_projection = integrate_pitlane.project_point_to_samples((-1.0, 5.0), samples, closed=True, total_length=40.0)

    assert open_projection["distance_m"] > 5.0
    assert closed_projection["distance_m"] == pytest.approx(1.0)
    assert closed_projection["station_m"] == pytest.approx(35.0)


def test_real_placement_forward_source_can_cross_loop_seam() -> None:
    mainline_xy = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    pit_xy = [(1.0, 10.0), (10.0, 1.0)]

    result = integrate_pitlane.real_placement_feasibility(
        segs=[],
        pit_xy=pit_xy,
        pit_main_length=10.0,
        max_chain_turn_deg=999.0,
        min_side_consistency=0.5,
        mainline_xy=mainline_xy,
    )

    assert result["status"] == "real-placement-ok"
    assert result["source_direction"] == "forward"
    assert result["host_start_station_m"] == pytest.approx(390.0)
    assert result["host_end_station_m"] == pytest.approx(10.0)
    assert result["projected_span_m"] == pytest.approx(20.0)


def test_real_placement_uses_best_pit_main_window_inside_curved_span() -> None:
    segs = [straight_segment("unused", 500.0)]
    mainline_xy = [(0.0, 0.0), (50.0, 0.0), (350.0, 0.0), (450.0, 0.0), (550.0, 100.0), (550.0, 300.0), (0.0, 300.0)]
    pit_xy = [(50.0, 20.0), (250.0, 20.0), (550.0, 120.0)]

    result = integrate_pitlane.real_placement_feasibility(
        segs=segs,
        pit_xy=pit_xy,
        pit_main_length=300.0,
        max_chain_turn_deg=4.0,
        min_side_consistency=0.5,
        mainline_xy=mainline_xy,
    )

    assert result["status"] == "real-placement-ok"
    assert result["full_span_turn_deg"] > result["mainline_turn_deg"]
    assert result["best_window"]["length_m"] >= 300.0


def test_to_xy_points_uses_common_lat_lon_reference() -> None:
    mainline_points = [{"lat": 45.0, "lon": 10.0}, {"lat": 45.0, "lon": 10.001}]
    pit_points = [{"lat": 45.0, "lon": 10.0}, {"lat": 45.0, "lon": 10.001}]

    mainline_xy = integrate_pitlane.to_xy_points(mainline_points, mainline_points[0])
    pit_xy = integrate_pitlane.to_xy_points(pit_points, mainline_points[0])

    assert pit_xy == mainline_xy


def test_real_placement_rejects_curved_pit_span() -> None:
    segs = [straight_segment("before", 50.0), turn_segment("oval bend", "lft", 220.0, 90.0), straight_segment("after", 300.0)]
    pit_xy = [(80.0, 20.0), (170.0, 80.0), (250.0, 200.0)]

    result = integrate_pitlane.real_placement_feasibility(
        segs=segs,
        pit_xy=pit_xy,
        pit_main_length=100.0,
        max_chain_turn_deg=4.0,
        min_side_consistency=0.5,
    )

    assert result["status"] == "real-placement-rejected-curvature"
    assert result["checks"]["span_long_enough"]
    assert not result["checks"]["curvature_ok"]


def test_real_placement_rejects_short_or_side_inconsistent_span() -> None:
    mainline_xy = [(0.0, 0.0), (400.0, 0.0)]

    too_short = integrate_pitlane.real_placement_feasibility(
        segs=[],
        pit_xy=[(10.0, 20.0), (40.0, 20.0)],
        pit_main_length=100.0,
        max_chain_turn_deg=4.0,
        min_side_consistency=0.8,
        mainline_xy=mainline_xy,
    )
    assert too_short["status"] == "real-placement-rejected-too-short"
    assert not too_short["checks"]["span_long_enough"]

    side_inconsistent = integrate_pitlane.real_placement_feasibility(
        segs=[],
        pit_xy=[(50.0, 20.0), (200.0, -20.0), (350.0, 20.0)],
        pit_main_length=100.0,
        max_chain_turn_deg=4.0,
        min_side_consistency=0.8,
        mainline_xy=mainline_xy,
    )
    assert side_inconsistent["status"] == "real-placement-rejected-side-inconsistent"
    assert side_inconsistent["side_counts"] == {"left": 2, "right": 1, "center": 0}
    assert side_inconsistent["side_consistency"] == pytest.approx(2.0 / 3.0)


def test_real_placement_report_only_writes_report_and_does_not_edit_xml(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    pit_source = tmp_path / "pitlane-source.json"
    report_json = tmp_path / "pit-report.json"
    overlay_svg = tmp_path / "pit-report.svg"
    original = """
<params>
  <section name="Main Track">
    <section name="Track Segments">
      <section name="pit straight">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="400"/>
      </section>
    </section>
  </section>
</params>
""".strip()
    track_xml.write_text(original, encoding="utf-8")
    pit_source.write_text(
        json.dumps({"polyline": [{"x": 50.0, "y": 20.0}, {"x": 200.0, "y": 20.0}, {"x": 350.0, "y": 20.0}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-integrate-pitlane",
            "--track-xml",
            str(track_xml),
            "--pit-source",
            str(pit_source),
            "--real-placement-report-only",
            "--report",
            str(report_json),
            "--real-placement-overlay",
            str(overlay_svg),
        ],
    )

    assert integrate_pitlane.main() == 0

    assert track_xml.read_text(encoding="utf-8") == original
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["real_placement"]["status"] == "real-placement-ok"
    assert report["real_placement"]["overlay"] == str(overlay_svg)
    assert "real-placement-ok" in overlay_svg.read_text(encoding="utf-8")


def test_serialize_xml_restore_entity_preserves_xml_prolog_comments() -> None:
    raw = """
<?xml version="1.0" encoding="UTF-8"?>
<!-- GPL header -->
<!DOCTYPE params SYSTEM "../../../src/libs/tgf/params.dtd" [
<!ENTITY default-surfaces SYSTEM "../../../data/tracks/surfaces.xml">
]>

<params>
  <section name="Surfaces">
    &default-surfaces;
  </section>
</params>
""".strip()
    replaced = raw.replace("&default-surfaces;", f"<{integrate_pitlane.ENTITY_PLACEHOLDER}/>")
    tree = ET.ElementTree(ET.fromstring(replaced))

    out = integrate_pitlane.serialize_xml_restore_entity(raw, tree)

    assert out.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!-- GPL header -->\n')
    assert "<!DOCTYPE params" in out
    assert "&default-surfaces;" in out


def test_real_placement_mutates_xml_and_preserves_no_pit_backup(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    mainline_source = tmp_path / "mainline-source.json"
    pit_source = tmp_path / "pitlane-source.json"
    report_json = tmp_path / "pit-report.json"
    original = """
<params>
  <section name="Main Track">
    <section name="Pits">
      <attstr name="type" val="none"/>
      <attstr name="side" val="right"/>
    </section>
    <section name="Track Segments">
      <section name="main straight">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="400"/>
      </section>
    </section>
  </section>
</params>
""".strip()
    track_xml.write_text(original, encoding="utf-8")
    mainline_source.write_text(
        json.dumps({"polyline": [{"x": 0.0, "y": 0.0}, {"x": 400.0, "y": 0.0}]}),
        encoding="utf-8",
    )
    pit_source.write_text(
        json.dumps({"polyline": [{"x": 50.0, "y": -20.0}, {"x": 200.0, "y": -20.0}, {"x": 350.0, "y": -20.0}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-integrate-pitlane",
            "--track-xml",
            str(track_xml),
            "--pit-source",
            str(pit_source),
            "--mainline-source",
            str(mainline_source),
            "--report",
            str(report_json),
            "--no-enforce-safety",
        ],
    )

    assert integrate_pitlane.main() == 0

    backup = tmp_path / "source" / "unit-track-no-pits.xml"
    assert backup.read_text(encoding="utf-8") == original
    root = ET.parse(track_xml).getroot()
    pits = next(s for s in root.iter("section") if s.get("name") == "Pits")
    assert integrate_pitlane.get_attstr(pits, "type") == "track side"
    assert integrate_pitlane.get_attstr(pits, "side") == "right"
    assert integrate_pitlane.get_attnum(pits, "length") == 15.0
    pit_main_a = next(s for s in root.iter("section") if s.get("name") == "pit_main_a")
    pit_side = integrate_pitlane.get_child_section(pit_main_a, "Right Side")
    pit_wall = integrate_pitlane.get_child_section(pit_main_a, "Right Border")
    assert pit_side is not None
    assert pit_wall is not None
    assert integrate_pitlane.get_attnum(pit_side, "start width") == 14.5
    assert integrate_pitlane.get_attnum(pit_wall, "width") == 0.5
    assert integrate_pitlane.get_attstr(pit_wall, "style") == "wall"
    assert integrate_pitlane.get_attnum(pit_side, "start width") + integrate_pitlane.get_attnum(pit_wall, "width") == 15.0
    entry_seg = next(s for s in root.iter("section") if s.get("name") == integrate_pitlane.get_attstr(pits, "entry"))
    exit_seg = next(s for s in root.iter("section") if s.get("name") == integrate_pitlane.get_attstr(pits, "exit"))
    entry_border = integrate_pitlane.get_child_section(entry_seg, "Right Border")
    exit_border = integrate_pitlane.get_child_section(exit_seg, "Right Border")
    assert entry_border is not None
    assert exit_border is not None
    assert integrate_pitlane.get_attstr(entry_border, "style") == "plan"
    assert integrate_pitlane.get_attstr(exit_border, "style") == "plan"
    assert integrate_pitlane.get_attstr(entry_border, "surface") == "b-road1-l2p"
    assert integrate_pitlane.get_attstr(exit_border, "surface") == "b-road1-l2p"
    assert integrate_pitlane.get_attnum(entry_border, "width") == 1.0
    assert integrate_pitlane.get_attnum(exit_border, "width") == 1.0
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["host_selection"]["real_placement"]
    assert report["no_pit_backup"] == str(backup)


def test_no_pit_backup_path_does_not_nest_source_directory(tmp_path) -> None:
    staging_xml = tmp_path / "source" / "unit-staging.xml"

    backup = integrate_pitlane.no_pit_backup_path(staging_xml)

    assert backup == tmp_path / "source" / "unit-staging-no-pits.xml"


def test_write_no_pit_backup_respects_active_pits_dry_run_and_existing_file(tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    raw = "<params />"
    pits = ET.Element("section", {"name": "Pits"})
    ET.SubElement(pits, "attstr", {"name": "type", "val": "track side"})
    assert integrate_pitlane.write_no_pit_backup(track_xml, raw, pits, dry_run=False) == ""

    integrate_pitlane.set_attstr(pits, "type", "none")
    dry_path = integrate_pitlane.write_no_pit_backup(track_xml, raw, pits, dry_run=True)
    assert dry_path == str(tmp_path / "source" / "unit-no-pits.xml")
    assert not (tmp_path / "source" / "unit-no-pits.xml").exists()

    written_path = integrate_pitlane.write_no_pit_backup(track_xml, raw, pits, dry_run=False)
    assert written_path == dry_path
    assert (tmp_path / "source" / "unit-no-pits.xml").read_text(encoding="utf-8") == raw
    assert integrate_pitlane.write_no_pit_backup(track_xml, "changed", pits, dry_run=False) == written_path
    assert (tmp_path / "source" / "unit-no-pits.xml").read_text(encoding="utf-8") == raw


def test_load_track_context_filters_generated_pit_segments(tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    track_xml.write_text(
        """
<params><section name="Main Track">
<section name="Pits"><attstr name="type" val="none"/></section>
<section name="Track Segments">
<section name="pit_main_a"><attstr name="type" val="str"/><attnum name="lg" val="150"/></section>
<section name="usable"><attstr name="type" val="str"/><attnum name="lg" val="400"/></section>
</section>
</section></params>
""".strip(),
        encoding="utf-8",
    )

    raw, tree, root, main_track, pits, track_segments, segs = integrate_pitlane.load_track_context(track_xml)

    assert raw.startswith("<params>")
    assert tree.getroot() is root
    assert main_track.get("name") == "Main Track"
    assert pits.get("name") == "Pits"
    assert track_segments.get("name") == "Track Segments"
    assert [seg.get("name") for seg in segs] == ["usable"]


def test_load_track_context_rejects_missing_required_sections(tmp_path) -> None:
    missing_main = tmp_path / "missing-main.xml"
    missing_segments = tmp_path / "missing-segments.xml"
    empty_segments = tmp_path / "empty-segments.xml"
    missing_main.write_text("<params></params>", encoding="utf-8")
    missing_segments.write_text('<params><section name="Main Track" /></params>', encoding="utf-8")
    empty_segments.write_text(
        '<params><section name="Main Track"><section name="Track Segments" /></section></params>',
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="Main Track section not found"):
        integrate_pitlane.load_track_context(missing_main)
    with pytest.raises(SystemExit, match="Main Track/Track Segments section not found"):
        integrate_pitlane.load_track_context(missing_segments)
    with pytest.raises(SystemExit, match="No track segments found"):
        integrate_pitlane.load_track_context(empty_segments)


def test_reset_normal_side_state_restores_grass_and_flat_border() -> None:
    seg = straight_segment("after pit exit", 80.0)

    integrate_pitlane.reset_normal_side_state(seg, "Right Side", "Right Border", 7.0)

    side = integrate_pitlane.get_child_section(seg, "Right Side")
    border = integrate_pitlane.get_child_section(seg, "Right Border")
    assert side is not None
    assert border is not None
    assert integrate_pitlane.get_attstr(side, "surface") == "grass6"
    assert integrate_pitlane.get_attnum(side, "start width") == 7.0
    assert integrate_pitlane.get_attnum(side, "end width") == 7.0
    assert integrate_pitlane.get_attstr(border, "style") == "plan"
    assert integrate_pitlane.get_attstr(border, "surface") == "b-road1-grass6"
    assert integrate_pitlane.get_attnum(border, "width") == 1.0
    assert integrate_pitlane._find_att(border, "attnum", "height") is None


def test_reset_normal_border_state_restores_left_flat_border() -> None:
    seg = straight_segment("after pit main", 80.0)

    integrate_pitlane.reset_normal_border_state(seg, "Left Border")

    border = integrate_pitlane.get_child_section(seg, "Left Border")
    assert border is not None
    assert integrate_pitlane.get_attstr(border, "style") == "plan"
    assert integrate_pitlane.get_attstr(border, "surface") == "b-road1-grass6"
    assert integrate_pitlane.get_attnum(border, "width") == 1.0
    assert integrate_pitlane._find_att(border, "attnum", "height") is None


def test_taper_index_order_and_side_width_profile_are_characterized() -> None:
    lengths = [10.0, 20.0, 30.0, 40.0]

    assert integrate_pitlane.ordered_taper_indices_backward(lengths, 1, 50.0) == [3, 0]
    assert integrate_pitlane.ordered_taper_indices_backward(lengths, 1, 50.0, {3}) == [0]
    assert integrate_pitlane.ordered_taper_indices_forward(lengths, 2, 60.0) == [3, 0, 1]
    assert integrate_pitlane.ordered_taper_indices_forward(lengths, 2, 60.0, {0}) == [3]
    assert integrate_pitlane.apply_side_width_profile([], [], "Right Side", 1.0, 2.0, 10.0, "manual-asphalt") == ("", "")

    segs = [straight_segment("entry", 10.0), straight_segment("middle", 20.0)]
    first, last = integrate_pitlane.apply_side_width_profile(segs, [0, 1], "Right Side", 4.0, 10.0, 30.0, "manual-asphalt")

    assert (first, last) == ("entry", "middle")
    entry_side = integrate_pitlane.get_child_section(segs[0], "Right Side")
    middle_side = integrate_pitlane.get_child_section(segs[1], "Right Side")
    assert entry_side is not None
    assert middle_side is not None
    assert integrate_pitlane.get_attnum(entry_side, "start width") == pytest.approx(4.0)
    assert integrate_pitlane.get_attnum(entry_side, "end width") == pytest.approx(6.0)
    assert integrate_pitlane.get_attnum(middle_side, "start width") == pytest.approx(6.0)
    assert integrate_pitlane.get_attnum(middle_side, "end width") == pytest.approx(10.0)
    assert integrate_pitlane.get_attstr(middle_side, "surface") == "manual-asphalt"


def test_border_style_and_manual_surface_normalization() -> None:
    seg = straight_segment("pit taper", 40.0)
    integrate_pitlane.apply_border_style(seg, "Right Border", "wall", "manual-barrier", 0.5, 1.0)
    border = integrate_pitlane.get_child_section(seg, "Right Border")
    assert border is not None
    assert integrate_pitlane.get_attstr(border, "style") == "wall"
    assert integrate_pitlane.get_attnum(border, "height") == pytest.approx(1.0)

    integrate_pitlane.apply_border_style(seg, "Right Border", "plan", "b-road1-l2p", 1.0, None)
    assert integrate_pitlane._find_att(border, "attnum", "height") is None

    root = ET.Element("params")
    integrate_pitlane.normalize_manual_surfaces(root)
    assert list(root) == []

    surfaces = ET.SubElement(root, "section", {"name": "Surfaces"})
    integrate_pitlane.normalize_manual_surfaces(root)
    asphalt = integrate_pitlane.get_child_section(surfaces, "manual-asphalt")
    barrier = integrate_pitlane.get_child_section(surfaces, "manual-barrier")
    assert asphalt is not None
    assert barrier is not None
    assert integrate_pitlane.get_attstr(asphalt, "texture name") == "tr-road1.rgb"
    assert integrate_pitlane.get_attstr(asphalt, "raceline name") == "raceline.png"
    assert integrate_pitlane.get_attnum(barrier, "dammage") == pytest.approx(10.0)


def test_source_station_for_segment_origin_verifies_suffix_way_name() -> None:
    points = [
        {"x": 0.0, "y": 0.0, "way_name": ""},
        {"x": 10.0, "y": 0.0, "way_name": "Other"},
        {"x": 30.0, "y": 0.0, "way_name": "Pit Straight"},
    ]
    seg = straight_segment("Pit Straight-1", 80.0)

    assert integrate_pitlane.source_station_for_segment_origin(points, seg) == 30.0


def test_source_station_for_segment_origin_accepts_verified_suffix() -> None:
    points = [
        {"x": 0.0, "y": 0.0, "way_name": "Pit Straight"},
        {"x": 10.0, "y": 0.0, "way_name": "Pit Straight"},
        {"x": 30.0, "y": 0.0, "way_name": "Other"},
    ]
    seg = straight_segment("Pit Straight-1", 80.0)

    assert integrate_pitlane.source_station_for_segment_origin(points, seg) == 10.0


def test_source_station_for_segment_origin_prefers_exact_numeric_source_name() -> None:
    points = [
        {"x": 0.0, "y": 0.0, "way_name": "Pit Straight"},
        {"x": 10.0, "y": 0.0, "way_name": "Pit Straight"},
        {"x": 30.0, "y": 0.0, "way_name": "Pit Straight-1"},
    ]
    seg = straight_segment("Pit Straight-1", 80.0)

    assert integrate_pitlane.source_station_for_segment_origin(points, seg) == 30.0


def test_source_origin_for_segments_uses_first_matching_named_segment() -> None:
    points = [
        {"x": 0.0, "y": 0.0, "way_name": "Start Straight"},
        {"x": 100.0, "y": 0.0, "way_name": "Named Bend"},
        {"x": 300.0, "y": 0.0, "way_name": "Named Bend"},
        {"x": 400.0, "y": 0.0, "way_name": "End Straight"},
    ]
    segs = [straight_segment("Segment-9", 40.0), straight_segment("Named Bend-2", 80.0)]

    assert integrate_pitlane.source_origin_for_segments(points, segs) == 260.0


def test_source_origin_for_segments_matches_exact_numeric_source_name() -> None:
    points = [
        {"x": 0.0, "y": 0.0, "way_name": "Start Straight"},
        {"x": 100.0, "y": 0.0, "way_name": "Named Bend-12"},
        {"x": 200.0, "y": 0.0, "way_name": "End Straight"},
    ]
    segs = [straight_segment("before", 40.0), straight_segment("Named Bend-12", 80.0)]

    assert integrate_pitlane.source_origin_for_segments(points, segs) == 60.0


def test_choose_manual_host_strategy_accepts_named_straight() -> None:
    segs = [straight_segment("before", 50.0), straight_segment("main straight", 400.0)]

    host = integrate_pitlane.choose_manual_host_strategy(
        segs,
        host_segment="main straight",
        host_start_segment="",
        host_end_segment="",
        pit_len=300.0,
        mode_override="auto",
    )

    assert host["mode"] == "exact"
    assert host["i0"] == 1
    assert host["i1"] == 1
    assert host["manual_host"]


def test_choose_manual_host_strategy_accepts_contiguous_chain() -> None:
    segs = [straight_segment("entry", 100.0), turn_segment("bend", "lft", 1000.0, 1.0), straight_segment("exit", 220.0)]

    host = integrate_pitlane.choose_manual_host_strategy(
        segs,
        host_segment="",
        host_start_segment="entry",
        host_end_segment="exit",
        pit_len=300.0,
        mode_override="auto",
    )

    assert host["mode"] == "almost"
    assert host["i0"] == 0
    assert host["i1"] == 2
    assert host["length"] > 300.0


def test_wrapping_manual_host_can_be_rotated_before_selection() -> None:
    segs = [
        straight_segment("tail", 200.0),
        turn_segment("middle", "lft", 500.0, 5.0),
        straight_segment("entry", 120.0),
    ]

    rotated = integrate_pitlane.rotate_segments_to_start(segs, "entry")
    host = integrate_pitlane.choose_manual_host_strategy(
        rotated,
        host_segment="",
        host_start_segment="entry",
        host_end_segment="tail",
        pit_len=300.0,
        mode_override="auto",
    )

    assert [s.get("name") for s in rotated[:2]] == ["entry", "tail"]
    assert host["mode"] == "almost"
    assert host["i0"] == 0
    assert host["i1"] == 1
    assert host["length"] == 320.0


def test_apply_manual_wrap_rotation_records_straighten_connector_rotation() -> None:
    segs = [
        straight_segment("tail", 200.0),
        turn_segment("connector", "lft", 500.0, 5.0),
        straight_segment("entry", 120.0),
    ]
    args = Namespace(host_segment="", host_start_segment="entry", host_end_segment="tail", host_mode="straighten")

    rotated, meta = integrate_pitlane.apply_manual_wrap_rotation(segs, args, manual_host_requested=True)

    assert [seg.get("name") for seg in rotated] == ["connector", "entry", "tail"]
    assert meta == {
        "start_segment": "entry",
        "end_segment": "tail",
        "original_start_index": 2,
        "original_end_index": 0,
        "rotation_start_segment": "connector",
        "rotation_reason": "straighten-connector",
    }


def test_wrapping_manual_straighten_cli_rotates_to_connector(monkeypatch, tmp_path) -> None:
    pre = turn_segment("Deer Leap-2", "lft", 221.840, 12.85482915)
    post = turn_segment("Old Hall Corner-2", "rgt", 241.205, 14.71348596)
    host_chain = [
        turn_segment("Deer Leap-3", "lft", 276.412, 10.33229456),
        straight_segment("Deer Leap-4", 52.013697),
        turn_segment("Deer Leap-5", "lft", 675.780, 1.69549763),
        turn_segment("Deer Leap-6", "lft", 484.159, 2.36638099),
        straight_segment("Deer Leap-7", 72.018965),
        turn_segment("Deer Leap-8", "lft", 558.188, 4.92549182),
        turn_segment("Old Hall Corner-pre", "rgt", 21847.893, 0.03073904741),
        turn_segment("Old Hall Corner-curb", "rgt", 21847.893, 0.09517895259),
    ]
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "pit-report.json"
    ordered = host_chain[4:] + [post, straight_segment("filler", 40.0), pre] + host_chain[:4]
    track_xml.write_text(
        """
<params>
  <section name="Main Track">
    <section name="Pits">
      <attstr name="type" val="none"/>
    </section>
    <section name="Track Segments">
      {segments}
    </section>
  </section>
</params>
""".strip().format(segments="\n".join(ET.tostring(seg, encoding="unicode") for seg in ordered)),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-integrate-pitlane",
            "--track-xml",
            str(track_xml),
            "--host-start-segment",
            "Deer Leap-3",
            "--host-end-segment",
            "Old Hall Corner-curb",
            "--host-mode",
            "straighten",
            "--dry-run",
            "--report",
            str(report_json),
        ],
    )

    assert integrate_pitlane.main() == 0

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["manual_wrap_rotation"]["rotation_reason"] == "straighten-connector"
    assert report["manual_wrap_rotation"]["rotation_start_segment"] == "Deer Leap-2"
    assert report["connector_straightening"]["host_chain_start"] == "Deer Leap-3"
    assert report["connector_straightening"]["host_chain_end"] == "Old Hall Corner-curb"
    assert report["connector_straightening"]["pose_error"]["xy_m"] < 0.01
    assert report["host_selection"]["straightened_host"] == "pit_host_straight"


def test_station_window_to_host_strategy_selects_wrapping_window() -> None:
    segs = [straight_segment("start", 100.0), straight_segment("middle-a", 100.0), straight_segment("middle-b", 100.0), straight_segment("tail", 100.0)]

    host = integrate_pitlane.station_window_to_host_strategy(
        segs,
        source_start=350.0,
        source_end=50.0,
        source_total=400.0,
        pit_len=150.0,
    )

    assert host["wrap"]
    assert host["i0"] == 3
    assert host["i1"] == 0
    assert host["index_count"] == 2
    assert host["length"] == 200.0


def test_select_host_strategy_uses_real_placement_window() -> None:
    segs = [straight_segment("start", 100.0), straight_segment("middle-a", 100.0), straight_segment("middle-b", 100.0), straight_segment("tail", 100.0)]
    args = Namespace(
        pit_main_length=150.0,
        host_segment="",
        host_start_segment="",
        host_end_segment="",
        host_mode="auto",
        almost_max_curvature=0.0025,
        almost_max_seg_turn_deg=2.0,
        almost_max_chain_turn_deg=4.0,
        preserve_host_pose=True,
        max_host_window_segs=8,
        max_host_window_len_m=450.0,
    )
    real_placement = {"best_window": {"start_station_m": 350.0, "end_station_m": 50.0}}

    host = integrate_pitlane.select_host_strategy(segs, args, False, real_placement, 400.0, 0.0)

    assert host["wrap"]
    assert host["i0"] == 3
    assert host["i1"] == 0
    assert host["length"] == 200.0


def test_auto_host_strategy_can_select_wrapping_almost_chain() -> None:
    segs = [
        straight_segment("tail", 110.0),
        turn_segment("tight-blocker", "lft", 50.0, 10.0),
        straight_segment("middle", 50.0),
        straight_segment("entry", 110.0),
    ]

    host = integrate_pitlane.choose_host_strategy(
        segs,
        pit_len=200.0,
        almost_max_curv=0.0025,
        almost_max_seg_turn_deg=2.0,
        almost_max_chain_turn_deg=4.0,
        preserve_host_pose=True,
        max_host_window_segs=2,
        max_host_window_len_m=240.0,
        mode_override="auto",
    )

    assert host["mode"] == "almost"
    assert host["wrap"]
    assert host["i0"] == 3
    assert host["i1"] == 0
    assert host["index_count"] == 2
    assert host["length"] == 220.0


def test_apply_host_wrap_rotation_normalizes_indices() -> None:
    segs = [straight_segment("start", 100.0), straight_segment("middle", 100.0), straight_segment("tail", 100.0), straight_segment("entry", 100.0)]
    host = {"mode": "almost", "wrap": True, "i0": 3, "i1": 0, "index_count": 2, "length": 200.0}

    rotated, rotated_host = integrate_pitlane.apply_host_wrap_rotation(segs, host)

    assert [seg.get("name") for seg in rotated] == ["entry", "start", "middle", "tail"]
    assert rotated_host["i0"] == 0
    assert rotated_host["i1"] == 1
    assert rotated_host["original_i0"] == 3
    assert rotated_host["original_i1"] == 0
    assert rotated_host["rotation_start_segment"] == "entry"
    assert rotated_host["wrap_rotation_applied"]


def test_apply_injected_host_mode_adds_balancing_straights() -> None:
    segs = [turn_segment("turn", "lft", 100.0, 5.0), straight_segment("straight", 120.0)]
    args = Namespace(pit_main_length=300.0)

    updated, i0, i1, mode = integrate_pitlane.apply_injected_host_mode(segs, args, set(), 0, 0, "inject")

    assert mode == "inject"
    assert i0 == 0
    assert i1 == 0
    assert [seg.get("name") for seg in updated[:2]] == ["pit_injected_host", "pit_counter_straight"]
    assert integrate_pitlane.segment_length(updated[0]) == pytest.approx(300.0)
    assert integrate_pitlane.segment_length(updated[1]) == pytest.approx(300.0)


def test_apply_lengthen_host_mode_extends_host_and_counter() -> None:
    segs = [straight_segment("host", 120.0), straight_segment("counter", 80.0)]
    args = Namespace(pit_main_length=300.0)
    report: dict = {}

    integrate_pitlane.apply_lengthen_host_mode(segs, args, 0, "lengthen", report)

    assert integrate_pitlane.segment_length(segs[0]) == pytest.approx(300.0)
    assert integrate_pitlane.segment_length(segs[1]) == pytest.approx(260.0)
    assert report["lengthen"] == {"segment": "host", "old_len": 120.0, "new_len": 300.0}
    assert report["counter_adjust"] == {"segment": "counter", "delta_len": 180.0}


def test_replace_host_with_pit_main_exact_mode_splits_host() -> None:
    segs = [straight_segment("host", 400.0), straight_segment("after", 50.0)]
    args = Namespace(pit_main_length=300.0, min_piece_len=8.0, pit_main_align="center", preserve_host_pose=True)
    report: dict = {}

    updated, pit_a_name, pit_b_name = integrate_pitlane.replace_host_with_pit_main(segs, args, set(), 0, 0, "exact", report)

    assert [seg.get("name") for seg in updated[:4]] == ["pit_host_pre", "pit_main_a", "pit_main_b", "pit_host_post"]
    assert (pit_a_name, pit_b_name) == ("pit_main_a", "pit_main_b")
    assert [integrate_pitlane.segment_length(seg) for seg in updated[:4]] == [50.0, 150.0, 150.0, 50.0]
    assert report == {}


def test_apply_pit_lane_styles_sets_pits_tapers_and_report() -> None:
    main_track = ET.Element("section", {"name": "Main Track"})
    ET.SubElement(main_track, "attnum", {"name": "width", "val": "12.0"})
    pits = ET.SubElement(main_track, "section", {"name": "Pits"})
    segs = [straight_segment("entry", 80.0)]
    pieces, pit_a_name, pit_b_name = integrate_pitlane.split_host_to_pit_segments(
        template=straight_segment("host", 400.0),
        host_len=400.0,
        pit_len=300.0,
        min_piece_len=8.0,
        names_used=set(),
        align="end",
    )
    segs.extend(pieces)
    segs.append(straight_segment("exit", 120.0))
    args = Namespace(
        pit_main_align="end",
        entry_taper_length=120.0,
        exit_taper_length=120.0,
        entry_taper_length_explicit=False,
        exit_taper_length_explicit=False,
        pit_side="right",
        entry_exit_side_width=14.0,
        pit_side_width=14.5,
        speed_limit=80.0,
        pit_slot_length=15.0,
        pit_main_length=300.0,
    )

    updated, report, pit_count = integrate_pitlane.apply_pit_lane_styles(main_track, pits, segs, args, pit_a_name, pit_b_name)

    assert updated[0].get("name") == pit_b_name
    assert pit_count == 20
    assert integrate_pitlane.get_attstr(pits, "type") == "track side"
    assert integrate_pitlane.get_attstr(pits, "entry") == "pit_host_pre"
    assert integrate_pitlane.get_attstr(pits, "start") == pit_a_name
    assert integrate_pitlane.get_attstr(pits, "end") == pit_b_name
    assert integrate_pitlane.get_attstr(pits, "exit") == "exit"
    assert report["pit_host_pre_length_m"] == pytest.approx(100.0)
    assert report["entry_taper_target_length_m"] == pytest.approx(100.0)
    assert report["entry_taper_auto_limited"]
    assert report["exit_taper_target_length_m"] == pytest.approx(120.0)
    assert report["exit_taper_selected_length_m"] == pytest.approx(120.0)
    pit_side = integrate_pitlane.get_child_section(next(seg for seg in updated if seg.get("name") == pit_a_name), "Right Side")
    assert pit_side is not None
    assert integrate_pitlane.get_attstr(pit_side, "surface") == "road1-pits"


def test_rewrite_track_segments_replaces_only_segment_children() -> None:
    track_segments = ET.Element("section", {"name": "Track Segments"})
    ET.SubElement(track_segments, "attstr", {"name": "meta", "val": "kept"})
    ET.SubElement(track_segments, "section", {"name": "old"})
    new_seg = straight_segment("new", 100.0)

    integrate_pitlane.rewrite_track_segments(track_segments, [new_seg])

    assert [child.tag for child in track_segments] == ["attstr", "section"]
    assert track_segments[1].get("name") == "new"


def test_choose_manual_host_strategy_rejects_mixed_host_options() -> None:
    segs = [straight_segment("main", 400.0)]

    try:
        integrate_pitlane.choose_manual_host_strategy(
            segs,
            host_segment="main",
            host_start_segment="main",
            host_end_segment="main",
            pit_len=300.0,
            mode_override="auto",
        )
    except SystemExit as exc:
        assert "either --host-segment" in str(exc)
    else:
        raise AssertionError("Expected SystemExit")


def test_choose_manual_host_strategy_rejects_partial_chain_and_bad_straighten() -> None:
    segs = [straight_segment("main", 400.0), straight_segment("tail", 120.0)]

    with pytest.raises(SystemExit, match="requires both --host-start-segment"):
        integrate_pitlane.choose_manual_host_strategy(
            segs,
            host_segment="",
            host_start_segment="main",
            host_end_segment="",
            pit_len=300.0,
            mode_override="auto",
        )
    with pytest.raises(SystemExit, match="straighten requires --host-start-segment"):
        integrate_pitlane.choose_manual_host_strategy(
            segs,
            host_segment="main",
            host_start_segment="",
            host_end_segment="",
            pit_len=300.0,
            mode_override="straighten",
        )


def test_host_strategy_error_and_fallback_modes_are_characterized() -> None:
    tight_turn = turn_segment("tight", "lft", 50.0, 10.0)
    short_straight = straight_segment("short", 80.0)

    with pytest.raises(SystemExit, match="host-mode 'exact'"):
        integrate_pitlane.choose_host_strategy([short_straight], 120.0, 0.0025, 2.0, 4.0, True, 8, 450.0, "exact")
    with pytest.raises(SystemExit, match="host-mode 'almost'"):
        integrate_pitlane.choose_host_strategy([tight_turn], 120.0, 0.0025, 2.0, 4.0, True, 8, 450.0, "almost")
    with pytest.raises(SystemExit, match="host-mode 'lengthen'"):
        integrate_pitlane.choose_host_strategy([tight_turn], 120.0, 0.0025, 2.0, 4.0, True, 8, 450.0, "lengthen")

    lengthen = integrate_pitlane.choose_host_strategy([tight_turn, short_straight], 120.0, 0.0025, 2.0, 4.0, True, 8, 450.0, "auto")
    assert lengthen == {"mode": "lengthen", "i0": 1, "i1": 1, "length": 80.0}

    inject = integrate_pitlane.choose_host_strategy([tight_turn], 120.0, 0.0025, 2.0, 4.0, True, 8, 450.0, "inject")
    assert inject == {"mode": "inject", "i0": 0, "i1": 0, "length": 0.0}


def test_almost_replacement_splits_original_turn_for_low_pose_error() -> None:
    chain = [
        straight_segment("pre", 204.0),
        turn_segment("shallow", "rgt", 3008.0, 0.4),
        straight_segment("post", 126.0),
    ]

    _, _, _, meta = integrate_pitlane.make_pose_preserving_almost_replacement(
        chain=chain,
        pit_len=300.0,
        min_piece_len=8.0,
        names_used=set(),
    )

    assert meta["method"] == "split-original-turn"
    assert meta["pose_error"]["xy_m"] < 0.002
    assert meta["pose_error"]["ang_deg"] < 0.0001


def test_almost_replacement_does_not_confuse_host_straight_for_pit_main() -> None:
    chain = [
        straight_segment("pre", 150.0),
        turn_segment("shallow", "lft", 3000.0, 0.25),
        straight_segment("post", 300.0),
    ]

    pieces, pit_a_name, pit_b_name, meta = integrate_pitlane.make_pose_preserving_almost_replacement(
        chain=chain,
        pit_len=300.0,
        min_piece_len=8.0,
        names_used=set(),
    )

    names = [p.get("name") for p in pieces]
    assert meta["method"] == "split-original-turn"
    assert names.index(pit_b_name) == names.index(pit_a_name) + 1
    assert names.index(pit_a_name) > 0


def test_almost_replacement_uses_synthetic_model_for_straight_chain() -> None:
    chain = [straight_segment("host", 360.0)]

    pieces, pit_a_name, pit_b_name, meta = integrate_pitlane.make_pose_preserving_almost_replacement(
        chain=chain,
        pit_len=300.0,
        min_piece_len=8.0,
        names_used=set(),
    )

    names = [piece.get("name") for piece in pieces]
    assert meta["method"] == "synthetic-correction-turns"
    assert names.index(pit_b_name) == names.index(pit_a_name) + 1
    assert sum(integrate_pitlane.segment_length(piece) for piece in pieces) == pytest.approx(360.0)


def test_safety_gate_requires_absolute_final_closure() -> None:
    args = Namespace(
        max_delta_ang_deg_increase=0.01,
        max_delta_x_increase_m=1.0,
        max_delta_y_increase_m=1.0,
        max_final_delta_x_m=0.001,
        max_final_delta_y_m=0.001,
        max_final_delta_ang_deg=0.0001,
        max_length_drift_ratio=0.005,
    )
    before = {"trackgen": {"delta_x": 0.0, "delta_y": 0.0, "delta_ang_deg": 0.0, "length": 1000.0}}
    after = {"trackgen": {"delta_x": 0.05, "delta_y": 0.0005, "delta_ang_deg": 0.0, "length": 1000.0}}

    result = integrate_pitlane.safety_gate_eval(before, after, args)

    assert not result["checks"]["final_delta_x_ok"]
    assert not result["checks"]["all_ok"]


def test_safety_gate_evaluates_overlay_drift_limits() -> None:
    args = Namespace(
        max_delta_ang_deg_increase=0.01,
        max_delta_x_increase_m=1.0,
        max_delta_y_increase_m=1.0,
        max_final_delta_x_m=1.0,
        max_final_delta_y_m=1.0,
        max_final_delta_ang_deg=1.0,
        max_length_drift_ratio=0.005,
        max_rmse_increase_m=0.5,
        max_mean_dev_increase_m=0.25,
    )
    before = {
        "trackgen": {"delta_x": 0.0, "delta_y": 0.0, "delta_ang_deg": 0.0, "length": 1000.0},
        "overlay": {"rmse_deviation_m": 1.0, "mean_deviation_m": 0.5},
    }
    after = {
        "trackgen": {"delta_x": 0.0, "delta_y": 0.0, "delta_ang_deg": 0.0, "length": 1000.0},
        "overlay": {"rmse_deviation_m": 1.6, "mean_deviation_m": 0.7},
    }

    result = integrate_pitlane.safety_gate_eval(before, after, args)

    assert result["gates"]["rmse_increase"] == pytest.approx(0.6)
    assert result["gates"]["mean_deviation_increase"] == pytest.approx(0.2)
    assert not result["checks"]["rmse_increase_ok"]
    assert result["checks"]["mean_deviation_increase_ok"]
    assert not result["checks"]["all_ok"]


def test_run_enforced_safety_records_passed_gate(monkeypatch, tmp_path, capsys) -> None:
    track_xml = tmp_path / "unit.xml"
    track_xml.write_text("<before />", encoding="utf-8")
    metrics = [
        {"delta_x": 0.0, "delta_y": 0.0, "delta_ang_deg": 0.0, "length": 1000.0, "pits": 0},
        {"delta_x": 0.0, "delta_y": 0.0, "delta_ang_deg": 0.0, "length": 1000.0, "pits": 20},
    ]

    def fake_trackgen(runtime_dir, category, name):
        assert runtime_dir == tmp_path
        assert category == "road"
        assert name == "unit"
        return metrics.pop(0)

    monkeypatch.setattr(integrate_pitlane, "run_trackgen_z", fake_trackgen)
    report = {}

    before, after, safety, failed = integrate_pitlane.run_enforced_safety(
        track_xml,
        "<before />",
        "<after />",
        safety_args(tmp_path),
        report,
    )

    assert not metrics
    assert not failed
    assert track_xml.read_text(encoding="utf-8") == "<after />"
    assert before == report["safety"]["before"]
    assert after == report["safety"]["after"]
    assert safety == report["safety"]["evaluation"]
    assert report["safety"]["status"] == "passed"
    assert not report["safety"]["rolled_back"]
    assert "Safety gates passed" in capsys.readouterr().out


def test_run_enforced_safety_rolls_back_failed_gate(monkeypatch, tmp_path, capsys) -> None:
    track_xml = tmp_path / "unit.xml"
    track_xml.write_text("<before />", encoding="utf-8")
    metrics = [
        {"delta_x": 0.0, "delta_y": 0.0, "delta_ang_deg": 0.0, "length": 1000.0, "pits": 0},
        {"delta_x": 5.0, "delta_y": 0.0, "delta_ang_deg": 0.0, "length": 1000.0, "pits": 20},
    ]

    monkeypatch.setattr(integrate_pitlane, "run_trackgen_z", lambda _runtime_dir, _category, _name: metrics.pop(0))
    report = {}

    before, after, safety, failed = integrate_pitlane.run_enforced_safety(
        track_xml,
        "<before />",
        "<after />",
        safety_args(tmp_path),
        report,
    )

    assert not metrics
    assert failed
    assert track_xml.read_text(encoding="utf-8") == "<before />"
    assert before == report["safety"]["before"]
    assert after == report["safety"]["after"]
    assert safety == report["safety"]["evaluation"]
    assert report["safety"]["status"] == "failed"
    assert report["safety"]["reason"] == "Safety gates failed"
    assert report["safety"]["rolled_back"]
    assert "Safety gates failed; rolled back XML to baseline" in capsys.readouterr().out


def test_resolve_safety_runtime_context_uses_explicit_and_auto_values(tmp_path) -> None:
    explicit_runtime = tmp_path / "explicit-runtime"
    explicit_args = Namespace(runtime_dir=str(explicit_runtime), category="road", name="unit")

    assert integrate_pitlane.resolve_safety_runtime_context(tmp_path / "ignored.xml", explicit_args) == (explicit_runtime, "road", "unit")

    track_xml = tmp_path / "runtime" / "tracks" / "road" / "auto-unit" / "auto-unit.xml"
    track_xml.parent.mkdir(parents=True)
    auto_args = Namespace(runtime_dir="", category="custom-category", name="")

    runtime_dir, category, name = integrate_pitlane.resolve_safety_runtime_context(track_xml, auto_args)

    assert runtime_dir == tmp_path / "runtime"
    assert category == "custom-category"
    assert name == "auto-unit"


def test_write_optional_reports_writes_requested_json_files(tmp_path, capsys) -> None:
    report_path = tmp_path / "reports" / "pit.json"
    baseline_path = tmp_path / "reports" / "baseline.json"
    safety_path = tmp_path / "reports" / "safety.json"
    args = Namespace(report=str(report_path), baseline_report=str(baseline_path), safety_report=str(safety_path))
    report = {"pit": {"expected_pits": 20}}
    before = {"trackgen": {"delta_x": 0.0}}
    after = {"trackgen": {"delta_x": 0.1}}
    safety = {"checks": {"all_ok": False}}

    integrate_pitlane.write_optional_reports(args, report, before, after, safety)

    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == before
    assert json.loads(safety_path.read_text(encoding="utf-8")) == {"before": before, "after": after, "evaluation": safety}
    output = capsys.readouterr().out
    assert "Wrote report:" in output
    assert "Wrote baseline report:" in output
    assert "Wrote safety report:" in output


def test_build_initial_report_includes_optional_sections_and_backup(tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    raw = "<params />"
    pits = ET.Element("section", {"name": "Pits"})
    ET.SubElement(pits, "attstr", {"name": "type", "val": "none"})
    args = Namespace(no_pit_backup=False, dry_run=True)
    host = {"mode": "exact", "i0": 0, "i1": 0}
    manual_wrap = {"rotation_start_segment": "connector"}
    real_placement = {"status": "real-placement-ok"}

    report = integrate_pitlane.build_initial_report(track_xml, raw, pits, args, host, manual_wrap, real_placement)

    assert report["host_selection"] == host
    assert report["manual_wrap_rotation"] == manual_wrap
    assert report["real_placement"] == real_placement
    assert report["no_pit_backup"] == str(tmp_path / "source" / "unit-no-pits.xml")


def test_almost_pose_limits_reject_xy_error() -> None:
    args = Namespace(max_almost_pose_error_m=0.001, max_almost_pose_error_deg=0.0001)
    pose_meta = {"pose_error": {"xy_m": 0.465, "ang_deg": 0.0}}

    assert not integrate_pitlane.almost_pose_within_limits(pose_meta, args)
