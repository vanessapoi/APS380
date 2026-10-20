# /***************************************************************************
#     file                 : test_radius_repair.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

import copy
import math
import re
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from torcs_track_tools.cli.repair_track_radii import main
from torcs_track_tools.core.radius_audit import audit_tree
from torcs_track_tools.core.radius_repair import (
    apply_parameters,
    fit,
    polish_closure,
    profile,
    replacement,
    segment_blocks,
    selected_sections,
    validate,
)
from torcs_track_tools.core.track_loader_probe import relocated_entities


def curve(name="large"):
    return f'''<section name="{name}">
    <attstr name="type" val="rgt"/>
    <attnum name="radius" unit="m" val="3000000"/>
    <attnum name="arc" unit="deg" val="0.0002"/>
    <attnum name="z start" unit="m" val="1"/>
    <attnum name="z end" unit="m" val="2"/>
    <attnum name="profil start tangent" unit="%" val="3"/>
    <attnum name="profil end tangent" unit="%" val="-1"/>
    <attstr name="profil" val="spline"/>
    </section>'''


def track():
    return '''<?xml version="1.0"?>
<!DOCTYPE params [<!ENTITY default-surfaces SYSTEM "surfaces.xml">]>
<!-- preserve my hand edit -->
<params name="pilot">
<section name="Header"><attnum name="version" val="4"/></section>
<section name="Surfaces">&default-surfaces;</section>
<section name="Main Track"><section name="Track Segments">''' + curve() + '''
<section name="tail"><attstr name="type" val="str"/><attnum name="lg" val="50"/></section>
</section></section></params>'''


def row(name, start, end, length):
    a, b = np.array([start, 0., 0.]), np.array([end, 0., 0.])
    side = np.array([0., 6., 0.])
    return {"name": name, "start": a, "end": b, "length": length, "angle": 0., "end_angle": 0.,
            "outer_edges": np.array([[a-side, b-side], [a+side, b+side]]),
            "vertices": np.array([a+side, a-side, b+side, b-side])}


def models():
    before = {"rows": [row("large", 0, 10, 10), row("tail", 10, 0, 50)],
              "origin": np.zeros(3), "pit_count": 20, "wall_runs": 1}
    after = copy.deepcopy(before)
    after["rows"] = [row("large", 0, 5, 5), row("large:radius-out", 5, 10, 5), row("tail", 10, 0, 50)]
    return before, after


def test_audit_units_end_radius_legacy_list_and_no_source_duplicates(tmp_path):
    folder = tmp_path / "oval" / "example"
    folder.mkdir(parents=True)
    text = '''<params><section name="Main Track"><section name="Pits"><attstr name="entry" val="big"/></section>
    <section name="segments"><section name="small"><attstr name="type" val="lft"/>
    <attnum name="radius" unit="ft" val="5000"/></section>
    <section name="big"><attstr name="type" val="rgt"/><attnum name="radius" unit="m" val="3000"/>
    <attnum name="end radius" unit="km" val="6"/></section></section></section></params>'''
    (folder / "example.xml").write_text(text)
    source = folder / "source"
    source.mkdir()
    (source / "example.xml").write_text(text)
    result = audit_tree(tmp_path)
    assert result["tracks_scanned"] == 1
    assert result["affected_segments"] == 1
    hit = result["tracks"][0]["segments"][0]
    assert hit["end_radius_m"] == pytest.approx(6000)
    assert hit["pit_reference"]


def test_audit_reports_bad_files_and_continues(tmp_path):
    for name, data in [("good", track()), ("bad", "<params")]:
        folder = tmp_path / "road" / name
        folder.mkdir(parents=True)
        (folder / (name + ".xml")).write_text(data)
    result = audit_tree(tmp_path)
    assert result["affected_tracks"] == 1
    assert len(result["errors"]) == 1


@pytest.mark.parametrize("unit", ["ft", "feet"])
def test_radius_audit_matches_native_legacy_feet_at_limit(tmp_path, unit):
    directory = tmp_path/"road"/"example"
    directory.mkdir(parents=True)
    text = track().replace('unit="m" val="3000000"', f'unit="{unit}" val="13123.34"')
    (directory/"example.xml").write_text(text)
    result = audit_tree(tmp_path)
    assert result["affected_segments"] == 1  # standard SI feet would incorrectly fall below 4000 m
    assert result["tracks"][0]["segments"][0]["radius_m"] == pytest.approx(4000.00715534, rel=0, abs=1e-8)


@pytest.mark.parametrize("limit", [3500., 5000.])
def test_preflight_cannot_classify_only_a_subset_of_required_repairs(tmp_path, limit):
    with pytest.raises(ValueError, match="repair limit"):
        audit_tree(tmp_path, limit, preflight=True)


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_audit_rejects_invalid_limits(tmp_path, limit):
    with pytest.raises(ValueError):
        audit_tree(tmp_path, limit)


def test_preserves_prolog_hand_edits_utf8_names_and_crlf():
    text = track().replace('name="large"', 'name="Largé &amp; curve"').replace("\n", "\r\n")
    sections = selected_sections(text, ["Largé & curve"])
    result = apply_parameters(text, sections, {"Largé & curve": [10, .0025, 0]})
    assert text.split('<section name="Largé')[0] == result.split('<section name="Largé')[0]
    assert result[result.index('<section name="tail"'):] == text[text.index('<section name="tail"'):]
    assert result.count("&default-surfaces;") == 1
    assert "\n" not in result.replace("\r\n", "")
    root = ET.fromstring(result.replace("&default-surfaces;", ""))
    assert any(s.get("name") == "Largé & curve:radius-out" for s in root.iter("section"))


@pytest.mark.parametrize("declaration", ['<!ENTITY expanded "nested data">', '<!ENTITY % parameter "nested data">'])
def test_span_scanner_rejects_internal_entity_expansion(declaration):
    text = track().replace('<!ENTITY default-surfaces SYSTEM "surfaces.xml">', declaration)
    with pytest.raises(ValueError, match="Internal/parameter"):
        segment_blocks(text)


def test_validation_rejects_changed_midpoint_grade():
    text = track()
    sections = selected_sections(text, ["large"])
    candidate = apply_parameters(text, sections, {"large": [10, .0025, 0]})
    blocks = segment_blocks(candidate)
    second = blocks["large:radius-out"]
    changed = re.sub(r'(name="profil start tangent" unit="%" val=")[^"]+', r'\g<1>99', second)
    candidate = candidate.replace(second, changed)
    report = validate(text, candidate, sections, *models())
    assert not report["accepted"]
    assert any("midpoint" in message for message in report["failures"])


@pytest.mark.parametrize("change", [
    lambda text: text.replace('<attstr name="profil"', '<section name="Right Barrier"/><attstr name="profil"'),
    lambda text: text.replace('<attstr name="profil"', '<attnum name="banking start" val="2"/><attstr name="profil"'),
    lambda text: text.replace('<attstr name="profil"', '<attnum name="end radius" val="42"/><attstr name="profil"'),
    lambda text: text.replace('<section name="Main Track">', '<section name="Main Track"><section name="Pits"><attstr name="start" val="large"/></section>'),
    lambda text: text.replace('name="tail"', 'name="large:radius-out"'),
    lambda text: text.replace('name="radius" unit="m"', 'name="radius" unit="ft"'),
])
def test_unsupported_selected_sections_are_not_silently_rewritten(change):
    with pytest.raises(ValueError):
        selected_sections(change(track()), ["large"])


def test_profile_preserves_endpoint_grades_and_midpoint_continuity():
    meta = selected_sections(track(), ["large"])["large"]
    assert profile(meta["values"], 10, 0) == pytest.approx((1, 3), abs=1e-9)
    assert profile(meta["values"], 10, 1) == pytest.approx((2, -1), abs=1e-9)
    parts = ET.fromstring("<root>" + replacement("large", meta["values"], [10, -.0025, 0]) + "</root>")
    assert parts[0].find("attstr[@name='type']").get("val") == "rgt"
    assert parts[1].find("attstr[@name='type']").get("val") == "lft"
    for left, right in [("z end", "z start"), ("profil end tangent", "profil start tangent")]:
        assert parts[0].find(f"attnum[@name='{left}']").get("val") == parts[1].find(f"attnum[@name='{right}']").get("val")


def test_validation_accepts_preserved_configuration_and_geometry():
    text = track()
    sections = selected_sections(text, ["large"])
    candidate = apply_parameters(text, sections, {"large": [10, .0025, 0]})
    report = validate(text, candidate, sections, *models())
    assert report["accepted"]


def test_acceptable_straight_polish_does_not_change_headings():
    text = track()
    sections = selected_sections(text, ["large"])
    parameters = {"large": [10., .0025, 0.]}
    before, after = models()

    class Loader:
        def load(self, _text):
            return after

        def endpoint(self, *_args):
            pytest.fail("An already acceptable candidate must not get angle perturbations")

    assert polish_closure(text, sections, parameters, before, Loader()) == parameters


@pytest.mark.parametrize("defect", ["closure", "pits", "walls", "far-endpoint", "xml", "height", "origin", "road-vertex"])
def test_validation_rejects_independent_regressions(defect):
    text = track()
    sections = selected_sections(text, ["large"])
    candidate = apply_parameters(text, sections, {"large": [10, .0025, 0]})
    before, after = models()
    if defect == "closure":
        after["rows"][-1]["vertices"][2, 0] += .02
    elif defect == "pits":
        after["pit_count"] = 19
    elif defect == "walls":
        after["wall_runs"] = 2
    elif defect == "far-endpoint":
        after["rows"][-1]["end"][0] += .02
    elif defect == "xml":
        candidate = candidate.replace('name="lg" val="50"', 'name="lg" val="51"')
    elif defect == "height":
        after["rows"][0]["end"][2] = .1
    elif defect == "origin":
        after["origin"][0] = .1
    elif defect == "road-vertex":
        after["rows"][-1]["vertices"][0, 0] += .02
    assert not validate(text, candidate, sections, before, after)["accepted"]


def test_relocated_external_entity_is_relative_to_trial(tmp_path):
    source = tmp_path / "original"
    stage = tmp_path / "stage"
    text = relocated_entities(track(), source, stage)
    assert 'SYSTEM "../original/surfaces.xml"' in text
    assert text[text.index("<params"):] == track()[track().index("<params"):]


def test_cli_rejects_work_directory_inside_live_track(tmp_path):
    source = tmp_path / "track.xml"
    source.write_text(track())
    with pytest.raises(SystemExit) as error:
        main(["--input", str(source), "--runtime-dir", str(tmp_path), "--segment", "large", "--work-dir", str(tmp_path / "work")])
    assert error.value.code == 1
    assert not (tmp_path / "work").exists()
    assert source.read_text() == track()


@pytest.mark.parametrize("lateral", [.02, -.02])
def test_fitter_targets_loaded_pose_for_both_lateral_directions(lateral):
    # Model a legacy endpoint which differs from the XML's ideal huge circle.
    # Candidate evaluations use independent analytical arc geometry here; the
    # real DLL/PDB integration is separately exercised against the pilot XML.
    original = track()
    sections = selected_sections(original, ["large"])

    class Loader:
        def load(self, text):
            if text == original:
                segment = row("large", 0, 10, 10)
                segment["end"][1] = lateral
                return {"rows": [segment]}
            root = ET.fromstring(text.replace("&default-surfaces;", ""))
            parts = root.find("section[@name='Main Track']/section[@name='Track Segments']")
            x = y = angle = 0.
            rows = []
            for section in list(parts)[:2]:
                radius = float(section.find("attnum[@name='radius']").get("val"))
                arc = math.radians(float(section.find("attnum[@name='arc']").get("val")))
                sign = 1 if section.find("attstr[@name='type']").get("val") == "lft" else -1
                end_angle = angle + sign*arc
                end_x = x + sign*radius*(math.sin(end_angle)-math.sin(angle))
                end_y = y + sign*radius*(math.cos(angle)-math.cos(end_angle))
                rows.append({"name": section.get("name"), "angle": angle, "end_angle": end_angle,
                             "start": np.array([x, y, 0.]), "end": np.array([end_x, end_y, 0.])})
                x, y, angle = end_x, end_y, end_angle
            return {"rows": rows}

    loader = Loader()
    candidate, parameters, _ = fit(original, sections, loader)
    last = loader.load(candidate)["rows"][-1]
    assert last["end"][:2] == pytest.approx([10, lateral], abs=1e-4)
    assert last["end_angle"] == pytest.approx(0, abs=1e-6)
    length, peak, turn = parameters["large"]
    assert max(length/2/abs(peak), length/2/abs(turn-peak)) < 4000
