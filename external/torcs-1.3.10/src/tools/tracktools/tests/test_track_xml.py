# /***************************************************************************
#
#     file                 : test_track_xml.py
#     created              : 04 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

import math
import xml.etree.ElementTree as ET

import pytest

from torcs_track_tools.core.track_xml import (
    effective_border_states,
    effective_side_width_profiles,
    pit_protected_indices,
    segment_length,
    segment_sections,
)


def test_segment_length_uses_average_radius_for_variable_turn_xml() -> None:
    seg = ET.fromstring(
        """
<section name="transition">
  <attstr name="type" val="lft"/>
  <attnum name="radius" unit="m" val="80"/>
  <attnum name="end radius" unit="m" val="120"/>
  <attnum name="arc" unit="deg" val="10"/>
</section>
""".strip()
    )

    assert segment_length(seg) == pytest.approx(100.0 * math.radians(10.0))


def test_effective_border_states_inherit_segment_overrides() -> None:
    root = ET.fromstring(
        """
<params>
  <section name="Main Track">
    <section name="Left Border"><attnum name="width" val="1"/><attstr name="style" val="plan"/></section>
    <section name="Right Border"><attnum name="width" val="2"/><attstr name="surface" val="grass"/></section>
    <section name="Track Segments">
      <section name="a"><section name="Left Border"><attnum name="width" val="3"/><attstr name="surface" val="wall"/></section></section>
      <section name="b"/>
    </section>
  </section>
</params>
""".strip()
    )
    main_track, segs = segment_sections(root)

    states = effective_border_states(main_track, segs)

    assert states[0]["Left Border"]["width"] == pytest.approx(3.0)
    assert states[0]["Left Border"]["surface"] == "wall"
    assert states[1]["Left Border"]["width"] == pytest.approx(3.0)
    assert states[1]["Right Border"]["surface"] == "grass"


def test_effective_side_width_profiles_inherit_end_widths() -> None:
    root = ET.fromstring(
        """
<params>
  <section name="Main Track">
    <section name="Left Side"><attnum name="width" val="5"/></section>
    <section name="Right Side"><attnum name="width" val="6"/></section>
    <section name="Track Segments">
      <section name="a">
        <section name="Left Side"><attnum name="start width" val="4"/><attnum name="end width" val="7"/></section>
        <section name="Right Side"><attnum name="width" val="8"/></section>
      </section>
      <section name="b"/>
    </section>
  </section>
</params>
""".strip()
    )
    main_track, segs = segment_sections(root)

    profiles = effective_side_width_profiles(main_track, segs)

    assert profiles[0]["left"] == pytest.approx((4.0, 7.0))
    assert profiles[0]["right"] == pytest.approx((6.0, 8.0))
    assert profiles[1]["left"] == pytest.approx((7.0, 7.0))
    assert profiles[1]["right"] == pytest.approx((8.0, 8.0))


def test_pit_protected_indices_include_pit_ranges_and_walls_only() -> None:
    root = ET.fromstring(
        """
<params>
  <section name="Main Track">
    <section name="Pits"><attstr name="type" val="single"/><attstr name="entry" val="entry"/><attstr name="start" val="start"/><attstr name="end" val="end"/><attstr name="exit" val="exit"/></section>
    <section name="Track Segments">
      <section name="entry"/><section name="a"/><section name="start"/><section name="b"/><section name="end"/><section name="c"/><section name="exit"/>
      <section name="wall"><section name="Left Border"><attstr name="style" val="wall"/></section></section>
      <section name="pit-access"><section name="Left Border"><attstr name="style" val="plan"/></section></section>
      <section name="Spitzkehre"/>
    </section>
  </section>
</params>
""".strip()
    )
    main_track, segs = segment_sections(root)
    border_states = effective_border_states(main_track, segs)

    protected = pit_protected_indices(main_track, segs, border_states)

    assert protected == set(range(8))
