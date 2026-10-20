# /***************************************************************************
#
#     file                 : test_import_elevation_raster.py
#     created              : 08 May 2026
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

import torcs_track_tools.cli.import_elevation_raster as import_elevation_raster
from torcs_track_tools.core.track_georeference import track_plan_sha256


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
<params name="Raster Import Unit">
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
    _, _, segments, _, _ = import_elevation_raster.load_track(track_xml)
    samples = import_elevation_raster.sample_track_plan(segments, 8.0)
    points = [{"x": sample.x, "y": sample.y} for sample in samples]
    points.append(points[0])
    polyline.write_text(json.dumps({"polyline": points}), encoding="utf-8")


def write_ascii_grid(path) -> None:
    ncols = 281
    nrows = 281
    xll = -90.0
    yll = -90.0
    cell = 1.0
    rows = []
    for row in range(nrows):
        y = yll + (nrows - row - 0.5) * cell
        values = []
        for col in range(ncols):
            x = xll + (col + 0.5) * cell
            values.append(f"{x + y:.3f}")
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
    monkeypatch.setattr("sys.argv", ["torcs-import-elevation-raster", *args])
    return import_elevation_raster.main()


class Raster:
    def __init__(self, crs: str) -> None:
        self.crs = crs


def test_raster_requires_scale_fit_characterizes_crs_units(recwarn) -> None:  # noqa: ANN001
    assert import_elevation_raster.raster_requires_scale_fit(Raster("")) is False
    assert import_elevation_raster.raster_requires_scale_fit(Raster("EPSG:32617")) is False
    assert import_elevation_raster.raster_requires_scale_fit(Raster("EPSG:4326")) is True
    assert import_elevation_raster.raster_requires_scale_fit(Raster("EPSG:6438")) is True
    assert import_elevation_raster.raster_requires_scale_fit(Raster("not-a-crs")) is False
    assert not recwarn


def test_load_source_points_preserves_xy_without_transform(tmp_path) -> None:
    polyline = tmp_path / "xy.json"
    polyline.write_text(json.dumps({"polyline": [{"x": 0, "y": 0}, {"x": 3, "y": 4}, {"x": 6, "y": 4}]}), encoding="utf-8")

    points = import_elevation_raster.load_source_points(polyline, "", "")

    assert [(p.x, p.y) for p in points] == [(0.0, 0.0), (3.0, 4.0), (6.0, 4.0)]
    assert [p.station for p in points] == pytest.approx([0.0, 5.0, 8.0])


def test_load_source_points_latlon_requires_raster_crs(tmp_path) -> None:
    polyline = tmp_path / "latlon.json"
    polyline.write_text(json.dumps({"polyline": [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.001}]}), encoding="utf-8")

    with pytest.raises(SystemExit, match="Lat/lon source polylines need a raster CRS"):
        import_elevation_raster.load_source_points(polyline, "", "")


def test_load_source_points_reprojects_latlon_to_raster_crs(tmp_path) -> None:
    polyline = tmp_path / "latlon.json"
    polyline.write_text(json.dumps({"polyline": [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.001}]}), encoding="utf-8")

    points = import_elevation_raster.load_source_points(polyline, "EPSG:3857", "")

    assert points[0].x == pytest.approx(0.0, abs=1e-9)
    assert points[0].y == pytest.approx(0.0, abs=1e-9)
    assert points[1].x == pytest.approx(111.3194908, rel=1e-7)
    assert points[1].y == pytest.approx(0.0, abs=1e-9)
    assert points[1].station == pytest.approx(111.3194908, rel=1e-7)


def test_source_loop_samples_dedupes_closed_loop_and_keeps_closing_span() -> None:
    points = [
        import_elevation_raster.SourcePoint(0.0, 0.0, 0.0),
        import_elevation_raster.SourcePoint(3.0, 0.0, 3.0),
        import_elevation_raster.SourcePoint(3.0, 4.0, 7.0),
        import_elevation_raster.SourcePoint(0.0, 0.0, 12.0),
    ]

    samples, total = import_elevation_raster.source_loop_samples(points, 4)

    assert total == pytest.approx(12.0)
    assert len(samples) == 8
    assert samples[0] == pytest.approx({"x": 0.0, "y": 0.0, "s": 0.0})
    assert samples[2] == pytest.approx({"x": 3.0, "y": 0.0, "s": 3.0})
    assert samples[4] == pytest.approx({"x": 3.0, "y": 3.0, "s": 6.0})


def test_source_loop_samples_rejects_zero_length_source() -> None:
    points = [import_elevation_raster.SourcePoint(1.0, 1.0, 0.0), import_elevation_raster.SourcePoint(1.0, 1.0, 0.0)]

    with pytest.raises(SystemExit, match="zero length"):
        import_elevation_raster.source_loop_samples(points, 8)


def test_ascii_grid_sampler_bilinear_interpolates(tmp_path) -> None:
    grid = tmp_path / "dem.asc"
    write_ascii_grid(grid)
    sampler = import_elevation_raster.AsciiGridSampler(grid)

    assert sampler.sample(0.0, 0.0, "bilinear") == pytest.approx(0.0)
    assert sampler.sample(25.25, 10.75, "bilinear") == pytest.approx(36.0)


def test_import_elevation_raster_writes_profile_report_and_overlay(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    polyline = tmp_path / "source.json"
    raster = tmp_path / "dem.asc"
    output = tmp_path / "profile.json"
    report = tmp_path / "report.json"
    overlay = tmp_path / "overlay.svg"

    write_circle_track(track_xml)
    write_source_from_track(track_xml, polyline)
    write_ascii_grid(raster)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--polyline",
            str(polyline),
            "--raster",
            str(raster),
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
    assert profile["type"] == "raster-dem-profile"
    assert profile["track_plan_sha256"] == track_plan_sha256(track_xml.read_text(encoding="utf-8"))
    assert profile["fit"]["scale"] == pytest.approx(1.0)
    assert profile["samples"][0]["elevation_m"] == pytest.approx(0.0)
    elevations = [sample["elevation_m"] for sample in profile["samples"]]
    assert max(elevations) - min(elevations) > 90.0

    report_obj = json.loads(report.read_text(encoding="utf-8"))
    assert report_obj["sample_count"] == len(profile["samples"])
    assert report_obj["fit"]["rmse_m"] < 1.0

    overlay_text = overlay.read_text(encoding="utf-8")
    assert 'id="source-centerline"' in overlay_text
    assert 'id="profile-samples"' in overlay_text
