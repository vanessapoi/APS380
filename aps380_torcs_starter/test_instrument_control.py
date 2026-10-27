"""Mock-only control and live loopback integration; no physical transports."""
from dataclasses import replace
import json
from pathlib import Path
import socket
import tempfile
import time
import unittest

from instrument_control import (ControlConfig, Demand, InstrumentCoordinator,
                                LatestDemand, MockInstrumentService, State)
from instrument_interfaces import InstrumentError, InstrumentTimeout
from mock_instruments import MockPSU, MockBK8500, MockIsolation
from prototype_current_config import current_metadata


class Clock:
    def __init__(self): self.now=10.
    def __call__(self): return self.now
    def sleep(self, seconds): self.now+=seconds


class CoordinatorTest(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        options=dict(clock=self.clock,sleep=self.clock.sleep,response_delay_s=0.)
        self.psu=MockPSU(**options)
        self.load=MockBK8500(**options)
        self.isolation=MockIsolation(self.psu,self.load)
        self.c=InstrumentCoordinator(self.psu,self.load,self.isolation,
            ControlConfig(slew_rate_A_per_s=1000.,neutral_hold_s=.01),clock=self.clock)

    def demand(self, current, session='test'):
        return Demand(current,self.clock(),session,0)

    def run_current(self, current):
        if self.c.state==State.DISARMED:self.c.arm()
        target=max(self.c.config.battery_current_min_A,min(self.c.config.battery_current_max_A,current))
        for _ in range(200):
            self.clock.sleep(.01)
            self.c.step(self.demand(current))
            if self.c.state==State.FAULT:return
            if (self.c.state==State.RUNNING and self.c.phase=='TRACK' and
                    abs(self.c.applied_target-target)<1e-12):return
        self.fail('Control did not settle')

    def assert_safe(self):
        self.assertTrue(self.isolation.is_open)
        self.assertFalse(self.psu.output_enabled)
        self.assertFalse(self.load.output_enabled)
        self.assertTrue(self.c.shutdown_verified)

    def test_explicit_arm_and_disarm(self):
        self.c.step(self.demand(1.))
        self.assertEqual(self.c.state,State.DISARMED)
        self.assert_safe()
        self.run_current(.2)
        self.assertEqual(self.c.state,State.RUNNING)
        self.c.disarm()
        self.assertEqual(self.c.state,State.DISARMED)
        self.assert_safe()

    def test_negative_discharge(self):
        self.run_current(-1.)
        self.assertAlmostEqual(self.load.setpoint_A,2.)
        self.assertAlmostEqual(self.c.snapshot()['mock_cell_current_A'],-1.)

    def test_positive_charge(self):
        self.run_current(.3)
        self.assertAlmostEqual(self.load.setpoint_A,.7)
        self.assertAlmostEqual(self.c.snapshot()['mock_cell_current_A'],.3)

    def test_zero_is_balanced_energized_not_disarmed(self):
        self.run_current(0.)
        self.assertAlmostEqual(self.load.setpoint_A,1.)
        self.assertAlmostEqual(self.c.snapshot()['mock_cell_current_A'],0.)
        self.assertTrue(self.psu.output_enabled and self.load.output_enabled)
        self.assertFalse(self.isolation.is_open)

    def test_directional_saturation_and_separate_charge_bound(self):
        self.run_current(-4.)
        self.assertEqual(self.c.last['permitted_A'],-2.)
        self.assertTrue(self.c.last['directional_saturated'])
        self.assertAlmostEqual(self.load.setpoint_A,3.)
        self.run_current(4.)
        self.assertEqual(self.c.last['permitted_A'],1.)
        self.assertAlmostEqual(self.load.setpoint_A,0.)
        self.assertEqual(self.c.state,State.RUNNING)

    def test_zero_charge_bound(self):
        self.c.config=replace(self.c.config,battery_current_max_A=0.)
        self.run_current(.3)
        self.assertAlmostEqual(self.c.snapshot()['mock_cell_current_A'],0.)

    def test_rapid_sign_changes(self):
        for current in [.4,-.4,0.,1.,-.5]*10:
            self.run_current(current)
            self.assertEqual(self.c.state,State.RUNNING)
            self.assertAlmostEqual(self.c.last['branch_net_A'],current)

    def test_actual_psu_readback_and_loss_of_cc(self):
        self.run_current(-.3)
        self.psu.current_offset_A=-.01
        self.c.step(self.demand(-.3))
        self.assertAlmostEqual(self.load.setpoint_A,1.29)
        self.assertAlmostEqual(self.c.last['branch_net_A'],-.3)
        self.psu.cv_available_A=.8
        self.c.step(self.demand(-.3))
        self.assertEqual(self.c.fault_reason,'PSU_NOT_CC')
        self.assert_safe()

    def test_infeasible_charge_and_discharge_latch_fault(self):
        self.run_current(0.)
        self.psu.current_offset_A=-.2
        self.c.step(self.demand(1.))
        self.assertEqual(self.c.fault_reason,'INFEASIBLE_CURRENT')
        self.assert_safe()
        self.psu.current_offset_A=0.
        self.c.recover()
        self.c.config=replace(self.c.config,eload_current_max_A=1.2)
        self.run_current(-1.)
        self.assertEqual(self.c.fault_reason,'INFEASIBLE_CURRENT')
        self.assert_safe()

    def test_delayed_response_settles_before_cell_is_connected(self):
        self.psu.response_delay_s=self.load.response_delay_s=.15
        self.c.config=replace(self.c.config,settling_timeout_s=3.,transition_timeout_s=None)
        self.c.arm()
        self.c.step(self.demand(.4))
        self.assertEqual(self.c.state,State.READY)
        self.assertTrue(self.isolation.is_open)
        self.assertEqual(self.c.snapshot()['mock_cell_current_A'],0.)
        for _ in range(60):
            self.clock.sleep(.05)
            self.c.step(self.demand(.4))
        self.assertEqual(self.c.state,State.RUNNING)
        self.assertAlmostEqual(self.c.last['branch_net_A'],.4,places=3)

    def test_persistent_tracking_error_trips(self):
        self.run_current(.2)
        self.load.current_offset_A=.1
        for _ in range(10):
            self.clock.sleep(.1)
            self.c.step(self.demand(.2))
        self.assertEqual(self.c.fault_reason,'CURRENT_TRACKING_TIMEOUT')
        self.assert_safe()

    def test_measurement_directional_limit_trips(self):
        self.c.config=replace(self.c.config,battery_current_min_A=-.5)
        self.run_current(-.5)
        self.load.current_offset_A=.1
        self.c.step(self.demand(-.5))
        self.assertEqual(self.c.fault_reason,'MEASURED_DIRECTIONAL_LIMIT')
        self.assert_safe()

    def test_stale_measurements(self):
        self.run_current(.2)
        self.psu.measurement_age_s=1.
        self.c.step(self.demand(.2))
        self.assertIn('STALE',self.c.fault_reason)
        self.assert_safe()

    def test_stale_telemetry_and_unavailable_states(self):
        self.run_current(.2)
        old=self.demand(.2)
        self.clock.sleep(.6)
        self.c.step(old)
        self.assertEqual(self.c.fault_reason,'TELEMETRY_EXPIRED')
        self.assert_safe()
        for reason in ('INVALID','GAP','RECEIVER_ERROR'):
            self.c.recover()
            self.run_current(.2)
            self.c.step(None,reason)
            self.assertEqual(self.c.fault_reason,reason)
            self.assert_safe()

    def test_communication_failures_and_timeouts_disable_both_outputs(self):
        for device in (self.psu,self.load):
            for failure in ('communication','timeout'):
                if self.c.state==State.FAULT:self.c.recover()
                self.run_current(.2)
                device.failure=failure
                self.c.step(self.demand(.2))
                self.assertEqual(self.c.state,State.FAULT)
                self.assert_safe()
                self.assertTrue(self.c.shutdown_errors)
                device.failure=None

    def test_validated_end_disarms_and_new_samples_cannot_rearm(self):
        self.run_current(.2)
        self.c.step(None,'ENDED')
        self.assertEqual(self.c.state,State.DISARMED)
        self.assert_safe()
        self.c.step(self.demand(.2))
        self.assertEqual(self.c.state,State.DISARMED)

    def test_command_expires_during_io(self):
        self.c.config=replace(self.c.config,command_expiry_s=.04)
        self.run_current(.2)
        self.psu.communication_delay_s=self.load.communication_delay_s=.015
        self.c.step(self.demand(.2))
        self.assertEqual(self.c.fault_reason,'TELEMETRY_EXPIRED')
        self.assert_safe()

    def test_emergency_stop_fault_latch_and_explicit_recovery(self):
        self.run_current(.2)
        self.c.emergency_stop()
        self.assert_safe()
        with self.assertRaises(ValueError):self.c.arm()
        self.c.disarm()
        self.c.step(self.demand(.2))
        self.assertEqual(self.c.state,State.FAULT)
        self.psu.failure='communication'
        self.c.recover()
        self.assertEqual(self.c.state,State.FAULT)
        self.psu.failure=None
        self.c.recover()
        self.assertEqual(self.c.state,State.DISARMED)
        self.assert_safe()
        self.run_current(.1)
        self.assertEqual(self.c.state,State.RUNNING)

    def test_recovery_requires_new_demand_and_session_change_trips(self):
        self.run_current(.2)
        old=self.demand(.2)
        self.c.emergency_stop()
        self.c.recover()
        self.c.arm()
        self.c.step(old)
        self.assertIn('NEW_DEMAND',self.c.fault_reason)
        self.c.recover()
        self.run_current(.2)
        self.c.step(self.demand(.2,session='new'))
        self.assertEqual(self.c.fault_reason,'TELEMETRY_SESSION_CHANGED')

    def test_recovery_rejects_nonzero_readback_and_ready_polls_faults(self):
        self.c.arm()
        self.psu.failure='communication'
        self.c.step(None,'WAITING')
        self.assertEqual(self.c.state,State.FAULT)
        self.assert_safe()
        self.psu.failure=None
        self.load.current_offset_A=.1
        self.c.recover()
        self.assertEqual(self.c.state,State.FAULT)
        self.load.current_offset_A=0.
        self.c.recover()
        self.assertEqual(self.c.state,State.DISARMED)

    def test_waiting_ready_timeout_and_invalidated_inflight_sample(self):
        self.c.config=replace(self.c.config,ready_timeout_s=.1)
        self.c.arm()
        self.c.step(None,'WAITING')
        self.assertEqual(self.c.state,State.READY)
        self.clock.sleep(.2)
        self.c.step(None,'WAITING')
        self.assertEqual(self.c.fault_reason,'READY_TIMEOUT')
        self.c.recover()
        self.c.arm()
        self.clock.sleep(.01)
        self.c.step(self.demand(.2),still_valid=lambda:False)
        self.assertEqual(self.c.fault_reason,'TELEMETRY_INVALIDATED_DURING_IO')
        self.assert_safe()

    def test_mock_transport_timeout_and_limits(self):
        self.psu.communication_delay_s=.1
        with self.assertRaises(InstrumentTimeout):self.psu.read(.01)
        with self.assertRaises(InstrumentError):self.load.set_current(-1.,.01)
        with self.assertRaises(InstrumentError):self.load.set_current(3.1,.01)

    def test_config_and_hardware_guard(self):
        for settings in ({'control_hz':0},{'battery_current_max_A':-1},{'psu_cc_setpoint_A':float('nan')},
                         {'io_timeout_s':2.},{'control_hz':True}):
            with self.assertRaises(ValueError):ControlConfig(**settings)
        self.psu.mock_only=False
        with self.assertRaises(ValueError):
            InstrumentCoordinator(self.psu,self.load,self.isolation)


class MailboxAndWorkerTest(unittest.TestCase):
    def wait_for(self, predicate, tick=lambda:None):
        deadline=time.perf_counter()+3.
        while time.perf_counter()<deadline:
            tick()
            if predicate():return
            time.sleep(.01)
        self.fail('Timed out waiting for mock worker')

    def test_latest_only_and_invalidation_generation(self):
        box=LatestDemand()
        def row(i):return dict(**current_metadata(),cell_current_command_A=.1,received_qpc_s=10.,
                              session_id='test',sequence=i,target_available=True)
        box.publish(row(0));d,_,rev=box.snapshot()
        for i in range(1000):box.publish(row(i))
        self.assertEqual(box.snapshot()[0].sequence,999)
        self.assertTrue(box.valid(d,rev))
        box.publish(None,'INVALID');box.publish(row(1001))
        self.assertFalse(box.valid(d,rev))

    def test_live_udp_scaling_is_unchanged_and_fault_is_logged(self):
        from torcs_live import LiveReceiver
        from test_torcs_live import packet
        with tempfile.TemporaryDirectory() as folder:
            service=MockInstrumentService(Path(folder)/'instruments',ControlConfig(control_hz=20.))
            service.psu.communication_delay_s=service.load.communication_delay_s=.01
            receiver=LiveReceiver(0,Path(folder)/'telemetry',demand_sink=service.demands)
            receiver.processor.shared_clock=False
            sender=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            receiver.start();service.start(arm=True)
            try:
                for i in range(20):
                    p=packet(receiver.processor,t=i*.02,seq=i,power=100000,session='loopback')
                    sender.sendto(json.dumps(p).encode(),('127.0.0.1',receiver.port))
                    time.sleep(.02)
                self.wait_for(lambda:service.latest['state']=='RUNNING')
                self.assertAlmostEqual(receiver.processor.current['cell_current_command_A'],-.42)
                self.assertAlmostEqual(service.latest['permitted_A'],-.42)
                sender.sendto(b'[]',('127.0.0.1',receiver.port))
                self.wait_for(lambda:service.latest['state']=='FAULT')
                self.assertIn(service.latest['fault'],('INVALID','TELEMETRY_INVALIDATED_DURING_IO'))
                self.assertTrue(service.latest['shutdown_verified'])
            finally:
                sender.close()
                result=service.close()
                receiver.close()
            events=[json.loads(line) for line in (service.output/'instruments.jsonl').read_text().splitlines()]
            self.assertTrue(any(abs(e.get('permitted_A',-10)+.42)<1e-12 for e in events))
            self.assertTrue(any(e['transactions']['psu'] for e in events))
            self.assertFalse(result['physical_commands_sent'])
            self.assertIsNone(result['worker_error'])

    def test_worker_operator_stop_recovery_and_disarm(self):
        with tempfile.TemporaryDirectory() as folder:
            service=MockInstrumentService(Path(folder)/'trial')
            def publish():
                service.demands.publish(dict(**current_metadata(),cell_current_command_A=.1,received_qpc_s=time.perf_counter(),
                    session_id='test',sequence=0,target_available=True))
            service.start(arm=True)
            try:
                publish()
                self.wait_for(lambda:service.latest['state']=='RUNNING',publish)
                service.request('emergency_stop')
                self.wait_for(lambda:service.latest['state']=='FAULT')
                self.assertEqual(service.latest['fault'],'EMERGENCY_STOP')
                self.assertTrue(service.latest['shutdown_verified'])
                service.request('arm')
                time.sleep(.12)
                self.assertEqual(service.latest['state'],'FAULT')
                service.request('recover')
                self.wait_for(lambda:service.latest['state']=='DISARMED')
                publish()
                service.request('arm')
                self.wait_for(lambda:service.latest['state']=='RUNNING',publish)
                service.request('disarm')
                self.wait_for(lambda:service.latest['state']=='DISARMED')
                self.assertTrue(service.latest['shutdown_verified'])
            finally:service.close()

    def test_worker_shutdown_after_telemetry_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            service=MockInstrumentService(Path(folder)/'trial',ControlConfig(command_expiry_s=.15,control_hz=30.))
            service.start(arm=True)
            try:
                service.demands.publish(dict(**current_metadata(),cell_current_command_A=.1,received_qpc_s=time.perf_counter(),
                    session_id='test',sequence=0,target_available=True))
                self.wait_for(lambda:service.latest['state']=='FAULT')
                self.assertEqual(service.latest['fault'],'TELEMETRY_EXPIRED')
            finally:result=service.close()
            self.assertTrue(result['final']['shutdown_verified'])


class SignTransitionTest(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        options=dict(clock=self.clock,sleep=self.clock.sleep,response_delay_s=.02)
        self.psu,self.load=MockPSU(**options),MockBK8500(**options)
        self.c=InstrumentCoordinator(self.psu,self.load,MockIsolation(self.psu,self.load),clock=self.clock)
        self.c.arm()

    def tick(self,current,dt=.1):
        self.clock.sleep(dt)
        self.c.step(Demand(current,self.clock(),'reversals',0))
        return self.c.snapshot()

    def settle(self,current):
        for _ in range(300):
            e=self.tick(current)
            if self.c.state==State.FAULT:self.fail(self.c.fault_reason)
            if (self.c.state==State.RUNNING and self.c.phase=='TRACK' and
                    abs(e['applied_target_A']-current)<1e-9 and abs(e['tracking_error_A'])<.002):return
        self.fail('Mock did not settle')

    def test_reversal_requires_measured_zero_dwell_both_directions(self):
        self.settle(.3)
        for target in (-.3,.3):
            records=[]
            for _ in range(60):
                old=self.c.applied_target
                e=self.tick(target);records.append(e)
                self.assertNotEqual(self.c.state,State.FAULT,self.c.fault_reason)
                self.assertLessEqual(abs(e['applied_target_A']-old),.0200000001)
                self.assertTrue(e['direction_ok'])
                if abs(e['applied_target_A']-target)<1e-9:break
            self.assertTrue(any(e['transition_phase']=='HOLD_ZERO' for e in records))
            self.assertTrue(any(e['applied_target_A']==0 and abs(e['branch_net_A'])<=.002 for e in records))

    def test_default_policy_reaches_full_directional_bounds_without_instantaneous_steps(self):
        self.settle(1.)
        self.assertAlmostEqual(self.c.last['branch_net_A'],1.,delta=.002)
        self.settle(-2.)
        self.assertAlmostEqual(self.c.last['branch_net_A'],-2.,delta=.002)
        self.assertGreaterEqual(self.load.setpoint_A,0.)

    def test_rapid_reversals_do_not_reset_zero_dwell_or_queue_targets(self):
        self.settle(.3)
        applied=[]
        for i in range(30):
            e=self.tick(-.3 if i%2==0 else .3)
            applied.append(e['applied_target_A'])
            self.assertNotEqual(self.c.state,State.FAULT,self.c.fault_reason)
            self.assertTrue(e['direction_ok'])
        for a,b in zip(applied,applied[1:]):self.assertGreaterEqual(a*b,0.)
        self.settle(-.2)
        self.assertAlmostEqual(self.c.last['permitted_A'],-.2)

    def test_stuck_neutral_faults_even_when_tracking_within_tolerance(self):
        self.settle(.1)
        self.load.current_offset_A=-.005
        for _ in range(int(self.c.config.transition_timeout_s/.1)+3):
            self.tick(-.1)
            if self.c.state==State.FAULT:break
        self.assertEqual(self.c.fault_reason,'SIGN_TRANSITION_TIMEOUT')
        self.assertTrue(self.c.shutdown_verified)

    def test_communication_failure_during_reversal_trips_both_outputs(self):
        self.settle(.2)
        self.tick(-.2)
        self.load.failure='timeout'
        self.tick(-.2)
        self.assertEqual(self.c.state,State.FAULT)
        self.assertTrue(self.c.shutdown_verified)
        self.assertFalse(self.psu.output_enabled or self.load.output_enabled)

    def test_unexpected_direction_is_a_fault(self):
        self.settle(.1)
        self.load.current_offset_A=.2
        self.tick(.1)
        self.assertEqual(self.c.fault_reason,'UNEXPECTED_CURRENT_DIRECTION')
        self.assertTrue(self.c.shutdown_verified)

    def test_startup_does_not_connect_before_readbacks_stabilize(self):
        self.c.step(Demand(.00126,self.clock(),'reversals',0))
        self.assertEqual(self.c.state,State.READY)
        self.assertTrue(self.c.isolation.is_open)
        self.settle(.00126)
        self.assertFalse(self.c.isolation.is_open)

    def test_arm_while_regenerating_balances_before_applying_demand(self):
        for current in (.0039082654926, .3, 1.):
            with self.subTest(current=current):
                self.setUp()
                e=self.tick(current,dt=.00002)  # first manual-session readback
                self.assertEqual(e['state'],'READY')
                self.assertEqual(e['transition_phase'],'BALANCING')
                self.assertEqual(e['applied_target_A'],0.)
                self.assertTrue(e['isolation']['is_open'])
                self.assertLess(e['psu']['current_A'],.001)
                for _ in range(50):
                    e=self.tick(current)
                    self.assertNotEqual(e['state'],'FAULT',e['fault'])
                    self.assertEqual(e['applied_target_A'],0.)
                    if e['state']=='RUNNING':break
                    self.assertTrue(e['isolation']['is_open'])
                    self.assertEqual(e['mock_cell_current_A'],0.)
                self.assertEqual(e['state'],'RUNNING')
                self.assertLessEqual(abs(e['branch_net_A']),self.c.config.neutral_tolerance_A)
                self.settle(current)
                self.assertAlmostEqual(self.c.last['branch_net_A'],current,delta=.002)

    def test_waiting_startup_balances_but_never_connects_without_demand(self):
        for _ in range(15):
            self.clock.sleep(.1)
            self.c.step(None,'WAITING')
        e=self.c.snapshot()
        self.assertEqual(e['state'],'READY')
        self.assertTrue(e['isolation']['is_open'])
        self.assertAlmostEqual(e['branch_net_A'],0.,delta=.002)
        self.assertEqual(e['applied_target_A'],0.)
        self.settle(-.3)

    def test_failed_startup_latches_timeout_and_stale_readback_faults(self):
        self.c.config=replace(self.c.config,ready_timeout_s=.5)
        self.psu.response_delay_s=1e9
        for _ in range(8):self.tick(-.3)
        self.assertEqual(self.c.fault_reason,'READY_TIMEOUT')
        self.assertTrue(self.c.shutdown_verified)
        self.assertTrue(self.c.snapshot()['measurements_retained'])
        self.assertEqual(self.c.snapshot()['measurement_context'],'retained_pre_fault')
        self.setUp()
        self.psu.measurement_age_s=1.
        self.tick(-.3)
        self.assertEqual(self.c.fault_reason,'STALE_OR_FUTURE_MEASUREMENT')
        self.assertTrue(self.c.shutdown_verified)

    def test_cv_cannot_qualify_startup(self):
        self.psu.cv_available_A=.1
        self.tick(.4)
        self.assertEqual(self.c.fault_reason,'PSU_NOT_CC')
        self.assertTrue(self.c.shutdown_verified)
        self.assertTrue(self.c.isolation.is_open)


if __name__=='__main__':unittest.main()
