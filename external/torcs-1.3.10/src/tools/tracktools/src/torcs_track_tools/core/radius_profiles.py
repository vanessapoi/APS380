# /***************************************************************************
#     file                 : radius_profiles.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""Split the v4 loader's banked Hermite road-edge profiles without reimporting data."""

import copy
import math

BANK_FIELDS = {"banking start", "banking end"}
COMMON_TANGENTS = {"profil start tangent", "profil end tangent"}
EDGE_TANGENTS = {f"profil {end} tangent {side}" for end in ("start", "end") for side in ("left", "right")}


def is_implicit_flat_track(segments):
    """Prove the zero-height/default-slope case; do not guess missing hill data."""
    return all(is_flat_attribute(att) for segment in segments for att in segment)


def is_flat_attribute(att):
    numeric = {"z start", "z end", "grade"} | COMMON_TANGENTS | EDGE_TANGENTS
    name = att.get("name", "")
    if name in BANK_FIELDS or name.startswith(("z start left", "z start right", "z end left", "z end right")):
        return False
    if name in numeric:
        return att.tag == "attnum" and float(att.get("val", "nan")) == 0
    if name == "profil":
        return att.get("val") == "spline"
    return True


def materialize_flat_profile(section):
    result = copy.deepcopy(section)
    for name, unit in (("z start", "m"), ("z end", "m"), ("profil start tangent", "%"), ("profil end tangent", "%")):
        if result.find(f"attnum[@name='{name}']") is None:
            result.append(result.makeelement("attnum", {"name": name, "unit": unit, "val": "0"}))
    if result.find("attstr[@name='profil']") is None:
        result.append(result.makeelement("attstr", {"name": "profil", "val": "spline"}))
    return result


def banked_profile(values, width, length, station, center_profile):
    height, grade = center_profile(values, length, station)
    offset0 = width/2 * math.tan(math.radians(float(values["banking start"])))
    offset1 = width/2 * math.tan(math.radians(float(values["banking end"])))
    slope0 = (edge_grade(values, "start", "left")-edge_grade(values, "start", "right"))/200
    slope1 = (edge_grade(values, "end", "left")-edge_grade(values, "end", "right"))/200
    t = station
    offset = ((2*t**3-3*t*t+1)*offset0 + (-2*t**3+3*t*t)*offset1
              + (t**3-2*t*t+t)*length*slope0 + (t**3-t*t)*length*slope1)
    offset_grade = ((6*t*t-6*t)*(offset0-offset1)/length + (3*t*t-4*t+1)*slope0 + (3*t*t-2*t)*slope1)*100
    bank = math.degrees(math.atan2(2*offset, width))
    return {"z": height, "bank": bank, "left_grade": grade+offset_grade, "right_grade": grade-offset_grade}


def tangent_attributes(values, width, length, start, end, center_profile):
    if "banking start" not in values:
        _, m0 = center_profile(values, length, start)
        _, m1 = center_profile(values, length, end)
        return f'''<attnum name="profil start tangent" unit="%" val="{m0:.10f}" />
\t\t\t\t<attnum name="profil end tangent" unit="%" val="{m1:.10f}" />'''
    first = banked_profile(values, width, length, start, center_profile)
    last = banked_profile(values, width, length, end, center_profile)
    attributes = []
    for endpoint, state in (("start", first), ("end", last)):
        attributes.append(f'<attnum name="banking {endpoint}" unit="deg" val="{state["bank"]:.10f}" />')
        for side in ("left", "right"):
            attributes.append(f'<attnum name="profil {endpoint} tangent {side}" unit="%" val="{state[side+"_grade"]:.10f}" />')
    # Shared tangent attributes would override these edge tangents in track4.cpp.
    return "\n\t\t\t\t".join(attributes)


def profile_fields(fields, actual, allow_edges):
    bank = actual & BANK_FIELDS
    if bank and bank != BANK_FIELDS:
        raise ValueError("Both banking endpoints must be explicit")
    expected = fields | bank
    if actual & EDGE_TANGENTS:
        if not allow_edges or bank != BANK_FIELDS:
            raise ValueError("Independent edge tangents are only supported in banked replacement parts")
        expected = (expected-COMMON_TANGENTS) | EDGE_TANGENTS
    return expected


def normalize_profile_values(values):
    if "banking start" in values:
        if any(abs(float(values[key])) >= 90 for key in BANK_FIELDS):
            raise ValueError("Banking endpoints must be strictly between -90 and 90 degrees")
    if "profil start tangent left" in values:
        for endpoint in ("start", "end"):
            left = float(values[f"profil {endpoint} tangent left"])
            right = float(values[f"profil {endpoint} tangent right"])
            values[f"profil {endpoint} tangent"] = str((left+right)/2)
    return values


def validate_banking(name, parts, original, failures):
    banked = "banking start" in original
    if any(("banking start" in part) != banked for part in parts):
        failures.append(f"{name}: banking attributes added or removed")
        return
    if not banked:
        return
    for key, part in (("banking start", parts[0]), ("banking end", parts[-1])):
        if abs(float(part[key])-float(original[key])) > 1e-8:
            failures.append(f"{name}: endpoint {key} changed")
    for first, last in zip(parts[:-1], parts[1:], strict=True):
        if abs(float(first["banking end"])-float(last["banking start"])) > 1e-8:
            failures.append(f"{name}: banking discontinuity at replacement join")
        validate_edge_join(name, first, last, failures)
    validate_edge_endpoints(name, parts, original, failures)


def edge_grade(values, endpoint, side):
    return float(values.get(f"profil {endpoint} tangent {side}", values[f"profil {endpoint} tangent"]))


def validate_edge_join(name, first, last, failures):
    for side in ("left", "right"):
        if abs(edge_grade(first, "end", side)-edge_grade(last, "start", side)) > 1e-8:
            failures.append(f"{name}: {side} edge grade discontinuity")


def validate_edge_endpoints(name, parts, original, failures):
    for endpoint, part in (("start", parts[0]), ("end", parts[-1])):
        for side in ("left", "right"):
            if abs(edge_grade(part, endpoint, side)-edge_grade(original, endpoint, side)) > 1e-8:
                failures.append(f"{name}: endpoint {side} edge grade changed")
