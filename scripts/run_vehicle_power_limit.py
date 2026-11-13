"""Opt-in MOCK vehicle availability demo. No PSU/eLoad/serial access."""
import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from configure_tesla import ROOT,RUNTIME,TORCS
from run_tesla_ai import prepare_profile,build
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from torcs_live import LiveReceiver
from vehicle_power_limit import DemoPolicy,PowerFeedback


def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=('ai','keyboard','g29'),default='ai')
    p.add_argument('--policy',choices=('demo','rint','rint-live-mock'),default='demo')
    p.add_argument('--mock-arm',action='store_true',help='Explicitly arm in-memory prototype instruments, live-mock policy only')
    p.add_argument('--sop-config',type=Path,help='Explicit unvalidated mock Rint parameters/state; no resistance default')
    p.add_argument('--duration',type=float,default=30.)
    p.add_argument('--demo-soc',type=float,help='Simulated policy SOC override (0..1), separate from native pack SOC')
    p.add_argument('--fraction',type=float,help='Fixed mock test fraction (0..1); overrides the SOC policy')
    p.add_argument('--soc-low',type=float,default=.1)
    p.add_argument('--soc-full',type=float,default=.3)
    p.add_argument('--minimum-fraction',type=float,default=.2)
    p.add_argument('--no-ui',action='store_true')
    p.add_argument('--no-console',action='store_true')
    p.add_argument('--skip-build',action='store_true')
    p.add_argument('--output',type=Path)
    args=p.parse_args(argv)
    if not 0<args.duration<=3600:p.error('Duration must be 0..3600 s')
    try:
        if args.policy in ('rint','rint-live-mock'):
            live = args.policy=='rint-live-mock'
            if args.sop_config is None:p.error('--policy rint requires --sop-config')
            if args.demo_soc is not None or args.fraction is not None:p.error('Rint uses its explicit mock cell state; demo/fixed overrides are separate modes')
            from cell_sop import RintParameters,RintPolicy
            config=json.loads(args.sop_config.read_text(encoding='utf-8'))
            if config.get('purpose')!='unvalidated_mock_assumptions':raise ValueError('Only explicit unvalidated mock SOP configurations are supported')
            parameters=RintParameters(**config['parameters'])
            if live:
                from live_cell_state import LiveCellObserver,LiveRintPolicy
                acquisition=config['live_mock_measurements']
                args.observer=LiveCellObserver(parameters.capacity_Ah,config['mock_state']['soc_fraction'],
                    freshness_s=acquisition['freshness_s'],max_gap_s=acquisition['max_gap_s'])
                args.acquisition=acquisition
                args.policy=LiveRintPolicy(parameters,config['mock_state']['soc_fraction'],
                    config['mock_state']['temperature_C'],args.observer)
            else:
                args.policy=RintPolicy(parameters,config['mock_state']['soc_fraction'],config['mock_state']['temperature_C'])
        else:
            if args.sop_config is not None:p.error('--sop-config requires --policy rint')
            args.policy=DemoPolicy(args.soc_low,args.soc_full,args.minimum_fraction,args.demo_soc,args.fraction)
        if args.mock_arm and not hasattr(args,'observer'):p.error('--mock-arm requires --policy rint-live-mock')
    except (ValueError,OSError,KeyError,TypeError) as exc:p.error(str(exc))
    return args


def profile_for(mode):
    saved=ROOT/'.local/tesla-profile'
    for name in ('drivers/human/human.xml','drivers/human/preferences.xml','config/raceman/practice.xml'):
        if not (saved/name).is_file():raise FileNotFoundError('Prepared profile missing: '+str(saved/name))
    if mode=='g29':return saved
    if mode=='keyboard':
        from configure_keyboard import prepare_keyboard
        return prepare_keyboard()
    profile=ROOT/'.local/vehicle-power-ai-profile'
    prepare_profile(profile,manual_profile=saved)
    return profile


def commands(feedback,quit_event,service=None):
    print('MOCK vehicle feedback: RESET = explicit recovery; QUIT = zero propulsion and save. Ctrl+C stops.',flush=True)
    if service:print('ARM | DISARM | ESTOP | RECOVER control MOCK instruments. RESET CELL explicitly reanchors configured MOCK SOC; then RESET propulsion.',flush=True)
    while not quit_event.is_set():
        try:command=input('POWER MOCK> ').strip().upper()
        except EOFError:quit_event.set();return
        if command=='RESET':feedback.request_reset()
        elif service and command=='RESET CELL':feedback.policy.observer.reset(feedback.policy.observer.initial_soc)
        elif service and command in ('ARM','DISARM','ESTOP','RECOVER'):
            service.request({'ARM':'arm','DISARM':'disarm','ESTOP':'emergency_stop','RECOVER':'recover'}[command])
        elif command in ('QUIT','STOP'):quit_event.set();return
        elif command:print('Commands: RESET | QUIT',flush=True)


def main(argv=None):
    args=parse_args(argv)
    if not args.skip_build:
        build(TORCS/'src/modules/simu/simuv2/simuv2.vcxproj',ROOT/'.local/vehicle-power-build.log')
    output=(args.output or ROOT/'.local/vehicle-power-trials'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')).resolve()
    output.mkdir(parents=True,exist_ok=False)
    os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.local/matplotlib'))
    feedback=PowerFeedback(args.policy)
    service=None;stream=None;instrument_report=None;observer_report=None
    if hasattr(args,'observer'):
        from live_cell_state import MockCellStream
        from instrument_control import MockInstrumentService
        stream=MockCellStream(args.observer,output/'cell_measurements.jsonl',
            voltage_V=args.acquisition['voltage_V'],temperature_C=args.policy.mock_temperature_C,
            max_skew_s=args.acquisition['max_readback_skew_s'])
        service=MockInstrumentService(output/'mock_instruments',measurement_sink=stream)
        args.policy.on_fault=lambda:service.request('emergency_stop')
    receiver=LiveReceiver(0,output/'telemetry',power_feedback=feedback,
        demand_sink=service.demands if service else None)
    if hasattr(args.policy,'configure'):args.policy.configure(receiver.processor.cell,receiver.processor.profile)
    child=None;quit_event=threading.Event();error=None;shutdown=False
    receiver.peer_exit_status=lambda:child.poll() if child else None
    policy_config=args.policy.describe() if hasattr(args.policy,'describe') else asdict(args.policy)
    (output/'config.json').write_text(json.dumps(dict(mock_only=True,policy=policy_config,
        mode=args.mode,native_feedback_expiry_s=.5,protocol='APS380POWER1',
        physical_instruments_accessed=False),indent=2)+'\n')
    sources=[Path(__file__),ROOT/'aps380_torcs_starter/vehicle_power_limit.py',
        ROOT/'aps380_torcs_starter/torcs_live.py',ROOT/'aps380_torcs_starter/live_display.py',
        TORCS/'src/modules/simu/simuv2/aps380_power_limit.h',TORCS/'src/modules/simu/simuv2/aps380_ev.h',
        TORCS/'src/modules/simu/simuv2/aps380_live.h',TORCS/'src/modules/simu/simuv2/simu.cpp',
        RUNTIME/'modules/simu/simuv2.dll']
    if hasattr(args.policy,'describe'):
        sources += [ROOT/'aps380_torcs_starter/cell_sop.py',ROOT/'aps380_torcs_starter/cell_soc.py',
            ROOT/'aps380_torcs_starter/cell_scaling.py',ROOT/'aps380_torcs_starter/profiles/eve_35v_ocv_candidate.json',
            ROOT/'aps380_torcs_starter/profiles/live_scaling_demo.json',ROOT/'aps380_torcs_starter/profiles/tesla_model3_rwd.json']
        (output/'sop_config.json').write_bytes(args.sop_config.read_bytes())
    if stream:
        sources += [ROOT/'aps380_torcs_starter'/name for name in
            ('live_cell_state.py','instrument_control.py','mock_instruments.py','prototype_current_config.py')]
    (output/'manifest.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},indent=2)+'\n')
    try:
        if not receiver.processor.shared_clock:raise RuntimeError('Power feedback requires verified shared monotonic clock')
        profile=profile_for(args.mode)
        env=dict(os.environ,APS380_MOCK_POWER_LIMIT='1',APS380_LIVE_PORT=str(receiver.port),
            APS380_LIVE_REALTIME='1' if args.mode=='ai' else '0',
            APS380_TORCS_PROFILE=str(profile),APS380_AI_LOG=str(output/'driver.csv'))
        receiver.start()
        if service:service.start(arm=args.mock_arm)
        with (output/'torcs.log').open('w') as log:
            cmd=[str(RUNTIME/'wtorcs.exe')]
            if args.mode=='ai':cmd+=['-r',str(profile/'race.xml')]
            child=subprocess.Popen(cmd,cwd=RUNTIME,env=env,stdout=log,stderr=subprocess.STDOUT)
            print('MOCK power limiting enabled. Records: '+str(output),flush=True)
            if not args.no_console:threading.Thread(target=commands,args=(feedback,quit_event,service),daemon=True).start()
            started=time.perf_counter();notice=0.
            def finished():
                return (quit_event.is_set() or receiver.failed or child.poll() is not None or
                    feedback.fatal.is_set() or
                    time.perf_counter()-started>=args.duration)
            if args.no_ui:
                while not finished():
                    if time.perf_counter()>=notice:
                        r=feedback.latest
                        print({k:r.get(k) for k in ('vehicle_limit_state','vehicle_limit_requested_fraction','vehicle_limit_applied_fraction','vehicle_limit_error')},flush=True)
                        notice=time.perf_counter()+5
                    time.sleep(.02)
            else:
                from live_display import LiveDisplay
                LiveDisplay(receiver,finished,args.duration+1,mock_service=service).run()
    except KeyboardInterrupt:pass
    except Exception as exc:error=repr(exc)
    finally:
        if stream:
            # Freeze acquisition before intentional OFF/retained shutdown records.
            # No final retained readback may be integrated as a fresh measurement.
            stream.close()
            observer_report=args.observer.snapshot()
        if service:
            try:instrument_report=service.close()
            except Exception as exc:
                error='Mock shutdown could not be verified: '+repr(exc)
                instrument_report=dict(acceptance=dict(passed=False),shutdown_error=repr(exc))
        # Verify a fresh native zero acknowledgement before ending healthy telemetry.
        feedback.request_stop()
        if child and child.poll() is None:shutdown=feedback.stop_verified.wait(1.)
        receiver.begin_shutdown()
        if child and child.poll() is None:child.terminate();child.wait(timeout=10)
        timing=receiver.close()
    rows=[e['row'] for e in (json.loads(line) for line in
        (output/'telemetry/received.jsonl').read_text().splitlines()) if e['kind']=='sample']
    faults=sorted({r.get('vehicle_limit_state') for r in rows if r.get('vehicle_limit_state','').startswith('FAULT')})
    passed=bool(rows and not error and not receiver.failed and not feedback.error and not feedback.fatal.is_set() and
        shutdown and not faults and not timing['stale_intervals'] and
        timing['statistics']['invalid']==timing['statistics']['missing']==0 and
        any(r.get('vehicle_limit_state')=='ACTIVE' for r in rows))
    if service:
        passed=bool(passed and instrument_report['acceptance']['passed'] and
            observer_report['state']=='VALID' and observer_report['accepted']>1)
    report=dict(mock_only=True,passed=passed,runtime_error=error,feedback_error=feedback.error,
        shutdown_zero_verified=shutdown,fault_states=faults,telemetry=timing,
        shutdown_request_sequence=feedback.stop_sequence,
        shutdown_native_ack_sequence=feedback.latest.get('vehicle_limit_ack_sequence'),
        hardware_accessed=False,full_course='NOT ASSESSED')
    if service:
        report.update(cell_observer=observer_report,instruments=instrument_report)
    (output/'trial.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='telemetry'},indent=2),flush=True)
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
