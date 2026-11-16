"""Actual native TORCS, existing scripted human inputs, Battery Bias mocks only."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from battery_bias import BatteryBiasService
from battery_bias_feedback import BiasRintPolicy
from vehicle_power_limit import PowerFeedback
from torcs_live import LiveReceiver
from cell_sop import RintEstimator,RintParameters
import validate_keyboard as keyboard


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    output=p.parse_args().output.resolve();output.mkdir(parents=True,exist_ok=False)
    config=json.loads((ROOT/'aps380_torcs_starter/profiles/rint_sop_live_mock_example.json').read_text())
    results={};traces={};inputs={}
    target=keyboard.RUNTIME/'drivers/aps380_keyboard_fixture/aps380_keyboard_fixture.dll'
    if target.exists():raise RuntimeError('Fixture already installed; stop rather than overwrite')
    try:
        for name,cap in (('full',1.),('reduced',.5),('low',.2)):
            folder=output/name;folder.mkdir();box={};model=copy.deepcopy(config)
            model['parameters']['maximum_discharge_A']=cap
            def service_factory(path):
                service=BatteryBiasService(path,sop_config=model);service.psu.cv_available_A=.05
                feedback=PowerFeedback(BiasRintPolicy(service));box.update(service=service,feedback=feedback)
                close=service.close
                def finish():
                    feedback.request_stop();box['zero']=feedback.stop_verified.wait(1.)
                    return close()
                service.close=finish
                return service
            def receiver_factory(*a,**kw):
                feedback=box['feedback'];receiver=LiveReceiver(*a,**kw,power_feedback=feedback)
                feedback.policy.configure(receiver.processor.cell,receiver.processor.profile)
                return receiver
            with patch.object(keyboard,'MockInstrumentService',side_effect=service_factory),patch.object(keyboard,'LiveReceiver',side_effect=receiver_factory),patch.dict(os.environ,{'APS380_MOCK_POWER_LIMIT':'1'}):
                keyboard.trial(folder)
            rows=[e['row'] for e in map(json.loads,(folder/'telemetry/received.jsonl').read_text().splitlines()) if e['kind']=='sample']
            window=[r for r in rows if 7<=r['time_s']<=8]
            inputs[name]={r['time_s']:(r['throttle'],r['brake']) for r in window}
            sent={r['vehicle_limit_sent_sequence']:r['vehicle_limit_requested_fraction'] for r in rows if 'vehicle_limit_sent_sequence' in r}
            ack=[r for r in rows if r.get('vehicle_limit_state')=='ACTIVE' and r['vehicle_limit_ack_sequence'] in sent]
            assert ack and all(abs(r['vehicle_limit_applied_fraction']-sent[r['vehicle_limit_ack_sequence']])<1e-9 for r in ack)
            assert box['zero'] and not box['feedback'].error
            valid=[r for r in window if r.get('cell_observer_state')=='VALID']
            assert valid and all(r['cell_measurement_source']=='battery_bias_mock_sensor' for r in valid)
            events=[e for e in map(json.loads,(folder/'instruments/instruments.jsonl').read_text().splitlines())
                    if e['state'] in ('READY','RUNNING') and e.get('cell_model_state',{}).get('sop_model_valid')]
            counted={i:e['cell_model_state']['sop_cell_soc_fraction'] for i,e in enumerate(events)}
            previous=None;integrated=model['mock_state']['soc_fraction']
            for e in events:
                f=e['cell_sensor_frame'];current=0. if f['cell_isolated'] else f['cell_current_A']
                if previous:
                    integrated+=(previous[1]+current)/2*(f['acquired_s']-previous[0])/(3600*model['parameters']['capacity_Ah'])
                assert abs(integrated-e['cell_model_state']['sop_cell_soc_fraction'])<1e-12
                previous=(f['acquired_s'],current)
            estimator=RintEstimator(RintParameters(**model['parameters']))
            for r in rows:
                if r.get('cell_observer_state')=='VALID':
                    assert abs(r['sop_cell_soc_fraction']-counted[r['cell_measurement_sequence']])<1e-12
                    assert abs(r['sop_max_discharge_W']-estimator.estimate(r['sop_cell_soc_fraction'],25.)['sop_max_discharge_W'])<1e-12
            results[name]=dict(cap_A=cap,matched_acks=len(ack),speed_at_8_mps=window[-1]['speed_mps'],
                peak_motor_window_W=max(r['motor_power_W'] for r in window),
                applied_fraction=valid[-1]['vehicle_limit_applied_fraction'],
                initial_soc=config['mock_state']['soc_fraction'],final_soc=valid[-1]['sop_cell_soc_fraction'],
                native_zero_shutdown=True,mock_shutdown=box['service'].coordinator.shutdown_verified)
            results[name]['measured_soc_sop_chain_verified']=True
            traces[name]=rows
        common=set.intersection(*(set(x) for x in inputs.values()))
        assert len(common)>=40 and all(inputs[n][t]==inputs['full'][t] for n in inputs for t in common)
        for metric in ('speed_at_8_mps','peak_motor_window_W'):
            assert results['full'][metric]>results['reduced'][metric]>results['low'][metric],results
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,axes=plt.subplots(4,1,sharex=True,figsize=(11,10),layout='constrained')
        for name,rows in traces.items():
            for ax,key in zip(axes,('speed_mps','motor_power_W','sop_cell_soc_fraction','vehicle_limit_applied_fraction')):
                ax.plot([r['time_s'] for r in rows],[r.get(key) for r in rows],label=name)
        for ax,label in zip(axes,('Speed m/s','Native motor W','Cell SOC [MOCK]','Native applied fraction')):
            ax.set_ylabel(label);ax.legend();ax.grid(alpha=.3)
        axes[-1].set_xlabel('Simulation time s; identical scripted keys; compare 7..8 s')
        fig.savefig(output/'comparison.png',dpi=140);plt.close(fig)
        summary=dict(passed=True,mock_only=True,matched_samples=len(common),cases=results,
            assumptions='Imposed mock source contribution 0.05 A; original limits and 0.02 A/s slew unchanged')
        (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
    finally:
        if target.exists():
            import hashlib
            expected=ROOT/'.local/keyboard-tests/aps380_keyboard_fixture.dll'
            assert hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256(expected.read_bytes()).digest()
            target.unlink()


if __name__=='__main__':main()
