"""Actual TORCS, synthetic Rint assumptions, existing mock controller; no hardware."""
from dataclasses import replace
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

from configure_tesla import ROOT,RUNTIME
from run_tesla_ai import build
from run_vehicle_power_limit import profile_for
import validate_keyboard as keyboard
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from cell_sop import RintParameters,RintPolicy
from torcs_live import LiveReceiver
from vehicle_power_limit import PowerFeedback

CONFIG=ROOT/'aps380_torcs_starter/profiles/rint_sop_mock_example.json'


def plot_comparison(output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,sharex=True,figsize=(9,7))
    for name,label in (('full','1.0 A assumed cap'),('reduced','0.5 A assumed cap'),('low','0.2 A assumed cap')):
        with (output/name/'telemetry/live_profile.csv').open() as f:
            rows=[r for r in csv.DictReader(f) if float(r['time_s'])<=2]
        t=[float(r['time_s']) for r in rows]
        axes[0].plot(t,[float(r['speed_mps']) for r in rows],label=label)
        axes[1].plot(t,[float(r['motor_power_W'])/1000 for r in rows],label=label)
    axes[0].set_ylabel('Speed (m/s)');axes[1].set_ylabel('Delivered motor power (kW)')
    axes[1].set_xlabel('Simulation time (s)')
    for ax in axes:ax.grid();ax.legend()
    fig.suptitle('MOCK Rint SOP assumptions: identical TORCS keyboard inputs')
    fig.tight_layout();fig.savefig(output/'comparison.png');plt.close(fig)


def model_fault_trial(output,parameters):
    output=output.resolve();output.mkdir()
    policy=RintPolicy(parameters,.8,25.);feedback=PowerFeedback(policy)
    receiver=LiveReceiver(0,output/'telemetry',power_feedback=feedback)
    policy.configure(receiver.processor.cell,receiver.processor.profile)
    profile=profile_for('ai');child=None;flags=set()
    env=dict(os.environ,APS380_MOCK_POWER_LIMIT='1',APS380_LIVE_PORT=str(receiver.port),
        APS380_LIVE_REALTIME='1',APS380_TORCS_PROFILE=str(profile),APS380_AI_LOG=str(output/'driver.csv'))
    receiver.start()
    try:
        with (output/'torcs.log').open('w') as log:
            child=subprocess.Popen([str(RUNTIME/'wtorcs.exe'),'-r',str(profile/'race.xml')],cwd=RUNTIME,env=env,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.perf_counter()+15
            while time.perf_counter()<deadline:
                r=feedback.latest;t=r.get('time_s',-1);state=r.get('vehicle_limit_state')
                if t>=2 and 'invalid_model' not in flags:policy.mock_temperature_C=99.;flags.add('invalid_model')
                if 3<t<4 and state=='FAULT_STALE' and r.get('vehicle_limit_applied_fraction')==0:flags.add('zero_latched')
                if t>=4 and 'valid_again' not in flags:policy.mock_temperature_C=25.;flags.add('valid_again')
                if 4.5<t<5 and state=='FAULT_STALE' and r.get('sop_model_valid'):flags.add('no_automatic_recovery')
                if t>=5 and 'reset' not in flags:feedback.request_reset();flags.add('reset')
                if t>5.5 and state=='ACTIVE' and r.get('vehicle_limit_applied_fraction',0)>0:flags.add('explicit_recovery');break
                if receiver.failed or child.poll() is not None:raise RuntimeError('Model fault experiment failed')
                time.sleep(.01)
            feedback.request_stop();zero=feedback.stop_verified.wait(1.)
    finally:
        receiver.begin_shutdown()
        if child and child.poll() is None:child.terminate();child.wait(timeout=10)
        timing=receiver.close()
    assert {'zero_latched','no_automatic_recovery','explicit_recovery'}<=flags,flags
    assert zero and not timing['receiver_error'] and timing['statistics']['invalid']==timing['statistics']['missing']==0
    fault_rows=[r for r in receiver.processor.history if r.get('vehicle_limit_state','').startswith('FAULT')]
    assert fault_rows and all(r['motor_power_W']<=0 for r in fault_rows)
    result=dict(mock_only=True,normal_operation_passed=False,fault_response_passed=True,
        shutdown_zero_verified=zero,checks=sorted(flags),telemetry=timing)
    (output/'trial.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    output=p.parse_args().output.resolve();output.mkdir(parents=True,exist_ok=False)
    os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.local/matplotlib'))
    parameters=RintParameters(**json.loads(CONFIG.read_text())['parameters'])
    protected={str(root):keyboard.fingerprint(root) for root in (keyboard.G29_PROFILE,Path(os.environ['LOCALAPPDATA'])/'torcs')}
    build(ROOT/'scripts/tests/keyboard_fixture.vcxproj',output/'fixture-build.log')
    target=RUNTIME/'drivers/aps380_keyboard_fixture/aps380_keyboard_fixture.dll'
    source=ROOT/'.local/keyboard-tests/aps380_keyboard_fixture.dll';assert not target.exists()
    sources=[Path(__file__),CONFIG,source,RUNTIME/'modules/simu/simuv2.dll']
    sources += [ROOT/'aps380_torcs_starter'/name for name in ('cell_sop.py','cell_soc.py','cell_scaling.py','vehicle_power_limit.py',
        'profiles/eve_35v_ocv_candidate.json','profiles/live_scaling_demo.json','profiles/tesla_model3_rwd.json','profiles/keyboard_driving.json')]
    (output/'manifest.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},indent=2)+'\n')
    result={};inputs={}
    try:
        for name,current in (('full',1.),('reduced',.5),('low',.2)):
            folder=output/name;folder.mkdir()
            policy=RintPolicy(replace(parameters,maximum_discharge_A=current),.8,25.)
            feedback=PowerFeedback(policy)
            def factory(*a,**kw):
                r=LiveReceiver(*a,**kw,power_feedback=feedback)
                policy.configure(r.processor.cell,r.processor.profile);return r
            with patch.object(keyboard,'LiveReceiver',side_effect=factory),patch.dict(os.environ,{'APS380_MOCK_POWER_LIMIT':'1'}):
                trial=keyboard.trial(folder)
            with (folder/'telemetry/live_profile.csv').open() as f:rows=list(csv.DictReader(f))
            active=[r for r in rows if r['vehicle_limit_state']=='ACTIVE']
            window=[r for r in rows if 1<=float(r['time_s'])<=2]
            inputs[name]={r['time_s']:(float(r['throttle']),float(r['brake'])) for r in window}
            assert all(float(r['sop_motor_delivered_W'])<=float(r['sop_motor_allowable_W'])+.01 for r in active)
            assert all(abs(float(r['vehicle_limit_applied_fraction'])-float(r['sop_vehicle_fraction']))<1e-8 for r in active)
            report=dict(mock_only=True,current_limit_assumption_A=current,
                estimated_cell_sop_W=float(active[-1]['sop_max_discharge_W']),
                vehicle_fraction=float(active[-1]['sop_vehicle_fraction']),
                speed_at_2_s=float(window[-1]['speed_mps']),
                peak_motor_power_first_2_s_W=max(float(r['motor_power_W']) for r in rows if float(r['time_s'])<=2),
                samples=trial['telemetry']['samples'],mock_shutdown_verified=trial['instruments']['acceptance']['passed'])
            (folder/'sop_policy.json').write_text(json.dumps(policy.describe(),indent=2)+'\n')
            result[name]=report;print(name,report,flush=True)
        for key in ('speed_at_2_s','peak_motor_power_first_2_s_W'):
            assert result['full'][key]>result['reduced'][key]>result['low'][key]
        assert result['full']['vehicle_fraction']==1 and 0<result['low']['vehicle_fraction']<result['reduced']['vehicle_fraction']<1
        common=set.intersection(*(set(t) for t in inputs.values()))
        assert len(common)>=40
        assert all(max(abs(a-b) for a,b in zip(inputs['full'][t],inputs[n][t]))<1e-6 for n in inputs for t in common)
        result['matched_input_samples']=len(common)
        plot_comparison(output)
        result['model_fault']=model_fault_trial(output/'model-fault',replace(parameters,maximum_discharge_A=.5))
    finally:
        if target.exists():
            assert hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256(source.read_bytes()).digest()
            target.unlink()
            if not any(target.parent.iterdir()):target.parent.rmdir()
        result['g29_profiles_preserved']=all(keyboard.fingerprint(root)==hashes for root,hashes in protected.items())
        (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
        assert result['g29_profiles_preserved']
    print('PASS',output,flush=True)


if __name__=='__main__':main()
