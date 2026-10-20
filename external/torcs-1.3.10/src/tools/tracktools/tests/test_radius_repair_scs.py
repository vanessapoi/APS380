# /***************************************************************************
#     file                 : test_radius_repair_scs.py
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
from test_radius_repair import models, row, track

from torcs_track_tools.core.radius_repair import (
    apply_parameters,
    border_blocks,
    closure_target,
    fit,
    polish_terminal_straights,
    profile,
    sampled_profile,
    scs_fit_bounds,
    segment_blocks,
    selected_sections,
    validate,
)


def with_border(text, side="Right", style="plan"):
    border = f'''<section name="{side} Border">
    <!-- hand-edited reset after the preceding curb -->
    <attstr name="style" val="{style}"/>
    <attnum name="width" unit="m" val="1"/>
    <attstr name="surface" val="b-road1-grass6"/>
    </section>'''
    return text.replace('<attstr name="profil"', border+'\n<attstr name="profil"', 1)


@pytest.mark.parametrize("method", ["biarc", "scs"])
@pytest.mark.parametrize("side", ["Left", "Right"])
def test_border_reset_is_copied_verbatim_to_every_part(method, side):
    text = with_border(track(), side).replace("\n", "\r\n")
    sections = selected_sections(text, ["large"], method)
    parameters = [2., .002, 3.] if method == "scs" else [10., .0025, 0.]
    candidate = apply_parameters(text, sections, {"large": parameters})
    original_border = sections["large"]["borders"]
    assert "hand-edited reset" in original_border[side+" Border"]
    blocks = segment_blocks(candidate)
    labels = ["large", "large:radius-out"]
    if method == "scs":
        labels.insert(1, "large:radius-turn")
    for name in labels:
        assert border_blocks(blocks[name]) == original_border
    assert "\n" not in candidate.replace("\r\n", "")


@pytest.mark.parametrize("style", ["curb", "wall", "fence"])
def test_nonplanar_borders_still_require_manual_handling(style):
    with pytest.raises(ValueError, match="manual handling"):
        selected_sections(with_border(track(), style=style), ["large"], "scs")


def test_tapered_border_is_not_silently_treated_as_constant():
    text = with_border(track()).replace('name="width"', 'name="start width"')
    with pytest.raises(ValueError, match="constant width"):
        selected_sections(text, ["large"], "scs")


def test_scs_preserves_cubic_profile_at_unequal_length_boundaries():
    text = with_border(track())
    sections = selected_sections(text, ["large"], "scs", 2000)
    candidate = apply_parameters(text, sections, {"large": [2., .003, 4.]})
    blocks = segment_blocks(candidate)
    lengths = [2., 6., 4.]
    stations = [0., 2/12, 8/12, 1.]
    for i, name in enumerate(["large", "large:radius-turn", "large:radius-out"]):
        part = ET.fromstring(blocks[name])
        z0, m0 = profile(sections["large"]["values"], sum(lengths), stations[i])
        z1, m1 = profile(sections["large"]["values"], sum(lengths), stations[i+1])
        for key, expected in [("z start", z0), ("z end", z1), ("profil start tangent", m0), ("profil end tangent", m1)]:
            assert float(part.find(f"attnum[@name='{key}']").get("val")) == pytest.approx(expected, abs=1e-9)


def scs_models():
    before, after = models()
    after["rows"] = [row("large", 0, 2, 2), row("large:radius-turn", 2, 8, 6),
                     row("large:radius-out", 8, 10, 2), row("tail", 10, 0, 50)]
    return before, after


def test_validation_accepts_scs_and_rejects_missing_border_reset():
    text = with_border(track())
    sections = selected_sections(text, ["large"], "scs", 2000)
    candidate = apply_parameters(text, sections, {"large": [2., .003, 2.]})
    assert validate(text, candidate, sections, *scs_models())["accepted"]
    blocks = segment_blocks(candidate)
    last = blocks["large:radius-out"]
    missing = last.replace(sections["large"]["borders"]["Right Border"], "")
    changed = candidate.replace(last, missing)
    report = validate(text, changed, sections, *scs_models())
    assert not report["accepted"]
    assert any("border resets" in failure for failure in report["failures"])


@pytest.mark.parametrize("radius", [0., -1., 4001., math.inf, math.nan])
def test_scs_rejects_invalid_requested_radius(radius):
    with pytest.raises(ValueError, match="curve radius"):
        selected_sections(track(), ["large"], "scs", radius)


def test_scs_reserves_middle_segment_name():
    text = track().replace('name="tail"', 'name="large:radius-turn"')
    with pytest.raises(ValueError, match="collision"):
        selected_sections(text, ["large"], "scs")


@pytest.mark.parametrize("case", ["too-small-turn", "negative-straight"])
def test_scs_rejects_unrepresentable_loaded_poses(case):
    first = row("large", 0, 10, 10)
    last = row("large", 0, 10, 10)
    last["end_angle"] = 0 if case == "too-small-turn" else -.1
    with pytest.raises(ValueError, match="unsuitable|negative straight"):
        scs_fit_bounds(first, last, "large", {"type": "rgt"}, 3000)


@pytest.mark.parametrize("kind,sign", [("lft", 1), ("rgt", -1)])
def test_scs_fitter_preserves_turn_direction_and_loaded_endpoint(kind, sign):
    text = with_border(track().replace('val="rgt"', f'val="{kind}"'))
    sections = selected_sections(text, ["large"], "scs", 3000)
    turn = .004
    target = np.array([3+3000*math.sin(turn)+5*math.cos(turn), sign*(3000*(1-math.cos(turn))+5*math.sin(turn)), 0.])

    class Loader:
        def load(self, xml):
            if xml == text:
                item = row("large", 0, 20, 20)
                item.update(end=target.copy(), end_angle=sign*turn)
                return {"rows": [item]}
            root = ET.fromstring(xml.replace("&default-surfaces;", ""))
            parts = root.find("section[@name='Main Track']/section[@name='Track Segments']")
            position = np.zeros(3)
            angle = 0.
            rows = []
            for section in list(parts)[:3]:
                item, position, angle = advance_part(section, position, angle)
                rows.append(item)
            return {"rows": rows}

    loader = Loader()
    candidate, parameters, _ = fit(text, sections, loader)
    end = loader.load(candidate)["rows"][-1]
    assert end["end"] == pytest.approx(target, abs=1e-4)
    assert end["end_angle"] == pytest.approx(sign*turn, abs=1e-6)
    assert min(parameters["large"]) > 0


def advance_part(section, position, angle):
    kind = section.find("attstr[@name='type']").get("val")
    if kind == "str":
        length = float(section.find("attnum[@name='lg']").get("val"))
        delta = [length*math.cos(angle), length*math.sin(angle), 0]
        end_angle = angle
    else:
        sign = 1 if kind == "lft" else -1
        radius = float(section.find("attnum[@name='radius']").get("val"))
        arc = math.radians(float(section.find("attnum[@name='arc']").get("val")))
        end_angle = angle+sign*arc
        delta = [sign*radius*(math.sin(end_angle)-math.sin(angle)), sign*radius*(math.cos(angle)-math.cos(end_angle)), 0]
    end = position+delta
    return {"name": section.get("name"), "start": position, "end": end, "angle": angle, "end_angle": end_angle}, end, end_angle


def test_auto_pads_biarc_when_full_length_arcs_cannot_meet_endpoint():
    text = track()
    sections = selected_sections(text, ["large"], "auto")
    target = np.array([14., .005, 0.])

    class Loader:
        def load(self, xml):
            if xml == text:
                original = row("large", 0, 14, 14)
                original.update(end=target.copy(), end_angle=-.00002)
                return {"rows": [original]}
            parts = ET.fromstring(xml.replace("&default-surfaces;", "")).find("section[@name='Main Track']/section[@name='Track Segments']")
            position, angle, rows = np.zeros(3), 0., []
            for part in parts:
                if part.get("name") == "tail":
                    break
                item, position, angle = advance_part(part, position, angle)
                rows.append(item)
            return {"rows": rows}

    checkpoints = []
    loader = Loader()
    candidate, parameters, _ = fit(text, sections, loader, progress=lambda p, s: checkpoints.append(dict(p)))
    assert sections["large"]["method"] == "sbbs"
    rows = loader.load(candidate)["rows"]
    assert len(rows) == 4
    assert rows[-1]["end"] == pytest.approx(target, abs=1e-4)
    assert rows[-1]["end_angle"] == pytest.approx(-.00002, abs=1e-6)
    assert checkpoints[-1] == parameters


def test_terminal_polish_changes_only_selected_straights_not_arc():
    text = track()
    sections = selected_sections(text, ["large"], "scs")
    parameters = {"large": [5.249, .001, 4.75]}
    baseline = {"rows": [{"name": "tail", "end": np.zeros(3), "end_angle": 0.}]}

    class Loader:
        def endpoint(self, xml, name):
            assert name == "tail"
            blocks = segment_blocks(xml)
            before = float(ET.fromstring(blocks["large"]).find("attnum[@name='lg']").get("val"))
            after = float(ET.fromstring(blocks["large:radius-out"]).find("attnum[@name='lg']").get("val"))
            return {"end": np.array([before+after-10, .01*(before-after)-.005, 0.]), "end_angle": 0.}

    result = polish_terminal_straights(text, sections, parameters, baseline, Loader())
    assert result["large"][0] == pytest.approx(5.25, abs=1e-6)
    assert result["large"][1] == parameters["large"][1]
    assert result["large"][2] == pytest.approx(4.75, abs=1e-6)
    assert parameters["large"] == [5.249, .001, 4.75]


def test_closure_polish_does_not_target_an_existing_out_of_tolerance_gap():
    original_end = np.array([.000061, -.001923, 0.])
    baseline = {"rows": [{"name": "tail", "end": original_end, "angle": 0., "end_angle": 2*math.pi}]}
    target = closure_target(baseline)
    assert target["end"] == pytest.approx([.000061, -.00075, 0.], abs=1e-12)
    assert original_end == pytest.approx([.000061, -.001923, 0.], abs=1e-12)


def test_long_shallow_curve_uses_distributed_turns_to_preserve_shape():
    radius, arc = 30080., math.radians(.4)
    text = track().replace('val="3000000"', 'val="30080"').replace('val="0.0002"', 'val="0.4"').replace('val="rgt"', 'val="lft"')
    sections = selected_sections(text, ["large"], "auto")

    class Loader:
        def load(self, xml):
            if xml == text:
                angles = np.linspace(0, arc, 36)
                points = np.array([[radius*math.sin(a), radius*(1-math.cos(a)), 0.] for a in angles])
                return {"rows": [{"name": "large", "start": points[i], "end": points[i+1],
                                  "angle": angles[i], "end_angle": angles[i+1], "length": radius*arc/35} for i in range(35)]}
            root = ET.fromstring(xml.replace("&default-surfaces;", ""))
            parts = root.find("section[@name='Main Track']/section[@name='Track Segments']")
            position, angle, rows = np.zeros(3), 0., []
            for part in parts:
                if part.get("name") == "tail":
                    break
                item, position, angle = advance_part(part, position, angle)
                length = part.find("attnum[@name='lg']")
                item["length"] = float(length.get("val")) if length is not None else float(part.find("attnum[@name='radius']").get("val"))*math.radians(float(part.find("attnum[@name='arc']").get("val")))
                rows.append(item)
            return {"rows": rows}

    loader = Loader()
    candidate, _, before = fit(text, sections, loader)
    after = loader.load(candidate)
    assert sections["large"]["cells"] >= 2
    assert after["rows"][-1]["end"] == pytest.approx(before["rows"][-1]["end"], abs=1e-4)
    assert max(np.linalg.norm(sampled_profile(after["rows"])-sampled_profile(before["rows"]), axis=1)) < .05
