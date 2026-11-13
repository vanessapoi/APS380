"""Extended PSU-only commissioning tests. No instrument connections."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from live_control import LiveConfig, LiveController, MockLiveLoad, LatestDemand, validate_approval
from live_torcs import parse_args, main
from test_live_control import Clock, approval, row


def config():
    return LiveConfig(max_current_A=1., max_power_W=5.5, reference_current_A=2.,
                      slew_A_per_s=.02, tracking_tolerance_A=.01,
                      protection_envelope=(30., 3., 90.))


class ExtendedTests(unittest.TestCase):
    def controller(self):
        clock = Clock(); cfg = config()
        device = MockLiveLoad(cfg, clock, clock.sleep, delay_s=.001)
        box = LatestDemand()
        c = LiveController(device, box, cfg, clock, clock.sleep)
        c.initialize()
        self.assertEqual(c.state, 'READY', c.fault)
        box.publish(row(clock, -2.))
        self.assertTrue(c.arm(), c.fault)
        return clock, device, box, c

    def test_mapping_is_one_third_of_original_range_and_regen_zero(self):
        old = LiveConfig(); new = config()
        for signed in (-10., -2., -1., -.1, 0., .5):
            self.assertAlmostEqual(new.map_current(signed)[1], old.map_current(signed)[1]/3.)

    def test_reaches_one_amp_and_returns_to_zero_with_slew(self):
        clock, device, box, c = self.controller()
        for signed in ([-4.]*60 + [1.]*60):
            clock.sleep(1); box.publish(row(clock, signed)); previous = c.applied
            c.cycle()
            self.assertEqual(c.state, 'RUNNING', c.fault)
            self.assertLessEqual(abs(c.applied-previous), .0200000001)
            self.assertLessEqual(c.applied, 1.)
            self.assertLess(abs(c.last['tracking_error_A']), .01)
            if signed < 0: peak = c.applied
        self.assertEqual(peak, 1.)
        self.assertEqual(c.applied, 0.)
        c.stop(); self.assertTrue(c.shutdown['verified'])

    def test_rapid_reversal_stale_and_recovery_do_not_rearm(self):
        clock, device, box, c = self.controller()
        for i in range(12):
            clock.sleep(1); box.publish(row(clock, -2. if i%2 else 1.)); c.cycle()
            self.assertEqual(c.state, 'RUNNING', c.fault)
        clock.sleep(.6); c.cycle()
        self.assertEqual(c.state, 'FAULT'); self.assertFalse(device.enabled)
        self.assertTrue(c.shutdown['verified'])
        box.publish(row(clock)); c.cycle()
        self.assertEqual(c.state, 'FAULT')
        c.reset(); self.assertEqual(c.state, 'READY'); self.assertFalse(device.enabled)

    def test_communications_failure_remains_unverified_and_latched(self):
        clock, device, box, c = self.controller()
        device.failure = 'timeout'; c.cycle()
        self.assertEqual(c.state, 'FAULT'); self.assertFalse(c.shutdown['verified'])

    def test_protections_are_rechecked_before_arm(self):
        clock = Clock(); cfg = config(); device = MockLiveLoad(cfg, clock, clock.sleep)
        box = LatestDemand(); c = LiveController(device, box, cfg, clock, clock.sleep)
        c.initialize(); box.publish(row(clock))
        device.protection_limits = lambda: dict(voltage_V=30., current_A=4., power_W=90.)
        self.assertFalse(c.arm())
        self.assertEqual(c.state, 'FAULT'); self.assertFalse(device.enabled)
        self.assertNotIn('input_True', [name for name, _ in device.commands])

    def test_actual_maxima_outside_either_end_block_initialization(self):
        for limits in ((30., .9, 90.), (31., 3., 90.), (30., 4., 90.), (30., 3., 91.),
                       (30., 3., 5.4)):
            cfg = config(); device = MockLiveLoad(cfg, delay_s=0)
            device.protection_limits = lambda: dict(zip(('voltage_V','current_A','power_W'),limits))
            c = LiveController(device, LatestDemand(), cfg); c.initialize()
            self.assertEqual(c.state, 'FAULT'); self.assertFalse(device.enabled)

    def test_approval_must_cover_extended_scope_and_existing_protections(self):
        p = approval()
        with self.assertRaises(ValueError): validate_approval(p, config())
        p.update(extended_psu_only_commissioning_approved=True,
                 approved_load_max_voltage_V=30., approved_load_max_current_A=3.,
                 approved_load_max_power_W=90.)
        validate_approval(p, config())
        for key in ('approved_current_A', 'approved_load_max_current_A', 'wiring_current_rating_A'):
            with self.assertRaises(ValueError): validate_approval(dict(p, **{key:.1}), config())

    def test_cli_requires_opt_in_and_complete_envelope(self):
        for args in (['--device','hardware','--max-current-A','1'],
                     ['--extended-psu-only','--max-current-A','1'],
                     ['--extended-psu-only','--max-current-A','1.01',
                      '--protection-voltage-ceiling-V','30','--protection-current-ceiling-A','3',
                      '--protection-power-ceiling-W','90']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): parse_args(args)

    def test_cli_hardware_still_forbids_auto_arm_and_piped_console(self):
        p = approval(); p.update(extended_psu_only_commissioning_approved=True,
            approved_load_max_voltage_V=30., approved_load_max_current_A=3., approved_load_max_power_W=90.)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'approval.json'; path.write_text(json.dumps(p))
            args = ['--device','hardware','--extended-psu-only','--max-current-A','1',
                    '--max-power-W','5.5','--port','TEST_ONLY','--approval',str(path),
                    '--protection-voltage-ceiling-V','30','--protection-current-ceiling-A','3',
                    '--protection-power-ceiling-W','90']
            with patch('sys.stdin.isatty', return_value=True):
                self.assertEqual(parse_args(args).config.max_current_A, 1.)
            for extra in ([], ['--auto-arm-mock'], ['--no-console']):
                with patch('sys.stdin.isatty', return_value=False), \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): parse_args(args+extra)

    def test_startup_failure_preserves_fault_experiment_report(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'trial'
            with patch('live_torcs.prepare_launch_profile', side_effect=OSError('mock launch failure')), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main(['--device','mock','--torcs','ai','--duration','10',
                    '--telemetry-port','0','--no-console','--output',str(output),
                    '--inject-telemetry-loss-after','5','--expect-telemetry-fault'])
            self.assertNotEqual(code, 0)
            report = json.loads((output/'trial.json').read_text())
            self.assertFalse(report['fault_response_passed'])
            self.assertIsNone(report['interruption_host_s'])
            self.assertIn('mock launch failure', report['runtime_error'])


if __name__ == '__main__': unittest.main()
