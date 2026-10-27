import unittest

from instrument_control import ControlConfig
from trial_acceptance import instrument_acceptance, trial_acceptance


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.process=dict(launched=True,exit_code=1,terminated_by_launcher=True,
                          stop_reason='duration_elapsed')

    def test_smoke_does_not_require_full_course(self):
        result=trial_acceptance({'telemetry':True},self.process,'smoke')
        self.assertTrue(result['passed'])
        self.assertIsNone(result['full_course']['completed'])
        self.assertFalse(result['full_course']['required'])
        self.assertFalse(trial_acceptance({'telemetry':True},self.process,'full-course')['passed'])

    def test_smoke_never_hides_crashes_or_telemetry_errors(self):
        crashed=dict(self.process,terminated_by_launcher=False,stop_reason='process_exit')
        self.assertFalse(trial_acceptance({'telemetry':True},crashed,'smoke')['passed'])
        self.assertFalse(trial_acceptance({'no_stale_intervals':False},self.process,'smoke')['passed'])
        self.assertFalse(trial_acceptance({'timing':False},self.process,'smoke')['passed'])
        self.assertFalse(trial_acceptance({'telemetry':True},self.process,'smoke',{'passed':False})['passed'])

    def test_full_course_requires_successful_course_and_other_gates(self):
        self.assertTrue(trial_acceptance({'telemetry':True},self.process,'full-course',course={'passed':True})['passed'])
        self.assertFalse(trial_acceptance({'telemetry':True},self.process,'full-course',course={'passed':False})['passed'])

    def test_fault_shutdown_success_is_not_operational_success(self):
        final=dict(state='FAULT',fault='TELEMETRY_EXPIRED',shutdown_verified=True,
                   shutdown_errors=[],isolation=dict(is_open=True,outputs_disabled=True))
        event=dict(final,transactions={})
        result=instrument_acceptance([event],ControlConfig(),final)
        self.assertFalse(result['passed'])
        self.assertTrue(result['fault_handling']['every_fault_shutdown_verified'])
        self.assertFalse(result['checks']['commands_fresh'])
        self.assertTrue(result['checks']['measurements_fresh'])

    def test_stale_measurement_does_not_mislabel_command_freshness(self):
        final=dict(state='FAULT',fault='STALE_OR_FUTURE_MEASUREMENT',shutdown_verified=True,
                   shutdown_errors=[],isolation=dict(is_open=True,outputs_disabled=True))
        result=instrument_acceptance([dict(final,transactions={})],ControlConfig(),final)
        self.assertFalse(result['passed'])
        self.assertFalse(result['checks']['measurements_fresh'])
        self.assertTrue(result['checks']['commands_fresh'])

    def test_errors_remain_visible_after_recovery(self):
        final=dict(state='DISARMED',fault='',shutdown_verified=True,shutdown_errors=[],
                   isolation=dict(is_open=True,outputs_disabled=True))
        events=[dict(final,state='FAULT',fault='CURRENT_TRACKING_TIMEOUT',transactions={}),
                dict(final,transactions={'psu':[dict(event='transaction',failure='timeout')]})]
        result=instrument_acceptance(events,ControlConfig(),final)
        self.assertFalse(result['passed'])
        self.assertEqual(result['communication_failure_count'],1)
        self.assertFalse(result['checks']['tracking_within_policy'])

    def test_stale_readback_failed_shutdown_and_missing_run_fail(self):
        final=dict(state='DISARMED',fault='',shutdown_verified=False,shutdown_errors=['timeout'],
                   isolation=dict(is_open=False,outputs_disabled=False))
        event=dict(final,command_age_s=1.,psu_measurement_age_s=1.,transactions={})
        result=instrument_acceptance([event],ControlConfig(),final,require_running=True)
        self.assertFalse(result['passed'])
        for key in ('commands_fresh','measurements_fresh','outputs_disabled','isolation_open',
                    'shutdown_verified','shutdown_commands_healthy','running_observed'):
            self.assertFalse(result['checks'][key],key)

    def test_tracks_applied_target_and_reports_demand_lag_separately(self):
        final=dict(state='DISARMED',fault='',shutdown_verified=True,shutdown_errors=[],
                   isolation=dict(is_open=True,outputs_disabled=True))
        event=dict(final,state='RUNNING',tracking_error_A=.001,demand_error_A=.2,
                   direction_ok=True,command_age_s=.01,psu_measurement_age_s=.01,
                   load_measurement_age_s=0.,transition_phase='TO_ZERO',transactions={})
        result=instrument_acceptance([event],ControlConfig(),final,require_running=True)
        self.assertTrue(result['passed'])
        self.assertEqual(result['demand_error_abs_A']['max'],.2)
        self.assertEqual(result['settling_cycles'],1)


if __name__=='__main__':unittest.main()
