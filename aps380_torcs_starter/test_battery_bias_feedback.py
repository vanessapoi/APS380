"""Feedback composition tests; no transports or extra SOC observers."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from battery_bias import BiasCellStream
from battery_bias_feedback import BiasRintPolicy
import test_battery_bias as rig
from test_cell_sop import CELL,PROFILE,row
from vehicle_power_limit import PowerFeedback


class BiasFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.r=rig.BiasTest();self.r.setUp()
        config=json.loads((Path(__file__).parent/'profiles/rint_sop_live_mock_example.json').read_text())
        self.stream=BiasCellStream(config,self.r.clock)
        self.service=SimpleNamespace(cell_stream=self.stream,latest=self.r.c.snapshot())
        self.policy=BiasRintPolicy(self.service);self.policy.configure(CELL,PROFILE)

    def sample(self,current=0.):
        self.service.latest=self.r.step(current)
        self.stream.update(self.service.latest)

    def test_shared_observer_signed_current_and_evolving_mapping(self):
        self.assertIs(self.policy.observer,self.stream.observer)
        self.assertIs(self.policy.estimator,self.stream.estimator)
        self.r.ready();self.sample()
        first=self.policy.evaluate_row(row())
        for _ in range(100):self.sample(-.1)
        last=self.policy.evaluate_row(row())
        self.assertLess(last[0],first[0]);self.assertLess(last[1],first[1])
        self.assertEqual(last[2]['cell_measurement_source'],'battery_bias_mock_sensor')
        for _ in range(180):self.sample(.1)
        self.assertGreater(self.policy.evaluate_row(row())[0],last[0])

    def test_initial_waiting_disarm_stop_and_explicit_reset(self):
        feedback=PowerFeedback(self.policy,clock=self.r.clock);sock=Mock()
        payload=json.dumps({'power_limit':dict(enabled=True,state='ACTIVE',sequence=0,commanded=0.,applied=0.)}).encode()
        feedback.handle(row(),payload,('127.0.0.1',1),sock)
        self.assertEqual(feedback.latest['vehicle_limit_requested_fraction'],0.)
        self.r.ready();self.sample();feedback.handle(row(),payload,('',1),sock)
        self.assertGreater(feedback.latest['vehicle_limit_requested_fraction'],0.)
        self.r.c.disarm();self.service.latest=self.r.c.snapshot();self.stream.update(self.service.latest)
        feedback.handle(row(),payload,('',1),sock);self.assertTrue(feedback.error)
        self.r.ready();self.sample();n=sock.sendto.call_count
        feedback.handle(row(),payload,('',1),sock);self.assertEqual(sock.sendto.call_count,n)
        feedback.request_reset();feedback.handle(row(),payload,('',1),sock)
        self.assertGreater(sock.sendto.call_count,n)
        self.r.c.emergency_stop();self.service.latest=self.r.c.snapshot();self.stream.update(self.service.latest)
        self.assertEqual(self.policy.evaluate_row(row())[1],0.)
        feedback.request_stop();feedback.handle(row(),payload,('',1),sock)
        self.assertFalse(feedback.error)  # Intentional zero shutdown does not invent a new model fault.

    def test_stale_observer_has_zero_fraction(self):
        self.r.ready();self.sample();self.r.clock.sleep(1.)
        soc,fraction,details=self.policy.evaluate_row(row())
        self.assertEqual(fraction,0.);self.assertFalse(details['sop_model_valid'])


if __name__=='__main__':unittest.main()
