#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : adjust_side_overlap.py
#     created              : 06 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Reduce side widths where distant track sides overlap across narrow gaps."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from torcs_track_tools.core.geometry import Pose, advance_constant_turn, advance_straight, variable_turn_step_length
from torcs_track_tools.core.track_xml import (
    child_section,
    effective_border_states,
    effective_side_width_profiles,
    get_attnum,
    get_or_make_child_section,
    parse_xml_preserve_prolog,
    pit_protected_indices,
    segment_from_element,
    segment_length,
    segment_sections,
    serialize_xml_restore_entity,
    set_attnum,
)

ROUNDING_GAP_MARGIN = 1e-3


@dataclass(frozen=True)
class SideSample:
    x: float
    y: float
    heading: float
    s: float
    segment_index: int
    segment_name: str
    left_side_width: float
    right_side_width: float


@dataclass(frozen=True)
class OverlapCandidate:
    a: SideSample
    b: SideSample
    side_a: str
    side_b: str
    border_a: float
    border_b: float
    width_a: float
    width_b: float
    center_distance: float
    progress_separation: float
    gap: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adjust TORCS side widths where distant side envelopes overlap")
    parser.add_argument("--input", required=True, help="Input TORCS track XML")
    parser.add_argument("--output", default="", help="Output TORCS track XML; defaults to --input")
    parser.add_argument("--target-gap", type=float, default=2.0, help="Minimum open space between facing side envelopes")
    parser.add_argument("--sample-step", type=float, default=2.0, help="Centerline sampling interval for overlap checks")
    parser.add_argument(
        "--min-progress-separation",
        type=float,
        default=60.0,
        help="Ignore nearby samples whose centerline distance along the track is below this value",
    )
    parser.add_argument("--taper-length", type=float, default=45.0, help="Length in meters used to taper side widths before and after overlaps")
    parser.add_argument("--min-side-width", type=float, default=1.0, help="Smallest side width this tool may write")
    parser.add_argument("--side", choices=["left", "right", "both"], default="both", help="Limit adjustments to one side")
    parser.add_argument("--report", default="", help="Optional JSON report path")
    parser.add_argument("--dry-run", action="store_true", help="Report proposed changes without writing XML")
    return parser.parse_args()


def side_section_name(side: str) -> str:
    return "Left Side" if side == "left" else "Right Side"


def border_section_name(side: str) -> str:
    return "Left Border" if side == "left" else "Right Border"


def interpolated_width(profile: tuple[float, float], t: float) -> float:
    return profile[0] + (profile[1] - profile[0]) * t


def append_side_sample(
    samples: list[SideSample],
    profiles: list[dict[str, tuple[float, float]]],
    segment_index: int,
    segment_name: str,
    segment_start_s: float,
    segment_length_m: float,
    sample_count: int,
    k: int,
    cur_pose: Pose,
) -> None:
    t = k / sample_count
    samples.append(
        SideSample(
            cur_pose.x,
            cur_pose.y,
            cur_pose.heading,
            segment_start_s + segment_length_m * t,
            segment_index,
            segment_name,
            interpolated_width(profiles[segment_index]["left"], t),
            interpolated_width(profiles[segment_index]["right"], t),
        )
    )


def collect_straight_samples(
    samples: list[SideSample],
    profiles: list[dict[str, tuple[float, float]]],
    segment_index: int,
    segment_name: str,
    pose: Pose,
    segment_start_s: float,
    length: float,
    count: int,
) -> Pose:
    cur = pose
    step_len = length / count
    for k in range(count):
        append_side_sample(
            samples,
            profiles,
            segment_index,
            segment_name,
            segment_start_s,
            length,
            count,
            k,
            cur,
        )
        cur = advance_straight(cur, step_len)
    return cur


def collect_constant_turn_samples(
    samples: list[SideSample],
    profiles: list[dict[str, tuple[float, float]]],
    segment_index: int,
    segment_name: str,
    segment,
    pose: Pose,
    segment_start_s: float,
    length: float,
    count: int,
    arc_rad: float,
) -> Pose:
    cur = pose
    step_arc = arc_rad / count
    for k in range(count):
        append_side_sample(
            samples,
            profiles,
            segment_index,
            segment_name,
            segment_start_s,
            length,
            count,
            k,
            cur,
        )
        cur = advance_constant_turn(cur, segment.kind, segment.radius, step_arc)
    return cur


def collect_variable_turn_samples(
    samples: list[SideSample],
    profiles: list[dict[str, tuple[float, float]]],
    segment_index: int,
    segment_name: str,
    segment,
    pose: Pose,
    segment_start_s: float,
    length: float,
    count: int,
    arc_rad: float,
    end_radius: float,
) -> Pose:
    cur = pose
    step_len, dradius = variable_turn_step_length(segment.radius, end_radius, arc_rad, count)
    cur_radius = segment.radius
    for k in range(count):
        append_side_sample(
            samples,
            profiles,
            segment_index,
            segment_name,
            segment_start_s,
            length,
            count,
            k,
            cur,
        )
        cur = advance_constant_turn(cur, segment.kind, cur_radius, step_len / max(1e-9, cur_radius))
        cur_radius += dradius
    heading = pose.heading + (1.0 if segment.kind == "lft" else -1.0) * arc_rad
    return Pose(cur.x, cur.y, heading)


def collect_segment_samples(
    samples: list[SideSample],
    profiles: list[dict[str, tuple[float, float]]],
    segment_index: int,
    segment_name: str,
    segment,
    pose: Pose,
    segment_start_s: float,
    length: float,
    count: int,
) -> Pose:
    if segment.kind == "str":
        return collect_straight_samples(samples, profiles, segment_index, segment_name, pose, segment_start_s, length, count)
    arc_rad = math.radians(segment.arc_deg)
    end_radius = segment.radius if segment.end_radius is None else segment.end_radius
    if abs(end_radius - segment.radius) <= 1e-12:
        return collect_constant_turn_samples(
            samples,
            profiles,
            segment_index,
            segment_name,
            segment,
            pose,
            segment_start_s,
            length,
            count,
            arc_rad,
        )
    return collect_variable_turn_samples(
        samples,
        profiles,
        segment_index,
        segment_name,
        segment,
        pose,
        segment_start_s,
        length,
        count,
        arc_rad,
        end_radius,
    )


def collect_samples(main_track: ET.Element, segs: list[ET.Element], sample_step: float) -> tuple[list[SideSample], float]:
    profiles = effective_side_width_profiles(main_track, segs)
    samples: list[SideSample] = []
    pose = Pose(0.0, 0.0, 0.0)
    s_acc = 0.0
    for idx, seg in enumerate(segs):
        segment = segment_from_element(seg)
        if segment is None:
            continue
        name = seg.get("name", f"#{idx + 1}")
        length = max(0.0, segment_length(seg))
        count = max(1, int(math.ceil(length / max(1e-6, sample_step))))
        pose = collect_segment_samples(samples, profiles, idx, name, segment, pose, s_acc, length, count)
        s_acc += length
    return samples, s_acc


def side_toward(sample: SideSample, dx: float, dy: float) -> str:
    lateral = -math.sin(sample.heading) * dx + math.cos(sample.heading) * dy
    return "left" if lateral > 0.0 else "right"


def sample_side_width(sample: SideSample, side: str) -> float:
    return sample.left_side_width if side == "left" else sample.right_side_width


def sample_grid_cell(sample: SideSample, cell_size: float) -> tuple[int, int]:
    return math.floor(sample.x / cell_size), math.floor(sample.y / cell_size)


def neighbor_cells(cell: tuple[int, int]) -> list[tuple[int, int]]:
    return [(nx, ny) for nx in range(cell[0] - 1, cell[0] + 2) for ny in range(cell[1] - 1, cell[1] + 2)]


def nearby_prior_sample_pairs(
    samples: list[SideSample],
    grid: dict[tuple[int, int], list[int]],
    idx: int,
    sample: SideSample,
    cell: tuple[int, int],
    search_distance: float,
) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for neighbor in neighbor_cells(cell):
        for other_idx in grid.get(neighbor, []):
            other = samples[other_idx]
            if math.hypot(sample.x - other.x, sample.y - other.y) <= search_distance:
                pairs.append((other_idx, idx))
    return pairs


def sample_pairs(samples: list[SideSample], search_distance: float) -> list[tuple[int, int]]:
    if not samples:
        return []
    cell_size = max(1.0, search_distance)
    grid: dict[tuple[int, int], list[int]] = {}
    pairs: list[tuple[int, int]] = []
    for idx, sample in enumerate(samples):
        cell = sample_grid_cell(sample, cell_size)
        pairs.extend(nearby_prior_sample_pairs(samples, grid, idx, sample, cell, search_distance))
        grid.setdefault(cell, []).append(idx)
    return pairs


def side_overlap_defaults(main_track: ET.Element) -> dict[str, float]:
    left_side = child_section(main_track, "Left Side")
    right_side = child_section(main_track, "Right Side")
    left_border = child_section(main_track, "Left Border")
    right_border = child_section(main_track, "Right Border")
    return {
        "track_width": get_attnum(main_track, "width", 0.0),
        "left_side_width": get_attnum(left_side, "width", 0.0),
        "right_side_width": get_attnum(right_side, "width", 0.0),
        "left_border_width": get_attnum(left_border, "width", 0.0),
        "right_border_width": get_attnum(right_border, "width", 0.0),
    }


def side_overlap_search_distance(defaults: dict[str, float], samples: list[SideSample], target_gap: float) -> float:
    half_width = defaults["track_width"] * 0.5
    max_side_width = max(
        defaults["left_side_width"],
        defaults["right_side_width"],
        *(sample.left_side_width for sample in samples),
        *(sample.right_side_width for sample in samples),
    )
    max_border_width = max(defaults["left_border_width"], defaults["right_border_width"])
    return 2.0 * (half_width + max_side_width + max_border_width) + target_gap


def wrapped_progress_separation(a: SideSample, b: SideSample, total_len: float) -> float:
    progress_sep = abs(a.s - b.s)
    if total_len > 0.0:
        return min(progress_sep, total_len - progress_sep)
    return progress_sep


def side_filter_matches(side_filter: str, side_a: str, side_b: str) -> bool:
    return side_filter == "both" or side_a == side_filter or side_b == side_filter


def build_overlap_candidate(
    samples: list[SideSample],
    border_states: list[dict[str, dict[str, float | str]]],
    defaults: dict[str, float],
    total_len: float,
    min_progress_separation: float,
    side_filter: str,
    a_idx: int,
    b_idx: int,
) -> OverlapCandidate | None:
    a = samples[a_idx]
    b = samples[b_idx]
    progress_sep = wrapped_progress_separation(a, b, total_len)
    if progress_sep < min_progress_separation:
        return None
    dx = b.x - a.x
    dy = b.y - a.y
    side_a = side_toward(a, dx, dy)
    side_b = side_toward(b, -dx, -dy)
    if not side_filter_matches(side_filter, side_a, side_b):
        return None
    border_a = float(border_states[a.segment_index][border_section_name(side_a)]["width"])
    border_b = float(border_states[b.segment_index][border_section_name(side_b)]["width"])
    width_a = sample_side_width(a, side_a)
    width_b = sample_side_width(b, side_b)
    center_distance = math.hypot(dx, dy)
    half_width = defaults["track_width"] * 0.5
    gap = center_distance - half_width - border_a - width_a - half_width - border_b - width_b
    return OverlapCandidate(
        a,
        b,
        side_a,
        side_b,
        border_a,
        border_b,
        width_a,
        width_b,
        center_distance,
        progress_sep,
        gap,
    )


def side_is_adjustable(
    sample: SideSample,
    side: str,
    side_filter: str,
    protected_idxs: set[int],
    width: float,
    min_side_width: float,
) -> bool:
    return side_filter in ("both", side) and sample.segment_index not in protected_idxs and width > min_side_width


def overlap_slack(adjustable: bool, width: float, min_side_width: float) -> float:
    return max(0.0, width - min_side_width) if adjustable else 0.0


def distribute_overlap_reduction(required_reduction: float, slack_a: float, slack_b: float) -> tuple[float, float, float]:
    reduction_a = 0.0
    reduction_b = 0.0
    unresolved = required_reduction
    slack_sum = slack_a + slack_b
    if slack_sum <= 0.0:
        return reduction_a, reduction_b, unresolved

    reduction_a = min(slack_a, required_reduction * slack_a / slack_sum)
    reduction_b = min(slack_b, required_reduction - reduction_a)
    leftover = required_reduction - reduction_a - reduction_b
    if leftover > 1e-9 and slack_a - reduction_a > slack_b - reduction_b:
        extra = min(leftover, slack_a - reduction_a)
        reduction_a += extra
        leftover -= extra
    if leftover > 1e-9:
        extra = min(leftover, slack_b - reduction_b)
        reduction_b += extra
        leftover -= extra
    return reduction_a, reduction_b, max(0.0, leftover)


def update_overlap_proposal(
    proposals: dict[tuple[int, str], float],
    sample: SideSample,
    side: str,
    width: float,
    reduction: float,
    min_side_width: float,
) -> None:
    key = (sample.segment_index, side)
    proposals[key] = min(proposals.get(key, width), max(min_side_width, width - reduction))


def overlap_report(candidate: OverlapCandidate, target_gap: float, required_reduction: float, unresolved: float) -> dict:
    return {
        "sample_a": {
            "segment_index": candidate.a.segment_index,
            "segment": candidate.a.segment_name,
            "side": candidate.side_a,
            "side_width": candidate.width_a,
        },
        "sample_b": {
            "segment_index": candidate.b.segment_index,
            "segment": candidate.b.segment_name,
            "side": candidate.side_b,
            "side_width": candidate.width_b,
        },
        "center_distance": candidate.center_distance,
        "progress_separation": candidate.progress_separation,
        "gap": candidate.gap,
        "target_gap": target_gap,
        "required_reduction": required_reduction,
        "unresolved_deficit": unresolved,
    }


def apply_overlap_candidate(
    candidate: OverlapCandidate,
    proposals: dict[tuple[int, str], float],
    overlaps: list[dict],
    protected_idxs: set[int],
    target_gap: float,
    min_side_width: float,
    side_filter: str,
) -> None:
    if candidate.gap >= target_gap:
        return
    required_reduction = target_gap - candidate.gap + ROUNDING_GAP_MARGIN
    adjustable_a = side_is_adjustable(
        candidate.a,
        candidate.side_a,
        side_filter,
        protected_idxs,
        candidate.width_a,
        min_side_width,
    )
    adjustable_b = side_is_adjustable(
        candidate.b,
        candidate.side_b,
        side_filter,
        protected_idxs,
        candidate.width_b,
        min_side_width,
    )
    slack_a = overlap_slack(adjustable_a, candidate.width_a, min_side_width)
    slack_b = overlap_slack(adjustable_b, candidate.width_b, min_side_width)
    reduction_a, reduction_b, unresolved = distribute_overlap_reduction(required_reduction, slack_a, slack_b)
    if adjustable_a:
        update_overlap_proposal(proposals, candidate.a, candidate.side_a, candidate.width_a, reduction_a, min_side_width)
    if adjustable_b:
        update_overlap_proposal(proposals, candidate.b, candidate.side_b, candidate.width_b, reduction_b, min_side_width)
    overlaps.append(overlap_report(candidate, target_gap, required_reduction, unresolved))


def detect_overlaps(
    main_track: ET.Element,
    segs: list[ET.Element],
    border_states: list[dict[str, dict[str, float | str]]],
    protected_idxs: set[int],
    target_gap: float,
    sample_step: float,
    min_progress_separation: float,
    min_side_width: float,
    side_filter: str,
) -> tuple[dict[str, float], list[SideSample], float, list[dict], dict[tuple[int, str], float]]:
    samples, total_len = collect_samples(main_track, segs, sample_step)
    defaults = side_overlap_defaults(main_track)
    search_distance = side_overlap_search_distance(defaults, samples, target_gap)
    overlaps: list[dict] = []
    proposals: dict[tuple[int, str], float] = {}
    min_gap = math.inf
    for a_idx, b_idx in sample_pairs(samples, search_distance):
        candidate = build_overlap_candidate(samples, border_states, defaults, total_len, min_progress_separation, side_filter, a_idx, b_idx)
        if candidate is None:
            continue
        min_gap = min(min_gap, candidate.gap)
        apply_overlap_candidate(candidate, proposals, overlaps, protected_idxs, target_gap, min_side_width, side_filter)
    if math.isinf(min_gap):
        min_gap = 0.0
    return defaults, samples, min_gap, overlaps, proposals


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
    return sum(max(1e-6, segment_length(segs[idx])) for idx in forward_gap_indices(segs, start_idx, end_idx))


def segment_name(segs: list[ET.Element], idx: int) -> str:
    return segs[idx].get("name", f"#{idx + 1}")


def proposal_items_for_side(proposals: dict[tuple[int, str], float], side: str) -> list[tuple[int, float]]:
    return sorted((idx, target) for (idx, proposal_side), target in proposals.items() if proposal_side == side)


def proposal_gap_status(segs: list[ET.Element], start_idx: int, end_idx: int, protected_idxs: set[int]) -> tuple[float, bool]:
    gap_indices = forward_gap_indices(segs, start_idx, end_idx)
    gap_len = sum(max(1e-6, segment_length(segs[gap_idx])) for gap_idx in gap_indices)
    blocked = any(gap_idx in protected_idxs for gap_idx in gap_indices)
    return gap_len, blocked


def should_merge_proposal_run(run: dict, idx: int, segs: list[ET.Element], taper_len: float, protected_idxs: set[int]) -> bool:
    gap_len, blocked = proposal_gap_status(segs, run["end_index"], idx, protected_idxs)
    return not blocked and (run["end_index"] + 1 == idx or gap_len <= taper_len * 2.0)


def extend_proposal_run(run: dict, segs: list[ET.Element], idx: int, target: float) -> None:
    run["end_index"] = idx
    run["segments"].append(segment_name(segs, idx))
    run["target_width"] = min(run["target_width"], target)


def new_proposal_run(side: str, segs: list[ET.Element], idx: int, target: float) -> dict:
    return {
        "side": side,
        "start_index": idx,
        "end_index": idx,
        "segments": [segment_name(segs, idx)],
        "target_width": target,
    }


def merge_wraparound_side_runs(
    side_runs: list[dict],
    segs: list[ET.Element],
    taper_len: float,
    protected_idxs: set[int],
) -> list[dict]:
    if len(side_runs) <= 1:
        return side_runs
    gap_len, blocked = proposal_gap_status(segs, side_runs[-1]["end_index"], side_runs[0]["start_index"], protected_idxs)
    if not blocked and gap_len <= taper_len * 2.0:
        first = side_runs.pop(0)
        side_runs[-1]["wrap_start_index"] = first["start_index"]
        side_runs[-1]["segments"].extend(first["segments"])
        side_runs[-1]["target_width"] = min(side_runs[-1]["target_width"], first["target_width"])
    return side_runs


def merge_side_proposal_runs(
    proposals: dict[tuple[int, str], float],
    side: str,
    segs: list[ET.Element],
    taper_len: float,
    protected_idxs: set[int],
) -> list[dict]:
    side_runs: list[dict] = []
    for idx, target in proposal_items_for_side(proposals, side):
        if idx in protected_idxs:
            continue
        if side_runs and should_merge_proposal_run(side_runs[-1], idx, segs, taper_len, protected_idxs):
            extend_proposal_run(side_runs[-1], segs, idx, target)
        else:
            side_runs.append(new_proposal_run(side, segs, idx, target))
    return merge_wraparound_side_runs(side_runs, segs, taper_len, protected_idxs)


def merge_proposal_runs(proposals: dict[tuple[int, str], float], segs: list[ET.Element], taper_len: float, protected_idxs: set[int]) -> list[dict]:
    runs = []
    for side in ("left", "right"):
        runs.extend(merge_side_proposal_runs(proposals, side, segs, taper_len, protected_idxs))
    return sorted(runs, key=lambda run: run["start_index"])


def set_side_width(seg: ET.Element, side: str, start_width: float, end_width: float) -> None:
    side_section = get_or_make_child_section(seg, side_section_name(side))
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
    changed: list[str] = []
    run = 0.0
    total = max(1e-6, sum(max(1e-6, segment_length(segs[idx])) for idx in idxs))
    denom = max(1e-6, min(taper_len, total))
    for idx in idxs:
        seg = segs[idx]
        length = max(1e-6, segment_length(seg))
        t0 = min(1.0, run / denom)
        t1 = min(1.0, (run + length) / denom)
        set_side_width(seg, side, start_width + (end_width - start_width) * t0, start_width + (end_width - start_width) * t1)
        changed.append(seg.get("name", f"#{idx + 1}"))
        run += length
    return changed


def run_indices(run: dict, seg_count: int) -> list[int]:
    if "wrap_start_index" in run:
        return list(range(run["start_index"], seg_count)) + list(range(0, run["wrap_start_index"] + 1))
    return list(range(run["start_index"], run["end_index"] + 1))


def apply_adjustments(segs: list[ET.Element], defaults: dict[str, float], runs: list[dict], taper_len: float, protected_idxs: set[int]) -> list[dict]:
    applied: list[dict] = []
    for run in runs:
        side = run["side"]
        normal = defaults[f"{side}_side_width"]
        target = run["target_width"]
        bad_idxs = run_indices(run, len(segs))
        same_side_run_indices = {idx for other in runs if other["side"] == side for idx in run_indices(other, len(segs))} | protected_idxs
        taper_start_idx = run["start_index"]
        taper_end_idx = run.get("wrap_start_index", run["end_index"])
        before = taper_backward_indices(segs, taper_start_idx, same_side_run_indices, taper_len)
        after = taper_forward_indices(segs, taper_end_idx, same_side_run_indices, taper_len)
        overlap = set(before) & set(after)
        before_taper = [idx for idx in before if idx not in overlap]
        after_taper = [idx for idx in after if idx not in overlap]
        before_names = apply_taper(segs, before_taper, side, normal, target, taper_len)
        bad_names: list[str] = []
        for idx in [item for item in bad_idxs if item not in protected_idxs]:
            set_side_width(segs[idx], side, target, target)
            bad_names.append(segs[idx].get("name", f"#{idx + 1}"))
        overlap_names: list[str] = []
        for idx in sorted(overlap):
            set_side_width(segs[idx], side, target, target)
            overlap_names.append(segs[idx].get("name", f"#{idx + 1}"))
        after_names = apply_taper(segs, after_taper, side, target, normal, taper_len)
        applied.append(
            {
                **run,
                "normal_width": normal,
                "target_width": target,
                "incoming_taper_segments": before_names,
                "overlap_segments": bad_names,
                "overlap_taper_segments": overlap_names,
                "outgoing_taper_segments": after_names,
            }
        )
    return applied


def main() -> int:
    args = parse_args()
    input_xml = pathlib.Path(args.input)
    output_xml = pathlib.Path(args.output) if args.output else input_xml
    prolog, tree = parse_xml_preserve_prolog(input_xml)
    main_track, segs = segment_sections(tree.getroot())
    border_states = effective_border_states(main_track, segs)
    protected_idxs = pit_protected_indices(main_track, segs, border_states)
    defaults, samples, initial_min_gap, overlaps, proposals = detect_overlaps(
        main_track,
        segs,
        border_states,
        protected_idxs,
        args.target_gap,
        args.sample_step,
        args.min_progress_separation,
        args.min_side_width,
        args.side,
    )
    runs = merge_proposal_runs(proposals, segs, args.taper_length, protected_idxs)
    applied = [] if args.dry_run else apply_adjustments(segs, defaults, runs, args.taper_length, protected_idxs)

    final_min_gap = None
    final_overlaps: list[dict] = []
    if not args.dry_run:
        final_border_states = effective_border_states(main_track, segs)
        _, _, final_min_gap, final_overlaps, _ = detect_overlaps(
            main_track,
            segs,
            final_border_states,
            protected_idxs,
            args.target_gap,
            args.sample_step,
            args.min_progress_separation,
            args.min_side_width,
            args.side,
        )

    status = "dry-run" if args.dry_run else ("failed" if final_overlaps else "ok")

    report = {
        "input": str(input_xml),
        "output": str(output_xml),
        "dry_run": bool(args.dry_run),
        "target_gap": args.target_gap,
        "sample_step": args.sample_step,
        "min_progress_separation": args.min_progress_separation,
        "taper_length": args.taper_length,
        "min_side_width": args.min_side_width,
        "sample_count": len(samples),
        "status": status,
        "initial_min_gap": initial_min_gap,
        "final_min_gap": final_min_gap,
        "final_overlap_count": len(final_overlaps),
        "final_overlaps": final_overlaps[:200],
        "defaults": defaults,
        "protected_segments": [segs[idx].get("name", f"#{idx + 1}") for idx in sorted(protected_idxs)],
        "overlap_count": len(overlaps),
        "proposal_count": len(proposals),
        "overlaps": overlaps[:200],
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

    print(f"Detected {len(overlaps)} side-overlap samples in {input_xml}")
    print(f"Proposed {len(proposals)} side-width reductions across {len(runs)} runs")
    if final_min_gap is not None:
        print(f"Final estimated minimum side gap: {final_min_gap:.3f} m")
    if args.dry_run:
        print("Dry run: XML not written")
    else:
        print(f"Wrote adjusted XML: {output_xml}")
    if args.report:
        print(f"Wrote report: {args.report}")
    if final_overlaps:
        print("Side-overlap adjustment failed; unresolved overlaps remain")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
