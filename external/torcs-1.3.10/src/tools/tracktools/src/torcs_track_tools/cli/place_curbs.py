#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : place_curbs.py
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

"""Place safe TORCS curbs without hand-editing segment XML.

The tool has two independent passes:
1) The inside pass puts a curb on the inside border of qualifying tight/medium
   turn segments.  It does not split geometry.
2) The outside pass approximates the K1999 raceline, finds approach/exit zones
   where that line runs near the outside edge, and curbs only short runs there.
   It snaps to existing segment boundaries when they are close enough and splits
   only straights or constant-radius turns when a shorter run is needed.

Before either pass runs, the global left/right borders are normalized to flat
1 m plan borders.  After curbs are placed, explicit flat-border resets are added
after each curb run because TORCS carries side/border state forward.  The tool
will not replace pit-protected borders, wall borders, or variable-radius turns.

If the outside pass reports any ``outside_splits``, the caller must re-close the
track XML before generating assets because segment splitting can change the
trackgen closure residual by a small amount.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import pathlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from torcs_track_tools.core.defaults import BORDER_NAMES, LEFT_CURB_SURFACE, NORMAL_BORDER_SURFACE, RIGHT_CURB_SURFACE
from torcs_track_tools.core.track_xml import (
    child_section,
    effective_border_states,
    find_att,
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

RACELINE_SECURITY_R = 100.0
EPSILON = 1e-6


@dataclass
class EdgeSample:
    station: float
    segment_index: int
    segment: str
    left: tuple[float, float]
    right: tuple[float, float]
    lane: float
    target: tuple[float, float]


@dataclass(frozen=True)
class SegmentSpan:
    index: int
    start: float
    end: float
    length: float
    name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Place inside and raceline-guided outside curbs on TORCS track segments")
    parser.add_argument("--input", required=True, help="Input TORCS track XML")
    parser.add_argument("--output", default="", help="Output TORCS track XML; defaults to --input")
    parser.add_argument("--placement", choices=["inside", "outside", "both"], default="both", help="Which curb placement pass to run")
    parser.add_argument("--max-radius", type=float, default=250.0, help="Largest turn radius that receives curbs")
    parser.add_argument("--min-arc-deg", type=float, default=3.0, help="Smallest turn angle that receives curbs")
    parser.add_argument("--border-width", type=float, default=1.0, help="Border/curb width to write")
    parser.add_argument("--border-height", type=float, default=0.04, help="Curb height to write")
    parser.add_argument("--flat-border-surface", default=NORMAL_BORDER_SURFACE, help="Surface for normal flat borders")
    parser.add_argument("--side", choices=["left", "right", "both"], default="both", help="Limit inside curb placement to one side")
    parser.add_argument("--outside-max-run-m", type=float, default=40.0, help="Maximum length of one outside curb run")
    parser.add_argument("--outside-min-run-m", type=float, default=8.0, help="Minimum length of one outside curb run")
    parser.add_argument("--outside-merge-gap-m", type=float, default=6.0, help="Merge raceline edge-contact samples across this station gap")
    parser.add_argument(
        "--outside-context-m",
        type=float,
        default=0.0,
        help="Maximum distance from a qualifying turn for outside curb placement; 0 derives from max run length",
    )
    parser.add_argument(
        "--raceline-edge-tolerance-m",
        type=float,
        default=0.35,
        help="Tolerance beyond the K1999 outside security lane used to detect edge-contact ranges",
    )
    parser.add_argument("--raceline-step-m", type=float, default=2.0, help="Sampling step for the K1999 raceline approximation")
    parser.add_argument("--split-boundary-tolerance-m", type=float, default=5.0, help="Snap desired curb ends to nearby segment boundaries")
    parser.add_argument("--segment-fit-ratio", type=float, default=0.85, help="Use a whole segment if the desired curb covers this fraction")
    parser.add_argument("--min-split-piece-m", type=float, default=8.0, help="Avoid creating split segment pieces shorter than this")
    parser.add_argument("--report", default="", help="Optional JSON report path")
    parser.add_argument("--dry-run", action="store_true", help="Report proposed changes without writing XML")
    return parser.parse_args()


def set_attstr(section: ET.Element, name: str, value: str) -> None:
    att = find_att(section, "attstr", name)
    if att is None:
        att = ET.SubElement(section, "attstr")
        att.set("name", name)
    att.set("val", value)


def set_attnum_precise(section: ET.Element, name: str, value: float, unit: str | None = None, precision: int = 9) -> None:
    att = find_att(section, "attnum", name)
    if att is None:
        att = ET.SubElement(section, "attnum")
        att.set("name", name)
    att.set("val", f"{value:.{precision}f}".rstrip("0").rstrip("."))
    if unit:
        att.set("unit", unit)


def remove_attnum(section: ET.Element, name: str) -> None:
    att = find_att(section, "attnum", name)
    if att is not None:
        section.remove(att)


def normalize_main_borders(main_track: ET.Element, border_width: float, flat_surface: str) -> None:
    for border_name in BORDER_NAMES:
        border = get_or_make_child_section(main_track, border_name)
        set_flat_border(border, border_width, flat_surface)


def set_flat_border(border: ET.Element, border_width: float, flat_surface: str) -> None:
    set_attnum(border, "width", border_width, "m")
    remove_attnum(border, "height")
    set_attstr(border, "style", "plan")
    set_attstr(border, "surface", flat_surface)


def set_curb_border(seg: ET.Element, border_name: str, border_width: float, border_height: float) -> None:
    border = get_or_make_child_section(seg, border_name)
    set_attnum(border, "width", border_width, "m")
    set_attnum(border, "height", border_height, "m")
    set_attstr(border, "style", "curb")
    set_attstr(border, "surface", curb_surface(border_name))


def direct_border_is_wall(seg: ET.Element, border_name: str) -> bool:
    border = child_section(seg, border_name)
    if border is None:
        return False
    return get_attstr(border, "style", "").lower() == "wall" or get_attstr(border, "surface", "").lower() == "wall"


def direct_border_is_curb(seg: ET.Element, border_name: str) -> bool:
    border = child_section(seg, border_name)
    if border is None:
        return False
    surface = get_attstr(border, "surface", "").lower()
    return get_attstr(border, "style", "").lower() == "curb" and surface.startswith("curb-")


def border_state_is_wall(border_state: dict[str, float | str]) -> bool:
    return str(border_state["style"]).lower() == "wall" or str(border_state["surface"]).lower() == "wall"


def inside_side_and_border(seg_type: str) -> tuple[str, str]:
    if seg_type == "lft":
        return "left", "Left Border"
    return "right", "Right Border"


def outside_border_for_turn(seg_type: str) -> str:
    if seg_type == "lft":
        return "Right Border"
    return "Left Border"


def curb_surface(border_name: str) -> str:
    if border_name.startswith("Left"):
        return LEFT_CURB_SURFACE
    return RIGHT_CURB_SURFACE


def qualifies_for_turn_curb(seg: ET.Element, max_radius: float, min_arc_deg: float) -> tuple[bool, dict]:
    seg_type = get_attstr(seg, "type")
    if seg_type not in ("lft", "rgt"):
        return False, {}
    start_radius, end_radius = turn_radii(seg)
    radius = min(start_radius, end_radius)
    arc_deg = abs(get_attnum(seg, "arc", 0.0))
    return radius > 0.0 and radius <= max_radius and arc_deg >= min_arc_deg, {
        "type": seg_type,
        "radius": radius,
        "start_radius": start_radius,
        "end_radius": end_radius,
        "arc_deg": arc_deg,
    }


def qualifies_for_inside_curb(seg: ET.Element, side_filter: str, max_radius: float, min_arc_deg: float) -> tuple[bool, dict]:
    qualifies, meta = qualifies_for_turn_curb(seg, max_radius, min_arc_deg)
    if not qualifies:
        return False, {}
    side, border_name = inside_side_and_border(str(meta["type"]))
    if side_filter != "both" and side_filter != side:
        return False, {}
    return True, {**meta, "side": side, "border": border_name}


def placed_curb_indices_by_border(segs: list[ET.Element]) -> dict[str, set[int]]:
    placed_idxs_by_border: dict[str, set[int]] = {name: set() for name in BORDER_NAMES}
    for idx, seg in enumerate(segs):
        for border_name in BORDER_NAMES:
            if direct_border_is_curb(seg, border_name):
                placed_idxs_by_border[border_name].add(idx)
    return placed_idxs_by_border


def add_carry_over_resets(
    segs: list[ET.Element],
    placed_idxs_by_border: dict[str, set[int]],
    border_states: list[dict[str, dict[str, float | str]]],
    protected_idxs: set[int],
    border_width: float,
    flat_surface: str,
) -> list[dict]:
    resets: list[dict] = []
    if not segs:
        return resets
    for border_name in BORDER_NAMES:
        placed_idxs = placed_idxs_by_border[border_name]
        for idx in sorted(placed_idxs):
            next_idx = (idx + 1) % len(segs)
            if next_idx in placed_idxs:
                continue
            if direct_border_is_wall(segs[next_idx], border_name) or border_state_is_wall(border_states[next_idx][border_name]):
                resets.append(
                    {
                        "index": next_idx,
                        "segment": segs[next_idx].get("name", f"#{next_idx + 1}"),
                        "border": border_name,
                        "skipped": "wall",
                    }
                )
                continue
            if next_idx in protected_idxs and child_section(segs[next_idx], border_name) is not None:
                resets.append(
                    {
                        "index": next_idx,
                        "segment": segs[next_idx].get("name", f"#{next_idx + 1}"),
                        "border": border_name,
                        "skipped": "protected",
                    }
                )
                continue
            border = get_or_make_child_section(segs[next_idx], border_name)
            set_flat_border(border, border_width, flat_surface)
            resets.append(
                {
                    "index": next_idx,
                    "segment": segs[next_idx].get("name", f"#{next_idx + 1}"),
                    "border": border_name,
                    "surface": flat_surface,
                }
            )
    return resets


def place_inside_curbs(
    segs: list[ET.Element],
    protected_idxs: set[int],
    args: argparse.Namespace,
) -> tuple[list[dict], list[dict]]:
    placed: list[dict] = []
    skipped_protected: list[dict] = []

    for idx, seg in enumerate(segs):
        qualifies, meta = qualifies_for_inside_curb(seg, args.side, args.max_radius, args.min_arc_deg)
        if not qualifies:
            continue
        item = {"index": idx, "segment": seg.get("name", f"#{idx + 1}"), **meta}
        if idx in protected_idxs:
            skipped_protected.append(item)
            continue

        set_curb_border(seg, str(meta["border"]), args.border_width, args.border_height)
        placed.append({**item, "surface": curb_surface(str(meta["border"])), "placement": "inside"})
    return placed, skipped_protected


def track_width(main_track: ET.Element) -> float:
    return max(EPSILON, get_attnum(main_track, "width", 12.0))


def segment_spans(segs: list[ET.Element]) -> list[SegmentSpan]:
    spans: list[SegmentSpan] = []
    station = 0.0
    for idx, seg in enumerate(segs):
        length = max(0.0, segment_length(seg))
        spans.append(SegmentSpan(idx, station, station + length, length, seg.get("name", f"#{idx + 1}")))
        station += length
    return spans


def point_on_segment(start_pose: tuple[float, float, float], seg: ET.Element, local_s: float) -> tuple[float, float, float]:
    x, y, h = start_pose
    seg_type = get_attstr(seg, "type")
    if seg_type == "str":
        return x + local_s * math.cos(h), y + local_s * math.sin(h), h

    if seg_type not in ("lft", "rgt"):
        return x, y, h

    length = max(EPSILON, segment_length(seg))
    radius, end_radius = turn_radii(seg)
    radius = max(EPSILON, 0.5 * (radius + end_radius))
    arc = math.radians(abs(get_attnum(seg, "arc", 0.0))) * max(0.0, min(1.0, local_s / length))
    sign = 1.0 if seg_type == "lft" else -1.0
    cx = x - sign * radius * math.sin(h)
    cy = y + sign * radius * math.cos(h)
    hk = h + sign * arc
    return cx + sign * radius * math.sin(hk), cy - sign * radius * math.cos(hk), hk


def edge_points(x: float, y: float, h: float, width: float) -> tuple[tuple[float, float], tuple[float, float]]:
    half_width = 0.5 * width
    left = (x - math.sin(h) * half_width, y + math.cos(h) * half_width)
    right = (x + math.sin(h) * half_width, y - math.cos(h) * half_width)
    return left, right


def sample_track_edges(segs: list[ET.Element], width: float, step_m: float) -> tuple[list[EdgeSample], float]:
    spans = segment_spans(segs)
    total = spans[-1].end if spans else 0.0
    if total <= EPSILON:
        return [], 0.0

    start_poses: list[tuple[float, float, float]] = []
    pose = (0.0, 0.0, 0.0)
    for seg, span in zip(segs, spans, strict=True):
        start_poses.append(pose)
        pose = point_on_segment(pose, seg, span.length)

    samples: list[EdgeSample] = []
    step = max(0.5, step_m)
    sample_count = max(2, int(math.floor(total / step)))
    span_idx = 0
    for sample_idx in range(sample_count):
        station = min(total - EPSILON, sample_idx * step)
        while span_idx + 1 < len(spans) and station >= spans[span_idx].end - EPSILON:
            span_idx += 1
        span = spans[span_idx]
        x, y, h = point_on_segment(start_poses[span_idx], segs[span_idx], station - span.start)
        left, right = edge_points(x, y, h, width)
        target = ((left[0] + right[0]) * 0.5, (left[1] + right[1]) * 0.5)
        samples.append(EdgeSample(station, span.index, span.name, left, right, 0.5, target))
    return samples, total


def interpolate_lane(sample: EdgeSample) -> None:
    lx, ly = sample.left
    rx, ry = sample.right
    lane = sample.lane
    sample.target = (lane * rx + (1.0 - lane) * lx, lane * ry + (1.0 - lane) * ly)


def inverse_radius(samples: list[EdgeSample], prev: int, point: tuple[float, float], nxt: int) -> float:
    px, py = point
    nx, ny = samples[nxt].target
    qx, qy = samples[prev].target
    x1 = nx - px
    y1 = ny - py
    x2 = qx - px
    y2 = qy - py
    x3 = nx - qx
    y3 = ny - qy
    det = x1 * y2 - x2 * y1
    n1 = x1 * x1 + y1 * y1
    n2 = x2 * x2 + y2 * y2
    n3 = x3 * x3 + y3 * y3
    denom = math.sqrt(max(EPSILON, n1 * n2 * n3))
    return 2.0 * det / denom


def projected_lane_from_neighbors(
    sample: EdgeSample,
    prev_sample: EdgeSample,
    next_sample: EdgeSample,
) -> float | None:
    nx, ny = next_sample.target
    px, py = prev_sample.target
    lx, ly = sample.left
    rx, ry = sample.right
    denom = (ny - py) * (rx - lx) - (nx - px) * (ry - ly)
    if abs(denom) <= EPSILON:
        return None
    return (-(ny - py) * (lx - px) + (nx - px) * (ly - py)) / denom


def raceline_lane_limits(
    track_width_m: float,
    side_dist_ext: float,
    side_dist_int: float,
    security: float,
) -> tuple[float, float]:
    return min(0.5, (side_dist_ext + security) / track_width_m), min(0.5, (side_dist_int + security) / track_width_m)


def clamp_positive_curvature_lane(lane: float, old_lane: float, ext_lane: float, int_lane: float) -> float:
    if lane < int_lane:
        lane = int_lane
    if 1.0 - lane < ext_lane:
        return min(old_lane, lane) if 1.0 - old_lane < ext_lane else 1.0 - ext_lane
    return lane


def clamp_negative_curvature_lane(lane: float, old_lane: float, ext_lane: float, int_lane: float) -> float:
    if lane < ext_lane:
        lane = max(old_lane, lane) if old_lane < ext_lane else ext_lane
    if 1.0 - lane < int_lane:
        return 1.0 - int_lane
    return lane


def clamp_raceline_lane_for_curvature(
    lane: float,
    old_lane: float,
    target_inverse_radius: float,
    ext_lane: float,
    int_lane: float,
) -> float:
    if target_inverse_radius >= 0.0:
        return clamp_positive_curvature_lane(lane, old_lane, ext_lane, int_lane)
    return clamp_negative_curvature_lane(lane, old_lane, ext_lane, int_lane)


def adjust_raceline_radius(
    samples: list[EdgeSample],
    prev: int,
    idx: int,
    nxt: int,
    target_inverse_radius: float,
    track_width_m: float,
    side_dist_ext: float,
    side_dist_int: float,
    security: float = 0.0,
) -> None:
    sample = samples[idx]
    old_lane = sample.lane
    lx, ly = sample.left
    rx, ry = sample.right
    projected_lane = projected_lane_from_neighbors(sample, samples[prev], samples[nxt])
    if projected_lane is None:
        return

    sample.lane = max(-0.2, min(1.2, projected_lane))
    interpolate_lane(sample)

    d_lane = 0.0001
    dx = d_lane * (rx - lx)
    dy = d_lane * (ry - ly)
    d_inverse_radius = inverse_radius(samples, prev, (sample.target[0] + dx, sample.target[1] + dy), nxt)

    if d_inverse_radius > 0.000000001:
        sample.lane += (d_lane / d_inverse_radius) * target_inverse_radius
        ext_lane, int_lane = raceline_lane_limits(track_width_m, side_dist_ext, side_dist_int, security)
        sample.lane = clamp_raceline_lane_for_curvature(sample.lane, old_lane, target_inverse_radius, ext_lane, int_lane)

    interpolate_lane(sample)


def smooth_raceline_step(samples: list[EdgeSample], step: int, track_width_m: float, side_dist_ext: float, side_dist_int: float) -> None:
    count = len(samples)
    if count <= step:
        return
    prev = ((count - step) // step) * step
    prevprev = prev - step
    nxt = step
    nextnext = nxt + step

    for idx in range(0, count - step + 1, step):
        ri0 = inverse_radius(samples, prevprev % count, samples[prev].target, idx)
        ri1 = inverse_radius(samples, idx, samples[nxt % count].target, nextnext % count)
        l_prev = math.dist(samples[idx].target, samples[prev].target)
        l_next = math.dist(samples[idx].target, samples[nxt % count].target)
        target_inverse_radius = (l_next * ri0 + l_prev * ri1) / max(EPSILON, l_next + l_prev)
        security = l_prev * l_next / (8.0 * RACELINE_SECURITY_R)
        adjust_raceline_radius(samples, prev, idx, nxt % count, target_inverse_radius, track_width_m, side_dist_ext, side_dist_int, security)

        prevprev = prev
        prev = idx
        nxt = nextnext
        nextnext = nxt + step
        if nextnext > count - step:
            nextnext = 0


def interpolate_raceline_step(samples: list[EdgeSample], step: int, track_width_m: float, side_dist_ext: float, side_dist_int: float) -> None:
    count = len(samples)
    if step <= 1 or count <= step:
        return
    starts = list(range(step, count - step + 1, step))
    for end in starts + [count]:
        start = end - step
        nxt = (end + step) % count
        if nxt > count - step:
            nxt = 0
        prev = (((count + start - step) % count) // step) * step
        if prev > count - step:
            prev -= step
        i_min = start
        i_max = end % count
        ri0 = inverse_radius(samples, prev % count, samples[i_min].target, i_max)
        ri1 = inverse_radius(samples, i_min, samples[i_max].target, nxt)
        for idx in range(end - 1, start, -1):
            mix = float(idx - i_min) / float(end - i_min)
            target_inverse_radius = mix * ri1 + (1.0 - mix) * ri0
            adjust_raceline_radius(samples, i_min, idx % count, i_max, target_inverse_radius, track_width_m, side_dist_ext, side_dist_int)


def generate_k1999_raceline(samples: list[EdgeSample], track_width_m: float, side_dist_ext: float, side_dist_int: float) -> None:
    for step in (64, 32, 16, 8, 4, 2, 1):
        if len(samples) <= step:
            continue
        for _ in range(100 * int(math.sqrt(float(step)))):
            smooth_raceline_step(samples, step, track_width_m, side_dist_ext, side_dist_int)
        interpolate_raceline_step(samples, step, track_width_m, side_dist_ext, side_dist_int)


def distance_to_span(station: float, start: float, end: float, total: float) -> float:
    if start <= station <= end:
        return 0.0
    return min((start - station) % total, (station - end) % total)


def turn_contexts(
    segs: list[ET.Element],
    spans: list[SegmentSpan],
    border_states: list[dict[str, dict[str, float | str]]],
    protected_idxs: set[int],
    args: argparse.Namespace,
) -> list[dict]:
    contexts: list[dict] = []
    for span, seg in zip(spans, segs, strict=True):
        qualifies, meta = qualifies_for_turn_curb(seg, args.max_radius, args.min_arc_deg)
        if not qualifies or span.index in protected_idxs:
            continue
        border = outside_border_for_turn(str(meta["type"]))
        if border_state_is_wall(border_states[span.index][border]) or direct_border_is_wall(seg, border):
            continue
        contexts.append({"start": span.start, "end": span.end, "border": border, "segment": span.name, **meta})
    return contexts


def outside_context_for_sample(sample: EdgeSample, border_name: str, contexts: list[dict], total: float, context_m: float) -> dict | None:
    best: tuple[float, dict] | None = None
    for context in contexts:
        if context["border"] != border_name:
            continue
        distance = distance_to_span(sample.station, float(context["start"]), float(context["end"]), total)
        if distance > context_m:
            continue
        item = (distance, context)
        if best is None or item[0] < best[0]:
            best = item
    return None if best is None else best[1]


def close_outside_run(run: dict, args: argparse.Namespace, total: float) -> dict | None:
    if not run["samples"]:
        return None
    half_step = max(0.25, args.raceline_step_m * 0.5)
    start = max(0.0, float(run["samples"][0]["station"]) - half_step)
    end = min(total, float(run["samples"][-1]["station"]) + half_step)
    length = end - start
    if length < args.outside_min_run_m:
        return None

    best_sample = max(run["samples"], key=lambda item: float(item["strength"]))
    trimmed = False
    if length > args.outside_max_run_m:
        center = float(best_sample["station"])
        start = max(start, center - args.outside_max_run_m * 0.5)
        end = min(end, start + args.outside_max_run_m)
        start = max(float(run["samples"][0]["station"]) - half_step, end - args.outside_max_run_m)
        start = max(0.0, start)
        end = min(total, end)
        length = end - start
        trimmed = True

    return {
        "border": run["border"],
        "start": start,
        "end": end,
        "length": length,
        "sample_count": len(run["samples"]),
        "peak_station": best_sample["station"],
        "peak_strength": best_sample["strength"],
        "matched_turn": best_sample.get("matched_turn", ""),
        "trimmed": trimmed,
    }


def merge_wrapped_outside_ranges(ranges: list[dict], total: float, merge_gap: float, max_run_m: float) -> list[dict]:
    if len(ranges) < 2 or total <= 0.0:
        return ranges
    first = ranges[0]
    last = ranges[-1]
    if first["border"] != last["border"]:
        return ranges
    gap = float(first["start"]) + max(0.0, total - float(last["end"]))
    if gap > merge_gap:
        return ranges
    length = max(0.0, total - float(last["start"])) + max(0.0, float(first["end"]))
    if length <= 0.0 or length > max_run_m:
        return ranges
    peak = max((first, last), key=lambda item: float(item.get("peak_strength", 0.0)))
    merged = {
        "border": first["border"],
        "start": last["start"],
        "end": first["end"],
        "length": length,
        "sample_count": int(first.get("sample_count", 0)) + int(last.get("sample_count", 0)),
        "peak_station": peak.get("peak_station", first.get("peak_station", 0.0)),
        "peak_strength": peak.get("peak_strength", 0.0),
        "matched_turn": peak.get("matched_turn", ""),
        "trimmed": bool(first.get("trimmed", False) or last.get("trimmed", False)),
        "wrapped": True,
    }
    return [merged, *ranges[1:-1]]


def outside_edge_contacts(
    sample: EdgeSample,
    contexts: list[dict],
    total: float,
    context_m: float,
    edge_lane: float,
) -> list[tuple[str, float, dict]]:
    contacts = []
    left_margin = sample.lane
    right_margin = 1.0 - sample.lane
    if left_margin <= edge_lane:
        context = outside_context_for_sample(sample, "Left Border", contexts, total, context_m)
        if context is not None:
            contacts.append(("Left Border", edge_lane - left_margin, context))
    if right_margin <= edge_lane:
        context = outside_context_for_sample(sample, "Right Border", contexts, total, context_m)
        if context is not None:
            contacts.append(("Right Border", edge_lane - right_margin, context))
    return contacts


def close_active_outside_run(
    active: dict | None,
    ranges: list[dict],
    args: argparse.Namespace,
    total: float,
) -> None:
    if active is None:
        return
    closed = close_outside_run(active, args, total)
    if closed is not None:
        ranges.append(closed)


def should_start_outside_run(active: dict | None, border_name: str, station: float, merge_gap: float) -> bool:
    return active is None or active["border"] != border_name or station - float(active["last_station"]) > merge_gap


def new_outside_run(border_name: str, station: float) -> dict:
    return {"border": border_name, "last_station": station, "samples": []}


def append_outside_run_sample(active: dict, sample: EdgeSample, strength: float, context: dict) -> None:
    active["last_station"] = sample.station
    active["samples"].append(
        {"station": sample.station, "strength": strength, "matched_turn": context["segment"]}
    )


def find_outside_curb_ranges(
    main_track: ET.Element,
    segs: list[ET.Element],
    border_states: list[dict[str, dict[str, float | str]]],
    protected_idxs: set[int],
    args: argparse.Namespace,
) -> tuple[list[dict], dict]:
    """Return station ranges where the approximated raceline reaches an outside edge.

    The ranges are only candidates: they are clipped to nearby qualifying turns,
    merged across short gaps, and capped to a conservative maximum run length.
    ``apply_outside_curb_ranges`` later decides which segments can safely receive
    curbs and whether they need splitting.
    """
    width = track_width(main_track)
    samples, total = sample_track_edges(segs, width, args.raceline_step_m)
    if not samples:
        return [], {"sample_count": 0, "track_length": 0.0}

    side_dist_ext = get_attnum(main_track, "raceline ext", 3.0)
    side_dist_int = get_attnum(main_track, "raceline int", 3.0)
    generate_k1999_raceline(samples, width, side_dist_ext, side_dist_int)

    spans = segment_spans(segs)
    contexts = turn_contexts(segs, spans, border_states, protected_idxs, args)
    if not contexts:
        return [], {"sample_count": len(samples), "track_length": total, "turn_context_count": 0}

    context_m = args.outside_context_m if args.outside_context_m > 0.0 else max(60.0, args.outside_max_run_m * 2.0 + args.split_boundary_tolerance_m)
    edge_lane = min(0.5, side_dist_ext / width) + max(0.0, args.raceline_edge_tolerance_m) / width
    merge_gap = max(args.outside_merge_gap_m, args.raceline_step_m * 1.5)

    ranges: list[dict] = []
    active: dict | None = None

    for sample in samples:
        contacts = outside_edge_contacts(sample, contexts, total, context_m, edge_lane)
        if not contacts:
            close_active_outside_run(active, ranges, args, total)
            active = None
            continue

        border_name, strength, context = max(contacts, key=lambda item: item[1])
        if should_start_outside_run(active, border_name, sample.station, merge_gap):
            close_active_outside_run(active, ranges, args, total)
            active = new_outside_run(border_name, sample.station)
        append_outside_run_sample(active, sample, strength, context)
    close_active_outside_run(active, ranges, args, total)
    ranges = merge_wrapped_outside_ranges(ranges, total, merge_gap, args.outside_max_run_m)

    return ranges, {
        "sample_count": len(samples),
        "track_length": total,
        "turn_context_count": len(contexts),
        "side_dist_ext": side_dist_ext,
        "side_dist_int": side_dist_int,
        "edge_lane_threshold": edge_lane,
        "outside_context_m": context_m,
    }


def segment_has_variable_radius(seg: ET.Element) -> bool:
    return find_att(seg, "attnum", "end radius") is not None or find_att(seg, "attnum", "end-radius") is not None


def initial_local_range(span: SegmentSpan, start: float, end: float) -> tuple[float, float]:
    return max(0.0, start - span.start), min(span.length, end - span.start)


def snap_local_range_start(local_start: float, args: argparse.Namespace) -> tuple[float, str]:
    if local_start <= args.split_boundary_tolerance_m or local_start < args.min_split_piece_m:
        return 0.0, "snap-start"
    return local_start, "split"


def snap_local_range_end(
    span: SegmentSpan,
    local_end: float,
    reason: str,
    args: argparse.Namespace,
) -> tuple[float, str]:
    if span.length - local_end <= args.split_boundary_tolerance_m or span.length - local_end < args.min_split_piece_m:
        return span.length, "snap-end" if reason == "split" else f"{reason}+snap-end"
    return local_end, reason


def local_range_leaves_short_piece(
    span: SegmentSpan,
    local_start: float,
    local_end: float,
    args: argparse.Namespace,
) -> bool:
    return local_end - local_start < args.min_split_piece_m and (local_start > EPSILON or span.length - local_end > EPSILON)


def whole_segment_snap_reason(span: SegmentSpan, local_start: float, local_end: float, reason: str) -> str:
    if local_start <= EPSILON and span.length - local_end <= EPSILON and reason == "split":
        return "whole-segment"
    return reason


def adjusted_local_range(span: SegmentSpan, start: float, end: float, args: argparse.Namespace) -> tuple[float, float, str] | None:
    """Map a desired track-station curb range to one segment-local range.

    The outside pass should avoid creating tiny XML fragments.  This helper first
    accepts a whole segment if the desired range covers most of it, then snaps
    starts/ends to nearby boundaries, and finally rejects ranges that would leave
    unusably short split pieces.
    """
    local_start, local_end = initial_local_range(span, start, end)
    if local_end - local_start <= EPSILON:
        return None

    original_len = local_end - local_start
    if span.length <= EPSILON:
        return None
    reason = "split"
    if original_len / span.length >= args.segment_fit_ratio:
        return 0.0, span.length, "fit-ratio"

    local_start, reason = snap_local_range_start(local_start, args)
    local_end, reason = snap_local_range_end(span, local_end, reason, args)
    if local_end - local_start <= EPSILON:
        return None
    if local_range_leaves_short_piece(span, local_start, local_end, args):
        return None
    return local_start, local_end, whole_segment_snap_reason(span, local_start, local_end, reason)


def linear_range_parts(start: float, end: float, total: float) -> list[tuple[float, float]]:
    if total <= 0.0:
        return [(start, end)] if end > start else []
    start %= total
    end %= total
    if end >= start:
        return [(start, end)]
    return [(start, total), (0.0, end)]


def choose_piece_name(existing_names: set[str], preferred: str) -> str:
    base = preferred or "segment"
    candidate = base
    suffix = 2
    while candidate in existing_names:
        candidate = f"{base}-{suffix}"
        suffix += 1
    existing_names.add(candidate)
    return candidate


def clear_geometry_attrs(seg: ET.Element, names: tuple[str, ...]) -> None:
    for name in names:
        remove_attnum(seg, name)


def linear_interp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def preserve_split_side_widths(original: ET.Element, piece: ET.Element, t0: float, t1: float) -> None:
    for side_name in ("Left Side", "Right Side"):
        original_side = child_section(original, side_name)
        piece_side = child_section(piece, side_name)
        if original_side is None or piece_side is None:
            continue
        if find_att(original_side, "attnum", "start width") is None or find_att(original_side, "attnum", "end width") is None:
            continue
        width_start = get_attnum(original_side, "start width", 0.0)
        width_end = get_attnum(original_side, "end width", width_start)
        set_attnum(piece_side, "start width", linear_interp(width_start, width_end, t0), "m")
        set_attnum(piece_side, "end width", linear_interp(width_start, width_end, t1), "m")


def straight_piece(seg: ET.Element, name: str, length: float) -> ET.Element:
    piece = copy.deepcopy(seg)
    piece.set("name", name)
    set_attstr(piece, "type", "str")
    set_attnum_precise(piece, "lg", length, "m")
    clear_geometry_attrs(piece, ("radius", "arc", "end radius", "end-radius"))
    return piece


def turn_piece(seg: ET.Element, name: str, arc_deg: float) -> ET.Element:
    piece = copy.deepcopy(seg)
    piece.set("name", name)
    set_attstr(piece, "type", get_attstr(seg, "type"))
    set_attnum_precise(piece, "arc", arc_deg, "deg", precision=11)
    clear_geometry_attrs(piece, ("lg", "end radius", "end-radius"))
    return piece


def split_segment_for_local_range(
    segs: list[ET.Element],
    idx: int,
    local_start: float,
    local_end: float,
    existing_names: set[str],
) -> tuple[int, list[dict]]:
    seg = segs[idx]
    length = max(EPSILON, segment_length(seg))
    local_start = max(0.0, min(length, local_start))
    local_end = max(local_start, min(length, local_end))
    if local_start <= EPSILON and length - local_end <= EPSILON:
        return idx, []

    base_name = seg.get("name", f"segment-{idx + 1}")
    existing_names.discard(base_name)
    seg_type = get_attstr(seg, "type")
    pieces: list[ET.Element] = []
    piece_reports: list[dict] = []
    target_idx = idx

    def append_piece(role: str, piece_len: float, is_target: bool, piece_start: float) -> None:
        nonlocal target_idx
        if piece_len <= EPSILON:
            return
        preferred = base_name if role == "curb" and not pieces else f"{base_name}-{role}"
        name = choose_piece_name(existing_names, preferred)
        if seg_type == "str":
            piece = straight_piece(seg, name, piece_len)
        else:
            piece = turn_piece(seg, name, abs(get_attnum(seg, "arc", 0.0)) * piece_len / length)
        preserve_split_side_widths(seg, piece, piece_start / length, (piece_start + piece_len) / length)
        if is_target:
            target_idx = idx + len(pieces)
        pieces.append(piece)
        piece_reports.append({"name": name, "role": role, "length": piece_len})

    append_piece("pre", local_start, False, 0.0)
    append_piece("curb", local_end - local_start, True, local_start)
    append_piece("post", length - local_end, False, local_end)
    segs[idx : idx + 1] = pieces
    return target_idx, piece_reports


def matching_outside_local_range(
    span: SegmentSpan,
    parts: list[tuple[float, float]],
    args: argparse.Namespace,
) -> tuple[bool, tuple[float, float, str] | None]:
    for part_start, part_end in parts:
        if span.end <= part_start + EPSILON or span.start >= part_end - EPSILON:
            continue
        return True, adjusted_local_range(span, part_start, part_end, args)
    return False, None


def outside_skip_reason(
    seg: ET.Element,
    span: SegmentSpan,
    border_name: str,
    border_states: list[dict[str, dict[str, float | str]]],
    protected_idxs: set[int],
    local: tuple[float, float, str] | None,
) -> str:
    if span.index in protected_idxs:
        return "protected"
    if direct_border_is_wall(seg, border_name) or border_state_is_wall(border_states[span.index][border_name]):
        return "wall"
    if segment_has_variable_radius(seg):
        return "variable-radius"
    if get_attstr(seg, "type") not in ("str", "lft", "rgt"):
        return "unsupported-segment"
    if local is None:
        return "too-short-after-snap"
    return ""


def outside_curb_item(curb_range: dict, span: SegmentSpan, border_name: str) -> dict:
    return {"range": curb_range, "segment": span.name, "index": span.index, "border": border_name}


def outside_adjustment_for_span(
    seg: ET.Element,
    span: SegmentSpan,
    curb_range: dict,
    border_name: str,
    parts: list[tuple[float, float]],
    border_states: list[dict[str, dict[str, float | str]]],
    protected_idxs: set[int],
    args: argparse.Namespace,
) -> tuple[dict | None, dict | None]:
    matched, local = matching_outside_local_range(span, parts, args)
    if not matched:
        return None, None
    item = outside_curb_item(curb_range, span, border_name)
    skip_reason = outside_skip_reason(seg, span, border_name, border_states, protected_idxs, local)
    if skip_reason:
        return None, {**item, "reason": skip_reason}
    local_start, local_end, snap_reason = local
    return {
        **item,
        "local_start": local_start,
        "local_end": local_end,
        "snap": snap_reason,
        "length": local_end - local_start,
    }, None


def outside_adjustments_for_range(
    segs: list[ET.Element],
    spans: list[SegmentSpan],
    curb_range: dict,
    border_name: str,
    parts: list[tuple[float, float]],
    border_states: list[dict[str, dict[str, float | str]]],
    protected_idxs: set[int],
    args: argparse.Namespace,
) -> tuple[list[dict], list[dict]]:
    adjusted: list[dict] = []
    skipped: list[dict] = []
    for span in spans:
        adjustment, skip = outside_adjustment_for_span(
            segs[span.index],
            span,
            curb_range,
            border_name,
            parts,
            border_states,
            protected_idxs,
            args,
        )
        if adjustment is not None:
            adjusted.append(adjustment)
        if skip is not None:
            skipped.append(skip)
    return adjusted, skipped


def outside_adjusted_length(adjusted: list[dict]) -> float:
    return sum(float(item["length"]) for item in adjusted)


def place_outside_adjustment(
    segs: list[ET.Element],
    item: dict,
    border_name: str,
    args: argparse.Namespace,
    existing_names: set[str],
) -> tuple[dict, dict | None]:
    target_idx, pieces = split_segment_for_local_range(
        segs,
        int(item["index"]),
        float(item["local_start"]),
        float(item["local_end"]),
        existing_names,
    )
    set_curb_border(segs[target_idx], border_name, args.border_width, args.border_height)
    target_name = segs[target_idx].get("name", f"#{target_idx + 1}")
    split = None
    if pieces:
        split = {
            "source_segment": item["segment"],
            "target_segment": target_name,
            "pieces": pieces,
            "border": border_name,
        }
    placed = {
        "index": target_idx,
        "segment": target_name,
        "source_segment": item["segment"],
        "border": border_name,
        "surface": curb_surface(border_name),
        "placement": "outside",
        "start": item["range"]["start"],
        "end": item["range"]["end"],
        "snap": item["snap"],
    }
    return placed, split


def place_outside_adjustments(
    segs: list[ET.Element],
    adjusted: list[dict],
    border_name: str,
    args: argparse.Namespace,
    existing_names: set[str],
) -> tuple[list[dict], list[dict]]:
    placed: list[dict] = []
    splits: list[dict] = []
    for item in sorted(adjusted, key=lambda value: int(value["index"]), reverse=True):
        placed_item, split = place_outside_adjustment(segs, item, border_name, args, existing_names)
        placed.append(placed_item)
        if split is not None:
            splits.append(split)
    return placed, splits


def refresh_placed_indices(segs: list[ET.Element], placed: list[dict]) -> None:
    name_to_idx = {seg.get("name", ""): idx for idx, seg in enumerate(segs)}
    for item in placed:
        item["index"] = name_to_idx.get(str(item["segment"]), item["index"])


def apply_outside_curb_ranges(
    main_track: ET.Element,
    segs: list[ET.Element],
    ranges: list[dict],
    args: argparse.Namespace,
) -> tuple[list[ET.Element], list[dict], list[dict], list[dict]]:
    """Write outside curbs for candidate ranges and split geometry only if safe.

    Protected pit corridors, walls, variable-radius turns, and unsupported segment
    types are reported as skips.  Splitting is limited to straights and
    constant-radius turns so TORCS geometry semantics remain simple and closure
    drift can be repaired by a later geometric close.
    """
    placed: list[dict] = []
    skipped: list[dict] = []
    splits: list[dict] = []
    existing_names = {seg.get("name", "") for seg in segs if seg.get("name")}

    for curb_range in ranges:
        border_name = str(curb_range["border"])
        spans = segment_spans(segs)
        total = spans[-1].end if spans else 0.0
        parts = linear_range_parts(float(curb_range["start"]), float(curb_range["end"]), total)
        border_states = effective_border_states(main_track, segs)
        protected_idxs = pit_protected_indices(main_track, segs, border_states)
        adjusted, range_skips = outside_adjustments_for_range(
            segs,
            spans,
            curb_range,
            border_name,
            parts,
            border_states,
            protected_idxs,
            args,
        )
        skipped.extend(range_skips)

        if outside_adjusted_length(adjusted) < args.outside_min_run_m:
            skipped.append({"range": curb_range, "reason": "below-min-run-after-protection"})
            continue

        range_placed, range_splits = place_outside_adjustments(segs, adjusted, border_name, args, existing_names)
        placed.extend(range_placed)
        splits.extend(range_splits)
    refresh_placed_indices(segs, placed)
    return segs, sorted(placed, key=lambda item: int(item["index"])), skipped, splits


def replace_track_segments(main_track: ET.Element, segs: list[ET.Element]) -> None:
    track_segments = child_section(main_track, "Track Segments")
    if track_segments is None:
        raise SystemExit("Track XML has no Main Track/Track Segments section")
    for child in list(track_segments):
        if child.tag == "section":
            track_segments.remove(child)
    for seg in segs:
        track_segments.append(seg)


def main() -> int:
    args = parse_args()
    input_xml = pathlib.Path(args.input)
    output_xml = pathlib.Path(args.output) if args.output else input_xml
    prolog, tree = parse_xml_preserve_prolog(input_xml)
    main_track, segs = segment_sections(tree.getroot())
    normalize_main_borders(main_track, args.border_width, args.flat_border_surface)

    border_states = effective_border_states(main_track, segs)
    protected_idxs = pit_protected_indices(main_track, segs, border_states)
    inside_placed: list[dict] = []
    inside_skipped: list[dict] = []
    if args.placement in ("inside", "both"):
        inside_placed, inside_skipped = place_inside_curbs(segs, protected_idxs, args)

    outside_ranges: list[dict] = []
    outside_raceline: dict = {}
    outside_placed: list[dict] = []
    outside_skipped: list[dict] = []
    outside_splits: list[dict] = []
    if args.placement in ("outside", "both"):
        border_states = effective_border_states(main_track, segs)
        protected_idxs = pit_protected_indices(main_track, segs, border_states)
        outside_ranges, outside_raceline = find_outside_curb_ranges(main_track, segs, border_states, protected_idxs, args)
        segs, outside_placed, outside_skipped, outside_splits = apply_outside_curb_ranges(main_track, segs, outside_ranges, args)
        replace_track_segments(main_track, segs)

    final_border_states = effective_border_states(main_track, segs)
    final_protected_idxs = pit_protected_indices(main_track, segs, final_border_states)
    resets = add_carry_over_resets(
        segs,
        placed_curb_indices_by_border(segs),
        final_border_states,
        final_protected_idxs,
        args.border_width,
        args.flat_border_surface,
    )

    placed = sorted(inside_placed + outside_placed, key=lambda item: (str(item.get("placement", "")), int(item.get("index", 0))))
    report = {
        "input": str(input_xml),
        "output": str(output_xml),
        "dry_run": bool(args.dry_run),
        "placement": args.placement,
        "max_radius": args.max_radius,
        "min_arc_deg": args.min_arc_deg,
        "border_width": args.border_width,
        "border_height": args.border_height,
        "flat_border_surface": args.flat_border_surface,
        "outside_max_run_m": args.outside_max_run_m,
        "outside_min_run_m": args.outside_min_run_m,
        "outside_merge_gap_m": args.outside_merge_gap_m,
        "split_boundary_tolerance_m": args.split_boundary_tolerance_m,
        "segment_fit_ratio": args.segment_fit_ratio,
        "min_split_piece_m": args.min_split_piece_m,
        "protected_segments": [segs[idx].get("name", f"#{idx + 1}") for idx in sorted(final_protected_idxs)],
        "placed_count": len(placed),
        "placed_curbs": placed,
        "inside_placed_count": len(inside_placed),
        "placed_inside_curbs": inside_placed,
        "outside_placed_count": len(outside_placed),
        "placed_outside_curbs": outside_placed,
        "outside_candidate_count": len(outside_ranges),
        "outside_ranges": outside_ranges,
        "outside_raceline": outside_raceline,
        "outside_splits": outside_splits,
        "outside_skipped": outside_skipped,
        "reset_count": len(resets),
        "curb_resets": resets,
        "skipped_protected": inside_skipped,
    }

    if args.report:
        report_path = pathlib.Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not args.dry_run:
        output_xml.parent.mkdir(parents=True, exist_ok=True)
        output_xml.write_text(serialize_xml_restore_entity(prolog, tree), encoding="utf-8")

    print(f"Placed {len(inside_placed)} inside curbs and {len(outside_placed)} outside curbs in {input_xml}")
    if args.dry_run:
        print("Dry run: XML not written")
    else:
        print(f"Wrote XML: {output_xml}")
    if args.report:
        print(f"Wrote report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
