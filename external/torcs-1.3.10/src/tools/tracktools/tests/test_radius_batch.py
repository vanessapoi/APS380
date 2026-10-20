# /***************************************************************************
#     file                 : test_radius_batch.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

import copy
import json
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest
from test_radius_repair import track

from torcs_track_tools.cli import batch_repair_track_radii as cli
from torcs_track_tools.core import radius_batch as batch
from torcs_track_tools.core.radius_repair import apply_parameters, selected_sections

CLOSURE = "length = 100\npits = 20\nDelta X = 0.000244\nDelta Y = 0.000488\nDelta Z = 0\nDelta Ang = -0.000001 (-0.000082)\n"
MODEL = '''AC3Db
MATERIAL "test" rgb 1 1 1 amb 1 1 1 emis 0 0 0 spec 0 0 0 shi 0 trans 0
OBJECT poly
numvert 3
0 0 0
1 0 0
0 1 0
numsurf 1
SURF 0x30
mat 0
refs 3
0 0 0
1 1 0
2 0 1
kids 0
'''


@pytest.mark.parametrize("radius,expected,resume", [(None, 2000., True), (2000., 2000., True), (3000., 3000., False)])
def test_resume_keeps_fit_radius_or_starts_fresh_when_changed(tmp_path, radius, expected, resume):
    batch.write_json(tmp_path/"fit-progress.json", {"curve_radius_m": 2000.})
    runner = batch.Batch.__new__(batch.Batch)
    runner.curve_radius = radius
    args = runner.fit_resume_arguments(tmp_path)
    assert args[:2] == ["--curve-radius", expected]
    assert ("--resume-report" in args) == resume


class FakeTools:
    def __init__(self, runtime):
        self.runtime = runtime
        self.calls = []
        self.fail = set()
        self.active_merges = 0
        self.max_merges = 0
        self.lock = threading.Lock()

    def __call__(self, command, cwd, log, timeout):
        assert cwd == self.runtime and timeout > 0
        phase, key = log.stem, log.parent.name
        self.calls.append((key, phase))
        if (key, phase) in self.fail:
            raise RuntimeError("simulated generation failure")
        log.write_text(CLOSURE if phase.endswith("closure") else "ok\n")
        if phase.startswith("fit-"):
            self.fit(command)
        elif phase in ("side-clearance", "side-overlap"):
            report = {"anomaly_count": 0, "anomalies": [], "applied_runs": [], "overlap_count": 0,
                      "proposal_count": 0, "final_overlap_count": 0}
            batch.write_json(Path(command[command.index("--report")+1]), report)
        elif phase in ("geometry", "raceline"):
            directory = Path(command[command.index("-o")+1])
            name = command[command.index("-n")+1]
            for suffix in (".ac", "-trk.ac", "-msh.ac", "-trk-raceline.ac"):
                (directory/(name+suffix)).write_text(MODEL)
        elif phase == "merge":
            self.merge(command)
        elif phase in ("labels", "map"):
            Path(command[command.index("--output")+1]).write_bytes(b"generated preview")
            if "--svg-output" in command:
                Path(command[command.index("--svg-output")+1]).write_text("<svg/>")

    def fit(self, command):
        source = Path(command[command.index("--input")+1])
        output = Path(command[command.index("--work-dir")+1])
        output.mkdir()
        original = source.read_bytes()
        (output/"before.xml").write_bytes(original)
        with zipfile.ZipFile(output/"before.zip", "w") as archive:
            for path in source.parent.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(source.parent))
        text = original.decode()
        candidate = apply_parameters(text, selected_sections(text, ["large"]), {"large": [10, .0025, 0]})
        (output/"candidate.xml").write_bytes(candidate.encode())
        batch.write_json(output/"report.json", {"accepted": True, "pit_count": 20,
                         "candidate_sha256": batch.digest(output/"candidate.xml"),
                         "curve_radius_m": float(command[command.index("--curve-radius")+1]),
                         "source_sha256": batch.digest(source),
                         "track_dll_sha256": batch.digest(self.runtime/"modules/track/track.dll")})

    def merge(self, command):
        with self.lock:
            self.active_merges += 1
            self.max_merges = max(self.max_merges, self.active_merges)
        time.sleep(.03)
        Path(command[command.index("-g")+1]).write_text(MODEL)
        with self.lock:
            self.active_merges -= 1


@pytest.fixture
def environment(tmp_path, monkeypatch):
    runtime = tmp_path/"runtime"
    (runtime/"modules/track").mkdir(parents=True)
    (runtime/"modules/track/track.dll").write_bytes(b"test DLL")
    for name in ("a", "b"):
        directory = runtime/"tracks/road"/name
        directory.mkdir(parents=True)
        xml = track().replace('<section name="Main Track">',
                              f'<section name="Graphic"><attstr name="3d description" val="{name}.acc"/></section><section name="Main Track">')
        (directory/(name+".xml")).write_bytes(xml.encode())
        (directory/(name+".acc")).write_bytes(b"old model")
        (directory/"readme.txt").write_bytes(b"hand-edited readme")
    tools = FakeTools(runtime)
    monkeypatch.setattr(batch, "execute", tools)
    return runtime, tmp_path/"batch", tools


def test_batch_continues_after_failure_and_resumes_without_redoing_completed_track(environment):
    runtime, work, tools = environment
    source_b = runtime/"tracks/road/b/b.xml"
    original_b = source_b.read_bytes()
    tools.fail.add(("road__b", "geometry"))
    runner = batch.Batch(runtime, work, ["road/a", "road/b"], deploy=True)
    assert runner.run() == 1
    assert runner.data["tracks"]["road/a"]["status"] == "deployed"
    assert runner.data["tracks"]["road/b"]["status"] == "failed"
    assert source_b.read_bytes() == original_b
    calls_a = [c for c in tools.calls if c[0] == "road__a"]
    tools.fail.clear()
    resumed = batch.Batch(runtime, work, None, resume=True, deploy=True)
    assert resumed.run() == 0
    assert [c for c in tools.calls if c[0] == "road__a"] == calls_a
    assert not batch.audit_track(source_b)["segments"]
    assert (source_b.parent/"readme.txt").read_bytes() == b"hand-edited readme"


def test_parallel_generation_serializes_merges(environment):
    runtime, work, tools = environment
    runner = batch.Batch(runtime, work, ["road/a", "road/b"], deploy=False, workers=2)
    assert runner.run() == 0
    assert tools.max_merges == 1
    assert batch.audit_track(runtime/"tracks/road/a/a.xml")["segments"]
    before = list(tools.calls)
    assert batch.Batch(runtime, work, None, resume=True, deploy=True).run() == 0
    assert [call for call in tools.calls if call[1] != "deployed-closure"] == before


def test_failed_live_closure_rolls_back_deployment(environment):
    runtime, work, tools = environment
    source = runtime/"tracks/road/a/a.xml"
    original = source.read_bytes()
    tools.fail.add(("road__a", "deployed-closure"))
    assert batch.Batch(runtime, work, ["road/a"], deploy=True).run() == 1
    assert source.read_bytes() == original
    assert (source.parent/"a.acc").read_bytes() == b"old model"


def test_deployment_failure_restores_every_original_output(environment, monkeypatch):
    runtime, work, _ = environment
    directory = runtime/"tracks/road/a"
    originals = {p.name: p.read_bytes() for p in directory.iterdir()}
    copy = batch.shutil.copy2

    def fail_xml(source, target):
        if Path(source).name == "candidate.xml":
            raise OSError("simulated disk failure")
        return copy(source, target)

    monkeypatch.setattr(batch.shutil, "copy2", fail_xml)
    assert batch.Batch(runtime, work, ["road/a"], deploy=True).run() == 1
    for name, data in originals.items():
        assert (directory/name).read_bytes() == data
    assert not (directory/"a-trk.ac").exists()


def test_changed_input_is_not_overwritten_on_resume(environment):
    runtime, work, _ = environment
    assert batch.Batch(runtime, work, ["road/a"]).run() == 0
    source = runtime/"tracks/road/a/a.xml"
    changed = source.read_bytes()+b"\n<!-- user edit -->"
    source.write_bytes(changed)
    assert batch.Batch(runtime, work, None, resume=True, deploy=True).run() == 1
    assert source.read_bytes() == changed


def test_new_live_output_added_after_snapshot_is_not_overwritten(environment):
    runtime, work, _ = environment
    assert batch.Batch(runtime, work, ["road/a"]).run() == 0
    added = runtime/"tracks/road/a/a.png"
    added.write_bytes(b"user-created preview after staging")
    runner = batch.Batch(runtime, work, None, resume=True, deploy=True)
    assert runner.run() == 1
    assert "New live output" in runner.data["tracks"]["road/a"]["error"]
    assert added.read_bytes() == b"user-created preview after staging"
    assert batch.audit_track(runtime/"tracks/road/a/a.xml")["segments"]


def test_changed_staged_candidate_is_rejected(environment):
    runtime, work, _ = environment
    runner = batch.Batch(runtime, work, ["road/a"])
    assert runner.run() == 0
    candidate = Path(runner.data["tracks"]["road/a"]["fit_dir"])/"candidate.xml"
    candidate.write_bytes(candidate.read_bytes()+b"\n<!-- edit -->")
    assert batch.Batch(runtime, work, None, resume=True, deploy=True).run() == 1
    assert batch.audit_track(runtime/"tracks/road/a/a.xml")["segments"]


@pytest.mark.parametrize("changed", [False, True])
def test_fit_report_covers_interruption_before_manifest_candidate_hash(environment, changed):
    runtime, work, tools = environment
    tools.fail.add(("road__a", "geometry"))
    runner = batch.Batch(runtime, work, ["road/a"])
    assert runner.run() == 1
    record = runner.data["tracks"]["road/a"]
    del record["candidate_sha256"]  # interrupted after writing the fit report
    runner.save()
    if changed:
        candidate = Path(record["fit_dir"])/"candidate.xml"
        candidate.write_bytes(candidate.read_bytes()+b"\n<!-- unvalidated edit -->")
    tools.fail.clear()
    assert batch.Batch(runtime, work, None, resume=True, deploy=True).run() == int(changed)


def test_staged_fit_cannot_ignore_requested_radius_change(environment):
    runtime, work, _ = environment
    assert batch.Batch(runtime, work, ["road/a"]).run() == 0
    runner = batch.Batch(runtime, work, None, resume=True, deploy=True, curve_radius=2000.)
    assert runner.run() == 1
    assert "different curve radius" in runner.data["tracks"]["road/a"]["error"]
    assert batch.audit_track(runtime/"tracks/road/a/a.xml")["segments"]


def test_diagnose_handles_failure_before_fitting(environment):
    runtime, work, _ = environment
    source = runtime/"tracks/road/a/a.xml"
    source.write_text(source.read_text().replace('val="a.acc"', 'val="custom.acc"'))
    runner = batch.Batch(runtime, work, ["road/a"])
    assert runner.run() == 1
    assert runner.diagnose() == 0
    assert "baseline_closure" in runner.data["tracks"]["road/a"]


def test_completed_deployment_journal_recovers_without_overwriting(environment):
    runtime, work, tools = environment
    runner = batch.Batch(runtime, work, ["road/a"])
    assert runner.run() == 0
    record = runner.data["tracks"]["road/a"]
    directory = work/"road__a"
    source = runtime/"tracks/road/a/a.xml"
    runner.update("road/a", status="deploying")
    batch.deploy_track(source, Path(record["fit_dir"]), directory/"model", record["generated_files"], directory, runner.data["id"])
    before = list(tools.calls)
    assert batch.Batch(runtime, work, None, resume=True, deploy=True).run() == 0
    assert tools.calls == before
    assert not (directory/"deployment.json").exists()


def test_missing_side_metrics_fail_instead_of_defaulting_to_success(tmp_path):
    batch.write_json(tmp_path/"side-clearance.json", {})
    batch.write_json(tmp_path/"side-overlap.json", {})
    with pytest.raises(KeyError):
        batch.check_side_reports(tmp_path)


def test_failed_json_report_replace_preserves_last_checkpoint(tmp_path, monkeypatch):
    path = tmp_path/"report.json"
    batch.write_json(path, {"completed": 1})

    def fail_replace(*_):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failure"):
        batch.write_json(path, {"completed": 2})
    assert batch.read_json(path) == {"completed": 1}
    assert not path.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize("heading,ok", [("-0.000082", True), ("-0.000109", False)])
def test_native_printed_heading_gate(tmp_path, heading, ok):
    log = tmp_path/"closure.log"
    log.write_text(CLOSURE.replace("-0.000082", heading))
    if ok:
        assert batch.check_closure(log)["pits"] == 20
    else:
        with pytest.raises(ValueError, match="closure"):
            batch.check_closure(log)


def test_invalid_track_key_is_rejected(environment):
    runtime, _, _ = environment
    with pytest.raises(ValueError):
        batch.track_path(runtime, "../a")


def test_manifest_summary_is_machine_readable(environment):
    runtime, work, _ = environment
    assert batch.Batch(runtime, work, ["road/a"]).run() == 0
    data = json.loads((work/"manifest.json").read_text())
    assert data["summary"] == {"staged": 1}
    assert "road/a | staged" in (work/"summary.md").read_text()


@pytest.mark.parametrize("bad", [MODEL.replace("2 0 1", "3 0 1"), MODEL.replace("1 0 0\n0 1 0", "nan 0 0\n0 1 0"), "AC3Db\n"])
def test_invalid_generated_geometry_is_rejected(tmp_path, bad):
    path = tmp_path/"model.acc"
    path.write_text(bad)
    with pytest.raises(ValueError):
        batch.validate_model(path)


@pytest.mark.parametrize("selection", [["--track", "road/a"], ["--all"], ["--resume"]])
def test_cli_dispatches_requested_batch_mode(tmp_path, monkeypatch, selection):
    received = []

    class Runner:
        def __init__(self, *args):
            received.extend(args)

        def run(self):
            return 0

    monkeypatch.setattr(cli, "Batch", Runner)
    monkeypatch.setattr(cli, "eligible_keys", lambda _runtime: ["road/a", "road/b"])
    assert cli.main(["--runtime-dir", str(tmp_path), "--work-dir", str(tmp_path/"work"), *selection]) == 0
    assert received[3] == (selection == ["--resume"])
    assert received[5] == 2


def test_timeout_terminates_the_owned_process(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        batch.execute([sys.executable, "-c", "import time; time.sleep(20)"], tmp_path, tmp_path/"timeout.log", .1)


def test_resume_can_retry_a_subset_without_touching_other_jobs(environment):
    runtime, work, tools = environment
    tools.fail.update({("road__a", "geometry"), ("road__b", "geometry")})
    assert batch.Batch(runtime, work, ["road/a", "road/b"]).run() == 1
    calls_b = [c for c in tools.calls if c[0] == "road__b"]
    tools.fail.clear()
    runner = batch.Batch(runtime, work, ["road/a"], resume=True, deploy=True)
    assert runner.run() == 1  # The consolidated batch still reports b's failure.
    assert runner.data["tracks"]["road/a"]["status"] == "deployed"
    assert [c for c in tools.calls if c[0] == "road__b"] == calls_b


def test_diagnose_measures_baseline_without_refitting(environment):
    runtime, work, tools = environment
    tools.fail.add(("road__a", "geometry"))
    assert batch.Batch(runtime, work, ["road/a"]).run() == 1
    calls = list(tools.calls)
    runner = batch.Batch(runtime, work, None, resume=True)
    assert runner.diagnose() == 0
    assert tools.calls[len(calls):] == [("road__a", "baseline-closure")]
    assert "road/a" in (work/"diagnostics.md").read_text()
    assert runner.data["tracks"]["road/a"]["status"] == "failed"


def existing_clearance():
    return {"index": 1, "segment": "tail", "side": "right", "type": "rgt", "radius": 15.358,
            "start_radius": 15.358, "end_radius": 15.358, "arc_deg": 74.7,
            "old_side_width": 8.169, "old_side_start_width": 7., "old_side_end_width": 8.169,
            "border_width": 1., "clearance_margin": .5, "deficit": .311,
            "unresolved_deficit": 0., "protected": True}


def test_explicit_clearance_acceptance_ignores_only_shifted_list_index(tmp_path):
    source, candidate = tmp_path/"source.xml", tmp_path/"candidate.xml"
    source.write_bytes(track().encode())
    candidate.write_bytes(track().encode())
    original = existing_clearance()
    current = dict(original, index=154)
    accepted = batch.accept_unchanged_clearance(source, candidate, {"anomalies": [original]}, {"anomalies": [current]}, {"tail"})
    assert accepted[0]["physical_clearance_m"] == pytest.approx(.189, abs=1e-12)
    assert accepted[0]["existing_deficit_m"] == .311


@pytest.mark.parametrize("change", ["unapproved", "new", "worse", "edited", "nonpositive"])
def test_clearance_acceptance_rejects_changes_and_unapproved_conditions(tmp_path, change):
    source, candidate = tmp_path/"source.xml", tmp_path/"candidate.xml"
    source.write_bytes(track().encode())
    candidate.write_bytes(track().encode())
    baseline = {"anomalies": [existing_clearance()]}
    current = copy.deepcopy(baseline)
    names = {"tail"}
    if change == "unapproved":
        names = set()
    elif change == "new":
        baseline["anomalies"] = []
    elif change == "worse":
        current["anomalies"][0]["deficit"] += .01
    elif change == "edited":
        candidate.write_bytes(track().replace('name="lg" val="50"', 'name="lg" val="51"').encode())
    else:
        baseline["anomalies"][0]["deficit"] = .5
        current["anomalies"][0]["deficit"] = .5
    with pytest.raises(ValueError):
        batch.accept_unchanged_clearance(source, candidate, baseline, current, names)


def test_clearance_acceptance_does_not_waive_overlaps(tmp_path):
    item = existing_clearance()
    batch.write_json(tmp_path/"side-clearance.json", {"anomaly_count": 1, "anomalies": [item], "applied_runs": []})
    batch.write_json(tmp_path/"side-overlap.json", {"overlap_count": 1, "proposal_count": 1, "final_overlap_count": 1})
    with pytest.raises(ValueError, match="overlaps"):
        batch.check_side_reports(tmp_path, [item])


def test_batch_records_explicit_unchanged_clearance_acceptance(environment, monkeypatch):
    runtime, work, tools = environment

    def run(command, cwd, log, timeout):
        if log.stem in ("side-clearance", "baseline-side-clearance"):
            log.write_text("existing clearance\n")
            batch.write_json(Path(command[command.index("--report")+1]),
                             {"anomaly_count": 1, "anomalies": [existing_clearance()], "applied_runs": []})
        else:
            tools(command, cwd, log, timeout)

    monkeypatch.setattr(batch, "execute", run)
    runner = batch.Batch(runtime, work, ["road/a"], deploy=True, clearance_acceptances={"road/a": {"tail"}})
    assert runner.run() == 0
    record = runner.data["tracks"]["road/a"]
    assert record["status"] == "deployed"
    assert record["accepted_baseline_clearance"][0]["segment"] == "tail"
    report_dir = runtime/"tracks/road/a/source"/("radius-batch-"+runner.data["id"])
    assert (report_dir/"accepted-clearance.json").is_file()
    assert "Accepted unchanged baseline clearance: tail" in (work/"summary.md").read_text()
