# /***************************************************************************
#
#     file                 : georeference_centerline.py
#     created              : 14 Aug 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Georeference a local centerline against a geographic reference."""

from __future__ import annotations

import argparse
import html
import json
import math
import pathlib
from dataclasses import dataclass

from torcs_track_tools.cli.import_elevation_raster import crs_from_user_input, crs_unit_to_meter, transformer_for
from torcs_track_tools.cli.render_elevation_diff_svg import find_best_fit
from torcs_track_tools.core.georeference import (
    Point,
    SimilarityTransform,
    closed_length,
    control_distribution,
    convex_hull,
    fit_similarity,
    project_to_closed_loop,
    resample_closed,
    residuals,
    signed_area,
    transform_point,
)

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_POINTS = 1_000_000
MAX_CONTROLS = 32
MAX_CONTROL_SEGMENT_CHECKS = 10_000_000


@dataclass(frozen=True)
class AlignmentContext:
    reference_path: pathlib.Path | None
    reference_data: dict
    control_data: dict
    controls: list[dict]
    reference_metric: list[Point]
    control_reference_metric: list[Point]
    reference_crs: str
    control_reference_crs: str
    fit_crs: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Georeference a local x/y centerline using a geographic reference or control points")
    parser.add_argument("--input", required=True, help="Local x/y centerline JSON")
    parser.add_argument("--reference", default="", help="Optional geographic reference centerline JSON")
    parser.add_argument("--control-points", default="", help="Control-point JSON; enables landmark mode")
    parser.add_argument("--reference-crs", default="", help="CRS for reference x/y coordinates")
    parser.add_argument("--fit-crs", default="", help="Metric fitting CRS; defaults to UTM from reference centroid")
    parser.add_argument("--output-crs", default="EPSG:4326", help="Output CRS; EPSG:4326 writes lat/lon")
    parser.add_argument("--transform", choices=("rigid", "similarity"), default="rigid", help="Spatial transform model")
    parser.add_argument("--allow-reference-reverse", action="store_true", help="Allow reversed point correspondence in automatic mode")
    parser.add_argument("--allow-weak-control-set", action="store_true", help="Allow two or poorly distributed control points")
    parser.add_argument("--samples", type=int, default=800, help="Automatic loop-fit sample count")
    parser.add_argument("--max-rmse-m", type=float, default=10.0, help="Maximum accepted fit RMSE")
    parser.add_argument("--max-error-m", type=float, default=25.0, help="Maximum accepted control residual")
    parser.add_argument("--max-source-snap", type=float, default=25.0, help="Maximum control snap distance in local source units")
    parser.add_argument("--max-reference-snap-m", type=float, default=25.0, help="Maximum control snap distance on the reference loop")
    parser.add_argument("--output", required=True, help="Georeferenced centerline JSON")
    parser.add_argument("--report", required=True, help="Alignment report JSON")
    parser.add_argument("--overlay", required=True, help="Review overlay SVG")
    return parser.parse_args()


def read_json(path: pathlib.Path) -> dict:
    try:
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise SystemExit(f"Input exceeds the {MAX_INPUT_BYTES // (1024 * 1024)} MiB authoring limit: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"Could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return data


def write_json(path: pathlib.Path, data: dict) -> None:
    try:
        encoded = json.dumps(data, indent=2, allow_nan=False)
    except ValueError as exc:
        raise SystemExit(f"Could not serialize finite JSON output for {path}: {exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def raw_polyline(data: dict, label: str) -> list[dict]:
    points = data.get("polyline", [])
    if not isinstance(points, list) or len(points) < 3:
        raise SystemExit(f"{label} needs at least three polyline points")
    if len(points) > MAX_POINTS:
        raise SystemExit(f"{label} exceeds the {MAX_POINTS}-point limit")
    if not all(isinstance(point, dict) for point in points):
        raise SystemExit(f"{label} polyline points must be objects")
    return points


def local_points(raw: list[dict]) -> list[Point]:
    if not all("x" in point and "y" in point for point in raw):
        raise SystemExit("Input centerline must use local x/y coordinates")
    try:
        points = [(float(point["x"]), float(point["y"])) for point in raw]
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"Input centerline contains an invalid coordinate: {exc}") from exc
    if not all(math.isfinite(value) for point in points for value in point):
        raise SystemExit("Input centerline contains non-finite coordinates")
    if len(points) > 3 and math.dist(points[0], points[-1]) <= 1e-9:
        points = points[:-1]
    validate_loop(points, "Input centerline")
    return points


def validate_loop(points: list[Point], label: str) -> None:
    length = closed_length(points)
    if len(points) < 3 or len(set(points)) < 3 or length <= 1e-9:
        raise SystemExit(f"{label} must be a nonzero closed loop with at least three distinct points")
    hull = convex_hull(points)
    if len(hull) < 3 or abs(signed_area(hull)) <= max(1e-6, length * length * 1e-12):
        raise SystemExit(f"{label} must have non-collinear two-dimensional geometry")


def inferred_reference_crs(raw: list[dict], requested: str, data: dict) -> str:
    if requested:
        return requested
    georeferencing = data.get("georeferencing", {})
    source = data.get("source", {})
    candidate = georeferencing.get("output_crs", source.get("crs", data.get("crs", ""))) if isinstance(georeferencing, dict) else ""
    if candidate:
        return str(candidate)
    if "lat" in raw[0] and "lon" in raw[0]:
        return "EPSG:4326"
    raise SystemExit("Reference x/y coordinates require --reference-crs or CRS metadata")


def coordinate_pairs(raw: list[dict]) -> tuple[list[Point], str]:
    try:
        if all("lat" in point and "lon" in point for point in raw):
            points = [(float(point["lon"]), float(point["lat"])) for point in raw]
            kind = "geographic"
        elif all("x" in point and "y" in point for point in raw):
            points = [(float(point["x"]), float(point["y"])) for point in raw]
            kind = "projected"
        else:
            raise SystemExit("Reference points need consistent lat/lon or x/y coordinates")
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"Reference contains an invalid coordinate: {exc}") from exc
    if not all(math.isfinite(value) for point in points for value in point):
        raise SystemExit("Reference contains non-finite coordinates")
    return points, kind


def transformed_points(points: list[Point], source_crs: str, target_crs: str) -> list[Point]:
    transformer = transformer_for(source_crs, target_crs)
    transformed = [transformer.transform(*point) if transformer is not None else point for point in points]
    if not all(math.isfinite(value) for point in transformed for value in point):
        raise SystemExit(f"CRS transformation from {source_crs} to {target_crs} produced non-finite coordinates")
    return transformed


def auto_utm_crs(reference_points: list[Point], reference_crs: str) -> str:
    lonlat = transformed_points(reference_points, reference_crs, "EPSG:4326")
    lon = sum(point[0] for point in lonlat) / len(lonlat)
    lat = sum(point[1] for point in lonlat) / len(lonlat)
    if not (-80.0 <= lat <= 84.0):
        raise SystemExit("Automatic UTM selection supports latitudes from 80S to 84N; pass --fit-crs")
    zone = max(1, min(60, int(math.floor((lon + 180.0) / 6.0)) + 1))
    return f"EPSG:{32600 + zone if lat >= 0.0 else 32700 + zone}"


def validate_crs(crs: str, label: str) -> None:
    parsed = crs_from_user_input(crs)
    if parsed is None:
        raise SystemExit(f"Invalid {label}: {crs}")
    if label == "fit CRS" and not parsed.is_projected:
        raise SystemExit("Fit CRS must be projected")
    if label == "fit CRS" and abs(crs_unit_to_meter(crs) - 1.0) > 1e-6:
        raise SystemExit("Fit CRS must use meter units")
    if label == "output CRS" and not (parsed.is_geographic or parsed.is_projected):
        raise SystemExit("Output CRS must be geographic or projected")


def validate_coordinate_kind(kind: str, crs: str, label: str) -> None:
    parsed = crs_from_user_input(crs)
    if parsed is None:
        raise SystemExit(f"Invalid {label} CRS: {crs}")
    if kind == "geographic" and not parsed.is_geographic:
        raise SystemExit(f"{label} uses lat/lon fields but CRS {crs} is not geographic")
    if kind == "projected" and not parsed.is_projected:
        raise SystemExit(f"{label} uses x/y fields but CRS {crs} is not projected")


def validate_args(args: argparse.Namespace) -> None:
    if not args.reference and not args.control_points:
        raise SystemExit("Pass --reference for automatic mode or --control-points for landmark mode")
    if not math.isfinite(args.max_rmse_m) or args.max_rmse_m <= 0.0:
        raise SystemExit("--max-rmse-m must be positive")
    if not math.isfinite(args.max_error_m) or args.max_error_m <= 0.0:
        raise SystemExit("--max-error-m must be positive")
    if not math.isfinite(args.max_source_snap) or args.max_source_snap <= 0.0:
        raise SystemExit("--max-source-snap must be positive")
    if not math.isfinite(args.max_reference_snap_m) or args.max_reference_snap_m <= 0.0:
        raise SystemExit("--max-reference-snap-m must be positive")


def validate_paths(args: argparse.Namespace) -> None:
    paths = {
        "input": args.input,
        "reference": args.reference,
        "control points": args.control_points,
        "output": args.output,
        "report": args.report,
        "overlay": args.overlay,
    }
    resolved: dict[str, pathlib.Path] = {}
    for name, value in paths.items():
        if value:
            resolved[name] = pathlib.Path(value).resolve(strict=False)
    names = list(resolved)
    for index, name in enumerate(names):
        for other in names[index + 1 :]:
            same_file = resolved[name] == resolved[other]
            if not same_file and resolved[name].exists() and resolved[other].exists():
                same_file = resolved[name].samefile(resolved[other])
            if same_file:
                raise SystemExit(f"{name} and {other} paths must be distinct: {resolved[name]}")


def control_reference_points(control_data: dict) -> tuple[list[dict], list[Point], str, str]:
    controls = control_data.get("control_points", [])
    if not isinstance(controls, list) or len(controls) < 2:
        raise SystemExit("Control-point JSON needs at least two control_points")
    if len(controls) > MAX_CONTROLS:
        raise SystemExit(f"Control-point JSON exceeds the {MAX_CONTROLS}-control limit")
    reference_crs = str(control_data.get("reference_crs", "EPSG:4326"))
    reference_points: list[Point] = []
    reference_kind = ""
    for index, control in enumerate(controls):
        if not isinstance(control, dict):
            raise SystemExit(f"Control {index} must be an object")
        reference = control.get("reference", {})
        if not isinstance(reference, dict):
            raise SystemExit(f"Control {index} reference must be an object")
        try:
            pairs, kind = coordinate_pairs([reference])
        except SystemExit as exc:
            raise SystemExit(f"Control {index} has an invalid reference coordinate: {exc}") from exc
        if reference_kind and kind != reference_kind:
            raise SystemExit("Control reference coordinates must consistently use lat/lon or x/y fields")
        reference_kind = kind
        reference_points.append(pairs[0])
    return controls, reference_points, reference_crs, reference_kind


def alignment_context(args: argparse.Namespace) -> AlignmentContext:  # noqa: CCR001 - source and CRS normalization
    reference_path = pathlib.Path(args.reference) if args.reference else None
    reference_data = read_json(reference_path) if reference_path else {}
    reference_raw = raw_polyline(reference_data, "Reference centerline") if reference_path else []
    if args.control_points:
        control_data = read_json(pathlib.Path(args.control_points))
        controls, control_reference, control_reference_crs, control_reference_kind = control_reference_points(control_data)
    else:
        control_data = {}
        controls, control_reference, control_reference_crs, control_reference_kind = [], [], "", ""
    if args.reference_crs and control_reference and not reference_raw:
        control_reference_crs = args.reference_crs
    reference_pairs, reference_kind = coordinate_pairs(reference_raw) if reference_raw else ([], "")
    reference_crs = inferred_reference_crs(reference_raw, args.reference_crs, reference_data) if reference_raw else (args.reference_crs or control_reference_crs)
    validate_crs(reference_crs, "reference CRS")
    if reference_kind:
        validate_coordinate_kind(reference_kind, reference_crs, "Reference centerline")
    if control_reference_crs and control_reference_crs != reference_crs:
        validate_crs(control_reference_crs, "control reference CRS")
    if control_reference_kind:
        validate_coordinate_kind(control_reference_kind, control_reference_crs, "Control reference")
    fit_seed = reference_pairs or control_reference
    fit_crs = args.fit_crs or auto_utm_crs(fit_seed, reference_crs)
    validate_crs(fit_crs, "fit CRS")
    validate_crs(args.output_crs, "output CRS")
    reference_metric = transformed_points(reference_pairs, reference_crs, fit_crs) if reference_pairs else []
    if reference_metric:
        validate_loop(reference_metric, "Reference centerline")
    control_reference_metric = transformed_points(control_reference, control_reference_crs, fit_crs) if control_reference else []
    return AlignmentContext(
        reference_path,
        reference_data,
        control_data,
        controls,
        reference_metric,
        control_reference_metric,
        reference_crs,
        control_reference_crs,
        fit_crs,
    )


def automatic_fit(source: list[Point], reference: list[Point], args: argparse.Namespace) -> tuple[SimilarityTransform, dict]:
    if args.samples < 16 or args.samples > 10000:
        raise SystemExit("--samples must be between 16 and 10000")
    try:
        source_samples = resample_closed(source, args.samples)
        reference_samples = resample_closed(reference, args.samples)
    except ValueError as exc:
        raise SystemExit(f"Could not prepare automatic loop alignment: {exc}") from exc
    source_dicts = [{"x": point[0], "y": point[1]} for point in source_samples]
    reference_dicts = [{"x": point[0], "y": point[1]} for point in reference_samples]
    try:
        fit = find_best_fit(
            source_dicts,
            reference_dicts,
            closed_length(reference_samples),
            max(1, args.samples // 100),
            args.allow_reference_reverse,
            args.transform == "similarity",
        )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"Could not fit automatic loop alignment: {exc}") from exc
    transformed = SimilarityTransform(fit.theta, fit.scale, fit.ox, fit.oy)
    return transformed, {
        "reference_shift_m": fit.source_shift_m,
        "reference_reversed": fit.source_reversed,
        "paired_rmse_m": fit.rmse,
        "sample_count": args.samples,
    }


def control_fit(  # noqa: CCR001 - validates and records each control-point correspondence
    source: list[Point],
    reference_loop: list[Point],
    controls: list[dict],
    control_reference_metric: list[Point],
    args: argparse.Namespace,
) -> tuple[SimilarityTransform, list[dict], dict]:
    if len(controls) < 3 and not args.allow_weak_control_set:
        raise SystemExit("At least three controls are required; use --allow-weak-control-set to override")
    if len(controls) * (len(source) + len(reference_loop)) > MAX_CONTROL_SEGMENT_CHECKS:
        raise SystemExit("Control snapping exceeds the control/centerline work limit")
    source_controls: list[Point] = []
    target_controls: list[Point] = []
    details: list[dict] = []
    for index, (control, reference_point) in enumerate(zip(controls, control_reference_metric, strict=True)):
        source_value = control.get("source", {})
        if not isinstance(source_value, dict):
            raise SystemExit(f"Control {index} source must be an object")
        if "x" not in source_value or "y" not in source_value:
            raise SystemExit(f"Control {index} source needs x/y")
        try:
            source_requested = float(source_value["x"]), float(source_value["y"])
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Control {index} source has an invalid coordinate: {exc}") from exc
        if not all(math.isfinite(value) for value in source_requested):
            raise SystemExit(f"Control {index} source contains non-finite coordinates")
        source_projected, source_snap, source_segment, source_amount = project_to_closed_loop(source_requested, source)
        if reference_loop:
            target_projected, target_snap, target_segment, target_amount = project_to_closed_loop(reference_point, reference_loop)
        else:
            target_projected, target_snap, target_segment, target_amount = reference_point, 0.0, -1, 0.0
        source_controls.append(source_projected)
        target_controls.append(target_projected)
        details.append(
            {
                "index": index,
                "name": str(control.get("name", f"control-{index + 1}")),
                "source_requested": {"x": source_requested[0], "y": source_requested[1]},
                "source_snapped": {"x": source_projected[0], "y": source_projected[1]},
                "source_snap_distance_units": source_snap,
                "source_segment_index": source_segment,
                "source_segment_fraction": source_amount,
                "reference_requested": control.get("reference", {}),
                "reference_requested_fit_crs": {"x": reference_point[0], "y": reference_point[1]},
                "reference_snapped_fit_crs": {"x": target_projected[0], "y": target_projected[1]},
                "reference_snap_distance_m": target_snap,
                "reference_segment_index": target_segment,
                "reference_segment_fraction": target_amount,
            }
        )
    distribution = control_distribution(source_controls, source)
    weak = distribution["span_ratio"] < 0.25 or distribution["hull_area_ratio"] < 0.01
    if weak and not args.allow_weak_control_set:
        raise SystemExit("Control points are too clustered or collinear; distribute them around the circuit or use --allow-weak-control-set")
    try:
        fit = fit_similarity(source_controls, target_controls, args.transform == "similarity")
    except ValueError as exc:
        raise SystemExit(f"Could not fit control-point alignment: {exc}") from exc
    errors = residuals(source_controls, target_controls, fit)
    for detail, target, error in zip(details, target_controls, errors, strict=True):
        detail["reference_fit"] = {"x": target[0], "y": target[1]}
        detail["residual_m"] = error
    metrics = {
        "control_count": len(controls),
        "rmse_m": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "mean_error_m": sum(errors) / len(errors),
        "max_error_m": max(errors),
        "max_source_snap_units": max(detail["source_snap_distance_units"] for detail in details),
        "max_reference_snap_m": max(detail["reference_snap_distance_m"] for detail in details),
        "distribution": distribution,
        "weak_distribution": weak,
    }
    return fit, details, metrics


def fit_dict(fit: SimilarityTransform) -> dict:
    return {
        "rotation_deg": math.degrees(fit.rotation_rad),
        "scale": fit.scale,
        "cos": fit.cosine,
        "sin": fit.sine,
        "offset_x": fit.offset_x,
        "offset_y": fit.offset_y,
    }


def alignment_status(metrics: dict, args: argparse.Namespace) -> tuple[str, list[str]]:
    rmse = float(metrics.get("rmse_m", metrics.get("paired_rmse_m", 0.0)))
    max_error = float(metrics.get("max_error_m", rmse))
    warnings = []
    status = "ok"
    if metrics.get("weak_distribution", False):
        status = "review"
        warnings.append("Control points have weak spatial distribution")
    if rmse > args.max_rmse_m or max_error > args.max_error_m:
        status = "rejected"
        warnings.append("Residual thresholds exceeded")
    if metrics.get("max_source_snap_units", 0.0) > args.max_source_snap:
        status = "rejected"
        warnings.append("Source control snap-distance threshold exceeded")
    if metrics.get("max_reference_snap_m", 0.0) > args.max_reference_snap_m:
        status = "rejected"
        warnings.append("Reference control snap-distance threshold exceeded")
    return status, warnings


def write_overlay(
    path: pathlib.Path,
    source: list[Point],
    reference: list[Point],
    controls: list[dict],
    fit: SimilarityTransform,
    metrics: dict,
    status: str,
    warnings: list[str],
) -> None:
    transformed_source = [transform_point(point, fit) for point in source]
    control_targets = [(control["reference_fit"]["x"], control["reference_fit"]["y"]) for control in controls]
    all_points = transformed_source + reference + control_targets
    if not all_points:
        raise SystemExit("No geometry available for georeference overlay")
    min_x = min(point[0] for point in all_points)
    max_x = max(point[0] for point in all_points)
    min_y = min(point[1] for point in all_points)
    max_y = max(point[1] for point in all_points)
    span = max(max_x - min_x, max_y - min_y, 1.0)
    pad = span * 0.08
    width = max_x - min_x + 2.0 * pad
    height = max_y - min_y + 2.0 * pad

    def mapped(point: Point) -> str:
        return f"{point[0] - min_x + pad:.2f},{max_y - point[1] + pad:.2f}"

    source_line = " ".join(mapped(point) for point in transformed_source + transformed_source[:1])
    reference_line = " ".join(mapped(point) for point in reference + reference[:1]) if reference else ""
    control_svg = []
    for control in controls:
        snapped = control["source_snapped"]
        fitted_source = transform_point((snapped["x"], snapped["y"]), fit)
        target = control["reference_fit"]
        source_xy = mapped(fitted_source)
        target_xy = mapped((target["x"], target["y"]))
        label = html.escape(control["name"])
        control_svg.append(f'<line x1="{source_xy.split(",")[0]}" y1="{source_xy.split(",")[1]}" x2="{target_xy.split(",")[0]}" y2="{target_xy.split(",")[1]}" stroke="#f59e0b" stroke-width="1.5"/>')
        control_svg.append(f'<circle cx="{target_xy.split(",")[0]}" cy="{target_xy.split(",")[1]}" r="4" fill="#f59e0b"><title>{label}: {control["residual_m"]:.2f} m</title></circle>')
    rmse = metrics.get("rmse_m", metrics.get("paired_rmse_m", 0.0))
    warning_text = html.escape("; ".join(warnings) if warnings else "none")
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 {width:.2f} {height:.2f}">
  <rect width="100%" height="100%" fill="#0f172a"/>
  <g id="reference-centerline"><polyline points="{reference_line}" fill="none" stroke="#38bdf8" stroke-width="{span * 0.003:.2f}"/></g>
  <g id="georeferenced-centerline"><polyline points="{source_line}" fill="none" stroke="#ef4444" stroke-width="{span * 0.003:.2f}"/></g>
  <g id="control-residuals">{''.join(control_svg)}</g>
  <text id="alignment-status" x="{pad:.2f}" y="{pad:.2f}" fill="#e2e8f0" font-family="monospace" font-size="{span * 0.018:.2f}">status={status}, RMSE={rmse:.2f} m; red=source, blue=reference</text>
  <text x="{pad:.2f}" y="{pad + span * 0.025:.2f}" fill="#fbbf24" font-family="monospace" font-size="{span * 0.014:.2f}">warnings={warning_text}</text>
</svg>
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def output_polyline(raw: list[dict], local: list[Point], fit: SimilarityTransform, fit_crs: str, output_crs: str) -> list[dict]:
    transformed = [transform_point(point, fit) for point in local]
    output_points = transformed_points(transformed, fit_crs, output_crs)
    parsed_output_crs = crs_from_user_input(output_crs)
    if parsed_output_crs is None:
        raise SystemExit(f"Invalid output CRS: {output_crs}")
    geographic = bool(parsed_output_crs.is_geographic)
    result = []
    for original, source_point, output_point in zip(raw[: len(local)], local, output_points, strict=True):
        item = {key: value for key, value in original.items() if key not in ("x", "y", "lat", "lon", "source_x", "source_y")}
        item["source_x"] = source_point[0]
        item["source_y"] = source_point[1]
        if geographic:
            item["lon"] = output_point[0]
            item["lat"] = output_point[1]
        else:
            item["x"] = output_point[0]
            item["y"] = output_point[1]
        result.append(item)
    return result


def main() -> int:  # noqa: CCR001 - command validation and artifact assembly belong together
    args = parse_args()
    validate_args(args)
    validate_paths(args)
    input_path = pathlib.Path(args.input)
    input_data = read_json(input_path)
    input_raw = raw_polyline(input_data, "Input centerline")
    source = local_points(input_raw)
    context = alignment_context(args)
    if context.controls:
        fit, control_details, metrics = control_fit(
            source,
            context.reference_metric,
            context.controls,
            context.control_reference_metric,
            args,
        )
        mode = "control-points"
    else:
        fit, metrics = automatic_fit(source, context.reference_metric, args)
        control_details = []
        mode = "automatic-loop"

    rmse = float(metrics.get("rmse_m", metrics.get("paired_rmse_m", 0.0)))
    status, warnings = alignment_status(metrics, args)
    output_path = pathlib.Path(args.output)
    report_path = pathlib.Path(args.report)
    overlay_path = pathlib.Path(args.overlay)
    if status == "rejected":
        output_path.unlink(missing_ok=True)
    transformed_source = [transform_point(point, fit) for point in source]
    result_points = output_polyline(input_raw, source, fit, context.fit_crs, args.output_crs) if status != "rejected" else []
    georeferencing = {
        "mode": mode,
        "status": status,
        "fit_crs": context.fit_crs,
        "reference_crs": context.reference_crs,
        "control_reference_crs": context.control_reference_crs,
        "output_crs": args.output_crs,
        "transform": args.transform,
        "fit": fit_dict(fit),
        "metrics": metrics,
        "warnings": warnings,
    }
    output = {
        "schema": 1,
        "source": {
            "type": "georeferenced-centerline",
            "input": str(input_path),
            "reference": str(context.reference_path) if context.reference_path else "",
            "control_points": args.control_points,
            "crs": args.output_crs,
        },
        "orientation": {"signed_area": signed_area(transformed_source), "direction": "ccw" if signed_area(transformed_source) > 0.0 else "cw"},
        "length_m": closed_length(transformed_source),
        "georeferencing": georeferencing,
        "polyline": result_points,
    }
    report = {
        "input": str(input_path),
        "reference": str(context.reference_path) if context.reference_path else "",
        "control_points_file": args.control_points,
        **georeferencing,
        "controls": control_details,
        "input_length": closed_length(source),
        "output_length_m": closed_length(transformed_source),
        "overlay": args.overlay,
        "output_written": status != "rejected",
        "reference_metadata": context.control_data.get("reference", context.reference_data.get("source", {})),
    }
    write_json(report_path, report)
    write_overlay(overlay_path, source, context.reference_metric, control_details, fit, metrics, status, warnings)
    print(f"Alignment mode={mode}, status={status}, RMSE={rmse:.3f} m, scale={fit.scale:.9f}, fit CRS={context.fit_crs}")
    if status == "rejected":
        raise SystemExit(f"Georeferencing rejected; no centerline was written. Review {report_path}")
    write_json(output_path, output)
    print(f"Wrote georeferenced centerline: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
