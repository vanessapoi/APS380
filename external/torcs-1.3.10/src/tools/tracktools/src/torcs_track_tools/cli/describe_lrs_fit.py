#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : describe_lrs_fit.py
#     created              : 19 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Create L/R/S descriptions from cached polyline and measure fit.

This script does not touch TORCS XML. It only:
1) reads cached centerline points,
2) builds left/right/straight segment descriptions,
3) reconstructs the polyline from that description,
4) compares reconstructed vs source geometry.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
from dataclasses import dataclass

from torcs_track_tools.core.overlay import nearest_polyline_distance as nearest_polyline_dist
from torcs_track_tools.core.overlay import rigid_fit
from torcs_track_tools.core.polyline import to_xy_dicts


@dataclass
class Segment:
    kind: str  # str|lft|rgt
    length: float
    turn_rad: float


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build L/R/S description and measure fit")
    p.add_argument("--input", required=True, help="Cached centerline JSON")
    p.add_argument("--output-json", required=True, help="Output report JSON")
    p.add_argument("--output-svg", required=True, help="Output overlay SVG")
    p.add_argument("--step", type=float, default=3.0, help="Resample step in meters")
    p.add_argument("--coarse-kappa", type=float, default=0.0022, help="Straight threshold (coarse)")
    p.add_argument("--coarse-min-len", type=float, default=24.0, help="Min run length (coarse)")
    p.add_argument("--fine-kappa", type=float, default=0.0012, help="Straight threshold (fine)")
    p.add_argument("--fine-min-len", type=float, default=8.0, help="Min run length (fine)")
    p.add_argument("--max-curve-rmse", type=float, default=1.8, help="Max arc fit RMSE before splitting run")
    return p.parse_args()


def dist(a: dict, b: dict) -> float:
    return math.hypot(b["x"] - a["x"], b["y"] - a["y"])


def heading(a: dict, b: dict) -> float:
    return math.atan2(b["y"] - a["y"], b["x"] - a["x"])


def norm_angle(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def resample(poly: list[dict], step: float) -> list[dict]:
    out = [poly[0]]
    carry = 0.0
    for i in range(1, len(poly)):
        a = poly[i - 1]
        b = poly[i]
        L = dist(a, b)
        if L < 1e-9:
            continue
        ux = (b["x"] - a["x"]) / L
        uy = (b["y"] - a["y"]) / L
        d = step - carry
        while d <= L + 1e-9:
            out.append({"x": a["x"] + ux * d, "y": a["y"] + uy * d})
            d += step
        carry = L - (d - step)
    if dist(out[-1], poly[-1]) > 0.3 * step:
        out.append(poly[-1])
    return out


def smooth(vals: list[float], window: int = 5) -> list[float]:
    if window <= 1:
        return vals[:]
    n = len(vals)
    half = window // 2
    out = []
    for i in range(n):
        a = max(0, i - half)
        b = min(n, i + half + 1)
        out.append(sum(vals[a:b]) / (b - a))
    return out


def classify_points(points: list[dict], step: float, straight_kappa: float) -> list[dict]:
    heads = [heading(points[i], points[i + 1]) for i in range(len(points) - 1)]
    dtheta = [norm_angle(heads[i + 1] - heads[i]) for i in range(len(heads) - 1)]
    kappa = smooth([dt / max(step, 1e-9) for dt in dtheta], window=7)
    out = []
    for i, k in enumerate(kappa, start=1):
        if abs(k) < straight_kappa:
            kind = "str"
        elif k > 0:
            kind = "lft"
        else:
            kind = "rgt"
        out.append({"i": i, "kind": kind, "kappa": k})
    return out


def initial_class_runs(classes: list[dict]) -> list[dict]:
    runs = [{"kind": classes[0]["kind"], "i0": classes[0]["i"], "i1": classes[0]["i"]}]
    for c in classes[1:]:
        if c["kind"] == runs[-1]["kind"]:
            runs[-1]["i1"] = c["i"]
        else:
            runs.append({"kind": c["kind"], "i0": c["i"], "i1": c["i"]})
    return runs


def class_run_length(run: dict, step: float) -> float:
    return (run["i1"] - run["i0"] + 1) * step


def merge_tiny_class_run(runs: list[dict], i: int, step: float, min_len: float) -> bool:
    if class_run_length(runs[i], step) >= min_len:
        return False
    prev = runs[i - 1]
    nxt = runs[i + 1]
    if prev["kind"] == nxt["kind"]:
        prev["i1"] = nxt["i1"]
        runs.pop(i + 1)
        runs.pop(i)
    elif prev["kind"] == runs[i]["kind"]:
        prev["i1"] = runs[i]["i1"]
        runs.pop(i)
    elif nxt["kind"] == runs[i]["kind"]:
        nxt["i0"] = runs[i]["i0"]
        runs.pop(i)
    elif class_run_length(prev, step) >= class_run_length(nxt, step):
        prev["i1"] = runs[i]["i1"]
        runs.pop(i)
    else:
        nxt["i0"] = runs[i]["i0"]
        runs.pop(i)
    return True


def runs_from_classes(classes: list[dict], min_len: float, step: float) -> list[dict]:
    if not classes:
        return []
    runs = initial_class_runs(classes)

    changed = True
    while changed and len(runs) > 2:
        changed = False
        i = 1
        while i < len(runs) - 1:
            if not merge_tiny_class_run(runs, i, step, min_len):
                i += 1
                continue
            changed = True
    return runs


def solve_3x3(a: list[list[float]], b: list[float]) -> tuple[float, float, float] | None:
    # Gaussian elimination with partial pivoting.
    m = [a[0][:] + [b[0]], a[1][:] + [b[1]], a[2][:] + [b[2]]]
    n = 3
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None
        if piv != col:
            m[col], m[piv] = m[piv], m[col]
        div = m[col][col]
        for j in range(col, n + 1):
            m[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            fac = m[r][col]
            for j in range(col, n + 1):
                m[r][j] -= fac * m[col][j]
    return m[0][3], m[1][3], m[2][3]


def fit_circle(points: list[dict]) -> tuple[float, float, float, float] | None:
    # Algebraic fit: x^2 + y^2 + A x + B y + C = 0
    if len(points) < 4:
        return None
    sx = sy = sxx = syy = sxy = 0.0
    sxxx = syyy = sxxy = sxyy = 0.0
    n = float(len(points))
    for p in points:
        x = p["x"]
        y = p["y"]
        xx = x * x
        yy = y * y
        sx += x
        sy += y
        sxx += xx
        syy += yy
        sxy += x * y
        sxxx += xx * x
        syyy += yy * y
        sxxy += xx * y
        sxyy += x * yy

    a = [
        [sxx, sxy, sx],
        [sxy, syy, sy],
        [sx, sy, n],
    ]
    rhs = [-(sxxx + sxyy), -(sxxy + syyy), -(sxx + syy)]
    sol = solve_3x3(a, rhs)
    if sol is None:
        return None
    A, B, C = sol
    cx = -A / 2.0
    cy = -B / 2.0
    rr = cx * cx + cy * cy - C
    if rr <= 1e-6:
        return None
    r = math.sqrt(rr)
    err = 0.0
    for p in points:
        err += (math.hypot(p["x"] - cx, p["y"] - cy) - r) ** 2
    rmse = math.sqrt(err / len(points))
    return cx, cy, r, rmse


def lrs_run_bounds(points: list[dict], run: dict) -> tuple[int, int] | None:
    i0 = max(0, run["i0"] - 1)
    i1 = min(len(points) - 1, run["i1"] + 1)
    if i1 <= i0:
        return None
    return i0, i1


def lrs_run_length(points: list[dict], i0: int, i1: int) -> float:
    return sum(dist(points[i], points[i + 1]) for i in range(i0, i1))


def lrs_run_turn(heads: list[float], i0: int, i1: int) -> float:
    return sum(norm_angle(heads[i + 1] - heads[i]) for i in range(max(0, i0), min(len(heads) - 1, i1)))


def sign_consistent_turn(kind: str, turn: float) -> float:
    if kind == "str":
        return 0.0
    if kind == "lft" and turn < 0:
        return abs(turn)
    if kind == "rgt" and turn > 0:
        return -abs(turn)
    return turn


def noisy_curve_split(run: dict, i0: int, i1: int, length: float, rmse: float, max_curve_rmse: float) -> tuple[dict, dict] | None:
    if rmse <= max_curve_rmse or (i1 - i0) < 10 or length < 18.0:
        return None
    mid = (run["i0"] + run["i1"]) // 2
    if mid <= run["i0"] or mid >= run["i1"]:
        return None
    kind = run["kind"]
    return {"kind": kind, "i0": run["i0"], "i1": mid}, {"kind": kind, "i0": mid + 1, "i1": run["i1"]}


def fitted_curve_geometry(kind: str, turn: float, radius_fit: float, round_len: float, round_arc: float) -> tuple[float, float]:
    arc_deg = max(0.4, round(abs(math.degrees(turn)) / round_arc) * round_arc)
    signed_turn = math.radians(arc_deg) * (1.0 if kind == "lft" else -1.0)
    radius = max(6.0, round(radius_fit / round_len) * round_len)
    return radius * abs(signed_turn), signed_turn


def segments_for_lrs_run(
    points: list[dict],
    heads: list[float],
    run: dict,
    round_len: float,
    round_arc: float,
    max_curve_rmse: float,
) -> list[Segment]:
    bounds = lrs_run_bounds(points, run)
    if bounds is None:
        return []
    i0, i1 = bounds
    length = lrs_run_length(points, i0, i1)
    kind = run["kind"]
    turn = sign_consistent_turn(kind, lrs_run_turn(heads, i0, i1))

    if kind != "str":
        fit = fit_circle(points[i0 : i1 + 1])
        if fit is not None:
            _, _, radius_fit, rmse = fit
            split = noisy_curve_split(run, i0, i1, length, rmse, max_curve_rmse)
            if split is not None:
                left, right = split
                return segments_for_lrs_run(points, heads, left, round_len, round_arc, max_curve_rmse) + segments_for_lrs_run(points, heads, right, round_len, round_arc, max_curve_rmse)
            length, turn = fitted_curve_geometry(kind, turn, radius_fit, round_len, round_arc)

    length = round(length / round_len) * round_len
    if length < 2.0:
        return []
    return [Segment(kind=kind, length=length, turn_rad=turn)]


def merge_adjacent_segments(segs: list[Segment]) -> list[Segment]:
    merged: list[Segment] = []
    for s in segs:
        if not merged:
            merged.append(s)
            continue
        p = merged[-1]
        if s.kind == p.kind:
            merged[-1] = Segment(kind=p.kind, length=p.length + s.length, turn_rad=p.turn_rad + s.turn_rad)
        else:
            merged.append(s)
    return merged


def segments_from_runs(
    points: list[dict],
    runs: list[dict],
    round_len: float = 1.0,
    round_arc: float = 0.1,
    max_curve_rmse: float = 1.8,
) -> list[Segment]:
    segs: list[Segment] = []
    heads = [heading(points[i], points[i + 1]) for i in range(len(points) - 1)]

    for run in runs:
        segs.extend(segments_for_lrs_run(points, heads, run, round_len, round_arc, max_curve_rmse))
    return merge_adjacent_segments(segs)


def reconstruct(segments: list[Segment], step: float = 3.0) -> list[dict]:
    x = 0.0
    y = 0.0
    h = 0.0
    sacc = 0.0
    pts = [{"x": x, "y": y, "s": sacc}]
    for seg in segments:
        if seg.kind == "str" or abs(seg.turn_rad) < 1e-8:
            n = max(1, int(math.ceil(seg.length / step)))
            ds = seg.length / n
            for _ in range(n):
                x += ds * math.cos(h)
                y += ds * math.sin(h)
                sacc += ds
                pts.append({"x": x, "y": y, "s": sacc})
            continue

        sign = 1.0 if seg.turn_rad > 0 else -1.0
        radius = seg.length / abs(seg.turn_rad)
        n = max(1, int(math.ceil(seg.length / step)))
        da = seg.turn_rad / n
        cx = x - sign * radius * math.sin(h)
        cy = y + sign * radius * math.cos(h)
        for _ in range(n):
            h += da
            x = cx + sign * radius * math.sin(h)
            y = cy - sign * radius * math.cos(h)
            sacc += abs(radius * da)
            pts.append({"x": x, "y": y, "s": sacc})
    return pts


def sample_by_arc(points: list[dict], count: int) -> tuple[list[dict], float]:
    arr = [{"x": points[0]["x"], "y": points[0]["y"], "s": 0.0}]
    total = 0.0
    for i in range(1, len(points)):
        ds = dist(points[i - 1], points[i])
        total += ds
        arr.append({"x": points[i]["x"], "y": points[i]["y"], "s": total})
    out = []
    k = 1
    for i in range(count):
        t = total * i / max(1, count - 1)
        while k < len(arr) and arr[k]["s"] < t:
            k += 1
        if k >= len(arr):
            out.append(arr[-1])
            continue
        a = arr[k - 1]
        b = arr[k]
        u = 0.0 if b["s"] == a["s"] else (t - a["s"]) / (b["s"] - a["s"])
        out.append({"x": a["x"] + u * (b["x"] - a["x"]), "y": a["y"] + u * (b["y"] - a["y"]), "s": t})
    return out, total


def transform(points: list[dict], fit: dict) -> list[dict]:
    out = []
    for p in points:
        out.append(
            {
                "x": fit["c"] * p["x"] - fit["s"] * p["y"] + fit["ox"],
                "y": fit["s"] * p["x"] + fit["c"] * p["y"] + fit["oy"],
                "s": p.get("s", 0.0),
            }
        )
    return out


def evaluate(source_xy: list[dict], segments: list[Segment]) -> dict:
    source_s, source_len = sample_by_arc(source_xy, 900)
    rec = reconstruct(segments, step=3.0)
    rec_s, rec_len = sample_by_arc(rec, 900)
    fit = rigid_fit(rec_s, source_s)
    rec_fit = transform(rec_s, fit)
    dists = [nearest_polyline_dist(p, source_xy) for p in rec_fit]
    mean = sum(dists) / len(dists)
    rmse = math.sqrt(sum(d * d for d in dists) / len(dists))
    maxd = max(dists)
    return {
        "source_len": source_len,
        "reconstructed_len": rec_len,
        "fit_rotation_deg": math.degrees(fit["theta"]),
        "mean_dev": mean,
        "rmse_dev": rmse,
        "max_dev": maxd,
        "segments": segments,
        "source_points": source_s,
        "recon_points": rec_fit,
    }


def segments_to_text(segments: list[Segment]) -> list[str]:
    rows = []
    for idx, s in enumerate(segments, start=1):
        if s.kind == "str":
            rows.append(f"{idx:02d}. STR {s.length:.1f}m")
        else:
            arc_deg = abs(math.degrees(s.turn_rad))
            radius = s.length / max(abs(s.turn_rad), math.radians(0.1))
            rows.append(f"{idx:02d}. {s.kind.upper()} R={radius:.1f}m A={arc_deg:.1f}deg L={s.length:.1f}m")
    return rows


def write_svg(path: pathlib.Path, src: list[dict], rec: list[dict]) -> None:
    pts = src + rec
    min_x = min(p["x"] for p in pts)
    max_x = max(p["x"] for p in pts)
    min_y = min(p["y"] for p in pts)
    max_y = max(p["y"] for p in pts)
    w = 1400.0
    h = 1400.0
    pad = 30.0
    sx = (w - 2 * pad) / max(1e-6, max_x - min_x)
    sy = (h - 2 * pad) / max(1e-6, max_y - min_y)
    s = min(sx, sy)

    def m(pt: dict) -> str:
        x = pad + (pt["x"] - min_x) * s
        y = h - (pad + (pt["y"] - min_y) * s)
        return f"{x:.2f},{y:.2f}"

    src_poly = " ".join(m(p) for p in src)
    rec_poly = " ".join(m(p) for p in rec)
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{int(w)}" height="{int(h)}" viewBox="0 0 {int(w)} {int(h)}">
  <rect x="0" y="0" width="{int(w)}" height="{int(h)}" fill="#111217"/>
  <polyline points="{src_poly}" fill="none" stroke="#ff5a5a" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>
  <polyline points="{rec_poly}" fill="none" stroke="#f4f4f4" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
  <rect x="20" y="20" width="460" height="80" rx="8" fill="#00000088"/>
  <text x="34" y="50" fill="#ff5a5a" font-family="Consolas, monospace" font-size="20">Source polyline</text>
  <text x="34" y="78" fill="#f4f4f4" font-family="Consolas, monospace" font-size="20">Reconstructed from L/R/S description</text>
</svg>
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def build_description(source_xy: list[dict], step: float, kappa: float, min_len: float, max_curve_rmse: float) -> dict:
    sampled = resample(source_xy, step)
    classes = classify_points(sampled, step, kappa)
    runs = runs_from_classes(classes, min_len=min_len, step=step)
    segs = segments_from_runs(sampled, runs, max_curve_rmse=max_curve_rmse)
    return evaluate(source_xy, segs)


def main() -> int:
    args = parse_args()
    data = json.loads(pathlib.Path(args.input).read_text(encoding="utf-8"))
    source_polyline = data.get("polyline", [])
    if not source_polyline:
        raise ValueError("Empty polyline")
    source_xy = to_xy_dicts(source_polyline)

    coarse = build_description(
        source_xy,
        step=args.step,
        kappa=args.coarse_kappa,
        min_len=args.coarse_min_len,
        max_curve_rmse=args.max_curve_rmse,
    )
    fine = build_description(
        source_xy,
        step=args.step,
        kappa=args.fine_kappa,
        min_len=args.fine_min_len,
        max_curve_rmse=args.max_curve_rmse,
    )

    chosen = coarse if coarse["rmse_dev"] <= fine["rmse_dev"] + 1.5 else fine
    chosen_name = "coarse" if chosen is coarse else "fine"

    out = {
        "source_points": len(source_xy),
        "settings": {
            "step": args.step,
            "coarse_kappa": args.coarse_kappa,
            "coarse_min_len": args.coarse_min_len,
            "fine_kappa": args.fine_kappa,
            "fine_min_len": args.fine_min_len,
            "max_curve_rmse": args.max_curve_rmse,
        },
        "coarse": {
            "segment_count": len(coarse["segments"]),
            "source_length_m": coarse["source_len"],
            "reconstructed_length_m": coarse["reconstructed_len"],
            "mean_deviation_m": coarse["mean_dev"],
            "rmse_deviation_m": coarse["rmse_dev"],
            "max_deviation_m": coarse["max_dev"],
            "sequence": segments_to_text(coarse["segments"]),
        },
        "fine": {
            "segment_count": len(fine["segments"]),
            "source_length_m": fine["source_len"],
            "reconstructed_length_m": fine["reconstructed_len"],
            "mean_deviation_m": fine["mean_dev"],
            "rmse_deviation_m": fine["rmse_dev"],
            "max_deviation_m": fine["max_dev"],
            "sequence": segments_to_text(fine["segments"]),
        },
        "chosen": chosen_name,
    }

    out_json = pathlib.Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(out, indent=2), encoding="utf-8")

    out_svg = pathlib.Path(args.output_svg)
    write_svg(out_svg, chosen["source_points"], chosen["recon_points"])

    print(f"Source points: {len(source_xy)}")
    print(f"Coarse: segments={len(coarse['segments'])}, rmse={coarse['rmse_dev']:.2f}m, max={coarse['max_dev']:.2f}m")
    print(f"Fine: segments={len(fine['segments'])}, rmse={fine['rmse_dev']:.2f}m, max={fine['max_dev']:.2f}m")
    print(f"Chosen profile: {chosen_name}")
    print(f"Wrote report: {out_json}")
    print(f"Wrote overlay: {out_svg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
