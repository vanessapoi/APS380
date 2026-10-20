# /***************************************************************************
#
#     file                 : test_close_loop.py
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

import pytest

import torcs_track_tools.cli.close_loop as close_loop

TRACKGEN_OUTPUT = """
Delta X = 0.0
Delta Y = 0.0
Delta Z = 0.0
Delta Ang = 0.0 (0.0)
length = 100.0
pits = 0
"""


def minimal_track_xml() -> str:
    return """
<params>
  <section name="Track Segments">
    <section name="Main Straight">
      <attstr name="type" val="str"/>
      <attnum name="lg" unit="m" val="50.0"/>
    </section>
  </section>
</params>
""".strip()


def rich_track_xml() -> str:
    return """
<params>
  <section name="Track Segments">
    <section name="Start">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="60" />
    </section>
    <section name="Left Authority">
      <attstr name="type" val="lft"/>
      <attnum name="radius" val="80" />
      <attnum name="arc" val="45" />
    </section>
    <section name="Diagonal">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="80" />
    </section>
    <section name="Right Wide">
      <attstr name="type" val="rgt"/>
      <attnum name="radius" val="500" />
      <attnum name="arc" val="8" />
    </section>
    <section name="Closure Start">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="40" />
    </section>
    <section name="pit lane helper">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="100" />
    </section>
  </section>
</params>
""".strip()


def args_obj(**overrides):
    values = {
        "category": "road",
        "name": "unit-track",
        "target_dx": 0.1,
        "target_dy": 0.1,
        "target_dz": 0.1,
        "target_ang": 0.1,
        "linear_max_arc_delta": 0.01,
        "linear_max_straight_delta": 1.0,
        "linear_polish_candidates": 1000,
    }
    values.update(overrides)
    return type("Args", (), values)()


def metrics_obj(dx=0.0, dy=0.0, dz=0.0, ang=0.0) -> dict[str, float]:
    return {"delta_x": dx, "delta_y": dy, "delta_z": dz, "delta_ang_deg": ang}


def configure_baseline_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    *extra_args: str,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    runtime_dir = tmp_path / "runtime"
    track_xml = tmp_path / "candidate.xml"
    config = tmp_path / "closure-config.json"
    report = tmp_path / "closure-report.json"
    track_xml.write_text(minimal_track_xml(), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-close-loop",
            "--track-xml",
            str(track_xml),
            "--runtime-dir",
            str(runtime_dir),
            "--category",
            "road",
            "--name",
            "unit-track",
            "--config",
            str(config),
            "--report",
            str(report),
            "--baseline-only",
            *extra_args,
        ],
    )
    return runtime_dir, track_xml, report


def configure_close_loop_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    *extra_args: str,
    track_text: str | None = None,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    runtime_dir = tmp_path / "runtime"
    track_xml = tmp_path / "candidate.xml"
    config = tmp_path / "closure-config.json"
    report = tmp_path / "closure-report.json"
    track_xml.write_text(track_text if track_text is not None else rich_track_xml(), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "torcs-close-loop",
            "--track-xml",
            str(track_xml),
            "--runtime-dir",
            str(runtime_dir),
            "--category",
            "road",
            "--name",
            "unit-track",
            "--config",
            str(config),
            "--report",
            str(report),
            *extra_args,
        ],
    )
    return runtime_dir, track_xml, config, report


def matching_config(track_xml: pathlib.Path, controls: dict) -> dict:
    segs = close_loop.parse_top_level_segments(track_xml.read_text(encoding="utf-8"))
    return {
        "schema": 1,
        "track_xml": str(track_xml),
        "category": "road",
        "name": "unit-track",
        "track_segments_sha256": close_loop.track_segments_fingerprint(segs),
        "controls": controls,
        "steps": {
            "straight": 1.0,
            "arc": 0.1,
            "x_straight": 1.0,
            "radius": 1.0,
            "min_straight": 1e-5,
            "min_arc": 1e-6,
        },
    }


def reset_trackgen_state() -> None:
    close_loop.TRACKGEN_CACHE.clear()
    close_loop.TRACKGEN_PHASE_STATS.clear()
    close_loop.TRACKGEN_CALLS = 0
    close_loop.TRACKGEN_SECONDS = 0.0
    close_loop.TRACKGEN_CACHE_HITS = 0
    close_loop.TRACKGEN_STATS.calls = 0
    close_loop.TRACKGEN_STATS.seconds = 0.0
    close_loop.TRACKGEN_STATS.cache_hits = 0


def test_mainline_profile_uses_trackgen_y_quantum_default(monkeypatch, tmp_path) -> None:
    configure_baseline_argv(monkeypatch, tmp_path)

    args = close_loop.parse_args()

    assert args.target_dy == 0.001


def test_post_pit_profile_enables_linear_polish_defaults(monkeypatch, tmp_path) -> None:
    runtime_dir, track_xml, report = configure_baseline_argv(monkeypatch, tmp_path, "--profile", "post-pit")
    argv = list(close_loop.sys.argv)
    argv.remove("--baseline-only")
    monkeypatch.setattr("sys.argv", argv)

    args = close_loop.parse_args()

    assert args.runtime_dir == str(runtime_dir)
    assert args.track_xml == str(track_xml)
    assert args.report == str(report)
    assert args.linear_polish
    assert args.target_dy == 0.001


def test_run_trackgen_z_removes_temporary_live_xml_for_new_track(monkeypatch, tmp_path) -> None:
    reset_trackgen_state()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "trackgen.exe").write_text("", encoding="utf-8")
    candidate_xml = tmp_path / "candidate.xml"
    live_xml = runtime_dir / "tracks" / "road" / "unit-track" / "unit-track.xml"
    live_xml.parent.mkdir(parents=True)
    candidate_xml.write_text("<track>candidate</track>", encoding="utf-8")

    def fake_run(cmd, cwd, stdout, stderr, text, check, timeout):  # noqa: ARG001
        assert timeout is None
        assert pathlib.Path(cwd) == runtime_dir
        assert live_xml.read_text(encoding="utf-8") == "<track>candidate</track>"
        return subprocess.CompletedProcess(cmd, 0, stdout=TRACKGEN_OUTPUT)

    monkeypatch.setattr("torcs_track_tools.core.trackgen.subprocess.run", fake_run)

    metrics, _ = close_loop.run_trackgen_z(runtime_dir, "road", "unit-track", candidate_xml)

    assert metrics["length"] == 100.0
    assert not live_xml.exists()
    assert not (runtime_dir / ".trackgen-road-unit-track.lock").exists()


def test_run_trackgen_z_restores_existing_live_xml_after_probe(monkeypatch, tmp_path) -> None:
    reset_trackgen_state()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "trackgen.exe").write_text("", encoding="utf-8")
    candidate_xml = tmp_path / "candidate.xml"
    live_xml = runtime_dir / "tracks" / "road" / "unit-track" / "unit-track.xml"
    live_xml.parent.mkdir(parents=True)
    live_xml.write_text("<track>original</track>", encoding="utf-8")
    candidate_xml.write_text("<track>candidate</track>", encoding="utf-8")

    def fake_run(cmd, cwd, stdout, stderr, text, check, timeout):  # noqa: ARG001
        assert timeout is None
        assert pathlib.Path(cwd) == runtime_dir
        assert live_xml.read_text(encoding="utf-8") == "<track>candidate</track>"
        return subprocess.CompletedProcess(cmd, 0, stdout=TRACKGEN_OUTPUT)

    monkeypatch.setattr("torcs_track_tools.core.trackgen.subprocess.run", fake_run)

    close_loop.run_trackgen_z(runtime_dir, "road", "unit-track", candidate_xml)

    assert live_xml.read_text(encoding="utf-8") == "<track>original</track>"
    assert not (runtime_dir / ".trackgen-road-unit-track.lock").exists()


def test_baseline_only_returns_zero_when_within_limits(monkeypatch, tmp_path) -> None:
    _, _, report = configure_baseline_argv(monkeypatch, tmp_path, "--max-baseline-ang", "2.0")

    monkeypatch.setattr(
        close_loop,
        "run_trackgen_z",
        lambda *args: ({"delta_x": 0.0, "delta_y": 0.0, "delta_z": 0.0, "delta_ang_deg": 1.5, "length": 100.0, "pits": 0}, ""),
    )

    assert close_loop.main() == 0
    obj = json.loads(report.read_text(encoding="utf-8"))
    assert obj["ok"]
    assert obj["baseline_ready"]


def test_baseline_only_returns_one_when_angle_exceeds_limit(monkeypatch, tmp_path) -> None:
    _, _, report = configure_baseline_argv(monkeypatch, tmp_path, "--max-baseline-ang", "2.0")

    monkeypatch.setattr(
        close_loop,
        "run_trackgen_z",
        lambda *args: ({"delta_x": 0.0, "delta_y": 0.0, "delta_z": 0.0, "delta_ang_deg": 2.5, "length": 100.0, "pits": 0}, ""),
    )

    assert close_loop.main() == 1
    obj = json.loads(report.read_text(encoding="utf-8"))
    assert not obj["ok"]
    assert not obj["baseline_ready"]


def test_solve_3x3_solves_linear_correction() -> None:
    sol = close_loop.solve_3x3(
        [
            [1.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, -4.0],
        ],
        [3.0, 8.0, -2.0],
    )

    assert sol == [3.0, 4.0, 0.5]


def test_apply_attnum_deltas_updates_multiple_controls() -> None:
    text = """
<params>
  <section name="Track Segments">
    <section name="a"><attnum name="lg" val="10" /></section>
    <section name="b"><attnum name="arc" val="2" /></section>
  </section>
</params>
""".strip()

    updated = close_loop.apply_attnum_deltas(text, [("a", "lg", 1.5), ("b", "arc", -0.25)])

    assert close_loop.read_attnum_value(updated, "a", "lg") == 11.5
    assert close_loop.read_attnum_value(updated, "b", "arc") == 1.75


def test_linear_polish_is_opt_in(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["torcs-close-loop", "--track-xml", "t.xml", "--runtime-dir", "runtime", "--category", "road", "--name", "t", "--config", "c.json"])

    args = close_loop.parse_args()

    assert not args.linear_polish


def test_parse_and_config_helpers_characterize_track_identity(tmp_path) -> None:
    text = rich_track_xml()
    segs = close_loop.parse_top_level_segments(text)
    args = args_obj(category="road", name="unit-track")
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(text, encoding="utf-8")
    controls = {
        "primary_straight": "Diagonal",
        "primary_turn": "Left Authority",
        "backup_straight": "Start",
        "x_straight": "Closure Start",
        "y_turn": "Left Authority",
    }
    config = {
        "schema": 1,
        "category": "road",
        "name": "unit-track",
        "track_xml": str(track_xml),
        "track_segments_sha256": close_loop.track_segments_fingerprint(segs),
        "controls": controls,
    }

    assert [seg["name"] for seg in segs] == ["Start", "Left Authority", "Diagonal", "Right Wide", "Closure Start", "pit lane helper"]
    assert close_loop.config_matches_track(config, args, track_xml, segs)
    assert close_loop.track_segments_fingerprint(segs) == close_loop.track_segments_fingerprint(close_loop.parse_top_level_segments(text))

    for broken in (
        {**config, "schema": 2},
        {**config, "category": "oval"},
        {**config, "track_xml": "other.xml"},
        {**config, "track_segments_sha256": "bad"},
        {**config, "controls": []},
        {**config, "controls": {**controls, "primary_straight": "missing"}},
        {**config, "controls": {**controls, "backup_straight": "missing"}},
    ):
        assert not close_loop.config_matches_track(broken, args, track_xml, segs)

    with pytest.raises(RuntimeError, match="Track Segments"):
        close_loop.locate_track_segments_block("<params />")
    with pytest.raises(RuntimeError, match="Section open"):
        close_loop.find_matching_section_end(text, 0)
    with pytest.raises(RuntimeError, match="Unbalanced"):
        close_loop.find_matching_section_end('<section name="Track Segments">', 0)


def test_selection_config_helpers_capture_paths_steps_and_report_default(tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    config_path = tmp_path / "closure-config.json"
    text = rich_track_xml()
    track_xml.write_text(text, encoding="utf-8")
    segs = close_loop.parse_top_level_segments(text)
    controls = {
        "primary_straight": "Diagonal",
        "primary_turn": "Left Authority",
        "backup_straight": "Start",
        "x_straight": "Closure Start",
        "y_turn": "Left Authority",
    }
    args = args_obj(
        category="road",
        name="unit-track",
        report="",
        straight_step=2.0,
        arc_step=0.2,
        min_straight_step=0.0002,
        min_arc_step=0.00002,
    )

    config = close_loop.build_selection_config(track_xml, args, segs, controls)

    assert close_loop.resolve_report_path(args, config_path) == tmp_path / "closure-config-report.json"
    assert config["schema"] == 1
    assert config["track_xml"] == str(track_xml)
    assert config["track_segments_sha256"] == close_loop.track_segments_fingerprint(segs)
    assert config["controls"] == controls
    assert config["steps"] == {
        "straight": 2.0,
        "arc": 0.2,
        "x_straight": 2.0,
        "radius": 2.0,
        "min_straight": 0.0002,
        "min_arc": 0.00002,
    }

    explicit = args_obj(report=str(tmp_path / "explicit-report.json"))
    assert close_loop.resolve_report_path(explicit, config_path) == tmp_path / "explicit-report.json"


def test_baseline_report_helpers_capture_readiness_targets_and_limits() -> None:
    reset_trackgen_state()
    close_loop.SELF_INTERSECTION_CHECKS = 0
    close_loop.SELF_INTERSECTION_SECONDS = 0.0
    args = args_obj(
        target_dx=0.1,
        target_dy=0.2,
        target_dz=0.3,
        target_ang=0.4,
        max_baseline_dx=20.0,
        max_baseline_dy=5.0,
        max_baseline_ang=2.0,
    )
    ready_metrics = metrics_obj(dx=19.0, dy=-4.0, ang=1.5)
    rough_metrics = metrics_obj(dx=21.0, dy=0.0, ang=0.0)
    controls = {"primary_straight": "Diagonal", "primary_turn": "Left Authority"}
    history = [{"iter": 0, "action": "baseline", "metrics": rough_metrics}]

    baseline_report = close_loop.build_baseline_only_report(ready_metrics, args, close_loop.is_baseline_ready(ready_metrics, args))
    not_ready_report = close_loop.build_baseline_not_ready_report(rough_metrics, args, controls, 1.5, 2, history, 0.25)
    final_report = close_loop.build_final_report(True, 0.5, controls, args, ready_metrics, 0.0, 1, history)

    assert close_loop.is_baseline_ready(ready_metrics, args)
    assert not close_loop.is_baseline_ready(rough_metrics, args)
    assert close_loop.report_targets(args) == {"delta_x": 0.1, "delta_y": 0.2, "delta_z": 0.3, "delta_ang_deg": 0.4}
    assert close_loop.report_baseline_limits(args) == {"delta_x": 20.0, "delta_y": 5.0, "delta_ang_deg": 2.0}
    assert baseline_report["ok"]
    assert baseline_report["baseline_ready"]
    assert baseline_report["history"] == [{"iter": 0, "metrics": ready_metrics, "action": "baseline"}]
    assert baseline_report["stats"]["trackgen_calls"] == 0
    assert not_ready_report["ok"] is False
    assert not_ready_report["baseline_ready"] is False
    assert not_ready_report["controls"] == controls
    assert not_ready_report["best_gap"] == pytest.approx(1.5)
    assert not_ready_report["plateau_count"] == 2
    assert not_ready_report["history"] == history
    assert final_report["ok"]
    assert final_report["elapsed_seconds"] == pytest.approx(0.5)
    assert final_report["controls"] == controls
    assert final_report["targets"] == close_loop.report_targets(args)
    assert final_report["final_metrics"] == ready_metrics
    assert final_report["best_gap"] == pytest.approx(0.0)
    assert final_report["plateau_count"] == 1


def test_run_linear_polish_rounds_updates_best_state_and_stops_on_pass(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text("base", encoding="utf-8")
    args = args_obj(
        category="road",
        name="unit-track",
        linear_polish=True,
        linear_polish_rounds=3,
        target_dx=0.01,
        target_dy=0.01,
        target_dz=0.01,
        target_ang=0.01,
    )
    calls: list[int] = []

    def fake_linear_polish_once(track_xml, runtime_dir, category, name, metrics, args, history, iter_id):  # noqa: ARG001
        calls.append(iter_id)
        track_xml.write_text(f"round-{iter_id}", encoding="utf-8")
        history.append({"iter": iter_id, "phase": "linear-polish"})
        if iter_id == 1:
            return metrics_obj(dx=0.2), True
        return metrics_obj(), True

    monkeypatch.setattr(close_loop, "linear_polish_once", fake_linear_polish_once)
    history: list[dict] = []

    metrics, best_metrics, best_text, best_gap, plateau_count, ok = close_loop.run_linear_polish_rounds(
        track_xml=track_xml,
        runtime_dir=pathlib.Path("runtime"),
        args=args,
        metrics=metrics_obj(dx=0.5),
        history=history,
        best_gap=close_loop.closure_gap(metrics_obj(dx=0.5), args),
        best_metrics=metrics_obj(dx=0.5),
        best_text="base",
        plateau_count=3,
        ok=False,
    )

    assert calls == [1, 2]
    assert ok
    assert metrics == metrics_obj()
    assert best_metrics == metrics_obj()
    assert best_text == "round-2"
    assert best_gap == pytest.approx(0.0)
    assert plateau_count == 0
    assert history == [{"iter": 1, "phase": "linear-polish"}, {"iter": 2, "phase": "linear-polish"}]


def test_basic_numeric_name_and_phase_helpers(monkeypatch) -> None:
    close_loop.TRACKGEN_PHASE_STATS.clear()
    monkeypatch.setattr(close_loop, "TRACKGEN_PHASE", "outer")

    assert close_loop.to_float(None, 7.0) == 7.0
    assert close_loop.to_float("bad", 3.0) == 3.0
    assert close_loop.to_float("2.5") == pytest.approx(2.5)
    assert close_loop.unique_name({"Helper", "Helper-2"}, "Helper") == "Helper-3"
    assert close_loop.norm_angle(3.0 * math.pi) == pytest.approx(math.pi)
    assert close_loop.norm_angle(-3.0 * math.pi) == pytest.approx(-math.pi)
    assert close_loop.phase_stats("probe") == {"calls": 0, "seconds": 0.0, "cache_hits": 0}

    with close_loop.trackgen_phase("inner"):
        assert close_loop.TRACKGEN_PHASE == "inner"
    assert close_loop.TRACKGEN_PHASE == "outer"


def test_simulation_sampling_and_intersection_helpers(monkeypatch, tmp_path) -> None:
    segs = close_loop.parse_top_level_segments(rich_track_xml())
    close_loop.simulate_segments(segs)
    points = close_loop.sample_centerline_points(segs)

    assert segs[0]["sim_x0"] == pytest.approx(0.0)
    assert segs[0]["sim_x1"] == pytest.approx(60.0)
    assert segs[1]["sim_h1"] == pytest.approx(math.radians(45.0))
    assert points[0] == pytest.approx((0.0, 0.0))
    assert len(points) > len(segs)
    assert close_loop.segments_intersect((0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0))
    assert not close_loop.segments_intersect((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))

    clean_xml = tmp_path / "clean.xml"
    clean_xml.write_text(
        """
<params><section name="Track Segments">
<section name="a"><attstr name="type" val="str"/><attnum name="lg" val="10"/></section>
<section name="b"><attstr name="type" val="lft"/><attnum name="radius" val="10"/><attnum name="arc" val="90"/></section>
</section></params>
""".strip(),
        encoding="utf-8",
    )
    crossing_xml = tmp_path / "crossing.xml"
    crossing_xml.write_text(minimal_track_xml(), encoding="utf-8")

    close_loop.SELF_INTERSECTION_CHECKS = 0
    close_loop.SELF_INTERSECTION_SECONDS = 0.0
    assert not close_loop.has_planar_self_intersection(clean_xml)
    monkeypatch.setattr(
        close_loop,
        "sample_centerline_points",
        lambda _segs: [(0.0, 0.0), (10.0, 10.0), (20.0, 10.0), (0.0, 10.0), (10.0, 0.0), (20.0, 0.0)],
    )
    assert close_loop.has_planar_self_intersection(crossing_xml)
    assert close_loop.SELF_INTERSECTION_CHECKS == 2
    assert close_loop.SELF_INTERSECTION_SECONDS >= 0.0


def test_pick_controls_prioritizes_authoritative_non_pit_segments() -> None:
    segs = close_loop.parse_top_level_segments(rich_track_xml())

    controls = close_loop.pick_controls(segs)

    assert controls["primary_straight"] == "Diagonal"
    assert controls["primary_turn"] == "Left Authority"
    assert controls["backup_straight"] == "Start"
    assert controls["x_straight"] == "Closure Start"
    assert controls["y_turn"] == "Left Authority"

    with pytest.raises(RuntimeError, match="No track segments"):
        close_loop.pick_controls([])
    with pytest.raises(RuntimeError, match="straight"):
        close_loop.pick_controls(close_loop.parse_top_level_segments('<params><section name="Track Segments"><section name="turn"><attstr name="type" val="lft"/><attnum name="radius" val="50"/><attnum name="arc" val="5"/></section></section></params>'))
    with pytest.raises(RuntimeError, match="turn"):
        close_loop.pick_controls(close_loop.parse_top_level_segments(minimal_track_xml()))


def test_xml_rewrite_and_turn_split_helpers() -> None:
    text = rich_track_xml()

    updated = close_loop.replace_attnum_value(text, "Start", "lg", 61.25)
    assert close_loop.read_attnum_value(updated, "Start", "lg") == pytest.approx(61.25)
    replaced = close_loop.replace_segment_raw(updated, "Start", '<section name="Start"><attnum name="lg" val="1" /></section>')
    assert close_loop.read_attnum_value(replaced, "Start", "lg") == pytest.approx(1.0)

    split, pre_name = close_loop.split_turn_with_straight_insert(text, "Left Authority", "y_comp", 0.75)
    split_segs = close_loop.parse_top_level_segments(split)
    assert pre_name == "Left Authority-xpre"
    assert [seg["name"] for seg in split_segs][1:4] == ["Left Authority-xpre", "y_comp", "Left Authority"]
    assert close_loop.read_attnum_value(split, "Left Authority-xpre", "arc") == pytest.approx(22.5)
    assert close_loop.read_attnum_value(split, "Left Authority", "arc") == pytest.approx(22.5)
    assert close_loop.read_attnum_value(split, "y_comp", "lg") == pytest.approx(0.75)

    with pytest.raises(RuntimeError, match="Segment not found"):
        close_loop.read_attnum_value(text, "missing", "lg")
    with pytest.raises(RuntimeError, match="Attribute"):
        close_loop.replace_attnum_value(text, "Start", "missing", 1.0)
    with pytest.raises(RuntimeError, match="Segment not found"):
        close_loop.replace_segment_raw(text, "missing", "raw")
    with pytest.raises(RuntimeError, match="not a turn"):
        close_loop.split_turn_with_straight_insert(text, "Start", "bad", 1.0)
    with pytest.raises(RuntimeError, match="end radius"):
        close_loop.split_turn_with_straight_insert(
            '<params><section name="Track Segments"><section name="var"><attstr name="type" val="lft"/><attnum name="radius" val="50"/><attnum name="end radius" val="60"/><attnum name="arc" val="5"/></section></section></params>',
            "var",
            "bad",
            1.0,
        )


def test_x_comp_turn_candidates_skip_pit_neighbors_and_rank_wide_turns() -> None:
    text = """
<params><section name="Track Segments">
<section name="start"><attstr name="type" val="str"/><attnum name="lg" val="50"/></section>
<section name="too-tight"><attstr name="type" val="lft"/><attnum name="radius" val="200"/><attnum name="arc" val="5"/></section>
<section name="wide-a"><attstr name="type" val="lft"/><attnum name="radius" val="800"/><attnum name="arc" val="5"/></section>
<section name="filler"><attstr name="type" val="str"/><attnum name="lg" val="30"/></section>
<section name="pit entry"><attstr name="type" val="str"/><attnum name="lg" val="30"/></section>
<section name="blocked"><attstr name="type" val="rgt"/><attnum name="radius" val="900"/><attnum name="arc" val="6"/></section>
<section name="variable"><attstr name="type" val="lft"/><attnum name="radius" val="900"/><attnum name="end radius" val="1000"/><attnum name="arc" val="6"/></section>
<section name="wide-b"><attstr name="type" val="rgt"/><attnum name="radius" val="1200"/><attnum name="arc" val="8"/></section>
</section></params>
""".strip()

    candidates = close_loop.find_x_comp_turn_candidates(close_loop.parse_top_level_segments(text))

    assert [item["seg"]["name"] for item in candidates] == ["wide-b", "wide-a"]
    assert all(abs(item["mid_cos"]) <= 1.0 for item in candidates)


def test_probe_refinement_selects_best_turn_y_and_x_controls(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    base_text = rich_track_xml()
    track_xml.write_text(base_text, encoding="utf-8")
    segs = close_loop.parse_top_level_segments(base_text)
    controls = {
        "primary_straight": "Start",
        "primary_turn": "Right Wide",
        "backup_straight": "",
        "x_straight": "Start",
        "y_turn": "Right Wide",
    }
    baseline = metrics_obj(dx=10.0, dy=5.0, ang=2.0)

    def fake_run(_runtime_dir, _category, _name, under_test):
        text = under_test.read_text(encoding="utf-8")
        left_arc = close_loop.read_attnum_value(text, "Left Authority", "arc")
        diagonal_lg = close_loop.read_attnum_value(text, "Diagonal", "lg")
        left_radius = close_loop.read_attnum_value(text, "Left Authority", "radius")
        closure_lg = close_loop.read_attnum_value(text, "Closure Start", "lg")
        if left_arc > 45.0:
            return metrics_obj(dx=10.0, dy=5.2, ang=0.3), ""
        if diagonal_lg > 80.0:
            return metrics_obj(dx=10.0, dy=0.8, ang=2.0), ""
        if left_radius < 80.0:
            return metrics_obj(dx=10.0, dy=0.4, ang=2.0), ""
        if closure_lg > 40.0:
            return metrics_obj(dx=0.5, dy=5.0, ang=2.0), ""
        return baseline, ""

    monkeypatch.setattr(close_loop, "run_trackgen_z", fake_run)
    monkeypatch.setattr(close_loop, "has_planar_self_intersection", lambda _track_xml: False)

    controls = close_loop.refine_turn_controls_by_probe(track_xml, pathlib.Path("runtime"), "road", "unit", segs, controls, baseline)
    controls = close_loop.refine_y_controls_by_probe(track_xml, pathlib.Path("runtime"), "road", "unit", segs, controls, baseline)
    controls = close_loop.refine_x_controls_by_probe(track_xml, pathlib.Path("runtime"), "road", "unit", segs, controls, baseline)

    assert controls["primary_turn"] == "Left Authority"
    assert controls["primary_straight"] == "Diagonal"
    assert controls["y_turn"] == "Left Authority"
    assert controls["x_straight"] == "Closure Start"
    assert track_xml.read_text(encoding="utf-8") == base_text


def test_runtime_x_control_reselects_locked_improving_straight(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    base_text = rich_track_xml()
    track_xml.write_text(base_text, encoding="utf-8")
    current = metrics_obj(dx=-8.0, dy=0.01, ang=0.0001)

    def fake_run(_runtime_dir, _category, _name, under_test):
        text = under_test.read_text(encoding="utf-8")
        closure_lg = close_loop.read_attnum_value(text, "Closure Start", "lg")
        diagonal_lg = close_loop.read_attnum_value(text, "Diagonal", "lg")
        if closure_lg > 40.0:
            return metrics_obj(dx=-2.0, dy=0.02, ang=0.0001), ""
        if diagonal_lg > 80.0:
            return metrics_obj(dx=-1.0, dy=2.0, ang=0.0001), ""
        return current, ""

    monkeypatch.setattr(close_loop, "run_trackgen_z", fake_run)
    monkeypatch.setattr(close_loop, "has_planar_self_intersection", lambda _track_xml: False)

    selected = close_loop.choose_runtime_x_control(
        track_xml,
        pathlib.Path("runtime"),
        "road",
        "unit",
        current,
        "Start",
        ang_lock=0.001,
        y_lock=0.05,
        probe_step=1.0,
    )

    assert selected == "Closure Start"
    assert track_xml.read_text(encoding="utf-8") == base_text


def test_linear_polish_applies_verified_three_control_solution(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    base_text = rich_track_xml()
    track_xml.write_text(base_text, encoding="utf-8")
    base_metrics = metrics_obj(dx=0.3, dy=-0.4, ang=0.002)
    args = args_obj(target_dx=0.01, target_dy=0.01, target_ang=0.001)

    def fake_run(_runtime_dir, _category, _name, under_test):
        text = under_test.read_text(encoding="utf-8")
        start_delta = close_loop.read_attnum_value(text, "Start", "lg") - 60.0
        diagonal_delta = close_loop.read_attnum_value(text, "Diagonal", "lg") - 80.0
        left_arc_delta = close_loop.read_attnum_value(text, "Left Authority", "arc") - 45.0
        return metrics_obj(
            dx=0.3 + start_delta + 10.0 * left_arc_delta,
            dy=-0.4 + diagonal_delta,
            ang=0.002 + left_arc_delta,
        ), ""

    monkeypatch.setattr(close_loop, "run_trackgen_z", fake_run)
    monkeypatch.setattr(close_loop, "has_planar_self_intersection", lambda _track_xml: False)
    history: list[dict] = []

    metrics, changed = close_loop.linear_polish_once(
        track_xml,
        pathlib.Path("runtime"),
        "road",
        "unit",
        base_metrics,
        args,
        history,
        iter_id=7,
    )

    updated = track_xml.read_text(encoding="utf-8")
    assert changed
    assert metrics == pytest.approx(metrics_obj())
    assert close_loop.read_attnum_value(updated, "Left Authority", "arc") == pytest.approx(44.998)
    assert close_loop.read_attnum_value(updated, "Start", "lg") == pytest.approx(59.72)
    assert close_loop.read_attnum_value(updated, "Diagonal", "lg") == pytest.approx(80.4)
    assert history[0]["phase"] == "linear-polish"
    assert history[0]["iter"] == 7


def test_tune_projected_uses_probe_slope_for_larger_projected_jump(monkeypatch, tmp_path) -> None:
    close_loop.PROJECTED_SLOPES.clear()
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(minimal_track_xml(), encoding="utf-8")
    current = metrics_obj(dx=8.0)

    def fake_run(_runtime_dir, _category, _name, under_test):
        lg = close_loop.read_attnum_value(under_test.read_text(encoding="utf-8"), "Main Straight", "lg")
        return metrics_obj(dx=8.0 - 2.0 * (lg - 50.0)), ""

    monkeypatch.setattr(close_loop, "run_trackgen_z", fake_run)
    monkeypatch.setattr(close_loop, "has_planar_self_intersection", lambda _track_xml: False)
    history: list[dict] = []

    metrics, step, changed = close_loop.tune_projected(
        track_xml,
        pathlib.Path("runtime"),
        "road",
        "unit",
        "Main Straight",
        "lg",
        1.0,
        lambda m: abs(m["delta_x"]),
        history,
        iter_id=3,
        phase="C",
        sub_iter=2,
        target_key="delta_x",
        current_metrics=current,
    )

    assert changed
    assert metrics["delta_x"] == pytest.approx(0.0)
    assert step == pytest.approx(2.0)
    assert close_loop.read_attnum_value(track_xml.read_text(encoding="utf-8"), "Main Straight", "lg") == pytest.approx(54.0)
    assert history[0]["method"] == "projected"
    assert close_loop.PROJECTED_SLOPES[("C", "Main Straight", "lg", "delta_x")] == pytest.approx(-2.0)


def test_tune_projected_accepts_cached_slope_before_probe(monkeypatch, tmp_path) -> None:
    close_loop.PROJECTED_SLOPES.clear()
    close_loop.PROJECTED_SLOPES[("C", "Main Straight", "lg", "delta_x")] = -4.0
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(minimal_track_xml(), encoding="utf-8")
    current = metrics_obj(dx=8.0)
    probed_values: list[float] = []

    def fake_run(_runtime_dir, _category, _name, under_test):
        lg = close_loop.read_attnum_value(under_test.read_text(encoding="utf-8"), "Main Straight", "lg")
        probed_values.append(lg)
        return metrics_obj(dx=8.0 - 4.0 * (lg - 50.0)), ""

    monkeypatch.setattr(close_loop, "run_trackgen_z", fake_run)
    monkeypatch.setattr(close_loop, "has_planar_self_intersection", lambda _track_xml: False)
    history: list[dict] = []

    metrics, step, changed = close_loop.tune_projected(
        track_xml,
        pathlib.Path("runtime"),
        "road",
        "unit",
        "Main Straight",
        "lg",
        1.0,
        lambda m: abs(m["delta_x"]),
        history,
        iter_id=4,
        phase="C",
        sub_iter=1,
        target_key="delta_x",
        current_metrics=current,
        use_cached_slope=True,
    )

    assert changed
    assert metrics["delta_x"] == pytest.approx(0.0)
    assert step == pytest.approx(1.0)
    assert probed_values == [52.0]
    assert close_loop.read_attnum_value(track_xml.read_text(encoding="utf-8"), "Main Straight", "lg") == pytest.approx(52.0)
    assert history[0]["method"] == "cached-projected"


def test_polish_near_pass_runs_angle_x_y_and_stops_on_pass(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(rich_track_xml(), encoding="utf-8")
    controls = {
        "primary_straight": "Diagonal",
        "primary_turn": "Left Authority",
        "backup_straight": "Start",
        "x_straight": "Closure Start",
    }
    args = args_obj(target_dx=0.01, target_dy=0.001, target_ang=0.005)
    results = {
        "A-polish": (metrics_obj(dx=0.02, dy=0.015, ang=0.004), 0.002, True),
        "C-polish": (metrics_obj(dx=0.009, dy=0.015, ang=0.004), 0.25, True),
        "B-polish": (metrics_obj(dx=0.009, dy=0.0005, ang=0.004), 0.5, True),
    }
    calls: list[dict] = []

    def fake_tune_once(**kwargs):
        phase = kwargs["phase"]
        calls.append(
            {
                "phase": phase,
                "seg_name": kwargs["seg_name"],
                "att_name": kwargs["att_name"],
                "step": kwargs["step"],
                "iter_id": kwargs["iter_id"],
                "sub_iter": kwargs["sub_iter"],
            }
        )
        assert kwargs["is_valid_metrics"](results[phase][0])
        return results[phase]

    monkeypatch.setattr(close_loop, "tune_once", fake_tune_once)
    history: list[dict] = []

    metrics, arc_step, x_step, straight_step, changed = close_loop.polish_near_pass(
        track_xml,
        pathlib.Path("runtime"),
        "road",
        "unit",
        controls,
        metrics_obj(dx=0.02, dy=0.015, ang=0.006),
        args,
        history,
        start_iter=100,
        arc_step=0.0001,
        x_step=0.1,
        straight_step=0.05,
        min_arc=0.001,
        min_straight=0.25,
    )

    assert changed
    assert metrics == pytest.approx(metrics_obj(dx=0.009, dy=0.0005, ang=0.004))
    assert arc_step == pytest.approx(0.002)
    assert x_step == pytest.approx(0.25)
    assert straight_step == pytest.approx(0.5)
    assert calls == [
        {"phase": "A-polish", "seg_name": "Left Authority", "att_name": "arc", "step": 0.001, "iter_id": 101, "sub_iter": 1},
        {"phase": "C-polish", "seg_name": "Closure Start", "att_name": "lg", "step": 0.25, "iter_id": 101, "sub_iter": 1},
        {"phase": "B-polish", "seg_name": "Diagonal", "att_name": "lg", "step": 0.25, "iter_id": 101, "sub_iter": 1},
    ]


def test_run_near_pass_polish_restores_best_and_updates_only_on_improvement(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text("current", encoding="utf-8")
    args = args_obj(
        category="road",
        name="unit-track",
        target_dx=0.01,
        target_dy=0.01,
        target_dz=0.01,
        target_ang=0.01,
        max_iters=7,
    )
    controls = {"primary_straight": "Diagonal", "primary_turn": "Left Authority"}
    calls: list[dict] = []

    def fake_polish_near_pass(**kwargs):
        calls.append(
            {
                "category": kwargs["category"],
                "name": kwargs["name"],
                "metrics": kwargs["metrics"],
                "start_iter": kwargs["start_iter"],
                "arc_step": kwargs["arc_step"],
                "x_step": kwargs["x_step"],
                "straight_step": kwargs["straight_step"],
            }
        )
        assert track_xml.read_text(encoding="utf-8") == "best"
        track_xml.write_text("improved", encoding="utf-8")
        return metrics_obj(dx=0.015), 0.2, 0.3, 0.4, True

    monkeypatch.setattr(close_loop, "polish_near_pass", fake_polish_near_pass)
    history: list[dict] = []

    metrics, best_metrics, best_text, best_gap, ok = close_loop.run_near_pass_polish(
        track_xml=track_xml,
        runtime_dir=pathlib.Path("runtime"),
        args=args,
        controls=controls,
        metrics=metrics_obj(dx=0.4),
        history=history,
        best_metrics=metrics_obj(dx=0.02),
        best_text="best",
        best_gap=0.02,
        ok=False,
        arc_step=0.1,
        x_step=1.0,
        straight_step=2.0,
        min_arc=0.001,
        min_straight=0.25,
    )

    assert calls == [
        {
            "category": "road",
            "name": "unit-track",
            "metrics": metrics_obj(dx=0.02),
            "start_iter": 107,
            "arc_step": 0.1,
            "x_step": 1.0,
            "straight_step": 2.0,
        }
    ]
    assert not ok
    assert metrics == metrics_obj(dx=0.015)
    assert best_metrics == metrics_obj(dx=0.015)
    assert best_text == "improved"
    assert best_gap == pytest.approx(0.005)

    skipped = close_loop.run_near_pass_polish(
        track_xml=track_xml,
        runtime_dir=pathlib.Path("runtime"),
        args=args,
        controls=controls,
        metrics=metrics_obj(dx=0.0),
        history=history,
        best_metrics=best_metrics,
        best_text=best_text,
        best_gap=best_gap,
        ok=True,
        arc_step=0.1,
        x_step=1.0,
        straight_step=2.0,
        min_arc=0.001,
        min_straight=0.25,
    )
    assert skipped == (metrics_obj(dx=0.0), best_metrics, best_text, best_gap, True)
    assert len(calls) == 1


def test_final_output_helpers_restore_best_on_failure_and_persist_reports(tmp_path) -> None:
    reset_trackgen_state()
    track_xml = tmp_path / "track.xml"
    config_path = tmp_path / "closure-config.json"
    report_path = tmp_path / "closure-report.json"
    track_xml.write_text("current", encoding="utf-8")
    args = args_obj(target_dx=0.1, target_dy=0.2, target_dz=0.3, target_ang=0.4)
    config = {"controls": {"old": "control"}, "schema": 1}
    controls = {"primary_straight": "Diagonal", "primary_turn": "Left Authority"}
    history = [{"iter": 0, "action": "baseline"}]

    restored = close_loop.restore_best_state_if_failed(track_xml, metrics_obj(dx=9.0), metrics_obj(dx=1.0), "best", ok=False)
    assert restored == metrics_obj(dx=1.0)
    assert track_xml.read_text(encoding="utf-8") == "best"

    track_xml.write_text("passing", encoding="utf-8")
    kept = close_loop.restore_best_state_if_failed(track_xml, metrics_obj(), metrics_obj(dx=1.0), "best", ok=True)
    assert kept == metrics_obj()
    assert track_xml.read_text(encoding="utf-8") == "passing"

    close_loop.persist_final_outputs(
        config_path,
        report_path,
        config,
        controls,
        True,
        0.75,
        args,
        kept,
        0.0,
        4,
        history,
    )

    saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    saved_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved_config == {"schema": 1, "controls": controls}
    assert config["controls"] == controls
    assert saved_report["ok"]
    assert saved_report["elapsed_seconds"] == pytest.approx(0.75)
    assert saved_report["controls"] == controls
    assert saved_report["targets"] == {"delta_x": 0.1, "delta_y": 0.2, "delta_z": 0.3, "delta_ang_deg": 0.4}
    assert saved_report["final_metrics"] == kept
    assert saved_report["best_gap"] == pytest.approx(0.0)
    assert saved_report["plateau_count"] == 4
    assert saved_report["history"] == history


def test_run_phase_a_angle_retries_after_step_shrink_and_stops_on_target(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(rich_track_xml(), encoding="utf-8")
    args = args_obj(
        category="road",
        name="unit-track",
        phase_iters=3,
        target_ang=0.01,
        target_dx=0.1,
        target_dy=0.1,
        target_dz=0.1,
    )
    results = [
        (metrics_obj(ang=0.2), 0.02, False),
        (metrics_obj(ang=0.005), 0.02, True),
    ]
    calls: list[dict] = []

    def fake_tune_projected(**kwargs):
        calls.append(
            {
                "phase": kwargs["phase"],
                "sub_iter": kwargs["sub_iter"],
                "seg_name": kwargs["seg_name"],
                "att_name": kwargs["att_name"],
                "step": kwargs["step"],
                "target_key": kwargs["target_key"],
                "current_metrics": kwargs["current_metrics"],
            }
        )
        assert kwargs["is_valid_value"](1.0)
        return results[len(calls) - 1]

    monkeypatch.setattr(close_loop, "tune_projected", fake_tune_projected)
    history: list[dict] = []

    metrics, arc_step, ok = close_loop.run_phase_a_angle(
        track_xml=track_xml,
        runtime_dir=pathlib.Path("runtime"),
        args=args,
        metrics=metrics_obj(ang=1.0),
        history=history,
        iter_id=5,
        primary_turn="Left Authority",
        arc_step=0.1,
        min_arc=0.001,
        valid_turn_arc=lambda value: value > 0.0,
    )

    assert ok
    assert metrics == metrics_obj(ang=0.005)
    assert arc_step == pytest.approx(0.02)
    assert calls == [
        {
            "phase": "A",
            "sub_iter": 1,
            "seg_name": "Left Authority",
            "att_name": "arc",
            "step": 0.1,
            "target_key": "delta_ang_deg",
            "current_metrics": metrics_obj(ang=1.0),
        },
        {
            "phase": "A",
            "sub_iter": 2,
            "seg_name": "Left Authority",
            "att_name": "arc",
            "step": 0.02,
            "target_key": "delta_ang_deg",
            "current_metrics": metrics_obj(ang=0.2),
        },
    ]


def test_run_phase_b_y_uses_straight_then_radius_fallback(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(rich_track_xml(), encoding="utf-8")
    args = args_obj(
        category="road",
        name="unit-track",
        phase_iters=4,
        target_dx=0.1,
        target_dy=0.01,
        target_dz=0.1,
        target_ang=0.3,
    )
    calls: list[dict] = []

    def fake_tune_once(**kwargs):
        phase = kwargs["phase"]
        calls.append(
            {
                "phase": phase,
                "sub_iter": kwargs["sub_iter"],
                "seg_name": kwargs["seg_name"],
                "att_name": kwargs["att_name"],
                "step": kwargs["step"],
            }
        )
        assert kwargs["is_valid_metrics"](metrics_obj(dy=0.2, ang=0.2))
        if phase == "B":
            return metrics_obj(dy=0.3, ang=0.2), 1.5, False
        assert phase == "B-radius"
        assert kwargs["is_valid_value"](10.0)
        return metrics_obj(dy=0.005, ang=0.2), 0.4, True

    monkeypatch.setattr(close_loop, "tune_once", fake_tune_once)
    history: list[dict] = []

    metrics, straight_step, radius_step, ang_lock, ok = close_loop.run_phase_b_y(
        track_xml=track_xml,
        runtime_dir=pathlib.Path("runtime"),
        args=args,
        metrics=metrics_obj(dy=0.5, ang=0.2),
        history=history,
        iter_id=6,
        primary_straight="Diagonal",
        y_turn="Left Authority",
        straight_step=2.0,
        radius_step=1.0,
        valid_turn_radius=lambda value: value >= 2.0,
    )

    assert ok
    assert metrics == metrics_obj(dy=0.005, ang=0.2)
    assert straight_step == pytest.approx(1.5)
    assert radius_step == pytest.approx(0.4)
    assert ang_lock == pytest.approx(0.3 + 1e-12)
    assert calls == [
        {"phase": "B", "sub_iter": 1, "seg_name": "Diagonal", "att_name": "lg", "step": 2.0},
        {"phase": "B-radius", "sub_iter": 1, "seg_name": "Left Authority", "att_name": "radius", "step": 1.0},
        {"phase": "B-radius", "sub_iter": 2, "seg_name": "Left Authority", "att_name": "radius", "step": 0.4},
    ]


def test_run_phase_c_x_skips_when_delta_x_within_target(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(rich_track_xml(), encoding="utf-8")
    args = args_obj(category="road", name="unit-track", phase_iters=3, target_dx=0.1, target_dy=0.1, target_dz=0.1, target_ang=0.1, runtime_x_reselect=False)
    controls = {"x_straight": "Closure Start"}

    def fail_tune_projected(**_kwargs):
        pytest.fail("Phase C should not tune when X is already within target")

    monkeypatch.setattr(close_loop, "tune_projected", fail_tune_projected)

    metrics, x_step, x_straight, changed, ok = close_loop.run_phase_c_x(
        track_xml=track_xml,
        runtime_dir=pathlib.Path("runtime"),
        args=args,
        metrics=metrics_obj(dx=0.05),
        history=[],
        iter_id=7,
        controls=controls,
        x_straight="Closure Start",
        backup_straight="Start",
        primary_straight="Diagonal",
        x_step=1.0,
        x_step_initial=1.0,
        min_straight=0.01,
        ang_lock=0.1,
    )

    assert ok
    assert not changed
    assert metrics == metrics_obj(dx=0.05)
    assert x_step == pytest.approx(1.0)
    assert x_straight == "Closure Start"
    assert controls == {"x_straight": "Closure Start"}


def test_run_phase_c_x_uses_projected_tuning_and_updates_step(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(rich_track_xml(), encoding="utf-8")
    args = args_obj(category="road", name="unit-track", phase_iters=3, target_dx=0.1, target_dy=0.1, target_dz=0.1, target_ang=0.1, runtime_x_reselect=False)
    calls: list[dict] = []

    def fake_tune_projected(**kwargs):
        calls.append(
            {
                "phase": kwargs["phase"],
                "sub_iter": kwargs["sub_iter"],
                "seg_name": kwargs["seg_name"],
                "att_name": kwargs["att_name"],
                "step": kwargs["step"],
                "target_key": kwargs["target_key"],
                "use_cached_slope": kwargs["use_cached_slope"],
                "max_jump_multiplier": kwargs["max_jump_multiplier"],
                "current_metrics": kwargs["current_metrics"],
            }
        )
        assert kwargs["is_valid_metrics"](metrics_obj(dx=0.0, dy=0.02, ang=0.02))
        return metrics_obj(dx=0.0, dy=0.02, ang=0.02), 2.5, True

    monkeypatch.setattr(close_loop, "tune_projected", fake_tune_projected)
    history: list[dict] = []

    metrics, x_step, x_straight, changed, ok = close_loop.run_phase_c_x(
        track_xml=track_xml,
        runtime_dir=pathlib.Path("runtime"),
        args=args,
        metrics=metrics_obj(dx=2.0, dy=0.02, ang=0.02),
        history=history,
        iter_id=8,
        controls={"x_straight": "Closure Start"},
        x_straight="Closure Start",
        backup_straight="Start",
        primary_straight="Diagonal",
        x_step=1.25,
        x_step_initial=1.25,
        min_straight=0.01,
        ang_lock=0.1,
    )

    assert ok
    assert changed
    assert metrics == metrics_obj(dx=0.0, dy=0.02, ang=0.02)
    assert x_step == pytest.approx(2.5)
    assert x_straight == "Closure Start"
    assert calls == [
        {
            "phase": "C",
            "sub_iter": 1,
            "seg_name": "Closure Start",
            "att_name": "lg",
            "step": 1.25,
            "target_key": "delta_x",
            "use_cached_slope": True,
            "max_jump_multiplier": 64.0,
            "current_metrics": metrics_obj(dx=2.0, dy=0.02, ang=0.02),
        }
    ]


def test_run_phase_c_x_reselects_runtime_control_and_resets_step(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(rich_track_xml(), encoding="utf-8")
    args = args_obj(category="road", name="unit-track", phase_iters=1, target_dx=0.1, target_dy=0.01, target_dz=0.1, target_ang=0.1, runtime_x_reselect=True)
    controls = {"x_straight": "Start"}
    calls: list[dict] = []

    def fake_choose_runtime_x_control(**kwargs):
        calls.append({"fallback_name": kwargs["fallback_name"], "probe_step": kwargs["probe_step"], "current_metrics": kwargs["current_metrics"]})
        return "Closure Start"

    def fake_tune_projected(**kwargs):
        calls.append({"seg_name": kwargs["seg_name"], "step": kwargs["step"]})
        return metrics_obj(dx=0.5, dy=0.2), kwargs["step"] * 0.5, False

    monkeypatch.setattr(close_loop, "choose_runtime_x_control", fake_choose_runtime_x_control)
    monkeypatch.setattr(close_loop, "tune_projected", fake_tune_projected)

    metrics, x_step, x_straight, changed, ok = close_loop.run_phase_c_x(
        track_xml=track_xml,
        runtime_dir=pathlib.Path("runtime"),
        args=args,
        metrics=metrics_obj(dx=1.0, dy=0.2),
        history=[],
        iter_id=9,
        controls=controls,
        x_straight="Start",
        backup_straight="Diagonal",
        primary_straight="Diagonal",
        x_step=0.05,
        x_step_initial=1.0,
        min_straight=0.01,
        ang_lock=0.1,
    )

    assert not ok
    assert not changed
    assert metrics == metrics_obj(dx=0.5, dy=0.2)
    assert x_step == pytest.approx(0.5)
    assert x_straight == "Closure Start"
    assert controls["x_straight"] == "Closure Start"
    assert calls == [
        {"fallback_name": "Start", "probe_step": 1.0, "current_metrics": metrics_obj(dx=1.0, dy=0.2)},
        {"seg_name": "Closure Start", "step": 1.0},
    ]


def test_run_x_structure_fallback_inserts_compensation_straight(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(rich_track_xml(), encoding="utf-8")
    args = args_obj(
        category="road",
        name="unit-track",
        target_dx=0.1,
        allow_x_structure_fallback=True,
        verbose=False,
    )
    controls = {"x_straight": "Closure Start"}
    calls: list[str] = []

    def fake_run(_runtime_dir, _category, _name, under_test):
        text = under_test.read_text(encoding="utf-8")
        if "x_probe_straight" in text:
            calls.append("probe")
            return metrics_obj(dx=4.0, dy=1.0, ang=0.01), ""
        if "x_comp_straight" in text:
            calls.append("insert")
            return metrics_obj(dx=0.2, dy=1.0, ang=0.01), ""
        pytest.fail("fallback should only run probe and insertion trackgen calls")

    monkeypatch.setattr(close_loop, "run_trackgen_z", fake_run)
    history: list[dict] = []

    metrics, x_straight, attempts, changed = close_loop.run_x_structure_fallback(
        track_xml=track_xml,
        runtime_dir=pathlib.Path("runtime"),
        args=args,
        metrics=metrics_obj(dx=5.0, dy=1.0, ang=0.01),
        history=history,
        iter_id=10,
        controls=controls,
        x_straight="Closure Start",
        c_changed=False,
        c_start_dx=5.0,
        x_fallback_attempts=0,
        x_fallback_max=1,
    )

    text = track_xml.read_text(encoding="utf-8")
    assert calls == ["probe", "insert"]
    assert metrics == metrics_obj(dx=0.2, dy=1.0, ang=0.01)
    assert x_straight == "x_comp_straight"
    assert controls["x_straight"] == "x_comp_straight"
    assert attempts == 1
    assert changed
    assert close_loop.read_attnum_value(text, "x_comp_straight", "lg") == pytest.approx(5.0)
    assert history == [
        {
            "iter": 10,
            "phase": "C-fallback",
            "sub_iter": 1,
            "action": "split Right Wide -> Right Wide-xpre + x_comp_straight(5.000000m) + Right Wide",
            "metrics": metrics_obj(dx=0.2, dy=1.0, ang=0.01),
            "objective": 0.2,
        }
    ]


def test_run_x_structure_fallback_restores_xml_when_guard_rejects(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    original = rich_track_xml()
    track_xml.write_text(original, encoding="utf-8")
    args = args_obj(
        category="road",
        name="unit-track",
        target_dx=0.1,
        allow_x_structure_fallback=True,
        verbose=False,
    )

    def fake_run(_runtime_dir, _category, _name, under_test):
        text = under_test.read_text(encoding="utf-8")
        if "x_probe_straight" in text:
            return metrics_obj(dx=4.0, dy=1.0, ang=0.01), ""
        if "x_comp_straight" in text:
            return metrics_obj(dx=0.2, dy=100.0, ang=0.01), ""
        pytest.fail("fallback should only run probe and insertion trackgen calls")

    monkeypatch.setattr(close_loop, "run_trackgen_z", fake_run)
    history: list[dict] = []
    controls = {"x_straight": "Closure Start"}

    metrics, x_straight, attempts, changed = close_loop.run_x_structure_fallback(
        track_xml=track_xml,
        runtime_dir=pathlib.Path("runtime"),
        args=args,
        metrics=metrics_obj(dx=5.0, dy=1.0, ang=0.01),
        history=history,
        iter_id=11,
        controls=controls,
        x_straight="Closure Start",
        c_changed=False,
        c_start_dx=5.0,
        x_fallback_attempts=0,
        x_fallback_max=1,
    )

    assert metrics == metrics_obj(dx=5.0, dy=1.0, ang=0.01)
    assert x_straight == "Closure Start"
    assert controls == {"x_straight": "Closure Start"}
    assert attempts == 0
    assert not changed
    assert history == []
    assert track_xml.read_text(encoding="utf-8") == original


def test_update_broad_loop_progress_tracks_improvement_and_plateau(tmp_path, capsys) -> None:
    track_xml = tmp_path / "track.xml"
    improved_text = rich_track_xml().replace('val="60"', 'val="61"')
    track_xml.write_text(improved_text, encoding="utf-8")
    args = args_obj(target_dx=0.1, target_dy=0.1, target_dz=0.1, target_ang=0.1, plateau_iters=4)
    history: list[dict] = []

    best_metrics, best_text, best_gap, plateau_count, ok, stop = close_loop.update_broad_loop_progress(
        track_xml=track_xml,
        args=args,
        metrics=metrics_obj(dx=0.5),
        history=history,
        iter_id=12,
        straight_step=1.0,
        x_step=0.5,
        radius_step=0.25,
        arc_step=0.1,
        min_straight=0.01,
        min_arc=0.001,
        best_gap=10.0,
        best_metrics=metrics_obj(dx=2.0),
        best_text="old",
        plateau_count=3,
    )

    assert not ok
    assert not stop
    assert best_metrics == metrics_obj(dx=0.5)
    assert best_text == improved_text
    assert best_gap == pytest.approx(0.4)
    assert plateau_count == 0
    assert history == []
    assert "Iter 12: dx=0.500000" in capsys.readouterr().out

    best_metrics, best_text, best_gap, plateau_count, ok, stop = close_loop.update_broad_loop_progress(
        track_xml=track_xml,
        args=args,
        metrics=metrics_obj(dx=2.0),
        history=history,
        iter_id=13,
        straight_step=1.0,
        x_step=0.5,
        radius_step=0.25,
        arc_step=0.1,
        min_straight=0.01,
        min_arc=0.001,
        best_gap=0.4,
        best_metrics=best_metrics,
        best_text=best_text,
        plateau_count=3,
    )

    assert not ok
    assert stop
    assert best_gap == pytest.approx(0.4)
    assert plateau_count == 4
    assert history == [{"iter": 13, "action": "plateau-stop", "metrics": metrics_obj(dx=2.0), "gap": pytest.approx(1.9)}]


def test_update_broad_loop_progress_stops_on_pass_before_best_update(tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(rich_track_xml(), encoding="utf-8")
    args = args_obj(target_dx=0.1, target_dy=0.1, target_dz=0.1, target_ang=0.1, plateau_iters=4)

    best_metrics, best_text, best_gap, plateau_count, ok, stop = close_loop.update_broad_loop_progress(
        track_xml=track_xml,
        args=args,
        metrics=metrics_obj(dx=0.05),
        history=[],
        iter_id=14,
        straight_step=0.001,
        x_step=0.001,
        radius_step=0.001,
        arc_step=0.001,
        min_straight=0.01,
        min_arc=0.01,
        best_gap=2.0,
        best_metrics=metrics_obj(dx=2.0),
        best_text="old",
        plateau_count=2,
    )

    assert ok
    assert stop
    assert best_metrics == metrics_obj(dx=2.0)
    assert best_text == "old"
    assert best_gap == pytest.approx(2.0)
    assert plateau_count == 2


def test_main_select_only_reuses_matching_config(monkeypatch, tmp_path) -> None:
    _, track_xml, config, _report = configure_close_loop_argv(monkeypatch, tmp_path, "--select-only")
    controls = {
        "primary_straight": "Diagonal",
        "primary_turn": "Left Authority",
        "backup_straight": "Start",
        "x_straight": "Closure Start",
        "y_turn": "Left Authority",
    }
    expected_config = matching_config(track_xml, controls)
    config.write_text(json.dumps(expected_config, indent=2), encoding="utf-8")
    monkeypatch.setattr(close_loop, "run_trackgen_z", lambda *_args: (metrics_obj(), ""))

    def fail_pick_controls(_segs):
        pytest.fail("matching config should avoid control reselection")

    monkeypatch.setattr(close_loop, "pick_controls", fail_pick_controls)

    assert close_loop.main() == 0
    assert json.loads(config.read_text(encoding="utf-8")) == expected_config


def test_main_select_only_reselects_stale_config(monkeypatch, tmp_path) -> None:
    _, _track_xml, config, _report = configure_close_loop_argv(monkeypatch, tmp_path, "--select-only")
    config.write_text(json.dumps({"schema": 1, "track_segments_sha256": "stale", "controls": {}}), encoding="utf-8")
    monkeypatch.setattr(close_loop, "run_trackgen_z", lambda *_args: (metrics_obj(), ""))
    refine_order: list[str] = []

    def fake_pick_controls(_segs):
        return {
            "primary_straight": "Start",
            "primary_turn": "Right Wide",
            "backup_straight": "",
            "x_straight": "Start",
            "y_turn": "Right Wide",
        }

    def fake_refine_turn(_track_xml, _runtime_dir, _category, _name, _segs, controls, _metrics):
        refine_order.append("turn")
        controls["primary_turn"] = "Left Authority"
        controls["y_turn"] = "Left Authority"
        return controls

    def fake_refine_y(_track_xml, _runtime_dir, _category, _name, _segs, controls, _metrics):
        refine_order.append("y")
        controls["primary_straight"] = "Diagonal"
        return controls

    def fake_refine_x(_track_xml, _runtime_dir, _category, _name, _segs, controls, _metrics):
        refine_order.append("x")
        controls["x_straight"] = "Closure Start"
        return controls

    monkeypatch.setattr(close_loop, "pick_controls", fake_pick_controls)
    monkeypatch.setattr(close_loop, "refine_turn_controls_by_probe", fake_refine_turn)
    monkeypatch.setattr(close_loop, "refine_y_controls_by_probe", fake_refine_y)
    monkeypatch.setattr(close_loop, "refine_x_controls_by_probe", fake_refine_x)

    assert close_loop.main() == 0
    saved = json.loads(config.read_text(encoding="utf-8"))
    assert refine_order == ["turn", "y", "x"]
    assert saved["schema"] == 1
    assert saved["controls"] == {
        "primary_straight": "Diagonal",
        "primary_turn": "Left Authority",
        "backup_straight": "",
        "x_straight": "Closure Start",
        "y_turn": "Left Authority",
    }
    assert saved["steps"] == {
        "straight": 1.0,
        "arc": 0.1,
        "x_straight": 1.0,
        "radius": 1.0,
        "min_straight": 1e-5,
        "min_arc": 1e-6,
    }


def test_main_full_mode_writes_baseline_not_ready_report(monkeypatch, tmp_path) -> None:
    _, _track_xml, config, report = configure_close_loop_argv(monkeypatch, tmp_path)
    controls = {
        "primary_straight": "Diagonal",
        "primary_turn": "Left Authority",
        "backup_straight": "Start",
        "x_straight": "Closure Start",
        "y_turn": "Left Authority",
    }
    monkeypatch.setattr(close_loop, "run_trackgen_z", lambda *_args: (metrics_obj(dx=25.0), ""))
    monkeypatch.setattr(close_loop, "pick_controls", lambda _segs: dict(controls))
    monkeypatch.setattr(close_loop, "refine_turn_controls_by_probe", lambda _track_xml, _runtime_dir, _category, _name, _segs, controls, _metrics: controls)
    monkeypatch.setattr(close_loop, "refine_y_controls_by_probe", lambda _track_xml, _runtime_dir, _category, _name, _segs, controls, _metrics: controls)
    monkeypatch.setattr(close_loop, "refine_x_controls_by_probe", lambda _track_xml, _runtime_dir, _category, _name, _segs, controls, _metrics: controls)

    assert close_loop.main() == 1
    saved_config = json.loads(config.read_text(encoding="utf-8"))
    saved_report = json.loads(report.read_text(encoding="utf-8"))
    assert saved_config["controls"] == controls
    assert not saved_report["ok"]
    assert not saved_report["baseline_ready"]
    assert saved_report["final_metrics"] == metrics_obj(dx=25.0)
    assert saved_report["history"][-1]["action"] == "baseline-not-closure-ready"
    assert saved_report["best_gap"] == pytest.approx(25.0 - close_loop.DEFAULT_TARGET_DX_M)


def test_main_linear_polish_success_skips_broad_loop(monkeypatch, tmp_path) -> None:
    _, track_xml, config, report = configure_close_loop_argv(monkeypatch, tmp_path, "--linear-polish", "--linear-polish-rounds", "2")
    controls = {
        "primary_straight": "Diagonal",
        "primary_turn": "Left Authority",
        "backup_straight": "Start",
        "x_straight": "Closure Start",
        "y_turn": "Left Authority",
    }
    config.write_text(json.dumps(matching_config(track_xml, controls), indent=2), encoding="utf-8")
    monkeypatch.setattr(close_loop, "run_trackgen_z", lambda *_args: (metrics_obj(dx=0.5), ""))
    linear_calls: list[int] = []

    def fake_linear_polish_once(track_xml, runtime_dir, category, name, metrics, args, history, iter_id):  # noqa: ARG001
        linear_calls.append(iter_id)
        history.append({"iter": iter_id, "phase": "linear-polish", "metrics": metrics_obj()})
        return metrics_obj(), True

    def fail_tune_projected(**_kwargs):
        pytest.fail("passing linear polish should skip the broad closure loop")

    monkeypatch.setattr(close_loop, "linear_polish_once", fake_linear_polish_once)
    monkeypatch.setattr(close_loop, "tune_projected", fail_tune_projected)

    assert close_loop.main() == 0
    saved_report = json.loads(report.read_text(encoding="utf-8"))
    assert linear_calls == [1]
    assert saved_report["ok"]
    assert saved_report["final_metrics"] == metrics_obj()
    assert saved_report["history"][-1]["phase"] == "linear-polish"


def test_trackgen_wrapper_updates_legacy_and_phase_stats(monkeypatch) -> None:
    reset_trackgen_state()
    captured = {}

    class FakeRunner:
        def __init__(self, runtime_dir, cache, stats, allow_missing_live_xml):
            captured["init"] = (runtime_dir, cache, stats, allow_missing_live_xml)
            self.stats = stats

        def run_z(self, category, name, track_xml_under_test):
            captured["run_z"] = (category, name, track_xml_under_test)
            self.stats.calls += 1
            self.stats.seconds += 0.25
            self.stats.cache_hits += 1
            return {"delta_x": 0.0}, "out"

    monkeypatch.setattr(close_loop, "TrackgenRunner", FakeRunner)

    with close_loop.trackgen_phase("probe"):
        metrics, output = close_loop.run_trackgen_z(pathlib.Path("runtime"), "road", "unit", pathlib.Path("track.xml"))

    assert metrics == {"delta_x": 0.0}
    assert output == "out"
    assert captured["init"][0] == pathlib.Path("runtime")
    assert captured["init"][3] is True
    assert captured["run_z"] == ("road", "unit", pathlib.Path("track.xml"))
    assert close_loop.TRACKGEN_CALLS == 1
    assert close_loop.TRACKGEN_SECONDS == pytest.approx(0.25)
    assert close_loop.TRACKGEN_CACHE_HITS == 1
    assert close_loop.runtime_stats()["trackgen_phases"]["probe"] == {"calls": 1, "seconds": 0.25, "cache_hits": 1}


def test_metric_helpers_singular_solve_and_json_writer(tmp_path) -> None:
    args = args_obj(target_dx=0.1, target_dy=0.2, target_dz=0.3, target_ang=0.4)
    passing = {"delta_x": 0.05, "delta_y": -0.1, "delta_z": 0.2, "delta_ang_deg": -0.3}
    rough = {"delta_x": 0.5, "delta_y": -0.7, "delta_z": 0.8, "delta_ang_deg": -1.0}
    out = tmp_path / "nested" / "report.json"

    assert close_loop.passed(passing, args)
    assert not close_loop.passed(rough, args)
    assert close_loop.closure_gap(rough, args) == pytest.approx(2.0)
    assert close_loop.phase_objective({"delta_y": 2.0, "delta_z": 0.5}, "delta_y") == pytest.approx(27.0)
    assert close_loop.solve_3x3([[1.0, 2.0, 3.0], [2.0, 4.0, 6.0], [0.0, 0.0, 0.0]], [1.0, 2.0, 0.0]) is None

    close_loop.write_json(out, {"ok": True})
    assert json.loads(out.read_text(encoding="utf-8")) == {"ok": True}


def test_try_best_of_three_and_tune_once_record_improvement(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    base_text = minimal_track_xml()
    track_xml.write_text(base_text, encoding="utf-8")
    calls: list[float] = []

    def fake_run(_runtime_dir, _category, _name, under_test):
        lg = close_loop.read_attnum_value(under_test.read_text(encoding="utf-8"), "Main Straight", "lg")
        calls.append(lg)
        return {"delta_x": abs(lg - 51.0), "delta_y": 0.0, "delta_z": 0.0, "delta_ang_deg": 0.0}, ""

    monkeypatch.setattr(close_loop, "run_trackgen_z", fake_run)
    monkeypatch.setattr(close_loop, "has_planar_self_intersection", lambda _track_xml: False)

    def objective(metrics: dict) -> float:
        return metrics["delta_x"]

    best_text, best_val, metrics, objective_value = close_loop.try_best_of_three(
        track_xml,
        base_text,
        "Main Straight",
        "lg",
        50.0,
        1.0,
        pathlib.Path("runtime"),
        "road",
        "unit",
        objective,
    )

    assert best_val == pytest.approx(51.0)
    assert metrics["delta_x"] == pytest.approx(0.0)
    assert objective_value == pytest.approx(0.0)
    assert close_loop.read_attnum_value(best_text, "Main Straight", "lg") == pytest.approx(51.0)
    assert calls == [50.0, 51.0, 49.0]

    track_xml.write_text(base_text, encoding="utf-8")
    history: list[dict] = []
    metrics, step, changed = close_loop.tune_once(
        track_xml,
        pathlib.Path("runtime"),
        "road",
        "unit",
        "Main Straight",
        "lg",
        1.0,
        objective,
        history,
        2,
        "phase-x",
        3,
    )

    assert changed
    assert step == pytest.approx(1.0)
    assert metrics["delta_x"] == pytest.approx(0.0)
    assert history[0]["phase"] == "phase-x"
    assert history[0]["action"] == "Main Straight.lg -> 51.00000000"


def test_try_best_of_three_falls_back_when_candidates_are_rejected(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    base_text = minimal_track_xml()
    track_xml.write_text(base_text, encoding="utf-8")
    monkeypatch.setattr(close_loop, "run_trackgen_z", lambda *_args: ({"delta_x": 5.0}, ""))
    monkeypatch.setattr(close_loop, "has_planar_self_intersection", lambda _track_xml: False)

    best_text, best_val, metrics, objective_value = close_loop.try_best_of_three(
        track_xml,
        base_text,
        "Main Straight",
        "lg",
        50.0,
        1.0,
        pathlib.Path("runtime"),
        "road",
        "unit",
        lambda metrics: metrics["delta_x"],
        is_valid_value=lambda _value: False,
    )

    assert best_text == base_text
    assert best_val == pytest.approx(50.0)
    assert metrics == {"delta_x": 5.0}
    assert objective_value == pytest.approx(5.0)
