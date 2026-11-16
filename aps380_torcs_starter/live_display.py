"""Small desktop display; receiver thread and logs run independently of Tk."""
from collections import deque
import math
import time
import tkinter as tk
from tkinter import ttk


def display_number(value, unit='', fmt='.3f'):
    """Presentation only: never substitute zero for missing/invalid data."""
    if type(value) not in (int,float) or not math.isfinite(value):
        return 'NOT AVAILABLE'
    return format(value,fmt)+((' '+unit) if unit else '')


def thin_trace(points, limit=600):
    """Retain extrema and time order while bounding Tk line coordinates."""
    if len(points)<=limit:return points
    width=max(1,math.ceil(len(points)/max(1,limit//4)))
    result=[]
    for start in range(0,len(points),width):
        chunk=points[start:start+width]
        selected={0,len(chunk)-1,min(range(len(chunk)),key=lambda i:chunk[i][1]),
                  max(range(len(chunk)),key=lambda i:chunk[i][1])}
        result.extend(chunk[i] for i in sorted(selected))
    return result


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
        self.root.geometry(f'{min(1180,self.root.winfo_screenwidth()-60)}x{min(850,self.root.winfo_screenheight()-90)}')
        self.root.minsize(860,620)
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
        self.age_label=ttk.Label(frame);self.age_label.pack(anchor='w',pady=(0,6))
        self.health_label=ttk.Label(frame,font=('Segoe UI',10,'bold'),wraplength=1080);self.health_label.pack(anchor='w',pady=(0,4))
        self.notebook=ttk.Notebook(frame);self.notebook.pack(fill='both',expand=True)
        self.tabs={}
        for name in ('Vehicle','Battery','SOC & SOP','Instruments','Safety & Logs'):
            tab=ttk.Frame(self.notebook,padding=10);self.notebook.add(tab,text=name);self.tabs[name]=tab
        self.readouts={};self.window_s=30.;self.render_times=deque(maxlen=200)
        self._build_panels()
        control_parent=self.tabs['Safety & Logs']
        power=getattr(receiver,'power_feedback',None)
        if power is not None:
            controls=ttk.Frame(control_parent);controls.pack(fill='x',pady=3)
            ttk.Label(controls,text='MOCK vehicle power policy; no physical battery/SOP safety').pack(side='left')
            ttk.Button(controls,text='Reset propulsion feedback',command=power.request_reset).pack(side='left')
            ttk.Button(controls,text='Zero propulsion',command=power.request_stop).pack(side='left')
        if mock_service is not None:
            controls=ttk.LabelFrame(control_parent,text='MOCK PSU/eLoad controls (in memory)',padding=6);controls.pack(fill='x',pady=3)
            self.mock_label=ttk.Label(controls,text='MOCK instruments: DISARMED',wraplength=950)
            self.mock_label.pack(anchor='w')
            actions_row=ttk.Frame(controls);actions_row.pack(fill='x')
            for label,action in [('Arm mock','arm'),('Disarm','disarm'),('Emergency stop','emergency_stop'),('Clear fault','recover')]:
                ttk.Button(actions_row,text=label,command=lambda a=action: mock_service.request(a)).pack(side='left')
        if load_service is not None:
            controls=ttk.LabelFrame(control_parent,text='REAL BK8500 stop / recovery only; ARM requires supervised terminal' if load_service.hardware else 'MOCK BK8500 controls',padding=6);controls.pack(fill='x',pady=3)
            self.load_label=ttk.Label(controls,wraplength=950);self.load_label.pack(anchor='w')
            actions_row=ttk.Frame(controls);actions_row.pack(fill='x')
            actions=[('Disarm','disarm'),('Emergency stop','stop'),('Reset fault (does not arm)','reset')]
            if not load_service.hardware: actions.insert(0,('Arm mock','arm'))
            for label,action in actions:
                ttk.Button(actions_row,text=label,command=lambda a=action: load_service.request(a)).pack(side='left')
        ttk.Label(control_parent,text='Detailed diagnostics (read-only)',font=('Segoe UI',10,'bold')).pack(anchor='w',pady=(8,3))
        diagnostics=tk.Canvas(control_parent,highlightthickness=0)
        scrollbar=ttk.Scrollbar(control_parent,orient='vertical',command=diagnostics.yview)
        scrollbar.pack(side='right',fill='y');diagnostics.pack(fill='both',expand=True)
        diagnostics.configure(yscrollcommand=scrollbar.set)
        body=ttk.Frame(diagnostics);window=diagnostics.create_window((0,0),window=body,anchor='nw')
        body.bind('<Configure>',lambda e:diagnostics.configure(scrollregion=diagnostics.bbox('all')))
        diagnostics.bind('<Configure>',lambda e:diagnostics.itemconfigure(window,width=e.width))
        self.values=ttk.Label(body,font=('Consolas',10),justify='left',wraplength=1000);self.values.pack(anchor='w',fill='x')
        chart_parent=self.tabs['Battery']
        if load_service is not None:
            load_frame=ttk.Frame(self.notebook,padding=10)
            self.notebook.add(load_frame,text='BK8500 current')
            self.tabs['BK8500 current']=load_frame
            ttk.Label(load_frame,text='BK8500 branch current (not battery current) | '+('REAL instrument readbacks' if load_service.hardware else 'MOCK readbacks')).pack(anchor='w')
            self.bk_legend=ttk.Label(load_frame,text='amber=limited target | purple=applied command | blue=setting readback | green='+
                ('REAL' if load_service.hardware else 'MOCK')+' measured',wraplength=1000)
            self.bk_legend.pack(anchor='w',pady=(2,4))
            self.load_canvas=tk.Canvas(load_frame,height=260,background='#111827',highlightthickness=0)
            self.load_canvas.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(chart_parent,height=260,background='#111827',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.create_text(20,20,anchor='w',text='Waiting for signed cell demand / mock current history',fill='white')
        if load_service is not None:
            self.load_canvas.create_text(20,20,anchor='w',text='Waiting for completed BK8500 records',fill='white')
        # Reserve the footer BEFORE the expanding notebook. Otherwise Windows
        # DPI scaling / short screens can push the existing Stop button offscreen.
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x',pady=(5,0),before=self.notebook)
        self.details=ttk.Label(footer,wraplength=780,font=('Segoe UI',9));self.details.pack(side='left',fill='x',expand=True)
        self.stop_button=ttk.Button(footer,text='Stop trial and save timing report',command=self.root.quit)
        self.stop_button.pack(side='right',padx=(8,0))
        self.notebook.bind('<<NotebookTabChanged>>',lambda e:self._draw_visible())
        self.notebook.bind('<Configure>',self._resize_panels)

    def _resize_panels(self,event):
        for value in self.readouts.values():value.configure(wraplength=max(250,(event.width-65)//2))
        self.instrument_summary.configure(wraplength=max(500,event.width-40))
        self.safety_summary.configure(wraplength=max(500,event.width-40))
        self.health_label.configure(wraplength=max(500,event.width-20))
        self.values.configure(wraplength=max(500,event.width-50))
        self.details.configure(wraplength=max(400,event.width-280))

    def _cards(self,tab,fields):
        grid=ttk.Frame(self.tabs[tab]);grid.pack(fill='x')
        for column in (0,1):grid.columnconfigure(column,weight=1)
        for i,(key,title) in enumerate(fields):
            card=ttk.LabelFrame(grid,text=title,padding=(10,5))
            card.grid(row=i//2,column=i%2,sticky='nsew',padx=4,pady=3)
            value=ttk.Label(card,text='NOT CONNECTED',font=('Segoe UI',13,'bold'),wraplength=490)
            value.pack(anchor='w');self.readouts[key]=value

    def _build_panels(self):
        self._cards('Vehicle',[('speed','Speed [SIMULATED]'),('motor','Motor output [SIMULATED]'),
            ('pack_power','Pack power [SIMULATED; positive = draw]'),('pack_soc','Pack SOC [SIMULATED; not Cell SOC]'),
            ('propulsion','Propulsion availability [native acknowledgement]'),('vehicle_age','Vehicle data / source')])
        self.vehicle_canvas=tk.Canvas(self.tabs['Vehicle'],background='#111827',highlightthickness=0,height=230)
        self.vehicle_canvas.pack(fill='both',expand=True,pady=5)
        self._cards('Battery',[('cell_soc','Cell SOC [ESTIMATED / MOCK]'),('cell_current','Cell current [+charge / -discharge]'),
            ('cell_voltage','Cell voltage [source identified below]'),('cell_temperature','Cell temperature [source identified below]'),
            ('cell_quality','Cell source / quality'),('cell_age','Cell measurement timestamp / age')])
        ttk.Label(self.tabs['Battery'],text='Original signed battery-current graph | amber=requested, blue=limited, purple=applied, green=MOCK measured').pack(anchor='w',pady=(4,0))
        self._cards('SOC & SOP',[('sop_soc','Cell SOC [ESTIMATED / MOCK; separate from pack]'),('ocv','OCV [CANDIDATE model; not measured voltage]'),
            ('sop','Discharge SOP [ESTIMATED; unvalidated]'),('imax','Allowable discharge current [ESTIMATED magnitude]')])
        toolbar=ttk.Frame(self.tabs['SOC & SOP']);toolbar.pack(fill='x',pady=4)
        ttk.Label(toolbar,text='Auto-scaled Y axes | host elapsed time | window:').pack(side='left')
        choice=ttk.Combobox(toolbar,values=('30 s','60 s','90 s'),state='readonly',width=6);choice.set('30 s');choice.pack(side='left')
        def change(event):self.window_s=float(choice.get().split()[0]);self._draw_visible()
        choice.bind('<<ComboboxSelected>>',change)
        self.trend_status=ttk.Label(toolbar);self.trend_status.pack(side='left',padx=10)
        plots=ttk.Frame(self.tabs['SOC & SOP']);plots.pack(fill='both',expand=True)
        self.trend_canvases={}
        for i,key in enumerate(('soc','current','sop','fraction')):
            c=tk.Canvas(plots,background='#111827',highlightthickness=0,width=400,height=180)
            c.grid(row=i//2,column=i%2,sticky='nsew',padx=3,pady=3)
            self.trend_canvases[key]=c
        for i in (0,1):plots.rowconfigure(i,weight=1);plots.columnconfigure(i,weight=1)
        self.instrument_summary=ttk.Label(self.tabs['Instruments'],wraplength=1050,justify='left');self.instrument_summary.pack(anchor='w',pady=5)
        self.instrument_table=ttk.Treeview(self.tabs['Instruments'],columns=('metric','psu','load'),show='headings',height=13)
        for key,title,width in (('metric','Quantity / source',300),('psu','PSU',310),('load','eLoad',360)):
            self.instrument_table.heading(key,text=title);self.instrument_table.column(key,width=width,stretch=True)
        self.instrument_table.pack(fill='both',expand=True)
        ttk.Label(self.tabs['Instruments'],text='Branch current is not an independent cell-current measurement. No physical ARM control is provided here.',wraplength=1000).pack(anchor='w',pady=5)
        self.safety_summary=ttk.Label(self.tabs['Safety & Logs'],wraplength=1050,justify='left',font=('Segoe UI',10))
        self.safety_summary.pack(anchor='w',pady=(0,8))

    def refresh(self):
        redraw_started=time.perf_counter()
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
        if row and state!='RECEIVING':text+='RETAINED vehicle/policy values below; telemetry is not live.\n'
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
        if load is not None:
            legend=('Signed demand: amber=original, blue=limited. BK8500 tab: amber=limited load target, '
                    'purple=applied, blue=setting readback, green='+('REAL' if load.hardware else 'MOCK')+' measured. '
                    'PSU is manual/unmeasured; load current is NOT battery current.')
            self.details.config(text=f"{p.profile['name']}\n{p.error or legend}\nLogs: {self.receiver.output}")
        if hasattr(self,'notebook'):
            self._chart_history=history
            self._render_panels(state,row,rate)
            self._draw_visible()
            self.render_times.append((time.perf_counter()-redraw_started)*1000)
        else:
            self.draw_chart(history)
            if load is not None:self.draw_load_chart(load)
        if self.finished() or time.perf_counter()>=self.deadline or self.receiver.failed:
            self.root.quit();return
        self.refresh_job = self.root.after(max(20,int(p.config.get('display_refresh_ms',100))),self.refresh)

    def _set(self,key,value):
        self.readouts[key].configure(text=value)

    def _render_panels(self,state,row,rate):
        """Read cached records only. Never call instruments or observer.snapshot()."""
        now=time.perf_counter();p=self.receiver.processor
        row=row or {};power=getattr(self.receiver,'power_feedback',None)
        bias=getattr(self.mock_service,'latest',{}).get('control_mode')=='battery_bias_mock'
        s=power.latest if power else getattr(self.mock_service,'latest',{}).get('cell_model_state',{})
        fresh=state=='RECEIVING'
        tag='SIMULATED' if fresh else 'RETAINED / '+state
        def n(key,unit='',fmt='.3f',source=row):return display_number(source.get(key),unit,fmt)
        def scaled(key,divisor,unit):
            v=row.get(key)
            return display_number(v/divisor if type(v) in (int,float) else None,unit)
        age=now-p.last_receive if p.last_receive is not None else None
        self.age_label.configure(text=f'{rate:.1f} Hz telemetry | '+('LIVE' if fresh else state)+
            ' | age '+display_number(age,'s')+' | Controls and diagnostics: Safety & Logs')
        self._set('speed',display_number(row.get('speed_mps')*3.6 if type(row.get('speed_mps')) in (int,float) else None,'km/h')+' | '+tag)
        self._set('motor',scaled('motor_power_W',1000,'kW')+' | '+tag)
        self._set('pack_power',scaled('pack_power_W',1000,'kW')+' | '+tag)
        self._set('pack_soc',display_number(row.get('soc')*100 if type(row.get('soc')) in (int,float) else None,'%')+' | '+tag)
        self._set('vehicle_age','TORCS native telemetry | '+display_number(age,'s')+' old')
        if power is not None:
            self._set('propulsion','Applied '+display_number(s.get('vehicle_limit_applied_fraction'),fmt='.3%')+
                ' | '+s.get('vehicle_limit_state','WAITING')+('' if fresh else ' | RETAINED'))
        else:self._set('propulsion','External feedback NOT CONNECTED')
        has_sop='sop_model_valid' in s
        live='cell_observer_state' in s
        quality=(s.get('cell_observer_state','WAITING') if live else 'MOCK supplied; held inputs' if has_sop else 'NOT CONNECTED')
        if not fresh and has_sop:quality='RETAINED / '+state
        soc=n('sop_cell_soc_fraction',fmt='.5%',source=s) if has_sop else 'NOT CONNECTED'
        soc+=' | '+('ESTIMATED / MOCK counted' if live else 'MOCK supplied' if has_sop else 'no Cell SOC source')
        if not fresh and has_sop:soc='RETAINED | '+soc
        self._set('cell_soc',soc);self._set('sop_soc',soc)
        self._set('cell_temperature',n('sop_mock_temperature_C','C','.1f',source=s)+' | MOCK imposed' if has_sop else 'NOT CONNECTED')
        self._set('cell_voltage','NOT CONNECTED (OCV is a model estimate)')
        self._set('cell_current','NOT CONNECTED (demand is not a measurement)')
        self._set('cell_age','No cell measurement stream')
        self._set('cell_quality',quality)
        observer=getattr(getattr(power,'policy',None),'observer',None)
        if observer is None and bias:
            observer=getattr(getattr(self.mock_service,'cell_stream',None),'observer',None)
        sample=getattr(observer,'sample',None)
        measurement=getattr(sample,'measurement',None)
        if live and measurement is not None:
            cell_age=now-measurement.time_s
            stale=cell_age<0 or cell_age>observer.freshness or bool(observer.error) or not fresh
            prefix='RETAINED / STALE | ' if stale else ''
            self._set('cell_current',prefix+display_number(measurement.net_cell_current_A,'A','+.5f')+
                (' | MOCK independent sensor model' if bias else ' | MOCK branch readbacks'))
            self._set('cell_voltage',prefix+display_number(measurement.cell_voltage_V,'V')+' | MOCK imposed; not measured')
            self._set('cell_temperature',prefix+display_number(measurement.cell_temperature_C,'C','.1f')+' | MOCK imposed; not measured')
            self._set('cell_age',f'Seq {sample.sequence} | host {measurement.time_s:.3f} s | age {cell_age:.3f} s')
            self._set('cell_quality',(observer.error or ('STALE' if stale else quality))+' | '+sample.source)
        m=self.mock_service.latest if self.mock_service is not None else {}
        if m and not live and 'psu' in m and 'load' in m:
            stamps=[m[b]['acquired_s'] for b in ('psu','load')]
            cell_age=now-min(stamps)
            stale=m.get('measurements_retained') or m['state'] not in ('READY','RUNNING') or cell_age>self.mock_service.config.measurement_expiry_s
            self._set('cell_current',('RETAINED / STALE | ' if stale else '')+display_number(m.get('mock_cell_current_A'),'A','+.5f')+' | MOCK modeled net current')
            self._set('cell_quality','MOCK branch readbacks + isolation; no physical cell sensor')
            self._set('cell_age',f'Oldest branch age {cell_age:.3f} s | '+('STALE / retained' if stale else 'fresh readbacks'))
        for key,field,unit in (('ocv','sop_ocv_candidate_V','V'),('sop','sop_max_discharge_W','W'),('imax','sop_max_discharge_A','A')):
            self._set(key,n(field,unit,'.6f',source=s)+(' | '+quality if has_sop else ' | NOT CONNECTED'))
        self.trend_status.configure(text=('LIVE' if fresh else 'HISTORICAL / '+state)+' | '+quality)
        self._render_instruments(m,now)
        isolation=m.get('isolation')
        isolation_text=('OPEN' if isolation['is_open'] else 'CLOSED')+' [MOCK]' if isolation else 'NOT CONNECTED / not reported'
        if bias:
            bs=m.get('bias_safety',{})
            isolation_text+=f" | source isolated: {bs.get('source_isolated')} | protection ready: {bs.get('protection_ready')} | E-stop: {bs.get('estop_active')} [MOCK]"
        retained=' | RETAINED' if m.get('measurements_retained') else ''
        controller=m.get('state','NOT CONNECTED')
        fault=m.get('fault','')
        if self.load_service is not None:
            ls=self.load_service.latest;controller=ls.get('state','WAITING');fault=ls.get('fault','')
            retained=' | RETAINED' if ls.get('measurements_retained') else ''
        alert=fault or s.get('cell_observer_error') or getattr(power,'error','') or p.error
        if s.get('vehicle_limit_state','').startswith('FAULT'):alert=alert or s['vehicle_limit_state']
        if not fresh:alert=alert or state
        self.health_label.configure(text=('ATTENTION: '+alert) if alert else
            'Controller: '+controller+' | Cell state: '+quality+' | Physical cell sensors NOT CONNECTED',
            foreground='#b45309' if alert else '#334155')
        log=getattr(self.receiver,'log',None)
        recording='JSONL OPEN; CSV / plots / reports saved on stop' if log is not None and not log.closed else 'CLOSED / unavailable'
        redraw=self.render_times[-1] if self.render_times else 0.
        shutdown=('verified [MOCK]' if m.get('shutdown_verified') else 'not currently verified / not assessed')
        if self.load_service is not None:
            result=self.load_service.latest.get('shutdown',{})
            shutdown=str(result.get('verified','not assessed'))+' (last completed check, not live readback)'
        self.safety_summary.configure(text=f'Telemetry: {state} | age {display_number(age,"s")} | received / missing / invalid: '
            f'{p.stats["accepted"]} / {p.stats["missing"]} / {p.stats["invalid"]}\n'
            f'Controller: {controller}{retained} | fault: {fault or "none reported"} | isolation: {isolation_text}\n'
            f'Shutdown verification: {shutdown}\n'
            f'Cell state: {quality} | {s.get("cell_observer_error","")} | propulsion: {s.get("vehicle_limit_state","NOT CONNECTED")}\n'
            f'Recording: {recording} | display refresh {p.config.get("display_refresh_ms",100)} ms; last redraw {redraw:.1f} ms\n'
            f'Logs: {self.receiver.output}\nPhysical cell sensing/protection: NOT CONNECTED; a GUI stop is not physical isolation.')
        selected=self.notebook.tab(self.notebook.select(),'text')
        legend=('Signed demand / mock net current; positive cell current = charge. Historical values remain visible on loss.' if selected=='Battery' else
            'BK8500 load branch only; PSU manual/unmeasured. No battery current is inferred.' if selected=='BK8500 current' else
            'Plots use auto-scaled axes, break on missing data and resets, and draw only the selected tab.')
        self.details.configure(text=f'{p.profile["name"]} | {legend}\nLogs: {self.receiver.output}')

    def _render_instruments(self,m,now):
        rows=[];load=self.load_service
        if load is not None:
            s=load.latest;kind='REAL' if load.hardware else 'MOCK'
            stamp=s.get('measurement_received_host_s')
            age=now-stamp if stamp is not None else None
            context='RETAINED, NOT LIVE' if s.get('measurements_retained') else s.get('state','WAITING')
            if age is not None and age>1/load.config.control_hz+load.config.max_cycle_s and not s.get('measurements_retained'):
                context='STALE completed readbacks | '+context
            self.instrument_summary.configure(text=f'BK8500 {kind}: {context} | '+
                ('PSU manual/unmeasured. Physical ARM: supervised terminal only.' if load.hardware else 'No hardware access; PSU manual/unmeasured in this standalone test.'))
            values=(('Original signed cell demand',s.get('original_cell_current_A'),'A'),
                ('Original 0-3 A load demand',s.get('original_eload_demand_A'),'A'),
                ('Mapped load demand',s.get('scaled_load_demand_A'),'A'),('Limited load target',s.get('power_limited_load_target_A'),'A'),
                ('Applied command',s.get('commanded_load_A'),'A'),('Setting query readback',s.get('readback_setting_A'),'A'),
                ('Measured branch current',s.get('measured_A'),'A'),('Measured voltage',s.get('voltage_V'),'V'),
                ('Measured power',s.get('power_W'),'W'),('Measured minus command',s.get('tracking_error_A'),'A'),
                ('TORCS source time',s.get('torcs_time_s'),'s'),('Measurement age',age,'s'))
            rows=[(name,'NOT CONNECTED',display_number(value,unit)+' ['+kind+']') for name,value,unit in values]
            rows.append(('Input status','NOT CONNECTED',('ON' if s['input_on'] else 'OFF')+' ['+kind+']' if 'input_on' in s else 'Not reported'))
            startup=s.get('startup_measurement',{})
            summary=(display_number(startup.get('voltage_V'),'V')+' / '+display_number(startup.get('measured_A'),'A')+
                ' / input '+('ON' if startup['input_on'] else 'OFF')) if 'input_on' in startup else 'NOT AVAILABLE'
            rows.append(('Startup snapshot (READY; not live polling)','NOT CONNECTED',summary))
        elif m and 'psu' in m and 'load' in m:
            p,e=m['psu'],m['load'];context='RETAINED, NOT LIVE' if m.get('measurements_retained') else m['state']
            if now-min(p['acquired_s'],e['acquired_s'])>self.mock_service.config.measurement_expiry_s:
                context='STALE readbacks | '+context
            bias=m.get('control_mode')=='battery_bias_mock'
            self.instrument_summary.configure(text=('Battery Bias: MOCK independent cell sensor + PSU/load readbacks | ' if bias else 'Prototype instruments: MOCK | ')+context+' | Cell current = PSU - eLoad; no physical instrument access.')
            for name,pv,ev,unit in (('CC target',self.mock_service.config.psu_cc_setpoint_A,m.get('load_target_A'),'A'),
                ('Applied command (if separately recorded)',None,m.get('load_command_A'),'A'),
                ('Setting readback [mock state]',p.get('setpoint_A'),e.get('setpoint_A'),'A'),
                ('Measured branch current [MOCK]',p.get('current_A'),e.get('current_A'),'A'),
                ('Branch voltage [MOCK]',p.get('voltage_V'),e.get('voltage_V'),'V'),
                ('Readback age',now-p['acquired_s'],now-e['acquired_s'],'s')):
                rows.append((name,display_number(pv,unit),display_number(ev,unit)))
            rows.append(('Output at last readback','ON' if p['status']['output_enabled'] else 'OFF','ON' if e['status']['output_enabled'] else 'OFF'))
            rows.append(('Mode at last readback',p['status']['mode'],e['status']['mode']))
            for key,label in (('requested_A','Net cell request'),('permitted_A','Net cell limited'),('applied_target_A','Net cell applied'),('mock_cell_current_A','Modeled net cell current')):
                rows.append((label,'PSU - eLoad [MOCK]',display_number(m.get(key),'A','+.5f')))
        else:
            self.instrument_summary.configure(text='Instruments NOT CONNECTED'+(' | MOCK '+m.get('state','') if m else ''))
            rows=[('No instrument readbacks','NOT CONNECTED','NOT CONNECTED')]
        for i,values in enumerate(rows):
            item='metric-'+str(i)
            if self.instrument_table.exists(item):self.instrument_table.item(item,values=values)
            else:self.instrument_table.insert('', 'end',iid=item,values=values)
        for item in self.instrument_table.get_children()[len(rows):]:self.instrument_table.delete(item)

    def _draw_visible(self):
        if not hasattr(self,'notebook') or not self.notebook.select():return
        history=getattr(self,'_chart_history',[])
        selected=self.notebook.tab(self.notebook.select(),'text')
        if selected=='Battery':self.draw_chart(history)
        elif selected=='BK8500 current':self.draw_load_chart(self.load_service)
        elif selected in ('Vehicle','SOC & SOP'):
            if (selected=='SOC & SOP' and getattr(self.mock_service,'latest',{}).get('control_mode')=='battery_bias_mock'
                    and getattr(self.receiver,'power_feedback',None) is None):
                history=[dict(r.get('cell_model_state',{}),received_qpc_s=r['cell_sensor_frame']['acquired_s'],
                              session_id=r['cell_sensor_frame']['session_id'])
                         for r in list(self.mock_service.history) if 'cell_sensor_frame' in r]
            end=history[-1]['received_qpc_s'] if history else time.perf_counter()
            def series(key,scale=1.,model=False):
                points=[]
                for r in history:
                    value=r.get(key)
                    if model and (not r.get('sop_model_valid') or r.get('cell_observer_state','VALID')!='VALID'):value=None
                    value=value*scale if type(value) in (int,float) and math.isfinite(value) else None
                    points.append((r['received_qpc_s'],value,(r['session_id'],r.get('cell_observer_generation',0))))
                return points
            if selected=='Vehicle':
                self._plot(self.vehicle_canvas,[('Motor [SIM]','#38bdf8',series('motor_power_W',.001)),
                    ('Pack [SIM; positive draw]','#f59e0b',series('pack_power_W',.001))],end,'Native power','kW')
            else:
                self._plot(self.trend_canvases['soc'],[('Cell SOC [MOCK estimate]','#38bdf8',series('sop_cell_soc_fraction',100.,True))],end,'Cell SOC (not pack SOC)','%')
                current=series('cell_mock_measured_current_A',model=True)
                if self.mock_service is not None and not any(v is not None for _,v,_ in current):
                    current=[]
                    for r in list(self.mock_service.history):
                        stamp=r.get('load',{}).get('acquired_s')
                        if stamp is not None:
                            value=r.get('mock_cell_current_A') if r['state']=='RUNNING' and not r.get('measurements_retained') else None
                            current.append((stamp,value,r.get('source_session')))
                self._plot(self.trend_canvases['current'],[('Net cell [MOCK readbacks]','#34d399',current)],end,'Cell current (+charge / -discharge)','A')
                self._plot(self.trend_canvases['sop'],[('Rint SOP [EST; unvalidated]','#a78bfa',series('sop_max_discharge_W',model=True))],end,'Allowable discharge power','W')
                self._plot(self.trend_canvases['fraction'],[('Requested [MOCK]','#f59e0b',series('vehicle_limit_requested_fraction',100.)),
                    ('Native applied','#38bdf8',series('vehicle_limit_applied_fraction',100.))],end,'Propulsion availability','%')

    def _plot(self,canvas,series,end,title,unit):
        canvas.delete('all');w=max(canvas.winfo_width(),300);h=max(canvas.winfo_height(),160)
        left,right,top,bottom=82,w-15,40,h-32
        traces=[];all_values=[]
        for name,color,points in series:
            points=[p for p in points if end-self.window_s<=p[0]<=end]
            traces.append((name,color,points));all_values.extend(v for _,v,_ in points if v is not None and math.isfinite(v))
        canvas.create_text(10,14,anchor='w',fill='white',text=title+' ['+unit+']')
        if not all_values:
            canvas.create_text(w/2,h/2,fill='#cbd5e1',text='NOT CONNECTED / no valid history');return
        low,high=min(all_values),max(all_values);span=high-low
        pad=span*.12 if span>1e-12 else max(abs(high)*.001,.000001)
        low-=pad;high+=pad
        def xy(x,y):return (left+(x-(end-self.window_s))/self.window_s*(right-left),bottom-(y-low)/(high-low)*(bottom-top))
        for i in range(3):
            value=low+(high-low)*i/2;yp=xy(end,value)[1]
            canvas.create_line(left,yp,right,yp,fill='#334155');canvas.create_text(left-5,yp,anchor='e',fill='#cbd5e1',text=f'{value:.8g}')
        for offset in (-self.window_s,-self.window_s/2,0):
            xp=xy(end+offset,low)[0];canvas.create_text(xp,h-14,fill='#cbd5e1',text=f'{offset:g} s')
        for name,color,points in traces:
            chunk=[];previous=None
            def draw():
                sampled=thin_trace(chunk,max(80,min(600,int(right-left))))
                coords=[c for x,y in sampled for c in xy(x,y)]
                if len(coords)>=4:canvas.create_line(*coords,fill=color,width=2,tags='trace')
                elif len(coords)==2:canvas.create_oval(coords[0]-2,coords[1]-2,coords[0]+2,coords[1]+2,fill=color,tags='trace')
            for x,value,group in points:
                if value is None or not math.isfinite(value) or (previous and (group!=previous[1] or x-previous[0]>.5)):
                    draw();chunk=[]
                if value is not None and math.isfinite(value):chunk.append((x,value))
                previous=(x,group)
            draw()
        canvas.create_text(right,14,anchor='e',fill='#cbd5e1',text=' | '.join(name for name,_,_ in traces))

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
