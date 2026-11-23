"""Real Tk form tests: presentation only; no hardware or simulator launch."""
from pathlib import Path
import tkinter as tk
import unittest

from live_display import MockExperimentSetup
from mock_test_config import BASE,load_mock_test_config,resolve_mock_test_config


class MockSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:r=tk.Tk();r.withdraw();r.destroy()
        except tk.TclError as error:raise unittest.SkipTest(str(error))

    def setUp(self):
        self.seed=load_mock_test_config(BASE/'profiles/mock_test_20_percent_manual.json')
        self.ui=MockExperimentSetup(self.seed);self.ui.root.withdraw();self.closed=False

    def tearDown(self):
        if not self.closed:self.ui.root.destroy()

    def test_initial_values_units_and_effective_preview(self):
        self.assertEqual(self.ui.values['initial_soc_fraction'].get(),'20')
        self.assertIn('1 A',self.ui.preview.get())
        self.assertIn('CC limit',self.ui.preview.get())
        self.assertEqual(self.ui.validate().audit['overrides'],self.seed.audit['overrides'])
        self.assertIn('0 to 3 A',self.ui.required_range.get())
        self.assertIn('0 to 3 A',self.ui.capability_range.get())

    def test_required_range_updates_without_changing_selected_capability(self):
        self.ui.values['maximum_discharge_A'].set('5')
        self.assertIn('0 to 6 A',self.ui.required_range.get())
        self.assertIn('0 to 3 A',self.ui.capability_range.get())
        self.assertEqual(self.ui.values['eload_max_A'].get(),'3')
        self.assertIn('INFEASIBLE',self.ui.range_status.get())
        self.ui.start();self.assertIsNone(self.ui.result)
        self.assertIn('0..2 A',self.ui.message.get())  # No explicit extended selection.

    def test_extended_capability_is_explicit_and_does_not_change_other_inputs(self):
        before={key:value.get() for key,value in self.ui.values.items()}
        self.ui.capability.set('Extended MOCK ONLY (5 A discharge / 6 A load)')
        self.assertEqual(before,{key:value.get() for key,value in self.ui.values.items()})
        self.ui.values['maximum_discharge_A'].set('5')
        self.assertIsNone(self.ui.validate())  # Load capability is still 3 A.
        self.ui.values['eload_max_A'].set('6')
        resolved=self.ui.validate();self.assertIsNotNone(resolved)
        self.assertEqual(resolved.control.transition_timeout_s,452.)
        self.assertEqual(resolved.model['parameters']['maximum_discharge_A'],.5)
        self.assertEqual(resolved.scaling['cell']['experiment_scale'],.06)
        self.ui.start();self.assertTrue(self.ui.capability_picker.instate(['disabled']))

    def test_negative_required_minimum_is_visible_and_rejected(self):
        self.ui.values['mock_psu_contribution_A'].set('.2')
        self.assertIn('-0.8',self.ui.required_range.get())
        self.assertIn('charging exceeds',self.ui.range_status.get())
        self.ui.start();self.assertIsNone(self.ui.result)
        self.assertIn('negative',self.ui.message.get())

    def test_derived_operating_minimum_does_not_change_startup_capability(self):
        self.ui.values['maximum_charge_A'].set('.5')
        self.assertIn('0.5 to 3 A',self.ui.required_range.get())
        resolved=self.ui.validate()
        self.assertEqual(resolved.control.eload_current_min_A,0.)
        self.assertEqual(resolved.audit['effective']['required_eload_range_A'],dict(minimum_A=.5,maximum_A=3.))

    def test_invalid_preview_input_does_not_leave_stale_required_range(self):
        self.ui.values['maximum_discharge_A'].set('nan')
        self.assertIn('unavailable',self.ui.required_range.get())
        self.assertIn('No settings applied',self.ui.range_status.get())

    def test_edit_soc_percent_and_validate_with_existing_resolver(self):
        self.ui.values['initial_soc_fraction'].set('40')
        self.assertIn('not yet validated',self.ui.message.get())
        resolved=self.ui.validate()
        self.assertEqual(resolved.model['mock_state']['soc_fraction'],.4)
        self.assertEqual(self.seed.model['mock_state']['soc_fraction'],.2)
        expected=dict(self.seed.audit['requested'],initial_soc_fraction=.4)
        self.assertEqual(resolved.audit['effective'],resolve_mock_test_config(expected).audit['effective'])

    def test_invalid_inputs_and_infeasible_source_never_start(self):
        for field,value in (('initial_soc_fraction','101'),('initial_soc_fraction',''),
                            ('experiment_scale','nan'),('eload_max_A','6'),('mock_psu_contribution_A','.2')):
            with self.subTest(field=field,value=value):
                old=self.ui.values[field].get();self.ui.values[field].set(value)
                self.ui.start();self.assertIsNone(self.ui.result)
                self.assertIn('Cannot start',self.ui.message.get())
                self.assertFalse(self.ui.start_button.instate(['disabled']))
                self.ui.values[field].set(old)

    def test_start_revalidates_after_preview_and_locks(self):
        self.ui.validate();self.ui.values['initial_soc_fraction'].set('30')
        self.ui.start()
        self.assertEqual(self.ui.result.model['mock_state']['soc_fraction'],.3)
        self.assertTrue(all(entry.instate(['disabled']) for entry in self.ui.entries))
        self.assertTrue(self.ui.start_button.instate(['disabled']))

    def test_cancel_and_close_return_no_settings(self):
        self.ui.root.after(1,self.ui.cancel)
        result=self.ui.run();self.closed=True
        self.assertIsNone(result)

    def test_window_close_is_cancellation(self):
        command=self.ui.root.protocol('WM_DELETE_WINDOW')
        self.ui.root.after(1,lambda:self.ui.root.tk.call(command))
        self.assertIsNone(self.ui.run());self.closed=True

    def test_confirmed_start_returns_resolved_settings_and_destroys_form(self):
        self.ui.root.after(1,self.ui.start)
        result=self.ui.run();self.closed=True
        self.assertEqual(result.source_A,1.)
        self.assertEqual(result.audit['source_file'],'mock-setup-gui')


if __name__=='__main__':unittest.main()
