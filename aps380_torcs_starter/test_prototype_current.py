"""Prototype KCL, fixed-source behavior, limits and sign-contract regressions."""
from dataclasses import asdict, replace
import json
import unittest

from instrument_control import ControlConfig, Demand, InstrumentCoordinator, LatestDemand, State
from mock_instruments import MockPSU, MockBK8500, MockIsolation
from prototype_current_config import PROTOTYPE, current_metadata
from test_instrument_control import Clock
from test_torcs_live import CONFIG, PROFILE, packet, accept
from torcs_live import LiveProcessor
from types import SimpleNamespace
from unittest.mock import Mock


class PrototypeCurrentTest(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.psu=MockPSU(clock=self.clock,sleep=self.clock.sleep,response_delay_s=0.)
        self.load=MockBK8500(clock=self.clock,sleep=self.clock.sleep,response_delay_s=0.)
        self.c=InstrumentCoordinator(self.psu,self.load,MockIsolation(self.psu,self.load),
            replace(PROTOTYPE,slew_rate_A_per_s=1000.,neutral_hold_s=.01),clock=self.clock)

    def drive(self,target):
        if self.c.state==State.DISARMED:self.c.arm()
        for _ in range(400):
            self.clock.sleep(.1)
            self.c.step(Demand(target,self.clock(),'prototype',0))
            self.assertNotEqual(self.c.state,State.FAULT,self.c.fault_reason)
            if self.c.state==State.RUNNING and self.c.phase=='TRACK' and abs(self.c.applied_target-target)<1e-9:return
        self.fail('Target did not settle')

    def test_effective_prototype_and_no_final_design_limits(self):
        self.assertEqual((PROTOTYPE.psu_current_min_A,PROTOTYPE.psu_current_max_A,PROTOTYPE.psu_cc_setpoint_A),(0.,1.,1.))
        self.assertEqual((PROTOTYPE.eload_current_min_A,PROTOTYPE.eload_current_max_A),(0.,3.))
        self.assertEqual((PROTOTYPE.battery_current_min_A,PROTOTYPE.battery_current_max_A),(-2.,1.))
        self.assertEqual((self.psu.max_current_A,self.load.max_current_A),(1.,3.))
        self.assertEqual(current_metadata()['cell_current_convention'],'charging_positive')

    def test_kcl_endpoints_neutral_and_fixed_psu_setpoint(self):
        for cell,load in ((-2.,3.),(0.,1.),(1.,0.),(-.7,1.7),(.4,.6)):
            self.drive(cell)
            self.assertAlmostEqual(self.load.setpoint_A,load)
            self.assertAlmostEqual(self.c.snapshot()['mock_cell_current_A'],cell)
            self.assertTrue(self.load.output_enabled)  # 0 A is valid while enabled
        commands=[e['setpoint_A'] for e in self.psu.log if e['event']=='command']
        self.assertEqual(commands,[1.])
        self.assertTrue(all(0<=e['setpoint_A']<=3 for e in self.load.log if e['event']=='command'))
        self.c.disarm()
        self.assertTrue(self.c.snapshot()['shutdown_verified'])
        self.assertTrue(self.c.isolation.is_open)

    def test_measured_psu_current_not_the_setpoint(self):
        self.drive(.4)
        self.psu.current_offset_A=-.02
        self.clock.sleep(.1)
        self.c.step(Demand(.4,self.clock(),'prototype',1))
        self.assertAlmostEqual(self.load.setpoint_A,.58)
        self.assertAlmostEqual(self.c.last['branch_net_A'],.4)
        self.assertEqual(self.psu.setpoint_A,1.)

    def test_zero_eload_setpoint_estop_and_explicit_recovery(self):
        self.drive(1.)
        self.assertEqual(self.load.setpoint_A,0.)
        self.assertTrue(self.load.output_enabled)
        self.c.emergency_stop()
        self.assertEqual(self.c.state,State.FAULT)
        self.assertTrue(self.c.shutdown_verified)
        self.assertFalse(self.psu.output_enabled or self.load.output_enabled)
        self.assertTrue(self.c.isolation.is_open)
        self.c.recover()
        self.assertEqual(self.c.state,State.DISARMED)
        self.drive(1.)
        self.assertEqual(self.load.setpoint_A,0.)
        self.assertEqual(self.c.state,State.RUNNING)

    def test_infeasible_charge_is_rejected_before_any_load_command(self):
        self.drive(0.)
        self.psu.current_offset_A=-.2
        before=sum(e['event']=='command' for e in self.load.log)
        self.clock.sleep(.1)
        self.c.step(Demand(1.,self.clock(),'prototype',1))
        self.assertEqual(self.c.fault_reason,'INFEASIBLE_CURRENT')
        self.assertEqual(sum(e['event']=='command' for e in self.load.log),before)
        self.assertTrue(self.c.shutdown_verified)

    def test_overcurrent_is_checked_before_compensating_for_branch_failure(self):
        self.drive(-2.)
        self.psu.current_offset_A=-1.  # source collapses while load still draws 3 A
        self.clock.sleep(.1)
        self.c.step(Demand(-2.,self.clock(),'prototype',1))
        self.assertEqual(self.c.fault_reason,'MEASURED_DIRECTIONAL_LIMIT')
        self.assertEqual(self.c.last['pre_control_cell_current_A'],-3.)
        self.assertTrue(self.c.shutdown_verified)

    def test_psu_setpoint_tampering_and_cv_fault(self):
        for failure in ('setpoint','cv'):
            self.setUp();self.drive(0.)
            if failure=='setpoint':self.psu.set_current(.8,.02)
            else:self.psu.cv_available_A=.8
            self.c.step(Demand(0.,self.clock(),'prototype',1))
            self.assertEqual(self.c.fault_reason,'PSU_SETPOINT_CHANGED' if failure=='setpoint' else 'PSU_NOT_CC')
            self.assertTrue(self.c.shutdown_verified)

    def test_slowest_full_range_reversal_fits_validated_deadline(self):
        self.c.config=PROTOTYPE
        self.drive(-2.)
        self.drive(1.)
        self.assertAlmostEqual(self.c.last['branch_net_A'],1.)
        with self.assertRaises(ValueError):replace(PROTOTYPE,transition_timeout_s=6.)
        with self.assertRaises(ValueError):replace(PROTOTYPE,eload_current_min_A=1.1)

    def test_native_conversion_once_and_original_telemetry_preserved(self):
        for power,expected in ((100000.,-.42),(-100000.,.42),(0.,0.)):
            p=LiveProcessor(PROFILE,CONFIG)
            frame=packet(p,power=power)
            r=accept(p,frame)
            self.assertEqual(r['pack_power_W'],power)
            self.assertAlmostEqual(r['pack_current_A'],power/355)
            self.assertEqual(r['native_csv'],frame['csv'])
            self.assertAlmostEqual(r['cell_current_unclamped_A'],expected)
            box=LatestDemand();box.publish(r)
            self.assertAlmostEqual(box.snapshot()[0].current_A,expected)
            self.assertEqual(r['current_schema_version'],2)
        box.publish(dict(r,cell_current_convention='discharge_positive'))
        self.assertIsNone(box.snapshot()[0])
        self.assertEqual(box.snapshot()[1],'INVALID_CURRENT_CONVENTION')

    def test_original_and_limited_values_survive_mailbox(self):
        p=LiveProcessor(PROFILE,CONFIG)
        r=accept(p,packet(p,power=1e6))
        box=LatestDemand();box.publish(r)
        d=box.snapshot()[0]
        self.assertAlmostEqual(d.requested_current_A,-4.2)
        self.assertEqual(d.current_A,-2.)

    def test_dashboard_labels_targets_readbacks_and_retained_state_without_tk(self):
        # Presentation logic only. The real Tk initialization smoke test remains
        # separate and may skip when the test environment lacks Tcl resources.
        from live_display import LiveDisplay
        import time
        self.drive(-.7)
        p=LiveProcessor(PROFILE,CONFIG)
        p.accept(json.dumps(packet(p,power=100000.)).encode(),time.perf_counter())
        ui=LiveDisplay.__new__(LiveDisplay)
        ui.receiver=SimpleNamespace(processor=p,output='mock-test',failed=None)
        ui.mock_service=SimpleNamespace(latest=self.c.snapshot())
        ui.mock_label=Mock();ui.state_label=Mock();ui.values=Mock();ui.details=Mock()
        ui.root=Mock();ui.draw_chart=Mock();ui.finished=lambda:False;ui.deadline=float('inf')
        ui.refresh()
        text=ui.values.config.call_args.kwargs['text']
        self.assertIn('Cell (+charge / -discharge)',text)
        self.assertIn('Native pack (+draw)',text)
        self.assertIn('applied -0.7000 / measured -0.7000 A',text)
        self.assertIn('PSU set/read 1.0000/1.0000 A',text)
        self.assertIn('eLoad set/read 1.7000/1.7000 A',text)
        self.c.disarm();ui.mock_service.latest=self.c.snapshot();ui.refresh()
        self.assertIn('RETAINED; NOT LIVE',ui.values.config.call_args.kwargs['text'])
        self.assertIn('measured +0.0000 A',ui.values.config.call_args.kwargs['text'])


if __name__=='__main__':unittest.main()
