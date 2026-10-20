#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : render_elevation_diff_svg.py
#     created              : 08 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Render a DEM-vs-track elevation diagnostic SVG.

The SVG is intentionally a plan-view diagnostic: it aligns the generated TORCS
track with the source DEM loop, draws the real/source outline, then colors track
samples by ``track_z - DEM_z``. Red therefore means the track is above the DEM
surface, and blue means it is below it.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import pathlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass

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
class DemPoint:
    x: float
    y: float
    z: float
    station: float


@dataclass(frozen=True)
class DemLine:
    side: str
    distance: float
    points: list[DemPoint]


@dataclass(frozen=True)
class TrackPoint:
    station: float
    x: float
    y: float
    heading: float
    segment: str
    z: float


@dataclass(frozen=True)
class FitResult:
    theta: float
    c: float
    s: float
    ox: float
    oy: float
    rmse: float
    source_shift_m: float
    source_reversed: bool
    scale: float = 1.0


@dataclass(frozen=True)
class HeightHit:
    z: float
    distance: float
    station: float
    side: str
    offset_distance: float


@dataclass(frozen=True)
class DiffSample:
    station: float
    segment: str
    x: float
    y: float
    heading: float
    track_z: float
    dem_z: float
    diff: float
    plan_distance: float
    source_station: float


@dataclass(frozen=True)
class RenderPaths:
    track_xml: pathlib.Path
    cache_path: pathlib.Path | None
    profile_path: pathlib.Path | None
    source_path: pathlib.Path | None
    map_cache_path: pathlib.Path | None
    output: pathlib.Path


@dataclass(frozen=True)
class HeightSourceContext:
    dem_lines: list[DemLine]
    cache_zero: float
    source_data: dict
    map_dem_lines: list[DemLine]
    source_center: DemLine
    height_lines: list[DemLine]


@dataclass(frozen=True)
class TrackRenderContext:
    track_total: float
    source_total: float
    track_width: float
    fit: FitResult
    track_samples: list[TrackPoint]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a TORCS XML vs DEM elevation-difference SVG")
    parser.add_argument("--track-xml", required=True, help="TORCS track XML with the currently applied elevation profile")
    parser.add_argument("--elevation-cache", default="", help="DEM cache produced by torcs-fetch-elevation")
    parser.add_argument(
        "--profile",
        default="",
        help="Station/elevation profile JSON with raster_x/raster_y samples, such as torcs-import-elevation-raster output.",
    )
    parser.add_argument(
        "--map-elevation-cache",
        default="",
        help="Optional DEM cache used only for the background height-map lines; differences still use --elevation-cache.",
    )
    parser.add_argument(
        "--map-lines",
        choices=("center", "all"),
        default="center",
        help="DEM lines drawn in the background height map. Use 'all' only when offset terrain corridors are known clean.",
    )
    parser.add_argument("--output", required=True, help="Output SVG path")
    parser.add_argument("--report", default="", help="Optional JSON report path")
    parser.add_argument(
        "--profile-output",
        default="",
        help="Optional JSON station/elevation profile sampled from the fitted DEM at the accepted XML centerline.",
    )
    parser.add_argument("--sample-step", type=float, default=5.0, help="Track sampling spacing in meters")
    parser.add_argument("--fit-samples", type=int, default=720, help="Loop samples used for the circular plan-view fit")
    parser.add_argument("--fit-shift-step", type=int, default=3, help="Initial circular shift stride; best area is refined at stride 1")
    parser.add_argument(
        "--height-lines",
        choices=("center", "all"),
        default="center",
        help="DEM lines used for height lookup. 'center' compares the road centerline; 'all' uses the whole cached corridor.",
    )
    parser.add_argument(
        "--dem-zero",
        choices=("track-start", "cache-start", "none"),
        default="track-start",
        help="Relative DEM zero. 'track-start' samples DEM at XML station 0 after fitting.",
    )
    parser.add_argument("--color-range", type=float, default=5.0, help="Absolute difference in meters that reaches full red/blue")
    parser.add_argument("--legend-step", type=float, default=5.0, help="Legend tick spacing in meters")
    parser.add_argument("--label-top", type=int, default=10, help="Label this many largest absolute differences in the SVG")
    parser.add_argument("--width", type=float, default=1600.0, help="SVG viewport width in pixels")
    parser.add_argument("--pad", type=float, default=50.0, help="SVG viewport padding in pixels")
    parser.add_argument("--allow-reverse-source", action="store_true", help="Also try the source loop in reverse during plan-view fitting")
    parser.add_argument("--allow-scale-fit", action="store_true", help="Allow a uniform scale in the plan-view fit for georeferenced map sources")
    return parser.parse_args()


def parse_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def attnum_si(section: ET.Element | None, name: str, default: float = 0.0) -> float:
    att = find_att(section, "attnum", name)
    if att is None:
        return default
    value = parse_float(att.get("val"), default)
    unit = (att.get("unit") or "").lower()
    if unit in ("%", "percent"):
        return value * 0.01
    if unit == "deg":
        return math.radians(value)
    return value


def load_dem_cache(path: pathlib.Path) -> tuple[list[DemLine], float, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_lines = data.get("terrain_lines", []) if isinstance(data, dict) else []
    lines = []
    for line in raw_lines:
        points = []
        for item in line.get("samples", []):
            if "x" not in item or "y" not in item or "elevation_m" not in item:
                continue
            points.append(
                DemPoint(
                    parse_float(item.get("x")),
                    parse_float(item.get("y")),
                    parse_float(item.get("elevation_m")),
                    parse_float(item.get("station_m", item.get("station"))),
                )
            )
        if len(points) >= 2:
            lines.append(DemLine(str(line.get("side", "")).strip().lower(), parse_float(line.get("distance_m")), points))
    if not lines:
        raise SystemExit(f"Elevation cache has no positioned terrain_lines samples: {path}")
    normalization = data.get("normalization") or {}
    cache_zero = parse_float(normalization.get("road_start_elevation_m"), lines[0].points[0].z)
    return lines, cache_zero, data


def load_positioned_profile(path: pathlib.Path) -> tuple[list[DemLine], float, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = data.get("samples", []) if isinstance(data, dict) else []
    points = []
    for item in samples:
        if "raster_x" not in item or "raster_y" not in item:
            continue
        elevation = item.get("elevation_m", item.get("elevation", item.get("z")))
        if elevation is None:
            continue
        points.append(
            DemPoint(
                parse_float(item.get("raster_x")),
                parse_float(item.get("raster_y")),
                parse_float(elevation),
                parse_float(item.get("station_m", item.get("station"))),
            )
        )
    if len(points) < 2:
        raise SystemExit(f"Profile has no positioned samples with raster_x/raster_y: {path}")
    return [DemLine("center", 0.0, points)], 0.0, data


def load_height_source(cache_path: pathlib.Path | None, profile_path: pathlib.Path | None) -> tuple[list[DemLine], float, dict]:
    if cache_path is not None and profile_path is not None:
        raise SystemExit("Use either --elevation-cache or --profile, not both")
    if profile_path is not None:
        return load_positioned_profile(profile_path)
    if cache_path is not None:
        return load_dem_cache(cache_path)
    raise SystemExit("Use --elevation-cache or --profile")


def source_uses_scaled_fit(data: dict) -> bool:
    fit = data.get("fit") if isinstance(data, dict) else None
    if not isinstance(fit, dict):
        return False
    return abs(parse_float(fit.get("scale"), 1.0) - 1.0) > 1e-9


def center_dem_line(lines: list[DemLine]) -> DemLine:
    centers = [line for line in lines if line.side == "center"]
    if centers:
        return min(centers, key=lambda line: abs(line.distance))
    return min(lines, key=lambda line: abs(line.distance))


def dedupe_loop_points(points: list[DemPoint], epsilon: float = 1e-6) -> list[DemPoint]:
    if len(points) >= 2 and math.hypot(points[0].x - points[-1].x, points[0].y - points[-1].y) <= epsilon:
        return points[:-1]
    return list(points)


def loop_stations(points: list[DemPoint]) -> tuple[list[float], float]:
    stations = [0.0]
    total = 0.0
    for i in range(1, len(points)):
        total += math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y)
        stations.append(total)
    if len(points) > 2:
        total += math.hypot(points[0].x - points[-1].x, points[0].y - points[-1].y)
    return stations, total


def dem_point_at_loop_station(points: list[DemPoint], stations: list[float], total: float, station: float) -> DemPoint:
    if not points:
        return DemPoint(0.0, 0.0, 0.0, 0.0)
    if len(points) == 1 or total <= 1e-9:
        return points[0]
    s = station % total
    for i in range(1, len(points)):
        if s <= stations[i]:
            a = points[i - 1]
            b = points[i]
            span = stations[i] - stations[i - 1]
            t = 0.0 if span <= 1e-9 else (s - stations[i - 1]) / span
            return DemPoint(a.x + t * (b.x - a.x), a.y + t * (b.y - a.y), a.z + t * (b.z - a.z), s)
    a = points[-1]
    b = points[0]
    span = total - stations[-1]
    t = 0.0 if span <= 1e-9 else (s - stations[-1]) / span
    return DemPoint(a.x + t * (b.x - a.x), a.y + t * (b.y - a.y), a.z + t * (b.z - a.z), s)


def resample_dem_loop(points: list[DemPoint], count: int) -> tuple[list[dict], float]:
    clean = dedupe_loop_points(points)
    stations, total = loop_stations(clean)
    count = max(8, count)
    out = []
    for i in range(count):
        p = dem_point_at_loop_station(clean, stations, total, total * i / count)
        out.append({"x": p.x, "y": p.y, "z": p.z, "s": total * i / count})
    return out, total


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


def resample_track_loop(segments: list[Segment], total: float, count: int) -> list[dict]:
    plan = sample_track_plan(segments, 3.0)
    out = []
    for i in range(max(8, count)):
        sample = interpolate_track_plan(plan, total * i / max(8, count), total)
        out.append({"x": sample.x, "y": sample.y, "s": sample.s, "seg": sample.segment})
    return out


def rigid_fit(source: list[dict], target: list[dict], allow_scale: bool = False) -> dict:
    n = min(len(source), len(target))
    sx = sum(source[i]["x"] for i in range(n)) / n
    sy = sum(source[i]["y"] for i in range(n)) / n
    tx = sum(target[i]["x"] for i in range(n)) / n
    ty = sum(target[i]["y"] for i in range(n)) / n
    a = 0.0
    b = 0.0
    var = 0.0
    for i in range(n):
        ux = source[i]["x"] - sx
        uy = source[i]["y"] - sy
        vx = target[i]["x"] - tx
        vy = target[i]["y"] - ty
        a += ux * vx + uy * vy
        b += ux * vy - uy * vx
        var += ux * ux + uy * uy
    theta = math.atan2(b, a)
    c = math.cos(theta)
    s = math.sin(theta)
    scale = math.hypot(a, b) / var if allow_scale and var > 1e-12 else 1.0
    ox = tx - scale * (c * sx - s * sy)
    oy = ty - scale * (s * sx + c * sy)
    return {"theta": theta, "c": c, "s": s, "ox": ox, "oy": oy, "scale": scale}


def transform_xy(x: float, y: float, fit: FitResult | dict) -> tuple[float, float]:
    c = fit.c if isinstance(fit, FitResult) else fit["c"]
    s = fit.s if isinstance(fit, FitResult) else fit["s"]
    ox = fit.ox if isinstance(fit, FitResult) else fit["ox"]
    oy = fit.oy if isinstance(fit, FitResult) else fit["oy"]
    scale = fit.scale if isinstance(fit, FitResult) else fit.get("scale", 1.0)
    return scale * (c * x - s * y) + ox, scale * (s * x + c * y) + oy


def fit_rmse(source: list[dict], target: list[dict], fit: dict) -> float:
    n = min(len(source), len(target))
    err = 0.0
    for i in range(n):
        x, y = transform_xy(source[i]["x"], source[i]["y"], fit)
        dx = x - target[i]["x"]
        dy = y - target[i]["y"]
        err += dx * dx + dy * dy
    return math.sqrt(err / max(1, n))


def shifted(points: list[dict], shift: int) -> list[dict]:
    if not points:
        return []
    k = shift % len(points)
    return points[k:] + points[:k]


def source_fit_variants(base_source: list[dict], allow_reverse: bool) -> list[tuple[list[dict], bool]]:
    variants = [(base_source, False)]
    if allow_reverse:
        variants.append((list(reversed(base_source)), True))
    return variants


def evaluated_fit(
    track: list[dict],
    source: list[dict],
    shift: int,
    reversed_source: bool,
    allow_scale: bool,
) -> tuple[float, int, bool, dict]:
    target = shifted(source, shift)
    fit = rigid_fit(track, target, allow_scale)
    return fit_rmse(track, target, fit), shift, reversed_source, fit


def better_fit(
    best: tuple[float, int, bool, dict] | None,
    candidate: tuple[float, int, bool, dict],
) -> tuple[float, int, bool, dict]:
    if best is None or candidate[0] < best[0]:
        return candidate
    return best


def coarse_best_fit(
    track: list[dict],
    source_variants: list[tuple[list[dict], bool]],
    n: int,
    stride: int,
    allow_scale: bool,
) -> tuple[float, int, bool, dict]:
    best: tuple[float, int, bool, dict] | None = None
    for variant, reversed_source in source_variants:
        for shift in range(0, n, stride):
            best = better_fit(best, evaluated_fit(track, variant, shift, reversed_source, allow_scale))
    if best is None:
        raise RuntimeError("No elevation-diff alignment fit candidates were evaluated")
    return best


def source_variant_for_refinement(source_variants: list[tuple[list[dict], bool]], reversed_source: bool) -> list[dict]:
    if reversed_source and len(source_variants) > 1:
        return source_variants[1][0]
    return source_variants[0][0]


def refined_best_fit(
    track: list[dict],
    source_variants: list[tuple[list[dict], bool]],
    n: int,
    stride: int,
    best: tuple[float, int, bool, dict],
    allow_scale: bool,
) -> tuple[float, int, bool, dict]:
    if stride <= 1:
        return best
    _, coarse_shift, coarse_reversed, _ = best
    variant = source_variant_for_refinement(source_variants, coarse_reversed)
    for shift in range(coarse_shift - stride, coarse_shift + stride + 1):
        candidate = evaluated_fit(track, variant, shift, coarse_reversed, allow_scale)
        best = better_fit(best, (candidate[0], shift % n, candidate[2], candidate[3]))
    return best


def find_best_fit(
    track_points: list[dict],
    source_points: list[dict],
    source_total: float,
    shift_step: int,
    allow_reverse: bool,
    allow_scale: bool = False,
) -> FitResult:
    n = min(len(track_points), len(source_points))
    track = track_points[:n]
    base_source = source_points[:n]
    source_variants = source_fit_variants(base_source, allow_reverse)
    stride = max(1, shift_step)
    best = coarse_best_fit(track, source_variants, n, stride, allow_scale)
    best = refined_best_fit(track, source_variants, n, stride, best, allow_scale)
    rmse, shift, reversed_source, fit = best
    source_shift = source_total * (shift % n) / max(1, n)
    return FitResult(fit["theta"], fit["c"], fit["s"], fit["ox"], fit["oy"], rmse, source_shift, reversed_source, fit.get("scale", 1.0))


def hermite(p0: float, p1: float, t0: float, t1: float, t: float) -> float:
    t2 = t * t
    t3 = t * t2
    h1 = 3.0 * t2 - 2.0 * t3
    h0 = 1.0 - h1
    h2 = t3 - 2.0 * t2 + t
    h3 = t3 - t2
    return h0 * p0 + h1 * p1 + h2 * t0 + h3 * t1


def segment_starts(lengths: list[float]) -> list[float]:
    starts = []
    acc = 0.0
    for length in lengths:
        starts.append(acc)
        acc += length
    return starts


def track_z_at(segs: list[ET.Element], lengths: list[float], starts: list[float], station: float, total: float) -> tuple[float, str]:
    s = station % total
    for i, start in enumerate(starts):
        length = lengths[i]
        end = start + length
        if s <= end or i == len(starts) - 1:
            seg = segs[i]
            t = 0.0 if length <= 1e-9 else max(0.0, min(1.0, (s - start) / length))
            z0 = get_attnum(seg, "z start", 0.0)
            z1 = get_attnum(seg, "z end", z0)
            if (find_att(seg, "attstr", "profil") is not None and (find_att(seg, "attstr", "profil").get("val") or "") == "spline"):
                t0 = attnum_si(seg, "profil start tangent", 0.0) * length
                t1 = attnum_si(seg, "profil end tangent", 0.0) * length
                return hermite(z0, z1, t0, t1, t), seg.get("name", "")
            return z0 + t * (z1 - z0), seg.get("name", "")
    return 0.0, ""


def build_track_samples(
    segs: list[ET.Element],
    segments: list[Segment],
    lengths: list[float],
    total: float,
    sample_step: float,
) -> list[TrackPoint]:
    starts = segment_starts(lengths)
    plan = sample_track_plan(segments, min(3.0, max(1.0, sample_step)))
    count = max(3, int(math.ceil(total / max(1.0, sample_step))))
    samples = []
    for i in range(count):
        station = total * i / count
        p = interpolate_track_plan(plan, station, total)
        z, segment = track_z_at(segs, lengths, starts, station, total)
        samples.append(TrackPoint(station, p.x, p.y, p.heading, segment or p.segment, z))
    return samples


def nearest_height_on_lines(lines: list[DemLine], x: float, y: float) -> HeightHit:
    best: HeightHit | None = None
    best_d2 = float("inf")
    for line in lines:
        points = dedupe_loop_points(line.points)
        if len(points) < 2:
            continue
        stations, total = loop_stations(points)
        for i, a in enumerate(points):
            j = (i + 1) % len(points)
            b = points[j]
            ax = a.x
            ay = a.y
            vx = b.x - ax
            vy = b.y - ay
            wx = x - ax
            wy = y - ay
            vv = vx * vx + vy * vy
            t = 0.0 if vv <= 1e-12 else max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
            qx = ax + t * vx
            qy = ay + t * vy
            d2 = (x - qx) * (x - qx) + (y - qy) * (y - qy)
            if d2 >= best_d2:
                continue
            span = (total - stations[i]) if j == 0 else (stations[j] - stations[i])
            station = (stations[i] + t * max(0.0, span)) % max(total, 1e-9)
            z = a.z + t * (b.z - a.z)
            best_d2 = d2
            best = HeightHit(z, math.sqrt(d2), station, line.side, line.distance)
    if best is None:
        raise SystemExit("DEM height lookup failed: no usable line segments")
    return best


def transformed_track_point(point: TrackPoint, fit: FitResult) -> tuple[float, float, float]:
    x, y = transform_xy(point.x, point.y, fit)
    return x, y, point.heading + fit.theta


def build_diff_samples(track_samples: list[TrackPoint], height_lines: list[DemLine], fit: FitResult, dem_zero: float) -> list[DiffSample]:
    out = []
    for sample in track_samples:
        x, y, heading = transformed_track_point(sample, fit)
        hit = nearest_height_on_lines(height_lines, x, y)
        dem_z = hit.z - dem_zero
        out.append(
            DiffSample(sample.station, sample.segment, x, y, heading, sample.z, dem_z, sample.z - dem_z, hit.distance, hit.station)
        )
    return out


def mix_color(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    t = max(0.0, min(1.0, t))
    r = round(a[0] + (b[0] - a[0]) * t)
    g = round(a[1] + (b[1] - a[1]) * t)
    bl = round(a[2] + (b[2] - a[2]) * t)
    return f"#{r:02x}{g:02x}{bl:02x}"


def color_for_diff(diff: float, color_range: float) -> str:
    white = (255, 255, 255)
    red = (220, 38, 38)
    blue = (37, 99, 235)
    scale = abs(diff) / max(1e-9, color_range)
    return mix_color(white, red if diff > 0.0 else blue, scale)


def color_for_elevation(z: float, min_z: float, max_z: float) -> str:
    t = 0.5 if max_z <= min_z else (z - min_z) / (max_z - min_z)
    if t <= 0.5:
        return mix_color((20, 83, 45), (250, 204, 21), t * 2.0)
    return mix_color((250, 204, 21), (124, 45, 18), (t - 0.5) * 2.0)


def source_edge_points(points: list[DemPoint], offset: float) -> list[tuple[float, float]]:
    clean = dedupe_loop_points(points)
    out = []
    n = len(clean)
    for i, p in enumerate(clean):
        prev_p = clean[(i - 1) % n]
        next_p = clean[(i + 1) % n]
        heading = math.atan2(next_p.y - prev_p.y, next_p.x - prev_p.x)
        out.append((p.x - math.sin(heading) * offset, p.y + math.cos(heading) * offset))
    if out:
        out.append(out[0])
    return out


def track_edge_points(samples: list[DiffSample], offset: float) -> list[tuple[float, float]]:
    out = [(p.x - math.sin(p.heading) * offset, p.y + math.cos(p.heading) * offset) for p in samples]
    if out:
        out.append(out[0])
    return out


def polyline_points(points: list[tuple[float, float]], mapper) -> str:  # noqa: ANN001
    return " ".join(f"{mapper(x, y)[0]:.2f},{mapper(x, y)[1]:.2f}" for x, y in points)


def build_mapper(points: list[tuple[float, float]], width: float, pad: float):  # noqa: ANN201
    min_x = min(x for x, _ in points)
    max_x = max(x for x, _ in points)
    min_y = min(y for _, y in points)
    max_y = max(y for _, y in points)
    bbox_w = max(1.0, max_x - min_x)
    bbox_h = max(1.0, max_y - min_y)
    scale = (width - 2.0 * pad) / bbox_w
    height = bbox_h * scale + 2.0 * pad

    def mapper(x: float, y: float) -> tuple[float, float]:
        return pad + (x - min_x) * scale, height - (pad + (y - min_y) * scale)

    return mapper, height


def dem_line_segments_svg(lines: list[DemLine], mapper, dem_zero: float) -> list[str]:  # noqa: ANN001
    elevations = [p.z - dem_zero for line in lines for p in line.points]
    min_z = min(elevations, default=0.0)
    max_z = max(elevations, default=1.0)
    out = []
    for line in lines:
        points = line.points
        for i in range(1, len(points)):
            a = points[i - 1]
            b = points[i]
            x1, y1 = mapper(a.x, a.y)
            x2, y2 = mapper(b.x, b.y)
            color = color_for_elevation(0.5 * (a.z + b.z) - dem_zero, min_z, max_z)
            stroke_width = 2.4 if line.side == "center" else 1.3
            out.append(
                f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
                f'stroke="{color}" stroke-width="{stroke_width:.1f}" stroke-opacity="0.55"/>'
            )
    return out


def legend_svg(color_range: float, legend_step: float) -> list[str]:
    out = [
        '<g id="legend">',
        '<rect x="18" y="18" width="455" height="178" rx="10" fill="#020617" fill-opacity="0.88" stroke="#64748b"/>',
        '<text x="36" y="48" fill="#f8fafc" font-family="Consolas, monospace" font-size="18">Elevation difference</text>',
        '<text x="36" y="72" fill="#cbd5e1" font-family="Consolas, monospace" font-size="13">diff = track z - DEM z (m)</text>',
        '<text x="36" y="94" fill="#cbd5e1" font-family="Consolas, monospace" font-size="13">red: track too high, blue: track too low</text>',
    ]
    step = max(1.0, legend_step)
    values = []
    v = -abs(color_range)
    while v <= abs(color_range) + 1e-9:
        values.append(v)
        v += step
    if 0.0 not in values:
        values.append(0.0)
        values.sort()
    x0 = 38.0
    y0 = 112.0
    cell = 380.0 / max(1, len(values))
    for i, value in enumerate(values):
        color = color_for_diff(value, color_range)
        x = x0 + i * cell
        out.append(f'<rect x="{x:.2f}" y="{y0:.2f}" width="{cell + 0.5:.2f}" height="16" fill="{color}"/>')
    for value in (-abs(color_range), 0.0, abs(color_range)):
        idx = min(range(len(values)), key=lambda i: abs(values[i] - value))
        x = x0 + idx * cell
        out.append(f'<text x="{x:.2f}" y="151" fill="#e2e8f0" font-family="Consolas, monospace" font-size="12">{value:+.0f}</text>')
    out.extend(
        [
            '<line x1="38" y1="166" x2="98" y2="166" stroke="#22c55e" stroke-width="4" stroke-dasharray="10 7"/>',
            '<text x="108" y="171" fill="#bbf7d0" font-family="Consolas, monospace" font-size="13">real/source road outline</text>',
            '<line x1="278" y1="166" x2="338" y2="166" stroke="#0f172a" stroke-width="5"/>',
            '<text x="348" y="171" fill="#cbd5e1" font-family="Consolas, monospace" font-size="13">TORCS outline</text>',
            "</g>",
        ]
    )
    return out


def write_svg(
    path: pathlib.Path,
    dem_lines: list[DemLine],
    source_center: DemLine,
    diff_samples: list[DiffSample],
    track_width: float,
    dem_zero: float,
    color_range: float,
    legend_step: float,
    label_top: int,
    width: float,
    pad: float,
) -> None:
    half_width = 0.5 * track_width
    source_left = source_edge_points(source_center.points, half_width)
    source_right = source_edge_points(source_center.points, -half_width)
    source_center_xy = [(p.x, p.y) for p in dedupe_loop_points(source_center.points)]
    if source_center_xy:
        source_center_xy.append(source_center_xy[0])
    track_left = track_edge_points(diff_samples, half_width)
    track_right = track_edge_points(diff_samples, -half_width)
    sample_xy = [(p.x, p.y) for p in diff_samples]
    all_points = source_left + source_right + source_center_xy + track_left + track_right + sample_xy
    for line in dem_lines:
        all_points.extend((p.x, p.y) for p in line.points)
    mapper, height = build_mapper(all_points, width, pad)

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.2f} {height:.2f}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#f8fafc"/>',
        '<g id="dem-height-map">',
        *dem_line_segments_svg(dem_lines, mapper, dem_zero),
        "</g>",
    ]
    if source_left and source_right:
        out.extend(
            [
                '<g id="real-track-outline" fill="none" stroke="#22c55e" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round" '
                'stroke-dasharray="10 7" opacity="0.92">',
                f'<polyline points="{polyline_points(source_left, mapper)}"/>',
                f'<polyline points="{polyline_points(source_right, mapper)}"/>',
                "</g>",
                '<g id="real-track-center" fill="none" stroke="#064e3b" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" opacity="0.65">',
                f'<polyline points="{polyline_points(source_center_xy, mapper)}"/>',
                "</g>",
            ]
        )
    out.extend(
        [
            '<g id="torcs-track-outline" fill="none" stroke="#0f172a" stroke-width="4.2" stroke-linejoin="round" stroke-linecap="round" opacity="0.86">',
            f'<polyline points="{polyline_points(track_left, mapper)}"/>',
            f'<polyline points="{polyline_points(track_right, mapper)}"/>',
            "</g>",
            '<g id="difference-centerline" fill="none" stroke-linejoin="round" stroke-linecap="round">',
        ]
    )
    for i in range(1, len(diff_samples)):
        a = diff_samples[i - 1]
        b = diff_samples[i]
        x1, y1 = mapper(a.x, a.y)
        x2, y2 = mapper(b.x, b.y)
        color = color_for_diff(0.5 * (a.diff + b.diff), color_range)
        out.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="8.0"/>')
    if len(diff_samples) > 2:
        a = diff_samples[-1]
        b = diff_samples[0]
        x1, y1 = mapper(a.x, a.y)
        x2, y2 = mapper(b.x, b.y)
        color = color_for_diff(0.5 * (a.diff + b.diff), color_range)
        out.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="8.0"/>')
    out.extend(
        [
            "</g>",
            '<g id="difference-samples">',
        ]
    )
    for sample in diff_samples:
        x, y = mapper(sample.x, sample.y)
        color = color_for_diff(sample.diff, color_range)
        title = html.escape(
            f"s={sample.station:.1f}m seg={sample.segment} diff={sample.diff:+.2f}m "
            f"track={sample.track_z:.2f}m dem={sample.dem_z:.2f}m plan_d={sample.plan_distance:.2f}m"
        )
        out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.6" fill="{color}" stroke="#020617" stroke-width="0.85"><title>{title}</title></circle>')
    out.append("</g>")

    labels = sorted(diff_samples, key=lambda item: abs(item.diff), reverse=True)[: max(0, label_top)]
    out.append('<g id="top-difference-labels" font-family="Consolas, monospace" font-size="12" font-weight="700">')
    for sample in labels:
        x, y = mapper(sample.x, sample.y)
        color = "#991b1b" if sample.diff > 0.0 else "#1d4ed8"
        out.append(f'<text x="{x + 7:.2f}" y="{y - 7:.2f}" fill="{color}" stroke="#ffffff" stroke-width="2" paint-order="stroke">{sample.diff:+.1f}</text>')
    out.append("</g>")
    out.extend(legend_svg(color_range, legend_step))
    out.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def report_summary(
    diff_samples: list[DiffSample],
    fit: FitResult,
    dem_zero: float,
    track_total: float,
    source_total: float,
    output: pathlib.Path,
    map_cache: pathlib.Path | None,
    map_lines: str,
) -> dict:
    diffs = [sample.diff for sample in diff_samples]
    plan_distances = [sample.plan_distance for sample in diff_samples]
    max_high = max(diff_samples, key=lambda sample: sample.diff)
    max_low = min(diff_samples, key=lambda sample: sample.diff)
    max_abs = max(diff_samples, key=lambda sample: abs(sample.diff))

    def sample_obj(sample: DiffSample) -> dict:
        return {
            "station_m": sample.station,
            "segment": sample.segment,
            "track_z_m": sample.track_z,
            "dem_z_m": sample.dem_z,
            "difference_track_minus_dem_m": sample.diff,
            "plan_distance_to_dem_m": sample.plan_distance,
            "source_station_m": sample.source_station,
        }

    return {
        "output_svg": str(output),
        "map_elevation_cache": str(map_cache) if map_cache is not None else "",
        "map_lines": map_lines,
        "sample_count": len(diff_samples),
        "track_length_m": track_total,
        "source_fit_length_m": source_total,
        "dem_zero_m": dem_zero,
        "difference_definition": "track_z_m - dem_z_m; red means track too high, blue means track too low",
        "mean_difference_m": sum(diffs) / max(1, len(diffs)),
        "rmse_difference_m": math.sqrt(sum(d * d for d in diffs) / max(1, len(diffs))),
        "mean_abs_difference_m": sum(abs(d) for d in diffs) / max(1, len(diffs)),
        "max_too_high": sample_obj(max_high),
        "max_too_low": sample_obj(max_low),
        "max_abs_difference": sample_obj(max_abs),
        "top_too_high": [sample_obj(sample) for sample in sorted(diff_samples, key=lambda item: item.diff, reverse=True)[:10]],
        "top_too_low": [sample_obj(sample) for sample in sorted(diff_samples, key=lambda item: item.diff)[:10]],
        "plan_fit": {
            "rmse_m": fit.rmse,
            "rotation_deg": math.degrees(fit.theta),
            "scale": fit.scale,
            "source_shift_m": fit.source_shift_m,
            "source_reversed": fit.source_reversed,
            "mean_distance_to_dem_m": sum(plan_distances) / max(1, len(plan_distances)),
            "max_distance_to_dem_m": max(plan_distances, default=0.0),
        },
    }


def write_profile_output(
    path: pathlib.Path,
    diff_samples: list[DiffSample],
    track_xml: pathlib.Path,
    source_path: pathlib.Path,
    track_total: float,
    fit: FitResult,
) -> None:
    samples = [
        {
            "station_m": sample.station,
            "elevation_m": sample.dem_z,
            "weight": 1.0,
        }
        for sample in diff_samples
    ]
    obj = {
        "schema": 1,
        "type": "plan-fit-dem-profile",
        "track_xml": str(track_xml),
        "elevation_source": str(source_path),
        "total_length_m": track_total,
        "samples": samples,
        "fit": {
            "rmse_m": fit.rmse,
            "rotation_deg": math.degrees(fit.theta),
            "scale": fit.scale,
            "source_shift_m": fit.source_shift_m,
            "source_reversed": fit.source_reversed,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def render_paths(args: argparse.Namespace) -> RenderPaths:
    cache_path = pathlib.Path(args.elevation_cache) if args.elevation_cache else None
    profile_path = pathlib.Path(args.profile) if args.profile else None
    return RenderPaths(
        track_xml=pathlib.Path(args.track_xml),
        cache_path=cache_path,
        profile_path=profile_path,
        source_path=profile_path or cache_path,
        map_cache_path=pathlib.Path(args.map_elevation_cache) if args.map_elevation_cache else None,
        output=pathlib.Path(args.output),
    )


def validate_render_paths(paths: RenderPaths) -> None:
    if not paths.track_xml.exists():
        raise SystemExit(f"Track XML not found: {paths.track_xml}")
    if paths.cache_path is not None and not paths.cache_path.exists():
        raise SystemExit(f"Elevation cache not found: {paths.cache_path}")
    if paths.profile_path is not None and not paths.profile_path.exists():
        raise SystemExit(f"Profile not found: {paths.profile_path}")


def load_height_context(args: argparse.Namespace, paths: RenderPaths) -> HeightSourceContext:
    dem_lines, cache_zero, source_data = load_height_source(paths.cache_path, paths.profile_path)
    map_dem_lines_all = load_dem_cache(paths.map_cache_path)[0] if paths.map_cache_path is not None else dem_lines
    map_dem_lines = [center_dem_line(map_dem_lines_all)] if args.map_lines == "center" else map_dem_lines_all
    source_center = center_dem_line(dem_lines)
    height_lines = [source_center] if args.height_lines == "center" else dem_lines
    return HeightSourceContext(dem_lines, cache_zero, source_data, map_dem_lines, source_center, height_lines)


def build_track_render_context(
    args: argparse.Namespace,
    track_xml: pathlib.Path,
    source_center: DemLine,
    source_data: dict,
) -> TrackRenderContext:
    main_track, segs, segments, lengths, track_total = load_track(track_xml)
    track_width = get_attnum(main_track, "width", 12.0)
    source_fit_samples, source_total = resample_dem_loop(source_center.points, args.fit_samples)
    track_fit_samples = resample_track_loop(segments, track_total, args.fit_samples)
    allow_scale_fit = args.allow_scale_fit or source_uses_scaled_fit(source_data)
    fit = find_best_fit(track_fit_samples, source_fit_samples, source_total, args.fit_shift_step, args.allow_reverse_source, allow_scale_fit)
    track_samples = build_track_samples(segs, segments, lengths, track_total, args.sample_step)
    return TrackRenderContext(track_total, source_total, track_width, fit, track_samples)


def select_dem_zero(
    args: argparse.Namespace,
    track_samples: list[TrackPoint],
    fit: FitResult,
    height_lines: list[DemLine],
    cache_zero: float,
) -> float:
    start_x, start_y, _ = transformed_track_point(track_samples[0], fit)
    if args.dem_zero == "track-start":
        return nearest_height_on_lines(height_lines, start_x, start_y).z
    if args.dem_zero == "cache-start":
        return cache_zero
    return 0.0


def write_render_outputs(
    args: argparse.Namespace,
    paths: RenderPaths,
    height_context: HeightSourceContext,
    track_context: TrackRenderContext,
    dem_zero: float,
    diff_samples: list[DiffSample],
) -> dict:
    write_svg(
        paths.output,
        height_context.map_dem_lines,
        height_context.source_center,
        diff_samples,
        track_context.track_width,
        dem_zero,
        max(1.0, args.color_range),
        max(1.0, args.legend_step),
        args.label_top,
        max(400.0, args.width),
        max(10.0, args.pad),
    )
    report = report_summary(
        diff_samples,
        track_context.fit,
        dem_zero,
        track_context.track_total,
        track_context.source_total,
        paths.output,
        paths.map_cache_path,
        args.map_lines,
    )
    if args.profile_output:
        if paths.source_path is None:
            raise RuntimeError("Profile output requires a source polyline path")
        write_profile_output(
            pathlib.Path(args.profile_output),
            diff_samples,
            paths.track_xml,
            paths.source_path,
            track_context.track_total,
            track_context.fit,
        )
    if args.report:
        report_path = pathlib.Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def print_render_summary(
    args: argparse.Namespace,
    output: pathlib.Path,
    diff_samples: list[DiffSample],
    fit: FitResult,
    report: dict,
) -> None:
    print(f"Wrote SVG: {output}")
    if args.report:
        print(f"Wrote report: {args.report}")
    if args.profile_output:
        print(f"Wrote profile: {args.profile_output}")
    print(f"Samples: {len(diff_samples)} at ~{args.sample_step:.1f} m")
    print(f"Fit RMSE: {fit.rmse:.2f} m, source shift: {fit.source_shift_m:.1f} m")
    print(f"Max too high: {report['max_too_high']['difference_track_minus_dem_m']:+.2f} m at s={report['max_too_high']['station_m']:.1f}")
    print(f"Max too low: {report['max_too_low']['difference_track_minus_dem_m']:+.2f} m at s={report['max_too_low']['station_m']:.1f}")


def main() -> int:
    args = parse_args()
    paths = render_paths(args)
    validate_render_paths(paths)
    height_context = load_height_context(args, paths)
    track_context = build_track_render_context(args, paths.track_xml, height_context.source_center, height_context.source_data)
    dem_zero = select_dem_zero(
        args,
        track_context.track_samples,
        track_context.fit,
        height_context.height_lines,
        height_context.cache_zero,
    )
    diff_samples = build_diff_samples(track_context.track_samples, height_context.height_lines, track_context.fit, dem_zero)
    report = write_render_outputs(args, paths, height_context, track_context, dem_zero, diff_samples)
    print_render_summary(args, paths.output, diff_samples, track_context.fit, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
