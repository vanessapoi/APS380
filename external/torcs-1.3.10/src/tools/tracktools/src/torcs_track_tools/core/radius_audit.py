# /***************************************************************************
#     file                 : radius_audit.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""Read-only large-radius inventory, including legacy track XML and units."""

import math
from pathlib import Path

from torcs_track_tools.core.defaults import DISTANCE_TO_METERS
from torcs_track_tools.core.geometry import MAX_TORCS_RADIUS_M
from torcs_track_tools.core.track_xml import child_section, find_att, get_attstr, parse_xml_readonly


def metres(att):
    unit = att.get("unit", "")
    if unit not in DISTANCE_TO_METERS:
        raise ValueError(f"Unsupported radius unit: {unit}")
    value = float(att.get("val", "nan")) * DISTANCE_TO_METERS[unit]
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Radius must be finite and positive")
    return value


def audit_track(path: Path, limit: float = MAX_TORCS_RADIUS_M) -> dict:
    root = parse_xml_readonly(path).getroot()
    main = child_section(root, "Main Track")
    segments = child_section(main, "Track Segments")
    if segments is None:
        segments = child_section(main, "segments")
    if segments is None:
        raise ValueError("Missing track segment list")
    pits = child_section(main, "Pits")
    references = {get_attstr(pits, key) for key in ("entry", "start", "end", "exit")}
    hits = []
    for segment in segments:
        if get_attstr(segment, "type") not in ("lft", "rgt"):
            continue
        radius_att = find_att(segment, "attnum", "radius")
        if radius_att is None:
            raise ValueError(f"Missing radius: {segment.get('name')}")
        radius = metres(radius_att)
        end_att = find_att(segment, "attnum", "end radius")
        end_radius = metres(end_att) if end_att is not None else radius
        if max(radius, end_radius) > limit:
            hits.append({"name": segment.get("name"), "radius_m": radius, "end_radius_m": end_radius,
                          "pit_reference": segment.get("name") in references,
                         "banking_attributes": [dict(a.attrib) for a in segment if a.get("name") in ("banking start", "banking end")],
                         "child_sections": [s.get("name") for s in segment if s.tag == "section"]})
    return {"path": str(path), "segments": hits, "maximum_radius_m": max(
        (max(s["radius_m"], s["end_radius_m"]) for s in hits), default=0.0)}


def repair_preflight(path: Path, names: list[str]) -> dict:
    """Static schema/reference check only; runtime geometry still needs fitting."""
    from torcs_track_tools.core.radius_repair import selected_sections

    text = path.read_bytes().decode("utf-8")
    blocked = []
    for name in names:
        try:
            selected_sections(text, [name], "auto")
        except (ValueError, SyntaxError) as error:
            blocked.append({"segment": name, "reason": str(error)})
    return {"status": "blocked" if blocked else "eligible_for_fitting",
            "eligible_segments": len(names)-len(blocked), "blocked_segments": blocked}


def audit_tree(root: Path, limit: float = MAX_TORCS_RADIUS_M, preflight: bool = False) -> dict:
    if not math.isfinite(limit) or limit <= 0:
        raise ValueError("Radius limit must be finite and positive")
    if preflight and limit != MAX_TORCS_RADIUS_M:
        raise ValueError(f"Repair preflight requires the repair limit of {MAX_TORCS_RADIUS_M:g} m")
    paths = sorted(p for p in root.glob("*/*/*.xml") if p.stem == p.parent.name)
    if not paths:
        raise ValueError(f"No live track XMLs found under {root}")
    tracks, errors = [], []
    for path in paths:
        try:
            result = audit_track(path, limit)
            if result["segments"]:
                if preflight:
                    result["repair_preflight"] = repair_preflight(path, [s["name"] for s in result["segments"]])
                tracks.append(result)
        except (ValueError, OSError, SystemExit, SyntaxError) as error:
            errors.append({"path": str(path), "error": str(error)})
    tracks.sort(key=lambda t: t["maximum_radius_m"], reverse=True)
    report = {"limit_m": limit, "tracks_scanned": len(paths), "affected_tracks": len(tracks),
              "affected_segments": sum(len(t["segments"]) for t in tracks), "tracks": tracks, "errors": errors}
    if preflight:
        eligible = sum(t["repair_preflight"]["status"] == "eligible_for_fitting" for t in tracks)
        report["preflight"] = {"eligible_tracks": eligible, "blocked_tracks": len(tracks)-eligible,
                               "scope": "static XML support; does not establish geometric acceptance"}
    return report
