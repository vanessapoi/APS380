#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : apply_segments_to_track.py
#     created              : 20 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Apply a fitted TORCS segment snippet to a full track XML template.

This keeps all non-mainline track metadata from the template and replaces only
`Main Track/Track Segments` with a deterministic segment list produced by a
tracktools segment drafter/fitter.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import pathlib
import re
import xml.etree.ElementTree as ET

from torcs_track_tools.core.defaults import DEFAULT_LICENSE, DEFAULT_PROFILE_STEPS_LENGTH_M, ENTITY_PLACEHOLDER, PLACEHOLDER_AUTHORS
from torcs_track_tools.core.track_georeference import fit_reference, reference_for_segment, remove_reference, set_reference


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply segments.xml to a track XML template")
    parser.add_argument("--template-xml", required=True, help="Template/full track XML path")
    parser.add_argument("--segments-xml", required=True, help="Segment snippet XML path produced by a tracktools drafter/fitter")
    parser.add_argument("--output-xml", required=True, help="Output rebuilt track XML path")
    parser.add_argument("--track-name", default="", help="Optional override for track name")
    parser.add_argument("--author", default="", help="Required non-placeholder track author")
    parser.add_argument("--license", default=DEFAULT_LICENSE, help="Track license statement")
    parser.add_argument("--category", default="", help="Optional override for Header/category")
    parser.add_argument("--description", default="", help="Optional override for Header/description")
    parser.add_argument("--graphic-description", default="", help="Optional override for Graphic/3d description (for example kyalami.ac)")
    parser.add_argument("--start-segment", default="", help="Optional segment name to force as first Track Segments entry")
    parser.add_argument("--georeference-source", default="", help="Geographic source JSON; otherwise use the segment JSON sidecar")
    parser.add_argument("--segment-name-prefix", default="", help="Optional prefix for generic output segment names")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not write output")
    return parser.parse_args()


def _find_att(section: ET.Element, tag: str, name: str) -> ET.Element | None:
    for child in section:
        if child.tag == tag and child.get("name") == name:
            return child
    return None


def set_attstr(section: ET.Element, name: str, value: str) -> None:
    att = _find_att(section, "attstr", name)
    if att is None:
        att = ET.SubElement(section, "attstr")
        att.set("name", name)
    att.set("val", value)


def validate_author(author: str) -> str:
    clean = author.strip()
    if clean.lower() in PLACEHOLDER_AUTHORS:
        raise SystemExit("A real track author is required; placeholder authors such as OpenCode are not allowed")
    return clean


def default_description(track_name: str) -> str:
    clean = track_name.strip()
    if clean:
        return f"{clean} track layout generated for TORCS."
    return "Track layout generated for TORCS."


def xml_file_header(file_name: str, author: str, license_text: str) -> str:
    year = datetime.date.today().year
    created = datetime.date.today().strftime("%d %b %Y")
    return (
        "<!-- \n"
        f"    file                 : {file_name}\n"
        f"    created              : {created}\n"
        f"    copyright            : (C) {year} by {author}\n"
        f"    license              : {license_text}\n"
        "-->\n\n"
        "<!--    This program is free software; you can redistribute it and/or modify  -->\n"
        "<!--    it under the terms of the GNU General Public License as published by  -->\n"
        "<!--    the Free Software Foundation; either version 2 of the License, or     -->\n"
        "<!--    (at your option) any later version.                                   -->\n\n"
    )


def get_attnum(section: ET.Element, name: str, default: float = 0.0) -> float:
    att = _find_att(section, "attnum", name)
    if att is None:
        return default
    try:
        return float(att.get("val", str(default)))
    except ValueError:
        return default


def set_attnum(section: ET.Element, name: str, value: float, unit: str | None = None) -> None:
    att = _find_att(section, "attnum", name)
    if att is None:
        att = ET.SubElement(section, "attnum")
        att.set("name", name)
    att.set("val", f"{value:.4f}".rstrip("0").rstrip("."))
    if unit:
        att.set("unit", unit)


def remove_attnum(section: ET.Element, name: str) -> None:
    att = _find_att(section, "attnum", name)
    if att is not None:
        section.remove(att)


def get_child_section(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if child.tag == "section" and child.get("name") == name:
            return child
    return None


def parse_xml_preserve_entity(xml_path: pathlib.Path) -> tuple[str, ET.ElementTree]:
    raw = xml_path.read_text(encoding="utf-8")
    replaced = raw.replace("&default-surfaces;", f"<{ENTITY_PLACEHOLDER}/>")
    tree = ET.ElementTree(ET.fromstring(replaced))
    return raw, tree


def serialize_xml_restore_entity(raw: str, tree: ET.ElementTree, header_comment: str = "") -> str:
    root = tree.getroot()
    ET.indent(tree, space="\t")
    body = ET.tostring(root, encoding="unicode")
    body = body.replace(f"<{ENTITY_PLACEHOLDER} />", "&default-surfaces;")
    body = body.replace(f"<{ENTITY_PLACEHOLDER}/>", "&default-surfaces;")

    decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    doctype = ""
    m = re.search(r"(<!DOCTYPE\s+params\s+SYSTEM\s+\"[^\"]+\"\s*\[[\s\S]*?\]>)", raw)
    if m:
        doctype = m.group(1) + "\n\n"
    return decl + header_comment + doctype + body + "\n"


def parse_segments_snippet(snippet_path: pathlib.Path) -> list[ET.Element]:
    raw = snippet_path.read_text(encoding="utf-8").strip()
    wrapped = f"<wrapper>\n{raw}\n</wrapper>"
    root = ET.fromstring(wrapped)
    segs = [child for child in root if child.tag == "section"]
    if not segs:
        raise SystemExit("No <section> segments found in segments snippet")
    return segs


def choose_start_straight_index(segs: list[ET.Element]) -> int:
    best_idx = -1
    best_score = float("inf")
    n = len(segs)
    for i, seg in enumerate(segs):
        seg_type_att = _find_att(seg, "attstr", "type")
        seg_type_val = seg_type_att.get("val", "") if seg_type_att is not None else ""
        if seg_type_val != "str":
            continue
        if (seg.get("name", "")).startswith("Closure Helper"):
            continue
        lg = get_attnum(seg, "lg", 0.0)
        if lg < 20.0:
            continue
        rotated = segs[i:] + segs[:i]
        pos_err, head_err_deg = end_pose_error(rotated)
        prev_seg = segs[(i - 1) % n]
        next_seg = segs[(i + 1) % n]
        prev_arc = abs(get_attnum(prev_seg, "arc", 0.0))
        next_arc = abs(get_attnum(next_seg, "arc", 0.0))
        # Small stability bonus for keeping the current start when it is already
        # competitive, but always score every candidate because seam placement
        # can materially change closure readiness.
        keep_start_bonus = -0.5 if i == 0 else 0.0
        score = 8.0 * head_err_deg + pos_err + 0.5 * (prev_arc + next_arc) - 0.01 * min(lg, 300.0) + keep_start_bonus
        if score < best_score:
            best_score = score
            best_idx = i
    return best_idx


def rotate_segments_to_start_straight(segs: list[ET.Element], forced_start: str = "") -> tuple[list[ET.Element], str]:
    if forced_start:
        for i, seg in enumerate(segs):
            if seg.get("name", "") == forced_start:
                rotated = segs[i:] + segs[:i]
                return rotated, rotated[0].get("name", "")
        raise SystemExit(f"Forced start segment not found: {forced_start}")
    idx = choose_start_straight_index(segs)
    if idx < 0:
        return segs, ""
    rotated = segs[idx:] + segs[:idx]
    return rotated, rotated[0].get("name", "")


def split_start_straight_for_closure(segs: list[ET.Element]) -> tuple[list[ET.Element], str]:
    if not segs:
        return segs, ""
    first = segs[0]
    seg_type_att = _find_att(first, "attstr", "type")
    seg_type_val = seg_type_att.get("val", "") if seg_type_att is not None else ""
    if seg_type_val != "str":
        return segs, ""
    lg = get_attnum(first, "lg", 0.0)
    if lg < 24.0:
        return segs, ""
    helper_len = min(20.0, max(8.0, round_to_step(lg * 0.25, 1.0)))
    rem_len = lg - helper_len
    if rem_len < 12.0:
        return segs, ""

    helper = ET.fromstring(ET.tostring(first, encoding="unicode"))
    helper.set("name", "Closure Start")
    set_attnum(helper, "lg", helper_len, "m")

    remainder = ET.fromstring(ET.tostring(first, encoding="unicode"))
    set_attnum(remainder, "lg", rem_len, "m")

    return [helper, remainder] + segs[1:], helper.get("name", "")


def rename_segments_with_prefix(segs: list[ET.Element], prefix: str) -> list[ET.Element]:
    clean = prefix.strip()
    if not clean:
        return segs
    width = max(3, len(str(len(segs))))
    for idx, seg in enumerate(segs, start=1):
        seg.set("name", f"{clean}-{idx:0{width}d}")
    return segs


def round_to_half(v: float) -> float:
    return round(v * 2.0) / 2.0


def round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(value / step) * step


def norm_angle(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def simulate_segment_end(x: float, y: float, h: float, seg: ET.Element) -> tuple[float, float, float]:
    seg_type_att = _find_att(seg, "attstr", "type")
    seg_type_val = seg_type_att.get("val", "") if seg_type_att is not None else ""
    if seg_type_val == "str":
        lg = get_attnum(seg, "lg", 0.0)
        return x + lg * math.cos(h), y + lg * math.sin(h), h
    if seg_type_val in ("lft", "rgt"):
        radius = max(1e-6, abs(get_attnum(seg, "radius", 0.0)))
        arc = math.radians(get_attnum(seg, "arc", 0.0))
        sign = 1.0 if seg_type_val == "lft" else -1.0
        cx = x - sign * radius * math.sin(h)
        cy = y + sign * radius * math.cos(h)
        h2 = h + sign * arc
        x2 = cx + sign * radius * math.sin(h2)
        y2 = cy - sign * radius * math.cos(h2)
        return x2, y2, h2
    return x, y, h


def end_pose_error(segs: list[ET.Element]) -> tuple[float, float]:
    x = y = h = 0.0
    for seg in segs:
        x, y, h = simulate_segment_end(x, y, h, seg)
    pos_err = math.hypot(x, y)
    head_err_deg = abs(math.degrees(norm_angle(h)))
    return pos_err, head_err_deg


def make_helper_segment(name: str, seg_type: str, value_a: float, value_b: float = 0.0) -> ET.Element:
    seg = ET.Element("section", {"name": name})
    set_attstr(seg, "type", seg_type)
    if seg_type == "str":
        set_attnum(seg, "lg", value_a, "m")
    else:
        set_attnum(seg, "radius", value_a, "m")
        set_attnum(seg, "arc", value_b, "deg")
    set_attnum(seg, "z end", 0.0, "m")
    return seg


def append_closure_helpers(segs: list[ET.Element]) -> tuple[list[ET.Element], dict]:
    pos_err, head_err_deg = end_pose_error(segs)
    info = {"applied": False, "position_error_m": pos_err, "heading_error_deg": head_err_deg, "helpers": []}
    if pos_err <= 5.0 and head_err_deg <= 1.0:
        return segs, info

    out = list(segs)
    x = y = h = 0.0
    for seg in out:
        x, y, h = simulate_segment_end(x, y, h, seg)
    dx = -x
    dy = -y
    target_h = math.atan2(dy, dx) if abs(dx) + abs(dy) > 1e-9 else 0.0
    turn1 = norm_angle(target_h - h)
    if abs(math.degrees(turn1)) >= 0.1:
        radius = round_to_step(max(25.0, min(200.0, max(25.0, math.hypot(dx, dy) * 0.5))), 1.0)
        seg = make_helper_segment("Closure Helper Turn A", "lft" if turn1 > 0 else "rgt", radius, round_to_step(abs(math.degrees(turn1)), 0.1))
        out.append(seg)
        info["helpers"].append(seg.get("name", ""))
        x, y, h = simulate_segment_end(x, y, h, seg)
    dist_to_start = math.hypot(-x, -y)
    if dist_to_start >= 2.0:
        seg = make_helper_segment("Closure Helper Straight", "str", round_to_step(dist_to_start, 1.0))
        out.append(seg)
        info["helpers"].append(seg.get("name", ""))
        x, y, h = simulate_segment_end(x, y, h, seg)
    turn2 = norm_angle(-h)
    if abs(math.degrees(turn2)) >= 0.1:
        seg = make_helper_segment("Closure Helper Turn B", "lft" if turn2 > 0 else "rgt", 80.0, round_to_step(abs(math.degrees(turn2)), 0.1))
        out.append(seg)
        info["helpers"].append(seg.get("name", ""))
    info["applied"] = bool(info["helpers"])
    pos_after, head_after = end_pose_error(out)
    info["position_error_m_after"] = pos_after
    info["heading_error_deg_after"] = head_after
    if pos_after > pos_err + 1e-6:
        info["applied"] = False
        info["helpers"] = []
        return segs, info
    return out, info


def synthesize_profile_steps(main_track: ET.Element, segs: list[ET.Element]) -> int:
    # Keep a stable global fallback and add local refinement only where turn
    # curvature warrants it.
    set_attnum(main_track, "profil steps length", DEFAULT_PROFILE_STEPS_LENGTH_M, "m")
    local_count = 0
    for seg in segs:
        seg_type = _find_att(seg, "attstr", "type")
        seg_type_val = seg_type.get("val", "") if seg_type is not None else ""
        if seg_type_val in ("lft", "rgt"):
            radius = abs(get_attnum(seg, "radius", 0.0))
            if radius > 1e-6:
                step = round_to_half(0.35 * math.sqrt(radius))
                step = max(2.0, min(6.0, step))
                if step < 5.95:
                    set_attnum(seg, "profil steps length", step, "m")
                    local_count += 1
                    continue
        remove_attnum(seg, "profil steps length")
    return local_count


def apply_segments_paths(args: argparse.Namespace) -> tuple[str, str, pathlib.Path, pathlib.Path, pathlib.Path]:
    author = validate_author(args.author)
    license_text = args.license.strip() or DEFAULT_LICENSE
    return author, license_text, pathlib.Path(args.template_xml), pathlib.Path(args.segments_xml), pathlib.Path(args.output_xml)


def prepared_segments(segments_xml: pathlib.Path, start_segment: str, segment_name_prefix: str) -> tuple[list[ET.Element], str]:
    new_segments = parse_segments_snippet(segments_xml)
    new_segments, start_straight_name = rotate_segments_to_start_straight(new_segments, start_segment.strip())
    return rename_segments_with_prefix(new_segments, segment_name_prefix), start_straight_name


def main_track_sections(root: ET.Element) -> tuple[ET.Element, ET.Element]:
    main_track = next((s for s in root.iter("section") if s.get("name") == "Main Track"), None)
    if main_track is None:
        raise SystemExit("Main Track section not found in template")
    track_segments = get_child_section(main_track, "Track Segments")
    if track_segments is None:
        raise SystemExit("Main Track/Track Segments section not found in template")
    return main_track, track_segments


def replace_track_segments(track_segments: ET.Element, new_segments: list[ET.Element]) -> None:
    for child in list(track_segments):
        if child.tag == "section":
            track_segments.remove(child)
    for seg in new_segments:
        track_segments.append(seg)


def update_header_metadata(root: ET.Element, args: argparse.Namespace, author: str) -> None:
    if args.track_name:
        root.set("name", args.track_name)

    header = next((s for s in root.iter("section") if s.get("name") == "Header"), None)
    if header is None:
        return
    if args.track_name:
        set_attstr(header, "name", args.track_name)
    set_attstr(header, "author", author)
    if args.category:
        set_attstr(header, "category", args.category)
    set_attstr(header, "description", args.description.strip() or default_description(args.track_name or root.get("name", "")))


def update_graphic_metadata(root: ET.Element, args: argparse.Namespace) -> None:
    graphic = next((s for s in root.iter("section") if s.get("name") == "Graphic"), None)
    if graphic is None:
        return
    graphic_desc = args.graphic_description.strip()
    if not graphic_desc:
        graphic_desc = f"{args.track_name.strip().lower()}.ac" if args.track_name.strip() else ""
    if graphic_desc:
        set_attstr(graphic, "3d description", graphic_desc)


def print_dry_run_summary(
    template_xml: pathlib.Path,
    segments_xml: pathlib.Path,
    new_segments: list[ET.Element],
    start_straight_name: str,
    closure_start_name: str,
    closure_helper_info: dict,
    local_profile_count: int,
) -> None:
    print(f"Validated template: {template_xml}")
    print(f"Validated segments: {segments_xml}")
    print(f"Segment count: {len(new_segments)}")
    print(f"Start straight: {start_straight_name or 'none'}")
    print(f"Closure start helper: {closure_start_name or 'none'}")
    print(f"Closure helpers: {closure_helper_info}")
    print(f"Local profil steps length overrides: {local_profile_count}")


def write_applied_track(raw: str, tree: ET.ElementTree, output_xml: pathlib.Path, author: str, license_text: str) -> None:
    output_xml.parent.mkdir(parents=True, exist_ok=True)
    out_text = serialize_xml_restore_entity(raw, tree, xml_file_header(output_xml.name, author, license_text))
    output_xml.write_text(out_text, encoding="utf-8")


def print_apply_summary(
    template_xml: pathlib.Path,
    segments_xml: pathlib.Path,
    output_xml: pathlib.Path,
    new_segments: list[ET.Element],
    start_straight_name: str,
    closure_start_name: str,
    closure_helper_info: dict,
    local_profile_count: int,
) -> None:
    print(f"Applied {len(new_segments)} segments")
    print(f"Start straight: {start_straight_name or 'none'}")
    print(f"Closure start helper: {closure_start_name or 'none'}")
    print(f"Closure helpers: {closure_helper_info}")
    print(f"Local profil steps length overrides: {local_profile_count}")
    print(f"Template: {template_xml}")
    print(f"Segments: {segments_xml}")
    print(f"Wrote track XML: {output_xml}")


def apply_georeference(root: ET.Element, segments_xml: pathlib.Path, start_name: str, explicit_source: str) -> None:
    """Replace template metadata using a verified sidecar or an explicit source."""
    remove_reference(root)
    source_path = pathlib.Path(explicit_source) if explicit_source else segments_xml.with_suffix(".json")
    if not source_path.is_file():
        return
    data = json.loads(source_path.read_text(encoding="utf-8-sig"))
    snippet = segments_xml.read_text(encoding="utf-8")
    matches = data.get("georeference_snippet_sha256") == hashlib.sha256(snippet.encode("utf-8")).hexdigest()
    if not explicit_source and not matches:
        return
    source_data = data if explicit_source else data.get("georeference_source")
    if not source_data:
        return
    try:
        if not explicit_source and data.get("georeference_start"):
            geo = reference_for_segment(snippet, start_name, data["georeference_start"])
        else:
            geo, _ = fit_reference(ET.tostring(root, encoding="unicode"), source_data)
        set_reference(root, geo)
    except ValueError as error:
        print(f"Georeference unavailable: {error}")


def main() -> int:
    args = parse_args()
    author, license_text, template_xml, segments_xml, output_xml = apply_segments_paths(args)

    raw, tree = parse_xml_preserve_entity(template_xml)
    root = tree.getroot()
    new_segments, start_straight_name = prepared_segments(segments_xml, args.start_segment, args.segment_name_prefix)
    closure_start_name = ""
    closure_helper_info = {"applied": False, "disabled": True, "helpers": []}

    main_track, track_segments = main_track_sections(root)
    replace_track_segments(track_segments, new_segments)
    local_profile_count = synthesize_profile_steps(main_track, new_segments)
    update_header_metadata(root, args, author)
    update_graphic_metadata(root, args)
    apply_georeference(root, segments_xml, start_straight_name, args.georeference_source)

    if args.dry_run:
        print_dry_run_summary(template_xml, segments_xml, new_segments, start_straight_name, closure_start_name, closure_helper_info, local_profile_count)
        return 0

    write_applied_track(raw, tree, output_xml, author, license_text)
    print_apply_summary(template_xml, segments_xml, output_xml, new_segments, start_straight_name, closure_start_name, closure_helper_info, local_profile_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
