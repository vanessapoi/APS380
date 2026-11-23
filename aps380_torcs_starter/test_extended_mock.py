"""Full-range virtual-clock mock plant; no physical drivers or shortcuts to slew."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from battery_bias import BatteryBiasCoordinator,BiasCellStream
from battery_bias_feedback import BiasRintPolicy
from instrument_control import Demand,State
from mock_instruments import MockPSU,MockBK8500,MockIsolation
from mock_test_config import BASE,resolve_mock_test_config
from test_instrument_control import Clock
from test_cell_sop import row
from torcs_live import LiveProcessor


class ExtendedRig:
    def __init__(self):
        data=json.loads((BASE/'profiles/mock_test_extended_5a.json').read_text())
        data.update(initial_soc_fraction=.8,sop_discharge_ceiling_A=5.)
        self.config=resolve_mock_test_config(data);self.clock=Clock()
        options=dict(clock=self.clock,sleep=self.clock.sleep,response_delay_s=.02)
        self.psu=MockPSU(max_current_A=1.,**options);self.psu.cv_available_A=1.
        self.load=MockBK8500(max_current_A=6.,**options)
        self.c=BatteryBiasCoordinator(self.psu,self.load,MockIsolation(self.psu,self.load),self.config.control,self.clock)
        self.stream=BiasCellStream(self.config.model,clock=self.clock)
        self.service=SimpleNamespace(cell_stream=self.stream,latest=self.c.snapshot())
        self.policy=BiasRintPolicy(self.service)
        p=LiveProcessor((BASE/'profiles/tesla_model3_rwd.json').read_bytes(),self.config.scaling,current_config=self.config.control)
        self.policy.configure(p.cell,p.profile)
        self.sequence=0;self.previous=None;self.soc=.8;self.trace=[]

    def step(self,target,original=None):
        self.clock.sleep(.1);self.sequence+=1
        self.c.step(Demand(target,self.clock(),'extended',self.sequence,requested_current_A=target if original is None else original))
        snapshot=self.c.snapshot();model=self.stream.update(snapshot)
        self.service.latest=snapshot
        if self.c.state in (State.READY,State.RUNNING):
            assert model['cell_observer_state']=='VALID',model
            frame=snapshot['cell_sensor_frame'];current=frame['cell_current_A']
            if self.previous:
                dt=frame['acquired_s']-self.previous[0]
                self.soc+=(self.previous[1]+current)/2*dt/(3600*3.5)
            self.previous=(frame['acquired_s'],current)
            assert abs(self.soc-model['sop_cell_soc_fraction'])<1e-12
            assert abs(snapshot['load_command_A']-snapshot['previous_load_command_A'])<=snapshot['load_slew_budget_A']+1e-12
            fraction=self.policy.evaluate_row(row())[1]
            self.trace.append(dict(time_s=self.clock(),target_A=target,applied_A=snapshot['applied_target_A'],
                measured_A=current,load_A=snapshot['load']['current_A'],soc=self.soc,
                sop_W=model['sop_max_discharge_W'],fraction=fraction,state=snapshot['state']))
        return snapshot

    def ready(self):
        self.c.arm()
        for _ in range(700):
            snapshot=self.step(0.)
            if self.c.state==State.RUNNING:return snapshot
            assert self.c.state==State.READY,snapshot
            assert snapshot['bias_safety']['cell_isolated']
        raise AssertionError('No RUNNING startup')

    def follow(self,target,steps):
        for _ in range(steps):
            snapshot=self.step(target)
            assert self.c.state==State.RUNNING,snapshot
        assert abs(snapshot['cell_sensor_frame']['cell_current_A']-target)<.003,snapshot
        return snapshot


class ExtendedMockTests(unittest.TestCase):
    def test_original_limited_applied_and_measured_currents_stay_separate(self):
        rig=ExtendedRig();rig.ready()
        snapshot=rig.step(-5.,original=-8.)
        self.assertEqual(snapshot['requested_A'],-8.)
        self.assertEqual(snapshot['permitted_A'],-5.)
        self.assertGreater(snapshot['applied_target_A'],-.01)
        self.assertGreater(snapshot['cell_sensor_frame']['cell_current_A'],-.01)
        self.assertTrue(snapshot['directional_saturated'])

    def test_explicit_selection_derived_timeout_and_unchanged_defaults(self):
        from battery_bias import BIAS_CONTROL
        rig=ExtendedRig()
        self.assertEqual(rig.config.control.transition_timeout_s,452.)
        self.assertEqual(BIAS_CONTROL.transition_timeout_s,182.)
        self.assertEqual(rig.config.control.slew_rate_A_per_s,.02)
        self.assertEqual(rig.config.control.measurement_expiry_s,.2)
        data=dict(rig.config.audit['requested']);data.pop('mock_capability')
        with self.assertRaises(ValueError):resolve_mock_test_config(data)

    def test_full_range_measured_current_soc_sop_and_reversals(self):
        rig=ExtendedRig();neutral=rig.ready()
        self.assertTrue(neutral['startup_balanced'])
        self.assertAlmostEqual(neutral['psu']['current_A'],1.,places=3)
        self.assertAlmostEqual(neutral['load']['current_A'],1.,places=3)
        for target,steps in ((-5.,2700),(1.,3400),(-5.,3400),(0.,2800)):
            rig.follow(target,steps)
        self.assertLess(min(x['measured_A'] for x in rig.trace),-4.999)
        self.assertGreater(max(x['measured_A'] for x in rig.trace),.999)
        self.assertGreater(max(x['load_A'] for x in rig.trace),5.999)
        self.assertLess(min(x['soc'] for x in rig.trace),.8)
        self.assertNotEqual(rig.trace[0]['sop_W'],rig.trace[-1]['sop_W'])
        rig.c.disarm();self.assertTrue(rig.c.snapshot()['shutdown_verified'])

    def test_genuine_source_loss_measurement_loss_and_transition_timeout_fault(self):
        for failure in ('source','sensor','timeout'):
            with self.subTest(failure=failure):
                rig=ExtendedRig();rig.ready()
                if failure=='source':rig.psu.cv_available_A=.2;rig.step(.3)
                elif failure=='sensor':rig.c.sensors.failure='missing';rig.step(0.)
                else:
                    rig.c.phase='TO_ZERO';rig.c.transition_started=rig.clock()-453
                    rig.step(.5)
                self.assertEqual(rig.c.state,State.FAULT)
                if failure=='source':self.assertEqual(rig.c.fault_reason,'INFEASIBLE_CURRENT')
                if failure=='timeout':self.assertEqual(rig.c.fault_reason,'SIGN_TRANSITION_TIMEOUT')
                state=rig.c.snapshot()
                self.assertTrue(state['shutdown_verified']);self.assertTrue(state['bias_safety']['cell_isolated'])
                self.assertTrue(state['bias_safety']['source_isolated']);self.assertTrue(state['bias_safety']['outputs_disabled'])
                self.assertEqual(rig.policy.evaluate_row(row())[1],0.)
