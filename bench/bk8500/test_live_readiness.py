"""Low-current commissioning regressions; mocks/fake transports only."""
import contextlib
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

if sys.version_info < (3, 10):
    raise unittest.SkipTest('Live control requires Python 3.10+')

from instrument import BK8500, ProtocolError, packet
from live_control import LiveConfig, LiveController, LatestDemand, MockLiveLoad, LiveService
from live_torcs import artifacts, close_receiver, main, parse_args, prepare_launch_profile
from test_bench import Transport
from test_live_control import Clock, approval, row


def low_config():
    return LiveConfig(max_current_A=.1, reference_current_A=.05, max_power_W=.6,
                      slew_A_per_s=.02, tracking_tolerance_A=.01)


class LowCurrentTests(unittest.TestCase):
    def controller(self):
        clock=Clock(); config=low_config()
        # Fast preflight needs only one sample in this synchronous unit fixture.
        # Runtime exchanges then use the observed ~64 ms acknowledgement delay.
        device=MockLiveLoad(config,clock,clock.sleep,delay_s=.01)
        box=LatestDemand(); c=LiveController(device,box,config,clock,clock.sleep)
        c.initialize();box.publish(row(clock, -.05));self.assertTrue(c.arm(),c.fault)
        device.delay_s=.064
        return clock,device,box,c

    def test_low_range_scales_before_clipping_and_preserves_default_three_amp_mapping(self):
        c=low_config()
        for requested,target in ((-.025,.05),(-.05,.1),(-.1,.1),(0,0),(.05,0)):
            self.assertAlmostEqual(c.map_current(requested)[1],target)
        self.assertEqual(LiveConfig().map_current(-2.),(3.,3.))

    def test_ack_readback_measurement_and_timestamps_at_low_current(self):
        clock,device,box,c=self.controller()
        for _ in range(7):
            clock.sleep(.6);box.publish(row(clock,-.05));c.cycle()
            self.assertEqual(c.state,'RUNNING',c.fault)
            self.assertLessEqual(c.last['commanded_load_A'],.1)
        e=c.last
        self.assertTrue(e['command_acknowledged'])
        self.assertAlmostEqual(e['commanded_load_A'],.1)
        self.assertAlmostEqual(e['readback_setting_A'],.1)
        self.assertLess(abs(e['tracking_error_A']),.01)
        keys=('source_received_s','command_started_host_s','command_ack_received_host_s',
              'setpoint_read_received_host_s','measurement_received_host_s')
        self.assertEqual([e[k] for k in keys],sorted(e[k] for k in keys))
        for _ in range(7):
            clock.sleep(.6);box.publish(row(clock,.03));c.cycle()
        self.assertEqual(c.applied,0.)
        self.assertTrue(c.last['regen_suppressed'])
        c.stop();self.assertTrue(c.shutdown['verified']);self.assertFalse(device.enabled)

    def test_real_driver_rejected_ack_trips_live_controller(self):
        clock,device,box,c=self.controller()
        driver=BK8500(Transport(packet(0x12,b'\xC0')))
        device.set_current=driver.set_current
        c.cycle()
        self.assertEqual(c.state,'FAULT')
        self.assertIn('rejected',c.fault)
        self.assertFalse(c.last['command_acknowledged'])
        # The link also refuses the shutdown zero command; OFF remains verifiable
        # at the already-zero mock setting, with the rejected command reported.
        self.assertFalse(device.enabled)
        self.assertTrue(c.shutdown['errors'])

    def test_low_range_telemetry_loss_and_transport_failure_are_distinct(self):
        clock,device,box,c=self.controller()
        clock.sleep(.6);c.cycle()
        self.assertEqual(c.fault,'TELEMETRY_EXPIRED')
        self.assertTrue(c.shutdown['verified'])
        clock,device,box,c=self.controller()
        device.failure='timeout';c.cycle()
        self.assertEqual(c.state,'FAULT')
        self.assertFalse(c.shutdown['verified'])

    def test_protection_mismatch_keeps_input_off_and_retains_observed_limits(self):
        clock=Clock();config=low_config();device=MockLiveLoad(config,clock,clock.sleep)
        device.protection_limits=lambda:dict(voltage_V=5.5,current_A=1.,power_W=.6)
        c=LiveController(device,LatestDemand(),config,clock,clock.sleep);c.initialize()
        self.assertEqual(c.state,'FAULT')
        self.assertIn('read 1.0, required 0.1',c.fault)
        self.assertEqual(c.observed_limits['current_A'],1.)
        self.assertFalse(device.enabled)
        self.assertNotIn('input_True',[e[0] for e in device.commands])

    def test_csv_keeps_ack_source_and_measurement_times(self):
        clock,device,box,c=self.controller();c.cycle()
        with tempfile.TemporaryDirectory() as folder:
            service=LiveService(device,low_config(),Path(folder)/'service')
            service.controller=c;service.record('cycle');service.log.close()
            mpl=Mock();plt=Mock();mpl.pyplot=plt
            plt.subplots.return_value=(Mock(),[Mock(),Mock(),Mock()])
            with patch.dict(sys.modules,{'matplotlib':mpl,'matplotlib.pyplot':plt}):
                artifacts(Path(folder),service)
            with (Path(folder)/'load_tracking.csv').open() as f: rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['command_acknowledged'],'True')
            self.assertTrue(rows[0]['recorded_utc'].endswith('+00:00'))
            self.assertTrue(rows[0]['source_received_s'])
            self.assertTrue(rows[0]['measurement_received_host_s'])
        c.stop()


class LaunchAndReportingTests(unittest.TestCase):
    def test_g29_and_ai_use_saved_profile_without_writing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);saved=root/'.local/tesla-profile'
            for name in ('drivers/human/human.xml','drivers/human/preferences.xml','config/raceman/practice.xml'):
                p=saved/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'untouched G29')
            before={str(p):p.read_bytes() for p in saved.rglob('*') if p.is_file()}
            with patch('live_torcs.ROOT',root),patch('live_torcs.prepare_profile') as prepare:
                self.assertEqual(prepare_launch_profile('g29'),saved)
                prepare.assert_not_called()
                prepare_launch_profile('ai')
                prepare.assert_called_once_with(root/'.local/tesla-bk8500-ai-profile',manual_profile=saved)
            self.assertEqual(before,{str(p):p.read_bytes() for p in saved.rglob('*') if p.is_file()})

    def test_keyboard_uses_its_existing_separate_preparation(self):
        import live_torcs
        with patch('configure_keyboard.prepare_keyboard',return_value=Path('keyboard-only')) as prepare:
            self.assertEqual(prepare_launch_profile('keyboard'),Path('keyboard-only'))
            prepare.assert_called_once_with()

    def test_explicit_keyboard_presets_and_analog_mode_isolation(self):
        from configure_keyboard import keyboard_config
        for name in ('5s','3s','8s'):
            with patch('configure_keyboard.prepare_keyboard',return_value=Path('keyboard-only')) as prepare:
                self.assertEqual(prepare_launch_profile('keyboard',name),Path('keyboard-only'))
                prepare.assert_called_once_with(keyboard_config(name))
            args=parse_args(['--device','mock','--torcs','keyboard','--keyboard-profile',name,
                             '--slew-A-per-s','.02'])
            self.assertEqual(args.keyboard_profile,name)
            self.assertEqual(args.config.slew_A_per_s,.02)
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            parse_args(['--torcs','g29','--keyboard-profile','5s'])

    def test_hardware_higher_current_rejected_without_importing_serial(self):
        with patch.dict(sys.modules,{'serial':None}),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            parse_args(['--device','hardware','--max-current-A','.1001'])

    def test_hardware_8s_selection_preserves_limits_without_serial_access(self):
        profile=approval()
        profile.update(extended_psu_only_commissioning_approved=True,
            approved_load_max_voltage_V=110., approved_load_max_current_A=12.,
            approved_load_max_power_W=305.)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test-only-approval.json'
            path.write_text(json.dumps(profile))
            argv=['--device','hardware','--torcs','keyboard','--keyboard-profile','8s',
                  '--port','TEST_ONLY','--approval',str(path),'--extended-psu-only',
                  '--max-current-A','1','--reference-current-A','2','--max-power-W','5.5',
                  '--slew-A-per-s','.02','--tracking-tolerance-A','.01','--control-hz','1',
                  '--protection-voltage-ceiling-V','110','--protection-current-ceiling-A','12',
                  '--protection-power-ceiling-W','305']
            with patch.dict(sys.modules,{'serial':None}),patch('sys.stdin.isatty',return_value=True):
                args=parse_args(argv)
            self.assertEqual(args.keyboard_profile,'8s')
            self.assertEqual(args.config.max_current_A,1.)
            self.assertEqual(args.config.max_power_W,5.5)
            self.assertEqual(args.config.slew_A_per_s,.02)
            self.assertEqual(args.config.protection_envelope,(110.,12.,305.))
            self.assertFalse(args.auto_arm_mock)
            with patch.dict(sys.modules,{'serial':None}),patch('sys.stdin.isatty',return_value=False), \
                    contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                parse_args(argv)

    def test_low_hardware_profile_requires_interactive_supervision_and_no_automation(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test-approval.json';p.write_text(json.dumps(approval()))
            args=['--device','hardware','--max-current-A','.1','--port','TEST_ONLY',
                  '--approval',str(p),'--tracking-tolerance-A','.01']
            with patch.dict(sys.modules,{'serial':None}),patch('sys.stdin.isatty',return_value=True):
                result=parse_args(args);self.assertEqual(result.config.max_current_A,.1)
                self.assertEqual(result.config.tracking_tolerance_A,.01)
            for extra in ([],['--auto-arm-mock'],['--no-console']):
                with self.subTest(extra=extra),patch('sys.stdin.isatty',return_value=False),\
                    contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                    parse_args(args+extra)

    def test_plotting_failure_still_saves_trial_and_verified_shutdown(self):
        from torcs_live import LiveReceiver
        original=LiveReceiver.close
        def failed_plot(receiver):
            original(receiver)
            raise RuntimeError('SIMULATED_PLOT_SAVE_FAILURE')
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'trial'
            with patch('live_torcs.write_manifest'),patch.object(LiveReceiver,'close',failed_plot),\
                contextlib.redirect_stdout(io.StringIO()):
                result=main(['--torcs','listen','--device','mock','--duration','.2',
                    '--telemetry-port','0','--no-console','--mock-transaction-delay-s','0',
                    '--max-current-A','.1','--output',str(output)])
            trial=json.loads((output/'trial.json').read_text())
            self.assertEqual(result,1)
            self.assertEqual(trial['acceptance']['artifacts'],'FAIL')
            self.assertIn('SIMULATED_PLOT_SAVE_FAILURE',trial['artifact_error'])
            self.assertTrue(trial['instrument']['shutdown_verified'])
            self.assertFalse(trial['hardware_commands_may_have_been_sent'])

    def test_receiver_failure_without_partial_report_is_visible(self):
        receiver=Mock();receiver.close.side_effect=RuntimeError('no report')
        with tempfile.TemporaryDirectory() as folder:
            timing,error=close_receiver(receiver,Path(folder))
        self.assertIsNone(timing);self.assertIn('no report',error)


if __name__=='__main__':unittest.main()
