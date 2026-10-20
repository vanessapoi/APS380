#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : adjust_side_clearance.py
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

"""Reduce effective inner side widths where tight turns invert side geometry."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import xml.etree.ElementTree as ET

from torcs_track_tools.core.track_xml import (
    child_section,
    effective_border_states,
    effective_side_width_profiles,
    forward_inclusive_indices,
    get_attnum,
    get_attstr,
    get_or_make_child_section,
    parse_xml_preserve_prolog,
    pit_protected_indices,
    segment_length,
    segment_sections,
    serialize_xml_restore_entity,
    set_attnum,
    turn_radii,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adjust TORCS effective side widths where tight turns would invert side/barrier geometry")
    parser.add_argument("--input", required=True, help="Input TORCS track XML")
    parser.add_argument("--output", default="", help="Output TORCS track XML; defaults to --input")
    parser.add_argument("--clearance-margin", type=float, default=0.5, help="Minimum clearance from turn center after track half-width, border, and side")
    parser.add_argument("--taper-length", type=float, default=35.0, help="Length in meters used to taper side widths before and after anomalies")
    parser.add_argument("--min-side-width", type=float, default=0.5, help="Smallest side width this tool may write")
    parser.add_argument("--side", choices=["left", "right", "both"], default="both", help="Limit adjustments to one effective inner side")
    parser.add_argument("--report", default="", help="Optional JSON report path with protected and hard-protected segment lists")
    parser.add_argument("--dry-run", action="store_true", help="Report proposed changes without writing XML")
    return parser.parse_args()


def side_names(seg_type: str) -> tuple[str, str, str]:
    if seg_type == "lft":
        return "left", "Left Side", "Left Border"
    return "right", "Right Side", "Right Border"


def pit_range_indices(main_track: ET.Element, segs: list[ET.Element]) -> set[int]:
    if not segs:
        return set()
    name_to_idx = {seg.get("name", ""): idx for idx, seg in enumerate(segs)}
    pits = child_section(main_track, "Pits")
    if pits is None or get_attstr(pits, "type", "none") == "none":
        return set()
    start = get_attstr(pits, "start", "")
    end = get_attstr(pits, "end", "")
    if start in name_to_idx and end in name_to_idx:
        return set(forward_inclusive_indices(len(segs), name_to_idx[start], name_to_idx[end]))
    return set()


def is_generated_pit_segment(seg: ET.Element) -> bool:
    name = seg.get("name", "").lower()
    return name.startswith("pit_main") or name.startswith("pit_host")


def border_state_is_wall(border_state: dict[str, float | str]) -> bool:
    return str(border_state["style"]).lower() == "wall" or str(border_state["surface"]).lower() == "wall"


def segment_has_wall_border(border_states: dict[str, dict[str, float | str]]) -> bool:
    return any(border_state_is_wall(border_state) for border_state in border_states.values())


def hard_protected_indices(
    main_track: ET.Element,
    segs: list[ET.Element],
    border_states: list[dict[str, dict[str, float | str]]],
) -> set[int]:
    protected = pit_range_indices(main_track, segs)
    for idx, seg in enumerate(segs):
        if is_generated_pit_segment(seg) or segment_has_wall_border(border_states[idx]):
            protected.add(idx)
    return protected


def collect_anomalies(
    main_track: ET.Element,
    segs: list[ET.Element],
    border_states: list[dict[str, dict[str, float | str]]],
    side_profiles: list[dict[str, tuple[float, float]]],
    protected_idxs: set[int],
    clearance_margin: float,
    min_side_width: float,
    side_filter: str,
) -> tuple[dict[str, float], list[dict]]:
    left_side = child_section(main_track, "Left Side")
    right_side = child_section(main_track, "Right Side")
    left_border = child_section(main_track, "Left Border")
    right_border = child_section(main_track, "Right Border")
    defaults = {
        "track_width": get_attnum(main_track, "width", 0.0),
        "left_side_width": get_attnum(left_side, "width", 0.0),
        "right_side_width": get_attnum(right_side, "width", 0.0),
        "left_border_width": get_attnum(left_border, "width", 0.0),
        "right_border_width": get_attnum(right_border, "width", 0.0),
    }

    anomalies: list[dict] = []
    for idx, seg in enumerate(segs):
        seg_type = get_attstr(seg, "type")
        if seg_type not in ("lft", "rgt"):
            continue
        side, _, border_name = side_names(seg_type)
        if side_filter != "both" and side_filter != side:
            continue
        start_radius, end_radius = turn_radii(seg)
        radius = min(start_radius, end_radius)
        side_start_width, side_end_width = side_profiles[idx][side]
        side_width = max(side_start_width, side_end_width)
        default_side_width = defaults[f"{side}_side_width"]
        if idx in protected_idxs and side_width <= default_side_width:
            continue
        border_width = float(border_states[idx][border_name]["width"])
        required = defaults["track_width"] * 0.5 + side_width + border_width + clearance_margin
        # Summing the component widths can round an exact boundary a few ULPs
        # above the radius. Do not propose a femtometre-scale width reduction.
        if radius >= required or math.isclose(radius, required, rel_tol=0.0, abs_tol=4*math.ulp(required)):
            continue

        safe_width = radius - defaults["track_width"] * 0.5 - border_width - clearance_margin
        adjusted = max(min_side_width, safe_width)
        anomalies.append(
            {
                "index": idx,
                "segment": seg.get("name", f"#{idx + 1}"),
                "type": seg_type,
                "side": side,
                "radius": radius,
                "start_radius": start_radius,
                "end_radius": end_radius,
                "arc_deg": abs(get_attnum(seg, "arc", 0.0)),
                "old_side_width": side_width,
                "old_side_start_width": side_start_width,
                "old_side_end_width": side_end_width,
                "new_side_width": adjusted,
                "border_width": border_width,
                "clearance_margin": clearance_margin,
                "deficit": required - radius,
                "unresolved_deficit": max(0.0, min_side_width - safe_width),
                "protected": idx in protected_idxs,
            }
        )
    return defaults, anomalies


def forward_gap_indices(segs: list[ET.Element], start_idx: int, end_idx: int) -> list[int]:
    if not segs or start_idx == end_idx:
        return []
    out: list[int] = []
    idx = start_idx
    while len(out) < len(segs):
        idx = (idx + 1) % len(segs)
        if idx == end_idx:
            break
        out.append(idx)
    return out


def forward_gap_length(segs: list[ET.Element], start_idx: int, end_idx: int) -> float:
    if start_idx == end_idx:
        return 0.0
    return sum(max(1e-6, segment_length(segs[idx])) for idx in forward_gap_indices(segs, start_idx, end_idx))


def gap_status(segs: list[ET.Element], start_idx: int, end_idx: int, protected_idxs: set[int]) -> tuple[float, bool]:
    gap_indices = forward_gap_indices(segs, start_idx, end_idx)
    return forward_gap_length(segs, start_idx, end_idx), any(idx in protected_idxs for idx in gap_indices)


def anomalies_for_side(anomalies: list[dict], side: str) -> list[dict]:
    return sorted((item for item in anomalies if item["side"] == side), key=lambda item: item["index"])


def should_merge_anomaly_run(run: dict, anomaly: dict, segs: list[ET.Element], taper_len: float, protected_idxs: set[int]) -> bool:
    gap_len, blocked = gap_status(segs, run["end_index"], anomaly["index"], protected_idxs)
    return not blocked and (run["end_index"] + 1 == anomaly["index"] or gap_len <= taper_len * 2.0)


def extend_anomaly_run(run: dict, anomaly: dict) -> None:
    run["end_index"] = anomaly["index"]
    run["segments"].append(anomaly["segment"])
    run["target_width"] = min(run["target_width"], anomaly["new_side_width"])


def new_anomaly_run(anomaly: dict) -> dict:
    return {
        "side": anomaly["side"],
        "start_index": anomaly["index"],
        "end_index": anomaly["index"],
        "segments": [anomaly["segment"]],
        "target_width": anomaly["new_side_width"],
    }


def merge_wraparound_anomaly_runs(
    side_runs: list[dict],
    segs: list[ET.Element],
    taper_len: float,
    protected_idxs: set[int],
) -> list[dict]:
    if len(side_runs) <= 1:
        return side_runs
    gap_len, blocked = gap_status(segs, side_runs[-1]["end_index"], side_runs[0]["start_index"], protected_idxs)
    if not blocked and gap_len <= taper_len * 2.0:
        first = side_runs.pop(0)
        side_runs[-1]["wrap_start_index"] = first["start_index"]
        side_runs[-1]["segments"].extend(first["segments"])
        side_runs[-1]["target_width"] = min(side_runs[-1]["target_width"], first["target_width"])
    return side_runs


def merge_side_anomaly_runs(
    anomalies: list[dict],
    side: str,
    segs: list[ET.Element],
    taper_len: float,
    protected_idxs: set[int],
) -> list[dict]:
    side_runs: list[dict] = []
    for anomaly in anomalies_for_side(anomalies, side):
        if side_runs and should_merge_anomaly_run(side_runs[-1], anomaly, segs, taper_len, protected_idxs):
            extend_anomaly_run(side_runs[-1], anomaly)
        else:
            side_runs.append(new_anomaly_run(anomaly))
    return merge_wraparound_anomaly_runs(side_runs, segs, taper_len, protected_idxs)


def merge_anomaly_runs(anomalies: list[dict], segs: list[ET.Element], taper_len: float, protected_idxs: set[int] | None = None) -> list[dict]:
    protected_idxs = protected_idxs or set()
    runs: list[dict] = []
    for side in ("left", "right"):
        runs.extend(merge_side_anomaly_runs(anomalies, side, segs, taper_len, protected_idxs))
    return sorted(runs, key=lambda run: run["start_index"])


def set_side_width(seg: ET.Element, side: str, start_width: float, end_width: float) -> None:
    side_section_name = "Left Side" if side == "left" else "Right Side"
    side_section = get_or_make_child_section(seg, side_section_name)
    set_attnum(side_section, "start width", max(0.0, start_width), "m")
    set_attnum(side_section, "end width", max(0.0, end_width), "m")


def taper_backward_indices(segs: list[ET.Element], start_idx: int, stop_idxs: set[int], taper_len: float) -> list[int]:
    out: list[int] = []
    acc = 0.0
    idx = start_idx
    while acc < taper_len and len(out) < len(segs):
        idx = (idx - 1 + len(segs)) % len(segs)
        if idx in stop_idxs:
            break
        out.append(idx)
        acc += max(1e-6, segment_length(segs[idx]))
    out.reverse()
    return out


def taper_forward_indices(segs: list[ET.Element], end_idx: int, stop_idxs: set[int], taper_len: float) -> list[int]:
    out: list[int] = []
    acc = 0.0
    idx = end_idx
    while acc < taper_len and len(out) < len(segs):
        idx = (idx + 1) % len(segs)
        if idx in stop_idxs:
            break
        out.append(idx)
        acc += max(1e-6, segment_length(segs[idx]))
    return out


def apply_taper(segs: list[ET.Element], idxs: list[int], side: str, start_width: float, end_width: float, taper_len: float) -> list[str]:
    if not idxs:
        return []
    run = 0.0
    total = max(1e-6, sum(max(1e-6, segment_length(segs[idx])) for idx in idxs))
    denom = max(1e-6, min(taper_len, total))
    changed: list[str] = []
    for idx in idxs:
        seg = segs[idx]
        length = max(1e-6, segment_length(seg))
        t0 = min(1.0, run / denom)
        t1 = min(1.0, (run + length) / denom)
        set_side_width(seg, side, start_width + (end_width - start_width) * t0, start_width + (end_width - start_width) * t1)
        changed.append(seg.get("name", f"#{idx + 1}"))
        run += length
    return changed


def anomaly_run_indices(run: dict, seg_count: int) -> list[int]:
    if "wrap_start_index" in run:
        return list(range(run["start_index"], seg_count)) + list(range(0, run["wrap_start_index"] + 1))
    return list(range(run["start_index"], run["end_index"] + 1))


def anomaly_run_taper_bounds(run: dict) -> tuple[int, int]:
    return run["start_index"], run.get("wrap_start_index", run["end_index"])


def same_side_anomaly_run_indices(runs: list[dict], side: str, seg_count: int) -> set[int]:
    return {idx for other in runs if other["side"] == side for idx in anomaly_run_indices(other, seg_count)}


def split_taper_overlap(before: list[int], after: list[int]) -> tuple[list[int], set[int], list[int]]:
    overlap = set(before) & set(after)
    return [idx for idx in before if idx not in overlap], overlap, [idx for idx in after if idx not in overlap]


def taper_start_width(
    side_profiles: list[dict[str, tuple[float, float]]] | None,
    before_taper: list[int],
    side: str,
    normal: float,
) -> float:
    return side_profiles[before_taper[0]][side][0] if side_profiles is not None and before_taper else normal


def taper_end_width(
    side_profiles: list[dict[str, tuple[float, float]]] | None,
    after_taper: list[int],
    side: str,
    normal: float,
) -> float:
    return side_profiles[after_taper[-1]][side][1] if side_profiles is not None and after_taper else normal


def apply_constant_side_width(segs: list[ET.Element], idxs: list[int], side: str, target: float) -> list[str]:
    changed: list[str] = []
    for idx in idxs:
        set_side_width(segs[idx], side, target, target)
        changed.append(segs[idx].get("name", f"#{idx + 1}"))
    return changed


def adjustment_taper_indices(
    segs: list[ET.Element],
    run: dict,
    runs: list[dict],
    side: str,
    taper_len: float,
    protected_idxs: set[int],
) -> tuple[list[int], set[int], list[int]]:
    taper_start_idx, taper_end_idx = anomaly_run_taper_bounds(run)
    stop_idxs = same_side_anomaly_run_indices(runs, side, len(segs)) | protected_idxs
    before = taper_backward_indices(segs, taper_start_idx, stop_idxs, taper_len)
    after = taper_forward_indices(segs, taper_end_idx, stop_idxs, taper_len)
    return split_taper_overlap(before, after)


def apply_adjustment_run(
    segs: list[ET.Element],
    defaults: dict[str, float],
    run: dict,
    runs: list[dict],
    taper_len: float,
    protected_idxs: set[int],
    side_profiles: list[dict[str, tuple[float, float]]] | None,
) -> dict:
    side = run["side"]
    normal = defaults[f"{side}_side_width"]
    target = run["target_width"]
    bad_idxs = anomaly_run_indices(run, len(segs))
    before_taper, overlap, after_taper = adjustment_taper_indices(segs, run, runs, side, taper_len, protected_idxs)
    before_names = apply_taper(
        segs,
        before_taper,
        side,
        taper_start_width(side_profiles, before_taper, side, normal),
        target,
        taper_len,
    )
    bad_names = apply_constant_side_width(segs, [idx for idx in bad_idxs if idx not in protected_idxs], side, target)
    overlap_names = apply_constant_side_width(segs, sorted(overlap), side, target)
    after_names = apply_taper(
        segs,
        after_taper,
        side,
        target,
        taper_end_width(side_profiles, after_taper, side, normal),
        taper_len,
    )
    return {
        **run,
        "normal_width": normal,
        "target_width": target,
        "incoming_taper_segments": before_names,
        "anomaly_segments": bad_names,
        "overlap_taper_segments": overlap_names,
        "outgoing_taper_segments": after_names,
    }


def apply_adjustments(
    segs: list[ET.Element],
    defaults: dict[str, float],
    runs: list[dict],
    taper_len: float,
    protected_idxs: set[int] | None = None,
    side_profiles: list[dict[str, tuple[float, float]]] | None = None,
) -> list[dict]:
    protected_idxs = protected_idxs or set()
    return [
        apply_adjustment_run(segs, defaults, run, runs, taper_len, protected_idxs, side_profiles)
        for run in runs
    ]


def main() -> int:
    args = parse_args()
    input_xml = pathlib.Path(args.input)
    output_xml = pathlib.Path(args.output) if args.output else input_xml
    prolog, tree = parse_xml_preserve_prolog(input_xml)
    main_track, segs = segment_sections(tree.getroot())
    border_states = effective_border_states(main_track, segs)
    side_profiles = effective_side_width_profiles(main_track, segs)
    protected_idxs = pit_protected_indices(main_track, segs, border_states)
    hard_protected_idxs = hard_protected_indices(main_track, segs, border_states)
    defaults, anomalies = collect_anomalies(
        main_track,
        segs,
        border_states,
        side_profiles,
        protected_idxs,
        args.clearance_margin,
        args.min_side_width,
        args.side,
    )
    adjustable_anomalies = [anomaly for anomaly in anomalies if anomaly["index"] not in hard_protected_idxs]
    runs = merge_anomaly_runs(adjustable_anomalies, segs, args.taper_length, hard_protected_idxs)
    applied = [] if args.dry_run else apply_adjustments(segs, defaults, runs, args.taper_length, hard_protected_idxs, side_profiles)

    report = {
        "input": str(input_xml),
        "output": str(output_xml),
        "dry_run": bool(args.dry_run),
        "clearance_margin": args.clearance_margin,
        "taper_length": args.taper_length,
        "min_side_width": args.min_side_width,
        "defaults": defaults,
        "protected_segments": [segs[idx].get("name", f"#{idx + 1}") for idx in sorted(protected_idxs)],
        "hard_protected_segments": [segs[idx].get("name", f"#{idx + 1}") for idx in sorted(hard_protected_idxs)],
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "runs": runs,
        "applied_runs": applied,
    }

    if args.report:
        report_path = pathlib.Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not args.dry_run:
        output_xml.parent.mkdir(parents=True, exist_ok=True)
        output_xml.write_text(serialize_xml_restore_entity(prolog, tree), encoding="utf-8")

    print(f"Detected {len(anomalies)} side-clearance anomalies in {input_xml}")
    if args.dry_run:
        print("Dry run: XML not written")
    else:
        print(f"Wrote adjusted XML: {output_xml}")
    if args.report:
        print(f"Wrote report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
