import json
import unittest
from unittest.mock import Mock,patch
from pathlib import Path
import tempfile
from vehicle_power_limit import DemoPolicy,PowerFeedback


class VehiclePowerTests(unittest.TestCase):
    def test_demo_soc_policy_and_fixed_fractions(self):
        for soc,expected in ((0,.2),(.1,.2),(.175,.5),(.225,.7),(.3,1.),(.8,1.)):
            self.assertAlmostEqual(DemoPolicy().evaluate(soc)[1],expected)
        self.assertEqual(DemoPolicy(demo_soc=.175).evaluate(.8)[1],.5)
        for f in (1.,.7,.5,.2,0.):self.assertEqual(DemoPolicy(fixed_fraction=f).evaluate(.8)[1],f)

    def test_invalid_policy_values(self):
        for value in (float('nan'),float('inf'),-.1,1.1,True):
            with self.assertRaises(ValueError):DemoPolicy(fixed_fraction=value)
        with self.assertRaises(ValueError):DemoPolicy(low_soc=.5,full_soc=.2)
        with self.assertRaises(ValueError):DemoPolicy().evaluate(float('nan'))

    def sample(self,bridge,ack=None,session='race',available=True):
        row=dict(session_id=session,soc=.8,target_available=available,received_qpc_s=10.)
        ack=ack or dict(enabled=True,state='ACTIVE',commanded=.7,applied=.7,sequence=0)
        sock=Mock();bridge.handle(row,json.dumps(dict(power_limit=ack)).encode(),('127.0.0.1',1234),sock)
        return row,sock

    def test_reset_is_explicit_single_shot_and_faults_do_not_auto_reset(self):
        b=PowerFeedback(DemoPolicy(fixed_fraction=.7),clock=lambda:10.)
        r,s=self.sample(b);self.assertTrue(r['vehicle_limit_reset_sent'])
        r,s=self.sample(b);self.assertFalse(r['vehicle_limit_reset_sent'])
        r,s=self.sample(b,dict(enabled=True,state='FAULT_STALE',commanded=.7,applied=0,sequence=1))
        self.assertFalse(r['vehicle_limit_reset_sent']);self.assertEqual(r['vehicle_limit_applied_fraction'],0)
        b.request_reset();r,s=self.sample(b);self.assertTrue(r['vehicle_limit_reset_sent'])
        self.assertTrue(s.sendto.call_args.args[0].startswith(b'APS380POWER1 race'))

    def test_invalid_ack_is_fatal_until_trial_restart(self):
        b=PowerFeedback();self.sample(b)
        r,s=self.sample(b,dict(enabled=True,state='ACTIVE',commanded=.7,applied=2,sequence=0))
        self.assertTrue(b.error);s.sendto.assert_not_called()
        self.assertTrue(b.fatal.is_set())
        r,s=self.sample(b);s.sendto.assert_not_called()
        b.request_reset();r,s=self.sample(b);s.sendto.assert_not_called()
        self.assertEqual(r['vehicle_limit_requested_fraction'],0.)
        b.request_stop();r,s=self.sample(b);s.sendto.assert_called_once()
        self.assertEqual(float(s.sendto.call_args.args[0].split()[4]),0.)

    def test_missing_native_support_and_new_session_are_visible(self):
        b=PowerFeedback();sock=Mock();r=dict(session_id='race',soc=.8,target_available=True)
        b.handle(r,b'{}',('127.0.0.1',1),sock)
        self.assertEqual(r['vehicle_limit_state'],'UNAVAILABLE');sock.sendto.assert_not_called()
        self.assertTrue(b.fatal.is_set())
        b=PowerFeedback();self.sample(b)
        r,s=self.sample(b,session='new');self.assertIn('explicit RESET',b.error);s.sendto.assert_not_called()

    def test_gap_pause_and_shutdown(self):
        b=PowerFeedback();r,s=self.sample(b,available=False);s.sendto.assert_not_called()
        b.paused.set();r,s=self.sample(b);s.sendto.assert_not_called()
        b.paused.clear();b.request_stop();r,s=self.sample(b)
        self.assertEqual(r['vehicle_limit_requested_fraction'],0);self.assertFalse(r['vehicle_limit_reset_sent'])
        self.assertFalse(b.stop_verified.is_set())
        self.sample(b,dict(enabled=True,state='ACTIVE',commanded=0,applied=0,sequence=2))
        self.assertTrue(b.stop_verified.is_set())

    def test_feedback_send_failure_is_visible_and_stops_retrying(self):
        b=PowerFeedback();b.reset.clear()
        sock=Mock();sock.sendto.side_effect=OSError('fake network failure')
        row=dict(session_id='race',soc=.8,target_available=True)
        payload=json.dumps(dict(power_limit=dict(enabled=True,state='ACTIVE',commanded=1.,applied=1.,sequence=1))).encode()
        b.handle(row,payload,('127.0.0.1',1),sock)
        self.assertIn('send failed',b.error)
        _,s=self.sample(b);s.sendto.assert_not_called()

    def test_shutdown_requires_ack_of_the_zero_request_not_an_old_zero(self):
        b=PowerFeedback();b.request_stop()
        ack=dict(enabled=True,state='WAITING',commanded=0,applied=0,sequence=-1)
        self.sample(b,ack);self.assertFalse(b.stop_verified.is_set())
        self.sample(b,ack);self.assertFalse(b.stop_verified.is_set())
        ack['sequence']=b.stop_sequence
        self.sample(b,ack);self.assertTrue(b.stop_verified.is_set())

    def test_original_dashboard_displays_requested_and_native_applied_fractions(self):
        import tkinter as tk
        from live_display import LiveDisplay
        from torcs_live import LiveReceiver
        try:
            r=tk.Tk();r.withdraw();r.destroy()
        except tk.TclError as exc:self.skipTest(str(exc))
        b=PowerFeedback(DemoPolicy(fixed_fraction=.7));row,_=self.sample(b)
        row['received_qpc_s']=__import__('time').perf_counter()
        with tempfile.TemporaryDirectory() as folder:
            receiver=LiveReceiver(0,Path(folder)/'telemetry',power_feedback=b)
            try:
                d=LiveDisplay(receiver,finished=lambda:True);d.root.withdraw()
                d.refresh();self.assertIn('applied 70%',d.values.cget('text'))
                self.assertIn('Python requested 70%',d.values.cget('text'))
                d.root.destroy()
            finally:
                with patch('torcs_live.write_report',return_value={}):receiver.close()


if __name__=='__main__':unittest.main()
