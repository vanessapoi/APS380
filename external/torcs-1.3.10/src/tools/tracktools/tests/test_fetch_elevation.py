# /***************************************************************************
#
#     file                 : test_fetch_elevation.py
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

import torcs_track_tools.cli.fetch_elevation as fetch_elevation


def test_query_provider_formats_url_and_parses_elevations(monkeypatch) -> None:
    seen_urls = []

    def fake_fetch_json(url):
        seen_urls.append(url)
        return {"status": "OK", "results": [{"elevation": "12.5"}, {"elevation": 13}]}

    monkeypatch.setattr(fetch_elevation, "fetch_json", fake_fetch_json)

    elevations = fetch_elevation.query_provider(
        [{"lat": 50.0, "lon": 1.0}, {"lat": 51.25, "lon": 2.5}],
        "https://example.test/elev/",
        retries=1,
        retry_delay=0.0,
    )

    assert elevations == [12.5, 13.0]
    assert seen_urls == ["https://example.test/elev?locations=50.0000000,1.0000000|51.2500000,2.5000000"]


def test_fetch_elevation_builds_corridor_cache(monkeypatch, tmp_path) -> None:
    source = tmp_path / "centerline.json"
    output = tmp_path / "elevation.json"
    source.write_text(
        json.dumps(
            {
                "polyline": [
                    {"lat": 50.0, "lon": 1.0},
                    {"lat": 50.0, "lon": 1.001},
                    {"lat": 50.001, "lon": 1.001},
                    {"lat": 50.001, "lon": 1.0},
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_query(locations, provider_url, retries, retry_delay):
        return [100.0 + float(item["lat"]) * 0.1 + float(item["lon"]) * 0.01 for item in locations]

    monkeypatch.setattr(fetch_elevation, "query_provider", fake_query)
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-fetch-elevation",
            "--polyline",
            str(source),
            "--output",
            str(output),
            "--sample-step",
            "80",
            "--distances",
            "20,60",
        ],
    )

    assert fetch_elevation.main() == 0

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["source"]["type"] == "dem-corridor"
    assert len(data["road_profile"]["samples"]) >= 3
    assert [line["side"] for line in data["terrain_lines"]] == ["center", "left", "left", "right", "right"]
    assert data["terrain_lines"][1]["distance_m"] == 20.0
    assert "road_start_elevation_m" in data["normalization"]


def test_fetch_elevation_road_only_skips_offset_lines(monkeypatch, tmp_path) -> None:
    source = tmp_path / "centerline.json"
    output = tmp_path / "elevation-road.json"
    source.write_text(
        json.dumps(
            {
                "polyline": [
                    {"lat": 50.0, "lon": 1.0},
                    {"lat": 50.0, "lon": 1.001},
                    {"lat": 50.001, "lon": 1.001},
                    {"lat": 50.001, "lon": 1.0},
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_query(locations, provider_url, retries, retry_delay):
        return [100.0 + i for i, _ in enumerate(locations)]

    monkeypatch.setattr(fetch_elevation, "query_provider", fake_query)
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-fetch-elevation",
            "--polyline",
            str(source),
            "--output",
            str(output),
            "--sample-step",
            "80",
            "--road-only",
        ],
    )

    assert fetch_elevation.main() == 0

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["source"]["road_only"]
    assert data["source"]["distances_m"] == []
    assert [line["side"] for line in data["terrain_lines"]] == ["center"]
