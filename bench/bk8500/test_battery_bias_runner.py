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
        self.assertEqual(a.mock_preset,'baseline');self.assertEqual(a.mock_psu_current_A,.2)
        self.assertFalse(a.mock_source_overridden)
        self.assertTrue(bias.parse_args(['--propulsion-feedback']).propulsion_feedback)
        for preset in ('3s','5s','8s'):
            self.assertEqual(bias.parse_args(['--torcs','keyboard','--keyboard-profile',preset]).keyboard_profile,preset)

    def test_manual_mock_preset_and_explicit_override(self):
        a=bias.parse_args(['--mock-preset','manual-driving'])
        self.assertEqual(a.mock_psu_current_A,1.);self.assertFalse(a.mock_source_overridden)
        self.assertEqual(a.device,'mock');self.assertFalse(a.auto_arm_mock)
        a=bias.parse_args(['--mock-preset','manual-driving','--mock-psu-current-A','.2'])
        self.assertEqual(a.mock_psu_current_A,.2);self.assertTrue(a.mock_source_overridden)

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

    def test_mock_file_cannot_reach_hardware_or_psu_only_transport(self):
        with patch.object(live_torcs,'BK8500') as hardware,patch.object(bias,'BatteryBiasService') as service:
            for mode in ('psu-only','battery-bias'):
                with self.subTest(mode=mode),self.assertRaises(SystemExit):
                    live_torcs.main(['--control-mode',mode,'--device','hardware','--mock-test-config','missing.json'])
            hardware.assert_not_called();service.assert_not_called()

    def test_custom_conflicting_flags_rejected(self):
        for flag in (['--sop-config','x'],['--mock-preset','baseline'],['--mock-psu-current-A','.2'],['--sop-c=x']):
            with self.subTest(flag=flag),self.assertRaises(SystemExit):
                bias.parse_args(['--mock-test-config','x']+flag)

    def test_gui_cancel_precedes_all_session_initialization(self):
        with tempfile.TemporaryDirectory() as tmp,patch('live_display.MockExperimentSetup') as setup,patch.object(bias,'BatteryBiasService') as service,patch.object(bias,'LiveReceiver') as receiver:
            setup.return_value.run.return_value=None
            output=Path(tmp)/'not-created'
            self.assertEqual(bias.main(['--mock-setup','--output',str(output)]),0)
            self.assertFalse(output.exists());service.assert_not_called();receiver.assert_not_called()

    def test_gui_selection_reaches_existing_launcher_and_report(self):
        from mock_test_config import load_mock_test_config
        chosen=load_mock_test_config(bias.ROOT/'aps380_torcs_starter/profiles/mock_test_20_percent_manual.json')
        with tempfile.TemporaryDirectory() as tmp,patch('live_display.MockExperimentSetup') as setup,patch.object(bias,'LiveReceiver',side_effect=OSError('test bind failure')):
            setup.return_value.run.return_value=chosen
            output=Path(tmp)/'run'
            code=bias.main(['--mock-setup','--output',str(output)])
            report=json.loads((output/'trial.json').read_text())
            self.assertEqual(code,1)
            self.assertEqual(report['mock_test_config'],chosen.audit)
            self.assertTrue(report['instruments']['final']['shutdown_verified'])

    def test_gui_only_mock_and_supervised_start(self):
        self.assertTrue(bias.parse_args(['--mock-setup']).dashboard)
        self.assertFalse(bias.parse_args([]).mock_setup)
        for flags in (['--no-console'],['--auto-arm-mock'],['--mock-preset','baseline']):
            with self.assertRaises(SystemExit):bias.parse_args(['--mock-setup']+flags)
        with patch.object(live_torcs,'BK8500') as hardware:
            for mode in ('psu-only','battery-bias'):
                with self.assertRaises(SystemExit):live_torcs.main(['--control-mode',mode,'--device','hardware','--mock-setup'])
            hardware.assert_not_called()

    def test_invalid_file_rejected_before_output_and_services(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(bias,'BatteryBiasService') as service:
            path=Path(tmp)/'invalid.json';path.write_text('{}');output=Path(tmp)/'output'
            with self.assertRaises(ValueError):
                bias.main(['--mock-test-config',str(path),'--output',str(output),'--no-console'])
            self.assertFalse(output.exists());service.assert_not_called()

    def test_invalid_parameters(self):
        for args in (['--mock-psu-current-A','nan'],['--mock-psu-current-A','1.1'],['--duration','nan'],
                     ['--keyboard-profile','8s'],['--telemetry-port','70000']):
            with self.subTest(args=args),self.assertRaises(SystemExit):bias.parse_args(args)


if __name__=='__main__':unittest.main()
