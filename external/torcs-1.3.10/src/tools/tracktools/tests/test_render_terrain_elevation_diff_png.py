# /***************************************************************************
#
#     file                 : test_render_terrain_elevation_diff_png.py
#     created              : 09 May 2026
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
from PIL import Image

import torcs_track_tools.cli.render_terrain_elevation_diff_png as render_terrain_elevation_diff_png


def source_height(x: float, y: float) -> float:
    return 100.0 + 0.02 * x + 0.03 * y


def write_track(path, map_name: str, min_altitude: float, max_altitude: float) -> None:
    path.write_text(
        f"""
<params name="Terrain Diff Unit">
  <section name="Graphic">
    <section name="Terrain Generation">
      <attnum name="track step" unit="m" val="10"/>
      <attnum name="border margin" unit="m" val="20"/>
      <attstr name="elevation map" val="{map_name}"/>
      <attnum name="minimum altitude" unit="m" val="{min_altitude}"/>
      <attnum name="maximum altitude" unit="m" val="{max_altitude}"/>
    </section>
  </section>
  <section name="Main Track">
    <attnum name="width" unit="m" val="10"/>
    <section name="Track Segments">
      <section name="straight">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="100"/>
      </section>
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )


def write_ascii_grid(path) -> None:
    ncols = 80
    nrows = 80
    cellsize = 5.0
    xllcorner = -100.0
    yllcorner = -120.0
    y_top = yllcorner + (nrows - 0.5) * cellsize
    rows = []
    for row in range(nrows):
        y = y_top - row * cellsize
        values = []
        for col in range(ncols):
            x = xllcorner + (col + 0.5) * cellsize
            values.append(f"{source_height(x, y):.6f}")
        rows.append(" ".join(values))
    path.write_text(
        "\n".join(
            [
                f"ncols {ncols}",
                f"nrows {nrows}",
                f"xllcorner {xllcorner}",
                f"yllcorner {yllcorner}",
                f"cellsize {cellsize}",
                "NODATA_value -9999",
                *rows,
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_profile(path, raster) -> None:
    path.write_text(
        json.dumps(
            {
                "raster": str(raster),
                "zero_elevation_m": 100.0,
                "fit": {"cos": 1.0, "sin": 0.0, "offset_x": 0.0, "offset_y": 0.0},
                "samples": [
                    {"station_m": 0.0, "elevation_m": 0.0},
                    {"station_m": 100.0, "elevation_m": 2.0},
                ],
            }
        ),
        encoding="utf-8",
    )


def terrain_bounds(track_xml):
    main_track, terrain, segs, segments, lengths, _total = render_terrain_elevation_diff_png.load_track(track_xml)
    return render_terrain_elevation_diff_png.terrain_bounds(main_track, terrain, segs, segments, lengths)


def write_terrain_map(path, bounds, width: int, height: int, flip_for_trackgen: bool) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = bounds
    values = np.empty((height, width), dtype=float)
    for row in range(height):
        y = min_y + (max_y - min_y) * row / max(1, height - 1)
        for col in range(width):
            x = min_x + (max_x - min_x) * col / max(1, width - 1)
            values[row, col] = source_height(x, y) - 100.0
    min_altitude = float(np.min(values))
    max_altitude = float(np.max(values))
    gray = np.rint((values - min_altitude) * 255.0 / (max_altitude - min_altitude)).clip(0, 255).astype(np.uint8)
    if flip_for_trackgen:
        gray = np.flipud(gray)
    Image.fromarray(np.dstack((gray, gray, gray))).save(path)
    return min_altitude, max_altitude


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-render-terrain-elevation-diff-png", *args])
    return render_terrain_elevation_diff_png.main()


def test_color_for_diff_uses_white_for_match() -> None:
    colors = render_terrain_elevation_diff_png.colors_for_diff(np.array([[-10.0, 0.0, 10.0]]), 10.0)

    assert tuple(colors[0, 0]) == (37, 99, 235)
    assert tuple(colors[0, 1]) == (255, 255, 255)
    assert tuple(colors[0, 2]) == (220, 38, 38)


def test_terrain_elevation_diff_png_matches_trackgen_row_order(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    raster = tmp_path / "terrain.asc"
    profile = tmp_path / "profile.json"
    elevation_map = tmp_path / "terrain.png"
    diff_png = tmp_path / "diff.png"
    report_json = tmp_path / "diff.json"
    write_ascii_grid(raster)
    write_profile(profile, raster)
    write_track(track_xml, elevation_map.name, -1.0, 1.0)
    bounds = terrain_bounds(track_xml)
    min_altitude, max_altitude = write_terrain_map(elevation_map, bounds, 16, 8, True)
    write_track(track_xml, elevation_map.name, min_altitude, max_altitude)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile),
            "--output",
            str(diff_png),
            "--report",
            str(report_json),
            "--color-range",
            "1",
        )
        == 0
    )

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["max_abs_difference_m"] < 0.05
    with Image.open(diff_png) as image:
        colors = np.asarray(image.convert("RGB"))
    assert np.min(colors) > 245


def test_terrain_elevation_diff_png_detects_unflipped_map(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    raster = tmp_path / "terrain.asc"
    profile = tmp_path / "profile.json"
    elevation_map = tmp_path / "terrain.png"
    diff_png = tmp_path / "diff.png"
    report_json = tmp_path / "diff.json"
    write_ascii_grid(raster)
    write_profile(profile, raster)
    write_track(track_xml, elevation_map.name, -1.0, 1.0)
    bounds = terrain_bounds(track_xml)
    min_altitude, max_altitude = write_terrain_map(elevation_map, bounds, 16, 8, False)
    write_track(track_xml, elevation_map.name, min_altitude, max_altitude)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile),
            "--output",
            str(diff_png),
            "--report",
            str(report_json),
            "--color-range",
            "1",
        )
        == 0
    )

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["max_abs_difference_m"] > 1.0
