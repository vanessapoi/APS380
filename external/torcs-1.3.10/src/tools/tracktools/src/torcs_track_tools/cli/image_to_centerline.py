#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : image_to_centerline.py
#     created              : 29 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Extract a closed TORCS centerline source polyline from a raster track map.

The output of this script is deliberately the same lightweight centerline JSON
used by OSM fetchers: an ordered, closed list of local x/y points plus source
metadata.  Later stages do not care whether the source came from OSM, a GPX
file, or an image.

Basic workflow:
1) Select track-line pixels by color/threshold.
2) Keep the largest connected loop and thin/link it into one pixel path.
3) Optionally refine antialiased ridge pixels to subpixel positions.
4) Smooth/resample the closed loop and scale it to the requested real length.
5) Rotate the seam onto a smooth section so fitting does not start at a kink.

The supported profiles encode the useful choices from raster experiments.  The
removed stabilization/upscale/control-spline experiments are intentionally not
kept as normal authoring options because they produced worse accepted tracks.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import pathlib
import sys
import warnings
from collections import deque

from PIL import Image

try:
    import numpy as np
    from skimage import morphology
except ImportError:  # pragma: no cover - dependencies are declared for normal tool use.
    np = None
    morphology = None

Point = tuple[int, int]
FloatPoint = tuple[float, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract a scaled closed centerline JSON from a raster track drawing")
    parser.add_argument(
        "--profile",
        choices=["standard", "clean-map", "antialias-ridge", "skimage-map"],
        default="standard",
        help="Extraction preset; clean-map, antialias-ridge, and skimage-map set stable drawing-map defaults",
    )
    parser.add_argument("--input", required=True, help="Input raster image path")
    parser.add_argument("--output", required=True, help="Output centerline JSON path")
    parser.add_argument("--length-m", type=float, required=True, help="Real closed-loop length in meters")
    parser.add_argument("--preview-svg", default="", help="Optional extraction preview SVG path")
    parser.add_argument(
        "--extractor",
        default="skeleton",
        choices=["skeleton", "ridge", "ridge-link", "skimage-skeleton"],
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--track-color", default="red", choices=["red", "dark", "light", "custom"], help="Pixel selection mode")
    parser.add_argument("--rgb", default="255,0,0", help="Custom RGB color for --track-color custom")
    parser.add_argument("--color-tolerance", type=float, default=90.0, help="RGB Euclidean tolerance for red/custom extraction")
    parser.add_argument("--red-hue-tolerance-deg", type=float, default=15.0, help="Hue tolerance around red for --track-color red")
    parser.add_argument("--min-saturation", type=float, default=0.15, help="Minimum HSV saturation for --track-color red")
    parser.add_argument("--threshold", type=int, default=180, help="Grayscale threshold for dark/light extraction")
    parser.add_argument("--invert", action="store_true", help="Invert grayscale dark/light extraction")
    parser.add_argument("--crop", default="", help="Optional crop rectangle x,y,w,h before extraction")
    parser.add_argument("--close-gap-px", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--max-seam-gap-px", type=float, default=60.0, help=argparse.SUPPRESS)
    parser.add_argument("--min-component-area", type=int, default=100, help=argparse.SUPPRESS)
    parser.add_argument("--ridge-sigma", type=float, default=1.2, help=argparse.SUPPRESS)
    parser.add_argument("--ridge-min-strength", type=float, default=0.03, help=argparse.SUPPRESS)
    parser.add_argument("--ridge-max-offset-px", type=float, default=1.25, help=argparse.SUPPRESS)
    parser.add_argument("--smooth-window", type=int, default=5, help=argparse.SUPPRESS)
    parser.add_argument("--smooth-rounds", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--adaptive-smoothing", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--preserve-curvature-deg", type=float, default=8.0, help=argparse.SUPPRESS)
    parser.add_argument("--curvature-window", type=int, default=4, help=argparse.SUPPRESS)
    parser.add_argument("--resample-step", type=float, default=3.0, help=argparse.SUPPRESS)
    parser.add_argument("--start-window", type=int, default=30, help=argparse.SUPPRESS)
    parser.add_argument("--reverse", action="store_true", help="Reverse extracted driving direction")
    args = parser.parse_args()
    apply_profile_defaults(args)
    return args


def cli_arg_present(name: str) -> bool:
    return any(arg == name or arg.startswith(name + "=") for arg in sys.argv[1:])


def apply_profile_defaults(args: argparse.Namespace) -> None:
    if args.profile == "standard":
        return
    profile_defaults = {
        "clean-map": {
            "--extractor": ("extractor", "skeleton"),
            "--smooth-window": ("smooth_window", 15),
            "--smooth-rounds": ("smooth_rounds", 3),
            "--resample-step": ("resample_step", 2.0),
            "--preserve-curvature-deg": ("preserve_curvature_deg", 8.0),
        },
        "antialias-ridge": {
            "--extractor": ("extractor", "ridge-link"),
            "--ridge-sigma": ("ridge_sigma", 1.2),
            "--ridge-min-strength": ("ridge_min_strength", 0.01),
            "--smooth-window": ("smooth_window", 15),
            "--smooth-rounds": ("smooth_rounds", 3),
            "--resample-step": ("resample_step", 2.0),
            "--preserve-curvature-deg": ("preserve_curvature_deg", 8.0),
        },
        "skimage-map": {
            "--extractor": ("extractor", "skimage-skeleton"),
            "--smooth-window": ("smooth_window", 15),
            "--smooth-rounds": ("smooth_rounds", 3),
            "--resample-step": ("resample_step", 2.0),
            "--preserve-curvature-deg": ("preserve_curvature_deg", 8.0),
        },
    }[args.profile]
    for flag, (attr, value) in profile_defaults.items():
        if not cli_arg_present(flag):
            setattr(args, attr, value)
    if not cli_arg_present("--adaptive-smoothing"):
        args.adaptive_smoothing = True


def parse_crop(value: str) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    parts = [int(p.strip()) for p in value.split(",")]
    if len(parts) != 4:
        raise SystemExit("--crop must be x,y,w,h")
    x, y, w, h = parts
    if w <= 0 or h <= 0:
        raise SystemExit("--crop width and height must be positive")
    return x, y, w, h


def parse_rgb(value: str) -> tuple[int, int, int]:
    parts = [int(p.strip()) for p in value.split(",")]
    if len(parts) != 3 or any(p < 0 or p > 255 for p in parts):
        raise SystemExit("--rgb must be r,g,b with values from 0 to 255")
    return parts[0], parts[1], parts[2]


def rgb_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def gray_value(r: int, g: int, b: int) -> int:
    return int(round(0.299 * r + 0.587 * g + 0.114 * b))


def red_hsv_metrics(r: int, g: int, b: int) -> tuple[float, float, float]:
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    hue_deg = h * 360.0
    return min(hue_deg, 360.0 - hue_deg), s, v


def keep_red_pixel(r: int, g: int, b: int, args: argparse.Namespace) -> bool:
    hue_dist, s, v = red_hsv_metrics(r, g, b)
    return s >= args.min_saturation and v > 0.2 and hue_dist <= args.red_hue_tolerance_deg


def keep_threshold_pixel(r: int, g: int, b: int, args: argparse.Namespace) -> bool:
    gray = gray_value(r, g, b)
    keep = gray < args.threshold if args.track_color == "dark" else gray > args.threshold
    return not keep if args.invert else keep


def keep_track_pixel(r: int, g: int, b: int, target: tuple[int, int, int], args: argparse.Namespace) -> bool:
    if args.track_color == "red":
        return keep_red_pixel(r, g, b, args)
    if args.track_color == "custom":
        return rgb_dist((r, g, b), target) <= args.color_tolerance
    return keep_threshold_pixel(r, g, b, args)


def extract_mask(img: Image.Image, args: argparse.Namespace) -> set[Point]:
    rgb = img.convert("RGB")
    target = (255, 0, 0) if args.track_color == "red" else parse_rgb(args.rgb)
    mask: set[Point] = set()
    for y in range(rgb.height):
        for x in range(rgb.width):
            r, g, b = rgb.getpixel((x, y))
            if keep_track_pixel(r, g, b, target, args):
                mask.add((x, y))
    return mask


def red_pixel_probability(r: int, g: int, b: int, args: argparse.Namespace) -> float:
    hue_dist, s, v = red_hsv_metrics(r, g, b)
    hue_score = max(0.0, 1.0 - hue_dist / max(1e-9, args.red_hue_tolerance_deg))
    sat_score = max(0.0, min(1.0, (s - args.min_saturation) / max(1e-9, 1.0 - args.min_saturation)))
    return hue_score * sat_score * max(0.0, min(1.0, v))


def threshold_pixel_probability(r: int, g: int, b: int, args: argparse.Namespace) -> float:
    gray = gray_value(r, g, b)
    if args.track_color == "dark":
        score = max(0.0, min(1.0, (args.threshold - gray) / max(1.0, args.threshold)))
    else:
        score = max(0.0, min(1.0, (gray - args.threshold) / max(1.0, 255 - args.threshold)))
    return 1.0 - score if args.invert else score


def track_pixel_probability(r: int, g: int, b: int, target: tuple[int, int, int], args: argparse.Namespace) -> float:
    if args.track_color == "red":
        return red_pixel_probability(r, g, b, args)
    if args.track_color == "custom":
        return max(0.0, 1.0 - rgb_dist((r, g, b), target) / max(1e-9, args.color_tolerance))
    return threshold_pixel_probability(r, g, b, args)


def extract_probability(img: Image.Image, args: argparse.Namespace) -> list[list[float]]:
    rgb = img.convert("RGB")
    target = (255, 0, 0) if args.track_color == "red" else parse_rgb(args.rgb)
    out: list[list[float]] = []
    for y in range(rgb.height):
        row: list[float] = []
        for x in range(rgb.width):
            r, g, b = rgb.getpixel((x, y))
            row.append(track_pixel_probability(r, g, b, target, args))
        out.append(row)
    return out


def gaussian_kernel(sigma: float) -> list[float]:
    sigma = max(0.1, sigma)
    radius = max(1, int(math.ceil(sigma * 3.0)))
    values = [math.exp(-(i * i) / (2.0 * sigma * sigma)) for i in range(-radius, radius + 1)]
    total = sum(values)
    return [v / total for v in values]


def gaussian_blur(values: list[list[float]], sigma: float) -> list[list[float]]:
    if not values:
        return []
    kernel = gaussian_kernel(sigma)
    radius = len(kernel) // 2
    h = len(values)
    w = len(values[0])
    tmp = [[0.0 for _ in range(w)] for _ in range(h)]
    out = [[0.0 for _ in range(w)] for _ in range(h)]
    for y in range(h):
        for x in range(w):
            tmp[y][x] = sum(values[y][min(w - 1, max(0, x + k - radius))] * kernel[k] for k in range(len(kernel)))
    for y in range(h):
        for x in range(w):
            out[y][x] = sum(tmp[min(h - 1, max(0, y + k - radius))][x] * kernel[k] for k in range(len(kernel)))
    return out


def steger_offset_at(
    img: list[list[float]],
    x: int,
    y: int,
    min_strength: float,
    max_offset: float,
) -> tuple[float, float, float] | None:
    h = len(img)
    w = len(img[0])
    if x <= 0 or x >= w - 1 or y <= 0 or y >= h - 1:
        return None
    ix = 0.5 * (img[y][x + 1] - img[y][x - 1])
    iy = 0.5 * (img[y + 1][x] - img[y - 1][x])
    ixx = img[y][x + 1] - 2.0 * img[y][x] + img[y][x - 1]
    iyy = img[y + 1][x] - 2.0 * img[y][x] + img[y - 1][x]
    ixy = 0.25 * (img[y + 1][x + 1] - img[y + 1][x - 1] - img[y - 1][x + 1] + img[y - 1][x - 1])
    trace = ixx + iyy
    diff = ixx - iyy
    disc = math.sqrt(max(0.0, diff * diff + 4.0 * ixy * ixy))
    lam1 = 0.5 * (trace + disc)
    lam2 = 0.5 * (trace - disc)
    ridge_lam = lam1 if abs(lam1) >= abs(lam2) else lam2
    if ridge_lam >= -min_strength:
        return None
    if abs(ixy) > 1e-12:
        nx = ridge_lam - iyy
        ny = ixy
    elif ixx <= iyy:
        nx, ny = 1.0, 0.0
    else:
        nx, ny = 0.0, 1.0
    nlen = math.hypot(nx, ny)
    if nlen <= 1e-12:
        return None
    nx /= nlen
    ny /= nlen
    t = -(ix * nx + iy * ny) / ridge_lam
    if abs(t) > max_offset:
        return None
    return t * nx, t * ny, abs(ridge_lam)


def steger_candidate_map(
    probability: list[list[float]],
    sigma: float,
    min_strength: float,
    max_offset: float,
) -> tuple[dict[Point, FloatPoint], dict]:
    if not probability:
        return {}, {"ridge_candidate_points": 0, "ridge_mean_offset_px": 0.0, "ridge_max_offset_px": 0.0}
    img = gaussian_blur(probability, sigma)
    h = len(img)
    w = len(img[0])
    candidates: dict[Point, FloatPoint] = {}
    offsets: list[float] = []
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            offset = steger_offset_at(img, x, y, min_strength, max_offset)
            if offset is None:
                continue
            ox, oy, _ = offset
            candidates[(x, y)] = (x + ox, y + oy)
            offsets.append(math.hypot(ox, oy))
    return candidates, {
        "ridge_candidate_points": len(candidates),
        "ridge_mean_offset_px": sum(offsets) / len(offsets) if offsets else 0.0,
        "ridge_max_offset_px": max(offsets) if offsets else 0.0,
    }


def steger_refine_loop(
    pixel_loop: list[Point],
    probability: list[list[float]],
    sigma: float,
    min_strength: float,
    max_offset: float,
) -> tuple[list[FloatPoint], dict]:
    if not pixel_loop or not probability:
        return [(float(x), float(y)) for x, y in pixel_loop], {"ridge_refined_points": 0, "ridge_mean_offset_px": 0.0, "ridge_max_offset_px": 0.0}
    img = gaussian_blur(probability, sigma)
    out: list[FloatPoint] = []
    offsets: list[float] = []
    refined = 0
    for x, y in pixel_loop:
        offset = steger_offset_at(img, x, y, min_strength, max_offset)
        if offset is None:
            out.append((float(x), float(y)))
            offsets.append(0.0)
            continue
        ox, oy, _ = offset
        out.append((x + ox, y + oy))
        offsets.append(math.hypot(ox, oy))
        refined += 1
    return out, {
        "ridge_refined_points": refined,
        "ridge_mean_offset_px": sum(offsets) / len(offsets),
        "ridge_max_offset_px": max(offsets) if offsets else 0.0,
    }


def neighbors8(p: Point) -> list[Point]:
    x, y = p
    return [
        (x - 1, y - 1),
        (x, y - 1),
        (x + 1, y - 1),
        (x - 1, y),
        (x + 1, y),
        (x - 1, y + 1),
        (x, y + 1),
        (x + 1, y + 1),
    ]


def disk_offsets(radius: int) -> list[Point]:
    r2 = radius * radius
    return [
        (dx, dy)
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1)
        if dx * dx + dy * dy <= r2
    ]


def inside_image(x: int, y: int, width: int, height: int) -> bool:
    return 0 <= x < width and 0 <= y < height


def dilate(mask: set[Point], width: int, height: int, radius: int) -> set[Point]:
    if radius <= 0:
        return set(mask)
    out: set[Point] = set()
    offsets = disk_offsets(radius)
    for x, y in mask:
        for dx, dy in offsets:
            xx = x + dx
            yy = y + dy
            if inside_image(xx, yy, width, height):
                out.add((xx, yy))
    return out


def erosion_keeps_pixel(mask: set[Point], x: int, y: int, width: int, height: int, offsets: list[Point]) -> bool:
    return all(inside_image(x + dx, y + dy, width, height) and (x + dx, y + dy) in mask for dx, dy in offsets)


def erode(mask: set[Point], width: int, height: int, radius: int) -> set[Point]:
    if radius <= 0:
        return set(mask)
    out: set[Point] = set()
    offsets = disk_offsets(radius)
    for x, y in mask:
        if erosion_keeps_pixel(mask, x, y, width, height, offsets):
            out.add((x, y))
    return out


def close_mask(mask: set[Point], width: int, height: int, radius: int) -> set[Point]:
    if radius <= 0:
        return set(mask)
    return erode(dilate(mask, width, height, radius), width, height, radius)


def connected_components(mask: set[Point]) -> list[set[Point]]:
    remaining = set(mask)
    comps: list[set[Point]] = []
    while remaining:
        start = remaining.pop()
        comp = {start}
        q: deque[Point] = deque([start])
        while q:
            p = q.popleft()
            for nb in neighbors8(p):
                if nb in remaining:
                    remaining.remove(nb)
                    comp.add(nb)
                    q.append(nb)
        comps.append(comp)
    return comps


def largest_component(mask: set[Point], min_area: int) -> set[Point]:
    comps = connected_components(mask)
    if not comps:
        raise SystemExit("No track-colored pixels found")
    best = max(comps, key=len)
    if len(best) < min_area:
        raise SystemExit(f"Largest extracted component has only {len(best)} pixels; lower --min-component-area or adjust extraction")
    return best


def zhang_suen_values(pixels: set[Point], p: Point) -> list[int]:
    x, y = p
    pts = [(x, y - 1), (x + 1, y - 1), (x + 1, y), (x + 1, y + 1), (x, y + 1), (x - 1, y + 1), (x - 1, y), (x - 1, y - 1)]
    return [1 if q in pixels else 0 for q in pts]


def zhang_suen_transition_count(values: list[int]) -> int:
    return sum(1 for i in range(8) if values[i] == 0 and values[(i + 1) % 8] == 1)


def zhang_suen_step_condition(values: list[int], step: int) -> bool:
    if step == 0:
        return values[0] * values[2] * values[4] == 0 and values[2] * values[4] * values[6] == 0
    return values[0] * values[2] * values[6] == 0 and values[0] * values[4] * values[6] == 0


def zhang_suen_removes_pixel(pixels: set[Point], p: Point, step: int) -> bool:
    values = zhang_suen_values(pixels, p)
    count = sum(values)
    transitions = zhang_suen_transition_count(values)
    return 2 <= count <= 6 and transitions == 1 and zhang_suen_step_condition(values, step)


def zhang_suen_step(pixels: set[Point], step: int) -> bool:
    remove = [p for p in list(pixels) if zhang_suen_removes_pixel(pixels, p, step)]
    if not remove:
        return False
    pixels.difference_update(remove)
    return True


def zhang_suen_thin(mask: set[Point]) -> set[Point]:
    pixels = set(mask)
    if not pixels:
        return pixels

    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            changed = zhang_suen_step(pixels, step) or changed
    return pixels


def skimage_skeletonize(mask: set[Point], width: int, height: int, close_radius: int, min_area: int) -> set[Point]:
    if np is None or morphology is None:
        raise SystemExit("--extractor skimage-skeleton requires numpy and scikit-image; update the torcs-tracktools environment")
    if not mask:
        return set()
    arr = np.zeros((height, width), dtype=bool)
    for x, y in mask:
        arr[y, x] = True
    if close_radius > 0:
        arr = morphology.binary_closing(arr, morphology.disk(close_radius))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Parameter `min_size` is deprecated", category=FutureWarning)
        arr = morphology.remove_small_objects(arr, min_size=max(1, min_area))
    skel = morphology.skeletonize(arr)
    ys, xs = np.nonzero(skel)
    return {(int(x), int(y)) for x, y in zip(xs, ys, strict=True)}


def skeleton_endpoints(pixels: set[Point]) -> list[Point]:
    return [p for p in pixels if sum(1 for nb in neighbors8(p) if nb in pixels) == 1]


def trace_start_point(pixels: set[Point], endpoints: list[Point]) -> Point:
    source = endpoints if endpoints else pixels
    return min(source, key=lambda p: (p[1], p[0]))


def trace_seam_target(endpoints: list[Point], start: Point) -> Point:
    if len(endpoints) == 2:
        return max(endpoints, key=lambda p: math.hypot(p[0] - start[0], p[1] - start[1]))
    return start


def trace_candidates(
    pixels: set[Point],
    cur: Point,
    prev: Point | None,
    visited: set[Point],
    start: Point,
    ordered_len: int,
) -> list[Point]:
    return [
        nb
        for nb in neighbors8(cur)
        if nb in pixels and nb != prev and (nb not in visited or (nb == start and ordered_len > 12))
    ]


def accepts_open_seam(
    endpoints: list[Point],
    cur: Point,
    seam_target: Point,
    start: Point,
    max_seam_gap_px: float,
) -> bool:
    seam_gap = math.hypot(cur[0] - start[0], cur[1] - start[1])
    return len(endpoints) == 2 and cur == seam_target and seam_gap <= max_seam_gap_px


def first_trace_next(candidates: list[Point], cur: Point) -> Point:
    return min(candidates, key=lambda p: math.atan2(p[1] - cur[1], p[0] - cur[0]))


def continuity_score(prev: Point, cur: Point, candidate: Point) -> float:
    inx = cur[0] - prev[0]
    iny = cur[1] - prev[1]
    outx = candidate[0] - cur[0]
    outy = candidate[1] - cur[1]
    return (inx * outx + iny * outy) / max(
        1e-9,
        math.hypot(inx, iny) * math.hypot(outx, outy),
    )


def next_trace_pixel(candidates: list[Point], cur: Point, prev: Point | None) -> Point:
    if prev is None:
        return first_trace_next(candidates, cur)
    return max(candidates, key=lambda p: continuity_score(prev, cur, p))


def trace_loop(pixels: set[Point], max_seam_gap_px: float) -> list[Point]:
    if len(pixels) < 8:
        raise SystemExit("Extracted skeleton is too small")
    endpoints = skeleton_endpoints(pixels)
    start = trace_start_point(pixels, endpoints)
    seam_target = trace_seam_target(endpoints, start)
    ordered = [start]
    visited = {start}
    prev: Point | None = None
    cur = start
    max_steps = len(pixels) * 3
    for _ in range(max_steps):
        candidates = trace_candidates(pixels, cur, prev, visited, start, len(ordered))
        if not candidates:
            if accepts_open_seam(endpoints, cur, seam_target, start, max_seam_gap_px):
                return ordered
            break
        nxt = next_trace_pixel(candidates, cur, prev)
        if nxt == start:
            return ordered
        ordered.append(nxt)
        visited.add(nxt)
        prev, cur = cur, nxt
    gap = math.hypot(ordered[-1][0] - start[0], ordered[-1][1] - start[1])
    raise SystemExit(f"Could not trace a closed loop from extracted pixels; seam gap is {gap:.1f} px. Try --close-gap-px, --max-seam-gap-px, or adjust --track-color/--crop")

def norm_angle(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def local_curvature(points: list[FloatPoint], idx: int, span: int) -> float:
    n = len(points)
    span = max(1, min(span, n // 4))
    a = points[(idx - span) % n]
    b = points[idx]
    c = points[(idx + span) % n]
    h0 = math.atan2(b[1] - a[1], b[0] - a[0])
    h1 = math.atan2(c[1] - b[1], c[0] - b[0])
    return abs(norm_angle(h1 - h0))


def smooth_closed(
    points: list[FloatPoint],
    window: int,
    rounds: int,
    adaptive: bool = False,
    preserve_curvature_deg: float = 8.0,
    curvature_window: int = 4,
) -> list[FloatPoint]:
    if window <= 1 or rounds <= 0:
        return list(points)
    if window % 2 == 0:
        window += 1
    half = window // 2
    out = list(points)
    n = len(out)
    for _ in range(rounds):
        src = out
        next_out: list[FloatPoint] = []
        for i in range(n):
            local_half = half
            if adaptive:
                curv = local_curvature(src, i, curvature_window)
                preserve = max(1e-9, math.radians(preserve_curvature_deg))
                factor = max(0.0, min(1.0, curv / preserve))
                local_half = max(1, int(round(half * (1.0 - factor))))
            local_window = local_half * 2 + 1
            next_out.append(
                (
                    sum(src[(i + j) % n][0] for j in range(-local_half, local_half + 1)) / local_window,
                    sum(src[(i + j) % n][1] for j in range(-local_half, local_half + 1)) / local_window,
                )
            )
        out = next_out
    return out


def closed_length(points: list[FloatPoint]) -> float:
    return sum(math.hypot(points[(i + 1) % len(points)][0] - points[i][0], points[(i + 1) % len(points)][1] - points[i][1]) for i in range(len(points)))


def resample_closed(points: list[FloatPoint], step: float) -> list[FloatPoint]:
    if step <= 0.0:
        return list(points)
    total = closed_length(points)
    count = max(8, int(round(total / step)))
    cumulative = [0.0]
    for i in range(len(points)):
        a = points[i]
        b = points[(i + 1) % len(points)]
        cumulative.append(cumulative[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    out: list[FloatPoint] = []
    seg = 0
    for k in range(count):
        s = total * k / count
        while seg + 1 < len(cumulative) and cumulative[seg + 1] < s:
            seg += 1
        a = points[seg % len(points)]
        b = points[(seg + 1) % len(points)]
        span = max(1e-9, cumulative[seg + 1] - cumulative[seg])
        u = (s - cumulative[seg]) / span
        out.append((a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1])))
    return out


def heading_delta(a: FloatPoint, b: FloatPoint, c: FloatPoint) -> float:
    h0 = math.atan2(b[1] - a[1], b[0] - a[0])
    h1 = math.atan2(c[1] - b[1], c[0] - b[0])
    d = h1 - h0
    while d > math.pi:
        d -= 2.0 * math.pi
    while d < -math.pi:
        d += 2.0 * math.pi
    return abs(d)


def rotate_to_smooth_start(points: list[FloatPoint], window: int) -> tuple[list[FloatPoint], int]:
    if len(points) < 8:
        return points, 0
    span = max(2, min(window, len(points) // 8))
    best_idx = 0
    best_score = 1e30
    n = len(points)
    for i in range(n):
        score = 0.0
        for j in range(-span, span + 1):
            idx = (i + j) % n
            score += heading_delta(points[(idx - 1) % n], points[idx], points[(idx + 1) % n])
        chord = math.hypot(points[(i + span) % n][0] - points[(i - span) % n][0], points[(i + span) % n][1] - points[(i - span) % n][1])
        score -= 0.001 * chord
        if score < best_score:
            best_score = score
            best_idx = i
    return points[best_idx:] + points[:best_idx], best_idx


def scale_points(
    pixel_loop: list[FloatPoint],
    length_m: float,
    reverse: bool,
    smooth_window: int,
    smooth_rounds: int,
    adaptive_smoothing: bool,
    preserve_curvature_deg: float,
    curvature_window: int,
    resample_step: float,
    start_window: int,
) -> tuple[list[FloatPoint], dict]:
    pts = [(float(x), -float(y)) for x, y in pixel_loop]
    if reverse:
        pts.reverse()
    pts = smooth_closed(pts, smooth_window, smooth_rounds, adaptive_smoothing, preserve_curvature_deg, curvature_window)
    px_len = closed_length(pts)
    if px_len <= 1e-9:
        raise SystemExit("Extracted loop has zero length")
    scale = length_m / px_len
    x0, y0 = pts[0]
    meters = [((x - x0) * scale, (y - y0) * scale) for x, y in pts]
    meters = resample_closed(meters, resample_step)
    resampled_len = closed_length(meters)
    if resampled_len > 1e-9:
        adjust = length_m / resampled_len
        meters = [(x * adjust, y * adjust) for x, y in meters]
    meters, start_index = rotate_to_smooth_start(meters, start_window)
    return meters, {
        "pixel_length": px_len,
        "scale_m_per_px": scale,
        "output_length_m": closed_length(meters),
        "rotated_start_index": start_index,
        "adaptive_smoothing": adaptive_smoothing,
        "preserve_curvature_deg": preserve_curvature_deg,
    }


def svg_poly(points: list[FloatPoint], min_x: float, min_y: float, view_h: float, pad: float) -> str:
    return " ".join(f"{x - min_x + pad:.2f},{view_h - (y - min_y + pad):.2f}" for x, y in points)


def write_preview(path: pathlib.Path, points_m: list[FloatPoint], stats: dict) -> None:
    xs = [x for x, _ in points_m]
    ys = [y for _, y in points_m]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    pad = 20.0
    view_w = max(1.0, max_x - min_x) + 2.0 * pad
    view_h = max(1.0, max_y - min_y) + 2.0 * pad
    poly = svg_poly(points_m + [points_m[0]], min_x, min_y, view_h, pad)
    start_x = points_m[0][0] - min_x + pad
    start_y = view_h - (points_m[0][1] - min_y + pad)
    svg = "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 {view_w:.2f} {view_h:.2f}">',
            '<rect width="100%" height="100%" fill="#0f172a"/>',
            f'<polyline fill="none" stroke="#ef4444" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" points="{poly}"/>',
            f'<circle cx="{start_x:.2f}" cy="{start_y:.2f}" r="8" fill="#22c55e"/>',
            f'<text x="20" y="32" fill="#e2e8f0" font-family="monospace" font-size="18">length={stats["output_length_m"]:.2f} m, scale={stats["scale_m_per_px"]:.6f} m/px, points={len(points_m)}</text>',
            '<text x="20" y="58" fill="#94a3b8" font-family="monospace" font-size="15">green=start, red=extracted centerline</text>',
            "</svg>",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.length_m <= 0.0:
        raise SystemExit("--length-m must be positive")

    img = Image.open(args.input)
    crop = parse_crop(args.crop)
    if crop is not None:
        x, y, w, h = crop
        img = img.crop((x, y, x + w, y + h))
    original_size = (img.width, img.height)

    raw_mask = extract_mask(img, args)
    probability = extract_probability(img, args) if args.extractor in ("ridge", "ridge-link") else []
    close_gap_px = args.close_gap_px
    max_seam_gap_px = args.max_seam_gap_px
    min_component_area = args.min_component_area
    ridge_stats: dict = {}
    if args.extractor == "ridge-link":
        ridge_candidates, ridge_stats = steger_candidate_map(
            probability,
            args.ridge_sigma,
            args.ridge_min_strength,
            args.ridge_max_offset_px,
        )
        if not ridge_candidates:
            raise SystemExit("No ridge candidates found; lower --ridge-min-strength or adjust color extraction")
        linked_ridges = close_mask(set(ridge_candidates), img.width, img.height, close_gap_px)
        component = largest_component(linked_ridges, max(8, min_component_area))
        skeleton = zhang_suen_thin(component)
        skeleton = largest_component(skeleton, max(8, min(len(skeleton), min_component_area)))
        pixel_loop = trace_loop(skeleton, max_seam_gap_px)
        pixel_points = [ridge_candidates.get(p, (float(p[0]), float(p[1]))) for p in pixel_loop]
    else:
        closed = close_mask(raw_mask, img.width, img.height, close_gap_px)
        component = largest_component(closed, min_component_area)
        if args.extractor == "skimage-skeleton":
            skeleton = skimage_skeletonize(component, img.width, img.height, 0, min_component_area)
        else:
            skeleton = zhang_suen_thin(component)
        skeleton = largest_component(skeleton, max(8, min(min_component_area, len(skeleton))))
        pixel_loop = trace_loop(skeleton, max_seam_gap_px)
    if args.extractor == "ridge":
        pixel_points, ridge_stats = steger_refine_loop(
            pixel_loop,
            probability,
            args.ridge_sigma,
            args.ridge_min_strength,
            args.ridge_max_offset_px,
        )
    elif args.extractor in ("skeleton", "skimage-skeleton"):
        pixel_points = [(float(x), float(y)) for x, y in pixel_loop]
    points_m, stats = scale_points(
        pixel_points,
        args.length_m,
        args.reverse,
        args.smooth_window,
        args.smooth_rounds,
        args.adaptive_smoothing,
        args.preserve_curvature_deg,
        args.curvature_window,
        args.resample_step,
        args.start_window,
    )

    out = {
        "source": "image-to-centerline",
        "input_image": str(args.input),
        "length_m": args.length_m,
        "extraction": {
            "track_color": args.track_color,
            "color_tolerance": args.color_tolerance,
            "threshold": args.threshold,
            "extractor": args.extractor,
            "crop": args.crop,
            "original_size_px": {"width": original_size[0], "height": original_size[1]},
            "extraction_size_px": {"width": img.width, "height": img.height},
            "close_gap_px": close_gap_px,
            "max_seam_gap_px": max_seam_gap_px,
            "min_component_area": min_component_area,
            "raw_pixels": len(raw_mask),
            "component_pixels": len(component),
            "skeleton_pixels": len(skeleton),
            **ridge_stats,
            **stats,
        },
        "polyline": [{"x": x, "y": y, "way_name": "image-centerline"} for x, y in points_m],
    }
    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    if args.preview_svg:
        write_preview(pathlib.Path(args.preview_svg), points_m, stats)
    print(f"Wrote centerline: {out_path}")
    print(f"Extracted {len(points_m)} points, length={stats['output_length_m']:.3f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
