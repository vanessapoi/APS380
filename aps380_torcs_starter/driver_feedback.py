"""Visual-only driver feedback. Never modifies TORCS controls or instruments."""
import math
import os
import time

from numerical_validation import finite_number

HUD_HELLO = b'APS380_HUD_HELLO_V1 '
HUD_VALUE_COUNT = 31
STATES = {'WAITING':0,'RECEIVING':1,'INVALID':3,'ENDED':4,'GAP':5}


class DriverFeedback:
    """Immediate limit alerts, with a one-second visual hold to avoid flicker."""
    def __init__(self):
        self.sequence=0
        self.alert=0
        self.hold_until=0.
        self.last_session=None

    def evaluate(self, current, discharge_limit, charge_limit, now):
        for name,value in (('current',current),('discharge_limit',discharge_limit),
                           ('charge_limit',charge_limit),('now',now)):
            finite_number(name,value)
        if min(discharge_limit,charge_limit)<0:
            raise ValueError('Current bounds must be nonnegative')
        limit=charge_limit if current>=0 else discharge_limit
        utilization=min(abs(current)/limit,1e6) if limit>0 else (1e6 if current else 0.)
        excess=max(current-charge_limit,-discharge_limit-current,0.)
        # Relative tolerance suppresses floating-point boundary noise only.
        tolerance=limit*1e-9
        instantaneous=2 if current < -discharge_limit-tolerance else (3 if current > charge_limit+tolerance else 0)
        if instantaneous:
            self.alert=instantaneous;self.hold_until=now+1.
        elif now>=self.hold_until:
            self.alert=1 if utilization>=.9 else 0
        return self.alert,utilization,excess

    def encode(self, processor, game_pid, now=None):
        now=time.perf_counter() if now is None else now
        state=processor.state(now)
        status=2 if state.startswith('STALE') else STATES.get(state,3)
        row=processor.history[-1] if processor.history else None
        session=processor.session or 'waiting'
        if session!=self.last_session:
            self.alert=0;self.hold_until=0.;self.last_session=session
        if row and status==1 and processor.current is not None:
            alarm,utilization,excess=self.evaluate(row['cell_current_unclamped_A'],
                processor.cell.discharge_limit_A,processor.cell.charge_limit_A,now)
        else:
            alarm=0;utilization=0.;excess=0.
        r=row or dict.fromkeys(('time_s','speed_mps','throttle','brake','pack_power_W',
            'pack_voltage_V','pack_current_A','soc','motor_power_W','motor_torque_Nm',
            'motor_radps','cell_current_unclamped_A','cell_current_command_A','damage',
            'collision','discharge_Wh','charge_Wh'),0.)
        history=[x for x in list(processor.history)[-100:] if x['session_id']==session]
        span=history[-1]['received_qpc_s']-history[0]['received_qpc_s'] if len(history)>1 else 0
        rate=(len(history)-1)/span if span>0 else 0.
        try:car_index=int(session.rsplit('-',1)[-1])
        except ValueError:car_index=0
        values=[now,status,alarm,car_index,r['speed_mps']*3.6,r['throttle']*100,r['brake']*100,
                r['pack_power_W']/1000,r['pack_voltage_V'],r['pack_current_A'],r['soc']*100,
                r['motor_power_W']/1000,r['motor_torque_Nm'],abs(r['motor_radps'])*60/(2*math.pi),
                r['cell_current_unclamped_A'],r['cell_current_command_A'],
                processor.cell.discharge_limit_A,processor.cell.charge_limit_A,
                processor.cell.nominal_voltage_V,processor.cell.capacity_Ah,processor.cell.experiment_scale,
                utilization,excess,max(0,now-processor.last_receive)*1000 if row else 0,
                r['damage'],r['collision'],r['discharge_Wh']-r['charge_Wh'],
                processor.stats['missing'],processor.stats['invalid'],rate,r['time_s']]
        for value in values:finite_number('HUD value',value)
        # V2 changes CELL signs only; native PACK fields retain TORCS signs.
        text=f'APS380HUD2 {game_pid} {os.getpid()} {self.sequence} {session} '
        self.sequence+=1
        return (text+' '.join(format(value,'.12g') for value in values)).encode('ascii')
