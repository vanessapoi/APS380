# /***************************************************************************
#     file                 : test_radius_pits.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

import copy
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from test_radius_repair import track

from torcs_track_tools.core.radius_pits import configure_pit_markers, remap_exit_reference, validate_pit_markers
from torcs_track_tools.core.radius_repair import (
    apply_parameters,
    segment_blocks,
    selected_sections,
    validate_preserved_xml,
    validate_replacement,
)


@pytest.mark.parametrize("role", ["entry", "exit"])
def test_pit_reference_split_preserves_only_authorized_xml_edit(role):
    text = track().replace('<section name="Main Track">',
                           f'<section name="Main Track"><section name="Pits"><attstr name="{role}" val="large"/></section>')
    sections = selected_sections(text, ["large"], "scs")
    configure_pit_markers(sections["large"], [{"length": 2.}])
    candidate = apply_parameters(text, sections, {"large": [4., .002, 4.]})
    failures = []
    blocks = segment_blocks(candidate)
    validate_preserved_xml(text, candidate, sections, blocks, failures)
    validate_replacement("large", sections["large"], blocks, failures)
    assert not failures
    marker = ET.fromstring(blocks["large" if role == "entry" else "large:radius-out"])
    assert float(marker.find("attnum[@name='lg']").get("val")) == 2.
    assert marker.find("attnum[@name='profil steps']").get("val") == "1"
    if role == "exit":
        assert '<attstr name="exit" val="large:radius-out"/>' in candidate


def test_unknown_pit_reference_still_rejected():
    text = track().replace('<section name="Main Track">',
                           '<section name="Main Track"><section name="Pits"><attstr name="start" val="large"/></section>')
    with pytest.raises(ValueError, match="referenced"):
        selected_sections(text, ["large"])


def test_reference_remapping_preserves_spacing_quotes_and_other_attributes():
    block = "<section name='Pits'><attstr val = 'a&amp;b' name='exit' /><attstr name='entry' val='a&amp;b'/></section>"
    changed = remap_exit_reference(block, "a&b", "a&b:radius-out")
    assert changed == block.replace("val = 'a&amp;b'", "val = 'a&amp;b:radius-out'")
    assert remap_exit_reference(changed, "a&b:radius-out", "a&b") == block


def test_reference_remapping_does_not_edit_commented_tags_or_other_attribute_values():
    comment = '<!-- <attstr name="exit" val="a"/> -->'
    block = '<section name="Pits">'+comment+'''<attstr note="val='a' >" name="exit" val="a"></attstr></section>'''
    expected = block.replace('name="exit" val="a"></attstr>', 'name="exit" val="a:radius-out"></attstr>')
    assert remap_exit_reference(block, "a", "a:radius-out") == expected


@pytest.mark.parametrize("key,value", [("vertices", np.full((4, 3), .01)), ("length", 6.01), ("race_info", 0)])
def test_same_pit_count_does_not_hide_changed_marker_interval_or_flags(key, value):
    old = {"station": 2., "length": 6., "race_info": 8, "vertices": np.zeros((4, 3))}
    new = copy.deepcopy(old)
    new[key] = value
    failures = []
    validate_pit_markers({"pit_markers": {"pitExit": old}}, {"pit_markers": {"pitExit": new}}, failures)
    assert failures


def test_station_recalculation_is_reported_without_moving_physical_marker():
    old = {"station": 2., "length": 6., "race_info": 8, "vertices": np.zeros((4, 3))}
    new = dict(old, station=2.1)
    failures = []
    report = validate_pit_markers({"pit_markers": {"pitExit": old}}, {"pit_markers": {"pitExit": new}}, failures)
    assert not failures
    assert report["pitExit"]["station_shift_m"] == pytest.approx(.1)
    assert report["pitExit"]["length_shift_m"] == 0


@pytest.mark.parametrize("shift,accepted", [((.01, 0, 0), True), ((.151, 0, 0), False), ((0, 0, .021), False)])
def test_selected_marker_uses_existing_local_road_edge_limits(shift, accepted):
    old = {"name": "selected", "station": 2., "length": 6., "race_info": 8, "vertices": np.zeros((4, 3))}
    new = dict(old, vertices=old["vertices"]+shift)
    failures = []
    validate_pit_markers({"pit_markers": {"pitExit": old}}, {"pit_markers": {"pitExit": new}}, failures, ["selected"])
    assert (not failures) == accepted
