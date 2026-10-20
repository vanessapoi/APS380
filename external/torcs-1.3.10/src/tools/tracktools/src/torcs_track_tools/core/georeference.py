# /***************************************************************************
#
#     file                 : georeference.py
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

"""Control-point and loop helpers for centerline georeferencing."""

from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True)
class SimilarityTransform:
    rotation_rad: float
    scale: float
    offset_x: float
    offset_y: float

    @property
    def cosine(self) -> float:
        return math.cos(self.rotation_rad)

    @property
    def sine(self) -> float:
        return math.sin(self.rotation_rad)


def distance(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def closed_length(points: list[Point]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(distance(a, b) for a, b in zip(points, points[1:] + points[:1], strict=True))


def signed_area(points: list[Point]) -> float:
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1], strict=True))


def transform_point(point: Point, fit: SimilarityTransform) -> Point:
    x, y = point
    return (
        fit.scale * (fit.cosine * x - fit.sine * y) + fit.offset_x,
        fit.scale * (fit.sine * x + fit.cosine * y) + fit.offset_y,
    )


def fit_similarity(source: list[Point], target: list[Point], allow_scale: bool) -> SimilarityTransform:
    if len(source) != len(target) or len(source) < 2:
        raise ValueError("Alignment needs matching source/reference control points")
    source_x = sum(point[0] for point in source) / len(source)
    source_y = sum(point[1] for point in source) / len(source)
    target_x = sum(point[0] for point in target) / len(target)
    target_y = sum(point[1] for point in target) / len(target)
    dot = 0.0
    cross = 0.0
    variance = 0.0
    for source_point, target_point in zip(source, target, strict=True):
        sx = source_point[0] - source_x
        sy = source_point[1] - source_y
        tx = target_point[0] - target_x
        ty = target_point[1] - target_y
        dot += sx * tx + sy * ty
        cross += sx * ty - sy * tx
        variance += sx * sx + sy * sy
    if variance <= 1e-12:
        raise ValueError("Source control points have no usable spatial spread")
    rotation = math.atan2(cross, dot)
    scale = math.hypot(dot, cross) / variance if allow_scale else 1.0
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("Alignment produced an invalid scale")
    cosine = math.cos(rotation)
    sine = math.sin(rotation)
    offset_x = target_x - scale * (cosine * source_x - sine * source_y)
    offset_y = target_y - scale * (sine * source_x + cosine * source_y)
    return SimilarityTransform(rotation, scale, offset_x, offset_y)


def project_to_closed_loop(point: Point, loop: list[Point]) -> tuple[Point, float, int, float]:
    if len(loop) < 2:
        raise ValueError("Cannot project onto a loop with fewer than two points")
    best: tuple[Point, float, int, float] | None = None
    for index, (start, end) in enumerate(zip(loop, loop[1:] + loop[:1], strict=True)):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length_squared = dx * dx + dy * dy
        amount = 0.0 if length_squared <= 1e-18 else max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared))
        projected = start[0] + amount * dx, start[1] + amount * dy
        candidate = projected, distance(point, projected), index, amount
        if best is None or candidate[1] < best[1]:
            best = candidate
    if best is None:
        raise ValueError("Could not project control point onto centerline")
    return best


def resample_closed(points: list[Point], count: int) -> list[Point]:
    if len(points) < 3 or count < 3:
        raise ValueError("Closed-loop resampling needs at least three points")
    lengths = [distance(a, b) for a, b in zip(points, points[1:] + points[:1], strict=True)]
    total = sum(lengths)
    if total <= 1e-9:
        raise ValueError("Cannot resample a zero-length loop")
    output: list[Point] = []
    segment = 0
    segment_start = 0.0
    for sample_index in range(count):
        station = total * sample_index / count
        while segment < len(lengths) - 1 and station > segment_start + lengths[segment]:
            segment_start += lengths[segment]
            segment += 1
        start = points[segment]
        end = points[(segment + 1) % len(points)]
        amount = 0.0 if lengths[segment] <= 1e-12 else (station - segment_start) / lengths[segment]
        output.append((start[0] + amount * (end[0] - start[0]), start[1] + amount * (end[1] - start[1])))
    return output


def residuals(source: list[Point], target: list[Point], fit: SimilarityTransform) -> list[float]:
    return [distance(transform_point(source_point, fit), target_point) for source_point, target_point in zip(source, target, strict=True)]


def convex_hull(points: list[Point]) -> list[Point]:
    unique = sorted(set(points))
    if len(unique) <= 2:
        return unique

    def cross(origin: Point, a: Point, b: Point) -> float:
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])

    lower: list[Point] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper: list[Point] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def control_distribution(controls: list[Point], loop: list[Point]) -> dict:
    loop_min_x = min(point[0] for point in loop)
    loop_max_x = max(point[0] for point in loop)
    loop_min_y = min(point[1] for point in loop)
    loop_max_y = max(point[1] for point in loop)
    diagonal = math.hypot(loop_max_x - loop_min_x, loop_max_y - loop_min_y)
    span = max((distance(a, b) for index, a in enumerate(controls) for b in controls[index + 1 :]), default=0.0)
    hull = convex_hull(controls)
    hull_area = abs(signed_area(hull)) if len(hull) >= 3 else 0.0
    box_area = max(1e-12, (loop_max_x - loop_min_x) * (loop_max_y - loop_min_y))
    return {
        "span_m": span,
        "span_ratio": span / diagonal if diagonal > 1e-12 else 0.0,
        "hull_area_m2": hull_area,
        "hull_area_ratio": hull_area / box_area,
    }
