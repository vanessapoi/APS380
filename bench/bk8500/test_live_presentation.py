"""Console/dashboard regressions. All instruments and hardware labels are fake."""
import contextlib
import io
import sys
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

if sys.version_info < (3, 10):
    raise unittest.SkipTest('Live control requires Python 3.10+')

from live_torcs import console, main, parse_args
from live_control import LiveConfig
from live_presentation import ConsoleStatus, LoadMonitor
from torcs_live import LiveReceiver


def fake_service():
    return SimpleNamespace(config=LiveConfig(max_current_A=.1),
        controller=SimpleNamespace(state='READY',fault=''),events=[],request=Mock())


class PresentationTests(unittest.TestCase):
    def test_ready_not_repeated_running_rate_limited_and_fault_immediate(self):
        s=fake_service();m=LoadMonitor(s);p=ConsoleStatus(interval=5)
        self.assertIn('waiting for ARM',p.render(m,'RECEIVING',0))
        self.assertIsNone(p.render(m,'RECEIVING',10))
        s.controller.state='RUNNING'
        self.assertIn('RUNNING',p.render(m,'RECEIVING',11))
        self.assertIsNone(p.render(m,'RECEIVING',12))
        self.assertIsNotNone(p.render(m,'RECEIVING',16))
        s.controller.state='FAULT';s.controller.fault='TEST_FAILURE'
        self.assertIn('TEST_FAILURE',p.render(m,'RECEIVING',16.1))

    def test_dashboard_console_only_transitions_and_json_opt_in(self):
        s=fake_service();s.controller.state='RUNNING';m=LoadMonitor(s)
        p=ConsoleStatus(dashboard=True)
        self.assertIsNotNone(p.render(m,'RECEIVING',0))
        self.assertIsNone(p.render(m,'RECEIVING',100))
        self.assertIn('"state": "RUNNING"',ConsoleStatus(json_output=True).render(m,'RECEIVING',0))

    def test_console_prompt_commands_and_exact_hardware_phrase(self):
        s=fake_service();q=threading.Event();output=io.StringIO()
        with patch('builtins.input',side_effect=['ARM','HELP','ARM LAB-TEST','DISARM','STOP','RESET','QUIT']) as inp,contextlib.redirect_stdout(output):
            console(s,q,'ARM LAB-TEST')
        self.assertEqual([call.args[0] for call in s.request.call_args_list],['arm','disarm','stop','reset'])
        self.assertEqual(inp.call_args.args,('BK8500> ',))
        self.assertIn('worker verifies',output.getvalue());self.assertTrue(q.is_set())

    def test_eof_requests_stop(self):
        s=fake_service();q=threading.Event()
        with patch('builtins.input',side_effect=EOFError),contextlib.redirect_stdout(io.StringIO()):console(s,q,'ARM')
        s.request.assert_called_once_with('stop');self.assertTrue(q.is_set())

    def test_monitor_blocks_hardware_arm_and_marks_retained_without_mutation(self):
        s=fake_service();s.events=[dict(event='cycle',state='RUNNING',measured_A=.01)]
        m=LoadMonitor(s,True)
        with self.assertRaises(ValueError):m.request('arm')
        m.request('stop');s.request.assert_called_once_with('stop')
        self.assertTrue(m.latest['measurements_retained'])
        self.assertEqual(s.events[0]['state'],'RUNNING')
        self.assertEqual(len(m.history),1)

    def test_status_interval_validation(self):
        for interval in ('nan','0','inf'):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                parse_args(['--status-interval-s',interval])

    def test_dashboard_does_not_relax_hardware_supervision(self):
        import json
        from test_live_control import approval
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'approval.json';p.write_text(json.dumps(approval()))
            args=['--device','hardware','--dashboard','--max-current-A','.1',
                  '--port','FAKE_ONLY','--approval',str(p)]
            for extra,tty in ((['--no-console'],True),(['--auto-arm-mock'],True),([],False)):
                with patch('sys.stdin.isatty',return_value=tty),patch.dict('sys.modules',{'serial':None}),\
                     contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                    parse_args(args+extra)

    def test_dashboard_startup_failure_reports_fail_and_verified_shutdown(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'trial'
            with patch('live_torcs.write_manifest'),patch('live_display.LiveDisplay',side_effect=RuntimeError('FAKE_TK_ERROR')),\
                 contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                result=main(['--device','mock','--torcs','listen','--duration','.2','--telemetry-port','0',
                             '--no-console','--dashboard','--mock-transaction-delay-s','0','--output',str(output)])
            r=json.loads((output/'trial.json').read_text())
            self.assertEqual(result,1);self.assertEqual(r['stop_reason'],'runtime_error')
            self.assertIn('FAKE_TK_ERROR',r['runtime_error'])
            self.assertTrue(r['instrument']['shutdown_verified'])


class DashboardTests(unittest.TestCase):
    def test_real_widgets_mock_and_real_labels_original_mock_and_callback_failure(self):
        import tkinter as tk
        from live_display import LiveDisplay
        try:
            root=tk.Tk();root.withdraw();root.destroy()
        except tk.TclError as exc:self.skipTest(str(exc))
        def destroy(d):
            for job in d.root.tk.call('after','info'):d.root.after_cancel(job)
            d.root.destroy()
        with tempfile.TemporaryDirectory() as folder:
            receiver=LiveReceiver(0,Path(folder)/'telemetry')
            try:
                for hardware in (False,True):
                    s=fake_service();monitor=LoadMonitor(s,hardware)
                    d=LiveDisplay(receiver,load_service=monitor);d.root.withdraw()
                    d.refresh();d.root.update()
                    self.assertIn('waiting for ARM',d.values.cget('text'))
                    def buttons(widget):
                        found=[]
                        for child in widget.winfo_children():
                            if child.winfo_class()=='TButton':found.append(child)
                            found+=buttons(child)
                        return found
                    labels=[b.cget('text') for b in buttons(d.root)]
                    self.assertEqual('Arm mock' in labels,not hardware)
                    for b in buttons(d.root):
                        if b.cget('text') in ('Emergency stop','Arm mock'):b.invoke()
                    self.assertEqual([call.args[0] for call in s.request.call_args_list],
                                     ['stop'] if hardware else ['arm','stop'])
                    now=time.perf_counter();s.controller.state='RUNNING'
                    r=dict(event='cycle',state='RUNNING',host_s=now,measurement_received_host_s=now,
                        scaled_load_demand_A=.08,power_limited_load_target_A=.08,commanded_load_A=.07,
                        readback_setting_A=.07,measured_A=.069,voltage_V=5.,power_W=.345,input_on=True)
                    s.events=[dict(r,host_s=now-1),r]
                    d.refresh();d.root.update()
                    self.assertIn('BK8500 '+('REAL' if hardware else 'MOCK'),d.values.cget('text'))
                    self.assertTrue(d.load_canvas.find_all())
                    s.controller.state='FAULT';s.controller.fault='FAKE_FAILURE'
                    d.refresh();self.assertIn('RETAINED, NOT LIVE',d.values.cget('text'))
                    destroy(d)
                old=SimpleNamespace(latest=dict(state='READY',fault=''),history=[],request=Mock())
                d=LiveDisplay(receiver,mock_service=old);d.root.withdraw();d.refresh()
                self.assertIn('MOCK: READY',d.mock_label.cget('text'));destroy(d)
                d=LiveDisplay(receiver);d.root.withdraw()
                d.root.after(1,lambda:1/0)
                with self.assertRaisesRegex(RuntimeError,'Dashboard callback failed'):d.run()
            finally:
                with patch('torcs_live.write_report',return_value={}):receiver.close()


if __name__=='__main__':unittest.main()
