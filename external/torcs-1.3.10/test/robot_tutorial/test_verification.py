"""Portable regression tests for verification infrastructure, not driving physics.
Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from maintenance import Run
from race_support import race_entries, write_race, read_ranks, require
from check_windows import validate_ranks, workflow, verify_build_summary


class RaceFixtures(unittest.TestCase):
    def test_reversed_indices_and_opponent_order(self):
        case = {'module': 'tutorialc', 'indices': [2, 1], 'opponent': 'bt',
                'opponent_index': 7, 'opponent_first': True}
        entries = race_entries(case)
        self.assertEqual(entries, [('bt', 7), ('tutorialc', 2), ('tutorialc', 1)])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'race.xml'
            write_race(path, entries, 'e-track-2', 12, 2)
            tree = ET.parse(path)
            rows = tree.findall("./section[@name='Drivers']/section")
            self.assertEqual([(require(r, 'attstr').attrib['val'], int(require(r, 'attnum').attrib['val'])) for r in rows], entries)
            self.assertEqual(require(tree, ".//section[@name='Tracks']/section/attstr[@name='name']").get('val'), 'e-track-2')
            self.assertEqual(require(tree, "./section[@name='Quick Race']/attnum[@name='laps']").get('val'), '12')
            self.assertEqual(require(tree, "./section[@name='Quick Race']/attnum[@name='cars per pit']").get('val'), '2')

    def test_motion_grid_order(self):
        self.assertEqual(race_entries({'module': 'tutorial5', 'motion': True}),
                         [('tutorial5pace', 1), ('tutorial5', 1), ('tutorial5rear', 1)])

    def test_result_parser_preserves_module_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'result.xml'
            path.write_text('<params><section name="Rank"><section name="1">'
                            '<attstr name="module" val="tutorialc"/><attnum name="idx" val="2"/>'
                            '</section></section></params>', encoding='utf-8')
            self.assertEqual(read_ranks(path), [{'module': 'tutorialc', 'idx': '2'}])

    def test_documented_workflows_are_unambiguous(self):
        for suffix in '23456abc':
            with self.subTest(suffix=suffix):
                copy, build, _ = workflow('tutorial'+suffix)
                self.assertIn('Copy-Item', copy)
                self.assertIn('/p:Platform=x64', build)


class WindowsResultChecks(unittest.TestCase):
    def test_build_summary_requires_exact_zero_counts(self):
        verify_build_summary('    0 Warning(s)\n    0 Error(s)\n', 1)
        for output in ('10 Warning(s)\n0 Error(s)\n', '0 Warning(s)\n10 Error(s)\n', ''):
            with self.subTest(output=output), self.assertRaises(AssertionError):
                verify_build_summary(output, 1)

    def setUp(self):
        self.row = {'module': 'tutorial6', 'idx': '1', 'laps': '6',
                    'best lap time': '51', 'top speed': '60', 'dammages': '0',
                    'penaltytime': '0', 'pits stops': '0'}

    def test_rejects_missing_duplicate_wrong_or_incomplete_driver(self):
        cases = [[], [self.row, self.row], [dict(self.row, idx='2')], [dict(self.row, laps='5')]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(AssertionError):
                validate_ranks(rows, [('tutorial6', 1)], 6)

    def test_rejects_damage_penalties_and_nonfinite_motion(self):
        for key, value in [('dammages', '1'), ('penaltytime', '0.01'), ('best lap time', 'nan'), ('top speed', 'inf'), ('top speed', '0')]:
            with self.subTest(key=key), self.assertRaises(AssertionError):
                validate_ranks([dict(self.row, **{key: value})], [('tutorial6', 1)], 6)

    def test_demo_requires_actual_stop(self):
        with self.assertRaises(AssertionError):
            validate_ranks([self.row], [('tutorial6', 1)], 6, demo=True)
        validate_ranks([dict(self.row, **{'pits stops': '1'})], [('tutorial6', 1)], 6, demo=True)

    def test_recovery_exception_does_not_relax_lap_requirement(self):
        row = dict(self.row, module='tutorial2', dammages='29', penaltytime='0.09')
        validate_ranks([row], [('tutorial2', 1)], 6)
        with self.assertRaises(AssertionError):
            validate_ranks([dict(row, laps='0')], [('tutorial2', 1)], 6)


class EvidenceFailures(unittest.TestCase):
    def test_nonzero_exit_and_timeout_leave_failed_reports(self):
        for label, code, timeout, expected in [('exit', 'raise SystemExit(7)', 10, 'failed'),
                                              ('timeout', 'import time; time.sleep(30)', 0.1, 'timed out')]:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                with contextlib.redirect_stdout(io.StringIO()):
                    run = Run(folder, 'negative')
                    with self.assertRaises(RuntimeError):
                        with run:
                            run.command(label, [sys.executable, '-c', code], timeout=timeout)
                report = json.loads((run.work/'report.json').read_text(encoding='utf-8'))
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['checks'][0]['status'], expected)
                self.assertTrue((run.work/(label+'.log')).is_file())


if __name__ == '__main__':
    unittest.main()
