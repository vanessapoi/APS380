"""Offline tests only: no real serial port is opened."""
import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from instrument import BK8500, ProtocolError, packet
from replay import main, prepare_torcs, run_profile


class Transport:
    def __init__(self, reply):
        self.reply = reply
        self.sent = []
    def reset_input_buffer(self): pass
    def flush(self): pass
    def write(self, data):
        self.sent.append(data)
        return len(data)
    def read(self, count): return self.reply


class ProtocolTests(unittest.TestCase):
    def test_current_command_units_and_ack(self):
        transport = Transport(packet(0x12, b'\x80'))
        device = BK8500(transport)
        device.set_current(.1)
        self.assertEqual(transport.sent[0], packet(0x2A, (1000).to_bytes(4, 'little')))

    def test_reject_invalid_replies(self):
        good = packet(0x5F)
        for reply in (good[:-1], good[:-1] + bytes((good[-1] ^ 1,)),
                      packet(0x5F, address=1), packet(0x6A), packet(0x12, b'\xC0')):
            with self.subTest(reply=reply), self.assertRaises(ProtocolError):
                BK8500(Transport(reply)).measure()

    def test_readback_units(self):
        data = (5120).to_bytes(4, 'little') + (990).to_bytes(4, 'little') + (506).to_bytes(4, 'little') + b'\x0c\x40\x00'
        m = BK8500(Transport(packet(0x5F, data))).measure()
        self.assertEqual((m['voltage_V'], m['measured_A'], m['power_W']), (5.12, .099, .506))
        self.assertTrue(m['input_on'])
        self.assertEqual(m['status'], 64)

    def test_reject_current_outside_bench_range(self):
        transport = Transport(b'')
        for i in (-.001, .1001, float('nan'), float('inf')):
            with self.assertRaises(ValueError): BK8500(transport).set_current(i)
        self.assertEqual(transport.sent, [])

    def test_shutdown_attempts_zero_even_when_off_fails(self):
        device = BK8500(Transport(b''))
        with patch.object(device, 'input', side_effect=TimeoutError('lost USB')) as off, \
             patch.object(device, 'set_current') as zero, \
             patch.object(device, 'measure', side_effect=TimeoutError('lost USB')), \
             patch('instrument.time.sleep'):
            result = device.shutdown()
        self.assertEqual(off.call_count, 2)
        zero.assert_called_once_with(0)
        self.assertFalse(result['verified'])


class ProfileTests(unittest.TestCase):
    def source(self, folder, values):
        path = Path(folder) / 'profile.csv'
        with path.open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['time_s', 'cell_current_unclamped_A'])
            writer.writerows(values)
        return path

    def test_sign_conversion_and_time_averaging(self):
        # Half interval discharge, half regeneration: rectify BEFORE averaging.
        values = [(n * .02, 2 if n < 25 else -1) for n in range(51)]
        with tempfile.TemporaryDirectory() as folder:
            source = self.source(folder, values)
            bins, metadata = prepare_torcs(source, 'discharge-positive')
            self.assertEqual(len(bins), 1)
            self.assertAlmostEqual(bins[0]['source_discharge_mean_A'], 1)
            self.assertAlmostEqual(bins[0]['regen_fraction'], .5)
            self.assertEqual(bins[0]['requested_A'], .1)
            source = self.source(folder, [(t, -i) for t, i in values])
            converted, _ = prepare_torcs(source, 'charging-positive')
            self.assertEqual(bins, converted)

    def test_bad_telemetry_fails(self):
        for values in ([(0, 1)], [(0, 1), (.1, 1)], [(0, 1), (0, 1)],
                       [(.02, 1), (.01, 1)], [(0, 1), (.02, float('nan'))],
                       [(-.01, 1), (.01, 1)]):
            with self.subTest(values=values), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    prepare_torcs(self.source(folder, values), 'discharge-positive')

    def test_unknown_capture_requires_sign(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                prepare_torcs(self.source(folder, [(0, 1), (.02, 1)]))

    def test_regen_only_produces_zero_and_partial_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            bins, metadata = prepare_torcs(self.source(folder, [(0, -1), (.02, -1)]), 'discharge-positive')
            self.assertEqual(bins[0]['requested_A'], 0)
            self.assertEqual(bins[0]['duration_s'], .02)

    def test_historical_capture_reproduces_recorded_plan(self):
        from replay import DEFAULT_SOURCE
        bins, metadata = prepare_torcs(DEFAULT_SOURCE)
        captured = Path(__file__).parent / 'evidence/2026-10-27/torcs_profile_20261027_163348/planned_profile.csv'
        with captured.open() as f:
            original = list(csv.DictReader(f))
        self.assertEqual([b['requested_A'] for b in bins], [float(b['requested_A']) for b in original])
        self.assertAlmostEqual(metadata['duration_s'], 17.95200208)


class FakeDevice:
    def __init__(self, fail=False):
        self.enabled = False
        self.current = 0
        self.fail = fail
        self.shutdown_called = False
        self.last_roundtrip_ms = 60
    def identify(self): return {'model': '8500'}
    def remote(self): pass
    def input(self, enabled): self.enabled = enabled
    def fixed_cc(self): pass
    def set_current(self, i): self.current = i
    def current_setting(self): return self.current
    def measure(self):
        if self.enabled and self.fail: raise TimeoutError('injected measurement failure')
        return dict(voltage_V=5., measured_A=self.current if self.enabled else 0.,
                    power_W=5 * self.current if self.enabled else 0.,
                    input_on=self.enabled, status=64 if self.enabled else 0)
    def shutdown(self):
        self.shutdown_called = True
        self.enabled = False
        self.current = 0
        return {'verified': True}


class HardwareGateTests(unittest.TestCase):
    def test_missing_hardware_confirmations_fail_before_connecting(self):
        for argv in (["replay.py", "--run"],
                     ["replay.py", "--run", "--port", "COM4", "--confirm-ttl"],
                     ["replay.py", "--identify", "--port", "COM4"],
                     ["replay.py", "--run", "--ports"]):
            with self.subTest(argv=argv), patch('sys.argv', argv), \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                main()
            self.assertEqual(exc.exception.code, 2)


class PlaybackTests(unittest.TestCase):
    def test_completion_and_fault_both_shutdown_and_log(self):
        for fail in (False, True):
            device = FakeDevice(fail)
            bins = [dict(step=0, scheduled_s=0., duration_s=1., requested_A=.1)]
            with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
                if fail:
                    with self.assertRaises(TimeoutError):
                        run_profile(device, bins, Path(folder), clock=lambda: 0., sleep=lambda _: None)
                else:
                    run_profile(device, bins, Path(folder), clock=lambda: 0., sleep=lambda _: None)
                result = json.loads((Path(folder) / 'result.json').read_text())
            self.assertTrue(device.shutdown_called)
            self.assertFalse(device.enabled)
            self.assertEqual(result['completed'], not fail)
            self.assertTrue(result['shutdown']['verified'])


if __name__ == '__main__':
    unittest.main()
