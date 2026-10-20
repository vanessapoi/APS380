# file: test_runner.py; created: September 2026
# Copyright (C) 2026 by Bernhard Wymann <berniw@bluewin.ch>
# This program is free software under the GNU General Public License,
# version 2 or (at your option) any later version.
"""Unit tests of race-runner infrastructure; these do not launch the simulator."""
import json
import csv
import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

import brain_state
import check_lifecycle
from brain_state import BrainState, fingerprint, recover_brain
from behavior import check_behavior
from run_olethros_regression import Track, build_raceman_xml, parse_run
import run_olethros_regression as runner


class BrainIsolation(unittest.TestCase):
    def test_incomplete_journal_is_not_published_or_allowed_to_move_brain(self):
        for stage in ("json.dump", "os.fsync", "os.rename"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                brain = Path(temp)/"track.brain"
                brain.write_bytes(b"original")
                state = BrainState(brain, "clean")
                with patch("brain_state."+stage, side_effect=OSError("injected journal failure")):
                    with self.assertRaises(OSError):
                        with state: pass
                self.assertEqual(brain.read_bytes(), b"original")
                self.assertFalse(state.journal.exists())
                self.assertFalse(state.backup.exists())
                self.assertEqual([p.name for p in Path(temp).iterdir()], [brain.name])

    def test_published_journal_is_complete_before_brain_move(self):
        with tempfile.TemporaryDirectory() as temp:
            brain = Path(temp)/"track.brain"
            brain.write_bytes(b"original")
            state = BrainState(brain, "clean")
            replace = brain_state.os.replace
            def checked_replace(source, destination):
                if Path(source) == brain:
                    report = json.loads(state.journal.read_text(encoding="utf-8"))
                    self.assertEqual(report["original_sha256"], fingerprint(brain))
                    self.assertEqual(report["name"], brain.name)
                return replace(source, destination)
            with patch.object(brain_state.os, "replace", side_effect=checked_replace):
                with state: pass
            self.assertEqual(brain.read_bytes(), b"original")

    def test_malformed_journal_reports_error_without_changing_files(self):
        for contents in (b"", b"{", b"[]", b"{}", b"\xff",
                         b'{"name":"track.brain","original_sha256":42}'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as temp:
                brain = Path(temp)/"track.brain"
                state = BrainState(brain, "clean")
                brain.write_bytes(b"original")
                state.backup.write_bytes(b"backup")
                state.journal.write_bytes(contents)
                with self.assertRaisesRegex(RuntimeError, "recovery journal"):
                    recover_brain(state.journal)
                self.assertEqual(brain.read_bytes(), b"original")
                self.assertEqual(state.backup.read_bytes(), b"backup")
                self.assertEqual(state.journal.read_bytes(), contents)

    def test_multiple_brains_restore_after_run_or_second_entry_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp)
            first = local/"drivers"/"olethros"/"6"/"track.brain"
            second = local/"drivers"/"olethros"/"7"/"track.brain"
            first.parent.mkdir(parents=True)
            first.write_bytes(b"first brain")
            with self.assertRaises(RuntimeError):
                with runner.isolate_track_brains(local, "track", (6,7), "persisted"):
                    self.fail("missing second brain must fail entry")
            self.assertEqual(first.read_bytes(), b"first brain")
            second.write_bytes(b"second brain")
            with self.assertRaises(KeyboardInterrupt):
                with runner.isolate_track_brains(local, "track", (6,7), "clean"):
                    first.write_bytes(b"new first")
                    second.write_bytes(b"new second")
                    raise KeyboardInterrupt()
            self.assertEqual(first.read_bytes(), b"first brain")
            self.assertEqual(second.read_bytes(), b"second brain")
            self.assertFalse(list(local.rglob("*.regression.json")))

    def test_clean_and_persisted_restore_content_and_metadata(self):
        for mode in ("clean", "persisted"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                brain = Path(temp)/"track.brain"
                brain.write_bytes(b"original brain")
                stat = brain.stat()
                with BrainState(brain, mode):
                    self.assertEqual(brain.exists(), mode == "persisted")
                    if brain.exists(): self.assertEqual(brain.read_bytes(), b"original brain")
                    brain.write_bytes(b"changes during a session")
                self.assertEqual(brain.read_bytes(), b"original brain")
                self.assertEqual(brain.stat().st_mtime_ns, stat.st_mtime_ns)
                self.assertEqual([p.name for p in Path(temp).iterdir()], ["track.brain"])

    def test_exception_timeout_and_interrupt_restore_original(self):
        for error in (RuntimeError("error"), subprocess.TimeoutExpired("wtorcs", 1), KeyboardInterrupt()):
            with self.subTest(error=type(error)), tempfile.TemporaryDirectory() as temp:
                brain = Path(temp)/"track.brain"; brain.write_bytes(b"original")
                with self.assertRaises(type(error)):
                    with BrainState(brain, "clean"):
                        raise error
                self.assertEqual(brain.read_bytes(), b"original")

    def test_missing_brain_clean_restores_absence(self):
        with tempfile.TemporaryDirectory() as temp:
            brain = Path(temp)/"new.brain"
            with BrainState(brain, "clean"):
                brain.write_bytes(b"new learning")
            self.assertFalse(brain.exists())
            with self.assertRaises(RuntimeError):
                with BrainState(brain, "persisted"): pass

    def test_journal_supports_interrupted_run_and_blocks_reentry(self):
        with tempfile.TemporaryDirectory() as temp:
            brain = Path(temp)/"track.brain"; brain.write_bytes(b"original")
            state = BrainState(brain, "clean"); state.__enter__()
            with self.assertRaises(RuntimeError):
                BrainState(brain, "clean").__enter__()
            recover_brain(state.journal)
            self.assertEqual(brain.read_bytes(), b"original")
            # Interrupted after journal fsync but before the backup rename.
            state.journal.write_text(json.dumps({"name": brain.name, "original_sha256": fingerprint(brain)}))
            recover_brain(state.journal)
            self.assertEqual(brain.read_bytes(), b"original")

    def test_corrupt_backup_is_preserved_not_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            brain = Path(temp)/"track.brain"; brain.write_bytes(b"original")
            state = BrainState(brain, "clean"); state.__enter__()
            state.backup.write_bytes(b"corrupt")
            with self.assertRaises(RuntimeError): recover_brain(state.journal)
            self.assertTrue(state.journal.exists()); self.assertTrue(state.backup.exists())


def telemetry(rows, length=2000, omit_plan=None, bot=6, brain="missing", recovery=False, gear=2):
    lines = [f"OlethrosSession bot={bot} length={length}",
             f"OlethrosBrain bot={bot} status={brain}",
             f"OlethrosRegular mesh count=500 length={length} nominal=4 spacing=4"]
    for i, row in enumerate(rows):
        lap, distance, speed, accel, brake, pit = row
        identity = f"bot={bot} tick={i+1} time={i}"
        lines.append(f"OlethrosTick {identity} dt=1 recovery={int(recovery)} gear={gear} speed={speed}")
        lines.append(f"OlethrosNumeric controls {identity} steer=0 accel={accel} brake={brake} clutch=0")
        lines.append(f"OlethrosSeam state {identity} lap={lap} distance={distance} speed={speed} accel={accel} brake={brake} pit={pit}")
        if not recovery:
            lines.append(f"OlethrosNumeric target {identity} x=1 y=2 car=0,0")
            if speed >= -5:
                lines.append(f"OlethrosBrakePlan {identity} brake=0")
            if gear > 0 and i != omit_plan:
                lines.append(f"OlethrosPlan {identity} allowed=70")
    lines.append(f"OlethrosEnd bot={bot} ticks={len(rows)}")
    return "\n".join(lines)


class BehaviorChecks(unittest.TestCase):
    def test_race_ticks_require_positive_intervals(self):
        data = telemetry([(1,i*2,30,1,0,0) for i in range(12)])
        for step in ("0", "-0.02"):
            with self.subTest(step=step):
                self.assertTrue(check_behavior(data.replace("dt=1", "dt="+step), "road/forza", 2)["failures"])

    def test_end_marker_closes_only_its_own_bot_stream(self):
        rows = [(1,i*2,30,1,0,0) for i in range(12)]
        first = telemetry(rows, bot=6)
        second = telemetry(rows, bot=7)
        self.assertFalse(check_behavior(first+"\n"+second, "road/forza", 2, driver_indices=(6,7))["failures"])
        early_end = "OlethrosEnd bot=6 ticks=12\n"+first.replace("OlethrosEnd bot=6 ticks=12", "")
        self.assertTrue(check_behavior(early_end, "road/forza", 2)["failures"])

    def test_missing_or_nonfinite_controls_fail(self):
        self.assertTrue(check_behavior("", "road/forza", 2)["failures"])
        rows = [(1,i*2,30,1,0,0) for i in range(12)]
        self.assertFalse(check_behavior(telemetry(rows), "road/forza", 2)["failures"])
        self.assertTrue(check_behavior(telemetry(rows).replace("steer=0", "steer=nan"), "road/forza", 2)["failures"])

    def test_each_control_record_requires_all_control_fields(self):
        complete = telemetry([(1,i*2,30,1,0,0) for i in range(12)])
        for field in ("time", "steer", "accel", "brake", "clutch"):
            with self.subTest(field=field):
                lines = complete.splitlines()
                # Corrupt one record, leaving eleven complete records. A
                # minimum-record count must not hide partial telemetry.
                for i, line in enumerate(lines):
                    if line.startswith("OlethrosNumeric controls "):
                        lines[i] = " ".join(token for token in line.split() if not token.startswith(field+"="))
                        break
                failures = check_behavior("\n".join(lines), "road/forza", 2)["failures"]
                self.assertIn(f"control fields missing: {field}", "\n".join(failures))

    def test_time_only_control_records_cannot_pass(self):
        complete = telemetry([(1,i*2,30,1,0,0) for i in range(12)])
        partial = "\n".join(line.split(" steer=")[0] if line.startswith("OlethrosNumeric controls ")
                            else line for line in complete.splitlines())
        self.assertIn("control fields missing: accel, brake, clutch, steer",
                      "\n".join(check_behavior(partial, "road/forza", 2)["failures"]))

    def test_later_stronger_braking_demand_cannot_be_hidden(self):
        base = telemetry([(1,i*2,30,1,0,0) for i in range(12)])
        identity = "bot=6 tick=1 time=0"
        candidates = f"OlethrosSeam brake {identity} distance=3 delta=0.1\nOlethrosSeam brake {identity} distance=9 delta=8\n"
        import math
        good = base.replace(f"OlethrosBrakePlan {identity} brake=0", candidates+f"OlethrosBrakePlan {identity} brake={math.tanh(0.8)}")
        bad = base.replace(f"OlethrosBrakePlan {identity} brake=0", candidates+f"OlethrosBrakePlan {identity} brake={math.tanh(0.01)}")
        self.assertFalse(check_behavior(good,"road/forza",2)["failures"])
        self.assertTrue(check_behavior(bad,"road/forza",2)["failures"])

    def test_whole_records_and_entire_ticks_cannot_go_missing(self):
        complete = telemetry([(1,i*2,30,1,0,0) for i in range(12)])
        for prefix in ("OlethrosTick ", "OlethrosNumeric controls ", "OlethrosSeam state ",
                       "OlethrosNumeric target ", "OlethrosPlan ", "OlethrosBrakePlan "):
            with self.subTest(prefix=prefix):
                partial = "\n".join(line for line in complete.splitlines()
                                    if not (line.startswith(prefix) and "tick=6 " in line))
                self.assertTrue(check_behavior(partial, "road/forza", 2)["failures"])
        missing_tick = "\n".join(line for line in complete.splitlines() if "tick=6 " not in line)
        self.assertTrue(check_behavior(missing_tick, "road/forza", 2)["failures"])

    def test_braking_plan_session_and_end_coverage_are_required(self):
        complete = telemetry([(1,i*2,30,1,0,0) for i in range(12)])
        for prefix in ("OlethrosBrakePlan ", "OlethrosSession ", "OlethrosEnd "):
            with self.subTest(prefix=prefix):
                partial = "\n".join(line for line in complete.splitlines() if not line.startswith(prefix))
                self.assertTrue(check_behavior(partial, "road/forza", 2)["failures"])

    def test_persisted_mode_requires_positive_load_evidence(self):
        rows = [(1,i*2,30,1,0,0) for i in range(12)]
        self.assertFalse(check_behavior(telemetry(rows, brain="loaded"), "road/forza", 2, "persisted")["failures"])
        for status in ("missing", "rejected", "io-error", "fresh"):
            with self.subTest(status=status):
                self.assertTrue(check_behavior(telemetry(rows, brain=status), "road/forza", 2, "persisted")["failures"])
        partial = telemetry(rows).replace("OlethrosBrain bot=6 status=missing", "")
        self.assertTrue(check_behavior(partial, "road/forza", 2, "persisted")["failures"])
        self.assertTrue(check_behavior(telemetry(rows, brain="loaded"), "road/forza", 2, "clean")["failures"])

    def test_modes_define_which_planner_records_are_required(self):
        for recovery, gear, speed in ((True, -1, -2), (False, 0, 0), (False, -1, -8)):
            with self.subTest(recovery=recovery, gear=gear, speed=speed):
                data = telemetry([(1,i*2,speed,1,0,0) for i in range(12)], recovery=recovery, gear=gear)
                self.assertFalse(check_behavior(data, "road/forza", 2)["failures"])

    def test_interleaved_bots_require_separate_complete_observations(self):
        rows = [(1,i*2,30,1,0,0) for i in range(12)]
        first = telemetry(rows, bot=6).splitlines()
        second = telemetry(rows, bot=7).splitlines()
        data = "\n".join(line for pair in zip(first, second) for line in pair)
        self.assertFalse(check_behavior(data, "road/forza", 2, driver_indices=(6,7))["failures"])
        partial = "\n".join(line for line in data.splitlines()
                            if not line.startswith("OlethrosNumeric controls bot=7 tick=6 "))
        self.assertTrue(check_behavior(partial, "road/forza", 2, driver_indices=(6,7))["failures"])
        self.assertTrue(check_behavior("\n".join(first), "road/forza", 2, driver_indices=(6,7))["failures"])

    def test_duplicate_malformed_and_misidentified_records_fail(self):
        complete = telemetry([(1,i*2,30,1,0,0) for i in range(12)])
        control = next(line for line in complete.splitlines() if line.startswith("OlethrosNumeric controls "))
        for replacement in (control+"\n"+control, control.replace("bot=6", "bot=8"),
                            control.replace("tick=1", "tick=nan"), control.replace("steer=0", "steer=bad"),
                            control.replace("time=0", "time=100")):
            with self.subTest(replacement=replacement):
                self.assertTrue(check_behavior(complete.replace(control, replacement), "road/forza", 2)["failures"])
        target = next(line for line in complete.splitlines() if line.startswith("OlethrosNumeric target "))
        self.assertTrue(check_behavior(complete.replace(target, target+"\n"+target), "road/forza", 2)["failures"])

    def test_dirt_straight_rejects_plateau_and_pit_mask(self):
        rows = [(lap,1520+i*8,35+i,1,0,0) for lap in (1,2) for i in range(11)]
        self.assertFalse(check_behavior(telemetry(rows), "dirt/dirt-2", 2)["failures"])
        plateau = [(l,d,25.6,0.2,b,p) for l,d,s,a,b,p in rows]
        self.assertTrue(check_behavior(telemetry(plateau), "dirt/dirt-2", 2)["failures"])
        masked = [(l,d,s,a,b,1) for l,d,s,a,b,p in rows]
        self.assertTrue(check_behavior(telemetry(masked), "dirt/dirt-2", 2, "persisted")["failures"])

    def test_wide_oval_requires_smooth_fast_unmasked_flying_laps(self):
        rows = [(lap, d, 84, 1, 0, 0) for lap in (2, 3) for d in range(1400, 2001, 2)]
        data = telemetry(rows, length=3428).replace("pit=0", "pit=0 middle=0 radius=900")
        self.assertFalse(check_behavior(data, "oval/d-speedway", 3)["failures"])
        for before, after, expected in [("speed=84", "speed=40", "slowdown"),
                                        ("brake=0 ", "brake=0.5 ", "slowdown"),
                                        ("radius=900", "radius=50", "tight bend"),
                                        ("pit=0", "pit=1", "pit masks"),
                                        ("middle=0", "middle=nan", "nonfinite"),
                                        ("radius=900", "radius=nan", "nonfinite"),
                                        (" middle=0", "", "missing"),
                                        ("lap=3", "lap=4", "incomplete")]:
            with self.subTest(before=before, after=after):
                errors = check_behavior(data.replace(before, after), "oval/d-speedway", 3)["failures"]
                self.assertIn(expected, "\n".join(errors))
        weaving = "\n".join(line.replace("middle=0", "middle=4") if "distance=1600 " in line else line
                            for line in data.splitlines())
        self.assertIn("weaving", "\n".join(check_behavior(weaving, "oval/d-speedway", 3)["failures"]))

    def test_opposite_straight_rejects_heading_kicks_and_weaving(self):
        rows = [(lap, d, 70, 1, 0, 0) for lap in (2, 3) for d in range(900, 1031, 2)]
        data = telemetry(rows).replace("pit=0", "pit=0 middle=-10.6")
        self.assertFalse(check_behavior(data, "oval/a-speedway", 3)["failures"])
        kick = data.replace("tick=42 time=41 steer=0", "tick=42 time=41 steer=0.063")
        self.assertIn("steering kick", "\n".join(check_behavior(kick, "oval/a-speedway", 3)["failures"]))
        weaving = "\n".join(line.replace("middle=-10.6", "middle=-10.0") if "distance=950 " in line else line
                            for line in data.splitlines())
        self.assertIn("weaving", "\n".join(check_behavior(weaving, "oval/a-speedway", 3)["failures"]))
        for before, after in [("middle=-10.6", "middle=nan"), (" middle=-10.6", ""),
                              ("pit=0", "pit=1"), ("lap=3", "lap=4")]:
            with self.subTest(before=before, after=after):
                self.assertTrue(check_behavior(data.replace(before, after), "oval/a-speedway", 3)["failures"])

    def test_seam_requires_each_return_and_every_planner_sample(self):
        rows = []
        for lap in (1,2):
            rows.extend((lap,d,62,1,0,0) for d in (1975,1980,1985,1990,1995,1999))
            rows.extend((lap+1,d,62,1,0,0) for d in (0,3,6,9,12))
        self.assertFalse(check_behavior(telemetry(rows), "road/lone-star-circuit-full", 3)["failures"])
        self.assertTrue(check_behavior(telemetry(rows[:11]), "road/lone-star-circuit-full", 3)["failures"])
        self.assertTrue(check_behavior(telemetry(rows, omit_plan=8), "road/lone-star-circuit-full", 3)["failures"])
        skipped_ceiling = [((l,d,s,a,b,p) if d != 12 else (l,13.0615,s,a,b,p)) for l,d,s,a,b,p in rows]
        self.assertFalse(check_behavior(telemetry(skipped_ceiling), "road/lone-star-circuit-full", 3)["failures"])
        rows[8] = (2,6,1,0,0.5,0)
        self.assertTrue(check_behavior(telemetry(rows), "road/lone-star-circuit-full", 3)["failures"])


class RaceConfigurationCleanup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root/"runtime"
        (self.runtime/"config"/"raceman").mkdir(parents=True)
        self.out_dir = self.root/"results"
        self.out_dir.mkdir()
        self.track = Track("road", "forza", Path("unused"))
        self.config = self.runtime/"config"/"raceman"/("olethros-compat-"+runner.track_artifact_stem(self.track)+"-6-race.xml")
        self.args = Namespace(runtime_dir=self.runtime, wtorcs=Path("unused.exe"),
                                    olethros_idx=6, opponent_idx=[], laps=2, timeout=1,
                                    min_top_speed=0, max_sim_time=0, brain_state="clean")

    def test_early_failures_remove_owned_config_and_restore_brain(self):
        brain = self.root/"forza.brain"
        brain.write_bytes(b"original")
        for stage in ("build_raceman_xml", "shutil.copyfile", "result_xml_mtimes"):
            with self.subTest(stage=stage):
                # Keep the test independent of the installed runtime/user directory.
                with patch.object(runner, "result_xml_mtimes", return_value={}):
                    with patch("run_olethros_regression."+stage, side_effect=OSError("injected failure")):
                        with self.assertRaises(OSError):
                            with BrainState(brain, "clean"):
                                runner.run_track(self.args, self.track, self.out_dir)
                self.assertFalse(self.config.exists())
                self.assertEqual(brain.read_bytes(), b"original")
                self.assertFalse(brain.with_name(brain.name+".regression.json").exists())

    def test_launch_error_is_a_failed_result_and_restores_brain(self):
        brain = self.root/"forza.brain"
        brain.write_bytes(b"original")
        with patch.object(runner, "result_xml_mtimes", return_value={}), \
             patch.object(runner, "latest_result_xml") as latest, \
             patch.object(runner.subprocess, "run", side_effect=OSError("cannot launch")):
            with BrainState(brain, "clean"):
                result = runner.run_track(self.args, self.track, self.out_dir)
        self.assertEqual(result.status, "fail")
        self.assertIn("could not launch", result.message)
        latest.assert_not_called()
        self.assertFalse(self.config.exists())
        self.assertEqual(brain.read_bytes(), b"original")
        stem = runner.track_artifact_stem(self.track)
        for suffix in (".log", ".drivers.json", ".behavior.json"):
            self.assertTrue((self.out_dir/(stem+suffix)).exists())

    def test_completed_results_survive_unexpected_later_error(self):
        executable = self.runtime/"wtorcs.exe"
        executable.write_bytes(b"unused")
        out = self.root/"batch"
        tracks = [self.track, Track("road", "second", Path("unused"))]
        with patch.object(runner, "discover_tracks", return_value=tracks), \
             patch.object(runner, "local_torcs_dir", return_value=self.root/"local"), \
             patch.object(runner, "exclusive_session", return_value=contextlib.nullcontext()), \
             patch.object(runner, "run_track", side_effect=[runner.Result("road", "forza", "pass", 1), RuntimeError("bug")]), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "bug"):
                runner.main(["--runtime-dir", str(self.runtime), "--out-dir", str(out)])
        with (out/"summary.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([(row["track"], row["status"]) for row in rows], [("forza", "pass")])

    def test_batch_continues_after_launch_failure(self):
        executable = self.runtime/"wtorcs.exe"
        executable.write_bytes(b"unused")
        out = self.root/"launch-batch"
        tracks = [self.track, Track("road", "second", Path("unused"))]
        with patch.object(runner, "discover_tracks", return_value=tracks), \
             patch.object(runner, "local_torcs_dir", return_value=self.root/"local"), \
             patch.object(runner, "exclusive_session", return_value=contextlib.nullcontext()), \
             patch.object(runner.subprocess, "run", side_effect=OSError("cannot launch")) as launch, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(["--runtime-dir", str(self.runtime), "--out-dir", str(out)]), 1)
        self.assertEqual(launch.call_count, 2)
        with (out/"summary.csv").open(newline="", encoding="utf-8") as handle:
            self.assertEqual([row["status"] for row in csv.DictReader(handle)], ["fail", "fail"])

    def test_timeout_removes_owned_config(self):
        with patch.object(runner, "result_xml_mtimes", return_value={}), \
             patch.object(runner, "latest_result_xml", return_value=None), \
             patch.object(runner.subprocess, "run", side_effect=subprocess.TimeoutExpired("wtorcs", 1)):
            result = runner.run_track(self.args, self.track, self.out_dir)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.status, "fail")
        self.assertFalse(self.config.exists())

    def test_existing_config_is_never_removed(self):
        self.config.write_bytes(b"user-owned configuration")
        with self.assertRaises(FileExistsError):
            runner.run_track(self.args, self.track, self.out_dir)
        self.assertEqual(self.config.read_bytes(), b"user-owned configuration")


class ResultParsing(unittest.TestCase):
    def test_configuration_includes_all_selected_bots_in_order(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(build_raceman_xml(Track("road", "forza", Path("dummy")), 3, 6, (7,5)))
        drivers = root.find("./section[@name='Drivers']")
        self.assertIsNotNone(drivers)
        self.assertEqual(drivers.find("./attnum[@name='maximum number']").get("val"), "3")
        self.assertEqual([s.find("./attnum[@name='idx']").get("val") for s in drivers.findall("section")], ["6", "7", "5"])

    def test_race_results_are_checked_for_every_bot(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"results.xml"
            path.write_text('''<params><section name="Rank">
                <section name="1"><attstr name="module" val="olethros"/><attnum name="idx" val="6"/>
                <attnum name="laps" val="3"/><attnum name="top speed" val="60"/></section>
                <section name="2"><attstr name="module" val="olethros"/><attnum name="idx" val="7"/>
                <attnum name="laps" val="1"/><attnum name="top speed" val="50"/></section>
                </section></params>''')
            output = "Sim Time: 100 [s], Leader Laps: 3, Leader Distance: 2 [km]"
            results = [parse_run(Track("road", "forza", Path("dummy")), output, 1, 0, False, 10,
                                 path, idx, 3, 0, 0, Path("log")) for idx in (6,7,8)]
            self.assertEqual([r.status for r in results], ["pass", "fail", "fail"])
            self.assertEqual([r.driver_idx for r in results], [6,7,8])

    def test_configuration_has_requested_bot_laps_and_race_type(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(build_raceman_xml(Track("road", "a&b", Path("dummy")),3,6))
        self.assertEqual(root.find("./section[@name='Race']/attstr[@name='type']").get("val"), "race")
        self.assertEqual(root.find("./section[@name='Race']/attnum[@name='laps']").get("val"), "3")
        self.assertEqual(root.find("./section[@name='Drivers']/section/attnum[@name='idx']").get("val"), "6")

    def test_practice_configuration_enables_actual_practice_and_rejects_opponents(self):
        import xml.etree.ElementTree as ET
        track = Track("oval", "d-speedway", Path("dummy"))
        root = ET.fromstring(build_raceman_xml(track, 6, 6, session="practice"))
        self.assertEqual(root.find("./section[@name='Practice']/attstr[@name='type']").get("val"), "practice")
        self.assertEqual(root.find("./section[@name='Races']/section/attstr[@name='name']").get("val"), "Practice")
        with self.assertRaises(ValueError):
            build_raceman_xml(track, 6, 6, (7,), session="practice")

    def test_practice_results_require_identity_and_complete_finite_laps(self):
        xml = '''<params><section name="D-Speedway">
            <section name="Drivers"><section name="1">
            <attstr name="dll name" val="olethros"/><attnum name="index" val="6"/>
            </section></section><section name="Results"><section name="Practice">
            <attstr name="driver name" val="Olethros 7"/>
            <section name="1"><attnum name="time" val="46"/><attnum name="top speed" val="84"/></section>
            <section name="2"><attnum name="time" val="41"/><attnum name="top speed" val="85"/></section>
            </section></section></section></params>'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"practice.xml"
            path.write_text(xml)
            output = "Sim Time: 90 [s], Leader Laps: 2, Leader Distance: 7 [km]"
            result = parse_run(Track("oval", "d-speedway", Path("dummy")), output, 1, 0, False, 10,
                               path, 6, 2, 0, 0, Path("log"), "practice")
            self.assertEqual((result.status, result.laps, result.top_speed_mps, result.session),
                             ("pass", "2", "85", "practice"))
            self.assertTrue(runner.parse_driver_result(path, 7, "practice")[2])
            for before, after in [('name="2"', 'name="3"'), ('val="85"', 'val="nan"'),
                                  ('name="time" val="41"', 'name="time" val="0"'),
                                  ('name="top speed"', 'name="missing"'),
                                  ('name="index" val="6"', 'name="index" val="7"')]:
                with self.subTest(before=before, after=after):
                    path.write_text(xml.replace(before, after))
                    self.assertTrue(runner.parse_driver_result(path, 6, "practice")[2])

    def test_missing_result_and_timeout_cannot_pass(self):
        result = parse_run(Track("road","forza",Path("dummy")), "", 1, None, True, 1, None, 6, 2, 0, 0, Path("log"))
        self.assertEqual(result.status, "fail")
        self.assertIn("timed out", result.message); self.assertIn("result XML missing", result.message)


class RunnerPaths(unittest.TestCase):
    def test_reference_fixture_is_needed_only_for_reference_modes(self):
        for flags, needs_fixture in ((["--list"], False), (["--list", "--track", "forza"], False),
                                     (["--list", "--classic"], True),
                                     (["--compare-reference", "--laps", "2"], True)):
            with self.subTest(flags=flags), patch.object(runner, "discover_tracks", return_value=[Track("road", "forza", Path("unused"))]), \
                 patch.object(Path, "open", side_effect=FileNotFoundError("reference missing")) as opened, \
                 contextlib.redirect_stdout(io.StringIO()):
                if needs_fixture:
                    with self.assertRaises(FileNotFoundError): runner.main(flags)
                else:
                    self.assertEqual(runner.main(flags), 0)
                    opened.assert_not_called()

    def test_default_output_directories_are_unique_in_the_same_second(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runner.time, "strftime", return_value="same-second"):
            root = Path(temp)
            first = runner.create_output_dir(None, root)
            second = runner.create_output_dir(None, root)
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_dir())
            self.assertTrue(second.is_dir())
            with self.assertRaises(FileExistsError): runner.create_output_dir(first, root)

    def test_artifact_stems_distinguish_names_with_the_same_readable_slug(self):
        tracks = [Track("road", name, Path("unused")) for name in ("a b", "a&b", "a-b", "A-B")]
        stems = [runner.track_artifact_stem(track) for track in tracks]
        self.assertEqual(len(set(stem.lower() for stem in stems)), len(tracks))
        for track, stem in zip(tracks, stems):
            self.assertEqual(stem, runner.track_artifact_stem(track))
            self.assertRegex(stem, r"^[A-Za-z0-9_.-]+$")

    def test_missing_lifecycle_callback_has_a_clear_diagnostic(self):
        for pointer in (None, 0):
            with self.subTest(pointer=pointer):
                with self.assertRaisesRegex(RuntimeError, "initialize.*bot 6"):
                    check_lifecycle.require_callback(pointer, "initialize", 6)


if __name__ == "__main__":
    unittest.main()
