# /***************************************************************************
#
#     file                 : test_adjust_side_clearance.py
#     created              : 03 May 2026
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

import pytest

import torcs_track_tools.cli.adjust_side_clearance as adjust_side_clearance


def child_section(parent: ET.Element, name: str) -> ET.Element:
    for child in parent:
        if child.tag == "section" and child.get("name") == name:
            return child
    raise AssertionError(f"missing section: {name}")


def attnum(section: ET.Element, name: str) -> float:
    for child in section:
        if child.tag == "attnum" and child.get("name") == name:
            return float(child.get("val", "0"))
    raise AssertionError(f"missing attnum: {name}")


def write_track(path, segments: str, with_entity: bool = False, pits: str = "") -> None:
    prefix = ""
    surfaces = ""
    if with_entity:
        prefix = """<?xml version="1.0" encoding="UTF-8"?>
<!-- generated test header -->
<!DOCTYPE params SYSTEM "../../../src/libs/tgf/params.dtd" [
<!ENTITY default-surfaces SYSTEM "../../../data/tracks/surfaces.xml">
]>
"""
        surfaces = "&default-surfaces;"
    path.write_text(
        prefix
        + f"""
<params name="Unit Track">
  <section name="Surfaces">
    {surfaces}
  </section>
  <section name="Main Track">
    <attnum name="width" unit="m" val="12.0"/>
    <section name="Left Border">
      <attnum name="width" unit="m" val="1.0"/>
    </section>
    <section name="Right Border">
      <attnum name="width" unit="m" val="1.0"/>
    </section>
    <section name="Left Side">
      <attnum name="width" unit="m" val="7.0"/>
    </section>
    <section name="Right Side">
      <attnum name="width" unit="m" val="7.0"/>
    </section>
    {pits}
    <section name="Track Segments">
      {segments}
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )


def straight(name: str, length: float = 20.0) -> str:
    return f"""
<section name="{name}">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="{length}"/>
</section>
"""


def turn(name: str, seg_type: str, radius: float, arc: float = 45.0, end_radius: float | None = None) -> str:
    end_radius_att = "" if end_radius is None else f'<attnum name="end radius" unit="m" val="{end_radius}"/>'
    return f"""
<section name="{name}">
  <attstr name="type" val="{seg_type}"/>
  <attnum name="radius" unit="m" val="{radius}"/>
  {end_radius_att}
  <attnum name="arc" unit="deg" val="{arc}"/>
</section>
"""


def turn_with_right_side(name: str, seg_type: str, radius: float, start_width: float, end_width: float, arc: float = 45.0) -> str:
    return f"""
<section name="{name}">
  <attstr name="type" val="{seg_type}"/>
  <attnum name="radius" unit="m" val="{radius}"/>
  <attnum name="arc" unit="deg" val="{arc}"/>
  <section name="Right Side">
    <attnum name="start width" unit="m" val="{start_width}"/>
    <attnum name="end width" unit="m" val="{end_width}"/>
  </section>
</section>
"""


def straight_with_right_side(name: str, length: float, start_width: float, end_width: float) -> str:
    return f"""
<section name="{name}">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="{length}"/>
  <section name="Right Side">
    <attnum name="start width" unit="m" val="{start_width}"/>
    <attnum name="end width" unit="m" val="{end_width}"/>
  </section>
</section>
"""


def parse_track(path):
    raw = path.read_text(encoding="utf-8").replace("&default-surfaces;", "<default_surfaces/>")
    return ET.fromstring(raw)


def segment(root: ET.Element, name: str) -> ET.Element:
    for section in root.iter("section"):
        if section.get("name") == name:
            return section
    raise AssertionError(f"missing segment: {name}")


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-adjust-side-clearance", *args])
    return adjust_side_clearance.main()


def test_dry_run_reports_safe_track_without_writing(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    write_track(track_xml, straight("before") + turn("safe", "lft", 30.0) + straight("after"))
    original = track_xml.read_text(encoding="utf-8")

    assert run_tool(monkeypatch, "--input", str(track_xml), "--dry-run", "--report", str(report_json)) == 0

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["anomaly_count"] == 0
    assert track_xml.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("extra_width,expected_count", [(0.0, 0), (0.000001, 1)])
def test_decimal_clearance_boundary_ignores_only_roundoff(monkeypatch, tmp_path, extra_width, expected_count):
    xml, report = tmp_path/"track.xml", tmp_path/"report.json"
    width = 4.838+extra_width
    write_track(xml, turn_with_right_side("boundary", "rgt", 12.338, width, width))
    original = xml.read_bytes()
    assert run_tool(monkeypatch, "--input", str(xml), "--dry-run", "--report", str(report)) == 0
    assert json.loads(report.read_text())["anomaly_count"] == expected_count
    assert xml.read_bytes() == original


def test_left_turn_reduces_only_left_side_and_tapers_neighbors(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    write_track(track_xml, straight("before") + turn("tight", "lft", 10.0) + straight("after"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--clearance-margin", "0.5", "--taper-length", "20") == 0

    root = parse_track(track_xml)
    before_left = child_section(segment(root, "before"), "Left Side")
    tight_left = child_section(segment(root, "tight"), "Left Side")
    after_left = child_section(segment(root, "after"), "Left Side")

    assert attnum(before_left, "start width") == 7.0
    assert attnum(before_left, "end width") == 2.5
    assert attnum(tight_left, "start width") == 2.5
    assert attnum(tight_left, "end width") == 2.5
    assert attnum(after_left, "start width") == 2.5
    assert attnum(after_left, "end width") == 7.0
    with pytest.raises(AssertionError):
        child_section(segment(root, "tight"), "Right Side")


def test_right_turn_reduces_only_right_side(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    write_track(track_xml, straight("before") + turn("tight", "rgt", 12.0) + straight("after"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--taper-length", "10") == 0

    root = parse_track(track_xml)
    tight_right = child_section(segment(root, "tight"), "Right Side")
    assert attnum(tight_right, "start width") == 4.5
    assert attnum(tight_right, "end width") == 4.5
    with pytest.raises(AssertionError):
        child_section(segment(root, "tight"), "Left Side")


def test_min_side_width_clamps_unresolved_case(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    write_track(track_xml, straight("before") + turn("hairpin", "lft", 6.5) + straight("after"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--min-side-width", "0.5", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    hairpin_left = child_section(segment(root, "hairpin"), "Left Side")
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert attnum(hairpin_left, "start width") == 0.5
    assert report["anomalies"][0]["unresolved_deficit"] > 0.0


def test_variable_radius_turn_uses_smaller_end_radius(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    write_track(track_xml, straight("before") + turn("tight-end", "lft", 50.0, end_radius=10.0) + straight("after"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["anomaly_count"] == 1
    assert report["anomalies"][0]["start_radius"] == 50.0
    assert report["anomalies"][0]["end_radius"] == 10.0
    assert attnum(child_section(segment(root, "tight-end"), "Left Side"), "start width") == 2.5


def test_per_segment_border_width_is_used_for_clearance(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    wide_border_turn = """
<section name="wide-border-tight">
  <attstr name="type" val="lft"/>
  <attnum name="radius" unit="m" val="14.8"/>
  <attnum name="arc" unit="deg" val="45"/>
  <section name="Left Border">
    <attnum name="width" unit="m" val="2.0"/>
  </section>
</section>
"""
    write_track(track_xml, straight("before") + wide_border_turn + straight("after"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["anomaly_count"] == 1
    assert report["anomalies"][0]["border_width"] == 2.0
    assert attnum(child_section(segment(root, "wide-border-tight"), "Left Side"), "start width") == 6.3


def test_adjacent_anomalies_are_merged_to_single_constant_run(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    write_track(track_xml, straight("before") + turn("tight-a", "lft", 12.0) + turn("tight-b", "lft", 10.0) + straight("after"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert len(report["runs"]) == 1
    assert report["runs"][0]["segments"] == ["tight-a", "tight-b"]
    assert attnum(child_section(segment(root, "tight-a"), "Left Side"), "start width") == 2.5
    assert attnum(child_section(segment(root, "tight-b"), "Left Side"), "end width") == 2.5


def test_same_side_anomalies_inside_taper_window_are_merged(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    write_track(track_xml, straight("before") + turn("tight-a", "lft", 12.0) + straight("between", 20.0) + turn("tight-b", "lft", 10.0) + straight("after"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--taper-length", "15", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert len(report["runs"]) == 1
    assert report["runs"][0]["segments"] == ["tight-a", "tight-b"]
    assert attnum(child_section(segment(root, "between"), "Left Side"), "start width") == 2.5
    assert attnum(child_section(segment(root, "between"), "Left Side"), "end width") == 2.5


def test_opposite_side_anomaly_does_not_block_taper(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    write_track(track_xml, straight("before") + turn("left-tight", "lft", 10.0) + turn("right-tight", "rgt", 12.0) + straight("after"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--side", "left", "--taper-length", "40") == 0

    root = parse_track(track_xml)
    right_left_side = child_section(segment(root, "right-tight"), "Left Side")
    assert attnum(right_left_side, "start width") == 2.5
    assert attnum(right_left_side, "end width") > 2.5


def test_same_side_anomalies_can_merge_across_start_line(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    write_track(track_xml, turn("first-tight", "lft", 10.0) + straight("middle", 100.0) + turn("last-tight", "lft", 12.0))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--taper-length", "15", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert len(report["runs"]) == 1
    assert report["runs"][0]["segments"] == ["last-tight", "first-tight"]
    assert attnum(child_section(segment(root, "last-tight"), "Left Side"), "start width") == 2.5
    assert attnum(child_section(segment(root, "first-tight"), "Left Side"), "end width") == 2.5
    assert report["applied_runs"][0]["overlap_taper_segments"] == ["middle"]
    assert attnum(child_section(segment(root, "middle"), "Left Side"), "start width") == 2.5
    assert attnum(child_section(segment(root, "middle"), "Left Side"), "end width") == 2.5


def test_pit_corridor_segments_are_protected(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    pits = """
<section name="Pits">
  <attstr name="type" val="track side"/>
  <attstr name="side" val="right"/>
  <attstr name="entry" val="pit entry"/>
  <attstr name="start" val="pit_main_a"/>
  <attstr name="end" val="pit_main_b"/>
  <attstr name="exit" val="pit exit"/>
</section>
"""
    write_track(
        track_xml,
        turn("pit entry", "rgt", 10.0)
        + straight("pit_main_a")
        + straight("pit_main_b")
        + turn("pit exit", "rgt", 10.0)
        + straight("gap", 60.0)
        + turn("outside", "rgt", 10.0)
        + straight("after"),
        pits=pits,
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--report", str(report_json), "--taper-length", "20") == 0

    root = parse_track(track_xml)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["anomaly_count"] == 1
    assert report["anomalies"][0]["segment"] == "outside"
    assert "pit entry" in report["protected_segments"]
    with pytest.raises(AssertionError):
        child_section(segment(root, "pit entry"), "Right Side")
    with pytest.raises(AssertionError):
        child_section(segment(root, "pit exit"), "Right Side")
    assert attnum(child_section(segment(root, "outside"), "Right Side"), "start width") == 2.5


def test_widened_pit_entry_turn_is_still_checked(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    pits = """
<section name="Pits">
  <attstr name="type" val="track side"/>
  <attstr name="side" val="right"/>
  <attstr name="entry" val="entry"/>
  <attstr name="start" val="pit_main_a"/>
  <attstr name="end" val="pit_main_b"/>
  <attstr name="exit" val="pit exit"/>
</section>
"""
    write_track(
        track_xml,
        turn_with_right_side("entry", "lft", 25.0, 7.0, 8.6)
        + turn_with_right_side("tight", "rgt", 13.223, 8.6, 9.0)
        + turn_with_right_side("tight-after", "rgt", 14.994, 9.0, 10.0)
        + turn_with_right_side("connector", "rgt", 99.0, 10.0, 11.0, arc=7.0)
        + straight_with_right_side("pit_host_pre", 40.0, 11.0, 14.0)
        + straight("pit_main_a")
        + straight("pit_main_b")
        + turn_with_right_side("pit exit", "rgt", 10.0, 7.0, 7.0),
        pits=pits,
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--report", str(report_json), "--taper-length", "20") == 0

    root = parse_track(track_xml)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["anomaly_count"] == 2
    assert [item["segment"] for item in report["anomalies"]] == ["tight", "tight-after"]
    assert all(item["protected"] for item in report["anomalies"])
    assert report["applied_runs"][0]["outgoing_taper_segments"] == ["connector"]

    tight_right = child_section(segment(root, "tight"), "Right Side")
    connector_right = child_section(segment(root, "connector"), "Right Side")
    pit_host_right = child_section(segment(root, "pit_host_pre"), "Right Side")
    assert attnum(tight_right, "start width") == pytest.approx(5.723)
    assert attnum(tight_right, "end width") == pytest.approx(5.723)
    assert attnum(connector_right, "start width") == pytest.approx(5.723)
    assert attnum(connector_right, "end width") == pytest.approx(11.0)
    assert attnum(pit_host_right, "start width") == 11.0
    assert attnum(pit_host_right, "end width") == 14.0


def test_hard_protected_anomaly_is_report_only(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    pits = """
<section name="Pits">
  <attstr name="type" val="track side"/>
  <attstr name="side" val="right"/>
  <attstr name="entry" val="before"/>
  <attstr name="start" val="pit_main_a"/>
  <attstr name="end" val="pit_main_b"/>
  <attstr name="exit" val="after"/>
</section>
"""
    write_track(
        track_xml,
        straight("before")
        + turn_with_right_side("pit_host_curve", "rgt", 13.0, 10.0, 10.0)
        + straight("pit_main_a")
        + straight("pit_main_b")
        + straight("after"),
        pits=pits,
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--report", str(report_json), "--taper-length", "20") == 0

    root = parse_track(track_xml)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["anomaly_count"] == 1
    assert report["anomalies"][0]["segment"] == "pit_host_curve"
    assert "pit_host_curve" in report["hard_protected_segments"]
    assert report["runs"] == []
    assert report["applied_runs"] == []
    assert attnum(child_section(segment(root, "pit_host_curve"), "Right Side"), "start width") == 10.0
    with pytest.raises(AssertionError):
        child_section(segment(root, "before"), "Right Side")
    with pytest.raises(AssertionError):
        child_section(segment(root, "after"), "Right Side")


def test_wrap_merge_is_per_side_when_other_side_has_anomalies(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    write_track(
        track_xml,
        turn("first-left-tight", "lft", 10.0)
        + straight("middle-a", 80.0)
        + turn("right-tight", "rgt", 12.0)
        + straight("middle-b", 80.0)
        + turn("last-left-tight", "lft", 12.0),
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--taper-length", "15", "--report", str(report_json)) == 0

    report = json.loads(report_json.read_text(encoding="utf-8"))
    left_runs = [run for run in report["runs"] if run["side"] == "left"]
    right_runs = [run for run in report["runs"] if run["side"] == "right"]
    assert len(left_runs) == 1
    assert len(right_runs) == 1
    assert left_runs[0]["segments"] == ["last-left-tight", "first-left-tight"]


def test_output_preserves_prolog_and_default_surfaces_entity(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    output_xml = tmp_path / "out.xml"
    write_track(track_xml, straight("before") + turn("tight", "lft", 10.0) + straight("after"), with_entity=True)

    assert run_tool(monkeypatch, "--input", str(track_xml), "--output", str(output_xml)) == 0

    text = output_xml.read_text(encoding="utf-8")
    assert "<!-- generated test header -->" in text
    assert "<!ENTITY default-surfaces" in text
    assert "&default-surfaces;" in text
