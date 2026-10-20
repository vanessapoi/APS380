# /***************************************************************************
#     file                 : test_track_georeference.py
#     created              : 24 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2, or (at your option) any later version.

import hashlib
import json
import math
import xml.etree.ElementTree as ET

import pytest

from torcs_track_tools.cli import apply_segments, georeference_track
from torcs_track_tools.core.overlay import parse_track_segments, torcs_points
from torcs_track_tools.core.polyline import lonlat_from_xy
from torcs_track_tools.core.track_georeference import (
    fit_reference,
    geographic_polyline,
    insert_reference,
    invalidate_reference_text,
    profile_altitude,
    reference_at_pose,
    reference_for_segment,
    reference_from_profile,
    refresh_reference,
    sample_absolute_raster,
    track_plan_sha256,
    update_elevation_reference,
)


def track_and_source():
    # Rounded scalene triangle: no half-lap rotational symmetry.
    turn1 = math.pi - math.atan2(200, 300)
    turn2 = 1.5 * math.pi - turn1
    trims = [10, 10 * math.tan(turn1 / 2), 10 * math.tan(turn2 / 2)]
    lengths = [300 - trims[0] - trims[1], math.hypot(300, 200) - trims[1] - trims[2], 200 - trims[2] - trims[0]]
    turns = [math.degrees(turn1), math.degrees(turn2), 90]
    parts = []
    for i in range(3):
        parts.append(f'<section name="s{i}"><attstr name="type" val="str"/><attnum name="lg" val="{lengths[i]}"/></section>')
        parts.append(f'<section name="t{i}"><attstr name="type" val="lft"/><attnum name="radius" val="10"/><attnum name="arc" unit="deg" val="{turns[i]}"/></section>')
    xml = '<params><section name="Main Track"><section name="Track Segments">' + ''.join(parts) + '</section></section></params>'
    source = []
    theta = math.radians(32)
    for p in torcs_points(parse_track_segments(xml), 0.5)[:-1]:
        x = p["x"] * math.cos(theta) - p["y"] * math.sin(theta)
        y = p["x"] * math.sin(theta) + p["y"] * math.cos(theta)
        lat, lon = lonlat_from_xy((x, y), {"lat": 45, "lon": 7})
        source.append({"lat": lat, "lon": lon})
    return xml, source


@pytest.mark.parametrize("reverse", [False, True])
def test_reference_recovers_shifted_source_and_true_bearing(reverse):
    xml, points = track_and_source()
    points = points[235:] + points[:235]
    if reverse:
        points.reverse()
    geo, report = fit_reference(xml, {"polyline": points})
    assert geo["latitude"] == pytest.approx(45, abs=2e-6)  # About 20 cm.
    assert geo["longitude"] == pytest.approx(7, abs=2e-6)
    assert geo["heading"] == pytest.approx(58, abs=0.03)
    assert report["source_reversed"] == reverse
    assert report["rmse_m"] < 0.1
    assert "altitude" not in geo


def test_rejects_unknown_frame_and_degenerate_or_bad_source():
    with pytest.raises(ValueError, match="CRS"):
        geographic_polyline({"polyline": [{"x": i, "y": 0} for i in range(3)]})
    xml, points = track_and_source()
    with pytest.raises(ValueError, match="Degenerate"):
        fit_reference(xml, {"polyline": [points[0]] * 4})
    with pytest.raises(ValueError, match="RMSE"):
        fit_reference(xml, {"polyline": [{"lat": 45 + (p["lat"] - 45) * 2, "lon": p["lon"]} for p in points]}, max_rmse=1)


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_metadata_only_insertion_preserves_every_original_byte(newline):
    original = b'\xef\xbb\xbf<?xml version="1.0"?>\n<!DOCTYPE params [<!ENTITY test "hello">]>\n<params>\n<!-- keep --> &test;\n</params>\n'.replace(b"\n", newline)
    updated = insert_reference(original, {"latitude": 0, "longitude": 0, "heading": 0, "altitude": -12})
    start = updated.index(b'  <section name="Georeference">')
    end = updated.index(b"</section>", start) + len(b"</section>") + len(newline)
    assert updated[:start] + updated[end:] == original
    with pytest.raises(ValueError, match="already exists"):
        insert_reference(updated, {"latitude": 1})


def test_assembly_references_selected_start_and_drops_template_location(tmp_path, monkeypatch):
    xml, points = track_and_source()
    template = tmp_path / "template.xml"
    snippet = tmp_path / "segments.xml"
    output = tmp_path / "out.xml"
    template.write_bytes(insert_reference(xml.encode(), {"latitude": -30, "longitude": -60, "altitude": 999}))
    segments = ET.fromstring(xml).find(".//section[@name='Track Segments']")
    snippet.write_text("\n".join(ET.tostring(seg, encoding="unicode") for seg in segments))
    snippet.with_suffix(".json").write_text(json.dumps({"georeference_source": {"polyline": points},
        "georeference_snippet_sha256": hashlib.sha256(snippet.read_text().encode()).hexdigest()}))
    monkeypatch.setattr("sys.argv", ["apply-segments", "--template-xml", str(template), "--segments-xml", str(snippet),
                                   "--output-xml", str(output), "--author", "Test Author", "--start-segment", "s1"])
    assert apply_segments.main() == 0
    root = ET.parse(output).getroot()
    geo = root.find("section[@name='Georeference']")
    assert geo is not None
    values = {a.get("name"): float(a.get("val")) for a in geo}
    assert 44.99 < values["latitude"] < 45.01
    assert values["longitude"] > 7.001
    assert "altitude" not in values
    assert abs(values["heading"] - 58) > 90
    snippet.with_suffix(".json").unlink()
    assert apply_segments.main() == 0
    assert ET.parse(output).getroot().find("section[@name='Georeference']") is None


def test_layout_invalidation_and_relative_elevation_clear_stale_metadata():
    xml = insert_reference(b"<params></params>", {"latitude": 45, "longitude": 7, "heading": 58, "altitude": 123}).decode()
    root = ET.fromstring(xml)
    update_elevation_reference(root, [])
    assert root.find("section/attnum[@name='altitude']") is None
    assert root.find("section/attnum[@name='latitude']") is not None
    update_elevation_reference(root, [(100, 1), (110, 3)])
    assert float(root.find("section/attnum[@name='altitude']").get("val")) == pytest.approx(107.5)
    assert "Georeference" not in invalidate_reference_text(xml)


def test_absolute_corridor_altitude_uses_source_station_not_first_sample(tmp_path):
    xml, points = track_and_source()
    points = points[len(points)//3:] + points[:len(points)//3]
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"polyline": points}))
    _, fit = fit_reference(xml, {"polyline": points})
    data = {"source": {"type": "dem-corridor", "polyline": str(source)}, "total_length_m": 1000,
            "road_profile": {"samples": [{"station_m": 0, "elevation_m": 100}, {"station_m": 500, "elevation_m": 200}]}}
    value, report = profile_altitude(tmp_path / "profile.json", data, {}, xml)
    s = fit["source_phase_fraction"] * 1000
    expected = 100 + 0.2 * min(s, 1000-s)
    assert value == pytest.approx(expected)
    assert value > 110
    assert report["method"] == "absolute-dem-corridor"


def test_known_fitter_pose_survives_start_rotation_without_shape_matching():
    xml, _ = track_and_source()
    segments = ET.fromstring(xml).find(".//section[@name='Track Segments']")
    snippet = "".join(ET.tostring(s, encoding="unicode") for s in segments)
    original = {"latitude": 45, "longitude": 7, "heading": 58}
    assert reference_for_segment(snippet, "s0", original) == pytest.approx(original)
    shifted = reference_for_segment(snippet, "s1", original)
    expected_turn = 180 - math.degrees(math.atan2(200, 300))
    assert shifted["heading"] == pytest.approx((58 - expected_turn) % 360)
    assert shifted["latitude"] > 45
    assert shifted["longitude"] > 7


def test_projected_pose_uses_crs_and_grid_convergence():
    data = {"source": {"crs": "EPSG:32632"}, "polyline": [{"x": 500000, "y": 0}]}
    geo = reference_at_pose(data, 500000, 0, 0)
    assert geo == pytest.approx({"latitude": 0, "longitude": 9, "heading": 90}, abs=1e-7)
    geo = reference_at_pose(data, 700000, 5000000, 0)
    assert abs(geo["heading"] - 90) > 1  # Grid north is not true north here.


def test_dem_fallback_samples_anchor_and_rejects_nodata(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    raster = tmp_path / "dem.tif"
    values = np.array([[10, 20], [30, 40]], dtype="float32")
    with rasterio.open(raster, "w", driver="GTiff", width=2, height=2, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(7, 46, 0.01, 0.01), nodata=-9999) as dataset:
        dataset.write(values, 1)
    data = {"type": "raster-dem-profile", "zero_elevation_m": 999, "raster": str(raster)}
    geo = {"latitude": 45.99, "longitude": 7.01}
    value, _ = sample_absolute_raster(tmp_path / "profile.json", data, geo)
    assert value == pytest.approx(25, abs=1e-6)  # Not the stale profile's 999 m baseline.
    with rasterio.open(raster, "r+") as dataset:
        values[0, 0] = -9999
        dataset.write(values, 1)
    with pytest.raises(ValueError, match="Missing elevation"):
        sample_absolute_raster(tmp_path / "profile.json", data, geo)


def test_cli_dry_run_write_and_repeat_are_metadata_only(tmp_path, monkeypatch):
    xml, points = track_and_source()
    xml = xml.replace("<params>", '<params><section name="Header"><attnum name="version" val="4"/></section>')
    track = tmp_path / "track.xml"
    source = tmp_path / "centerline.json"
    report = tmp_path / "report.json"
    track.write_bytes(xml.encode())
    source.write_text(json.dumps({"polyline": points}))
    argv = ["georeference-track", "--track-xml", str(track), "--source", str(source), "--report", str(report)]
    monkeypatch.setattr("sys.argv", argv)
    assert georeference_track.main() == 0
    assert track.read_bytes() == xml.encode()
    assert json.loads(report.read_text())[0]["status"] == "ready"
    monkeypatch.setattr("sys.argv", [*argv, "--write"])
    assert georeference_track.main() == 0
    updated = track.read_bytes()
    record = json.loads(report.read_text())[0]
    assert record["metadata_only_verified"]
    assert record["original_sha256"] == hashlib.sha256(xml.encode()).hexdigest()
    assert record["updated_sha256"] == hashlib.sha256(updated).hexdigest()
    assert "altitude" not in record["reference"]
    assert georeference_track.main() == 0
    assert track.read_bytes() == updated
    assert json.loads(report.read_text())[0]["status"] == "already-present"


def test_refresh_unchanged_layout_preserves_altitude_after_section_invalidation(tmp_path):
    xml, points = track_and_source()
    original = insert_reference(xml.encode(), {"latitude": 45, "longitude": 7, "heading": 58, "altitude": 123}).decode()
    track, source = tmp_path / "track.xml", tmp_path / "source.json"
    source.write_text(json.dumps({"polyline": points}))
    track.write_text(original)
    refresh_reference(track, source)
    assert float(ET.parse(track).find("section/attnum[@name='altitude']").get("val")) == pytest.approx(123)
    # Closure may rebuild segment text and remove the section despite leaving
    # the final ordered geometry unchanged. Its pre-edit snapshot retains the datum.
    track.write_text(invalidate_reference_text(original))
    refresh_reference(track, source, previous_xml=original)
    assert float(ET.parse(track).find("section/attnum[@name='altitude']").get("val")) == pytest.approx(123)


@pytest.mark.parametrize("change", ["start", "elevation"])
def test_refresh_invalidates_altitude_when_reference_changes(tmp_path, change):
    xml, points = track_and_source()
    original = insert_reference(xml.encode(), {"latitude": 45, "longitude": 7, "heading": 58, "altitude": 123}).decode()
    root = ET.fromstring(original)
    sections = root.find(".//section[@name='Track Segments']")
    if change == "start":
        segs = list(sections)
        sections[:] = segs[2:] + segs[:2]
    else:
        ET.SubElement(sections[0], "attnum", {"name": "z start", "unit": "m", "val": "10"})
    track, source = tmp_path / "track.xml", tmp_path / "source.json"
    track.write_text(ET.tostring(root, encoding="unicode"))
    source.write_text(json.dumps({"polyline": points}))
    refresh_reference(track, source, previous_xml=original)
    assert ET.parse(track).find("section/attnum[@name='altitude']") is None
    assert ET.parse(track).find("section/attnum[@name='latitude']") is not None


def test_all_curve_assembly_uses_actual_first_segment(tmp_path, monkeypatch):
    snippet = ''.join(f'<section name="curve{i}"><attstr name="type" val="lft"/><attnum name="radius" val="100"/><attnum name="arc" unit="deg" val="90"/></section>' for i in range(4))
    template, segments, output = tmp_path / "template.xml", tmp_path / "segments.xml", tmp_path / "out.xml"
    template.write_text('<params><section name="Main Track"><section name="Track Segments">' + snippet + '</section></section></params>')
    segments.write_text(snippet)
    _, points = track_and_source()
    start = {"latitude": 45, "longitude": 7, "heading": 90}
    segments.with_suffix(".json").write_text(json.dumps({
        "georeference_source": {"polyline": points}, "georeference_start": start,
        "georeference_snippet_sha256": hashlib.sha256(snippet.encode()).hexdigest(),
    }))
    monkeypatch.setattr("sys.argv", ["apply-segments", "--template-xml", str(template), "--segments-xml", str(segments),
                                   "--output-xml", str(output), "--author", "Test Author"])
    assert apply_segments.main() == 0
    geo = ET.parse(output).find("section[@name='Georeference']")
    assert {a.get("name"): float(a.get("val")) for a in geo} == pytest.approx(start)
    with pytest.raises(ValueError, match="Reference segment not found"):
        reference_for_segment(snippet, "missing", start)


def test_profile_fingerprint_rejects_relocated_live_xml_and_legacy_profile(tmp_path):
    import rasterio
    from rasterio.transform import from_origin

    xml, _ = track_and_source()
    track = tmp_path / "live.xml"
    track.write_text(xml)
    raster = tmp_path / "dem.tif"
    with rasterio.open(raster, "w", driver="GTiff", width=2, height=2, count=1, dtype="float32",
                       crs="EPSG:32632", transform=from_origin(500000, 5000000, 1, 1)):
        pass
    data = {"type": "raster-dem-profile", "track_xml": str(track), "raster": str(raster),
            "track_plan_sha256": track_plan_sha256(xml),
            "fit": {"rmse_m": 1, "offset_x": 500000, "offset_y": 5000000, "cos": 1, "sin": 0, "scale": 1}}
    profile = tmp_path / "profile.json"
    old, _ = reference_from_profile(xml, data, profile, 20)
    root = ET.fromstring(xml)
    sections = root.find(".//section[@name='Track Segments']")
    ET.SubElement(sections[0], "attnum", {"name": "z start", "val": "10", "unit": "m"})
    elevated = ET.tostring(root, encoding="unicode")
    track.write_text(elevated)
    new, _ = reference_from_profile(elevated, data, profile, 20)
    assert new == old  # Elevation does not change the horizontal fit.
    segs = list(sections)
    sections[:] = segs[2:] + segs[:2]
    updated = ET.tostring(root, encoding="unicode")
    track.write_text(updated)
    with pytest.raises(ValueError, match="layout no longer matches"):
        reference_from_profile(updated, data, profile, 20)
    del data["track_plan_sha256"]
    with pytest.raises(ValueError, match="no immutable layout fingerprint"):
        reference_from_profile(updated, data, profile, 20)


def test_layout_fingerprint_includes_units_but_ignores_formatting_and_elevation():
    xml, _ = track_and_source()
    root = ET.fromstring(xml)
    signature = track_plan_sha256(xml)
    ET.indent(root)
    assert track_plan_sha256(ET.tostring(root, encoding="unicode")) == signature
    root.find(".//attnum[@name='arc']").set("unit", "rad")
    assert track_plan_sha256(ET.tostring(root, encoding="unicode")) != signature
