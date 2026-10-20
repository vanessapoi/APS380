# /***************************************************************************
#
#     file                 : track_map.py
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

"""Render final TORCS XML geometry as a menu map and review SVG."""

from __future__ import annotations

import math
import pathlib
from dataclasses import dataclass, replace
from typing import Any

from PIL import Image, ImageDraw  # type: ignore[import-not-found]

from torcs_track_tools.core.defaults import DISTANCE_TO_METERS
from torcs_track_tools.core.geometry import (
    Pose,
    Sample,
    Segment,
    advance_constant_turn,
    advance_straight,
    torcs_step_count,
    turn_length,
    variable_turn_step_length,
)
from torcs_track_tools.core.track_xml import child_section, find_att, parse_xml_readonly, segment_from_element

Point = tuple[float, float]
MAX_MAP_SIZE = 1024


@dataclass(frozen=True)
class TrackMapScene:
    size: int
    track: tuple[Point, ...]
    start_marker: tuple[Point, ...]
    road_width: float
    marker_outline_width: float


def distance_scale(element: Any, name: str) -> float:
    attribute = find_att(element, "attnum", name)
    if attribute is None:
        return 1.0
    unit = attribute.get("unit", "")
    if unit not in DISTANCE_TO_METERS:
        raise SystemExit(f"Unsupported distance unit '{unit}' on segment attribute '{name}'")
    return DISTANCE_TO_METERS[unit]


def segment_in_meters(element: Any, segment: Segment) -> Segment:
    profile_scale = distance_scale(element, "profil steps length")
    profile_length = segment.profil_steps_length * profile_scale
    if segment.kind == "str":
        return replace(segment, length=segment.length * distance_scale(element, "lg"), profil_steps_length=profile_length)
    end_radius_name = "end radius" if find_att(element, "attnum", "end radius") is not None else "end-radius"
    end_radius = None if segment.end_radius is None else segment.end_radius * distance_scale(element, end_radius_name)
    return replace(
        segment,
        radius=segment.radius * distance_scale(element, "radius"),
        end_radius=end_radius,
        profil_steps_length=profile_length,
    )


def track_segments(root: Any) -> list[Segment]:
    main_track = child_section(root, "Main Track")
    if main_track is None:
        raise SystemExit("Track XML has no Main Track section")
    elements = child_section(main_track, "Track Segments")
    if elements is None:
        elements = child_section(main_track, "segments")
    if elements is None:
        raise SystemExit("Track XML has no Main Track/Track Segments or legacy segments section")
    segments = []
    for element in elements:
        if element.tag != "section":
            continue
        segment = segment_from_element(element)
        if segment is not None:
            segments.append(segment_in_meters(element, segment))
    return segments


def sample_map_segments(segments: list[Segment], step: float) -> list[Sample]:
    pose = Pose(0.0, 0.0, 0.0)
    station = 0.0
    samples = [Sample(pose.x, pose.y, station, pose.heading, "start")]
    for segment in segments:
        if segment.kind == "str":
            count = max(1, math.ceil(segment.length / step))
            distance = segment.length / count
            for _ in range(count):
                pose = advance_straight(pose, distance)
                station += distance
                samples.append(Sample(pose.x, pose.y, station, pose.heading, segment.name))
            continue

        start_heading = pose.heading
        arc_rad = math.radians(segment.arc_deg)
        end_radius = segment.radius if segment.end_radius is None else segment.end_radius
        length = turn_length(segment.radius, arc_rad, end_radius)
        geometry_steps = torcs_step_count(length, segment.profil_steps_length)
        step_length, radius_delta = variable_turn_step_length(segment.radius, end_radius, arc_rad, geometry_steps)
        radius = segment.radius
        for _ in range(geometry_steps):
            drawing_steps = max(1, math.ceil(step_length / step))
            distance = step_length / drawing_steps
            for _ in range(drawing_steps):
                pose = advance_constant_turn(pose, segment.kind, radius, distance / radius)
                station += distance
                samples.append(Sample(pose.x, pose.y, station, pose.heading, segment.name))
            radius += radius_delta
        final_heading = start_heading + arc_rad * (1.0 if segment.kind == "lft" else -1.0)
        pose = Pose(pose.x, pose.y, final_heading)
        last = samples[-1]
        samples[-1] = Sample(last.x, last.y, last.s, final_heading, last.segment)
    return samples


def fit_map(points: list[Point], marker: tuple[Point, ...], size: int, margin: float,
            road_width: float, outline_width: float) -> tuple[tuple[Point, ...], tuple[Point, ...]]:
    """Fit the stroked road and fixed-pixel marker together, preserving aspect ratio."""
    start_x, start_y = points[0]
    image_points = [(x - start_x, start_y - y) for x, y in points]
    min_x = min(x for x, y in image_points)
    max_x = max(x for x, y in image_points)
    min_y = min(y for x, y in image_points)
    max_y = max(y for x, y in image_points)
    extent = max(max_x - min_x, max_y - min_y)
    if extent <= 1e-9:
        raise SystemExit("Track map geometry has zero extent")
    radius = road_width * 0.5
    outline = outline_width * 0.5
    marker_bounds = (min(x for x, y in marker) - outline, min(y for x, y in marker) - outline,
                     max(x for x, y in marker) + outline, max(y for x, y in marker) + outline)

    def bounds(scale: float) -> tuple[float, float, float, float]:
        return (min(min_x * scale - radius, marker_bounds[0]),
                min(min_y * scale - radius, marker_bounds[1]),
                max(max_x * scale + radius, marker_bounds[2]),
                max(max_y * scale + radius, marker_bounds[3]))

    # Reserve the Lanczos filter footprint as well as the requested visible gap.
    available = size - 2.0 * (margin + 3.0)
    left, top, right, bottom = bounds(0.0)
    if max(right - left, bottom - top) >= available:
        raise SystemExit("--margin leaves no room for the track and its markers")
    low, high = 0.0, available / extent
    # Only extrema are evaluated here; the sampled track is transformed once.
    for _ in range(60):
        scale = (low + high) * 0.5
        left, top, right, bottom = bounds(scale)
        if max(right - left, bottom - top) <= available:
            low = scale
        else:
            high = scale
    left, top, right, bottom = bounds(low)
    offset_x = (size - left - right) * 0.5
    offset_y = (size - top - bottom) * 0.5
    return (tuple((x * low + offset_x, y * low + offset_y) for x, y in image_points),
            tuple((x + offset_x, y + offset_y) for x, y in marker))


def validate_render_settings(size: int, margin: float | None, sample_step: float) -> float:
    if size < 64 or size > MAX_MAP_SIZE or size & (size - 1):
        raise SystemExit(f"--size must be a power of two from 64 through {MAX_MAP_SIZE}")
    if margin is None:
        margin = max(2.0, size / 128.0)
    if not math.isfinite(margin) or margin < 0.0 or margin * 2.0 >= size:
        raise SystemExit("--margin must be non-negative and less than half of --size")
    if not math.isfinite(sample_step) or sample_step <= 0.0:
        raise SystemExit("--sample-step must be positive")
    return margin


def build_scene(root: Any, size: int = 1024, margin: float | None = None, sample_step: float = 2.0) -> TrackMapScene:
    margin = validate_render_settings(size, margin, sample_step)

    segments = track_segments(root)
    if not segments:
        raise SystemExit("Track XML has no drawable str/lft/rgt segments")
    samples = sample_map_segments(segments, sample_step)
    world_points = [(sample.x, sample.y) for sample in samples]
    if len(world_points) < 2:
        raise SystemExit("Track XML produced fewer than two map points")
    closure_gap = math.hypot(world_points[-1][0] - world_points[0][0], world_points[-1][1] - world_points[0][1])
    maximum_gap = max(1.0, samples[-1].s * 0.002)
    if closure_gap > maximum_gap:
        raise SystemExit(f"Track XML centerline is not closed: gap {closure_gap:.3f} m exceeds {maximum_gap:.3f} m")
    world_points.append(world_points[0])
    road_width = max(4.0, size * 0.014)
    marker_outline_width = max(1.0, size * 0.0035)
    # One silhouette: cross-track bar, left-side elbow, and filled arrowhead.
    # Local x points forward; local y points left (up in image coordinates).
    half_stem = road_width * 0.275
    elbow = road_width * 1.5
    head_base = road_width * 1.2
    head_tip = road_width * 2.85
    head_half_width = road_width * 0.45
    local_marker = (
        (-half_stem, -road_width),
        (half_stem, -road_width),
        (half_stem, elbow - half_stem),
        (head_base, elbow - half_stem),
        (head_base, elbow - head_half_width),
        (head_tip, elbow),
        (head_base, elbow + head_half_width),
        (head_base, elbow + half_stem),
        (-half_stem, elbow + half_stem),
    )
    # Use the exact starting heading, including when the first segment is curved.
    tangent = (math.cos(samples[0].heading), -math.sin(samples[0].heading))
    normal = (tangent[1], -tangent[0])
    marker = tuple(
        (tangent[0] * x + normal[0] * y, tangent[1] * x + normal[1] * y)
        for x, y in local_marker
    )
    points, start_marker = fit_map(world_points, marker, size, margin, road_width, marker_outline_width)
    return TrackMapScene(
        size=size,
        track=tuple(points),
        start_marker=start_marker,
        road_width=road_width,
        marker_outline_width=marker_outline_width,
    )


def scene_from_xml(track_xml: pathlib.Path, size: int = 1024, margin: float | None = None, sample_step: float = 2.0) -> TrackMapScene:
    tree = parse_xml_readonly(track_xml)
    root = tree.getroot()
    if root is None:
        raise SystemExit(f"Track XML has no root element: {track_xml}")
    return build_scene(root, size=size, margin=margin, sample_step=sample_step)


def scaled_scene(scene: TrackMapScene, scale: int) -> TrackMapScene:
    def scaled_points(points: tuple[Point, ...]) -> tuple[Point, ...]:
        return tuple((x * scale, y * scale) for x, y in points)

    return TrackMapScene(
        size=scene.size * scale,
        track=scaled_points(scene.track),
        start_marker=scaled_points(scene.start_marker),
        road_width=scene.road_width * scale,
        marker_outline_width=scene.marker_outline_width * scale,
    )


def render_png(scene: TrackMapScene, output: pathlib.Path) -> None:
    supersample = 4
    rendered = scaled_scene(scene, supersample)
    image = Image.new("RGBA", (rendered.size, rendered.size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    road_width = round(rendered.road_width)
    road_radius = road_width * 0.5
    draw.line(rendered.track, fill=(255, 255, 255, 255), width=road_width)
    # Pillow can leave tiny triangular holes at densely sampled polyline joins.
    # Overlapping round caps make the menu stroke a single sealed shape.
    for x, y in rendered.track:
        draw.ellipse((x - road_radius, y - road_radius, x + road_radius, y + road_radius), fill=(255, 255, 255, 255))
    # Draw the outline first, then fill the entire silhouette to avoid seams.
    outline_width = round(rendered.marker_outline_width)
    draw.line(rendered.start_marker + (rendered.start_marker[0],), fill=(17, 17, 17, 220), width=outline_width, joint="curve")
    outline_radius = outline_width * 0.5
    for x, y in rendered.start_marker:
        draw.ellipse((x - outline_radius, y - outline_radius, x + outline_radius, y + outline_radius), fill=(17, 17, 17, 220))
    draw.polygon(rendered.start_marker, fill=(255, 255, 255, 255))
    image = image.resize((scene.size, scene.size), Image.Resampling.LANCZOS)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")


def svg_points(points: tuple[Point, ...]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def render_svg(scene: TrackMapScene, output: pathlib.Path) -> None:
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{scene.size}" height="{scene.size}" viewBox="0 0 {scene.size} {scene.size}">
  <rect id="background" width="100%" height="100%" fill="#111111"/>
  <polyline id="track" points="{svg_points(scene.track)}" fill="none" stroke="#ffffff" stroke-width="{scene.road_width:.2f}" stroke-linecap="round" stroke-linejoin="round"/>
  <g id="start-marker">
    <polygon points="{svg_points(scene.start_marker)}" fill="none" stroke="#111111" stroke-opacity="0.86" stroke-width="{scene.marker_outline_width:.2f}" stroke-linejoin="round"/>
    <polygon points="{svg_points(scene.start_marker)}" fill="#ffffff"/>
  </g>
</svg>
'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
