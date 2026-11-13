"""OFF-only checks use in-memory devices; never open a serial port."""
import unittest
from unittest.mock import patch

from live_control import MockLiveLoad, validate_approval
from off_preflight import OffOnlyDevice, check, inspect, low_config, main


class OffPreflightTests(unittest.TestCase):
    def device(self):
        return MockLiveLoad(low_config(), delay_s=0)

    def test_pass_without_approval_never_enables_or_requests_current(self):
        device = self.device()
        with patch.object(device, 'input', wraps=device.input) as inputs, \
                patch.object(device, 'set_current', wraps=device.set_current) as currents:
            report = check(device, low_config(), 'MOCK_ONLY')
        self.assertEqual(report['result'], 'PASS')
        self.assertTrue(report['shutdown']['verified'])
        self.assertTrue(inputs.call_args_list)
        self.assertTrue(all(call.args == (False,) for call in inputs.call_args_list))
        self.assertTrue(all(call.args == (0,) for call in currents.call_args_list))
        self.assertFalse(report['arming_available'])
        self.assertFalse(report['current_draw_assessed'])

    def test_facade_rejects_on_and_nonzero_current(self):
        device = OffOnlyDevice(self.device())
        for value in (True, 1, None):
            with self.assertRaises(ValueError): device.input(value)
        for value in (.0001, -.1, float('nan')):
            with self.assertRaises(ValueError): device.set_current(value)

    def test_inspection_reads_actual_maxima_without_any_writes(self):
        device = self.device()
        device.protection_limits = lambda: dict(voltage_V=30., current_A=3., power_W=90.)
        report = inspect(device, low_config(), 'MOCK_ONLY')
        self.assertEqual(report['observed_protection_limits']['current_A'], 3.)
        self.assertEqual([name for name, _ in device.commands], ['identify', 'measure'])
        self.assertIn('NOT ASSESSED', report['scope'])
        device.enabled = True
        with self.assertRaises(ValueError): inspect(device, low_config())

    def test_protection_mismatch_fails_and_shuts_down(self):
        device = self.device()
        device.protection_limits = lambda: dict(voltage_V=5.5, current_A=3, power_W=.6)
        report = check(device, low_config())
        self.assertEqual(report['result'], 'FAIL')
        self.assertTrue(report['shutdown']['verified'])
        self.assertEqual(report['observed_protection_limits']['current_A'], 3)

    def test_voltage_outside_envelope_fails(self):
        device = self.device()
        original = device.measure
        device.measure = lambda: dict(original(), voltage_V=5.6)
        self.assertEqual(check(device, low_config())['result'], 'FAIL')

    def test_serial_mismatch_fails_without_enabling(self):
        report = check(self.device(), low_config(), 'OTHER_TEST_DEVICE')
        self.assertEqual(report['fault'], 'INSTRUMENT_SERIAL_MISMATCH')
        self.assertTrue(report['shutdown']['verified'])

    def test_communication_failure_reports_unverified_shutdown(self):
        device = self.device()
        device.measure = lambda: (_ for _ in ()).throw(TimeoutError('mock timeout'))
        report = check(device, low_config())
        self.assertEqual(report['result'], 'FAIL')
        self.assertFalse(report['shutdown']['verified'])

    def test_full_current_draw_approval_still_rejects_missing_fields(self):
        with self.assertRaises(ValueError):
            validate_approval(dict(supervised_lab_approval=True), low_config())

    def test_hardware_requires_explicit_port_and_ttl_confirmation(self):
        with self.assertRaises(SystemExit): main(['--device', 'hardware'])


if __name__ == '__main__':
    unittest.main()
