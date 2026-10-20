# /***************************************************************************
#
#     file                 : test_georeference_centerline.py
#     created              : 14 Aug 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

from __future__ import annotations

import json
import math

import pytest  # type: ignore[import-not-found]

import torcs_track_tools.cli.georeference_centerline as georeference_centerline
import torcs_track_tools.cli.import_elevation_raster as import_elevation_raster
from torcs_track_tools.core.georeference import (
    SimilarityTransform,
    control_distribution,
    fit_similarity,
    project_to_closed_loop,
    resample_closed,
    transform_point,
)


def write_centerline(path, points: list[tuple[float, float]], crs: str = "") -> None:  # noqa: ANN001
    source = {"type": "test"}
    if crs:
        source["crs"] = crs
    path.write_text(
        json.dumps({"source": source, "polyline": [{"x": x, "y": y, "way_name": f"point-{index}"} for index, (x, y) in enumerate(points)]}),
        encoding="utf-8",
    )


def write_controls(path, source: list[tuple[float, float]], reference: list[tuple[float, float]], crs: str = "EPSG:3857") -> None:  # noqa: ANN001
    path.write_text(
        json.dumps(
            {
                "reference_crs": crs,
                "reference": {"name": "Synthetic reference"},
                "control_points": [
                    {
                        "name": f"control-{index}",
                        "source": {"x": source_point[0], "y": source_point[1]},
                        "reference": {"x": reference_point[0], "y": reference_point[1]},
                    }
                    for index, (source_point, reference_point) in enumerate(zip(source, reference, strict=True))
                ],
            }
        ),
        encoding="utf-8",
    )


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-georeference-centerline", *args])
    return georeference_centerline.main()


def transformed(points: list[tuple[float, float]], fit: SimilarityTransform) -> list[tuple[float, float]]:
    return [transform_point(point, fit) for point in points]


def test_similarity_fit_recovers_rotation_scale_and_translation() -> None:
    source = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    expected = SimilarityTransform(math.radians(30.0), 1.25, 500.0, 700.0)

    actual = fit_similarity(source, transformed(source, expected), allow_scale=True)

    assert actual.rotation_rad == pytest.approx(expected.rotation_rad)
    assert actual.scale == pytest.approx(expected.scale)
    assert actual.offset_x == pytest.approx(expected.offset_x)
    assert actual.offset_y == pytest.approx(expected.offset_y)


def test_projection_resampling_and_distribution_characterize_loop() -> None:
    loop = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]

    projected, snap, segment, amount = project_to_closed_loop((40.0, 3.0), loop)
    samples = resample_closed(loop, 12)
    distribution = control_distribution([loop[0], loop[1], loop[2]], loop)

    assert projected == pytest.approx((40.0, 0.0))
    assert snap == pytest.approx(3.0)
    assert segment == 0
    assert amount == pytest.approx(0.4)
    assert len(samples) == 12
    assert distribution["span_ratio"] == pytest.approx(1.0)
    assert distribution["hull_area_ratio"] == pytest.approx(0.5)


def test_loop_validation_accepts_self_intersection_and_rejects_non_planar_crs() -> None:
    georeference_centerline.validate_loop([(0.0, 0.0), (100.0, 100.0), (0.0, 100.0), (100.0, 0.0)], "Figure eight")

    with pytest.raises(SystemExit, match="Output CRS must be geographic or projected"):
        georeference_centerline.validate_crs("EPSG:4978", "output CRS")
    with pytest.raises(SystemExit, match="x/y fields but CRS EPSG:4978 is not projected"):
        georeference_centerline.validate_coordinate_kind("projected", "EPSG:4978", "Reference")


def test_control_point_cli_writes_projected_output_report_and_overlay(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    controls_path = tmp_path / "controls.json"
    output_path = tmp_path / "georeferenced.json"
    report_path = tmp_path / "report.json"
    overlay_path = tmp_path / "overlay.svg"
    source = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    expected = SimilarityTransform(math.radians(90.0), 1.0, 1000.0, 2000.0)
    reference = transformed(source[:3], expected)
    write_centerline(source_path, source)
    write_controls(controls_path, source[:3], reference)

    assert (
        run_tool(
            monkeypatch,
            "--input",
            str(source_path),
            "--control-points",
            str(controls_path),
            "--fit-crs",
            "EPSG:3857",
            "--output-crs",
            "EPSG:3857",
            "--output",
            str(output_path),
            "--report",
            str(report_path),
            "--overlay",
            str(overlay_path),
        )
        == 0
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output["source"]["type"] == "georeferenced-centerline"
    assert output["georeferencing"]["status"] == "ok"
    assert output["polyline"][0]["x"] == pytest.approx(1000.0)
    assert output["polyline"][0]["y"] == pytest.approx(2000.0)
    assert output["polyline"][1]["x"] == pytest.approx(1000.0)
    assert output["polyline"][1]["y"] == pytest.approx(2100.0)
    assert output["polyline"][1]["source_x"] == pytest.approx(100.0)
    assert output["polyline"][1]["way_name"] == "point-1"
    assert report["metrics"]["rmse_m"] == pytest.approx(0.0, abs=1e-9)
    assert len(report["controls"]) == 3
    assert 'id="reference-centerline"' in overlay_path.read_text(encoding="utf-8")
    assert 'id="control-residuals"' in overlay_path.read_text(encoding="utf-8")


def test_similarity_control_fit_scales_unscaled_source(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    controls_path = tmp_path / "controls.json"
    output_path = tmp_path / "georeferenced.json"
    report_path = tmp_path / "report.json"
    overlay_path = tmp_path / "overlay.svg"
    source = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)]
    expected = SimilarityTransform(0.0, 20.0, 5000.0, 10000.0)
    write_centerline(source_path, source)
    write_controls(controls_path, source[:3], transformed(source[:3], expected))

    assert (
        run_tool(
            monkeypatch,
            "--input",
            str(source_path),
            "--control-points",
            str(controls_path),
            "--transform",
            "similarity",
            "--fit-crs",
            "EPSG:3857",
            "--output-crs",
            "EPSG:3857",
            "--output",
            str(output_path),
            "--report",
            str(report_path),
            "--overlay",
            str(overlay_path),
        )
        == 0
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["fit"]["scale"] == pytest.approx(20.0)
    assert report["output_length_m"] == pytest.approx(600.0)


def test_automatic_cli_handles_shifted_reversed_reference(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    reference_path = tmp_path / "reference.json"
    output_path = tmp_path / "georeferenced.json"
    report_path = tmp_path / "report.json"
    overlay_path = tmp_path / "overlay.svg"
    source = [(0.0, 0.0), (100.0, 0.0), (120.0, 40.0), (60.0, 80.0), (0.0, 50.0)]
    expected = SimilarityTransform(math.radians(-20.0), 1.0, 400000.0, 5600000.0)
    reference = transformed(source, expected)
    reference = list(reversed(reference[2:] + reference[:2]))
    write_centerline(source_path, source)
    write_centerline(reference_path, reference, "EPSG:32632")

    assert (
        run_tool(
            monkeypatch,
            "--input",
            str(source_path),
            "--reference",
            str(reference_path),
            "--allow-reference-reverse",
            "--samples",
            "120",
            "--fit-crs",
            "EPSG:32632",
            "--output-crs",
            "EPSG:32632",
            "--max-rmse-m",
            "1",
            "--output",
            str(output_path),
            "--report",
            str(report_path),
            "--overlay",
            str(overlay_path),
        )
        == 0
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "automatic-loop"
    assert report["metrics"]["reference_reversed"] is True
    assert "reference_shift_m" in report["metrics"]
    assert "source_shift_m" not in report["metrics"]
    assert report["metrics"]["paired_rmse_m"] < 0.2
    assert report["fit"]["rotation_deg"] == pytest.approx(-20.0, abs=0.2)


def test_control_cli_requires_three_distributed_points(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    controls_path = tmp_path / "controls.json"
    source = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    write_centerline(source_path, source)
    write_controls(controls_path, source[:2], [(1000.0, 2000.0), (1100.0, 2000.0)])

    with pytest.raises(SystemExit, match="At least three controls"):
        run_tool(
            monkeypatch,
            "--input",
            str(source_path),
            "--control-points",
            str(controls_path),
            "--fit-crs",
            "EPSG:3857",
            "--output",
            str(tmp_path / "output.json"),
            "--report",
            str(tmp_path / "report.json"),
            "--overlay",
            str(tmp_path / "overlay.svg"),
        )


def test_weak_control_override_writes_review_status(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    controls_path = tmp_path / "controls.json"
    output_path = tmp_path / "output.json"
    report_path = tmp_path / "report.json"
    overlay_path = tmp_path / "overlay.svg"
    source = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    write_centerline(source_path, source)
    write_controls(controls_path, source[:2], [(1000.0, 2000.0), (1100.0, 2000.0)])

    assert (
        run_tool(
            monkeypatch,
            "--input",
            str(source_path),
            "--control-points",
            str(controls_path),
            "--allow-weak-control-set",
            "--fit-crs",
            "EPSG:3857",
            "--output-crs",
            "EPSG:3857",
            "--output",
            str(output_path),
            "--report",
            str(report_path),
            "--overlay",
            str(overlay_path),
        )
        == 0
    )

    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "review"
    assert "status=review" in overlay_path.read_text(encoding="utf-8")
    assert output_path.exists()


def test_rejected_snap_does_not_leave_consumable_output(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    controls_path = tmp_path / "controls.json"
    output_path = tmp_path / "output.json"
    report_path = tmp_path / "report.json"
    overlay_path = tmp_path / "overlay.svg"
    source = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    expected = SimilarityTransform(0.0, 1.0, 1000.0, 2000.0)
    source_controls = [(0.0, 1000.0), source[1], source[2]]
    write_centerline(source_path, source)
    write_controls(controls_path, source_controls, transformed(source[:3], expected))
    output_path.write_text("stale", encoding="utf-8")

    with pytest.raises(SystemExit, match="no centerline was written"):
        run_tool(
            monkeypatch,
            "--input",
            str(source_path),
            "--control-points",
            str(controls_path),
            "--allow-weak-control-set",
            "--fit-crs",
            "EPSG:3857",
            "--output-crs",
            "EPSG:3857",
            "--output",
            str(output_path),
            "--report",
            str(report_path),
            "--overlay",
            str(overlay_path),
        )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "rejected"
    assert report["output_written"] is False
    assert "snap-distance threshold exceeded" in " ".join(report["warnings"])
    assert "status=rejected" in overlay_path.read_text(encoding="utf-8")
    assert not output_path.exists()


def test_cli_rejects_nonfinite_control_and_nonmetric_fit_crs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    controls_path = tmp_path / "controls.json"
    source = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    write_centerline(source_path, source)
    write_controls(controls_path, source[:3], [(math.inf, 2000.0), (1100.0, 2000.0), (1100.0, 2050.0)])
    common = (
        "--input",
        str(source_path),
        "--control-points",
        str(controls_path),
        "--output",
        str(tmp_path / "output.json"),
        "--report",
        str(tmp_path / "report.json"),
        "--overlay",
        str(tmp_path / "overlay.svg"),
    )

    with pytest.raises(SystemExit, match="non-finite"):
        run_tool(monkeypatch, *common)

    write_controls(controls_path, source[:3], [(1000.0, 2000.0), (1100.0, 2000.0), (1100.0, 2050.0)], "EPSG:2263")
    with pytest.raises(SystemExit, match="Fit CRS must use meter units"):
        run_tool(monkeypatch, *common, "--fit-crs", "EPSG:2263")


def test_latlon_output_is_accepted_by_elevation_source_reader(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    controls_path = tmp_path / "controls.json"
    output_path = tmp_path / "georeferenced.json"
    source = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    expected = SimilarityTransform(0.0, 1.0, 500000.0, 5600000.0)
    write_centerline(source_path, source)
    write_controls(controls_path, source[:3], transformed(source[:3], expected), "EPSG:32632")

    assert (
        run_tool(
            monkeypatch,
            "--input",
            str(source_path),
            "--control-points",
            str(controls_path),
            "--fit-crs",
            "EPSG:32632",
            "--output",
            str(output_path),
            "--report",
            str(tmp_path / "report.json"),
            "--overlay",
            str(tmp_path / "overlay.svg"),
        )
        == 0
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert "lat" in output["polyline"][0]
    assert "lon" in output["polyline"][0]
    loaded = import_elevation_raster.load_source_points(output_path, "EPSG:32632", "")
    assert loaded[0].x == pytest.approx(500000.0, abs=0.01)
    assert loaded[0].y == pytest.approx(5600000.0, abs=0.01)
    assert loaded[1].station == pytest.approx(100.0, abs=0.02)


def test_control_cli_selects_utm_from_latlon_controls(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    controls_path = tmp_path / "controls.json"
    output_path = tmp_path / "georeferenced.json"
    source = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    expected = SimilarityTransform(0.0, 1.0, 500000.0, 5600000.0)
    projected = transformed(source[:3], expected)
    to_lonlat = import_elevation_raster.transformer_for("EPSG:32632", "EPSG:4326")
    assert to_lonlat is not None
    lonlat = [to_lonlat.transform(*point) for point in projected]
    controls_path.write_text(
        json.dumps(
            {
                "reference_crs": "EPSG:4326",
                "control_points": [
                    {
                        "name": f"control-{index}",
                        "source": {"x": source_point[0], "y": source_point[1]},
                        "reference": {"lon": reference_point[0], "lat": reference_point[1]},
                    }
                    for index, (source_point, reference_point) in enumerate(zip(source[:3], lonlat, strict=True))
                ],
            }
        ),
        encoding="utf-8",
    )
    write_centerline(source_path, source)

    assert (
        run_tool(
            monkeypatch,
            "--input",
            str(source_path),
            "--control-points",
            str(controls_path),
            "--output",
            str(output_path),
            "--report",
            str(tmp_path / "report.json"),
            "--overlay",
            str(tmp_path / "overlay.svg"),
        )
        == 0
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["georeferencing"]["fit_crs"] == "EPSG:32632"
    assert output["polyline"][0]["lon"] == pytest.approx(lonlat[0][0], abs=1e-8)
    assert output["polyline"][0]["lat"] == pytest.approx(lonlat[0][1], abs=1e-8)


def test_reference_crs_override_does_not_override_control_crs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    reference_path = tmp_path / "reference.json"
    controls_path = tmp_path / "controls.json"
    output_path = tmp_path / "output.json"
    source = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    expected = SimilarityTransform(0.0, 1.0, 557000.0, 164000.0)
    reference = transformed(source, expected)
    to_lonlat = import_elevation_raster.transformer_for("EPSG:27700", "EPSG:4326")
    assert to_lonlat is not None
    lonlat = [to_lonlat.transform(*point) for point in reference[:3]]
    write_centerline(source_path, source)
    write_centerline(reference_path, reference)
    controls_path.write_text(
        json.dumps(
            {
                "reference_crs": "EPSG:4326",
                "control_points": [
                    {
                        "source": {"x": source_point[0], "y": source_point[1]},
                        "reference": {"lon": reference_point[0], "lat": reference_point[1]},
                    }
                    for source_point, reference_point in zip(source[:3], lonlat, strict=True)
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        run_tool(
            monkeypatch,
            "--input",
            str(source_path),
            "--reference",
            str(reference_path),
            "--reference-crs",
            "EPSG:27700",
            "--control-points",
            str(controls_path),
            "--fit-crs",
            "EPSG:27700",
            "--output-crs",
            "EPSG:27700",
            "--output",
            str(output_path),
            "--report",
            str(tmp_path / "report.json"),
            "--overlay",
            str(tmp_path / "overlay.svg"),
        )
        == 0
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["reference_crs"] == "EPSG:27700"
    assert report["control_reference_crs"] == "EPSG:4326"
    assert report["metrics"]["rmse_m"] == pytest.approx(0.0, abs=0.01)


def test_cli_rejects_aliasing_source_and_artifact_paths(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    reference_path = tmp_path / "reference.json"
    source = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    write_centerline(source_path, source)
    write_centerline(reference_path, source, "EPSG:3857")

    with pytest.raises(SystemExit, match="input and output paths must be distinct"):
        run_tool(
            monkeypatch,
            "--input",
            str(source_path),
            "--reference",
            str(reference_path),
            "--fit-crs",
            "EPSG:3857",
            "--output",
            str(source_path),
            "--report",
            str(tmp_path / "report.json"),
            "--overlay",
            str(tmp_path / "overlay.svg"),
        )

    assert json.loads(source_path.read_text(encoding="utf-8"))["polyline"]


def test_cli_rejects_hardlink_alias_coordinate_crs_mismatch_and_degenerate_loop(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.json"
    reference_path = tmp_path / "reference.json"
    output_path = tmp_path / "output.json"
    source = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    write_centerline(source_path, source)
    write_centerline(reference_path, source, "EPSG:3857")
    output_path.hardlink_to(source_path)
    common = (
        "--input",
        str(source_path),
        "--reference",
        str(reference_path),
        "--fit-crs",
        "EPSG:3857",
        "--output",
        str(output_path),
        "--report",
        str(tmp_path / "report.json"),
        "--overlay",
        str(tmp_path / "overlay.svg"),
    )

    with pytest.raises(SystemExit, match="input and output paths must be distinct"):
        run_tool(monkeypatch, *common)

    output_path.unlink()
    reference_path.write_text(
        json.dumps({"source": {"crs": "EPSG:3857"}, "polyline": [{"lat": 51.0, "lon": 0.0}, {"lat": 51.1, "lon": 0.1}, {"lat": 51.0, "lon": 0.2}]}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="lat/lon fields but CRS EPSG:3857 is not geographic"):
        run_tool(monkeypatch, *common)

    write_centerline(reference_path, source, "EPSG:3857")
    write_centerline(source_path, [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)])
    with pytest.raises(SystemExit, match="non-collinear two-dimensional geometry"):
        run_tool(monkeypatch, *common)
