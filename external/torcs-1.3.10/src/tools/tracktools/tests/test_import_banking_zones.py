# /***************************************************************************
#
#     file                 : test_import_banking_zones.py
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

import torcs_track_tools.cli.import_banking_zones as import_banking_zones


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-import-banking-zones", *args])
    return import_banking_zones.main()


def write_polyline(path) -> None:
    path.write_text(
        json.dumps(
            {
                "polyline": [
                    {"x": 0.0, "y": 0.0, "way_name": "Straight"},
                    {"x": 100.0, "y": 0.0, "way_name": "Straight"},
                    {"x": 100.0, "y": 100.0, "way_name": "Turn"},
                    {"x": 0.0, "y": 100.0, "way_name": "Turn"},
                ]
            }
        ),
        encoding="utf-8",
    )


def test_import_banking_zones_writes_source_station_profile(monkeypatch, tmp_path) -> None:
    polyline = tmp_path / "centerline.json"
    zones = tmp_path / "zones.json"
    output = tmp_path / "banking-profile.json"
    report = tmp_path / "banking-report.json"
    overlay = tmp_path / "banking.svg"
    write_polyline(polyline)
    zones.write_text(
        json.dumps(
            {
                "zones": [
                    {
                        "name": "Turn",
                        "source_start_station_m": 80.0,
                        "source_end_station_m": 180.0,
                        "banking_start_deg": 0.0,
                        "banking_peak_deg": 12.0,
                        "banking_end_deg": 0.0,
                        "transition_in_m": 20.0,
                        "transition_out_m": 20.0,
                        "confidence": 0.75,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        run_tool(
            monkeypatch,
            "--polyline",
            str(polyline),
            "--zones",
            str(zones),
            "--output",
            str(output),
            "--sample-step",
            "20",
            "--report",
            str(report),
            "--overlay",
            str(overlay),
        )
        == 0
    )

    profile = json.loads(output.read_text(encoding="utf-8"))
    assert profile["type"] == "road-surface-profile"
    assert profile["station_frame"] == "source"
    assert profile["source_total_length_m"] == pytest.approx(400.0)
    samples = profile["banking_profile"]["samples"]
    assert len(samples) >= 20
    assert max(sample["banking_deg"] for sample in samples) == pytest.approx(12.0)
    assert all("source_station_m" in sample for sample in samples)

    report_data = json.loads(report.read_text(encoding="utf-8"))
    assert report_data["zone_count"] == 1
    assert report_data["overlap_count"] == 0
    assert overlay.exists()


def test_import_banking_zones_rejects_empty_zone_file(monkeypatch, tmp_path) -> None:
    polyline = tmp_path / "centerline.json"
    zones = tmp_path / "zones.json"
    write_polyline(polyline)
    zones.write_text(json.dumps({"zones": []}), encoding="utf-8")

    with pytest.raises(SystemExit, match="No banking zones"):
        run_tool(monkeypatch, "--polyline", str(polyline), "--zones", str(zones), "--output", str(tmp_path / "out.json"))


def test_zero_length_banking_zone_spans_full_lap() -> None:
    zone = {
        "source_start_station_m": 0.0,
        "source_end_station_m": 0.0,
        "banking_deg": 7.0,
    }

    assert import_banking_zones.zone_banking(zone, 0.0, 400.0) == pytest.approx(7.0)
    assert import_banking_zones.zone_banking(zone, 100.0, 400.0) == pytest.approx(7.0)
    assert import_banking_zones.zone_banking(zone, 399.0, 400.0) == pytest.approx(7.0)
