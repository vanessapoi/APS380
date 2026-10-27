"""Complete-profile automatic scaling, independent clipping and CLI contracts."""
from dataclasses import replace
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from battery_model import process, process_auto_scaled
from cell_scaling import CellParameters, auto_scale_profile, scale_to_cell
from ev_model import VehicleParameters
from numerical_validation import TimingPolicy

BASE = Path(__file__).parent.resolve()


def sample(time, speed=0):
    return dict(time_s=time, speed_mps=speed, throttle=0, brake=0)


class AutoScalingTest(unittest.TestCase):
    def test_one_factor_preserves_shape_and_both_current_signs(self):
        # Unity currents: -2, +0.5, -1 A. One factor produces -1, +0.25, -0.5 A.
        powers = [50000., -12500., 25000.]
        before = list(powers)
        rows, info = auto_scale_profile(powers, 1.0)
        self.assertEqual(info['scale'], .5)
        self.assertEqual(info['original_current_peak_A'], 2)
        self.assertEqual(info['scaled_current_peak_A'], 1)
        self.assertEqual(info['remaining_clipped_samples'], 0)
        for row, expected in zip(rows, (-1, .25, -.5)):
            self.assertAlmostEqual(row['cell_current_unclamped_A'], expected)
            self.assertAlmostEqual(row['cell_current_command_A'], expected)
        self.assertEqual(powers, before)

    def test_peak_is_unclipped_and_can_be_in_the_charging_direction(self):
        params = CellParameters(discharge_limit_A=.4, charge_limit_A=.1)
        rows, info = auto_scale_profile([25000., -100000.], 1, params)
        self.assertEqual(info['original_current_peak_A'], 4)
        self.assertEqual(info['scale'], .25)
        self.assertEqual([row['cell_current_unclamped_A'] for row in rows], [-.25, 1])
        self.assertEqual(rows[1]['cell_current_command_A'], .1)
        self.assertEqual(info['remaining_clipped_samples'], 1)
        self.assertEqual(info['remaining_clipped_fraction'], .5)
        self.assertEqual(info['charge_clipped_samples'], 1)
        self.assertEqual(info['discharge_clipped_samples'], 0)

    def test_existing_experiment_scale_is_replaced_not_applied_twice(self):
        expected, _ = auto_scale_profile([50000., -12500.], 1)
        for old_scale in (.1, .2, 5., 1e308):
            rows, info = auto_scale_profile([50000., -12500.], 1,
                                             CellParameters(experiment_scale=old_scale))
            self.assertEqual(rows, expected)
            self.assertEqual(info['configured_experiment_scale'], old_scale)
            self.assertEqual(info['baseline_experiment_scale'], 1)
            self.assertEqual(info['scale'], .5)

    def test_no_amplification_and_zero_profile(self):
        for powers in ([12500., -6250.], [0., 0.], [0.]):
            rows, info = auto_scale_profile(powers, 1)
            self.assertEqual(info['scale'], 1)
            self.assertEqual(rows, [scale_to_cell(power) for power in powers])
        _, info = auto_scale_profile([0., 0.], math.nextafter(0., 1.))
        self.assertEqual(info['original_current_peak_A'], 0)
        self.assertEqual(info['scaled_current_peak_A'], 0)

    def test_single_sample_and_generator_are_supported(self):
        rows, info = auto_scale_profile((power for power in [50000.]), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(info['samples'], 1)
        self.assertEqual(info['scale'], .5)

    def test_invalid_targets_and_profiles(self):
        for target in (0, -1, True, False, '1', None, float('nan'), float('inf'), -float('inf'), 10**1000):
            with self.subTest(target=type(target).__name__), self.assertRaises(ValueError):
                auto_scale_profile([50000.], target)
        for profile in ([], iter([]), None, 1., '123', [0., float('nan')],
                        [0., float('inf')], [True], ['50000'], [10**1000]):
            with self.subTest(profile=type(profile).__name__), self.assertRaises(ValueError):
                auto_scale_profile(profile, 1)

    def test_reject_numerically_unrepresentable_scaling(self):
        with self.assertRaises(ValueError):
            auto_scale_profile([math.nextafter(0., 1.)], 1)  # baseline current underflows
        with self.assertRaises(ValueError):
            auto_scale_profile([1e308], math.nextafter(0., 1.))  # factor underflows
        with self.assertRaises(ValueError):
            auto_scale_profile([1e308, 1e-300], 1e-300)  # small sample underflows
        with self.assertRaises(ValueError):
            auto_scale_profile([1.], 1, CellParameters(nominal_voltage_V=1e308))

    def test_floating_point_roundoff_never_exceeds_target(self):
        for power in (1., 3.14159e8, 1e200, -1e200, 75000., -38700.):
            for target in (1., .1, 1e-10, 1e100):
                rows, info = auto_scale_profile([power, -power/3], target)
                self.assertLessEqual(info['scaled_current_peak_A'], target)
                self.assertTrue(0 < info['scale'] <= 1)
                self.assertTrue(all(abs(row['cell_current_unclamped_A']) <= target for row in rows))

    def test_zero_directional_bound_remains_an_independent_final_limit(self):
        rows, info = auto_scale_profile([50000., -12500.], 1,
                                        CellParameters(charge_limit_A=0))
        self.assertEqual(info['scale'], .5)
        self.assertEqual(rows[1]['cell_current_unclamped_A'], .25)
        self.assertEqual(rows[1]['cell_current_command_A'], 0)
        self.assertEqual(info['remaining_clipped_samples'], 1)

    def test_telemetry_wrapper_preserves_time_vehicle_fields_and_input(self):
        telemetry = [sample(0), sample(.5, 2), sample(2, 3), sample(3, 0)]
        original = [dict(row) for row in telemetry]
        cell = CellParameters(experiment_scale=.2)
        baseline = process(telemetry, cell=replace(cell, experiment_scale=1))
        rows, info = process_auto_scaled(telemetry, .01, cell=cell)
        self.assertLessEqual(info['scaled_current_peak_A'], .01)
        for before, after in zip(baseline, rows):
            for key in ('time_s', 'interval_s', 'speed_mps', 'accel_mps2', 'vehicle_battery_power_W'):
                self.assertEqual(after[key], before[key])
            self.assertAlmostEqual(after['cell_current_unclamped_A'],
                                   before['cell_current_unclamped_A']*info['scale'])
        self.assertEqual(telemetry, original)
        for invalid in ([], [sample(0), sample(0)], [sample(0), sample(1e-320, 1)]):
            with self.assertRaises(ValueError):
                process_auto_scaled(invalid, 1)
        with self.assertRaises(ValueError):
            process_auto_scaled([sample(0), sample(2)], 1, timing=TimingPolicy(max_gap_s=1))

    def test_zero_current_telemetry(self):
        rows, info = process_auto_scaled([sample(0), sample(1)], 1,
                                         vehicle=VehicleParameters(auxiliary_power_W=0))
        self.assertEqual(info['scale'], 1)
        self.assertTrue(all(row['cell_current_unclamped_A'] == 0 for row in rows))


class AutoScalingCliTest(unittest.TestCase):
    def run_cli(self, output, *args):
        env = dict(os.environ, MPLCONFIGDIR=str(output.parent/'matplotlib'))
        return subprocess.run([sys.executable, '-B', str(BASE/'run.py'),
                               '--input', str(BASE/'data/g29_20261020_200536.csv'),
                               '--config', str(BASE/'config_torcs.json'),
                               '--output-dir', str(output), *args],
                              env=env, capture_output=True, text=True, timeout=60)

    def test_one_amp_cli_and_legacy_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for automatic in (True, False):
                output = root/('automatic' if automatic else 'legacy')
                args = ('--target-current-a', '1.0') if automatic else ()
                result = self.run_cli(output, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                params = json.loads((output/'model_parameters.json').read_text())
                with (output/'current_profile.csv').open(newline='') as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(len(rows), 4293)
                if automatic:
                    info = params['automatic_scaling']
                    self.assertEqual(info['target_current_A'], 1)
                    self.assertAlmostEqual(info['original_current_peak_A'], 15.826110365792665)
                    self.assertLessEqual(info['scaled_current_peak_A'], 1)
                    self.assertEqual(params['cell']['experiment_scale'], info['scale'])
                    self.assertEqual(info['remaining_clipped_samples'], 0)
                    self.assertTrue(all(abs(float(row['cell_current_unclamped_A'])) <= 1 for row in rows))
                else:
                    self.assertNotIn('automatic_scaling', params)
                    self.assertEqual(params['cell']['experiment_scale'], 1)
                    self.assertAlmostEqual(max(abs(float(row['cell_current_unclamped_A'])) for row in rows),
                                           15.826110365792665)

    def test_invalid_cli_target_produces_no_output_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            for target in ('0', '-1', 'nan', 'inf'):
                output = Path(directory)/target
                result = self.run_cli(output, '--target-current-a', target)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
