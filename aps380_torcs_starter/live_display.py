"""Small desktop display; receiver thread and logs run independently of Tk."""
import time
import tkinter as tk
from tkinter import ttk


class LiveDisplay:
    def __init__(self, receiver, finished=lambda: False, duration=500, mock_service=None, load_service=None):
        if mock_service is not None and load_service is not None:
            raise ValueError('Choose prototype mock instruments OR standalone BK8500 monitoring')
        self.receiver, self.finished = receiver, finished
        self.mock_service = mock_service
        self.load_service = load_service
        self.deadline = time.perf_counter()+duration
        self.root = tk.Tk()
        self.callback_error = None
        self.refresh_job = None
        def callback_failed(error_type, error, traceback):
            self.callback_error = error
            self.root.quit()
        self.root.report_callback_exception = callback_failed
        self.root.title('APS380 Live EV Telemetry')
        self.root.geometry('1050x800' if load_service or getattr(receiver,'power_feedback',None) is not None else '980x680')
        if mock_service is not None and getattr(receiver,'power_feedback',None) is not None:
            self.root.geometry('1050x980')
        self.root.protocol('WM_DELETE_WINDOW',self.root.quit)
        frame=ttk.Frame(self.root,padding=14);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='APS380 • LIVE NATIVE EV TELEMETRY',font=('Segoe UI',18,'bold')).pack(anchor='w')
        banner = ('BK8500 REAL readbacks | PSU-to-eLoad test | NO BATTERY | ARM only in supervised terminal'
                  if load_service and load_service.hardware else
                  'BK8500 MOCK readbacks | no hardware access | NO BATTERY' if load_service else
                  'SIMULATION ONLY  |  hardware control disabled  |  no measured cell connected')
        ttk.Label(frame,text=banner).pack(anchor='w',pady=5)
        ttk.Label(frame,text='Cell current: negative = discharge; positive = charge. Native PACK power/current: positive = draw.').pack(anchor='w')
        self.state_label=ttk.Label(frame,font=('Segoe UI',13,'bold'));self.state_label.pack(anchor='w')
        power=getattr(receiver,'power_feedback',None)
        if power is not None:
            controls=ttk.Frame(frame);controls.pack(fill='x')
            ttk.Label(controls,text='MOCK vehicle power policy; no physical battery/SOP safety').pack(side='left')
            ttk.Button(controls,text='Reset propulsion feedback',command=power.request_reset).pack(side='left')
            ttk.Button(controls,text='Zero propulsion',command=power.request_stop).pack(side='left')
        if mock_service is not None:
            controls=ttk.Frame(frame);controls.pack(fill='x')
            self.mock_label=ttk.Label(controls,text='MOCK instruments: DISARMED')
            self.mock_label.pack(side='left')
            for label,action in [('Arm mock','arm'),('Disarm','disarm'),('Emergency stop','emergency_stop'),('Clear fault','recover')]:
                ttk.Button(controls,text=label,command=lambda a=action: mock_service.request(a)).pack(side='left')
        if load_service is not None:
            controls=ttk.Frame(frame);controls.pack(fill='x')
            self.load_label=ttk.Label(controls);self.load_label.pack(side='left')
            actions=[('Disarm','disarm'),('Emergency stop','stop'),('Reset fault (does not arm)','reset')]
            if not load_service.hardware: actions.insert(0,('Arm mock','arm'))
            for label,action in actions:
                ttk.Button(controls,text=label,command=lambda a=action: load_service.request(a)).pack(side='left')
        self.values=ttk.Label(frame,font=('Consolas',12),justify='left');self.values.pack(anchor='w',pady=10)
        chart_parent=frame
        if load_service is not None:
            notebook=ttk.Notebook(frame);notebook.pack(fill='both',expand=True)
            chart_parent=ttk.Frame(notebook);load_frame=ttk.Frame(notebook)
            notebook.add(chart_parent,text='Signed battery DEMAND (simulation)')
            notebook.add(load_frame,text='BK8500 branch current (not battery current)')
            self.load_canvas=tk.Canvas(load_frame,height=260,background='#111827',highlightthickness=0)
            self.load_canvas.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(chart_parent,height=260,background='#111827',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.details=ttk.Label(frame,wraplength=930);self.details.pack(anchor='w',pady=8)
        ttk.Button(frame,text='Stop trial and save timing report',command=self.root.quit).pack(anchor='e')

    def refresh(self):
        if self.mock_service is not None:
            status=self.mock_service.latest
            retained=' (readbacks retained; not live)' if status.get('measurements_retained') else ''
            self.mock_label.config(text=f"MOCK: {status['state']} {status['fault']}{retained}")
        p=self.receiver.processor
        state=p.state();current=p.current if state=='RECEIVING' else None
        self.state_label.config(text=state,foreground='#137547' if current else '#b45309')
        row=p.history[-1] if p.history else None
        history=list(p.history)
        recent=[r for r in history if row and r['session_id']==row['session_id']][-100:]
        span=recent[-1]['received_qpc_s']-recent[0]['received_qpc_s'] if len(recent)>1 else 0
        rate=(len(recent)-1)/span if span>0 else 0
        if row:
            demand=f"{current['cell_current_unclamped_A']:+.4f} / {current['cell_current_command_A']:+.4f} A" if current else 'UNAVAILABLE (no fresh target)'
            text=(f"Speed: {row['speed_mps']*3.6:7.2f} km/h     Pack power: {row['pack_power_W']/1000:+8.2f} kW\n"
                  f"Cell (+charge / -discharge) target / limited: {demand}\n"
                  f"Native pack (+draw): {row['pack_voltage_V']:.1f} V, {row['pack_current_A']:+.2f} A, SOC {row['soc']*100:.2f}%   "
                  f"Sample age: {time.perf_counter()-p.last_receive:.3f} s\n")
        else:
            text='Waiting for a Practice race to start in TORCS.\n'
        text+=(f"Fixed scale: {p.cell.experiment_scale:g}   Cell basis: {p.cell.nominal_voltage_V:g} V / {p.cell.capacity_Ah:g} Ah\n"
               f"Cell bounds: -{p.cell.discharge_limit_A:g} to +{p.cell.charge_limit_A:g} A  "
               f"Rate: {rate:.1f} Hz   Received / missing / invalid: {p.stats['accepted']} / {p.stats['missing']} / {p.stats['invalid']}\n"
               'Physical cell V / I / T / SOC: NOT CONNECTED')
        if self.mock_service is not None:
            s=self.mock_service.latest
            if 'psu' in s and 'load' in s:
                context='RETAINED; NOT LIVE' if s.get('measurements_retained') else s['state']
                text+=(f"\nMOCK {context}: target {s['requested_A']:+.4f} / limited {s['permitted_A']:+.4f} / "
                       f"applied {s['applied_target_A']:+.4f} / measured {s['mock_cell_current_A']:+.4f} A\n"
                       f"PSU set/read {s['psu']['setpoint_A']:.4f}/{s['psu']['current_A']:.4f} A; "
                       f"eLoad set/read {s['load']['setpoint_A']:.4f}/{s['load']['current_A']:.4f} A")
        load=getattr(self,'load_service',None)
        if load is not None:
            s=load.latest
            kind='REAL' if load.hardware else 'MOCK'
            retained=' | RETAINED, NOT LIVE' if s.get('measurements_retained') else ''
            self.load_label.config(text=f"BK8500 {kind}: {s['state']} {s['fault']}{retained}")
            if s['state']=='READY':
                text+='\nINPUT OFF; waiting for ARM '+('(supervised terminal only)' if load.hardware else '(button or terminal)')
                preflight=s.get('startup_measurement')
                if preflight:
                    text+=(f"\n{kind} preflight snapshot (not continuously polled while READY): "
                           f"{preflight['voltage_V']:.3f} V / {preflight['measured_A']:.4f} A; "
                           f"input {'ON' if preflight['input_on'] else 'OFF'}")
            if 'measured_A' in s:
                age=time.perf_counter()-s['measurement_received_host_s']
                text+=(f"\nBK8500 {kind}{retained}: mapped {s['scaled_load_demand_A']:.4f} / "
                       f"limited {s['power_limited_load_target_A']:.4f} / applied {s['commanded_load_A']:.4f} A\n"
                       f"Setting readback {s['readback_setting_A']:.4f} A; measured {s['measured_A']:.4f} A; "
                       f"{s['voltage_V']:.3f} V / {s['power_W']:.3f} W; input {'ON' if s['input_on'] else 'OFF'}; "
                       f"measurement age {age:.2f} s")
            shutdown=s.get('shutdown',{})
            if s['state']!='RUNNING' and shutdown and shutdown.get('errors')!=['Not checked yet']:
                text+=f"\nLast shutdown OFF/zero verified: {shutdown.get('verified',False)} (not a live readback)"
        power=getattr(self.receiver,'power_feedback',None)
        if power is not None:
            s=power.latest
            text+='\nMOCK propulsion: '+s.get('vehicle_limit_state','WAITING')
            if 'vehicle_limit_applied_fraction' in s:
                age=time.perf_counter()-s['received_qpc_s']
                text+=(f" | Python requested {s['vehicle_limit_requested_fraction']:.0%} / "
                       f"native commanded {s['vehicle_limit_native_commanded']:.0%} / "
                       f"applied {s['vehicle_limit_applied_fraction']:.0%}; feedback age {age:.2f}s\n"
                       f"{s['vehicle_limit_policy']}")
                if 'sop_model_valid' in s:
                    def number(key,fmt='.3f'):
                        return format(s[key],fmt) if s.get(key) is not None else 'UNAVAILABLE'
                    soc_label='MOCK Coulomb Counted' if 'cell_observer_state' in s else 'MOCK supplied'
                    soc_format='.5%' if 'cell_observer_state' in s else '.1%'
                    text+=(f"\nCell SOC estimate [{soc_label}]: {number('sop_cell_soc_fraction',soc_format)}; "
                           f"T [MOCK]: {number('sop_mock_temperature_C','.1f')} C; "
                           f"OCV [candidate]: {number('sop_ocv_candidate_V')} V\n"
                           f"R0 [ASSUMED]: {number('sop_r0_assumed_ohm')} ohm; "
                           f"max discharge [EST]: {number('sop_max_discharge_A')} A; "
                           f"SOP [EST]: {number('sop_max_discharge_W')} W\n"
                           f"Motor requested [SIM, unlimited]: {number('sop_motor_requested_unlimited_W','.1f')} W; "
                           f"allowable [MODEL]: {number('sop_motor_allowable_W','.1f')} W\n"
                           f"SOP model valid in assumed range: {s['sop_model_valid']} | {s['sop_reason']}")
                    if 'cell_observer_state' in s:
                        text+=f"\nCell stream [MOCK]: {s['cell_observer_state']} | {s['cell_observer_error']} | age {s['cell_measurement_age_s']} s"
                    if not s['sop_auxiliary_budget_satisfied']:
                        text+=' | SOP cannot cover native auxiliary draw; propulsion zero does not turn auxiliaries off'
                else:text+=f" | simulated policy SOC {s['vehicle_limit_demo_soc']:.1%}"
            if power.error:text+='\n'+power.error
        self.values.config(text=text)
        self.details.config(text=f"{p.profile['name']}\n{p.error or 'Chart: amber=target, blue=limited, purple=applied, green=mock measured. Pausing or losing telemetry shows STALE.'}\nLogs: {self.receiver.output}")
        self.draw_chart(history)
        if load is not None:
            legend=('Signed demand: amber=original, blue=limited. BK8500 tab: amber=limited load target, '
                    'purple=applied, blue=setting readback, green='+('REAL' if load.hardware else 'MOCK')+' measured. '
                    'PSU is manual/unmeasured; load current is NOT battery current.')
            self.details.config(text=f"{p.profile['name']}\n{p.error or legend}\nLogs: {self.receiver.output}")
            self.draw_load_chart(load)
        if self.finished() or time.perf_counter()>=self.deadline or self.receiver.failed:
            self.root.quit();return
        self.refresh_job = self.root.after(max(20,int(p.config.get('display_refresh_ms',100))),self.refresh)

    def draw_chart(self, history):
        c=self.canvas;c.delete('all')
        w,h=max(c.winfo_width(),300),max(c.winfo_height(),200)
        bound=max(self.receiver.processor.cell.discharge_limit_A,self.receiver.processor.cell.charge_limit_A,1)*1.2
        if history:
            last=history[-1]
            history=[r for r in history if r['session_id']==last['session_id'] and r['time_s']>=last['time_s']-30]
            bound=max(bound,max(abs(r['cell_current_unclamped_A']) for r in history)*1.1)
        def y(value):return h/2-value/bound*(h/2-25)
        for value in (0,-self.receiver.processor.cell.discharge_limit_A,self.receiver.processor.cell.charge_limit_A):
            c.create_line(45,y(value),w-12,y(value),fill='#475569',dash=(3,3))
            c.create_text(5,y(value),anchor='w',text=f'{value:+g} A',fill='white')
        for key,color in [('cell_current_unclamped_A','#f59e0b'),('cell_current_command_A','#38bdf8')]:
            points=[]
            for row in history:
                x=45+(row['time_s']-(history[-1]['time_s']-30))/30*(w-60)
                points.extend((x,y(row[key])))
            if len(points)>=4:c.create_line(*points,fill=color,width=2)
        if self.mock_service is not None and history:
            for key,color in [('applied_target_A','#a78bfa'),('mock_cell_current_A','#34d399')]:
                points=[]
                for s in list(self.mock_service.history):
                    t=s.get('source_sim_time_s')
                    if s['state']=='RUNNING' and t is not None and s.get('source_session')==history[-1]['session_id'] and history[-1]['time_s']-30<=t<=history[-1]['time_s']:
                        points.extend((45+(t-(history[-1]['time_s']-30))/30*(w-60),y(s[key])))
                if len(points)>=4:c.create_line(*points,fill=color,width=2)

    def draw_load_chart(self, load):
        c=self.load_canvas;c.delete('all')
        w,h=max(c.winfo_width(),300),max(c.winfo_height(),200)
        now=time.perf_counter();bound=load.config.max_current_A*1.1
        def y(value):return h-25-value/bound*(h-50)
        for value in (0,load.config.max_current_A):
            c.create_line(60,y(value),w-12,y(value),fill='#475569',dash=(3,3))
            c.create_text(5,y(value),anchor='w',text=f'{value:g} A',fill='white')
        for key,color in [('power_limited_load_target_A','#f59e0b'),('commanded_load_A','#a78bfa'),
                          ('readback_setting_A','#38bdf8'),('measured_A','#34d399')]:
            points=[]
            for row in load.history:
                if now-30<=row['host_s']<=now:
                    points.extend((60+(row['host_s']-(now-30))/30*(w-75),y(row[key])))
            if len(points)>=4:c.create_line(*points,fill=color,width=2)

    def run(self):
        try:
            self.refresh();self.root.mainloop()
        finally:
            if self.refresh_job is not None:
                self.root.after_cancel(self.refresh_job)
            self.root.destroy()
        if self.callback_error is not None:
            raise RuntimeError('Dashboard callback failed') from self.callback_error
