"""Launch native real-time AI/G29 trials or listen; save timing and CSV audits."""
import argparse
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from configure_tesla import ROOT,TORCS,RUNTIME,PROFILE,configure
from run_tesla_ai import build,prepare_profile,validate_protocol
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from torcs_live import LiveReceiver
from run_ev import read_ev,verify_configuration
from trial_acceptance import trial_acceptance


def audit_capture(output, receiver_rows, source):
    shutil.copy2(source,output/'drive.csv')
    shutil.copy2(source.with_suffix('.xml'),output/'drive.xml')
    profile,raw=read_ev(output/'drive.csv',output/'vehicle_profile.json')
    verify_configuration(output/'drive.xml',profile)
    lines=set(source.read_text().splitlines()[1:])
    matched=sum(row['native_csv'].strip() in lines for row in receiver_rows)
    return {'native_samples':len(raw),'received_samples':len(receiver_rows),
            'matching_samples':matched,'all_received_samples_match_csv':matched==len(receiver_rows) and matched>0,
            'native_csv_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('ai','g29','listen'),default='ai')
    parser.add_argument('--duration',type=float,default=500)
    parser.add_argument('--port',type=int,default=0,help='0 selects a free loopback port')
    parser.add_argument('--config',type=Path,default=ROOT/'aps380_torcs_starter/profiles/live_scaling_demo.json')
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--no-ui','--no-desktop',dest='no_ui',action='store_true',
                        help='Hide the separate Python monitor; TORCS in-game HUD stays enabled')
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--visible-ai',action='store_true',help='AI Practice in the TORCS window; start it from the Race menu')
    parser.add_argument('--acceptance',choices=('smoke','full-course'),
                        help='Smoke checks integration; full-course also requires the completed AI protocol')
    parser.add_argument('--mock-instruments',action='store_true',help='Enable in-memory PSU/eLoad coordinator only')
    parser.add_argument('--mock-arm',action='store_true',help='Explicitly arm mock outputs; never physical hardware')
    parser.add_argument('--mock-control-hz',type=float,default=10.)
    parser.add_argument('--mock-charge-limit',type=float,default=.5)
    args=parser.parse_args()
    policy=args.acceptance or ('full-course' if args.mode=='ai' and not args.visible_ai else 'smoke')
    if policy=='full-course' and (args.mode!='ai' or args.visible_ai):
        parser.error('full-course requires headless --mode ai')
    if args.mock_arm and not args.mock_instruments:parser.error('--mock-arm requires --mock-instruments')
    mock_config = None
    if args.mock_instruments:
        from instrument_control import ControlConfig, MockInstrumentService
        try:
            mock_config=ControlConfig(discharge_limit_A=1., charge_limit_A=args.mock_charge_limit,
                                      control_hz=args.mock_control_hz)
        except ValueError as error:parser.error(str(error))
    if args.visible_ai and args.mode!='ai':parser.error('--visible-ai requires --mode ai')
    if not 0<args.duration<=3600 or not 0<=args.port<=65535:
        parser.error('duration must be 0–3600 seconds and port 0–65535')
    output=args.output_dir or ROOT/'.local/live-trials'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output=output.resolve()
    if args.mode!='listen' and not args.skip_build:
        build(TORCS/'src/modules/simu/simuv2/simuv2.vcxproj',ROOT/'.local/live-simulator-build.log')
        build(TORCS/'src/modules/graphic/ssggraph/ssggraphlib.vcxproj',ROOT/'.local/live-graphics-build.log')
        build(TORCS/'src/libs/client/client.vcxproj',ROOT/'.local/live-client-build.log')
        if args.mode=='ai':build(TORCS/'src/drivers/aps380_ai/aps380_ai.vcxproj',ROOT/'.local/live-driver-build.log')
    if args.mode=='ai':
        local=ROOT/'.local/tesla-live-ai-profile';prepare_profile(local)
    elif args.mode=='g29':
        local=configure()
    receiver=LiveReceiver(args.port,output,args.config,PROFILE)
    mock_service = None
    if mock_config is not None:
        mock_service=MockInstrumentService(output/'mock_instruments',mock_config)
        receiver.demand_sink=mock_service.demands
    implementation=[Path(__file__), ROOT/'aps380_torcs_starter/torcs_live.py',
                    ROOT/'aps380_torcs_starter/trial_acceptance.py',
                    ROOT/'aps380_torcs_starter/live_display.py',ROOT/'aps380_torcs_starter/cell_scaling.py',
                    TORCS/'src/modules/simu/simuv2/aps380_live.h',RUNTIME/'modules/simu/simuv2.dll',
                    ROOT/'aps380_torcs_starter/driver_feedback.py',
                    TORCS/'src/modules/graphic/ssggraph/aps380_hud.h',
                    TORCS/'src/modules/graphic/ssggraph/grboard.cpp',RUNTIME/'client.dll']
    if mock_service is not None:
        implementation += [ROOT/'aps380_torcs_starter'/name for name in
                           ('instrument_interfaces.py','mock_instruments.py','instrument_control.py')]
    (output/'implementation_manifest.json').write_text(json.dumps(
        {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in implementation},indent=2)+'\n')
    receiver.start()
    if mock_service is not None:mock_service.start(arm=args.mock_arm)
    before=set((RUNTIME/'telemetry').glob('aps380_ev_*.csv'))
    child=None;log=None
    stop_reason='startup_error'
    env=dict(os.environ,APS380_LIVE_PORT=str(receiver.port),
             MPLCONFIGDIR=str(ROOT/'.local/matplotlib'))
    os.environ['MPLCONFIGDIR']=env['MPLCONFIGDIR']
    print(f'Live receiver: 127.0.0.1:{receiver.port}\nArtifacts: {output}',flush=True)
    try:
        if args.mode!='listen':
            env['APS380_TORCS_PROFILE']=str(local)
            # Headless AI gets explicit wall-clock pacing; GUI G29 uses TORCS pacing.
            env['APS380_LIVE_REALTIME']='1' if args.mode=='ai' and not args.visible_ai else '0'
            env['APS380_AI_LOG']=str(output/'driver.csv')
            command=[str(RUNTIME/'wtorcs.exe')]
            if args.mode=='ai' and not args.visible_ai:command+=['-r',str(local/'race.xml')]
            log=(output/'torcs.log').open('w')
            child=subprocess.Popen(command,cwd=RUNTIME,env=env,stdout=log,stderr=subprocess.STDOUT)
        finished=lambda: child is not None and child.poll() is not None
        if args.no_ui:
            deadline=time.perf_counter()+args.duration;notice=0
            while time.perf_counter()<deadline and not finished() and not receiver.failed:
                if time.perf_counter()>notice:
                    print(receiver.processor.state(),receiver.processor.stats,flush=True)
                    notice=time.perf_counter()+15
                time.sleep(.1)
            stop_reason='receiver_error' if receiver.failed else ('process_exit' if finished() else 'duration_elapsed')
        else:
            from live_display import LiveDisplay
            LiveDisplay(receiver,finished,args.duration,mock_service=mock_service).run()
            stop_reason='receiver_error' if receiver.failed else ('process_exit' if finished() else 'operator_stop')
    finally:
        # Stop mock control while telemetry is still live, then end our native
        # peer. Mark the boundary before peer termination so a Windows UDP reset
        # from an outstanding HUD reply cannot masquerade as a driving failure.
        receiver.begin_shutdown()
        try:
            mock_report=mock_service.close() if mock_service is not None else None
        finally:
            try:
                terminated=child is not None and child.poll() is None
                if terminated:
                    child.terminate();child.wait(timeout=10)
            finally:
                if log:log.close()
                report=receiver.close()
    rows=[json.loads(line)['row'] for line in (output/'received.jsonl').read_text().splitlines()
          if json.loads(line)['kind']=='sample']
    result={'mode':args.mode,'timing':report,'terminated_before_exit':terminated,
            'stop_reason':stop_reason,
            'torcs_exit_code':child.returncode if child else None,
            'manual_g29_trial':'requires_human_wheel_and_pedal_evidence' if args.mode=='g29' else 'not_run',
            'simulator_dll_sha256':hashlib.sha256((RUNTIME/'modules/simu/simuv2.dll').read_bytes()).hexdigest()}
    if mock_report is not None:result['mock_instruments']=mock_report
    fresh=set((RUNTIME/'telemetry').glob('aps380_ev_*.csv'))-before
    if len(fresh)==1:
        result['capture_audit']=audit_capture(output,rows,fresh.pop())
    else:
        result['capture_audit']={'all_received_samples_match_csv':False,'fresh_csv_count':len(fresh)}
    if args.mode=='ai' and not args.visible_ai and not terminated and child.returncode==0:
        result['course_protocol']=validate_protocol(output/'drive.csv',output/'vehicle_profile.json',output/'driver.csv')
    stats=report['statistics']
    lost_fraction=stats['missing']/max(stats['missing']+stats['accepted'],1)
    result['acceptance_policy']='Software trial gates; not hardware capabilities or physical calibration'
    pacing_ratio=report['active_sim_to_wall_ratio'] if args.mode=='g29' else report['sim_to_wall_ratio']
    result['checks']={
        'received_at_least_10_seconds':report['sim_duration_s']>=10,
        'no_invalid_packets':stats['invalid']==0,
        'packet_loss_at_most_1_percent':lost_fraction<=.01,
        'no_packet_loss':stats['missing']==0,
        'no_stale_intervals':not any(state.startswith('STALE') for state in report['state_transitions']),
        'no_publisher_send_errors':report['publisher_send_errors']==0,
        'no_continuity_breaks':stats['gaps']==0,
        'real_time_ratio_within_5_percent':pacing_ratio is not None and .95<=pacing_ratio<=1.05,
        'receive_rate_40_to_55_hz':report['received_hz'] is not None and 40<=report['received_hz']<=55,
        'csv_agreement':result['capture_audit']['all_received_samples_match_csv'],
        'receiver_healthy':report['receiver_error'] is None,
        'processing_p95_below_10_ms':report['processing_ms'] is not None and report['processing_ms']['p95']<10,
        'sender_age_p95_below_50_ms':report['sender_to_receive_ms'] is not None and report['sender_to_receive_ms']['p95']<50,
    }
    if args.mode=='g29' or args.visible_ai:
        result['checks']['in_game_hud_rendered']=report['visual_hud_feedback']['rendered_acks']>0
    if args.visible_ai:result['trial_scope']='visible AI feedback smoke; complete course protocol not assessed'
    if args.mode=='g29':
        states=report['state_transitions']
        result['manual_g29_trial']='recorded telemetry; operator confirmation of physical controls required'
        result['manual_observations']={
            'throttle_seen':any(row['throttle']>.1 for row in rows),
            'brake_seen':any(row['brake']>.1 for row in rows),
            'vehicle_movement_seen':any(row['speed_mps']>1 for row in rows),
            'regeneration_seen':any(row['pack_power_W']<-100 for row in rows),
            'stale_then_receiving_seen':any(state.startswith('STALE') and 'RECEIVING' in states[index+1:] for index,state in enumerate(states)),
        }
    result['acceptance']=trial_acceptance(result['checks'],
        dict(launched=child is not None,exit_code=child.returncode if child else None,
             terminated_by_launcher=terminated,stop_reason=stop_reason),policy,
        mock_report['acceptance'] if mock_report else None,result.get('course_protocol'))
    result['all_software_gates_passed']=result['acceptance']['passed']
    (output/'trial.json').write_text(json.dumps(result,indent=2)+'\n')
    report_text='# '+args.mode.upper()+' real-time trial\n\n'
    report_text+='Simulation only. Physical cell current tracking and Tesla fidelity remain unvalidated.\n\n'
    for key,value in result['checks'].items():report_text+=f'- {key}: **{value}**\n'
    report_text+=f"\nAcceptance: {policy}; overall **{result['all_software_gates_passed']}**.\n"
    for section in ('telemetry','process','instruments','full_course'):
        report_text+=f"\n{section}: `{json.dumps(result['acceptance'][section])}`\n"
    if 'course_protocol' in result:
        report_text+=f"\n30/50 km/h qualifying holds: {result['course_protocol']['hold_30_seconds']:.2f} / {result['course_protocol']['hold_50_seconds']:.2f} s.\n"
    report_text+='\nSee timing_report.md, trial.json, live_profile.png and raw received.jsonl.\n'
    (output/'trial_report.md').write_text(report_text,encoding='utf-8')
    print(json.dumps({'all_passed':result['all_software_gates_passed'],'checks':result['checks'],'output':str(output)},indent=2))
    if not result['all_software_gates_passed']:raise SystemExit(1)


if __name__=='__main__':main()
