"""Small desktop display; receiver thread and logs run independently of Tk."""
import time
import tkinter as tk
from tkinter import ttk


class LiveDisplay:
    def __init__(self, receiver, finished=lambda: False, duration=500, mock_service=None):
        self.receiver, self.finished = receiver, finished
        self.mock_service = mock_service
        self.deadline = time.perf_counter()+duration
        self.root = tk.Tk()
        self.root.title('APS380 Live EV Telemetry — simulation only')
        self.root.geometry('980x680')
        self.root.protocol('WM_DELETE_WINDOW',self.root.quit)
        frame=ttk.Frame(self.root,padding=14);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='APS380 • LIVE NATIVE EV TELEMETRY',font=('Segoe UI',18,'bold')).pack(anchor='w')
        ttk.Label(frame,text='SIMULATION ONLY  |  hardware control disabled  |  no measured cell connected').pack(anchor='w',pady=5)
        ttk.Label(frame,text='Cell current: negative = discharge; positive = charge. Native PACK power/current: positive = draw.').pack(anchor='w')
        self.state_label=ttk.Label(frame,font=('Segoe UI',13,'bold'));self.state_label.pack(anchor='w')
        if mock_service is not None:
            controls=ttk.Frame(frame);controls.pack(fill='x')
            self.mock_label=ttk.Label(controls,text='MOCK instruments: DISARMED')
            self.mock_label.pack(side='left')
            for label,action in [('Arm mock','arm'),('Disarm','disarm'),('Emergency stop','emergency_stop'),('Clear fault','recover')]:
                ttk.Button(controls,text=label,command=lambda a=action: mock_service.request(a)).pack(side='left')
        self.values=ttk.Label(frame,font=('Consolas',12),justify='left');self.values.pack(anchor='w',pady=10)
        self.canvas=tk.Canvas(frame,height=260,background='#111827',highlightthickness=0)
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
        self.values.config(text=text)
        self.details.config(text=f"{p.profile['name']}\n{p.error or 'Chart: amber=target, blue=limited, purple=applied, green=mock measured. Pausing or losing telemetry shows STALE.'}\nLogs: {self.receiver.output}")
        self.draw_chart(history)
        if self.finished() or time.perf_counter()>=self.deadline or self.receiver.failed:
            self.root.quit();return
        self.root.after(max(20,int(p.config.get('display_refresh_ms',100))),self.refresh)

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

    def run(self):
        try:
            self.refresh();self.root.mainloop()
        finally:
            self.root.destroy()
