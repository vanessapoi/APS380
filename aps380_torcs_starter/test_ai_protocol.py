"""Interval qualification must use contiguous simulation time, not sample counts."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from run_tesla_ai import longest_interval


class ProtocolIntervalTest(unittest.TestCase):
    def test_short_separate_holds_cannot_be_combined(self):
        rows = [{'time_s': i*.02, 'qualified': q} for i, q in enumerate(
            [False]+[True]*6+[False]+[True]*6)]
        self.assertAlmostEqual(longest_interval(rows, lambda x: x['qualified']), .12)

    def test_irregular_sampling_uses_elapsed_time(self):
        rows = [{'time_s': t, 'qualified': True} for t in (0, .02, .07, .11)]
        self.assertAlmostEqual(longest_interval(rows, lambda x: x['qualified']), .11)

    def test_dropout_cannot_count_as_a_steady_hold(self):
        rows = [{'time_s': t} for t in (0, .02, 10, 10.02)]
        self.assertAlmostEqual(longest_interval(rows, lambda x: True), .02)

    def test_single_sample_has_no_duration(self):
        self.assertEqual(longest_interval([{'time_s': 10}], lambda x: True), 0)


if __name__ == '__main__':
    unittest.main()
