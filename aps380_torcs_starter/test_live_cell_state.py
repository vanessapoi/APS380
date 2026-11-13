from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

from cell_soc import CellMeasurement
from cell_sop import RintParameters, RintPolicy
from live_cell_state import CellSample, LiveCellObserver, MockCellStream, LiveRintPolicy
from test_cell_sop import CELL, PROFILE, parameters, row
from vehicle_power_limit import PowerFeedback, DemoPolicy


class LiveCellTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.
        self.observer = LiveCellObserver(3.5, .8, freshness_s=.2, max_gap_s=.5, clock=lambda:self.now)

    def sample(self, current=0., sequence=0, session='cell', **kw):
        return CellSample(CellMeasurement(session,self.now,3.65,current,25.),sequence,self.now,**kw)

    def pair(self, psu=.3, load=.8, opened=False, state='RUNNING'):
        return dict(state=state, measurements_retained=False,
            isolation=dict(is_open=opened),
            psu=dict(current_A=psu,acquired_s=self.now,status=dict(fault=''),setpoint_A=1.),
            load=dict(current_A=load,acquired_s=self.now,status=dict(fault=''),setpoint_A=2.))

    def test_charging_positive_and_discharging_negative(self):
        for current in (-1., 1.):
            self.setUp()
            self.assertTrue(self.observer.accept(self.sample(current)))
            for seq in range(1,101):
                self.now = 10+seq*.1
                self.assertTrue(self.observer.accept(self.sample(current,seq)))
            self.assertAlmostEqual(self.observer.estimate.soc,.8+current*10/(3600*3.5))
            self.assertAlmostEqual(self.observer.estimate.net_discharged_Ah,-current*10/3600)

    def test_branch_readbacks_not_targets_and_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            stream=MockCellStream(self.observer,Path(d)/'samples.jsonl',voltage_V=3.65,temperature_C=25.,clock=lambda:self.now)
            try:
                stream(self.pair())
                self.assertAlmostEqual(self.observer.sample.measurement.net_cell_current_A,-.5)
                self.now+=.1
                stream(self.pair(opened=True))
                self.assertEqual(self.observer.sample.measurement.net_cell_current_A,0.)
                # End-point average accounts for the imposed linear intersample transition.
                self.assertAlmostEqual(self.observer.estimate.soc,.8-.25*.1/(3600*3.5))
            finally:stream.close()
            lines=[json.loads(x) for x in (Path(d)/'samples.jsonl').read_text().splitlines()]
            self.assertEqual(len(lines),2)
            self.assertEqual(lines[-1]['sample']['temperature_source'],'imposed_mock_temperature')

    def test_sequence_loss_duplicate_reorder_and_session_latch(self):
        for seq,session in ((2,'cell'),(0,'cell'),(1,'other')):
            self.setUp();self.observer.accept(self.sample())
            self.now+=.1
            self.assertFalse(self.observer.accept(self.sample(-1.,seq,session)))
            self.assertEqual(self.observer.counter.soc,.8)
            self.assertEqual(self.observer.snapshot()['state'],'FAULT')
            self.assertFalse(self.observer.accept(self.sample(-1.,1)))

    def test_older_sequence_after_two_accepted_samples(self):
        self.assertTrue(self.observer.accept(self.sample(-1.,0)))
        self.now+=.1
        self.assertTrue(self.observer.accept(self.sample(-1.,1)))
        before=self.observer.counter.soc
        self.now+=.1
        self.assertFalse(self.observer.accept(self.sample(-1.,0)))
        self.assertEqual(self.observer.counter.soc,before)
        self.assertEqual(self.observer.snapshot()['state'],'FAULT')

    def test_stale_future_and_bad_quality_rejected(self):
        for change in (dict(received_s=9.),dict(received_s=11.),dict(quality='real'),dict(source='requested_current'),
                       dict(sequence=True),dict(voltage_source='physical'),dict(isolation_open=True)):
            self.setUp()
            self.assertFalse(self.observer.accept(replace(self.sample(-1.),**change)))
            self.assertIsNone(self.observer.counter)

    def test_gap_clock_reversal_and_expiry_no_bridge(self):
        self.observer.accept(self.sample(-1.))
        self.now+=.6
        self.assertFalse(self.observer.accept(self.sample(-1.,1)))
        self.assertEqual(self.observer.counter.soc,.8)
        self.setUp();self.observer.accept(self.sample(-1.))
        self.now+=.21
        self.assertEqual(self.observer.snapshot()['error'],'CELL_MEASUREMENT_EXPIRED')
        self.now+=.1
        self.assertFalse(self.observer.accept(self.sample(-1.,1)))
        self.setUp();self.observer.accept(self.sample(-1.))
        self.assertFalse(self.observer.accept(self.sample(-1.,1)))

    def test_reset_requires_new_fresh_anchor_and_does_not_fill_gap(self):
        self.observer.accept(self.sample(-1.));old=self.sample(-1.,1)
        self.now+=1.;self.observer.snapshot()
        self.observer.reset(.6)
        self.assertFalse(self.observer.accept(old))
        self.observer.reset(.6)
        self.assertTrue(self.observer.accept(self.sample(1.,100,'new-session')))
        self.assertEqual(self.observer.estimate.soc,.6)
        self.assertEqual(self.observer.estimate.interval_s,0)
        self.assertEqual(self.observer.generation,2)

    def test_soc_boundary_is_visible_and_latched(self):
        for initial,current,bound in ((0.,-1.,0.),(1.,1.,1.)):
            self.setUp();self.observer.reset(initial)
            self.observer.accept(self.sample(current))
            self.now+=.1
            self.assertFalse(self.observer.accept(self.sample(current,1)))
            s=self.observer.snapshot()
            self.assertTrue(s['estimate']['boundary_clipped'])
            self.assertEqual(s['estimate']['soc'],bound)
            self.assertTrue(s['retained'])

    def test_retained_skew_and_stale_branch_are_not_measurements(self):
        for bad in ('retained','skew','stale','fault','negative'):
            self.setUp()
            with tempfile.TemporaryDirectory() as d:
                stream=MockCellStream(self.observer,Path(d)/'m.jsonl',voltage_V=3.65,temperature_C=25.,clock=lambda:self.now)
                try:
                    stream(self.pair());self.now+=.1;p=self.pair()
                    if bad=='retained':p.update(measurements_retained=True,state='FAULT')
                    if bad=='skew':p['psu']['acquired_s']-=.1
                    if bad=='stale':p['psu']['acquired_s']-=.3;p['load']['acquired_s']-=.3
                    if bad=='fault':p['psu']['status']['fault']='COMM_ERROR'
                    if bad=='negative':p['psu']['current_A']=-1
                    stream(p)
                    self.assertEqual(self.observer.accepted,1)
                    self.assertTrue(self.observer.error)
                finally:stream.close()

    def test_cached_readbacks_cannot_refresh_measurement_age(self):
        with tempfile.TemporaryDirectory() as d:
            stream=MockCellStream(self.observer,Path(d)/'m.jsonl',voltage_V=3.65,temperature_C=25.,clock=lambda:self.now)
            try:
                p=self.pair();stream(p);self.now+=.21;stream(p)
                self.assertEqual(self.observer.accepted,1)
                self.assertEqual(self.observer.snapshot()['state'],'FAULT')
            finally:stream.close()

    def test_live_policy_soc_ocv_sop_and_fraction_evolve(self):
        p=LiveRintPolicy(parameters(maximum_discharge_A=.5),.8,25.,self.observer)
        p.configure(CELL,PROFILE)
        self.observer.accept(self.sample(-1.))
        first=p.evaluate_row(row())[2]
        for seq in range(1,101):
            self.now=10+seq*.1;self.observer.accept(self.sample(-1.,seq))
        last=p.evaluate_row(row())[2]
        for key in ('sop_cell_soc_fraction','sop_ocv_candidate_V','sop_max_discharge_W','sop_vehicle_fraction'):
            self.assertLess(last[key],first[key],key)
        self.assertFalse(last['sop_physically_validated'])

    def test_waiting_zero_then_active_and_expiry_requires_reset(self):
        p=LiveRintPolicy(parameters(maximum_discharge_A=.5),.8,25.,self.observer);p.configure(CELL,PROFILE)
        b=PowerFeedback(p,clock=lambda:self.now);sock=Mock()
        payload=json.dumps(dict(power_limit=dict(enabled=True,state='ACTIVE',commanded=0.,applied=0.,sequence=0))).encode()
        b.handle(row(),payload,('127.0.0.1',1),sock)
        self.assertFalse(b.error);self.assertEqual(b.latest['vehicle_limit_requested_fraction'],0)
        self.observer.accept(self.sample(-1.))
        b.handle(row(),payload,('127.0.0.1',1),sock)
        self.assertGreater(b.latest['vehicle_limit_requested_fraction'],0)
        self.now+=.21;b.handle(row(),payload,('127.0.0.1',1),sock)
        writes=sock.sendto.call_count;self.assertTrue(b.error)
        b.request_reset();b.handle(row(),payload,('127.0.0.1',1),sock)
        self.assertEqual(writes,sock.sendto.call_count)
        self.observer.reset(.8);self.observer.accept(self.sample(-1.,2))
        b.handle(row(),payload,('127.0.0.1',1),sock)
        self.assertEqual(writes,sock.sendto.call_count)
        b.request_reset();b.handle(row(),payload,('127.0.0.1',1),sock)
        self.assertGreater(sock.sendto.call_count,writes)

    def test_modes_remain_separate_and_arm_is_explicit(self):
        sys.path.insert(0,str(Path(__file__).parent.parent/'scripts'))
        from run_vehicle_power_limit import parse_args
        base=Path(__file__).parent/'profiles'
        self.assertIsInstance(parse_args([]).policy,DemoPolicy)
        fixed=parse_args(['--policy','rint','--sop-config',str(base/'rint_sop_mock_example.json')])
        self.assertEqual(type(fixed.policy),RintPolicy)
        live=parse_args(['--policy','rint-live-mock','--sop-config',str(base/'rint_sop_live_mock_example.json')])
        self.assertIsInstance(live.policy,LiveRintPolicy);self.assertFalse(live.mock_arm)

    def test_real_mock_coordinator_readbacks_drive_counter_and_fault_latch(self):
        from instrument_control import InstrumentCoordinator, Demand, State
        from mock_instruments import MockPSU, MockBK8500, MockIsolation
        def sleep(dt):self.now+=dt
        options=dict(clock=lambda:self.now,sleep=sleep)
        psu,load=MockPSU(**options),MockBK8500(**options)
        coordinator=InstrumentCoordinator(psu,load,MockIsolation(psu,load),clock=lambda:self.now)
        with tempfile.TemporaryDirectory() as d:
            stream=MockCellStream(self.observer,Path(d)/'m.jsonl',voltage_V=3.65,temperature_C=25.,clock=lambda:self.now)
            def cycles(current,count):
                for i in range(count):
                    self.now+=.1
                    coordinator.step(Demand(current,self.now,'drive',i))
                    stream(coordinator.snapshot())
                    self.assertNotEqual(coordinator.state,State.FAULT,coordinator.fault_reason)
                    if self.observer.sample:
                        expected=0. if coordinator.isolation.is_open else coordinator.last['psu']['current_A']-coordinator.last['load']['current_A']
                        self.assertAlmostEqual(self.observer.sample.measurement.net_cell_current_A,expected)
                    self.assertFalse(self.observer.error)
            try:
                coordinator.arm();cycles(-.2,100)
                discharged=self.observer.estimate.soc
                self.assertLess(discharged,.8)
                cycles(.2,150)
                self.assertGreater(self.observer.estimate.soc,discharged)
                self.assertEqual(coordinator.state,State.RUNNING)
                load.failure='communication';self.now+=.1
                coordinator.step(Demand(.2,self.now,'drive',300));stream(coordinator.snapshot())
                self.assertEqual(coordinator.state,State.FAULT)
                self.assertTrue(coordinator.shutdown_verified)
                self.assertEqual(self.observer.snapshot()['state'],'FAULT')
            finally:stream.close();coordinator.disarm()

    def test_invalid_observer_parameters(self):
        for args,kw in (((0,.8),{}),((3.5,80),{}),((3.5,.8),dict(freshness_s=0)),((3.5,.8),dict(max_gap_s=float('nan')))):
            with self.assertRaises(ValueError):LiveCellObserver(*args,**kw)

    def test_fault_notifies_mock_stop_once_per_generation(self):
        p=LiveRintPolicy(parameters(),.8,25.,self.observer);p.configure(CELL,PROFILE)
        p.on_fault=Mock()
        p.evaluate_row(row());p.on_fault.assert_not_called()
        self.observer.unavailable('TEST_LOSS')
        p.evaluate_row(row());p.evaluate_row(row());self.assertEqual(p.on_fault.call_count,1)
        self.observer.reset(.8);self.observer.unavailable('SECOND_LOSS')
        p.evaluate_row(row());self.assertEqual(p.on_fault.call_count,2)

    def test_combined_dashboard_displays_counted_mock_soc_and_quality(self):
        import tkinter as tk
        from unittest.mock import patch
        from live_display import LiveDisplay
        from torcs_live import LiveReceiver
        try:
            root=tk.Tk();root.withdraw();root.destroy()
        except tk.TclError as exc:self.skipTest(str(exc))
        p=LiveRintPolicy(parameters(),.8,25.,self.observer);p.configure(CELL,PROFILE)
        self.observer.accept(self.sample(-.2))
        b=PowerFeedback(p,clock=lambda:self.now)
        r=row();import time;r['received_qpc_s']=time.perf_counter()
        payload=json.dumps(dict(power_limit=dict(enabled=True,state='ACTIVE',commanded=.5,applied=.5,sequence=0))).encode()
        b.handle(r,payload,('127.0.0.1',1),Mock())
        service=Mock();service.latest=dict(state='RUNNING',fault='')
        with tempfile.TemporaryDirectory() as d:
            receiver=LiveReceiver(0,Path(d)/'telemetry',power_feedback=b)
            try:
                display=LiveDisplay(receiver,finished=lambda:True,mock_service=service)
                display.root.withdraw();display.refresh()
                text=display.values.cget('text')
                for label in ('MOCK Coulomb Counted','Cell stream [MOCK]: VALID','R0 [ASSUMED]','SOP [EST]'):
                    self.assertIn(label,text)
                display.root.destroy()
            finally:
                with patch('torcs_live.write_report',return_value={}):receiver.close()


if __name__=='__main__':unittest.main()
