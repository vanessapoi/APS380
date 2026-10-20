# /***************************************************************************
#
#     file                 : test_prepare_raster.py
#     created              : 23 May 2026
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

import numpy as np
import pytest

import torcs_track_tools.cli.prepare_raster as prepare_raster


def write_tile(path, x0: float, value: float) -> None:
    rasterio = prepare_raster.import_rasterio()
    from rasterio.transform import from_origin

    data = np.full((1, 2, 2), value, dtype="float32")
    transform = from_origin(x0, 2.0, 1.0, 1.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:6438",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(data)


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-prepare-raster", *args])
    return prepare_raster.main()


def test_prepare_raster_mosaics_and_converts_us_survey_feet(monkeypatch, tmp_path) -> None:
    tile_a = tmp_path / "a.tif"
    tile_b = tmp_path / "b.tif"
    output = tmp_path / "mosaic-m.tif"
    report = tmp_path / "report.json"
    write_tile(tile_a, 0.0, 1.0)
    write_tile(tile_b, 2.0, 2.0)

    assert (
        run_tool(
            monkeypatch,
            "--input",
            str(tile_a),
            "--input",
            str(tile_b),
            "--output",
            str(output),
            "--vertical-unit",
            "us-ft",
            "--report",
            str(report),
        )
        == 0
    )

    rasterio = prepare_raster.import_rasterio()
    with rasterio.open(output) as src:
        data = src.read(1)
        assert src.crs.to_string() == "EPSG:6438"
        assert src.width == 4
        assert data.min() == pytest.approx(1200.0 / 3937.0)
        assert data.max() == pytest.approx(2.0 * 1200.0 / 3937.0)

    report_data = json.loads(report.read_text(encoding="utf-8"))
    assert report_data["input_count"] == 2
    assert report_data["output"] == str(output)


def test_prepare_raster_dry_run_reports_without_output(monkeypatch, tmp_path) -> None:
    tile = tmp_path / "tile.tif"
    report = tmp_path / "report.json"
    write_tile(tile, 0.0, 1.0)

    assert run_tool(monkeypatch, "--input", str(tile), "--dry-run", "--report", str(report)) == 0

    report_data = json.loads(report.read_text(encoding="utf-8"))
    assert report_data["dry_run"] is True
    assert report_data["inputs"][0]["driver"] == "GTiff"
