"""Reproducible native MOCK power-limit trials; no OS input/instrument access."""
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

from configure_tesla import ROOT,RUNTIME,TORCS
from run_tesla_ai import build
import validate_keyboard as keyboard
from run_vehicle_power_limit import profile_for
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from torcs_live import LiveReceiver
from vehicle_power_limit import DemoPolicy,PowerFeedback


def plot_comparison(output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,sharex=True,figsize=(9,7))
    for name in ('100','70','50','20'):
        with (output/name/'telemetry/live_profile.csv').open() as f:
            rows=[r for r in csv.DictReader(f) if float(r['time_s'])<=2]
        t=[float(r['time_s']) for r in rows]
        axes[0].plot(t,[float(r['speed_mps']) for r in rows],label=name+'%')
        axes[1].plot(t,[float(r['motor_power_W'])/1000 for r in rows],label=name+'%')
    axes[0].set_ylabel('Speed (m/s)');axes[1].set_ylabel('Delivered motor power (kW)')
    axes[1].set_xlabel('Simulation time (s)')
    for ax in axes:ax.grid();ax.legend()
    fig.suptitle('MOCK availability: same native keyboard inputs / initial conditions')
    fig.tight_layout();fig.savefig(output/'comparison.png');plt.close(fig)


def native_fault_trial(output):
    output=output.resolve()
    output.mkdir()
    class ObservedFeedback(PowerFeedback):
        def handle(self,row,payload,address,sock):
            self.address=address
            return super().handle(row,payload,address,sock)
    feedback=ObservedFeedback(DemoPolicy(fixed_fraction=.5))
    receiver=LiveReceiver(0,output/'telemetry',power_feedback=feedback)
    profile=profile_for('ai')
    env=dict(os.environ,APS380_MOCK_POWER_LIMIT='1',APS380_LIVE_PORT=str(receiver.port),
        APS380_LIVE_REALTIME='1',APS380_TORCS_PROFILE=str(profile),APS380_AI_LOG=str(output/'driver.csv'))
    receiver.start();child=None;flags=set();states=[]
    try:
        with (output/'torcs.log').open('w') as log:
            child=subprocess.Popen([str(RUNTIME/'wtorcs.exe'),'-r',str(profile/'race.xml')],cwd=RUNTIME,env=env,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.perf_counter()+20
            while time.perf_counter()<deadline:
                row=feedback.latest;t=row.get('time_s',-1)
                state=row.get('vehicle_limit_state');fraction=row.get('vehicle_limit_applied_fraction')
                if state and (not states or state!=states[-1]):states.append(state)
                if t>=2 and 'paused' not in flags:feedback.paused.set();flags.add('paused')
                if 3<t<4 and state=='FAULT_STALE' and fraction==0:flags.add('stale_zero')
                if t>=4 and 'resumed' not in flags:feedback.paused.clear();flags.add('resumed')
                if 4.5<t<5 and state=='FAULT_STALE' and fraction==0:flags.add('latch_preserved')
                if t>=5 and 'reset' not in flags:feedback.request_reset();flags.add('reset')
                if 5.5<t<7 and state=='ACTIVE' and fraction==.5:flags.add('recovered')
                if t>=7 and 'invalid_sent' not in flags:
                    # Send from the exact registered receiver endpoint, so the
                    # native parser (not an unrelated sender filter) is tested.
                    native_address=feedback.address
                    bad=f'APS380POWER1 {feedback.session} {feedback.sequence} {time.perf_counter():.9f} 1.5 0'
                    receiver.socket.sendto(bad.encode(),native_address);flags.add('invalid_sent')
                if 7.5<t<9 and state=='FAULT_INVALID' and fraction==0:flags.add('invalid_zero')
                if t>=9 and 'reset_again' not in flags:feedback.request_reset();flags.add('reset_again')
                if t>9.5 and state=='ACTIVE' and fraction==.5:flags.add('recovered_again');break
                if receiver.failed or child.poll() is not None:raise RuntimeError('Native fault trial failed')
                time.sleep(.01)
            feedback.request_stop();zero=feedback.stop_verified.wait(1.)
    finally:
        receiver.begin_shutdown()
        if child and child.poll() is None:child.terminate();child.wait(timeout=10)
        timing=receiver.close()
    required={'stale_zero','latch_preserved','recovered','invalid_zero','recovered_again'}
    assert required<=flags,(flags,states)
    assert zero and not receiver.failed
    assert timing['statistics']['missing']==timing['statistics']['invalid']==0 and not timing['stale_intervals']
    fault_rows=[r for r in receiver.processor.history if r.get('vehicle_limit_state','').startswith('FAULT')]
    assert fault_rows and all(r['motor_power_W']<=0 and r['vehicle_limit_applied_fraction']==0 for r in fault_rows)
    report=dict(passed=True,mock_only=True,checks=sorted(flags),states=states,shutdown_zero_verified=zero,telemetry=timing)
    (output/'trial.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.local/matplotlib'))
    protected={str(root):keyboard.fingerprint(root) for root in (keyboard.G29_PROFILE,Path(os.environ['LOCALAPPDATA'])/'torcs')}
    build(ROOT/'scripts/tests/keyboard_fixture.vcxproj',output/'fixture-build.log')
    # Existing fixture compiles human.cpp but substitutes test key states and
    # disables joystick polling. Never install over human.dll.
    source=ROOT/'.local/keyboard-tests/aps380_keyboard_fixture.dll'
    target=RUNTIME/'drivers/aps380_keyboard_fixture/aps380_keyboard_fixture.dll'
    assert not target.exists(),'Existing fixture installation must not be overwritten'
    sources=[Path(__file__),ROOT/'aps380_torcs_starter/vehicle_power_limit.py',
        ROOT/'aps380_torcs_starter/torcs_live.py',ROOT/'aps380_torcs_starter/profiles/keyboard_driving.json',
        TORCS/'src/modules/simu/simuv2/aps380_ev.h',TORCS/'src/modules/simu/simuv2/aps380_power_limit.h',
        TORCS/'src/modules/simu/simuv2/aps380_live.h',TORCS/'src/modules/simu/simuv2/simu.cpp',
        RUNTIME/'modules/simu/simuv2.dll',source]
    (output/'manifest.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},indent=2)+'\n')
    results={};traces={}
    try:
        for fraction in (None,1.,.7,.5,.2):
            name='default' if fraction is None else str(int(fraction*100))
            folder=output/name;folder.mkdir()
            feedback=PowerFeedback(DemoPolicy(fixed_fraction=fraction)) if fraction is not None else None
            def receiver_factory(*a,**kw):return LiveReceiver(*a,**kw,power_feedback=feedback)
            with patch.object(keyboard,'LiveReceiver',side_effect=receiver_factory),patch.dict(os.environ,{'APS380_MOCK_POWER_LIMIT':'1' if feedback else '0'}):
                trial=keyboard.trial(folder)
            with (folder/'telemetry/live_profile.csv').open() as f:rows=list(csv.DictReader(f))
            window=[r for r in rows if 1<=float(r['time_s'])<=2]
            first,last=window[0],window[-1]
            metric=dict(speed_at_2_s=float(last['speed_mps']),
                mean_accel_1_to_2_s=(float(last['speed_mps'])-float(first['speed_mps']))/(float(last['time_s'])-float(first['time_s'])),
                peak_motor_power_first_2_s=max(float(r['motor_power_W']) for r in rows if float(r['time_s'])<=2),
                samples=trial['telemetry']['samples'],mock_instrument_shutdown=trial['instruments']['acceptance']['passed'])
            if feedback:
                assert any(float(r.get('vehicle_limit_applied_fraction') or 0)==fraction for r in rows)
            traces[name]={r['time_s']:(float(r['throttle']),float(r['brake'])) for r in window}
            results[name]=metric;print(name,metric,flush=True)
        for key in ('speed_at_2_s','mean_accel_1_to_2_s','peak_motor_power_first_2_s'):
            assert results['100'][key]>results['70'][key]>results['50'][key]>results['20'][key],(key,results)
        common=set.intersection(*(set(t) for t in traces.values()))
        assert len(common)>=40
        assert all(max(abs(a-b) for a,b in zip(traces['100'][t],traces[n][t]))<1e-6 for n in traces for t in common),'Input comparison differs'
        results['fault_recovery']=native_fault_trial(output/'faults')
        results['matched_input_samples']=len(common)
        plot_comparison(output)
    finally:
        if target.exists():
            assert hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256(source.read_bytes()).digest()
            target.unlink()
            if not any(target.parent.iterdir()):target.parent.rmdir()
        results['g29_profiles_preserved']=all(keyboard.fingerprint(root)==hashes for root,hashes in protected.items())
        (output/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
        assert results['g29_profiles_preserved']
    print('PASS',output,flush=True)


if __name__=='__main__':main()
