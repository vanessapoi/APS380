# /***************************************************************************
#     file                 : radius_pits.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""Preserve the native first/last subdivision used as a pit entry/exit marker."""

import re
from html import escape
from xml.parsers import expat

import numpy as np

from torcs_track_tools.core.defaults import (
    RADIUS_LOCAL_EDGE_TOLERANCE_M,
    RADIUS_LOCAL_HEIGHT_TOLERANCE_M,
    RADIUS_UNTOUCHED_TOLERANCE_M,
)


def pit_references(root, name):
    pits = root.find("section[@name='Main Track']/section[@name='Pits']")
    supported = {} if pits is None else {id(att): att.get("name") for att in pits.findall("attstr")
                                       if att.get("name") in ("entry", "exit")}
    roles = []
    for att in root.iter("attstr"):
        if att.get("val") != name:
            continue
        if id(att) not in supported:
            raise ValueError(f"{name}: referenced by another XML section; repair its references manually")
        roles.append(supported[id(att)])
    return roles


def configure_pit_markers(meta, rows):
    roles = meta.get("pit_roles", [])
    if not roles:
        return
    if meta["method"] != "scs":
        raise ValueError("Pit entry/exit replacement requires straight–curve–straight geometry")
    meta["cells"] = 1
    meta["pit_lengths"] = {role: rows[0 if role == "entry" else -1]["length"] for role in roles}


def constrain_pit_bounds(bounds, lengths):
    initial, lower, upper = bounds
    for role, length in lengths.items():
        index = 0 if role == "entry" else 2
        lower[index] = length+.1
        if lower[index] >= upper[index]:
            raise ValueError(f"No space for preserved pit {role} marker")
    return initial, lower, upper


def pit_labels(labels, roles):
    result = list(labels)
    if "entry" in roles:
        result.insert(1, labels[0]+":radius-entry-pad")
    if "exit" in roles:
        result.insert(-1, labels[0]+":radius-exit-pad")
    return result


def split_pit_geometry(geometry, lengths):
    result = list(geometry)
    for role, length in lengths.items():
        index = 0 if role == "entry" else -1
        part = result[index]
        if part[0] != "str" or part[1] <= length:
            raise ValueError(f"Insufficient straight padding to preserve pit {role} marker interval")
        marker = ("str", length, 0, 0, 1)
        pad = ("str", part[1]-length, 0, 0)
        if role == "entry":
            result[:1] = [marker, pad]
        else:
            result[-1:] = [pad, marker]
    return result


def remap_exit_reference(block, old, new):
    data = block.encode("utf-8")
    parser = expat.ParserCreate()
    edits = []

    def start(tag, attrs):
        if tag != "attstr" or attrs.get("name") != "exit" or attrs.get("val") != old:
            return
        begin = parser.CurrentByteIndex
        # Consume entire quoted values (which may contain '>') and leave XML
        # comments and CDATA untouched by using actual parser element events.
        match = re.match(rb'''<attstr\b(?:[^>"']|"[^"]*"|'[^']*')*>''', data[begin:])
        text = match.group().decode("utf-8")
        updated = re.sub(r'''(\s+)([^\s=]+)(\s*=\s*)(["'])(.*?)\4''',
                         lambda value: (value[1]+value[2]+value[3]+value[4]+escape(new, quote=True)+value[4])
                         if value[2] == "val" else value.group(), text, flags=re.DOTALL)
        edits.append((begin, begin+match.end(), updated.encode("utf-8")))

    parser.StartElementHandler = start
    parser.Parse(data, True)
    for begin, end, replacement in reversed(edits):
        data = data[:begin]+replacement+data[end:]
    return data.decode("utf-8")


def validate_pit_markers(baseline, after, failures, selected=()):
    before = baseline.get("pit_markers", {})
    current = after.get("pit_markers", {})
    if before.keys() != current.keys():
        failures.append("Native pit references added or removed")
        return {}
    measurements = {}
    for name, old in before.items():
        new = current[name]
        delta = new["vertices"]-old["vertices"]
        vertices = float(np.max(np.linalg.norm(delta, axis=1)))
        plan = float(np.max(np.linalg.norm(delta[:, :2], axis=1)))
        height = float(np.max(abs(delta[:, 2])))
        intervals = max(abs(new["station"]-old["station"]),
                        abs(new["station"]+new["length"]-old["station"]-old["length"]))
        length = abs(new["length"]-old["length"])
        # lgfromstart is recomputed along the repaired preceding road. Its
        # absolute change is not marker movement: car stations change with it.
        # Preserve both physical boundaries and the marked interval's length.
        local = old.get("name") in selected
        # Apply the existing road-edge gates: selected road may move 15 cm XY /
        # 2 cm Z, untouched road only 2 mm. The marker must still cover exactly
        # one original-length native subdivision, not an entire replacement pad.
        moved = (plan > RADIUS_LOCAL_EDGE_TOLERANCE_M or height > RADIUS_LOCAL_HEIGHT_TOLERANCE_M) if local else vertices > RADIUS_UNTOUCHED_TOLERANCE_M
        measurements[name] = {"vertex_shift_m": vertices, "station_shift_m": intervals, "length_shift_m": length,
                              "selected_road": local}
        if moved or length > RADIUS_UNTOUCHED_TOLERANCE_M or new["race_info"] != old["race_info"]:
            failures.append(f"{name}: native pit marker geometry, interval length, or flags changed beyond preservation limits")
    return measurements
