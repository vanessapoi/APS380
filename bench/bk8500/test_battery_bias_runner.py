"""Mock-only selector cannot reach a serial backend, irrespective of other flags."""
import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
import battery_bias_runner as bias
import live_torcs


class BiasLauncherTests(unittest.TestCase):
    def test_feedback_startup_failure_still_writes_failed_report(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(bias,'LiveReceiver',side_effect=OSError('bind busy')):
            output=Path(tmp)/'run'
            code=bias.main(['--propulsion-feedback','--no-console','--output',str(output)])
            report=json.loads((output/'trial.json').read_text())
            self.assertEqual(code,1)
            self.assertIn('bind busy',report['runtime_error'])
            self.assertFalse(report['native_zero_shutdown_verified'])
            self.assertTrue(report['instruments']['final']['shutdown_verified'])

    def test_defaults_and_keyboard_presets(self):
        a=bias.parse_args([])
        self.assertEqual(a.device,'mock');self.assertFalse(a.auto_arm_mock)
        self.assertFalse(a.propulsion_feedback)
        self.assertTrue(bias.parse_args(['--propulsion-feedback']).propulsion_feedback)
        for preset in ('3s','5s','8s'):
            self.assertEqual(bias.parse_args(['--torcs','keyboard','--keyboard-profile',preset]).keyboard_profile,preset)

    def test_physical_mode_and_serial_flags_rejected_before_any_service(self):
        with patch.object(bias,'BatteryBiasService') as service:
            for args in (['--device','hardware'],['--port','COM10'],['--approval','missing.json']):
                with self.subTest(args=args),self.assertRaises(SystemExit):
                    live_torcs.main(['--control-mode','battery-bias']+args)
            service.assert_not_called()

    def test_dispatch_preserves_arguments(self):
        with patch.object(bias,'main',return_value=0) as main:
            self.assertEqual(live_torcs.main(['--control-mode','battery-bias','--device','mock']),0)
            main.assert_called_once_with(['--device','mock'])

    def test_invalid_parameters(self):
        for args in (['--mock-psu-current-A','nan'],['--mock-psu-current-A','1.1'],['--duration','nan'],
                     ['--keyboard-profile','8s'],['--telemetry-port','70000']):
            with self.subTest(args=args),self.assertRaises(SystemExit):bias.parse_args(args)


if __name__=='__main__':unittest.main()
