# /***************************************************************************
#
#     file                 : test_svg_to_centerline.py
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

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET

import pytest  # type: ignore[import-not-found]

import torcs_track_tools.cli.svg_to_centerline as svg_to_centerline
import torcs_track_tools.core.svg_geometry as svg_geometry
from torcs_track_tools.core.svg_geometry import apply_matrix, extract_candidates, parse_path, parse_points, parse_transform


def write_svg(path) -> None:
    path.write_text(
        """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">
  <g id="layout" transform="translate(10 20)">
    <g transform="scale(2)">
      <path id="main" class="circuit" d="M0 0 h100 v50 h-100 z"/>
      <polygon id="short" points="10,10 20,10 20,20 10,20"/>
    </g>
  </g>
  <path id="open" d="M0 0 L300 200"/>
</svg>
""".strip(),
        encoding="utf-8",
    )


def run_tool(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["torcs-svg-to-centerline", *args])
    return svg_to_centerline.main()


def test_path_parser_supports_lines_curves_quadratics_and_arcs() -> None:
    paths = parse_path(
        "M0 0 h20 v10 l-5 5 C10 20 5 20 0 15 S-10 10 0 5 Q5 0 10 5 T20 5 A10 10 0 0 1 30 15 L0 0 z",
        tolerance=0.1,
    )

    assert len(paths) == 1
    assert paths[0].closed
    assert len(paths[0].points) > 20
    assert all(math.isfinite(value) for point in paths[0].points for value in point)


def test_path_parser_rejects_unsupported_command() -> None:
    with pytest.raises(ValueError, match="Unsupported SVG path command"):
        parse_path("M0 0 R10 10 20 20 z", tolerance=0.5)


def test_curve_flattening_preserves_collinear_overshoot() -> None:
    cubic = parse_path("M0 0 C100 0 -100 0 10 0", tolerance=0.1)[0].points
    quadratic = parse_path("M0 0 Q100 0 10 0", tolerance=0.1)[0].points

    assert len(cubic) > 2
    assert max(point[0] for point in cubic) > 10.0
    assert min(point[0] for point in cubic) < 0.0
    assert len(quadratic) > 2
    assert max(point[0] for point in quadratic) > 10.0


def test_strict_grammars_reject_junk_and_invalid_arc_flags() -> None:
    with pytest.raises(ValueError, match="Malformed SVG path"):
        parse_path("M0 0 @ L10 0 z", tolerance=0.5)
    with pytest.raises(ValueError, match="Malformed SVG points"):
        parse_points("0,0 10,0 junk 10,10")
    with pytest.raises(ValueError, match="Malformed SVG transform"):
        parse_transform("translate(10 garbage 20)")
    with pytest.raises(ValueError, match="arc flag"):
        parse_path("M0 0 A10 10 0 2 0 10 10 z", tolerance=0.5)


def test_arc_parser_accepts_compact_flags() -> None:
    path = parse_path("M0 0 A10 10 0 0110 10 L0 0 z", tolerance=0.25)[0]

    assert path.closed
    assert any(point == pytest.approx((10.0, 10.0)) for point in path.points)


def test_transform_parser_applies_svg_order_and_rotation_center() -> None:
    assert apply_matrix(parse_transform("translate(10 20) scale(2)"), (1.0, 1.0)) == pytest.approx((12.0, 22.0))
    assert apply_matrix(parse_transform("rotate(90 10 10)"), (20.0, 10.0)) == pytest.approx((10.0, 20.0))
    assert apply_matrix(parse_transform("matrix(1 0 0 1 5 6)"), (2.0, 3.0)) == pytest.approx((7.0, 9.0))


def test_candidate_extraction_honors_nested_transforms_and_group_selection(tmp_path) -> None:
    svg = tmp_path / "layout.svg"
    write_svg(svg)
    root = ET.parse(svg).getroot()

    candidates = extract_candidates(root, "layout", tolerance=0.25)

    assert len(candidates) == 2
    main = max(candidates, key=lambda candidate: candidate.length)
    assert main.element_id == "main"
    assert main.element_class == "circuit"
    assert min(point[0] for point in main.points) == pytest.approx(10.0)
    assert max(point[0] for point in main.points) == pytest.approx(210.0)
    assert min(point[1] for point in main.points) == pytest.approx(20.0)
    assert max(point[1] for point in main.points) == pytest.approx(120.0)
    assert main.length == pytest.approx(600.0)


def test_default_extraction_skips_hidden_and_definition_geometry_but_resolves_use() -> None:
    root = ET.fromstring(
        """
<svg xmlns="http://www.w3.org/2000/svg">
  <style>.hidden { display:none; }</style>
  <defs><polygon id="template" points="0,0 20,0 20,20 0,20"/></defs>
  <polygon class="hidden" id="hidden" points="0,0 100,0 100,100 0,100"/>
  <polygon id="visible" points="0,0 5,0 5,5 0,5"/>
  <use href="#template" x="30" y="40"/>
</svg>
""".strip()
    )

    candidates = extract_candidates(root)

    assert [candidate.element_id for candidate in candidates] == ["visible", "template"]
    used = candidates[1]
    assert min(point[0] for point in used.points) == pytest.approx(30.0)
    assert min(point[1] for point in used.points) == pytest.approx(40.0)


def test_selected_group_keeps_independently_hidden_children_hidden() -> None:
    root = ET.fromstring(
        """
<svg>
  <g id="layout" style="display:none">
    <polygon id="visible" style="display:inline" points="0,0 10,0 10,10 0,10"/>
    <polygon id="helper" style="display:none" points="0,0 100,0 100,100 0,100"/>
  </g>
</svg>
""".strip()
    )

    candidates = extract_candidates(root, "layout")

    assert [candidate.element_id for candidate in candidates] == ["visible"]


def test_symbol_use_applies_instance_viewport() -> None:
    root = ET.fromstring(
        """
<svg>
  <defs>
    <symbol id="track-symbol" viewBox="0 0 10 10" preserveAspectRatio="none">
      <polygon id="track" points="0,0 10,0 10,10 0,10"/>
    </symbol>
  </defs>
  <use href="#track-symbol" x="5" y="7" width="100" height="50"/>
</svg>
""".strip()
    )

    candidate = extract_candidates(root)[0]

    assert min(point[0] for point in candidate.points) == pytest.approx(5.0)
    assert max(point[0] for point in candidate.points) == pytest.approx(105.0)
    assert min(point[1] for point in candidate.points) == pytest.approx(7.0)
    assert max(point[1] for point in candidate.points) == pytest.approx(57.0)


def test_percentage_root_viewport_uses_viewbox_dimensions() -> None:
    root = ET.fromstring(
        '<svg width="100%" height="100%" viewBox="0 0 100 50"><polygon points="0,0 100,0 100,50 0,50"/></svg>'
    )

    candidate = extract_candidates(root)[0]

    assert max(point[0] for point in candidate.points) == pytest.approx(100.0)
    assert max(point[1] for point in candidate.points) == pytest.approx(50.0)


def test_absolute_viewport_units_are_converted_to_css_pixels() -> None:
    root = ET.fromstring(
        '<svg width="25.4mm" height="1in" viewBox="0 0 96 96" preserveAspectRatio="none"><polygon points="0,0 96,0 96,96 0,96"/></svg>'
    )

    candidate = extract_candidates(root)[0]

    assert max(point[0] for point in candidate.points) == pytest.approx(96.0)
    assert max(point[1] for point in candidate.points) == pytest.approx(96.0)


def test_nested_percentage_viewport_is_rejected() -> None:
    root = ET.fromstring(
        '<svg viewBox="0 0 200 100"><svg x="50%" width="50%" viewBox="0 0 10 10"><polygon points="0,0 10,0 10,10 0,10"/></svg></svg>'
    )

    with pytest.raises(ValueError, match="known parent viewport"):
        extract_candidates(root)


def test_token_and_tree_limits_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svg_geometry, "MAX_PATH_TOKENS", 4)
    with pytest.raises(ValueError, match="token limit"):
        parse_path("M0 0 L10 0", tolerance=0.5)
    monkeypatch.setattr(svg_geometry, "MAX_PATH_TOKENS", 2_000_000)
    with pytest.raises(ValueError, match="remaining geometry limit"):
        parse_path("M0 0 L10 0 L10 10 Z M20 20 L30 20", tolerance=0.5, point_limit=3)

    monkeypatch.setattr(svg_geometry, "MAX_TREE_DEPTH", 2)
    root = ET.fromstring('<svg><g><g><g><polygon points="0,0 10,0 10,10 0,10"/></g></g></g></svg>')
    with pytest.raises(ValueError, match="traversal limit"):
        extract_candidates(root)


def test_nested_svg_viewport_preserves_nonuniform_none_scaling() -> None:
    root = ET.fromstring(
        """
<svg xmlns="http://www.w3.org/2000/svg">
  <svg id="nested" x="10" y="20" width="200" height="100" viewBox="0 0 100 100" preserveAspectRatio="none">
    <polygon id="track" points="0,0 100,0 100,100 0,100"/>
  </svg>
</svg>
""".strip()
    )

    candidate = extract_candidates(root, "nested")[0]

    assert min(point[0] for point in candidate.points) == pytest.approx(10.0)
    assert max(point[0] for point in candidate.points) == pytest.approx(210.0)
    assert min(point[1] for point in candidate.points) == pytest.approx(20.0)
    assert max(point[1] for point in candidate.points) == pytest.approx(120.0)


def test_curve_tolerance_is_measured_after_transform() -> None:
    unscaled = ET.fromstring('<svg><path d="M0 0 C0 100 100 100 100 0 L0 0 z"/></svg>')
    scaled = ET.fromstring('<svg><path transform="scale(100)" d="M0 0 C0 100 100 100 100 0 L0 0 z"/></svg>')

    base_points = len(extract_candidates(unscaled, tolerance=1.0)[0].points)
    scaled_points = len(extract_candidates(scaled, tolerance=1.0)[0].points)

    assert scaled_points > base_points


def test_cli_extracts_longest_closed_group_candidate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    svg = tmp_path / "layout.svg"
    output = tmp_path / "centerline.json"
    report = tmp_path / "report.json"
    preview = tmp_path / "preview.svg"
    write_svg(svg)

    assert run_tool(
        monkeypatch,
        "--input",
        str(svg),
        "--output",
        str(output),
        "--length-m",
        "1200",
        "--group-id",
        "layout",
        "--resample-step",
        "10",
        "--keep-start",
        "--report",
        str(report),
        "--preview-svg",
        str(preview),
    ) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == 2
    assert result["source"]["type"] == "svg-to-centerline"
    assert result["source"]["group_id"] == "layout"
    assert result["extraction"]["selected"]["element_id"] == "main"
    assert result["orientation"]["direction"] == "cw"
    assert result["length_m"] == pytest.approx(1200.0)
    assert len(result["polyline"]) == 120
    assert result["polyline"][0]["x"] == pytest.approx(0.0)
    assert result["polyline"][0]["y"] == pytest.approx(0.0)
    assert json.loads(report.read_text(encoding="utf-8"))["output_point_count"] == 120
    preview_root = ET.fromstring(preview.read_text(encoding="utf-8"))
    preview_line = preview_root.find("{http://www.w3.org/2000/svg}polyline")
    assert preview_line is not None
    assert preview_line.get("id") == "centerline"


def test_cli_element_selection_and_reverse_change_direction(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    svg = tmp_path / "layout.svg"
    output = tmp_path / "short.json"
    write_svg(svg)

    assert run_tool(
        monkeypatch,
        "--input",
        str(svg),
        "--output",
        str(output),
        "--length-m",
        "400",
        "--element-id",
        "short",
        "--reverse",
        "--keep-start",
    ) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["extraction"]["selected"]["element_id"] == "short"
    assert result["orientation"]["direction"] == "ccw"
    assert result["length_m"] == pytest.approx(400.0)


def test_cli_can_choose_start_near_transformed_svg_coordinate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    svg = tmp_path / "layout.svg"
    output = tmp_path / "start.json"
    write_svg(svg)

    assert run_tool(
        monkeypatch,
        "--input",
        str(svg),
        "--output",
        str(output),
        "--length-m",
        "600",
        "--element-id",
        "main",
        "--start",
        "210,120",
    ) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["extraction"]["source_start_index"] == 2
    assert result["polyline"][0]["x"] == pytest.approx(0.0)
    assert result["polyline"][0]["y"] == pytest.approx(0.0)


def test_cli_projects_requested_start_onto_segment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    svg = tmp_path / "layout.svg"
    output = tmp_path / "projected-start.json"
    write_svg(svg)

    assert run_tool(
        monkeypatch,
        "--input",
        str(svg),
        "--output",
        str(output),
        "--length-m",
        "600",
        "--element-id",
        "main",
        "--start",
        "110,20",
        "--keep-svg-y",
    ) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["extraction"]["selected_start_svg"] == pytest.approx({"x": 110.0, "y": 20.0})
    assert result["extraction"]["start_snap_distance_svg_units"] == pytest.approx(0.0)
    assert result["polyline"][0]["x"] == pytest.approx(0.0)
    assert result["polyline"][0]["y"] == pytest.approx(0.0)


def test_candidate_index_uses_all_candidate_report_space(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    svg = tmp_path / "indices.svg"
    output = tmp_path / "indices.json"
    svg.write_text('<svg><path d="M0 0 L20 0"/><polygon points="0,0 10,0 10,10 0,10"/></svg>', encoding="utf-8")

    with pytest.raises(SystemExit, match="does not identify a usable closed"):
        run_tool(monkeypatch, "--input", str(svg), "--output", str(output), "--length-m", "100", "--candidate-index", "0")
    assert run_tool(monkeypatch, "--input", str(svg), "--output", str(output), "--length-m", "100", "--candidate-index", "1") == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["source"]["candidate_index"] == 1
    assert result["source"]["closed_candidate_index"] == 0


def test_cli_rejects_nonfinite_values(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    svg = tmp_path / "layout.svg"
    output = tmp_path / "invalid.json"
    write_svg(svg)

    with pytest.raises(SystemExit, match="--length-m must be positive"):
        run_tool(monkeypatch, "--input", str(svg), "--output", str(output), "--length-m", "nan")
    with pytest.raises(SystemExit, match="--start-window must not exceed 1000"):
        run_tool(monkeypatch, "--input", str(svg), "--output", str(output), "--length-m", "100", "--start-window", "1001")


def test_cli_rejects_selection_without_closed_geometry(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    svg = tmp_path / "layout.svg"
    output = tmp_path / "open.json"
    write_svg(svg)

    with pytest.raises(SystemExit, match="no usable closed"):
        run_tool(monkeypatch, "--input", str(svg), "--output", str(output), "--length-m", "100", "--element-id", "open")
