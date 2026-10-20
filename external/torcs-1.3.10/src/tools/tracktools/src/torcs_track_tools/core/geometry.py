#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : geometry.py
#     created              : 01 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""TORCS v4 2D segment geometry helpers for tracktools.

This module intentionally mirrors the position/heading stepping used by the
TORCS v4 track loader closely enough for fitting and overlay diagnostics. It is
kept independent from the legacy fitters so new tools can share one geometry
model instead of each command carrying a subtly different approximation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MAX_TORCS_RADIUS_M = 4000.0


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    heading: float


@dataclass(frozen=True)
class Segment:
    name: str
    kind: str
    length: float = 0.0
    radius: float = 0.0
    arc_deg: float = 0.0
    end_radius: float | None = None
    profil_steps_length: float = 6.0


@dataclass(frozen=True)
class Sample:
    x: float
    y: float
    s: float
    heading: float
    segment: str


@dataclass(frozen=True)
class CurvatureSample:
    x: float
    y: float
    s: float
    heading: float
    curvature: float
    radius: float


def turn_length(radius: float, arc_rad: float, end_radius: float | None = None) -> float:
    radius_end = radius if end_radius is None else end_radius
    return 0.5 * (radius + radius_end) * abs(arc_rad)


def torcs_step_count(length: float, profil_steps_length: float) -> int:
    if profil_steps_length <= 0.0:
        return 1
    return max(1, int(length / profil_steps_length) + 1)


def advance_straight(pose: Pose, length: float) -> Pose:
    return Pose(
        pose.x + length * math.cos(pose.heading),
        pose.y + length * math.sin(pose.heading),
        pose.heading,
    )


def advance_constant_turn(pose: Pose, kind: str, radius: float, arc_rad: float) -> Pose:
    sign = 1.0 if kind == "lft" else -1.0
    cx = pose.x - sign * radius * math.sin(pose.heading)
    cy = pose.y + sign * radius * math.cos(pose.heading)
    heading = pose.heading + sign * arc_rad
    return Pose(
        cx + sign * radius * math.sin(heading),
        cy - sign * radius * math.cos(heading),
        heading,
    )


def variable_turn_step_length(radius: float, end_radius: float, arc_rad: float, steps: int) -> tuple[float, float]:
    length = turn_length(radius, arc_rad, end_radius)
    cur_length = length / steps
    dradius = 0.0 if steps == 1 else (end_radius - radius) / (steps - 1)
    if steps != 1 and abs(end_radius - radius) > 1e-12:
        tmp_angle = 0.0
        tmp_radius = radius
        for _ in range(steps):
            tmp_angle += cur_length / tmp_radius
            tmp_radius += dradius
        if abs(tmp_angle) > 1e-12:
            cur_length *= abs(arc_rad) / tmp_angle
    return cur_length, dradius


def advance_variable_turn(pose: Pose, kind: str, radius: float, end_radius: float, arc_rad: float, steps: int) -> Pose:
    sign = 1.0 if kind == "lft" else -1.0
    cur_length, dradius = variable_turn_step_length(radius, end_radius, arc_rad, steps)
    out = pose
    cur_radius = radius
    for _ in range(steps):
        out = advance_constant_turn(out, kind, cur_radius, cur_length / cur_radius)
        cur_radius += dradius
    # Match the requested final heading exactly; TORCS stepping is numerically
    # very close, but downstream closure code should not accumulate test noise.
    return Pose(out.x, out.y, pose.heading + sign * abs(arc_rad))


def advance_segment(pose: Pose, segment: Segment) -> Pose:
    if segment.kind == "str":
        return advance_straight(pose, segment.length)
    if segment.kind not in ("lft", "rgt"):
        raise ValueError(f"Unsupported segment kind: {segment.kind}")
    arc_rad = math.radians(segment.arc_deg)
    end_radius = segment.radius if segment.end_radius is None else segment.end_radius
    if abs(end_radius - segment.radius) <= 1e-12:
        return advance_constant_turn(pose, segment.kind, segment.radius, arc_rad)
    steps = torcs_step_count(turn_length(segment.radius, arc_rad, end_radius), segment.profil_steps_length)
    return advance_variable_turn(pose, segment.kind, segment.radius, end_radius, arc_rad, steps)


def sample_segment(pose: Pose, segment: Segment, start_s: float = 0.0, step: float = 3.0) -> tuple[Pose, list[Sample]]:
    samples: list[Sample] = []
    if segment.kind == "str":
        count = max(1, int(segment.length / max(1e-6, step)) + 1)
        ds = segment.length / count
        out = pose
        s = start_s
        for _ in range(count):
            out = advance_straight(out, ds)
            s += ds
            samples.append(Sample(out.x, out.y, s, out.heading, segment.name))
        return out, samples

    arc_rad = math.radians(segment.arc_deg)
    end_radius = segment.radius if segment.end_radius is None else segment.end_radius
    length = turn_length(segment.radius, arc_rad, end_radius)
    count = torcs_step_count(length, segment.profil_steps_length)
    if abs(end_radius - segment.radius) <= 1e-12:
        cur_arc = arc_rad / count
        cur_length = segment.radius * cur_arc
        out = pose
        s = start_s
        for _ in range(count):
            out = advance_constant_turn(out, segment.kind, segment.radius, cur_arc)
            s += cur_length
            samples.append(Sample(out.x, out.y, s, out.heading, segment.name))
        return out, samples

    cur_length, dradius = variable_turn_step_length(segment.radius, end_radius, arc_rad, count)
    out = pose
    s = start_s
    cur_radius = segment.radius
    for _ in range(count):
        out = advance_constant_turn(out, segment.kind, cur_radius, cur_length / cur_radius)
        s += cur_length
        samples.append(Sample(out.x, out.y, s, out.heading, segment.name))
        cur_radius += dradius
    return Pose(out.x, out.y, pose.heading + (1.0 if segment.kind == "lft" else -1.0) * abs(arc_rad)), samples


def sample_segments(segments: list[Segment], start_pose: Pose | None = None, step: float = 3.0) -> list[Sample]:
    pose = start_pose or Pose(0.0, 0.0, 0.0)
    s = 0.0
    samples = [Sample(pose.x, pose.y, s, pose.heading, "start")]
    for segment in segments:
        pose, segment_samples = sample_segment(pose, segment, s, step)
        if segment_samples:
            s = segment_samples[-1].s
            samples.extend(segment_samples)
    return samples


def segment_to_point(pose: Pose, x: float, y: float, name: str, lateral_epsilon: float = 1e-6) -> Segment | None:
    dx = x - pose.x
    dy = y - pose.y
    local_x = dx * math.cos(pose.heading) + dy * math.sin(pose.heading)
    local_y = -dx * math.sin(pose.heading) + dy * math.cos(pose.heading)
    if local_x <= 1e-9:
        return None
    if abs(local_y) <= lateral_epsilon:
        return Segment(name, "str", length=local_x)
    kind = "lft" if local_y > 0.0 else "rgt"
    lateral = abs(local_y)
    radius = (local_x * local_x + lateral * lateral) / (2.0 * lateral)
    arc = math.degrees(math.atan2(local_x, max(1e-12, radius - lateral)))
    if radius <= 1e-9 or arc <= 1e-9 or arc >= 180.0:
        return None
    return Segment(name, kind, radius=radius, arc_deg=arc)


def pose_to_pose_arc(start: Pose, end: Pose, name: str, tolerance: float = 1e-5) -> Segment | None:
    dx = end.x - start.x
    dy = end.y - start.y
    local_x = dx * math.cos(start.heading) + dy * math.sin(start.heading)
    local_y = -dx * math.sin(start.heading) + dy * math.cos(start.heading)
    turn = normalize_angle(end.heading - start.heading)
    turn_abs = abs(turn)
    if turn_abs <= 1e-8:
        if abs(local_y) > tolerance or local_x < -tolerance:
            return None
        return Segment(name, "str", length=max(0.0, local_x))
    if local_x <= 1e-9 or turn_abs >= math.pi - 1e-9:
        return None
    sign = 1.0 if turn > 0.0 else -1.0
    sx = math.sin(turn_abs)
    sy = 1.0 - math.cos(turn_abs)
    if abs(sx) <= 1e-12 or abs(sy) <= 1e-12:
        return None
    radius_x = local_x / sx
    radius_y = sign * local_y / sy
    if radius_x <= 1e-9 or radius_y <= 1e-9:
        return None
    radius = 0.5 * (radius_x + radius_y)
    if abs(radius_x - radius_y) > tolerance * max(1.0, radius):
        return None
    return Segment(name, "lft" if turn > 0.0 else "rgt", radius=radius, arc_deg=math.degrees(turn_abs))


def variable_turn_seed_values(seeds: list[tuple[float, float]] | None, base_radius: float) -> list[tuple[float, float]]:
    seed_values = list(seeds or [])
    seed_values.extend(
        [
            (base_radius * 0.5, base_radius * 2.0),
            (base_radius * 2.0, base_radius * 0.5),
            (base_radius * 0.75, base_radius * 1.5),
            (base_radius * 1.5, base_radius * 0.75),
            (base_radius * 0.35, base_radius * 3.0),
            (base_radius * 3.0, base_radius * 0.35),
        ]
    )
    return seed_values


def clamp_log_radius(value: float, log_min: float, log_max: float) -> float:
    return max(log_min, min(log_max, value))


def variable_turn_endpoint_error(
    start: Pose,
    end: Pose,
    kind: str,
    turn_abs: float,
    log_min: float,
    log_max: float,
    log_r0: float,
    log_r1: float,
) -> tuple[float, float]:
    radius = math.exp(clamp_log_radius(log_r0, log_min, log_max))
    end_radius = math.exp(clamp_log_radius(log_r1, log_min, log_max))
    pose = advance_segment(start, Segment("candidate", kind, radius=radius, end_radius=end_radius, arc_deg=math.degrees(turn_abs)))
    return pose.x - end.x, pose.y - end.y


def variable_turn_newton_delta(endpoint_error, log_r0: float, log_r1: float, err_x: float, err_y: float) -> tuple[float, float] | None:  # noqa: ANN001
    eps = 1e-4
    err_x0, err_y0 = endpoint_error(log_r0 + eps, log_r1)
    err_x1, err_y1 = endpoint_error(log_r0, log_r1 + eps)
    j00 = (err_x0 - err_x) / eps
    j10 = (err_y0 - err_y) / eps
    j01 = (err_x1 - err_x) / eps
    j11 = (err_y1 - err_y) / eps
    det = j00 * j11 - j01 * j10
    if abs(det) <= 1e-12:
        return None
    delta0 = max(-0.75, min(0.75, (j11 * err_x - j01 * err_y) / det))
    delta1 = max(-0.75, min(0.75, (-j10 * err_x + j00 * err_y) / det))
    return delta0, delta1


def refine_variable_turn_logs(endpoint_error, log_r0: float, log_r1: float, log_min: float, log_max: float, endpoint_tolerance: float) -> tuple[float, float]:  # noqa: ANN001
    best_err = math.inf
    for _ in range(10):
        err_x, err_y = endpoint_error(log_r0, log_r1)
        err = math.hypot(err_x, err_y)
        if err < endpoint_tolerance:
            break
        if err >= best_err * 1.5:
            break
        best_err = min(best_err, err)
        delta = variable_turn_newton_delta(endpoint_error, log_r0, log_r1, err_x, err_y)
        if delta is None:
            break
        log_r0 = clamp_log_radius(log_r0 - delta[0], log_min, log_max)
        log_r1 = clamp_log_radius(log_r1 - delta[1], log_min, log_max)
    return log_r0, log_r1


def variable_turn_candidate_params(endpoint_error, log_r0: float, log_r1: float, turn_abs: float, endpoint_tolerance: float) -> tuple[float, float, tuple[int, int, int]] | None:  # noqa: ANN001
    err_x, err_y = endpoint_error(log_r0, log_r1)
    if math.hypot(err_x, err_y) > endpoint_tolerance:
        return None
    radius = math.exp(log_r0)
    end_radius = math.exp(log_r1)
    if max(radius, end_radius) / max(min(radius, end_radius), 1e-9) < 1.05:
        return None
    key = (round(radius * 100.0), round(end_radius * 100.0), round(math.degrees(turn_abs) * 1000.0))
    return radius, end_radius, key


def variable_pose_to_pose_turn_candidates(
    start: Pose,
    end: Pose,
    name_prefix: str = "var",
    seeds: list[tuple[float, float]] | None = None,
    min_radius: float = 2.0,
    max_radius: float = MAX_TORCS_RADIUS_M,
    endpoint_tolerance: float = 0.05,
) -> list[Segment]:
    turn = normalize_angle(end.heading - start.heading)
    turn_abs = abs(turn)
    if turn_abs <= math.radians(0.25) or turn_abs >= math.pi - 1e-9:
        return []

    chord = math.hypot(end.x - start.x, end.y - start.y)
    if chord <= 1e-6:
        return []
    base_radius = max(min_radius, min(max_radius, chord / max(1e-6, 2.0 * math.sin(0.5 * turn_abs))))
    seed_values = variable_turn_seed_values(seeds, base_radius)

    kind = "lft" if turn > 0.0 else "rgt"
    log_min = math.log(min_radius)
    log_max = math.log(max_radius)
    candidates: list[Segment] = []
    seen: set[tuple[int, int, int]] = set()

    def endpoint_error(log_r0: float, log_r1: float) -> tuple[float, float]:
        return variable_turn_endpoint_error(start, end, kind, turn_abs, log_min, log_max, log_r0, log_r1)

    for seed_radius, seed_end_radius in seed_values:
        if seed_radius <= 0.0 or seed_end_radius <= 0.0:
            continue
        log_r0 = clamp_log_radius(math.log(seed_radius), log_min, log_max)
        log_r1 = clamp_log_radius(math.log(seed_end_radius), log_min, log_max)
        log_r0, log_r1 = refine_variable_turn_logs(endpoint_error, log_r0, log_r1, log_min, log_max, endpoint_tolerance)
        params = variable_turn_candidate_params(endpoint_error, log_r0, log_r1, turn_abs, endpoint_tolerance)
        if params is None:
            continue
        radius, end_radius, key = params
        if key in seen:
            continue
        seen.add(key)
        candidates.append(Segment(f"{name_prefix}-{len(candidates) + 1}", kind, radius=radius, end_radius=end_radius, arc_deg=math.degrees(turn_abs)))
    return candidates


def biarc_segments_for_distance(start: Pose, end: Pose, d: float, name_prefix: str) -> list[Segment] | None:
    if d <= 0.0:
        return None
    t1 = (math.cos(start.heading), math.sin(start.heading))
    t2 = (math.cos(end.heading), math.sin(end.heading))
    mid_x = 0.5 * (start.x + end.x + d * (t1[0] - t2[0]))
    mid_y = 0.5 * (start.y + end.y + d * (t1[1] - t2[1]))
    first = segment_to_point(start, mid_x, mid_y, f"{name_prefix}-1")
    if first is None:
        return None
    mid_pose = advance_segment(start, first)
    second = pose_to_pose_arc(mid_pose, end, f"{name_prefix}-2")
    if second is None:
        return None
    return [seg for seg in (first, second) if segment_length_like(seg) > 1e-8]


def biarc_segment_candidates(start: Pose, end: Pose, name_prefix: str = "biarc") -> list[list[Segment]]:
    t1 = (math.cos(start.heading), math.sin(start.heading))
    t2 = (math.cos(end.heading), math.sin(end.heading))
    vx = end.x - start.x
    vy = end.y - start.y
    vdotv = vx * vx + vy * vy
    if vdotv <= 1e-12:
        return []

    tdot = t1[0] * t2[0] + t1[1] * t2[1]
    vdot_t = vx * (t1[0] + t2[0]) + vy * (t1[1] + t2[1])
    denominator = 2.0 * (1.0 - tdot)
    distances = []
    if abs(denominator) <= 1e-12:
        vdot_t2 = vx * t2[0] + vy * t2[1]
        if abs(vdot_t2) <= 1e-12:
            return []
        distances.append(vdotv / (4.0 * vdot_t2))
    else:
        discriminant = vdot_t * vdot_t + denominator * vdotv
        if discriminant < 0.0:
            return []
        root = math.sqrt(discriminant)
        distances.extend([(-vdot_t + root) / denominator, (-vdot_t - root) / denominator])

    candidates = []
    seen: set[tuple[tuple[str, int, int], ...]] = set()
    for d in distances:
        segments = biarc_segments_for_distance(start, end, d, name_prefix)
        if not segments:
            continue
        key = tuple((segment.kind, round(segment.radius * 1000.0), round(segment.arc_deg * 1000.0)) for segment in segments)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(segments)
    return candidates


def biarc_segments(start: Pose, end: Pose, name_prefix: str = "biarc") -> list[Segment] | None:
    candidates = biarc_segment_candidates(start, end, name_prefix)
    return candidates[0] if candidates else None


def segment_length_like(segment: Segment) -> float:
    if segment.kind == "str":
        return segment.length
    return turn_length(segment.radius, math.radians(segment.arc_deg), segment.end_radius)


def normalize_angle(angle: float) -> float:
    while angle <= -math.pi:
        angle += 2.0 * math.pi
    while angle > math.pi:
        angle -= 2.0 * math.pi
    return angle


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def moving_average(values: list[float], radius: int) -> list[float]:
    if radius <= 0 or len(values) < 2:
        return values[:]
    out = []
    for i in range(len(values)):
        lo = max(0, i - radius)
        hi = min(len(values), i + radius + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def median_filter(values: list[float], radius: int) -> list[float]:
    if radius <= 0 or len(values) < 2:
        return values[:]
    out = []
    for i in range(len(values)):
        lo = max(0, i - radius)
        hi = min(len(values), i + radius + 1)
        out.append(median(values[lo:hi]))
    return out


def circular_moving_average(values: list[float], radius: int) -> list[float]:
    if radius <= 0 or len(values) < 2:
        return values[:]
    count = len(values)
    return [sum(values[(i + j) % count] for j in range(-radius, radius + 1)) / (2 * radius + 1) for i in range(count)]


def circular_median_filter(values: list[float], radius: int) -> list[float]:
    if radius <= 0 or len(values) < 2:
        return values[:]
    count = len(values)
    return [median([values[(i + j) % count] for j in range(-radius, radius + 1)]) for i in range(count)]


def closed_endpoint_distance(points: list[dict]) -> float:
    return math.hypot(points[0]["x"] - points[-1]["x"], points[0]["y"] - points[-1]["y"])


def circular_curvature_profile(points: list[dict], window: int, median_radius: int, smooth_radius: int, deadband: float) -> list[CurvatureSample]:
    unique = points[:-1]
    count = len(unique)
    s = [0.0]
    for i in range(1, count):
        s.append(s[-1] + math.hypot(unique[i]["x"] - unique[i - 1]["x"], unique[i]["y"] - unique[i - 1]["y"]))
    total = s[-1] + math.hypot(unique[0]["x"] - unique[-1]["x"], unique[0]["y"] - unique[-1]["y"])

    def point_at(i: int) -> dict:
        return unique[i % count]

    def s_at(i: int) -> float:
        return s[i % count] + (i // count) * total

    ext_start = -window
    ext_end = count + window
    headings = []
    for i in range(ext_start, ext_end):
        a = point_at(i - window)
        b = point_at(i + window)
        headings.append(math.atan2(b["y"] - a["y"], b["x"] - a["x"]))

    unwrapped = [headings[0]]
    for h in headings[1:]:
        unwrapped.append(unwrapped[-1] + normalize_angle(h - unwrapped[-1]))

    def ext_index(i: int) -> int:
        return i - ext_start

    curvatures = []
    center_headings = []
    for i in range(count):
        a = i - window
        b = i + window
        ds = s_at(b) - s_at(a)
        center_headings.append(unwrapped[ext_index(i)])
        curvatures.append(0.0 if ds <= 1e-9 else (unwrapped[ext_index(b)] - unwrapped[ext_index(a)]) / ds)
    curvatures = circular_moving_average(circular_median_filter(curvatures, median_radius), smooth_radius)

    out = []
    for i, k in enumerate(curvatures):
        if abs(k) < deadband:
            k = 0.0
        radius = math.inf if abs(k) <= 1e-12 else 1.0 / abs(k)
        out.append(CurvatureSample(unique[i]["x"], unique[i]["y"], s[i], center_headings[i], k, radius))
    out.append(CurvatureSample(unique[0]["x"], unique[0]["y"], total, center_headings[0], out[0].curvature, out[0].radius))
    return out


def cumulative_distances(points: list[dict]) -> list[float]:
    s = [0.0]
    for i in range(1, len(points)):
        s.append(s[-1] + math.hypot(points[i]["x"] - points[i - 1]["x"], points[i]["y"] - points[i - 1]["y"]))
    return s


def open_curve_headings(points: list[dict], window: int) -> list[float]:
    headings = []
    count = len(points)
    for i in range(count):
        a = max(0, i - window)
        b = min(count - 1, i + window)
        if a == b:
            headings.append(headings[-1] if headings else 0.0)
        else:
            headings.append(math.atan2(points[b]["y"] - points[a]["y"], points[b]["x"] - points[a]["x"]))
    return headings


def unwrap_headings(headings: list[float]) -> list[float]:
    unwrapped = [headings[0]]
    for h in headings[1:]:
        unwrapped.append(unwrapped[-1] + normalize_angle(h - unwrapped[-1]))
    return unwrapped


def open_curvature_values(stations: list[float], unwrapped: list[float], window: int) -> list[float]:
    curvature = []
    count = len(stations)
    for i in range(count):
        a = max(0, i - window)
        b = min(count - 1, i + window)
        ds = stations[b] - stations[a]
        curvature.append(0.0 if ds <= 1e-9 else (unwrapped[b] - unwrapped[a]) / ds)
    return curvature


def curvature_samples(points: list[dict], stations: list[float], headings: list[float], curvatures: list[float], deadband: float) -> list[CurvatureSample]:
    out = []
    for i, k in enumerate(curvatures):
        if abs(k) < deadband:
            k = 0.0
        radius = math.inf if abs(k) <= 1e-12 else 1.0 / abs(k)
        out.append(CurvatureSample(points[i]["x"], points[i]["y"], stations[i], headings[i], k, radius))
    return out


def curvature_profile(points: list[dict], window: int = 3, median_radius: int = 2, smooth_radius: int = 2, deadband: float = 1.0 / 2000.0) -> list[CurvatureSample]:
    if len(points) < 3:
        return []
    if len(points) >= 4 and closed_endpoint_distance(points) <= 1e-9:
        return circular_curvature_profile(points, window, median_radius, smooth_radius, deadband)
    s = cumulative_distances(points)
    unwrapped = unwrap_headings(open_curve_headings(points, window))
    curvature = open_curvature_values(s, unwrapped, window)
    curvature = moving_average(median_filter(curvature, median_radius), smooth_radius)
    return curvature_samples(points, s, unwrapped, curvature, deadband)
