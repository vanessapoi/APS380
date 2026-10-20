#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : render_terrain_elevation_diff_png.py
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

"""Render a whole-map terrain elevation PNG-vs-raster diagnostic.

The diagnostic compares the height that trackgen will read from
`Graphic/Terrain Generation/elevation map` against the source LiDAR/DEM raster
used to create it. White means the PNG matches the raster, red means the terrain
PNG is too high, blue means it is too low, and black means the raster has no
sample for that map pixel.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

from torcs_track_tools.cli.apply_elevation import (
    element_segments,
    terrain_generation_bounds,
    terrain_profile_data,
    transform_with_fit,
    xml_road_visual_min_elevation,
)
from torcs_track_tools.cli.import_elevation_raster import open_raster
from torcs_track_tools.core.geometry import Segment
from torcs_track_tools.core.track_xml import (
    child_section,
    get_attnum,
    get_attstr,
    parse_xml_preserve_prolog,
    segment_length,
    segment_sections,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a trackgen terrain elevation map vs source raster diff PNG")
    parser.add_argument("--track-xml", required=True, help="TORCS track XML containing Graphic/Terrain Generation/elevation map")
    parser.add_argument("--profile", required=True, help="Raster-backed profile JSON used to create the terrain elevation map")
    parser.add_argument(
        "--output", required=True, help="Output diagnostic PNG. White means match, red means terrain map too high, blue too low."
    )
    parser.add_argument("--report", default="", help="Optional JSON report path")
    parser.add_argument("--color-range", type=float, default=10.0, help="Absolute difference in meters that reaches full red/blue")
    parser.add_argument("--resampling", choices=("bilinear", "nearest"), default="bilinear", help="Raster resampling mode")
    return parser.parse_args()


def resolve_track_relative(path_value: str, track_xml: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(path_value)
    if path.is_absolute():
        return path
    return track_xml.parent / path


def load_track(track_xml: pathlib.Path) -> tuple[ET.Element, ET.Element, list[ET.Element], list[Segment], list[float], float]:
    _, tree = parse_xml_preserve_prolog(track_xml)
    root = tree.getroot()
    graphic = child_section(root, "Graphic")
    terrain = child_section(graphic, "Terrain Generation")
    if terrain is None:
        raise SystemExit("Track XML has no Graphic/Terrain Generation section")
    main_track, segs = segment_sections(root)
    segments = element_segments(segs, get_attnum(main_track, "profil steps length", 6.0))
    lengths = [segment_length(seg) for seg in segs]
    total = sum(lengths)
    if total <= 0.0:
        raise SystemExit("Track XML has zero length")
    return main_track, terrain, segs, segments, lengths, total


def terrain_bounds(
    main_track: ET.Element, terrain: ET.Element, segs: list[ET.Element], segments: list[Segment], lengths: list[float]
) -> tuple[float, float, float, float]:
    return terrain_generation_bounds(main_track, terrain, segs, segments, lengths)


def terrain_map_elevations(image_path: pathlib.Path, min_altitude: float, max_altitude: float) -> np.ndarray:
    with Image.open(image_path) as image:
        gray = np.asarray(image.convert("L"), dtype=float)
    # Emulate GfImgReadPng row storage exactly: trackgen memory row 0 is the file
    # bottom row, and trackgen maps that memory row to the terrain ymin edge.
    trackgen_gray = np.flipud(gray)
    return min_altitude + trackgen_gray * (max_altitude - min_altitude) / 255.0


def colors_for_diff(diff: np.ndarray, color_range: float) -> np.ndarray:
    colors = np.full((*diff.shape, 3), 255.0, dtype=float)
    color_range = max(1e-9, color_range)
    blue = np.array((37.0, 99.0, 235.0), dtype=float)
    red = np.array((220.0, 38.0, 38.0), dtype=float)
    white = np.array((255.0, 255.0, 255.0), dtype=float)
    low = diff < 0.0
    high = diff > 0.0
    low_t = np.clip(-diff / color_range, 0.0, 1.0)
    high_t = np.clip(diff / color_range, 0.0, 1.0)
    for idx in range(3):
        colors[:, :, idx] = np.where(low, white[idx] + (blue[idx] - white[idx]) * low_t, colors[:, :, idx])
        colors[:, :, idx] = np.where(high, white[idx] + (red[idx] - white[idx]) * high_t, colors[:, :, idx])
    return np.rint(colors).clip(0, 255).astype(np.uint8)


def sample_source_grid(
    width: int,
    height: int,
    bounds: tuple[float, float, float, float],
    fit: dict[str, float],
    raster,  # noqa: ANN001
    zero_elevation: float,
    track_z_offset: float,
    resampling: str,
) -> tuple[np.ndarray, int]:
    """Sample the source raster at each terrain-map pixel in TORCS coordinates."""
    min_x, min_y, max_x, max_y = bounds
    x_span = max_x - min_x
    y_span = max_y - min_y
    source = np.empty((height, width), dtype=float)
    missing = 0
    for row in range(height):
        y = min_y + y_span * row / max(1, height - 1)
        for col in range(width):
            x = min_x + x_span * col / max(1, width - 1)
            raster_x, raster_y = transform_with_fit(x, y, fit)
            elevation = raster.sample(raster_x, raster_y, resampling)
            if elevation is None:
                source[row, col] = np.nan
                missing += 1
            else:
                source[row, col] = elevation - zero_elevation + track_z_offset
    return source, missing


def report_summary(
    output: pathlib.Path,
    image_path: pathlib.Path,
    profile_path: pathlib.Path,
    raster_path: pathlib.Path,
    bounds: tuple[float, float, float, float],
    map_elevation: np.ndarray,
    source_elevation: np.ndarray,
    diff: np.ndarray,
    missing: int,
    track_z_offset: float,
) -> dict:
    valid = diff[np.isfinite(diff)]
    valid_map = map_elevation[np.isfinite(map_elevation)]
    valid_source = source_elevation[np.isfinite(source_elevation)]
    max_high = float(np.max(valid)) if valid.size else 0.0
    max_low = float(np.min(valid)) if valid.size else 0.0
    max_abs = float(np.max(np.abs(valid))) if valid.size else 0.0
    mean = float(np.mean(valid)) if valid.size else 0.0
    rmse = float(math.sqrt(np.mean(valid * valid))) if valid.size else 0.0
    mean_abs = float(np.mean(np.abs(valid))) if valid.size else 0.0
    return {
        "output_png": str(output),
        "terrain_elevation_map": str(image_path),
        "source_profile": str(profile_path),
        "raster": str(raster_path),
        "difference_definition": "trackgen_terrain_z_m - normalized_source_raster_z_m; white means match, red too high, blue too low, black missing source raster",
        "width": int(diff.shape[1]),
        "height": int(diff.shape[0]),
        "bounds": bounds,
        "missing_source_samples": missing,
        "track_z_offset_m": track_z_offset,
        "terrain_min_m": float(np.min(valid_map)) if valid_map.size else 0.0,
        "terrain_max_m": float(np.max(valid_map)) if valid_map.size else 0.0,
        "source_min_m": float(np.min(valid_source)) if valid_source.size else 0.0,
        "source_max_m": float(np.max(valid_source)) if valid_source.size else 0.0,
        "mean_difference_m": mean,
        "rmse_difference_m": rmse,
        "mean_abs_difference_m": mean_abs,
        "max_too_high_m": max_high,
        "max_too_low_m": max_low,
        "max_abs_difference_m": max_abs,
    }


def main() -> int:
    args = parse_args()
    track_xml = pathlib.Path(args.track_xml)
    profile_path = pathlib.Path(args.profile)
    output = pathlib.Path(args.output)
    if not track_xml.exists():
        raise SystemExit(f"Track XML not found: {track_xml}")
    if not profile_path.exists():
        raise SystemExit(f"Profile not found: {profile_path}")

    main_track, terrain, segs, segments, lengths, total = load_track(track_xml)
    image_value = get_attstr(terrain, "elevation map", "")
    if not image_value:
        raise SystemExit("Track XML has no terrain elevation map")
    image_path = resolve_track_relative(image_value, track_xml)
    if not image_path.exists():
        raise SystemExit(f"Terrain elevation map not found: {image_path}")
    min_altitude = get_attnum(terrain, "minimum altitude", 0.0)
    max_altitude = get_attnum(terrain, "maximum altitude", 0.0)
    if max_altitude <= min_altitude:
        raise SystemExit("Terrain elevation map needs maximum altitude > minimum altitude")

    profile_path, _data, fit, zero_elevation, raster_path = terrain_profile_data([str(profile_path)], segments, total)
    raster = open_raster(raster_path, "")
    map_elevation = terrain_map_elevations(image_path, min_altitude, max_altitude)
    bounds = terrain_bounds(main_track, terrain, segs, segments, lengths)
    track_z_offset = -xml_road_visual_min_elevation(main_track, segs, lengths)
    source_elevation, missing = sample_source_grid(
        map_elevation.shape[1],
        map_elevation.shape[0],
        bounds,
        fit,
        raster,
        zero_elevation,
        track_z_offset,
        args.resampling,
    )
    diff = map_elevation - source_elevation
    valid = np.isfinite(diff)
    colors = colors_for_diff(np.nan_to_num(diff, nan=0.0), max(1.0, args.color_range))
    colors[~valid] = (0, 0, 0)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Write visually in conventional image order (top row is ymax), while all
    # comparisons above stay in trackgen memory order (row 0 is ymin).
    Image.fromarray(np.flipud(colors)).save(output)

    report = report_summary(
        output, image_path, profile_path, raster_path, bounds, map_elevation, source_elevation, diff, missing, track_z_offset
    )
    if args.report:
        report_path = pathlib.Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Wrote PNG: {output}")
    if args.report:
        print(f"Wrote report: {args.report}")
    print(f"Difference range: {report['max_too_low_m']:+.2f} m .. {report['max_too_high_m']:+.2f} m")
    print(f"RMSE: {report['rmse_difference_m']:.2f} m, mean abs: {report['mean_abs_difference_m']:.2f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
