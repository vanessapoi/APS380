"""Short mock-only experiment. Does not launch TORCS or connect to instruments."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from cell_scaling import CellParameters, scale_to_cell
from instrument_control import ControlConfig, MockInstrumentService


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm-mock',action='store_true',help='Required explicit mock arming')
    parser.add_argument('--charge-limit',type=float,default=.5)
    parser.add_argument('--control-hz',type=float,default=10.)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    if not args.arm_mock:parser.error('Use --arm-mock to run this in-memory demonstration')
    try:
        config=ControlConfig(discharge_limit_A=1.,charge_limit_A=args.charge_limit,control_hz=args.control_hz)
    except ValueError as error:parser.error(str(error))
    output=args.output_dir or ROOT/'.local/mock-instruments'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    service=MockInstrumentService(output,config)
    cell=CellParameters(nominal_voltage_V=3.65,capacity_Ah=3.5,equivalent_pack_energy_Wh=50000,
                        discharge_limit_A=1.,charge_limit_A=args.charge_limit,experiment_scale=.06)
    factor=cell.capacity_Ah/cell.equivalent_pack_energy_Wh*cell.experiment_scale
    profile=[('discharge',1.4),('neutral',0.),('charge',-min(.3,args.charge_limit))]
    source=(output/'demand.jsonl').open('w',encoding='utf-8')
    service.start(arm=True)
    sequence=0
    try:
        for label,current in profile:
            deadline=time.perf_counter()+1.2
            while time.perf_counter()<deadline:
                now=time.perf_counter()
                row=dict(scale_to_cell(current/factor,cell),received_qpc_s=now,
                         session_id='mock-demo',sequence=sequence,target_available=True)
                service.demands.publish(row)
                source.write(json.dumps(dict(phase=label,source='synthetic_pack_power',**row))+'\n')
                sequence+=1
                time.sleep(.02)
        # Stop producing samples; verify expiry rather than continuing old demand.
        time.sleep(config.command_expiry_s+2/config.control_hz)
    finally:
        source.close()
        report=service.close()
    print(json.dumps(dict(output=str(output),**report),indent=2))
    final=report['final']
    if (report['worker_error'] or final['state']!='FAULT' or
            final['fault']!='TELEMETRY_EXPIRED' or not final['shutdown_verified']):
        raise SystemExit('Mock demonstration failed; inspect instruments.jsonl')


if __name__=='__main__':main()
