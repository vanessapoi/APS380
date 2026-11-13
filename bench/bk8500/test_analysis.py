"""Synthetic recorded-file fixtures only; never a hardware test."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from analyze_session import load_run, render, slew_comparison
except ImportError:
    raise unittest.SkipTest('Analysis requires live-requirements.txt')


class AnalysisTests(unittest.TestCase):
    def capture(self, root):
        (root/'telemetry').mkdir(); (root/'instruments').mkdir()
        config = dict(device='hardware', max_current_A=1., reference_current_A=2.,
            voltage_min_V=4.5, voltage_max_V=5.5, max_power_W=5.5, control_hz=1.,
            slew_A_per_s=.02, approval=dict(approved_by='PRIVATE_FIXTURE_NAME'))
        trial = dict(device='hardware', telemetry=dict(statistics=dict(accepted=3), stale_intervals=[]),
            instrument=dict(faults=[], shutdown=dict(verified=True, measurement=dict(input_on=False))),
            acceptance=dict(telemetry='FAIL', instruments='PASS', normal_operation_passed=False))
        (root/'config.json').write_text(json.dumps(config)); (root/'trial.json').write_text(json.dumps(trial))
        rows=[]; telemetry=[]; events=[]
        for i in range(3):
            command = .01*i
            rows.append(dict(source_session='fixture', source_sequence=i, original_cell_current_A=-.2,
                commanded_load_A=command, previous_commanded_load_A=max(0, command-.01),
                measured_A=command+.001, power_limited_load_target_A=.1, readback_setting_A=command,
                measurement_received_host_s=10+i+.3, command_ack_received_host_s=10+i+.1,
                setpoint_read_received_host_s=10+i+.2, source_received_s=10+i,
                slew_budget_A=.02, slew_elapsed_s=1., voltage_V=5., power_W=(command+.001)*5,
                command_roundtrip_ms=60., cycle_ms=350., command_age_s=.3))
            telemetry.append(dict(session_id='fixture', sequence=i, cell_current_unclamped_A=-.2,
                received_qpc_s=10+i, soc=.8-i*.001, speed_mps=i, throttle=.2, brake=0.,pack_power_W=1000.))
            events.append(dict(event='cycle', state='RUNNING', last_operation='complete', mock_only=False))
        # Partial shutdown cycle is deliberately not a measured RUNNING sample.
        events.append(dict(event='cycle', state='DISARMED', last_operation='set_current', mock_only=False))
        for name, data in [('load_tracking.csv',rows),('telemetry/live_profile.csv',telemetry)]:
            with (root/name).open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
        (root/'instruments/control.jsonl').write_text('\n'.join(json.dumps(e) for e in events))

    def test_measured_command_error_and_failed_acceptance_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.capture(root)
            with patch.dict('sys.modules',{'serial':None}): run=load_run(root)
            self.assertEqual(run['metrics']['samples'],3)
            self.assertAlmostEqual(run['metrics']['measured_minus_command']['MAE_A'],.001)
            self.assertAlmostEqual(run['metrics']['measured_minus_command']['RMSE_A'],.001)
            self.assertFalse(run['metrics']['acceptance']['normal_operation_passed'])

    def test_report_omits_private_approval_and_marks_missing_sop(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.capture(root);run=load_run(root)
            render([run],root/'analysis',[])
            report=(root/'analysis/REPORT.md').read_text(encoding='utf-8')
            self.assertNotIn('PRIVATE_FIXTURE_NAME',report)
            self.assertNotIn('PRIVATE_FIXTURE_NAME',(root/'analysis/metrics.json').read_text())
            self.assertTrue((root/'analysis/soc_availability.png').exists())
            self.assertIn('no battery SOC',report)

    def test_provenance_and_event_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.capture(root)
            path=root/'instruments/control.jsonl';original=path.read_text()
            path.write_text(original.replace('"mock_only": false','"mock_only": true'))
            with self.assertRaises(ValueError):load_run(root)
            path.write_text(original.splitlines()[0])
            with self.assertRaises(ValueError):load_run(root)

    def test_mock_counterfactual_is_explicit_and_does_not_open_serial(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.capture(root);run=load_run(root)
            with patch.dict('sys.modules',{'serial':None}):
                result=slew_comparison(run,[.02,.05],.04)
            self.assertEqual(len(result),2)
            self.assertIn('not physical',result[0]['provenance'])


if __name__=='__main__':unittest.main()
