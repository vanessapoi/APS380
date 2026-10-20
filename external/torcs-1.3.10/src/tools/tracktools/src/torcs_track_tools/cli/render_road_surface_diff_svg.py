#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : render_road_surface_diff_svg.py
#     created              : 22 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Render profile-only TORCS road-surface diagnostics."""

from __future__ import annotations

import argparse
import html
import json
import math
import pathlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from torcs_track_tools.cli import apply_elevation
from torcs_track_tools.cli.render_elevation_diff_svg import build_mapper, color_for_diff, polyline_points
from torcs_track_tools.core.geometry import Pose, Sample, Segment, sample_segment
from torcs_track_tools.core.track_xml import (
    find_att,
    get_attnum,
    parse_xml_preserve_prolog,
    segment_from_element,
    segment_length,
    segment_sections,
)


@dataclass(frozen=True)
class SurfaceSample:
    station: float
    segment: str
    x: float
    y: float
    heading: float
    width: float
    track_center_z: float
    track_left_z: float
    track_right_z: float
    track_banking_deg: float
    profile_center_z: float | None
    profile_left_z: float | None
    profile_right_z: float | None
    profile_banking_deg: float | None

    @property
    def center_diff(self) -> float | None:
        return None if self.profile_center_z is None else self.track_center_z - self.profile_center_z

    @property
    def left_diff(self) -> float | None:
        return None if self.profile_left_z is None else self.track_left_z - self.profile_left_z

    @property
    def right_diff(self) -> float | None:
        return None if self.profile_right_z is None else self.track_right_z - self.profile_right_z

    @property
    def banking_diff(self) -> float | None:
        return None if self.profile_banking_deg is None else self.track_banking_deg - self.profile_banking_deg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render TORCS road surface vs road-surface-profile diagnostics")
    parser.add_argument("--track-xml", required=True, help="TORCS track XML with applied elevation/banking")
    parser.add_argument("--profile", required=True, help="Road-surface profile JSON")
    parser.add_argument("--output", required=True, help="Output SVG path")
    parser.add_argument("--report", default="", help="Optional JSON report path")
    parser.add_argument("--sample-step", type=float, default=10.0, help="Track sampling spacing in meters")
    parser.add_argument("--color-mode", choices=("auto", "center", "left", "right", "bank"), default="auto", help="Channel used to color the plan-view samples")
    parser.add_argument("--color-range", type=float, default=2.0, help="Absolute height difference in meters that reaches full red/blue")
    parser.add_argument("--bank-color-range", type=float, default=5.0, help="Absolute banking difference in degrees that reaches full red/blue")
    parser.add_argument("--label-top", type=int, default=10, help="Label this many largest absolute differences")
    parser.add_argument("--width", type=float, default=1600.0, help="SVG viewport width in pixels")
    parser.add_argument("--pad", type=float, default=50.0, help="SVG viewport padding in pixels")
    parser.add_argument("--no-align-source-landmarks", dest="align_source_landmarks", action="store_false", default=True, help="Disable source-to-XML landmark station mapping")
    parser.add_argument("--bank-source-sign", choices=("auto", "preserve", "flip"), default="auto", help="Banking sign handling for reversed source profiles")
    parser.add_argument("--bank-width-policy", choices=("angle", "edge-delta"), default="angle", help="Preserve banking angle or real-road edge delta when comparing the profile to XML")
    parser.add_argument("--bank-real-width", type=float, default=0.0, help="Real road width used by --bank-width-policy edge-delta")
    parser.add_argument("--bank-max-abs-deg", type=float, default=45.0, help="Clamp expected banking angle before comparing to XML")
    return parser.parse_args()


def attnum_si(section: ET.Element | None, name: str, default: float = 0.0) -> float:
    return apply_elevation.attnum_si(section, name, default)


def hermite(p0: float, p1: float, t0: float, t1: float, t: float) -> float:
    return apply_elevation.hermite(p0, p1, t0, t1, t)


def load_track(track_xml: pathlib.Path) -> tuple[ET.Element, list[ET.Element], list[Segment], list[float], float]:
    _, tree = parse_xml_preserve_prolog(track_xml)
    root = tree.getroot()
    main_track, segs = segment_sections(root)
    segments = []
    lengths = []
    for seg in segs:
        segment = segment_from_element(seg)
        if segment is None:
            raise SystemExit(f"Unsupported segment in XML: {seg.get('name', '')}")
        segments.append(segment)
        lengths.append(segment_length(seg))
    total = sum(lengths)
    if total <= 0.0:
        raise SystemExit("Track XML has zero length")
    return main_track, segs, segments, lengths, total


def segment_starts(lengths: list[float]) -> list[float]:
    starts = []
    acc = 0.0
    for length in lengths:
        starts.append(acc)
        acc += length
    return starts


def sample_track_plan(segments: list[Segment], step: float) -> list[Sample]:
    pose = Pose(0.0, 0.0, 0.0)
    station = 0.0
    samples = [Sample(pose.x, pose.y, station, pose.heading, "start")]
    for segment in segments:
        pose, seg_samples = sample_segment(pose, segment, station, max(0.5, step))
        if seg_samples:
            station = seg_samples[-1].s
            samples.extend(seg_samples)
    return samples


def interpolate_track_plan(samples: list[Sample], station: float, total: float) -> Sample:
    if not samples:
        return Sample(0.0, 0.0, station, 0.0, "start")
    s = station % total
    if s <= samples[0].s:
        return samples[0]
    for i in range(1, len(samples)):
        if s <= samples[i].s:
            a = samples[i - 1]
            b = samples[i]
            span = b.s - a.s
            t = 0.0 if span <= 1e-9 else (s - a.s) / span
            heading = math.atan2(b.y - a.y, b.x - a.x) if math.hypot(b.x - a.x, b.y - a.y) > 1e-9 else a.heading
            return Sample(a.x + t * (b.x - a.x), a.y + t * (b.y - a.y), s, heading, a.segment or b.segment)
    first = samples[0]
    last = samples[-1]
    span = total - last.s
    t = 0.0 if span <= 1e-9 else (s + total - last.s) / span
    heading = math.atan2(first.y - last.y, first.x - last.x) if math.hypot(first.x - last.x, first.y - last.y) > 1e-9 else last.heading
    return Sample(last.x + t * (first.x - last.x), last.y + t * (first.y - last.y), s, heading, last.segment)


def locate_segment(starts: list[float], lengths: list[float], station: float, total: float) -> tuple[int, float]:
    s = station % total
    for i, start in enumerate(starts):
        length = lengths[i]
        if s <= start + length or i == len(starts) - 1:
            t = 0.0 if length <= 1e-9 else max(0.0, min(1.0, (s - start) / length))
            return i, t
    return len(starts) - 1, 0.0


def center_z_at(segs: list[ET.Element], lengths: list[float], starts: list[float], station: float, total: float) -> tuple[float, str]:
    i, t = locate_segment(starts, lengths, station, total)
    seg = segs[i]
    length = lengths[i]
    z0 = get_attnum(seg, "z start", 0.0)
    z1 = get_attnum(seg, "z end", z0)
    if find_att(seg, "attstr", "profil") is not None and (find_att(seg, "attstr", "profil").get("val") or "") == "spline":
        t0 = attnum_si(seg, "profil start tangent", 0.0) * length
        t1 = attnum_si(seg, "profil end tangent", 0.0) * length
        return hermite(z0, z1, t0, t1, t), seg.get("name", "")
    return z0 + t * (z1 - z0), seg.get("name", "")


def banking_deg_at(segs: list[ET.Element], lengths: list[float], starts: list[float], station: float, total: float) -> float:
    i, t = locate_segment(starts, lengths, station, total)
    seg = segs[i]
    banking_start = math.degrees(attnum_si(seg, "banking start", 0.0))
    banking_end = math.degrees(attnum_si(seg, "banking end", math.radians(banking_start)))
    return banking_start + (banking_end - banking_start) * t


def lerp_pair(pair: tuple[float, float], t: float) -> float:
    return pair[0] + (pair[1] - pair[0]) * t


def load_profile_sources(profile: pathlib.Path) -> tuple[list[apply_elevation.ProfileSource], list[apply_elevation.ProfileSource]]:
    elevation_sources: list[apply_elevation.ProfileSource] = []
    try:
        elevation_sources.append(apply_elevation.read_profile(profile))
    except SystemExit as exc:
        if "Road-surface profile has no elevation samples" not in str(exc):
            raise
    banking_sources = apply_elevation.read_banking_profiles(profile)
    return elevation_sources, banking_sources


def align_sources(
    elevation_sources: list[apply_elevation.ProfileSource],
    banking_sources: list[apply_elevation.ProfileSource],
    segs: list[ET.Element],
    lengths: list[float],
    total: float,
    align: bool,
) -> tuple[list[apply_elevation.ProfileSource], list[dict], list[apply_elevation.ProfileSource], list[dict]]:
    xml_ranges = apply_elevation.xml_landmark_ranges(segs, lengths)
    elevation_sources, elevation_reports = apply_elevation.align_sources_to_xml_landmarks(elevation_sources, xml_ranges, total, align)
    banking_sources, banking_reports = apply_elevation.align_sources_to_xml_landmarks(banking_sources, xml_ranges, total, align)
    return elevation_sources, elevation_reports, banking_sources, banking_reports


def source_center_at(sources: list[apply_elevation.ProfileSource], station: float, total: float) -> float | None:
    if not sources:
        return None
    return apply_elevation.eval_sources(apply_elevation.normalized_sources(sources, total), station, total)


def source_banking_at(sources: list[apply_elevation.ProfileSource], station: float, total: float, args: argparse.Namespace) -> float | None:
    if not sources:
        return None
    return apply_elevation.eval_banking_sources(sources, station, total, args)


def build_surface_samples(
    main_track: ET.Element,
    segs: list[ET.Element],
    segments: list[Segment],
    lengths: list[float],
    total: float,
    elevation_sources: list[apply_elevation.ProfileSource],
    banking_sources: list[apply_elevation.ProfileSource],
    args: argparse.Namespace,
) -> list[SurfaceSample]:
    starts = segment_starts(lengths)
    plan = sample_track_plan(segments, min(3.0, max(1.0, args.sample_step)))
    widths = apply_elevation.main_width_profile(main_track, segs)
    real_width = apply_elevation.banking_real_width(args, banking_sources)
    count = max(3, int(math.ceil(total / max(1.0, args.sample_step))))
    out = []
    for i in range(count):
        station = total * i / count
        seg_i, t = locate_segment(starts, lengths, station, total)
        p = interpolate_track_plan(plan, station, total)
        width = lerp_pair(widths[seg_i], t)
        track_center, segment = center_z_at(segs, lengths, starts, station, total)
        track_bank = banking_deg_at(segs, lengths, starts, station, total)
        track_dz = math.tan(math.radians(track_bank)) * width * 0.5
        profile_center = source_center_at(elevation_sources, station, total)
        profile_bank = source_banking_at(banking_sources, station, total, args)
        if profile_bank is not None:
            profile_bank = apply_elevation.scale_banking_for_width(profile_bank, real_width, width, args)
        if profile_center is not None and profile_bank is not None:
            profile_dz = math.tan(math.radians(profile_bank)) * width * 0.5
            profile_left = profile_center + profile_dz
            profile_right = profile_center - profile_dz
        else:
            profile_left = None
            profile_right = None
        out.append(
            SurfaceSample(
                station,
                segment or p.segment,
                p.x,
                p.y,
                p.heading,
                width,
                track_center,
                track_center + track_dz,
                track_center - track_dz,
                track_bank,
                profile_center,
                profile_left,
                profile_right,
                profile_bank,
            )
        )
    return out


def sample_diff(sample: SurfaceSample, mode: str) -> float | None:
    if mode == "center":
        return sample.center_diff
    if mode == "left":
        return sample.left_diff
    if mode == "right":
        return sample.right_diff
    if mode == "bank":
        return sample.banking_diff
    return None


def choose_color_mode(samples: list[SurfaceSample], requested: str) -> str:
    if requested != "auto":
        return requested
    if any(sample.center_diff is not None for sample in samples):
        return "center"
    return "bank"


def offset_points(samples: list[SurfaceSample], side: float) -> list[tuple[float, float]]:
    points = [
        (
            sample.x - math.sin(sample.heading) * sample.width * 0.5 * side,
            sample.y + math.cos(sample.heading) * sample.width * 0.5 * side,
        )
        for sample in samples
    ]
    if points:
        points.append(points[0])
    return points


def metric(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mean": None, "rmse": None, "mean_abs": None, "max_abs": None}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "rmse": math.sqrt(sum(v * v for v in values) / len(values)),
        "mean_abs": sum(abs(v) for v in values) / len(values),
        "max_abs": max(abs(v) for v in values),
    }


def report_summary(
    samples: list[SurfaceSample],
    output: pathlib.Path,
    color_mode: str,
    label_top: int,
    elevation_reports: list[dict],
    banking_reports: list[dict],
    args: argparse.Namespace,
    banking_sources: list[apply_elevation.ProfileSource],
) -> dict:
    def values(mode: str) -> list[float]:
        return [value for sample in samples if (value := sample_diff(sample, mode)) is not None]

    def sample_obj(sample: SurfaceSample) -> dict:
        return {
            "station_m": sample.station,
            "segment": sample.segment,
            "width_m": sample.width,
            "track_center_z_m": sample.track_center_z,
            "profile_center_z_m": sample.profile_center_z,
            "center_difference_m": sample.center_diff,
            "track_left_z_m": sample.track_left_z,
            "profile_left_z_m": sample.profile_left_z,
            "left_difference_m": sample.left_diff,
            "track_right_z_m": sample.track_right_z,
            "profile_right_z_m": sample.profile_right_z,
            "right_difference_m": sample.right_diff,
            "track_banking_deg": sample.track_banking_deg,
            "profile_banking_deg": sample.profile_banking_deg,
            "banking_difference_deg": sample.banking_diff,
        }

    ranked = [sample for sample in samples if sample_diff(sample, color_mode) is not None]
    ranked.sort(key=lambda item: abs(sample_diff(item, color_mode) or 0.0), reverse=True)
    return {
        "output_svg": str(output),
        "sample_count": len(samples),
        "color_mode": color_mode,
        "bank_width_policy": args.bank_width_policy,
        "bank_real_width_m": apply_elevation.banking_real_width(args, banking_sources),
        "difference_definition": "track - profile; red means track above/profile-more-positive, blue means track below/profile-more-negative",
        "metrics": {mode: metric(values(mode)) for mode in ("center", "left", "right", "bank")},
        "elevation_source_alignment": elevation_reports,
        "banking_source_alignment": banking_reports,
        "top_abs_samples": [sample_obj(sample) for sample in ranked[: max(0, label_top)]],
    }


def legend_svg(mode: str, color_range: float) -> list[str]:
    unit = "deg" if mode == "bank" else "m"
    return [
        '<g id="legend">',
        '<rect x="18" y="18" width="430" height="96" rx="10" fill="#020617" fill-opacity="0.88" stroke="#64748b"/>',
        f'<text x="34" y="44" fill="#f8fafc" font-family="sans-serif" font-size="15" font-weight="700">Road surface diff: {html.escape(mode)}</text>',
        '<text x="34" y="68" fill="#e2e8f0" font-family="sans-serif" font-size="12">track - profile; red high, blue low</text>',
        f'<text x="34" y="92" fill="#e2e8f0" font-family="monospace" font-size="12">range +/- {color_range:.2f} {unit}</text>',
        "</g>",
    ]


def write_svg(path: pathlib.Path, samples: list[SurfaceSample], color_mode: str, color_range: float, label_top: int, width: float, pad: float) -> None:
    if not samples:
        raise SystemExit("No road-surface samples to render")
    center = [(sample.x, sample.y) for sample in samples]
    if center:
        center.append(center[0])
    left = offset_points(samples, 1.0)
    right = offset_points(samples, -1.0)
    mapper, height = build_mapper(center + left + right, width, pad)
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.2f} {height:.2f}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#f8fafc"/>',
        '<g id="torcs-track-outline" fill="none" stroke="#0f172a" stroke-width="4.2" stroke-linejoin="round" stroke-linecap="round" opacity="0.82">',
        f'<polyline points="{polyline_points(left, mapper)}"/>',
        f'<polyline points="{polyline_points(right, mapper)}"/>',
        "</g>",
        '<g id="difference-centerline" fill="none" stroke-linejoin="round" stroke-linecap="round">',
    ]
    for i in range(1, len(samples)):
        a = samples[i - 1]
        b = samples[i]
        diff_a = sample_diff(a, color_mode) or 0.0
        diff_b = sample_diff(b, color_mode) or 0.0
        color = color_for_diff(0.5 * (diff_a + diff_b), color_range)
        x1, y1 = mapper(a.x, a.y)
        x2, y2 = mapper(b.x, b.y)
        out.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="8.0"/>')
    if len(samples) > 2:
        a = samples[-1]
        b = samples[0]
        diff_a = sample_diff(a, color_mode) or 0.0
        diff_b = sample_diff(b, color_mode) or 0.0
        color = color_for_diff(0.5 * (diff_a + diff_b), color_range)
        x1, y1 = mapper(a.x, a.y)
        x2, y2 = mapper(b.x, b.y)
        out.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="8.0"/>')
    out.extend(["</g>", '<g id="difference-samples">'])
    for sample in samples:
        diff = sample_diff(sample, color_mode)
        color = color_for_diff(diff or 0.0, color_range)
        x, y = mapper(sample.x, sample.y)
        title = html.escape(
            f"s={sample.station:.1f}m seg={sample.segment} center={sample.center_diff} left={sample.left_diff} "
            f"right={sample.right_diff} bank={sample.banking_diff}"
        )
        out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.6" fill="{color}" stroke="#020617" stroke-width="0.85"><title>{title}</title></circle>')
    out.append("</g>")
    labels = [sample for sample in samples if sample_diff(sample, color_mode) is not None]
    labels.sort(key=lambda item: abs(sample_diff(item, color_mode) or 0.0), reverse=True)
    out.append('<g id="top-difference-labels" font-family="Consolas, monospace" font-size="12" font-weight="700">')
    for sample in labels[: max(0, label_top)]:
        diff = sample_diff(sample, color_mode) or 0.0
        x, y = mapper(sample.x, sample.y)
        color = "#991b1b" if diff > 0.0 else "#1d4ed8"
        out.append(f'<text x="{x + 7:.2f}" y="{y - 7:.2f}" fill="{color}" stroke="#ffffff" stroke-width="2" paint-order="stroke">{diff:+.1f}</text>')
    out.append("</g>")
    out.extend(legend_svg(color_mode, color_range))
    out.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    track_xml = pathlib.Path(args.track_xml)
    profile_path = pathlib.Path(args.profile)
    main_track, segs, segments, lengths, total = load_track(track_xml)
    elevation_sources, banking_sources = load_profile_sources(profile_path)
    elevation_sources, elevation_reports, banking_sources, banking_reports = align_sources(
        elevation_sources,
        banking_sources,
        segs,
        lengths,
        total,
        args.align_source_landmarks,
    )
    if not elevation_sources and not banking_sources:
        raise SystemExit("Profile has neither elevation nor banking samples")
    samples = build_surface_samples(main_track, segs, segments, lengths, total, elevation_sources, banking_sources, args)
    color_mode = choose_color_mode(samples, args.color_mode)
    color_range = max(1e-9, args.bank_color_range if color_mode == "bank" else args.color_range)
    output = pathlib.Path(args.output)
    write_svg(output, samples, color_mode, color_range, args.label_top, args.width, args.pad)
    report = report_summary(samples, output, color_mode, args.label_top, elevation_reports, banking_reports, args, banking_sources)
    if args.report:
        report_path = pathlib.Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote road-surface diff SVG: {output}")
    print(f"Samples: {len(samples)}, color mode: {color_mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
