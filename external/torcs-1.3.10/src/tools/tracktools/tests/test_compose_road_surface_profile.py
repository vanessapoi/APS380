# /***************************************************************************
#
#     file                 : test_compose_road_surface_profile.py
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

import pytest

import torcs_track_tools.cli.apply_elevation as apply_elevation
import torcs_track_tools.cli.compose_road_surface_profile as compose_road_surface_profile


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-compose-road-surface-profile", *args])
    return compose_road_surface_profile.main()


def write_polyline(path) -> None:
    path.write_text(
        json.dumps(
            {
                "polyline": [
                    {"x": 0.0, "y": 0.0, "way_name": "Start"},
                    {"x": 100.0, "y": 0.0, "way_name": "Start"},
                    {"x": 200.0, "y": 0.0, "way_name": "Straight"},
                ]
            }
        ),
        encoding="utf-8",
    )


def test_compose_combines_source_elevation_and_banking(monkeypatch, tmp_path) -> None:
    polyline = tmp_path / "centerline.json"
    elevation = tmp_path / "elevation.json"
    banking = tmp_path / "banking.json"
    output = tmp_path / "road-surface.json"
    report = tmp_path / "road-surface-report.json"
    write_polyline(polyline)
    elevation.write_text(
        json.dumps(
            {
                "schema": 1,
                "source": {"type": "dem-corridor", "polyline": str(polyline)},
                "total_length_m": 200.0,
                "normalization": {"road_start_elevation_m": 100.0},
                "road_profile": {
                    "samples": [
                        {"station_m": 0.0, "elevation_m": 0.0, "weight": 0.8},
                        {"station_m": 200.0, "elevation_m": 5.0, "weight": 0.8},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    banking.write_text(
        json.dumps(
            {
                "schema": 1,
                "type": "road-surface-profile",
                "station_frame": "source",
                "source_polyline": str(polyline),
                "source_total_length_m": 200.0,
                "mapping": {
                    "source_reversed": True,
                    "station_map": [
                        {"xml_station_m": 0.0, "source_station_m": 20.0},
                        {"xml_station_m": 100.0, "source_station_m": 120.0},
                    ],
                },
                "sampling": {"real_road_width_m": 8.0},
                "banking_profile": {
                    "source": "manual-zones",
                    "samples": [
                        {"source_station_m": 0.0, "banking_deg": 2.0},
                        {"source_station_m": 200.0, "banking_deg": 4.0},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    assert (
        run_tool(
            monkeypatch,
            "--elevation-profile",
            str(elevation),
            "--banking-profile",
            str(banking),
            "--output",
            str(output),
            "--report",
            str(report),
        )
        == 0
    )

    profile = json.loads(output.read_text(encoding="utf-8"))
    assert profile["type"] == "road-surface-profile"
    assert profile["station_frame"] == "source"
    assert profile["source_total_length_m"] == pytest.approx(200.0)
    assert profile["mapping"]["source_reversed"] is True
    assert profile["sampling"]["real_road_width_m"] == pytest.approx(8.0)
    assert "source_station_m" in profile["elevation_profile"]["samples"][0]
    assert "station_m" not in profile["elevation_profile"]["samples"][0]
    assert profile["banking_profile"]["source"] == "manual-zones"

    elevation_source = apply_elevation.read_profile(output)
    banking_source = apply_elevation.read_banking_profiles(output)[0]
    assert elevation_source.source_total == pytest.approx(200.0)
    assert elevation_source.station_map[0] == apply_elevation.StationMapPoint(0.0, 20.0)
    assert banking_source.source_reversed is True
    assert banking_source.real_width_m == pytest.approx(8.0)

    report_data = json.loads(report.read_text(encoding="utf-8"))
    assert report_data["elevation_sample_count"] == 2
    assert report_data["banking_sample_count"] == 2
    assert report_data["mapping"]["station_map_count"] == 2


def test_compose_resolves_relative_source_polyline_from_input_profile(monkeypatch, tmp_path) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    polyline = source_dir / "centerline.json"
    elevation = source_dir / "elevation.json"
    output = output_dir / "road-surface.json"
    write_polyline(polyline)
    elevation.write_text(
        json.dumps(
            {
                "type": "road-surface-profile",
                "station_frame": "source",
                "source_polyline": "centerline.json",
                "source_total_length_m": 200.0,
                "elevation_profile": {
                    "samples": [
                        {"source_station_m": 0.0, "elevation_m": 0.0},
                        {"source_station_m": 200.0, "elevation_m": 5.0},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    assert run_tool(monkeypatch, "--elevation-profile", str(elevation), "--output", str(output)) == 0

    profile = json.loads(output.read_text(encoding="utf-8"))
    assert profile["source_polyline"] == str(polyline.resolve())
    source = apply_elevation.read_profile(output)
    assert source.landmarks[0].name == "Start"


def test_compose_supports_elevation_only_profiles(monkeypatch, tmp_path) -> None:
    elevation = tmp_path / "elevation.json"
    output = tmp_path / "road-surface.json"
    elevation.write_text(
        json.dumps(
            {
                "total_length_m": 100.0,
                "weight": 0.5,
                "samples": [
                    {"station_m": 0.0, "elevation_m": 1.0},
                    {"station_m": 100.0, "elevation_m": 3.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert run_tool(monkeypatch, "--elevation-profile", str(elevation), "--output", str(output)) == 0

    profile = json.loads(output.read_text(encoding="utf-8"))
    assert profile["station_frame"] == "xml"
    assert profile["total_length_m"] == pytest.approx(100.0)
    assert profile["weight"] == pytest.approx(0.5)
    assert "banking_profile" not in profile
    assert profile["elevation_profile"]["samples"][1]["station_m"] == pytest.approx(100.0)
    assert apply_elevation.read_profile(output).weight == pytest.approx(0.5)


def test_compose_csv_accepts_distance_header(monkeypatch, tmp_path) -> None:
    elevation = tmp_path / "elevation.csv"
    output = tmp_path / "road-surface.json"
    elevation.write_text("distance,elevation\n10,1\n20,3\n", encoding="utf-8")

    assert run_tool(monkeypatch, "--elevation-profile", str(elevation), "--output", str(output)) == 0

    profile = json.loads(output.read_text(encoding="utf-8"))
    assert profile["elevation_profile"]["samples"][0]["station_m"] == pytest.approx(10.0)
    assert profile["elevation_profile"]["samples"][0]["elevation_m"] == pytest.approx(1.0)


def test_compose_supports_banking_only_profiles(monkeypatch, tmp_path) -> None:
    banking = tmp_path / "banking.json"
    output = tmp_path / "road-surface.json"
    banking.write_text(
        json.dumps(
            {
                "type": "road-surface-profile",
                "station_frame": "xml",
                "sampling": {"real_road_width_m": 12.0},
                "banking_profile": {
                    "samples": [
                        {"station_m": 0.0, "banking_deg": 1.0},
                        {"station_m": 100.0, "banking_deg": 2.0},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    assert run_tool(monkeypatch, "--banking-profile", str(banking), "--output", str(output)) == 0

    profile = json.loads(output.read_text(encoding="utf-8"))
    assert profile["station_frame"] == "xml"
    assert "elevation_profile" not in profile
    assert profile["banking_profile"]["samples"][1]["banking_deg"] == pytest.approx(2.0)
    assert apply_elevation.read_banking_profiles(output)[0].real_width_m == pytest.approx(12.0)


def test_compose_rejects_mixed_station_frames(monkeypatch, tmp_path) -> None:
    elevation = tmp_path / "elevation.json"
    banking = tmp_path / "banking.json"
    elevation.write_text(
        json.dumps(
            {
                "samples": [
                    {"station_m": 0.0, "elevation_m": 0.0},
                    {"station_m": 100.0, "elevation_m": 1.0},
                ]
            }
        ),
        encoding="utf-8",
    )
    banking.write_text(
        json.dumps(
            {
                "type": "road-surface-profile",
                "station_frame": "source",
                "source_total_length_m": 100.0,
                "banking_profile": {
                    "samples": [
                        {"source_station_m": 0.0, "banking_deg": 0.0},
                        {"source_station_m": 100.0, "banking_deg": 5.0},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="Incompatible station frames"):
        run_tool(monkeypatch, "--elevation-profile", str(elevation), "--banking-profile", str(banking), "--output", str(tmp_path / "out.json"))
