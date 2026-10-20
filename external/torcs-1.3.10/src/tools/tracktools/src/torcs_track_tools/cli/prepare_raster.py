#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : prepare_raster.py
#     created              : 23 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Inspect, mosaic, and vertically scale local raster DEM tiles."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
from typing import Any

import numpy as np

from torcs_track_tools.cli.import_elevation_raster import import_rasterio

SUPPORTED_SUFFIXES = {".tif", ".tiff", ".asc", ".grd", ".txt"}
VERTICAL_UNIT_SCALE = {
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "ft": 0.3048,
    "feet": 0.3048,
    "us-ft": 1200.0 / 3937.0,
    "survey-ft": 1200.0 / 3937.0,
    "us-survey-ft": 1200.0 / 3937.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare local raster DEM tiles for TORCS tracktools")
    parser.add_argument("--input", action="append", required=True, help="Input raster file or directory. Repeat for multiple files/directories.")
    parser.add_argument("--output", default="", help="Output GeoTIFF mosaic path. Required unless --dry-run is set.")
    parser.add_argument("--report", default="", help="Optional JSON inspection/preparation report")
    parser.add_argument("--recursive", action="store_true", help="Recurse into input directories")
    parser.add_argument("--include-no-extension", action="store_true", help="Try files without an extension, useful for some LiDAR packages")
    parser.add_argument("--vertical-unit", default="m", help="Input grid vertical unit: m, ft, or us-ft")
    parser.add_argument("--vertical-scale", type=float, default=1.0, help="Additional vertical multiplier applied after --vertical-unit")
    parser.add_argument("--vertical-offset", type=float, default=0.0, help="Vertical offset added after scaling")
    parser.add_argument("--nodata", type=float, default=math.nan, help="Override output nodata value; defaults to first source nodata or -9999")
    parser.add_argument("--dry-run", action="store_true", help="Only inspect inputs and write the report; do not write an output raster")
    return parser.parse_args()


def vertical_scale(args: argparse.Namespace) -> float:
    unit = str(args.vertical_unit).strip().lower()
    if unit not in VERTICAL_UNIT_SCALE:
        raise SystemExit(f"Unsupported --vertical-unit '{args.vertical_unit}'. Use m, ft, or us-ft.")
    return VERTICAL_UNIT_SCALE[unit] * args.vertical_scale


def is_supported_file(path: pathlib.Path, include_no_extension: bool) -> bool:
    if path.suffix.lower() in SUPPORTED_SUFFIXES:
        return True
    return include_no_extension and not path.suffix


def collect_inputs(raw_inputs: list[str], recursive: bool, include_no_extension: bool) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for raw in raw_inputs:
        path = pathlib.Path(raw)
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            out.extend(sorted(child for child in iterator if child.is_file() and is_supported_file(child, include_no_extension)))
        elif path.is_file():
            if not is_supported_file(path, include_no_extension):
                raise SystemExit(f"Unsupported raster extension: {path}")
            out.append(path)
        else:
            raise SystemExit(f"Raster input not found: {path}")
    if not out:
        raise SystemExit("No raster inputs found")
    return sorted(dict.fromkeys(out))


def dataset_report(dataset: Any, path: pathlib.Path) -> dict[str, Any]:
    band = dataset.read(1, masked=True)
    valid = band.compressed()
    res_x, res_y = dataset.res
    return {
        "path": str(path),
        "driver": dataset.driver,
        "crs": dataset.crs.to_string() if dataset.crs is not None else "",
        "width": dataset.width,
        "height": dataset.height,
        "bounds": [dataset.bounds.left, dataset.bounds.bottom, dataset.bounds.right, dataset.bounds.top],
        "resolution": [abs(res_x), abs(res_y)],
        "nodata": dataset.nodata,
        "min": float(valid.min()) if valid.size else None,
        "max": float(valid.max()) if valid.size else None,
    }


def output_nodata(datasets: list[Any], override: float) -> float:
    if math.isfinite(override):
        return override
    for dataset in datasets:
        if dataset.nodata is not None and math.isfinite(float(dataset.nodata)):
            return float(dataset.nodata)
    return -9999.0


def check_compatible(datasets: list[Any], paths: list[pathlib.Path]) -> None:
    first_crs = datasets[0].crs
    for dataset, path in zip(datasets[1:], paths[1:], strict=True):
        if dataset.crs != first_crs:
            raise SystemExit(f"Raster CRS differs from first input: {path}: {dataset.crs} vs {first_crs}")


def scaled_values(data: np.ndarray, nodata: float, scale: float, offset: float) -> np.ndarray:
    out = data.astype("float32", copy=True)
    valid = np.isfinite(out)
    if math.isfinite(nodata):
        valid &= np.abs(out - nodata) > 1e-9
    out[valid] = out[valid] * scale + offset
    return out


def prepare_raster(paths: list[pathlib.Path], output: pathlib.Path, scale: float, offset: float, nodata: float) -> dict[str, Any]:
    rasterio = import_rasterio()
    from rasterio.merge import merge  # type: ignore[import-not-found]

    datasets = [rasterio.open(path) for path in paths]
    try:
        check_compatible(datasets, paths)
        out_nodata = output_nodata(datasets, nodata)
        if len(datasets) == 1:
            first = datasets[0]
            masked = first.read(1, masked=True)
            data = masked.filled(out_nodata).astype("float32")[np.newaxis, :, :]
            transform = first.transform
        else:
            data, transform = merge(datasets, indexes=1, nodata=out_nodata, dtype="float32")
        data = scaled_values(data, out_nodata, scale, offset)
        profile = datasets[0].profile.copy()
        profile.update(driver="GTiff", width=data.shape[2], height=data.shape[1], count=1, transform=transform, dtype="float32", nodata=out_nodata)
        output.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output, "w", **profile) as dst:
            dst.write(data)
        valid = data[np.isfinite(data) & (np.abs(data - out_nodata) > 1e-9)]
        return {
            "output": str(output),
            "output_crs": datasets[0].crs.to_string() if datasets[0].crs is not None else "",
            "output_bounds": list(rasterio.transform.array_bounds(data.shape[1], data.shape[2], transform)),
            "output_nodata": out_nodata,
            "output_min": float(valid.min()) if valid.size else None,
            "output_max": float(valid.max()) if valid.size else None,
        }
    finally:
        for dataset in datasets:
            dataset.close()


def main() -> int:
    args = parse_args()
    paths = collect_inputs(args.input, args.recursive, args.include_no_extension)
    rasterio = import_rasterio()
    datasets = [rasterio.open(path) for path in paths]
    try:
        input_reports = [dataset_report(dataset, path) for dataset, path in zip(datasets, paths, strict=True)]
    finally:
        for dataset in datasets:
            dataset.close()

    scale = vertical_scale(args)
    report: dict[str, Any] = {
        "inputs": input_reports,
        "input_count": len(paths),
        "vertical_unit": args.vertical_unit,
        "vertical_scale": scale,
        "vertical_offset": args.vertical_offset,
        "dry_run": bool(args.dry_run),
    }

    if not args.dry_run:
        if not args.output:
            raise SystemExit("--output is required unless --dry-run is set")
        report.update(prepare_raster(paths, pathlib.Path(args.output), scale, args.vertical_offset, args.nodata))

    if args.report:
        report_path = pathlib.Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Raster inputs: {len(paths)}")
    print(f"Vertical transform: z_out = z_in * {scale:.12g} + {args.vertical_offset:.12g}")
    if not args.dry_run:
        print(f"Wrote raster: {args.output}")
    if args.report:
        print(f"Wrote report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
