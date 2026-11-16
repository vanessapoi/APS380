"""MOCK-only demonstration availability policy; never physical SOC/SOP safety."""
from dataclasses import dataclass
import json
import math
import threading
import time


@dataclass(frozen=True)
class DemoPolicy:
    low_soc: float = .10
    full_soc: float = .30
    minimum_fraction: float = .20
    demo_soc: float | None = None
    fixed_fraction: float | None = None

    def __post_init__(self):
        for value in (self.low_soc,self.full_soc,self.minimum_fraction,self.demo_soc,self.fixed_fraction):
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1):
                raise ValueError('Demo policy values must be finite within 0..1')
        if self.low_soc>=self.full_soc:raise ValueError('SOC thresholds must increase')

    def evaluate(self, native_soc):
        soc=self.demo_soc if self.demo_soc is not None else native_soc
        if type(soc) not in (float,int) or not math.isfinite(soc) or not 0<=soc<=1:
            raise ValueError('Invalid simulated SOC')
        fraction=(self.fixed_fraction if self.fixed_fraction is not None else
            self.minimum_fraction+(1-self.minimum_fraction)*max(0,min(1,(soc-self.low_soc)/(self.full_soc-self.low_soc))))
        return soc,fraction


class PowerFeedback:
    """Receiver-thread sends only; UI/console set events, never hardware I/O."""
    def __init__(self,policy=DemoPolicy(),clock=time.perf_counter):
        self.policy,self.clock=policy,clock
        self.sequence=0;self.session=None;self.error='';self.latest={}
        self.fatal=threading.Event()
        self.reset=threading.Event();self.reset.set() # One initial opt-in reset, no auto-retry.
        self.stopping=threading.Event();self.stop_verified=threading.Event()
        self.stop_sequence=None
        self.paused=threading.Event() # Mock validation of feedback interruption.

    def request_reset(self):
        if not self.stopping.is_set():self.reset.set()

    def request_stop(self):
        self.stop_sequence=None;self.stop_verified.clear();self.stopping.set()

    def handle(self,row,payload,address,sock):
        ack=json.loads(payload).get('power_limit')
        if not isinstance(ack,dict) or ack.get('enabled') is not True:
            self.fatal.set()
            self.error='Native mock power feedback unavailable; rebuild/enable the simulator'
            row.update(vehicle_limit_state='UNAVAILABLE',vehicle_limit_error=self.error)
            self.latest=dict(row);return
        valid=(ack.get('state') in ('WAITING','ACTIVE','FAULT_STALE','FAULT_INVALID') and
               type(ack.get('sequence')) is int and ack['sequence']>=-1 and
               all(type(ack.get(k)) in (int,float) and math.isfinite(ack[k]) and 0<=ack[k]<=1 for k in ('commanded','applied')))
        if not valid:
            self.fatal.set()
            self.error='Invalid native power acknowledgement'
            row.update(vehicle_limit_state='INVALID_ACK',vehicle_limit_error=self.error)
            self.latest=dict(row);return # Stop sends: native expiry still applies.
        if self.session is not None and self.session!=row['session_id']:
            self.error='Race session changed; explicit RESET required'
        self.session=row['session_id']
        details={}
        if hasattr(self.policy,'evaluate_row'):
            soc,fraction,details=self.policy.evaluate_row(row)
            if (details.get('sop_model_valid') is False and not details.get('sop_waiting_for_measurement',False)
                    and not self.stopping.is_set()):
                self.error='SOP model unavailable: '+details['sop_reason']
                self.reset.clear() # Require explicit recovery after the model becomes valid.
        else:soc,fraction=self.policy.evaluate(row['soc'])
        if self.stopping.is_set() or self.fatal.is_set():fraction=0.
        row.update(vehicle_limit_demo_soc=soc,vehicle_limit_requested_fraction=fraction,
            vehicle_limit_native_commanded=ack['commanded'],vehicle_limit_applied_fraction=ack['applied'],
            vehicle_limit_state=ack['state'],vehicle_limit_ack_sequence=ack['sequence'],
            vehicle_limit_policy=(self.policy.label if hasattr(self.policy,'label') else
                'FIXED MOCK TEST' if self.policy.fixed_fraction is not None else 'DEMO SIMULATED SOC; NOT VALIDATED SOP'),
            vehicle_limit_error=self.error)
        row.update(details)
        if (self.stopping.is_set() and self.stop_sequence is not None and
                ack['sequence']>=self.stop_sequence and ack['applied']==0):
            self.stop_verified.set()
        if self.reset.is_set() and not self.fatal.is_set():self.error=''
        can_send=(not self.error and not self.fatal.is_set()) or self.stopping.is_set()
        if row['target_available'] and not self.paused.is_set() and can_send:
            reset=int(self.reset.is_set() and not self.stopping.is_set())
            packet=f'APS380POWER1 {self.session} {self.sequence} {self.clock():.9f} {fraction:.9f} {reset}'
            try:
                sock.sendto(packet.encode('ascii'),address)
                if self.stopping.is_set() and self.stop_sequence is None:self.stop_sequence=self.sequence
                row.update(vehicle_limit_sent_sequence=self.sequence,vehicle_limit_reset_sent=bool(reset))
                self.sequence+=1
                self.reset.clear()
            except OSError as exc:
                self.error='Power feedback send failed: '+repr(exc)
                row['vehicle_limit_error']=self.error
        self.latest=dict(row)
