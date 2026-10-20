# /***************************************************************************
#
#     file                 : test_prepare_loop_polyline.py
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

import json

import pytest

import torcs_track_tools.cli.prepare_loop_polyline as prepare_loop_polyline
from torcs_track_tools.core.polyline import from_xy_tuple, to_xy_tuples


def test_prepare_loop_removes_duplicate_endpoint_without_repair(monkeypatch, tmp_path) -> None:
    input_json = tmp_path / "centerline-osm.json"
    output_json = tmp_path / "centerline-prepared.json"
    report_json = tmp_path / "seam-report.json"
    overlay_svg = tmp_path / "seam-overlay.svg"
    points = [
        {"x": 0.0, "y": 0.0},
        {"x": 10.0, "y": 0.0},
        {"x": 20.0, "y": 0.0},
        {"x": 30.0, "y": 0.0},
        {"x": 40.0, "y": 0.0},
        {"x": 50.0, "y": 0.0},
        {"x": 60.0, "y": 0.0},
        {"x": 70.0, "y": 0.0},
        {"x": 0.0, "y": 0.0},
    ]
    input_json.write_text(json.dumps({"schema": 2, "polyline": points}), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-prepare-loop-polyline",
            "--input",
            str(input_json),
            "--output",
            str(output_json),
            "--report",
            str(report_json),
            "--overlay",
            str(overlay_svg),
            "--repair-heading-threshold",
            "999",
            "--repair-gap-threshold",
            "999",
        ],
    )

    assert prepare_loop_polyline.main() == 0

    out = json.loads(output_json.read_text(encoding="utf-8"))
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert out["schema"] == 3
    assert out["source_preparation"]["method"] == "identity-duplicate-trim"
    assert out["source_preparation"]["duplicate_end_removed"]
    assert not out["source_preparation"]["repair_applied"]
    assert out["polyline"] == points[:-1]
    assert report["raw_point_count"] == len(points)
    assert report["prepared_point_count"] == len(points) - 1
    assert overlay_svg.exists()


def test_prepare_loop_rejects_too_short_polylines(monkeypatch, tmp_path) -> None:
    input_json = tmp_path / "centerline-osm.json"
    output_json = tmp_path / "centerline-prepared.json"
    input_json.write_text(json.dumps({"polyline": [{"x": float(i), "y": 0.0} for i in range(7)]}), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-prepare-loop-polyline",
            "--input",
            str(input_json),
            "--output",
            str(output_json),
        ],
    )

    try:
        prepare_loop_polyline.main()
    except SystemExit as exc:
        assert str(exc) == "Polyline too short for seam preparation"
    else:
        raise AssertionError("expected SystemExit")


def test_from_xy_uses_coordinate_reference_separate_from_metadata() -> None:
    coord_ref = {"lat": 47.0, "lon": 8.0, "way_name": "origin"}
    meta_ref = {"lat": 47.5, "lon": 8.5, "way_id": 42, "way_name": "seam"}
    xy = (123.0, -45.0)

    point = from_xy_tuple(xy, coord_ref, meta_ref)
    converted = to_xy_tuples([coord_ref, point], coord_ref)[1]

    assert converted[0] == pytest.approx(xy[0])
    assert converted[1] == pytest.approx(xy[1])
    assert point["way_id"] == 42
    assert point["way_name"] == "seam"


def test_seam_repair_must_reduce_heading_substantially_if_still_above_threshold() -> None:
    assert prepare_loop_polyline.seam_repair_is_useful(16.0, 6.8, 5.0)
    assert prepare_loop_polyline.seam_repair_is_useful(8.0, 4.9, 5.0)
    assert not prepare_loop_polyline.seam_repair_is_useful(9.0, 8.0, 5.0)
