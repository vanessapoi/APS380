"""Native TORCS + Battery Bias mocks: explicit disarm/stop/recovery and demand loss."""
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
from vehicle_power_limit import PowerFeedback
from torcs_live import LiveReceiver
from live_torcs import prepare_launch_profile,RUNTIME


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    output=p.parse_args().output.resolve();output.mkdir(parents=True,exist_ok=False)
    model=json.loads((ROOT/'aps380_torcs_starter/profiles/rint_sop_live_mock_example.json').read_text())
    service=BatteryBiasService(output/'instruments',sop_config=model);service.psu.cv_available_A=.05
    feedback=PowerFeedback(BiasRintPolicy(service));receiver=LiveReceiver(0,output/'telemetry',power_feedback=feedback,demand_sink=service.demands)
    feedback.policy.configure(receiver.processor.cell,receiver.processor.profile)
    profile=prepare_launch_profile('ai');child=None;checks={};zero=False
    def wait(predicate,timeout=12.):
        deadline=time.perf_counter()+timeout
        while time.perf_counter()<deadline:
            if predicate():return
            if receiver.failed or (child and child.poll() is not None):raise RuntimeError('Native/receiver failed')
            time.sleep(.02)
        raise AssertionError(('Condition timed out',service.latest,feedback.latest))
    active=lambda:feedback.latest.get('vehicle_limit_applied_fraction',0)>0 and service.latest['state']=='RUNNING'
    stopped=lambda:feedback.latest.get('vehicle_limit_applied_fraction')==0 and feedback.latest.get('vehicle_limit_state','').startswith('FAULT')
    receiver.start();service.start()
    try:
        with (output/'torcs.log').open('w') as log:
            env=dict(os.environ,APS380_MOCK_POWER_LIMIT='1',APS380_LIVE_PORT=str(receiver.port),APS380_LIVE_REALTIME='1',APS380_TORCS_PROFILE=str(profile),APS380_AI_LOG=str(output/'driver.csv'))
            child=subprocess.Popen([str(RUNTIME/'wtorcs.exe'),'-r',str(profile/'race.xml')],cwd=RUNTIME,env=env,stdout=log,stderr=subprocess.STDOUT)
            wait(lambda:service.demands.snapshot()[0] is not None);service.request('arm');wait(active)
            checks['normal_active']=True
            service.request('disarm');wait(lambda:service.latest['state']=='DISARMED');wait(stopped)
            checks['disarm_zero']=service.latest['shutdown_verified']
            service.request('arm');wait(lambda:service.latest['state']=='RUNNING')
            time.sleep(.3);assert feedback.latest['vehicle_limit_applied_fraction']==0
            feedback.request_reset();wait(active);checks['disarm_explicit_recovery']=True
            service.request('emergency_stop');wait(lambda:service.latest['state']=='FAULT');wait(stopped)
            checks['stop_zero']=service.latest['shutdown_verified']
            service.request('recover');wait(lambda:service.latest['state']=='DISARMED')
            service.request('arm');wait(lambda:service.latest['state']=='RUNNING')
            assert feedback.latest['vehicle_limit_applied_fraction']==0
            feedback.request_reset();wait(active);checks['stop_explicit_recovery']=True
            # Cut the validated demand stream while native telemetry continues;
            # this allows native applied-zero confirmation after a telemetry-demand fault.
            receiver.demand_sink=None;service.demands.publish(None,'STALE_TELEMETRY_INJECTED')
            wait(lambda:service.latest['state']=='FAULT');wait(stopped)
            checks['demand_loss_zero']=service.latest['shutdown_verified']
            feedback.request_stop();zero=feedback.stop_verified.wait(1.);assert zero
    finally:
        instrument=service.close();receiver.begin_shutdown()
        if child and child.poll() is None:child.terminate();child.wait(timeout=10)
        timing=receiver.close()
    result=dict(passed=all(checks.values()) and zero,mock_only=True,checks=checks,
        native_zero_shutdown=zero,instrument_shutdown=instrument['final']['shutdown_verified'],
        scope='Demand-stream loss injected while native UDP continues; separate process-loss test covers UDP silence')
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    assert result['passed'] and timing['statistics']['invalid']==timing['statistics']['missing']==0


if __name__=='__main__':main()
