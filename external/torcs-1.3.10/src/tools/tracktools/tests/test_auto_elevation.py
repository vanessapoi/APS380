# /***************************************************************************
#
#     file                 : test_auto_elevation.py
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
import zipfile

import numpy as np
import pytest
from rasterio.transform import from_origin

import torcs_track_tools.cli.auto_elevation as auto_elevation
import torcs_track_tools.cli.import_elevation_raster as import_elevation_raster


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
<params name="Auto Elevation Unit">
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


def write_dem_zip(path) -> None:
    grid = path.with_suffix(".asc")
    write_ascii_grid(grid)
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(grid, "tile.asc")


def write_tiff(path, left: float, top: float, values: list[list[float]]) -> None:
    rasterio = import_elevation_raster.import_rasterio()
    data = np.array(values, dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:27700",
        transform=from_origin(left, top, 1.0, 1.0),
        nodata=np.finfo("float32").min,
    ) as dataset:
        dataset.write(data, 1)


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-auto-elevation", *args])
    return auto_elevation.main()


def test_select_best_tiles_prefers_composite_latest_best_resolution() -> None:
    results = [
        {"product": {"id": "national_lidar_programme_dtm", "label": "NLP DTM"}, "year": {"id": "2019"}, "resolution": {"id": "1"}, "tile": {"id": "A"}},
        {"product": {"id": "lidar_composite_dtm", "label": "Composite DTM"}, "year": {"id": "2021"}, "resolution": {"id": "2"}, "tile": {"id": "B"}},
        {"product": {"id": "lidar_composite_dtm", "label": "Composite DTM"}, "year": {"id": "2022"}, "resolution": {"id": "1"}, "tile": {"id": "C"}},
    ]

    tiles = auto_elevation.select_best_tiles(results, "lidar_composite_dtm,national_lidar_programme_dtm")

    assert [tile.tile_id for tile in tiles] == ["C"]


def test_mosaic_rasters_preserves_ea_float32_values(tmp_path) -> None:
    left = tmp_path / "left.tif"
    right = tmp_path / "right.tif"
    output = tmp_path / "mosaic.tif"
    write_tiff(left, 0.0, 2.0, [[10.0, 11.0], [12.0, 13.0]])
    write_tiff(right, 2.0, 2.0, [[20.0, 21.0], [22.0, 23.0]])

    auto_elevation.mosaic_rasters([left, right], output)

    rasterio = import_elevation_raster.import_rasterio()
    with rasterio.open(output) as dataset:
        data = dataset.read(1)
        assert dataset.nodata == -9999.0
        assert data.shape == (2, 4)
        assert data[0, 0] == pytest.approx(10.0)
        assert data[1, 3] == pytest.approx(23.0)


def test_extract_tile_zip_rejects_unsafe_paths(tmp_path) -> None:
    tile_zip = tmp_path / "tile.zip"
    with zipfile.ZipFile(tile_zip, "w") as zf:
        zf.writestr("../escape.asc", "ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1\n")

    with pytest.raises(SystemExit, match="unsafe archive path"):
        auto_elevation.extract_tile_zip(tile_zip, tmp_path / "tiles")

    assert not (tmp_path / "escape.asc").exists()


def test_auto_elevation_imports_mocked_ea_tile(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    polyline = tmp_path / "source.json"
    out_dir = tmp_path / "auto"
    fake_zip = tmp_path / "tile.zip"
    write_circle_track(track_xml)
    write_source_from_track(track_xml, polyline)
    write_dem_zip(fake_zip)

    captured = {}

    def fake_search(area, url, subscription_key):  # noqa: ANN001
        captured["area"] = area
        captured["url"] = url
        captured["subscription_key"] = subscription_key
        return [
            {
                "product": {"id": "lidar_composite_dtm", "label": "LIDAR Composite DTM"},
                "year": {"id": "2022"},
                "resolution": {"id": "1"},
                "tile": {"id": "TF2580", "label": "TF28se"},
                "uri": "https://example.invalid/tile",
            }
        ]

    def fake_download(tile, directory, subscription_key, force):  # noqa: ANN001
        captured["tile"] = tile
        captured["download_dir"] = directory
        captured["force"] = force
        return fake_zip

    monkeypatch.setattr(auto_elevation, "search_ea_tiles", fake_search)
    monkeypatch.setattr(auto_elevation, "download_tile", fake_download)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--polyline",
            str(polyline),
            "--polyline-crs",
            "EPSG:27700",
            "--provider-crs",
            "EPSG:27700",
            "--output-dir",
            str(out_dir),
            "--sample-step",
            "25",
            "--fit-samples",
            "120",
            "--landscape-margin-m",
            "500",
        )
        == 0
    )

    assert captured["subscription_key"] == "dspui"
    assert captured["tile"].tile_id == "TF2580"
    profile = json.loads((out_dir / "elevation-ea-lidar-profile.json").read_text(encoding="utf-8"))
    report = json.loads((out_dir / "auto-elevation-report.json").read_text(encoding="utf-8"))
    assert profile["type"] == "raster-dem-profile"
    assert report["landscape_margin_m"] == 500.0
    assert report["selected_tiles"][0]["tile_id"] == "TF2580"
