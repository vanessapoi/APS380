"""Existing Rint policy, SOC units and valid zero-SOP commissioning reports."""
import unittest
from cell_sop import RintEstimator,vehicle_mapping
from test_cell_sop import parameters,CELL,PROFILE,row
from battery_bias_feedback import propulsion_run_observed


class LowSocTests(unittest.TestCase):
    def test_existing_half_amp_model_is_not_voltage_limited(self):
        estimator=RintEstimator(parameters(maximum_discharge_A=.5))
        for soc in (.8,.4,.2,.1,.05,0.):
            s=estimator.estimate(soc,25.)
            self.assertGreater(s['sop_voltage_constraint_A'],.5)
            if soc>.12:self.assertEqual(s['sop_max_discharge_A'],.5)
            else:self.assertEqual(s['sop_max_discharge_W'],0.)

    def test_budget_transition_is_continuous_and_mapping_monotonic(self):
        estimator=RintEstimator(parameters(maximum_discharge_A=.5))
        previous=-1.
        for z in (0.,.05,.10,.12,.120001,.12001,.1201,.1202,.1204,.2,.4,.8):
            s=estimator.estimate(z,25.);f=vehicle_mapping(s['sop_max_discharge_W'],CELL,PROFILE,row())['sop_vehicle_fraction']
            self.assertGreaterEqual(f,previous);self.assertTrue(0<=f<=1);previous=f
        partial=estimator.estimate(.1202,25.)
        self.assertAlmostEqual(partial['sop_max_discharge_A'],.252)
        self.assertEqual(estimator.estimate(.12,25.)['sop_reason'],'SOC_RESERVE')

    def test_zero_sop_requires_valid_running_model_and_native_ack(self):
        sent=dict(vehicle_limit_sent_sequence=7,vehicle_limit_requested_fraction=0.,
            bias_controller_state='RUNNING',cell_observer_state='VALID',sop_model_valid=True)
        ack=dict(vehicle_limit_state='ACTIVE',vehicle_limit_ack_sequence=7,vehicle_limit_applied_fraction=0.)
        self.assertTrue(propulsion_run_observed([sent,ack]))
        for changes in (dict(bias_controller_state='READY'),dict(sop_model_valid=False),dict(cell_observer_state='STALE')):
            self.assertFalse(propulsion_run_observed([dict(sent,**changes),ack]))
        self.assertFalse(propulsion_run_observed([sent,dict(ack,vehicle_limit_ack_sequence=6)]))


if __name__=='__main__':unittest.main()
