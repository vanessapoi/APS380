#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : auto_elevation.py
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

"""Automate high-resolution DEM discovery, download, and profile import."""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from types import SimpleNamespace

from torcs_track_tools.cli import import_elevation_raster as raster_import
from torcs_track_tools.cli.render_elevation_diff_svg import find_best_fit, resample_track_loop


@dataclass(frozen=True)
class TileChoice:
    product_id: str
    product_label: str
    year: str
    resolution: str
    tile_id: str
    tile_label: str
    uri: str


@dataclass(frozen=True)
class SearchArea:
    polygon: dict
    bng_bounds: tuple[float, float, float, float]
    wgs84_bounds: tuple[float, float, float, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automatically fetch high-resolution DEM data and create a TORCS elevation profile")
    parser.add_argument("--track-xml", required=True, help="Accepted TORCS track XML")
    parser.add_argument("--polyline", required=True, help="Source centerline JSON used for spatial fitting")
    parser.add_argument("--provider", choices=("ea-lidar",), default="ea-lidar", help="DEM provider; currently England Environment Agency LiDAR")
    parser.add_argument("--output-dir", default="", help="Output directory; defaults beside --polyline")
    parser.add_argument("--landscape-margin-m", type=float, default=1000.0, help="Margin around the source bbox used for tile discovery/download")
    parser.add_argument("--subscription-key", default="dspui", help="EA/Defra public tile API subscription key")
    parser.add_argument("--tile-search-url", default="https://api.agrimetrics.co.uk/tiles/collections/survey/search", help="EA tile search endpoint")
    parser.add_argument("--product-priority", default="lidar_composite_dtm,national_lidar_programme_dtm", help="Comma-separated DTM products in preference order")
    parser.add_argument("--polyline-crs", default="", help="CRS for x/y source polylines; lat/lon sources default to EPSG:4326")
    parser.add_argument("--provider-crs", default="EPSG:27700", help="Provider/raster CRS for EA LiDAR")
    parser.add_argument("--force-download", action="store_true", help="Redownload existing tile zip files")
    parser.add_argument("--sample-step", type=float, default=5.0, help="Profile sampling interval in meters")
    parser.add_argument("--fit-samples", type=int, default=720, help="Loop samples used for spatial fitting")
    parser.add_argument("--fit-shift-step", type=int, default=3, help="Initial circular shift stride")
    parser.add_argument("--allow-scale-fit", action="store_true", help="Allow a uniform scale in the plan-view fit for georeferenced map sources")
    parser.add_argument("--resampling", choices=("bilinear", "nearest"), default="bilinear", help="Raster sampling mode")
    parser.add_argument("--zero", choices=("track-start", "minimum", "none"), default="track-start", help="Profile zeroing mode")
    parser.add_argument("--smooth-window", type=float, default=15.0, help="Smoothing window used when --apply is set")
    parser.add_argument("--smooth-step", type=float, default=2.0, help="Smoothing sample step used when --apply is set")
    parser.add_argument("--smooth-iters", type=int, default=1, help="Smoothing iterations used when --apply is set")
    parser.add_argument("--apply", action="store_true", help="Apply the imported profile to --track-xml")
    parser.add_argument("--diff", action="store_true", help="Render an elevation-difference SVG/report after import or apply")
    return parser.parse_args()


def output_dir(args: argparse.Namespace) -> pathlib.Path:
    if args.output_dir:
        return pathlib.Path(args.output_dir)
    return pathlib.Path(args.polyline).parent / "elevation-auto"


def read_polyline(path: pathlib.Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    points = data.get("polyline", []) if isinstance(data, dict) else []
    if len(points) < 3:
        raise SystemExit(f"Source polyline has too few points: {path}")
    return points


def transformer(source_crs: str, target_crs: str):  # noqa: ANN201
    transformer_obj = raster_import.transformer_for(source_crs, target_crs)
    if transformer_obj is not None:
        return transformer_obj

    class IdentityTransformer:
        def transform(self, x: float, y: float) -> tuple[float, float]:
            return x, y

    return IdentityTransformer()


def source_points_in_provider_crs(points: list[dict], provider_crs: str, polyline_crs: str) -> list[tuple[float, float]]:
    if "lat" in points[0] and "lon" in points[0]:
        tr = transformer(polyline_crs or "EPSG:4326", provider_crs)
        return [tr.transform(float(point["lon"]), float(point["lat"])) for point in points]
    if "x" in points[0] and "y" in points[0]:
        if not polyline_crs or polyline_crs.lower() == provider_crs.lower():
            return [(float(point["x"]), float(point["y"])) for point in points]
        tr = transformer(polyline_crs, provider_crs)
        return [tr.transform(float(point["x"]), float(point["y"])) for point in points]
    raise SystemExit("Source polyline points need either lat/lon or x/y fields")


def build_search_area(polyline_path: pathlib.Path, provider_crs: str, polyline_crs: str, margin_m: float) -> SearchArea:
    points = read_polyline(polyline_path)
    xy = source_points_in_provider_crs(points, provider_crs, polyline_crs)
    xs = [p[0] for p in xy]
    ys = [p[1] for p in xy]
    margin = max(0.0, margin_m)
    min_x = min(xs) - margin
    min_y = min(ys) - margin
    max_x = max(xs) + margin
    max_y = max(ys) + margin

    to_wgs84 = transformer(provider_crs, "EPSG:4326")
    corners_bng = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y), (min_x, min_y)]
    corners_lonlat = [to_wgs84.transform(x, y) for x, y in corners_bng]
    lons = [p[0] for p in corners_lonlat]
    lats = [p[1] for p in corners_lonlat]
    polygon = {"type": "Polygon", "coordinates": [[list(p) for p in corners_lonlat]]}
    return SearchArea(polygon, (min_x, min_y, max_x, max_y), (min(lons), min(lats), max(lons), max(lats)))


def search_ea_tiles(area: SearchArea, url: str, subscription_key: str) -> list[dict]:
    body = json.dumps(area.polygon).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/geo+json",
            "Ocp-Apim-Subscription-Key": subscription_key,
            "User-Agent": "TORCS-tracktools/0.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return list(payload.get("results", []))


def tile_choice_from_result(item: dict) -> TileChoice:
    return TileChoice(
        str((item.get("product") or {}).get("id", "")),
        str((item.get("product") or {}).get("label", "")),
        str((item.get("year") or {}).get("id", "")),
        str((item.get("resolution") or {}).get("id", "")),
        str((item.get("tile") or {}).get("id", "")),
        str((item.get("tile") or {}).get("label", "")),
        str(item.get("uri", "")),
    )


def numeric_text(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except ValueError:
        return default


def select_best_tiles(results: list[dict], product_priority: str) -> list[TileChoice]:
    priority = [part.strip() for part in product_priority.split(",") if part.strip()]
    priority_index = {product: i for i, product in enumerate(priority)}
    choices = [tile_choice_from_result(item) for item in results]
    choices = [c for c in choices if c.product_id in priority_index and c.tile_id and c.year and c.resolution]
    if not choices:
        raise SystemExit("No matching DTM tiles found for the requested area")

    groups: dict[tuple[str, str, str], list[TileChoice]] = {}
    for choice in choices:
        groups.setdefault((choice.product_id, choice.year, choice.resolution), []).append(choice)

    best_key = min(
        groups,
        key=lambda key: (
            priority_index.get(key[0], 999),
            -numeric_text(key[1]),
            numeric_text(key[2], 999),
        ),
    )
    return sorted(groups[best_key], key=lambda item: item.tile_id)


def tile_download_url(tile: TileChoice, subscription_key: str) -> str:
    uri = tile.uri or f"https://environment.data.gov.uk/tiles/collections/survey/{tile.product_id}/{tile.year}/{tile.resolution}/{tile.tile_id}"
    sep = "&" if "?" in uri else "?"
    return f"{uri}{sep}subscription-key={urllib.parse.quote(subscription_key)}"


def download_tile(tile: TileChoice, directory: pathlib.Path, subscription_key: str, force: bool) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{tile.product_id}-{tile.year}-{tile.resolution}m-{tile.tile_id}.zip"
    path = directory / filename
    if path.exists() and not force:
        return path
    req = urllib.request.Request(tile_download_url(tile, subscription_key), headers={"User-Agent": "TORCS-tracktools/0.1"})
    with urllib.request.urlopen(req, timeout=900) as resp, path.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    return path


def extract_tile_zip(zip_path: pathlib.Path, directory: pathlib.Path) -> list[pathlib.Path]:
    dest = directory / zip_path.stem
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        dest_root = dest.resolve()
        for member in zf.infolist():
            target = dest / member.filename
            try:
                target.resolve().relative_to(dest_root)
            except ValueError as exc:
                raise SystemExit(f"Downloaded tile has unsafe archive path: {member.filename}") from exc
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as fh:
                shutil.copyfileobj(src, fh)
    rasters = sorted([path for path in dest.rglob("*") if path.suffix.lower() in (".tif", ".tiff", ".asc", ".grd", ".txt")])
    if not rasters:
        raise SystemExit(f"Downloaded tile has no supported raster: {zip_path}")
    return rasters


def mosaic_rasters(rasters: list[pathlib.Path], output_path: pathlib.Path) -> pathlib.Path:
    if len(rasters) == 1:
        return rasters[0]
    rasterio = raster_import.import_rasterio()
    from rasterio.merge import merge  # type: ignore[import-not-found]

    datasets = [rasterio.open(path) for path in rasters]
    try:
        data, transform = merge(datasets, nodata=-9999.0, dtype="float32")
        profile = datasets[0].profile.copy()
        profile.update(width=data.shape[2], height=data.shape[1], transform=transform, dtype="float32", nodata=-9999.0)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(data)
    finally:
        for dataset in datasets:
            dataset.close()
    return output_path


def import_profile(args: argparse.Namespace, raster_path: pathlib.Path, out_dir: pathlib.Path) -> pathlib.Path:
    profile_path = out_dir / "elevation-ea-lidar-profile.json"
    report_path = out_dir / "elevation-ea-lidar-profile-report.json"
    overlay_path = out_dir / "elevation-ea-lidar-profile.svg"
    raster = raster_import.open_raster(raster_path, args.provider_crs)
    source_points = raster_import.load_source_points(pathlib.Path(args.polyline), raster.crs, args.polyline_crs)
    source_fit_samples, source_total = raster_import.source_loop_samples(source_points, args.fit_samples)
    _, _, segments, _, track_total = raster_import.load_track(pathlib.Path(args.track_xml))
    track_fit_samples = resample_track_loop(segments, track_total, args.fit_samples)
    fit = find_best_fit(track_fit_samples, source_fit_samples, source_total, args.fit_shift_step, False, args.allow_scale_fit)
    profile_points, total = raster_import.sample_profile(raster, fit, pathlib.Path(args.track_xml), args.sample_step, args.resampling)
    profile_points, zero = raster_import.zero_profile(profile_points, args.zero)

    import_args = SimpleNamespace(
        track_xml=args.track_xml,
        polyline=args.polyline,
        raster=str(raster_path),
        output=str(profile_path),
        report=str(report_path),
        overlay=str(overlay_path),
        sample_step=args.sample_step,
        resampling=args.resampling,
        profile_weight=1.0,
    )
    raster_import.write_profile(profile_path, profile_points, import_args, fit, total, zero, source_total)
    raster_import.write_report(report_path, profile_points, import_args, fit, total, zero, source_total, raster)
    raster_import.write_overlay(overlay_path, source_points, profile_points)
    return profile_path


def run_python_module(module: str, args: list[str]) -> None:
    subprocess.run([sys.executable, "-m", module, *args], check=True)


def apply_profile(args: argparse.Namespace, profile_path: pathlib.Path, out_dir: pathlib.Path) -> None:
    run_python_module(
        "torcs_track_tools.cli.apply_elevation",
        [
            "--track-xml",
            args.track_xml,
            "--profile",
            str(profile_path),
            "--smooth-window",
            str(args.smooth_window),
            "--smooth-step",
            str(args.smooth_step),
            "--smooth-iters",
            str(args.smooth_iters),
            "--report",
            str(out_dir / "elevation-report.json"),
        ],
    )


def render_diff(args: argparse.Namespace, profile_path: pathlib.Path, out_dir: pathlib.Path) -> None:
    scale_args = ["--allow-scale-fit"] if args.allow_scale_fit else []
    run_python_module(
        "torcs_track_tools.cli.render_elevation_diff_svg",
        [
            "--track-xml",
            args.track_xml,
            "--profile",
            str(profile_path),
            "--output",
            str(out_dir / "elevation-diff.svg"),
            "--report",
            str(out_dir / "elevation-diff-report.json"),
            "--sample-step",
            str(args.sample_step),
            "--color-range",
            "5",
            *scale_args,
        ],
    )


def write_auto_report(path: pathlib.Path, area: SearchArea, tiles: list[TileChoice], raster_path: pathlib.Path, profile_path: pathlib.Path, args: argparse.Namespace) -> None:
    report = {
        "provider": args.provider,
        "landscape_margin_m": args.landscape_margin_m,
        "bng_bounds": area.bng_bounds,
        "wgs84_bounds": area.wgs84_bounds,
        "selected_tiles": [tile.__dict__ for tile in tiles],
        "raster": str(raster_path),
        "profile": str(profile_path),
        "allow_scale_fit": bool(args.allow_scale_fit),
        "applied": bool(args.apply),
        "diff_rendered": bool(args.diff),
    }
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    track_xml = pathlib.Path(args.track_xml)
    polyline = pathlib.Path(args.polyline)
    if not track_xml.exists():
        raise SystemExit(f"Track XML not found: {track_xml}")
    if not polyline.exists():
        raise SystemExit(f"Source polyline not found: {polyline}")
    out_dir = output_dir(args)
    downloads_dir = out_dir / "downloads"
    extracts_dir = out_dir / "tiles"
    out_dir.mkdir(parents=True, exist_ok=True)

    area = build_search_area(polyline, args.provider_crs, args.polyline_crs, args.landscape_margin_m)
    results = search_ea_tiles(area, args.tile_search_url, args.subscription_key)
    (out_dir / "tile-search.json").write_text(json.dumps({"area": area.__dict__, "results": results}, indent=2), encoding="utf-8")
    tiles = select_best_tiles(results, args.product_priority)
    zip_paths = [download_tile(tile, downloads_dir, args.subscription_key, args.force_download) for tile in tiles]
    rasters = [raster for zip_path in zip_paths for raster in extract_tile_zip(zip_path, extracts_dir)]
    raster_path = mosaic_rasters(rasters, out_dir / "elevation-landscape.tif")
    profile_path = import_profile(args, raster_path, out_dir)
    if args.apply:
        apply_profile(args, profile_path, out_dir)
    if args.diff:
        render_diff(args, profile_path, out_dir)
    write_auto_report(out_dir / "auto-elevation-report.json", area, tiles, raster_path, profile_path, args)

    print(f"Selected {len(tiles)} tile(s): {', '.join(tile.tile_id for tile in tiles)}")
    print(f"Landscape margin: {args.landscape_margin_m:.0f} m")
    print(f"Raster: {raster_path}")
    print(f"Profile: {profile_path}")
    if args.apply:
        print(f"Applied profile to: {track_xml}")
    if args.diff:
        print(f"Diff SVG: {out_dir / 'elevation-diff.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
