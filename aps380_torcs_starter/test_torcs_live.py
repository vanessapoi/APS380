import csv
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from torcs_live import BASE,CSV_FIELDS,LiveProcessor,LiveReceiver,replay_native

PROFILE=(BASE/'profiles/tesla_model3_rwd.json').read_bytes()
CONFIG=json.loads((BASE/'profiles/live_scaling_demo.json').read_text())


def packet(processor,t=0,seq=0,session='test-session',power=300,**updates):
    energy=power*t/3600
    row=dict.fromkeys(CSV_FIELDS,0.)
    row.update(time_s=t,car_id=processor.profile['car_id'],profile_id=processor.identity,
               pack_power_W=power,pack_voltage_V=355,pack_current_A=power/355,
               pack_energy_Wh=40000-energy,soc=(40000-energy)/50000,
               discharge_Wh=max(energy,0),charge_Wh=max(-energy,0))
    row.update(updates)
    stream=io.StringIO();csv.writer(stream).writerow([row[k] for k in CSV_FIELDS])
    return dict(version=1,session_id=session,sequence=seq,sender_qpc_s=10+t,
                send_errors=0,event='sample',csv=stream.getvalue().strip())


def accept(processor,frame,offset=.001):
    return processor.accept(json.dumps(frame).encode(),frame['sender_qpc_s']+offset)


class LiveProcessorTest(unittest.TestCase):
    def setUp(self):self.p=LiveProcessor(PROFILE,CONFIG,True)

    def test_native_power_fixed_scale_and_packet_loss(self):
        result=accept(self.p,packet(self.p,power=100000))
        self.assertAlmostEqual(result['cell_current_unclamped_A'],.42)
        self.assertEqual(self.p.cell.equivalent_pack_energy_Wh,50000)
        accept(self.p,packet(self.p,t=.04,seq=2,power=100000))
        self.assertEqual(self.p.stats['missing'],1)
        self.assertEqual(self.p.cell.experiment_scale,.06)

    def test_independent_charge_discharge_and_clipping(self):
        for power in (100000,-100000,1e6):
            p=LiveProcessor(PROFILE,CONFIG)
            result=accept(p,packet(p,power=power))
            self.assertAlmostEqual(result['cell_current_unclamped_A'],power*.0000042)
            self.assertTrue(-1<=result['cell_current_command_A']<=1)

    def test_no_speed_based_power_or_automatic_normalization(self):
        with patch('cell_scaling.auto_scale_profile',side_effect=AssertionError('offline only')):
            first=accept(self.p,packet(self.p,power=100000))
            second=accept(self.p,packet(self.p,t=.02,seq=1,power=100000,speed_mps=100))
        self.assertEqual(first['cell_current_unclamped_A'],second['cell_current_unclamped_A'])

    def test_invalid_packets_do_not_advance_sample_state(self):
        accept(self.p,packet(self.p))
        previous=self.p.previous
        bad=[dict(packet(self.p,.02,1),version=True),dict(packet(self.p,.02,1),version=2),
             packet(self.p,.02,1,profile_id='wrong'),packet(self.p,.02,1,pack_current_A=99),
             packet(self.p,.02,1,pack_power_W=float('nan')),packet(self.p,.02,1,time_s=True),
             dict(packet(self.p,.02,1),sequence=True),dict(packet(self.p,.02,1),send_errors=-1)]
        for frame in bad:
            with self.assertRaises(ValueError):accept(self.p,frame)
            self.assertIs(self.p.previous,previous)
            self.assertEqual(self.p.sequence,0)
        for payload in (b'[]',b'null',b'bad',b' '*4097):
            with self.assertRaises(ValueError):self.p.accept(payload,10.1)

    def test_delayed_and_future_packets(self):
        for age in (.3,-.1):
            with self.assertRaises(ValueError):accept(self.p,packet(self.p),age)

    def test_reordering_and_retired_session(self):
        accept(self.p,packet(self.p))
        with self.assertRaises(ValueError):accept(self.p,packet(self.p))
        accept(self.p,packet(self.p,session='new'))
        with self.assertRaises(ValueError):accept(self.p,packet(self.p,.02,1))
        self.assertEqual(self.p.stats['sessions'],2)

    def test_staleness_and_recovery(self):
        accept(self.p,packet(self.p))
        self.assertTrue(self.p.state(11).startswith('STALE'))
        accept(self.p,packet(self.p,.02,1))
        self.assertEqual(self.p.state(10.03),'RECEIVING')

    def test_gap_has_no_target_then_explicit_rebaseline_recovers(self):
        accept(self.p,packet(self.p))
        result=accept(self.p,packet(self.p,1,50))
        self.assertFalse(result['target_available']);self.assertIsNone(self.p.current)
        self.assertEqual(self.p.stats['gaps'],1)
        accept(self.p,packet(self.p,1.02,51))
        self.assertEqual(self.p.status,'RECEIVING')

    def test_ended_and_session_restart(self):
        accept(self.p,packet(self.p))
        event=dict(packet(self.p,.02,1),event='ended',csv='')
        self.assertIsNone(accept(self.p,event));self.assertEqual(self.p.state(100),'ENDED')
        with self.assertRaises(ValueError):accept(self.p,packet(self.p,.04,2))
        accept(self.p,packet(self.p,session='restart'))
        self.assertEqual(self.p.status,'RECEIVING')

    def test_energy_reset_and_overflow(self):
        accept(self.p,packet(self.p,.02))
        for frame in (packet(self.p,.04,1,discharge_Wh=0),
                      packet(self.p,.04,1,motor_radps=1e308,motor_torque_Nm=1e308)):
            with self.assertRaises(ValueError):accept(self.p,frame)

    def test_config_does_not_allow_hardware_mode(self):
        with self.assertRaises(ValueError):LiveProcessor(PROFILE,dict(CONFIG,mode='hardware'))
        with self.assertRaises(ValueError):LiveProcessor(PROFILE,dict(CONFIG,max_sim_gap_s=float('nan')))


class LiveLoopbackTest(unittest.TestCase):
    def test_windows_udp_reset_is_expected_only_after_explicit_shutdown(self):
        for expected in (False,True):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder:
                r=LiveReceiver(0,Path(folder)/'trial')
                r.socket.close()
                r.socket=Mock()
                r.socket.recvfrom.side_effect=ConnectionResetError(10054,'UDP peer reset')
                r.processor.last_receive=time.perf_counter()-10
                r.demand_sink=Mock()
                if expected:r.begin_shutdown()
                r._receive()
                r.close()
                events=[json.loads(line) for line in (r.output/'received.jsonl').read_text().splitlines()]
                report=json.loads((r.output/'timing_report.json').read_text())
                if expected:
                    self.assertIsNone(r.failed)
                    self.assertEqual(report['expected_shutdown_resets'],1)
                    self.assertTrue(any(e['kind']=='expected_shutdown_reset' for e in events))
                    self.assertEqual(report['final_state'],'STOPPED')
                else:
                    self.assertIn('10054',r.failed)
                    self.assertEqual(report['final_state'],'RECEIVER_ERROR')
                    self.assertTrue(any(e['kind']=='receiver_error' for e in events))
                    r.demand_sink.publish.assert_any_call(None,'RECEIVER_ERROR')

    def test_other_udp_errors_are_not_hidden_during_shutdown(self):
        with tempfile.TemporaryDirectory() as folder:
            r=LiveReceiver(0,Path(folder)/'trial')
            r.socket.close();r.socket=Mock()
            r.socket.recvfrom.side_effect=OSError(10051,'network unreachable')
            r.begin_shutdown();r._receive();r.close()
            self.assertIn('10051',r.failed)
            self.assertEqual(r.processor.state(),'RECEIVER_ERROR')

    def test_frozen_native_replay_matches_independent_current_equation(self):
        folder=BASE/'data/tesla_drive_04'
        rows,summary=replay_native(folder/'drive.csv',folder/'vehicle_profile.json')
        self.assertEqual(len(rows),4541)
        self.assertFalse(summary['real_time_timing_evidence'])
        for row in rows:
            self.assertAlmostEqual(row['cell_current_unclamped_A'],row['pack_power_W']*.0000042)

    def test_receiver_logs_bad_data_and_valid_data_and_saves_report(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ,{'MPLCONFIGDIR':str(Path(folder)/'mpl')}):
                r=LiveReceiver(0,Path(folder)/'trial');r.processor.shared_clock=False;r.start()
                sender=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                try:
                    sender.sendto(b'[]',('127.0.0.1',r.port))
                    for i in range(2):
                        sender.sendto(json.dumps(packet(r.processor,i*.02,i)).encode(),('127.0.0.1',r.port))
                        time.sleep(.03)
                    deadline=time.perf_counter()+2
                    while r.processor.stats['accepted']<2 and time.perf_counter()<deadline:time.sleep(.01)
                finally:
                    sender.close();report=r.close()
                self.assertEqual(report['samples'],2)
                self.assertEqual(report['statistics']['invalid'],1)
                self.assertFalse(report['hardware_commands_sent'])
                self.assertIsNone(report['receiver_error'])
                self.assertTrue((r.output/'timing_report.md').exists())

    def test_display_refresh_and_stale_target_without_mainloop(self):
        # Windows desktop widget smoke test; does not launch or control TORCS.
        from live_display import LiveDisplay
        with tempfile.TemporaryDirectory() as folder:
            r=LiveReceiver(0,Path(folder)/'ui');r.processor.shared_clock=False
            try:
                r.processor.accept(json.dumps(packet(r.processor)).encode(),time.perf_counter())
                time.sleep(.02)
                r.processor.accept(json.dumps(packet(r.processor,.02,1)).encode(),time.perf_counter())
                import tkinter
                try:ui=LiveDisplay(r,duration=1)
                except tkinter.TclError as error:self.skipTest(f'Desktop Tk unavailable: {error}')
                try:
                    ui.root.withdraw();ui.root.update_idletasks();ui.refresh()
                    self.assertIn('Hz',ui.values.cget('text'))
                    self.assertEqual(ui.state_label.cget('text'),'RECEIVING')
                    r.processor.last_receive=time.perf_counter()-1
                    ui.refresh()
                    self.assertIn('STALE',ui.state_label.cget('text'))
                    self.assertIn('UNAVAILABLE',ui.values.cget('text'))
                finally:ui.root.destroy()
            finally:r.socket.close();r.log.close()


if __name__=='__main__':unittest.main()
