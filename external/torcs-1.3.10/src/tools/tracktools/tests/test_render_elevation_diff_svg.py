# /***************************************************************************
#
#     file                 : test_render_elevation_diff_svg.py
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
import math

import pytest

import torcs_track_tools.cli.render_elevation_diff_svg as render_elevation_diff_svg


def write_track(path) -> None:
    path.write_text(
        """
<params name="Elevation Diff Unit">
  <section name="Main Track">
    <attnum name="width" unit="m" val="10"/>
    <section name="Track Segments">
      <section name="up">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="50"/>
        <attnum name="z start" unit="m" val="0"/>
        <attnum name="z end" unit="m" val="10"/>
        <attnum name="profil start tangent" unit="%" val="0"/>
        <attnum name="profil end tangent" unit="%" val="0"/>
        <attstr name="profil" val="spline"/>
      </section>
      <section name="down">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="50"/>
        <attnum name="z start" unit="m" val="10"/>
        <attnum name="z end" unit="m" val="0"/>
        <attnum name="profil start tangent" unit="%" val="0"/>
        <attnum name="profil end tangent" unit="%" val="0"/>
        <attstr name="profil" val="spline"/>
      </section>
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )


def write_circle_track(path) -> None:
    segments = []
    for idx in range(4):
        segments.append(
            f"""
      <section name="turn-{idx}">
        <attstr name="type" val="lft"/>
        <attnum name="radius" unit="m" val="50"/>
        <attnum name="arc" unit="deg" val="90"/>
        <attnum name="z start" unit="m" val="0"/>
        <attnum name="z end" unit="m" val="0"/>
      </section>
"""
        )
    path.write_text(
        f"""
<params name="Elevation Diff Scaled Unit">
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


def write_cache(path) -> None:
    samples = [
        {"station_m": 0.0, "x": 0.0, "y": 0.0, "elevation_m": 100.0},
        {"station_m": 50.0, "x": 50.0, "y": 0.0, "elevation_m": 100.0},
        {"station_m": 100.0, "x": 100.0, "y": 0.0, "elevation_m": 100.0},
        {"station_m": 200.0, "x": 0.0, "y": 0.0, "elevation_m": 100.0},
    ]
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "normalization": {"road_start_elevation_m": 100.0},
                "terrain_lines": [{"side": "center", "distance_m": 0.0, "samples": samples}],
            }
        ),
        encoding="utf-8",
    )


def write_positioned_profile(path) -> None:
    samples = [
        {"station_m": 0.0, "raster_x": 0.0, "raster_y": 0.0, "elevation_m": 0.0},
        {"station_m": 50.0, "raster_x": 50.0, "raster_y": 0.0, "elevation_m": 0.0},
        {"station_m": 100.0, "raster_x": 100.0, "raster_y": 0.0, "elevation_m": 0.0},
        {"station_m": 200.0, "raster_x": 0.0, "raster_y": 0.0, "elevation_m": 0.0},
    ]
    path.write_text(json.dumps({"schema": 1, "type": "raster-dem-profile", "samples": samples}), encoding="utf-8")


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-render-elevation-diff-svg", *args])
    return render_elevation_diff_svg.main()


def test_color_for_diff_uses_blue_white_red() -> None:
    assert render_elevation_diff_svg.color_for_diff(0.0, 10.0) == "#ffffff"
    assert render_elevation_diff_svg.color_for_diff(10.0, 10.0) == "#dc2626"
    assert render_elevation_diff_svg.color_for_diff(-10.0, 10.0) == "#2563eb"


def test_find_best_fit_can_allow_uniform_scale() -> None:
    track = [
        {"x": 0.0, "y": 0.0},
        {"x": 120.0, "y": 0.0},
        {"x": 140.0, "y": 55.0},
        {"x": 70.0, "y": 100.0},
        {"x": -20.0, "y": 75.0},
    ]
    scale = 0.95
    theta = math.radians(12.0)
    c = math.cos(theta)
    s = math.sin(theta)
    source = [
        {
            "x": scale * (c * point["x"] - s * point["y"]) + 500.0,
            "y": scale * (s * point["x"] + c * point["y"]) + 260000.0,
        }
        for point in track
    ]

    fit = render_elevation_diff_svg.find_best_fit(track, source, 360.0, 1, False, allow_scale=True)

    assert fit.scale == pytest.approx(scale)
    assert math.degrees(fit.theta) == pytest.approx(12.0)
    x, y = render_elevation_diff_svg.transform_xy(140.0, 55.0, fit)
    assert x == pytest.approx(source[2]["x"])
    assert y == pytest.approx(source[2]["y"])


def test_positioned_profile_scale_metadata_enables_scaled_fit(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "circle.xml"
    profile = tmp_path / "scaled-profile.json"
    svg = tmp_path / "diff.svg"
    report_json = tmp_path / "diff.json"
    write_circle_track(track_xml)
    _, _, segments, _, total = render_elevation_diff_svg.load_track(track_xml)
    track_samples = render_elevation_diff_svg.resample_track_loop(segments, total, 80)
    scale = 0.82
    theta = math.radians(-15.0)
    c = math.cos(theta)
    s = math.sin(theta)
    profile.write_text(
        json.dumps(
            {
                "schema": 1,
                "type": "raster-dem-profile",
                "fit": {"scale": scale},
                "samples": [
                    {
                        "station_m": sample["s"],
                        "raster_x": scale * (c * sample["x"] - s * sample["y"]) + 500.0,
                        "raster_y": scale * (s * sample["x"] + c * sample["y"]) + 260000.0,
                        "elevation_m": 0.0,
                    }
                    for sample in track_samples
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile),
            "--output",
            str(svg),
            "--report",
            str(report_json),
            "--fit-samples",
            "80",
        )
        == 0
    )

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["plan_fit"]["scale"] == pytest.approx(scale, rel=0.01)


def test_render_elevation_diff_svg_writes_outline_overlay_and_report(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    cache = tmp_path / "elevation.json"
    svg = tmp_path / "diff.svg"
    report_json = tmp_path / "diff.json"
    profile_json = tmp_path / "profile.json"
    write_track(track_xml)
    write_cache(cache)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--elevation-cache",
            str(cache),
            "--output",
            str(svg),
            "--report",
            str(report_json),
            "--profile-output",
            str(profile_json),
            "--sample-step",
            "25",
            "--color-range",
            "10",
            "--fit-samples",
            "80",
        )
        == 0
    )

    text = svg.read_text(encoding="utf-8")
    assert 'id="real-track-outline"' in text
    assert 'id="torcs-track-outline"' in text
    assert 'id="difference-samples"' in text
    assert "red: track too high, blue: track too low" in text

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["sample_count"] == 4
    assert report["max_too_high"]["difference_track_minus_dem_m"] == pytest.approx(10.0)
    assert report["difference_definition"].startswith("track_z_m - dem_z_m")

    profile = json.loads(profile_json.read_text(encoding="utf-8"))
    assert profile["type"] == "plan-fit-dem-profile"
    assert profile["total_length_m"] == pytest.approx(100.0)
    assert len(profile["samples"]) == 4
    assert profile["samples"][0]["elevation_m"] == pytest.approx(0.0)


def test_render_elevation_diff_svg_accepts_positioned_profile(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "unit.xml"
    profile = tmp_path / "lidar-profile.json"
    svg = tmp_path / "diff.svg"
    report_json = tmp_path / "diff.json"
    write_track(track_xml)
    write_positioned_profile(profile)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile),
            "--output",
            str(svg),
            "--report",
            str(report_json),
            "--sample-step",
            "25",
            "--fit-samples",
            "80",
        )
        == 0
    )

    assert 'id="difference-centerline"' in svg.read_text(encoding="utf-8")
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["sample_count"] == 4
    assert report["max_too_high"]["difference_track_minus_dem_m"] == pytest.approx(10.0)
