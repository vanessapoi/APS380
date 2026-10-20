#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : compose_road_surface_profile.py
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

"""Compose elevation and banking data into one road-surface profile."""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProfilePayload:
    path: pathlib.Path
    kind: str
    data: Any
    section: dict[str, Any]
    samples: list[dict[str, Any]]
    station_frame: str
    source_total: float | None
    total_length: float | None
    source_polyline: str
    mapping: dict[str, Any]
    sampling: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compose elevation and banking profiles into a road-surface profile")
    parser.add_argument("--elevation-profile", default="", help="Elevation profile JSON/CSV or road-surface profile JSON")
    parser.add_argument("--banking-profile", default="", help="Banking road-surface profile JSON")
    parser.add_argument("--output", required=True, help="Output road-surface profile JSON")
    parser.add_argument("--report", default="", help="Optional compose diagnostics JSON")
    return parser.parse_args()


def parse_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def finite_float(value: object) -> float | None:
    parsed = parse_float(value, math.nan)
    return parsed if math.isfinite(parsed) else None


def load_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON profile: {path}: {exc}") from exc


def load_csv_elevation(path: pathlib.Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        raise SystemExit(f"Profile has no samples: {path}")
    header = [c.strip().lower() for c in rows[0]]
    if any(h in header for h in ("station_m", "station", "s", "distance_m", "distance")):
        station_idx = next(i for i, h in enumerate(header) if h in ("station_m", "station", "s", "distance_m", "distance"))
        elevation_idx = next(i for i, h in enumerate(header) if h in ("elevation_m", "elevation", "z", "height_m", "height"))
        weight_idx = next((i for i, h in enumerate(header) if h == "weight"), -1)
        data_rows = rows[1:]
    else:
        station_idx = 0
        elevation_idx = 1
        weight_idx = 2 if len(rows[0]) > 2 else -1
        data_rows = rows
    samples = []
    for row in data_rows:
        if len(row) <= max(station_idx, elevation_idx):
            continue
        sample = {"station_m": parse_float(row[station_idx]), "elevation_m": parse_float(row[elevation_idx])}
        if weight_idx >= 0 and len(row) > weight_idx:
            sample["weight"] = parse_float(row[weight_idx], 1.0)
        samples.append(sample)
    return samples, {"source": "csv-elevation-profile"}


def scalar_equal(a: object, b: object) -> bool:
    fa = finite_float(a)
    fb = finite_float(b)
    if fa is not None and fb is not None:
        return abs(fa - fb) <= 1e-6
    return a == b


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def normalized_path_value(path_value: str, owner: pathlib.Path) -> str:
    path = resolved_path_value(path_value, owner)
    return str(path).replace("\\", "/").lower()


def resolved_path_value(path_value: str, owner: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(path_value)
    if not path.is_absolute():
        path = owner.parent / path
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def data_source_polyline(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("source_polyline", "polyline"):
        if data.get(key):
            return str(data[key])
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    return str(source.get("polyline", ""))


def data_mapping(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    mapping = deepcopy(data.get("mapping")) if isinstance(data.get("mapping"), dict) else {}
    if data.get("station_map") and not mapping.get("station_map"):
        mapping["station_map"] = deepcopy(data["station_map"])
    if data.get("source_shift_m") is not None and "source_shift_m" not in mapping:
        mapping["source_shift_m"] = data["source_shift_m"]
    if data.get("source_reversed") is not None and "source_reversed" not in mapping:
        mapping["source_reversed"] = bool(data["source_reversed"])
    return mapping


def data_sampling(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    sampling = deepcopy(data.get("sampling")) if isinstance(data.get("sampling"), dict) else {}
    if data.get("real_road_width_m") is not None and "real_road_width_m" not in sampling:
        sampling["real_road_width_m"] = data["real_road_width_m"]
    return sampling


def first_defined_float(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if data.get(key) is not None:
            return finite_float(data.get(key))
    return None


def infer_station_frame(data: Any, samples: list[dict[str, Any]]) -> str:
    if isinstance(data, dict):
        frame = str(data.get("station_frame", "")).strip().lower()
        if frame in ("source", "xml"):
            return frame
        if data.get("type") == "raster-dem-profile":
            return "xml"
        source = data.get("source") if isinstance(data.get("source"), dict) else {}
        if source.get("type") == "dem-corridor" or data.get("road_profile"):
            return "source" if data_source_polyline(data) else "xml"
    if any("source_station_m" in sample for sample in samples):
        return "source"
    return "xml"


def validate_samples(samples: list[dict[str, Any]], path: pathlib.Path, kind: str) -> None:
    field = "elevation_m" if kind == "elevation" else "banking_deg"
    if len(samples) < 2:
        raise SystemExit(f"At least two {kind} samples are required: {path}")
    for sample in samples:
        if not isinstance(sample, dict):
            raise SystemExit(f"Unsupported {kind} sample in {path}: {sample}")
        if field not in sample and (kind != "banking" or not any(key in sample for key in ("bank_deg", "banking", "bank"))):
            raise SystemExit(f"{kind.capitalize()} sample missing {field}: {sample}")
        if not any(key in sample for key in ("source_station_m", "station_m", "station", "s", "distance_m", "distance")):
            raise SystemExit(f"{kind.capitalize()} sample missing station: {sample}")


def samples_from_section(section: dict[str, Any]) -> list[dict[str, Any]]:
    return deepcopy(section.get("samples", [])) if isinstance(section.get("samples"), list) else []


def elevation_section_from_dict(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if data.get("type") == "road-surface-profile":
        section = deepcopy(data.get("elevation_profile")) if isinstance(data.get("elevation_profile"), dict) else {}
        return section, samples_from_section(section)
    if isinstance(data.get("road_profile"), dict):
        section = deepcopy(data.get("road_profile"))
        return section, samples_from_section(section)
    section = {"source": str(data.get("type", "elevation-profile"))}
    raw_samples = data.get("samples", data.get("profile", []))
    samples = deepcopy(raw_samples) if isinstance(raw_samples, list) else []
    return section, samples


def elevation_samples_from_list(data: list[Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    samples = [
        {"station_m": item[0], "elevation_m": item[1], **({"weight": item[2]} if len(item) > 2 else {})}
        for item in data
        if isinstance(item, list | tuple) and len(item) >= 2
    ]
    return {"source": "elevation-profile"}, samples


def elevation_section_from_data(data: Any, path: pathlib.Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if isinstance(data, dict):
        return elevation_section_from_dict(data)
    if isinstance(data, list):
        return elevation_samples_from_list(data)
    raise SystemExit(f"Unsupported elevation profile: {path}")


def extract_elevation(path: pathlib.Path) -> ProfilePayload:
    if path.suffix.lower() == ".csv":
        samples, section = load_csv_elevation(path)
        data: Any = {"samples": samples}
    else:
        data = load_json(path)
        section, samples = elevation_section_from_data(data, path)
    validate_samples(samples, path, "elevation")
    return make_payload(path, "elevation", data, section, samples)


def extract_banking(path: pathlib.Path) -> ProfilePayload:
    if path.suffix.lower() == ".csv":
        raise SystemExit(f"Banking profiles must be JSON road-surface profiles: {path}")
    data = load_json(path)
    if not isinstance(data, dict):
        raise SystemExit(f"Unsupported banking profile: {path}")
    if data.get("type") == "road-surface-profile":
        section = deepcopy(data.get("banking_profile")) if isinstance(data.get("banking_profile"), dict) else {}
    else:
        section = deepcopy(data.get("banking_profile")) if isinstance(data.get("banking_profile"), dict) else deepcopy(data)
    samples = deepcopy(section.get("samples", [])) if isinstance(section.get("samples"), list) else []
    validate_samples(samples, path, "banking")
    return make_payload(path, "banking", data, section, samples)


def make_payload(path: pathlib.Path, kind: str, data: Any, section: dict[str, Any], samples: list[dict[str, Any]]) -> ProfilePayload:
    station_frame = infer_station_frame(data, samples)
    source_total = None
    total_length = None
    if isinstance(data, dict):
        source_total = first_defined_float(data, ("source_total_length_m", "source_fit_length_m"))
        total_length = first_defined_float(data, ("total_length_m",))
        if source_total is None and station_frame == "source":
            source_total = total_length
    return ProfilePayload(
        path,
        kind,
        data,
        section,
        samples,
        station_frame,
        source_total,
        total_length,
        data_source_polyline(data),
        data_mapping(data),
        data_sampling(data),
    )


def merge_mapping(current: dict[str, Any], incoming: dict[str, Any], path: pathlib.Path) -> dict[str, Any]:
    merged = deepcopy(current)
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = deepcopy(value)
        elif key == "station_map":
            if canonical_json(merged[key]) != canonical_json(value):
                raise SystemExit(f"Incompatible station maps in {path}")
        elif not scalar_equal(merged[key], value):
            raise SystemExit(f"Incompatible mapping field {key} in {path}: {merged[key]} vs {value}")
    return merged


def merge_sampling(current: dict[str, Any], incoming: dict[str, Any], path: pathlib.Path) -> dict[str, Any]:
    merged = deepcopy(current)
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = deepcopy(value)
        elif not scalar_equal(merged[key], value):
            raise SystemExit(f"Incompatible sampling field {key} in {path}: {merged[key]} vs {value}")
    return merged


def require_matching_station_frame(first: ProfilePayload, payload: ProfilePayload, station_frame: str) -> None:
    if payload.station_frame != station_frame:
        raise SystemExit(f"Incompatible station frames: {first.path} is {station_frame}, {payload.path} is {payload.station_frame}")


def merge_source_total(current: float | None, payload: ProfilePayload) -> float | None:
    if payload.source_total is None:
        return current
    if current is None:
        return payload.source_total
    if abs(current - payload.source_total) > 1e-6:
        raise SystemExit(f"Incompatible source lengths in {payload.path}: {current} vs {payload.source_total}")
    return current


def merge_total_length(current: float | None, payload: ProfilePayload) -> float | None:
    if payload.total_length is None:
        return current
    if current is None:
        return payload.total_length
    if abs(current - payload.total_length) > 1e-6:
        raise SystemExit(f"Incompatible track lengths in {payload.path}: {current} vs {payload.total_length}")
    return current


def merge_source_polyline(current: str, owner: pathlib.Path, payload: ProfilePayload) -> tuple[str, pathlib.Path]:
    if not payload.source_polyline:
        return current, owner
    if not current:
        return payload.source_polyline, payload.path
    if normalized_path_value(current, owner) != normalized_path_value(payload.source_polyline, payload.path):
        raise SystemExit(f"Incompatible source polylines in {payload.path}: {current} vs {payload.source_polyline}")
    return current, owner


def compatible_metadata(payloads: list[ProfilePayload]) -> dict[str, Any]:
    first = payloads[0]
    station_frame = first.station_frame
    source_total = first.source_total
    total_length = first.total_length
    source_polyline = first.source_polyline
    source_polyline_owner = first.path
    mapping = deepcopy(first.mapping)
    sampling = deepcopy(first.sampling)
    for payload in payloads[1:]:
        require_matching_station_frame(first, payload, station_frame)
        source_total = merge_source_total(source_total, payload)
        total_length = merge_total_length(total_length, payload)
        source_polyline, source_polyline_owner = merge_source_polyline(source_polyline, source_polyline_owner, payload)
        mapping = merge_mapping(mapping, payload.mapping, payload.path)
        sampling = merge_sampling(sampling, payload.sampling, payload.path)
    return {
        "station_frame": station_frame,
        "source_total_length_m": source_total,
        "total_length_m": total_length,
        "source_polyline": str(resolved_path_value(source_polyline, source_polyline_owner)) if source_polyline else "",
        "mapping": mapping,
        "sampling": sampling,
    }


def station_value(sample: dict[str, Any], frame: str) -> float:
    if frame == "source":
        return parse_float(sample.get("source_station_m", sample.get("station_m", sample.get("station", sample.get("s", sample.get("distance_m", sample.get("distance")))))))
    return parse_float(sample.get("station_m", sample.get("station", sample.get("s", sample.get("distance_m", sample.get("distance", sample.get("source_station_m")))))))


def canonical_sample(sample: dict[str, Any], frame: str, value_key: str) -> dict[str, Any]:
    out = deepcopy(sample)
    for key in ("source_station_m", "station_m", "station", "s", "distance_m", "distance"):
        out.pop(key, None)
    if value_key == "banking_deg" and "banking_deg" not in out:
        for key in ("bank_deg", "banking", "bank"):
            if key in out:
                out["banking_deg"] = out.pop(key)
                break
    station_key = "source_station_m" if frame == "source" else "station_m"
    return {station_key: station_value(sample, frame), **out}


def canonical_section(payload: ProfilePayload, frame: str) -> dict[str, Any]:
    value_key = "elevation_m" if payload.kind == "elevation" else "banking_deg"
    section = deepcopy(payload.section)
    section.pop("samples", None)
    section.setdefault("source_profile", str(payload.path))
    section["samples"] = [canonical_sample(sample, frame, value_key) for sample in payload.samples]
    return section


def copy_elevation_top_level(output: dict[str, Any], payload: ProfilePayload | None) -> None:
    if payload is None or not isinstance(payload.data, dict):
        return
    for key in ("track_xml", "raster", "zero_elevation_m", "sample_step_m", "resampling", "fit", "normalization", "elevation_source"):
        if payload.data.get(key) is not None:
            output[key] = deepcopy(payload.data[key])
    if payload.data.get("weight") is not None:
        output["weight"] = payload.data["weight"]


def compose_profile(elevation: ProfilePayload | None, banking: ProfilePayload | None) -> dict[str, Any]:
    payloads = [payload for payload in (elevation, banking) if payload is not None]
    if not payloads:
        raise SystemExit("Use --elevation-profile, --banking-profile, or both")
    metadata = compatible_metadata(payloads)
    output: dict[str, Any] = {
        "schema": 1,
        "type": "road-surface-profile",
        "station_frame": metadata["station_frame"],
        "composed_from": {
            "elevation_profile": str(elevation.path) if elevation else None,
            "banking_profile": str(banking.path) if banking else None,
        },
    }
    if metadata["station_frame"] == "source" and metadata["source_total_length_m"] is not None:
        output["source_total_length_m"] = metadata["source_total_length_m"]
    elif metadata["total_length_m"] is not None:
        output["total_length_m"] = metadata["total_length_m"]
    if metadata["source_polyline"]:
        output["source_polyline"] = metadata["source_polyline"]
    if metadata["mapping"]:
        output["mapping"] = metadata["mapping"]
    if metadata["sampling"]:
        output["sampling"] = metadata["sampling"]
    copy_elevation_top_level(output, elevation)
    if elevation is not None:
        output["elevation_profile"] = canonical_section(elevation, metadata["station_frame"])
    if banking is not None:
        output["banking_profile"] = canonical_section(banking, metadata["station_frame"])
    return output


def report_for(output_path: pathlib.Path, profile: dict[str, Any], elevation: ProfilePayload | None, banking: ProfilePayload | None) -> dict[str, Any]:
    mapping = profile.get("mapping") if isinstance(profile.get("mapping"), dict) else {}
    return {
        "output": str(output_path),
        "station_frame": profile.get("station_frame"),
        "source_total_length_m": profile.get("source_total_length_m"),
        "total_length_m": profile.get("total_length_m"),
        "source_polyline": profile.get("source_polyline", ""),
        "elevation_profile": str(elevation.path) if elevation else None,
        "banking_profile": str(banking.path) if banking else None,
        "elevation_sample_count": len(elevation.samples) if elevation else 0,
        "banking_sample_count": len(banking.samples) if banking else 0,
        "mapping": {
            "has_station_map": bool(mapping.get("station_map")),
            "station_map_count": len(mapping.get("station_map", [])) if isinstance(mapping.get("station_map"), list) else 0,
            "source_reversed": bool(mapping.get("source_reversed", False)),
            "source_shift_m": mapping.get("source_shift_m"),
        },
    }


def main() -> int:
    args = parse_args()
    elevation = extract_elevation(pathlib.Path(args.elevation_profile)) if args.elevation_profile else None
    banking = extract_banking(pathlib.Path(args.banking_profile)) if args.banking_profile else None
    profile = compose_profile(elevation, banking)
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    if args.report:
        report_path = pathlib.Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report_for(output, profile, elevation, banking), indent=2), encoding="utf-8")
    print(f"Wrote road-surface profile: {output}")
    print(f"Elevation samples: {len(elevation.samples) if elevation else 0}, banking samples: {len(banking.samples) if banking else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
