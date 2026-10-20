#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : render_labeled_segments_svg.py
#     created              : 09 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Render a TORCS XML centerline with segment labels for review discussions."""

from __future__ import annotations

import argparse
import collections
import math
import pathlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from torcs_track_tools.core.geometry import Pose, Segment, sample_segment, segment_length_like
from torcs_track_tools.core.track_xml import child_section, get_attstr, parse_xml_preserve_prolog, segment_from_element, segment_sections


@dataclass
class RenderedSegment:
    index: int
    segment: Segment
    display_label: str
    points: list[tuple[float, float]]
    midpoint: tuple[float, float]
    has_curb: bool
    turn_deg: float


def positive_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a labeled SVG from TORCS track XML segments")
    parser.add_argument("--track-xml", required=True, help="Input TORCS track XML")
    parser.add_argument("--output", required=True, help="Output SVG path")
    parser.add_argument("--title", default="", help="Optional title text shown in the SVG")
    parser.add_argument("--sample-step", type=float, default=5.0, help="Polyline sample step in meters")
    parser.add_argument("--width", type=float, default=1800.0, help="Maximum SVG width")
    parser.add_argument("--height", type=float, default=1300.0, help="Maximum SVG height")
    parser.add_argument(
        "--label-mode",
        choices=["auto", "index", "name"],
        default="auto",
        help="Label style: trailing source number when available, 1-based index, or full XML segment name",
    )
    parser.add_argument("--label-font-size", type=positive_finite_float, default=5.0, help="Segment label font size in SVG pixels")
    parser.add_argument("--zoom-labels", default="", help="Optional auto-mode source labels or index-mode indices, for example 27-38,80")
    parser.add_argument("--no-curb-markers", action="store_true", help="Do not draw magenta rings around direct curb segments")
    return parser.parse_args()


def parse_label_filter(value: str) -> set[int] | None:
    if not value.strip():
        return None
    out: set[int] = set()
    for item in value.split(","):
        part = item.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start = int(left.strip())
            end = int(right.strip())
            lo, hi = sorted((start, end))
            out.update(range(lo, hi + 1))
        else:
            out.add(int(part))
    return out


def split_suffix(name: str) -> tuple[str, str]:
    for suffix, short in (("-pre", "p"), ("-curb", "c"), ("-post", "o")):
        if name.endswith(suffix):
            return name[: -len(suffix)], short
    return name, ""


def numbered_name(name: str) -> tuple[str, int] | None:
    base, _suffix = split_suffix(name)
    match = re.fullmatch(r"(.+)-(\d+)", base)
    return (match.group(1), int(match.group(2))) if match else None


def source_name_prefix(names: list[str]) -> str | None:
    counts = collections.Counter(numbered[0] for name in names if (numbered := numbered_name(name)) is not None)
    if not counts:
        return None
    ranked = counts.most_common(2)
    prefix, count = ranked[0]
    if len(ranked) > 1 and ranked[1][1] == count:
        return None
    return prefix if count >= 2 else None


def trailing_number(name: str, source_prefix: str | None) -> int | None:
    base, _suffix = split_suffix(name)
    numbered = numbered_name(name)
    if numbered is not None and numbered[0] == source_prefix:
        return numbered[1]
    if source_prefix is not None and base == source_prefix:
        return 0
    return None


def compact_xml_name(name: str, max_len: int = 42) -> str:
    base, suffix = split_suffix(name)
    label = f"{base}:{suffix}" if suffix else base
    if len(label) <= max_len:
        return label
    keep_tail = max(8, min(18, max_len // 3))
    keep_head = max(8, max_len - keep_tail - 1)
    return f"{label[:keep_head]}~{label[-keep_tail:]}"


def display_label(name: str, index: int, mode: str, source_prefix: str | None = None) -> str:
    if mode == "index":
        return str(index + 1)
    if mode == "name":
        return name
    number = trailing_number(name, source_prefix)
    if number is None:
        return compact_xml_name(name)
    _base, suffix = split_suffix(name)
    return f"{number}:{suffix}" if suffix else str(number)


def disambiguate_auto_labels(rendered: list[RenderedSegment]) -> None:
    counts = collections.Counter(item.display_label for item in rendered)
    for item in rendered:
        if counts[item.display_label] > 1:
            item.display_label = compact_xml_name(item.segment.name)
    fallback_counts = collections.Counter(item.display_label for item in rendered)
    reserved = {label for label, count in fallback_counts.items() if count == 1}
    for item in rendered:
        if fallback_counts[item.display_label] > 1:
            base = f"{item.display_label}#{item.index + 1}"
            candidate = base
            suffix = 2
            while candidate in reserved:
                candidate = f"{base}.{suffix}"
                suffix += 1
            item.display_label = candidate
            reserved.add(candidate)


def direct_curb(seg: ET.Element) -> bool:
    for border_name in ("Left Border", "Right Border"):
        border = child_section(seg, border_name)
        if border is not None and get_attstr(border, "style", "").lower() == "curb":
            return True
    return False


def midpoint(points: list[tuple[float, float]]) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    if len(points) == 1:
        return points[0]
    lengths = [0.0]
    for idx in range(1, len(points)):
        lengths.append(lengths[-1] + math.hypot(points[idx][0] - points[idx - 1][0], points[idx][1] - points[idx - 1][1]))
    half = lengths[-1] * 0.5
    idx = 1
    while idx < len(lengths) and lengths[idx] < half:
        idx += 1
    if idx >= len(points):
        return points[-1]
    span = max(1e-12, lengths[idx] - lengths[idx - 1])
    t = (half - lengths[idx - 1]) / span
    return points[idx - 1][0] + (points[idx][0] - points[idx - 1][0]) * t, points[idx - 1][1] + (points[idx][1] - points[idx - 1][1]) * t


def render_segments(root: ET.Element, sample_step: float, label_mode: str) -> list[RenderedSegment]:
    _main_track, seg_elements = segment_sections(root)
    source_prefix = source_name_prefix([element.get("name", "") for element in seg_elements])
    pose = Pose(0.0, 0.0, 0.0)
    station = 0.0
    rendered: list[RenderedSegment] = []
    for index, seg_element in enumerate(seg_elements):
        segment = segment_from_element(seg_element)
        if segment is None:
            continue
        start = pose
        pose, samples = sample_segment(pose, segment, station, sample_step)
        if samples:
            station = samples[-1].s
        points = [(start.x, start.y), *[(sample.x, sample.y) for sample in samples]]
        if len(points) == 1:
            points.append((pose.x, pose.y))
        turn = 0.0
        if segment.kind == "lft":
            turn = segment.arc_deg
        elif segment.kind == "rgt":
            turn = -segment.arc_deg
        rendered.append(
            RenderedSegment(
                index=index,
                segment=segment,
                display_label=display_label(segment.name, index, label_mode, source_prefix),
                points=points,
                midpoint=midpoint(points),
                has_curb=direct_curb(seg_element),
                turn_deg=turn,
            )
        )
    if label_mode == "auto":
        disambiguate_auto_labels(rendered)
    return rendered


def label_number_for_segment(rendered: RenderedSegment) -> int | None:
    match = re.fullmatch(r"(\d+)(?::[pco])?", rendered.display_label)
    return int(match.group(1)) if match else None


def filter_segments(rendered: list[RenderedSegment], labels: set[int] | None) -> list[RenderedSegment]:
    if labels is None:
        return rendered
    selected = [seg for seg in rendered if label_number_for_segment(seg) in labels]
    if not selected:
        raise SystemExit(f"No segments matched --zoom-labels {sorted(labels)}")
    return selected


def svg_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def legend_height(curb_markers: bool) -> float:
    return 186.0 if curb_markers else 166.0


def append_legend(lines: list[str], curb_markers: bool, label_mode: str) -> None:
    x = 24.0
    y = 54.0
    row = 20.0
    height = legend_height(curb_markers)
    lines.extend(
        [
            f'<g id="legend" transform="translate({x:.1f},{y:.1f})">',
            f'<rect x="0" y="0" width="472" height="{height:.0f}" rx="8" fill="#020617" fill-opacity="0.82" stroke="#334155"/>',
            '<text x="14" y="24" class="legend-title">Legend</text>',
            '<line x1="16" y1="45" x2="62" y2="45" stroke="#38bdf8" stroke-width="5" stroke-linecap="round"/>',
            '<text x="76" y="50" class="legend-text">straight segment</text>',
            f'<line x1="16" y1="{45 + row:.0f}" x2="62" y2="{45 + row:.0f}" stroke="#22c55e" stroke-width="5" stroke-linecap="round"/>',
            f'<text x="76" y="{50 + row:.0f}" class="legend-text">left turn segment</text>',
            f'<line x1="16" y1="{45 + row * 2:.0f}" x2="62" y2="{45 + row * 2:.0f}" stroke="#f97316" stroke-width="5" stroke-linecap="round"/>',
            f'<text x="76" y="{50 + row * 2:.0f}" class="legend-text">right turn segment</text>',
            f'<circle cx="39" cy="{45 + row * 3:.0f}" r="8" fill="#ef4444"/>',
            f'<text x="76" y="{50 + row * 3:.0f}" class="legend-text">start line / segment 1</text>',
        ]
    )
    suffix_y = 50.0 + row * 4.0
    if curb_markers:
        lines.extend(
            [
                f'<circle cx="39" cy="{45 + row * 4:.0f}" r="10" fill="none" stroke="#f0abfc" stroke-width="3"/>',
                f'<text x="76" y="{50 + row * 4:.0f}" class="legend-text">magenta ring = direct curb</text>',
            ]
        )
        suffix_y += row
    if label_mode == "auto":
        lines.extend(
            [
                f'<text x="14" y="{suffix_y:.0f}" class="legend-text">Labels: source numbers when available; compact names otherwise</text>',
                f'<text x="14" y="{suffix_y + row:.0f}" class="legend-text">Label suffixes: :p pre, :c curb, :o post</text>',
            ]
        )
    elif label_mode == "index":
        lines.append(f'<text x="14" y="{suffix_y:.0f}" class="legend-text">Labels: 1-based XML segment indices</text>')
    else:
        lines.append(f'<text x="14" y="{suffix_y:.0f}" class="legend-text">Labels: full XML segment names</text>')
    lines.append("</g>")


def write_svg(
    path: pathlib.Path,
    rendered: list[RenderedSegment],
    title: str,
    width: float,
    height: float,
    curb_markers: bool,
    label_font_size: float,
    label_mode: str,
) -> None:
    all_points = [point for seg in rendered for point in seg.points]
    if not all_points:
        raise SystemExit("No drawable segments found")
    min_x = min(point[0] for point in all_points)
    max_x = max(point[0] for point in all_points)
    min_y = min(point[1] for point in all_points)
    max_y = max(point[1] for point in all_points)
    left_pad = 55.0
    right_pad = 55.0
    bottom_pad = 55.0
    top_pad = 54.0 + legend_height(curb_markers) + 46.0
    track_w = max(1.0, max_x - min_x)
    track_h = max(1.0, max_y - min_y)
    scale = min((width - left_pad - right_pad) / track_w, max(1.0, height - top_pad - bottom_pad) / track_h)
    out_w = int(track_w * scale + left_pad + right_pad)
    out_h = int(track_h * scale + top_pad + bottom_pad)

    def map_point(point: tuple[float, float]) -> tuple[float, float]:
        return left_pad + (point[0] - min_x) * scale, top_pad + (max_y - point[1]) * scale

    def polyline(points: list[tuple[float, float]]) -> str:
        return " ".join(f"{map_point(point)[0]:.2f},{map_point(point)[1]:.2f}" for point in points)

    colors = {"str": "#38bdf8", "lft": "#22c55e", "rgt": "#f97316"}
    default_heading = "TORCS segment labels: blue=str, green=lft, orange=rgt"
    if curb_markers:
        default_heading += ", magenta rings=direct curb segments"
    heading = title or default_heading
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{out_w}" height="{out_h}" viewBox="0 0 {out_w} {out_h}">',
        '<rect width="100%" height="100%" fill="#111827"/>',
        f'<style><![CDATA[text {{ font-family: Consolas, monospace; }} .lbl {{ paint-order: stroke; stroke: #111827; stroke-width: {max(0.75, label_font_size * 0.3):.2f}px; stroke-linejoin: round; font-size: {label_font_size:.2f}px; font-weight: 700; }} .note {{ fill: #e5e7eb; font-size: 17px; }} .legend-title {{ fill: #f8fafc; font-size: 14px; font-weight: 700; }} .legend-text {{ fill: #e5e7eb; font-size: 12px; }}]]></style>',
        f'<text x="24" y="32" class="note">{svg_escape(heading)}</text>',
    ]
    append_legend(lines, curb_markers, label_mode)
    for item in rendered:
        color = colors.get(item.segment.kind, "#e5e7eb")
        title_text = f"{item.segment.name} type={item.segment.kind} length={segment_length_like(item.segment):.2f}m turn={item.turn_deg:.3f}deg curb={item.has_curb}"
        lines.append(
            f'<polyline points="{polyline(item.points)}" fill="none" stroke="{color}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"><title>{svg_escape(title_text)}</title></polyline>'
        )
    for item in rendered:
        color = colors.get(item.segment.kind, "#e5e7eb")
        x, y = map_point(item.midpoint)
        if curb_markers and item.has_curb:
            lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="12" fill="none" stroke="#f0abfc" stroke-width="3"/>')
        label_offset = max(2.0, label_font_size * 0.65)
        lines.append(f'<text class="lbl" x="{x + label_offset:.2f}" y="{y - label_offset:.2f}" fill="{color}">{svg_escape(item.display_label)}</text>')
    if rendered and rendered[0].index == 0:
        sx, sy = map_point(rendered[0].points[0])
        lines.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="9" fill="#ef4444"><title>start</title></circle>')
    lines.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.label_mode == "name" and args.zoom_labels.strip():
        raise SystemExit("--zoom-labels is not available with --label-mode name; use auto or index labels")
    _prolog, tree = parse_xml_preserve_prolog(pathlib.Path(args.track_xml))
    root = tree.getroot()
    if root is None:
        raise SystemExit("Track XML has no root element")
    rendered = render_segments(root, max(0.5, args.sample_step), args.label_mode)
    filtered = filter_segments(rendered, parse_label_filter(args.zoom_labels))
    write_svg(
        pathlib.Path(args.output),
        filtered,
        args.title,
        args.width,
        args.height,
        not args.no_curb_markers,
        args.label_font_size,
        args.label_mode,
    )
    print(f"Wrote labeled SVG: {args.output}")
    print(f"Segments rendered: {len(filtered)} of {len(rendered)}")
    print(f"Direct curb segments marked: {sum(1 for seg in filtered if seg.has_curb)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
