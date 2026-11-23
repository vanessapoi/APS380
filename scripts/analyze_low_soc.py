"""Offline Rint SOC sweep using existing live scaling; no hardware or sockets."""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from cell_sop import RintEstimator,RintParameters,vehicle_mapping
from cell_scaling import CellParameters


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=ROOT/'aps380_torcs_starter/profiles/rint_sop_live_mock_example.json')
    parser.add_argument('--session',type=Path,help='Optional completed Battery Bias mock run to plot separately')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    config=json.loads(args.config.read_text(encoding='utf-8'))
    if config.get('purpose')!='unvalidated_mock_assumptions':raise ValueError('Explicit mock model required')
    profile=json.loads((ROOT/'aps380_torcs_starter/profiles/tesla_model3_rwd.json').read_text())
    scaling=json.loads((ROOT/'aps380_torcs_starter/profiles/live_scaling_demo.json').read_text())
    cell=CellParameters(**scaling['cell'],equivalent_pack_energy_Wh=profile['unvalidated']['capacity_Wh'])
    estimator=RintEstimator(RintParameters(**config['parameters']))
    native=dict(throttle=1.,brake=0.,speed_mps=20.,soc=.8,motor_power_W=0.,motor_radps=100.)
    def calculate(soc):
        s=estimator.estimate(soc,config['mock_state']['temperature_C'])
        f=vehicle_mapping(s['sop_max_discharge_W'],cell,profile,native)['sop_vehicle_fraction']
        constraints={'current':estimator.p.maximum_discharge_A,'voltage':s['sop_voltage_constraint_A'],
            'SOC reserve / horizon budget':s['sop_soc_budget_constraint_A']}
        return dict(SOC_percent=soc*100,OCV_V=s['sop_ocv_candidate_V'],allowable_discharge_A=s['sop_max_discharge_A'],
            SOP_W=s['sop_max_discharge_W'],propulsion_percent=f*100,
            active_constraint=min(constraints,key=constraints.get),voltage_limit_A=s['sop_voltage_constraint_A'],
            soc_budget_A=s['sop_soc_budget_constraint_A'])
    rows=[calculate(z) for z in (.8,.4,.2,.1204,.1202,.12001,.12,.1,.05,0.)]
    with (args.output/'comparison.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    result=dict(mock_only=True,physical_validation=False,model=config,rows=rows,
        conclusions='Voltage constraint is inactive at the current 0.5 A cap. The SOC margin plus reserve gives a 12% cutoff; auxiliary demand can remove propulsion slightly earlier.')
    (args.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    sweep=[calculate(i/10000) for i in range(10001)]
    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    for ax,field in zip(axes.flat,('OCV_V','allowable_discharge_A','SOP_W','propulsion_percent')):
        ax.plot([x['SOC_percent'] for x in sweep],[x[field] for x in sweep]);ax.set_ylabel(field);ax.set_xlabel('Cell SOC % [MOCK]');ax.grid(alpha=.3)
    fig.suptitle('Existing unvalidated Rint model; unchanged 0.5 A assumptions; no physical battery')
    fig.savefig(args.output/'soc_sweep.png',dpi=140);plt.close(fig)
    if args.session:
        trial=json.loads((args.session/'trial.json').read_text())
        if trial.get('mock_only') is not True:raise ValueError('Only a completed mock session is supported')
        events=map(json.loads,(args.session/'telemetry/received.jsonl').read_text().splitlines())
        valid=[e['row'] for e in events if e['kind']=='sample' and
            e['row'].get('bias_controller_state')=='RUNNING' and e['row'].get('cell_observer_state')=='VALID']
        if not valid:raise ValueError('No valid RUNNING cell observations')
        fields=('sop_cell_soc_fraction','sop_max_discharge_W','vehicle_limit_applied_fraction','motor_power_W')
        fig,axes=plt.subplots(4,1,figsize=(11,10),sharex=True,layout='constrained')
        for ax,field in zip(axes,fields):
            ax.plot([r['time_s'] for r in valid],[r[field] for r in valid]);ax.set_ylabel(field);ax.grid(alpha=.3)
            ax.ticklabel_format(axis='y',style='plain',useOffset=False)
        axes[-1].set_xlabel('Native TORCS time [s]')
        fig.suptitle('MOCK measured-current SOC evolution; no accelerated depletion or physical battery')
        fig.savefig(args.output/'live_evolution.png',dpi=140);plt.close(fig)
        evolution=dict(mock_only=True,trial_passed=trial['passed'],native_zero_shutdown=trial['native_zero_shutdown_verified'],
            first={field:valid[0][field] for field in fields},last={field:valid[-1][field] for field in fields},
            valid_samples=len(valid))
        active=[r for r in valid if r['vehicle_limit_applied_fraction']>0]
        evolution['boundary_note']='First/last native fractions may be zero during startup/intentional shutdown.'
        if active:
            evolution['positive_propulsion_window']=dict(first_time_s=active[0]['time_s'],last_time_s=active[-1]['time_s'],
                first_applied_fraction=active[0]['vehicle_limit_applied_fraction'],
                last_applied_fraction=active[-1]['vehicle_limit_applied_fraction'])
        (args.output/'live_evolution.json').write_text(json.dumps(evolution,indent=2)+'\n')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':main()
