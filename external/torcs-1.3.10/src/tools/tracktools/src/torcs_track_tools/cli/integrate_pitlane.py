#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : integrate_pitlane.py
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

"""Integrate TORCS side pits into an already accepted track layout.

Design goals:
- enforce a 300 m pit main section split into two 150 m segments
- place start line at end of pit 10 by rotating track start to pit_main_b
- prefer existing straights, allow manual connector straightening, then
  "almost-straight" chains, then lengthen/inject
- allow entry/exit taper across multiple segments (including curved segments)
- normalize pit materials/surfaces to the manual track example defaults

Two placement modes share the same XML mutation code.  Real-placement mode
projects a separately fetched pitlane source onto the accepted racing-layout
source, determines side consistency, and finds a low-curvature host window.
Manual mode skips OSM geometry and uses a named host segment/chain from XML.

The tool can stage XML without immediate safety gates because pit insertion
usually shifts closure; the intended safe workflow is: preserve a no-pit backup,
integrate with ``--stage-for-closure``, close with ``torcs-close-loop --profile
post-pit``, then accept only if ``trackgen -z`` reports the expected pit count
(normally 20) and strict closure.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import pathlib
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np

from torcs_track_tools.core.defaults import (
    ENTITY_PLACEHOLDER,
    NORMAL_BORDER_STYLE,
    NORMAL_BORDER_SURFACE,
    NORMAL_BORDER_WIDTH,
    PIT_TRANSITION_BORDER_SURFACE,
)
from torcs_track_tools.core.polyline import to_xy_tuples
from torcs_track_tools.core.trackgen import run_trackgen_z as run_trackgen_z_shared
from torcs_track_tools.core.trackgen import trackgen_xml_lock

AUTO_PIT_SEGMENT_PREFIXES = (
    "pit_main_a",
    "pit_main_b",
    "pit_host_pre",
    "pit_host_post",
    "pit_host_mid",
    "pit_host_turn",
    "pit_injected_host",
    "pit_counter_straight",
)


def cli_arg_present(name: str) -> bool:
    return any(arg == name or arg.startswith(name + "=") for arg in sys.argv[1:])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Integrate TORCS pit lane with robust host-straight synthesis")
    parser.add_argument("--track-xml", required=True, help="Path to track XML")
    parser.add_argument("--pit-side", default="right", choices=["left", "right"], help="Pit side")
    parser.add_argument("--pit-main-length", type=float, default=300.0, help="Pit main total length (m)")
    parser.add_argument(
        "--pit-main-align",
        choices=["center", "start", "end"],
        default="center",
        help="Place spare host length before/after the pit main; default centers the pit main in the host",
    )
    parser.add_argument("--pit-slot-length", type=float, default=15.0, help="Pit slot length (m)")
    parser.add_argument("--pit-side-width", type=float, default=14.5, help=argparse.SUPPRESS)
    parser.add_argument("--entry-exit-side-width", type=float, default=14.0, help=argparse.SUPPRESS)
    parser.add_argument("--entry-taper-length", type=float, default=120.0, help=argparse.SUPPRESS)
    parser.add_argument("--exit-taper-length", type=float, default=120.0, help=argparse.SUPPRESS)
    parser.add_argument("--almost-max-curvature", type=float, default=0.0025, help=argparse.SUPPRESS)
    parser.add_argument("--almost-max-seg-turn-deg", type=float, default=2.0, help=argparse.SUPPRESS)
    parser.add_argument("--almost-max-chain-turn-deg", type=float, default=4.0, help=argparse.SUPPRESS)
    parser.add_argument(
        "--host-mode",
        default="auto",
        choices=["auto", "exact", "almost", "straighten", "lengthen", "inject"],
        help=(
            "Pit host selection mode. Use 'auto' normally. Use 'straighten' with "
            "--host-start-segment/--host-end-segment to replace a slightly curved "
            "manual host chain with a straight pit host and refit adjacent connectors."
        ),
    )
    parser.add_argument("--preserve-host-pose", dest="preserve_host_pose", action="store_true", default=True, help=argparse.SUPPRESS)
    parser.add_argument("--max-host-window-segs", type=int, default=8, help=argparse.SUPPRESS)
    parser.add_argument("--max-host-window-len-m", type=float, default=450.0, help=argparse.SUPPRESS)
    parser.add_argument("--min-piece-len", type=float, default=8.0, help=argparse.SUPPRESS)
    parser.add_argument("--speed-limit", type=float, default=80.0, help="Pit speed limit (km/h)")
    parser.add_argument("--runtime-dir", default="", help="TORCS runtime directory (auto-detect from track path if omitted)")
    parser.add_argument("--category", default="", help="Track category for trackgen safety checks")
    parser.add_argument("--name", default="", help="Track short name for trackgen safety checks")
    parser.add_argument("--pit-source", default="", help="Optional real pitlane source JSON for placement feasibility reporting")
    parser.add_argument("--mainline-source", default="", help="Optional mainline source JSON in the same coordinate frame as --pit-source")
    parser.add_argument("--host-segment", default="", help="Manual pit host segment name")
    parser.add_argument("--host-start-segment", default="", help="Manual pit host chain first segment name")
    parser.add_argument("--host-end-segment", default="", help="Manual pit host chain last segment name")
    parser.add_argument("--real-placement-report-only", action="store_true", help="Only report real pitlane placement feasibility; do not edit XML")
    parser.add_argument("--real-placement-overlay", default="", help="Optional SVG overlay for real pitlane placement feasibility")
    parser.add_argument("--real-max-chain-turn-deg", type=float, default=4.0, help=argparse.SUPPRESS)
    parser.add_argument("--real-min-side-consistency", type=float, default=0.8, help=argparse.SUPPRESS)
    parser.add_argument("--overlay-polyline", default="", help=argparse.SUPPRESS)
    parser.add_argument("--overlay-script", default="", help=argparse.SUPPRESS)
    parser.add_argument("--stage-for-closure", action="store_true", help="Integrate XML now and skip immediate safety gates; close with torcs-close-loop afterward")
    parser.add_argument("--enforce-safety", dest="enforce_safety", action="store_true", default=True, help=argparse.SUPPRESS)
    parser.add_argument("--no-enforce-safety", dest="enforce_safety", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("--no-rollback-on-fail", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--max-delta-ang-deg-increase", type=float, default=0.01, help=argparse.SUPPRESS)
    parser.add_argument("--max-delta-x-increase-m", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--max-delta-y-increase-m", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--max-final-delta-x-m", type=float, default=0.001, help=argparse.SUPPRESS)
    parser.add_argument("--max-final-delta-y-m", type=float, default=0.001, help=argparse.SUPPRESS)
    parser.add_argument("--max-final-delta-ang-deg", type=float, default=0.0001, help=argparse.SUPPRESS)
    parser.add_argument("--max-length-drift-ratio", type=float, default=0.005, help=argparse.SUPPRESS)
    parser.add_argument("--max-rmse-increase-m", type=float, default=0.5, help=argparse.SUPPRESS)
    parser.add_argument("--max-mean-dev-increase-m", type=float, default=0.5, help=argparse.SUPPRESS)
    parser.add_argument("--max-almost-pose-error-m", type=float, default=0.002, help=argparse.SUPPRESS)
    parser.add_argument("--max-almost-pose-error-deg", type=float, default=0.0001, help=argparse.SUPPRESS)
    parser.add_argument("--baseline-report", default="", help=argparse.SUPPRESS)
    parser.add_argument("--safety-report", default="", help=argparse.SUPPRESS)
    parser.add_argument("--no-pit-backup", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help="Do not write XML")
    parser.add_argument("--report", default="", help="Optional JSON report path")
    args = parser.parse_args()
    args.entry_taper_length_explicit = cli_arg_present("--entry-taper-length")
    args.exit_taper_length_explicit = cli_arg_present("--exit-taper-length")
    if args.stage_for_closure:
        args.enforce_safety = False
    return args


def _find_att(section: ET.Element, tag: str, name: str) -> ET.Element | None:
    for child in section:
        if child.tag == tag and child.get("name") == name:
            return child
    return None


def get_attstr(section: ET.Element, name: str, default: str = "") -> str:
    att = _find_att(section, "attstr", name)
    return att.get("val", default) if att is not None else default


def get_attnum(section: ET.Element, name: str, default: float = 0.0) -> float:
    att = _find_att(section, "attnum", name)
    if att is None:
        return default
    try:
        return float(att.get("val", str(default)))
    except ValueError:
        return default


def set_attstr(section: ET.Element, name: str, value: str) -> None:
    att = _find_att(section, "attstr", name)
    if att is None:
        att = ET.SubElement(section, "attstr")
        att.set("name", name)
    att.set("val", value)


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


def get_or_make_child_section(parent: ET.Element, name: str) -> ET.Element:
    child = get_child_section(parent, name)
    if child is not None:
        return child
    return ET.SubElement(parent, "section", {"name": name})


def segment_length(seg: ET.Element) -> float:
    seg_type = get_attstr(seg, "type")
    if seg_type == "str":
        return max(0.0, get_attnum(seg, "lg", 0.0))
    if seg_type in ("lft", "rgt"):
        radius = max(1e-6, abs(get_attnum(seg, "radius", 0.0)))
        arc_deg = abs(get_attnum(seg, "arc", 0.0))
        return radius * math.radians(arc_deg)
    return 0.0


def segment_heading_delta_deg(seg: ET.Element) -> float:
    seg_type = get_attstr(seg, "type")
    arc = get_attnum(seg, "arc", 0.0)
    if seg_type == "lft":
        return arc
    if seg_type == "rgt":
        return -arc
    return 0.0


def segment_curvature(seg: ET.Element) -> float:
    seg_type = get_attstr(seg, "type")
    if seg_type not in ("lft", "rgt"):
        return 0.0
    radius = abs(get_attnum(seg, "radius", 0.0))
    if radius <= 1e-9:
        return 1e9
    return 1.0 / radius


def clone_as_straight(template: ET.Element, new_name: str, lg: float) -> ET.Element:
    seg = copy.deepcopy(template)
    seg.set("name", new_name)
    set_attstr(seg, "type", "str")
    set_attnum(seg, "lg", lg, "m")
    for child in list(seg):
        if child.tag == "attnum" and child.get("name") in ("radius", "arc", "end radius", "end-radius"):
            seg.remove(child)
    return seg


def clone_as_turn(template: ET.Element, new_name: str, seg_type: str, radius: float, arc_deg: float) -> ET.Element:
    seg = copy.deepcopy(template)
    seg.set("name", new_name)
    set_attstr(seg, "type", seg_type)
    set_attnum(seg, "radius", radius, "m")
    set_attnum(seg, "arc", arc_deg, "deg")
    for child in list(seg):
        if child.tag == "attnum" and child.get("name") in ("lg",):
            seg.remove(child)
    return seg


def simulate_model_segments(model_segs: list[dict]) -> tuple[float, float, float]:
    x = 0.0
    y = 0.0
    h = 0.0
    for s in model_segs:
        t = s.get("type", "")
        if t == "str":
            lg = float(s.get("lg", 0.0))
            x += lg * math.cos(h)
            y += lg * math.sin(h)
            continue
        if t in ("lft", "rgt"):
            radius = max(1e-6, abs(float(s.get("radius", 0.0))))
            arc = float(s.get("arc", 0.0))
            a = math.radians(arc)
            sign = 1.0 if t == "lft" else -1.0
            cx = x - sign * radius * math.sin(h)
            cy = y + sign * radius * math.cos(h)
            h = h + sign * a
            x = cx + sign * radius * math.sin(h)
            y = cy - sign * radius * math.cos(h)
    return x, y, h


def chain_pose(chain: list[ET.Element]) -> tuple[float, float, float, float, float]:
    model = []
    total_len = 0.0
    total_turn = 0.0
    for seg in chain:
        t = get_attstr(seg, "type")
        if t == "str":
            lg = segment_length(seg)
            total_len += lg
            model.append({"type": "str", "lg": lg})
            continue
        if t in ("lft", "rgt"):
            r = max(1e-6, abs(get_attnum(seg, "radius", 0.0)))
            a = abs(get_attnum(seg, "arc", 0.0))
            total_len += r * math.radians(a)
            sgn = 1.0 if t == "lft" else -1.0
            total_turn += sgn * a
            model.append({"type": t, "radius": r, "arc": a})
    dx, dy, dpsi = simulate_model_segments(model)
    return dx, dy, math.degrees(dpsi), total_len, total_turn


def to_xy_points(points: list[dict], ref: dict | None = None) -> list[tuple[float, float]]:
    return to_xy_tuples(points, ref)


def read_source_polyline(path: pathlib.Path) -> list[tuple[float, float]]:
    points = read_source_points(path)
    xy = to_xy_points(points)
    if len(xy) < 2:
        raise RuntimeError(f"Source polyline is too short: {path}")
    return xy


def read_source_points(path: pathlib.Path) -> list[dict]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    points = obj.get("polyline") if isinstance(obj, dict) else obj
    if not isinstance(points, list):
        raise RuntimeError(f"Source has no polyline: {path}")
    if len(points) < 2:
        raise RuntimeError(f"Source polyline is too short: {path}")
    return points


def append_sample(samples: list[dict], x: float, y: float, h: float, station: float, seg_index: int, seg_name: str) -> None:
    if samples and math.hypot(samples[-1]["x"] - x, samples[-1]["y"] - y) < 1e-9:
        return
    samples.append({"x": x, "y": y, "h": h, "station": station, "seg_index": seg_index, "seg_name": seg_name})


def sample_track_centerline(segs: list[ET.Element], step_m: float = 5.0) -> tuple[list[dict], float]:
    samples: list[dict] = []
    x = 0.0
    y = 0.0
    h = 0.0
    station = 0.0
    append_sample(samples, x, y, h, station, 0, segs[0].get("name", "") if segs else "")
    for i, seg in enumerate(segs):
        seg_name = seg.get("name", "")
        seg_type = get_attstr(seg, "type")
        if seg_type == "str":
            lg = segment_length(seg)
            n = max(1, int(math.ceil(lg / max(1.0, step_m))))
            for k in range(1, n + 1):
                ds = lg * k / n
                append_sample(samples, x + ds * math.cos(h), y + ds * math.sin(h), h, station + ds, i, seg_name)
            x += lg * math.cos(h)
            y += lg * math.sin(h)
            station += lg
            continue
        if seg_type in ("lft", "rgt"):
            radius = max(1e-6, abs(get_attnum(seg, "radius", 0.0)))
            arc = math.radians(abs(get_attnum(seg, "arc", 0.0)))
            sign = 1.0 if seg_type == "lft" else -1.0
            cx = x - sign * radius * math.sin(h)
            cy = y + sign * radius * math.cos(h)
            seg_len = radius * arc
            n = max(2, int(math.ceil(seg_len / max(1.0, step_m))))
            h0 = h
            for k in range(1, n + 1):
                a = arc * k / n
                hk = h0 + sign * a
                xk = cx + sign * radius * math.sin(hk)
                yk = cy - sign * radius * math.cos(hk)
                append_sample(samples, xk, yk, hk, station + seg_len * k / n, i, seg_name)
            h = h0 + sign * arc
            x = cx + sign * radius * math.sin(h)
            y = cy - sign * radius * math.cos(h)
            station += seg_len
    return samples, station


def sample_polyline_centerline(xy: list[tuple[float, float]], closed: bool = False) -> tuple[list[dict], float]:
    samples: list[dict] = []
    station = 0.0
    for i, point in enumerate(xy):
        if i < len(xy) - 1:
            h = math.atan2(xy[i + 1][1] - point[1], xy[i + 1][0] - point[0])
        elif i > 0:
            h = math.atan2(point[1] - xy[i - 1][1], point[0] - xy[i - 1][0])
        else:
            h = 0.0
        if i > 0:
            station += math.hypot(point[0] - xy[i - 1][0], point[1] - xy[i - 1][1])
        append_sample(samples, point[0], point[1], h, station, i, f"source-{i}")
    if closed and len(xy) > 2:
        close_len = math.hypot(xy[0][0] - xy[-1][0], xy[0][1] - xy[-1][1])
        if close_len > 1e-9:
            station += close_len
            h = math.atan2(xy[0][1] - xy[-1][1], xy[0][0] - xy[-1][0])
            append_sample(samples, xy[0][0], xy[0][1], h, station, 0, "source-0")
    return samples, station


def source_span_turn_deg(samples: list[dict], start: float, end: float, total: float) -> float:
    headings = [float(sample["h"]) for sample in samples if station_in_span(float(sample["station"]), start, end, total)]
    if len(headings) < 2:
        return 0.0
    turn = 0.0
    for i in range(1, len(headings)):
        turn += abs(math.degrees((headings[i] - headings[i - 1] + math.pi) % (2.0 * math.pi) - math.pi))
    return turn


def empty_source_window(start: float, end: float) -> dict:
    return {"turn_deg": 0.0, "start_station_m": start, "end_station_m": end, "length_m": 0.0}


def source_window_samples(samples: list[dict], start: float, end: float, total: float) -> list[dict]:
    span_samples = []
    for sample in samples:
        station = float(sample["station"])
        if station_in_span(station, start, end, total):
            span_samples.append({"rel": span_length(start, station, total), "h": float(sample["h"]), "station": station})
    span_samples.sort(key=lambda item: item["rel"])
    return span_samples


def source_heading_turn_between(span_samples: list[dict], i: int, j: int) -> float:
    turn = 0.0
    for k in range(i + 1, j + 1):
        turn += abs(math.degrees((span_samples[k]["h"] - span_samples[k - 1]["h"] + math.pi) % (2.0 * math.pi) - math.pi))
    return turn


def first_source_window_candidate(span_samples: list[dict], i: int, window_len: float) -> tuple[float, float, float, float] | None:
    for j in range(i + 1, len(span_samples)):
        length = span_samples[j]["rel"] - span_samples[i]["rel"]
        if length < window_len:
            continue
        turn = source_heading_turn_between(span_samples, i, j)
        return turn, length, span_samples[i]["station"], span_samples[j]["station"]
    return None


def best_source_window_turn_deg(samples: list[dict], start: float, end: float, total: float, window_len: float) -> dict:
    span_samples = source_window_samples(samples, start, end, total)
    if len(span_samples) < 2:
        return empty_source_window(start, end)
    best = None
    for i in range(len(span_samples)):
        cand = first_source_window_candidate(span_samples, i, window_len)
        if cand is not None and (best is None or cand < best):
            best = cand
    if best is None:
        return empty_source_window(start, end)
    return {"turn_deg": best[0], "length_m": best[1], "start_station_m": best[2], "end_station_m": best[3]}


def samples_to_xy(samples: list[dict]) -> list[tuple[float, float]]:
    return [(float(sample["x"]), float(sample["y"])) for sample in samples]


def station_window_xy(samples: list[dict], start: float, end: float, total: float) -> list[tuple[float, float]]:
    return [
        (float(sample["x"]), float(sample["y"]))
        for sample in samples
        if station_in_span(float(sample["station"]), start, end, total)
    ]


def write_real_placement_overlay(
    path: pathlib.Path,
    mainline_xy: list[tuple[float, float]],
    pit_xy: list[tuple[float, float]],
    result: dict,
) -> None:
    best_window = result.get("best_window") or {}
    samples, total = sample_polyline_centerline(mainline_xy, closed=True)
    window_start = float(best_window.get("start_station_m", result.get("host_start_station_m", 0.0)))
    window_end = float(best_window.get("end_station_m", result.get("host_end_station_m", 0.0)))
    window_xy = station_window_xy(samples, window_start, window_end, total)
    all_points = mainline_xy + pit_xy + window_xy
    if not all_points:
        return
    minx = min(p[0] for p in all_points)
    maxx = max(p[0] for p in all_points)
    miny = min(p[1] for p in all_points)
    maxy = max(p[1] for p in all_points)
    pad = 30.0
    width = max(1.0, maxx - minx)
    height = max(1.0, maxy - miny)
    view_w = width + 2.0 * pad
    view_h = height + 2.0 * pad

    def project(point: tuple[float, float]) -> tuple[float, float]:
        return point[0] - minx + pad, view_h - (point[1] - miny + pad)

    def poly(points: list[tuple[float, float]]) -> str:
        return " ".join(f"{x:.2f},{y:.2f}" for x, y in (project(point) for point in points))

    status = str(result.get("status", "unknown"))
    color = "#22c55e" if status == "real-placement-ok" else "#ef4444"
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="1000" viewBox="0 0 {view_w:.2f} {view_h:.2f}">',
        '<rect width="100%" height="100%" fill="#111827"/>',
        f'<polyline fill="none" stroke="#94a3b8" stroke-width="3" points="{poly(mainline_xy)}"/>',
        f'<polyline fill="none" stroke="#38bdf8" stroke-width="4" points="{poly(pit_xy)}"/>',
    ]
    if len(window_xy) >= 2:
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="7" stroke-linecap="round" points="{poly(window_xy)}"/>')
    for key, fill in (("entry_projection", "#facc15"), ("exit_projection", "#fb923c")):
        projection = result.get(key, {})
        station = float(projection.get("station_m", 0.0))
        pts = station_window_xy(samples, station, station + 1e-6, total)
        if pts:
            x, y = project(pts[0])
            lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="8" fill="{fill}"/>')
    lines.extend(
        [
            f'<text x="20" y="32" fill="#e5e7eb" font-family="monospace" font-size="18">{status}</text>',
            f'<text x="20" y="58" fill="#e5e7eb" font-family="monospace" font-size="15">span {float(result.get("projected_span_m", 0.0)):.1f} m, best turn {float(result.get("mainline_turn_deg", 0.0)):.2f} deg</text>',
            '<text x="20" y="84" fill="#94a3b8" font-family="monospace" font-size="14">gray=mainline source, blue=pit source, green/red=best pit-main window</text>',
            "</svg>",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def projection_edge_count(samples: list[dict], closed: bool) -> int:
    edge_count = max(0, len(samples) - 1)
    if closed and len(samples) > 2 and math.hypot(float(samples[0]["x"]) - float(samples[-1]["x"]), float(samples[0]["y"]) - float(samples[-1]["y"])) > 1e-9:
        edge_count += 1
    return edge_count


def projection_side_sign(cross: float) -> int:
    return 1 if cross > 0.0 else -1 if cross < 0.0 else 0


def projection_candidate(point: tuple[float, float], samples: list[dict], i: int, closed: bool, total_length: float) -> dict:
    px, py = point
    a = samples[i]
    b = samples[(i + 1) % len(samples)]
    ax = float(a["x"])
    ay = float(a["y"])
    bx = float(b["x"])
    by = float(b["y"])
    vx = bx - ax
    vy = by - ay
    denom = vx * vx + vy * vy
    t = 0.0 if denom <= 1e-12 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / denom))
    qx = ax + t * vx
    qy = ay + t * vy
    station_a = float(a["station"])
    station_b = float(b["station"])
    effective_total_length = total_length
    if (i + 1) >= len(samples):
        if effective_total_length <= 0.0:
            effective_total_length = station_a + math.hypot(bx - ax, by - ay)
        station_b += effective_total_length
    station = station_a + t * (station_b - station_a)
    if closed and effective_total_length > 0.0:
        station %= effective_total_length
    cross = vx * (py - ay) - vy * (px - ax)
    return {
        "distance_m": math.hypot(px - qx, py - qy),
        "station_m": station,
        "side_sign": projection_side_sign(cross),
        "seg_index": int(a["seg_index"]),
        "seg_name": str(a["seg_name"]),
    }


def project_point_to_samples(point: tuple[float, float], samples: list[dict], closed: bool = False, total_length: float = 0.0) -> dict:
    best = None
    edge_count = projection_edge_count(samples, closed)
    for i in range(edge_count):
        cand = projection_candidate(point, samples, i, closed, total_length)
        if best is None or cand["distance_m"] < best["distance_m"]:
            best = cand
    if best is None:
        raise RuntimeError("Cannot project to empty mainline samples")
    return best


def station_in_span(station: float, start: float, end: float, total: float) -> bool:
    if total <= 0.0:
        return False
    if end >= start:
        return start <= station <= end
    return station >= start or station <= end


def span_length(start: float, end: float, total: float) -> float:
    if end >= start:
        return end - start
    return total - start + end


def shortest_signed_station_delta(start: float, end: float, total: float) -> float:
    if total <= 0.0:
        return end - start
    forward = (end - start) % total
    backward = (start - end) % total
    if forward <= backward:
        return forward
    return -backward


def real_projection_direction(projections: list[dict], total_length: float) -> tuple[str, float, float, float]:
    direction_score = sum(
        shortest_signed_station_delta(
            float(projections[i - 1]["station_m"]),
            float(projections[i]["station_m"]),
            total_length,
        )
        for i in range(1, len(projections))
    )
    entry = projections[0]
    exit_ = projections[-1]
    if direction_score < 0.0:
        host_start = exit_["station_m"]
        host_end = entry["station_m"]
        return "reversed", host_start, host_end, span_length(host_start, host_end, total_length)
    host_start = entry["station_m"]
    host_end = exit_["station_m"]
    return "forward", host_start, host_end, span_length(host_start, host_end, total_length)


def projection_side_counts(projections: list[dict]) -> dict:
    side_counts = {"left": 0, "right": 0, "center": 0}
    for projection in projections:
        if projection["side_sign"] > 0:
            side_counts["left"] += 1
        elif projection["side_sign"] < 0:
            side_counts["right"] += 1
        else:
            side_counts["center"] += 1
    return side_counts


def track_xml_span_turn_details(segs: list[ET.Element], host_start: float, host_end: float, total_length: float) -> tuple[float, list[str]]:
    seg_lengths = [segment_length(seg) for seg in segs]
    seg_starts = segment_start_stations(seg_lengths)
    turn_deg = 0.0
    host_names: list[str] = []
    for idx, seg in enumerate(segs):
        mid = seg_starts[idx] + seg_lengths[idx] * 0.5
        if station_in_span(mid, host_start, host_end, total_length):
            turn_deg += abs(segment_heading_delta_deg(seg))
            name = seg.get("name", "")
            if name:
                host_names.append(name)
    return turn_deg, host_names


def real_placement_turn_details(
    segs: list[ET.Element],
    samples: list[dict],
    host_start: float,
    host_end: float,
    total_length: float,
    pit_main_length: float,
    using_source_frame: bool,
) -> tuple[float, float, dict | None, list[str]]:
    if using_source_frame:
        full_span_turn_deg = source_span_turn_deg(samples, host_start, host_end, total_length)
        best_window = best_source_window_turn_deg(samples, host_start, host_end, total_length, pit_main_length)
        return float(best_window["turn_deg"]), full_span_turn_deg, best_window, []

    turn_deg, host_names = track_xml_span_turn_details(segs, host_start, host_end, total_length)
    return turn_deg, turn_deg, None, host_names


def real_placement_status(checks: dict) -> str:
    if checks["span_long_enough"] and checks["curvature_ok"] and checks["side_consistent"]:
        return "real-placement-ok"
    if not checks["span_long_enough"]:
        return "real-placement-rejected-too-short"
    if not checks["curvature_ok"]:
        return "real-placement-rejected-curvature"
    return "real-placement-rejected-side-inconsistent"


def real_placement_feasibility(
    segs: list[ET.Element],
    pit_xy: list[tuple[float, float]],
    pit_main_length: float,
    max_chain_turn_deg: float,
    min_side_consistency: float,
    mainline_xy: list[tuple[float, float]] | None = None,
) -> dict:
    using_source_frame = mainline_xy is not None
    if mainline_xy is not None:
        samples, total_length = sample_polyline_centerline(mainline_xy, closed=True)
    else:
        samples, total_length = sample_track_centerline(segs)
    projections = [project_point_to_samples(point, samples, closed=True, total_length=total_length) for point in pit_xy]
    entry = projections[0]
    exit_ = projections[-1]
    source_direction, host_start, host_end, host_span = real_projection_direction(projections, total_length)
    side_counts = projection_side_counts(projections)
    side = "left" if side_counts["left"] >= side_counts["right"] else "right"
    side_consistency = side_counts[side] / max(1, len(projections))
    turn_deg, full_span_turn_deg, best_window, host_names = real_placement_turn_details(
        segs,
        samples,
        host_start,
        host_end,
        total_length,
        pit_main_length,
        using_source_frame,
    )

    checks = {
        "span_long_enough": host_span >= pit_main_length,
        "curvature_ok": turn_deg <= max_chain_turn_deg,
        "side_consistent": side_consistency >= min_side_consistency,
    }
    return {
        "status": real_placement_status(checks),
        "checks": checks,
        "pit_side": side,
        "side_counts": side_counts,
        "side_consistency": side_consistency,
        "entry_projection": entry,
        "exit_projection": exit_,
        "source_direction": source_direction,
        "host_start_station_m": host_start,
        "host_end_station_m": host_end,
        "projected_span_m": host_span,
        "required_span_m": pit_main_length,
        "mainline_turn_deg": turn_deg,
        "full_span_turn_deg": full_span_turn_deg,
        "best_window": best_window,
        "max_chain_turn_deg": max_chain_turn_deg,
        "host_segments": host_names,
        "projection_frame": "source" if using_source_frame else "track-xml",
        "mean_projection_distance_m": sum(p["distance_m"] for p in projections) / max(1, len(projections)),
        "max_projection_distance_m": max(p["distance_m"] for p in projections),
    }


def pose_replacement_templates(chain: list[ET.Element]) -> tuple[ET.Element, ET.Element, float]:
    str_template = next((s for s in chain if get_attstr(s, "type") == "str"), chain[0])
    turn_template = next((s for s in chain if get_attstr(s, "type") in ("lft", "rgt")), chain[0])
    turn_radii = [max(1e-6, abs(get_attnum(s, "radius", 0.0))) for s in chain if get_attstr(s, "type") in ("lft", "rgt")]
    if turn_radii:
        corr_radius = max(60.0, min(300.0, min(turn_radii)))
    else:
        corr_radius = 180.0
    return str_template, turn_template, corr_radius


def pose_model_error(model: list[dict], dx_tgt: float, dy_tgt: float, dpsi_tgt: float) -> tuple[float, float, float, float]:
    dx, dy, dpsi = simulate_model_segments(model)
    err = math.hypot(dx - dx_tgt, dy - dy_tgt) + 25.0 * abs(math.degrees(dpsi) - dpsi_tgt)
    return err, dx, dy, dpsi


def find_split_turn_pose_model(
    chain: list[ET.Element],
    pit_len: float,
    min_piece_len: float,
    dx_tgt: float,
    dy_tgt: float,
    dpsi_tgt: float,
) -> tuple[float, float, list[dict], float, float, float] | None:
    original_turns = [s for s in chain if get_attstr(s, "type") in ("lft", "rgt")]
    original_straight_len = sum(segment_length(s) for s in chain if get_attstr(s, "type") == "str")
    if len(original_turns) != 1 or original_straight_len < pit_len:
        return None

    split_turn_best = None
    original_turn = original_turns[0]
    original_turn_type = get_attstr(original_turn, "type")
    original_turn_radius = max(1e-6, abs(get_attnum(original_turn, "radius", 0.0)))
    original_turn_arc = abs(get_attnum(original_turn, "arc", 0.0))
    straight_rem = original_straight_len - pit_len
    for frac_i in range(1001):
        turn_frac = frac_i / 1000.0
        for pre_i in range(101):
            pre = straight_rem * pre_i / 100.0
            post = straight_rem - pre
            model = build_split_turn_pose_model(original_turn_type, original_turn_radius, original_turn_arc, turn_frac, pit_len, min_piece_len, pre, post)
            err, dx, dy, dpsi = pose_model_error(model, dx_tgt, dy_tgt, dpsi_tgt)
            cand = (err, turn_frac, model, dx, dy, dpsi)
            if split_turn_best is None or cand[0] < split_turn_best[0]:
                split_turn_best = cand
    return split_turn_best


def build_split_turn_pose_model(
    original_turn_type: str,
    original_turn_radius: float,
    original_turn_arc: float,
    turn_frac: float,
    pit_len: float,
    min_piece_len: float,
    pre: float,
    post: float,
) -> list[dict]:
    model: list[dict] = []
    if pre >= min_piece_len:
        model.append({"type": "str", "role": "host", "lg": pre})
    if original_turn_arc * turn_frac > 1e-8:
        model.append({"type": original_turn_type, "radius": original_turn_radius, "arc": original_turn_arc * turn_frac})
    model.append({"type": "str", "role": "pit_a", "lg": pit_len * 0.5})
    model.append({"type": "str", "role": "pit_b", "lg": pit_len * 0.5})
    if original_turn_arc * (1.0 - turn_frac) > 1e-8:
        model.append({"type": original_turn_type, "radius": original_turn_radius, "arc": original_turn_arc * (1.0 - turn_frac)})
    if post >= min_piece_len:
        model.append({"type": "str", "role": "host", "lg": post})
    return model


def build_synthetic_pose_model(
    rem: float,
    pre_frac: float,
    pit_len: float,
    min_piece_len: float,
    abs_turn: float,
    turn_type: str,
    corr_radius: float,
) -> list[dict]:
    pre = rem * pre_frac
    post = rem - pre
    out: list[dict] = []
    if pre >= min_piece_len:
        out.append({"type": "str", "role": "host", "lg": pre})
    if abs_turn > 1e-6:
        out.append({"type": turn_type, "radius": corr_radius, "arc": abs_turn * 0.5})
    out.append({"type": "str", "role": "pit_a", "lg": pit_len * 0.5})
    out.append({"type": "str", "role": "pit_b", "lg": pit_len * 0.5})
    if abs_turn > 1e-6:
        out.append({"type": turn_type, "radius": corr_radius, "arc": abs_turn * 0.5})
    if post >= min_piece_len:
        out.append({"type": "str", "role": "host", "lg": post})
    return out


def select_best_pose_model(
    split_turn_best: tuple[float, float, list[dict], float, float, float] | None,
    rem: float,
    pit_len: float,
    min_piece_len: float,
    abs_turn: float,
    turn_type: str,
    corr_radius: float,
    dx_tgt: float,
    dy_tgt: float,
    dpsi_tgt: float,
) -> tuple[float, float, list[dict], float, float, float] | None:
    best = split_turn_best
    for i in range(41):
        frac = i / 40.0
        model = build_synthetic_pose_model(rem, frac, pit_len, min_piece_len, abs_turn, turn_type, corr_radius)
        err, dx, dy, dpsi = pose_model_error(model, dx_tgt, dy_tgt, dpsi_tgt)
        cand = (err, frac, model, dx, dy, dpsi)
        if best is None or cand[0] < best[0]:
            best = cand
    return best


def pose_replacement_straight_piece(
    model_part: dict,
    str_template: ET.Element,
    names_used: set[str],
    pit_b_name: str,
) -> tuple[ET.Element, str, str]:
    lg = float(model_part["lg"])
    role = model_part.get("role", "host")
    if role == "pit_a":
        name = unique_name(names_used, "pit_main_a")
        return clone_as_straight(str_template, name, lg), name, ""
    if role == "pit_b":
        name = unique_name(names_used, "pit_main_b")
        return clone_as_straight(str_template, name, lg), "", name
    name = unique_name(names_used, "pit_host_post") if pit_b_name else unique_name(names_used, "pit_host_mid")
    return clone_as_straight(str_template, name, lg), "", ""


def pose_replacement_turn_piece(model_part: dict, turn_template: ET.Element, names_used: set[str]) -> ET.Element | None:
    arc = float(model_part["arc"])
    if arc <= 1e-8:
        return None
    return clone_as_turn(
        turn_template,
        unique_name(names_used, "pit_host_turn"),
        model_part["type"],
        float(model_part["radius"]),
        arc,
    )


def build_pose_replacement_pieces(
    best_model: list[dict],
    str_template: ET.Element,
    turn_template: ET.Element,
    names_used: set[str],
) -> tuple[list[ET.Element], str, str]:
    pieces: list[ET.Element] = []
    pit_a_name = ""
    pit_b_name = ""
    for model_part in best_model:
        if model_part["type"] == "str":
            seg, new_pit_a_name, new_pit_b_name = pose_replacement_straight_piece(model_part, str_template, names_used, pit_b_name)
            pit_a_name = new_pit_a_name or pit_a_name
            pit_b_name = new_pit_b_name or pit_b_name
            pieces.append(seg)
        else:
            seg = pose_replacement_turn_piece(model_part, turn_template, names_used)
            if seg is not None:
                pieces.append(seg)
    return pieces, pit_a_name, pit_b_name


def pose_replacement_meta(
    dx_tgt: float,
    dy_tgt: float,
    dpsi_tgt: float,
    best_frac: float,
    best_dx: float,
    best_dy: float,
    best_dpsi: float,
    corr_radius: float,
    total_turn_deg: float,
    used_split_turn_model: bool,
) -> dict:
    return {
        "target_pose": {"dx": dx_tgt, "dy": dy_tgt, "dpsi_deg": dpsi_tgt},
        "replacement_pose": {"dx": best_dx, "dy": best_dy, "dpsi_deg": math.degrees(best_dpsi)},
        "pose_error": {
            "xy_m": math.hypot(best_dx - dx_tgt, best_dy - dy_tgt),
            "ang_deg": abs(math.degrees(best_dpsi) - dpsi_tgt),
        },
        "chosen_pre_fraction": best_frac,
        "correction_turn_radius_m": corr_radius,
        "correction_total_turn_deg": total_turn_deg,
        "method": "split-original-turn" if used_split_turn_model else "synthetic-correction-turns",
    }


def make_pose_preserving_almost_replacement(
    chain: list[ET.Element],
    pit_len: float,
    min_piece_len: float,
    names_used: set[str],
) -> tuple[list[ET.Element], str, str, dict]:
    if not chain:
        raise RuntimeError("Empty host chain")

    dx_tgt, dy_tgt, dpsi_tgt, host_len, total_turn_deg = chain_pose(chain)
    rem = max(0.0, host_len - pit_len)
    str_template, turn_template, corr_radius = pose_replacement_templates(chain)
    abs_turn = abs(total_turn_deg)
    turn_type = "lft" if total_turn_deg >= 0.0 else "rgt"

    split_turn_best = find_split_turn_pose_model(chain, pit_len, min_piece_len, dx_tgt, dy_tgt, dpsi_tgt)
    best = select_best_pose_model(
        split_turn_best,
        rem,
        pit_len,
        min_piece_len,
        abs_turn,
        turn_type,
        corr_radius,
        dx_tgt,
        dy_tgt,
        dpsi_tgt,
    )

    if best is None:
        raise RuntimeError("No viable pit-lane pose replacement model found")
    _, best_frac, best_model, best_dx, best_dy, best_dpsi = best
    pieces, pit_a_name, pit_b_name = build_pose_replacement_pieces(best_model, str_template, turn_template, names_used)

    if not pit_a_name or not pit_b_name:
        # Fallback to simple split if matching by geometry failed.
        pieces, pit_a_name, pit_b_name = split_host_to_pit_segments(
            template=str_template,
            host_len=host_len,
            pit_len=pit_len,
            min_piece_len=min_piece_len,
            names_used=names_used,
        )

    meta = pose_replacement_meta(
        dx_tgt,
        dy_tgt,
        dpsi_tgt,
        best_frac,
        best_dx,
        best_dy,
        best_dpsi,
        corr_radius,
        total_turn_deg,
        split_turn_best is not None and best is split_turn_best,
    )
    return pieces, pit_a_name, pit_b_name, meta


def connector_fit_initial_vectors(
    pre_radius: float,
    pre_arc: float,
    pit_len: float,
    host_len: float,
    post_radius: float,
    post_arc: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lower = np.array([30.0, 0.0, pit_len, 30.0, 0.0], dtype=float)
    upper = np.array([1000.0, 80.0, max(host_len, pit_len), 1000.0, 80.0], dtype=float)
    current = np.array(
        [
            min(max(pre_radius, lower[0]), upper[0]),
            min(max(pre_arc, lower[1]), upper[1]),
            min(max(pit_len, lower[2]), upper[2]),
            min(max(post_radius, lower[3]), upper[3]),
            min(max(post_arc, lower[4]), upper[4]),
        ],
        dtype=float,
    )
    return lower, upper, current


def connector_model_segments(pre_type: str, post_type: str, values: np.ndarray) -> list[dict]:
    radius_a, arc_a, straight_len, radius_b, arc_b = values
    return [
        {"type": pre_type, "radius": radius_a, "arc": arc_a},
        {"type": "str", "lg": straight_len},
        {"type": post_type, "radius": radius_b, "arc": arc_b},
    ]


def connector_residual(values: np.ndarray, context: dict) -> np.ndarray:
    radius_a, arc_a, straight_len, radius_b, arc_b = values
    dx, dy, dpsi = simulate_model_segments(connector_model_segments(context["pre_type"], context["post_type"], values))
    return np.array(
        [
            100.0 * (dx - context["target_dx"]),
            100.0 * (dy - context["target_dy"]),
            1000.0 * (math.degrees(dpsi) - context["target_dpsi_deg"]),
            0.001 * (radius_a - context["pre_radius"]),
            0.005 * (arc_a - context["pre_arc"]),
            0.001 * (straight_len - context["host_len"]),
            0.001 * (radius_b - context["post_radius"]),
            0.005 * (arc_b - context["post_arc"]),
        ],
        dtype=float,
    )


def connector_fit_error(values: np.ndarray, context: dict) -> float:
    residual = connector_residual(values, context)
    return float(np.dot(residual, residual))


def connector_jacobian(current: np.ndarray, lower: np.ndarray, upper: np.ndarray, base: np.ndarray, context: dict) -> np.ndarray:
    jac = np.zeros((base.size, current.size), dtype=float)
    for i in range(current.size):
        step = max(abs(current[i]) * 1e-6, 1e-6)
        trial = current.copy()
        trial[i] = min(upper[i], max(lower[i], trial[i] + step))
        actual_step = trial[i] - current[i]
        if abs(actual_step) > 1e-12:
            jac[:, i] = (connector_residual(trial, context) - base) / actual_step
    return jac


def solve_connector_delta(lhs: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    try:
        return np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(lhs, rhs, rcond=None)[0]


def improve_connector_fit_step(
    current: np.ndarray,
    best: np.ndarray,
    best_err: float,
    damping: float,
    delta: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    context: dict,
) -> tuple[bool, np.ndarray, np.ndarray, float, float]:
    scale = 1.0
    for _ in range(12):
        trial = np.minimum(upper, np.maximum(lower, current + scale * delta))
        err = connector_fit_error(trial, context)
        if err < best_err:
            return True, trial, trial.copy(), err, max(1e-8, damping * 0.5)
        scale *= 0.5
    return False, current, best, best_err, damping * 10.0


def fit_connector_values(current: np.ndarray, lower: np.ndarray, upper: np.ndarray, context: dict) -> np.ndarray:
    damping = 1e-3
    best = current.copy()
    best_err = connector_fit_error(best, context)
    for _ in range(80):
        base = connector_residual(current, context)
        jac = connector_jacobian(current, lower, upper, base, context)
        lhs = jac.T @ jac + damping * np.eye(current.size)
        rhs = -(jac.T @ base)
        delta = solve_connector_delta(lhs, rhs)
        if float(np.linalg.norm(delta)) < 1e-9:
            break
        improved, current, best, best_err, damping = improve_connector_fit_step(current, best, best_err, damping, delta, lower, upper, context)
        if not improved:
            continue
    return best


def connector_fit_context(
    pre_type: str,
    post_type: str,
    target_dx: float,
    target_dy: float,
    target_dpsi_deg: float,
    host_len: float,
    pre_radius: float,
    pre_arc: float,
    post_radius: float,
    post_arc: float,
) -> dict:
    return {
        "pre_type": pre_type,
        "post_type": post_type,
        "target_dx": target_dx,
        "target_dy": target_dy,
        "target_dpsi_deg": target_dpsi_deg,
        "host_len": host_len,
        "pre_radius": pre_radius,
        "pre_arc": pre_arc,
        "post_radius": post_radius,
        "post_arc": post_arc,
    }


def connector_fit_meta(
    pre_connector: ET.Element,
    post_connector: ET.Element,
    host_chain: list[ET.Element],
    host_len: float,
    pit_len: float,
    values: np.ndarray,
    context: dict,
    pose_error_xy: float,
    pose_error_ang: float,
) -> dict:
    radius_a, arc_a, straight_len, radius_b, arc_b = values
    return {
        "method": "connector-straighten",
        "host_chain_start": host_chain[0].get("name", "") if host_chain else "",
        "host_chain_end": host_chain[-1].get("name", "") if host_chain else "",
        "original_host_length_m": host_len,
        "straight_length_m": straight_len,
        "pit_main_length_m": pit_len,
        "entry_connector": {
            "segment": pre_connector.get("name", ""),
            "type": context["pre_type"],
            "old_radius_m": context["pre_radius"],
            "old_arc_deg": context["pre_arc"],
            "new_radius_m": radius_a,
            "new_arc_deg": arc_a,
        },
        "exit_connector": {
            "segment": post_connector.get("name", ""),
            "type": context["post_type"],
            "old_radius_m": context["post_radius"],
            "old_arc_deg": context["post_arc"],
            "new_radius_m": radius_b,
            "new_arc_deg": arc_b,
        },
        "pose_error": {"xy_m": pose_error_xy, "ang_deg": pose_error_ang},
    }


def fit_connector_straightening(
    pre_connector: ET.Element,
    host_chain: list[ET.Element],
    post_connector: ET.Element,
    pit_len: float,
    names_used: set[str],
) -> tuple[list[ET.Element], str, dict]:
    if get_attstr(pre_connector, "type") not in ("lft", "rgt") or get_attstr(post_connector, "type") not in ("lft", "rgt"):
        raise SystemExit("--host-mode straighten requires curved connector segments immediately before and after the host chain")

    target_dx, target_dy, target_dpsi_deg, _, _ = chain_pose([pre_connector, *host_chain, post_connector])
    host_len = sum(segment_length(seg) for seg in host_chain)
    if host_len < pit_len:
        raise SystemExit("--host-mode straighten host chain is shorter than the pit main length")

    pre_type = get_attstr(pre_connector, "type")
    post_type = get_attstr(post_connector, "type")
    pre_radius = abs(get_attnum(pre_connector, "radius", 0.0))
    pre_arc = abs(get_attnum(pre_connector, "arc", 0.0))
    post_radius = abs(get_attnum(post_connector, "radius", 0.0))
    post_arc = abs(get_attnum(post_connector, "arc", 0.0))

    lower, upper, current = connector_fit_initial_vectors(pre_radius, pre_arc, pit_len, host_len, post_radius, post_arc)
    context = connector_fit_context(pre_type, post_type, target_dx, target_dy, target_dpsi_deg, host_len, pre_radius, pre_arc, post_radius, post_arc)
    best = fit_connector_values(current, lower, upper, context)

    radius_a, arc_a, straight_len, radius_b, arc_b = best
    dx, dy, dpsi = simulate_model_segments(connector_model_segments(pre_type, post_type, best))
    pose_error_xy = math.hypot(dx - target_dx, dy - target_dy)
    pose_error_ang = abs(math.degrees(dpsi) - target_dpsi_deg)
    if pose_error_xy > 0.05 or pose_error_ang > 0.001:
        raise SystemExit(
            "--host-mode straighten could not refit adjacent connectors accurately enough: "
            f"xy={pose_error_xy:.6f} m, ang={pose_error_ang:.6f} deg"
        )

    host_template = next((seg for seg in host_chain if get_attstr(seg, "type") == "str"), host_chain[0])
    host_name = unique_name(names_used, "pit_host_straight")
    pieces = [
        clone_as_turn(pre_connector, pre_connector.get("name", "pit_host_entry"), pre_type, radius_a, arc_a),
        clone_as_straight(host_template, host_name, straight_len),
        clone_as_turn(post_connector, post_connector.get("name", "pit_host_exit"), post_type, radius_b, arc_b),
    ]
    meta = connector_fit_meta(pre_connector, post_connector, host_chain, host_len, pit_len, best, context, pose_error_xy, pose_error_ang)
    return pieces, host_name, meta


def is_turn_segment(seg: ET.Element) -> bool:
    return get_attstr(seg, "type") in ("lft", "rgt")


def is_straight_segment(seg: ET.Element) -> bool:
    return get_attstr(seg, "type") == "str"


def previous_turn_index_skipping_straights(segs: list[ET.Element], start_idx: int) -> int:
    """Return the previous turn index, scanning over straight connector fragments."""
    if not segs:
        raise SystemExit("--host-mode straighten requires a non-empty segment list")
    idx = (start_idx - 1) % len(segs)
    visited = 0
    while visited < len(segs) and is_straight_segment(segs[idx]):
        idx = (idx - 1) % len(segs)
        visited += 1
    if not is_turn_segment(segs[idx]):
        raise SystemExit("--host-mode straighten requires a curved connector before the host chain")
    return idx


def straighten_connector_window(segs: list[ET.Element], i0: int, i1: int) -> tuple[int, int, int, int, dict]:
    """Find adjustable connector turns around a manual straighten host.

    The requested host range is kept as the semantic selection, but XML generated
    by curb/closure passes may put short straight fragments between that range
    and the next usable arc.  Treat those straight fragments as connector
    straights and replace the expanded window with a refitted turn/straight/turn
    sequence.
    """
    if i0 <= 0 or i1 + 1 >= len(segs):
        raise SystemExit("--host-mode straighten requires one connector segment before and after the host chain")

    pre_idx = i0 - 1
    pre_scan: list[str] = []
    while pre_idx >= 0 and is_straight_segment(segs[pre_idx]):
        pre_scan.insert(0, segs[pre_idx].get("name", ""))
        pre_idx -= 1
    if pre_idx < 0 or not is_turn_segment(segs[pre_idx]):
        raise SystemExit("--host-mode straighten requires a curved connector before the host chain")

    post_idx = i1 + 1
    post_scan: list[str] = []
    while post_idx < len(segs) and is_straight_segment(segs[post_idx]):
        post_scan.append(segs[post_idx].get("name", ""))
        post_idx += 1
    if post_idx >= len(segs) or not is_turn_segment(segs[post_idx]):
        raise SystemExit("--host-mode straighten requires a curved connector after the host chain")

    meta = {
        "requested_host_chain_start": segs[i0].get("name", ""),
        "requested_host_chain_end": segs[i1].get("name", ""),
        "scanned_pre_straights": pre_scan,
        "scanned_post_straights": post_scan,
    }
    return pre_idx, pre_idx + 1, post_idx - 1, post_idx, meta


def unique_name(existing: set[str], base: str) -> str:
    if base not in existing:
        existing.add(base)
        return base
    idx = 1
    while True:
        cand = f"{base}-{idx}"
        if cand not in existing:
            existing.add(cand)
            return cand
        idx += 1


def pit_host_spare_lengths(host_len: float, pit_len: float, align: str) -> tuple[float, float]:
    rem = max(0.0, host_len - pit_len)
    if align == "start":
        return 0.0, rem
    if align == "end":
        return rem, 0.0
    pre = rem * 0.5
    return pre, rem - pre


def split_host_to_pit_segments(
    template: ET.Element,
    host_len: float,
    pit_len: float,
    min_piece_len: float,
    names_used: set[str],
    align: str = "center",
) -> tuple[list[ET.Element], str, str]:
    pre, post = pit_host_spare_lengths(host_len, pit_len, align)

    pieces: list[ET.Element] = []
    if pre >= min_piece_len:
        pieces.append(clone_as_straight(template, unique_name(names_used, "pit_host_pre"), pre))

    pit_a = clone_as_straight(template, unique_name(names_used, "pit_main_a"), pit_len * 0.5)
    pit_b = clone_as_straight(template, unique_name(names_used, "pit_main_b"), pit_len * 0.5)
    pieces.extend([pit_a, pit_b])

    if post >= min_piece_len:
        pieces.append(clone_as_straight(template, unique_name(names_used, "pit_host_post"), post))

    return pieces, pit_a.get("name", "pit_main_a"), pit_b.get("name", "pit_main_b")


def rotate_segments_to_start(segments: list[ET.Element], start_name: str) -> list[ET.Element]:
    idx = next((i for i, s in enumerate(segments) if s.get("name") == start_name), -1)
    if idx < 0:
        return segments
    return segments[idx:] + segments[:idx]


def cyclic_index_chain_wraps(indices: list[int]) -> bool:
    return any(indices[i] <= indices[i - 1] for i in range(1, len(indices)))


def forward_station_distance(start: float, station: float, total: float) -> float:
    if total <= 0.0:
        return abs(station - start)
    return (station - start) % total


def source_window_to_xml_stations(source_start: float, source_end: float, source_total: float, xml_total: float, source_origin: float) -> tuple[float, float]:
    rel_start = (source_start - source_origin) % source_total
    rel_end = (source_end - source_origin) % source_total
    return rel_start / source_total * xml_total, rel_end / source_total * xml_total


def segment_start_stations(lengths: list[float]) -> list[float]:
    starts: list[float] = []
    run = 0.0
    for length in lengths:
        starts.append(run)
        run += length
    return starts


def select_station_window_indices(lengths: list[float], starts: list[float], xml_start: float, xml_end: float, xml_total: float) -> list[int]:
    selected = []
    for i, length in enumerate(lengths):
        mid = starts[i] + length * 0.5
        if station_in_span(mid, xml_start, xml_end, xml_total):
            selected.append(i)
    if not selected:
        selected = [min(range(len(lengths)), key=lambda i: forward_station_distance(xml_start, starts[i] + lengths[i] * 0.5, xml_total))]
    return selected


def order_station_window_indices(selected: list[int], lengths: list[float], starts: list[float], xml_start: float, xml_total: float) -> list[int]:
    selected_set = set(selected)
    i0 = min(selected, key=lambda i: forward_station_distance(xml_start, starts[i] + lengths[i] * 0.5, xml_total))
    ordered = [idx for idx in (i0 + step for step in range(len(lengths))) if idx % len(lengths) in selected_set]
    ordered = [idx % len(lengths) for idx in ordered]
    if not ordered:
        ordered = [i0]
    return ordered


def expand_station_window_to_length(ordered: list[int], lengths: list[float], pit_len: float) -> list[int]:
    while sum(lengths[idx] for idx in ordered) < pit_len and len(ordered) < len(lengths):
        before = (ordered[0] - 1 + len(lengths)) % len(lengths)
        after = (ordered[-1] + 1) % len(lengths)
        if before in ordered and after in ordered:
            break
        if before in ordered:
            ordered.append(after)
        elif after in ordered:
            ordered.insert(0, before)
        elif lengths[before] <= lengths[after]:
            ordered.insert(0, before)
        else:
            ordered.append(after)
    return ordered


def station_window_to_host_strategy(
    segs: list[ET.Element],
    source_start: float,
    source_end: float,
    source_total: float,
    pit_len: float,
    source_origin: float = 0.0,
) -> dict:
    lengths = [segment_length(s) for s in segs]
    xml_total = sum(lengths)
    if source_total <= 0.0 or xml_total <= 0.0:
        raise SystemExit("Cannot map real pit placement station window onto an empty track")
    xml_start, xml_end = source_window_to_xml_stations(source_start, source_end, source_total, xml_total, source_origin)
    starts = segment_start_stations(lengths)
    selected = select_station_window_indices(lengths, starts, xml_start, xml_end, xml_total)
    ordered = order_station_window_indices(selected, lengths, starts, xml_start, xml_total)
    ordered = expand_station_window_to_length(ordered, lengths, pit_len)

    i0 = ordered[0]
    i1 = ordered[-1]
    host_len = sum(lengths[idx] for idx in ordered)
    if host_len < pit_len:
        raise SystemExit("Real pit placement host window is shorter than requested pit main length")
    turn_deg = sum(segment_heading_delta_deg(segs[idx]) for idx in ordered)
    wraps = cyclic_index_chain_wraps(ordered)
    return {
        "mode": "almost",
        "i0": i0,
        "i1": i1,
        "index_count": len(ordered),
        "wrap": wraps,
        "length": host_len,
        "turn_deg": turn_deg,
        "real_placement": True,
        "source_start_station_m": source_start,
        "source_end_station_m": source_end,
        "source_origin_station_m": source_origin,
        "xml_start_station_m": xml_start,
        "xml_end_station_m": xml_end,
    }


def source_station_at_index(points: list[dict], index: int) -> float:
    if index <= 0 or index >= len(points):
        return 0.0
    xy = to_xy_points(points, points[0])
    station = 0.0
    for i in range(1, index + 1):
        station += math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1])
    return station


def source_total_length(points: list[dict]) -> float:
    if len(points) < 2:
        return 0.0
    xy = to_xy_points(points, points[0])
    total = 0.0
    for i in range(1, len(xy)):
        total += math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1])
    close_len = math.hypot(xy[0][0] - xy[-1][0], xy[0][1] - xy[-1][1])
    if close_len > 1e-9:
        total += close_len
    return total


def segment_name_base_and_suffix(seg: ET.Element) -> tuple[str, int | None]:
    name = seg.get("name", "")
    match = re.search(r"-(\d+)$", name)
    if match is None:
        return name, None
    return name[: match.start()], int(match.group(1))


def source_station_for_segment_origin(points: list[dict], seg: ET.Element) -> float:
    name = seg.get("name", "")
    for i, point in enumerate(points):
        if point.get("way_name") == name:
            return source_station_at_index(points, i)

    base_name, suffix_index = segment_name_base_and_suffix(seg)
    if suffix_index is not None and 0 <= suffix_index < len(points) and points[suffix_index].get("way_name") == base_name:
        return source_station_at_index(points, suffix_index)
    for i, point in enumerate(points):
        if point.get("way_name") == base_name:
            return source_station_at_index(points, i)
    return 0.0


def source_origin_for_segments(points: list[dict], segs: list[ET.Element]) -> float:
    xml_station = 0.0
    source_total = source_total_length(points)
    source_names = {str(point.get("way_name", "")) for point in points}
    for seg in segs:
        name = seg.get("name", "")
        base_name, _ = segment_name_base_and_suffix(seg)
        if (name and name in source_names) or (base_name and not base_name.startswith("Segment-") and base_name in source_names):
            return (source_station_for_segment_origin(points, seg) - xml_station) % max(1e-9, source_total)
        xml_station += segment_length(seg)
    return 0.0


def no_pit_backup_path(xml_path: pathlib.Path) -> pathlib.Path:
    source_dir = xml_path.parent if xml_path.parent.name == "source" else xml_path.parent / "source"
    return source_dir / f"{xml_path.stem}-no-pits.xml"


def write_no_pit_backup(xml_path: pathlib.Path, raw: str, pits: ET.Element, dry_run: bool) -> str:
    if get_attstr(pits, "type", "none") != "none":
        return ""
    backup_path = no_pit_backup_path(xml_path)
    if dry_run or backup_path.exists():
        return str(backup_path)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(raw, encoding="utf-8")
    return str(backup_path)


def ordered_taper_indices_backward(lengths: list[float], start_idx: int, total_len: float, stop_idxs: set[int] | None = None) -> list[int]:
    stop_idxs = stop_idxs or set()
    out: list[int] = []
    acc = 0.0
    n = len(lengths)
    i = start_idx
    while acc < total_len and n > 0:
        i = (i - 1 + n) % n
        if i in stop_idxs:
            break
        out.append(i)
        acc += lengths[i]
        if len(out) > n:
            break
    out.reverse()
    return out


def ordered_taper_indices_forward(lengths: list[float], start_idx: int, total_len: float, stop_idxs: set[int] | None = None) -> list[int]:
    stop_idxs = stop_idxs or set()
    out: list[int] = []
    acc = 0.0
    n = len(lengths)
    i = start_idx
    while acc < total_len and n > 0:
        i = (i + 1) % n
        if i in stop_idxs:
            break
        out.append(i)
        acc += lengths[i]
        if len(out) > n:
            break
    return out


def linear_interp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def apply_side_width_profile(
    segs: list[ET.Element],
    idxs: list[int],
    side_name: str,
    width_start: float,
    width_end: float,
    total_len: float,
    side_surface: str,
) -> tuple[str, str]:
    if not idxs:
        return "", ""
    run = 0.0
    first_name = segs[idxs[0]].get("name", "")
    last_name = segs[idxs[-1]].get("name", "")
    for idx in idxs:
        seg = segs[idx]
        L = max(1e-6, segment_length(seg))
        t0 = run / max(1e-6, total_len)
        t1 = (run + L) / max(1e-6, total_len)
        run += L

        side = get_or_make_child_section(seg, side_name)
        set_attstr(side, "surface", side_surface)
        set_attnum(side, "start width", linear_interp(width_start, width_end, t0), "m")
        set_attnum(side, "end width", linear_interp(width_start, width_end, t1), "m")
    return first_name, last_name


def apply_border_style(seg: ET.Element, border_name: str, style: str, surface: str, width: float, height: float | None = None) -> None:
    border = get_or_make_child_section(seg, border_name)
    set_attstr(border, "style", style)
    set_attstr(border, "surface", surface)
    set_attnum(border, "width", width, "m")
    if height is None:
        remove_attnum(border, "height")
    else:
        set_attnum(border, "height", height, "m")


def reset_normal_side_state(seg: ET.Element, side_name: str, border_name: str, side_width: float) -> None:
    side = get_or_make_child_section(seg, side_name)
    set_attstr(side, "surface", "grass6")
    set_attnum(side, "start width", side_width, "m")
    set_attnum(side, "end width", side_width, "m")

    border = get_or_make_child_section(seg, border_name)
    set_attstr(border, "style", NORMAL_BORDER_STYLE)
    set_attstr(border, "surface", NORMAL_BORDER_SURFACE)
    set_attnum(border, "width", NORMAL_BORDER_WIDTH, "m")
    remove_attnum(border, "height")


def reset_normal_border_state(seg: ET.Element, border_name: str) -> None:
    border = get_or_make_child_section(seg, border_name)
    set_attstr(border, "style", NORMAL_BORDER_STYLE)
    set_attstr(border, "surface", NORMAL_BORDER_SURFACE)
    set_attnum(border, "width", NORMAL_BORDER_WIDTH, "m")
    remove_attnum(border, "height")


def normalize_manual_surfaces(root: ET.Element) -> None:
    surfaces = next((s for s in root.iter("section") if s.get("name") == "Surfaces"), None)
    if surfaces is None:
        return

    asphalt = get_or_make_child_section(surfaces, "manual-asphalt")
    set_attstr(asphalt, "texture name", "tr-road1.rgb")
    set_attstr(asphalt, "texture type", "continuous")
    set_attnum(asphalt, "texture size", 15.0001, "m")
    set_attnum(asphalt, "texture mipmap", 0.0, "m")
    set_attstr(asphalt, "texture start on boundary", "yes")
    set_attstr(asphalt, "texture link with previous", "yes")
    set_attstr(asphalt, "raceline name", "raceline.png")
    set_attnum(asphalt, "friction", 1.06)
    set_attnum(asphalt, "rolling resistance", 0.021)
    set_attnum(asphalt, "roughness", 0.0007)
    set_attnum(asphalt, "roughness wavelength", 2.0)

    barrier = get_or_make_child_section(surfaces, "manual-barrier")
    set_attstr(barrier, "texture name", "arbor2_n.rgb")
    set_attstr(barrier, "texture type", "continuous")
    set_attnum(barrier, "texture size", 10.0, "m")
    set_attnum(barrier, "texture mipmap", 0.0)
    set_attnum(barrier, "friction", 0.0)
    set_attnum(barrier, "dammage", 10)


def parse_xml_preserve_entity(xml_path: pathlib.Path) -> tuple[str, ET.ElementTree]:
    raw = xml_path.read_text(encoding="utf-8")
    replaced = raw.replace("&default-surfaces;", f"<{ENTITY_PLACEHOLDER}/>")
    tree = ET.ElementTree(ET.fromstring(replaced))
    return raw, tree


def serialize_xml_restore_entity(raw: str, tree: ET.ElementTree) -> str:
    root = tree.getroot()
    ET.indent(tree, space="\t")
    body = ET.tostring(root, encoding="unicode")

    body = body.replace(f"<{ENTITY_PLACEHOLDER} />", "&default-surfaces;")
    body = body.replace(f"<{ENTITY_PLACEHOLDER}/>", "&default-surfaces;")

    root_match = re.search(r"<params\b", raw)
    prolog = raw[: root_match.start()] if root_match else '<?xml version="1.0" encoding="UTF-8"?>\n'
    return prolog + body + "\n"


def find_exact_host_strategy(segs: list[ET.Element], lengths: list[float], pit_len: float) -> dict | None:
    exact = [(i, lengths[i]) for i, seg in enumerate(segs) if get_attstr(seg, "type") == "str" and lengths[i] >= pit_len]
    if not exact:
        return None
    i, length = max(exact, key=lambda x: x[1])
    return {"mode": "exact", "i0": i, "i1": i, "length": length}


def almost_segment_turn_delta(seg: ET.Element, almost_max_curv: float, almost_max_seg_turn_deg: float) -> tuple[bool, float]:
    seg_type = get_attstr(seg, "type")
    if seg_type in ("lft", "rgt"):
        if segment_curvature(seg) > almost_max_curv:
            return False, 0.0
        if abs(get_attnum(seg, "arc", 0.0)) > almost_max_seg_turn_deg:
            return False, 0.0
        return True, segment_heading_delta_deg(seg)
    return seg_type == "str", 0.0


def almost_chain_limits_exceeded(
    total_len: float,
    total_turn: float,
    seg_count: int,
    almost_max_chain_turn_deg: float,
    max_host_window_segs: int,
    max_host_window_len_m: float,
) -> bool:
    return (
        abs(total_turn) > almost_max_chain_turn_deg
        or seg_count > max(1, max_host_window_segs)
        or total_len > max(1.0, max_host_window_len_m)
    )


def almost_chain_candidate(
    segs: list[ET.Element],
    lengths: list[float],
    start: int,
    pit_len: float,
    almost_max_curv: float,
    almost_max_seg_turn_deg: float,
    almost_max_chain_turn_deg: float,
    max_host_window_segs: int,
    max_host_window_len_m: float,
) -> dict | None:
    total_len = 0.0
    total_turn = 0.0
    seg_count = 0
    n = len(segs)
    for offset in range(n):
        j = (start + offset) % n
        seg = segs[j]
        allowed, turn_delta = almost_segment_turn_delta(seg, almost_max_curv, almost_max_seg_turn_deg)
        if not allowed:
            break
        total_turn += turn_delta

        total_len += lengths[j]
        seg_count += 1
        if almost_chain_limits_exceeded(total_len, total_turn, seg_count, almost_max_chain_turn_deg, max_host_window_segs, max_host_window_len_m):
            break
        if total_len >= pit_len:
            return {
                "mode": "almost",
                "i0": start,
                "i1": j,
                "index_count": seg_count,
                "wrap": j < start,
                "length": total_len,
                "turn_deg": total_turn,
            }
    return None


def almost_chain_score(candidate: dict, preserve_host_pose: bool) -> tuple[float, int, float] | tuple[float, float, int]:
    if preserve_host_pose:
        return (-abs(candidate["turn_deg"]), candidate["index_count"], candidate["length"])
    return (candidate["length"], -abs(candidate["turn_deg"]), -candidate["index_count"])


def find_almost_host_strategy(
    segs: list[ET.Element],
    lengths: list[float],
    pit_len: float,
    almost_max_curv: float,
    almost_max_seg_turn_deg: float,
    almost_max_chain_turn_deg: float,
    preserve_host_pose: bool,
    max_host_window_segs: int,
    max_host_window_len_m: float,
) -> dict | None:
    best_chain = None
    for i in range(len(segs)):
        candidate = almost_chain_candidate(
            segs,
            lengths,
            i,
            pit_len,
            almost_max_curv,
            almost_max_seg_turn_deg,
            almost_max_chain_turn_deg,
            max_host_window_segs,
            max_host_window_len_m,
        )
        if candidate is None:
            continue
        score = almost_chain_score(candidate, preserve_host_pose)
        if best_chain is None or score > best_chain["score"]:
            candidate["score"] = score
            best_chain = candidate
    if best_chain is not None:
        best_chain.pop("score", None)
    return best_chain


def find_lengthen_host_strategy(segs: list[ET.Element], lengths: list[float]) -> dict | None:
    longest_straight = [(i, lengths[i]) for i, seg in enumerate(segs) if get_attstr(seg, "type") == "str"]
    if not longest_straight:
        return None
    i, length = max(longest_straight, key=lambda x: x[1])
    return {"mode": "lengthen", "i0": i, "i1": i, "length": length}


def choose_host_strategy(
    segs: list[ET.Element],
    pit_len: float,
    almost_max_curv: float,
    almost_max_seg_turn_deg: float,
    almost_max_chain_turn_deg: float,
    preserve_host_pose: bool,
    max_host_window_segs: int,
    max_host_window_len_m: float,
    mode_override: str,
) -> dict:
    lengths = [segment_length(s) for s in segs]

    exact = find_exact_host_strategy(segs, lengths, pit_len)
    if mode_override == "exact" and not exact:
        raise SystemExit("Requested host-mode 'exact' but no straight >= pit length was found")
    if exact is not None:
        if mode_override in ("auto", "exact"):
            return exact

    best_chain = find_almost_host_strategy(
        segs,
        lengths,
        pit_len,
        almost_max_curv,
        almost_max_seg_turn_deg,
        almost_max_chain_turn_deg,
        preserve_host_pose,
        max_host_window_segs,
        max_host_window_len_m,
    )
    if best_chain is not None:
        if mode_override in ("auto", "almost"):
            return best_chain
    if mode_override == "almost":
        raise SystemExit("Requested host-mode 'almost' but no suitable almost-straight chain was found")

    lengthen = find_lengthen_host_strategy(segs, lengths)
    if lengthen is not None:
        if mode_override in ("auto", "lengthen"):
            return lengthen
    if mode_override == "lengthen":
        raise SystemExit("Requested host-mode 'lengthen' but no straight segment was found")

    if mode_override not in ("auto", "inject"):
        raise SystemExit(f"Requested host-mode '{mode_override}' cannot be satisfied")
    return {"mode": "inject", "i0": 0, "i1": 0, "length": 0.0}


def find_segment_index(segs: list[ET.Element], name: str) -> int:
    for i, seg in enumerate(segs):
        if seg.get("name", "") == name:
            return i
    raise SystemExit(f"Manual pit host segment not found: {name}")


def resolve_manual_host_indices(
    segs: list[ET.Element],
    host_segment: str,
    host_start_segment: str,
    host_end_segment: str,
) -> tuple[int, int]:
    if host_segment and (host_start_segment or host_end_segment):
        raise SystemExit("Use either --host-segment or --host-start-segment/--host-end-segment, not both")
    if host_start_segment or host_end_segment:
        if not host_start_segment or not host_end_segment:
            raise SystemExit("Manual pit host chain requires both --host-start-segment and --host-end-segment")
        i0 = find_segment_index(segs, host_start_segment)
        i1 = find_segment_index(segs, host_end_segment)
        if i1 < i0:
            raise SystemExit("Manual pit host chain must be contiguous in XML order; rotate wrapping chains before selection")
        return i0, i1
    if host_segment:
        i0 = find_segment_index(segs, host_segment)
        return i0, i0
    raise SystemExit("No manual pit host specified")


def manual_host_turn_deg(segs: list[ET.Element], i0: int, i1: int) -> float:
    return sum(segment_heading_delta_deg(seg) for seg in segs[i0 : i1 + 1])


def build_manual_host_strategy(segs: list[ET.Element], i0: int, i1: int, host_len: float, mode: str) -> dict:
    return {
        "mode": mode,
        "i0": i0,
        "i1": i1,
        "length": host_len,
        "turn_deg": manual_host_turn_deg(segs, i0, i1),
        "manual_host": True,
    }


def validate_manual_straighten_host(host_start_segment: str, host_end_segment: str, host_len: float, pit_len: float) -> None:
    if not (host_start_segment and host_end_segment):
        raise SystemExit("--host-mode straighten requires --host-start-segment and --host-end-segment")
    if host_len < pit_len:
        raise SystemExit("--host-mode straighten host chain is shorter than pit main length")


def choose_manual_host_mode(segs: list[ET.Element], i0: int, i1: int, host_len: float, pit_len: float, mode_override: str) -> str:
    if host_len < pit_len and mode_override not in ("auto", "lengthen", "inject"):
        raise SystemExit("Manual pit host is shorter than pit main length")
    mode = "exact" if i0 == i1 and get_attstr(segs[i0], "type") == "str" and host_len >= pit_len else "almost"
    if host_len < pit_len:
        mode = "lengthen" if i0 == i1 and get_attstr(segs[i0], "type") == "str" else "almost"
    return mode


def choose_manual_host_strategy(
    segs: list[ET.Element],
    host_segment: str,
    host_start_segment: str,
    host_end_segment: str,
    pit_len: float,
    mode_override: str,
) -> dict:
    i0, i1 = resolve_manual_host_indices(segs, host_segment, host_start_segment, host_end_segment)
    host_len = sum(segment_length(seg) for seg in segs[i0 : i1 + 1])
    if mode_override == "straighten":
        validate_manual_straighten_host(host_start_segment, host_end_segment, host_len, pit_len)
        return build_manual_host_strategy(segs, i0, i1, host_len, "straighten")
    mode = choose_manual_host_mode(segs, i0, i1, host_len, pit_len, mode_override)
    return build_manual_host_strategy(segs, i0, i1, host_len, mode)


def run_trackgen_z(runtime_dir: pathlib.Path, category: str, name: str) -> dict:
    metrics, _ = run_trackgen_z_shared(runtime_dir, category, name)
    return metrics


def derive_runtime_context(xml_path: pathlib.Path) -> tuple[pathlib.Path, str, str]:
    parts = list(xml_path.parts)
    parts_l = [p.lower() for p in parts]
    if "tracks" not in parts_l:
        raise RuntimeError("Could not auto-detect runtime/category/name from track path")
    i = parts_l.index("tracks")
    if i + 3 >= len(parts):
        raise RuntimeError("Track path must be .../tracks/<category>/<name>/<name>.xml")
    category = parts[i + 1]
    name = parts[i + 2]
    runtime_dir = pathlib.Path(*parts[:i])
    return runtime_dir, category, name


def resolve_safety_runtime_context(xml_path: pathlib.Path, args: argparse.Namespace) -> tuple[pathlib.Path, str, str]:
    runtime_dir = pathlib.Path(args.runtime_dir) if args.runtime_dir else None
    category = args.category
    name = args.name
    if runtime_dir is None or not category or not name:
        auto_runtime, auto_category, auto_name = derive_runtime_context(xml_path)
        if runtime_dir is None:
            runtime_dir = auto_runtime
        if not category:
            category = auto_category
        if not name:
            name = auto_name
    return runtime_dir, category, name


def run_overlay_compare(
    overlay_script: pathlib.Path,
    polyline: pathlib.Path,
    track_xml: pathlib.Path,
    out_dir: pathlib.Path,
    tag: str,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay = out_dir / f"layout-compare-{tag}.svg"
    report = out_dir / f"layout-compare-{tag}.json"
    cmd = [
        sys.executable,
        str(overlay_script),
        "--polyline",
        str(polyline),
        "--track-xml",
        str(track_xml),
        "--overlay",
        str(overlay),
        "--report",
        str(report),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Overlay compare failed\n{proc.stdout}")
    obj = json.loads(report.read_text(encoding="utf-8"))
    return {
        "mean_deviation_m": float(obj.get("mean_deviation_m", 0.0)),
        "rmse_deviation_m": float(obj.get("rmse_deviation_m", obj.get("root_mean_square_error_deviation_m", 0.0))),
        "source_length_m": float(obj.get("source_length_m", 0.0)),
        "torcs_length_m": float(obj.get("torcs_length_m", 0.0)),
        "report": str(report),
        "overlay": str(overlay),
    }


def resolve_overlay_script(args: argparse.Namespace) -> pathlib.Path:
    if args.overlay_script:
        overlay_script = pathlib.Path(args.overlay_script)
    else:
        overlay_script = pathlib.Path(__file__).resolve().parent / "compare_overlay.py"
    if not overlay_script.exists():
        raise RuntimeError(f"Overlay script not found: {overlay_script}")
    return overlay_script


def collect_trackgen_safety_metrics(xml_path: pathlib.Path, raw: str, out_text: str, args: argparse.Namespace) -> tuple[dict, dict]:
    runtime_dir, category, name = resolve_safety_runtime_context(xml_path, args)

    with trackgen_xml_lock(runtime_dir, category, name):
        xml_path.write_text(raw, encoding="utf-8")
        before_trackgen = run_trackgen_z(runtime_dir, category, name)

        xml_path.write_text(out_text, encoding="utf-8")
        after_trackgen = run_trackgen_z(runtime_dir, category, name)

    return {"trackgen": before_trackgen}, {"trackgen": after_trackgen}


def add_overlay_safety_metrics(
    xml_path: pathlib.Path,
    raw: str,
    out_text: str,
    args: argparse.Namespace,
    before_metrics: dict,
    after_metrics: dict,
) -> None:
    if not args.overlay_polyline:
        return

    polyline = pathlib.Path(args.overlay_polyline)
    if not polyline.exists():
        raise RuntimeError(f"Overlay polyline not found: {polyline}")
    overlay_script = resolve_overlay_script(args)
    with tempfile.TemporaryDirectory(prefix="pit-safety-") as td:
        tdir = pathlib.Path(td)
        xml_path.write_text(raw, encoding="utf-8")
        before_overlay = run_overlay_compare(overlay_script, polyline, xml_path, tdir, "before")
        xml_path.write_text(out_text, encoding="utf-8")
        after_overlay = run_overlay_compare(overlay_script, polyline, xml_path, tdir, "after")
    before_metrics["overlay"] = before_overlay
    after_metrics["overlay"] = after_overlay


def safety_gate_eval(before: dict, after: dict, args: argparse.Namespace) -> dict:
    gates = {
        "delta_ang_increase": abs(after["trackgen"]["delta_ang_deg"]) - abs(before["trackgen"]["delta_ang_deg"]),
        "delta_x_increase": abs(after["trackgen"]["delta_x"]) - abs(before["trackgen"]["delta_x"]),
        "delta_y_increase": abs(after["trackgen"]["delta_y"]) - abs(before["trackgen"]["delta_y"]),
        "final_delta_x": abs(after["trackgen"]["delta_x"]),
        "final_delta_y": abs(after["trackgen"]["delta_y"]),
        "final_delta_ang_deg": abs(after["trackgen"]["delta_ang_deg"]),
        "length_drift_ratio": abs(after["trackgen"]["length"] - before["trackgen"]["length"]) / max(1e-9, abs(before["trackgen"]["length"])),
    }
    checks = {
        "delta_ang_increase_ok": gates["delta_ang_increase"] <= args.max_delta_ang_deg_increase,
        "delta_x_increase_ok": gates["delta_x_increase"] <= args.max_delta_x_increase_m,
        "delta_y_increase_ok": gates["delta_y_increase"] <= args.max_delta_y_increase_m,
        "final_delta_x_ok": gates["final_delta_x"] <= args.max_final_delta_x_m,
        "final_delta_y_ok": gates["final_delta_y"] <= args.max_final_delta_y_m,
        "final_delta_ang_ok": gates["final_delta_ang_deg"] <= args.max_final_delta_ang_deg,
        "length_drift_ok": gates["length_drift_ratio"] <= args.max_length_drift_ratio,
    }
    if "overlay" in before and "overlay" in after:
        gates["rmse_increase"] = after["overlay"]["rmse_deviation_m"] - before["overlay"]["rmse_deviation_m"]
        gates["mean_deviation_increase"] = after["overlay"]["mean_deviation_m"] - before["overlay"]["mean_deviation_m"]
        checks["rmse_increase_ok"] = gates["rmse_increase"] <= args.max_rmse_increase_m
        checks["mean_deviation_increase_ok"] = gates["mean_deviation_increase"] <= args.max_mean_dev_increase_m
    checks["all_ok"] = all(checks.values())
    return {"gates": gates, "checks": checks}


def apply_safety_evaluation(report: dict, safety_result: dict, xml_path: pathlib.Path, raw: str, args: argparse.Namespace) -> bool:
    if not safety_result["checks"]["all_ok"]:
        msg = "Safety gates failed"
        report["safety"]["status"] = "failed"
        report["safety"]["reason"] = msg
        if not args.no_rollback_on_fail and not args.dry_run:
            xml_path.write_text(raw, encoding="utf-8")
            report["safety"]["rolled_back"] = True
            print("Safety gates failed; rolled back XML to baseline")
        else:
            report["safety"]["rolled_back"] = False
            print("Safety gates failed; keeping modified XML due to --no-rollback-on-fail")
        return True

    report["safety"]["status"] = "passed"
    report["safety"]["rolled_back"] = False
    print("Safety gates passed")
    return False


def run_enforced_safety(
    xml_path: pathlib.Path,
    raw: str,
    out_text: str,
    args: argparse.Namespace,
    report: dict,
) -> tuple[dict | None, dict | None, dict | None, bool]:
    before_metrics = None
    after_metrics = None
    safety_result = None
    try:
        before_metrics, after_metrics = collect_trackgen_safety_metrics(xml_path, raw, out_text, args)
        add_overlay_safety_metrics(xml_path, raw, out_text, args, before_metrics, after_metrics)
        safety_result = safety_gate_eval(before_metrics, after_metrics, args)
        report["safety"] = {
            "before": before_metrics,
            "after": after_metrics,
            "evaluation": safety_result,
        }
        safety_failed = apply_safety_evaluation(report, safety_result, xml_path, raw, args)
    except Exception as exc:
        report["safety"] = {
            "before": before_metrics,
            "after": after_metrics,
            "status": "failed",
            "reason": f"Safety check error: {exc}",
        }
        if not args.no_rollback_on_fail:
            xml_path.write_text(raw, encoding="utf-8")
            report["safety"]["rolled_back"] = True
            print("Safety check failed; rolled back XML to baseline")
        else:
            report["safety"]["rolled_back"] = False
            print("Safety check failed; keeping current XML due to --no-rollback-on-fail")
        raise
    return before_metrics, after_metrics, safety_result, safety_failed


def almost_pose_within_limits(pose_meta: dict, args: argparse.Namespace) -> bool:
    pose_error = pose_meta.get("pose_error", {})
    return (
        abs(float(pose_error.get("xy_m", 0.0))) <= args.max_almost_pose_error_m
        and abs(float(pose_error.get("ang_deg", 0.0))) <= args.max_almost_pose_error_deg
    )


def write_optional_reports(
    args: argparse.Namespace,
    report: dict,
    before_metrics: dict | None,
    after_metrics: dict | None,
    safety_result: dict | None,
) -> None:
    if args.report:
        rp = pathlib.Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote report: {rp}")

    if args.baseline_report and before_metrics is not None:
        bp = pathlib.Path(args.baseline_report)
        bp.parent.mkdir(parents=True, exist_ok=True)
        bp.write_text(json.dumps(before_metrics, indent=2), encoding="utf-8")
        print(f"Wrote baseline report: {bp}")

    if args.safety_report and safety_result is not None:
        sp = pathlib.Path(args.safety_report)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({"before": before_metrics, "after": after_metrics, "evaluation": safety_result}, indent=2), encoding="utf-8")
        print(f"Wrote safety report: {sp}")


def clean_auto_pit_segments(segs: list[ET.Element]) -> list[ET.Element]:
    return [s for s in segs if not any((s.get("name", "")).startswith(prefix) for prefix in AUTO_PIT_SEGMENT_PREFIXES)]


def load_track_context(xml_path: pathlib.Path) -> tuple[str, ET.ElementTree, ET.Element, ET.Element, ET.Element, ET.Element, list[ET.Element]]:
    raw, tree = parse_xml_preserve_entity(xml_path)
    root = tree.getroot()

    main_track = next((s for s in root.iter("section") if s.get("name") == "Main Track"), None)
    if main_track is None:
        raise SystemExit("Main Track section not found")

    pits = get_or_make_child_section(main_track, "Pits")
    track_segments = get_child_section(main_track, "Track Segments")
    if track_segments is None:
        raise SystemExit("Main Track/Track Segments section not found")

    segs = clean_auto_pit_segments([c for c in track_segments if c.tag == "section"])
    if not segs:
        raise SystemExit("No track segments found")
    return raw, tree, root, main_track, pits, track_segments, segs


def apply_manual_wrap_rotation(segs: list[ET.Element], args: argparse.Namespace, manual_host_requested: bool) -> tuple[list[ET.Element], dict | None]:
    if not (manual_host_requested and not args.host_segment and args.host_start_segment and args.host_end_segment):
        return segs, None

    start_idx = find_segment_index(segs, args.host_start_segment)
    end_idx = find_segment_index(segs, args.host_end_segment)
    host_touches_xml_boundary = end_idx < start_idx or start_idx == 0 or end_idx == len(segs) - 1
    if args.host_mode == "straighten" and len(segs) > 0 and host_touches_xml_boundary:
        connector_idx = previous_turn_index_skipping_straights(segs, start_idx)
        connector_name = segs[connector_idx].get("name", "")
        return rotate_segments_to_start(segs, connector_name), {
            "start_segment": args.host_start_segment,
            "end_segment": args.host_end_segment,
            "original_start_index": start_idx,
            "original_end_index": end_idx,
            "rotation_start_segment": connector_name,
            "rotation_reason": "straighten-connector",
        }
    if end_idx < start_idx:
        return rotate_segments_to_start(segs, args.host_start_segment), {
            "start_segment": args.host_start_segment,
            "end_segment": args.host_end_segment,
            "original_start_index": start_idx,
            "original_end_index": end_idx,
        }
    return segs, None


def select_host_strategy(
    segs: list[ET.Element],
    args: argparse.Namespace,
    manual_host_requested: bool,
    real_placement: dict | None,
    real_placement_source_total: float,
    real_placement_source_origin: float,
) -> dict:
    if manual_host_requested:
        return choose_manual_host_strategy(
            segs,
            host_segment=args.host_segment,
            host_start_segment=args.host_start_segment,
            host_end_segment=args.host_end_segment,
            pit_len=args.pit_main_length,
            mode_override=args.host_mode,
        )
    if real_placement is not None and real_placement.get("best_window") and real_placement_source_total > 0.0:
        best_window = real_placement["best_window"]
        return station_window_to_host_strategy(
            segs,
            source_start=float(best_window["start_station_m"]),
            source_end=float(best_window["end_station_m"]),
            source_total=real_placement_source_total,
            pit_len=args.pit_main_length,
            source_origin=real_placement_source_origin,
        )
    return choose_host_strategy(
        segs,
        pit_len=args.pit_main_length,
        almost_max_curv=args.almost_max_curvature,
        almost_max_seg_turn_deg=args.almost_max_seg_turn_deg,
        almost_max_chain_turn_deg=args.almost_max_chain_turn_deg,
        preserve_host_pose=args.preserve_host_pose,
        max_host_window_segs=args.max_host_window_segs,
        max_host_window_len_m=args.max_host_window_len_m,
        mode_override=args.host_mode,
    )


def apply_host_wrap_rotation(segs: list[ET.Element], host: dict) -> tuple[list[ET.Element], dict]:
    if not host.get("wrap"):
        return segs, host

    original_i0 = int(host["i0"])
    original_i1 = int(host["i1"])
    rotation_start = segs[original_i0].get("name", "")
    segs = rotate_segments_to_start(segs, rotation_start)
    host = dict(host)
    host["original_i0"] = original_i0
    host["original_i1"] = original_i1
    host["rotation_start_segment"] = rotation_start
    host["i0"] = 0
    host["i1"] = int(host.get("index_count", len(segs))) - 1
    host["wrap_rotation_applied"] = True
    return segs, host


def build_initial_report(
    xml_path: pathlib.Path,
    raw: str,
    pits: ET.Element,
    args: argparse.Namespace,
    host: dict,
    manual_wrap_rotation: dict | None,
    real_placement: dict | None,
) -> dict:
    report: dict = {"host_selection": host}
    if manual_wrap_rotation is not None:
        report["manual_wrap_rotation"] = manual_wrap_rotation
    if real_placement is not None:
        report["real_placement"] = real_placement
    if not args.no_pit_backup:
        backup = write_no_pit_backup(xml_path, raw, pits, args.dry_run)
        if backup:
            report["no_pit_backup"] = backup
    return report


def write_real_placement_report_only(args: argparse.Namespace, real_placement: dict) -> int:
    report = {"real_placement": real_placement}
    if args.report:
        rp = pathlib.Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote report: {rp}")
    print(f"Real pit placement: {real_placement['status']}")
    print(f"Projected span: {real_placement['projected_span_m']:.3f} m")
    print(f"Mainline turn: {real_placement['mainline_turn_deg']:.3f} deg")
    return 0 if real_placement["status"] == "real-placement-ok" else 1


def evaluate_real_placement(
    segs: list[ET.Element],
    args: argparse.Namespace,
    manual_host_requested: bool,
) -> tuple[dict | None, float, float, int | None]:
    if not args.pit_source or manual_host_requested:
        return None, 0.0, 0.0, None

    pit_source = pathlib.Path(args.pit_source)
    real_placement_source_total = 0.0
    real_placement_source_origin = 0.0
    if args.mainline_source:
        mainline_points = read_source_points(pathlib.Path(args.mainline_source))
        pit_points = read_source_points(pit_source)
        common_ref = mainline_points[0]
        mainline_xy = to_xy_points(mainline_points, common_ref)
        pit_xy = to_xy_points(pit_points, common_ref)
        _, real_placement_source_total = sample_polyline_centerline(mainline_xy, closed=True)
        real_placement_source_origin = source_origin_for_segments(mainline_points, segs)
    else:
        pit_xy = read_source_polyline(pit_source)
        mainline_xy = None

    real_placement = real_placement_feasibility(
        segs=segs,
        pit_xy=pit_xy,
        pit_main_length=args.pit_main_length,
        max_chain_turn_deg=args.real_max_chain_turn_deg,
        min_side_consistency=args.real_min_side_consistency,
        mainline_xy=mainline_xy,
    )
    real_placement["source"] = str(pit_source)
    if args.mainline_source:
        real_placement["mainline_source"] = args.mainline_source
    if args.real_placement_overlay:
        overlay_path = pathlib.Path(args.real_placement_overlay)
        overlay_mainline_xy = mainline_xy if mainline_xy is not None else samples_to_xy(sample_track_centerline(segs)[0])
        write_real_placement_overlay(overlay_path, overlay_mainline_xy, pit_xy, real_placement)
        real_placement["overlay"] = str(overlay_path)
    if args.real_placement_report_only:
        return real_placement, real_placement_source_total, real_placement_source_origin, write_real_placement_report_only(args, real_placement)

    if real_placement["status"] != "real-placement-ok":
        raise SystemExit(f"Real pit placement rejected: {real_placement['status']}")
    args.pit_side = str(real_placement["pit_side"])
    return real_placement, real_placement_source_total, real_placement_source_origin, None


def apply_straighten_host_mode(
    segs: list[ET.Element],
    args: argparse.Namespace,
    names_used: set[str],
    host: dict,
    report: dict,
) -> tuple[list[ET.Element], dict, str]:
    mode = host["mode"]
    if mode != "straighten":
        return segs, host, mode

    i0 = int(host["i0"])
    i1 = int(host["i1"])
    pre_idx, expanded_i0, expanded_i1, post_idx, scan_meta = straighten_connector_window(segs, i0, i1)
    straightened_pieces, straight_host_name, straighten_meta = fit_connector_straightening(
        pre_connector=segs[pre_idx],
        host_chain=segs[expanded_i0 : expanded_i1 + 1],
        post_connector=segs[post_idx],
        pit_len=args.pit_main_length,
        names_used=names_used,
    )
    straighten_meta.update(scan_meta)
    segs = segs[:pre_idx] + straightened_pieces + segs[post_idx + 1 :]
    i0 = pre_idx + 1
    host = {
        "mode": "exact",
        "i0": i0,
        "i1": i0,
        "length": segment_length(segs[i0]),
        "manual_host": True,
        "straightened_host": straight_host_name,
        "requested_i0": int(host["i0"]),
        "requested_i1": i1,
        "expanded_i0": expanded_i0,
        "expanded_i1": expanded_i1,
    }
    report["host_selection"] = host
    report["connector_straightening"] = straighten_meta
    return segs, host, "exact"


def apply_injected_host_mode(
    segs: list[ET.Element],
    args: argparse.Namespace,
    names_used: set[str],
    i0: int,
    i1: int,
    mode: str,
) -> tuple[list[ET.Element], int, int, str]:
    if mode != "inject":
        return segs, i0, i1, mode

    template = copy.deepcopy(segs[0])
    host_len = args.pit_main_length
    injected = clone_as_straight(template, unique_name(names_used, "pit_injected_host"), host_len)
    counter = clone_as_straight(template, unique_name(names_used, "pit_counter_straight"), host_len)
    insert_mid = len(segs) // 2
    segs = [injected] + segs
    segs = segs[:insert_mid] + [counter] + segs[insert_mid:]
    return segs, 0, 0, "inject"


def apply_lengthen_host_mode(segs: list[ET.Element], args: argparse.Namespace, i0: int, mode: str, report: dict) -> None:
    if mode != "lengthen":
        return

    host_seg = segs[i0]
    old_len = segment_length(host_seg)
    need = max(0.0, args.pit_main_length - old_len)
    set_attnum(host_seg, "lg", old_len + need, "m")
    report["lengthen"] = {"segment": host_seg.get("name", ""), "old_len": old_len, "new_len": old_len + need}

    # Counter-adjust by extending an opposite-heading straight when possible.
    headings = []
    h = 0.0
    for s in segs:
        headings.append(h)
        h += math.radians(segment_heading_delta_deg(s))
    host_h = headings[i0]
    best_j = -1
    best_score = -1.0
    for j, s in enumerate(segs):
        if j == i0 or get_attstr(s, "type") != "str":
            continue
        d = abs((headings[j] - host_h + math.pi) % (2.0 * math.pi) - math.pi)
        align = 1.0 - min(abs(d - math.pi) / math.pi, 1.0)
        score = align * max(1.0, segment_length(s))
        if score > best_score:
            best_score = score
            best_j = j
    if need > 0.0 and best_j >= 0:
        s = segs[best_j]
        set_attnum(s, "lg", segment_length(s) + need, "m")
        report["counter_adjust"] = {"segment": s.get("name", ""), "delta_len": need}


def replace_host_with_pit_main(
    segs: list[ET.Element],
    args: argparse.Namespace,
    names_used: set[str],
    i0: int,
    i1: int,
    mode: str,
    report: dict,
) -> tuple[list[ET.Element], str, str]:
    if mode in ("exact", "lengthen"):
        return replace_exact_host_with_pit_main(segs, args, names_used, i0)

    return replace_chain_host_with_pit_main(segs, args, names_used, i0, i1, mode, report)


def replace_exact_host_with_pit_main(
    segs: list[ET.Element],
    args: argparse.Namespace,
    names_used: set[str],
    i0: int,
) -> tuple[list[ET.Element], str, str]:
    host_seg = segs[i0]
    host_len = segment_length(host_seg)
    pieces, pit_a_name, pit_b_name = split_host_to_pit_segments(
        template=host_seg,
        host_len=host_len,
        pit_len=args.pit_main_length,
        min_piece_len=args.min_piece_len,
        names_used=names_used,
        align=args.pit_main_align,
    )
    return segs[:i0] + pieces + segs[i0 + 1 :], pit_a_name, pit_b_name


def replace_chain_host_with_pit_main(
    segs: list[ET.Element],
    args: argparse.Namespace,
    names_used: set[str],
    i0: int,
    i1: int,
    mode: str,
    report: dict,
) -> tuple[list[ET.Element], str, str]:
    chain = segs[i0 : i1 + 1]
    if mode == "almost" and args.preserve_host_pose:
        if args.pit_main_align != "center":
            raise SystemExit("--pit-main-align is only supported for exact, lengthen, straighten, or non-pose-preserving almost hosts")
        pieces, pit_a_name, pit_b_name, pose_meta = make_pose_preserving_almost_replacement(
            chain=chain,
            pit_len=args.pit_main_length,
            min_piece_len=args.min_piece_len,
            names_used=names_used,
        )
        report["almost_pose_preserving"] = pose_meta
        if not almost_pose_within_limits(pose_meta, args):
            pose_error = pose_meta["pose_error"]
            raise SystemExit(
                "Almost-straight pit host replacement is not pose-exact enough: "
                f"xy={pose_error['xy_m']:.6f} m, ang={pose_error['ang_deg']:.6f} deg"
            )
    else:
        host_len = sum(segment_length(s) for s in chain)
        template = next((s for s in chain if get_attstr(s, "type") == "str"), chain[0])
        pieces, pit_a_name, pit_b_name = split_host_to_pit_segments(
            template=template,
            host_len=host_len,
            pit_len=args.pit_main_length,
            min_piece_len=args.min_piece_len,
            names_used=names_used,
            align=args.pit_main_align,
        )
    return segs[:i0] + pieces + segs[i1 + 1 :], pit_a_name, pit_b_name


def locate_pit_main_indices(segs: list[ET.Element], pit_a_name: str, pit_b_name: str) -> tuple[int, int, set[int]]:
    pit_a_idx = next(i for i, s in enumerate(segs) if s.get("name") == pit_a_name)
    pit_b_idx = next(i for i, s in enumerate(segs) if s.get("name") == pit_b_name)
    return pit_a_idx, pit_b_idx, {pit_a_idx, pit_b_idx}


def pit_neighbor_lengths(segs: list[ET.Element], lengths: list[float], pit_a_idx: int, pit_b_idx: int) -> tuple[float, float]:
    pre_host_idx = (pit_a_idx - 1) % len(segs)
    post_host_idx = (pit_b_idx + 1) % len(segs)
    pit_host_pre_length = lengths[pre_host_idx] if segs[pre_host_idx].get("name", "").startswith("pit_host_pre") else 0.0
    pit_host_post_length = lengths[post_host_idx] if segs[post_host_idx].get("name", "").startswith("pit_host_post") else 0.0
    return pit_host_pre_length, pit_host_post_length


def resolve_taper_targets(args: argparse.Namespace, pit_host_pre_length: float, pit_host_post_length: float) -> tuple[float, float, bool, bool]:
    entry_taper_target_length = args.entry_taper_length
    exit_taper_target_length = args.exit_taper_length
    entry_taper_auto_limited = False
    exit_taper_auto_limited = False
    if args.pit_main_align == "end" and not args.entry_taper_length_explicit:
        entry_taper_target_length = pit_host_pre_length
        entry_taper_auto_limited = True
    if args.pit_main_align == "start" and not args.exit_taper_length_explicit:
        exit_taper_target_length = pit_host_post_length
        exit_taper_auto_limited = True
    return entry_taper_target_length, exit_taper_target_length, entry_taper_auto_limited, exit_taper_auto_limited


def apply_entry_taper(
    main_track: ET.Element,
    segs: list[ET.Element],
    lengths: list[float],
    pit_a_idx: int,
    pit_b_idx: int,
    pit_main_idxs: set[int],
    right_or_left: str,
    target_length: float,
    target_width: float,
) -> tuple[list[int], str, str, float]:
    entry_idxs = ordered_taper_indices_backward(lengths, pit_a_idx, target_length, {pit_b_idx})
    main_side_section = get_child_section(main_track, f"{right_or_left} Side")
    base_side_width = get_attnum(main_side_section if main_side_section is not None else main_track, "width", 7.0)
    entry_start_name, entry_end_name = apply_side_width_profile(
        segs,
        entry_idxs,
        f"{right_or_left} Side",
        base_side_width,
        target_width,
        target_length,
        "manual-asphalt",
    )
    for idx in entry_idxs:
        apply_border_style(segs[idx], f"{right_or_left} Border", NORMAL_BORDER_STYLE, PIT_TRANSITION_BORDER_SURFACE, NORMAL_BORDER_WIDTH)
    if entry_idxs and (entry_idxs[0] - 1) % len(segs) not in pit_main_idxs:
        reset_normal_side_state(segs[(entry_idxs[0] - 1) % len(segs)], f"{right_or_left} Side", f"{right_or_left} Border", base_side_width)
    return entry_idxs, entry_start_name, entry_end_name, base_side_width


def apply_pit_main_materials(
    segs: list[ET.Element],
    pit_a_idx: int,
    pit_b_idx: int,
    right_or_left: str,
    opposite: str,
    args: argparse.Namespace,
) -> None:
    for idx in (pit_a_idx, pit_b_idx):
        side = get_or_make_child_section(segs[idx], f"{right_or_left} Side")
        set_attstr(side, "surface", "road1-pits")
        set_attnum(side, "start width", args.pit_side_width, "m")
        set_attnum(side, "end width", args.pit_side_width, "m")

        wall_border = get_or_make_child_section(segs[idx], f"{right_or_left} Border")
        set_attstr(wall_border, "style", "wall")
        set_attstr(wall_border, "surface", "wall")
        set_attnum(wall_border, "width", 0.5, "m")
        set_attnum(wall_border, "height", 1.0, "m")

        inner_border = get_or_make_child_section(segs[idx], f"{opposite} Border")
        set_attstr(inner_border, "style", NORMAL_BORDER_STYLE)
        set_attstr(inner_border, "surface", NORMAL_BORDER_SURFACE)
        set_attnum(inner_border, "width", NORMAL_BORDER_WIDTH, "m")
        remove_attnum(inner_border, "height")
    reset_normal_border_state(segs[(pit_a_idx - 1) % len(segs)], f"{opposite} Border")
    reset_normal_border_state(segs[(pit_b_idx + 1) % len(segs)], f"{opposite} Border")


def apply_exit_taper(
    segs: list[ET.Element],
    lengths: list[float],
    pit_a_idx: int,
    pit_b_idx: int,
    pit_main_idxs: set[int],
    right_or_left: str,
    target_length: float,
    start_width: float,
    end_width: float,
) -> tuple[list[int], str, str]:
    exit_idxs = ordered_taper_indices_forward(lengths, pit_b_idx, target_length, {pit_a_idx})
    exit_start_name, exit_end_name = apply_side_width_profile(
        segs,
        exit_idxs,
        f"{right_or_left} Side",
        start_width,
        end_width,
        target_length,
        "manual-asphalt",
    )
    for idx in exit_idxs:
        apply_border_style(segs[idx], f"{right_or_left} Border", NORMAL_BORDER_STYLE, PIT_TRANSITION_BORDER_SURFACE, NORMAL_BORDER_WIDTH)
    if exit_idxs and (exit_idxs[-1] + 1) % len(segs) not in pit_main_idxs:
        reset_normal_side_state(segs[(exit_idxs[-1] + 1) % len(segs)], f"{right_or_left} Side", f"{right_or_left} Border", end_width)
    return exit_idxs, exit_start_name, exit_end_name


def configure_pit_section(
    pits: ET.Element,
    args: argparse.Namespace,
    pit_a_name: str,
    pit_b_name: str,
    entry_start_name: str,
    entry_end_name: str,
    exit_start_name: str,
    exit_end_name: str,
) -> int:
    set_attstr(pits, "type", "track side")
    set_attstr(pits, "side", args.pit_side)
    set_attstr(pits, "entry", entry_start_name or entry_end_name or pit_a_name)
    set_attstr(pits, "start", pit_a_name)
    set_attstr(pits, "end", pit_b_name)
    set_attstr(pits, "exit", exit_end_name or exit_start_name or pit_b_name)
    set_attnum(pits, "speed limit", args.speed_limit, "km/h")
    set_attnum(pits, "length", args.pit_slot_length, "m")
    set_attnum(pits, "width", 5.0, "m")
    return int(round(args.pit_main_length / max(1e-6, args.pit_slot_length)))


def build_pit_report(
    args: argparse.Namespace,
    pit_a_name: str,
    pit_b_name: str,
    pit_host_pre_length: float,
    pit_host_post_length: float,
    entry_taper_target_length: float,
    exit_taper_target_length: float,
    entry_taper_auto_limited: bool,
    exit_taper_auto_limited: bool,
    entry_selected_length: float,
    exit_selected_length: float,
    pit_count: int,
    pits: ET.Element,
) -> dict:
    return {
        "pit_main_a": pit_a_name,
        "pit_main_b": pit_b_name,
        "pit_main_length": args.pit_main_length,
        "pit_main_align": args.pit_main_align,
        "pit_slot_length": args.pit_slot_length,
        "pit_host_pre_length_m": pit_host_pre_length,
        "pit_host_post_length_m": pit_host_post_length,
        "entry_taper_requested_length_m": args.entry_taper_length,
        "entry_taper_target_length_m": entry_taper_target_length,
        "entry_taper_selected_length_m": entry_selected_length,
        "entry_taper_auto_limited": entry_taper_auto_limited,
        "exit_taper_requested_length_m": args.exit_taper_length,
        "exit_taper_target_length_m": exit_taper_target_length,
        "exit_taper_selected_length_m": exit_selected_length,
        "exit_taper_auto_limited": exit_taper_auto_limited,
        "expected_pits": pit_count,
        "entry_segment": get_attstr(pits, "entry"),
        "start_segment": get_attstr(pits, "start"),
        "end_segment": get_attstr(pits, "end"),
        "exit_segment": get_attstr(pits, "exit"),
    }


def apply_pit_lane_styles(
    main_track: ET.Element,
    pits: ET.Element,
    segs: list[ET.Element],
    args: argparse.Namespace,
    pit_a_name: str,
    pit_b_name: str,
) -> tuple[list[ET.Element], dict, int]:
    pit_a_idx, pit_b_idx, pit_main_idxs = locate_pit_main_indices(segs, pit_a_name, pit_b_name)
    lengths = [segment_length(s) for s in segs]
    pit_host_pre_length, pit_host_post_length = pit_neighbor_lengths(segs, lengths, pit_a_idx, pit_b_idx)
    entry_taper_target_length, exit_taper_target_length, entry_taper_auto_limited, exit_taper_auto_limited = resolve_taper_targets(
        args,
        pit_host_pre_length,
        pit_host_post_length,
    )
    right_or_left = "Right" if args.pit_side == "right" else "Left"
    opposite = "Left" if args.pit_side == "right" else "Right"

    entry_idxs, entry_start_name, entry_end_name, base_side_width = apply_entry_taper(
        main_track,
        segs,
        lengths,
        pit_a_idx,
        pit_b_idx,
        pit_main_idxs,
        right_or_left,
        entry_taper_target_length,
        args.entry_exit_side_width,
    )
    apply_pit_main_materials(segs, pit_a_idx, pit_b_idx, right_or_left, opposite, args)
    exit_idxs, exit_start_name, exit_end_name = apply_exit_taper(
        segs,
        lengths,
        pit_a_idx,
        pit_b_idx,
        pit_main_idxs,
        right_or_left,
        exit_taper_target_length,
        args.entry_exit_side_width,
        base_side_width,
    )

    segs = rotate_segments_to_start(segs, pit_b_name)
    pit_count = configure_pit_section(pits, args, pit_a_name, pit_b_name, entry_start_name, entry_end_name, exit_start_name, exit_end_name)
    pit_report = build_pit_report(
        args,
        pit_a_name,
        pit_b_name,
        pit_host_pre_length,
        pit_host_post_length,
        entry_taper_target_length,
        exit_taper_target_length,
        entry_taper_auto_limited,
        exit_taper_auto_limited,
        sum(lengths[idx] for idx in entry_idxs),
        sum(lengths[idx] for idx in exit_idxs),
        pit_count,
        pits,
    )
    return segs, pit_report, pit_count


def rewrite_track_segments(track_segments: ET.Element, segs: list[ET.Element]) -> None:
    for child in list(track_segments):
        if child.tag == "section":
            track_segments.remove(child)
    for seg in segs:
        track_segments.append(seg)


def main() -> int:
    args = parse_args()
    xml_path = pathlib.Path(args.track_xml)
    raw, tree, root, main_track, pits, track_segments, segs = load_track_context(xml_path)

    manual_host_requested = bool(args.host_segment or args.host_start_segment or args.host_end_segment)
    if manual_host_requested and args.real_placement_report_only:
        raise SystemExit("--real-placement-report-only cannot be used with manual host selection")

    real_placement, real_placement_source_total, real_placement_source_origin, real_placement_exit = evaluate_real_placement(
        segs,
        args,
        manual_host_requested,
    )
    if real_placement_exit is not None:
        return real_placement_exit

    segs, manual_wrap_rotation = apply_manual_wrap_rotation(segs, args, manual_host_requested)
    host = select_host_strategy(segs, args, manual_host_requested, real_placement, real_placement_source_total, real_placement_source_origin)
    segs, host = apply_host_wrap_rotation(segs, host)

    names_used = {s.get("name", "") for s in segs}

    report = build_initial_report(xml_path, raw, pits, args, host, manual_wrap_rotation, real_placement)

    i0 = int(host["i0"])
    i1 = int(host["i1"])
    segs, host, mode = apply_straighten_host_mode(segs, args, names_used, host, report)
    i0 = int(host["i0"])
    i1 = int(host["i1"])
    segs, i0, i1, mode = apply_injected_host_mode(segs, args, names_used, i0, i1, mode)
    apply_lengthen_host_mode(segs, args, i0, mode, report)
    segs, pit_a_name, pit_b_name = replace_host_with_pit_main(segs, args, names_used, i0, i1, mode, report)

    segs, pit_report, pit_count = apply_pit_lane_styles(main_track, pits, segs, args, pit_a_name, pit_b_name)
    rewrite_track_segments(track_segments, segs)
    from torcs_track_tools.core.track_georeference import fit_reference, remove_reference, set_reference

    remove_reference(root)
    if args.mainline_source:
        try:
            geo, _ = fit_reference(ET.tostring(root, encoding="unicode"), json.loads(pathlib.Path(args.mainline_source).read_text(encoding="utf-8-sig")))
            set_reference(root, geo)
        except ValueError as error:
            print(f"Georeference unavailable after pit start rotation: {error}")
    normalize_manual_surfaces(root)
    report["pit"] = pit_report

    # Optional safety checks and rollback gate.
    safety_result = None
    before_metrics = None
    after_metrics = None
    safety_failed = False

    out_text = serialize_xml_restore_entity(raw, tree)

    if args.dry_run:
        print("Dry run: no XML written")
    else:
        xml_path.write_text(out_text, encoding="utf-8")
        print(f"Wrote XML: {xml_path}")

    if args.enforce_safety and not args.dry_run:
        before_metrics, after_metrics, safety_result, safety_failed = run_enforced_safety(xml_path, raw, out_text, args, report)
    elif args.enforce_safety and args.dry_run:
        report["safety"] = {"status": "skipped", "reason": "dry-run"}

    write_optional_reports(args, report, before_metrics, after_metrics, safety_result)

    print(f"Host mode: {report['host_selection']['mode']}")
    print(f"Expected pits: {pit_count}")
    print(f"Pit start/end: {get_attstr(pits, 'start')} / {get_attstr(pits, 'end')}")
    if safety_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
