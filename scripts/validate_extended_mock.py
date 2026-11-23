"""Full-range virtual-clock mocks plus matched-input actual native TORCS trials.

No physical transport. Full +/- current endpoints use virtual-clock plant tests;
native trials use real time, real telemetry and the real human-driver fixture.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from test_extended_mock import ExtendedRig
from mock_test_config import BASE,resolve_mock_test_config
from battery_bias import BatteryBiasService
from battery_bias_feedback import BiasRintPolicy
from torcs_live import LiveReceiver
from vehicle_power_limit import PowerFeedback
import validate_keyboard as keyboard


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--analyze-existing',action='store_true',help='Recheck completed native trial logs without launching TORCS')
    args=p.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=args.analyze_existing)
    rig=ExtendedRig();rig.ready()
    for current,steps in ((-5.,2700),(1.,3400),(-5.,3400),(0.,2800)):rig.follow(current,steps)
    rig.c.disarm();assert rig.c.snapshot()['shutdown_verified']
    with (output/'full_range.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rig.trace[0]));w.writeheader();w.writerows(rig.trace)
    summary=dict(mock_only=True,full_range_virtual_clock=dict(passed=True,
        measured_min_A=min(r['measured_A'] for r in rig.trace),measured_max_A=max(r['measured_A'] for r in rig.trace),
        maximum_load_A=max(r['load_A'] for r in rig.trace),
        soc_first=rig.trace[0]['soc'],soc_last=rig.trace[-1]['soc'],
        coulomb_independently_reintegrated=True,shutdown_verified=True),native={})
    fixture=keyboard.RUNTIME/'drivers/aps380_keyboard_fixture/aps380_keyboard_fixture.dll'
    if not args.analyze_existing:
        if fixture.exists():raise RuntimeError('Fixture already installed; refusing to overwrite')
        keyboard.build(ROOT/'scripts/tests/keyboard_fixture.vcxproj',output/'fixture-build.log')
    protected=keyboard.fingerprint(keyboard.G29_PROFILE)
    traces={}
    try:
        for name,ceiling in (('extended',5.),('reduced',.2)):
            data=json.loads((BASE/'profiles/mock_test_extended_5a.json').read_text())
            data.update(initial_soc_fraction=.8,sop_discharge_ceiling_A=ceiling,experiment_scale=.5)
            cfg=resolve_mock_test_config(data)
            folder=output/name;box={}
            if not args.analyze_existing:
                folder.mkdir();(folder/'effective.json').write_text(json.dumps(cfg.audit,indent=2)+'\n')
            else:
                saved=json.loads((folder/'effective.json').read_text())
                assert saved['requested']==cfg.audit['requested']
                for key in ('control','sop_model','scaling'):
                    assert saved['effective'][key]==cfg.audit['effective'][key],key
            def service_factory(path):
                service=BatteryBiasService(path,cfg.control,sop_config=cfg.model);service.psu.cv_available_A=cfg.source_A
                feedback=PowerFeedback(BiasRintPolicy(service));box.update(service=service,feedback=feedback)
                close=service.close
                def finish():
                    feedback.request_stop();box['zero']=feedback.stop_verified.wait(1.)
                    return close()
                service.close=finish
                return service
            def receiver_factory(*a,**kw):
                feedback=box['feedback']
                receiver=LiveReceiver(*a,**kw,power_feedback=feedback,current_config=cfg.control,scaling_config=cfg.scaling)
                feedback.policy.configure(receiver.processor.cell,receiver.processor.profile)
                return receiver
            if not args.analyze_existing:
                with patch.object(keyboard,'MockInstrumentService',side_effect=service_factory),patch.object(keyboard,'LiveReceiver',side_effect=receiver_factory),patch.dict(os.environ,{'APS380_MOCK_POWER_LIMIT':'1','APS380_FIXTURE_START_S':'60'}):
                    keyboard.trial(folder,duration_s=74.)
            rows=[e['row'] for e in map(json.loads,(folder/'telemetry/received.jsonl').read_text().splitlines()) if e['kind']=='sample']
            active=[r for r in rows if r.get('bias_controller_state')=='RUNNING']
            window=[r for r in rows if 67<=r['time_s']<=68]
            sent={r['vehicle_limit_sent_sequence']:r['vehicle_limit_requested_fraction'] for r in rows if 'vehicle_limit_sent_sequence' in r}
            acks=[r for r in rows if r.get('vehicle_limit_state')=='ACTIVE' and r['vehicle_limit_ack_sequence'] in sent]
            assert acks and all(abs(r['vehicle_limit_applied_fraction']-sent[r['vehicle_limit_ack_sequence']])<1e-9 for r in acks)
            # Verify a shutdown zero generated while the RUNNING model still
            # permitted positive SOP, not a startup/unavailable-model zero.
            zero_commands={r['vehicle_limit_sent_sequence'] for r in rows if
                'vehicle_limit_sent_sequence' in r and r.get('bias_controller_state')=='RUNNING'
                and r.get('sop_model_valid') and r.get('sop_max_discharge_W',0)>0
                and r.get('vehicle_limit_requested_fraction')==0}
            zero=any(r['vehicle_limit_ack_sequence'] in zero_commands and r['vehicle_limit_applied_fraction']==0 for r in acks)
            assert zero and not any(r.get('vehicle_limit_error') for r in rows)
            trial=json.loads((folder/'trial.json').read_text())
            assert trial['instruments']['acceptance']['passed'] and trial['instruments']['final']['shutdown_verified']
            assert active and max(r['throttle'] for r in window)>0
            regen=[r for r in active if r['throttle']<.05 and r['brake']==0 and r['cell_current_command_A']>0]
            assert any(r['throttle']<.05 and r['brake']==0 for r in active)
            if name=='extended':assert regen,'No native lift-off regeneration in extended driving case'
            summary['native'][name]=dict(passed=True,matched_acks=len(acks),native_zero=True,
                mock_shutdown=trial['instruments']['final']['shutdown_verified'],regen_samples=len(regen),
                peak_motor_W=max(r['motor_power_W'] for r in window),speed_at_68_mps=window[-1]['speed_mps'],
                native_measured_cell_range_A=[min(r['cell_mock_measured_current_A'] for r in active),max(r['cell_mock_measured_current_A'] for r in active)])
            traces[name]=rows
            print(name,summary['native'][name],flush=True)
        assert summary['native']['extended']['peak_motor_W']>summary['native']['reduced']['peak_motor_W']
        inputs=lambda name:{r['time_s']:(r['throttle'],r['brake']) for r in traces[name] if 67<=r['time_s']<=68}
        x,y=inputs('extended'),inputs('reduced');common=x.keys() & y.keys()
        assert len(common)>=40 and all(x[t]==y[t] for t in common)
        summary['matched_inputs']=len(common)
    finally:
        if not args.analyze_existing and fixture.exists():
            assert hashlib.sha256(fixture.read_bytes()).digest()==hashlib.sha256((ROOT/'.local/keyboard-tests/aps380_keyboard_fixture.dll').read_bytes()).digest()
            fixture.unlink()
        assert keyboard.fingerprint(keyboard.G29_PROFILE)==protected
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,1,sharex=True,figsize=(11,8),layout='constrained')
    for field in ('target_A','applied_A','measured_A'):axes[0].plot([r['time_s'] for r in rig.trace],[r[field] for r in rig.trace],label=field)
    axes[0].legend();axes[0].set_ylabel('Signed mock cell A')
    axes[1].plot([r['time_s'] for r in rig.trace],[r['soc']*100 for r in rig.trace]);axes[1].set_ylabel('SOC % [mock counted]')
    axes[2].plot([r['time_s'] for r in rig.trace],[r['sop_W'] for r in rig.trace]);axes[2].set_ylabel('SOP W [unvalidated]')
    axes[2].set_xlabel('Virtual instrument seconds; no shortened slew')
    fig.savefig(output/'full_range.png',dpi=140);plt.close(fig)
    fig,axes=plt.subplots(2,1,sharex=True,figsize=(11,7),layout='constrained')
    for name,rows in traces.items():
        axes[0].plot([r['time_s'] for r in rows],[r['motor_power_W'] for r in rows],label=name)
        axes[1].plot([r['time_s'] for r in rows],[r['vehicle_limit_applied_fraction'] for r in rows],label=name)
    axes[0].set_ylabel('Actual native motor W');axes[0].legend()
    axes[1].set_ylabel('Native applied fraction');axes[1].set_xlabel('Native simulation seconds; inputs begin at 60 s')
    fig.savefig(output/'native_comparison.png',dpi=140);plt.close(fig)
    summary['passed']=True
    summary['scope']='Full 5 A endpoints: deterministic virtual-clock mock plant. Native trials: real-time driving requests, not a claim of native driving reaching 5 A.'
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
