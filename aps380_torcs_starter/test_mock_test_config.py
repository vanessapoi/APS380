"""Mock experiment validation, shared effective parameters and immutable defaults."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mock_test_config as config
from cell_scaling import scale_to_cell
from cell_sop import vehicle_mapping
from torcs_live import LiveReceiver, LiveProcessor

EXAMPLE=config.BASE/'profiles/mock_test_20_percent_manual.json'


class MockTestConfigTests(unittest.TestCase):
    def test_required_range_math_and_capability_diagnostics(self):
        self.assertEqual(config.required_eload_range(5.,1.,1.),dict(minimum_A=0.,maximum_A=6.))
        self.assertEqual(config.required_eload_range(2.,1.,.2),dict(minimum_A=-.8,maximum_A=2.2))
        for args in ((-1.,1.,1.),(1.,True,1.),(1.,1.,float('nan'))):
            with self.assertRaises(ValueError):config.required_eload_range(*args)
        with self.assertRaisesRegex(ValueError,'selected mock capability'):
            self.load(eload_max_A=2.5)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'experiment.json'
        self.data=json.loads(EXAMPLE.read_text())

    def load(self,**overrides):
        self.path.write_text(json.dumps(dict(self.data,**overrides)))
        return config.load_mock_test_config(self.path)

    def test_example_matches_existing_manual_twenty_percent(self):
        profiles=list((config.BASE/'profiles').glob('*.json'))
        before={p:hashlib.sha256(p.read_bytes()).digest() for p in profiles}
        resolved=self.load()
        old=json.loads((config.BASE/'profiles/rint_sop_20_percent_mock.json').read_text())
        self.assertEqual(asdict(resolved.control),asdict(config.BIAS_CONTROL))
        for key in ('parameters','mock_state','live_mock_measurements'):
            self.assertEqual(resolved.model[key],old[key])
        self.assertEqual(resolved.source_A,1.)
        self.assertFalse(resolved.audit['physical_operation_enabled'])
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).digest() for p in profiles})

    def test_altered_parameters_share_receiver_scaler_and_inverse_mapping(self):
        resolved=self.load(initial_soc_fraction=.4,maximum_charge_A=.2,maximum_discharge_A=.6,
            sop_discharge_ceiling_A=.4,mock_psu_contribution_A=.4,eload_max_A=1.5,experiment_scale=.12)
        receiver=LiveReceiver(0,Path(self.tmp.name)/'telemetry',current_config=resolved.control,
                              scaling_config=resolved.scaling)
        self.addCleanup(receiver.log.close);self.addCleanup(receiver.socket.close)
        p=receiver.processor
        self.assertEqual(p.cell.discharge_limit_A,.6);self.assertEqual(p.cell.charge_limit_A,.2)
        self.assertEqual(p.cell.experiment_scale,.12)
        self.assertEqual(p.cell.capacity_Ah,resolved.model['parameters']['capacity_Ah'])
        scale=-scale_to_cell(1.,p.cell)['cell_power_requested_W']
        row=dict(throttle=1.,brake=0.,speed_mps=20.,soc=.8,motor_power_W=0.,motor_radps=100.)
        self.assertEqual(vehicle_mapping(1.,p.cell,p.profile,row)['sop_cell_per_pack_scale'],scale)
        self.assertEqual(resolved.audit['effective']['control'],asdict(resolved.control))
        self.assertEqual(json.loads((receiver.output/'scaling_config.json').read_text()),resolved.scaling)
        self.assertEqual(resolved.control.psu_cc_setpoint_A,1.)
        self.assertEqual(resolved.source_A,.4)  # Limit is not the imposed contribution.

    def test_unknown_missing_and_wrong_purpose_rejected(self):
        for overrides in ({'port':'COM10'},{'slew_A_per_s':1.},{'capacity_Ah':1.},
                          {'purpose':'hardware'},{'schema_version':True},{'schema_version':2}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):self.load(**overrides)
        del self.data['experiment_scale']
        with self.assertRaises(ValueError):self.load()

    def test_nonfinite_boolean_text_and_duplicate_rejected(self):
        for value in (float('nan'),float('inf'),True,'0.2',None,10**500):
            with self.subTest(value=value),self.assertRaises(ValueError):self.load(initial_soc_fraction=value)
        self.path.write_text('{"purpose":"a","purpose":"b"}')
        with self.assertRaisesRegex(ValueError,'Duplicate'):config.load_mock_test_config(self.path)

    def test_ranges_and_feasibility(self):
        for overrides in ({'initial_soc_fraction':20},{'maximum_charge_A':1.1},
            {'maximum_discharge_A':5.},{'sop_discharge_ceiling_A':2.1},
            {'mock_psu_contribution_A':1.1},{'mock_psu_contribution_A':.2},
            {'eload_max_A':6.},{'eload_min_A':1.1},{'eload_max_A':2.9},
            {'experiment_scale':0.},{'experiment_scale':1.1}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):self.load(**overrides)
        with self.assertRaisesRegex(ValueError,'configured PSU bias'):
            self.load(eload_max_A=.9,maximum_discharge_A=.5,maximum_charge_A=.1,mock_psu_contribution_A=.2)
        # A custom source-limited experiment must explicitly reduce its envelope.
        self.load(mock_psu_contribution_A=.2,maximum_charge_A=.1)

    def test_timing_constraints_and_capacity_consistency_not_bypassed(self):
        with patch.object(config,'BIAS_CONTROL',replace(config.BIAS_CONTROL,ready_timeout_s=.5)):
            with self.assertRaisesRegex(ValueError,'READY timeout'):self.load()
        processor=config.LiveProcessor
        def mismatch(*a,**kw):
            result=processor(*a,**kw);result.cell=replace(result.cell,capacity_Ah=3.)
            return result
        with patch.object(config,'LiveProcessor',side_effect=mismatch):
            with self.assertRaisesRegex(ValueError,'capacity'):self.load()

    def test_default_receiver_cell_scaling_unchanged(self):
        before=asdict(config.BIAS_CONTROL)
        self.load(maximum_charge_A=.1,maximum_discharge_A=.5,sop_discharge_ceiling_A=.3,
                  mock_psu_contribution_A=.2,experiment_scale=.1)
        profile=(config.BASE/'profiles/tesla_model3_rwd.json').read_bytes()
        scaling=json.loads((config.BASE/'profiles/live_scaling_demo.json').read_text())
        default=LiveProcessor(profile,scaling)
        self.assertEqual(default.cell.discharge_limit_A,2.)
        self.assertEqual(default.cell.charge_limit_A,1.)
        self.assertEqual(default.cell.experiment_scale,.06)
        self.assertEqual(asdict(config.BIAS_CONTROL),before)


if __name__=='__main__':unittest.main()
