#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : import_elevation_raster.py
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

"""Sample a local raster DEM into a TORCS station/elevation profile."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
from dataclasses import dataclass

import numpy as np

from torcs_track_tools.cli.render_elevation_diff_svg import (
    FitResult,
    build_mapper,
    find_best_fit,
    load_track,
    polyline_points,
    resample_track_loop,
    sample_track_plan,
    transform_xy,
)
from torcs_track_tools.core.polyline import xy_from_latlon

ASCII_GRID_HEADER_KEYS = {"ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter", "cellsize", "nodata_value"}


@dataclass(frozen=True)
class SourcePoint:
    x: float
    y: float
    station: float


@dataclass(frozen=True)
class ProfilePoint:
    station: float
    x: float
    y: float
    elevation: float
    raw_elevation: float


class RasterSampler:
    def sample(self, x: float, y: float, resampling: str) -> float | None:
        raise NotImplementedError

    @property
    def crs(self) -> str:
        return ""

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        raise NotImplementedError


class AsciiGridSampler(RasterSampler):
    def __init__(self, path: pathlib.Path, crs: str = "") -> None:
        self.path = path
        self._crs = crs
        self.header, self.data = read_ascii_grid(path)
        self.ncols = int(self.header["ncols"])
        self.nrows = int(self.header["nrows"])
        self.cellsize = float(self.header["cellsize"])
        self.nodata = self.header.get("nodata_value")
        if "xllcenter" in self.header:
            self.x0 = float(self.header["xllcenter"])
        else:
            self.x0 = float(self.header["xllcorner"]) + 0.5 * self.cellsize
        if "yllcenter" in self.header:
            self.y_top = float(self.header["yllcenter"]) + (self.nrows - 1) * self.cellsize
        else:
            self.y_top = float(self.header["yllcorner"]) + (self.nrows - 0.5) * self.cellsize

    @property
    def crs(self) -> str:
        return self._crs

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        half = 0.5 * self.cellsize
        return (
            self.x0 - half,
            self.y_top - (self.nrows - 1) * self.cellsize - half,
            self.x0 + (self.ncols - 1) * self.cellsize + half,
            self.y_top + half,
        )

    def value_at_index(self, row: int, col: int) -> float | None:
        if row < 0 or col < 0 or row >= self.nrows or col >= self.ncols:
            return None
        value = float(self.data[row, col])
        if self.nodata is not None and abs(value - float(self.nodata)) <= 1e-9:
            return None
        if not math.isfinite(value):
            return None
        return value

    def sample(self, x: float, y: float, resampling: str) -> float | None:
        colf = (x - self.x0) / self.cellsize
        rowf = (self.y_top - y) / self.cellsize
        if resampling == "nearest":
            return self.value_at_index(int(round(rowf)), int(round(colf)))
        return bilinear_sample(self.value_at_index, rowf, colf)


class GeoTiffSampler(RasterSampler):
    def __init__(self, path: pathlib.Path, crs_override: str = "") -> None:
        rasterio = import_rasterio()
        self.path = path
        self.dataset = rasterio.open(path)
        self.data = self.dataset.read(1, masked=True)
        self.transform = self.dataset.transform
        self.inv_transform = ~self.transform
        self.width = self.dataset.width
        self.height = self.dataset.height
        self.nodata = self.dataset.nodata
        self._crs = crs_override or (self.dataset.crs.to_string() if self.dataset.crs is not None else "")

    @property
    def crs(self) -> str:
        return self._crs

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        b = self.dataset.bounds
        return b.left, b.bottom, b.right, b.top

    def value_at_index(self, row: int, col: int) -> float | None:
        if row < 0 or col < 0 or row >= self.height or col >= self.width:
            return None
        value = self.data[row, col]
        if np.ma.is_masked(value):
            return None
        value = float(value)
        if self.nodata is not None and abs(value - float(self.nodata)) <= 1e-9:
            return None
        if not math.isfinite(value):
            return None
        return value

    def sample(self, x: float, y: float, resampling: str) -> float | None:
        colf, rowf = self.inv_transform * (x, y)
        colf -= 0.5
        rowf -= 0.5
        if resampling == "nearest":
            return self.value_at_index(int(round(rowf)), int(round(colf)))
        return bilinear_sample(self.value_at_index, rowf, colf)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sample a raster DEM into a TORCS station/elevation profile")
    parser.add_argument("--track-xml", required=True, help="Accepted TORCS track XML whose centerline stations should be sampled")
    parser.add_argument("--polyline", required=True, help="Source centerline JSON used to spatially fit the XML centerline to the raster")
    parser.add_argument("--raster", required=True, help="Input DEM raster, currently GeoTIFF or ESRI ASCII grid")
    parser.add_argument("--output", required=True, help="Output profile JSON consumed by torcs-apply-elevation --profile")
    parser.add_argument("--report", default="", help="Optional JSON diagnostics report")
    parser.add_argument("--overlay", default="", help="Optional SVG overlay of source centerline and fitted sample points")
    parser.add_argument("--sample-step", type=float, default=5.0, help="Output profile sampling interval in meters")
    parser.add_argument("--fit-samples", type=int, default=720, help="Loop samples used for circular plan-view fit")
    parser.add_argument("--fit-shift-step", type=int, default=3, help="Initial circular shift stride; best area is refined at stride 1")
    parser.add_argument("--allow-reverse-source", action="store_true", help="Also try the source loop in reverse during plan-view fitting")
    parser.add_argument("--allow-scale-fit", action="store_true", help="Allow a uniform scale in the plan-view fit for georeferenced map sources")
    parser.add_argument("--resampling", choices=("bilinear", "nearest"), default="bilinear", help="Raster resampling mode")
    parser.add_argument("--raster-crs", default="", help="CRS override for rasters without CRS metadata, for example EPSG:27700")
    parser.add_argument("--polyline-crs", default="", help="CRS for x/y polyline points when reprojection is needed; lat/lon defaults to EPSG:4326")
    parser.add_argument("--zero", choices=("track-start", "minimum", "none"), default="track-start", help="Elevation zeroing mode for the output profile")
    parser.add_argument("--profile-weight", type=float, default=1.0, help="Weight stored on each output sample")
    return parser.parse_args()


def import_rasterio():  # noqa: ANN201
    try:
        import rasterio  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit("GeoTIFF import requires rasterio. Install/update the tracktools environment dependencies.") from exc
    return rasterio


def ascii_grid_header_has_origin(header: dict[str, float]) -> bool:
    return bool({"xllcorner", "xllcenter"} & set(header)) and bool({"yllcorner", "yllcenter"} & set(header))


def ascii_grid_header_complete(header: dict[str, float]) -> bool:
    return {"ncols", "nrows", "cellsize"}.issubset(header) and ascii_grid_header_has_origin(header)


def read_ascii_grid_header(lines: list[str]) -> tuple[dict[str, float], int]:
    header: dict[str, float] = {}
    data_start = 0
    for idx, line in enumerate(lines):
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        key = parts[0].lower()
        if key not in ASCII_GRID_HEADER_KEYS:
            return header, idx
        header[key] = float(parts[1])
        data_start = idx + 1
        if ascii_grid_header_complete(header) and idx >= 5:
            return header, data_start
    return header, data_start


def ascii_grid_values(lines: list[str]) -> list[float]:
    values = []
    for line in lines:
        if line.strip():
            values.extend(float(part) for part in line.split())
    return values


def read_ascii_grid(path: pathlib.Path) -> tuple[dict[str, float], np.ndarray]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header, data_start = read_ascii_grid_header(lines)
    if not ascii_grid_header_complete(header):
        raise SystemExit(f"Invalid ESRI ASCII grid header: {path}")
    values = ascii_grid_values(lines[data_start:])
    ncols = int(header["ncols"])
    nrows = int(header["nrows"])
    if len(values) != ncols * nrows:
        raise SystemExit(f"ASCII grid has {len(values)} values, expected {ncols * nrows}: {path}")
    return header, np.array(values, dtype=float).reshape((nrows, ncols))


def bilinear_sample(value_at_index, rowf: float, colf: float) -> float | None:  # noqa: ANN001
    r0 = math.floor(rowf)
    c0 = math.floor(colf)
    r1 = r0 + 1
    c1 = c0 + 1
    dr = rowf - r0
    dc = colf - c0
    values = [
        (value_at_index(r0, c0), (1.0 - dr) * (1.0 - dc)),
        (value_at_index(r0, c1), (1.0 - dr) * dc),
        (value_at_index(r1, c0), dr * (1.0 - dc)),
        (value_at_index(r1, c1), dr * dc),
    ]
    numerator = 0.0
    denominator = 0.0
    for value, weight in values:
        if value is None or weight <= 0.0:
            continue
        numerator += value * weight
        denominator += weight
    if denominator <= 1e-12:
        return None
    return numerator / denominator


def open_raster(path: pathlib.Path, crs_override: str) -> RasterSampler:
    suffix = path.suffix.lower()
    if suffix in (".asc", ".grd", ".txt"):
        return AsciiGridSampler(path, crs_override)
    if suffix in (".tif", ".tiff"):
        return GeoTiffSampler(path, crs_override)
    raise SystemExit(f"Unsupported raster extension '{path.suffix}'. Use GeoTIFF or ESRI ASCII grid.")


def crs_from_user_input(crs: str):  # noqa: ANN201
    rasterio = import_rasterio()
    try:
        return rasterio.crs.CRS.from_user_input(crs)
    except Exception:
        return None


def crs_unit_to_meter(crs: str) -> float:
    parsed = crs_from_user_input(crs)
    if parsed is None or not parsed.is_projected:
        return 1.0
    try:
        return float(parsed.linear_units_factor[1])
    except Exception:
        return 1.0


def crs_is_geographic(crs: str) -> bool:
    parsed = crs_from_user_input(crs)
    return bool(parsed is not None and parsed.is_geographic)


def raster_requires_scale_fit(raster: RasterSampler) -> bool:
    if not raster.crs:
        return False
    if crs_is_geographic(raster.crs):
        return True
    return abs(crs_unit_to_meter(raster.crs) - 1.0) > 1e-6


def transformer_for(source_crs: str, target_crs: str):  # noqa: ANN201
    if not source_crs or not target_crs or source_crs.lower() == target_crs.lower():
        return None
    source = crs_from_user_input(source_crs)
    target = crs_from_user_input(target_crs)
    if source is not None and target is not None and source == target:
        return None
    import_rasterio()
    from rasterio.warp import transform as rasterio_transform  # type: ignore[import-not-found]

    class RasterioTransformer:
        def transform(self, x: float, y: float) -> tuple[float, float]:
            try:
                xs, ys = rasterio_transform(source_crs, target_crs, [x], [y])
            except Exception as exc:
                raise SystemExit(f"CRS transformation failed from {source_crs} to {target_crs}: {exc}") from exc
            return float(xs[0]), float(ys[0])

    return RasterioTransformer()


def source_xy_from_latlon_points(raw: list[dict], raster_crs: str, polyline_crs: str) -> list[tuple[float, float]]:
    source_crs = polyline_crs or "EPSG:4326"
    if not raster_crs:
        raise SystemExit("Lat/lon source polylines need a raster CRS. Use a GeoTIFF with CRS metadata or pass --raster-crs.")
    transformer = transformer_for(source_crs, raster_crs)
    out_xy = []
    for point in raw:
        lon = float(point["lon"])
        lat = float(point["lat"])
        if transformer is None:
            out_xy.append(xy_from_latlon(point, raw[0]) if source_crs.upper() == "LOCAL" else (lon, lat))
        else:
            out_xy.append(transformer.transform(lon, lat))
    return out_xy


def source_xy_from_xy_points(raw: list[dict], raster_crs: str, polyline_crs: str) -> list[tuple[float, float]]:
    transformer = transformer_for(polyline_crs, raster_crs)
    out_xy = []
    for point in raw:
        x = float(point["x"])
        y = float(point["y"])
        out_xy.append(transformer.transform(x, y) if transformer is not None else (x, y))
    return out_xy


def source_points_with_stations(out_xy: list[tuple[float, float]]) -> list[SourcePoint]:
    stations = [0.0]
    total = 0.0
    for i in range(1, len(out_xy)):
        total += math.hypot(out_xy[i][0] - out_xy[i - 1][0], out_xy[i][1] - out_xy[i - 1][1])
        stations.append(total)
    return [SourcePoint(x, y, s) for (x, y), s in zip(out_xy, stations, strict=True)]


def load_source_points(polyline_path: pathlib.Path, raster_crs: str, polyline_crs: str) -> list[SourcePoint]:
    data = json.loads(polyline_path.read_text(encoding="utf-8"))
    raw = data.get("polyline", []) if isinstance(data, dict) else []
    if len(raw) < 2:
        raise SystemExit(f"Source polyline has too few points: {polyline_path}")
    if "lat" in raw[0] and "lon" in raw[0]:
        out_xy = source_xy_from_latlon_points(raw, raster_crs, polyline_crs)
    elif "x" in raw[0] and "y" in raw[0]:
        out_xy = source_xy_from_xy_points(raw, raster_crs, polyline_crs)
    else:
        raise SystemExit("Source polyline points need either x/y or lat/lon fields")
    return source_points_with_stations(out_xy)


def clean_source_loop_points(points: list[SourcePoint]) -> list[SourcePoint]:
    clean = list(points)
    if len(clean) >= 2 and math.hypot(clean[0].x - clean[-1].x, clean[0].y - clean[-1].y) <= 1e-6:
        clean = clean[:-1]
    return clean


def source_loop_stations(clean: list[SourcePoint]) -> tuple[list[float], float]:
    stations = [0.0]
    total = 0.0
    for i in range(1, len(clean)):
        total += math.hypot(clean[i].x - clean[i - 1].x, clean[i].y - clean[i - 1].y)
        stations.append(total)
    if len(clean) > 2:
        total += math.hypot(clean[0].x - clean[-1].x, clean[0].y - clean[-1].y)
    return stations, total


def source_loop_point_at(clean: list[SourcePoint], stations: list[float], total: float, station: float) -> dict:
    s = station % total
    for i in range(1, len(clean)):
        if s <= stations[i]:
            a = clean[i - 1]
            b = clean[i]
            span = stations[i] - stations[i - 1]
            t = 0.0 if span <= 1e-9 else (s - stations[i - 1]) / span
            return {"x": a.x + t * (b.x - a.x), "y": a.y + t * (b.y - a.y), "s": s}
    a = clean[-1]
    b = clean[0]
    span = total - stations[-1]
    t = 0.0 if span <= 1e-9 else (s - stations[-1]) / span
    return {"x": a.x + t * (b.x - a.x), "y": a.y + t * (b.y - a.y), "s": s}


def source_loop_samples(points: list[SourcePoint], count: int) -> tuple[list[dict], float]:
    clean = clean_source_loop_points(points)
    stations, total = source_loop_stations(clean)
    if total <= 1e-9:
        raise SystemExit("Source polyline has zero length after CRS transform")

    count = max(8, count)
    return [source_loop_point_at(clean, stations, total, total * i / count) for i in range(count)], total


def sample_profile(
    raster: RasterSampler,
    fit: FitResult,
    track_xml: pathlib.Path,
    sample_step: float,
    resampling: str,
) -> tuple[list[ProfilePoint], float]:
    _, _, segments, _, total = load_track(track_xml)
    plan = sample_track_plan(segments, min(3.0, max(1.0, sample_step)))
    count = max(3, int(math.ceil(total / max(1.0, sample_step))))
    points = []
    missing = []
    from torcs_track_tools.cli.render_elevation_diff_svg import interpolate_track_plan  # local import keeps related math in one module

    for i in range(count):
        station = total * i / count
        sample = interpolate_track_plan(plan, station, total)
        x, y = transform_xy(sample.x, sample.y, fit)
        elevation = raster.sample(x, y, resampling)
        if elevation is None:
            missing.append({"station_m": station, "x": x, "y": y})
            continue
        points.append(ProfilePoint(station, x, y, elevation, elevation))
    if missing:
        first = missing[0]
        raise SystemExit(f"Raster has no elevation at {len(missing)} track samples; first missing at s={first['station_m']:.1f}, x={first['x']:.2f}, y={first['y']:.2f}")
    return points, total


def zero_profile(points: list[ProfilePoint], mode: str) -> tuple[list[ProfilePoint], float]:
    if not points or mode == "none":
        return list(points), 0.0
    if mode == "minimum":
        zero = min(point.raw_elevation for point in points)
    else:
        zero = points[0].raw_elevation
    return [ProfilePoint(p.station, p.x, p.y, p.raw_elevation - zero, p.raw_elevation) for p in points], zero


def write_profile(path: pathlib.Path, points: list[ProfilePoint], args: argparse.Namespace, fit: FitResult, total: float, zero: float, source_total: float) -> None:
    from torcs_track_tools.core.track_georeference import track_plan_sha256

    obj = {
        "schema": 1,
        "type": "raster-dem-profile",
        "track_xml": args.track_xml,
        "track_plan_sha256": track_plan_sha256(pathlib.Path(args.track_xml).read_text(encoding="utf-8-sig")),
        "polyline": args.polyline,
        "raster": args.raster,
        "total_length_m": total,
        "zero_elevation_m": zero,
        "sample_step_m": args.sample_step,
        "resampling": args.resampling,
        "source_fit_length_m": source_total,
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
        "samples": [
            {
                "station_m": point.station,
                "elevation_m": point.elevation,
                "weight": args.profile_weight,
                "raster_x": point.x,
                "raster_y": point.y,
                "raw_elevation_m": point.raw_elevation,
            }
            for point in points
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def write_report(path: pathlib.Path, points: list[ProfilePoint], args: argparse.Namespace, fit: FitResult, total: float, zero: float, source_total: float, raster: RasterSampler) -> None:
    elevations = [point.elevation for point in points]
    raw = [point.raw_elevation for point in points]
    report = {
        "profile": args.output,
        "sample_count": len(points),
        "track_length_m": total,
        "source_fit_length_m": source_total,
        "zero_elevation_m": zero,
        "min_elevation_m": min(elevations, default=0.0),
        "max_elevation_m": max(elevations, default=0.0),
        "min_raw_elevation_m": min(raw, default=0.0),
        "max_raw_elevation_m": max(raw, default=0.0),
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


def color_for_elevation(value: float, min_value: float, max_value: float) -> str:
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


def write_overlay(path: pathlib.Path, source_points: list[SourcePoint], profile_points: list[ProfilePoint], width: float = 1600.0, pad: float = 50.0) -> None:
    source_xy = [(p.x, p.y) for p in source_points]
    if source_xy and math.hypot(source_xy[0][0] - source_xy[-1][0], source_xy[0][1] - source_xy[-1][1]) > 1e-6:
        source_xy.append(source_xy[0])
    profile_xy = [(p.x, p.y) for p in profile_points]
    all_xy = source_xy + profile_xy
    mapper, height = build_mapper(all_xy, width, pad)
    min_z = min((p.elevation for p in profile_points), default=0.0)
    max_z = max((p.elevation for p in profile_points), default=1.0)
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.2f} {height:.2f}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#f8fafc"/>',
        '<g id="source-centerline" fill="none" stroke="#22c55e" stroke-width="4" stroke-dasharray="10 7" stroke-linecap="round" stroke-linejoin="round">',
        f'<polyline points="{polyline_points(source_xy, mapper)}"/>',
        "</g>",
        '<g id="profile-samples">',
    ]
    for point in profile_points:
        x, y = mapper(point.x, point.y)
        color = color_for_elevation(point.elevation, min_z, max_z)
        out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" fill="{color}" stroke="#020617" stroke-width="0.8"/>')
    out.extend(
        [
            "</g>",
            '<rect x="18" y="18" width="395" height="78" rx="10" fill="#020617" fill-opacity="0.86"/>',
            '<text x="36" y="48" fill="#f8fafc" font-family="Consolas, monospace" font-size="18">Raster DEM profile import</text>',
            f'<text x="36" y="74" fill="#cbd5e1" font-family="Consolas, monospace" font-size="13">profile range {min_z:.1f} m .. {max_z:.1f} m</text>',
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
    source_fit_samples, source_total = source_loop_samples(source_points, args.fit_samples)
    _, _, segments, _, track_total = load_track(track_xml)
    track_fit_samples = resample_track_loop(segments, track_total, args.fit_samples)
    fit = find_best_fit(track_fit_samples, source_fit_samples, source_total, args.fit_shift_step, args.allow_reverse_source, args.allow_scale_fit or raster_requires_scale_fit(raster))
    profile_points, total = sample_profile(raster, fit, track_xml, args.sample_step, args.resampling)
    profile_points, zero = zero_profile(profile_points, args.zero)

    output = pathlib.Path(args.output)
    write_profile(output, profile_points, args, fit, total, zero, source_total)
    if args.report:
        write_report(pathlib.Path(args.report), profile_points, args, fit, total, zero, source_total, raster)
    if args.overlay:
        write_overlay(pathlib.Path(args.overlay), source_points, profile_points)

    elevations = [p.elevation for p in profile_points]
    print(f"Wrote profile: {output}")
    if args.report:
        print(f"Wrote report: {args.report}")
    if args.overlay:
        print(f"Wrote overlay: {args.overlay}")
    print(f"Samples: {len(profile_points)} at ~{args.sample_step:.1f} m")
    print(f"Fit RMSE: {fit.rmse:.2f} m, source shift: {fit.source_shift_m:.1f} m")
    print(f"Elevation range: {min(elevations, default=0.0):.2f} m .. {max(elevations, default=0.0):.2f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
