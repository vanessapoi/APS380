"""Actual TORCS + synthetic branch-readback SOC/SOP; no physical instruments."""
import argparse
import copy
import csv
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

from configure_tesla import ROOT, RUNTIME
from run_vehicle_power_limit import parse_args, profile_for
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from instrument_control import MockInstrumentService
from live_cell_state import MockCellStream
from torcs_live import LiveReceiver
from vehicle_power_limit import PowerFeedback

CONFIG=ROOT/'aps380_torcs_starter/profiles/rint_sop_live_mock_example.json'


def sample_rows(folder):
    return [e['row'] for e in (json.loads(x) for x in (folder/'telemetry/received.jsonl').read_text().splitlines()) if e['kind']=='sample']


def matched_driving(output):
    """Actual human.cpp scripted keys; measured mock current drives live SOC."""
    import validate_keyboard as keyboard
    from cell_sop import RintPolicy
    from vehicle_power_limit import DemoPolicy
    target=RUNTIME/'drivers/aps380_keyboard_fixture/aps380_keyboard_fixture.dll'
    source=ROOT/'.local/keyboard-tests/aps380_keyboard_fixture.dll'
    assert not target.exists(),'A fixture is already installed; stop rather than overwrite it'
    results={};inputs={};plots={}
    try:
        cases=(('live_full',.8,1.),('live_reduced',.8,.5),('live_low_current',.8,.2),
               ('live_low_soc',.2,.5),('fixed_rint',.8,.5),('demo',.8,1.))
        for name,soc,current in cases:
            folder=output/name;folder.mkdir()
            args=parse_args(['--policy','rint-live-mock','--sop-config',str(CONFIG)])
            args.observer.reset(soc)
            policy=args.policy
            policy.estimator.p=replace(policy.estimator.p,maximum_discharge_A=current)
            if name=='fixed_rint':policy=RintPolicy(policy.estimator.p,soc,25.)
            if name=='demo':policy=DemoPolicy()
            feedback=PowerFeedback(policy);stream=None;shutdown={}
            if name.startswith('live_'):
                stream=MockCellStream(args.observer,folder/'cell_measurements.jsonl',voltage_V=3.65,temperature_C=25.)
            def service_factory(*a,**kw):
                service=MockInstrumentService(*a,**kw,measurement_sink=stream)
                if stream:policy.on_fault=lambda:service.request('emergency_stop')
                close=service.close
                def finish():
                    if stream:
                        stream.close();shutdown['observer']=args.observer.snapshot()
                    feedback.request_stop()
                    shutdown['native_zero']=feedback.stop_verified.wait(1.)
                    return close()
                service.close=finish
                return service
            def receiver_factory(*a,**kw):
                r=LiveReceiver(*a,**kw,power_feedback=feedback)
                if hasattr(policy,'configure'):policy.configure(r.processor.cell,r.processor.profile)
                return r
            try:
                with patch.object(keyboard,'MockInstrumentService',side_effect=service_factory),patch.object(keyboard,'LiveReceiver',side_effect=receiver_factory),patch.dict(os.environ,{'APS380_MOCK_POWER_LIMIT':'1'}):
                    trial=keyboard.trial(folder)
            finally:
                if stream:stream.close()
            assert shutdown['native_zero'],name
            rows=sample_rows(folder);active=[r for r in rows if r['vehicle_limit_state']=='ACTIVE']
            sent={r['vehicle_limit_sent_sequence']:r['vehicle_limit_requested_fraction'] for r in rows if 'vehicle_limit_sent_sequence' in r}
            assert all(abs(r['vehicle_limit_applied_fraction']-sent[r['vehicle_limit_ack_sequence']])<1e-9 for r in active if r['vehicle_limit_ack_sequence'] in sent)
            window=[r for r in rows if 1<=r['time_s']<=2]
            inputs[name]={r['time_s']:(r['throttle'],r['brake']) for r in window}
            stats=dict(mock_only=True,soc_assumption=soc,current_cap_assumption_A=current,
                samples=len(rows),speed_at_2_s=window[-1]['speed_mps'],
                peak_motor_first_2_s_W=max(r['motor_power_W'] for r in rows if r['time_s']<=2),
                native_zero_shutdown=shutdown['native_zero'],mock_shutdown=trial['instruments']['final']['shutdown_verified'])
            if stream:
                events=[json.loads(x) for x in (folder/'cell_measurements.jsonl').read_text().splitlines()]
                accepted=[e for e in events if e['accepted']]
                measurements=[e['sample']['measurement'] for e in accepted]
                charge=sum((a['net_cell_current_A']+b['net_cell_current_A'])/2*(b['time_s']-a['time_s'])/3600 for a,b in zip(measurements,measurements[1:]))
                final=shutdown['observer']['estimate']['soc']
                assert shutdown['observer']['state']=='VALID' and abs(final-(soc+charge/policy.estimator.p.capacity_Ah))<1e-12
                # Check every displayed/logged policy state against its exact measurement sequence.
                counted={e['sample']['sequence']:e['observer']['estimate']['soc'] for e in accepted}
                valid=[r for r in rows if r.get('cell_observer_state')=='VALID']
                for r in valid:
                    assert r['sop_cell_soc_fraction']==counted[r['cell_measurement_sequence']]
                    assert abs(r['sop_ocv_candidate_V']-policy.estimator.reference.voltage(r['sop_cell_soc_fraction']))<1e-12
                    expected=policy.estimator.estimate(r['sop_cell_soc_fraction'],25.)
                    assert abs(r['sop_max_discharge_W']-expected['sop_max_discharge_W'])<1e-12
                charge_steps=discharge_steps=0
                for a,b in zip(accepted,accepted[1:]):
                    ma,mb=a['sample']['measurement'],b['sample']['measurement']
                    mean=(ma['net_cell_current_A']+mb['net_cell_current_A'])/2
                    before=a['observer']['estimate']['soc'];after=b['observer']['estimate']['soc']
                    assert abs(after-before-mean*(mb['time_s']-ma['time_s'])/(3600*policy.estimator.p.capacity_Ah))<1e-12
                    if mean>.001:
                        assert after>before;charge_steps+=1
                    elif mean<-.001:
                        assert after<before;discharge_steps+=1
                branches=[json.loads(x) for x in (folder/'instruments/instruments.jsonl').read_text().splitlines()]
                assert any(abs(e.get('tracking_error_A',0))>1e-6 for e in branches), 'Need evidence that readbacks differ from applied demand'
                assert max(counted.values())>min(counted.values())
                stats.update(final_soc=final,integrated_charge_Ah=charge,charging_soc_steps=charge_steps,
                    discharging_soc_steps=discharge_steps,measured_current_range_A=[min(m['net_cell_current_A'] for m in measurements),max(m['net_cell_current_A'] for m in measurements)],
                    applied_fraction_range=[min(r['vehicle_limit_applied_fraction'] for r in valid if r['vehicle_limit_applied_fraction']>0),max(r['vehicle_limit_applied_fraction'] for r in valid)],
                    sop_range_W=[min(r['sop_max_discharge_W'] for r in valid),max(r['sop_max_discharge_W'] for r in valid)])
            elif name=='fixed_rint':
                assert all(r['sop_cell_soc_fraction']==soc for r in rows)
                assert len({r['sop_max_discharge_W'] for r in rows})==1
            else:assert all(r['vehicle_limit_requested_fraction']==1. for r in rows if r.get('vehicle_limit_sent_sequence',feedback.stop_sequence)<feedback.stop_sequence)
            assert not feedback.error,name
            results[name]=stats;plots[name]=rows
            (folder/'closed_loop.json').write_text(json.dumps(stats,indent=2)+'\n')
            print(name,stats,flush=True)
        common=set.intersection(*(set(t) for t in inputs.values()))
        assert len(common)>=40
        assert all(inputs[n][t]==inputs['live_full'][t] for n in inputs for t in common)
        for metric in ('speed_at_2_s','peak_motor_first_2_s_W'):
            assert results['live_full'][metric]>results['live_reduced'][metric]>results['live_low_current'][metric]
            assert results['live_reduced'][metric]>results['live_low_soc'][metric]
        assert any(r.get('charging_soc_steps',0)>0 and r.get('discharging_soc_steps',0)>0 for r in results.values())
        import matplotlib.pyplot as plt
        fig,axes=plt.subplots(3,1,sharex=True,figsize=(10,9))
        for name in ('live_full','live_reduced','live_low_current','live_low_soc'):
            rows=[r for r in plots[name] if r['time_s']<=2]
            for ax,key in zip(axes,('speed_mps','motor_power_W','vehicle_limit_applied_fraction')):
                ax.plot([r['time_s'] for r in rows],[r[key] for r in rows],label=name)
        for ax,label in zip(axes,('Speed (m/s)','Actual motor output (W)','Native availability')):
            ax.set_ylabel(label);ax.grid();ax.legend()
        axes[-1].set_xlabel('Simulation seconds; matched scripted human inputs')
        fig.suptitle('Actual TORCS with LIVE MOCK Cell SOC / Rint; unvalidated cell assumptions')
        fig.tight_layout();fig.savefig(output/'matched_power.png');plt.close(fig)
        return dict(passed=True,matched_input_samples=len(common),cases=results)
    finally:
        if target.exists():
            assert hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256(source.read_bytes()).digest()
            target.unlink()
            if not any(target.parent.iterdir()):target.parent.rmdir()


def fault_recovery_matrix(folder):
    """Inject measurement faults while real native telemetry continues."""
    folder.mkdir();args=parse_args(['--policy','rint-live-mock','--sop-config',str(CONFIG)])
    stream=MockCellStream(args.observer,folder/'cell_measurements.jsonl',voltage_V=3.65,temperature_C=25.)
    injection={'kind':None};original_accept=args.observer.accept
    def accept(sample):
        kind=injection['kind']
        if kind in ('stale','missing','reordered'):
            injection['kind']=None
            if kind=='stale':sample=replace(sample,measurement=replace(sample.measurement,time_s=sample.measurement.time_s-1.))
            else:sample=replace(sample,sequence=sample.sequence+(1 if kind=='missing' else -2))
        return original_accept(sample)
    args.observer.accept=accept
    def publish(snapshot):
        if injection['kind']=='invalid':
            injection['kind']=None;snapshot=copy.deepcopy(snapshot)
            snapshot['psu']['current_A']=float('nan')
        stream(snapshot)
    service=MockInstrumentService(folder/'instruments',measurement_sink=publish)
    args.policy.on_fault=lambda:service.request('emergency_stop')
    feedback=PowerFeedback(args.policy)
    receiver=LiveReceiver(0,folder/'telemetry',power_feedback=feedback,demand_sink=service.demands)
    args.policy.configure(receiver.processor.cell,receiver.processor.profile)
    profile=profile_for('ai');child=None;results={};timeline=[];zero=False
    def wait_for(predicate,seconds=5.):
        end=time.perf_counter()+seconds
        while time.perf_counter()<end:
            if receiver.failed or child.poll() is not None:raise RuntimeError('Fault matrix process/telemetry failure')
            if predicate():return
            time.sleep(.01)
        raise AssertionError(dict(stage=timeline[-1] if timeline else 'startup',latest=feedback.latest,instruments=service.latest))
    def mark(event):timeline.append(dict(event=event,host_s=time.perf_counter(),sim_s=feedback.latest.get('time_s')))
    env=dict(os.environ,APS380_MOCK_POWER_LIMIT='1',APS380_LIVE_PORT=str(receiver.port),APS380_LIVE_REALTIME='1',
        APS380_TORCS_PROFILE=str(profile),APS380_AI_LOG=str(folder/'driver.csv'))
    receiver.start();service.start(arm=True)
    try:
        with (folder/'torcs.log').open('w') as log:
            child=subprocess.Popen([str(RUNTIME/'wtorcs.exe'),'-r',str(profile/'race.xml')],cwd=RUNTIME,env=env,stdout=log,stderr=subprocess.STDOUT)
            wait_for(lambda:service.latest['state']=='RUNNING' and feedback.latest.get('vehicle_limit_applied_fraction',0)>0)
            for kind in ('stale','missing','invalid','reordered'):
                mark('inject_'+kind);injection['kind']=kind
                wait_for(lambda:feedback.latest.get('cell_observer_state')=='FAULT' and service.latest['state']=='FAULT' and service.latest['shutdown_verified'] and feedback.latest.get('vehicle_limit_state')=='FAULT_STALE')
                error=args.observer.error
                assert feedback.latest['vehicle_limit_applied_fraction']==0
                assert service.latest['isolation']['is_open'] and service.latest['isolation']['outputs_disabled']
                mark('verified_fault_'+kind)
                feedback.request_reset();time.sleep(.3)
                assert feedback.latest['vehicle_limit_applied_fraction']==0 and args.observer.error
                service.request('recover');wait_for(lambda:service.latest['state']=='DISARMED')
                # Preserve the coordinator's existing post-recovery demand interlock.
                # An immediate ARM in the same telemetry period must be rejected.
                wait_for(lambda:service.demands.snapshot()[0] is not None and
                    service.demands.snapshot()[0].received_s>service.coordinator.recovery_after)
                args.observer.reset(.8);service.request('arm')
                wait_for(lambda:service.latest['state']=='RUNNING' and feedback.latest.get('cell_observer_state')=='VALID')
                mark('valid_again_without_propulsion_reset_'+kind);time.sleep(.3)
                assert feedback.latest['vehicle_limit_state']=='FAULT_STALE' and feedback.latest['vehicle_limit_applied_fraction']==0
                feedback.request_reset()
                wait_for(lambda:feedback.latest.get('vehicle_limit_state')=='ACTIVE' and feedback.latest.get('vehicle_limit_applied_fraction',0)>0)
                mark('explicit_recovery_'+kind)
                results[kind]=dict(passed=True,error=error,outputs_off_isolation_open=True,no_automatic_recovery=True,explicit_recovery=True)
            feedback.request_stop();zero=feedback.stop_verified.wait(1.)
    finally:
        stream.close();instrument=service.close();receiver.begin_shutdown()
        if child and child.poll() is None:child.terminate();child.wait(timeout=10)
        timing=receiver.close()
        (folder/'timeline.json').write_text(json.dumps(timeline,indent=2)+'\n')
    assert zero and not timing['receiver_error'] and timing['statistics']['missing']==timing['statistics']['invalid']==0
    rows=sample_rows(folder)
    assert all(r['motor_power_W']<=.01 for r in rows if r.get('vehicle_limit_state')=='FAULT_STALE')
    result=dict(mock_only=True,normal_operation_passed=False,fault_response_passed=True,cases=results,
        native_zero_shutdown=zero,instruments=instrument,telemetry=timing)
    (folder/'trial.json').write_text(json.dumps(result,indent=2)+'\n')
    return dict(fault_response_passed=True,cases=results,native_zero_shutdown=zero)


def dashboard_regressions(output):
    """Exercise real Tk refresh/canvas callbacks against actual TORCS telemetry."""
    import live_display
    import run_vehicle_power_limit as power
    import run_tesla_live as original
    from run_tesla_ai import prepare_profile
    captured={}
    class RecordingDisplay(live_display.LiveDisplay):
        def __init__(self,*a,**kw):
            super().__init__(*a,**kw)
            self.root.withdraw()  # No human input or desktop-key injection.
            self.observations=[]
        def refresh(self):
            super().refresh()
            self.observations.append(dict(text=self.values.cget('text'),state=self.state_label.cget('text')))
        def run(self):
            try:super().run()
            finally:captured['observations']=self.observations
    results={}
    for name in ('live','original'):
        folder=output/name
        with patch.object(live_display,'LiveDisplay',RecordingDisplay):
            if name=='live':
                code=power.main(['--policy','rint-live-mock','--sop-config',str(CONFIG),
                    '--mode','ai','--duration','8','--skip-build','--mock-arm','--no-console','--output',str(folder)])
            else:
                # Read the existing G29 profile; never run its configuration writer.
                def prepare(destination):return prepare_profile(destination,manual_profile=ROOT/'.local/tesla-profile')
                with patch.object(original,'prepare_profile',side_effect=prepare),patch.object(sys,'argv',
                    ['run_tesla_live.py','--mode','ai','--duration','12','--skip-build','--mock-instruments',
                     '--mock-arm','--acceptance','smoke','--output-dir',str(folder)]):
                    code=original.main()
        assert code in (0,None),(name,code)
        trial=json.loads((folder/'trial.json').read_text())
        assert trial.get('passed',trial.get('all_software_gates_passed')),(name,trial)
        observations=captured['observations']
        assert any(o['state']=='RECEIVING' for o in observations)
        assert any('MOCK RUNNING' in o['text'] for o in observations)
        if name=='live':
            import re
            values={m.group(1) for o in observations for m in
                    [re.search(r'MOCK Coulomb Counted\]: ([0-9.]+)%',o['text'])] if m}
            assert len(values)>1,values
            logged={float(f"{r['sop_cell_soc_fraction']*100:.5f}") for r in sample_rows(folder)
                    if r.get('cell_observer_state')=='VALID'}
            assert all(float(v) in logged for v in values), 'Displayed SOC must match logged counted cell state'
            assert any('Cell stream [MOCK]: VALID' in o['text'] for o in observations)
            assert all('Physical cell V / I / T / SOC: NOT CONNECTED' in o['text'] for o in observations)
        (folder/'dashboard_observations.json').write_text(json.dumps(observations,indent=2)+'\n')
        results[name]=dict(passed=True,refreshes=len(observations),automated_Tk_not_manual_confirmation=True)
    return results


def assess_normal(folder):
    report=json.loads((folder/'trial.json').read_text())
    events=[json.loads(x) for x in (folder/'cell_measurements.jsonl').read_text().splitlines()]
    samples=[e['sample']['measurement'] for e in events if e['accepted']]
    rows=[e['row'] for e in (json.loads(x) for x in (folder/'telemetry/received.jsonl').read_text().splitlines()) if e['kind']=='sample']
    valid=[r for r in rows if r.get('cell_observer_state')=='VALID' and r['vehicle_limit_state']=='ACTIVE']
    expected=sum((a['net_cell_current_A']+b['net_cell_current_A'])/2*(b['time_s']-a['time_s'])/3600
                 for a,b in zip(samples,samples[1:]))
    capacity=json.loads((folder/'sop_config.json').read_text())['parameters']['capacity_Ah']
    initial=events[0]['observer']['estimate']['soc']
    final=report['cell_observer']['estimate']['soc']
    assert report['passed'] and len(valid)>100 and len(samples)>50,report
    assert abs(final-(initial+expected/capacity))<1e-12
    assert final<initial and min(r['sop_max_discharge_W'] for r in valid)<max(r['sop_max_discharge_W'] for r in valid)
    # Match native ACKs to the exact earlier command, not the current row's newer estimate.
    sent={r['vehicle_limit_sent_sequence']:r['vehicle_limit_requested_fraction'] for r in rows if 'vehicle_limit_sent_sequence' in r}
    matched=[r for r in valid if r['vehicle_limit_ack_sequence'] in sent]
    assert len(matched)>100
    assert all(abs(r['vehicle_limit_applied_fraction']-sent[r['vehicle_limit_ack_sequence']])<1e-9 for r in matched)
    assert all(r['motor_power_W']<=r['sop_motor_allowable_W']+.1 for r in matched)
    propulsion=[r for r in matched if r['vehicle_limit_applied_fraction']>0 and r['vehicle_limit_requested_fraction']>0]
    assert min(r['vehicle_limit_applied_fraction'] for r in propulsion)<max(r['vehicle_limit_applied_fraction'] for r in propulsion)
    instruments=[json.loads(x) for x in (folder/'mock_instruments/instruments.jsonl').read_text().splitlines()]
    pairs={(e['psu']['acquired_s'],e['load']['acquired_s']):e for e in instruments
           if 'psu' in e and 'load' in e and not e['measurements_retained']}
    # Every sample must correspond to actual branch readbacks or known open mock isolation.
    for event in events:
        if event['accepted']:
            s=event['sample'];m=s['measurement']
            candidates=[e for pair,e in pairs.items() if max(pair)==m['time_s'] and not e['measurements_retained']]
            assert candidates
            e=candidates[0]
            assert abs(m['net_cell_current_A']-(0 if s['isolation_open'] else e['psu']['current_A']-e['load']['current_A']))<1e-12
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(4,1,sharex=True,figsize=(10,10))
    t=[s['time_s']-samples[0]['time_s'] for s in samples]
    axes[0].plot(t,[s['net_cell_current_A'] for s in samples]);axes[0].set_ylabel('MOCK net I (A)')
    axes[1].plot(t,[e['observer']['estimate']['soc'] for e in events if e['accepted']]);axes[1].set_ylabel('Counted SOC')
    tr=[r['received_qpc_s']-samples[0]['time_s'] for r in valid]
    axes[2].plot(tr,[r['sop_max_discharge_W'] for r in valid]);axes[2].set_ylabel('Estimated SOP (W)')
    tp=[r['received_qpc_s']-samples[0]['time_s'] for r in propulsion]
    axes[3].plot(tp,[r['vehicle_limit_requested_fraction'] for r in propulsion],label='Python request')
    axes[3].plot(tp,[r['vehicle_limit_applied_fraction'] for r in propulsion],label='Native applied');axes[3].legend()
    axes[3].set_ylabel('Availability');axes[3].set_xlabel('Host elapsed seconds')
    for ax in axes:ax.grid();ax.ticklabel_format(axis='y',style='plain',useOffset=False)
    fig.suptitle('MOCK branch readbacks → Coulomb Counting → Rint → TORCS; unvalidated assumptions')
    fig.tight_layout();fig.savefig(folder/'live_cell_state.png');plt.close(fig)
    return dict(passed=True,samples=len(samples),telemetry_samples=len(rows),initial_soc=initial,final_soc=final,
        independent_integrated_charge_Ah=expected,matched_native_acks=len(matched),
        ocv_range_V=[min(r['sop_ocv_candidate_V'] for r in valid),max(r['sop_ocv_candidate_V'] for r in valid)],
        sop_range_W=[min(r['sop_max_discharge_W'] for r in valid),max(r['sop_max_discharge_W'] for r in valid)],
        nonzero_fraction_range=[min(r['vehicle_limit_applied_fraction'] for r in propulsion),max(r['vehicle_limit_applied_fraction'] for r in propulsion)],
        native_zero_shutdown=report['shutdown_zero_verified'],mock_shutdown=report['instruments']['final']['shutdown_verified'])


def measurement_loss(folder):
    folder.mkdir()
    args=parse_args(['--policy','rint-live-mock','--sop-config',str(CONFIG)])
    stream=MockCellStream(args.observer,folder/'cell_measurements.jsonl',voltage_V=args.acquisition['voltage_V'],
        temperature_C=25.,max_skew_s=args.acquisition['max_readback_skew_s'])
    publish=True
    service=MockInstrumentService(folder/'mock_instruments',measurement_sink=lambda s:stream(s) if publish else None)
    args.policy.on_fault=lambda:service.request('emergency_stop')
    feedback=PowerFeedback(args.policy)
    receiver=LiveReceiver(0,folder/'telemetry',power_feedback=feedback,demand_sink=service.demands)
    args.policy.configure(receiver.processor.cell,receiver.processor.profile)
    profile=profile_for('ai');child=None;flags=set();zero=False
    env=dict(os.environ,APS380_MOCK_POWER_LIMIT='1',APS380_LIVE_PORT=str(receiver.port),
        APS380_LIVE_REALTIME='1',APS380_TORCS_PROFILE=str(profile),APS380_AI_LOG=str(folder/'driver.csv'))
    receiver.start();service.start(arm=True)
    try:
        with (folder/'torcs.log').open('w') as log:
            child=subprocess.Popen([str(RUNTIME/'wtorcs.exe'),'-r',str(profile/'race.xml')],cwd=RUNTIME,env=env,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.perf_counter()+15
            while time.perf_counter()<deadline:
                r=feedback.latest
                if r.get('cell_observer_state')=='VALID':flags.add('live_state')
                if r.get('time_s',0)>=3 and 'live_state' in flags:
                    publish=False;flags.add('measurement_loss_injected')
                if r.get('cell_observer_state')=='FAULT':flags.add('observer_fault')
                if r.get('vehicle_limit_state')=='FAULT_STALE' and r.get('vehicle_limit_applied_fraction')==0:
                    flags.add('native_zero_latched')
                if service.latest['state']=='FAULT' and service.latest['shutdown_verified']:
                    flags.add('instruments_off_isolation_open')
                if {'native_zero_latched','instruments_off_isolation_open'}<=flags:break
                if receiver.failed or child.poll() is not None:raise RuntimeError('Mock loss trial failed')
                time.sleep(.01)
            assert len(flags)==5,flags
            feedback.request_stop();zero=feedback.stop_verified.wait(1.)
    finally:
        stream.close();instrument=service.close();receiver.begin_shutdown()
        if child and child.poll() is None:child.terminate();child.wait(timeout=10)
        timing=receiver.close()
    assert zero and not timing['receiver_error'] and timing['statistics']['invalid']==timing['statistics']['missing']==0
    report=dict(mock_only=True,fault_response_passed=True,normal_operation_passed=False,
        checks=sorted(flags),shutdown_zero_verified=zero,observer=args.observer.snapshot(),
        instruments=instrument,telemetry=timing)
    (folder/'trial.json').write_text(json.dumps(report,indent=2)+'\n')
    return dict(fault_response_passed=True,checks=sorted(flags),shutdown_zero_verified=zero)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--comprehensive',action='store_true',help='Add matched human-input driving, four fault/recovery cases and real Tk dashboard regression')
    args=p.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.local/matplotlib'))
    sources=[Path(__file__),CONFIG,ROOT/'scripts/run_vehicle_power_limit.py']
    sources += [ROOT/'aps380_torcs_starter'/name for name in
        ('live_cell_state.py','cell_soc.py','cell_sop.py','vehicle_power_limit.py','instrument_control.py','mock_instruments.py',
         'cell_scaling.py','prototype_current_config.py','profiles/keyboard_driving.json')]
    sources += [RUNTIME/'modules/simu/simuv2.dll',ROOT/'.local/keyboard-tests/aps380_keyboard_fixture.dll',
        ROOT/'external/torcs-1.3.10/src/drivers/human/human.cpp']
    (output/'manifest.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},indent=2)+'\n')
    protected=[ROOT/'bench/bk8500/instrument.py',ROOT/'aps380_torcs_starter/profiles/keyboard_driving.json',
        ROOT/'aps380_torcs_starter/prototype_current_config.py',ROOT/'aps380_torcs_starter/cell_soc.py']
    from validate_keyboard import fingerprint,G29_PROFILE
    roots=[G29_PROFILE,Path(os.environ['LOCALAPPDATA'])/'torcs']
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    profiles={str(p):fingerprint(p) for p in roots}
    command=[sys.executable,'-B',str(ROOT/'scripts/run_vehicle_power_limit.py'),'--policy','rint-live-mock',
        '--sop-config',str(CONFIG),'--mode','ai','--duration','20','--skip-build','--mock-arm','--no-ui','--no-console',
        '--output',str(output/'normal')]
    with (output/'normal-console.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
    result=dict(mock_only=True,normal=assess_normal(output/'normal'),measurement_loss=measurement_loss(output/'measurement-loss'))
    if args.comprehensive:
        result['matched_driving']=matched_driving(output)
        result['fault_recovery_matrix']=fault_recovery_matrix(output/'fault-recovery')
        result['dashboards']=dashboard_regressions(output)
    result['protected_files_and_profiles_unchanged']=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items()) and all(fingerprint(p)==h for p,h in profiles.items())
    assert result['protected_files_and_profiles_unchanged']
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
