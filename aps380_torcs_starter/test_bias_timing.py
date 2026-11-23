"""Deterministic Windows-stall counterfactuals; no physical interfaces."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
import test_battery_bias as rig
from battery_bias import BiasCellStream
from battery_bias_feedback import BiasRintPolicy
from live_cell_state import LiveCellObserver
from test_cell_sop import CELL,PROFILE,row
from vehicle_power_limit import PowerFeedback


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.r=rig.BiasTest();self.r.setUp();self.r.ready()
        config=json.loads((Path(__file__).parent/'profiles/rint_sop_live_mock_example.json').read_text())
        self.stream=BiasCellStream(config,self.r.clock)
        self.service=SimpleNamespace(cell_stream=self.stream,latest=self.r.c.snapshot())
        self.stream.update(self.service.latest)
        self.policy=BiasRintPolicy(self.service);self.policy.configure(CELL,PROFILE)

    def test_read_before_fresh_publication_does_not_latch_or_integrate_gap(self):
        for delay in (.25,.35,.499):
            with self.subTest(delay=delay):
                self.setUp();before=self.stream.observer.estimate.soc
                self.r.clock.sleep(delay)
                state=self.stream.observer.snapshot()
                self.assertEqual(state['state'],'STALE');self.assertFalse(self.stream.observer.error)
                self.assertEqual(self.policy.evaluate_row(row())[1],0.)
                self.r.sequence+=1
                from instrument_control import Demand
                self.r.c.step(Demand(-.1,self.r.clock(),'trial',self.r.sequence))
                self.service.latest=self.r.c.snapshot();model=self.stream.update(self.service.latest)
                self.assertEqual(model['cell_observer_state'],'VALID')
                self.assertEqual(self.stream.observer.estimate.soc,before)
                self.assertEqual(model['cell_timing']['excluded_intervals'],1)
                self.assertAlmostEqual(model['cell_timing']['excluded_time_s'],delay)
                self.assertGreater(self.policy.evaluate_row(row())[1],0.)

    def test_long_gap_latches_even_if_consumer_did_not_poll(self):
        self.r.clock.sleep(.51)
        from instrument_control import Demand
        self.r.c.step(Demand(0.,self.r.clock(),'trial',99))
        self.service.latest=self.r.c.snapshot();model=self.stream.update(self.service.latest)
        self.assertEqual(model['cell_observer_state'],'FAULT')
        self.assertIn('GAP_EXCEEDED',model['cell_observer_error'])
        self.assertEqual(self.policy.evaluate_row(row())[1],0.)

    def test_repeated_cached_reads_do_not_refresh_age(self):
        for _ in range(6):
            self.r.clock.sleep(.1);self.stream.update(self.service.latest)
        self.assertEqual(self.stream.observer.snapshot()['state'],'FAULT')

    def test_strict_original_policy_still_faults_at_200ms(self):
        observer=LiveCellObserver(3.5,.8,clock=self.r.clock)
        from live_cell_state import CellSample
        from cell_soc import CellMeasurement
        observer.accept(CellSample(CellMeasurement('s',self.r.clock(),3.65,-.1,25.),0,self.r.clock()))
        self.r.clock.sleep(.21)
        self.assertEqual(observer.snapshot()['state'],'FAULT')

    def test_delayed_acquisition_is_not_made_fresh_by_publication(self):
        from live_cell_state import CellSample
        from cell_soc import CellMeasurement
        observer=self.stream.observer
        self.r.clock.sleep(.3)
        sample=CellSample(CellMeasurement('delayed',self.r.clock()-.25,3.65,-.1,25.),5,self.r.clock(),
            source='battery_bias_mock_sensor',quality='mock_independent_sensor',
            voltage_source='mock_sensor_voltage',temperature_source='mock_sensor_temperature')
        self.assertFalse(observer.accept(sample))
        self.assertEqual(observer.snapshot()['state'],'FAULT')
        self.assertIn('STALE',observer.error)

    def test_pause_policy_cannot_be_enabled_for_other_sources(self):
        with self.assertRaises(ValueError):LiveCellObserver(3.5,.8,mock_pause=True)

    def test_stale_feedback_sends_zero_without_resetting_native(self):
        feedback=PowerFeedback(self.policy,clock=self.r.clock);sock=Mock()
        payload=json.dumps({'power_limit':dict(enabled=True,state='ACTIVE',sequence=0,commanded=.59,applied=.59)}).encode()
        feedback.handle(row(),payload,('',1),sock)
        self.r.clock.sleep(.25);feedback.handle(row(),payload,('',1),sock)
        self.assertEqual(feedback.latest['vehicle_limit_requested_fraction'],0.)
        self.assertFalse(feedback.error)
        self.assertTrue(sock.sendto.call_args.args[0].decode().endswith('0.000000000 0'))
        self.r.clock.sleep(.3);feedback.handle(row(),payload,('',1),sock)
        self.assertTrue(feedback.error)


if __name__=='__main__':unittest.main()
