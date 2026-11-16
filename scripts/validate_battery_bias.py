"""Reproducible accelerated-clock MOCK experiment; never opens hardware transports."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
sys.path.insert(0,str(ROOT/'bench/bk8500'))
from battery_bias import BatteryBiasCoordinator,BiasCellStream
from instrument_control import ControlConfig,Demand,State
from mock_instruments import MockPSU,MockBK8500,MockIsolation
from battery_bias_runner import artifacts


class Clock:
    def __init__(self):self.now=10.
    def __call__(self):return self.now
    def sleep(self,s):self.now+=s


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--live-dashboard',action='store_true',help='Actual TORCS/Tk with mocks, real elapsed time')
    p.add_argument('--propulsion-feedback',action='store_true',help='Validate opt-in bias propulsion display')
    a=p.parse_args(argv)
    if a.live_dashboard:return live_dashboard(a.output,a.propulsion_feedback)
    a.output.mkdir(parents=True,exist_ok=False)
    clock=Clock();opts=dict(clock=clock,sleep=clock.sleep,response_delay_s=.02)
    psu=MockPSU(**opts);psu.cv_available_A=.2
    load=MockBK8500(**opts);isolation=MockIsolation(psu,load)
    config=ControlConfig(slew_rate_A_per_s=.02,ready_timeout_s=90.)
    c=BatteryBiasCoordinator(psu,load,isolation,config,clock)
    model=json.loads((ROOT/'aps380_torcs_starter/profiles/rint_sop_live_mock_example.json').read_text())
    stream=BiasCellStream(model,clock);events=[];c.arm()
    for i in range(2400):
        clock.sleep(.1)
        t=i*.1
        # Identical deterministic trajectory, explicit mock source variation.
        target=0. if t<20 else -.1 if t<90 else .08 if t<170 else 0.
        psu.cv_available_A=.2+.005*math.sin(t/20)
        c.step(Demand(target,clock(),'mock-experiment',i,requested_current_A=target,sim_time_s=t))
        s=c.snapshot();s['host_s']=clock();s['cell_model_state']=stream.update(s)
        events.append(s)
        assert c.state!=State.FAULT,(t,c.fault_reason)
    # Deliberate telemetry loss after healthy operation: expected FAULT, isolated.
    c.step(None,'DELIBERATE_TELEMETRY_LOSS')
    fault=c.snapshot();assert c.state==State.FAULT and c.shutdown_verified
    assert fault['bias_safety']['cell_isolated'] and fault['bias_safety']['source_isolated']
    (a.output/'instruments.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events+[fault]))
    stats=artifacts(events,a.output)
    assert stats['max_kcl_error_A']<1e-10
    running=[e for e in events if e['state']=='RUNNING']
    assert any(e['cell_sensor_frame']['cell_current_A']<-.09 for e in running)
    assert any(e['cell_sensor_frame']['cell_current_A']>.07 for e in running)
    states=[e['cell_model_state'] for e in running if e['cell_model_state']['sop_model_valid']]
    assert min(s['sop_cell_soc_fraction'] for s in states)<model['mock_state']['soc_fraction']
    result=dict(passed=True,mock_only=True,clock='accelerated synthetic 0.1 s steps; not wall-time evidence',
        independent_sensor='separate channels over simplified mock plant truth; no physical sensor',
        config=asdict(config),qualification=asdict(c.qualification),model_assumptions=model,
        statistics=stats,soc_range=[min(s['sop_cell_soc_fraction'] for s in states),max(s['sop_cell_soc_fraction'] for s in states)],
        sop_range_W=[min(s['sop_max_discharge_W'] for s in states),max(s['sop_max_discharge_W'] for s in states)],
        expected_fault=fault,physical_operation_enabled=False,propulsion_feedback_connected=False)
    (a.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    (a.output/'report.md').write_text('# Battery Bias mock validation\n\nPASS. No physical commands.\n\n'
        'Four minutes of accelerated synthetic time: isolated balance, discharge, charge, neutral, varying source, deliberate telemetry-loss fault. '
        'Current channels derive from simplified mock plant truth, with separate sensor offset/failure injection; not an electrical battery model. '
        'SOC uses independent signed cell channel, not requested current; synthetic V/T and unvalidated model assumptions. '
        'Rint SOP updates, but this mode does not connect SOP to native propulsion feedback.\n\n'
        f'Running statistics: `{stats}`\n\nFault shutdown verified: `{fault["shutdown_verified"]}`; cell and source isolated. '
        'See bias_tracking.png, bias_model.png, CSV and full JSONL. Native real-time evidence is separate.\n')
    print(json.dumps({k:result[k] for k in ('passed','statistics','soc_range','sop_range_W')},indent=2))


def live_dashboard(output,propulsion_feedback=False):
    import time
    from unittest.mock import patch
    import live_display
    import battery_bias_runner
    observations=[]
    class RecordingDisplay(live_display.LiveDisplay):
        def __init__(self,*a,**kw):
            super().__init__(*a,**kw);self.root.withdraw();self.started=time.perf_counter()
        def refresh(self):
            elapsed=time.perf_counter()-self.started
            names=list(self.tabs);self.notebook.select(self.tabs[names[int(elapsed/4)%len(names)]])
            super().refresh()
            observations.append(dict(state=self.mock_service.latest['state'],
                tab=self.notebook.tab(self.notebook.select(),'text'),redraw_ms=self.render_times[-1],
                labels={k:v.cget('text') for k,v in self.readouts.items()}))
    with patch.object(live_display,'LiveDisplay',RecordingDisplay):
        code=battery_bias_runner.main(['--device','mock','--torcs','ai','--telemetry-port','0','--duration','35',
            '--auto-arm-mock','--no-console','--dashboard','--output',str(output)]+
            (['--propulsion-feedback'] if propulsion_feedback else []))
    output=Path(output)
    (output/'dashboard_observations.json').write_text(json.dumps(observations,indent=2)+'\n')
    assert code==0
    assert any(o['state']=='RUNNING' for o in observations)
    assert any('MOCK independent sensor model' in o['labels']['cell_current'] for o in observations)
    assert any('ESTIMATED / MOCK counted' in o['labels']['cell_soc'] for o in observations)
    if propulsion_feedback:assert any('ACTIVE' in o['labels']['propulsion'] for o in observations)
    else:assert all('NOT CONNECTED' in o['labels']['propulsion'] for o in observations)
    p95=sorted(o['redraw_ms'] for o in observations)[int(.95*(len(observations)-1))]
    assert p95<100,p95
    summary=dict(passed=True,mock_only=True,refreshes=len(observations),redraw_p95_ms=p95,
        all_tabs_visited=sorted({o['tab'] for o in observations}),physical_instruments_accessed=False)
    (output/'dashboard_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(summary)


if __name__=='__main__':main()
