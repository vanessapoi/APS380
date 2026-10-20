# /***************************************************************************
#
#     file                 : test_place_curbs.py
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

import torcs_track_tools.cli.place_curbs as place_curbs


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


def has_attnum(section: ET.Element, name: str) -> bool:
    return any(child.tag == "attnum" and child.get("name") == name for child in section)


def attstr(section: ET.Element, name: str) -> str:
    for child in section:
        if child.tag == "attstr" and child.get("name") == name:
            return child.get("val", "")
    raise AssertionError(f"missing attstr: {name}")


def write_track(path, segments: str, pits: str = "") -> None:
    path.write_text(
        f"""
<params name="Unit Track">
  <section name="Main Track">
    <attnum name="width" unit="m" val="12.0"/>
    <section name="Left Border">
      <attnum name="width" unit="m" val="0.8"/>
      <attnum name="height" unit="m" val="0.04"/>
      <attstr name="style" val="curb"/>
      <attstr name="surface" val="curb-5cm-l"/>
    </section>
    <section name="Right Border">
      <attnum name="width" unit="m" val="0.8"/>
      <attnum name="height" unit="m" val="0.04"/>
      <attstr name="style" val="curb"/>
      <attstr name="surface" val="curb-5cm-r"/>
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


def straight(name: str, length: float = 50.0) -> str:
    return f"""
<section name="{name}">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="{length}"/>
</section>
"""


def straight_with_wall(name: str, length: float = 50.0) -> str:
    return f"""
<section name="{name}">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="{length}"/>
  <section name="Right Border">
    <attnum name="width" unit="m" val="0.5"/>
    <attnum name="height" unit="m" val="1.0"/>
    <attstr name="style" val="wall"/>
    <attstr name="surface" val="wall"/>
  </section>
</section>
"""


def turn(name: str, seg_type: str, radius: float, arc: float = 45.0) -> str:
    return f"""
<section name="{name}">
  <attstr name="type" val="{seg_type}"/>
  <attnum name="radius" unit="m" val="{radius}"/>
  <attnum name="arc" unit="deg" val="{arc}"/>
</section>
"""


def turn_with_right_side_taper(name: str, seg_type: str, radius: float, arc: float, start_width: float, end_width: float) -> str:
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


def left_turn_after_pit_reset(name: str, radius: float, arc: float = 45.0) -> str:
    return f"""
<section name="{name}">
  <attstr name="type" val="lft"/>
  <attnum name="radius" unit="m" val="{radius}"/>
  <attnum name="arc" unit="deg" val="{arc}"/>
  <section name="Right Border">
    <attnum name="width" unit="m" val="1.0"/>
    <attnum name="height" unit="m" val="0.04"/>
    <attstr name="style" val="plan"/>
    <attstr name="surface" val="b-road1-grass6"/>
  </section>
</section>
"""


def parse_track(path):
    return ET.fromstring(path.read_text(encoding="utf-8"))


def segment(root: ET.Element, name: str) -> ET.Element:
    for section in root.iter("section"):
        if section.get("name") == name:
            return section
    raise AssertionError(f"missing segment: {name}")


def track_segments(root: ET.Element) -> list[ET.Element]:
    return [child for child in child_section(child_section(root, "Main Track"), "Track Segments") if child.tag == "section"]


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-place-curbs", *args])
    return place_curbs.main()


def mock_outside_ranges(monkeypatch: pytest.MonkeyPatch, ranges: list[dict]) -> None:
    def fake_ranges(main_track, segs, border_states, protected_idxs, args):
        return ranges, {"sample_count": 0, "mocked": True}

    monkeypatch.setattr(place_curbs, "find_outside_curb_ranges", fake_ranges)


def test_place_curbs_flattens_defaults_and_places_inside_turn_curbs(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "curbs.json"
    write_track(track_xml, straight("before") + turn("left-apex", "lft", 90.0) + turn("right-apex", "rgt", 180.0) + turn("wide", "lft", 400.0))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--placement", "inside", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    main_track = child_section(root, "Main Track")
    for border_name in ("Left Border", "Right Border"):
        border = child_section(main_track, border_name)
        assert attnum(border, "width") == 1.0
        assert not has_attnum(border, "height")
        assert attstr(border, "style") == "plan"
        assert attstr(border, "surface") == "b-road1-grass6"

    left_curb = child_section(segment(root, "left-apex"), "Left Border")
    right_curb = child_section(segment(root, "right-apex"), "Right Border")
    assert attstr(left_curb, "style") == "curb"
    assert attstr(left_curb, "surface") == "curb-5cm-l"
    assert attnum(left_curb, "width") == 1.0
    assert attnum(left_curb, "height") == 0.04
    assert attstr(right_curb, "style") == "curb"
    assert attstr(right_curb, "surface") == "curb-5cm-r"
    left_reset = child_section(segment(root, "right-apex"), "Left Border")
    right_reset = child_section(segment(root, "wide"), "Right Border")
    assert attstr(left_reset, "style") == "plan"
    assert attstr(left_reset, "surface") == "b-road1-grass6"
    assert not has_attnum(left_reset, "height")
    assert attstr(right_reset, "style") == "plan"
    assert attstr(right_reset, "surface") == "b-road1-grass6"
    assert not has_attnum(right_reset, "height")
    with pytest.raises(AssertionError):
        child_section(segment(root, "wide"), "Left Border")

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["placed_count"] == 2
    assert report["reset_count"] == 2
    assert [item["segment"] for item in report["placed_curbs"]] == ["left-apex", "right-apex"]
    assert [item["segment"] for item in report["curb_resets"]] == ["right-apex", "wide"]


def test_place_curbs_resets_only_after_same_side_curb_run(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "curbs.json"
    write_track(track_xml, turn("left-a", "lft", 120.0) + turn("left-b", "lft", 140.0) + straight("after"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--placement", "inside", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    left_a = child_section(segment(root, "left-a"), "Left Border")
    left_b = child_section(segment(root, "left-b"), "Left Border")
    after = child_section(segment(root, "after"), "Left Border")
    assert attstr(left_a, "style") == "curb"
    assert attstr(left_b, "style") == "curb"
    assert attstr(after, "style") == "plan"
    assert attstr(after, "surface") == "b-road1-grass6"
    assert not has_attnum(after, "height")

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["placed_count"] == 2
    assert report["reset_count"] == 1
    assert report["curb_resets"][0]["segment"] == "after"


def test_place_curbs_does_not_replace_wall_when_resetting_carryover(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "curbs.json"
    write_track(track_xml, turn("right-apex", "rgt", 120.0) + straight_with_wall("wall-after"))

    assert run_tool(monkeypatch, "--input", str(track_xml), "--placement", "inside", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    wall = child_section(segment(root, "wall-after"), "Right Border")
    assert attstr(wall, "style") == "wall"
    assert attstr(wall, "surface") == "wall"
    assert attnum(wall, "width") == 0.5

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["placed_count"] == 1
    assert report["reset_count"] == 1
    assert report["curb_resets"][0]["skipped"] == "wall"


def test_place_curbs_does_not_reset_carryover_into_protected_pit_entry(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "curbs.json"
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
    pit_entry = """
<section name="pit entry">
  <attstr name="type" val="str"/>
  <attnum name="lg" unit="m" val="80"/>
  <section name="Right Border">
    <attnum name="width" unit="m" val="1.0"/>
    <attstr name="style" val="plan"/>
    <attstr name="surface" val="b-road1-l2p"/>
  </section>
</section>
"""
    write_track(
        track_xml,
        turn("right-apex", "rgt", 120.0) + pit_entry + straight_with_wall("pit_main_a") + straight_with_wall("pit_main_b") + turn("pit exit", "rgt", 90.0),
        pits=pits,
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--placement", "inside", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    pit_entry_border = child_section(segment(root, "pit entry"), "Right Border")
    assert attstr(pit_entry_border, "style") == "plan"
    assert attstr(pit_entry_border, "surface") == "b-road1-l2p"
    assert attnum(pit_entry_border, "width") == 1.0

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["placed_count"] == 1
    assert report["reset_count"] == 1
    assert report["curb_resets"][0]["segment"] == "pit entry"
    assert report["curb_resets"][0]["skipped"] == "protected"


def test_place_curbs_skips_pit_corridor_and_preserves_wall(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "curbs.json"
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
        turn("pit entry", "rgt", 90.0)
        + straight_with_wall("pit_main_a")
        + straight_with_wall("pit_main_b")
        + turn("pit exit", "rgt", 90.0)
        + left_turn_after_pit_reset("outside", 90.0),
        pits=pits,
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--placement", "inside", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    with pytest.raises(AssertionError):
        child_section(segment(root, "pit entry"), "Right Border")
    pit_entry_left = child_section(segment(root, "pit entry"), "Left Border")
    assert attstr(pit_entry_left, "style") == "plan"
    assert attstr(pit_entry_left, "surface") == "b-road1-grass6"
    wall = child_section(segment(root, "pit_main_a"), "Right Border")
    assert attstr(wall, "style") == "wall"
    assert attnum(wall, "width") == 0.5
    assert attstr(child_section(segment(root, "outside"), "Left Border"), "style") == "curb"

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["placed_count"] == 1
    assert [item["segment"] for item in report["skipped_protected"]] == ["pit entry", "pit exit"]


def test_outside_curbs_split_straight_to_requested_range(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "curbs.json"
    write_track(track_xml, straight("approach", 100.0) + straight("after", 40.0))
    mock_outside_ranges(
        monkeypatch,
        [{"border": "Right Border", "start": 30.0, "end": 70.0, "length": 40.0, "sample_count": 4}],
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--placement", "outside", "--outside-min-run-m", "1", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    names = [seg.get("name") for seg in track_segments(root)]
    assert names == ["approach-pre", "approach-curb", "approach-post", "after"]
    assert attnum(segment(root, "approach-pre"), "lg") == 30.0
    assert attnum(segment(root, "approach-curb"), "lg") == 40.0
    assert attnum(segment(root, "approach-post"), "lg") == 30.0
    curb = child_section(segment(root, "approach-curb"), "Right Border")
    reset = child_section(segment(root, "approach-post"), "Right Border")
    assert attstr(curb, "style") == "curb"
    assert attstr(curb, "surface") == "curb-5cm-r"
    assert attstr(reset, "style") == "plan"
    assert not has_attnum(reset, "height")

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["inside_placed_count"] == 0
    assert report["outside_placed_count"] == 1
    assert report["outside_splits"][0]["target_segment"] == "approach-curb"


def test_outside_curbs_split_turn_preserves_side_width_taper(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "curbs.json"
    write_track(track_xml, turn_with_right_side_taper("approach", "lft", 100.0, 57.2957795131, 7.0, 3.0) + straight("after", 40.0))
    mock_outside_ranges(
        monkeypatch,
        [{"border": "Right Border", "start": 30.0, "end": 70.0, "length": 40.0, "sample_count": 4}],
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--placement", "outside", "--outside-min-run-m", "1", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    names = [seg.get("name") for seg in track_segments(root)]
    assert names == ["approach-pre", "approach-curb", "approach-post", "after"]
    pre_side = child_section(segment(root, "approach-pre"), "Right Side")
    curb_side = child_section(segment(root, "approach-curb"), "Right Side")
    post_side = child_section(segment(root, "approach-post"), "Right Side")
    assert attnum(pre_side, "start width") == pytest.approx(7.0)
    assert attnum(pre_side, "end width") == pytest.approx(5.8)
    assert attnum(curb_side, "start width") == pytest.approx(5.8)
    assert attnum(curb_side, "end width") == pytest.approx(4.2)
    assert attnum(post_side, "start width") == pytest.approx(4.2)
    assert attnum(post_side, "end width") == pytest.approx(3.0)


def test_outside_curbs_snap_to_almost_matching_segment(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "curbs.json"
    write_track(track_xml, straight("before", 100.0) + straight("target", 45.0) + straight("after", 50.0))
    mock_outside_ranges(
        monkeypatch,
        [{"border": "Right Border", "start": 103.0, "end": 142.0, "length": 39.0, "sample_count": 4}],
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--placement", "outside", "--outside-min-run-m", "1", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    assert [seg.get("name") for seg in track_segments(root)] == ["before", "target", "after"]
    curb = child_section(segment(root, "target"), "Right Border")
    reset = child_section(segment(root, "after"), "Right Border")
    assert attstr(curb, "style") == "curb"
    assert attnum(segment(root, "target"), "lg") == 45.0
    assert attstr(reset, "style") == "plan"

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["outside_splits"] == []
    assert report["placed_outside_curbs"][0]["snap"] == "fit-ratio"


def test_outside_curbs_skip_variable_radius_segments(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "curbs.json"
    variable_turn = """
<section name="variable">
  <attstr name="type" val="lft"/>
  <attnum name="radius" unit="m" val="80"/>
  <attnum name="end radius" unit="m" val="120"/>
  <attnum name="arc" unit="deg" val="45"/>
</section>
"""
    write_track(track_xml, variable_turn + straight("after"))
    mock_outside_ranges(
        monkeypatch,
        [{"border": "Right Border", "start": 10.0, "end": 40.0, "length": 30.0, "sample_count": 4}],
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--placement", "outside", "--outside-min-run-m", "1", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    with pytest.raises(AssertionError):
        child_section(segment(root, "variable"), "Right Border")
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["outside_placed_count"] == 0
    assert report["outside_skipped"][0]["reason"] == "variable-radius"


def test_outside_curbs_skip_protected_pit_segments(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "curbs.json"
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
    write_track(track_xml, straight("pit entry", 80.0) + straight("pit_main_a") + straight("pit_main_b") + straight("pit exit"), pits=pits)
    mock_outside_ranges(
        monkeypatch,
        [{"border": "Right Border", "start": 10.0, "end": 50.0, "length": 40.0, "sample_count": 4}],
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--placement", "outside", "--outside-min-run-m", "1", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    with pytest.raises(AssertionError):
        child_section(segment(root, "pit entry"), "Right Border")
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["outside_placed_count"] == 0
    assert report["outside_skipped"][0]["reason"] == "protected"


def test_merge_wrapped_outside_ranges_combines_start_and_end_runs() -> None:
    ranges = [
        {"border": "Right Border", "start": 0.0, "end": 10.0, "length": 10.0, "sample_count": 2, "peak_strength": 0.5},
        {"border": "Right Border", "start": 95.0, "end": 100.0, "length": 5.0, "sample_count": 1, "peak_strength": 0.8},
    ]

    merged = place_curbs.merge_wrapped_outside_ranges(ranges, total=100.0, merge_gap=1.0, max_run_m=20.0)

    assert len(merged) == 1
    assert merged[0]["start"] == 95.0
    assert merged[0]["end"] == 10.0
    assert merged[0]["length"] == 15.0
    assert merged[0]["wrapped"]
    assert merged[0]["peak_strength"] == 0.8


def test_linear_range_parts_splits_wrapped_range() -> None:
    assert place_curbs.linear_range_parts(180.0, 40.0, 220.0) == [(180.0, 220.0), (0.0, 40.0)]


def test_outside_curbs_apply_wrapped_range_across_xml_boundary(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit-track.xml"
    report_json = tmp_path / "curbs.json"
    write_track(track_xml, straight("tail", 60.0) + straight("middle", 100.0) + straight("head", 60.0))
    mock_outside_ranges(
        monkeypatch,
        [{"border": "Right Border", "start": 180.0, "end": 40.0, "length": 80.0, "sample_count": 6, "wrapped": True}],
    )

    assert run_tool(monkeypatch, "--input", str(track_xml), "--placement", "outside", "--outside-min-run-m", "1", "--report", str(report_json)) == 0

    root = parse_track(track_xml)
    names = [seg.get("name") for seg in track_segments(root)]
    assert names == ["tail", "tail-post", "middle", "head-pre", "head-curb"]
    assert attnum(segment(root, "tail"), "lg") == 40.0
    assert attnum(segment(root, "tail-post"), "lg") == 20.0
    assert attnum(segment(root, "head-pre"), "lg") == 20.0
    assert attnum(segment(root, "head-curb"), "lg") == 40.0
    assert attstr(child_section(segment(root, "tail"), "Right Border"), "style") == "curb"
    assert attstr(child_section(segment(root, "head-curb"), "Right Border"), "style") == "curb"
    assert attstr(child_section(segment(root, "tail-post"), "Right Border"), "style") == "plan"

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["outside_placed_count"] == 2
    assert [item["segment"] for item in report["placed_outside_curbs"]] == ["tail", "head-curb"]
    assert len(report["outside_splits"]) == 2
    assert [item["segment"] for item in report["curb_resets"]] == ["tail-post"]
