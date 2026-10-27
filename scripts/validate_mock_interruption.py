"""Fault-injection trial: stop this script's headless TORCS process, keep the
receiver/controller alive, and verify telemetry expiry and latched mock shutdown.
Normal-operation acceptance MUST fail; fault-response acceptance is separate.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from configure_tesla import ROOT, RUNTIME, PROFILE
from run_tesla_ai import prepare_profile
from run_tesla_live import audit_capture
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from instrument_control import MockInstrumentService
from torcs_live import LiveReceiver
from trial_acceptance import trial_acceptance


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--healthy-seconds',type=float,default=12.)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    if not 10 <= args.healthy_seconds <= 60:parser.error('healthy-seconds must be 10..60')
    output=args.output_dir or ROOT/'.local/mock-interruption'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    local=ROOT/'.local/tesla-live-ai-profile'
    prepare_profile(local)
    receiver=LiveReceiver(0,output)
    service=MockInstrumentService(output/'mock_instruments')
    implementation=[Path(__file__),ROOT/'aps380_torcs_starter/torcs_live.py',
                    ROOT/'aps380_torcs_starter/instrument_control.py',
                    ROOT/'aps380_torcs_starter/mock_instruments.py',
                    ROOT/'aps380_torcs_starter/trial_acceptance.py',
                    RUNTIME/'modules/simu/simuv2.dll']
    (output/'implementation_manifest.json').write_text(json.dumps(
        {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in implementation},indent=2)+'\n')
    receiver.demand_sink=service.demands
    before=set((RUNTIME/'telemetry').glob('aps380_ev_*.csv'))
    log=(output/'torcs.log').open('w')
    env=dict(os.environ,APS380_LIVE_PORT=str(receiver.port),APS380_LIVE_REALTIME='1',
             APS380_TORCS_PROFILE=str(local),APS380_AI_LOG=str(output.resolve()/'driver.csv'),
             MPLCONFIGDIR=str(ROOT/'.local/matplotlib'))
    os.environ['MPLCONFIGDIR']=env['MPLCONFIGDIR']
    process=None
    receiver.start();service.start(arm=True)
    try:
        process=subprocess.Popen([str(RUNTIME/'wtorcs.exe'),'-r',str(local/'race.xml')],
                                 cwd=RUNTIME,env=env,stdout=log,stderr=subprocess.STDOUT)
        deadline=time.perf_counter()+args.healthy_seconds
        while time.perf_counter()<deadline and process.poll() is None:
            time.sleep(.02)
        before_interrupt=service.latest
        intentional=process.poll() is None and before_interrupt['state']=='RUNNING'
        interrupted_at=time.perf_counter()
        if process.poll() is None:
            process.terminate();process.wait(timeout=10)
        # Deliberately do NOT close the controller with the process. Let expiry
        # supervision act, and retain the receiver's stale-state evidence.
        time.sleep(service.config.command_expiry_s+.5)
    finally:
        if process is not None and process.poll() is None:
            process.terminate();process.wait(timeout=10)
        log.close()
        try:instruments=service.close()
        finally:timing=receiver.close()
    rows=[e['row'] for e in map(json.loads,(output/'received.jsonl').read_text().splitlines()) if e['kind']=='sample']
    fresh=set((RUNTIME/'telemetry').glob('aps380_ev_*.csv'))-before
    capture=audit_capture(output,rows,fresh.pop()) if len(fresh)==1 else dict(all_received_samples_match_csv=False)
    process_result=dict(launched=True,exit_code=process.returncode,terminated_by_launcher=False,
                        stop_reason='deliberate_telemetry_interruption')
    telemetry_checks=dict(received_at_least_10_seconds=timing['sim_duration_s']>=10,
        no_invalid_packets=timing['statistics']['invalid']==0,
        no_packet_loss=timing['statistics']['missing']==0,
        no_stale_intervals=not any(s.startswith('STALE') for s in timing['state_transitions']),
        csv_agreement=capture['all_received_samples_match_csv'])
    normal=trial_acceptance(telemetry_checks,process_result,'smoke',instruments['acceptance'])
    fault=instruments['final']
    fault_checks=dict(running_before_interruption=intentional,
        expiry_fault_latched=fault['state']=='FAULT' and fault['fault'] in ('TELEMETRY_EXPIRED','STALE_TELEMETRY'),
        outputs_disabled=fault['isolation']['outputs_disabled'],isolation_open=fault['isolation']['is_open'],
        shutdown_verified=fault['shutdown_verified'],normal_operation_correctly_failed=not normal['passed'],
        no_worker_error=instruments['worker_error'] is None,csv_agreement=capture['all_received_samples_match_csv'])
    result=dict(scope='mock-only deliberate TORCS telemetry interruption',mock_only=True,
        interrupted_at_host_s=interrupted_at,normal_operation=normal,
        fault_response=dict(passed=all(fault_checks.values()),checks=fault_checks),
        timing=timing,instruments=instruments,capture_audit=capture)
    (output/'trial.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(output=str(output),fault_response=result['fault_response'],normal_passed=normal['passed']),indent=2))
    if not result['fault_response']['passed']:raise SystemExit(1)


if __name__=='__main__':main()
