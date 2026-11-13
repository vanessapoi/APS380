from dataclasses import replace
import contextlib
import io
import json
from pathlib import Path
import sys
import time
import tempfile
import unittest
from unittest.mock import Mock,patch

from cell_scaling import CellParameters,scale_to_cell
from cell_sop import RintEstimator,RintParameters,RintPolicy,vehicle_mapping
from vehicle_power_limit import PowerFeedback,DemoPolicy

BASE=Path(__file__).parent
CONFIG=json.loads((BASE/'profiles/rint_sop_mock_example.json').read_text())
PROFILE=json.loads((BASE/'profiles/tesla_model3_rwd.json').read_text())
CELL=CellParameters(nominal_voltage_V=3.65,capacity_Ah=3.5,equivalent_pack_energy_Wh=50000,experiment_scale=.06)


def parameters(**changes):
    return replace(RintParameters(**CONFIG['parameters']),**changes)


def row():
    return dict(session_id='race',soc=.6,target_available=True,received_qpc_s=10.,
        motor_radps=1000.,throttle=1.,brake=0.,speed_mps=20.,motor_power_W=100000.)


def policy(**changes):
    p=RintPolicy(parameters(**changes),.8,25.)
    p.configure(CELL,PROFILE);return p


class RintTests(unittest.TestCase):
    def test_candidate_soc_units_and_range(self):
        e=RintEstimator(parameters())
        self.assertAlmostEqual(e.reference.voltage(0),3.163)
        self.assertAlmostEqual(e.reference.voltage(1),4.182)
        self.assertAlmostEqual(e.reference.voltage(.5),3.8040625)
        for bad in (-.01,50.,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):e.estimate(bad,25.)

    def test_current_limit_and_terminal_power(self):
        e=RintEstimator(parameters(ocv_margin_V=0,r0_margin_ohm=0,soc_margin_fraction=0))
        d=e.estimate(.8,25)
        self.assertEqual(d['sop_max_discharge_A'],1.)
        self.assertAlmostEqual(d['sop_terminal_at_max_power_V'],e.reference.voltage(.8)-.05)
        self.assertAlmostEqual(d['sop_max_discharge_W'],d['sop_terminal_at_max_power_V'])
        self.assertFalse(d['sop_physically_validated'])

    def test_voltage_limit(self):
        e=RintEstimator(parameters(r0_ohm=1.,r0_margin_ohm=0,ocv_margin_V=0,soc_margin_fraction=0,
            minimum_voltage_V=3.5,maximum_discharge_A=2.))
        d=e.estimate(.5,25)
        self.assertAlmostEqual(d['sop_max_discharge_A'],e.reference.voltage(.5)-3.5)
        self.assertAlmostEqual(d['sop_terminal_at_max_power_V'],3.5)

    def test_low_soc_and_explicit_charge_budget_units(self):
        e=RintEstimator(parameters(soc_margin_fraction=0))
        self.assertEqual(e.estimate(.1,25)['sop_max_discharge_W'],0)
        d=e.estimate(.100001,25)
        self.assertAlmostEqual(d['sop_max_discharge_A'],3600*3.5*.000001/10)
        self.assertEqual(d['sop_reason'],'CONSTRAINED_RINT_ESTIMATE')
        self.assertEqual(e.estimate(0,25)['sop_max_discharge_W'],0)

    def test_zero_current_and_ocv_below_floor(self):
        self.assertEqual(RintEstimator(parameters(maximum_discharge_A=0)).estimate(.8,25)['sop_max_discharge_W'],0)
        d=RintEstimator(parameters(minimum_voltage_V=4.5)).estimate(.8,25)
        self.assertEqual(d['sop_reason'],'VOLTAGE_FLOOR');self.assertEqual(d['sop_max_discharge_A'],0)

    def test_power_point_is_not_assumed_to_be_maximum_current(self):
        e=RintEstimator(parameters(minimum_voltage_V=.1,r0_ohm=1.,r0_margin_ohm=0,
            maximum_discharge_A=100.,soc_margin_fraction=0,ocv_margin_V=0))
        d=e.estimate(.8,25);u=e.reference.voltage(.8)
        self.assertLess(d['sop_current_at_max_power_A'],d['sop_max_discharge_A'])
        self.assertAlmostEqual(d['sop_max_discharge_W'],u*u/4)

    def test_temperature_validity_does_not_claim_physical_limits(self):
        e=RintEstimator(parameters())
        for t in (23,25,27):self.assertTrue(e.estimate(.8,t)['sop_model_valid'])
        for t in (22.9,27.1):
            d=e.estimate(.8,t);self.assertFalse(d['sop_model_valid']);self.assertEqual(d['sop_max_discharge_W'],0)
        with self.assertRaises(ValueError):RintEstimator(parameters(temperature_min_C=-20,temperature_max_C=60))

    def test_uncertainty_margins_only_reduce_power(self):
        base=RintEstimator(parameters()).estimate(.8,25)['sop_max_discharge_W']
        for change in (dict(ocv_margin_V=.1),dict(r0_margin_ohm=.1),dict(soc_margin_fraction=.1)):
            self.assertLess(RintEstimator(parameters(**change)).estimate(.8,25)['sop_max_discharge_W'],base)

    def test_invalid_parameters_are_rejected(self):
        for field,value in (('r0_ohm',0),('r0_ohm',-.1),('r0_ohm',float('nan')),('r0_ohm',True),
            ('capacity_Ah',0),('maximum_discharge_A',-1),('soc_budget_horizon_s',0),
            ('ocv_margin_V',-1),('r0_margin_ohm',-1),('soc_reserve_fraction',1),
            ('temperature_max_C',22),('parameter_status','validated')):
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):parameters(**{field:value})
        with self.assertRaises(ValueError):RintEstimator(parameters(ocv_margin_V=4))


class SopMappingTests(unittest.TestCase):
    def test_mapping_inverts_existing_sign_and_scaling_then_accounts_for_losses(self):
        k=-scale_to_cell(1.,CELL)['cell_power_requested_W'];self.assertAlmostEqual(k,1.533e-5)
        cell_power=k*(202000*.7/.92+300)
        d=vehicle_mapping(cell_power,CELL,PROFILE,row())
        self.assertAlmostEqual(d['sop_vehicle_fraction'],.7)
        self.assertEqual(d['sop_motor_requested_unlimited_W'],202000.)
        self.assertGreater(k,0);self.assertLess(scale_to_cell(1.,CELL)['cell_current_unclamped_A'],0)

    def test_no_delivered_power_ratio_oscillation(self):
        r=row();a=vehicle_mapping(2.,CELL,PROFILE,r)
        r['motor_power_W']=1000.;b=vehicle_mapping(2.,CELL,PROFILE,r)
        self.assertEqual(a['sop_vehicle_fraction'],b['sop_vehicle_fraction'])
        self.assertGreater(a['sop_vehicle_fraction'],0);self.assertLess(a['sop_vehicle_fraction'],1)

    def test_full_power_and_unserved_auxiliary_budget(self):
        self.assertEqual(vehicle_mapping(10.,CELL,PROFILE,row())['sop_vehicle_fraction'],1.)
        d=vehicle_mapping(0.,CELL,PROFILE,row())
        self.assertEqual(d['sop_vehicle_fraction'],0);self.assertFalse(d['sop_auxiliary_budget_satisfied'])

    def test_motor_request_respects_existing_brake_and_regen_pedal_conditions(self):
        for change in (dict(brake=1.),dict(throttle=0.),dict(motor_radps=-100.)):
            r=dict(row(),**change)
            self.assertEqual(vehicle_mapping(2.,CELL,PROFILE,r)['sop_motor_requested_unlimited_W'],0)

    def test_policy_keeps_cell_soc_separate_from_native_pack_soc(self):
        p=policy(maximum_discharge_A=.5)
        soc,f,d=p.evaluate_row(row())
        self.assertEqual(soc,.8);self.assertNotEqual(soc,row()['soc'])
        self.assertTrue(0<f<1);self.assertFalse(d['sop_physically_validated'])
        self.assertLessEqual(f,d['sop_unquantized_vehicle_fraction'])

    def test_invalid_model_latches_feedback_until_valid_state_and_explicit_reset(self):
        p=policy();b=PowerFeedback(p,clock=lambda:10.)
        payload=json.dumps(dict(power_limit=dict(enabled=True,state='ACTIVE',commanded=1.,applied=1.,sequence=0))).encode()
        sock=Mock();b.handle(row(),payload,('127.0.0.1',1),sock);self.assertTrue(sock.sendto.called)
        p.mock_temperature_C=99.;sock.reset_mock();b.handle(row(),payload,('127.0.0.1',1),sock)
        self.assertIn('SOP model unavailable',b.error);sock.sendto.assert_not_called()
        p.mock_temperature_C=25.;b.handle(row(),payload,('127.0.0.1',1),sock);sock.sendto.assert_not_called()
        b.request_reset();b.handle(row(),payload,('127.0.0.1',1),sock)
        self.assertEqual(sock.sendto.call_args.args[0].split()[-1],b'1')
        self.assertFalse(b.error)

    def test_invalid_mock_state_produces_unavailable_diagnostics_not_nan(self):
        p=policy();p.mock_soc=float('nan')
        soc,f,d=p.evaluate_row(row())
        self.assertIsNone(soc);self.assertEqual(f,0);self.assertFalse(d['sop_model_valid'])
        json.dumps(d,allow_nan=False)

    def test_cli_requires_explicit_mock_config_and_preserves_demo(self):
        sys.path.insert(0,str(BASE.parent/'scripts'))
        from run_vehicle_power_limit import parse_args
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):parse_args(['--policy','rint'])
        self.assertIsInstance(parse_args([]).policy,DemoPolicy)
        p=parse_args(['--policy','rint','--sop-config',str(BASE/'profiles/rint_sop_mock_example.json')]).policy
        self.assertIsInstance(p,RintPolicy)

    def test_dashboard_labels_assumptions_and_estimates(self):
        import tkinter as tk
        from live_display import LiveDisplay
        from torcs_live import LiveReceiver
        try:
            root=tk.Tk();root.withdraw();root.destroy()
        except tk.TclError as exc:self.skipTest(str(exc))
        p=policy(maximum_discharge_A=.5);b=PowerFeedback(p,clock=lambda:10.)
        r=row();r['received_qpc_s']=time.perf_counter()
        payload=json.dumps(dict(power_limit=dict(enabled=True,state='ACTIVE',commanded=.5,applied=.5,sequence=0))).encode()
        b.handle(r,payload,('127.0.0.1',1),Mock())
        with tempfile.TemporaryDirectory() as folder:
            receiver=LiveReceiver(0,Path(folder)/'telemetry',power_feedback=b)
            try:
                display=LiveDisplay(receiver,finished=lambda:True);display.root.withdraw();display.refresh()
                text=display.values.cget('text')
                for label in ('MOCK supplied','OCV [candidate]','R0 [ASSUMED]','SOP [EST]','unlimited'):
                    self.assertIn(label,text)
                display.root.destroy()
            finally:
                with patch('torcs_live.write_report',return_value={}):receiver.close()


if __name__=='__main__':unittest.main()
