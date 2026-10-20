# /***************************************************************************
#
#     file                 : track_xml.py
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

"""Shared TORCS track XML helpers.

The CLI scripts intentionally remain small command wrappers.  XML attribute
lookup, entity preservation, segment length calculation, and pit-protection state
live here so tools do not grow subtly different TORCS XML interpretations.
"""

from __future__ import annotations

import pathlib
import re
import xml.etree.ElementTree as ET

from torcs_track_tools.core.defaults import BORDER_NAMES, DEFAULT_PROFILE_STEPS_LENGTH_M, ENTITY_PLACEHOLDER
from torcs_track_tools.core.geometry import Segment, segment_length_like


def find_att(section: ET.Element | None, tag: str, name: str) -> ET.Element | None:
    if section is None:
        return None
    for child in section:
        if child.tag == tag and child.get("name") == name:
            return child
    return None


def get_attnum(section: ET.Element | None, name: str, default: float = 0.0) -> float:
    att = find_att(section, "attnum", name)
    if att is None:
        return default
    try:
        return float(att.get("val", str(default)))
    except ValueError:
        return default


def get_attstr(section: ET.Element | None, name: str, default: str = "") -> str:
    att = find_att(section, "attstr", name)
    if att is None:
        return default
    return att.get("val", default)


def set_attnum(section: ET.Element, name: str, value: float, unit: str | None = None, precision: int = 4) -> None:
    att = find_att(section, "attnum", name)
    if att is None:
        att = ET.SubElement(section, "attnum")
        att.set("name", name)
    att.set("val", f"{value:.{precision}f}".rstrip("0").rstrip("."))
    if unit:
        att.set("unit", unit)


def set_attstr(section: ET.Element, name: str, value: str) -> None:
    att = find_att(section, "attstr", name)
    if att is None:
        att = ET.SubElement(section, "attstr")
        att.set("name", name)
    att.set("val", value)


def remove_attnum(section: ET.Element, name: str) -> None:
    att = find_att(section, "attnum", name)
    if att is not None:
        section.remove(att)


def child_section(parent: ET.Element | None, name: str) -> ET.Element | None:
    if parent is None:
        return None
    for child in parent:
        if child.tag == "section" and child.get("name") == name:
            return child
    return None


def get_or_make_child_section(parent: ET.Element, name: str) -> ET.Element:
    section = child_section(parent, name)
    if section is None:
        section = ET.SubElement(parent, "section")
        section.set("name", name)
    return section


def parse_xml_preserve_prolog(xml_path: pathlib.Path) -> tuple[str, ET.ElementTree]:
    raw = xml_path.read_text(encoding="utf-8")
    root_match = re.search(r"<params\b", raw)
    if not root_match:
        raise SystemExit(f"No <params> root found in {xml_path}")
    prolog = raw[: root_match.start()]
    replaced = raw[root_match.start() :].replace("&default-surfaces;", f"<{ENTITY_PLACEHOLDER}/>")
    return prolog, ET.ElementTree(ET.fromstring(replaced))


def parse_xml_readonly(xml_path: pathlib.Path) -> ET.ElementTree:
    raw = xml_path.read_text(encoding="utf-8")
    root_match = re.search(r"<params\b", raw)
    if not root_match:
        raise SystemExit(f"No <params> root found in {xml_path}")
    xml = raw[root_match.start() :]
    builtins = {"amp", "apos", "gt", "lt", "quot"}
    xml = re.sub(r"&([A-Za-z_][\w.:-]*);", lambda match: match.group(0) if match.group(1) in builtins else "", xml)
    return ET.ElementTree(ET.fromstring(xml))  # nosec B314 - local track-authoring input with external entities removed


def serialize_xml_restore_entity(prolog: str, tree: ET.ElementTree) -> str:
    ET.indent(tree, space="\t")
    root = tree.getroot()
    if root is None:
        raise SystemExit("Track XML tree has no root element")
    body = ET.tostring(root, encoding="unicode")
    body = body.replace(f"<{ENTITY_PLACEHOLDER} />", "&default-surfaces;")
    body = body.replace(f"<{ENTITY_PLACEHOLDER}/>", "&default-surfaces;")
    return prolog + body + "\n"


def parse_xml_preserve_entity(xml_path: pathlib.Path) -> tuple[str, ET.ElementTree]:
    raw = xml_path.read_text(encoding="utf-8")
    replaced = raw.replace("&default-surfaces;", f"<{ENTITY_PLACEHOLDER}/>")
    return raw, ET.ElementTree(ET.fromstring(replaced))


def turn_radii(seg: ET.Element) -> tuple[float, float]:
    radius = max(0.0, abs(get_attnum(seg, "radius", 0.0)))
    end_radius = max(0.0, abs(get_attnum(seg, "end radius", get_attnum(seg, "end-radius", radius))))
    return radius, end_radius


def segment_from_element(seg: ET.Element, default_profile_steps_length: float = DEFAULT_PROFILE_STEPS_LENGTH_M) -> Segment | None:
    name = seg.get("name", "")
    seg_type = get_attstr(seg, "type")
    if seg_type == "str":
        return Segment(
            name,
            "str",
            length=max(0.0, get_attnum(seg, "lg", 0.0)),
            profil_steps_length=get_attnum(seg, "profil steps length", default_profile_steps_length),
        )
    if seg_type in ("lft", "rgt"):
        radius, end_radius = turn_radii(seg)
        has_end_radius = find_att(seg, "attnum", "end radius") is not None or find_att(seg, "attnum", "end-radius") is not None
        return Segment(
            name,
            seg_type,
            radius=radius,
            arc_deg=abs(get_attnum(seg, "arc", 0.0)),
            end_radius=end_radius if has_end_radius else None,
            profil_steps_length=get_attnum(seg, "profil steps length", default_profile_steps_length),
        )
    return None


def segment_length(seg: ET.Element) -> float:
    segment = segment_from_element(seg)
    return 0.0 if segment is None else max(0.0, segment_length_like(segment))


def segment_sections(root: ET.Element) -> tuple[ET.Element, list[ET.Element]]:
    main_track = next((s for s in root.iter("section") if s.get("name") == "Main Track"), None)
    if main_track is None:
        raise SystemExit("Track XML has no Main Track section")
    track_segments = child_section(main_track, "Track Segments")
    if track_segments is None:
        raise SystemExit("Track XML has no Main Track/Track Segments section")
    return main_track, [s for s in track_segments if s.tag == "section"]


def border_state_from_section(section: ET.Element | None) -> dict[str, float | str]:
    return {
        "width": get_attnum(section, "width", 0.0),
        "height": get_attnum(section, "height", 0.0),
        "style": get_attstr(section, "style", ""),
        "surface": get_attstr(section, "surface", ""),
    }


def copy_border_states(state: dict[str, dict[str, float | str]]) -> dict[str, dict[str, float | str]]:
    return {name: dict(values) for name, values in state.items()}


def apply_border_override(seg_state: dict[str, dict[str, float | str]], border_name: str, border: ET.Element) -> None:
    values = seg_state[border_name]
    if find_att(border, "attnum", "width") is not None:
        values["width"] = get_attnum(border, "width", float(values["width"]))
    if find_att(border, "attnum", "height") is not None:
        values["height"] = get_attnum(border, "height", float(values["height"]))
    if find_att(border, "attstr", "style") is not None:
        values["style"] = get_attstr(border, "style", str(values["style"]))
    if find_att(border, "attstr", "surface") is not None:
        values["surface"] = get_attstr(border, "surface", str(values["surface"]))


def apply_segment_border_overrides(seg_state: dict[str, dict[str, float | str]], seg: ET.Element) -> None:
    for border_name in BORDER_NAMES:
        border = child_section(seg, border_name)
        if border is not None:
            apply_border_override(seg_state, border_name, border)


def effective_border_states(main_track: ET.Element, segs: list[ET.Element]) -> list[dict[str, dict[str, float | str]]]:
    state = {name: border_state_from_section(child_section(main_track, name)) for name in BORDER_NAMES}
    states: list[dict[str, dict[str, float | str]]] = []
    for seg in segs:
        seg_state = copy_border_states(state)
        apply_segment_border_overrides(seg_state, seg)
        states.append(seg_state)
        state = copy_border_states(seg_state)
    return states


def side_section_name(side: str) -> str:
    return "Left Side" if side == "left" else "Right Side"


def side_width_profile(section: ET.Element | None, inherited_width: float) -> tuple[float, float]:
    if section is None:
        return inherited_width, inherited_width
    start_width = get_attnum(section, "start width", inherited_width)
    width = get_attnum(section, "width", start_width)
    end_width = get_attnum(section, "end width", width)
    return start_width, end_width


def effective_side_width_profiles(main_track: ET.Element, segs: list[ET.Element]) -> list[dict[str, tuple[float, float]]]:
    state = {
        "left": get_attnum(child_section(main_track, "Left Side"), "width", 0.0),
        "right": get_attnum(child_section(main_track, "Right Side"), "width", 0.0),
    }
    profiles: list[dict[str, tuple[float, float]]] = []
    for seg in segs:
        profile: dict[str, tuple[float, float]] = {}
        for side in ("left", "right"):
            section = child_section(seg, side_section_name(side))
            start_width, end_width = side_width_profile(section, state[side])
            profile[side] = (start_width, end_width)
            state[side] = end_width
        profiles.append(profile)
    return profiles


def forward_inclusive_indices(count: int, start_idx: int, end_idx: int) -> list[int]:
    out = []
    idx = start_idx
    while len(out) < count:
        out.append(idx)
        if idx == end_idx:
            break
        idx = (idx + 1) % count
    return out


def named_pit_indices(pit_names: list[str], name_to_idx: dict[str, int]) -> set[int]:
    return {name_to_idx[name] for name in pit_names if name in name_to_idx}


def ranged_pit_indices(pit_names: list[str], name_to_idx: dict[str, int], count: int) -> set[int]:
    protected: set[int] = set()
    for first_name, last_name in ((pit_names[0], pit_names[1]), (pit_names[1], pit_names[2]), (pit_names[2], pit_names[3])):
        if first_name in name_to_idx and last_name in name_to_idx:
            protected.update(forward_inclusive_indices(count, name_to_idx[first_name], name_to_idx[last_name]))
    return protected


def pit_section_protected_indices(main_track: ET.Element, segs: list[ET.Element], name_to_idx: dict[str, int]) -> set[int]:
    pits = child_section(main_track, "Pits")
    if pits is None or get_attstr(pits, "type", "none") == "none":
        return set()
    pit_names = [get_attstr(pits, name, "") for name in ("entry", "start", "end", "exit")]
    return named_pit_indices(pit_names, name_to_idx) | ranged_pit_indices(pit_names, name_to_idx, len(segs))


def segment_has_wall_border(border_state: dict[str, dict[str, float | str]]) -> bool:
    for border_name in BORDER_NAMES:
        values = border_state[border_name]
        if str(values["style"]).lower() == "wall" or str(values["surface"]).lower() == "wall":
            return True
    return False


def segment_is_protected_by_border(border_state: dict[str, dict[str, float | str]]) -> bool:
    return segment_has_wall_border(border_state)


def pit_protected_indices(
    main_track: ET.Element,
    segs: list[ET.Element],
    border_states: list[dict[str, dict[str, float | str]]],
) -> set[int]:
    protected: set[int] = set()
    if not segs:
        return protected

    name_to_idx = {seg.get("name", ""): idx for idx, seg in enumerate(segs)}
    protected.update(pit_section_protected_indices(main_track, segs, name_to_idx))

    for idx, _seg in enumerate(segs):
        if segment_is_protected_by_border(border_states[idx]):
            protected.add(idx)
    return protected
