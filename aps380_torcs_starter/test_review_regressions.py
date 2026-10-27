"""Confirmed review defects: contract ambiguity, reporting and timing budgets."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from instrument_control import Demand, InstrumentCoordinator, LatestDemand, State
from mock_instruments import MockPSU, MockBK8500, MockIsolation
from prototype_current_config import PROTOTYPE, current_metadata
from test_instrument_control import Clock
from test_torcs_live import CONFIG, PROFILE, packet, accept
from test_trial_acceptance import running_evidence
from torcs_live import LiveProcessor, LiveReceiver, describe_stale_intervals
from trial_acceptance import instrument_acceptance


class ReviewRegressions(unittest.TestCase):
    def test_mailbox_rejects_undeclared_legacy_and_other_schema_currents(self):
        base=dict(target_available=True,cell_current_command_A=.5,received_qpc_s=10.,session_id='test',sequence=0)
        box=LatestDemand()
        for metadata in ({},{'cell_current_convention':'discharge_positive','current_schema_version':1},
                         dict(current_metadata(),current_schema_version=1),
                         dict(current_metadata(),current_schema_version=True)):
            box.publish(dict(base,**current_metadata()))
            previous,_,revision=box.snapshot()
            box.publish(dict(base,**metadata))
            self.assertIsNone(box.snapshot()[0])
            self.assertFalse(box.valid(previous,revision))

    def test_live_limit_override_is_rejected_instead_of_disagreeing_with_control(self):
        config=copy.deepcopy(CONFIG);config['cell']['charge_limit_A']=3.
        with self.assertRaisesRegex(ValueError,'centralized'):
            LiveProcessor(PROFILE,config)

    def test_narrower_control_limit_reaches_scaling_and_effective_report(self):
        config=replace(PROTOTYPE,battery_current_max_A=.25)
        p=LiveProcessor(PROFILE,CONFIG,current_config=config)
        row=accept(p,packet(p,power=-1e6))
        self.assertAlmostEqual(row['cell_current_unclamped_A'],4.2)
        self.assertEqual(row['cell_current_command_A'],.25)
        self.assertEqual(p.cell.charge_limit_A,.25)
        with tempfile.TemporaryDirectory() as directory:
            r=LiveReceiver(0,Path(directory)/'trial',current_config=config)
            report=r.close()
            self.assertEqual(report['prototype_current_config']['battery_current_max_A'],.25)
            saved=json.loads((r.output/'effective_current_config.json').read_text())
            self.assertEqual(saved['battery_current_max_A'],.25)

    def test_valid_io_delays_do_not_make_a_full_reversal_time_out(self):
        clock=Clock();options=dict(clock=clock,sleep=clock.sleep,response_delay_s=0.,communication_delay_s=.015)
        psu,load=MockPSU(**options),MockBK8500(**options)
        c=InstrumentCoordinator(psu,load,MockIsolation(psu,load),clock=clock)
        c.arm()
        for target in (-2.,1.):
            for _ in range(400):
                clock.sleep(.1);c.step(Demand(target,clock(),'delayed',0))
                self.assertNotEqual(c.state,State.FAULT,c.fault_reason)
                if c.state==State.RUNNING and c.phase=='TRACK' and abs(c.applied_target-target)<1e-9:break
            else:self.fail('Full-range target did not settle')
        self.assertAlmostEqual(c.last['branch_net_A'],1.)
        self.assertEqual(psu.setpoint_A,1.)
        self.assertGreater(PROTOTYPE.transition_timeout_s,PROTOTYPE.minimum_transition_timeout_s)

    def test_configurable_nonzero_branch_minima_do_not_break_isolated_startup(self):
        clock=Clock();opts=dict(clock=clock,sleep=clock.sleep,response_delay_s=.02)
        psu,load=MockPSU(**opts),MockBK8500(**opts)
        config=replace(PROTOTYPE,eload_current_min_A=.5,psu_current_min_A=.2)
        c=InstrumentCoordinator(psu,load,MockIsolation(psu,load),config,clock)
        c.arm();c.step(Demand(0.,clock(),'startup',0))
        self.assertEqual(c.state,State.READY)
        self.assertTrue(c.isolation.is_open)
        for _ in range(40):
            clock.sleep(.1);c.step(Demand(0.,clock(),'startup',0))
            self.assertNotEqual(c.state,State.FAULT,c.fault_reason)
            if c.state==State.RUNNING:break
        self.assertEqual(c.state,State.RUNNING)
        self.assertTrue(all(.5<=e['setpoint_A']<=3. for e in load.log if e['event']=='command'))

    def test_large_numerical_tolerance_cannot_hide_infeasibility(self):
        with self.assertRaises(ValueError):replace(PROTOTYPE,numeric_tolerance_A=.1)

    def test_missing_running_evidence_is_not_a_control_pass(self):
        final=dict(state='DISARMED',fault='',shutdown_verified=True,shutdown_errors=[],
                   isolation=dict(is_open=True,outputs_disabled=True))
        event=dict(final,state='RUNNING',tracking_error_A=0.,direction_ok=True,command_age_s=.01,
                   psu_measurement_age_s=.01,load_measurement_age_s=.01,transactions={})
        report=instrument_acceptance([event],PROTOTYPE,final,require_running=True)
        self.assertFalse(report['passed'])
        self.assertFalse(report['checks']['running_records_complete'])
        self.assertEqual(report['control_status'],'FAIL')
        event=running_evidence(final)
        event['psu']=dict(event['psu'],status={})
        report=instrument_acceptance([event],PROTOTYPE,final,require_running=True)
        self.assertFalse(report['passed'])
        self.assertFalse(report['checks']['running_records_complete'])

    def test_report_recomputes_mapping_and_checks_current_schema(self):
        final=dict(state='DISARMED',fault='',shutdown_verified=True,shutdown_errors=[],
                   isolation=dict(is_open=True,outputs_disabled=True))
        good=running_evidence(final)
        self.assertTrue(instrument_acceptance([good],PROTOTYPE,final,require_running=True)['passed'])
        for change,key in ((dict(branch_net_A=-.101),'readback_mapping_consistent'),
                           (dict(current_schema_version=1),'current_convention_consistent'),
                           (dict(active_direction=-1),'current_direction_expected')):
            report=instrument_acceptance([dict(good,**change)],PROTOTYPE,final,require_running=True)
            self.assertFalse(report['passed'])
            self.assertFalse(report['checks'][key])

    def test_genuine_startup_or_terminal_silence_still_becomes_stale(self):
        p=LiveProcessor(PROFILE,CONFIG,True)
        accept(p,packet(p))
        self.assertTrue(p.state(10.51).startswith('STALE'))
        following=packet(p,.02,1);following['sender_qpc_s']=13.34
        accept(p,following)
        self.assertEqual(p.stats['missing'],0)
        self.assertEqual(p.state(13.35),'RECEIVING')
        self.assertTrue(p.state(13.9).startswith('STALE'))

    def test_stale_diagnostics_preserve_both_initial_and_terminal_intervals(self):
        def row(seq,t,host):return dict(sequence=seq,time_s=t,received_qpc_s=host,sender_qpc_s=host-.001)
        events=[dict(kind='sample',row=row(0,0.,10.)),dict(kind='state',state='STALE',host_qpc_s=10.55),
                dict(kind='sample',row=row(1,.02,13.34)),dict(kind='state',state='RECEIVING',host_qpc_s=13.341),
                dict(kind='state',state='STALE',host_qpc_s=13.9),dict(kind='state',state='STOPPED',host_qpc_s=18.)]
        intervals=describe_stale_intervals(events)
        self.assertEqual([i['position'] for i in intervals],['initial_sample_gap','terminal_silence'])
        self.assertAlmostEqual(intervals[0]['host_sample_gap_s'],3.34)
        self.assertAlmostEqual(intervals[0]['sender_sample_gap_s'],3.34)
        self.assertIsNone(intervals[1]['next_sequence'])
        self.assertAlmostEqual(intervals[1]['silence_at_stop_s'],4.66)


if __name__=='__main__':unittest.main()
