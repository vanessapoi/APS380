# /***************************************************************************
#     file                 : test_track_loader_probe.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

import copy
import ctypes as C
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from torcs_track_tools.core import track_loader_probe as probe_module
from torcs_track_tools.core.radius_pits import configure_pit_markers
from torcs_track_tools.core.radius_repair import apply_parameters, selected_sections
from torcs_track_tools.core.radius_sampling import configure_sampling
from torcs_track_tools.core.track_loader_probe import Symbols, TrackLoaderProbe, relocated_entities


@pytest.fixture
def native_build():
    root = Path(__file__).resolve().parents[4]
    runtime = root / "runtime"
    symbols = root / "src/modules/track/Release"
    if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
        pytest.skip("Requires a Windows x64 development build")
    if not (runtime / "modules/track/track.dll").is_file() or not (symbols / "track.pdb").is_file():
        pytest.skip("Build the x64 Release track module to run the native probe tests")
    return runtime, symbols


def fixture_xml():
    return '''<params name="probe"><section name="Header">
    <attstr name="name" val="probe"/><attstr name="category" val="road"/>
    <attnum name="version" val="4"/></section><section name="Main Track">
    <attnum name="width" unit="m" val="12"/>
    <section name="Right Side"><attnum name="width" unit="m" val="7"/></section>
    <section name="Track Segments"><section name="lead">
    <attstr name="type" val="str"/><attnum name="lg" unit="m" val="20"/>
    </section><section name="corner"><attstr name="type" val="lft"/>
    <attnum name="radius" unit="m" val="100"/><attnum name="arc" unit="deg" val="90"/>
    <section name="Right Border"><attnum name="width" unit="m" val="0.5"/>
    <attnum name="height" unit="m" val="1"/><attstr name="style" val="wall"/></section>
    </section><section name="tail"><attstr name="type" val="str"/>
    <attnum name="lg" unit="m" val="30"/></section></section></section></params>'''


def test_native_probe_uses_matching_layout_and_copies_geometry(native_build, tmp_path):
    runtime, symbols = native_build
    source = tmp_path / "source.xml"
    source.write_text(fixture_xml())
    probe = TrackLoaderProbe(runtime, symbols, source, tmp_path / "trial.xml")
    try:
        first = probe.load(source.read_text())
        assert [r["name"] for r in first["rows"]] == ["lead", "corner", "tail"]
        assert first["pit_count"] == 0 and first["wall_runs"] == 1
        corner = first["rows"][1]
        assert corner["length"] == pytest.approx(100*math.pi/2, abs=1e-4)
        assert corner["end_angle"] == pytest.approx(math.pi/2, abs=1e-6)
        assert first["rows"][-1]["end"][:2] == pytest.approx([120, 130], abs=1e-4)
        assert np.linalg.norm(corner["vertices"][0]-corner["vertices"][1]) == pytest.approx(12, abs=1e-5)
        second = probe.load(source.read_text().replace('val="30"', 'val="40"'))
        assert second["rows"][-1]["end"][1]-first["rows"][-1]["end"][1] == pytest.approx(10, abs=1e-4)
        assert first["rows"][-1]["end"][1] == pytest.approx(130, abs=1e-4)
        for expected in first["rows"]:
            endpoint = probe.endpoint(source.read_text(), expected["name"])
            assert np.array_equal(endpoint["end"], expected["end"])
            assert endpoint["end_angle"] == expected["end_angle"]
        with pytest.raises(ValueError, match="not found"):
            probe.endpoint(source.read_text(), "missing")
    finally:
        probe.close()


def test_symbols_fail_explicitly_for_missing_type(native_build):
    runtime, directory = native_build
    symbols = Symbols(runtime / "modules/track/track.dll", directory)
    try:
        with pytest.raises(RuntimeError, match="does not expose"):
            symbols.fields("NoSuchTorcsTrackType")
    finally:
        symbols.close()


def test_native_implicit_flat_replacement_preserves_zero_road_heights(native_build, tmp_path):
    runtime, symbols = native_build
    root = ET.fromstring(fixture_xml())
    corner = root.find("section[@name='Main Track']/section[@name='Track Segments']/section[@name='corner']")
    corner.remove(corner.find("section"))
    corner.find("attnum[@name='radius']").set("val", "5000")
    corner.find("attnum[@name='arc']").set("val", "0.3")
    text = ET.tostring(root, encoding="unicode")
    selected = selected_sections(text, ["corner"], "scs")
    candidate = apply_parameters(text, selected, {"corner": [2., .005, 2.]})
    probe = TrackLoaderProbe(runtime, symbols, tmp_path/"source.xml", tmp_path/"trial.xml")
    try:
        for xml in (text, candidate):
            model = probe.load(xml)
            assert all(np.max(np.abs(row["vertices"][:, 2])) <= 1e-6 for row in model["rows"])
    finally:
        probe.close()


@pytest.mark.parametrize("role,native_name", [("entry", "pitEntry"), ("exit", "pitExit")])
def test_native_pit_reference_keeps_original_marker_length(native_build, tmp_path, role, native_name):
    runtime, symbols = native_build
    root = ET.fromstring(fixture_xml())
    main = root.find("section[@name='Main Track']")
    ET.SubElement(main, "attnum", name="profil steps length", unit="m", val="2")
    pits = ET.SubElement(main, "section", name="Pits")
    for name, target in [("entry", "lead"), ("exit", "tail"), ("start", "lead"), ("end", "tail")]:
        ET.SubElement(pits, "attstr", name=name, val="corner" if name == role else target)
    corner = main.find("section[@name='Track Segments']/section[@name='corner']")
    corner.remove(corner.find("section"))
    corner.find("attnum[@name='radius']").set("val", "50000")
    corner.find("attnum[@name='arc']").set("val", "0.03")
    text = ET.tostring(root, encoding="unicode")
    selected = selected_sections(text, ["corner"], "scs")
    probe = TrackLoaderProbe(runtime, symbols, tmp_path/"source.xml", tmp_path/"trial.xml")
    try:
        before = probe.load(text)
        configure_pit_markers(selected["corner"], [r for r in before["rows"] if r["name"] == "corner"])
        candidate = apply_parameters(text, selected, {"corner": [12., .00052, 12.]})
        after = probe.load(candidate)
        old, new = before["pit_markers"][native_name], after["pit_markers"][native_name]
        assert new["length"] == old["length"]
        assert new["race_info"] == old["race_info"]
        assert new["name"] == ("corner" if role == "entry" else "corner:radius-out")
        assert len([r for r in after["rows"] if r["name"] == new["name"]]) == 1
        assert old["length"] < 2.1
    finally:
        probe.close()


@pytest.mark.parametrize("side,index", [("Right", 0), ("Left", 1)])
def test_native_scs_parts_keep_planar_reset_after_curb(native_build, tmp_path, side, index):
    runtime, symbols = native_build
    root = ET.fromstring(fixture_xml().replace("Right", side))
    segments = root.find("section[@name='Main Track']/section[@name='Track Segments']")
    lead, corner, _ = list(segments)
    corner.find("attnum[@name='radius']").set("val", "5000")
    corner.find("attnum[@name='arc']").set("val", "0.3")
    border = corner.find(f"section[@name='{side} Border']")
    border.find("attnum[@name='height']").set("val", "0.04")
    border.find("attstr[@name='style']").set("val", "plan")
    ET.SubElement(border, "attstr", name="surface", val="b-road1-grass6")
    curb = copy.deepcopy(border)
    curb.find("attstr[@name='style']").set("val", "curb")
    lead.append(curb)
    for key, unit in [("z start", "m"), ("z end", "m"), ("profil start tangent", "%"), ("profil end tangent", "%")]:
        ET.SubElement(corner, "attnum", name=key, unit=unit, val="0")
    ET.SubElement(corner, "attstr", name="profil", val="spline")
    text = ET.tostring(root, encoding="unicode")
    selected = selected_sections(text, ["corner"], "scs")
    candidate = apply_parameters(text, selected, {"corner": [2., .005, 2.]})
    probe = TrackLoaderProbe(runtime, symbols, tmp_path / "source.xml", tmp_path / "trial.xml")
    try:
        model = probe.load(candidate)
        assert len(model["rows"]) == 5
        endpoint = probe.endpoint(candidate, "corner")
        assert np.array_equal(endpoint["end"], model["rows"][3]["end"])
        assert endpoint["end_angle"] == model["rows"][3]["end_angle"]
        track_ptr = probe.build(probe.trial.as_posix().encode())
        segment = probe.read(track_ptr, probe.track["seg"], C.c_void_p)
        for expected_style in [1, 0, 0, 0, 0]:
            segment = probe.read(segment, probe.seg["next"], C.c_void_p)
            actual_border = probe.read(segment, probe.seg["side"] + index*8, C.c_void_p)
            assert probe.read(actual_border, probe.seg["style"], C.c_int) == expected_style
            assert probe.read(actual_border, probe.seg["width"]) == pytest.approx(.5, abs=1e-6)
            assert probe.read(actual_border, probe.seg["height"]) == pytest.approx(.04, abs=1e-6)
    finally:
        probe.close()


def test_unsupported_platform_fails_before_loading_native_code(monkeypatch, tmp_path):
    monkeypatch.setattr(probe_module, "os", SimpleNamespace(name="posix"))
    with pytest.raises(RuntimeError, match="Windows x64"):
        TrackLoaderProbe(tmp_path, tmp_path, tmp_path / "source.xml", tmp_path / "trial.xml")


def test_native_banked_parts_follow_original_edge_hermite(native_build, tmp_path):
    runtime, symbols = native_build
    root = ET.fromstring(fixture_xml())
    main = root.find("section[@name='Main Track']")
    ET.SubElement(main, "attnum", name="profil steps length", unit="m", val="2")
    corner = main.find("section[@name='Track Segments']/section[@name='corner']")
    corner.remove(corner.find("section[@name='Right Border']"))
    corner.find("attnum[@name='radius']").set("val", "5000")
    corner.find("attnum[@name='arc']").set("val", "0.3")
    for name, unit, value in [("z start", "m", 1), ("z end", "m", 2),
                              ("profil start tangent", "%", 3), ("profil end tangent", "%", -1),
                              ("banking start", "deg", 2), ("banking end", "deg", -3)]:
        ET.SubElement(corner, "attnum", name=name, unit=unit, val=str(value))
    ET.SubElement(corner, "attstr", name="profil", val="spline")
    text = ET.tostring(root, encoding="unicode")
    meta = selected_sections(text, ["corner"], "scs")
    candidate = apply_parameters(text, meta, {"corner": [4., .003, 4.]})
    probe = TrackLoaderProbe(runtime, symbols, tmp_path / "source.xml", tmp_path / "trial.xml")
    try:
        model = probe.load(candidate)
        parts = [r for r in model["rows"] if r["name"].startswith("corner")]
        length = sum(r["length"] for r in parts)
        position = 0.
        for part in parts:
            position += part["length"]
            t = position/length
            for side, sign in [(0, 1), (1, -1)]:
                start_z = 1+sign*6*math.tan(math.radians(2))
                end_z = 2+sign*6*math.tan(math.radians(-3))
                expected = (2*t**3-3*t*t+1)*start_z + (t**3-2*t*t+t)*length*.03 + (-2*t**3+3*t*t)*end_z - (t**3-t*t)*length*.01
                assert part["vertices"][side+2, 2] == pytest.approx(expected, abs=1e-5)
    finally:
        probe.close()


def test_native_taper_replays_previous_end_width_and_preserves_following_side(native_build, tmp_path):
    runtime, symbols = native_build
    root = ET.fromstring(fixture_xml())
    main = root.find("section[@name='Main Track']")
    lead, corner, _ = list(main.find("section[@name='Track Segments']"))
    lead_side = ET.SubElement(lead, "section", name="Right Side")
    ET.SubElement(lead_side, "attnum", name="end width", unit="m", val="12")
    side = ET.SubElement(corner, "section", name="Right Side")
    ET.SubElement(side, "attnum", name="width", unit="m", val="7")
    corner.remove(corner.find("section[@name='Right Border']"))
    corner.find("attnum[@name='radius']").set("val", "5000")
    corner.find("attnum[@name='arc']").set("val", "0.3")
    for key, unit in [("z start", "m"), ("z end", "m"), ("profil start tangent", "%"), ("profil end tangent", "%")]:
        ET.SubElement(corner, "attnum", name=key, unit=unit, val="0")
    ET.SubElement(corner, "attstr", name="profil", val="spline")
    text = ET.tostring(root, encoding="unicode")
    selected = selected_sections(text, ["corner"], "scs")
    assert selected["corner"]["side_profiles"]["Right Side"] == {"start": 12., "end": 7.}
    candidate = apply_parameters(text, selected, {"corner": [2., .002, 2.]})
    probe = TrackLoaderProbe(runtime, symbols, tmp_path/"source.xml", tmp_path/"trial.xml")
    try:
        result = probe.load(candidate)
        spans = [r for r in result["rows"] if r["name"].startswith("corner")]
        start_widths = [float(np.linalg.norm(r["outer_edges"][0, 0]-r["vertices"][1])) for r in spans]
        end_widths = [float(np.linalg.norm(r["outer_edges"][0, 1]-r["vertices"][3])) for r in spans]
        assert start_widths == pytest.approx([12., 11., 8.], abs=1e-4)
        assert end_widths == pytest.approx([11., 8., 7.], abs=1e-4)
        assert np.linalg.norm(result["rows"][-1]["outer_edges"][0, 1]-result["rows"][-1]["vertices"][3]) == pytest.approx(7., abs=1e-4)
    finally:
        probe.close()


def test_native_subdivision_count_preserves_quantized_exit_heading(native_build, tmp_path):
    runtime, symbols = native_build
    root = ET.fromstring(fixture_xml())
    main = root.find("section[@name='Main Track']")
    ET.SubElement(main, "attnum", name="profil steps length", unit="m", val="6")
    lead, corner, _ = list(main.find("section[@name='Track Segments']"))
    lead.find("attstr[@name='type']").set("val", "rgt")
    lead.remove(lead.find("attnum[@name='lg']"))
    ET.SubElement(lead, "attnum", name="radius", unit="m", val="50")
    ET.SubElement(lead, "attnum", name="arc", unit="deg", val="80")
    corner.remove(corner.find("section[@name='Right Border']"))
    corner.find("attnum[@name='radius']").set("val", "30080")
    corner.find("attnum[@name='arc']").set("val", "0.4")
    for key, unit in [("z start", "m"), ("z end", "m"), ("profil start tangent", "%"), ("profil end tangent", "%")]:
        ET.SubElement(corner, "attnum", name=key, unit=unit, val="0")
    ET.SubElement(corner, "attstr", name="profil", val="spline")
    text = ET.tostring(root, encoding="unicode")
    selected = selected_sections(text, ["corner"], "auto")
    probe = TrackLoaderProbe(runtime, symbols, tmp_path/"source.xml", tmp_path/"trial.xml")
    try:
        baseline = probe.load(text)
        old = [r for r in baseline["rows"] if r["name"] == "corner"]
        selected["corner"]["method"] = "scs"
        configure_sampling(selected["corner"], old)
        angle = math.radians(.4)
        pad = (30080.-3000.)*angle/2
        candidate = apply_parameters(text, selected, {"corner": [pad, angle, pad]})
        end = probe.endpoint(candidate, "corner")
        assert end["end_angle"] == old[-1]["end_angle"]  # exact native float-angle identity
    finally:
        probe.close()


def test_external_url_is_not_passed_to_native_loader(tmp_path):
    with pytest.raises(ValueError, match="Only local"):
        relocated_entities('<!DOCTYPE params SYSTEM "https://example.com/track.dtd"><params/>', tmp_path, tmp_path)


@pytest.mark.parametrize("reason", ["connected", "missing", "plan", "outer-missing", "prior-missing", "prior-plan", "x", "height"])
def test_wall_split_diagnostic_matches_static_wall_rules(reason):
    # Synthetic memory reader with unrelated offsets, not the production ABI.
    probe = TrackLoaderProbe.__new__(TrackLoaderProbe)
    probe.seg = {"side": 10, "style": 30, "vertex": 40, "height": 100}
    memory = {(1, 10): 3, (2, 10): 4, (3, 30): 2, (4, 30): 2,
              (3, 10): 5, (3, 40): 0., (3, 52): 0., (4, 64): 0., (4, 76): 0.,
              (3, 100): 1., (4, 100): 1.}
    overrides = {"missing": ((1, 10), 0), "plan": ((3, 30), 0), "outer-missing": ((3, 10), 0),
                 "prior-missing": ((2, 10), 0), "prior-plan": ((4, 30), 0),
                 "x": ((4, 64), .02), "height": ((4, 100), 2.)}
    if reason in overrides:
        key, value = overrides[reason]
        memory[key] = value
    probe.read = lambda pointer, offset, *args: memory[pointer, offset]
    assert probe.starts_wall_run(1, 2, 0) == (reason in {"prior-missing", "prior-plan", "x", "height"})
