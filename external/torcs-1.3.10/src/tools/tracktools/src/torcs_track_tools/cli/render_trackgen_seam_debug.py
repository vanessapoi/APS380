#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : render_trackgen_seam_debug.py
#     created              : 23 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Render seam-local SVG using authoritative trackgen closure deltas."""

from __future__ import annotations

import argparse
import math
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render seam-local SVG with trackgen closure pose")
    parser.add_argument("--track-xml", required=True, help="Track XML path")
    parser.add_argument("--runtime-dir", required=True, help="TORCS runtime directory containing trackgen.exe")
    parser.add_argument("--category", required=True, help="Track category for trackgen")
    parser.add_argument("--name", required=True, help="Track short name for trackgen")
    parser.add_argument("--output", required=True, help="Output SVG path")
    parser.add_argument("--window-m", type=float, default=140.0, help="Arc-length window from seam on each side")
    return parser.parse_args()


SECTION_RE = re.compile(r'<section\s+name="([^"]+)">', re.IGNORECASE)
ATT_RE = re.compile(r'<att(?:num|str)\s+name="([^"]+)"[^>]*\bval="([^"]*)"[^>]*/>', re.IGNORECASE)


def norm_angle(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def find_matching_section_end(text: str, open_start: int) -> int:
    open_match = SECTION_RE.match(text, open_start)
    if not open_match:
        raise RuntimeError("Section open tag expected")
    i = open_match.end()
    depth = 1
    token_re = re.compile(r'</section>|<section\s+name="[^"]+">', re.IGNORECASE)
    while True:
        m = token_re.search(text, i)
        if not m:
            raise RuntimeError("Unbalanced section tags")
        token = m.group(0)
        if token.lower().startswith("<section"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.end()
        i = m.end()


def parse_top_level_segments(track_xml: pathlib.Path) -> list[dict]:
    text = track_xml.read_text(encoding="utf-8")
    m = re.search(r'<section\s+name="Track Segments">', text, re.IGNORECASE)
    if not m:
        raise RuntimeError("Track Segments section not found")
    start = m.start()
    end = find_matching_section_end(text, start)
    block = text[start:end]
    open_match = SECTION_RE.search(block)
    if not open_match:
        return []
    i = open_match.end()
    segs: list[dict] = []
    token_re = re.compile(r'</section>|<section\s+name="([^"]+)">', re.IGNORECASE)
    while True:
        m = token_re.search(block, i)
        if not m:
            break
        token = m.group(0)
        if token.lower().startswith("<section"):
            seg_start = m.start()
            seg_end = find_matching_section_end(block, seg_start)
            seg_text = block[seg_start:seg_end]
            segs.append({"name": m.group(1), "attrs": {k: v for k, v in ATT_RE.findall(seg_text)}})
            i = seg_end
            continue
        i = m.end()
    return segs


def to_float(v: str | None, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except ValueError:
        return default


def sample_centerline_points(segs: list[dict]) -> tuple[list[tuple[float, float]], list[float], float]:
    pts: list[tuple[float, float]] = [(0.0, 0.0)]
    arc: list[float] = [0.0]
    x = y = h = 0.0
    total = 0.0
    for seg in segs:
        t = seg["attrs"].get("type", "")
        if t == "str":
            lg = to_float(seg["attrs"].get("lg"), 0.0)
            x += lg * math.cos(h)
            y += lg * math.sin(h)
            total += lg
            pts.append((x, y))
            arc.append(total)
        elif t in ("lft", "rgt"):
            r = max(1e-6, abs(to_float(seg["attrs"].get("radius"), 0.0)))
            a = math.radians(to_float(seg["attrs"].get("arc"), 0.0))
            sign = 1.0 if t == "lft" else -1.0
            cx = x - sign * r * math.sin(h)
            cy = y + sign * r * math.cos(h)
            seg_len = r * abs(a)
            n = max(8, int(math.ceil(seg_len / 4.0)))
            da = a / n
            for _ in range(n):
                h += sign * da
                x = cx + sign * r * math.sin(h)
                y = cy - sign * r * math.cos(h)
                total += seg_len / n
                pts.append((x, y))
                arc.append(total)
    return pts, arc, h


def installed_track_xml(runtime_dir: pathlib.Path, category: str, name: str) -> pathlib.Path:
    return runtime_dir / "tracks" / category / name / f"{name}.xml"


def acquire_file_lock(lock_path: pathlib.Path, timeout_s: float = 120.0) -> None:
    deadline = time.perf_counter() + timeout_s
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
            finally:
                os.close(fd)
            return
        except FileExistsError:
            if time.perf_counter() >= deadline:
                raise RuntimeError(f"Timed out waiting for trackgen XML lock: {lock_path}") from None
            time.sleep(0.2)


def release_file_lock(lock_path: pathlib.Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def run_trackgen_z(runtime_dir: pathlib.Path, category: str, name: str, track_xml_under_test: pathlib.Path) -> dict:
    cmd = [str(runtime_dir / "trackgen.exe"), "-c", category, "-n", name, "-z"]
    live_track_xml = installed_track_xml(runtime_dir, category, name)
    under_test = track_xml_under_test.resolve()
    live_resolved = live_track_xml.resolve()

    def execute() -> dict:
        proc = subprocess.run(cmd, cwd=str(runtime_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        out = proc.stdout
        if proc.returncode != 0:
            raise RuntimeError(f"trackgen failed ({proc.returncode})\n{out}")

        def parse_num(label: str) -> float:
            m = re.search(rf'^{re.escape(label)}\s*=\s*([-+0-9.eE]+)', out, re.MULTILINE)
            if not m:
                raise RuntimeError(f"Could not parse {label}")
            return float(m.group(1))

        m = re.search(r'^Delta Ang\s*=\s*[-+0-9.eE]+\s*\(([-+0-9.eE]+)\)', out, re.MULTILINE)
        ang_deg = float(m.group(1)) if m else parse_num("Delta Ang")
        return {"delta_x": parse_num("Delta X"), "delta_y": parse_num("Delta Y"), "delta_ang_deg": ang_deg}

    if under_test == live_resolved:
        return execute()

    if not live_track_xml.exists():
        raise RuntimeError(f"Installed runtime track XML not found: {live_track_xml}")
    lock_path = runtime_dir / f".trackgen-{category}-{name}.lock"
    acquire_file_lock(lock_path)
    backup_dir = pathlib.Path(tempfile.mkdtemp(prefix="seam_debug_", dir=str(runtime_dir)))
    backup_xml = backup_dir / live_track_xml.name
    try:
        shutil.copyfile(live_track_xml, backup_xml)
        shutil.copyfile(under_test, live_track_xml)
        return execute()
    finally:
        if backup_xml.exists():
            shutil.copyfile(backup_xml, live_track_xml)
        shutil.rmtree(backup_dir, ignore_errors=True)
        release_file_lock(lock_path)


def transform_point(pt: tuple[float, float], origin: tuple[float, float], heading: float) -> tuple[float, float]:
    dx = pt[0] - origin[0]
    dy = pt[1] - origin[1]
    c = math.cos(heading)
    s = math.sin(heading)
    return (dx * c + dy * s, -dx * s + dy * c)


def rotate_translate_point(pt: tuple[float, float], from_pt: tuple[float, float], to_pt: tuple[float, float], delta_heading: float) -> tuple[float, float]:
    dx = pt[0] - from_pt[0]
    dy = pt[1] - from_pt[1]
    c = math.cos(delta_heading)
    s = math.sin(delta_heading)
    return (to_pt[0] + dx * c - dy * s, to_pt[1] + dx * s + dy * c)


def main() -> int:
    args = parse_args()
    segs = parse_top_level_segments(pathlib.Path(args.track_xml))
    pts, arc, end_heading = sample_centerline_points(segs)
    metrics = run_trackgen_z(pathlib.Path(args.runtime_dir), args.category, args.name, pathlib.Path(args.track_xml))

    start = pts[0]
    start_heading = math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0])
    total_len = arc[-1]
    window = max(10.0, float(args.window_m))
    first_idx = [i for i, s in enumerate(arc) if s <= window]
    last_idx = [i for i, s in enumerate(arc) if s >= total_len - window]

    first_pts = [transform_point(pts[i], start, start_heading) for i in first_idx]
    # Anchor the final window on authoritative trackgen end pose.
    end_target = (metrics["delta_x"], metrics["delta_y"])
    delta_heading = math.radians(metrics["delta_ang_deg"])
    last_pts_global = [rotate_translate_point(pts[i], pts[-1], end_target, delta_heading) for i in last_idx]
    last_pts = [transform_point(p, (0.0, 0.0), 0.0) for p in last_pts_global]

    all_pts = first_pts + last_pts + [(0.0, 0.0), end_target]
    minx = min(p[0] for p in all_pts)
    maxx = max(p[0] for p in all_pts)
    miny = min(p[1] for p in all_pts)
    maxy = max(p[1] for p in all_pts)
    pad = 20.0
    view_w = max(220.0, maxx - minx + 2 * pad)
    view_h = max(220.0, maxy - miny + 2 * pad)

    def map_pt(p: tuple[float, float]) -> str:
        x = p[0] - minx + pad
        y = view_h - (p[1] - miny + pad)
        return f"{x:.2f},{y:.2f}"

    first_poly = " ".join(map_pt(p) for p in first_pts)
    last_poly = " ".join(map_pt(p) for p in last_pts)
    origin = map_pt((0.0, 0.0))
    end_marker = map_pt(end_target)

    svg = "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 {view_w:.2f} {view_h:.2f}">',
        '<rect width="100%" height="100%" fill="#111217"/>',
        f'<polyline points="{first_poly}" fill="none" stroke="#f8fafc" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>',
        f'<polyline points="{last_poly}" fill="none" stroke="#fb7185" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>',
        f'<circle cx="{origin.split(",")[0]}" cy="{origin.split(",")[1]}" r="6" fill="#22c55e"/>',
        f'<circle cx="{end_marker.split(",")[0]}" cy="{end_marker.split(",")[1]}" r="6" fill="#f59e0b"/>',
        '<text x="24" y="34" fill="#f8fafc" font-family="Consolas, monospace" font-size="20">Trackgen seam debug</text>',
        f'<text x="24" y="60" fill="#f8fafc" font-family="Consolas, monospace" font-size="18">White: first {window:.0f} m, Red: last {window:.0f} m anchored by trackgen closure pose</text>',
        f'<text x="24" y="86" fill="#f8fafc" font-family="Consolas, monospace" font-size="18">trackgen dx={metrics["delta_x"]:.3f} m, dy={metrics["delta_y"]:.3f} m, dang={metrics["delta_ang_deg"]:.6f} deg</text>',
        '</svg>',
    ])

    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    print(f"Wrote SVG: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
