"""Actual TORCS/Tk timing faults, mocks only; no serial transport is imported."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'));sys.path.insert(0,str(ROOT/'bench/bk8500'))
from battery_bias import BatteryBiasService
from battery_bias_feedback import BiasRintPolicy
from torcs_live import LiveReceiver
from vehicle_power_limit import PowerFeedback
from live_display import LiveDisplay
from live_torcs import prepare_launch_profile,RUNTIME


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--soak-seconds',type=float,default=0.,help='Additional live GUI driving before deliberate stream loss (0..300)')
    args=p.parse_args()
    if not 0<=args.soak_seconds<=300:p.error('Invalid soak duration')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    config=json.loads((ROOT/'aps380_torcs_starter/profiles/rint_sop_live_mock_example.json').read_text())
    service=BatteryBiasService(output/'instruments',sop_config=config);service.psu.cv_available_A=.2 if args.soak_seconds else .05
    feedback=PowerFeedback(BiasRintPolicy(service))
    receiver=LiveReceiver(0,output/'telemetry',power_feedback=feedback,demand_sink=service.demands)
    feedback.policy.configure(receiver.processor.cell,receiver.processor.profile)
    injection={'delay':0.,'loss':False};step=service.coordinator.step;update=service.cell_stream.update
    def delayed(*a,**kw):
        delay=injection['delay'];injection['delay']=0.
        if delay:time.sleep(delay)
        return step(*a,**kw)
    def publication(snapshot):
        if injection['loss']:
            snapshot=dict(snapshot);snapshot.pop('cell_sensor_frame',None)
        return update(snapshot)
    service.coordinator.step=delayed;service.cell_stream.update=publication
    checks={};phase=0;phase_start=time.perf_counter();started=phase_start;child=None
    active=lambda:service.latest['state']=='RUNNING' and feedback.latest.get('vehicle_limit_applied_fraction',0)>0
    def advance():
        nonlocal phase,phase_start
        phase+=1;phase_start=time.perf_counter()
        print('Timing validation phase',phase,flush=True)
    def poll():
        elapsed=time.perf_counter()-phase_start
        if time.perf_counter()-started>65+args.soak_seconds:raise RuntimeError('Timing stress deadline exceeded')
        if receiver.failed or (child and child.poll() is not None):raise RuntimeError('Native receiver/process failed')
        if phase==0 and service.demands.snapshot()[0] is not None:service.request('arm');advance()
        elif phase==1 and active():checks['normal']=True;injection['delay']=.25;advance()
        elif phase==2 and elapsed>1. and active():checks['250ms_resume']=True;injection['delay']=.32;advance()
        elif phase==3 and elapsed>1. and active():checks['320ms_resume']=True;advance()
        elif phase==4 and elapsed>max(2.,args.soak_seconds) and active():checks['slow_dashboard_resume']=True;injection['loss']=True;advance()
        elif phase==5 and service.latest['state']=='FAULT' and feedback.latest.get('vehicle_limit_applied_fraction')==0:
            checks['stream_loss_zero']=True;checks['fault_shutdown']=service.latest['shutdown_verified']
            injection['loss']=False;service.request('recover');advance()
        elif phase==6 and service.latest['state']=='DISARMED':service.request('arm');advance()
        elif phase==7 and service.latest['state']=='RUNNING':
            assert feedback.latest['vehicle_limit_applied_fraction']==0
            feedback.request_reset();advance()
        elif phase==8 and active():checks['explicit_recovery']=True;return True
        return False
    class SlowDisplay(LiveDisplay):
        def __init__(self,*a,**kw):
            super().__init__(*a,**kw);self.root.withdraw();self.delayed=False
            self.notebook.select(self.tabs['SOC & SOP'])
        def refresh(self):
            if phase==4 and not self.delayed:self.delayed=True;time.sleep(.35)
            return super().refresh()
    receiver.start();service.start();zero=False
    try:
        profile=prepare_launch_profile('ai')
        env=dict(os.environ,APS380_MOCK_POWER_LIMIT='1',APS380_LIVE_PORT=str(receiver.port),APS380_LIVE_REALTIME='1',
            APS380_TORCS_PROFILE=str(profile),APS380_AI_LOG=str(output/'driver.csv'))
        with (output/'torcs.log').open('w') as log:
            child=subprocess.Popen([str(RUNTIME/'wtorcs.exe'),'-r',str(profile/'race.xml')],cwd=RUNTIME,env=env,stdout=log,stderr=subprocess.STDOUT)
            SlowDisplay(receiver,poll,duration=65+args.soak_seconds,mock_service=service).run()
            feedback.request_stop();zero=feedback.stop_verified.wait(1.)
    finally:
        instrument=service.close();receiver.begin_shutdown()
        if child and child.poll() is None:child.terminate();child.wait(timeout=10)
        timing=receiver.close()
    rows=[e['row'] for e in map(json.loads,(output/'telemetry/received.jsonl').read_text().splitlines()) if e['kind']=='sample']
    checks['stale_zero_recorded']=any(r.get('cell_observer_state')=='STALE' and r.get('vehicle_limit_requested_fraction')==0
        and r.get('vehicle_limit_applied_fraction')==0 for r in rows)
    checks['gaps_disclosed']=max(r.get('cell_timing',{}).get('excluded_intervals',0) for r in rows)>=2
    result=dict(mock_only=True,passed=len(checks)==9 and all(checks.values()) and zero,checks=checks,
        native_zero_shutdown=zero,mock_shutdown=instrument['final']['shutdown_verified'],telemetry=timing['statistics'])
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    assert result['passed'],result


if __name__=='__main__':main()
