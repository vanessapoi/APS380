# /***************************************************************************
#
#     file                 : test_import_road_surface_raster.py
#     created              : 22 May 2026
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

import torcs_track_tools.cli.apply_elevation as apply_elevation
import torcs_track_tools.cli.import_road_surface_raster as import_road_surface_raster


def write_circle_track(path) -> None:
    segments = []
    for idx in range(4):
        segments.append(
            f"""
      <section name="turn-{idx}">
        <attstr name="type" val="lft"/>
        <attnum name="radius" unit="m" val="50"/>
        <attnum name="arc" unit="deg" val="90"/>
      </section>
"""
        )
    path.write_text(
        f"""
<params name="Road Surface Raster Unit">
  <section name="Main Track">
    <attnum name="width" unit="m" val="10"/>
    <section name="Track Segments">
{''.join(segments)}
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )


def write_source_from_track(track_xml, polyline) -> None:
    _, _, segments, _, _ = import_road_surface_raster.load_track(track_xml)
    samples = import_road_surface_raster.resample_track_loop(segments, 2.0 * math.pi * 50.0, 160)
    points = [{"x": sample["x"], "y": sample["y"], "way_name": "turn"} for sample in samples]
    points.append(points[0])
    polyline.write_text(json.dumps({"polyline": points}), encoding="utf-8")


def write_banked_circle_ascii_grid(path, slope: float = 0.1) -> None:
    ncols = 241
    nrows = 241
    xll = -120.0
    yll = -70.0
    cell = 1.0
    center_x = 0.0
    center_y = 50.0
    radius = 50.0
    rows = []
    for row in range(nrows):
        y = yll + (nrows - row - 0.5) * cell
        values = []
        for col in range(ncols):
            x = xll + (col + 0.5) * cell
            radial = math.hypot(x - center_x, y - center_y)
            values.append(f"{100.0 + slope * (radius - radial):.6f}")
        rows.append(" ".join(values))
    path.write_text(
        "\n".join(
            [
                f"ncols {ncols}",
                f"nrows {nrows}",
                f"xllcorner {xll}",
                f"yllcorner {yll}",
                f"cellsize {cell}",
                "NODATA_value -9999",
                *rows,
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-import-road-surface-raster", *args])
    return import_road_surface_raster.main()


class RecordingRaster:
    crs = ""

    def __init__(self, value: float | None = 42.0) -> None:
        self.value = value
        self.calls: list[tuple[float, float, str]] = []

    def sample(self, x: float, y: float, resampling: str) -> float | None:
        self.calls.append((x, y, resampling))
        return self.value


def test_lateral_offsets_and_crossfall_orientation() -> None:
    assert import_road_surface_raster.lateral_offsets(10.0, 3) == pytest.approx([-5.0, 0.0, 5.0])

    center_z, banking_deg, left_z, right_z = import_road_surface_raster.fit_crossfall([(-5.0, 1.0), (0.0, 2.0), (5.0, 3.0)], 10.0)

    assert center_z == pytest.approx(2.0)
    assert banking_deg == pytest.approx(math.degrees(math.atan(0.2)))
    assert left_z == pytest.approx(3.0)
    assert right_z == pytest.approx(1.0)


def test_lateral_offsets_and_crossfall_reject_degenerate_inputs() -> None:
    with pytest.raises(SystemExit, match="--road-width"):
        import_road_surface_raster.lateral_offsets(0.0, 3)
    with pytest.raises(SystemExit, match="--cross-section-samples"):
        import_road_surface_raster.lateral_offsets(10.0, 1)
    with pytest.raises(SystemExit, match="zero variance"):
        import_road_surface_raster.fit_crossfall([(1.0, 2.0), (1.0, 3.0)], 10.0)


def test_source_loop_fit_samples_dedupes_closed_loop_and_scales_stations() -> None:
    points = [
        import_road_surface_raster.SourcePoint(0.0, 0.0, 0.0),
        import_road_surface_raster.SourcePoint(3.0, 0.0, 3.0),
        import_road_surface_raster.SourcePoint(3.0, 4.0, 7.0),
        import_road_surface_raster.SourcePoint(0.0, 0.0, 12.0),
    ]

    samples, total = import_road_surface_raster.source_loop_fit_samples(points, 4, 0.5)

    assert total == pytest.approx(6.0)
    assert len(samples) == 8
    assert samples[0] == pytest.approx({"x": 0.0, "y": 0.0, "s": 0.0})
    assert samples[4]["s"] == pytest.approx(3.0)


def test_sample_lateral_uses_left_normal_and_raster_units() -> None:
    raster = RecordingRaster(7.0)
    pose = import_road_surface_raster.SourcePose(10.0, 20.0, 0.0, 0.0)

    x, y, value = import_road_surface_raster.sample_lateral(raster, pose, 2.0, 3.0, "nearest")

    assert x == pytest.approx(10.0)
    assert y == pytest.approx(26.0)
    assert value == pytest.approx(7.0)
    assert len(raster.calls) == 1
    assert raster.calls[0][0] == pytest.approx(10.0)
    assert raster.calls[0][1] == pytest.approx(26.0)
    assert raster.calls[0][2] == "nearest"


def test_sample_road_surface_rejects_missing_cross_section_samples() -> None:
    raster = RecordingRaster(None)
    source_points = [
        import_road_surface_raster.SourcePoint(0.0, 0.0, 0.0),
        import_road_surface_raster.SourcePoint(10.0, 0.0, 10.0),
        import_road_surface_raster.SourcePoint(10.0, 10.0, 20.0),
        import_road_surface_raster.SourcePoint(0.0, 10.0, 30.0),
    ]
    args = type(
        "Args",
        (),
        {"road_width": 10.0, "cross_section_samples": 3, "min_cross_section_samples": 0, "sample_step": 5.0, "resampling": "nearest"},
    )()

    with pytest.raises(SystemExit, match="too few cross-section samples"):
        import_road_surface_raster.sample_road_surface(raster, source_points, args)


def test_zero_samples_track_start_uses_source_shift() -> None:
    samples = [
        import_road_surface_raster.CrossSample(0.0, 0.0, 0.0, 0.0, 100.0, 100.0, 0.0, 100.0, 100.0, 3),
        import_road_surface_raster.CrossSample(50.0, 50.0, 0.0, 0.0, 120.0, 120.0, 0.0, 120.0, 120.0, 3),
        import_road_surface_raster.CrossSample(100.0, 100.0, 0.0, 0.0, 140.0, 140.0, 0.0, 140.0, 140.0, 3),
    ]

    zeroed, zero = import_road_surface_raster.zero_samples(samples, "track-start", 25.0, 100.0)

    assert zero == pytest.approx(110.0)
    assert zeroed[0].elevation == pytest.approx(-10.0)
    assert zeroed[1].elevation == pytest.approx(10.0)


def test_import_road_surface_raster_writes_source_frame_profile(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    polyline = tmp_path / "source.json"
    raster = tmp_path / "surface.asc"
    output = tmp_path / "road-surface.json"
    report = tmp_path / "road-surface-report.json"
    overlay = tmp_path / "road-surface.svg"
    write_circle_track(track_xml)
    write_source_from_track(track_xml, polyline)
    write_banked_circle_ascii_grid(raster, slope=0.1)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--polyline",
            str(polyline),
            "--raster",
            str(raster),
            "--road-width",
            "10",
            "--output",
            str(output),
            "--report",
            str(report),
            "--overlay",
            str(overlay),
            "--sample-step",
            "25",
            "--fit-samples",
            "120",
        )
        == 0
    )

    profile = json.loads(output.read_text(encoding="utf-8"))
    assert profile["type"] == "road-surface-profile"
    assert profile["station_frame"] == "source"
    assert profile["sampling"]["real_road_width_m"] == pytest.approx(10.0)
    assert profile["mapping"]["method"] == "plan-fit"
    assert profile["fit"]["rmse_m"] < 1.0
    assert len(profile["elevation_profile"]["samples"]) == len(profile["banking_profile"]["samples"])

    banking = [sample["banking_deg"] for sample in profile["banking_profile"]["samples"]]
    assert sum(banking) / len(banking) == pytest.approx(math.degrees(math.atan(0.1)), abs=0.6)
    assert min(banking) > 4.5
    assert max(abs(sample["elevation_m"]) for sample in profile["elevation_profile"]["samples"]) < 1.0

    elevation_source = apply_elevation.read_profile(output)
    banking_source = apply_elevation.read_banking_profiles(output)[0]
    assert elevation_source.source_total == pytest.approx(profile["source_total_length_m"])
    assert banking_source.source_shift_m == pytest.approx(profile["mapping"]["source_shift_m"])
    assert banking_source.real_width_m == pytest.approx(10.0)

    report_obj = json.loads(report.read_text(encoding="utf-8"))
    assert report_obj["sample_count"] == len(profile["banking_profile"]["samples"])
    assert report_obj["min_banking_deg"] > 4.5
    overlay_text = overlay.read_text(encoding="utf-8")
    assert 'id="source-centerline"' in overlay_text
    assert 'id="road-surface-samples"' in overlay_text


def test_import_road_surface_raster_requires_positive_road_width(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    polyline = tmp_path / "source.json"
    raster = tmp_path / "surface.asc"
    output = tmp_path / "road-surface.json"
    write_circle_track(track_xml)
    write_source_from_track(track_xml, polyline)
    write_banked_circle_ascii_grid(raster)

    with pytest.raises(SystemExit, match="--road-width"):
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--polyline",
            str(polyline),
            "--raster",
            str(raster),
            "--road-width",
            "0",
            "--output",
            str(output),
        )


def test_road_surface_raster_rejects_geographic_crs() -> None:
    class Raster:
        crs = "EPSG:4326"

    with pytest.raises(SystemExit, match="Geographic raster CRS"):
        import_road_surface_raster.raster_units_per_meter(Raster())


def test_road_surface_raster_auto_scale_fit_for_foot_crs() -> None:
    class Raster:
        crs = "EPSG:6438"

    assert import_road_surface_raster.should_allow_scale_fit(Raster(), False) is True
    assert import_road_surface_raster.raster_units_per_meter(Raster()) == pytest.approx(3.280833333, rel=1e-5)
    assert import_road_surface_raster.raster_units_to_meter(Raster()) == pytest.approx(0.3048006096, rel=1e-5)
