#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : import_banking_zones.py
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

"""Convert manual banking zone descriptions into a road-surface profile."""

from __future__ import annotations

import argparse
import html
import json
import math
import pathlib

from torcs_track_tools.cli import apply_elevation
from torcs_track_tools.core.polyline import to_xy_tuples
from torcs_track_tools.core.track_xml import parse_xml_preserve_prolog, segment_length, segment_sections


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert manual banking zones into a road-surface profile")
    parser.add_argument("--polyline", required=True, help="Source centerline JSON that defines source stations")
    parser.add_argument("--zones", required=True, help="Manual banking zones JSON")
    parser.add_argument("--output", required=True, help="Output road-surface profile JSON")
    parser.add_argument("--track-xml", default="", help="Optional accepted TORCS XML used to write station-map anchors")
    parser.add_argument("--sample-step", type=float, default=10.0, help="Output banking sample spacing in meters")
    parser.add_argument("--report", default="", help="Optional diagnostics JSON")
    parser.add_argument("--overlay", default="", help="Optional banking profile SVG")
    return parser.parse_args()


def parse_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def read_polyline(path: pathlib.Path) -> tuple[list[dict], float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("polyline", []) if isinstance(data, dict) else []
    if len(raw) < 2:
        raise SystemExit(f"Source polyline has too few points: {path}")
    xy = to_xy_tuples(raw, raw[0])
    total = 0.0
    for a, b in zip(xy, xy[1:], strict=False):
        total += math.hypot(b[0] - a[0], b[1] - a[1])
    if len(xy) > 2 and math.hypot(xy[0][0] - xy[-1][0], xy[0][1] - xy[-1][1]) > 1e-6:
        total += math.hypot(xy[0][0] - xy[-1][0], xy[0][1] - xy[-1][1])
    if total <= 1e-9:
        raise SystemExit(f"Source polyline has zero length: {path}")
    return raw, total


def source_landmarks(polyline_path: pathlib.Path) -> tuple[apply_elevation.LandmarkRange, ...]:
    return apply_elevation.landmark_ranges_from_polyline(polyline_path)


def xml_station_map(track_xml: pathlib.Path, source_ranges: tuple[apply_elevation.LandmarkRange, ...], source_total: float) -> tuple[list[dict], dict]:
    _, tree = parse_xml_preserve_prolog(track_xml)
    root = tree.getroot()
    _, segs = segment_sections(root)
    lengths = [segment_length(seg) for seg in segs]
    xml_ranges = apply_elevation.xml_landmark_ranges(segs, lengths)
    points = apply_elevation.station_map_points(xml_ranges, source_ranges, source_total)
    return [
        {
            "xml_station_m": point.xml_station,
            "source_station_m": point.source_station,
        }
        for point in points
    ], {
        "xml_total_length_m": sum(lengths),
        "source_landmark_count": len(source_ranges),
        "matched_anchor_count": len(points),
        "matched_names": sorted({r.name for r in xml_ranges if any(s.name == r.name for s in source_ranges)}),
    }


def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


def station_in_zone(station: float, start: float, end: float, total: float) -> bool:
    if total <= 1e-9:
        return False
    s = station % total
    start %= total
    end %= total
    if abs((end - start) % total) <= 1e-9:
        return True
    if start <= end:
        return start <= s <= end
    return s >= start or s <= end


def station_delta_in_zone(station: float, start: float, total: float) -> float:
    return (station - start) % total


def zone_span(start: float, end: float, total: float) -> float:
    span = (end - start) % total
    return total if span <= 1e-9 else span


def zone_banking(zone: dict, station: float, total: float) -> float | None:
    start = parse_float(zone.get("source_start_station_m"), math.nan)
    end = parse_float(zone.get("source_end_station_m"), math.nan)
    if not math.isfinite(start) or not math.isfinite(end):
        raise SystemExit(f"Banking zone needs source_start_station_m and source_end_station_m: {zone}")
    if not station_in_zone(station, start, end, total):
        return None
    start_bank = parse_float(zone.get("banking_start_deg", zone.get("banking_deg", 0.0)), 0.0)
    peak_bank = parse_float(zone.get("banking_peak_deg", zone.get("banking_deg", start_bank)), start_bank)
    end_bank = parse_float(zone.get("banking_end_deg", zone.get("banking_deg", peak_bank)), peak_bank)
    span = zone_span(start, end, total)
    d = min(span, station_delta_in_zone(station, start, total))
    transition_in = max(0.0, parse_float(zone.get("transition_in_m"), 0.0))
    transition_out = max(0.0, parse_float(zone.get("transition_out_m"), 0.0))
    if transition_in > 0.0 and d < transition_in:
        return start_bank + (peak_bank - start_bank) * smoothstep(d / transition_in)
    if transition_out > 0.0 and d > span - transition_out:
        return peak_bank + (end_bank - peak_bank) * smoothstep((d - (span - transition_out)) / transition_out)
    return peak_bank


def build_samples(zones: list[dict], total: float, step: float) -> tuple[list[dict], list[dict]]:
    count = max(2, int(math.ceil(total / max(1.0, step))))
    samples = []
    overlaps = []
    for i in range(count + 1):
        station = total * i / count
        active = [(zone, zone_banking(zone, station, total)) for zone in zones]
        active = [(zone, value) for zone, value in active if value is not None]
        if len(active) > 1:
            overlaps.append({"source_station_m": station, "zones": [str(zone.get("name", "")) for zone, _ in active]})
        if active:
            confidence_sum = sum(parse_float(zone.get("confidence"), 1.0) for zone, _ in active)
            banking = sum(float(value) * parse_float(zone.get("confidence"), 1.0) for zone, value in active) / max(1e-12, confidence_sum)
            confidence = confidence_sum / len(active)
            source = ",".join(str(zone.get("name", "zone")) for zone, _ in active)
        else:
            banking = 0.0
            confidence = 1.0
            source = "default-flat"
        samples.append(
            {
                "source_station_m": station % total,
                "banking_deg": banking,
                "confidence": confidence,
                "source": source,
            }
        )
    return samples, overlaps


def write_overlay(path: pathlib.Path, samples: list[dict], total: float) -> None:
    width = 1200.0
    height = 360.0
    pad = 45.0
    values = [parse_float(sample.get("banking_deg"), 0.0) for sample in samples]
    lo = min(values, default=0.0)
    hi = max(values, default=0.0)
    if abs(hi - lo) <= 1e-9:
        lo -= 1.0
        hi += 1.0

    def x_for(station: float) -> float:
        return pad + (width - 2 * pad) * (station / max(1e-9, total))

    def y_for(value: float) -> float:
        return height - pad - (height - 2 * pad) * ((value - lo) / (hi - lo))

    points = " ".join(f"{x_for(parse_float(s['source_station_m'])):.1f},{y_for(parse_float(s['banking_deg'])):.1f}" for s in samples)
    text = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">\n'
        '<rect width="100%" height="100%" fill="white"/>\n'
        f'<text x="{pad}" y="24" font-family="sans-serif" font-size="16">Manual banking profile</text>\n'
        f'<line x1="{pad}" y1="{y_for(0.0):.1f}" x2="{width - pad}" y2="{y_for(0.0):.1f}" stroke="#999" stroke-dasharray="4 4"/>\n'
        f'<polyline fill="none" stroke="#c026d3" stroke-width="2" points="{html.escape(points)}"/>\n'
        f'<text x="{pad}" y="{height - 12:.1f}" font-family="sans-serif" font-size="12">0 m</text>\n'
        f'<text x="{width - pad - 90:.1f}" y="{height - 12:.1f}" font-family="sans-serif" font-size="12">{total:.1f} m</text>\n'
        f'<text x="8" y="{y_for(hi):.1f}" font-family="sans-serif" font-size="12">{hi:.1f} deg</text>\n'
        f'<text x="8" y="{y_for(lo):.1f}" font-family="sans-serif" font-size="12">{lo:.1f} deg</text>\n'
        "</svg>\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    polyline = pathlib.Path(args.polyline)
    zones_path = pathlib.Path(args.zones)
    _, total = read_polyline(polyline)
    zones_data = json.loads(zones_path.read_text(encoding="utf-8"))
    zones = list(zones_data.get("zones", [])) if isinstance(zones_data, dict) else []
    if not zones:
        raise SystemExit(f"No banking zones found: {zones_path}")

    samples, overlaps = build_samples(zones, total, args.sample_step)
    source_ranges = source_landmarks(polyline)
    station_map: list[dict] = []
    mapping_report: dict = {}
    if args.track_xml:
        station_map, mapping_report = xml_station_map(pathlib.Path(args.track_xml), source_ranges, total)

    output = pathlib.Path(args.output)
    profile = {
        "schema": 1,
        "type": "road-surface-profile",
        "station_frame": "source",
        "source_polyline": args.polyline,
        "source_total_length_m": total,
        "mapping": {
            "method": "station-map" if station_map else "identity",
            "source_reversed": False,
            "station_map": station_map,
        },
        "banking_profile": {
            "source": "manual-zones",
            "zones": zones,
            "samples": samples,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    if args.overlay:
        write_overlay(pathlib.Path(args.overlay), samples, total)
    if args.report:
        report = {
            "profile": args.output,
            "source_total_length_m": total,
            "zone_count": len(zones),
            "sample_count": len(samples),
            "overlap_count": len(overlaps),
            "overlaps": overlaps[:20],
            "mapping": mapping_report,
            "min_banking_deg": min(parse_float(sample.get("banking_deg"), 0.0) for sample in samples),
            "max_banking_deg": max(parse_float(sample.get("banking_deg"), 0.0) for sample in samples),
        }
        report_path = pathlib.Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Wrote banking profile: {output}")
    print(f"Samples: {len(samples)}, zones: {len(zones)}, overlaps: {len(overlaps)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
