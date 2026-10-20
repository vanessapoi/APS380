# /***************************************************************************
#
#     file                 : test_overlay.py
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

import json

import pytest

from torcs_track_tools.core.overlay import nearest_polyline_distance, parse_track_segments, torcs_points


def test_parse_track_segments_tolerates_default_surfaces_entity() -> None:
    xml = """
<params>
  &default-surfaces;
  <section name="Track Segments">
    <section name="straight">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="10"/>
    </section>
  </section>
</params>
""".strip()

    assert parse_track_segments(xml) == [{"name": "straight", "type": "str", "lg": 10.0}]


def test_torcs_points_samples_straight_length() -> None:
    points = torcs_points([{"name": "straight", "type": "str", "lg": 10.0}], step=3.0)

    assert points[-1]["x"] == pytest.approx(10.0)
    assert points[-1]["y"] == pytest.approx(0.0)
    assert points[-1]["s"] == pytest.approx(10.0)


def test_nearest_polyline_distance_can_use_closing_edge() -> None:
    poly = [
        {"x": 0.0, "y": 0.0},
        {"x": 10.0, "y": 0.0},
        {"x": 10.0, "y": 10.0},
        {"x": 0.0, "y": 10.0},
    ]
    point = {"x": -1.0, "y": 5.0}

    assert nearest_polyline_distance(point, poly, closed=False) > 5.0
    assert nearest_polyline_distance(point, poly, closed=True) == pytest.approx(1.0)


def test_closed_overlay_cli_aligns_reversed_source_with_different_start(tmp_path, monkeypatch):
    from torcs_track_tools.cli import compare_overlay
    from torcs_track_tools.cli.close_loop_geometric import sample_closed_by_arc

    segments = [
        {"name": "a", "type": "str", "lg": 100.0},
        {"name": "b", "type": "lft", "radius": 20.0, "arc": 180.0},
        {"name": "c", "type": "str", "lg": 100.0},
        {"name": "d", "type": "lft", "radius": 20.0, "arc": 180.0},
    ]
    points, _ = sample_closed_by_arc(torcs_points(segments), 80)
    points = list(reversed(points[17:] + points[:17]))
    source = tmp_path / "centerline.json"
    source.write_text(json.dumps({"polyline": points}), encoding="utf-8")
    xml = tmp_path / "track.xml"
    sections = []
    for segment in segments:
        attributes = ''.join(
            f'<attstr name="{key}" val="{value}"/>' for key, value in segment.items() if key != "name"
        )
        sections.append(f'<section name="{segment["name"]}">{attributes}</section>')
    xml.write_text('<params><section name="Track Segments">' + ''.join(sections) + '</section></params>', encoding="utf-8")
    svg, report = tmp_path / "fit.svg", tmp_path / "fit.json"
    monkeypatch.setattr("sys.argv", [
        "torcs-compare-overlay", "--polyline", str(source), "--track-xml", str(xml),
        "--overlay", str(svg), "--report", str(report), "--samples", "80", "--align-closed",
    ])
    assert compare_overlay.main() == 0
    assert '<svg' in svg.read_text(encoding="utf-8")
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["reversed"] is True
    assert result["max_deviation"]["d"] < 0.5  # metres; permits polyline resampling error
