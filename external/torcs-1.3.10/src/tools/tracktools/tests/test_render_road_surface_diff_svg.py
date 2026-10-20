# /***************************************************************************
#
#     file                 : test_render_road_surface_diff_svg.py
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

import torcs_track_tools.cli.render_road_surface_diff_svg as render_road_surface_diff_svg


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-render-road-surface-diff-svg", *args])
    return render_road_surface_diff_svg.main()


def write_track(path, banking: float = 5.0) -> None:
    path.write_text(
        f"""
<params name="Road Surface Unit">
  <section name="Main Track">
    <attnum name="width" unit="m" val="10"/>
    <section name="Track Segments">
      <section name="uphill">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="100"/>
        <attnum name="z start" unit="m" val="0"/>
        <attnum name="z end" unit="m" val="10"/>
        <attnum name="banking start" unit="deg" val="{banking}"/>
        <attnum name="banking end" unit="deg" val="{banking}"/>
      </section>
      <section name="downhill">
        <attstr name="type" val="str"/>
        <attnum name="lg" unit="m" val="100"/>
        <attnum name="z start" unit="m" val="10"/>
        <attnum name="z end" unit="m" val="0"/>
        <attnum name="banking start" unit="deg" val="{banking}"/>
        <attnum name="banking end" unit="deg" val="{banking}"/>
      </section>
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )


def write_surface_profile(path, include_elevation: bool = True, banking: float = 5.0, real_width: float = 0.0) -> None:
    data = {
        "type": "road-surface-profile",
        "station_frame": "xml",
        "banking_profile": {
            "samples": [
                {"station_m": 0.0, "banking_deg": banking},
                {"station_m": 200.0, "banking_deg": banking},
            ]
        },
    }
    if real_width > 0.0:
        data["sampling"] = {"real_road_width_m": real_width}
    if include_elevation:
        data["elevation_profile"] = {
            "samples": [
                {"station_m": 0.0, "elevation_m": 0.0},
                {"station_m": 100.0, "elevation_m": 10.0},
                {"station_m": 200.0, "elevation_m": 0.0},
            ]
        }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_road_surface_diff_reports_center_edges_and_bank_match(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    profile = tmp_path / "profile.json"
    output = tmp_path / "road-surface-diff.svg"
    report = tmp_path / "road-surface-diff-report.json"
    write_track(track_xml, banking=5.0)
    write_surface_profile(profile, include_elevation=True, banking=5.0)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile),
            "--output",
            str(output),
            "--report",
            str(report),
            "--sample-step",
            "50",
            "--label-top",
            "1",
        )
        == 0
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["sample_count"] == 4
    assert data["color_mode"] == "center"
    assert data["metrics"]["center"]["max_abs"] == pytest.approx(0.0)
    assert data["metrics"]["left"]["max_abs"] == pytest.approx(0.0)
    assert data["metrics"]["right"]["max_abs"] == pytest.approx(0.0)
    assert data["metrics"]["bank"]["max_abs"] == pytest.approx(0.0)
    assert len(data["top_abs_samples"]) == 1
    assert "Road surface diff" in output.read_text(encoding="utf-8")


def test_road_surface_diff_supports_banking_only_profiles(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    profile = tmp_path / "profile.json"
    report = tmp_path / "road-surface-diff-report.json"
    write_track(track_xml, banking=7.0)
    write_surface_profile(profile, include_elevation=False, banking=5.0)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile),
            "--output",
            str(tmp_path / "road-surface-diff.svg"),
            "--report",
            str(report),
            "--sample-step",
            "50",
        )
        == 0
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["color_mode"] == "bank"
    assert data["metrics"]["center"]["count"] == 0
    assert data["metrics"]["bank"]["mean"] == pytest.approx(2.0)
    assert data["metrics"]["bank"]["max_abs"] == pytest.approx(2.0)


def test_road_surface_diff_edge_delta_policy_scales_profile_banking(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    profile = tmp_path / "profile.json"
    report = tmp_path / "road-surface-diff-report.json"
    applied_banking = render_road_surface_diff_svg.apply_elevation.scale_banking_for_width(
        10.0,
        8.0,
        10.0,
        type("Args", (), {"bank_width_policy": "edge-delta", "bank_max_abs_deg": 45.0})(),
    )
    write_track(track_xml, banking=applied_banking)
    write_surface_profile(profile, include_elevation=True, banking=10.0, real_width=8.0)

    assert (
        run_tool(
            monkeypatch,
            "--track-xml",
            str(track_xml),
            "--profile",
            str(profile),
            "--output",
            str(tmp_path / "road-surface-diff.svg"),
            "--report",
            str(report),
            "--sample-step",
            "50",
            "--bank-width-policy",
            "edge-delta",
        )
        == 0
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["bank_width_policy"] == "edge-delta"
    assert data["bank_real_width_m"] == pytest.approx(8.0)
    assert data["metrics"]["left"]["max_abs"] == pytest.approx(0.0, abs=1e-12)
    assert data["metrics"]["right"]["max_abs"] == pytest.approx(0.0, abs=1e-12)
    assert data["metrics"]["bank"]["max_abs"] == pytest.approx(0.0, abs=1e-12)
