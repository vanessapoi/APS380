#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : apply_elevation.py
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

"""Apply a smooth station/elevation profile and relief-only terrain.

This tool intentionally runs after layout, curbs, and pitlane work. It only
adds vertical profile attributes and a trackgen relief .ac file; it never splits
or changes the plan-view segments, so a new loop-closing round is not needed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace

import numpy as np
from PIL import Image
from skimage import measure

from torcs_track_tools.cli.import_elevation_raster import open_raster
from torcs_track_tools.core.geometry import Pose, Sample, Segment, sample_segment
from torcs_track_tools.core.polyline import to_xy_tuples
from torcs_track_tools.core.track_xml import (
    child_section,
    find_att,
    get_attnum,
    get_attstr,
    get_or_make_child_section,
    parse_xml_preserve_prolog,
    segment_from_element,
    segment_length,
    segment_sections,
    serialize_xml_restore_entity,
    set_attnum,
    set_attstr,
    side_width_profile,
)

MIN_TANGENT_SEGMENT_LENGTH_M = 0.1


@dataclass(frozen=True)
class ProfileSample:
    station: float
    elevation: float
    weight: float = 1.0


@dataclass(frozen=True)
class LandmarkRange:
    name: str
    start: float
    end: float


@dataclass(frozen=True)
class StationMapPoint:
    xml_station: float
    source_station: float


@dataclass(frozen=True)
class ProfileSource:
    name: str
    samples: list[ProfileSample]
    weight: float = 1.0
    source_total: float = 0.0
    landmarks: tuple[LandmarkRange, ...] = ()
    station_map: tuple[StationMapPoint, ...] = ()
    source_shift_m: float = 0.0
    source_reversed: bool = False
    real_width_m: float = 0.0
    has_source_mapping: bool = False


@dataclass(frozen=True)
class BoundaryProfile:
    stations: list[float]
    elevations: list[float]
    tangents: list[float]
    raw_elevations: list[float]
    pit_ranges: list[dict]


@dataclass(frozen=True)
class BankingProfile:
    stations: list[float]
    banking_deg: list[float]
    raw_banking_deg: list[float]


@dataclass(frozen=True)
class TerrainLine:
    """DEM corridor line retained in its source station and lateral-distance frame."""

    side: str
    distance: float
    samples: list[ProfileSample]
    source_name: str = ""
    source_total: float = 0.0
    station_map: tuple[StationMapPoint, ...] = ()
    zero_offset: float = 0.0
    source_shift_m: float | None = None
    source_reversed: bool = False
    source_scale: float = 1.0


@dataclass(frozen=True)
class TerrainFit:
    """Plan-fit metadata keyed by the canonical elevation-source path."""

    source_name: str
    source_shift_m: float
    source_reversed: bool = False
    scale: float = 1.0


@dataclass(frozen=True)
class ReliefEdgePoint:
    """Outer-edge geometry with nominal XML station and local centerline distance."""

    x: float
    y: float
    station: float
    center_distance: float = 0.0
    outward_x: float = 0.0
    outward_y: float = 0.0


@dataclass(frozen=True)
class ReliefValidationIssue:
    line_index: int
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class ReliefValidationResult:
    issues: tuple[ReliefValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.reason] = counts.get(issue.reason, 0) + 1
        return counts


@dataclass(frozen=True)
class TerrainElevationMap:
    path: pathlib.Path
    xml_value: str
    width: int
    height: int
    min_altitude: float
    max_altitude: float
    track_z_offset: float
    bounds: tuple[float, float, float, float]
    source_profile: str
    raster: str
    missing_sample_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply smooth elevation and relief terrain to a TORCS track XML")
    parser.add_argument("--track-xml", required=True, help="Track XML to update in-place unless --output-xml is supplied")
    parser.add_argument("--output-xml", default="", help="Optional output XML path; defaults to --track-xml")
    parser.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Station/elevation profile JSON or CSV. Can be passed more than once; sources are fused by weighted average.",
    )
    parser.add_argument(
        "--elevation-cache",
        action="append",
        default=[],
        help="DEM corridor cache from torcs-fetch-elevation; used for both road profile and relief terrain heights.",
    )
    parser.add_argument(
        "--no-align-source-landmarks",
        dest="align_source_landmarks",
        action="store_false",
        default=True,
        help="Disable automatic source-to-XML station warping using matching source way names and XML segment names.",
    )
    parser.add_argument(
        "--point",
        action="append",
        default=[],
        help="Inline station/elevation control point as station:elevation or station,elevation. Repeat for quick/manual profiles.",
    )
    parser.add_argument("--smooth-window", type=float, default=80.0, help="Gaussian denoise window in meters")
    parser.add_argument("--smooth-step", type=float, default=5.0, help="Internal dense profile sampling step in meters")
    parser.add_argument("--smooth-iters", type=int, default=2, help="Number of denoise passes")
    parser.add_argument(
        "--pit-flatten-strength", type=float, default=0.85, help="Blend protected pit boxes toward a straight vertical ramp"
    )
    parser.add_argument(
        "--apply-banking", action="store_true", help="Apply banking_deg samples from road-surface profiles as segment banking start/end"
    )
    parser.add_argument(
        "--banking-profile-only",
        action="store_true",
        help="Apply only banking from road-surface profiles; do not rewrite elevation or relief attributes",
    )
    parser.add_argument("--bank-smooth-window", type=float, default=0.0, help="Gaussian denoise window for banking in meters")
    parser.add_argument("--bank-smooth-step", type=float, default=5.0, help="Internal dense banking profile sampling step in meters")
    parser.add_argument("--bank-smooth-iters", type=int, default=1, help="Number of banking denoise passes")
    parser.add_argument("--bank-median-window", type=float, default=0.0, help="Median filter window for banking spike removal in meters")
    parser.add_argument("--bank-max-abs-deg", type=float, default=45.0, help="Clamp absolute banking angle before writing XML")
    parser.add_argument("--bank-max-rate-deg-per-m", type=float, default=0.0, help="Reserved banking rate limit; 0 disables")
    parser.add_argument(
        "--bank-width-policy", choices=("angle", "edge-delta"), default="angle", help="Preserve banking angle or real-road edge delta"
    )
    parser.add_argument("--bank-real-width", type=float, default=0.0, help="Real road width used by --bank-width-policy edge-delta")
    parser.add_argument("--pit-side-banking", choices=("tangent", "level"), default="tangent", help="Reserved pit side banking policy")
    parser.add_argument(
        "--bank-source-sign",
        choices=("auto", "preserve", "flip"),
        default="auto",
        help="Banking sign handling for reversed source profiles",
    )
    parser.add_argument("--relief-output", default="", help="Optional relief .ac output path; defaults beside XML as <track>-relief.ac")
    parser.add_argument(
        "--relief-distances",
        default="none",
        help="Comma-separated terrain control distances from each road edge in meters, or 'none' to disable relief constraints",
    )
    parser.add_argument(
        "--relief-interior-max-distance",
        type=float,
        default=30.0,
        help="Maximum infield relief distance; larger distances are exterior-only to avoid trackgen insertion warnings",
    )
    parser.add_argument("--relief-sample-step", type=float, default=50.0, help="Spacing of relief control points along the track")
    parser.add_argument(
        "--relief-height-falloff", type=float, default=260.0, help="Damp terrain height away from road; <=0 keeps full height"
    )
    parser.add_argument(
        "--terrain-elevation-map",
        default="",
        help="Optional PNG elevation map for trackgen terrain. Use 'auto' to write <track>-terrain-elevation.png beside the XML.",
    )
    parser.add_argument("--terrain-elevation-width", type=int, default=1024, help="Width in pixels for --terrain-elevation-map")
    parser.add_argument(
        "--terrain-elevation-resampling",
        choices=("bilinear", "nearest"),
        default="bilinear",
        help="Raster resampling used for terrain elevation map",
    )
    parser.add_argument("--report", default="", help="Optional JSON report path")
    parser.add_argument("--dry-run", action="store_true", help="Only write the optional report; do not update XML or relief file")
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


def remove_att(section: ET.Element, tag: str, name: str) -> None:
    att = find_att(section, tag, name)
    if att is not None:
        section.remove(att)


def parse_profile_point(text: str) -> ProfileSample:
    sep = ":" if ":" in text else ","
    parts = [p.strip() for p in text.split(sep)]
    if len(parts) != 2:
        raise SystemExit(f"Invalid --point value: {text}")
    return ProfileSample(parse_float(parts[0]), parse_float(parts[1]), 1.0)


def sample_from_mapping(item: dict, default_weight: float) -> ProfileSample:
    station = item.get(
        "source_station_m", item.get("station_m", item.get("station", item.get("s", item.get("distance_m", item.get("distance")))))
    )
    elevation = item.get("elevation_m", item.get("elevation", item.get("z", item.get("height_m", item.get("height")))))
    if station is None or elevation is None:
        raise SystemExit(f"Profile sample needs station and elevation fields: {item}")
    return ProfileSample(parse_float(station), parse_float(elevation), parse_float(item.get("weight"), default_weight))


def banking_sample_from_mapping(item: dict, default_weight: float) -> ProfileSample:
    station = item.get(
        "source_station_m", item.get("station_m", item.get("station", item.get("s", item.get("distance_m", item.get("distance")))))
    )
    banking = item.get("banking_deg", item.get("bank_deg", item.get("banking", item.get("bank"))))
    if station is None or banking is None:
        raise SystemExit(f"Banking sample needs station and banking_deg fields: {item}")
    return ProfileSample(parse_float(station), parse_float(banking), parse_float(item.get("weight"), default_weight))


def clean_landmark_name(name: str) -> str:
    text = name.strip()
    if not text:
        return ""
    if text.startswith("pit_") or text.startswith("draft") or text.startswith("Closure "):
        return ""
    base, sep, suffix = text.rpartition("-")
    if sep and suffix.isdigit() and base:
        return base
    return text


def cache_polyline_path(data: dict, cache_path: pathlib.Path) -> pathlib.Path | None:
    for key in ("source_polyline", "polyline"):
        raw_path = data.get(key)
        if raw_path:
            path = pathlib.Path(str(raw_path))
            if path.exists():
                return path
            relative = cache_path.parent / path
            if relative.exists():
                return relative
    source = data.get("source") or {}
    raw = source.get("polyline")
    if not raw:
        return None
    path = pathlib.Path(str(raw))
    if path.exists():
        return path
    relative = cache_path.parent / path
    if relative.exists():
        return relative
    return None


def station_map_from_mapping(data: dict) -> tuple[StationMapPoint, ...]:
    mapping = data.get("mapping") if isinstance(data.get("mapping"), dict) else {}
    raw_points = mapping.get("station_map", data.get("station_map", [])) if isinstance(mapping, dict) else data.get("station_map", [])
    points = []
    for item in raw_points or []:
        if not isinstance(item, dict):
            continue
        xml_station = item.get("xml_station_m", item.get("xml_station", item.get("station_m")))
        source_station = item.get("source_station_m", item.get("source_station"))
        if xml_station is None or source_station is None:
            continue
        points.append(StationMapPoint(parse_float(xml_station), parse_float(source_station)))
    return tuple(sorted(points, key=lambda p: p.xml_station))


def profile_mapping_info(
    data: dict, path: pathlib.Path
) -> tuple[float, tuple[LandmarkRange, ...], tuple[StationMapPoint, ...], float, bool, float, bool]:
    mapping = data.get("mapping") if isinstance(data.get("mapping"), dict) else {}
    source_total = parse_float(
        data.get("source_total_length_m", data.get("source_fit_length_m", data.get("total_length_m"))),
        0.0,
    )
    source_shift = parse_float(
        mapping.get("source_shift_m", data.get("source_shift_m", 0.0)) if isinstance(mapping, dict) else data.get("source_shift_m", 0.0),
        0.0,
    )
    source_reversed = bool(
        mapping.get("source_reversed", data.get("source_reversed", False))
        if isinstance(mapping, dict)
        else data.get("source_reversed", False)
    )
    has_source_mapping = isinstance(mapping, dict) and ("source_shift_m" in mapping or "source_reversed" in mapping or "method" in mapping)
    sampling = data.get("sampling") if isinstance(data.get("sampling"), dict) else {}
    real_width = parse_float(
        sampling.get("real_road_width_m", data.get("real_road_width_m", 0.0))
        if isinstance(sampling, dict)
        else data.get("real_road_width_m", 0.0),
        0.0,
    )
    return (
        source_total,
        read_cache_landmarks(data, path),
        station_map_from_mapping(data),
        source_shift,
        source_reversed,
        real_width,
        has_source_mapping,
    )


def landmark_ranges_from_polyline(polyline_path: pathlib.Path) -> tuple[LandmarkRange, ...]:
    data = json.loads(polyline_path.read_text(encoding="utf-8"))
    raw_points = data.get("polyline", []) if isinstance(data, dict) else []
    if len(raw_points) < 2:
        return ()
    xy = to_xy_tuples(raw_points, raw_points[0])
    stations = [0.0]
    for i in range(1, len(raw_points)):
        stations.append(stations[-1] + math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]))

    ranges: list[LandmarkRange] = []
    current_name = ""
    current_start = 0.0
    current_end = 0.0
    for point, station in zip(raw_points, stations, strict=True):
        name = clean_landmark_name(str(point.get("way_name", point.get("name", ""))))
        if name != current_name:
            if current_name:
                ranges.append(LandmarkRange(current_name, current_start, current_end))
            current_name = name
            current_start = station
        current_end = station
    if current_name:
        ranges.append(LandmarkRange(current_name, current_start, current_end))
    return tuple(ranges)


def read_cache_landmarks(data: object, path: pathlib.Path) -> tuple[LandmarkRange, ...]:
    if not isinstance(data, dict):
        return ()
    polyline_path = cache_polyline_path(data, path)
    if polyline_path is None:
        return ()
    return landmark_ranges_from_polyline(polyline_path)


def csv_profile_columns(rows: list[list[str]]) -> tuple[int, int, int, list[list[str]]]:
    header = [c.strip().lower() for c in rows[0]]
    if any(h in header for h in ("station_m", "station", "s", "distance_m", "distance")):
        station_idx = next(i for i, h in enumerate(header) if h in ("station_m", "station", "s", "distance_m", "distance"))
        elevation_idx = next(i for i, h in enumerate(header) if h in ("elevation_m", "elevation", "z", "height_m", "height"))
        weight_idx = next((i for i, h in enumerate(header) if h == "weight"), -1)
        return station_idx, elevation_idx, weight_idx, rows[1:]
    return 0, 1, 2 if len(rows[0]) > 2 else -1, rows


def samples_from_csv_rows(data_rows: list[list[str]], station_idx: int, elevation_idx: int, weight_idx: int) -> list[ProfileSample]:
    samples: list[ProfileSample] = []
    for row in data_rows:
        if len(row) <= max(station_idx, elevation_idx):
            continue
        weight = parse_float(row[weight_idx], 1.0) if weight_idx >= 0 and len(row) > weight_idx else 1.0
        samples.append(ProfileSample(parse_float(row[station_idx]), parse_float(row[elevation_idx]), weight))
    return samples


def read_csv_profile(path: pathlib.Path) -> ProfileSource:
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        raise SystemExit(f"Profile has no samples: {path}")
    station_idx, elevation_idx, weight_idx, data_rows = csv_profile_columns(rows)
    samples = samples_from_csv_rows(data_rows, station_idx, elevation_idx, weight_idx)
    return ProfileSource(str(path), validate_profile_samples(samples), 1.0)


def read_road_surface_elevation_profile(data: dict, path: pathlib.Path) -> ProfileSource:
    source_total, landmarks, station_map, source_shift, source_reversed, real_width, has_source_mapping = profile_mapping_info(data, path)
    elevation_profile = data.get("elevation_profile") or {}
    source_weight = parse_float(elevation_profile.get("weight", data.get("weight", 1.0)), 1.0)
    raw_samples = elevation_profile.get("samples", [])
    if not raw_samples:
        raise SystemExit(f"Road-surface profile has no elevation samples: {path}")
    samples = [sample_from_mapping(item, 1.0) for item in raw_samples]
    return ProfileSource(
        str(path),
        validate_profile_samples(samples),
        source_weight,
        source_total,
        landmarks,
        station_map,
        source_shift,
        source_reversed,
        real_width,
        has_source_mapping,
    )


def raw_profile_samples(data: object) -> object:
    if not isinstance(data, dict):
        return data
    if "road_profile" in data:
        return (data.get("road_profile") or {}).get("samples", [])
    return data.get("samples", data.get("profile", []))


def samples_from_profile_items(raw_samples: object, path: pathlib.Path) -> list[ProfileSample]:
    samples = []
    for item in raw_samples:
        if isinstance(item, dict):
            samples.append(sample_from_mapping(item, 1.0))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            weight = parse_float(item[2], 1.0) if len(item) > 2 else 1.0
            samples.append(ProfileSample(parse_float(item[0]), parse_float(item[1]), weight))
        else:
            raise SystemExit(f"Unsupported profile sample in {path}: {item}")
    return samples


def read_profile(path: pathlib.Path) -> ProfileSource:
    if path.suffix.lower() == ".csv":
        return read_csv_profile(path)

    data = json.loads(path.read_text(encoding="utf-8"))
    source_weight = 1.0
    if isinstance(data, dict):
        source_weight = parse_float(data.get("weight"), 1.0)
        if data.get("type") == "road-surface-profile":
            return read_road_surface_elevation_profile(data, path)
    samples = samples_from_profile_items(raw_profile_samples(data), path)
    source_total = parse_float(data.get("total_length_m"), 0.0) if isinstance(data, dict) else 0.0
    landmarks = ()
    # Raster DEM profiles are already sampled in XML station space.
    if isinstance(data, dict) and data.get("type") != "raster-dem-profile":
        landmarks = read_cache_landmarks(data, path)
    return ProfileSource(str(path), validate_profile_samples(samples), source_weight, source_total, landmarks)


def read_banking_profiles(path: pathlib.Path) -> list[ProfileSource]:
    if path.suffix.lower() == ".csv":
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("type") != "road-surface-profile":
        return []
    banking = data.get("banking_profile") or {}
    raw_samples = banking.get("samples", []) if isinstance(banking, dict) else []
    if not raw_samples:
        return []
    source_total, landmarks, station_map, source_shift, source_reversed, real_width, has_source_mapping = profile_mapping_info(data, path)
    source_weight = parse_float((banking or {}).get("weight", data.get("weight", 1.0)), 1.0)
    samples = [banking_sample_from_mapping(item, 1.0) for item in raw_samples]
    return [
        ProfileSource(
            str(path),
            validate_profile_samples(samples),
            source_weight,
            source_total,
            landmarks,
            station_map,
            source_shift,
            source_reversed,
            real_width,
            has_source_mapping,
        )
    ]


def read_terrain_lines(path: pathlib.Path) -> list[TerrainLine]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_lines = data.get("terrain_lines", []) if isinstance(data, dict) else []
    if not raw_lines:
        return []
    road_start = parse_float((data.get("normalization") or {}).get("road_start_elevation_m"), 0.0)
    source_total = parse_float(data.get("total_length_m"), 0.0)
    out = []
    for line in raw_lines:
        side = str(line.get("side", "")).strip().lower()
        if side not in ("left", "right", "center"):
            continue
        distance = parse_float(line.get("distance_m", line.get("distance")), 0.0)
        samples = []
        for item in line.get("samples", []):
            station = item.get("station_m", item.get("station", item.get("s")))
            elevation = item.get("elevation_m", item.get("elevation", item.get("z")))
            if station is None or elevation is None:
                continue
            samples.append(ProfileSample(parse_float(station), parse_float(elevation) - road_start, parse_float(item.get("weight"), 1.0)))
        if len(samples) >= 2:
            out.append(TerrainLine(side, distance, validate_profile_samples(samples), str(path.resolve(strict=False)), source_total))
    return out


def path_identity(raw: object) -> str:
    path = pathlib.Path(str(raw))
    try:
        return path.resolve(strict=False).as_posix().lower()
    except OSError:
        return str(raw).replace("\\", "/").lower()


def terrain_fit_source_identities(source_name: str) -> set[str]:
    path = pathlib.PurePosixPath(str(source_name).replace("\\", "/"))
    suffix = path.suffix
    stem = path.stem
    variants = {path}
    if suffix:
        variants.add(path.with_name(f"{stem}-terrainonly{suffix}"))
        variants.add(path.with_name(f"{stem}-terrain-only{suffix}"))
    return {path_identity(variant.as_posix()) for variant in variants}


def terrain_fits_from_profile_paths(paths: list[pathlib.Path]) -> list[TerrainFit]:
    fits = []
    for path in paths:
        if path.suffix.lower() != ".json" or not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        fit = data.get("fit") or {}
        source_name = data.get("elevation_source", "")
        if not isinstance(fit, dict) or not source_name:
            continue
        source_shift = parse_float(fit.get("source_shift_m"), math.nan)
        if not math.isfinite(source_shift):
            continue
        source_path = resolve_fit_source_path(str(source_name), path)
        scale = parse_float(fit.get("scale"), 1.0)
        if not math.isfinite(scale) or scale <= 0.0:
            continue
        fits.append(TerrainFit(str(source_path.resolve(strict=False)), source_shift, bool(fit.get("source_reversed", False)), scale))
    return fits


def terrain_fit_for_line(line: TerrainLine, fits: list[TerrainFit]) -> TerrainFit | None:
    if not fits:
        return None
    line_id = path_identity(line.source_name)
    for fit in fits:
        if line_id in terrain_fit_source_identities(fit.source_name):
            return fit
    return None


def validate_profile_samples(samples: list[ProfileSample]) -> list[ProfileSample]:
    clean = [s for s in samples if s.station >= 0.0 and math.isfinite(s.station) and math.isfinite(s.elevation)]
    clean.sort(key=lambda s: s.station)
    if len(clean) < 2:
        raise SystemExit("At least two elevation profile samples are required")
    return clean


def eval_linear(samples: list[ProfileSample], station: float, total_length: float) -> float:
    if total_length <= 0.0:
        return samples[0].elevation
    s = station % total_length
    ordered = sorted(samples, key=lambda p: p.station)
    if ordered[0].station <= 1e-9 and s <= 1e-9:
        return ordered[0].elevation
    if s <= ordered[0].station:
        prev = ordered[-1]
        nxt = ordered[0]
        span = nxt.station + total_length - prev.station
        t = 0.0 if span <= 1e-9 else (s + total_length - prev.station) / span
        return prev.elevation + t * (nxt.elevation - prev.elevation)
    for i in range(1, len(ordered)):
        if s <= ordered[i].station:
            prev = ordered[i - 1]
            nxt = ordered[i]
            span = nxt.station - prev.station
            t = 0.0 if span <= 1e-9 else (s - prev.station) / span
            return prev.elevation + t * (nxt.elevation - prev.elevation)
    prev = ordered[-1]
    nxt = ordered[0]
    span = nxt.station + total_length - prev.station
    t = 0.0 if span <= 1e-9 else (s - prev.station) / span
    return prev.elevation + t * (nxt.elevation - prev.elevation)


def source_eval_total(source: ProfileSource, xml_total: float) -> float:
    if source.source_total > 1e-9:
        return source.source_total
    return xml_total


def map_profile_station_direct(source: ProfileSource, station: float, source_total: float) -> float:
    if source_total <= 0.0:
        return station
    if source.source_reversed:
        return (source.source_shift_m - station) % source_total
    if abs(source.source_shift_m) > 1e-9:
        return (source.source_shift_m + station) % source_total
    return station


def map_profile_station_between_points(s: float, prev: StationMapPoint, nxt: StationMapPoint, source_total: float) -> float:
    xml_span = nxt.xml_station - prev.xml_station
    src_span = nxt.source_station - prev.source_station
    if src_span < 0.0:
        src_span += source_total
    t = 0.0 if xml_span <= 1e-9 else (s - prev.xml_station) / xml_span
    return (prev.source_station + t * src_span) % source_total


def map_profile_station_wrapped(s: float, xml_total: float, points: list[StationMapPoint], source_total: float) -> float:
    prev = points[-1]
    nxt = points[0]
    xml_span = nxt.xml_station + xml_total - prev.xml_station
    src_span = nxt.source_station - prev.source_station
    if src_span <= 0.0:
        src_span += source_total
    xml_delta = s - prev.xml_station if s >= prev.xml_station else s + xml_total - prev.xml_station
    t = 0.0 if xml_span <= 1e-9 else xml_delta / xml_span
    return (prev.source_station + t * src_span) % source_total


def map_profile_station_from_points(station: float, xml_total: float, points: list[StationMapPoint], source_total: float) -> float:
    s = station % xml_total
    if abs(s - points[0].xml_station) <= 1e-9:
        return points[0].source_station % source_total
    if s > points[0].xml_station:
        for i in range(1, len(points)):
            if s <= points[i].xml_station:
                return map_profile_station_between_points(s, points[i - 1], points[i], source_total)
    return map_profile_station_wrapped(s, xml_total, points, source_total)


def map_profile_station(source: ProfileSource, station: float, xml_total: float) -> float:
    source_total = source_eval_total(source, xml_total)
    if not source.station_map or xml_total <= 0.0 or source_total <= 0.0:
        return map_profile_station_direct(source, station, source_total)
    points = sorted(source.station_map, key=lambda p: p.xml_station)
    return map_profile_station_from_points(station, xml_total, points, source_total)


def eval_source(source: ProfileSource, station: float, xml_total: float) -> float:
    mapped_station = map_profile_station(source, station, xml_total)
    return eval_linear(source.samples, mapped_station, source_eval_total(source, xml_total))


def terrain_line_source(line: TerrainLine) -> ProfileSource:
    return ProfileSource(line.source_name or "terrain-line", line.samples, 1.0, line.source_total, (), line.station_map)


def eval_terrain_line(line: TerrainLine, station: float, total: float) -> float:
    if line.source_shift_m is not None:
        eval_total = line.source_total if line.source_total > 1e-9 else total
        delta = station * line.source_scale
        if line.source_reversed:
            delta = -delta
        return eval_linear(line.samples, line.source_shift_m + delta, eval_total) - line.zero_offset
    return eval_source(terrain_line_source(line), station, total) - line.zero_offset


def terrain_line_xml_distance(line: TerrainLine) -> float:
    return line.distance / max(line.source_scale, 1e-9)


def terrain_alignment_key(line: TerrainLine) -> tuple:
    if line.source_shift_m is not None:
        return ("fit", line.source_name, line.source_total, line.source_shift_m, line.source_reversed, line.source_scale)
    return ("map", line.source_name, line.source_total, line.station_map)


def terrain_zero_line(line: TerrainLine, candidates: list[TerrainLine]) -> TerrainLine:
    key = terrain_alignment_key(line)
    centers = [candidate for candidate in candidates if candidate.side == "center" and terrain_alignment_key(candidate) == key]
    if centers:
        return min(centers, key=lambda candidate: abs(candidate.distance))
    return line


def aligned_terrain_line(
    line: TerrainLine,
    source_by_name: dict[str, ProfileSource],
    total: float,
    fits: list[TerrainFit],
) -> TerrainLine:
    fit = terrain_fit_for_line(line, fits)
    if fit is not None:
        side = line.side
        if fit.source_reversed and side in ("left", "right"):
            side = "right" if side == "left" else "left"
        return replace(
            line,
            side=side,
            station_map=(),
            source_shift_m=fit.source_shift_m,
            source_reversed=fit.source_reversed,
            source_scale=fit.scale,
            zero_offset=0.0,
        )

    source = source_by_name.get(path_identity(line.source_name))
    if source is None:
        return replace(line, zero_offset=0.0)
    return replace(
        line,
        source_total=source_eval_total(source, total),
        station_map=source.station_map,
        source_shift_m=None,
        source_reversed=False,
        source_scale=1.0,
        zero_offset=0.0,
    )


def zero_aligned_terrain_line(line: TerrainLine, candidates: list[TerrainLine], total: float) -> TerrainLine:
    if not line.samples:
        return replace(line, zero_offset=0.0)
    zero_line = terrain_zero_line(line, candidates)
    return replace(line, zero_offset=eval_terrain_line(zero_line, 0.0, total))


def align_terrain_lines_to_sources(
    lines: list[TerrainLine],
    sources: list[ProfileSource],
    total: float,
    fits: list[TerrainFit] | None = None,
) -> list[TerrainLine]:
    """Apply only matching profile maps/fits, then normalize each source at XML station zero."""

    source_by_name = {path_identity(source.name): source for source in sources}
    aligned_lines = [aligned_terrain_line(line, source_by_name, total, fits or []) for line in lines]
    return [zero_aligned_terrain_line(line, aligned_lines, total) for line in aligned_lines]


def terrain_source_alignment_report(lines: list[TerrainLine]) -> list[dict]:
    grouped: dict[tuple[str, float | None, bool, float], list[TerrainLine]] = {}
    for line in lines:
        key = (line.source_name, line.source_shift_m, line.source_reversed, line.source_scale)
        grouped.setdefault(key, []).append(line)
    return [
        {
            "name": source_name,
            "line_count": len(source_lines),
            "plan_fit_applied": source_shift is not None,
            "source_shift_m": source_shift,
            "source_reversed": source_reversed,
            "scale": scale,
            "zero_offset_m": source_lines[0].zero_offset if source_lines else 0.0,
        }
        for (source_name, source_shift, source_reversed, scale), source_lines in grouped.items()
    ]


def normalized_sources(sources: list[ProfileSource], total_length: float) -> list[ProfileSource]:
    out = []
    for source in sources:
        start_z = eval_source(source, 0.0, total_length)
        out.append(
            ProfileSource(
                source.name,
                [ProfileSample(s.station, s.elevation - start_z, s.weight) for s in source.samples],
                source.weight,
                source.source_total,
                source.landmarks,
                source.station_map,
                source.source_shift_m,
                source.source_reversed,
                source.real_width_m,
                source.has_source_mapping,
            )
        )
    return out


def eval_sources(sources: list[ProfileSource], station: float, total_length: float) -> float:
    numerator = 0.0
    denominator = 0.0
    for source in sources:
        local_weight = source.weight
        source_station = map_profile_station(source, station, total_length)
        z = eval_linear(source.samples, source_station, source_eval_total(source, total_length))
        # Per-sample weights are intentionally coarse here: they bias a source by
        # the nearest sample weight without changing the interpolation shape.
        eval_total = source_eval_total(source, total_length)
        nearest = min(
            source.samples,
            key=lambda p: min(abs(p.station - (source_station % eval_total)), eval_total - abs(p.station - (source_station % eval_total))),
        )
        weight = max(0.0, local_weight * nearest.weight)
        numerator += z * weight
        denominator += weight
    return 0.0 if denominator <= 1e-12 else numerator / denominator


def circular_distance(a: float, b: float, total: float) -> float:
    d = abs(a - b)
    return min(d, total - d)


def smooth_values(stations: list[float], values: list[float], total: float, window: float, iterations: int) -> list[float]:
    if window <= 0.0 or iterations <= 0 or len(values) < 3:
        return list(values)
    sigma = max(1e-6, window * 0.5)
    radius = window
    out = list(values)
    for _ in range(iterations):
        nxt = []
        for i, s in enumerate(stations):
            numerator = 0.0
            denominator = 0.0
            for j, sj in enumerate(stations):
                d = circular_distance(s, sj, total)
                if d > radius:
                    continue
                w = math.exp(-0.5 * (d / sigma) * (d / sigma))
                numerator += out[j] * w
                denominator += w
            nxt.append(out[i] if denominator <= 1e-12 else numerator / denominator)
        out = nxt
    return out


def eval_dense(stations: list[float], values: list[float], station: float, total: float) -> float:
    if not stations:
        return 0.0
    s = station % total if total > 0.0 else 0.0
    if s <= stations[0]:
        return values[0]
    for i in range(1, len(stations)):
        if s <= stations[i]:
            span = stations[i] - stations[i - 1]
            t = 0.0 if span <= 1e-9 else (s - stations[i - 1]) / span
            return values[i - 1] + t * (values[i] - values[i - 1])
    span = total - stations[-1]
    t = 0.0 if span <= 1e-9 else (s - stations[-1]) / span
    return values[-1] + t * (values[0] - values[-1])


def pit_station_ranges(
    main_track: ET.Element, segs: list[ET.Element], segment_starts: list[float], lengths: list[float], total: float
) -> list[dict]:
    pits = child_section(main_track, "Pits")
    if pits is None or get_attstr(pits, "type", "none") == "none":
        return []
    start_name = get_attstr(pits, "start", "")
    end_name = get_attstr(pits, "end", "")
    if not start_name or not end_name:
        return []
    name_to_idx = {seg.get("name", ""): idx for idx, seg in enumerate(segs)}
    if start_name not in name_to_idx or end_name not in name_to_idx:
        return []
    start_idx = name_to_idx[start_name]
    end_idx = name_to_idx[end_name]
    start_s = segment_starts[start_idx]
    end_s = (segment_starts[end_idx] + lengths[end_idx]) % total
    if start_s <= end_s:
        return [{"start": start_s, "end": end_s, "start_segment": start_name, "end_segment": end_name}]
    return [
        {"start": start_s, "end": total, "start_segment": start_name, "end_segment": end_name},
        {"start": 0.0, "end": end_s, "start_segment": start_name, "end_segment": end_name},
    ]


def station_in_range(station: float, start: float, end: float) -> bool:
    return start <= station <= end


def apply_pit_flattening(stations: list[float], elevations: list[float], ranges: list[dict], strength: float) -> list[float]:
    if not ranges or strength <= 0.0:
        return list(elevations)
    strength = max(0.0, min(1.0, strength))
    out = list(elevations)
    for item in ranges:
        start = float(item["start"])
        end = float(item["end"])
        if end <= start:
            continue
        z0 = eval_boundary_linear(stations, out, start)
        z1 = eval_boundary_linear(stations, out, end)
        for i, s in enumerate(stations):
            if not station_in_range(s, start, end):
                continue
            t = (s - start) / max(1e-9, end - start)
            ramp = z0 + t * (z1 - z0)
            out[i] = out[i] * (1.0 - strength) + ramp * strength
    return out


def eval_boundary_linear(stations: list[float], values: list[float], station: float) -> float:
    if not stations:
        return 0.0
    if station <= stations[0]:
        return values[0]
    for i in range(1, len(stations)):
        if station <= stations[i]:
            span = stations[i] - stations[i - 1]
            t = 0.0 if span <= 1e-9 else (station - stations[i - 1]) / span
            return values[i - 1] + t * (values[i] - values[i - 1])
    return values[0]


def boundary_tangents(stations: list[float], elevations: list[float], lengths: list[float], total: float) -> list[float]:
    n = len(elevations)
    if n == 0:
        return []
    tangents = []
    for i in range(n):
        if total <= 1e-9:
            tangents.append(0.0)
            continue
        slope_prev = previous_boundary_slope(i, elevations, lengths)
        slope_next = next_boundary_slope(i, elevations, lengths)
        tangents.append(0.5 * (slope_prev + slope_next))
    return tangents


def previous_boundary_slope(boundary_i: int, elevations: list[float], lengths: list[float]) -> float:
    n = len(elevations)
    for step in range(n):
        seg_i = (boundary_i - 1 - step) % n
        if lengths[seg_i] > MIN_TANGENT_SEGMENT_LENGTH_M:
            start_i = seg_i
            end_i = (seg_i + 1) % n
            return (elevations[end_i] - elevations[start_i]) / lengths[seg_i]
    return 0.0


def next_boundary_slope(boundary_i: int, elevations: list[float], lengths: list[float]) -> float:
    n = len(elevations)
    for step in range(n):
        seg_i = (boundary_i + step) % n
        if lengths[seg_i] > MIN_TANGENT_SEGMENT_LENGTH_M:
            start_i = seg_i
            end_i = (seg_i + 1) % n
            return (elevations[end_i] - elevations[start_i]) / lengths[seg_i]
    return 0.0


def merged_landmark_ranges(ranges: list[LandmarkRange]) -> tuple[LandmarkRange, ...]:
    by_name: dict[str, LandmarkRange] = {}
    for item in ranges:
        if not item.name:
            continue
        previous = by_name.get(item.name)
        if previous is None:
            by_name[item.name] = item
        else:
            by_name[item.name] = LandmarkRange(item.name, min(previous.start, item.start), max(previous.end, item.end))
    return tuple(sorted(by_name.values(), key=lambda item: item.start))


def xml_landmark_ranges(segs: list[ET.Element], lengths: list[float]) -> tuple[LandmarkRange, ...]:
    ranges = []
    station = 0.0
    current_name = ""
    current_start = 0.0
    current_end = 0.0
    for seg, length in zip(segs, lengths, strict=True):
        name = clean_landmark_name(seg.get("name", ""))
        if name != current_name:
            if current_name:
                ranges.append(LandmarkRange(current_name, current_start, current_end))
            current_name = name
            current_start = station
        current_end = station + length
        station += length
    if current_name:
        ranges.append(LandmarkRange(current_name, current_start, current_end))
    return merged_landmark_ranges(ranges)


def station_map_points(
    xml_ranges: tuple[LandmarkRange, ...],
    source_ranges: tuple[LandmarkRange, ...],
    source_total: float,
) -> list[StationMapPoint]:
    if source_total <= 1e-9:
        return []
    source_by_name = {item.name: item for item in merged_landmark_ranges(list(source_ranges)) if item.name}
    raw_points = []
    matched_names = set()
    for xml_range in xml_ranges:
        source_range = source_by_name.get(xml_range.name)
        if source_range is None:
            continue
        matched_names.add(xml_range.name)
        raw_points.append(StationMapPoint(xml_range.start, source_range.start))
        raw_points.append(StationMapPoint(xml_range.end, source_range.end))
    if len(matched_names) < 2:
        return []

    out: list[StationMapPoint] = []
    for point in sorted(raw_points, key=lambda p: p.xml_station):
        if out and abs(point.xml_station - out[-1].xml_station) <= 1e-6:
            out[-1] = point
        else:
            out.append(point)
    return out


def station_map_plan_fit_tolerance(source_total: float) -> float:
    if source_total <= 0.0:
        return 0.0
    return max(25.0, min(150.0, source_total * 0.03))


def station_map_max_plan_fit_deviation(source: ProfileSource, points: list[StationMapPoint], source_total: float) -> float:
    if not points or source_total <= 0.0:
        return 0.0
    return max(
        circular_distance(map_profile_station_direct(source, point.xml_station, source_total), point.source_station, source_total)
        for point in points
    )


def station_map_rejection_reason(source: ProfileSource, points: list[StationMapPoint], source_total: float) -> tuple[str, float]:
    if not points or source_total <= 0.0 or not source.has_source_mapping:
        return "", 0.0
    max_deviation = station_map_max_plan_fit_deviation(source, points, source_total)
    if max_deviation > station_map_plan_fit_tolerance(source_total):
        return "station-map-conflicts-with-plan-fit", max_deviation
    return "", max_deviation


def align_sources_to_xml_landmarks(
    sources: list[ProfileSource],
    xml_ranges: tuple[LandmarkRange, ...],
    xml_total: float,
    enabled: bool,
) -> tuple[list[ProfileSource], list[dict]]:
    aligned = []
    reports = []
    for source in sources:
        eval_total = source_eval_total(source, xml_total)
        explicit_station_map = bool(source.station_map)
        points = list(source.station_map)
        if not points and enabled and source.landmarks:
            points = station_map_points(xml_ranges, source.landmarks, eval_total)
        rejection_reason = ""
        plan_fit_max_deviation = 0.0
        if points and not explicit_station_map:
            rejection_reason, plan_fit_max_deviation = station_map_rejection_reason(source, points, eval_total)
            if rejection_reason:
                points = []
        aligned.append(
            ProfileSource(
                source.name,
                source.samples,
                source.weight,
                source.source_total,
                source.landmarks,
                tuple(points),
                source.source_shift_m,
                source.source_reversed,
                source.real_width_m,
                source.has_source_mapping,
            )
        )
        reports.append(
            {
                "name": source.name,
                "enabled": bool(enabled),
                "source_landmark_count": len(source.landmarks),
                "matched_anchor_count": len(points),
                "explicit_station_map": explicit_station_map,
                "alignment_rejected_reason": rejection_reason,
                "plan_fit_max_deviation_m": plan_fit_max_deviation,
                "matched_names": sorted({r.name for r in xml_ranges if any(s.name == r.name for s in source.landmarks)}),
            }
        )
    return aligned, reports


def build_boundary_profile(
    sources: list[ProfileSource],
    main_track: ET.Element,
    segs: list[ET.Element],
    lengths: list[float],
    total: float,
    args: argparse.Namespace,
) -> BoundaryProfile:
    segment_starts = []
    acc = 0.0
    for length in lengths:
        segment_starts.append(acc)
        acc += length

    dense_count = max(8, int(math.ceil(total / max(1.0, args.smooth_step))))
    dense_stations = [total * i / dense_count for i in range(dense_count)]
    normalized = normalized_sources(sources, total)
    dense_raw = [eval_sources(normalized, s, total) for s in dense_stations]
    dense_smooth = smooth_values(dense_stations, dense_raw, total, args.smooth_window, max(0, args.smooth_iters))
    start_offset = eval_dense(dense_stations, dense_smooth, 0.0, total)
    dense_smooth = [z - start_offset for z in dense_smooth]

    raw_boundaries = [eval_sources(normalized, s, total) for s in segment_starts]
    elevations = [eval_dense(dense_stations, dense_smooth, s, total) for s in segment_starts]
    if elevations:
        elevations[0] = 0.0

    ranges = pit_station_ranges(main_track, segs, segment_starts, lengths, total)
    elevations = apply_pit_flattening(segment_starts, elevations, ranges, args.pit_flatten_strength)
    if elevations:
        elevations[0] = 0.0
    tangents = boundary_tangents(segment_starts, elevations, lengths, total)
    return BoundaryProfile(segment_starts, elevations, tangents, raw_boundaries, ranges)


def apply_profile_to_xml(segs: list[ET.Element], profile: BoundaryProfile) -> None:
    n = len(segs)
    for i, seg in enumerate(segs):
        next_i = (i + 1) % n
        set_attnum(seg, "z start", profile.elevations[i], "m")
        set_attnum(seg, "z end", profile.elevations[next_i], "m")
        set_attnum(seg, "profil start tangent", profile.tangents[i] * 100.0, "%")
        set_attnum(seg, "profil end tangent", profile.tangents[next_i] * 100.0, "%")
        set_attstr(seg, "profil", "spline")
        for name in ("grade", "z start left", "z start right", "z end left", "z end right"):
            remove_att(seg, "attnum", name)


def median_filter_values(stations: list[float], values: list[float], total: float, window: float) -> list[float]:
    if window <= 0.0 or len(values) < 3:
        return list(values)
    radius = window * 0.5
    out = []
    for s in stations:
        local = [value for station, value in zip(stations, values, strict=True) if circular_distance(s, station, total) <= radius]
        if not local:
            out.append(values[len(out)])
            continue
        local.sort()
        mid = len(local) // 2
        if len(local) % 2:
            out.append(local[mid])
        else:
            out.append(0.5 * (local[mid - 1] + local[mid]))
    return out


def banking_sign_multiplier(source: ProfileSource, args: argparse.Namespace) -> float:
    if args.bank_source_sign == "flip":
        return -1.0
    if args.bank_source_sign == "preserve":
        return 1.0
    return -1.0 if source.source_reversed else 1.0


def eval_banking_sources(sources: list[ProfileSource], station: float, total_length: float, args: argparse.Namespace) -> float:
    numerator = 0.0
    denominator = 0.0
    for source in sources:
        source_station = map_profile_station(source, station, total_length)
        eval_total = source_eval_total(source, total_length)
        bank = eval_linear(source.samples, source_station, eval_total) * banking_sign_multiplier(source, args)
        nearest = min(
            source.samples,
            key=lambda p: min(abs(p.station - (source_station % eval_total)), eval_total - abs(p.station - (source_station % eval_total))),
        )
        weight = max(0.0, source.weight * nearest.weight)
        numerator += bank * weight
        denominator += weight
    return 0.0 if denominator <= 1e-12 else numerator / denominator


def clamp_banking(value: float, max_abs: float) -> float:
    limit = max(0.0, max_abs)
    return max(-limit, min(limit, value))


def build_banking_profile(
    sources: list[ProfileSource],
    segs: list[ET.Element],
    lengths: list[float],
    total: float,
    args: argparse.Namespace,
) -> BankingProfile | None:
    if not sources:
        return None
    segment_starts = []
    acc = 0.0
    for length in lengths:
        segment_starts.append(acc)
        acc += length

    dense_count = max(8, int(math.ceil(total / max(1.0, args.bank_smooth_step))))
    dense_stations = [total * i / dense_count for i in range(dense_count)]
    dense_raw = [eval_banking_sources(sources, s, total, args) for s in dense_stations]
    dense_filtered = median_filter_values(dense_stations, dense_raw, total, args.bank_median_window)
    dense_smooth = smooth_values(dense_stations, dense_filtered, total, args.bank_smooth_window, max(0, args.bank_smooth_iters))
    dense_smooth = [clamp_banking(value, args.bank_max_abs_deg) for value in dense_smooth]
    raw_boundaries = [eval_banking_sources(sources, s, total, args) for s in segment_starts]
    filters_disabled = args.bank_median_window <= 0.0 and (args.bank_smooth_window <= 0.0 or args.bank_smooth_iters <= 0)
    if filters_disabled:
        banking = raw_boundaries
    else:
        banking = [eval_dense(dense_stations, dense_smooth, s, total) for s in segment_starts]
    banking = [clamp_banking(value, args.bank_max_abs_deg) for value in banking]
    return BankingProfile(segment_starts, banking, raw_boundaries)


def banking_real_width(args: argparse.Namespace, sources: list[ProfileSource]) -> float:
    if args.bank_real_width > 0.0:
        return args.bank_real_width
    for source in sources:
        if source.real_width_m > 0.0:
            return source.real_width_m
    return 0.0


def scale_banking_for_width(bank_deg: float, real_width: float, torcs_width: float, args: argparse.Namespace) -> float:
    if args.bank_width_policy != "edge-delta":
        return bank_deg
    if real_width <= 0.0:
        raise SystemExit("--bank-width-policy edge-delta requires --bank-real-width or sampling.real_road_width_m in the profile")
    if torcs_width <= 1e-9:
        return bank_deg
    scaled = math.degrees(math.atan(math.tan(math.radians(bank_deg)) * real_width / torcs_width))
    return clamp_banking(scaled, args.bank_max_abs_deg)


def apply_banking_to_xml(
    main_track: ET.Element,
    segs: list[ET.Element],
    profile: BankingProfile,
    sources: list[ProfileSource],
    args: argparse.Namespace,
) -> None:
    n = len(segs)
    widths = main_width_profile(main_track, segs)
    real_width = banking_real_width(args, sources)
    for i, seg in enumerate(segs):
        next_i = (i + 1) % n
        start_width = widths[i][0]
        end_width = widths[i][1]
        start_bank = scale_banking_for_width(profile.banking_deg[i], real_width, start_width, args)
        end_bank = scale_banking_for_width(profile.banking_deg[next_i], real_width, end_width, args)
        set_attnum(seg, "banking start", start_bank, "deg")
        set_attnum(seg, "banking end", end_bank, "deg")


def track_relative_value(path: pathlib.Path, track_xml_path: pathlib.Path) -> str:
    try:
        return path.relative_to(track_xml_path.parent).as_posix()
    except ValueError:
        return path.name


def update_terrain_xml(
    root: ET.Element, relief_path: pathlib.Path, track_xml_path: pathlib.Path, terrain_map: TerrainElevationMap | None
) -> str:
    graphic = get_or_make_child_section(root, "Graphic")
    terrain = get_or_make_child_section(graphic, "Terrain Generation")
    relief_value = track_relative_value(relief_path, track_xml_path)
    set_attstr(terrain, "relief file", relief_value)
    if terrain_map is None:
        remove_att(terrain, "attstr", "elevation map")
        for name in ("minimum altitude", "maximum altitude"):
            remove_att(terrain, "attnum", name)
    else:
        set_attstr(terrain, "elevation map", terrain_map.xml_value)
        set_attnum(terrain, "minimum altitude", terrain_map.min_altitude, "m")
        set_attnum(terrain, "maximum altitude", terrain_map.max_altitude, "m")
    return relief_value


def resolve_existing_path(raw: str, anchor_path: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(raw)
    if path.is_absolute():
        return path
    candidates = [pathlib.Path.cwd() / path, anchor_path.parent / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_fit_source_path(raw: str, profile_path: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(raw)
    if path.is_absolute():
        return path
    candidates = [pathlib.Path.cwd() / path, profile_path.parent / path]
    existing = {candidate.resolve(strict=False) for candidate in candidates if candidate.exists()}
    if len(existing) > 1:
        raise SystemExit(f"Ambiguous elevation_source path in {profile_path}: {raw}")
    if existing:
        return existing.pop()
    return candidates[0]


def terrain_map_output_path(value: str, output_xml: pathlib.Path) -> pathlib.Path | None:
    if not value:
        return None
    if value.strip().lower() == "auto":
        return output_xml.with_name(f"{output_xml.stem}-terrain-elevation.png")
    path = pathlib.Path(value)
    if path.is_absolute():
        return path
    return output_xml.parent / path


def rigid_fit_points(source: list[tuple[float, float]], target: list[tuple[float, float]]) -> dict[str, float]:
    n = min(len(source), len(target))
    if n < 2:
        raise SystemExit("At least two positioned samples are required to infer the terrain elevation fit")
    sx = sum(source[i][0] for i in range(n)) / n
    sy = sum(source[i][1] for i in range(n)) / n
    tx = sum(target[i][0] for i in range(n)) / n
    ty = sum(target[i][1] for i in range(n)) / n
    a = 0.0
    b = 0.0
    for i in range(n):
        ux = source[i][0] - sx
        uy = source[i][1] - sy
        vx = target[i][0] - tx
        vy = target[i][1] - ty
        a += ux * vx + uy * vy
        b += ux * vy - uy * vx
    theta = math.atan2(b, a)
    c = math.cos(theta)
    s = math.sin(theta)
    return {
        "c": c,
        "s": s,
        "ox": tx - (c * sx - s * sy),
        "oy": ty - (s * sx + c * sy),
    }


def profile_fit_for_terrain(data: dict, profile_path: pathlib.Path, segments: list[Segment], total: float) -> dict[str, float]:
    """Return the XML-plan to raster-coordinate transform stored in a raster profile.

    New profiles store the rigid fit explicitly. Older profiles only have the
    raster coordinates sampled along the XML centerline, so this falls back to a
    least-squares rigid fit from XML plan samples to those raster sample points.
    """
    fit = data.get("fit") or {}
    if all(key in fit for key in ("cos", "sin", "offset_x", "offset_y")):
        return {
            "c": parse_float(fit.get("cos"), 1.0),
            "s": parse_float(fit.get("sin"), 0.0),
            "ox": parse_float(fit.get("offset_x"), 0.0),
            "oy": parse_float(fit.get("offset_y"), 0.0),
            "scale": parse_float(fit.get("scale"), 1.0),
        }

    plan = sample_centerline(segments, 3.0)
    source: list[tuple[float, float]] = []
    target: list[tuple[float, float]] = []
    for item in data.get("samples", []):
        if not isinstance(item, dict) or "raster_x" not in item or "raster_y" not in item:
            continue
        station = item.get("station_m", item.get("station", item.get("s")))
        if station is None:
            continue
        sample = interpolate_centerline_sample(plan, parse_float(station), total)
        source.append((sample.x, sample.y))
        target.append((parse_float(item.get("raster_x")), parse_float(item.get("raster_y"))))
    if len(source) < 2:
        raise SystemExit(f"Profile cannot drive a terrain elevation map without fit metadata or raster_x/raster_y samples: {profile_path}")
    return rigid_fit_points(source, target)


def transform_with_fit(x: float, y: float, fit: dict[str, float]) -> tuple[float, float]:
    scale = fit.get("scale", 1.0)
    return scale * (fit["c"] * x - fit["s"] * y) + fit["ox"], scale * (fit["s"] * x + fit["c"] * y) + fit["oy"]


def main_width_profile(main_track: ET.Element, segs: list[ET.Element]) -> list[tuple[float, float]]:
    previous_end = get_attnum(main_track, "width", 12.0)
    profiles = []
    for seg in segs:
        width = get_attnum(seg, "width", previous_end)
        start = get_attnum(seg, "start width", width)
        end = get_attnum(seg, "end width", width)
        profiles.append((max(0.0, start), max(0.0, end)))
        previous_end = max(0.0, end)
    return profiles


def lerp_pair(pair: tuple[float, float], t: float) -> float:
    return pair[0] + (pair[1] - pair[0]) * max(0.0, min(1.0, t))


def segment_outer_edge_points(
    samples: list[Sample],
    profile_station: float,
    length: float,
    main_width: tuple[float, float],
    left_side: tuple[float, float],
    right_side: tuple[float, float],
    left_border: tuple[float, float],
    right_border: tuple[float, float],
) -> tuple[list[ReliefEdgePoint], list[ReliefEdgePoint]]:
    left_points = []
    right_points = []
    step_count = max(1, len(samples) - 1)
    for sample_index, sample in enumerate(samples):
        t = sample_index / step_count
        station = profile_station + t * length
        half_width = 0.5 * lerp_pair(main_width, t)
        left_offset = half_width + lerp_pair(left_side, t) + lerp_pair(left_border, t)
        right_offset = half_width + lerp_pair(right_side, t) + lerp_pair(right_border, t)
        normal_x = -math.sin(sample.heading)
        normal_y = math.cos(sample.heading)
        left_x, left_y = offset_point(sample, left_offset)
        right_x, right_y = offset_point(sample, -right_offset)
        left_points.append(ReliefEdgePoint(left_x, left_y, station, left_offset, normal_x, normal_y))
        right_points.append(ReliefEdgePoint(right_x, right_y, station, right_offset, -normal_x, -normal_y))
    return left_points, right_points


def remove_consecutive_relief_edge_duplicates(points: list[ReliefEdgePoint]) -> list[ReliefEdgePoint]:
    clean = []
    for point in points:
        if not clean or math.hypot(point.x - clean[-1].x, point.y - clean[-1].y) > 1e-8:
            clean.append(point)
    return clean


def close_relief_edge_points(points: list[ReliefEdgePoint], total: float) -> list[ReliefEdgePoint]:
    points = [point for point in points if point.station < total - 1e-6]
    if not points:
        return points
    first = points[0]
    points.append(ReliefEdgePoint(first.x, first.y, total, first.center_distance, first.outward_x, first.outward_y))
    return points


def track_outer_edge_points(
    main_track: ET.Element,
    segs: list[ET.Element],
    segments: list[Segment],
    lengths: list[float],
    step: float,
    close: bool = False,
) -> tuple[list[ReliefEdgePoint], list[ReliefEdgePoint]]:
    """Sample outer side/border edges with loader-compatible width inheritance."""
    main_widths = main_width_profile(main_track, segs)
    left_side = width_profile(main_track, segs, "Left Side")
    right_side = width_profile(main_track, segs, "Right Side")
    left_border = width_profile(main_track, segs, "Left Border")
    right_border = width_profile(main_track, segs, "Right Border")
    left_points: list[ReliefEdgePoint] = []
    right_points: list[ReliefEdgePoint] = []
    pose = Pose(0.0, 0.0, 0.0)
    geometry_station = 0.0
    profile_station = 0.0

    for idx, segment in enumerate(segments):
        length = lengths[idx]
        local_step = max(1.0, min(max(1.0, step), segment.profil_steps_length if segment.profil_steps_length > 0.0 else step))
        start_pose = pose
        pose, seg_samples = sample_segment(pose, segment, geometry_station, local_step)
        samples = [Sample(start_pose.x, start_pose.y, geometry_station, start_pose.heading, segment.name), *seg_samples]
        segment_left, segment_right = segment_outer_edge_points(
            samples,
            profile_station,
            length,
            main_widths[idx],
            left_side[idx],
            right_side[idx],
            left_border[idx],
            right_border[idx],
        )
        left_points.extend(segment_left)
        right_points.extend(segment_right)
        geometry_station = seg_samples[-1].s if seg_samples else geometry_station + length
        profile_station += length

    left_points = remove_consecutive_relief_edge_duplicates(left_points)
    right_points = remove_consecutive_relief_edge_duplicates(right_points)
    if close:
        total = sum(lengths)
        left_points = close_relief_edge_points(left_points, total)
        right_points = close_relief_edge_points(right_points, total)
    return left_points, right_points


def track_bounds_for_terrain(
    main_track: ET.Element, segs: list[ET.Element], segments: list[Segment], lengths: list[float], step: float
) -> tuple[float, float, float, float]:
    """Return outer-edge bounds using loader-compatible side-width inheritance."""
    left_points, right_points = track_outer_edge_points(main_track, segs, segments, lengths, step)
    points = left_points + right_points
    if not points:
        raise SystemExit("Cannot determine terrain elevation map bounds from an empty track")
    return (
        min(0.0, *(point.x for point in points)),
        min(0.0, *(point.y for point in points)),
        max(0.0, *(point.x for point in points)),
        max(0.0, *(point.y for point in points)),
    )


def terrain_generation_bounds(
    main_track: ET.Element,
    terrain_section: ET.Element | None,
    segs: list[ET.Element],
    segments: list[Segment],
    lengths: list[float],
) -> tuple[float, float, float, float]:
    """Match trackgen's elevation-map XY extent: track bounds plus border margin."""
    track_step = get_attnum(terrain_section, "track step", 10.0)
    border_margin = get_attnum(terrain_section, "border margin", 100.0)
    min_x, min_y, max_x, max_y = track_bounds_for_terrain(main_track, segs, segments, lengths, max(1.0, track_step))
    return min_x - border_margin, min_y - border_margin, max_x + border_margin, max_y + border_margin


def terrain_profile_data(
    profile_paths: list[str], segments: list[Segment], total: float
) -> tuple[pathlib.Path, dict, dict[str, float], float, pathlib.Path]:
    for raw_profile in profile_paths:
        profile_path = pathlib.Path(raw_profile)
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("raster"):
            continue
        raster_path = resolve_existing_path(str(data["raster"]), profile_path)
        if not raster_path.exists():
            raise SystemExit(f"Terrain elevation raster not found: {raster_path}")
        zero_elevation = parse_float(data.get("zero_elevation_m"), 0.0)
        try:
            source = read_profile(profile_path)
            zero_elevation += eval_source(source, 0.0, total)
        except SystemExit:
            pass
        return profile_path, data, profile_fit_for_terrain(data, profile_path, segments, total), zero_elevation, raster_path
    raise SystemExit("--terrain-elevation-map requires a JSON --profile containing a raster path")


def side_banking_factor(main_track: ET.Element, section_name: str) -> float:
    section = child_section(main_track, section_name)
    return 1.0 if get_attstr(section, "banking type", "level") == "tangent" else 0.0


def road_visual_min_elevation(
    main_track: ET.Element,
    segs: list[ET.Element],
    lengths: list[float],
    profile: BoundaryProfile,
    sample_step: float = 1.0,
) -> float:
    """Approximate the road minimum that TORCS subtracts from generated geometry."""
    if not profile.elevations:
        return 0.0
    min_z = min(profile.elevations)
    main_widths = main_width_profile(main_track, segs)
    left_side = width_profile(main_track, segs, "Left Side")
    right_side = width_profile(main_track, segs, "Right Side")
    left_border = width_profile(main_track, segs, "Left Border")
    right_border = width_profile(main_track, segs, "Right Border")
    left_side_banking = side_banking_factor(main_track, "Left Side")
    right_side_banking = side_banking_factor(main_track, "Right Side")
    for i, seg in enumerate(segs):
        length = lengths[i]
        if length <= 1e-9:
            continue
        count = max(1, int(math.ceil(length / max(0.25, sample_step))))
        start_z = profile.elevations[i]
        end_z = profile.elevations[(i + 1) % len(segs)]
        start_t = profile.tangents[i] * length
        end_t = profile.tangents[(i + 1) % len(segs)] * length
        banking_start = attnum_si(seg, "banking start", 0.0)
        banking_end = attnum_si(seg, "banking end", banking_start)
        for k in range(count + 1):
            t = k / count
            center = hermite(start_z, end_z, start_t, end_t, t)
            banking = banking_start + (banking_end - banking_start) * t
            bank_slope = math.tan(banking)
            half_width = 0.5 * lerp_pair(main_widths[i], t)
            left_z = center + bank_slope * half_width
            right_z = center - bank_slope * half_width
            left_outer_z = left_z + left_side_banking * bank_slope * (lerp_pair(left_border[i], t) + lerp_pair(left_side[i], t))
            right_outer_z = right_z - right_side_banking * bank_slope * (lerp_pair(right_border[i], t) + lerp_pair(right_side[i], t))
            min_z = min(min_z, center, left_z, right_z, left_outer_z, right_outer_z)
    return min_z


def xml_road_visual_min_elevation(
    main_track: ET.Element,
    segs: list[ET.Element],
    lengths: list[float],
    sample_step: float = 1.0,
) -> float:
    """Approximate the pre-normalization road minimum from an elevated XML."""
    if not segs:
        return 0.0
    min_z = math.inf
    main_widths = main_width_profile(main_track, segs)
    left_side = width_profile(main_track, segs, "Left Side")
    right_side = width_profile(main_track, segs, "Right Side")
    left_border = width_profile(main_track, segs, "Left Border")
    right_border = width_profile(main_track, segs, "Right Border")
    left_side_banking = side_banking_factor(main_track, "Left Side")
    right_side_banking = side_banking_factor(main_track, "Right Side")
    previous_end_z = 0.0
    previous_end_slope = 0.0
    for i, (seg, length) in enumerate(zip(segs, lengths, strict=True)):
        start_z = get_attnum(seg, "z start", previous_end_z)
        end_z = get_attnum(seg, "z end", start_z)
        start_slope = attnum_si(seg, "profil start tangent", previous_end_slope)
        end_slope = attnum_si(seg, "profil end tangent", start_slope)
        banking_start = attnum_si(seg, "banking start", 0.0)
        banking_end = attnum_si(seg, "banking end", banking_start)
        count = max(1, int(math.ceil(max(length, 0.0) / max(0.25, sample_step))))
        for k in range(count + 1):
            t = k / count
            if get_attstr(seg, "profil", "").lower() == "spline":
                center = hermite(start_z, end_z, start_slope * length, end_slope * length, t)
            else:
                center = start_z + (end_z - start_z) * t
            banking = banking_start + (banking_end - banking_start) * t
            bank_slope = math.tan(banking)
            half_width = 0.5 * lerp_pair(main_widths[i], t)
            left_z = center + bank_slope * half_width
            right_z = center - bank_slope * half_width
            left_outer_z = left_z + left_side_banking * bank_slope * (lerp_pair(left_border[i], t) + lerp_pair(left_side[i], t))
            right_outer_z = right_z - right_side_banking * bank_slope * (lerp_pair(right_border[i], t) + lerp_pair(right_side[i], t))
            min_z = min(min_z, center, left_z, right_z, left_outer_z, right_outer_z)
        previous_end_z = end_z
        previous_end_slope = end_slope
    return 0.0 if not math.isfinite(min_z) else min_z


def write_terrain_elevation_map(
    output_path: pathlib.Path,
    profile_paths: list[str],
    output_xml: pathlib.Path,
    terrain_section: ET.Element | None,
    main_track: ET.Element,
    segs: list[ET.Element],
    segments: list[Segment],
    lengths: list[float],
    total: float,
    width: int,
    resampling: str,
    track_z_offset: float,
) -> TerrainElevationMap:
    """Sample a raster-backed profile into a trackgen-compatible 8-bit PNG.

    Trackgen maps the PNG over `track->min/max` plus `border margin`; each pixel
    encodes a linear height between `minimum altitude` and `maximum altitude`.
    The source raster is sampled in the fitted raster coordinate system and then
    zeroed by the same start elevation used for the road profile.
    """
    if width < 2:
        raise SystemExit("--terrain-elevation-width must be at least 2")
    profile_path, _data, fit, zero_elevation, raster_path = terrain_profile_data(profile_paths, segments, total)
    raster = open_raster(raster_path, "")
    min_x, min_y, max_x, max_y = terrain_generation_bounds(main_track, terrain_section, segs, segments, lengths)
    x_span = max_x - min_x
    y_span = max_y - min_y
    if x_span <= 1e-9 or y_span <= 1e-9:
        raise SystemExit("Terrain elevation map bounds are degenerate")

    height = max(2, int(y_span * width / x_span))
    values = np.empty((height, width), dtype=float)
    missing = 0
    for row in range(height):
        y = min_y + y_span * row / max(1, height - 1)
        for col in range(width):
            x = min_x + x_span * col / max(1, width - 1)
            raster_x, raster_y = transform_with_fit(x, y, fit)
            elevation = raster.sample(raster_x, raster_y, resampling)
            if elevation is None:
                values[row, col] = np.nan
                missing += 1
            else:
                values[row, col] = elevation - zero_elevation + track_z_offset
    if missing:
        raise SystemExit(f"Raster has no elevation at {missing} terrain map pixels; reduce border margin or provide a wider raster")

    min_altitude = float(np.min(values))
    max_altitude = float(np.max(values))
    if max_altitude <= min_altitude + 1e-9:
        max_altitude = min_altitude + 1.0
    gray = np.rint((values - min_altitude) * 255.0 / (max_altitude - min_altitude)).clip(0, 255).astype(np.uint8)
    rgb = np.dstack((gray, gray, gray))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # GfImgReadPng stores the file bottom row at memory row 0. Trackgen then maps
    # memory row 0 to ymin, so write the file top row as ymax to avoid an inverted
    # terrain heightmap.
    Image.fromarray(np.flipud(rgb)).save(output_path)
    return TerrainElevationMap(
        output_path,
        track_relative_value(output_path, output_xml),
        width,
        height,
        min_altitude,
        max_altitude,
        track_z_offset,
        (min_x, min_y, max_x, max_y),
        str(profile_path),
        str(raster_path),
        missing,
    )


def element_segments(segs: list[ET.Element], default_profile_steps_length: float = 6.0) -> list[Segment]:
    out = []
    for seg in segs:
        segment = segment_from_element(seg, default_profile_steps_length)
        if segment is None:
            raise SystemExit(f"Unsupported segment in XML: {seg.get('name', '')}")
        out.append(segment)
    return out


def sample_centerline(segments: list[Segment], step: float) -> list[Sample]:
    pose = Pose(0.0, 0.0, 0.0)
    station = 0.0
    samples = [Sample(pose.x, pose.y, station, pose.heading, "start")]
    for segment in segments:
        pose, seg_samples = sample_segment(pose, segment, station, step)
        if seg_samples:
            station = seg_samples[-1].s
            samples.extend(seg_samples)
    return samples


def interpolate_centerline_sample(samples: list[Sample], station: float, total: float) -> Sample:
    if not samples:
        return Sample(0.0, 0.0, station, 0.0, "start")
    if station >= total - 1e-6:
        first = samples[0]
        return Sample(first.x, first.y, total, first.heading, first.segment)
    for i in range(1, len(samples)):
        if station <= samples[i].s:
            a = samples[i - 1]
            b = samples[i]
            span = b.s - a.s
            t = 0.0 if span <= 1e-9 else (station - a.s) / span
            heading = math.atan2(b.y - a.y, b.x - a.x) if math.hypot(b.x - a.x, b.y - a.y) > 1e-9 else a.heading
            return Sample(a.x + t * (b.x - a.x), a.y + t * (b.y - a.y), station, heading, a.segment or b.segment)
    last = samples[-1]
    return Sample(last.x, last.y, station, last.heading, last.segment)


def resample_centerline(samples: list[Sample], total: float, step: float) -> list[Sample]:
    count = max(3, int(math.ceil(total / max(1.0, step))))
    return [interpolate_centerline_sample(samples, total * i / count, total) for i in range(count)] + [
        interpolate_centerline_sample(samples, total, total)
    ]


def line_height(z: float, distance: float, falloff: float) -> float:
    if falloff <= 0.0:
        return z
    return z * math.exp(-max(0.0, distance) / falloff)


def offset_point(sample: Sample, offset: float) -> tuple[float, float]:
    left_x = -math.sin(sample.heading)
    left_y = math.cos(sample.heading)
    return sample.x + left_x * offset, sample.y + left_y * offset


def signed_area_xy(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        area += p[0] * q[1] - q[0] * p[1]
    return 0.5 * area


def parse_distances(text: str) -> list[float]:
    if text.strip().lower() in ("", "none", "off", "disable", "disabled"):
        return []
    values = [parse_float(p.strip()) for p in text.split(",") if p.strip()]
    values = sorted({v for v in values if v > 0.0})
    if not values:
        raise SystemExit("At least one positive --relief-distances value is required")
    return values


def eval_terrain_lines(lines: list[TerrainLine], side: str, distance: float, station: float, total: float) -> float | None:
    candidates = sorted((line for line in lines if line.side == side), key=terrain_line_xml_distance)
    if not candidates:
        return None
    if distance <= terrain_line_xml_distance(candidates[0]):
        return eval_terrain_line(candidates[0], station, total)
    if distance >= terrain_line_xml_distance(candidates[-1]):
        return eval_terrain_line(candidates[-1], station, total)
    for i in range(1, len(candidates)):
        lo = candidates[i - 1]
        hi = candidates[i]
        lo_distance = terrain_line_xml_distance(lo)
        hi_distance = terrain_line_xml_distance(hi)
        if distance <= hi_distance:
            span = hi_distance - lo_distance
            t = 0.0 if span <= 1e-9 else (distance - lo_distance) / span
            z0 = eval_terrain_line(lo, station, total)
            z1 = eval_terrain_line(hi, station, total)
            return z0 + t * (z1 - z0)
    return None


def width_profile(main_track: ET.Element, segs: list[ET.Element], section_name: str) -> list[tuple[float, float]]:
    section = child_section(main_track, section_name)
    previous_end = get_attnum(section, "width", 0.0)
    profiles = []
    for seg in segs:
        local = child_section(seg, section_name)
        if section_name in ("Left Side", "Right Side"):
            start, end = side_width_profile(local, previous_end)
        else:
            width = get_attnum(local, "width", previous_end) if local is not None else previous_end
            start = get_attnum(local, "start width", width) if local is not None else width
            end = get_attnum(local, "end width", width) if local is not None else width
        profiles.append((max(0.0, start), max(0.0, end)))
        previous_end = max(0.0, end)
    return profiles


def normalization_extent(main_track: ET.Element, segs: list[ET.Element]) -> float:
    width = get_attnum(main_track, "width", 12.0)
    left_side = width_profile(main_track, segs, "Left Side")
    right_side = width_profile(main_track, segs, "Right Side")
    left_border = width_profile(main_track, segs, "Left Border")
    right_border = width_profile(main_track, segs, "Right Border")
    max_left = max((max(a) + max(b) for a, b in zip(left_side, left_border, strict=True)), default=0.0)
    max_right = max((max(a) + max(b) for a, b in zip(right_side, right_border, strict=True)), default=0.0)
    return 0.5 * width + max(max_left, max_right)


def sample_centerline_native(segments: list[Segment], max_step: float) -> list[Sample]:
    pose = Pose(0.0, 0.0, 0.0)
    station = 0.0
    samples = [Sample(pose.x, pose.y, station, pose.heading, "start")]
    for segment in segments:
        step = max(1.0, min(max_step, segment.profil_steps_length if segment.profil_steps_length > 0.0 else max_step))
        pose, seg_samples = sample_segment(pose, segment, station, step)
        if seg_samples:
            station = seg_samples[-1].s
            samples.extend(seg_samples)
    return samples


def sample_spacing(samples: list[Sample]) -> float:
    distances = []
    for i in range(1, len(samples)):
        d = math.hypot(samples[i].x - samples[i - 1].x, samples[i].y - samples[i - 1].y)
        if d > 1e-6:
            distances.append(d)
    if not distances:
        return 5.0
    distances.sort()
    return max(1.0, distances[len(distances) // 2])


def centerline_loop_xy(samples: list[Sample], total: float) -> list[tuple[float, float]]:
    return [(sample.x, sample.y) for sample in samples if sample.s < total - 1e-6]


def closed_loop_gap(samples: list[Sample]) -> float:
    if len(samples) < 2:
        return math.inf
    return math.hypot(samples[-1].x - samples[0].x, samples[-1].y - samples[0].y)


def relief_side_for_data(data: str, ccw: bool) -> tuple[str, float]:
    if data == "interior":
        side = "left" if ccw else "right"
    else:
        side = "right" if ccw else "left"
    return side, 1.0 if side == "left" else -1.0


def edge_points_for_side(samples: list[Sample], total: float, offset: float, sign: float) -> list[ReliefEdgePoint]:
    points = []
    for sample in samples:
        if sample.s >= total - 1e-6:
            continue
        x, y = offset_point(sample, sign * offset)
        outward_x = sign * -math.sin(sample.heading)
        outward_y = sign * math.cos(sample.heading)
        points.append(ReliefEdgePoint(x, y, sample.s, abs(offset), outward_x, outward_y))
    if points:
        first = points[0]
        points.append(ReliefEdgePoint(first.x, first.y, total, first.center_distance, first.outward_x, first.outward_y))
    return points


def track_bbox_from_edges(left_edge: list[ReliefEdgePoint], right_edge: list[ReliefEdgePoint]) -> tuple[float, float, float, float]:
    points = left_edge + right_edge
    if not points:
        return 0.0, 0.0, 0.0, 0.0
    return (
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


def strip_closed_duplicate(points: list[tuple[float, float]], tolerance: float = 1e-6) -> list[tuple[float, float]]:
    if len(points) > 1 and math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]) <= tolerance:
        return points[:-1]
    return list(points)


def xy_points_are_closed(points: list[tuple[float, float]], tolerance: float = 1e-6) -> bool:
    return len(points) > 1 and math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]) <= tolerance


RELIEF_VALIDATION_SCALE = 1000.0


def snap_relief_xy(point: tuple[float, float], scale: float = RELIEF_VALIDATION_SCALE) -> tuple[int, int]:
    return int(round(point[0] * scale)), int(round(point[1] * scale))


def snap_relief_points(points: list[tuple[float, float]], scale: float = RELIEF_VALIDATION_SCALE) -> list[tuple[int, int]]:
    return [snap_relief_xy(point, scale) for point in points]


def orientation2d_int(a: tuple[int, int], b: tuple[int, int], c: tuple[int, int]) -> int:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment2d_int(a: tuple[int, int], b: tuple[int, int], c: tuple[int, int]) -> bool:
    return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1]) and orientation2d_int(a, b, c) == 0


def segments_intersect2d_int(a: tuple[int, int], b: tuple[int, int], c: tuple[int, int], d: tuple[int, int]) -> bool:
    if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
        return False
    if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
        return False
    o1 = orientation2d_int(a, b, c)
    o2 = orientation2d_int(a, b, d)
    o3 = orientation2d_int(c, d, a)
    o4 = orientation2d_int(c, d, b)
    if ((o1 > 0 and o2 < 0) or (o1 < 0 and o2 > 0)) and ((o3 > 0 and o4 < 0) or (o3 < 0 and o4 > 0)):
        return True
    return on_segment2d_int(a, b, c) or on_segment2d_int(a, b, d) or on_segment2d_int(c, d, a) or on_segment2d_int(c, d, b)


def snapped_segments(points: list[tuple[int, int]]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    return list(zip(points[:-1], points[1:], strict=True))


def adjacent_snapped_segments_overlap(a: tuple[int, int], b: tuple[int, int], c: tuple[int, int]) -> bool:
    if orientation2d_int(a, b, c) != 0:
        return False
    return on_segment2d_int(a, b, c) or on_segment2d_int(b, c, a)


def relief_line_endpoint_issues(line_index: int, line: list[tuple[int, int]]) -> list[ReliefValidationIssue]:
    issues: list[ReliefValidationIssue] = []
    if len(line) < 2:
        issues.append(ReliefValidationIssue(line_index, "too_few_points"))
        return issues
    if line[0] == line[-1]:
        issues.append(ReliefValidationIssue(line_index, "closed_line"))
    return issues


def degenerate_relief_segment_issues(
    line_index: int,
    segments: list[tuple[tuple[int, int], tuple[int, int]]],
) -> list[ReliefValidationIssue]:
    issues: list[ReliefValidationIssue] = []
    for seg_index, (a, b) in enumerate(segments):
        if a == b:
            issues.append(ReliefValidationIssue(line_index, "degenerate_segment", f"segment {seg_index}"))
    return issues


def adjacent_relief_overlap_issues(
    line_index: int,
    segments: list[tuple[tuple[int, int], tuple[int, int]]],
) -> list[ReliefValidationIssue]:
    issues: list[ReliefValidationIssue] = []
    for seg_index in range(len(segments) - 1):
        a, b = segments[seg_index]
        _, c = segments[seg_index + 1]
        if adjacent_snapped_segments_overlap(a, b, c):
            issues.append(ReliefValidationIssue(line_index, "self_intersection", f"adjacent segments {seg_index}-{seg_index + 1}"))
    return issues


def relief_self_intersection_issues(
    line_index: int,
    segments: list[tuple[tuple[int, int], tuple[int, int]]],
) -> list[ReliefValidationIssue]:
    issues: list[ReliefValidationIssue] = []
    for i, (a, b) in enumerate(segments):
        if a == b:
            continue
        for j in range(i + 2, len(segments)):
            c, d = segments[j]
            if c == d:
                continue
            if segments_intersect2d_int(a, b, c, d):
                issues.append(ReliefValidationIssue(line_index, "self_intersection", f"segments {i}-{j}"))
                break
    return issues


def validate_relief_line_shape(line_index: int, line: list[tuple[int, int]]) -> list[ReliefValidationIssue]:
    issues = relief_line_endpoint_issues(line_index, line)
    if len(line) < 2:
        return issues
    segments = snapped_segments(line)
    issues.extend(degenerate_relief_segment_issues(line_index, segments))
    issues.extend(adjacent_relief_overlap_issues(line_index, segments))
    issues.extend(relief_self_intersection_issues(line_index, segments))
    return issues


def relief_track_boundary_intersection_issue(
    line_index: int,
    segments: list[tuple[tuple[int, int], tuple[int, int]]],
    snapped_track: list[list[tuple[int, int]]],
) -> ReliefValidationIssue | None:
    for track in snapped_track:
        for a, b in segments:
            if a == b:
                continue
            for c, d in snapped_segments(track):
                if c != d and segments_intersect2d_int(a, b, c, d):
                    return ReliefValidationIssue(line_index, "track_boundary_intersection")
    return None


def relief_line_intersection_issue(
    source_index: int,
    line: list[tuple[int, int]],
    line_index: int,
    other: list[tuple[int, int]],
) -> ReliefValidationIssue | None:
    for a, b in snapped_segments(line):
        if a == b:
            continue
        for c, d in snapped_segments(other):
            if c != d and segments_intersect2d_int(a, b, c, d):
                return ReliefValidationIssue(line_index, "relief_line_intersection", f"line {source_index}")
    return None


def validate_relief_line_intersections(snapped_lines: list[list[tuple[int, int]]]) -> list[ReliefValidationIssue]:
    issues = []
    for i, line in enumerate(snapped_lines):
        for j in range(i + 1, len(snapped_lines)):
            issue = relief_line_intersection_issue(i, line, j, snapped_lines[j])
            if issue is not None:
                issues.append(issue)
    return issues


def validate_relief_breakline_set(
    lines: list[list[tuple[float, float]]],
    track_polylines: list[list[tuple[float, float]]],
    scale: float = RELIEF_VALIDATION_SCALE,
) -> ReliefValidationResult:
    issues: list[ReliefValidationIssue] = []
    snapped_lines = [snap_relief_points(line, scale) for line in lines]
    snapped_track = [snap_relief_points(line, scale) for line in track_polylines]

    for line_index, line in enumerate(snapped_lines):
        issues.extend(validate_relief_line_shape(line_index, line))
        if len(line) < 2:
            continue
        segments = snapped_segments(line)
        boundary_issue = relief_track_boundary_intersection_issue(line_index, segments, snapped_track)
        if boundary_issue is not None:
            issues.append(boundary_issue)

    issues.extend(validate_relief_line_intersections(snapped_lines))

    return ReliefValidationResult(tuple(issues))


def first_relief_validation_reason(result: ReliefValidationResult, default: str = "invalid_relief") -> str:
    return result.issues[0].reason if result.issues else default


def add_relief_rejection(reason_counts: dict[str, int], reason: str) -> None:
    reason_counts[reason] = reason_counts.get(reason, 0) + 1


def point_in_polygon_xy(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    points = strip_closed_duplicate(polygon)
    if len(points) < 3:
        return False
    x, y = point
    inside = False
    xj, yj = points[-1]
    for xi, yi in points:
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        xj, yj = xi, yi
    return inside


def relief_domain_rejection_reason(
    points: list[tuple[float, float]],
    data: str,
    interior_polygon: list[tuple[float, float]],
    exterior_forbidden_polygon: list[tuple[float, float]],
    border_bounds: tuple[float, float, float, float] | None,
) -> str | None:
    if data == "interior" and interior_polygon:
        if any(not point_in_polygon_xy(point, interior_polygon) for point in points):
            return "outside_interior_domain"
    if data == "exterior" and exterior_forbidden_polygon:
        if any(point_in_polygon_xy(point, exterior_forbidden_polygon) for point in points):
            return "inside_track_domain"
    if border_bounds is not None:
        min_x, min_y, max_x, max_y = border_bounds
        for x, y in points:
            if x < min_x or x > max_x or y < min_y or y > max_y:
                return "outside_border"
    return None


def close_xy(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not points:
        return []
    return points + [points[0]]


def orient_trackgen_relief_contour(points: list[tuple[float, float]], data: str) -> list[tuple[float, float]]:
    open_points = strip_closed_duplicate(points)
    if len(open_points) < 3:
        return []
    area = signed_area_xy(open_points)
    want_ccw = data == "exterior"
    if (want_ccw and area < 0.0) or (not want_ccw and area > 0.0):
        open_points = list(reversed(open_points))
    return close_xy(open_points)


def point_in_polygon_mask(grid_x: np.ndarray, grid_y: np.ndarray, polygon: list[tuple[float, float]]) -> np.ndarray:
    inside = np.zeros(grid_x.shape, dtype=bool)
    xj, yj = polygon[-1]
    for xi, yi in polygon:
        dy = yj - yi
        if abs(dy) > 1e-12:
            crosses = ((yi > grid_y) != (yj > grid_y)) & (grid_x < ((xj - xi) * (grid_y - yi) / dy + xi))
            inside ^= crosses
        xj, yj = xi, yi
    return inside


def nearest_edge_distances(grid_x: np.ndarray, grid_y: np.ndarray, edge_points: list[ReliefEdgePoint]) -> np.ndarray:
    edge_x = np.array([point.x for point in edge_points], dtype=float)
    edge_y = np.array([point.y for point in edge_points], dtype=float)
    flat_x = grid_x.ravel()
    flat_y = grid_y.ravel()
    best = np.full(flat_x.shape, np.inf, dtype=float)
    if len(edge_points) == 0:
        return best.reshape(grid_x.shape)
    for start in range(0, flat_x.size, 4096):
        end = min(flat_x.size, start + 4096)
        dx = flat_x[start:end, None] - edge_x[None, :]
        dy = flat_y[start:end, None] - edge_y[None, :]
        best[start:end] = np.min(dx * dx + dy * dy, axis=1)
    return np.sqrt(best).reshape(grid_x.shape)


def contour_step_for_distance(distance: float, base_spacing: float, max_step: float) -> float:
    requested = max(base_spacing, distance * 0.25)
    return max(base_spacing, min(max_step, requested))


def clean_closed_contour(points: list[tuple[float, float]], close_tolerance: float, min_area: float) -> list[tuple[float, float]]:
    if len(points) < 4 or math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]) > close_tolerance:
        return []
    cleaned = []
    for point in points:
        if not cleaned or math.hypot(point[0] - cleaned[-1][0], point[1] - cleaned[-1][1]) > 1e-6:
            cleaned.append(point)
    if math.hypot(cleaned[0][0] - cleaned[-1][0], cleaned[0][1] - cleaned[-1][1]) > 1e-6:
        cleaned.append(cleaned[0])
    else:
        cleaned[-1] = cleaned[0]
    if len(cleaned) < 4 or abs(signed_area_xy(cleaned[:-1])) < min_area:
        return []
    return cleaned


def relief_breakline_gap_count(point_count: int, gap_fraction: float = 0.10) -> int:
    if point_count < 3:
        return 0
    gap = max(3, int(round(point_count * gap_fraction)))
    return min(gap, max(0, point_count - 2))


def open_relief_breakline_points(points: list[tuple[float, float]], gap_fraction: float = 0.10) -> list[tuple[float, float]]:
    # Trackgen treats closed relief contours as holes; leave a real seam so they act as breaklines.
    open_points = strip_closed_duplicate(points)
    gap = relief_breakline_gap_count(len(open_points), gap_fraction) if xy_points_are_closed(points) else 0
    return open_points[gap:] if gap > 0 else open_points


def distance_field_contours(
    center_polygon: list[tuple[float, float]],
    edge_points: list[ReliefEdgePoint],
    distance: float,
    data: str,
    step: float,
) -> list[list[tuple[float, float]]]:
    xs_all = [point[0] for point in center_polygon] + [point.x for point in edge_points]
    ys_all = [point[1] for point in center_polygon] + [point.y for point in edge_points]
    margin = distance + step * 4.0
    xs = np.arange(min(xs_all) - margin, max(xs_all) + margin + step, step)
    ys = np.arange(min(ys_all) - margin, max(ys_all) + margin + step, step)
    if len(xs) < 3 or len(ys) < 3:
        return []
    grid_x, grid_y = np.meshgrid(xs, ys)
    inside = point_in_polygon_mask(grid_x, grid_y, center_polygon)
    mask = inside if data == "interior" else ~inside
    if int(mask.sum()) < 4:
        return []
    field = nearest_edge_distances(grid_x, grid_y, edge_points)
    contours = []
    index_cols = np.arange(len(xs), dtype=float)
    index_rows = np.arange(len(ys), dtype=float)
    for contour in measure.find_contours(field, distance, mask=mask):
        if len(contour) < 4:
            continue
        x_values = np.interp(contour[:, 1], index_cols, xs)
        y_values = np.interp(contour[:, 0], index_rows, ys)
        cleaned = clean_closed_contour(list(zip(x_values.tolist(), y_values.tolist(), strict=True)), step * 1.5, step * step * 0.5)
        if cleaned:
            contours.append(cleaned)
    return contours


def nearest_edge_indices(points: list[tuple[float, float]], edge_points: list[ReliefEdgePoint]) -> list[int]:
    if not edge_points:
        return [0 for _ in points]
    edge_x = np.array([point.x for point in edge_points], dtype=float)
    edge_y = np.array([point.y for point in edge_points], dtype=float)
    query_x = np.array([point[0] for point in points], dtype=float)
    query_y = np.array([point[1] for point in points], dtype=float)
    best = np.zeros(query_x.shape, dtype=int)
    for start in range(0, query_x.size, 2048):
        end = min(query_x.size, start + 2048)
        dx = query_x[start:end, None] - edge_x[None, :]
        dy = query_y[start:end, None] - edge_y[None, :]
        d2 = dx * dx + dy * dy
        local = np.argmin(d2, axis=1)
        best[start:end] = local
    return best.tolist()


def orientation2d(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment2d(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], tolerance: float = 1e-8) -> bool:
    return (
        min(a[0], b[0]) - tolerance <= c[0] <= max(a[0], b[0]) + tolerance
        and min(a[1], b[1]) - tolerance <= c[1] <= max(a[1], b[1]) + tolerance
        and abs(orientation2d(a, b, c)) <= tolerance
    )


def segments_intersect2d(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
    tolerance: float = 1e-8,
) -> bool:
    if max(a[0], b[0]) + tolerance < min(c[0], d[0]) or max(c[0], d[0]) + tolerance < min(a[0], b[0]):
        return False
    if max(a[1], b[1]) + tolerance < min(c[1], d[1]) or max(c[1], d[1]) + tolerance < min(a[1], b[1]):
        return False
    o1 = orientation2d(a, b, c)
    o2 = orientation2d(a, b, d)
    o3 = orientation2d(c, d, a)
    o4 = orientation2d(c, d, b)
    if ((o1 > tolerance and o2 < -tolerance) or (o1 < -tolerance and o2 > tolerance)) and (
        (o3 > tolerance and o4 < -tolerance) or (o3 < -tolerance and o4 > tolerance)
    ):
        return True
    return (
        on_segment2d(a, b, c, tolerance)
        or on_segment2d(a, b, d, tolerance)
        or on_segment2d(c, d, a, tolerance)
        or on_segment2d(c, d, b, tolerance)
    )


def polyline_has_self_intersection(points: list[tuple[float, float]]) -> bool:
    segment_count = len(points) - 1
    closed = xy_points_are_closed(points)
    for i in range(segment_count):
        a = points[i]
        b = points[i + 1]
        for j in range(i + 1, segment_count):
            if abs(i - j) <= 1 or (closed and i == 0 and j == segment_count - 1):
                continue
            if segments_intersect2d(a, b, points[j], points[j + 1]):
                return True
    return False


def polylines_intersect(a_points: list[tuple[float, float]], b_points: list[tuple[float, float]]) -> bool:
    for i in range(len(a_points) - 1):
        a = a_points[i]
        b = a_points[i + 1]
        for j in range(len(b_points) - 1):
            if segments_intersect2d(a, b, b_points[j], b_points[j + 1]):
                return True
    return False


def relief_xy_is_valid(points: list[tuple[float, float]], track_polylines: list[list[tuple[float, float]]]) -> bool:
    if len(points) < 4 or math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]) > 1e-6:
        return False
    if polyline_has_self_intersection(points):
        return False
    return not any(polylines_intersect(points, track_line) for track_line in track_polylines)


def relief_breakline_xy_is_valid(
    points: list[tuple[float, float]],
    track_polylines: list[list[tuple[float, float]]],
    previous_lines: list[list[tuple[float, float]]],
) -> bool:
    return validate_relief_breakline_set(previous_lines + [points], track_polylines).ok


def build_distance_relief_line(
    contour: list[tuple[float, float]],
    edge_points: list[ReliefEdgePoint],
    side: str,
    distance: float,
    data: str,
    profile: BoundaryProfile,
    total: float,
    falloff: float,
    terrain_lines: list[TerrainLine],
    track_z_offset: float,
) -> dict:
    edge_indices = nearest_edge_indices(contour, edge_points)
    z_values = []
    terrain_distances = []
    for edge_index in edge_indices:
        edge_point = edge_points[edge_index] if edge_points else ReliefEdgePoint(0.0, 0.0, 0.0)
        station = edge_point.station
        terrain_distance = edge_point.center_distance + distance
        terrain_z = eval_terrain_lines(terrain_lines, side, terrain_distance, min(station, total), total)
        terrain_distances.append(terrain_distance)
        if terrain_z is None:
            road_z = eval_boundary_linear(profile.stations, profile.elevations, min(station, total))
            z_values.append(line_height(road_z + track_z_offset, distance, falloff))
        else:
            z_values.append(terrain_z + track_z_offset)
    open_xy = strip_closed_duplicate(contour)
    open_z = z_values[: len(open_xy)]
    gap = relief_breakline_gap_count(len(open_xy)) if xy_points_are_closed(contour) else 0
    output_xy = open_xy[gap:] if gap > 0 else open_xy
    output_z = open_z[gap:] if gap > 0 else open_z
    output_distances = terrain_distances[: len(open_xy)]
    if gap > 0:
        output_distances = output_distances[gap:]
    return {
        "side": side,
        "distance_m": distance,
        "data": data,
        "xy_points": contour,
        "output_xy_points": output_xy,
        "z_values": output_z,
        "terrain_distances_m": output_distances,
        "closed": False,
    }


def normalize_distance_relief_lines(lines: list[dict], min_x: float, min_y: float) -> None:
    for line in lines:
        line["points"] = [(x - min_x, z, -(y - min_y)) for (x, y), z in zip(line["output_xy_points"], line["z_values"], strict=True)]


def relief_terrain_sampling_report(lines: list[dict], terrain_lines: list[TerrainLine]) -> dict | None:
    available = {
        side: sorted({terrain_line_xml_distance(line) for line in terrain_lines if line.side == side}) for side in ("left", "right")
    }
    target_values = []
    clamped = 0
    for line in lines:
        side_distances = available.get(str(line.get("side", "")), [])
        for distance in line.get("terrain_distances_m", []):
            value = float(distance)
            target_values.append(value)
            if side_distances and (value < side_distances[0] - 1e-9 or value > side_distances[-1] + 1e-9):
                clamped += 1
    if not target_values:
        return None
    return {
        "target_centerline_distance_min_m": min(target_values),
        "target_centerline_distance_max_m": max(target_values),
        "available_centerline_distances_m": available,
        "clamped_sample_count": clamped,
    }


def relief_line_inside_border(line: dict, min_x: float, min_y: float, max_x: float, max_y: float, margin: float | None) -> bool:
    if margin is None:
        return True
    for x, y in line["output_xy_points"]:
        nx = x - min_x
        ny = y - min_y
        if nx < -margin - 1e-6 or nx > (max_x - min_x) + margin + 1e-6:
            return False
        if ny < -margin - 1e-6 or ny > (max_y - min_y) + margin + 1e-6:
            return False
    return True


def distance_relief_line_rejection_reason(
    line: dict,
    raw_lines: list[dict],
    track_polylines: list[list[tuple[float, float]]],
    border_box: tuple[float, float, float, float],
    border_margin: float | None,
    data: str,
    interior_polygon: list[tuple[float, float]],
    exterior_forbidden_polygon: list[tuple[float, float]],
    border_bounds: tuple[float, float, float, float] | None,
) -> str | None:
    track_min_x, track_min_y, track_max_x, track_max_y = border_box
    if not relief_xy_is_valid(line["xy_points"], track_polylines):
        return "invalid_closed_contour"
    if not relief_line_inside_border(line, track_min_x, track_min_y, track_max_x, track_max_y, border_margin):
        return "outside_border"
    if any(polylines_intersect(line["xy_points"], previous["xy_points"]) for previous in raw_lines):
        return "relief_contour_intersection"
    domain_reason = relief_domain_rejection_reason(
        line["output_xy_points"], data, interior_polygon, exterior_forbidden_polygon, border_bounds
    )
    if domain_reason is not None:
        return domain_reason
    validation = validate_relief_breakline_set(
        [previous["output_xy_points"] for previous in raw_lines] + [line["output_xy_points"]], track_polylines
    )
    if not validation.ok:
        return first_relief_validation_reason(validation)
    return None


def try_append_distance_relief_contour(
    raw_lines: list[dict],
    contour: list[tuple[float, float]],
    edge_points: list[ReliefEdgePoint],
    side: str,
    distance: float,
    data: str,
    profile: BoundaryProfile,
    total: float,
    falloff: float,
    terrain_lines: list[TerrainLine],
    track_z_offset: float,
    track_polylines: list[list[tuple[float, float]]],
    border_box: tuple[float, float, float, float],
    border_margin: float | None,
    interior_polygon: list[tuple[float, float]],
    exterior_forbidden_polygon: list[tuple[float, float]],
    border_bounds: tuple[float, float, float, float] | None,
) -> tuple[bool, str | None]:
    contour = orient_trackgen_relief_contour(contour, data)
    if not contour:
        return False, "invalid_contour"
    line = build_distance_relief_line(contour, edge_points, side, distance, data, profile, total, falloff, terrain_lines, track_z_offset)
    reason = distance_relief_line_rejection_reason(
        line,
        raw_lines,
        track_polylines,
        border_box,
        border_margin,
        data,
        interior_polygon,
        exterior_forbidden_polygon,
        border_bounds,
    )
    if reason is not None:
        return False, reason
    raw_lines.append(line)
    return True, None


def append_distance_relief_contours(
    raw_lines: list[dict],
    contours: list[list[tuple[float, float]]],
    edge_points: list[ReliefEdgePoint],
    side: str,
    distance: float,
    data: str,
    profile: BoundaryProfile,
    total: float,
    falloff: float,
    terrain_lines: list[TerrainLine],
    track_z_offset: float,
    track_polylines: list[list[tuple[float, float]]],
    border_box: tuple[float, float, float, float],
    border_margin: float | None,
    interior_polygon: list[tuple[float, float]],
    exterior_forbidden_polygon: list[tuple[float, float]],
    border_bounds: tuple[float, float, float, float] | None,
    rejection_reasons: dict[str, int],
) -> tuple[int, int]:
    accepted = 0
    rejected = 0
    for contour in contours:
        ok, reason = try_append_distance_relief_contour(
            raw_lines,
            contour,
            edge_points,
            side,
            distance,
            data,
            profile,
            total,
            falloff,
            terrain_lines,
            track_z_offset,
            track_polylines,
            border_box,
            border_margin,
            interior_polygon,
            exterior_forbidden_polygon,
            border_bounds,
        )
        if ok:
            accepted += 1
        else:
            rejected += 1
            add_relief_rejection(rejection_reasons, str(reason))
    return accepted, rejected


def distance_relief_edges_and_bounds(
    native_samples: list[Sample],
    total: float,
    protected_offset: float,
    track_edges: tuple[list[ReliefEdgePoint], list[ReliefEdgePoint]] | None,
    track_bounds: tuple[float, float, float, float] | None,
) -> tuple[list[ReliefEdgePoint], list[ReliefEdgePoint], tuple[float, float, float, float]]:
    if track_edges is None:
        left_edge = edge_points_for_side(native_samples, total, protected_offset, 1.0)
        right_edge = edge_points_for_side(native_samples, total, protected_offset, -1.0)
    else:
        left_edge, right_edge = track_edges
    if track_bounds is None:
        track_bounds = track_bbox_from_edges(left_edge, right_edge)
    return left_edge, right_edge, track_bounds


def distance_relief_specs(distances: list[float], interior_max_distance: float) -> list[tuple[float, str]]:
    return [
        (distance, data)
        for distance in distances
        for data in ("interior", "exterior")
        if data != "interior" or distance <= interior_max_distance
    ]


def build_distance_relief_lines(
    main_track: ET.Element,
    xml_segs: list[ET.Element],
    native_samples: list[Sample],
    center_polygon: list[tuple[float, float]],
    profile: BoundaryProfile,
    total: float,
    distances: list[float],
    sample_step: float,
    falloff: float,
    terrain_lines: list[TerrainLine],
    interior_max_distance: float,
    border_margin: float | None = None,
    track_z_offset: float = 0.0,
    track_edges: tuple[list[ReliefEdgePoint], list[ReliefEdgePoint]] | None = None,
    track_bounds: tuple[float, float, float, float] | None = None,
) -> tuple[list[dict], dict]:
    ccw = signed_area_xy(center_polygon) > 0.0
    protected_offset = normalization_extent(main_track, xml_segs)
    base_spacing = sample_spacing(native_samples)
    left_edge, right_edge, track_bounds = distance_relief_edges_and_bounds(
        native_samples, total, protected_offset, track_edges, track_bounds
    )
    track_min_x, track_min_y, track_max_x, track_max_y = track_bounds
    center_line = center_polygon + [center_polygon[0]]
    left_edge_xy = [(point.x, point.y) for point in left_edge]
    right_edge_xy = [(point.x, point.y) for point in right_edge]
    track_polylines = [center_line, left_edge_xy, right_edge_xy]
    interior_polygon = left_edge_xy if ccw else right_edge_xy
    exterior_forbidden_polygon = right_edge_xy if ccw else left_edge_xy
    border_box = (track_min_x, track_min_y, track_max_x, track_max_y)
    border_bounds = (
        None
        if border_margin is None
        else (track_min_x - border_margin, track_min_y - border_margin, track_max_x + border_margin, track_max_y + border_margin)
    )

    raw_lines: list[dict] = []
    rejected = 0
    rejection_reasons: dict[str, int] = {}
    contour_reports = []
    for distance, data in distance_relief_specs(distances, interior_max_distance):
        side, sign = relief_side_for_data(data, ccw)
        edge_points = left_edge if sign > 0.0 else right_edge
        step = contour_step_for_distance(distance, base_spacing, max(1.0, sample_step))
        contours = distance_field_contours(center_polygon, edge_points, distance, data, step)
        accepted_for_spec, rejected_for_spec = append_distance_relief_contours(
            raw_lines,
            contours,
            edge_points,
            side,
            distance,
            data,
            profile,
            total,
            falloff,
            terrain_lines,
            track_z_offset,
            track_polylines,
            border_box,
            border_margin,
            interior_polygon,
            exterior_forbidden_polygon,
            border_bounds,
            rejection_reasons,
        )
        rejected += rejected_for_spec
        contour_reports.append(
            {
                "data": data,
                "side": side,
                "distance_m": distance,
                "step_m": step,
                "contours": len(contours),
                "accepted": accepted_for_spec,
            }
        )

    normalize_distance_relief_lines(raw_lines, track_min_x, track_min_y)

    return raw_lines, {
        "method": "distance-field",
        "orientation": "ccw" if ccw else "cw",
        "normalization_min_x": track_min_x,
        "normalization_min_y": track_min_y,
        "track_max_x": track_max_x - track_min_x,
        "track_max_y": track_max_y - track_min_y,
        "border_margin_m": border_margin,
        "protected_offset_m": protected_offset,
        "base_sample_spacing_m": base_spacing,
        "breakline_gap_fraction": 0.10,
        "track_z_offset_m": track_z_offset,
        "terrain_sampling": relief_terrain_sampling_report(raw_lines, terrain_lines),
        "rejected_line_count": rejected,
        "rejection_reasons": rejection_reasons,
        "contours": contour_reports,
    }


def offset_relief_line_samples(
    edge_points: list[ReliefEdgePoint],
    total: float,
    side: str,
    distance: float,
    profile: BoundaryProfile,
    falloff: float,
    terrain_lines: list[TerrainLine],
    track_z_offset: float,
) -> tuple[list[tuple[float, float]], list[float], list[float]]:
    xy_points = []
    z_values = []
    terrain_distances = []
    for edge_point in edge_points:
        if edge_point.station > total + 1e-6:
            continue
        x = edge_point.x + distance * edge_point.outward_x
        y = edge_point.y + distance * edge_point.outward_y
        terrain_distance = edge_point.center_distance + distance
        station = min(edge_point.station, total)
        terrain_z = eval_terrain_lines(terrain_lines, side, terrain_distance, station, total)
        if terrain_z is None:
            z = eval_boundary_linear(profile.stations, profile.elevations, station)
            zn = line_height(z + track_z_offset, distance, falloff)
        else:
            zn = terrain_z + track_z_offset
        xy_points.append((x, y))
        z_values.append(zn)
        terrain_distances.append(terrain_distance)
    return xy_points, z_values, terrain_distances


def open_offset_relief_output(
    xy_points: list[tuple[float, float]],
    z_values: list[float],
    terrain_distances: list[float],
) -> tuple[list[tuple[float, float]], list[float], list[float]]:
    open_xy = strip_closed_duplicate(xy_points)
    open_z = z_values[: len(open_xy)]
    open_distances = terrain_distances[: len(open_xy)]
    gap = relief_breakline_gap_count(len(open_xy)) if xy_points_are_closed(xy_points) else 0
    output_xy = open_xy[gap:] if gap > 0 else open_xy
    output_z = open_z[gap:] if gap > 0 else open_z
    output_distances = open_distances[gap:] if gap > 0 else open_distances
    return output_xy, output_z, output_distances


def build_offset_relief_line(
    edge_points: list[ReliefEdgePoint],
    total: float,
    side: str,
    distance: float,
    data: str,
    profile: BoundaryProfile,
    falloff: float,
    terrain_lines: list[TerrainLine],
    track_z_offset: float,
    min_x: float,
    min_y: float,
) -> dict:
    xy_points, z_values, terrain_distances = offset_relief_line_samples(
        edge_points, total, side, distance, profile, falloff, terrain_lines, track_z_offset
    )
    output_xy, output_z, output_distances = open_offset_relief_output(xy_points, z_values, terrain_distances)
    points = [(x - min_x, z, -(y - min_y)) for (x, y), z in zip(output_xy, output_z, strict=True)]
    return {
        "side": side,
        "distance_m": distance,
        "data": data,
        "xy_points": xy_points,
        "output_xy_points": output_xy,
        "z_values": output_z,
        "terrain_distances_m": output_distances,
        "points": points,
        "closed": False,
    }


def append_offset_relief_line(
    raw_lines: list[dict],
    line: dict,
    track_polylines: list[list[tuple[float, float]]],
    rejection_reasons: dict[str, int],
) -> bool:
    validation = validate_relief_breakline_set(
        [previous["output_xy_points"] for previous in raw_lines] + [line["output_xy_points"]], track_polylines
    )
    if not validation.ok:
        add_relief_rejection(rejection_reasons, first_relief_validation_reason(validation))
        return False
    raw_lines.append(line)
    return True


def offset_relief_line_specs(
    ccw: bool,
    distances: list[float],
    interior_max_distance: float,
) -> list[tuple[str, float, str]]:
    specs = []
    for side in ("left", "right"):
        data = "interior" if (side == "left") == ccw else "exterior"
        for distance in distances:
            if data == "interior" and distance > interior_max_distance:
                continue
            specs.append((side, distance, data))
    return specs


def offset_relief_build_info(
    ccw: bool,
    min_x: float,
    min_y: float,
    rejected: int,
    rejection_reasons: dict[str, int],
    track_z_offset: float,
) -> dict:
    return {
        "method": "offset-fallback",
        "orientation": "ccw" if ccw else "cw",
        "normalization_min_x": min_x,
        "normalization_min_y": min_y,
        "track_z_offset_m": track_z_offset,
        "rejected_line_count": rejected,
        "rejection_reasons": rejection_reasons,
    }


def build_offset_relief_lines(
    main_track: ET.Element,
    xml_segs: list[ET.Element],
    segments: list[Segment],
    profile: BoundaryProfile,
    total: float,
    distances: list[float],
    sample_step: float,
    falloff: float,
    terrain_lines: list[TerrainLine],
    interior_max_distance: float,
    track_z_offset: float = 0.0,
    track_edges: tuple[list[ReliefEdgePoint], list[ReliefEdgePoint]] | None = None,
    track_bounds: tuple[float, float, float, float] | None = None,
) -> tuple[list[dict], dict]:
    samples = resample_centerline(sample_centerline(segments, sample_step), total, sample_step)
    width = get_attnum(main_track, "width", 12.0)
    half_width = 0.5 * width
    center_xy = [(s.x, s.y) for s in samples[:-1] if s.s < total - 1e-6]
    ccw = signed_area_xy(center_xy) > 0.0
    if track_edges is None:
        left_edge = edge_points_for_side(samples, total, half_width, 1.0)
        right_edge = edge_points_for_side(samples, total, half_width, -1.0)
    else:
        left_edge, right_edge = track_edges
    track_polylines = [center_xy] if len(center_xy) >= 2 else []

    raw_lines: list[dict] = []
    rejected = 0
    rejection_reasons: dict[str, int] = {}
    if track_bounds is None:
        track_bounds = track_bbox_from_edges(left_edge, right_edge)
    min_x, min_y, _max_x, _max_y = track_bounds

    for side, distance, data in offset_relief_line_specs(ccw, distances, interior_max_distance):
        edge_points = left_edge if side == "left" else right_edge
        line = build_offset_relief_line(
            edge_points, total, side, distance, data, profile, falloff, terrain_lines, track_z_offset, min_x, min_y
        )
        if not append_offset_relief_line(raw_lines, line, track_polylines, rejection_reasons):
            rejected += 1

    info = offset_relief_build_info(ccw, min_x, min_y, rejected, rejection_reasons, track_z_offset)
    info["terrain_sampling"] = relief_terrain_sampling_report(raw_lines, terrain_lines)
    return raw_lines, info


def build_relief_lines(
    main_track: ET.Element,
    xml_segs: list[ET.Element],
    segments: list[Segment],
    profile: BoundaryProfile,
    total: float,
    distances: list[float],
    sample_step: float,
    falloff: float,
    terrain_lines: list[TerrainLine],
    interior_max_distance: float,
    border_margin: float | None = None,
    track_z_offset: float = 0.0,
) -> tuple[list[dict], dict]:
    native_samples = sample_centerline_native(segments, max(1.0, sample_step))
    center_polygon = centerline_loop_xy(native_samples, total)
    gap = closed_loop_gap(native_samples)
    spacing = sample_spacing(native_samples)
    lengths = [segment_length(seg) for seg in xml_segs]
    track_edges = track_outer_edge_points(main_track, xml_segs, segments, lengths, max(1.0, sample_step), close=True)
    track_bounds = track_bounds_for_terrain(main_track, xml_segs, segments, lengths, 1.0)
    if not distances:
        return [], {
            "method": "none",
            "fallback_reason": "relief-distances-disabled",
            "closed_gap_m": gap,
            "base_sample_spacing_m": spacing,
            "track_z_offset_m": track_z_offset,
        }
    if len(center_polygon) >= 4 and abs(signed_area_xy(center_polygon)) > 1.0 and gap <= max(5.0, spacing * 2.0):
        lines, info = build_distance_relief_lines(
            main_track,
            xml_segs,
            native_samples,
            center_polygon,
            profile,
            total,
            distances,
            sample_step,
            falloff,
            terrain_lines,
            interior_max_distance,
            border_margin,
            track_z_offset,
            track_edges,
            track_bounds,
        )
        info["closed_gap_m"] = gap
        if lines:
            return lines, info
        info["fallback_reason"] = "no-valid-distance-contours"
        return lines, info

    lines, info = build_offset_relief_lines(
        main_track,
        xml_segs,
        segments,
        profile,
        total,
        distances,
        sample_step,
        falloff,
        terrain_lines,
        interior_max_distance,
        track_z_offset,
        track_edges,
        track_bounds,
    )
    info["fallback_reason"] = "open-or-degenerate-centerline"
    info["closed_gap_m"] = gap
    return lines, info


def write_ac_number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def relief_line_plan_points(line: dict) -> list[tuple[float, float]]:
    return [(float(x), -float(z)) for x, _y, z in line.get("points", [])]


def validate_relief_ac_lines(lines: list[dict]) -> ReliefValidationResult:
    issues = []
    for index, line in enumerate(lines):
        if str(line.get("data", "")) not in ("interior", "exterior"):
            issues.append(ReliefValidationIssue(index, "invalid_data"))
        if line.get("closed"):
            issues.append(ReliefValidationIssue(index, "closed_line"))
    result = validate_relief_breakline_set([relief_line_plan_points(line) for line in lines], [])
    return ReliefValidationResult(tuple(issues) + result.issues)


def format_relief_validation_issues(result: ReliefValidationResult) -> str:
    counts = result.reason_counts()
    return ", ".join(f"{reason}={count}" for reason, count in sorted(counts.items()))


def write_relief_ac(path: pathlib.Path, lines: list[dict]) -> None:
    validation = validate_relief_ac_lines(lines)
    if not validation.ok:
        raise ValueError(f"Invalid relief breaklines: {format_relief_validation_issues(validation)}")
    out = [
        "AC3Db",
        'MATERIAL "tracktools-relief" rgb 0 0 1 amb 0.2 0.2 0.2 emis 0 0 0 spec 0.5 0.5 0.5 shi 10 trans 0',
        "OBJECT world",
        f"kids {len(lines)}",
    ]
    for idx, line in enumerate(lines):
        points = line["points"]
        data = str(line["data"])
        out.extend(
            [
                "OBJECT poly",
                f'name "{data}-relief-{line["side"]}-{idx}"',
                f"data {len(data)}",
                data,
                f"numvert {len(points)}",
            ]
        )
        for x, y, z in points:
            out.append(f"{write_ac_number(x)} {write_ac_number(y)} {write_ac_number(z)}")
        out.extend(["numsurf 1", "SURF 0x22", "mat 0", f"refs {len(points)}"])
        for i in range(len(points)):
            out.append(f"{i} 0 0")
        out.append("kids 0")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def hermite(p0: float, p1: float, t0: float, t1: float, t: float) -> float:
    t2 = t * t
    t3 = t * t2
    h1 = 3.0 * t2 - 2.0 * t3
    h0 = 1.0 - h1
    h2 = t3 - 2.0 * t2 + t
    h3 = t3 - t2
    return h0 * p0 + h1 * p1 + h2 * t0 + h3 * t1


def smoothness_report(
    segs: list[ET.Element],
    lengths: list[float],
    profile: BoundaryProfile,
    track_width: float,
    sample_step: float = 5.0,
) -> dict:
    samples = []
    total = sum(lengths)
    for i, seg in enumerate(segs):
        length = lengths[i]
        if length <= 1e-9:
            continue
        count = max(1, int(math.ceil(length / max(1.0, sample_step))))
        start_z = profile.elevations[i]
        end_z = profile.elevations[(i + 1) % len(segs)]
        start_t = profile.tangents[i] * length
        end_t = profile.tangents[(i + 1) % len(segs)] * length
        banking_start = attnum_si(seg, "banking start", 0.0)
        banking_end = attnum_si(seg, "banking end", banking_start)
        for k in range(count + 1):
            t = k / count
            center = hermite(start_z, end_z, start_t, end_t, t)
            banking = banking_start + (banking_end - banking_start) * t
            dz = math.tan(banking) * track_width * 0.5
            samples.append(
                {
                    "s": (profile.stations[i] + t * length) % max(total, 1e-9),
                    "segment": seg.get("name", ""),
                    "center": center,
                    "left": center + dz,
                    "right": center - dz,
                }
            )
    metrics = {}
    for key in ("center", "left", "right"):
        grades = []
        curvatures = []
        ordered = sorted(samples, key=lambda item: item["s"])
        for i in range(1, len(ordered)):
            ds = ordered[i]["s"] - ordered[i - 1]["s"]
            if ds <= 1e-9:
                continue
            grades.append((ordered[i][key] - ordered[i - 1][key]) / ds)
        for i in range(1, len(grades)):
            ds = max(1.0, sample_step)
            curvatures.append(abs(grades[i] - grades[i - 1]) / ds)
        metrics[key] = {
            "max_abs_grade_pct": max((abs(g) * 100.0 for g in grades), default=0.0),
            "max_grade_change_pct_per_m": max((c * 100.0 for c in curvatures), default=0.0),
        }
    return {
        "sample_count": len(samples),
        "delta_z_m": 0.0 if not profile.elevations else profile.elevations[0] - profile.elevations[0],
        "min_elevation_m": min(profile.elevations, default=0.0),
        "max_elevation_m": max(profile.elevations, default=0.0),
        "metrics": metrics,
    }


def validate_apply_elevation_args(args: argparse.Namespace) -> None:
    if args.bank_max_rate_deg_per_m != 0.0:
        raise SystemExit("--bank-max-rate-deg-per-m is reserved and not implemented; leave it at 0")
    if args.pit_side_banking != "tangent":
        raise SystemExit("--pit-side-banking is reserved and not implemented; leave it as tangent")


def load_elevation_sources(
    args: argparse.Namespace,
) -> tuple[list[ProfileSource], list[ProfileSource], list[TerrainLine], list[TerrainFit]]:
    profile_paths = [pathlib.Path(p) for p in args.profile]
    sources: list[ProfileSource] = []
    banking_sources: list[ProfileSource] = []
    for path in profile_paths:
        try:
            sources.append(read_profile(path))
        except SystemExit as exc:
            if "Road-surface profile has no elevation samples" not in str(exc):
                raise
        banking_sources.extend(read_banking_profiles(path))
    cache_paths = [pathlib.Path(p) for p in args.elevation_cache]
    terrain_fits = terrain_fits_from_profile_paths(profile_paths)
    sources.extend(read_profile(path) for path in cache_paths)
    terrain_lines = [line for path in cache_paths for line in read_terrain_lines(path)]
    if args.point:
        sources.append(ProfileSource("inline-points", validate_profile_samples([parse_profile_point(p) for p in args.point]), 1.0))
    if not sources and not (args.apply_banking and args.banking_profile_only and banking_sources):
        raise SystemExit("No elevation profile supplied; use --profile or repeated --point values")
    return sources, banking_sources, terrain_lines, terrain_fits


def load_track_elevation_context(
    track_xml: pathlib.Path,
) -> tuple[str, ET.ElementTree, ET.Element, ET.Element, list[ET.Element], list[Segment], list[float], float]:
    prolog, tree = parse_xml_preserve_prolog(track_xml)
    root = tree.getroot()
    main_track, segs = segment_sections(root)
    if not segs:
        raise SystemExit("Track XML has no track segments")
    segments = element_segments(segs, get_attnum(main_track, "profil steps length", 6.0))
    lengths = [segment_length(seg) for seg in segs]
    total = sum(lengths)
    if total <= 0.0:
        raise SystemExit("Track length is zero")
    return prolog, tree, root, main_track, segs, segments, lengths, total


def align_elevation_sources(
    args: argparse.Namespace,
    sources: list[ProfileSource],
    banking_sources: list[ProfileSource],
    segs: list[ET.Element],
    lengths: list[float],
    total: float,
) -> tuple[list[ProfileSource], list[dict], list[ProfileSource], list[dict]]:
    xml_ranges = xml_landmark_ranges(segs, lengths)
    sources, alignment_reports = align_sources_to_xml_landmarks(sources, xml_ranges, total, args.align_source_landmarks)
    banking_sources, banking_alignment_reports = align_sources_to_xml_landmarks(
        banking_sources, xml_ranges, total, args.align_source_landmarks
    )
    return sources, alignment_reports, banking_sources, banking_alignment_reports


def write_optional_report(report_arg: str, report: dict) -> None:
    if report_arg:
        report_path = pathlib.Path(report_arg)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def banking_report_summary(banking_profile: BankingProfile | None, args: argparse.Namespace) -> dict | None:
    if banking_profile is None:
        return None
    return {
        "min_deg": min(banking_profile.banking_deg, default=0.0),
        "max_deg": max(banking_profile.banking_deg, default=0.0),
        "width_policy": args.bank_width_policy,
    }


def run_banking_profile_only(
    args: argparse.Namespace,
    prolog: str,
    tree: ET.ElementTree,
    main_track: ET.Element,
    segs: list[ET.Element],
    banking_profile: BankingProfile | None,
    banking_sources: list[ProfileSource],
    banking_alignment_reports: list[dict],
    track_xml: pathlib.Path,
    output_xml: pathlib.Path,
    total: float,
) -> int:
    if banking_profile is None:
        raise SystemExit("--banking-profile-only requires --apply-banking and at least one banking profile")
    if not args.dry_run:
        apply_banking_to_xml(main_track, segs, banking_profile, banking_sources, args)
        output_xml.parent.mkdir(parents=True, exist_ok=True)
        output_xml.write_text(serialize_xml_restore_entity(prolog, tree), encoding="utf-8")
    report = {
        "track_xml": str(track_xml),
        "output_xml": str(output_xml),
        "total_length_m": total,
        "segment_count": len(segs),
        "banking_source_count": len(banking_sources),
        "banking_sources": [
            {"name": s.name, "sample_count": len(s.samples), "weight": s.weight, "source_reversed": s.source_reversed}
            for s in banking_sources
        ],
        "banking_source_alignment": banking_alignment_reports,
        "banking": banking_report_summary(banking_profile, args),
        "dry_run": bool(args.dry_run),
    }
    write_optional_report(args.report, report)
    print(f"Track length: {total:.2f} m")
    print(f"Banking range: {report['banking']['min_deg']:.2f} deg .. {report['banking']['max_deg']:.2f} deg")
    if args.dry_run:
        print("Dry run: XML not written")
    return 0


def apply_elevation_outputs(
    args: argparse.Namespace,
    prolog: str,
    tree: ET.ElementTree,
    root: ET.Element,
    main_track: ET.Element,
    segs: list[ET.Element],
    segments: list[Segment],
    lengths: list[float],
    total: float,
    profile: BoundaryProfile,
    banking_profile: BankingProfile | None,
    banking_sources: list[ProfileSource],
    relief_path: pathlib.Path,
    relief_lines: list[dict],
    output_xml: pathlib.Path,
    terrain_section: ET.Element | None,
    terrain_map_path: pathlib.Path | None,
    track_z_offset: float,
) -> tuple[str, TerrainElevationMap | None]:
    relief_value = str(relief_path)
    terrain_map: TerrainElevationMap | None = None
    if not args.dry_run:
        apply_profile_to_xml(segs, profile)
        if banking_profile is not None:
            apply_banking_to_xml(main_track, segs, banking_profile, banking_sources, args)
        if terrain_map_path is not None:
            terrain_map = write_terrain_elevation_map(
                terrain_map_path,
                args.profile,
                output_xml,
                terrain_section,
                main_track,
                segs,
                segments,
                lengths,
                total,
                args.terrain_elevation_width,
                args.terrain_elevation_resampling,
                track_z_offset,
            )
        relief_value = update_terrain_xml(root, relief_path, output_xml, terrain_map)
        output_xml.parent.mkdir(parents=True, exist_ok=True)
        output_xml.write_text(serialize_xml_restore_entity(prolog, tree), encoding="utf-8")
        write_relief_ac(relief_path, relief_lines)
    return relief_value, terrain_map


def build_apply_elevation_report(
    args: argparse.Namespace,
    track_xml: pathlib.Path,
    output_xml: pathlib.Path,
    total: float,
    segs: list[ET.Element],
    sources: list[ProfileSource],
    alignment_reports: list[dict],
    banking_sources: list[ProfileSource],
    banking_alignment_reports: list[dict],
    banking_profile: BankingProfile | None,
    terrain_lines: list[TerrainLine],
    profile: BoundaryProfile,
    relief_value: str,
    relief_lines: list[dict],
    distances: list[float],
    relief_info: dict,
    terrain_map: TerrainElevationMap | None,
    smoothness: dict,
) -> dict:
    return {
        "track_xml": str(track_xml),
        "output_xml": str(output_xml),
        "total_length_m": total,
        "segment_count": len(segs),
        "source_count": len(sources),
        "sources": [{"name": s.name, "sample_count": len(s.samples), "weight": s.weight} for s in sources],
        "source_alignment": alignment_reports,
        "banking_source_count": len(banking_sources),
        "banking_sources": [
            {"name": s.name, "sample_count": len(s.samples), "weight": s.weight, "source_reversed": s.source_reversed}
            for s in banking_sources
        ],
        "banking_source_alignment": banking_alignment_reports,
        "banking": banking_report_summary(banking_profile, args),
        "terrain_line_count": len(terrain_lines),
        "terrain_source_alignment": terrain_source_alignment_report(terrain_lines),
        "first_z_start_m": 0.0,
        "last_z_end_m": 0.0,
        "pit_ranges": profile.pit_ranges,
        "relief_file": relief_value,
        "relief_line_count": len(relief_lines),
        "relief_distances_m": distances,
        "relief": relief_info,
        "terrain_elevation_map": None
        if terrain_map is None
        else {
            "path": str(terrain_map.path),
            "xml_value": terrain_map.xml_value,
            "width": terrain_map.width,
            "height": terrain_map.height,
            "minimum_altitude_m": terrain_map.min_altitude,
            "maximum_altitude_m": terrain_map.max_altitude,
            "track_z_offset_m": terrain_map.track_z_offset,
            "bounds": terrain_map.bounds,
            "source_profile": terrain_map.source_profile,
            "raster": terrain_map.raster,
            "missing_sample_count": terrain_map.missing_sample_count,
        },
        "smoothness": smoothness,
        "dry_run": bool(args.dry_run),
    }


def print_apply_elevation_summary(
    args: argparse.Namespace,
    total: float,
    smoothness: dict,
    banking_profile: BankingProfile | None,
    relief_lines: list[dict],
    relief_path: pathlib.Path,
    terrain_map: TerrainElevationMap | None,
) -> None:
    print(f"Track length: {total:.2f} m")
    print(f"Elevation range: {smoothness['min_elevation_m']:.2f} m .. {smoothness['max_elevation_m']:.2f} m")
    if banking_profile is not None:
        print(
            f"Banking range: {min(banking_profile.banking_deg, default=0.0):.2f} deg .. {max(banking_profile.banking_deg, default=0.0):.2f} deg"
        )
    print(f"Relief lines: {len(relief_lines)} -> {relief_path}")
    if terrain_map is not None:
        print(f"Terrain elevation map: {terrain_map.path} ({terrain_map.width}x{terrain_map.height})")
    if args.dry_run:
        print("Dry run: XML and relief file not written")


def absolute_start_elevations(sources: list[ProfileSource], total: float) -> list[tuple[float, float]]:
    """Evaluate absolute sources in their aligned station frame before zeroing."""
    result = []
    for source in sources:
        path = pathlib.Path(source.name)
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            continue
        if "zero_elevation_m" in data:
            result.append((float(data["zero_elevation_m"]) + eval_source(source, 0.0, total), source.weight))
        elif isinstance(data.get("source"), dict) and data["source"].get("type") == "dem-corridor":
            result.append((eval_source(source, 0.0, total), source.weight))
    return result


def main() -> int:
    args = parse_args()
    validate_apply_elevation_args(args)
    track_xml = pathlib.Path(args.track_xml)
    output_xml = pathlib.Path(args.output_xml) if args.output_xml else track_xml
    if not track_xml.exists():
        raise SystemExit(f"Track XML not found: {track_xml}")

    sources, banking_sources, terrain_lines, terrain_fits = load_elevation_sources(args)
    prolog, tree, root, main_track, segs, segments, lengths, total = load_track_elevation_context(track_xml)
    sources, alignment_reports, banking_sources, banking_alignment_reports = align_elevation_sources(
        args, sources, banking_sources, segs, lengths, total
    )
    banking_profile = build_banking_profile(banking_sources, segs, lengths, total, args) if args.apply_banking else None

    if args.banking_profile_only:
        return run_banking_profile_only(
            args, prolog, tree, main_track, segs, banking_profile, banking_sources, banking_alignment_reports, track_xml, output_xml, total
        )

    terrain_lines = align_terrain_lines_to_sources(terrain_lines, sources, total, terrain_fits)
    profile = build_boundary_profile(sources, main_track, segs, lengths, total, args)
    # The profile is zeroed at the new start. Only an absolute source can
    # supply sea-level altitude; invalidate any old vertical datum first.
    from torcs_track_tools.core.track_georeference import update_elevation_reference

    update_elevation_reference(root, absolute_start_elevations(sources, total))
    if banking_profile is not None:
        apply_banking_to_xml(main_track, segs, banking_profile, banking_sources, args)
    distances = parse_distances(args.relief_distances)
    relief_path = pathlib.Path(args.relief_output) if args.relief_output else output_xml.with_name(f"{output_xml.stem}-relief.ac")
    terrain_section = child_section(child_section(root, "Graphic"), "Terrain Generation")
    border_margin = get_attnum(terrain_section, "border margin", 100.0)
    track_z_offset = -road_visual_min_elevation(main_track, segs, lengths, profile)
    relief_lines, relief_info = build_relief_lines(
        main_track,
        segs,
        segments,
        profile,
        total,
        distances,
        args.relief_sample_step,
        args.relief_height_falloff,
        terrain_lines,
        args.relief_interior_max_distance,
        border_margin,
        track_z_offset,
    )
    smoothness = smoothness_report(segs, lengths, profile, get_attnum(main_track, "width", 12.0))
    relief_validation = validate_relief_ac_lines(relief_lines)
    if not relief_validation.ok:
        raise SystemExit(f"Invalid relief breaklines: {format_relief_validation_issues(relief_validation)}")
    terrain_map_path = terrain_map_output_path(args.terrain_elevation_map, output_xml)
    relief_value, terrain_map = apply_elevation_outputs(
        args,
        prolog,
        tree,
        root,
        main_track,
        segs,
        segments,
        lengths,
        total,
        profile,
        banking_profile,
        banking_sources,
        relief_path,
        relief_lines,
        output_xml,
        terrain_section,
        terrain_map_path,
        track_z_offset,
    )

    report = build_apply_elevation_report(
        args,
        track_xml,
        output_xml,
        total,
        segs,
        sources,
        alignment_reports,
        banking_sources,
        banking_alignment_reports,
        banking_profile,
        terrain_lines,
        profile,
        relief_value,
        relief_lines,
        distances,
        relief_info,
        terrain_map,
        smoothness,
    )
    write_optional_report(args.report, report)
    print_apply_elevation_summary(args, total, smoothness, banking_profile, relief_lines, relief_path, terrain_map)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
