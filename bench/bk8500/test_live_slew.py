"""Elapsed-time CC slew regressions; fake clocks and mock instruments only."""
from dataclasses import replace
import sys
import unittest

if sys.version_info < (3, 10):
    raise unittest.SkipTest('Live control requires Python 3.10+')

from live_control import LiveConfig, LiveController, LatestDemand, MockLiveLoad, slew_target
from test_live_control import Clock, row


def config(**changes):
    return replace(LiveConfig(max_current_A=.1, reference_current_A=.05,
        max_power_W=.6, slew_A_per_s=.02, tracking_tolerance_A=.01), **changes)


class QuantizedSlewTests(unittest.TestCase):
    def test_observed_short_interval_no_longer_exceeds_rate(self):
        value,budget=slew_target(.08,0.,.1,.9694413,config())
        self.assertEqual(value,.0607)
        self.assertLessEqual(.08-value,.02*.9694413)
        self.assertLessEqual(.08-value,budget)

    def test_subquantum_budget_holds_in_both_directions(self):
        for previous,target in ((0.,.1),(.1,0.)):
            with self.subTest(previous=previous):
                value,_=slew_target(previous,target,.1,.0049,config())
                self.assertEqual(value,previous)  # 98 uA cannot afford 100 uA.
                value,_=slew_target(previous,target,.1,.0051,config())
                self.assertAlmostEqual(abs(value-previous),.0001)

    def test_fractional_target_and_ceiling_never_rounded_up(self):
        self.assertEqual(slew_target(0.,.00009,.1,1.,config())[0],0.)
        self.assertEqual(slew_target(.099,.1,.09999,1.,config())[0],.0999)

    def test_long_delay_cannot_bank_a_catch_up_jump(self):
        self.assertEqual(slew_target(0.,.1,.1,100.,config())[0],.02)
        self.assertEqual(slew_target(.1,0.,.1,100.,config())[0],.08)

    def test_hard_ceiling_conflict_and_invalid_clock_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError,'SLEW_ENVELOPE_INFEASIBLE'):
            slew_target(.1,0.,.05,.1,config())
        for elapsed in (-1.,float('inf'),float('nan')):
            with self.assertRaisesRegex(RuntimeError,'INVALID_SLEW_CLOCK'):
                slew_target(0.,.1,.1,elapsed,config())

    def test_varied_elapsed_values_remain_inside_both_envelopes(self):
        for previous in (0.,.0001,.0499,.1):
            for target in (0.,.00009,.05006,.1):
                for elapsed in (0.,.001,.0049,.0051,.499,.9694413,1.,3.):
                    value,budget=slew_target(previous,target,.1,elapsed,config())
                    self.assertLessEqual(abs(value-previous),budget+1e-15)
                    self.assertTrue(0<=value<=.1)
                    self.assertAlmostEqual(value*10000,round(value*10000))


class ControllerSlewTests(unittest.TestCase):
    def controller(self, **changes):
        clock=Clock();cfg=config(**changes)
        device=MockLiveLoad(cfg,clock,clock.sleep,delay_s=.01)
        box=LatestDemand();c=LiveController(device,box,cfg,clock,clock.sleep)
        c.initialize();box.publish(row(clock,-.05));self.assertTrue(c.arm(),c.fault)
        return clock,device,box,c

    def cycle(self,clock,box,c,demand,wait):
        clock.sleep(wait);box.publish(row(clock,demand));c.cycle()
        self.assertEqual(c.state,'RUNNING',c.fault)
        e=c.last
        step=abs(e['commanded_load_A']-e['previous_commanded_load_A'])
        self.assertLessEqual(step,e['slew_budget_A']+1e-15)
        self.assertLessEqual(step,c.config.slew_A_per_s*(e['command_started_host_s']-e['slew_reference_ack_host_s'])+1e-15)
        self.assertEqual(e['readback_setting_A'],e['commanded_load_A'])
        return dict(e)

    def test_variable_latency_rapid_reversals_and_repeated_commands(self):
        clock,device,box,c=self.controller()
        previous=None
        for i in range(40):
            device.delay_s=(.01,.02,.064)[i%3]
            e=self.cycle(clock,box,c,-.05 if i%8<4 else .04,(.0,.3,.6,.9694413)[i%4])
            if previous:
                self.assertEqual(e['slew_reference_ack_host_s'],previous['command_ack_received_host_s'])
                self.assertLessEqual(abs(e['commanded_load_A']-previous['commanded_load_A']),
                    c.config.slew_A_per_s*(e['command_started_host_s']-previous['command_started_host_s'])+1e-15)
            previous=e
        c.stop();self.assertTrue(c.shutdown['verified']);self.assertFalse(device.enabled)

    def test_startup_and_rearm_do_not_bank_idle_ready_time(self):
        clock,device,box,c=self.controller()
        e=self.cycle(clock,box,c,-.05,0.)
        self.assertLess(e['commanded_load_A'],.02)
        c.stop();c.session=None;c.initialize();clock.sleep(100)
        box.publish(row(clock,-.05));self.assertTrue(c.arm(),c.fault)
        e=self.cycle(clock,box,c,-.05,0.)
        self.assertLess(e['commanded_load_A'],.02)
        c.stop();self.assertTrue(c.shutdown['verified'])

    def test_unrepresentable_nominal_rate_requires_slower_updates(self):
        with self.assertRaisesRegex(ValueError,'lower control_hz'):
            config(slew_A_per_s=.00004)
        clock,device,box,c=self.controller(slew_A_per_s=.00004,control_hz=.2)
        e=self.cycle(clock,box,c,-.05,5.)
        self.assertEqual(e['commanded_load_A'],.0002)
        c.stop()

    def test_unchanged_writes_reset_reference_before_direction_change(self):
        clock,device,box,c=self.controller()
        for _ in range(8):self.cycle(clock,box,c,-.05,1.)
        self.assertEqual(c.applied,.1)
        for _ in range(3):
            before=c.slew_reference_ack_s
            e=self.cycle(clock,box,c,-.05,.6)
            self.assertEqual(e['commanded_load_A'],.1)
            self.assertGreater(c.slew_reference_ack_s,before)
        e=self.cycle(clock,box,c,.03,.6)
        self.assertGreater(e['commanded_load_A'],.08)
        c.stop()

    def test_power_fault_disables_without_waiting_for_ramp(self):
        clock,device,box,c=self.controller()
        for _ in range(8):self.cycle(clock,box,c,-.05,1.)
        c.config=replace(c.config,max_power_W=.1)
        box.publish(row(clock,-.05));c.cycle()
        self.assertEqual(c.fault,'MEASURED_CURRENT_OR_POWER_LIMIT')
        self.assertTrue(c.shutdown['verified']);self.assertFalse(device.enabled)

    def test_telemetry_loss_and_communication_failure_still_stop(self):
        for failure in ('telemetry','timeout'):
            clock,device,box,c=self.controller()
            self.cycle(clock,box,c,-.05,1.)
            if failure=='telemetry':clock.sleep(.51)
            else:
                box.publish(row(clock,-.05));device.failure='timeout'
            c.cycle();self.assertEqual(c.state,'FAULT');self.assertIsNone(c.slew_reference_ack_s)
            if failure=='telemetry':self.assertTrue(c.shutdown['verified'])
            else:self.assertFalse(c.shutdown['verified'])


if __name__=='__main__':unittest.main()
