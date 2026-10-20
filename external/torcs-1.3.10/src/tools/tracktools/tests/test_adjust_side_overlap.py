# /***************************************************************************
#
#     file                 : test_adjust_side_overlap.py
#     created              : 06 May 2026
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

import torcs_track_tools.cli.adjust_side_overlap as adjust_side_overlap


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
    <attnum name="width" unit="m" val="10.0"/>
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


def straight(name: str, length: float = 100.0) -> str:
    return f"""
<section name="{name}">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="{length}"/>
</section>
"""


def turn(name: str, seg_type: str, radius: float, arc: float = 180.0) -> str:
    return f"""
<section name="{name}">
  <attstr name="type" val="{seg_type}"/>
  <attnum name="radius" unit="m" val="{radius}"/>
  <attnum name="arc" unit="deg" val="{arc}"/>
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
    monkeypatch.setattr("sys.argv", ["torcs-adjust-side-overlap", *args])
    return adjust_side_overlap.main()


def test_dry_run_reports_no_overlap_for_wide_parallel_straights(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    write_track(track_xml, straight("lower") + turn("connector", "lft", 30.0) + straight("upper"))
    original = track_xml.read_text(encoding="utf-8")

    assert run_tool(monkeypatch, "--input", str(track_xml), "--dry-run", "--report", str(report_json)) == 0

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["proposal_count"] == 0
    assert track_xml.read_text(encoding="utf-8") == original


def test_non_dry_no_overlap_succeeds_for_wide_parallel_straights(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    write_track(track_xml, straight("lower") + turn("connector", "lft", 30.0) + straight("upper"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--report", str(report_json)) == 0

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["status"] == "ok"
    assert report["final_overlap_count"] == 0


def test_overlapping_parallel_straights_reduce_facing_sides_and_restore_gap(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    write_track(track_xml, straight("lower") + turn("connector", "lft", 10.0) + straight("upper"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--report", str(report_json), "--taper-length", "20") == 0

    root = parse_track(track_xml)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    lower_left = child_section(segment(root, "lower"), "Left Side")
    upper_left = child_section(segment(root, "upper"), "Left Side")
    assert report["overlap_count"] > 0
    assert report["proposal_count"] > 0
    assert report["final_min_gap"] >= 1.9
    assert attnum(lower_left, "start width") < 7.0
    assert attnum(lower_left, "end width") < 7.0
    assert attnum(upper_left, "start width") < 7.0
    assert attnum(upper_left, "end width") < 7.0


def test_unresolved_overlap_returns_failure(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    write_track(track_xml, straight("lower") + turn("connector", "lft", 10.0) + straight("upper"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--report", str(report_json), "--min-side-width", "7.0") == 1

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["final_overlap_count"] > 0


def test_pit_protected_overlap_side_is_not_modified(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "report.json"
    pits = """
<section name="Pits">
  <attstr name="type" val="track side"/>
  <attstr name="side" val="left"/>
  <attstr name="entry" val="lower"/>
  <attstr name="start" val="lower"/>
  <attstr name="end" val="lower"/>
  <attstr name="exit" val="lower"/>
</section>
"""
    write_track(track_xml, straight("lower") + turn("connector", "lft", 10.0) + straight("upper"), pits=pits)

    assert run_tool(monkeypatch, "--input", str(track_xml), "--report", str(report_json), "--taper-length", "20") == 1

    root = parse_track(track_xml)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["final_overlap_count"] > 0
    assert "lower" in report["protected_segments"]
    with pytest.raises(AssertionError):
        child_section(segment(root, "lower"), "Left Side")
    assert child_section(segment(root, "upper"), "Left Side") is not None


def test_output_preserves_prolog_and_default_surfaces_entity(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    output_xml = tmp_path / "out.xml"
    write_track(track_xml, straight("lower") + turn("connector", "lft", 10.0) + straight("upper"), with_entity=True)

    assert run_tool(monkeypatch, "--input", str(track_xml), "--output", str(output_xml)) == 0

    text = output_xml.read_text(encoding="utf-8")
    assert "<!-- generated test header -->" in text
    assert "<!ENTITY default-surfaces" in text
    assert "&default-surfaces;" in text
