"""Tk presentation tests only. No physical drivers, device I/O or estimator updates."""
from collections import deque
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import Mock,patch

from cell_soc import CellMeasurement
from live_cell_state import CellSample
from live_display import LiveDisplay,display_number,thin_trace
from prototype_current_config import PROTOTYPE
from torcs_live import LiveReceiver


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:r=tk.Tk();r.withdraw();r.destroy()
        except tk.TclError as exc:raise unittest.SkipTest(str(exc))

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.receiver=LiveReceiver(0,Path(self.tmp.name)/'telemetry')
        self.ui=None;self.now=time.perf_counter()
        self.row=dict(session_id='race',sequence=2,received_qpc_s=self.now,time_s=2.,speed_mps=10.,
            motor_power_W=10000.,pack_power_W=12000.,pack_voltage_V=350.,pack_current_A=12000/350,
            soc=.99,cell_current_unclamped_A=-.12,cell_current_command_A=-.12)
        p=self.receiver.processor;p.current=self.row;p.last_receive=self.now;p.status='RECEIVING'
        p.history.extend(dict(self.row,sequence=i,received_qpc_s=self.now-.1*(2-i),time_s=1.8+i*.1) for i in range(3))

    def tearDown(self):
        if self.ui is not None:
            for job in self.ui.root.tk.call('after','info'):self.ui.root.after_cancel(job)
            self.ui.root.destroy()
        with patch('torcs_live.write_report',return_value={}):self.receiver.close()
        self.tmp.cleanup()

    def display(self,**kw):
        self.ui=LiveDisplay(self.receiver,finished=lambda:True,**kw);self.ui.root.withdraw()
        self.ui.root.update_idletasks();self.ui.refresh();return self.ui

    def prototype(self):
        def branch(current,setting):return dict(current_A=current,setpoint_A=setting,voltage_V=3.65,
            acquired_s=self.now,status=dict(output_enabled=True,mode='CC',fault=''))
        status=dict(state='RUNNING',fault='',measurements_retained=False,isolation=dict(is_open=False,outputs_disabled=False),
            psu=branch(1.,1.),load=branch(1.2,1.1),mock_cell_current_A=-.2,
            requested_A=-.1,permitted_A=-.1,applied_target_A=-.1,load_target_A=1.1,load_command_A=1.1,
            source_session='race',source_sim_time_s=2.,shutdown_verified=False)
        return SimpleNamespace(config=PROTOTYPE,latest=status,history=[status],request=Mock())

    def power(self,live=False):
        data=dict(self.row,vehicle_limit_state='ACTIVE',vehicle_limit_requested_fraction=.59,vehicle_limit_native_commanded=.59,
            vehicle_limit_applied_fraction=.59,vehicle_limit_policy='RINT MOCK',vehicle_limit_demo_soc=.8,
            sop_model_valid=True,sop_reason='CONSTRAINED_RINT_ESTIMATE',sop_cell_soc_fraction=.8,
            sop_mock_temperature_C=25.,sop_ocv_candidate_V=4.074397,sop_r0_assumed_ohm=.05,sop_max_discharge_A=.5,
            sop_max_discharge_W=1.990217,sop_motor_requested_unlimited_W=15000.,sop_motor_allowable_W=119000.,sop_auxiliary_budget_satisfied=True)
        policy=SimpleNamespace()
        if live:
            sample=CellSample(CellMeasurement('mock-cell',self.now,3.65,-.2,25.),2,self.now)
            policy.observer=SimpleNamespace(sample=sample,freshness=.2,error='',snapshot=Mock(side_effect=AssertionError('UI must not run observer')),
                counter=SimpleNamespace(update=Mock(side_effect=AssertionError('UI must not integrate current'))))
            data.update(cell_observer_state='VALID',cell_observer_error='',cell_measurement_age_s=0.,
                cell_mock_measured_current_A=-.2,cell_observer_generation=0)
        power=SimpleNamespace(latest=data,policy=policy,error='',request_reset=Mock(),request_stop=Mock())
        self.receiver.power_feedback=power
        self.receiver.processor.history=deque(dict(data,received_qpc_s=self.now-.1*(2-i),sequence=i) for i in range(3))
        return power

    def test_missing_cell_data_does_not_reuse_pack_soc_or_nominal_voltage(self):
        d=self.display()
        self.assertIn('99.000',d.readouts['pack_soc'].cget('text'))
        for key in ('cell_soc','cell_voltage','cell_current','cell_temperature','sop'):
            self.assertIn('NOT CONNECTED',d.readouts[key].cget('text'))
        self.assertEqual(set(d.tabs),{'Vehicle','Battery','SOC & SOP','Instruments','Safety & Logs'})

    def test_fixed_mock_ocv_is_not_presented_as_measured_cell_voltage(self):
        self.power();d=self.display()
        self.assertIn('MOCK supplied',d.readouts['cell_soc'].cget('text'))
        self.assertIn('4.074397',d.readouts['ocv'].cget('text'))
        self.assertIn('NOT CONNECTED',d.readouts['cell_voltage'].cget('text'))
        self.assertIn('held inputs',d.readouts['cell_quality'].cget('text'))

    def test_bias_independent_sensor_model_and_no_invented_propulsion_feedback(self):
        power=self.power(True);service=self.prototype()
        self.receiver.power_feedback=None
        model=dict(power.latest)
        for key in list(model):
            if key.startswith('vehicle_limit_'):del model[key]
        service.latest.update(control_mode='battery_bias_mock',cell_model_state=model,
            cell_sensor_frame=dict(acquired_s=self.now,session_id='cell'),
            bias_safety=dict(source_isolated=False,protection_ready=True,estop_active=False))
        service.cell_stream=SimpleNamespace(observer=power.policy.observer)
        service.history=[dict(service.latest,cell_sensor_frame=dict(acquired_s=self.now-.1,session_id='cell')),service.latest]
        d=self.display(mock_service=service)
        self.assertIn('MOCK independent sensor model',d.readouts['cell_current'].cget('text'))
        self.assertIn('80.00000%',d.readouts['cell_soc'].cget('text'))
        self.assertIn('NOT CONNECTED',d.readouts['propulsion'].cget('text'))
        self.assertIn('source isolated: False',d.safety_summary.cget('text'))
        d.notebook.select(d.tabs['SOC & SOP']);d.refresh()
        self.assertTrue(d.trend_canvases['soc'].find_withtag('trace'))
        self.assertFalse(d.trend_canvases['fraction'].find_withtag('trace'))

    def test_live_mock_values_and_source_labels_without_estimator_or_device_calls(self):
        power=self.power(True);service=self.prototype();d=self.display(mock_service=service)
        self.assertIn('80.00000%',d.readouts['cell_soc'].cget('text'))
        self.assertIn('MOCK imposed; not measured',d.readouts['cell_voltage'].cget('text'))
        self.assertIn('-0.20000 A',d.readouts['cell_current'].cget('text'))
        self.assertIn('Seq 2',d.readouts['cell_age'].cget('text'))
        service.request.assert_not_called();power.policy.observer.snapshot.assert_not_called()
        power.policy.observer.counter.update.assert_not_called()

    def test_stale_telemetry_explicitly_marks_retained_values(self):
        self.power(True);d=self.display()
        self.receiver.processor.last_receive=self.now-1;d.refresh()
        self.assertIn('RETAINED',d.readouts['motor'].cget('text'))
        self.assertIn('RETAINED',d.readouts['propulsion'].cget('text'))
        self.assertIn('RETAINED',d.readouts['cell_soc'].cget('text'))
        self.assertIn('HISTORICAL',d.trend_status.cget('text'))
        self.assertIn('STALE',d.health_label.cget('text'))

    def test_stale_cell_readback_is_visible_without_mutating_observer(self):
        power=self.power(True);d=self.display()
        observer=power.policy.observer
        observer.sample=replace(observer.sample,measurement=replace(observer.sample.measurement,time_s=self.now-2))
        d.refresh()
        self.assertIn('STALE',d.readouts['cell_current'].cget('text'))
        self.assertEqual(observer.error,'');observer.snapshot.assert_not_called()

    def test_prototype_targets_and_readbacks_are_separate_and_retention_is_marked(self):
        service=self.prototype();d=self.display(mock_service=service)
        self.assertIn('-0.20000 A',d.readouts['cell_current'].cget('text'))
        values=[d.instrument_table.item(i,'values') for i in d.instrument_table.get_children()]
        self.assertIn(('Applied command (if separately recorded)','NOT AVAILABLE','1.100 A'),values)
        self.assertIn(('Measured branch current [MOCK]','1.000 A','1.200 A'),values)
        service.latest=dict(service.latest,state='FAULT',fault='TEST_FAULT',measurements_retained=True)
        d.refresh();self.assertIn('RETAINED',d.instrument_summary.cget('text'))
        self.assertIn('TEST_FAULT',d.health_label.cget('text'));service.request.assert_not_called()

    def test_real_label_monitor_preserves_stop_reset_and_cannot_arm(self):
        monitor=SimpleNamespace(hardware=True,config=SimpleNamespace(control_hz=1.,max_cycle_s=.8,max_current_A=.1),
            latest=dict(state='READY',fault=''),history=[],request=Mock())
        d=self.display(load_service=monitor)
        def buttons(w):
            result=[]
            for c in w.winfo_children():
                if c.winfo_class()=='TButton':result.append(c)
                result+=buttons(c)
            return result
        controls={b.cget('text'):b for b in buttons(d.root)}
        self.assertNotIn('Arm mock',controls)
        controls['Disarm'].invoke();controls['Emergency stop'].invoke();controls['Reset fault (does not arm)'].invoke()
        self.assertEqual([c.args[0] for c in monitor.request.call_args_list],['disarm','stop','reset'])
        self.assertIn('REAL',d.instrument_summary.cget('text'))
        self.assertIn('REAL measured',d.bk_legend.cget('text'))
        self.assertIn('NOT CONNECTED',d.readouts['cell_current'].cget('text'))

    def test_all_soc_trends_draw_and_inactive_tabs_are_not_redrawn(self):
        self.power(True);d=self.display()
        with patch.object(d,'_plot',wraps=d._plot) as plot:
            d.refresh();self.assertEqual(plot.call_count,1)  # Vehicle only.
        d.notebook.select(d.tabs['SOC & SOP']);d.root.update_idletasks();d.refresh()
        for canvas in d.trend_canvases.values():self.assertTrue(canvas.find_withtag('trace'))

    def test_plot_breaks_at_missing_data_and_reset_and_rejects_nan(self):
        d=self.display();c=d.trend_canvases['soc'];t=self.now
        points=[(t-.5,1.,0),(t-.4,2.,0),(t-.3,None,0),(t-.2,3.,1),(t-.1,4.,1),(t,float('nan'),1)]
        d._plot(c,[('test','white',points)],t,'quality','%')
        self.assertEqual(len(c.find_withtag('trace')),2)

    def test_render_is_bounded_for_five_thousand_rows(self):
        self.power(True);d=self.display()
        base=self.receiver.processor.history[-1]
        self.receiver.processor.history=deque(dict(base,received_qpc_s=self.now-(4999-i)*.02,
            sop_max_discharge_W=1.99-i*.00000001) for i in range(5000))
        d.notebook.select(d.tabs['SOC & SOP']);d.refresh()
        for c in d.trend_canvases.values():
            for item in c.find_withtag('trace'):self.assertLessEqual(len(c.coords(item)),1210)

    def test_stop_button_remains_visible_at_smaller_window_size(self):
        self.power(True);d=self.display(mock_service=self.prototype())
        d.root.geometry('900x650');d.root.deiconify();d.root.update()
        self.assertTrue(d.stop_button.winfo_ismapped())
        self.assertLessEqual(d.stop_button.winfo_rooty()+d.stop_button.winfo_height(),
                             d.root.winfo_rooty()+d.root.winfo_height())


class PlotFormattingTests(unittest.TestCase):
    def test_invalid_values_are_not_replaced_with_zero(self):
        for v in (None,True,float('nan'),float('inf'),'1'):
            self.assertEqual(display_number(v),'NOT AVAILABLE')
        self.assertEqual(display_number(0.,'A'),'0.000 A')

    def test_decimation_preserves_short_spikes_and_order(self):
        points=[(i,1000. if i==317 else -500. if i==753 else 0.) for i in range(5000)]
        result=thin_trace(points,400)
        self.assertIn((317,1000.),result);self.assertIn((753,-500.),result)
        self.assertLessEqual(len(result),404);self.assertEqual(result,sorted(result))


if __name__=='__main__':unittest.main()
