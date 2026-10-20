# /***************************************************************************
#
#     file                 : test_trackgen.py
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

import subprocess

from torcs_track_tools.core.trackgen import TrackgenRunner, TrackgenStats, installed_track_xml, parse_trackgen_output

TRACKGEN_OUTPUT = """
Delta X = -0.000244
Delta Y = 0.000488
Delta Z = 0
Delta Ang = -0.000001 (-0.000055)
length = 5891.2
pits = 0
"""


def test_parse_trackgen_output_reads_closure_metrics() -> None:
    metrics = parse_trackgen_output(TRACKGEN_OUTPUT)

    assert metrics["delta_x"] == -0.000244
    assert metrics["delta_y"] == 0.000488
    assert metrics["delta_ang_deg"] == -0.000055
    assert metrics["length"] == 5891.2
    assert metrics["pits"] == 0


def test_trackgen_runner_removes_temporary_live_xml_for_new_track(monkeypatch, tmp_path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "trackgen.exe").write_text("", encoding="utf-8")
    candidate_xml = tmp_path / "candidate.xml"
    candidate_xml.write_text("<track>candidate</track>", encoding="utf-8")
    live_xml = installed_track_xml(runtime_dir, "road", "unit-track")

    def fake_run(cmd, cwd, stdout, stderr, text, check, timeout):  # noqa: ARG001
        assert timeout == 3.0
        assert live_xml.read_text(encoding="utf-8") == "<track>candidate</track>"
        return subprocess.CompletedProcess(cmd, 0, stdout=TRACKGEN_OUTPUT)

    monkeypatch.setattr("torcs_track_tools.core.trackgen.subprocess.run", fake_run)
    stats = TrackgenStats()

    metrics, _ = TrackgenRunner(runtime_dir, stats=stats, allow_missing_live_xml=True, timeout_s=3.0).run_z("road", "unit-track", candidate_xml)

    assert metrics["length"] == 5891.2
    assert stats.calls == 1
    assert not live_xml.exists()
