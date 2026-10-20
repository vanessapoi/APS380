# /***************************************************************************
#     file                 : track_georeference.py
#     created              : 24 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2, or (at your option) any later version.

"""Start-line geographic metadata. Never changes road geometry or XML formatting."""

from __future__ import annotations

import hashlib
import json
import math
import pathlib
import re
import xml.etree.ElementTree as ET  # nosec B405 - construction only; parsing uses overlay helpers

import numpy as np

from torcs_track_tools.core.overlay import parse_track_root, parse_track_segments, torcs_points
from torcs_track_tools.core.polyline import lonlat_from_xy, to_xy_tuples


def geographic_polyline(data: dict) -> list[dict]:
    """Accept lat/lon, or explicitly georeferenced projected coordinates."""
    points = data.get("polyline", [])
    if len(points) < 3:
        raise ValueError("No usable polyline")
    if all("lat" in p and "lon" in p for p in points):
        result = [{"lat": float(p["lat"]), "lon": float(p["lon"])} for p in points]
    else:
        source_info = data.get("source", {})
        crs = data.get("crs") or (source_info.get("crs") if isinstance(source_info, dict) else None)
        if not isinstance(crs, str) or not crs:
            raise ValueError("Local coordinates have no explicit CRS")
        from rasterio.warp import transform

        lon, lat = transform(crs, "EPSG:4326", [p["x"] for p in points], [p["y"] for p in points])
        result = [{"lat": a, "lon": o} for a, o in zip(lat, lon, strict=True)]
    if not all(math.isfinite(p["lat"]) and math.isfinite(p["lon"]) and abs(p["lat"]) <= 90 and abs(p["lon"]) <= 180 for p in result):
        raise ValueError("Invalid geographic coordinates")
    return result


def reference_at_pose(data: dict, x: float, y: float, heading: float) -> dict:
    """Convert the fitter's actual start pose, including projected grid convergence."""
    first = data["polyline"][0]
    if "x" not in first or "y" not in first:
        lat, lon = lonlat_from_xy((x, y), first)
        return {"latitude": lat, "longitude": lon, "heading": (90 - math.degrees(heading)) % 360}
    source = data.get("source", {})
    crs = data.get("crs") or (source.get("crs") if isinstance(source, dict) else None)
    if not crs:
        raise ValueError("Local fitted pose has no geographic frame")
    from rasterio.warp import transform

    lon, lat = transform(crs, "EPSG:4326", [x, x + 10 * math.cos(heading)], [y, y + 10 * math.sin(heading)])
    dx, dy = to_xy_tuples([{"lat": lat[1], "lon": lon[1]}], {"lat": lat[0], "lon": lon[0]})[0]
    return {"latitude": lat[0], "longitude": lon[0], "heading": math.degrees(math.atan2(dx, dy)) % 360}


def loop_samples(points: np.ndarray, count: int) -> tuple[np.ndarray, float]:
    closed = np.vstack((points, points[0]))
    lengths = np.hypot(*np.diff(closed, axis=0).T)
    keep = np.r_[True, lengths > 1e-8]
    closed = closed[keep]
    stations = np.r_[0.0, np.cumsum(np.hypot(*np.diff(closed, axis=0).T))]
    if stations[-1] < 1:
        raise ValueError("Degenerate polyline")
    targets = np.arange(count) * stations[-1] / count
    return np.column_stack([np.interp(targets, stations, closed[:, i]) for i in range(2)]), float(stations[-1])


def reference_for_segment(snippet: str, start_name: str, original: dict) -> dict:
    segments = parse_track_segments('<params><section name="Track Segments">' + snippet + '</section></params>')
    if not segments:
        raise ValueError("No track segments")
    start_name = start_name or segments[0]["name"]
    index = next((i for i, segment in enumerate(segments) if segment["name"] == start_name), None)
    if index is None:
        raise ValueError(f"Reference segment not found: {start_name}")
    before = segments[:index]
    pose = torcs_points(before, 1.0)[-1]
    angle = math.radians(90 - original["heading"])
    east = math.cos(angle) * pose["x"] - math.sin(angle) * pose["y"]
    north = math.sin(angle) * pose["x"] + math.cos(angle) * pose["y"]
    lat, lon = lonlat_from_xy((east, north), {"lat": original["latitude"], "lon": original["longitude"]})
    turn = sum((1 if s["type"] == "lft" else -1) * s["arc"] for s in before if s["type"] != "str")
    return {"latitude": lat, "longitude": lon, "heading": (original["heading"] - turn) % 360}


def fit_reference(xml: str, data: dict, max_rmse: float = 20.0) -> tuple[dict, dict]:
    """Rigid, unit-scale fit with cyclic phase and source direction search.

    Model origin is the road centre, tangent +X. Source projection uses the
    same east/north approximation as the polyline fitter (no grid bearing).
    """
    points = geographic_polyline(data)
    count = 720
    source, source_length = loop_samples(np.asarray(to_xy_tuples(points)), count)
    segments = parse_track_segments(xml)
    if not segments:
        raise ValueError("No track segments")
    model, model_length = loop_samples(np.array([(p["x"], p["y"]) for p in torcs_points(segments, 2.0)]), count)
    centre = model.mean(axis=0)
    u = model - centre

    def evaluate(phase: float, reverse: bool) -> tuple[float, float, np.ndarray]:
        indices = (phase + (-1 if reverse else 1) * np.arange(count)) % count
        lower = np.floor(indices).astype(int)
        fraction = (indices - lower)[:, None]
        target = source[lower] * (1 - fraction) + source[(lower + 1) % count] * fraction
        v = target - target.mean(axis=0)
        angle = math.atan2(float(np.sum(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])), float(np.sum(u * v)))
        c, s = math.cos(angle), math.sin(angle)
        rotation = np.array([[c, s], [-s, c]])
        offset = target.mean(axis=0) - centre @ rotation
        residual = model @ rotation + offset - target
        return float(np.sqrt(np.mean(np.sum(residual ** 2, axis=1)))), angle, offset

    candidates = [(evaluate(i, reverse)[0], i, reverse) for reverse in (False, True) for i in range(count)]
    _, phase, reverse = min(candidates)
    lo, hi = phase - 1.0, phase + 1.0
    for _ in range(24):
        a, b = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if evaluate(a, reverse)[0] < evaluate(b, reverse)[0]:
            hi = b
        else:
            lo = a
    phase = (lo + hi) / 2
    rmse, angle, offset = evaluate(phase, reverse)
    alternative = min(score for score, index, rev in candidates if rev != reverse or min((index - phase) % count, (phase - index) % count) > count * 0.1)
    if rmse > max_rmse:
        raise ValueError(f"Source fit RMSE {rmse:.2f} m exceeds {max_rmse:.2f} m")
    if alternative < rmse + 0.5:
        raise ValueError(f"Ambiguous source orientation (RMSE {rmse:.2f}/{alternative:.2f} m)")
    lat, lon = lonlat_from_xy(tuple(offset), points[0])
    geo = {"latitude": lat, "longitude": lon, "heading": (90 - math.degrees(angle)) % 360}
    report = {"rmse_m": rmse, "alternative_rmse_m": alternative, "source_reversed": reverse,
              "source_phase_fraction": (phase / count) % 1, "source_length_m": source_length,
              "track_length_m": model_length, "reference": geo.copy()}
    return geo, report


def remove_reference(root: ET.Element) -> None:
    for section in list(root):
        if section.tag == "section" and section.get("name") == "Georeference":
            root.remove(section)


def invalidate_reference_text(text: str) -> str:
    """For layout-changing tools; the metadata section has no nested sections."""
    return re.sub(r'<section\b(?=[^>]*\bname\s*=\s*[\"\']Georeference[\"\'])[^>]*>.*?</section>', "", text, flags=re.DOTALL)


def track_plan_sha256(xml: str) -> str:
    """Immutable ordered layout identity, independent of elevation and formatting."""
    root = parse_track_root(xml)
    section = root.find("section[@name='Main Track']/section[@name='Track Segments']") if root is not None else None
    segments = list(section.findall("section")) if section is not None else []
    if not segments:
        raise ValueError("No track segments")
    # Retain units: the overlay parser assumes degrees, but changing an XML
    # arc from degrees to radians must invalidate an old geographic transform.
    names = {"type", "lg", "radius", "end radius", "arc"}
    layout = [{"name": s.get("name"), "geometry": {
        a.get("name"): (a.get("val"), a.get("unit")) for a in s if a.get("name") in names
    }} for s in segments]
    canonical = json.dumps(layout, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def start_elevation_signature(xml: str) -> dict:
    root = parse_track_root(xml)
    if root is None:
        raise ValueError("Invalid track XML")
    segment = root.find("section[@name='Main Track']/section[@name='Track Segments']/section")
    if segment is None:
        raise ValueError("No track segments")
    names = {"z start", "z start left", "z start right", "banking start"}
    return {a.get("name"): (a.get("val"), a.get("unit")) for a in segment if a.get("name") in names}


def preserved_altitude(previous_xml: str, current_xml: str) -> float | None:
    """Preserve only with unchanged ordered geometry and reference elevation.

    Layout-mutating callers must supply the pre-edit XML. A changed layout is
    conservatively invalidated; its absolute altitude must be derived again.
    """
    if track_plan_sha256(previous_xml) != track_plan_sha256(current_xml):
        return None
    if start_elevation_signature(previous_xml) != start_elevation_signature(current_xml):
        return None
    root = parse_track_root(previous_xml)
    altitude = root.find("section[@name='Georeference']/attnum[@name='altitude']")
    if altitude is None or altitude.get("unit", "m") != "m":
        return None
    value = float(altitude.get("val", "nan"))
    return value if math.isfinite(value) else None


def refresh_reference(path: pathlib.Path, source: pathlib.Path, previous_xml: str | None = None) -> None:
    original = path.read_bytes()
    current_xml = original.decode("utf-8-sig")
    text = invalidate_reference_text(current_xml)
    try:
        geo, _ = fit_reference(text, json.loads(source.read_text(encoding="utf-8-sig")))
        altitude = preserved_altitude(previous_xml if previous_xml is not None else current_xml, current_xml)
        if altitude is not None:
            geo["altitude"] = altitude
        updated = insert_reference(text.encode("utf-8"), geo)
    except ValueError as error:
        print(f"Georeference unavailable: {error}")
        updated = text.encode("utf-8")
    path.write_bytes(updated)


def set_reference(root: ET.Element, values: dict) -> None:
    remove_reference(root)
    if not values:
        return
    section = ET.SubElement(root, "section", {"name": "Georeference"})
    for key in ("latitude", "longitude", "altitude", "heading"):
        if key in values:
            ET.SubElement(section, "attnum", {"name": key, "unit": "m" if key == "altitude" else "deg", "val": f"{values[key]:.9f}"})


def update_elevation_reference(root: ET.Element, sources: list[tuple[float, float]]) -> None:
    section = root.find("section[@name='Georeference']")
    valid = [(value, weight) for value, weight in sources if math.isfinite(value) and math.isfinite(weight) and weight > 0]
    if section is None and valid:
        section = ET.SubElement(root, "section", {"name": "Georeference"})
    if section is None:
        return
    for child in list(section):
        if child.get("name") == "altitude":
            section.remove(child)
    if valid:
        altitude = sum(value * weight for value, weight in valid) / sum(weight for _, weight in valid)
        ET.SubElement(section, "attnum", {"name": "altitude", "unit": "m", "val": f"{altitude:.6f}"})


def insert_reference(original: bytes, values: dict) -> bytes:
    """Insert only: preserve all existing bytes, including BOM, entities and CRLF."""
    if re.search(rb'<section\b[^>]*\bname\s*=\s*[\"\']Georeference[\"\']', original):
        raise ValueError("Georeference already exists; refusing to overwrite")
    end = original.rfind(b"</params>")
    if end < 0:
        raise ValueError("Missing params end tag")
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    root = ET.Element("params")
    set_reference(root, values)
    ET.indent(root, space="  ")
    block = ET.tostring(root[0], encoding="utf-8").rstrip().replace(b"\n", newline)
    insertion = b"  " + block + newline
    result = original[:end] + insertion + original[end:]
    if result[:end] + result[end + len(insertion):] != original:
        raise ValueError("Metadata insertion changed original XML bytes")
    return result


def enrich_file(path: pathlib.Path, source: pathlib.Path, max_rmse: float = 20.0, write: bool = False) -> dict:
    original = path.read_bytes()
    root = parse_track_root(original.decode("utf-8-sig"))
    version = root.find("section[@name='Header']/attnum[@name='version']") if root is not None else None
    if version is None or float(version.get("val", "0")) != 4:
        raise ValueError("Metadata enrichment requires a v4 track")
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if data.get("type") == "raster-dem-profile":
        geo, report = reference_from_profile(original.decode("utf-8-sig"), data, source, max_rmse)
    else:
        geo, report = fit_reference(original.decode("utf-8-sig"), data, max_rmse)
    altitude, altitude_report = find_altitude(path, geo, original.decode("utf-8-sig"))
    if altitude is not None:
        geo["altitude"] = altitude
    report["reference"] = geo.copy()
    report["altitude"] = altitude_report
    updated = insert_reference(original, geo)
    report.update({"track": str(path), "source": str(source), "original_sha256": hashlib.sha256(original).hexdigest(),
                   "updated_sha256": hashlib.sha256(updated).hexdigest(), "metadata_only_verified": True})
    if write:
        path.write_bytes(updated)
        if path.read_bytes() != updated:
            raise OSError("Metadata write verification failed")
    return report


def resolve_source_path(raw: str, context: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(raw.replace("\\", "/"))
    for candidate in (path, context.parent / path, *(parent / path for parent in context.parents)):
        if candidate.is_file():
            return candidate
    raise ValueError(f"Source file unavailable: {raw}")


def profile_altitude(profile: pathlib.Path, data: dict, geo: dict, xml: str) -> tuple[float, dict]:
    """Recover an absolute road elevation, never a normalized terrain-map bound."""
    if data.get("type") == "plan-fit-dem-profile":
        original = resolve_source_path(data["elevation_source"], profile)
        return profile_altitude(original, json.loads(original.read_text(encoding="utf-8-sig")), geo, xml)
    if isinstance(data.get("source"), dict) and data["source"].get("type") == "dem-corridor":
        source = resolve_source_path(data["source"]["polyline"], profile)
        _, fit = fit_reference(xml, json.loads(source.read_text(encoding="utf-8-sig")))
        samples = data["road_profile"]["samples"]
        total = float(data["total_length_m"])
        station = fit["source_phase_fraction"] * total
        value = float(np.interp(station, [s["station_m"] for s in samples] + [total],
                                [s["elevation_m"] for s in samples] + [samples[0]["elevation_m"]]))
        return value, {"method": "absolute-dem-corridor", "profile": str(profile), "station_m": station}
    if data.get("type") not in ("raster-dem-profile", "road-surface-profile") or "zero_elevation_m" not in data:
        raise ValueError("No supported absolute elevation datum")
    raster = resolve_source_path(data["raster"], profile)
    import rasterio
    from rasterio.warp import transform

    with rasterio.open(raster) as dataset:
        crs = dataset.crs
    if crs is None:
        raise ValueError("Raster CRS unavailable")
    # Geographic fit errors are in degrees, projected fit errors in CRS units.
    if data.get("type") == "raster-dem-profile" and crs.is_projected and data.get("fit", {}).get("rmse_m", float("inf")) > 20:
        raise ValueError("Rejected elevation profile with poor geographic fit")
    samples = data["samples"] if "samples" in data else data["elevation_profile"]["samples"]
    lon, lat = transform(crs, "EPSG:4326", [s["raster_x"] for s in samples], [s["raster_y"] for s in samples])
    xy = np.array(to_xy_tuples([{"lat": a, "lon": o} for a, o in zip(lat, lon, strict=True)],
                               {"lat": geo["latitude"], "lon": geo["longitude"]}))
    following = np.roll(xy, -1, axis=0)
    delta = following - xy
    fraction = np.clip(-np.sum(xy * delta, axis=1) / np.maximum(np.sum(delta * delta, axis=1), 1e-12), 0, 1)
    distance = np.hypot(*(xy + fraction[:, None] * delta).T)
    index = int(np.argmin(distance))
    if distance[index] > 25:
        raise ValueError(f"Elevation road reference is {distance[index]:.1f} m from start")
    heights = [float(s.get("raw_elevation_m", data["zero_elevation_m"] + s["elevation_m"])) for s in samples]
    height = heights[index] + float(fraction[index]) * (heights[(index + 1) % len(samples)] - heights[index])
    if not math.isfinite(height):
        raise ValueError("Nonfinite absolute elevation")
    return height, {"method": "absolute-raster-road-profile", "profile": str(profile), "raster": str(raster),
                    "distance_m": float(distance[index]), "sample_index": index}


def find_altitude(track: pathlib.Path, geo: dict, xml: str) -> tuple[float | None, dict]:
    rejected = []
    candidates = sorted(set((track.parent / "source").rglob("*profile*.json")) |
                        set((track.parent / "source").rglob("*terrain*.json")),
                        key=lambda p: ("road-surface" not in p.name, "terrain" in p.name, str(p)))
    for path in candidates:
        if "report" in path.name or "broken" in path.name or "backup" in str(path):
            continue
        try:
            value, report = profile_altitude(path, json.loads(path.read_text(encoding="utf-8-sig")), geo, xml)
            return value, report
        except (ValueError, KeyError, OSError) as error:
            rejected.append({"profile": str(path), "reason": str(error)})
    # A stale/misaligned profile does not make its DEM unusable. Sample the
    # independently recovered geographic anchor, without using that old fit.
    for path in candidates:
        if "report" in path.name or "broken" in path.name or "backup" in str(path):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            value, raster = sample_absolute_raster(path, data, geo)
            return value, {"method": "dem-at-geographic-anchor", "raster": str(raster), "profile": str(path), "rejected_profiles": rejected}
        except (ValueError, KeyError, OSError):
            continue
    return None, {"method": "unavailable", "rejected": rejected}


def sample_absolute_raster(profile: pathlib.Path, data: dict, geo: dict) -> tuple[float, pathlib.Path]:
    import rasterio
    from rasterio.warp import transform
    from rasterio.windows import Window

    if data.get("type") not in ("raster-dem-profile", "road-surface-profile") or "zero_elevation_m" not in data:
        raise ValueError("No absolute raster source")
    raster = resolve_source_path(data["raster"], profile)
    with rasterio.open(raster) as dataset:
        x, y = transform("EPSG:4326", dataset.crs, [geo["longitude"]], [geo["latitude"]])
        col, row = (~dataset.transform) * (x[0], y[0])
        col -= 0.5
        row -= 0.5
        c, r = math.floor(col), math.floor(row)
        if c < 0 or r < 0 or c + 1 >= dataset.width or r + 1 >= dataset.height:
            raise ValueError("Anchor outside raster")
        values = dataset.read(1, window=Window(c, r, 2, 2), masked=True)
        if np.ma.getmaskarray(values).any() or not np.isfinite(values).all():
            raise ValueError("Missing elevation at geographic anchor")
        fx, fy = col - c, row - r
        value = float(values[0, 0] * (1-fx) * (1-fy) + values[0, 1] * fx * (1-fy) + values[1, 0] * (1-fx) * fy + values[1, 1] * fx * fy)
    return value, raster


def reference_from_profile(xml: str, data: dict, profile: pathlib.Path, max_rmse: float) -> tuple[dict, dict]:
    """Use an existing accepted geographic transform for deliberately scaled layouts.

    The profile's stored original layout fingerprint must match. Only
    the reference point/tangent is imported, not its scale into simulation.
    """
    import rasterio
    from rasterio.warp import transform

    fingerprint = data.get("track_plan_sha256")
    if not fingerprint:
        raise ValueError("Elevation profile has no immutable layout fingerprint")
    if track_plan_sha256(xml) != fingerprint:
        raise ValueError("Elevation profile layout no longer matches")
    raster = resolve_source_path(data["raster"], profile)
    with rasterio.open(raster) as dataset:
        crs = dataset.crs
    fit = data["fit"]
    if not crs or not crs.is_projected or fit["rmse_m"] > max_rmse:
        raise ValueError("No reliable projected profile transform")
    x, y = fit["offset_x"], fit["offset_y"]
    lon, lat = transform(crs, "EPSG:4326", [x, x + fit["cos"] * 10], [y, y + fit["sin"] * 10])
    dx, dy = to_xy_tuples([{"lat": lat[1], "lon": lon[1]}], {"lat": lat[0], "lon": lon[0]})[0]
    geo = {"latitude": lat[0], "longitude": lon[0], "heading": math.degrees(math.atan2(dx, dy)) % 360}
    return geo, {"method": "accepted-profile-transform", "rmse_m": fit["rmse_m"], "source_scale": fit.get("scale", 1.0),
                 "scale_note": "Imported anchor and bearing only; simulation metres remain unscaled"}
