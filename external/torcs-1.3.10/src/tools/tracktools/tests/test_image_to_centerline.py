#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : test_image_to_centerline.py
#     created              : 29 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/

from __future__ import annotations

import json
import math

from PIL import Image, ImageDraw

import torcs_track_tools.cli.image_to_centerline as image_to_centerline


def test_image_to_centerline_extracts_scaled_red_loop(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "map.png"
    output_path = tmp_path / "centerline.json"
    preview_path = tmp_path / "preview.svg"

    img = Image.new("RGB", (160, 120), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse((25, 20, 135, 100), outline=(255, 0, 0), width=3)
    draw.text((5, 5), "label", fill=(255, 160, 0))
    img.save(image_path)

    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-image-to-centerline",
            "--input",
            str(image_path),
            "--output",
            str(output_path),
            "--length-m",
            "1000",
            "--preview-svg",
            str(preview_path),
            "--resample-step",
            "10",
            "--close-gap-px",
            "1",
            "--min-component-area",
            "50",
        ],
    )

    assert image_to_centerline.main() == 0

    obj = json.loads(output_path.read_text(encoding="utf-8"))
    points = obj["polyline"]
    assert len(points) == 100
    assert obj["source"] == "image-to-centerline"
    assert preview_path.exists()
    length = sum(
        math.hypot(
            points[(i + 1) % len(points)]["x"] - points[i]["x"],
            points[(i + 1) % len(points)]["y"] - points[i]["y"],
        )
        for i in range(len(points))
    )
    assert abs(length - 1000.0) < 1.0


def test_ridge_extractor_reports_subpixel_refinement(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "map.png"
    output_path = tmp_path / "centerline.json"

    img = Image.new("RGB", (120, 90), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse((20, 15, 100, 75), outline=(255, 0, 0), width=5)
    img.save(image_path)

    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-image-to-centerline",
            "--input",
            str(image_path),
            "--output",
            str(output_path),
            "--length-m",
            "800",
            "--resample-step",
            "10",
            "--extractor",
            "ridge",
            "--ridge-min-strength",
            "0.005",
            "--min-component-area",
            "30",
        ],
    )

    assert image_to_centerline.main() == 0

    extraction = json.loads(output_path.read_text(encoding="utf-8"))["extraction"]
    assert extraction["extractor"] == "ridge"
    assert extraction["ridge_refined_points"] > 0
    assert extraction["ridge_max_offset_px"] <= 1.25


def test_ridge_link_extractor_traces_direct_ridge_candidates(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "map.png"
    output_path = tmp_path / "centerline.json"

    img = Image.new("RGB", (120, 90), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse((20, 15, 100, 75), outline=(255, 0, 0), width=5)
    img.save(image_path)

    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-image-to-centerline",
            "--input",
            str(image_path),
            "--output",
            str(output_path),
            "--length-m",
            "800",
            "--resample-step",
            "10",
            "--extractor",
            "ridge-link",
            "--ridge-min-strength",
            "0.005",
            "--min-component-area",
            "30",
        ],
    )

    assert image_to_centerline.main() == 0

    obj = json.loads(output_path.read_text(encoding="utf-8"))
    extraction = obj["extraction"]
    assert extraction["extractor"] == "ridge-link"
    assert extraction["ridge_candidate_points"] > 0
    assert len(obj["polyline"]) == 80


def test_antialias_ridge_profile_sets_stable_defaults(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "map.png"
    output_path = tmp_path / "centerline.json"

    img = Image.new("RGB", (120, 90), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse((20, 15, 100, 75), outline=(255, 0, 0), width=5)
    img.save(image_path)

    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-image-to-centerline",
            "--profile",
            "antialias-ridge",
            "--input",
            str(image_path),
            "--output",
            str(output_path),
            "--length-m",
            "800",
            "--min-component-area",
            "30",
        ],
    )

    assert image_to_centerline.main() == 0

    obj = json.loads(output_path.read_text(encoding="utf-8"))
    extraction = obj["extraction"]
    assert extraction["extractor"] == "ridge-link"
    assert extraction["ridge_candidate_points"] > 0
    assert len(obj["polyline"]) == 400


def test_zurich_style_skimage_map_profile_extracts_cyan_loop(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "zurich-style.png"
    output_path = tmp_path / "centerline.json"

    img = Image.new("RGB", (180, 110), "white")
    draw = ImageDraw.Draw(img)
    # Cyan stroke like the Zurich source image; the profile behavior is what this
    # test covers, while corner preservation is tested in the fitter tests.
    draw.ellipse((18, 18, 162, 92), outline=(0, 220, 255), width=5)
    img.save(image_path)

    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-image-to-centerline",
            "--profile",
            "skimage-map",
            "--track-color",
            "custom",
            "--rgb",
            "0,220,255",
            "--color-tolerance",
            "30",
            "--input",
            str(image_path),
            "--output",
            str(output_path),
            "--length-m",
            "2460",
            "--max-seam-gap-px",
            "30",
            "--min-component-area",
            "30",
        ],
    )

    assert image_to_centerline.main() == 0

    obj = json.loads(output_path.read_text(encoding="utf-8"))
    extraction = obj["extraction"]
    assert extraction["extractor"] == "skimage-skeleton"
    assert extraction["skeleton_pixels"] > 0
    assert abs(extraction["output_length_m"] - 2460.0) < 1.0


def test_steger_refine_loop_moves_points_toward_subpixel_ridge() -> None:
    width = 30
    height = 20
    ridge_y = 9.35
    probability = []
    for y in range(height):
        row = []
        for _ in range(width):
            row.append(math.exp(-((y - ridge_y) ** 2) / (2.0 * 1.2 * 1.2)))
        probability.append(row)
    pixel_loop = [(x, 9) for x in range(3, 27)]

    refined, stats = image_to_centerline.steger_refine_loop(pixel_loop, probability, sigma=0.8, min_strength=0.005, max_offset=1.0)

    assert stats["ridge_refined_points"] == len(pixel_loop)
    mean_y = sum(y for _, y in refined) / len(refined)
    assert 9.1 < mean_y < 9.6
    assert mean_y > 9.0


def test_steger_candidate_map_detects_synthetic_ridge() -> None:
    width = 30
    height = 20
    ridge_y = 9.35
    probability = []
    for y in range(height):
        row = []
        for _ in range(width):
            row.append(math.exp(-((y - ridge_y) ** 2) / (2.0 * 1.2 * 1.2)))
        probability.append(row)

    candidates, stats = image_to_centerline.steger_candidate_map(probability, sigma=0.8, min_strength=0.005, max_offset=1.0)

    assert stats["ridge_candidate_points"] > 0
    mean_y = sum(y for _, y in candidates.values()) / len(candidates)
    assert 9.1 < mean_y < 9.6


def test_parse_crop_rejects_bad_shape() -> None:
    try:
        image_to_centerline.parse_crop("1,2,3")
    except SystemExit as exc:
        assert "--crop" in str(exc)
    else:
        raise AssertionError("Expected SystemExit")


def test_adaptive_smoothing_preserves_sharp_corner_better_than_uniform() -> None:
    points = [
        (0.0, 0.0),
        (10.0, 1.0),
        (20.0, -1.0),
        (30.0, 1.0),
        (40.0, -1.0),
        (50.0, 0.0),
        (50.0, 10.0),
        (50.0, 20.0),
        (50.0, 30.0),
        (50.0, 40.0),
        (40.0, 40.0),
        (30.0, 40.0),
        (20.0, 40.0),
        (10.0, 40.0),
        (0.0, 40.0),
        (0.0, 30.0),
        (0.0, 20.0),
        (0.0, 10.0),
    ]

    uniform = image_to_centerline.smooth_closed(points, window=9, rounds=1)
    adaptive = image_to_centerline.smooth_closed(points, window=9, rounds=1, adaptive=True, preserve_curvature_deg=20.0, curvature_window=2)

    corner = points[5]
    uniform_corner_move = math.hypot(uniform[5][0] - corner[0], uniform[5][1] - corner[1])
    adaptive_corner_move = math.hypot(adaptive[5][0] - corner[0], adaptive[5][1] - corner[1])

    assert adaptive_corner_move < uniform_corner_move
