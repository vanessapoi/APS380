"""No serial imports, ports or physical instruments: independent-channel mock tests."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from battery_bias import (BatteryBiasCoordinator, BiasCellStream, MeasurementGuard,bias_acceptance)
from instrument_control import ControlConfig, Demand, State
from mock_instruments import MockPSU, MockBK8500, MockIsolation
from test_instrument_control import Clock


class BiasTest(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        options=dict(clock=self.clock,sleep=self.clock.sleep,response_delay_s=.02)
        self.psu=MockPSU(**options);self.psu.cv_available_A=.2
        self.load=MockBK8500(**options)
        self.isolation=MockIsolation(self.psu,self.load)
        self.c=BatteryBiasCoordinator(self.psu,self.load,self.isolation,
            ControlConfig(slew_rate_A_per_s=.02,ready_timeout_s=90.),self.clock)
        self.sequence=0

    def step(self,current=0.,count=1):
        for _ in range(count):
            self.clock.sleep(.1);self.sequence+=1
            self.c.step(Demand(current,self.clock(),'trial',self.sequence,requested_current_A=current))
        return self.c.snapshot()

    def ready(self,current=0.):
        self.c.arm();self.step(current,150)
        self.assertEqual(self.c.state,State.RUNNING,self.c.fault_reason)

    def safe(self):
        s=self.c.snapshot()
        self.assertTrue(s['shutdown_verified'],s)
        self.assertTrue(s['bias_safety']['cell_isolated'])
        self.assertTrue(s['bias_safety']['source_isolated'])
        self.assertTrue(s['bias_safety']['outputs_disabled'])

    def test_disarmed_and_signed_startup(self):
        self.step(-.1);self.assertEqual(self.c.state,State.DISARMED);self.safe()
        self.ready(-.1);self.step(-.1,100)
        self.assertAlmostEqual(self.c.frame.cell_current_A,-.1,places=3)
        self.assertAlmostEqual(self.load.setpoint_A,.3,places=3)

    def test_charge_neutral_discharge_and_reversals(self):
        self.ready()
        for target in (-.1,.08,0.,-.08,.05,0.):
            self.step(target,180)
            self.assertEqual(self.c.state,State.RUNNING,self.c.fault_reason)
            self.assertAlmostEqual(self.c.frame.cell_current_A,target,places=3)
            self.assertAlmostEqual(self.load.setpoint_A,.2-target,places=3)
        self.c.disarm();self.safe()

    def test_varying_psu_and_branch_slew(self):
        self.ready(-.05)
        previous=self.load.setpoint_A
        for i in range(180):
            self.psu.cv_available_A=.2-i*.00005
            s=self.step(-.05)
            self.assertEqual(self.c.state,State.RUNNING,self.c.fault_reason)
            self.assertLessEqual(abs(self.load.setpoint_A-previous),s['load_slew_budget_A']+1e-12)
            previous=self.load.setpoint_A
            self.assertAlmostEqual(s['cell_sensor_frame']['cell_current_A'],
                s['contemporaneous_branch_net_A'],places=6)
        self.assertNotEqual(self.psu.setpoint_A,self.c.frame.psu_current_A)

    def test_rapid_latest_reversals_do_not_queue(self):
        self.ready()
        for i in range(200):
            self.step(.1 if i%2 else -.1)
            self.assertEqual(self.c.state,State.RUNNING,self.c.fault_reason)
            self.assertLessEqual(abs(self.c.frame.cell_current_A),.01)

    def test_infeasible_fault_latch_explicit_recovery(self):
        self.ready();self.step(.4)
        self.assertEqual(self.c.state,State.FAULT)
        self.assertIn('INFEASIBLE',self.c.fault_reason);self.safe()
        self.step(0.,10);self.assertEqual(self.c.state,State.FAULT)
        self.c.recover();self.assertEqual(self.c.state,State.DISARMED);self.safe()
        self.ready()

    def test_sensor_failures(self):
        for failure in ('missing','timeout','invalid','duplicate','nan'):
            with self.subTest(failure=failure):
                self.setUp();self.ready();self.c.sensors.failure=failure;self.step()
                self.assertEqual(self.c.state,State.FAULT);self.safe()

    def test_stale_sensor_telemetry_and_disagreement(self):
        for kind in ('stale','telemetry','cell','psu'):
            with self.subTest(kind=kind):
                self.setUp();self.ready()
                if kind=='stale':self.c.sensors.age_s=1.;self.step()
                elif kind=='telemetry':self.clock.sleep(1.);self.c.step(None,'TELEMETRY_LOST')
                elif kind=='cell':self.c.sensors.cell_offset_A=.1;self.step()
                else:self.c.sensors.psu_offset_A=.1;self.step()
                self.assertEqual(self.c.state,State.FAULT);self.safe()

    def test_protection_estop_and_unverified_shutdown(self):
        for kind in ('protection','estop','hardware','isolation','source_stuck'):
            with self.subTest(kind=kind):
                self.setUp();self.ready()
                if kind=='protection':self.c.safety.protection_ready=False;self.step()
                elif kind=='estop':self.c.safety.estop_active=True;self.step()
                elif kind=='hardware':self.c.safety.hardware_faults=('local_overvoltage',);self.step()
                elif kind=='isolation':self.isolation.is_open=True;self.step()
                else:self.c.safety.source_disconnect_stuck=True;self.c.emergency_stop()
                self.assertEqual(self.c.state,State.FAULT)
                if kind=='source_stuck':self.assertFalse(self.c.shutdown_verified)
                else:self.safe()

    def test_guard_rejects_reorder_session_future_and_real_source(self):
        for changes in ({'sequence':0},{'sequence':3},{'session_id':'other'},
                        {'acquired_s':99.},{'source':'esp32_real'},{'valid':False}):
            g=MeasurementGuard(self.clock)
            f=replace(self.c.sensors.sample(),sequence=0);g.accept(f)
            with self.subTest(changes=changes),self.assertRaises((ValueError,RuntimeError)):
                g.accept(replace(f,sequence=1,**changes) if 'sequence' not in changes else replace(f,**changes))

    def test_soc_uses_independent_channel_not_requested_current(self):
        config=json.loads((Path(__file__).parent/'profiles/rint_sop_live_mock_example.json').read_text())
        stream=BiasCellStream(config,self.clock)
        self.ready()
        stream.update(self.c.snapshot())
        self.c.sensors.cell_offset_A=.001
        before=stream.observer.snapshot()['estimate']['soc']
        for _ in range(120):
            s=self.step(-.1);model=stream.update(s)
        after=stream.observer.snapshot()['estimate']['soc']
        self.assertLess(after,before)
        self.assertEqual(model['cell_mock_measured_current_A'],s['cell_sensor_frame']['cell_current_A'])
        self.assertNotEqual(model['cell_mock_measured_current_A'],s['applied_target_A'])
        low_ocv=model['sop_ocv_candidate_V']
        for _ in range(200):model=stream.update(self.step(.1))
        self.assertEqual(self.c.state,State.RUNNING,self.c.fault_reason)
        self.assertGreater(model['sop_ocv_candidate_V'],low_ocv)
        self.assertTrue(model['sop_model_valid'])
        self.c.emergency_stop();self.assertEqual(stream.update(self.c.snapshot())['cell_observer_state'],'FAULT')
        stream.reset();self.assertEqual(stream.observer.snapshot()['state'],'WAITING')

    def test_physical_device_guard_unchanged(self):
        self.psu.mock_only=False
        with self.assertRaises(ValueError):
            BatteryBiasCoordinator(self.psu,self.load,self.isolation)

    def test_communication_failures_and_failed_startup(self):
        for device_name in ('psu','load'):
            for failure in ('communication','timeout'):
                with self.subTest(device=device_name,failure=failure):
                    self.setUp();self.ready();getattr(self,device_name).failure=failure;self.step()
                    self.assertEqual(self.c.state,State.FAULT);self.safe()
                    self.c.recover();self.assertEqual(self.c.state,State.FAULT)
                    getattr(self,device_name).failure=None;self.c.recover()
                    self.assertEqual(self.c.state,State.DISARMED)
        self.setUp();self.load.response_delay_s=1000.;self.c.arm();self.step(-.1,920)
        self.assertEqual(self.c.state,State.FAULT);self.assertIn('READY_TIMEOUT',self.c.fault_reason);self.safe()

    def test_voltage_temperature_and_isolation_qualification(self):
        for field,value in (('voltage_V',2.),('temperature_C',50.)):
            with self.subTest(field=field):
                self.setUp();setattr(self.c.sensors,field,value);self.c.arm()
                self.assertEqual(self.c.state,State.FAULT);self.safe()
        self.setUp();self.psu.voltage_V=4.;self.c.arm();self.step(0.,150)
        self.assertEqual(self.c.state,State.FAULT);self.assertIn('VOLTAGE_MISMATCH',self.c.fault_reason);self.safe()

    def test_zero_source_and_zero_load_are_valid(self):
        self.psu.cv_available_A=0.;self.ready()
        self.assertEqual(self.load.setpoint_A,0.)
        self.step(-.05,100)
        self.assertEqual(self.c.state,State.RUNNING,self.c.fault_reason)
        self.assertAlmostEqual(self.c.frame.cell_current_A,-.05,places=3)
        self.c.disarm();self.safe()

    def test_load_off_alone_can_charge_and_is_not_shutdown(self):
        self.ready(-.05);self.step(-.05,100)
        self.load.set_output(False,.02);self.clock.sleep(.1)
        self.assertGreater(self.c.sensors.sample().cell_current_A,0.)
        self.step();self.assertEqual(self.c.state,State.FAULT);self.safe()

    def test_isolation_failure_is_not_verified(self):
        self.ready()
        self.isolation.open=lambda:None
        self.c.emergency_stop()
        self.assertFalse(self.c.shutdown_verified)
        self.assertIn('BIAS_CELL_SOURCE_OR_OUTPUT_SHUTDOWN_NOT_VERIFIED',self.c.shutdown_errors)

    def test_persistent_tracking_error_from_source_drop(self):
        self.ready(-.1);self.step(-.1,100)
        self.psu.cv_available_A=.05
        self.step(-.1,20)
        self.assertEqual(self.c.state,State.FAULT)
        self.assertIn('CURRENT_TRACKING_TIMEOUT',self.c.fault_reason);self.safe()

    def test_limits_saturation_and_net_slew(self):
        self.ready();previous=self.c.applied_target
        for _ in range(1100):
            s=self.step(-3.)
            self.assertEqual(self.c.state,State.RUNNING,self.c.fault_reason)
            self.assertLessEqual(abs(s['applied_target_A']-previous),.002+1e-12)
            self.assertTrue(0<=self.load.setpoint_A<=3.)
            previous=s['applied_target_A']
        self.assertEqual(s['requested_A'],-3.)
        self.assertEqual(s['permitted_A'],-2.)
        self.assertAlmostEqual(s['cell_sensor_frame']['cell_current_A'],-2.,places=3)

    def test_independent_soc_boundary_latches(self):
        config=json.loads((Path(__file__).parent/'profiles/rint_sop_live_mock_example.json').read_text())
        config['mock_state']['soc_fraction']=0.
        stream=BiasCellStream(config,self.clock)
        self.ready();stream.update(self.c.snapshot())
        for _ in range(40):model=stream.update(self.step(-.1))
        self.assertEqual(model['cell_observer_state'],'FAULT')
        self.assertIn('BOUNDARY',model['cell_observer_error'])
        self.assertFalse(model['sop_model_valid'])

    def test_acceptance_uses_bias_policy_and_rejects_failed_checks(self):
        self.ready(-.1);events=[]
        for _ in range(100):
            s=self.step(-.1)
            s['transactions']={'psu':[dict(event='transaction',failure=None)]}
            events.append(s)
        self.c.disarm();final=self.c.snapshot()
        report=bias_acceptance(events,self.c.config,final,require_running=True)
        self.assertTrue(report['passed'],report['check_status'])
        self.assertIn('instrument_modes_qualified',report['checks'])
        broken=[dict(e,load_command_A=10.) for e in events]
        self.assertFalse(bias_acceptance(broken,self.c.config,final,require_running=True)['passed'])
        final['bias_safety']['source_isolated']=False
        self.assertFalse(bias_acceptance(events,self.c.config,final,require_running=True)['passed'])

    def test_no_running_is_not_assessed(self):
        result=bias_acceptance([],self.c.config,self.c.snapshot())
        self.assertEqual(result['control_status'],'NOT ASSESSED')
        self.assertIsNone(result['checks']['tracking_within_policy'])
        self.assertFalse(bias_acceptance([],self.c.config,self.c.snapshot(),require_running=True)['passed'])

    def test_default_bias_configuration_allows_full_mock_source_startup(self):
        self.psu.cv_available_A=1.
        self.c=BatteryBiasCoordinator(self.psu,self.load,self.isolation,clock=self.clock)
        self.c.arm();self.step(0.,650)
        self.assertEqual(self.c.state,State.RUNNING,self.c.fault_reason)
        self.assertEqual(self.c.config.slew_rate_A_per_s,.02)
        self.assertAlmostEqual(self.load.setpoint_A,1.)

    def test_ready_connection_faults_immediately(self):
        self.c.arm();self.isolation.is_open=False;self.step()
        self.assertEqual(self.c.state,State.FAULT);self.safe()

    def test_final_balance_source_jump_faults_before_connection(self):
        original=self.c._before_isolation_close
        def jump():
            self.psu.cv_available_A=.8;self.clock.sleep(.1);original()
        self.c._before_isolation_close=jump
        self.c.arm();self.step(0.,150)
        self.assertEqual(self.c.state,State.FAULT)
        self.assertIn('BALANCE_CHANGED',self.c.fault_reason);self.safe()

    def test_feedback_exception_reports_unknown_shutdown(self):
        self.ready()
        self.isolation.verify=lambda:(_ for _ in ()).throw(RuntimeError('lost feedback'))
        self.c.emergency_stop()
        s=self.c.snapshot()
        self.assertEqual(s['state'],'FAULT');self.assertFalse(s['shutdown_verified'])
        self.assertFalse(self.psu.output_enabled);self.assertFalse(self.load.output_enabled)
        self.assertTrue(s['shutdown_errors'])

    def test_disarm_resume_preserves_soc_and_excludes_isolated_gap(self):
        config=json.loads((Path(__file__).parent/'profiles/rint_sop_live_mock_example.json').read_text())
        stream=BiasCellStream(config,self.clock);self.ready()
        for _ in range(100):stream.update(self.step(-.1))
        before=stream.observer.estimate.soc
        self.c.disarm();stream.update(self.c.snapshot());self.clock.sleep(2.)
        self.assertEqual(stream.update(self.c.snapshot())['cell_observer_state'],'WAITING')
        self.c.arm();stream.update(self.step())
        self.assertEqual(stream.observer.estimate.soc,before)
        self.assertFalse(stream.observer.error)

    def test_isolated_sensor_noise_retained_but_not_integrated(self):
        config=json.loads((Path(__file__).parent/'profiles/rint_sop_live_mock_example.json').read_text())
        stream=BiasCellStream(config,self.clock)
        self.c.sensors.cell_offset_A=.001;self.c.arm();model=stream.update(self.step())
        self.assertEqual(model['cell_observer_state'],'VALID')
        self.assertEqual(model['raw_sensor_current_A'],.001)
        self.assertEqual(model['cell_mock_measured_current_A'],0.)

    def test_async_cached_frame_and_changed_duplicate(self):
        from battery_bias import LatestBiasMeasurement
        mailbox=LatestBiasMeasurement(self.clock)
        f=self.c.sensors.sample();mailbox.publish(f)
        self.assertEqual(mailbox.sample(),mailbox.sample())
        self.c.measurements.accept(f)
        self.c.measurements.accept(f,allow_repeated=True)
        with self.assertRaises(RuntimeError):mailbox.publish(replace(f,cell_current_A=.01))
        self.clock.sleep(1.)
        with self.assertRaises(RuntimeError):mailbox.sample()

    def test_partial_cell_disconnect_failure_still_requests_source_disconnect(self):
        self.ready()
        self.isolation.open=lambda:(_ for _ in ()).throw(RuntimeError('stuck contact'))
        self.c.emergency_stop()
        self.assertTrue(self.c.safety.source_isolated)
        self.assertFalse(self.c.shutdown_verified)
        self.assertFalse(self.psu.output_enabled);self.assertFalse(self.load.output_enabled)

    def test_manual_source_capabilities_fail_closed(self):
        from battery_bias import SourceCapabilities
        with self.assertRaises(ValueError):
            BatteryBiasCoordinator(self.psu,self.load,self.isolation,source_capabilities=SourceCapabilities(False,False,True))


if __name__=='__main__':unittest.main()
