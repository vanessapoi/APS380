# /***************************************************************************
#     file                 : test_radius_profiles.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from test_radius_repair import models, track
from test_radius_repair_scs import scs_models, with_border

from torcs_track_tools.core.radius_profiles import is_implicit_flat_track
from torcs_track_tools.core.radius_repair import (
    apply_parameters,
    border_blocks,
    choose_method,
    segment_blocks,
    selected_sections,
    validate,
)


@pytest.mark.parametrize("attribute", [
    '<attnum name="z end" val="1"/>',
    '<attnum name="grade" val="0.1"/>',
    '<attnum name="profil end tangent left" val="2"/>',
    '<attnum name="banking start" val="0"/>',
    '<attnum name="z start right" val="0"/>',
    '<attstr name="profil" val="linear"/>',
    '<attnum name="z start" val="nan"/>',
])
def test_flat_inference_rejects_ambiguous_or_nonflat_profiles(attribute):
    segments = ET.fromstring(f'<section><section name="prior">{attribute}</section><section name="selected"/></section>')
    assert not is_implicit_flat_track(segments)


def test_flat_defaults_materialize_only_selected_replacement():
    from test_track_loader_probe import fixture_xml

    root = ET.fromstring(fixture_xml())
    corner = root.find("section[@name='Main Track']/section[@name='Track Segments']/section[@name='corner']")
    corner.remove(corner.find("section"))
    corner.find("attnum[@name='radius']").set("val", "5000")
    text = ET.tostring(root, encoding="unicode")
    selected = selected_sections(text, ["corner"], "scs")
    assert selected["corner"]["implicit_flat"]
    candidate = apply_parameters(text, selected, {"corner": [2., .003, 2.]})
    before, after = segment_blocks(text), segment_blocks(candidate)
    assert before["lead"] == after["lead"]
    assert before["tail"] == after["tail"]
    for name, block in after.items():
        if name.startswith("corner"):
            section = ET.fromstring(block)
            for field in ("z start", "z end", "profil start tangent", "profil end tangent"):
                assert float(section.find(f"attnum[@name='{field}']").get("val")) == 0


def banked_track():
    text = track().replace('<section name="Main Track">', '<section name="Main Track"><attnum name="width" unit="m" val="12"/>')
    return text.replace('<attstr name="profil"', '''<attnum name="banking start" unit="deg" val="2"/>
    <attnum name="banking end" unit="deg" val="-3"/><attstr name="profil"''', 1)


def hermite(z0, z1, m0, m1, length, t):
    return (2*t**3-3*t*t+1)*z0 + (t**3-2*t*t+t)*length*m0 + (-2*t**3+3*t*t)*z1 + (t**3-t*t)*length*m1


@pytest.mark.parametrize("method,parameters,lengths", [("biarc", [12., .003, 0.], [6., 6.]), ("scs", [2., .003, 4.], [2., 6., 4.])])
def test_split_banking_preserves_both_edge_cubics(method, parameters, lengths):
    text = banked_track()
    sections = selected_sections(text, ["large"], method, 2000)
    candidate = apply_parameters(text, sections, {"large": parameters})
    blocks = segment_blocks(candidate)
    names = ["large", "large:radius-out"] if method == "biarc" else ["large", "large:radius-turn", "large:radius-out"]
    distance = 0.
    for name, length in zip(names, lengths, strict=True):
        part = ET.fromstring(blocks[name])
        values = {a.get("name"): a.get("val") for a in part}
        assert "profil start tangent" not in values and "profil end tangent" not in values
        for side, sign in [("left", 1), ("right", -1)]:
            z0 = float(values["z start"])+sign*6*math.tan(math.radians(float(values["banking start"])))
            z1 = float(values["z end"])+sign*6*math.tan(math.radians(float(values["banking end"])))
            m0 = float(values[f"profil start tangent {side}"])/100
            m1 = float(values[f"profil end tangent {side}"])/100
            for t in (.0, .25, .5, .75, 1.):
                expected = hermite(1+sign*6*math.tan(math.radians(2)), 2+sign*6*math.tan(math.radians(-3)),
                                   .03, -.01, 12, (distance+t*length)/12)
                assert hermite(z0, z1, m0, m1, length, t) == pytest.approx(expected, abs=1e-9)
        distance += length


def test_validation_detects_lost_banking_and_changed_edge_grade():
    text = banked_track()
    sections = selected_sections(text, ["large"], "scs", 2000)
    candidate = apply_parameters(text, sections, {"large": [2., .003, 2.]})
    assert validate(text, candidate, sections, *scs_models())["accepted"]
    blocks = segment_blocks(candidate)
    part = ET.fromstring(blocks["large:radius-out"])
    part.find("attnum[@name='banking end']").set("val", "0")
    part.find("attnum[@name='profil end tangent left']").set("val", "20")
    changed = candidate.replace(blocks["large:radius-out"], ET.tostring(part, encoding="unicode"))
    report = validate(text, changed, sections, *scs_models())
    assert not report["accepted"]
    assert any("banking end" in f for f in report["failures"])
    assert any("left edge grade" in f for f in report["failures"])


def test_curbs_and_constant_sides_are_copied_without_losing_overrides():
    text = with_border(track(), style="curb").replace('<attnum name="width" unit="m" val="1"/>',
             '<attnum name="width" unit="m" val="1"/><attnum name="height" unit="m" val="0.04"/>')
    side = '<section name="Left Side"><attstr name="surface" val="grass6"/><attnum name="start width" unit="m" val="7"/><attnum name="end width" unit="m" val="7"/></section>'
    text = text.replace('<attstr name="profil"', side+'<attstr name="profil"', 1)
    sections = selected_sections(text, ["large"], "scs")
    candidate = apply_parameters(text, sections, {"large": [2., .002, 2.]})
    for name, block in segment_blocks(candidate).items():
        if name != "tail":
            assert border_blocks(block) == sections["large"]["borders"]


def test_tapered_side_is_split_at_part_stations():
    side = '<section name="Left Side"><attstr name="surface" val="grass6"/><attnum name="start width" unit="m" val="7"/><attnum name="end width" unit="m" val="8"/></section>'
    text = track().replace('<attstr name="profil"', side+'<attstr name="profil"', 1)
    sections = selected_sections(text, ["large"])
    result = apply_parameters(text, sections, {"large": [10., .0025, 0.]})
    blocks = segment_blocks(result)
    first = ET.fromstring(border_blocks(blocks["large"])["Left Side"])
    last = ET.fromstring(border_blocks(blocks["large:radius-out"])["Left Side"])
    assert float(first.find("attnum[@name='start width']").get("val")) == 7
    assert float(first.find("attnum[@name='end width']").get("val")) == 7.5
    assert float(last.find("attnum[@name='start width']").get("val")) == 7.5
    assert float(last.find("attnum[@name='end width']").get("val")) == 8


@pytest.mark.parametrize("turn,expected", [(.004, "scs"), (.000001, "biarc")])
def test_auto_chooses_per_segment_from_loaded_pose(turn, expected):
    meta = selected_sections(track(), ["large"], "auto")["large"]
    before, _ = models()
    a, b = before["rows"][0], dict(before["rows"][0])
    b["end_angle"] = -turn
    b["end"] = np.array([3+3000*math.sin(turn)+5*math.cos(turn), -(3000*(1-math.cos(turn))+5*math.sin(turn)), 0.])
    choose_method(a, b, "large", meta)
    assert meta["method"] == expected


def test_edge_height_regression_cannot_hide_in_unchanged_centerline():
    text = track()
    sections = selected_sections(text, ["large"])
    candidate = apply_parameters(text, sections, {"large": [10., .0025, 0.]})
    before, after = models()
    after["rows"][0]["vertices"][2, 2] += .05
    after["rows"][0]["vertices"][3, 2] -= .05
    report = validate(text, candidate, sections, before, after)
    assert not report["accepted"]
    assert any("road-edge displacement" in f for f in report["failures"])
