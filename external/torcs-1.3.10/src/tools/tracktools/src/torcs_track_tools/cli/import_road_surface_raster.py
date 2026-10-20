#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : import_road_surface_raster.py
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

"""Sample a high-resolution raster into a road-surface profile."""

from __future__ import annotations

import argparse
import html
import json
import math
import pathlib
from dataclasses import dataclass

from torcs_track_tools.cli.import_elevation_raster import (
    RasterSampler,
    SourcePoint,
    crs_is_geographic,
    crs_unit_to_meter,
    load_source_points,
    open_raster,
)
from torcs_track_tools.cli.render_elevation_diff_svg import (
    FitResult,
    build_mapper,
    find_best_fit,
    load_track,
    polyline_points,
    resample_track_loop,
)


@dataclass(frozen=True)
class SourcePose:
    x: float
    y: float
    station: float
    heading: float


@dataclass(frozen=True)
class CrossSample:
    station: float
    x: float
    y: float
    heading: float
    elevation: float
    raw_elevation: float
    banking_deg: float
    left_elevation: float
    right_elevation: float
    valid_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sample a raster road surface into elevation and banking profiles")
    parser.add_argument("--track-xml", required=True, help="Accepted TORCS XML used only to fit XML stations to source stations")
    parser.add_argument("--polyline", required=True, help="Source centerline JSON; samples are taken in this source station frame")
    parser.add_argument("--raster", required=True, help="Input road-surface raster, currently GeoTIFF or ESRI ASCII grid")
    parser.add_argument("--output", required=True, help="Output road-surface profile JSON")
    parser.add_argument("--report", default="", help="Optional JSON diagnostics report")
    parser.add_argument("--overlay", default="", help="Optional SVG overlay of source centerline and banking samples")
    parser.add_argument("--sample-step", type=float, default=5.0, help="Source-station output sample spacing in meters")
    parser.add_argument("--road-width", type=float, required=True, help="Real road width in meters used for crossfall sampling")
    parser.add_argument("--cross-section-samples", type=int, default=5, help="Number of lateral raster samples across --road-width")
    parser.add_argument("--min-cross-section-samples", type=int, default=0, help="Minimum valid lateral samples; 0 means all cross-section samples")
    parser.add_argument("--fit-samples", type=int, default=720, help="Loop samples used for source-to-XML plan-view fit")
    parser.add_argument("--fit-shift-step", type=int, default=3, help="Initial circular shift stride; best area is refined at stride 1")
    parser.add_argument("--allow-reverse-source", action="store_true", help="Also try the source loop in reverse during plan-view fitting")
    parser.add_argument("--allow-scale-fit", action="store_true", help="Allow a uniform scale in the plan-view fit for georeferenced map sources")
    parser.add_argument("--resampling", choices=("bilinear", "nearest"), default="bilinear", help="Raster resampling mode")
    parser.add_argument("--raster-crs", default="", help="CRS override for rasters without CRS metadata, for example EPSG:27700")
    parser.add_argument("--polyline-crs", default="", help="CRS for x/y polyline points when reprojection is needed; lat/lon defaults to EPSG:4326")
    parser.add_argument("--zero", choices=("track-start", "minimum", "none"), default="track-start", help="Elevation zeroing mode for center elevation output")
    parser.add_argument("--profile-weight", type=float, default=1.0, help="Weight stored on each elevation sample")
    parser.add_argument("--banking-weight", type=float, default=1.0, help="Weight stored on each banking sample")
    return parser.parse_args()


def dedupe_loop_points(points: list[SourcePoint], epsilon: float = 1e-6) -> list[SourcePoint]:
    if len(points) >= 2 and math.hypot(points[0].x - points[-1].x, points[0].y - points[-1].y) <= epsilon:
        return points[:-1]
    return list(points)


def loop_stations(points: list[SourcePoint], units_to_meter: float) -> tuple[list[float], float]:
    stations = [0.0]
    total = 0.0
    for a, b in zip(points, points[1:], strict=False):
        total += math.hypot(b.x - a.x, b.y - a.y) * units_to_meter
        stations.append(total)
    if len(points) > 2:
        total += math.hypot(points[0].x - points[-1].x, points[0].y - points[-1].y) * units_to_meter
    if total <= 1e-9:
        raise SystemExit("Source polyline has zero length after CRS transform")
    return stations, total


def source_pose_at(points: list[SourcePoint], stations: list[float], total: float, station: float) -> SourcePose:
    s = station % total
    for i in range(1, len(points)):
        if s <= stations[i]:
            a = points[i - 1]
            b = points[i]
            span = stations[i] - stations[i - 1]
            t = 0.0 if span <= 1e-9 else (s - stations[i - 1]) / span
            heading = math.atan2(b.y - a.y, b.x - a.x)
            return SourcePose(a.x + t * (b.x - a.x), a.y + t * (b.y - a.y), s, heading)
    a = points[-1]
    b = points[0]
    span = total - stations[-1]
    t = 0.0 if span <= 1e-9 else (s - stations[-1]) / span
    heading = math.atan2(b.y - a.y, b.x - a.x)
    return SourcePose(a.x + t * (b.x - a.x), a.y + t * (b.y - a.y), s, heading)


def lateral_offsets(width: float, count: int) -> list[float]:
    if width <= 0.0:
        raise SystemExit("--road-width must be greater than zero")
    if count < 2:
        raise SystemExit("--cross-section-samples must be at least 2")
    half = 0.5 * width
    return [-half + width * i / (count - 1) for i in range(count)]


def raster_units_per_meter(raster: RasterSampler) -> float:
    if not raster.crs:
        return 1.0
    if crs_is_geographic(raster.crs):
        raise SystemExit("Geographic raster CRS is not supported for road-surface cross-section sampling; reproject to a projected CRS first")
    unit_to_meter = crs_unit_to_meter(raster.crs)
    return 1.0 / unit_to_meter if unit_to_meter > 0.0 else 1.0


def should_allow_scale_fit(raster: RasterSampler, requested: bool) -> bool:
    if requested:
        return True
    return abs(raster_units_per_meter(raster) - 1.0) > 1e-6


def raster_units_to_meter(raster: RasterSampler) -> float:
    return 1.0 / raster_units_per_meter(raster)


def source_loop_fit_samples(points: list[SourcePoint], count: int, units_to_meter: float) -> tuple[list[dict], float]:
    clean = dedupe_loop_points(points)
    stations, total = loop_stations(clean, units_to_meter)
    count = max(8, count)
    out = []
    for i in range(count):
        station = total * i / count
        pose = source_pose_at(clean, stations, total, station)
        out.append({"x": pose.x, "y": pose.y, "s": station})
    return out, total


def sample_lateral(raster: RasterSampler, pose: SourcePose, offset_m: float, units_per_meter: float, resampling: str) -> tuple[float, float, float | None]:
    nx = -math.sin(pose.heading)
    ny = math.cos(pose.heading)
    offset = offset_m * units_per_meter
    x = pose.x + nx * offset
    y = pose.y + ny * offset
    return x, y, raster.sample(x, y, resampling)


def fit_crossfall(values: list[tuple[float, float]], width: float) -> tuple[float, float, float, float]:
    mean_o = sum(offset for offset, _ in values) / len(values)
    mean_z = sum(z for _, z in values) / len(values)
    variance = sum((offset - mean_o) * (offset - mean_o) for offset, _ in values)
    if variance <= 1e-12:
        raise SystemExit("Cross-section offsets have zero variance")
    slope = sum((offset - mean_o) * (z - mean_z) for offset, z in values) / variance
    center_z = mean_z - slope * mean_o
    half = 0.5 * width
    return center_z, math.degrees(math.atan(slope)), center_z + slope * half, center_z - slope * half


def sample_road_surface(raster: RasterSampler, source_points: list[SourcePoint], args: argparse.Namespace) -> tuple[list[CrossSample], float]:
    clean = dedupe_loop_points(source_points)
    units_to_meter = raster_units_to_meter(raster)
    stations, total = loop_stations(clean, units_to_meter)
    offsets = lateral_offsets(args.road_width, args.cross_section_samples)
    units_per_meter = raster_units_per_meter(raster)
    min_valid = args.cross_section_samples if args.min_cross_section_samples <= 0 else args.min_cross_section_samples
    min_valid = max(2, min(args.cross_section_samples, min_valid))
    count = max(3, int(math.ceil(total / max(1.0, args.sample_step))))
    samples = []
    missing = []
    for i in range(count):
        station = total * i / count
        pose = source_pose_at(clean, stations, total, station)
        values = []
        for offset in offsets:
            _x, _y, z = sample_lateral(raster, pose, offset, units_per_meter, args.resampling)
            if z is not None:
                values.append((offset, z))
        if len(values) < min_valid:
            missing.append({"source_station_m": station, "valid_cross_section_samples": len(values)})
            continue
        center_z, banking_deg, left_z, right_z = fit_crossfall(values, args.road_width)
        samples.append(CrossSample(station, pose.x, pose.y, pose.heading, center_z, center_z, banking_deg, left_z, right_z, len(values)))
    if missing:
        first = missing[0]
        raise SystemExit(
            f"Raster has too few cross-section samples at {len(missing)} stations; first at s={first['source_station_m']:.1f} "
            f"with {first['valid_cross_section_samples']} valid samples"
        )
    return samples, total


def raw_elevation_at(samples: list[CrossSample], station: float, total: float) -> float:
    ordered = sorted(samples, key=lambda sample: sample.station)
    if not ordered:
        return 0.0
    if total <= 0.0:
        return ordered[0].raw_elevation
    s = station % total
    if s <= ordered[0].station:
        return ordered[0].raw_elevation
    for i in range(1, len(ordered)):
        if s <= ordered[i].station:
            prev = ordered[i - 1]
            nxt = ordered[i]
            span = nxt.station - prev.station
            t = 0.0 if span <= 1e-9 else (s - prev.station) / span
            return prev.raw_elevation + t * (nxt.raw_elevation - prev.raw_elevation)
    prev = ordered[-1]
    nxt = ordered[0]
    span = nxt.station + total - prev.station
    t = 0.0 if span <= 1e-9 else (s - prev.station) / span
    return prev.raw_elevation + t * (nxt.raw_elevation - prev.raw_elevation)


def zero_samples(samples: list[CrossSample], mode: str, source_shift: float = 0.0, source_total: float = 0.0) -> tuple[list[CrossSample], float]:
    if not samples or mode == "none":
        return list(samples), 0.0
    zero = min(sample.raw_elevation for sample in samples) if mode == "minimum" else raw_elevation_at(samples, source_shift, source_total)
    return [
        CrossSample(
            sample.station,
            sample.x,
            sample.y,
            sample.heading,
            sample.raw_elevation - zero,
            sample.raw_elevation,
            sample.banking_deg,
            sample.left_elevation,
            sample.right_elevation,
            sample.valid_count,
        )
        for sample in samples
    ], zero


def write_profile(path: pathlib.Path, samples: list[CrossSample], args: argparse.Namespace, fit: FitResult, source_total: float, zero: float) -> None:
    offsets = lateral_offsets(args.road_width, args.cross_section_samples)
    obj = {
        "schema": 1,
        "type": "road-surface-profile",
        "station_frame": "source",
        "track_xml": args.track_xml,
        "source_polyline": args.polyline,
        "raster": args.raster,
        "source_total_length_m": source_total,
        "sample_step_m": args.sample_step,
        "resampling": args.resampling,
        "zero_elevation_m": zero,
        "mapping": {
            "method": "plan-fit",
            "source_shift_m": fit.source_shift_m,
            "source_reversed": fit.source_reversed,
        },
        "sampling": {
            "real_road_width_m": args.road_width,
            "cross_section_sample_count": args.cross_section_samples,
            "cross_section_offsets_m": offsets,
        },
        "fit": {
            "rmse_m": fit.rmse,
            "rotation_deg": math.degrees(fit.theta),
            "scale": fit.scale,
            "cos": fit.c,
            "sin": fit.s,
            "offset_x": fit.ox,
            "offset_y": fit.oy,
            "source_shift_m": fit.source_shift_m,
            "source_reversed": fit.source_reversed,
        },
        "elevation_profile": {
            "source": "raster-road-surface",
            "samples": [
                {
                    "source_station_m": sample.station,
                    "elevation_m": sample.elevation,
                    "weight": args.profile_weight,
                    "raster_x": sample.x,
                    "raster_y": sample.y,
                    "raw_elevation_m": sample.raw_elevation,
                    "left_raw_elevation_m": sample.left_elevation,
                    "right_raw_elevation_m": sample.right_elevation,
                }
                for sample in samples
            ],
        },
        "banking_profile": {
            "source": "raster-road-surface",
            "samples": [
                {
                    "source_station_m": sample.station,
                    "banking_deg": sample.banking_deg,
                    "weight": args.banking_weight,
                    "left_raw_elevation_m": sample.left_elevation,
                    "right_raw_elevation_m": sample.right_elevation,
                    "valid_cross_section_samples": sample.valid_count,
                }
                for sample in samples
            ],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def write_report(path: pathlib.Path, samples: list[CrossSample], args: argparse.Namespace, fit: FitResult, source_total: float, zero: float, raster: RasterSampler) -> None:
    elevations = [sample.elevation for sample in samples]
    raw = [sample.raw_elevation for sample in samples]
    banking = [sample.banking_deg for sample in samples]
    report = {
        "profile": args.output,
        "sample_count": len(samples),
        "source_total_length_m": source_total,
        "zero_elevation_m": zero,
        "real_road_width_m": args.road_width,
        "cross_section_sample_count": args.cross_section_samples,
        "min_elevation_m": min(elevations, default=0.0),
        "max_elevation_m": max(elevations, default=0.0),
        "min_raw_elevation_m": min(raw, default=0.0),
        "max_raw_elevation_m": max(raw, default=0.0),
        "min_banking_deg": min(banking, default=0.0),
        "max_banking_deg": max(banking, default=0.0),
        "raster_crs": raster.crs,
        "raster_bounds": raster.bounds,
        "fit": {
            "rmse_m": fit.rmse,
            "rotation_deg": math.degrees(fit.theta),
            "scale": fit.scale,
            "source_shift_m": fit.source_shift_m,
            "source_reversed": fit.source_reversed,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def color_for_bank(value: float, min_value: float, max_value: float) -> str:
    if max_value <= min_value:
        t = 0.5
    else:
        t = max(0.0, min(1.0, (value - min_value) / (max_value - min_value)))
    if t <= 0.5:
        local = t * 2.0
        a = (37, 99, 235)
        b = (255, 255, 255)
    else:
        local = (t - 0.5) * 2.0
        a = (255, 255, 255)
        b = (220, 38, 38)
    r = round(a[0] + (b[0] - a[0]) * local)
    g = round(a[1] + (b[1] - a[1]) * local)
    bl = round(a[2] + (b[2] - a[2]) * local)
    return f"#{r:02x}{g:02x}{bl:02x}"


def write_overlay(path: pathlib.Path, source_points: list[SourcePoint], samples: list[CrossSample], width: float = 1600.0, pad: float = 50.0) -> None:
    source_xy = [(p.x, p.y) for p in source_points]
    if source_xy and math.hypot(source_xy[0][0] - source_xy[-1][0], source_xy[0][1] - source_xy[-1][1]) > 1e-6:
        source_xy.append(source_xy[0])
    sample_xy = [(p.x, p.y) for p in samples]
    mapper, height = build_mapper(source_xy + sample_xy, width, pad)
    min_bank = min((p.banking_deg for p in samples), default=0.0)
    max_bank = max((p.banking_deg for p in samples), default=1.0)
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.2f} {height:.2f}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#f8fafc"/>',
        '<g id="source-centerline" fill="none" stroke="#22c55e" stroke-width="4" stroke-dasharray="10 7" stroke-linecap="round" stroke-linejoin="round">',
        f'<polyline points="{polyline_points(source_xy, mapper)}"/>',
        "</g>",
        '<g id="road-surface-samples">',
    ]
    for sample in samples:
        x, y = mapper(sample.x, sample.y)
        color = color_for_bank(sample.banking_deg, min_bank, max_bank)
        title = html.escape(f"s={sample.station:.1f}m bank={sample.banking_deg:.2f}deg z={sample.elevation:.2f}m")
        out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" fill="{color}" stroke="#020617" stroke-width="0.8"><title>{title}</title></circle>')
    out.extend(
        [
            "</g>",
            '<rect x="18" y="18" width="445" height="78" rx="10" fill="#020617" fill-opacity="0.86"/>',
            '<text x="36" y="48" fill="#f8fafc" font-family="Consolas, monospace" font-size="18">Raster road-surface import</text>',
            f'<text x="36" y="74" fill="#cbd5e1" font-family="Consolas, monospace" font-size="13">banking range {min_bank:.1f} deg .. {max_bank:.1f} deg</text>',
            "</svg>",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    track_xml = pathlib.Path(args.track_xml)
    polyline = pathlib.Path(args.polyline)
    raster_path = pathlib.Path(args.raster)
    if not track_xml.exists():
        raise SystemExit(f"Track XML not found: {track_xml}")
    if not polyline.exists():
        raise SystemExit(f"Source polyline not found: {polyline}")
    if not raster_path.exists():
        raise SystemExit(f"Raster not found: {raster_path}")

    raster = open_raster(raster_path, args.raster_crs)
    source_points = load_source_points(polyline, raster.crs, args.polyline_crs)
    source_fit_samples, source_total = source_loop_fit_samples(source_points, args.fit_samples, raster_units_to_meter(raster))
    _, _, segments, _, track_total = load_track(track_xml)
    track_fit_samples = resample_track_loop(segments, track_total, args.fit_samples)
    fit = find_best_fit(track_fit_samples, source_fit_samples, source_total, args.fit_shift_step, args.allow_reverse_source, should_allow_scale_fit(raster, args.allow_scale_fit))
    samples, source_total = sample_road_surface(raster, source_points, args)
    samples, zero = zero_samples(samples, args.zero, fit.source_shift_m, source_total)

    output = pathlib.Path(args.output)
    write_profile(output, samples, args, fit, source_total, zero)
    if args.report:
        write_report(pathlib.Path(args.report), samples, args, fit, source_total, zero, raster)
    if args.overlay:
        write_overlay(pathlib.Path(args.overlay), source_points, samples)

    elevations = [p.elevation for p in samples]
    banking = [p.banking_deg for p in samples]
    print(f"Wrote road-surface profile: {output}")
    if args.report:
        print(f"Wrote report: {args.report}")
    if args.overlay:
        print(f"Wrote overlay: {args.overlay}")
    print(f"Samples: {len(samples)} at ~{args.sample_step:.1f} m, road width: {args.road_width:.2f} m")
    print(f"Fit RMSE: {fit.rmse:.2f} m, source shift: {fit.source_shift_m:.1f} m, reversed: {fit.source_reversed}")
    print(f"Elevation range: {min(elevations, default=0.0):.2f} m .. {max(elevations, default=0.0):.2f} m")
    print(f"Banking range: {min(banking, default=0.0):.2f} deg .. {max(banking, default=0.0):.2f} deg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
