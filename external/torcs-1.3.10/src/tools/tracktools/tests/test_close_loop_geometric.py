
import json
import pathlib

import pytest

import torcs_track_tools.cli.close_loop_geometric as geom


def args_obj(**overrides):
    values = {
        "target_dx": 0.1,
        "target_dy": 0.1,
        "target_dz": 0.1,
        "target_ang": 0.1,
        "max_yang_iters": 3,
        "max_control_delta": 30.0,
        "post_pit_turn_candidates": 8,
        "post_pit_straight_candidates": 8,
        "post_pit_terminal_candidates": 0,
        "min_start_straight": 0.1,
        "insert_straight_length": 0.15,
        "max_cycles": 2,
        "profile": "mainline",
        "trackgen_timeout": 30.0,
        "verbose": False,
        "track_xml": "track.xml",
        "runtime_dir": "runtime",
        "category": "road",
        "name": "unit",
        "report": "report.json",
        "source_polyline": "",
        "comparison_svg": "",
        "comparison_report": "",
        "comparison_samples": 4,
    }
    values.update(overrides)
    return type("Args", (), values)()


def test_solve_2x2_returns_expected_solution() -> None:
    sol = geom.solve_2x2(2.0, 0.0, 0.0, 4.0, 6.0, 20.0)

    assert sol == (3.0, 5.0)


def test_solve_3x3_returns_expected_solution() -> None:
    sol = geom.solve_3x3([2.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 5.0], [6.0, 20.0, 30.0])

    assert sol == (3.0, 5.0, 6.0)


def test_terminal_delta_candidates_prioritize_small_changes() -> None:
    candidates = geom.terminal_delta_candidates(1.0, args_obj(insert_straight_length=0.15))

    assert candidates[0] == pytest.approx(0.0)
    assert len(candidates) == len(set(candidates))
    assert [abs(value) for value in candidates] == sorted(abs(value) for value in candidates)


def test_terminal_delta_candidates_can_be_limited() -> None:
    candidates = geom.terminal_delta_candidates(1.0, args_obj(post_pit_terminal_candidates=5))

    assert len(candidates) == 5
    assert candidates[0] == pytest.approx(0.0)


def test_parse_args_mainline_uses_trackgen_y_quantum_default(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "close_loop_geometric.py",
            "--track-xml",
            "track.xml",
            "--runtime-dir",
            "runtime",
            "--category",
            "road",
            "--name",
            "track",
            "--report",
            "report.json",
        ],
    )

    args = geom.parse_args()

    assert args.target_dy == 0.001


def test_parse_args_post_pit_applies_profile_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "close_loop_geometric.py",
            "--profile",
            "post-pit",
            "--track-xml",
            "track.xml",
            "--runtime-dir",
            "runtime",
            "--category",
            "road",
            "--name",
            "track",
            "--report",
            "report.json",
        ],
    )

    args = geom.parse_args()

    assert args.target_dy == 0.002
    assert args.insert_straight_length == 0.1


def test_parse_args_post_pit_respects_explicit_y_tolerance(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "close_loop_geometric.py",
            "--profile",
            "post-pit",
            "--track-xml",
            "track.xml",
            "--runtime-dir",
            "runtime",
            "--category",
            "road",
            "--name",
            "track",
            "--report",
            "report.json",
            "--target-dy",
            "0.0005",
        ],
    )

    args = geom.parse_args()

    assert args.target_dy == 0.0005


def test_metric_helpers_and_verbose_logging(monkeypatch, capsys) -> None:
    args = type("Args", (), {"target_dx": 0.1, "target_dy": 0.2, "target_dz": 0.3, "target_ang": 0.4})()
    metrics = {"delta_x": 0.05, "delta_y": -0.1, "delta_z": 0.2, "delta_ang_deg": -0.3}
    rough = {"delta_x": 0.5, "delta_y": -0.7, "delta_z": 0.8, "delta_ang_deg": -1.0}

    assert geom.passed(metrics, args)
    assert geom.yang_passed(metrics, args)
    assert not geom.passed(rough, args)
    assert not geom.yang_passed(rough, args)
    assert geom.gap(rough, args) == pytest.approx(2.0)
    assert geom.yang_score(rough, args) == pytest.approx(15.5)

    monkeypatch.setattr(geom, "VERBOSE", False)
    geom.log("hidden")
    assert capsys.readouterr().out == ""

    monkeypatch.setattr(geom, "VERBOSE", True)
    geom.log("visible")
    assert capsys.readouterr().out == "visible\n"


def test_runtime_stats_reflects_global_counters(monkeypatch) -> None:
    stats = type("Stats", (), {"calls": 3, "seconds": 1.25, "cache_hits": 2})()
    monkeypatch.setattr(geom, "TRACKGEN_STATS", stats)
    monkeypatch.setattr(geom, "SELF_INTERSECTION_CHECKS", 4)
    monkeypatch.setattr(geom, "SELF_INTERSECTION_SECONDS", 0.5)

    assert geom.runtime_stats() == {
        "trackgen_calls": 3,
        "trackgen_seconds": 1.25,
        "trackgen_cache_hits": 2,
        "self_intersection_checks": 4,
        "self_intersection_seconds": 0.5,
    }


def test_trackgen_and_intersection_wrappers_delegate_and_update_stats(monkeypatch) -> None:
    captured = {}

    class FakeRunner:
        def __init__(self, runtime_dir, timeout_s, cache, stats, allow_missing_live_xml, log):
            captured["runner"] = {
                "runtime_dir": runtime_dir,
                "timeout_s": timeout_s,
                "cache": cache,
                "stats": stats,
                "allow_missing_live_xml": allow_missing_live_xml,
                "log": log,
            }

        def run_z(self, category, name, track_xml_under_test):
            captured["run_z"] = (category, name, track_xml_under_test)
            return {"delta_x": 0.0}, "trackgen output"

    monkeypatch.setattr(geom, "TRACKGEN_TIMEOUT_S", 12.5)
    monkeypatch.setattr(geom, "TRACKGEN_CACHE", {("road", "unit", "xml"): ({}, "")})
    monkeypatch.setattr(geom, "TRACKGEN_STATS", type("Stats", (), {"calls": 0, "seconds": 0.0, "cache_hits": 0})())
    monkeypatch.setattr(geom, "TrackgenRunner", FakeRunner)

    metrics, output = geom.run_trackgen_z(pathlib.Path("runtime"), "road", "unit", pathlib.Path("track.xml"))

    assert metrics == {"delta_x": 0.0}
    assert output == "trackgen output"
    assert captured["runner"]["runtime_dir"] == pathlib.Path("runtime")
    assert captured["runner"]["timeout_s"] == 12.5
    assert captured["runner"]["allow_missing_live_xml"] is True
    assert captured["run_z"] == ("road", "unit", pathlib.Path("track.xml"))

    monkeypatch.setattr(geom, "SELF_INTERSECTION_CHECKS", 0)
    monkeypatch.setattr(geom, "SELF_INTERSECTION_SECONDS", 0.0)
    monkeypatch.setattr(geom, "has_planar_self_intersection", lambda track_xml: track_xml.name == "bad.xml")

    assert geom.has_intersection(pathlib.Path("bad.xml"))
    assert geom.SELF_INTERSECTION_CHECKS == 1
    assert geom.SELF_INTERSECTION_SECONDS >= 0.0


def test_closed_polyline_sampling_and_shift_helpers() -> None:
    points = [
        {"x": 0.0, "y": 0.0, "seg": "a"},
        {"x": 10.0, "y": 0.0, "seg": "b"},
        {"x": 10.0, "y": 10.0, "seg": "c"},
        {"x": 0.0, "y": 10.0, "seg": "d"},
        {"x": 0.0, "y": 0.0, "seg": "duplicate"},
    ]

    assert geom.loop_distance(points[0], points[1]) == pytest.approx(10.0)
    assert geom.strip_duplicate_loop_endpoint(points) == points[:-1]
    sampled, total = geom.sample_closed_by_arc(points, 4)

    assert total == pytest.approx(40.0)
    assert [(p["x"], p["y"]) for p in sampled] == pytest.approx([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    assert geom.shifted_cycle([], 3) == []
    assert geom.shifted_cycle([1, 2, 3], 4) == [2, 3, 1]

    with pytest.raises(RuntimeError, match="too short"):
        geom.sample_closed_by_arc([{"x": 0.0, "y": 0.0}], 4)
    with pytest.raises(RuntimeError, match="length is zero"):
        geom.sample_closed_by_arc([{"x": 0.0, "y": 0.0}, {"x": 0.0, "y": 0.0}, {"x": 0.0, "y": 0.0}], 4)


def test_json_and_segment_text_helpers(tmp_path) -> None:
    out = tmp_path / "nested" / "report.json"
    geom.write_json(out, {"ok": True})
    assert json.loads(out.read_text(encoding="utf-8")) == {"ok": True}

    text = """
<params>
  <section name="Track Segments">
    <section name="start"><attstr name="type" val="str"/><attnum name="lg" val="20" /></section>
  </section>
</params>
""".strip()
    segs = geom.parse_top_level_segments(text)
    renamed_raw = geom.replace_section_name(segs[0]["raw"], "renamed")
    resized_raw = geom.replace_raw_attnum(renamed_raw, "lg", 12.5)
    rebuilt = geom.rebuild_track_segments_text(text, [{**segs[0], "raw": resized_raw}])

    assert geom.rebuild_track_segments_text(text, []) == text
    assert 'section name="renamed"' in rebuilt
    assert 'val="12.50000000"' in rebuilt
    assert 'section name="Closure Start"' in geom.insert_start_straight(text, 0.25)

    with pytest.raises(RuntimeError, match="Attribute"):
        geom.replace_raw_attnum(segs[0]["raw"], "missing", 1.0)
    with pytest.raises(RuntimeError, match="Track Segments"):
        geom.insert_start_straight("<params />", 1.0)


def test_write_final_comparison_writes_overlay_and_report(monkeypatch, tmp_path) -> None:
    source_polyline = tmp_path / "source.json"
    track_xml = tmp_path / "track.xml"
    overlay = tmp_path / "overlay.svg"
    report_path = tmp_path / "comparison.json"
    square = [
        {"x": 0.0, "y": 0.0, "seg": "a"},
        {"x": 10.0, "y": 0.0, "seg": "b"},
        {"x": 10.0, "y": 10.0, "seg": "c"},
        {"x": 0.0, "y": 10.0, "seg": "d"},
    ]
    source_polyline.write_text(json.dumps({"polyline": square}), encoding="utf-8")
    track_xml.write_text("<params />", encoding="utf-8")
    monkeypatch.setattr(geom, "overlay_to_xy", lambda polyline: polyline)
    monkeypatch.setattr(geom, "parse_overlay_track_segments", lambda _text: [{"name": "model"}])
    monkeypatch.setattr(geom, "overlay_torcs_points", lambda _segs, **_kwargs: square)
    monkeypatch.setattr(geom, "nearest_polyline_distance", lambda _point, _polyline, **_kwargs: 0.5)
    monkeypatch.setattr(geom, "write_overlay_svg", lambda path, _src, _model: path.write_text("<svg />", encoding="utf-8"))

    report = geom.write_final_comparison(track_xml, source_polyline, overlay, report_path, samples=4)

    assert overlay.read_text(encoding="utf-8") == "<svg />"
    assert json.loads(report_path.read_text(encoding="utf-8"))["rmse_deviation_m"] == pytest.approx(0.5)
    assert report["source_length_m"] == pytest.approx(40.0)
    assert report["torcs_length_m"] == pytest.approx(40.0)
    assert report["mean_deviation_m"] == pytest.approx(0.5)
    assert report["max_deviation"]["d"] == pytest.approx(0.5)


def test_write_final_comparison_rejects_bad_inputs(monkeypatch, tmp_path) -> None:
    source_polyline = tmp_path / "source.json"
    track_xml = tmp_path / "track.xml"
    source_polyline.write_text(json.dumps({"polyline": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}]}), encoding="utf-8")
    track_xml.write_text("<params />", encoding="utf-8")
    monkeypatch.setattr(geom, "overlay_to_xy", lambda polyline: polyline)

    with pytest.raises(RuntimeError, match="too short"):
        geom.write_final_comparison(track_xml, source_polyline, tmp_path / "overlay.svg", tmp_path / "report.json", samples=4)

    source_polyline.write_text(
        json.dumps({"polyline": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(geom, "parse_overlay_track_segments", lambda _text: [])
    with pytest.raises(RuntimeError, match="No TORCS"):
        geom.write_final_comparison(track_xml, source_polyline, tmp_path / "overlay.svg", tmp_path / "report.json", samples=4)


def test_ensure_starts_on_straight_rotates_existing_straight(tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(
        """
<params>
  <section name="Track Segments">
    <section name="turn">
      <attstr name="type" val="lft"/>
      <attnum name="radius" val="50" />
      <attnum name="arc" val="10" />
    </section>
    <section name="straight">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="20" />
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    args = type("Args", (), {"min_start_straight": 0.1, "insert_straight_length": 1.0})()
    history = []

    start_name = geom.ensure_starts_on_straight(track_xml, args, history)

    assert start_name == "straight"
    assert geom.parse_top_level_segments(track_xml.read_text(encoding="utf-8"))[0]["name"] == "straight"
    assert history[0]["action"] == "rotate-start"


def test_ensure_starts_on_straight_keeps_existing_usable_start(tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(
        """
<params>
  <section name="Track Segments">
    <section name="start"><attstr name="type" val="str"/><attnum name="lg" val="5"/></section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    history = []

    assert geom.ensure_starts_on_straight(track_xml, args_obj(min_start_straight=0.1, insert_straight_length=1.0), history) == "start"
    assert history == []


def test_ensure_starts_on_straight_inserts_or_rejects_empty_segment_block(tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(
        """
<params>
  <section name="Track Segments">
    <section name="turn"><attstr name="type" val="lft"/><attnum name="radius" val="50"/><attnum name="arc" val="10"/></section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    args = type("Args", (), {"min_start_straight": 0.1, "insert_straight_length": 1.5})()
    history = []

    assert geom.ensure_starts_on_straight(track_xml, args, history) == "Closure Start"
    assert geom.parse_top_level_segments(track_xml.read_text(encoding="utf-8"))[0]["name"] == "Closure Start"
    assert history == [{"action": "insert-start-straight", "length": 1.5}]

    empty_xml = tmp_path / "empty.xml"
    empty_xml.write_text('<params><section name="Track Segments"></section></params>', encoding="utf-8")
    with pytest.raises(RuntimeError, match="No track segments"):
        geom.ensure_starts_on_straight(empty_xml, args, [])


def test_prepare_terminal_x_lever_splits_first_straight_to_end(tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(
        """
<params>
  <section name="Track Segments">
    <section name="start">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="20" />
    </section>
    <section name="turn">
      <attstr name="type" val="lft"/>
      <attnum name="radius" val="50" />
      <attnum name="arc" val="10" />
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    args = type("Args", (), {"profile": "mainline", "min_start_straight": 0.1, "insert_straight_length": 1.0, "terminal_split_min": 10.0})()
    history = []

    start_name, terminal_name = geom.prepare_terminal_x_lever(track_xml, args, history)
    segs = geom.parse_top_level_segments(track_xml.read_text(encoding="utf-8"))

    assert start_name == "start"
    assert terminal_name == "Closure X Terminal"
    assert [seg["name"] for seg in segs] == ["start", "turn", "Closure X Terminal"]
    assert segs[0]["attrs"]["lg"] == "10.00000000"
    assert segs[-1]["attrs"]["lg"] == "10.00000000"
    assert history[0]["action"] == "split-terminal-x-lever"


def test_prepare_terminal_x_lever_rejects_empty_segment_block(tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text('<params><section name="Track Segments"></section></params>', encoding="utf-8")

    with pytest.raises(RuntimeError, match="No track segments"):
        geom.prepare_terminal_x_lever(track_xml, args_obj(profile="mainline", terminal_split_min=10.0), [])


def test_prepare_terminal_x_lever_rotates_short_usable_straight_then_appends(tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(
        """
<params>
  <section name="Track Segments">
    <section name="turn"><attstr name="type" val="lft"/><attnum name="radius" val="50"/><attnum name="arc" val="10"/></section>
    <section name="short"><attstr name="type" val="str"/><attnum name="lg" val="5"/></section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    args = type("Args", (), {"profile": "mainline", "min_start_straight": 0.1, "insert_straight_length": 2.0, "terminal_split_min": 20.0})()
    history = []

    start_name, terminal_name = geom.prepare_terminal_x_lever(track_xml, args, history)
    segs = geom.parse_top_level_segments(track_xml.read_text(encoding="utf-8"))

    assert start_name == "short"
    assert terminal_name == "Closure X Terminal"
    assert [seg["name"] for seg in segs] == ["short", "turn", "Closure X Terminal"]
    assert history == [
        {"action": "rotate-start", "segment": "short"},
        {"action": "append-terminal-x-lever", "terminal_segment": "Closure X Terminal", "lg": 2.0},
    ]


def test_prepare_terminal_x_lever_post_pit_preserves_pit_main_b_start(tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(
        """
<params>
  <section name="Track Segments">
    <section name="pit_main_b">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="150" />
    </section>
    <section name="long-straight">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="300" />
    </section>
    <section name="pit_main_a">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="150" />
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    args = type("Args", (), {"profile": "post-pit", "insert_straight_length": 1.0})()
    history = []

    start_name, terminal_name = geom.prepare_terminal_x_lever(track_xml, args, history)
    segs = geom.parse_top_level_segments(track_xml.read_text(encoding="utf-8"))

    assert start_name == "pit_main_b"
    assert terminal_name == "Closure X Terminal"
    assert [seg["name"] for seg in segs] == ["pit_main_b", "long-straight", "pit_main_a", "Closure X Terminal"]
    assert history == [{"action": "append-terminal-x-lever", "terminal_segment": "Closure X Terminal", "after_segment": "pit_main_a", "lg": 1.0, "profile": "post-pit"}]


def test_prepare_terminal_x_lever_post_pit_rotates_to_pit_main_b(tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(
        """
<params>
  <section name="Track Segments">
    <section name="long-straight">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="300" />
    </section>
    <section name="pit_main_b">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="150" />
    </section>
    <section name="pit_main_a">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="150" />
    </section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    args = type("Args", (), {"profile": "post-pit", "insert_straight_length": 1.0})()
    history = []

    start_name, terminal_name = geom.prepare_terminal_x_lever(track_xml, args, history)
    segs = geom.parse_top_level_segments(track_xml.read_text(encoding="utf-8"))

    assert start_name == "pit_main_b"
    assert terminal_name == "Closure X Terminal"
    assert [seg["name"] for seg in segs] == ["pit_main_b", "pit_main_a", "long-straight", "Closure X Terminal"]
    assert history == [
        {"action": "rotate-start", "segment": "pit_main_b", "profile": "post-pit"},
        {"action": "append-terminal-x-lever", "terminal_segment": "Closure X Terminal", "after_segment": "long-straight", "lg": 1.0, "profile": "post-pit"},
    ]


def test_valid_att_delta_allows_tiny_closure_terminal() -> None:
    text = """
<params>
  <section name="Track Segments">
    <section name="Closure X Terminal">
      <attstr name="type" val="str"/>
      <attnum name="lg" val="1.0" />
    </section>
  </section>
</params>
""".strip()

    assert geom.valid_att_delta(text, "Closure X Terminal", "lg", -0.98, 0.1)
    assert not geom.valid_att_delta(text, "Closure X Terminal", "lg", -0.995, 0.1)


def test_singular_solvers_and_att_delta_bounds() -> None:
    text = """
<params>
  <section name="Track Segments">
    <section name="turn"><attstr name="type" val="lft"/><attnum name="radius" val="80" /><attnum name="arc" val="10" /></section>
    <section name="straight"><attstr name="type" val="str"/><attnum name="lg" val="1.0" /></section>
  </section>
</params>
""".strip()

    assert geom.solve_2x2(1.0, 2.0, 2.0, 4.0, 1.0, 1.0) is None
    assert geom.solve_3x3([1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0], [1.0, 1.0, 1.0]) is None
    assert not geom.valid_att_delta(text, "missing", "lg", 1.0)
    assert not geom.valid_att_delta(text, "turn", "arc", -10.0)
    assert not geom.valid_att_delta(text, "turn", "arc", 350.0)
    assert geom.valid_att_delta(text, "turn", "radius", -1000.0)


def test_top_y_straights_prefers_non_parallel_to_start() -> None:
    text = """
<params>
  <section name="Track Segments">
    <section name="start"><attstr name="type" val="str"/><attnum name="lg" val="20" /></section>
    <section name="turn"><attstr name="type" val="lft"/><attnum name="radius" val="10" /><attnum name="arc" val="90" /></section>
    <section name="perp"><attstr name="type" val="str"/><attnum name="lg" val="20" /></section>
    <section name="turn2"><attstr name="type" val="rgt"/><attnum name="radius" val="10" /><attnum name="arc" val="90" /></section>
    <section name="parallel"><attstr name="type" val="str"/><attnum name="lg" val="100" /></section>
  </section>
</params>
""".strip()

    y_straights = geom.top_y_straights(geom.parse_top_level_segments(text), "start")

    assert y_straights[0]["name"] == "perp"


def test_top_angle_turns_filters_low_authority_and_pit_turns() -> None:
    text = """
<params>
  <section name="Track Segments">
    <section name="start"><attstr name="type" val="str"/><attnum name="lg" val="20" /></section>
    <section name="good"><attstr name="type" val="lft"/><attnum name="radius" val="80" /><attnum name="arc" val="20" /></section>
    <section name="pit_turn"><attstr name="type" val="rgt"/><attnum name="radius" val="80" /><attnum name="arc" val="30" /></section>
    <section name="clothoid"><attstr name="type" val="lft"/><attnum name="radius" val="80" /><attnum name="end radius" val="90" /><attnum name="arc" val="20" /></section>
    <section name="tiny"><attstr name="type" val="lft"/><attnum name="radius" val="1" /><attnum name="arc" val="20" /></section>
  </section>
</params>
""".strip()

    turns = geom.top_angle_turns(geom.parse_top_level_segments(text))

    assert [turn["name"] for turn in turns] == ["good"]
    assert turns[0]["geom_angle_score"] > 0.0


def test_insert_y_leverage_reports_no_candidate_or_inserted_split(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(
        """
<params>
  <section name="Track Segments">
    <section name="start"><attstr name="type" val="str"/><attnum name="lg" val="20" /></section>
    <section name="small"><attstr name="type" val="lft"/><attnum name="radius" val="80"/><attnum name="arc" val="10"/></section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    args = type("Args", (), {"insert_straight_length": 1.0})()
    history = []

    assert not geom.insert_y_leverage(track_xml, "start", args, history)
    assert history == []

    track_xml.write_text(
        """
<params>
  <section name="Track Segments">
    <section name="start"><attstr name="type" val="str"/><attnum name="lg" val="20" /></section>
    <section name="wide"><attstr name="type" val="lft"/><attnum name="radius" val="200"/><attnum name="arc" val="10"/></section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )

    def fake_split(text: str, turn_name: str, straight_name: str, length: float) -> tuple[str, str]:
        assert turn_name == "wide"
        assert straight_name == "y_comp_straight"
        assert length == pytest.approx(0.01)
        return text.replace('name="wide"', 'name="wide-before"'), "wide-before"

    monkeypatch.setattr(geom, "split_turn_with_straight_insert", fake_split)

    assert geom.insert_y_leverage(track_xml, "start", args, history, straight_lg=-5.0)
    assert history == [{"action": "insert-y-leverage", "turn": "wide", "pre_turn": "wide-before", "straight": "y_comp_straight", "lg": 0.01}]


def test_probe_metric_delta_restores_text_after_success_or_failure(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    base_text = """
<params>
  <section name="Track Segments">
    <section name="probe"><attstr name="type" val="str"/><attnum name="lg" val="10" /></section>
  </section>
</params>
""".strip()
    track_xml.write_text(base_text, encoding="utf-8")
    base_metrics = {"delta_ang_deg": 1.0, "delta_y": 2.0, "delta_x": 3.0}

    def fake_run(runtime_dir: pathlib.Path, category: str, name: str, under_test: pathlib.Path) -> tuple[dict, str]:
        assert runtime_dir == pathlib.Path("runtime")
        assert category == "road"
        assert name == "unit"
        assert under_test.read_text(encoding="utf-8") != base_text
        return {"delta_ang_deg": 1.5, "delta_y": 4.0, "delta_x": 8.0}, ""

    monkeypatch.setattr(geom, "run_trackgen_z", fake_run)

    assert geom.probe_metric_delta(track_xml, pathlib.Path("runtime"), "road", "unit", base_text, base_metrics, "probe", "lg", 0.5) == pytest.approx([1.0, 4.0, 10.0])
    assert track_xml.read_text(encoding="utf-8") == base_text

    def failing_run(*_args: object) -> tuple[dict, str]:
        raise RuntimeError("trackgen failed")

    monkeypatch.setattr(geom, "run_trackgen_z", failing_run)
    assert geom.probe_metric_delta(track_xml, pathlib.Path("runtime"), "road", "unit", base_text, base_metrics, "probe", "lg", 0.5) is None
    assert track_xml.read_text(encoding="utf-8") == base_text


def test_choose_yang_controls_returns_none_or_best_valid_pair(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text("base", encoding="utf-8")
    metrics = {"delta_ang_deg": 2.0, "delta_y": -4.0}
    args = type("Args", (), {"max_control_delta": 30.0, "min_start_straight": 0.1})()

    monkeypatch.setattr(geom, "parse_top_level_segments", lambda _text: [{"name": "sentinel"}])
    monkeypatch.setattr(geom, "top_angle_turns", lambda _segs: [{"name": "turn", "geom_angle_score": 2.0}])
    monkeypatch.setattr(geom, "top_y_straights", lambda _segs, _start_name: [])
    assert geom.choose_yang_controls(track_xml, pathlib.Path("runtime"), "road", "unit", "start", metrics, args) is None

    monkeypatch.setattr(geom, "top_y_straights", lambda _segs, _start_name: [{"name": "straight", "geom_y_score": 3.0}])

    def fake_probe(_track_xml, _runtime_dir, _category, _name, _base_text, _metrics, seg_name, att_name, step):
        if seg_name == "turn" and att_name == "arc" and step == 0.001:
            return [1.0, 0.0, 0.0]
        if seg_name == "straight" and att_name == "lg" and step == 1.0:
            return [0.0, 1.0, 0.0]
        return None

    monkeypatch.setattr(geom, "probe_metric_delta", fake_probe)
    monkeypatch.setattr(geom, "valid_att_delta", lambda *_args: True)

    controls = geom.choose_yang_controls(track_xml, pathlib.Path("runtime"), "road", "unit", "start", metrics, args)

    assert controls is not None
    assert controls["turn"] == "turn"
    assert controls["straight"] == "straight"
    assert controls["arc_delta"] == pytest.approx(-2.0)
    assert controls["straight_delta"] == pytest.approx(4.0)


def test_choose_yang_controls_rejects_singular_large_or_invalid_solutions(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text("base", encoding="utf-8")
    args = args_obj(max_control_delta=30.0, min_start_straight=0.1)
    monkeypatch.setattr(geom, "parse_top_level_segments", lambda _text: [{"name": "sentinel"}])
    monkeypatch.setattr(geom, "top_angle_turns", lambda _segs: [{"name": "turn", "geom_angle_score": 2.0}])
    monkeypatch.setattr(geom, "top_y_straights", lambda _segs, _start_name: [{"name": "straight", "geom_y_score": 3.0}])

    def set_probe(turn_sens, straight_sens):
        def fake_probe(_track_xml, _runtime_dir, _category, _name, _base_text, _metrics, seg_name, att_name, _step):
            if seg_name == "turn" and att_name == "arc":
                return turn_sens
            if seg_name == "straight" and att_name == "lg":
                return straight_sens
            return None

        monkeypatch.setattr(geom, "probe_metric_delta", fake_probe)

    set_probe([1.0, 1.0, 0.0], [2.0, 2.0, 0.0])
    assert geom.choose_yang_controls(track_xml, pathlib.Path("runtime"), "road", "unit", "start", {"delta_ang_deg": 1.0, "delta_y": 1.0}, args) is None

    set_probe([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    assert geom.choose_yang_controls(track_xml, pathlib.Path("runtime"), "road", "unit", "start", {"delta_ang_deg": 100.0, "delta_y": 1.0}, args) is None

    monkeypatch.setattr(geom, "valid_att_delta", lambda _text, seg, _att, _delta, *_args: seg != "turn")
    assert geom.choose_yang_controls(track_xml, pathlib.Path("runtime"), "road", "unit", "start", {"delta_ang_deg": 1.0, "delta_y": 1.0}, args) is None

    monkeypatch.setattr(geom, "valid_att_delta", lambda _text, seg, _att, _delta, *_args: seg != "straight")
    assert geom.choose_yang_controls(track_xml, pathlib.Path("runtime"), "road", "unit", "start", {"delta_ang_deg": 1.0, "delta_y": 1.0}, args) is None


def test_apply_deltas_and_terminal_x_adjustment(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    base_text = """
<params>
  <section name="Track Segments">
    <section name="Closure X Terminal"><attstr name="type" val="str"/><attnum name="lg" val="5" /></section>
  </section>
</params>
""".strip()
    track_xml.write_text(base_text, encoding="utf-8")
    args = type("Args", (), {"target_dx": 0.1, "target_dy": 0.1, "target_dz": 0.1, "target_ang": 0.1, "min_start_straight": 0.1})()

    assert 'val="3.00000000"' in geom.apply_deltas(base_text, [("Closure X Terminal", "lg", -2.0)])

    passed_metrics = {"delta_x": 0.0, "delta_y": 0.0, "delta_z": 0.0, "delta_ang_deg": 0.0}
    assert geom.adjust_terminal_x(track_xml, pathlib.Path("runtime"), "road", "unit", "Closure X Terminal", passed_metrics, args, []) == (passed_metrics, False, True)

    unsolved_y = {"delta_x": 1.0, "delta_y": 1.0, "delta_z": 0.0, "delta_ang_deg": 0.0}
    assert geom.adjust_terminal_x(track_xml, pathlib.Path("runtime"), "road", "unit", "Closure X Terminal", unsolved_y, args, []) == (unsolved_y, False, False)

    monkeypatch.setattr(geom, "probe_metric_delta", lambda *_args: [0.0, 0.0, 2.0])
    monkeypatch.setattr(geom, "run_trackgen_z", lambda *_args: (passed_metrics, ""))
    history: list[dict] = []
    metrics = {"delta_x": 4.0, "delta_y": 0.0, "delta_z": 0.0, "delta_ang_deg": 0.0}

    adjusted, changed, ok = geom.adjust_terminal_x(track_xml, pathlib.Path("runtime"), "road", "unit", "Closure X Terminal", metrics, args, history)

    assert adjusted == passed_metrics
    assert changed
    assert ok
    assert history[0]["phase"] == "solve-x-terminal"
    assert history[0]["delta_lg"] == pytest.approx(-2.0)


def test_terminal_x_adjustment_rejects_missing_sensitivity_or_failed_trials(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    base_text = """
<params>
  <section name="Track Segments">
    <section name="Closure X Terminal"><attstr name="type" val="str"/><attnum name="lg" val="5" /></section>
  </section>
</params>
""".strip()
    track_xml.write_text(base_text, encoding="utf-8")
    args = args_obj(target_dx=0.1, target_dy=0.1, target_ang=0.1, min_start_straight=0.1)
    metrics = {"delta_x": 4.0, "delta_y": 0.0, "delta_z": 0.0, "delta_ang_deg": 0.0}

    monkeypatch.setattr(geom, "probe_metric_delta", lambda *_args: None)
    assert geom.adjust_terminal_x(track_xml, pathlib.Path("runtime"), "road", "unit", "Closure X Terminal", metrics, args, []) == (metrics, False, False)

    monkeypatch.setattr(geom, "probe_metric_delta", lambda *_args: [0.0, 0.0, 2.0])
    monkeypatch.setattr(geom, "run_trackgen_z", lambda *_args: (_ for _ in ()).throw(RuntimeError("trackgen failed")))
    assert geom.adjust_terminal_x(track_xml, pathlib.Path("runtime"), "road", "unit", "Closure X Terminal", metrics, args, []) == (metrics, False, False)
    assert track_xml.read_text(encoding="utf-8") == base_text


def test_solve_yang_returns_immediately_when_y_and_angle_pass(tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text("base", encoding="utf-8")
    metrics = {"delta_y": 0.0, "delta_ang_deg": 0.0}

    assert geom.solve_yang(track_xml, pathlib.Path("runtime"), "road", "unit", "start", metrics, args_obj(), []) == (metrics, False)


def test_solve_yang_accepts_improving_control_pair(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    base_text = """
<params>
  <section name="Track Segments">
    <section name="turn"><attstr name="type" val="lft"/><attnum name="radius" val="80"/><attnum name="arc" val="10" /></section>
    <section name="straight"><attstr name="type" val="str"/><attnum name="lg" val="10" /></section>
  </section>
</params>
""".strip()
    track_xml.write_text(base_text, encoding="utf-8")
    args = args_obj(target_dy=0.1, target_ang=0.1, max_yang_iters=2, min_start_straight=0.1)
    metrics = {"delta_y": 2.0, "delta_ang_deg": 1.0}
    passed_metrics = {"delta_y": 0.0, "delta_ang_deg": 0.0}
    controls = {"turn": "turn", "straight": "straight", "arc_delta": -1.0, "straight_delta": -2.0}
    monkeypatch.setattr(geom, "choose_yang_controls", lambda *_args: controls)
    monkeypatch.setattr(geom, "run_trackgen_z", lambda *_args: (passed_metrics, ""))
    monkeypatch.setattr(geom, "has_intersection", lambda _track_xml: False)
    history: list[dict] = []

    result, changed = geom.solve_yang(track_xml, pathlib.Path("runtime"), "road", "unit", "start", metrics, args, history)

    assert result == passed_metrics
    assert changed
    assert history == [
        {
            "phase": "solve-yang",
            "iter": 1,
            "scale": 1.0,
            "turn": "turn",
            "y_straight": "straight",
            "deltas": {"turn.arc": -1.0, "straight.lg": -2.0},
            "metrics": passed_metrics,
        }
    ]


def test_solve_yang_uses_polish_fallback_when_controls_fail(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text("base", encoding="utf-8")
    args = args_obj(target_dy=0.1, target_ang=0.1, max_yang_iters=2)
    metrics = {"delta_y": 2.0, "delta_ang_deg": 1.0}
    polished = {"delta_y": 0.0, "delta_ang_deg": 0.0}
    monkeypatch.setattr(geom, "choose_yang_controls", lambda *_args: None)
    monkeypatch.setattr(geom, "polish_yang_axis", lambda *_args: (polished, True))

    assert geom.solve_yang(track_xml, pathlib.Path("runtime"), "road", "unit", "start", metrics, args, []) == (polished, True)

    controls = {"turn": "turn", "straight": "straight", "arc_delta": -1.0, "straight_delta": -2.0}
    monkeypatch.setattr(geom, "choose_yang_controls", lambda *_args: controls)
    monkeypatch.setattr(geom, "valid_att_delta", lambda *_args: False)
    monkeypatch.setattr(geom, "polish_yang_axis", lambda *_args: (metrics, False))

    assert geom.solve_yang(track_xml, pathlib.Path("runtime"), "road", "unit", "start", metrics, args, []) == (metrics, False)
    assert track_xml.read_text(encoding="utf-8") == "base"


def test_polish_yang_axis_accepts_y_or_angle_improvements(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    base_text = """
<params>
  <section name="Track Segments">
    <section name="y"><attstr name="type" val="str"/><attnum name="lg" val="10" /></section>
    <section name="turn"><attstr name="type" val="lft"/><attnum name="radius" val="80"/><attnum name="arc" val="10" /></section>
  </section>
</params>
""".strip()
    track_xml.write_text(base_text, encoding="utf-8")
    args = args_obj(target_dy=0.1, target_ang=0.1, max_control_delta=30.0, min_start_straight=0.1)
    monkeypatch.setattr(geom, "top_y_straights", lambda _segs, _start_name: [{"name": "y"}])
    monkeypatch.setattr(geom, "top_angle_turns", lambda _segs: [])
    monkeypatch.setattr(geom, "probe_metric_delta", lambda *_args: [0.0, 1.0, 0.0])
    monkeypatch.setattr(geom, "run_trackgen_z", lambda *_args: ({"delta_y": 0.0, "delta_ang_deg": 0.0}, ""))
    monkeypatch.setattr(geom, "has_intersection", lambda _track_xml: False)
    history: list[dict] = []

    result, changed = geom.polish_yang_axis(track_xml, pathlib.Path("runtime"), "road", "unit", "start", {"delta_y": 4.0, "delta_ang_deg": 0.0}, args, history, 3)

    assert changed
    assert result == {"delta_y": 0.0, "delta_ang_deg": 0.0}
    assert history[0]["phase"] == "polish-y"
    assert history[0]["delta"] == pytest.approx(-4.0)

    track_xml.write_text(base_text, encoding="utf-8")
    monkeypatch.setattr(geom, "top_y_straights", lambda _segs, _start_name: [])
    monkeypatch.setattr(geom, "top_angle_turns", lambda _segs: [{"name": "turn"}])
    monkeypatch.setattr(geom, "probe_metric_delta", lambda *_args: [1.0, 0.0, 0.0])
    history = []

    result, changed = geom.polish_yang_axis(track_xml, pathlib.Path("runtime"), "road", "unit", "start", {"delta_y": 0.0, "delta_ang_deg": 2.0}, args, history, 4)

    assert changed
    assert result == {"delta_y": 0.0, "delta_ang_deg": 0.0}
    assert history[0]["phase"] == "polish-angle"
    assert history[0]["delta"] == pytest.approx(-2.0)


def test_polish_yang_axis_returns_unchanged_without_valid_improvement(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text('<params><section name="Track Segments"></section></params>', encoding="utf-8")
    args = args_obj(target_dy=0.1, target_ang=0.1, max_control_delta=30.0, min_start_straight=0.1)
    metrics = {"delta_y": 4.0, "delta_ang_deg": 2.0}
    monkeypatch.setattr(geom, "top_y_straights", lambda _segs, _start_name: [{"name": "y"}])
    monkeypatch.setattr(geom, "top_angle_turns", lambda _segs: [{"name": "turn"}])
    monkeypatch.setattr(geom, "probe_metric_delta", lambda *_args: None)

    assert geom.polish_yang_axis(track_xml, pathlib.Path("runtime"), "road", "unit", "start", metrics, args, [], 1) == (metrics, False)


def test_solve_post_pit_terminal_rejects_missing_candidates_or_terminal(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text("base", encoding="utf-8")
    metrics = {"delta_x": 1.0, "delta_y": 1.0, "delta_z": 0.0, "delta_ang_deg": 1.0, "pits": 20}
    args = args_obj(insert_straight_length=0.15, max_control_delta=30.0, min_start_straight=0.1)

    monkeypatch.setattr(geom, "parse_top_level_segments", lambda _text: [])
    monkeypatch.setattr(geom, "top_angle_turns", lambda _segs, limit=8: [])
    monkeypatch.setattr(geom, "top_y_straights", lambda _segs, _start_name, limit=8: [])
    assert geom.solve_post_pit_terminal(track_xml, pathlib.Path("runtime"), "road", "unit", "start", "terminal", metrics, args, []) == (metrics, False, False)

    monkeypatch.setattr(geom, "parse_top_level_segments", lambda _text: [{"name": "turn"}, {"name": "s1"}, {"name": "s2"}])
    monkeypatch.setattr(geom, "top_angle_turns", lambda _segs, limit=8: [{"name": "turn"}])
    monkeypatch.setattr(geom, "top_y_straights", lambda _segs, _start_name, limit=8: [{"name": "s1"}, {"name": "s2"}])
    assert geom.solve_post_pit_terminal(track_xml, pathlib.Path("runtime"), "road", "unit", "start", "terminal", metrics, args, []) == (metrics, False, False)


def test_solve_post_pit_terminal_accepts_full_rank_solution(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(
        """
<params>
  <section name="Track Segments">
    <section name="turn"><attstr name="type" val="lft"/><attnum name="radius" val="80"/><attnum name="arc" val="10" /></section>
    <section name="s1"><attstr name="type" val="str"/><attnum name="lg" val="10" /></section>
    <section name="s2"><attstr name="type" val="str"/><attnum name="lg" val="20" /></section>
    <section name="Closure X Terminal"><attstr name="type" val="str"/><attnum name="lg" val="0.01" /></section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    metrics = {"delta_x": 0.4, "delta_y": 0.3, "delta_z": 0.0, "delta_ang_deg": 0.2, "pits": 20}
    passed_metrics = {"delta_x": 0.0, "delta_y": 0.0, "delta_z": 0.0, "delta_ang_deg": 0.0, "pits": 20}
    args = args_obj(target_dx=0.1, target_dy=0.1, target_dz=0.1, target_ang=0.1, insert_straight_length=0.15, max_control_delta=30.0, min_start_straight=0.1)
    monkeypatch.setattr(geom, "top_angle_turns", lambda _segs, limit=8: [{"name": "turn"}])
    monkeypatch.setattr(geom, "top_y_straights", lambda _segs, _start_name, limit=8: [{"name": "s1"}, {"name": "s2"}, {"name": "Closure X Terminal"}])

    def fake_probe(_track_xml, _runtime_dir, _category, _name, _base_text, _metrics, seg_name, att_name, _step):
        if seg_name == "Closure X Terminal" and att_name == "lg":
            return [0.0, 0.0, 1.0]
        if seg_name == "turn" and att_name == "arc":
            return [1.0, 0.0, 0.0]
        if seg_name == "s1" and att_name == "lg":
            return [0.0, 1.0, 0.0]
        if seg_name == "s2" and att_name == "lg":
            return [0.0, 0.0, 1.0]
        return None

    monkeypatch.setattr(geom, "probe_metric_delta", fake_probe)
    monkeypatch.setattr(geom, "run_trackgen_z", lambda *_args: (passed_metrics, ""))
    monkeypatch.setattr(geom, "has_intersection", lambda _track_xml: False)
    history: list[dict] = []

    result, changed, ok = geom.solve_post_pit_terminal(track_xml, pathlib.Path("runtime"), "road", "unit", "start", "Closure X Terminal", metrics, args, history)

    assert result == passed_metrics
    assert changed
    assert ok
    assert history[0]["phase"] == "solve-post-pit-terminal"
    assert history[0]["turn"] == "turn"
    assert history[0]["straights"] == ["s1", "s2"]
    assert history[0]["attempts"] == 1


def test_solve_post_pit_terminal_keeps_best_non_passing_improvement(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    track_xml.write_text(
        """
<params>
  <section name="Track Segments">
    <section name="turn"><attstr name="type" val="lft"/><attnum name="radius" val="80"/><attnum name="arc" val="10" /></section>
    <section name="s1"><attstr name="type" val="str"/><attnum name="lg" val="10" /></section>
    <section name="s2"><attstr name="type" val="str"/><attnum name="lg" val="20" /></section>
    <section name="Closure X Terminal"><attstr name="type" val="str"/><attnum name="lg" val="0.01" /></section>
  </section>
</params>
""".strip(),
        encoding="utf-8",
    )
    metrics = {"delta_x": 1.0, "delta_y": 1.0, "delta_z": 0.0, "delta_ang_deg": 1.0, "pits": 20}
    improved = {"delta_x": 0.5, "delta_y": 0.5, "delta_z": 0.0, "delta_ang_deg": 0.5, "pits": 20}
    args = args_obj(target_dx=0.1, target_dy=0.1, target_dz=0.1, target_ang=0.1, insert_straight_length=0.01, max_control_delta=30.0, min_start_straight=0.1)
    monkeypatch.setattr(geom, "top_angle_turns", lambda _segs, limit=8: [{"name": "turn"}])
    monkeypatch.setattr(geom, "top_y_straights", lambda _segs, _start_name, limit=8: [{"name": "s1"}, {"name": "s2"}])
    monkeypatch.setattr(
        geom,
        "probe_metric_delta",
        lambda _track_xml, _runtime_dir, _category, _name, _base_text, _metrics, seg_name, _att_name, _step: {
            "Closure X Terminal": [0.0, 0.0, 1.0],
            "turn": [1.0, 0.0, 0.0],
            "s1": [0.0, 1.0, 0.0],
            "s2": [0.0, 0.0, 1.0],
        }[seg_name],
    )
    monkeypatch.setattr(geom, "run_trackgen_z", lambda *_args: (improved, ""))
    monkeypatch.setattr(geom, "has_intersection", lambda _track_xml: False)
    history: list[dict] = []

    result, changed, ok = geom.solve_post_pit_terminal(track_xml, pathlib.Path("runtime"), "road", "unit", "start", "Closure X Terminal", metrics, args, history)

    assert result == improved
    assert changed
    assert not ok
    assert history[0]["phase"] == "solve-post-pit-terminal"


def test_main_writes_success_report_without_solver_cycles(monkeypatch, tmp_path, capsys) -> None:
    track_xml = tmp_path / "track.xml"
    report_path = tmp_path / "report.json"
    track_xml.write_text("base", encoding="utf-8")
    args = args_obj(track_xml=str(track_xml), runtime_dir=str(tmp_path / "runtime"), report=str(report_path), profile="mainline")
    passed_metrics = {"delta_x": 0.0, "delta_y": 0.0, "delta_z": 0.0, "delta_ang_deg": 0.0}
    monkeypatch.setattr(geom, "parse_args", lambda: args)
    monkeypatch.setattr(geom, "prepare_terminal_x_lever", lambda _track_xml, _args, history: (history.append({"action": "prepared"}) or ("start", "terminal")))
    monkeypatch.setattr(geom, "run_trackgen_z", lambda *_args: (passed_metrics, ""))
    monkeypatch.setattr(geom, "runtime_stats", lambda: {"trackgen_calls": 1})

    assert geom.main() == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["final_metrics"] == passed_metrics
    assert report["history"][0] == {"action": "prepared"}
    assert "Closure targets satisfied" in capsys.readouterr().out


def test_main_writes_failure_report_when_setup_raises(monkeypatch, tmp_path) -> None:
    track_xml = tmp_path / "track.xml"
    report_path = tmp_path / "report.json"
    track_xml.write_text("base", encoding="utf-8")
    args = args_obj(track_xml=str(track_xml), runtime_dir=str(tmp_path / "runtime"), report=str(report_path), profile="mainline")
    monkeypatch.setattr(geom, "parse_args", lambda: args)
    monkeypatch.setattr(geom, "prepare_terminal_x_lever", lambda *_args: (_ for _ in ()).throw(RuntimeError("setup failed")))
    monkeypatch.setattr(geom, "runtime_stats", lambda: {"trackgen_calls": 0})

    with pytest.raises(RuntimeError, match="setup failed"):
        geom.main()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["error"] == "setup failed"
    assert report["stats"] == {"trackgen_calls": 0}


def test_align_closed_loop_handles_cyclic_start_offset() -> None:
    source = [
        {"x": 0.0, "y": 0.0},
        {"x": 10.0, "y": 0.0},
        {"x": 10.0, "y": 10.0},
        {"x": 0.0, "y": 10.0},
    ]
    model = [
        {"x": 10.0, "y": 10.0, "seg": "c"},
        {"x": 0.0, "y": 10.0, "seg": "d"},
        {"x": 0.0, "y": 0.0, "seg": "a"},
        {"x": 10.0, "y": 0.0, "seg": "b"},
    ]

    fitted, alignment = geom.align_closed_loop(source, model)

    assert alignment["paired_rmse_m"] < 1e-9
    assert alignment["cyclic_shift_samples"] == 2
    assert [p["seg"] for p in fitted] == ["a", "b", "c", "d"]


def test_align_closed_loop_rejects_mismatched_sample_counts() -> None:
    with pytest.raises(RuntimeError, match="same sample count"):
        geom.align_closed_loop([{"x": 0.0, "y": 0.0}], [])
