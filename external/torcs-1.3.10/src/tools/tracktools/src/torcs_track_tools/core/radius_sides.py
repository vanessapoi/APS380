# /***************************************************************************
#     file                 : radius_sides.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""Replay v4 side-width inheritance and split linear tapers at part stations."""

import math
import re
from xml.parsers import expat

from defusedxml import ElementTree as ET

from torcs_track_tools.core.track_xml import child_section

SIDES = ("Left Side", "Right Side")
WIDTHS = {"width", "start width", "end width"}


def width(section, key, fallback):
    if section is None:
        return fallback
    att = section.find(f"attnum[@name='{key}']")
    if att is None:
        return fallback
    value = float(att.get("val", "nan"))
    if att.get("unit", "m") != "m" or not math.isfinite(value) or value < 0:
        raise ValueError("Side-width replay requires nonnegative metre values")
    return value


def side_states(main, segments):
    previous = {side: width(child_section(main, side), "width", 0.) for side in SIDES}
    result = {}
    for segment in segments:
        states = {}
        for side in SIDES:
            section = child_section(segment, side)
            start = width(section, "start width", previous[side])
            end = width(section, "end width", width(section, "width", start))
            if section is not None:
                states[side] = {"start": start, "end": end}
            previous[side] = end
        result[segment.get("name")] = states
    return result


def width_spans(block):
    data = block.encode("utf-8")
    parser = expat.ParserCreate()
    spans, active = [], []

    def start(tag, attrs):
        if tag == "attnum" and attrs.get("name") in WIDTHS:
            active.append(parser.CurrentByteIndex)

    def end(tag):
        if tag == "attnum" and active:
            begin = active.pop()
            stop = parser.CurrentByteIndex
            if data[stop:stop+8] == b"</attnum":
                stop = data.index(b">", stop)+1
            spans.append((begin, stop))

    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.Parse(data, True)
    return spans


def split_side(block, state, start, end):
    if state["start"] == state["end"]:
        return block
    widths = [state["start"]+(state["end"]-state["start"])*t for t in (start, end)]
    data = block.encode("utf-8")
    spans = width_spans(block)
    if not spans:
        raise ValueError("A tapered side has no explicit width attributes")
    replacement = (f'<attnum name="start width" unit="m" val="{widths[0]:.10f}" />\n'
                   f'\t\t\t\t\t<attnum name="end width" unit="m" val="{widths[1]:.10f}" />').encode()
    for begin, stop in reversed(spans[1:]):
        data = data[:begin]+data[stop:]
    begin, stop = spans[0]
    return (data[:begin]+replacement+data[stop:]).decode("utf-8")


def nonwidth_content(block):
    data = block.encode("utf-8")
    for begin, end in reversed(width_spans(block)):
        data = data[:begin]+data[end:]
    return re.sub(r">\s+<", "><", data.decode("utf-8")).strip()


def validate_side_split(original, actual, state, start, end):
    if nonwidth_content(original) != nonwidth_content(actual):
        return False
    section = ET.fromstring(actual)
    for key, t in (("start width", start), ("end width", end)):
        expected = state["start"]+(state["end"]-state["start"])*t
        if abs(width(section, key, math.inf)-expected) > 1e-7:
            return False
    return True
