# /***************************************************************************
#
#     file                 : test_rebuild_mainline.py
#     created              : 27 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

import json
import math
import pathlib
import subprocess
import xml.etree.ElementTree as ET
from argparse import Namespace

import pytest

import torcs_track_tools.cli.rebuild_mainline as rebuild_mainline
from torcs_track_tools.cli.rebuild_mainline import (
    DEFAULT_EXPAND_CANDIDATES_OBJECTIVE,
    DEFAULT_MAX_BASELINE_ANG,
    DP_EXPAND_CANDIDATES_OBJECTIVE,
    baseline_limit_args,
    baseline_objective,
    candidate_validation_batches,
    default_track_name,
    parse_segments_snippet,
    reverse_segments_xml,
    should_expand_before_closure,
)


def write_minimal_segments(path: pathlib.Path) -> None:
    path.write_text(
        """
			<section name="Main Straight">
				<attstr name="type" val="str"/>
				<attnum name="lg" unit="m" val="50.0"/>
			</section>
""".strip(),
        encoding="utf-8",
    )


def configure_rebuild_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    *extra_args: str,
    include_author: bool = True,
) -> tuple[pathlib.Path, pathlib.Path]:
    input_json = tmp_path / "centerline-osm.json"
    input_json.write_text('{"polyline": []}', encoding="utf-8")
    template_xml = tmp_path / "template.xml"
    template_xml.write_text("<params></params>\n", encoding="utf-8")
    output_xml = tmp_path / "runtime" / "tracks" / "road" / "unit-track" / "unit-track.xml"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "trackgen.exe").write_text("", encoding="utf-8")
    author_args = ["--author", "Test Author"] if include_author else []
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-rebuild-mainline",
            "--input",
            str(input_json),
            "--template-xml",
            str(template_xml),
            "--output-track-xml",
            str(output_xml),
            *author_args,
            *extra_args,
        ],
    )
    return input_json, output_xml


def test_baseline_objective_prioritizes_lower_closure_error() -> None:
    rough = {"delta_x": 2.0, "delta_y": 2.0, "delta_ang_deg": 0.2}
    better = {"delta_x": 1.0, "delta_y": 1.0, "delta_ang_deg": 0.05}

    assert baseline_objective(better) < baseline_objective(rough)


def test_baseline_limit_args_forwards_relaxed_angle_gate() -> None:
    assert baseline_limit_args(3.0) == ["--max-baseline-ang", "3.0"]


def test_default_baseline_angle_allows_large_but_closable_seams() -> None:
    assert DEFAULT_MAX_BASELINE_ANG == 10.0


def test_dp_default_expands_candidate_search_for_moderate_objectives(monkeypatch, tmp_path) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path)

    args = rebuild_mainline.parse_args()

    assert args.expand_candidates_objective == DP_EXPAND_CANDIDATES_OBJECTIVE


def test_legacy_polyline_keeps_old_candidate_expansion_threshold(monkeypatch, tmp_path) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--segment-fitter", "polyline")

    args = rebuild_mainline.parse_args()

    assert args.expand_candidates_objective == DEFAULT_EXPAND_CANDIDATES_OBJECTIVE


def test_default_track_name_title_cases_slug() -> None:
    assert default_track_name("yas-marina") == "Yas Marina"
    assert default_track_name("road_america") == "Road America"


def test_rebuild_helper_defaults_and_path_guards(monkeypatch, tmp_path) -> None:
    assert rebuild_mainline.default_description(" Test Track ") == "Test Track track layout generated for TORCS."
    assert rebuild_mainline.default_description("  ") == "Track layout generated for TORCS."
    assert rebuild_mainline.bundled_template_path(pathlib.Path("tools")) == pathlib.Path("templates") / "road-track-template.xml"
    assert rebuild_mainline.starts_with_runtime(pathlib.Path("runtime") / "tracks")
    assert not rebuild_mainline.starts_with_runtime(pathlib.Path("tracks") / "road")

    runtime, category, name = rebuild_mainline.derive_runtime_context(
        pathlib.Path("repo") / "runtime" / "tracks" / "road" / "unit" / "unit.xml"
    )
    assert runtime == pathlib.Path("repo") / "runtime"
    assert category == "road"
    assert name == "unit"

    with pytest.raises(RuntimeError, match="auto-detect"):
        rebuild_mainline.derive_runtime_context(pathlib.Path("unit.xml"))
    with pytest.raises(RuntimeError, match="Track path"):
        rebuild_mainline.derive_runtime_context(pathlib.Path("runtime") / "tracks" / "road")

    runtime_cwd = tmp_path / "runtime"
    runtime_cwd.mkdir()
    monkeypatch.chdir(runtime_cwd)
    with pytest.raises(SystemExit, match="Path style mismatch"):
        rebuild_mainline.validate_path_style(pathlib.Path("runtime") / "source.json", pathlib.Path("tracks") / "road" / "unit" / "unit.xml", runtime_cwd)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="nested runtime"):
        rebuild_mainline.validate_path_style(pathlib.Path("source.json"), pathlib.Path("runtime") / "runtime" / "tracks" / "road" / "unit" / "unit.xml", runtime_cwd)


def test_run_or_print_skips_subprocess_in_dry_run(monkeypatch, capsys) -> None:
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(rebuild_mainline.subprocess, "run", lambda cmd, check=True: calls.append((cmd, check)))

    rebuild_mainline.run_or_print(["tool", "--flag"], dry_run=True)
    assert calls == []
    assert "tool --flag" in capsys.readouterr().out

    rebuild_mainline.run_or_print(["tool", "--flag"], dry_run=False)
    assert calls == [(["tool", "--flag"], True)]


def test_real_rebuild_requires_author(monkeypatch, tmp_path) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, include_author=False)

    with pytest.raises(SystemExit, match="real track author"):
        rebuild_mainline.main()


def test_real_rebuild_rejects_placeholder_author(monkeypatch, tmp_path) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--author", "OpenCode", include_author=False)

    with pytest.raises(SystemExit, match="placeholder authors"):
        rebuild_mainline.main()


def test_reverse_segments_xml_swaps_order_direction_and_radius(tmp_path) -> None:
    src = tmp_path / "segments.xml"
    dst = tmp_path / "segments-reversed.xml"
    src.write_text(
        """
			<section name="straight">
				<attstr name="type" val="str"/>
				<attnum name="lg" unit="m" val="20.0"/>
			</section>
			<section name="turn">
				<attstr name="type" val="lft"/>
				<attnum name="radius" unit="m" val="40.0"/>
				<attnum name="end radius" unit="m" val="60.0"/>
				<attnum name="arc" unit="deg" val="10.0"/>
			</section>
""".strip(),
        encoding="utf-8",
    )

    reverse_segments_xml(src, dst)
    segs = parse_segments_snippet(dst)

    assert [seg.get("name") for seg in segs] == ["turn", "straight"]
    attrs = {child.get("name"): child.get("val") for child in segs[0]}
    assert attrs["type"] == "rgt"
    assert attrs["radius"] == "60.0"
    assert attrs["end radius"] == "40.0"


def test_reverse_segments_json_handles_dict_list_and_copy_fallback(tmp_path) -> None:
    src = tmp_path / "segments.json"
    dst = tmp_path / "segments-reversed.json"
    src.write_text(
        json.dumps(
            {
                "segments": [
                    {"name": "straight", "type": "str", "source_i0": 0, "source_i1": 1},
                    {"name": "left", "type": "lft", "radius": 40.0, "end_radius": 60.0, "source_i0": 1, "source_i1": 2},
                    {"name": "right", "type": "rgt"},
                ],
                "meta": "kept",
            }
        ),
        encoding="utf-8",
    )

    rebuild_mainline.reverse_segments_json(src, dst)
    obj = json.loads(dst.read_text(encoding="utf-8"))

    assert obj["reversed_by_tracktools"] is True
    assert obj["meta"] == "kept"
    assert [seg["name"] for seg in obj["segments"]] == ["right", "left", "straight"]
    assert obj["segments"][0]["type"] == "lft"
    assert obj["segments"][1]["type"] == "rgt"
    assert obj["segments"][1]["radius"] == 60.0
    assert obj["segments"][1]["end_radius"] == 40.0
    assert obj["segments"][1]["source_i0"] == 2
    assert obj["segments"][1]["source_i1"] == 1

    list_src = tmp_path / "segments-list.json"
    list_dst = tmp_path / "segments-list-reversed.json"
    list_src.write_text(json.dumps([{"name": "a"}, {"name": "b"}]), encoding="utf-8")
    rebuild_mainline.reverse_segments_json(list_src, list_dst)
    assert json.loads(list_dst.read_text(encoding="utf-8")) == [{"name": "b"}, {"name": "a"}]

    fallback_src = tmp_path / "segments-fallback.json"
    fallback_dst = tmp_path / "segments-fallback-reversed.json"
    fallback_src.write_text(json.dumps({"segments": "not-a-list"}), encoding="utf-8")
    rebuild_mainline.reverse_segments_json(fallback_src, fallback_dst)
    assert fallback_dst.read_text(encoding="utf-8") == fallback_src.read_text(encoding="utf-8")


def test_segment_pose_helpers_cover_defaults_turns_and_unknowns() -> None:
    bad = ET.Element("section")
    ET.SubElement(bad, "attnum", {"name": "lg", "val": "bad"})
    assert rebuild_mainline.get_attnum(bad, "lg", 12.0) == 12.0
    assert rebuild_mainline.get_attnum(bad, "missing", 3.0) == 3.0

    straight = ET.fromstring('<section name="str"><attstr name="type" val="str"/><attnum name="lg" val="10"/></section>')
    left = ET.fromstring('<section name="lft"><attstr name="type" val="lft"/><attnum name="radius" val="10"/><attnum name="arc" val="90"/></section>')
    right = ET.fromstring('<section name="rgt"><attstr name="type" val="rgt"/><attnum name="radius" val="10"/><attnum name="arc" val="90"/></section>')
    unknown = ET.fromstring('<section name="unknown"><attstr name="type" val="weird"/></section>')

    assert rebuild_mainline.norm_angle(3.0 * math.pi) == pytest.approx(math.pi)
    assert rebuild_mainline.norm_angle(-3.0 * math.pi) == pytest.approx(-math.pi)
    assert rebuild_mainline.simulate_segment_end(0.0, 0.0, 0.0, straight) == pytest.approx((10.0, 0.0, 0.0))
    assert rebuild_mainline.simulate_segment_end(0.0, 0.0, 0.0, left) == pytest.approx((10.0, 10.0, math.pi / 2.0))
    assert rebuild_mainline.simulate_segment_end(0.0, 0.0, 0.0, right) == pytest.approx((10.0, -10.0, -math.pi / 2.0))
    assert rebuild_mainline.simulate_segment_end(1.0, 2.0, 3.0, unknown) == pytest.approx((1.0, 2.0, 3.0))


def test_candidate_validation_batches_stages_initial_candidates() -> None:
    candidates = ["a", "b", "c", "d", "e"]

    assert candidate_validation_batches(candidates, initial_count=2, exhaustive=False) == [["a", "b"], ["c", "d", "e"]]


def test_candidate_validation_batches_keeps_at_least_one_initial_candidate() -> None:
    candidates = ["a", "b", "c"]

    assert candidate_validation_batches(candidates, initial_count=0, exhaustive=False) == [["a"], ["b", "c"]]


def test_candidate_validation_batches_exhaustive_keeps_single_batch() -> None:
    candidates = ["a", "b", "c"]

    assert candidate_validation_batches(candidates, initial_count=1, exhaustive=True) == [candidates]


def test_should_expand_before_closure_for_high_initial_objective() -> None:
    ready = [{"objective": 30.0}, {"objective": 35.0}]

    assert should_expand_before_closure(ready, batch_index=1, batch_count=2, objective_threshold=28.0)


def test_should_not_expand_before_closure_for_good_initial_objective() -> None:
    ready = [{"objective": 25.0}, {"objective": 35.0}]

    assert not should_expand_before_closure(ready, batch_index=1, batch_count=2, objective_threshold=28.0)


def test_seam_report_selection_and_fit_cache_validation(tmp_path) -> None:
    original = "source.json"
    prepared = tmp_path / "prepared.json"
    report = tmp_path / "seam-report.json"

    assert rebuild_mainline.choose_fit_input_from_seam_report(original, prepared, report) == str(prepared)
    report.write_text('{"repair_applied": false}', encoding="utf-8")
    assert rebuild_mainline.choose_fit_input_from_seam_report(original, prepared, report) == original
    report.write_text('{"repair_applied": true}', encoding="utf-8")
    assert rebuild_mainline.choose_fit_input_from_seam_report(original, prepared, report) == str(prepared)

    output = tmp_path / "segments.xml"
    meta = tmp_path / "segments.cache.json"
    key = {"schema": 2, "value": "expected"}
    assert not rebuild_mainline.fit_cache_valid(meta, key, [output])
    output.write_text("segments", encoding="utf-8")
    assert not rebuild_mainline.fit_cache_valid(meta, key, [output])
    meta.write_text("not-json", encoding="utf-8")
    assert not rebuild_mainline.fit_cache_valid(meta, key, [output])
    meta.write_text(json.dumps({"schema": 2, "value": "other"}), encoding="utf-8")
    assert not rebuild_mainline.fit_cache_valid(meta, key, [output])
    meta.write_text(json.dumps(key), encoding="utf-8")
    assert rebuild_mainline.fit_cache_valid(meta, key, [output])


def test_build_fit_input_candidates_orders_polyline_fallbacks(tmp_path) -> None:
    original = tmp_path / "source.json"
    prepared = tmp_path / "prepared.json"
    report = tmp_path / "seam-report.json"
    original.write_text("{}", encoding="utf-8")
    prepared.write_text("{}", encoding="utf-8")
    report.write_text(json.dumps({"repair_applied": False}), encoding="utf-8")
    args = Namespace(segment_fitter=rebuild_mainline.SEGMENT_FITTER_POLYLINE)

    assert rebuild_mainline.build_fit_input_candidates(args, original, prepared, report) == [
        ("stable", str(original), False),
        ("prepared-tail", str(prepared), True),
        ("prepared", str(prepared), False),
        ("tail", str(original), True),
    ]


def test_dry_run_forwards_min_segment_length_and_baseline_angle(monkeypatch, tmp_path, capsys) -> None:
    configure_rebuild_argv(
        monkeypatch,
        tmp_path,
        "--dry-run",
        "--min-seg-len",
        "20",
        "--max-baseline-ang",
        "7",
    )

    assert rebuild_mainline.main() == 0

    out = capsys.readouterr().out
    assert "draft_segments.py" in out
    assert "polyline_to_torcs.py" not in out
    assert "--min-seg-len 20.0" in out
    assert "--max-baseline-ang 7.0" in out
    assert "--linear-polish" in out
    assert "--segment-name-prefix segment" not in out
    assert "adjust_side_clearance.py" in out
    assert "side-clearance-report.json" in out
    assert "adjust_side_overlap.py" in out
    assert "side-overlap-report.json" in out


def test_dry_run_can_request_generic_segment_names(monkeypatch, tmp_path, capsys) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--dry-run", "--segment-name-prefix", "segment")

    assert rebuild_mainline.main() == 0

    out = capsys.readouterr().out
    assert "--segment-name-prefix segment" in out


def test_dry_run_can_skip_side_clearance_adjustment(monkeypatch, tmp_path, capsys) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--dry-run", "--no-adjust-side-clearance")

    assert rebuild_mainline.main() == 0

    out = capsys.readouterr().out
    assert "adjust_side_clearance.py" not in out
    assert "adjust-side-clearance: skipped" in out


def test_dry_run_can_skip_side_overlap_adjustment(monkeypatch, tmp_path, capsys) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--dry-run", "--no-adjust-side-overlap")

    assert rebuild_mainline.main() == 0

    out = capsys.readouterr().out
    assert "adjust_side_overlap.py" not in out
    assert "adjust-side-overlap: skipped" in out


def test_dry_run_can_use_legacy_polyline_fitter(monkeypatch, tmp_path, capsys) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--dry-run", "--segment-fitter", "polyline")

    assert rebuild_mainline.main() == 0

    out = capsys.readouterr().out
    assert "polyline_to_torcs.py" in out
    assert "draft_segments.py" not in out
    assert "--resample-step 3.0" in out
    assert "--min-seg-len 10.0" in out
    assert "--linear-polish" not in out


def test_drawing_profile_applies_detail_preserving_fit_defaults(monkeypatch, tmp_path) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--profile", "drawing")

    args = rebuild_mainline.parse_args()

    assert args.segment_fitter == "dp-biarc"
    assert args.resample_step == 4.0
    assert args.min_seg_len == 12.0
    assert args.max_seg_len == 180.0
    assert args.target_dy == 0.001
    assert args.linear_polish
    assert not args.cleanup_small_wiggles


def test_legacy_polyline_drawing_profile_keeps_old_defaults(monkeypatch, tmp_path) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--segment-fitter", "polyline", "--profile", "drawing")

    args = rebuild_mainline.parse_args()

    assert args.resample_step == 5.0
    assert args.straight_heading_deg == 5.0
    assert args.min_seg_len == 20.0
    assert args.fit_pos_threshold == 6.0
    assert args.beam_width == 10
    assert args.target_dy == 0.002
    assert args.cleanup_small_wiggles


def test_drawing_profile_keeps_explicit_overrides(monkeypatch, tmp_path) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--profile", "drawing", "--resample-step", "4", "--target-dy", "0.001")

    args = rebuild_mainline.parse_args()

    assert args.resample_step == 4.0
    assert args.target_dy == 0.001
    assert args.beam_width == 6


def test_drawing_detail_profile_lowers_segment_minimum(monkeypatch, tmp_path) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--profile", "drawing-detail")

    args = rebuild_mainline.parse_args()

    assert args.resample_step == 4.0
    assert args.min_seg_len == 10.0
    assert args.max_seg_len == 180.0
    assert not args.cleanup_small_wiggles


def test_corner_fit_options_change_fit_cache_key(monkeypatch, tmp_path) -> None:
    input_json, _ = configure_rebuild_argv(
        monkeypatch,
        tmp_path,
        "--segment-fitter",
        "polyline",
        "--corner-fit",
        "--corner-tolerance",
        "3",
        "--corner-trim-max",
        "4",
    )
    args = rebuild_mainline.parse_args()

    corner_key = rebuild_mainline.fit_cache_key(args, input_json, preserve_tail=False)

    configure_rebuild_argv(
        monkeypatch,
        tmp_path,
        "--segment-fitter",
        "polyline",
        "--corner-fit",
        "--corner-tolerance",
        "3",
        "--corner-trim-max",
        "12",
    )
    args = rebuild_mainline.parse_args()
    different_trim_key = rebuild_mainline.fit_cache_key(args, input_json, preserve_tail=False)

    configure_rebuild_argv(monkeypatch, tmp_path, "--segment-fitter", "polyline")
    args = rebuild_mainline.parse_args()
    normal_key = rebuild_mainline.fit_cache_key(args, input_json, preserve_tail=False)

    assert corner_key != different_trim_key
    assert corner_key != normal_key
    assert corner_key["segment_fitter"] == "polyline"
    assert corner_key["params"]["corner_fit"] is True
    assert corner_key["params"]["corner_tolerance"] == 3.0
    assert corner_key["params"]["corner_trim_max"] == 4.0


def test_rebuild_forwards_corner_fit_and_linear_polish_in_dry_run(monkeypatch, tmp_path, capsys) -> None:
    configure_rebuild_argv(
        monkeypatch,
        tmp_path,
        "--dry-run",
        "--segment-fitter",
        "polyline",
        "--corner-fit",
        "--corner-tolerance",
        "3",
        "--corner-trim-max",
        "4",
        "--linear-polish",
    )

    assert rebuild_mainline.main() == 0

    out = capsys.readouterr().out
    assert "--corner-fit" in out
    assert "--corner-tolerance 3.0" in out
    assert "--corner-trim-max 4.0" in out
    assert "--linear-polish" in out


def test_dry_run_can_use_geometric_closure_solver(monkeypatch, tmp_path, capsys) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--dry-run", "--closure-solver", "geometric")

    assert rebuild_mainline.main() == 0

    out = capsys.readouterr().out
    assert "Closure solver: geometric" in out
    assert "close_loop_geometric.py" in out
    assert "--source-polyline" in out
    assert "--comparison-svg" in out
    assert "select-controls" not in out


def test_dry_run_can_plan_curb_placement_and_post_curb_closure(monkeypatch, tmp_path, capsys) -> None:
    configure_rebuild_argv(monkeypatch, tmp_path, "--dry-run", "--closure-solver", "geometric", "--place-curbs", "--curb-placement", "outside")

    assert rebuild_mainline.main() == 0

    out = capsys.readouterr().out
    assert "Curb placement: enabled (outside)" in out
    assert "place_curbs.py" in out
    assert "--placement outside" in out
    assert "curb-placement-report.json" in out
    assert "closure-report-curbs-geometric.json" in out
    assert "close-loop-curbs: planned" in out


def test_successful_closure_promotes_staging_xml(monkeypatch, tmp_path) -> None:
    _, output_xml = configure_rebuild_argv(monkeypatch, tmp_path)

    def fake_run(cmd, check=True, timeout=None):  # noqa: ARG001
        _ = timeout
        command = [str(part) for part in cmd]
        script = pathlib.Path(command[1]).name
        if script == "prepare_loop_polyline.py":
            pathlib.Path(command[command.index("--report") + 1]).write_text('{"repair_applied": false}', encoding="utf-8")
        elif script == "draft_segments.py":
            pathlib.Path(command[command.index("--output-json") + 1]).write_text('{"segments": []}', encoding="utf-8")
            write_minimal_segments(pathlib.Path(command[command.index("--output-xml") + 1]))
            pathlib.Path(command[command.index("--output-svg") + 1]).write_text("<svg />", encoding="utf-8")
        elif script == "apply_segments.py":
            pathlib.Path(command[command.index("--output-xml") + 1]).write_text("<track>candidate</track>", encoding="utf-8")
        elif script == "close_loop.py" and "--baseline-only" in command:
            pathlib.Path(command[command.index("--report") + 1]).write_text(
                '{"baseline_ready": true, "final_metrics": {"delta_x": 0.0, "delta_y": 0.0, "delta_ang_deg": 0.0}}',
                encoding="utf-8",
            )
        elif script == "close_loop.py" and "--select-only" not in command:
            pathlib.Path(command[command.index("--track-xml") + 1]).write_text("<track>closed</track>", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(rebuild_mainline.subprocess, "run", fake_run)

    assert rebuild_mainline.main() == 0
    assert output_xml.read_text(encoding="utf-8") == "<track>closed</track>"
    readme = output_xml.parent / "readme.txt"
    assert "Test Author" in readme.read_text(encoding="utf-8")
    assert "License: GNU General Public License version 2 or later" in readme.read_text(encoding="utf-8")
    assert "Generation commands:" in readme.read_text(encoding="utf-8")


def test_successful_geometric_closure_promotes_staging_xml(monkeypatch, tmp_path) -> None:
    _, output_xml = configure_rebuild_argv(monkeypatch, tmp_path, "--closure-solver", "geometric")

    def fake_run(cmd, check=True, timeout=None):  # noqa: ARG001
        _ = timeout
        command = [str(part) for part in cmd]
        script = pathlib.Path(command[1]).name
        if script == "prepare_loop_polyline.py":
            pathlib.Path(command[command.index("--report") + 1]).write_text('{"repair_applied": false}', encoding="utf-8")
        elif script == "draft_segments.py":
            pathlib.Path(command[command.index("--output-json") + 1]).write_text('{"segments": []}', encoding="utf-8")
            write_minimal_segments(pathlib.Path(command[command.index("--output-xml") + 1]))
            pathlib.Path(command[command.index("--output-svg") + 1]).write_text("<svg />", encoding="utf-8")
        elif script == "apply_segments.py":
            pathlib.Path(command[command.index("--output-xml") + 1]).write_text("<track>candidate</track>", encoding="utf-8")
        elif script == "close_loop.py":
            raise AssertionError("geometric closure should not invoke legacy close_loop.py")
        elif script == "close_loop_geometric.py":
            pathlib.Path(command[command.index("--track-xml") + 1]).write_text("<track>closed-geometric</track>", encoding="utf-8")
            pathlib.Path(command[command.index("--report") + 1]).write_text('{"ok": true}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(rebuild_mainline.subprocess, "run", fake_run)

    assert rebuild_mainline.main() == 0
    assert output_xml.read_text(encoding="utf-8") == "<track>closed-geometric</track>"
    assert (output_xml.parent / "readme.txt").exists()
    timing = json.loads((output_xml.parent / "source" / "rebuild-mainline-timing.json").read_text(encoding="utf-8"))
    assert any(stage["stage"] == "adjust-side-clearance" and stage["status"] == "ok" for stage in timing["stages"])
    assert any(stage["stage"] == "adjust-side-overlap" and stage["status"] == "ok" for stage in timing["stages"])


def test_place_curbs_recloses_split_curbed_xml_before_promotion(monkeypatch, tmp_path) -> None:
    _, output_xml = configure_rebuild_argv(monkeypatch, tmp_path, "--closure-solver", "geometric", "--place-curbs")

    def fake_run(cmd, check=True, timeout=None):  # noqa: ARG001
        _ = timeout
        command = [str(part) for part in cmd]
        script = pathlib.Path(command[1]).name
        if script == "prepare_loop_polyline.py":
            pathlib.Path(command[command.index("--report") + 1]).write_text('{"repair_applied": false}', encoding="utf-8")
        elif script == "draft_segments.py":
            pathlib.Path(command[command.index("--output-json") + 1]).write_text('{"segments": []}', encoding="utf-8")
            write_minimal_segments(pathlib.Path(command[command.index("--output-xml") + 1]))
            pathlib.Path(command[command.index("--output-svg") + 1]).write_text("<svg />", encoding="utf-8")
        elif script == "apply_segments.py":
            pathlib.Path(command[command.index("--output-xml") + 1]).write_text("<track>candidate</track>", encoding="utf-8")
        elif script == "close_loop.py":
            raise AssertionError("geometric closure should not invoke legacy close_loop.py")
        elif script == "close_loop_geometric.py":
            track_xml = pathlib.Path(command[command.index("--track-xml") + 1])
            report = pathlib.Path(command[command.index("--report") + 1])
            if report.name == "closure-report-curbs-geometric.json":
                track_xml.write_text("<track>closed-curbs</track>", encoding="utf-8")
            else:
                track_xml.write_text("<track>closed-geometric</track>", encoding="utf-8")
            report.write_text('{"ok": true}', encoding="utf-8")
        elif script == "place_curbs.py":
            pathlib.Path(command[command.index("--input") + 1]).write_text("<track>curbs</track>", encoding="utf-8")
            pathlib.Path(command[command.index("--report") + 1]).write_text('{"outside_splits": [{"source_segment": "approach"}]}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(rebuild_mainline.subprocess, "run", fake_run)

    assert rebuild_mainline.main() == 0
    assert output_xml.read_text(encoding="utf-8") == "<track>closed-curbs</track>"
    timing = json.loads((output_xml.parent / "source" / "rebuild-mainline-timing.json").read_text(encoding="utf-8"))
    assert any(stage["stage"] == "place-curbs" and stage["status"] == "ok" for stage in timing["stages"])
    assert any(stage["stage"] == "close-loop-curbs" and stage["status"] == "ok" for stage in timing["stages"])


def test_failed_closure_does_not_promote_staging_xml(monkeypatch, tmp_path) -> None:
    _, output_xml = configure_rebuild_argv(monkeypatch, tmp_path)
    output_xml.parent.mkdir(parents=True)
    output_xml.write_text("<track>original</track>", encoding="utf-8")

    def fake_run(cmd, check=True, timeout=None):  # noqa: ARG001
        _ = timeout
        command = [str(part) for part in cmd]
        script = pathlib.Path(command[1]).name
        if script == "prepare_loop_polyline.py":
            pathlib.Path(command[command.index("--report") + 1]).write_text('{"repair_applied": false}', encoding="utf-8")
        elif script == "draft_segments.py":
            pathlib.Path(command[command.index("--output-json") + 1]).write_text('{"segments": []}', encoding="utf-8")
            write_minimal_segments(pathlib.Path(command[command.index("--output-xml") + 1]))
            pathlib.Path(command[command.index("--output-svg") + 1]).write_text("<svg />", encoding="utf-8")
        elif script == "apply_segments.py":
            pathlib.Path(command[command.index("--output-xml") + 1]).write_text("<track>candidate</track>", encoding="utf-8")
        elif script == "close_loop.py" and "--baseline-only" in command:
            pathlib.Path(command[command.index("--report") + 1]).write_text(
                '{"baseline_ready": true, "final_metrics": {"delta_x": 0.0, "delta_y": 0.0, "delta_ang_deg": 0.0}}',
                encoding="utf-8",
            )
        elif script == "close_loop.py" and "--select-only" not in command:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(rebuild_mainline.subprocess, "run", fake_run)

    assert rebuild_mainline.main() == 1
    assert output_xml.read_text(encoding="utf-8") == "<track>original</track>"
    assert not (output_xml.parent / "readme.txt").exists()


def test_failed_side_clearance_does_not_promote_staging_xml(monkeypatch, tmp_path) -> None:
    _, output_xml = configure_rebuild_argv(monkeypatch, tmp_path, "--closure-solver", "geometric")
    output_xml.parent.mkdir(parents=True)
    output_xml.write_text("<track>original</track>", encoding="utf-8")

    def fake_run(cmd, check=True, timeout=None):  # noqa: ARG001
        _ = timeout
        command = [str(part) for part in cmd]
        script = pathlib.Path(command[1]).name
        if script == "prepare_loop_polyline.py":
            pathlib.Path(command[command.index("--report") + 1]).write_text('{"repair_applied": false}', encoding="utf-8")
        elif script == "draft_segments.py":
            pathlib.Path(command[command.index("--output-json") + 1]).write_text('{"segments": []}', encoding="utf-8")
            write_minimal_segments(pathlib.Path(command[command.index("--output-xml") + 1]))
            pathlib.Path(command[command.index("--output-svg") + 1]).write_text("<svg />", encoding="utf-8")
        elif script == "apply_segments.py":
            pathlib.Path(command[command.index("--output-xml") + 1]).write_text("<track>candidate</track>", encoding="utf-8")
        elif script == "close_loop_geometric.py":
            pathlib.Path(command[command.index("--track-xml") + 1]).write_text("<track>closed-geometric</track>", encoding="utf-8")
            pathlib.Path(command[command.index("--report") + 1]).write_text('{"ok": true}', encoding="utf-8")
        elif script == "adjust_side_clearance.py":
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(rebuild_mainline.subprocess, "run", fake_run)

    assert rebuild_mainline.main() == 1
    assert output_xml.read_text(encoding="utf-8") == "<track>original</track>"
    assert not (output_xml.parent / "readme.txt").exists()


def test_failed_side_overlap_does_not_promote_staging_xml(monkeypatch, tmp_path) -> None:
    _, output_xml = configure_rebuild_argv(monkeypatch, tmp_path, "--closure-solver", "geometric")
    output_xml.parent.mkdir(parents=True)
    output_xml.write_text("<track>original</track>", encoding="utf-8")

    def fake_run(cmd, check=True, timeout=None):  # noqa: ARG001
        _ = timeout
        command = [str(part) for part in cmd]
        script = pathlib.Path(command[1]).name
        if script == "prepare_loop_polyline.py":
            pathlib.Path(command[command.index("--report") + 1]).write_text('{"repair_applied": false}', encoding="utf-8")
        elif script == "draft_segments.py":
            pathlib.Path(command[command.index("--output-json") + 1]).write_text('{"segments": []}', encoding="utf-8")
            write_minimal_segments(pathlib.Path(command[command.index("--output-xml") + 1]))
            pathlib.Path(command[command.index("--output-svg") + 1]).write_text("<svg />", encoding="utf-8")
        elif script == "apply_segments.py":
            pathlib.Path(command[command.index("--output-xml") + 1]).write_text("<track>candidate</track>", encoding="utf-8")
        elif script == "close_loop_geometric.py":
            pathlib.Path(command[command.index("--track-xml") + 1]).write_text("<track>closed-geometric</track>", encoding="utf-8")
            pathlib.Path(command[command.index("--report") + 1]).write_text('{"ok": true}', encoding="utf-8")
        elif script == "adjust_side_overlap.py":
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(rebuild_mainline.subprocess, "run", fake_run)

    assert rebuild_mainline.main() == 1
    assert output_xml.read_text(encoding="utf-8") == "<track>original</track>"
    assert not (output_xml.parent / "readme.txt").exists()
