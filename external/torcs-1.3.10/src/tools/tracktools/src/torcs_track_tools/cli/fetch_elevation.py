#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : fetch_elevation.py
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

"""Fetch DEM elevations for a track centerline and terrain relief corridors."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from torcs_track_tools.core.polyline import lonlat_from_xy, to_xy_tuples


@dataclass(frozen=True)
class SourcePoint:
    x: float
    y: float
    lat: float
    lon: float


@dataclass(frozen=True)
class StationPose:
    station: float
    x: float
    y: float
    heading: float


@dataclass(frozen=True)
class QueryPoint:
    line_index: int
    sample_index: int
    side: str
    distance: float
    station: float
    x: float
    y: float
    lat: float
    lon: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch terrain elevations for a TORCS source centerline cache")
    parser.add_argument("--polyline", required=True, help="Input cached centerline JSON with lat/lon points")
    parser.add_argument("--output", required=True, help="Output elevation terrain JSON")
    parser.add_argument(
        "--provider-url",
        default="https://api.opentopodata.org/v1/eudem25m",
        help="OpenTopoData-compatible endpoint accepting ?locations=lat,lon|lat,lon",
    )
    parser.add_argument("--sample-step", type=float, default=50.0, help="Station spacing for DEM samples in meters")
    parser.add_argument("--distances", default="25,80,160", help="Comma-separated offset distances from road edge/centerline in meters")
    parser.add_argument("--road-only", action="store_true", help="Fetch only the centerline road profile, without offset terrain corridors")
    parser.add_argument("--chunk-size", type=int, default=60, help="Locations per provider request")
    parser.add_argument("--retries", type=int, default=3, help="HTTP retry count")
    parser.add_argument("--retry-delay", type=float, default=1.5, help="Base retry delay in seconds")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output")
    return parser.parse_args()


def parse_distances(text: str) -> list[float]:
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = float(part)
        except ValueError as exc:
            raise SystemExit(f"Invalid distance: {part}") from exc
        if value > 0.0:
            out.append(value)
    out = sorted(set(out))
    if not out:
        raise SystemExit("At least one positive --distances value is required")
    return out


def load_source_points(path: pathlib.Path) -> tuple[list[SourcePoint], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_points = data.get("polyline", [])
    if len(raw_points) < 3:
        raise SystemExit(f"Polyline has too few points: {path}")
    if "lat" not in raw_points[0] or "lon" not in raw_points[0]:
        raise SystemExit("Elevation fetching currently requires a lat/lon source polyline")

    ref = raw_points[0]
    xy = to_xy_tuples(raw_points, ref)
    points = [SourcePoint(x, y, float(p["lat"]), float(p["lon"])) for p, (x, y) in zip(raw_points, xy, strict=True)]
    return points, ref


def cumulative_loop(points: list[SourcePoint]) -> tuple[list[float], float]:
    stations = [0.0]
    total = 0.0
    for i in range(1, len(points)):
        total += math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y)
        stations.append(total)
    close_len = math.hypot(points[0].x - points[-1].x, points[0].y - points[-1].y)
    if close_len > 1e-6:
        total += close_len
    return stations, total


def pose_at_station(points: list[SourcePoint], stations: list[float], total: float, station: float) -> StationPose:
    s = station % total if total > 0.0 else 0.0
    for i in range(1, len(points)):
        if s <= stations[i]:
            a = points[i - 1]
            b = points[i]
            span = stations[i] - stations[i - 1]
            t = 0.0 if span <= 1e-9 else (s - stations[i - 1]) / span
            heading = math.atan2(b.y - a.y, b.x - a.x)
            return StationPose(station, a.x + t * (b.x - a.x), a.y + t * (b.y - a.y), heading)
    a = points[-1]
    b = points[0]
    span = total - stations[-1]
    t = 0.0 if span <= 1e-9 else (s - stations[-1]) / span
    heading = math.atan2(b.y - a.y, b.x - a.x)
    return StationPose(station, a.x + t * (b.x - a.x), a.y + t * (b.y - a.y), heading)


def offset_xy(pose: StationPose, side: str, distance: float) -> tuple[float, float]:
    if side == "center":
        return pose.x, pose.y
    sign = 1.0 if side == "left" else -1.0
    nx = -math.sin(pose.heading)
    ny = math.cos(pose.heading)
    return pose.x + sign * distance * nx, pose.y + sign * distance * ny


def build_query_points(points: list[SourcePoint], ref: dict, sample_step: float, distances: list[float], road_only: bool = False) -> tuple[list[dict], float]:
    stations, total = cumulative_loop(points)
    sample_count = max(3, int(math.ceil(total / max(1.0, sample_step))))
    sample_stations = [total * i / sample_count for i in range(sample_count)] + [total]
    line_specs = [("center", 0.0)]
    if not road_only:
        line_specs += [(side, d) for side in ("left", "right") for d in distances]

    lines = []
    for line_index, (side, distance) in enumerate(line_specs):
        samples = []
        for sample_index, station in enumerate(sample_stations):
            pose = pose_at_station(points, stations, total, station)
            x, y = offset_xy(pose, side, distance)
            lat, lon = lonlat_from_xy((x, y), ref)
            samples.append(
                {
                    "line_index": line_index,
                    "sample_index": sample_index,
                    "side": side,
                    "distance_m": distance,
                    "station_m": station,
                    "x": x,
                    "y": y,
                    "lat": lat,
                    "lon": lon,
                }
            )
        lines.append({"side": side, "distance_m": distance, "samples": samples})
    return lines, total


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "TORCS-tracktools/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def provider_request_url(locations: list[dict], provider_url: str) -> str:
    loc_text = "|".join(f"{item['lat']:.7f},{item['lon']:.7f}" for item in locations)
    return f"{provider_url.rstrip('/')}?locations={urllib.parse.quote(loc_text, safe='|,')}"


def elevation_results(payload: dict, expected_count: int) -> list[dict]:
    if payload.get("status") not in (None, "OK"):
        raise RuntimeError(f"Elevation provider status: {payload.get('status')}")
    results = payload.get("results", [])
    if len(results) != expected_count:
        raise RuntimeError(f"Elevation provider returned {len(results)} results for {expected_count} locations")
    return results


def parse_elevations(results: list[dict]) -> list[float]:
    elevations = []
    for result in results:
        elevation = result.get("elevation")
        if elevation is None:
            raise RuntimeError("Elevation provider returned a null elevation")
        elevations.append(float(elevation))
    return elevations


def query_provider(locations: list[dict], provider_url: str, retries: int, retry_delay: float) -> list[float]:
    if not locations:
        return []
    url = provider_request_url(locations, provider_url)
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            payload = fetch_json(url)
            return parse_elevations(elevation_results(payload, len(locations)))
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(retry_delay * attempt)
    if last_exc is None:
        raise RuntimeError("Elevation provider retry loop completed without an exception")
    raise last_exc


def attach_elevations(lines: list[dict], args: argparse.Namespace) -> None:
    flat = [sample for line in lines for sample in line["samples"]]
    chunk_size = max(1, int(args.chunk_size))
    by_key: dict[tuple[int, int], float] = {}
    for i in range(0, len(flat), chunk_size):
        chunk = flat[i : i + chunk_size]
        elevations = query_provider(chunk, args.provider_url, args.retries, args.retry_delay)
        for sample, elevation in zip(chunk, elevations, strict=True):
            by_key[(int(sample["line_index"]), int(sample["sample_index"]))] = elevation

    for line in lines:
        for sample in line["samples"]:
            sample["elevation_m"] = by_key[(int(sample["line_index"]), int(sample["sample_index"]))]
            del sample["line_index"]
            del sample["sample_index"]


def main() -> int:
    args = parse_args()
    output = pathlib.Path(args.output)
    if output.exists() and not args.force:
        print(f"Elevation cache exists, skipping fetch: {output}")
        print("Use --force to refresh.")
        return 0
    source_path = pathlib.Path(args.polyline)
    points, ref = load_source_points(source_path)
    distances = [] if args.road_only else parse_distances(args.distances)
    lines, total = build_query_points(points, ref, args.sample_step, distances, args.road_only)
    attach_elevations(lines, args)

    center = next(line for line in lines if line["side"] == "center")
    road_start = float(center["samples"][0]["elevation_m"])
    road_samples = [
        {
            "station_m": sample["station_m"],
            "elevation_m": sample["elevation_m"],
            "weight": 1.0,
        }
        for sample in center["samples"]
    ]

    out_obj = {
        "schema": 1,
        "source": {
            "type": "dem-corridor",
            "provider_url": args.provider_url,
            "polyline": str(source_path),
            "sample_step_m": args.sample_step,
            "distances_m": distances,
            "road_only": bool(args.road_only),
        },
        "total_length_m": total,
        "normalization": {
            "road_start_elevation_m": road_start,
        },
        "road_profile": {
            "samples": road_samples,
        },
        "terrain_lines": lines,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out_obj, indent=2), encoding="utf-8")
    print(f"Wrote elevation cache: {output}")
    print(f"Track source length: {total:.2f} m")
    print(f"Samples: {sum(len(line['samples']) for line in lines)} across {len(lines)} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
