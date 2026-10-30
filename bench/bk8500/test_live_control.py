"""Live bench regression tests. Fake instruments only; no serial ports opened."""
from dataclasses import replace
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

if sys.version_info < (3, 10):
    raise unittest.SkipTest('New live controller requires Python 3.10+; legacy replay remains Python 3.9 compatible')

from live_control import (LiveConfig, LiveController, LiveService, LatestDemand,
                          MockLiveLoad, validate_approval)
from live_torcs import console, main, parse_args
from instrument import BK8500, packet
from test_bench import Transport
from prototype_current_config import current_metadata


class Clock:
    def __init__(self): self.t = 10.
    def __call__(self): return self.t
    def sleep(self, seconds): self.t += seconds


def row(clock, current=-.5, session='live', seq=0):
    return dict(**current_metadata(), target_available=True,
                cell_current_unclamped_A=current, cell_current_command_A=max(-2., min(1., current)),
                received_qpc_s=clock(), session_id=session, sequence=seq, time_s=seq*.02)


def approval():
    return dict(approved_by='TEST_ONLY', approval_reference='MOCK_APPROVAL',
        psu_model='FAKE', psu_output='CH1_independent', source_limit_kind='adjustable_current_limit',
        verified_output_voltage_V=5., psu_channel_voltage_rating_V=30.,
        psu_channel_current_rating_A=3., psu_channel_power_rating_W=90.,
        verified_source_current_ceiling_A=3.1, wiring_current_rating_A=3.,
        approved_current_A=3., approved_voltage_max_V=5.5, approved_power_W=18.,
        approved_slew_A_per_s=.5, approved_control_hz=1., no_battery=True, ttl_verified=True,
        wiring_polarity_and_ratings_verified=True, independent_protection_and_estop_verified=True,
        psu_settings_verified=True, supervised_lab_approval=True)


class LiveControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(); self.config = LiveConfig()
        self.device = MockLiveLoad(self.config, self.clock, self.clock.sleep)
        self.box = LatestDemand()
        self.c = LiveController(self.device, self.box, self.config, self.clock, self.clock.sleep)
        self.c.initialize()

    def arm(self):
        self.box.publish(row(self.clock))
        self.assertTrue(self.c.arm(), self.c.fault)

    def tick(self, current):
        self.clock.sleep(1.)
        self.box.publish(row(self.clock, current))
        self.c.cycle()

    def test_ready_does_not_enable_or_automatically_arm(self):
        self.assertEqual(self.c.state, 'READY')
        self.assertFalse(self.device.enabled)
        self.assertNotIn('input_True', [x[0] for x in self.device.commands])
        self.assertFalse(self.c.arm())

    def test_direct_mapping_full_range_regeneration_and_no_bias(self):
        self.assertEqual(self.config.map_current(-2.), (3., 3.))
        self.assertEqual(self.config.map_current(0.), (0., 0.))
        self.assertEqual(self.config.map_current(1.), (-1.5, 0.))
        self.assertEqual(self.config.map_current(-4.), (6., 3.))
        self.arm()
        for _ in range(8): self.tick(-2.)
        self.assertEqual(self.c.state, 'RUNNING', self.c.fault)
        self.assertEqual(self.c.last['commanded_load_A'], 3.)
        self.assertLess(abs(self.c.last['tracking_error_A']), .05)
        for _ in range(8): self.tick(1.)
        self.assertEqual(self.c.applied, 0.)
        self.assertEqual(self.c.last['original_cell_current_A'], 1.)
        self.assertTrue(self.c.last['regen_suppressed'])

    def test_dynamic_source_voltage_and_power_limit_are_logged(self):
        self.arm(); self.c.config = replace(self.config, max_power_W=5.)
        for _ in range(5): self.tick(-2.)
        self.assertLessEqual(self.c.applied, 1.)
        self.assertEqual(self.c.last['limited_load_target_A'], 3.)
        self.assertEqual(self.c.last['power_limited_load_target_A'], 1.)

    def test_psu_limiting_or_voltage_droop_faults_and_disables(self):
        self.arm(); self.device.source_limit_A = .1
        self.tick(-2.)
        self.assertEqual(self.c.state, 'FAULT')
        self.assertIn('VOLTAGE', self.c.fault)
        self.assertTrue(self.c.shutdown['verified'])
        self.assertFalse(self.device.enabled)

    def test_tracking_failure_latches(self):
        self.arm(); self.device.response_s = 100.
        for _ in range(5):
            if self.c.state == 'FAULT': break
            self.tick(-2.)
        self.assertEqual(self.c.fault, 'CURRENT_TRACKING_TIMEOUT_POSSIBLE_PSU_CC')
        self.assertTrue(self.c.shutdown['verified'])

    def test_setpoint_readback_mismatch_faults(self):
        self.arm(); self.device.readback_offset_A = .001
        self.tick(-.5)
        self.assertEqual(self.c.fault, 'SETPOINT_READBACK_MISMATCH')
        self.assertFalse(self.device.enabled)
        self.assertFalse(self.c.shutdown['verified'])  # bad readback cannot prove zero

    def test_stale_or_invalid_telemetry_disables(self):
        for reason in ('stale', 'invalid', 'new_session'):
            self.setUp(); self.arm()
            if reason == 'stale': self.clock.sleep(.51)
            elif reason == 'invalid': self.box.publish(None, 'INVALID')
            else: self.box.publish(row(self.clock, session='different'))
            self.c.cycle()
            self.assertEqual(self.c.state, 'FAULT')
            self.assertTrue(self.c.shutdown['verified'])

    def test_communication_loss_reports_unverified_shutdown(self):
        for failure in ('communication', 'timeout'):
            self.setUp(); self.arm(); self.device.failure = failure
            self.tick(-.5)
            self.assertEqual(self.c.state, 'FAULT')
            self.assertFalse(self.c.shutdown['verified'])
            self.assertTrue(self.c.shutdown['errors'])

    def test_emergency_stop_during_io_and_explicit_recovery(self):
        self.arm()
        original = self.device.set_current
        def interrupt(i):
            original(i); self.c.abort.set()
        with patch.object(self.device, 'set_current', side_effect=interrupt):
            self.tick(-.5)
        self.assertEqual(self.c.fault, 'EMERGENCY_STOP')
        self.assertFalse(self.device.enabled)
        self.c.reset()
        self.assertEqual(self.c.state, 'READY')
        self.assertFalse(self.c.arm())  # new telemetry and separate ARM required
        self.clock.sleep(.01); self.arm()

    def test_invalidated_sample_during_io_does_not_enable(self):
        self.box.publish(row(self.clock))
        original = self.device.current_setting
        def invalidate():
            self.box.publish(None, 'INVALID')
            return original()
        with patch.object(self.device, 'current_setting', side_effect=invalidate):
            self.assertFalse(self.c.arm())
        self.assertNotIn('input_True', [x[0] for x in self.device.commands])

    def test_inflight_expiry_is_detected_after_io(self):
        self.arm()
        self.device.delay_s = .14
        self.tick(-2.)
        self.assertEqual(self.c.state, 'FAULT')
        self.assertIn('EXPIRED', self.c.fault)
        self.assertFalse(self.device.enabled)

    def test_wrong_instrument_never_receives_settings_or_on(self):
        self.setUp()
        device = MockLiveLoad(self.config, self.clock, self.clock.sleep)
        c = LiveController(device, self.box, self.config, self.clock, self.clock.sleep)
        with patch.object(device, 'identify', return_value={'model': 'UNKNOWN'}): c.initialize()
        self.assertEqual(c.fault, 'WRONG_INSTRUMENT')
        self.assertEqual(device.commands, [])

    def test_orderly_close_during_cycle_is_not_a_spurious_estop(self):
        self.arm(); self.c.closing = True; self.c.abort.set()
        self.c.cycle()
        self.assertEqual(self.c.state, 'DISARMED')
        self.assertEqual(self.c.fault, '')
        self.assertTrue(self.c.shutdown['verified'])

    def test_cycle_overrun_fault_is_visible(self):
        self.arm(); self.c.config = replace(self.config, max_cycle_s=.05)
        self.tick(-.1)
        self.assertEqual(self.c.fault, 'CONTROL_CYCLE_OVERRUN')
        self.assertTrue(self.c.shutdown['verified'])

    def test_nan_measurement_and_non_cc_mode_trip(self):
        for changes in (dict(voltage_V=float('nan')), dict(status=128)):
            self.setUp(); self.arm()
            actual = self.device.measure
            with patch.object(self.device, 'measure', side_effect=lambda: dict(actual(), **changes)):
                self.tick(-.1)
            self.assertEqual(self.c.state, 'FAULT')
            self.assertFalse(self.device.enabled)

    def test_load_protection_must_match_verified_envelope_before_arm(self):
        d = MockLiveLoad(self.config, self.clock, self.clock.sleep)
        c = LiveController(d, self.box, self.config, self.clock, self.clock.sleep)
        with patch.object(d, 'protection_limits', return_value=dict(voltage_V=120., current_A=30., power_W=300.)):
            c.initialize()
        self.assertEqual(c.state, 'FAULT')
        self.assertFalse(d.enabled)
        self.assertNotIn('input_True', [x[0] for x in d.commands])

    def test_arm_rechecks_function_and_changed_protection_before_on(self):
        self.box.publish(row(self.clock))
        self.device.commands.clear()
        with patch.object(self.device, 'protection_limits', return_value=dict(voltage_V=120., current_A=30., power_W=300.)):
            self.assertFalse(self.c.arm())
        self.assertEqual(self.c.state, 'FAULT')
        calls = [x[0] for x in self.device.commands]
        self.assertIn('fixed_cc', calls)
        self.assertNotIn('input_True', calls)

    def test_latest_sample_is_selected_after_slow_voltage_check(self):
        self.arm(); self.device.delay_s = .064
        original = self.device.measure
        first = True
        def slow_voltage():
            nonlocal first
            if first:
                first = False
                self.clock.sleep(.2)
                self.box.publish(row(self.clock, -.5, seq=42))
            return original()
        with patch.object(self.device, 'measure', side_effect=slow_voltage): self.tick(-.5)
        self.assertEqual(self.c.state, 'RUNNING', self.c.fault)
        self.assertEqual(self.c.last['source_sequence'], 42)
        self.assertLess(self.c.last['command_age_s'], self.config.expiry_s)
        self.assertGreater(self.c.last['cycle_ms'], 500.)

    def test_refresh_cannot_erase_an_invalid_epoch(self):
        self.arm()
        original = self.c.fresh
        snapshots = 0
        def interrupted(demand=None, revision=None):
            nonlocal snapshots
            if demand is None:
                snapshots += 1
                if snapshots == 2:
                    self.box.publish(None, 'INVALID')
                    self.box.publish(row(self.clock, -.5, seq=99))
            return original(demand, revision)
        with patch.object(self.c, 'fresh', side_effect=interrupted): self.tick(-.5)
        self.assertEqual(self.c.fault, 'DEMAND_INVALIDATED_OR_EXPIRED_DURING_IO')
        self.assertFalse(self.device.enabled)


class ConfigurationAndProtocolTests(unittest.TestCase):
    def test_legacy_replay_cap_preserved_and_explicit_live_cap(self):
        link = Transport(packet(0x12, b'\x80'))
        with self.assertRaises(ValueError): BK8500(link).set_current(3.)
        BK8500(link, max_setpoint_A=3.).set_current(3.)
        self.assertEqual(link.sent[-1], packet(0x2A, (30000).to_bytes(4, 'little')))
        with self.assertRaises(ValueError): BK8500(link, max_setpoint_A=3.).set_current(3.0001)

    def test_protection_limit_command_units(self):
        class LimitsTransport(Transport):
            def write(self, data):
                n = {0x23: 5500, 0x25: 30000, 0x27: 18000}[data[2]]
                self.reply = packet(data[2], n.to_bytes(4, 'little'))
                return super().write(data)
        self.assertEqual(BK8500(LimitsTransport(b'')).protection_limits(),
                         dict(voltage_V=5.5, current_A=3., power_W=18.))

    def test_approval_missing_or_inconsistent_blocks_hardware(self):
        profile = approval(); validate_approval(profile, LiveConfig())
        for field, value in (('supervised_lab_approval', False), ('no_battery', False),
                             ('approved_current_A', 2.), ('psu_channel_power_rating_W', 10.),
                             ('psu_output', 'CH3_fixed')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_approval(dict(profile, **{field: value}), LiveConfig())
        template = json.loads(Path(__file__).with_name('approval.example.json').read_text())
        with self.assertRaises(ValueError): validate_approval(template, LiveConfig())

    def test_hardware_auto_arm_and_incomplete_approval_rejected_before_serial(self):
        for argv in (['--device', 'hardware', '--auto-arm-mock'],
                     ['--device', 'hardware', '--port', 'COM10'],
                     ['--device', 'hardware', '--no-console'],
                     ['--device', 'mock', '--port', 'COM10']):
            with self.subTest(argv=argv), patch.dict(sys.modules, {'serial': None}), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse_args(argv)

    def test_config_limits_and_fixed_mapping(self):
        for options in (dict(max_current_A=3.1), dict(control_hz=10),
                        dict(reference_current_A=float('nan')), dict(io_timeout_s=.6)):
            with self.assertRaises(ValueError): LiveConfig(**options)
        c = LiveConfig(reference_current_A=.05)
        self.assertEqual(c.map_current(-.05), (3., 3.))

    def test_valid_profile_still_cannot_enable_hardware_from_a_pipe(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'approval.json'
            path.write_text(json.dumps(approval()))
            with patch('sys.stdin.isatty', return_value=False), \
                 patch.dict(sys.modules, {'serial': None}), \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['--device', 'hardware', '--port', 'COM10', '--approval', str(path)])


class WorkerTests(unittest.TestCase):
    def test_lost_console_requests_stop(self):
        import threading
        from unittest.mock import Mock
        service = Mock(); quit_event = threading.Event()
        with patch('builtins.input', side_effect=EOFError), contextlib.redirect_stdout(io.StringIO()):
            console(service, quit_event, 'ARM APPROVAL')
        service.request.assert_called_once_with('stop')
        self.assertTrue(quit_event.is_set())

    def test_latest_mailbox_no_queue_and_fast_loss_supervision(self):
        with tempfile.TemporaryDirectory() as folder:
            config = LiveConfig()
            d = MockLiveLoad(config)
            s = LiveService(d, config, Path(folder)/'service'); s.start()
            try:
                deadline = time.perf_counter()+2
                while s.controller.state == 'DISARMED' and time.perf_counter() < deadline: time.sleep(.01)
                for n in range(1000): s.demands.publish(row(time.perf_counter, -.1, seq=n))
                self.assertEqual(s.demands.snapshot()[0].sequence, 999)
                s.request('arm')
                deadline = time.perf_counter()+2
                while s.controller.state != 'RUNNING' and time.perf_counter() < deadline: time.sleep(.01)
                self.assertEqual(s.controller.state, 'RUNNING')
                lost = time.perf_counter(); s.demands.publish(None, 'STALE_TELEMETRY')
                while s.controller.state != 'FAULT' and time.perf_counter()-lost < 1: time.sleep(.01)
                self.assertEqual(s.controller.state, 'FAULT')
                self.assertLess(time.perf_counter()-lost, .5)
            finally: report = s.close()
            self.assertTrue(report['shutdown_verified'])
            self.assertFalse(d.enabled)

    def test_new_receiver_to_mock_load_uses_actual_scaling(self):
        # Exercise the existing UDP receiver, new worker, and real command mapping.
        from torcs_live import LiveReceiver
        from test_torcs_live import packet
        with tempfile.TemporaryDirectory() as folder:
            s = LiveService(MockLiveLoad(LiveConfig()), LiveConfig(), Path(folder)/'load')
            r = LiveReceiver(0, Path(folder)/'telemetry', demand_sink=s.demands)
            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            r.start(); s.start()
            try:
                started = time.perf_counter()
                for n in range(110):
                    frame = packet(r.processor, t=n*.02, seq=n, power=100000)
                    frame['sender_qpc_s'] = time.perf_counter()
                    sender.sendto(json.dumps(frame).encode(), ('127.0.0.1', r.port))
                    if s.controller.state == 'READY' and s.demands.snapshot()[0]: s.request('arm')
                    time.sleep(.02)
                self.assertEqual(s.controller.state, 'RUNNING', s.controller.fault)
                self.assertAlmostEqual(s.controller.last['original_cell_current_A'], -.42)
                self.assertAlmostEqual(s.controller.last['limited_load_target_A'], .63)
                self.assertLess(time.perf_counter()-started, 5.)
            finally:
                summary = s.close()
                # The standalone replay's dependency set need not contain plot
                # libraries just to exercise this UDP/controller unit test.
                with patch('torcs_live.write_report', return_value={}): r.close()
                sender.close()
            self.assertTrue(summary['passed'], summary)


if __name__ == '__main__': unittest.main()
