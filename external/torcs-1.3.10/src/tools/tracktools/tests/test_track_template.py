# /***************************************************************************
#
#     file                 : test_track_template.py
#     created              : 03 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

import pathlib
import xml.etree.ElementTree as ET


def child_section(parent: ET.Element, name: str) -> ET.Element:
    for child in parent:
        if child.tag == "section" and child.get("name") == name:
            return child
    raise AssertionError(f"missing section: {name}")


def attnum(section: ET.Element, name: str) -> float:
    for child in section:
        if child.tag == "attnum" and child.get("name") == name:
            return float(child.get("val", "0"))
    raise AssertionError(f"missing attnum: {name}")


def has_attnum(section: ET.Element, name: str) -> bool:
    return any(child.tag == "attnum" and child.get("name") == name for child in section)


def attstr(section: ET.Element, name: str) -> str:
    for child in section:
        if child.tag == "attstr" and child.get("name") == name:
            return child.get("val", "")
    raise AssertionError(f"missing attstr: {name}")


def test_road_track_template_uses_flat_borders_and_level_sides() -> None:
    template = pathlib.Path(__file__).resolve().parents[1] / "src" / "torcs_track_tools" / "templates" / "road-track-template.xml"
    raw = template.read_text(encoding="utf-8").replace("&default-surfaces;", "<default_surfaces/>")
    root = ET.fromstring(raw)
    main_track = child_section(root, "Main Track")

    for border_name in ("Left Border", "Right Border"):
        border = child_section(main_track, border_name)
        assert attnum(border, "width") == 1.0
        assert not has_attnum(border, "height")
        assert attstr(border, "style") == "plan"
        assert attstr(border, "surface") == "b-road1-grass6"

    for side_name in ("Left Side", "Right Side"):
        side = child_section(main_track, side_name)
        assert attnum(side, "width") == 7.0
        assert attstr(side, "banking type") == "level"
