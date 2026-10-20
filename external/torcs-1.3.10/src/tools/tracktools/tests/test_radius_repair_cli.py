# /***************************************************************************
#     file                 : test_radius_repair_cli.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

import hashlib
import json
import zipfile

import pytest
from test_radius_repair import models, track

from torcs_track_tools.cli import audit_track_radii, repair_track_radii
from torcs_track_tools.core.radius_repair import apply_parameters, selected_sections


@pytest.fixture
def repair_case(tmp_path, monkeypatch):
    source_dir = tmp_path / "track"
    source_dir.mkdir()
    source = source_dir / "track.xml"
    source.write_bytes(track().encode())
    (source_dir / "hand-edited.txt").write_text("keep me")
    runtime = tmp_path / "runtime"
    (runtime / "modules/track").mkdir(parents=True)
    (runtime / "modules/track/track.dll").write_bytes(b"stub DLL hash input")
    before, after = models()
    candidate = apply_parameters(track(), selected_sections(track(), ["large"]), {"large": [10, .0025, 0]})
    state = {"closed": False, "after": after}

    class Probe:
        def __init__(self, *args):
            state["probe_args"] = args

        def load(self, text):
            return before if text == track() else state["after"]

        def close(self):
            state["closed"] = True

    monkeypatch.setattr(repair_track_radii, "TrackLoaderProbe", Probe)
    monkeypatch.setattr(repair_track_radii, "fit", lambda *args: (candidate, {"large": [10, .0025, 0]}, before))
    work = tmp_path / "output"
    args = ["--input", str(source), "--runtime-dir", str(runtime), "--segment", "large", "--work-dir", str(work)]
    return source, work, args, state, candidate


def test_fit_cli_archives_assets_and_emits_candidate_without_changing_source(repair_case):
    source, work, args, state, candidate = repair_case
    assert repair_track_radii.main(args) == 0
    assert source.read_text() == track()
    assert (work / "before.xml").read_bytes() == source.read_bytes()
    assert (work / "candidate.xml").read_text() == candidate
    with zipfile.ZipFile(work / "before.zip") as archive:
        assert archive.read("hand-edited.txt") == b"keep me"
        assert archive.read("track.xml") == source.read_bytes()
    report = json.loads((work / "report.json").read_text())
    assert report["accepted"] and len(report["source_sha256"]) == 64
    assert report["candidate_sha256"] == hashlib.sha256((work/"candidate.xml").read_bytes()).hexdigest()
    assert state["closed"]


def test_validate_cli_uses_requested_resources_and_does_not_fit(repair_case, monkeypatch, tmp_path):
    _, work, args, state, candidate = repair_case
    path = tmp_path / "candidate.xml"
    path.write_bytes(candidate.encode())
    monkeypatch.setattr(repair_track_radii, "fit", lambda *args: pytest.fail("unexpected fitting"))
    args += ["--validate-candidate", str(path), "--resource-dir", str(tmp_path), "--symbols-dir", str(tmp_path)]
    assert repair_track_radii.main(args) == 0
    assert state["probe_args"][1] == tmp_path
    assert state["probe_args"][-1] == tmp_path
    assert json.loads((work / "report.json").read_text())["parameters"] is None


def test_rejected_candidate_is_not_published_as_accepted(repair_case):
    _, work, args, state, _ = repair_case
    state["after"]["pit_count"] = 19
    assert repair_track_radii.main(args) == 1
    assert (work / "candidate-rejected.xml").exists()
    assert not (work / "candidate.xml").exists()
    assert "pit_count changed" in json.loads((work / "report.json").read_text())["failures"]
    assert state["closed"]


def test_existing_work_directory_is_preserved(repair_case):
    _, work, args, _, _ = repair_case
    work.mkdir()
    marker = work / "before.xml"
    marker.write_text("earlier backup")
    with pytest.raises(SystemExit, match="1"):
        repair_track_radii.main(args)
    assert marker.read_text() == "earlier backup"


def test_source_change_during_run_rejects_candidate(repair_case, monkeypatch):
    source, work, args, _, candidate = repair_case

    def changed(*_args):
        source.write_text(track() + "\n<!-- concurrent hand edit -->")
        return candidate, {}, models()[0]

    monkeypatch.setattr(repair_track_radii, "fit", changed)
    assert repair_track_radii.main(args) == 1
    assert "Source changed during the run" in json.loads((work / "report.json").read_text())["failures"]
    assert "concurrent hand edit" in source.read_text()


def test_probe_is_closed_after_fitting_error(repair_case, monkeypatch):
    _, _, args, state, _ = repair_case

    def fail(*_args):
        raise RuntimeError("fit failed")

    monkeypatch.setattr(repair_track_radii, "fit", fail)
    with pytest.raises(SystemExit, match="1"):
        repair_track_radii.main(args)
    assert state["closed"]


def test_audit_cli_reports_results_and_partial_failure(tmp_path, capsys):
    for name, content in [("valid", track()), ("broken", "<params")]:
        folder = tmp_path / "tracks/road" / name
        folder.mkdir(parents=True)
        (folder / (name + ".xml")).write_text(content)
    report = tmp_path / "report.json"
    assert audit_track_radii.main(["--tracks-root", str(tmp_path / "tracks"), "--report", str(report)]) == 1
    result = json.loads(report.read_text())
    assert result["affected_tracks"] == 1 and len(result["errors"]) == 1
    assert "ERROR" in capsys.readouterr().out
    (tmp_path / "tracks/road/broken/broken.xml").unlink()
    assert audit_track_radii.main(["--tracks-root", str(tmp_path / "tracks")]) == 0


def test_audit_cli_handles_invalid_root(tmp_path):
    with pytest.raises(SystemExit, match="2"):
        audit_track_radii.main(["--tracks-root", str(tmp_path)])


def test_all_over_limit_uses_audit_selection(repair_case):
    _, work, args, _, _ = repair_case
    index = args.index("--segment")
    del args[index:index+2]
    assert repair_track_radii.main(args+["--all-over-limit"]) == 0
    report = json.loads((work/"report.json").read_text())
    assert list(report["repairs"]) == ["large"]


def test_checkpoint_and_matching_resume(repair_case, monkeypatch, tmp_path):
    _, work, args, _, candidate = repair_case

    def fit_with_checkpoint(_text, sections, _probe, _seed, _resume, progress, _polish):
        parameters = {"large": [10, .0025, 0]}
        progress(parameters, sections)
        return candidate, parameters, models()[0]

    monkeypatch.setattr(repair_track_radii, "fit", fit_with_checkpoint)
    assert repair_track_radii.main(args) == 0
    assert (work/"fit-progress.json").is_file()
    assert not (work/"fit-progress.tmp").exists()
    previous = json.loads((work/"report.json").read_text())
    resumed = repair_track_radii.load_resume(work/"fit-progress.json", previous, ["large"])
    assert resumed["parameters"]["large"] == [10., .0025, 0.]
    next_args = list(args)
    next_args[next_args.index("--work-dir")+1] = str(tmp_path/"resumed")
    next_args += ["--resume-report", str(work/"fit-progress.json")]
    assert repair_track_radii.main(next_args) == 0


@pytest.mark.parametrize("field", ["source_sha256", "track_dll_sha256", "seed", "method", "curve_radius_m"])
def test_resume_rejects_changed_identity(repair_case, field):
    _, work, args, _, _ = repair_case
    assert repair_track_radii.main(args) == 0
    report = json.loads((work/"report.json").read_text())
    changed = dict(report, **{field: "different"})
    with pytest.raises(ValueError, match=field):
        repair_track_radii.load_resume(work/"report.json", changed, ["large"])


@pytest.mark.parametrize("values", [[1, 2], [1, None, 3], [1, "bad", 3], [1, float("nan"), 3]])
def test_resume_rejects_invalid_parameter_vector(values):
    report = {"parameters": {"large": values}, "methods": {"large": "biarc"}}
    with pytest.raises(ValueError, match="invalid parameters"):
        repair_track_radii.validate_resume_parameters(report, ["large"])


def test_audit_preflight_classifies_supported_and_blocked_tracks(tmp_path):
    supported = track()
    blocked = track().replace('<attstr name="profil"', '<section name="Right Barrier"/><attstr name="profil"')
    for name, text in [("supported", supported), ("blocked", blocked)]:
        directory = tmp_path/"road"/name
        directory.mkdir(parents=True)
        (directory/(name+".xml")).write_bytes(text.encode())
    report_path = tmp_path/"preflight.json"
    assert audit_track_radii.main(["--tracks-root", str(tmp_path), "--preflight", "--report", str(report_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report["preflight"]["eligible_tracks"] == 1
    assert report["preflight"]["blocked_tracks"] == 1
    blocked_result = next(t for t in report["tracks"] if "blocked.xml" in t["path"])
    assert blocked_result["repair_preflight"]["blocked_segments"][0]["segment"] == "large"
    assert (tmp_path/"road/blocked/blocked.xml").read_bytes() == blocked.encode()
