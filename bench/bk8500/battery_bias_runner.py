"""Opt-in MOCK Battery Bias workflow. No physical transport can be selected."""
import argparse
from dataclasses import asdict
from datetime import datetime
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from battery_bias import BatteryBiasService
from torcs_live import LiveReceiver


def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--device',choices=('mock',),default='mock',help='Physical Battery Bias is unavailable')
    p.add_argument('--torcs',choices=('ai','keyboard','g29','listen'),default='ai')
    p.add_argument('--keyboard-profile',choices=('3s','5s','8s'))
    p.add_argument('--duration',type=float,default=60.)
    p.add_argument('--telemetry-port',type=int,default=50001)
    p.add_argument('--mock-psu-current-A',type=float,default=.2,
                   help='Imposed mock available source current, NOT its configured CC limit')
    p.add_argument('--sop-config',type=Path,default=ROOT/'aps380_torcs_starter/profiles/rint_sop_live_mock_example.json')
    p.add_argument('--output',type=Path)
    p.add_argument('--dashboard',action='store_true')
    p.add_argument('--propulsion-feedback',action='store_true',help='Opt-in MOCK bias SOC/Rint -> native TORCS availability')
    p.add_argument('--auto-arm-mock',action='store_true')
    p.add_argument('--no-console',action='store_true')
    p.add_argument('--inject-telemetry-loss-after',type=float,help='MOCK only: stop own simulator and wait for freshness fault')
    p.add_argument('--expect-telemetry-fault',action='store_true')
    a=p.parse_args(argv)
    if not math.isfinite(a.duration) or not 1<=a.duration<=3600:p.error('Duration must be 1..3600 s')
    if not 0<=a.telemetry_port<=65535:p.error('Invalid UDP port')
    if not math.isfinite(a.mock_psu_current_A) or not 0<=a.mock_psu_current_A<=1:p.error('Mock source must be 0..1 A')
    if a.keyboard_profile and a.torcs!='keyboard':p.error('Keyboard profile requires keyboard mode')
    if a.inject_telemetry_loss_after is not None and (a.torcs=='listen' or not 1<a.inject_telemetry_loss_after<a.duration-2):
        p.error('Fault injection requires own simulator and time before trial end')
    if a.expect_telemetry_fault and a.inject_telemetry_loss_after is None:p.error('Expected fault requires deliberate injection')
    return a


def console(service,stop,feedback=None):
    print('MOCK ONLY. Starts DISARMED. ARM | DISARM | STOP (latched) | RESET | RESET POWER | QUIT; press Enter.',flush=True)
    actions={'ARM':'arm','DISARM':'disarm','STOP':'emergency_stop','RESET':'recover'}
    while not stop.is_set():
        try:command=input('Battery Bias MOCK> ').strip().upper()
        except EOFError:stop.set();return
        if command=='QUIT':stop.set();return
        if command=='RESET POWER' and feedback is not None:feedback.request_reset()
        elif command in actions:service.request(actions[command])
        elif command:print('Use ARM, DISARM, STOP, RESET or QUIT.',flush=True)


def artifacts(events,output):
    """Offline CSV and figures; no commands, no inferred physical battery SOC."""
    import csv
    rows=[]
    for e in events:
        if 'cell_sensor_frame' not in e:continue
        f=e['cell_sensor_frame'];m=e.get('cell_model_state',{})
        r=dict(host_s=e.get('host_s',f['acquired_s']),state=e['state'],fault=e['fault'],
            retained=e.get('measurements_retained',False),
            requested_A=e.get('requested_A'),limited_A=e.get('permitted_A'),
            applied_A=e.get('applied_target_A'),measured_cell_A=f['cell_current_A'],
            measured_psu_A=f['psu_current_A'],load_command_A=e.get('load_command_A'),
            measured_load_A=e.get('load',{}).get('current_A'),tracking_error_A=e.get('tracking_error_A'),
            branch_net_A=e.get('contemporaneous_branch_net_A'),sensor_sequence=f['sequence'],
            sensor_age_s=e.get('host_s',f['acquired_s'])-f['acquired_s'],
            cell_soc=m.get('sop_cell_soc_fraction'),sop_W=m.get('sop_max_discharge_W'),
            candidate_ocv_V=m.get('sop_ocv_candidate_V'),cell_isolated=f['cell_isolated'])
        rows.append(r)
    if not rows:return {'running_cycles':0,'tracking':'NOT ASSESSED'}
    output=Path(output)
    with (output/'bias_tracking.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    # The READY->RUNNING record can retain the last isolated balancing sample.
    # It is correctly measured zero at the cell, not a connected KCL sample.
    live=[r for r in rows if r['state']=='RUNNING' and not r['retained'] and not r['cell_isolated']]
    fig,axes=plt.subplots(4,1,sharex=True,figsize=(12,11),layout='constrained')
    t=[r['host_s']-rows[0]['host_s'] for r in live]
    for key in ('requested_A','limited_A','applied_A','measured_cell_A'):
        axes[0].plot(t,[r[key] for r in live],label=key)
    for key in ('measured_psu_A','load_command_A','measured_load_A'):
        axes[1].plot(t,[r[key] for r in live],label=key)
    axes[2].plot(t,[r['tracking_error_A'] for r in live],label='independent cell minus applied')
    axes[2].plot(t,[r['measured_cell_A']-r['branch_net_A'] for r in live],label='independent cell minus KCL')
    axes[3].plot(t,[r['cell_soc']*100 if r['cell_soc'] is not None else None for r in live],label='Cell SOC [MOCK estimate]')
    axes[0].set_ylabel('Signed cell A');axes[1].set_ylabel('Branch A');axes[2].set_ylabel('Error A');axes[3].set_ylabel('SOC %')
    axes[3].set_xlabel('Host elapsed s; RUNNING only; retained records excluded')
    for ax in axes:ax.grid(alpha=.3);ax.legend()
    fig.suptitle('Battery Bias MOCK ONLY: +charge / -discharge; independent synthetic sensor channels')
    fig.savefig(output/'bias_tracking.png',dpi=140);plt.close(fig)
    fig,axes=plt.subplots(2,1,sharex=True,figsize=(10,6),layout='constrained')
    axes[0].plot(t,[r['sop_W'] for r in live]);axes[0].set_ylabel('Rint SOP W [EST]')
    axes[1].plot(t,[r['candidate_ocv_V'] for r in live]);axes[1].set_ylabel('Candidate OCV V');axes[1].set_xlabel('Host elapsed s')
    fig.suptitle('Unvalidated mock assumptions; no physical battery; see telemetry for opt-in propulsion feedback')
    fig.savefig(output/'bias_model.png',dpi=140);plt.close(fig)
    return dict(running_cycles=len(live),tracking='ASSESSED' if live else 'NOT ASSESSED',
        max_tracking_error_A=max((abs(r['tracking_error_A']) for r in live),default=None),
        max_kcl_error_A=max((abs(r['measured_cell_A']-r['branch_net_A']) for r in live),default=None),
        measured_range_A=[min(r['measured_cell_A'] for r in live),max(r['measured_cell_A'] for r in live)] if live else None)


def main(argv=None):
    a=parse_args(argv)  # hardware is rejected BEFORE any service or process
    model=json.loads(a.sop_config.read_text(encoding='utf-8'))
    output=(a.output or ROOT/'.local/battery-bias'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')).resolve()
    output.mkdir(parents=True,exist_ok=False)
    service=BatteryBiasService(output/'instruments',sop_config=model)
    service.psu.cv_available_A=a.mock_psu_current_A
    feedback=None
    if a.propulsion_feedback:
        from battery_bias_feedback import BiasRintPolicy
        from vehicle_power_limit import PowerFeedback
        feedback=PowerFeedback(BiasRintPolicy(service))
    (output/'mode.json').write_text(json.dumps(dict(mode='battery_bias_mock',physical_operation_enabled=False,
        config=asdict(service.config),qualification=asdict(service.coordinator.qualification),
        imposed_mock_available_psu_current_A=a.mock_psu_current_A,model_assumptions=model),indent=2)+'\n')
    receiver=None;child=None;timing=None;stop=threading.Event();status=None;error=None
    natural_exit=None;terminated_by_launcher=False;injected=False;injected_at=None
    report=None
    # Reuse profile preparation and existing native launcher, not input mappings.
    from live_torcs import prepare_launch_profile,RUNTIME,close_receiver
    log=(output/'torcs.log').open('w')
    try:
        receiver=LiveReceiver(a.telemetry_port,output/'telemetry',demand_sink=service.demands,
            peer_exit_status=lambda:child.poll() if child and not injected else None,power_feedback=feedback)
        if feedback:
            if not receiver.processor.shared_clock:raise RuntimeError('Feedback requires qualified shared clock')
            feedback.policy.configure(receiver.processor.cell,receiver.processor.profile)
        receiver.start();service.start()
        if a.torcs!='listen':
            profile=prepare_launch_profile(a.torcs,a.keyboard_profile)
            env=dict(os.environ,APS380_LIVE_PORT=str(receiver.port),APS380_LIVE_REALTIME='1' if a.torcs=='ai' else '0',
                APS380_TORCS_PROFILE=str(profile),APS380_AI_LOG=str(output/'driver.csv'))
            if feedback:env['APS380_MOCK_POWER_LIMIT']='1'
            command=[str(RUNTIME/'wtorcs.exe')]
            if a.torcs=='ai':command+=['-r',str(profile/'race.xml')]
            child=subprocess.Popen(command,cwd=RUNTIME,env=env,stdout=log,stderr=subprocess.STDOUT)
        print(f'Battery Bias MOCK ONLY. Output: {output}\nUDP {receiver.port}. ARM explicitly; startup balances with cell isolated.',flush=True)
        if feedback:print('Propulsion feedback enabled (MOCK). After recovery/ARM, use RESET POWER explicitly.',flush=True)
        if not a.no_console:threading.Thread(target=console,args=(service,stop,feedback),daemon=True).start()
        started=time.perf_counter();deadline=started+a.duration;armed=False
        def finished():
            nonlocal armed,status,natural_exit,injected,injected_at
            s=service.latest;new=(s['state'],s['fault'])
            if new!=status:print('MOCK:',new,flush=True);status=new
            if a.auto_arm_mock and not armed and service.demands.snapshot()[0] is not None:
                service.request('arm');armed=True
            if a.inject_telemetry_loss_after is not None and not injected and time.perf_counter()-started>=a.inject_telemetry_loss_after:
                injected=True;injected_at=time.perf_counter()
                if child and child.poll() is None:child.terminate();child.wait(timeout=10)
            if child is not None and child.poll() is not None and not injected:natural_exit=child.returncode
            return bool(stop.is_set() or time.perf_counter()>=deadline or receiver.failed or service.failed
                or natural_exit is not None or (a.expect_telemetry_fault and s['state']=='FAULT'))
        if a.dashboard:
            from live_display import LiveDisplay
            LiveDisplay(receiver,finished,duration=a.duration,mock_service=service).run()
        else:
            while not finished():time.sleep(.05)
    except KeyboardInterrupt:pass
    except Exception as exc:error=repr(exc)
    finally:
        stop.set()
        native_zero=False
        if feedback:
            feedback.request_stop()
            if receiver and not receiver.failed and (child is None or child.poll() is None):
                native_zero=feedback.stop_verified.wait(1.)
        # Verify cell/source isolation and both mock outputs before receiver exit.
        try:report=service.close()
        except Exception as exc:
            error=(error+'; ' if error else '')+'SERVICE_CLOSE: '+repr(exc)
            service.coordinator.trip('CLEANUP_FAILED')
            report=dict(worker_error=error,final=service.coordinator.snapshot(),acceptance=dict(passed=False))
        if receiver:
            receiver.begin_shutdown()
            try:
                if child and child.poll() is None:
                    child.terminate();child.wait(timeout=10);terminated_by_launcher=True
                elif child and natural_exit is None and not injected:natural_exit=child.returncode
            except Exception as exc:
                error=(error+'; ' if error else '')+'PROCESS_CLEANUP: '+repr(exc)
            timing,report_error=close_receiver(receiver,output)
            if report_error:error=(error+'; ' if error else '')+'RECEIVER_REPORT: '+report_error
        log.close()
    events=[json.loads(line) for line in (output/'instruments/instruments.jsonl').read_text().splitlines()]
    analysis=artifacts(events,output)
    telemetry_ok=bool(timing and timing['samples'] and not timing['receiver_error'] and
                      not timing['statistics']['invalid'] and not timing['statistics']['missing'] and
                      not timing['stale_intervals'])
    process_ok=natural_exit in (None,0)
    passed=bool(telemetry_ok and process_ok and report['acceptance']['passed'] and report['final']['shutdown_verified'] and not error
                and not report['worker_error'] and not report['final']['fault']
                and (not service.arming_requested or analysis['running_cycles']))
    fault_passed=bool(a.expect_telemetry_fault and injected and analysis['running_cycles'] and not error
        and not report['worker_error'] and report['final']['shutdown_verified'] and
        any(token in report['final']['fault'] for token in ('TELEMETRY','STALE')))
    if feedback:
        telemetry_path=output/'telemetry/received.jsonl'
        telemetry_rows=[e['row'] for e in map(json.loads,telemetry_path.read_text().splitlines()) if e['kind']=='sample'] if telemetry_path.exists() else []
        native_faults=sorted({r.get('vehicle_limit_state') for r in telemetry_rows if r.get('vehicle_limit_state','').startswith('FAULT')})
        passed=bool(passed and native_zero and not feedback.fatal.is_set() and not native_faults
                    and any(r.get('vehicle_limit_applied_fraction',0)>0 for r in telemetry_rows))
    result=dict(mock_only=True,physical_commands_sent=False,propulsion_feedback_connected=feedback is not None,
        native_zero_shutdown_verified=native_zero if feedback else None,
        propulsion_error=feedback.error if feedback else None,
        native_faults=native_faults if feedback else [],
        runtime_error=error,telemetry=timing,instruments=report,analysis=analysis,
        process_exit=natural_exit,terminated_by_launcher=terminated_by_launcher,
        injected_at_host_s=injected_at,expected_fault_response_passed=fault_passed,
        acceptance=dict(telemetry='PASS' if telemetry_ok else 'FAIL',
                        instruments='PASS' if passed and analysis['running_cycles'] else 'FAIL' if service.arming_requested else 'NOT ASSESSED'),
        passed=passed,full_course_completion='NOT ASSESSED',keyboard_profile=a.keyboard_profile)
    (output/'trial.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(output=str(output),analysis=analysis,shutdown_verified=report['final']['shutdown_verified'],error=error),indent=2))
    return 0 if passed or fault_passed else 1


if __name__=='__main__':raise SystemExit(main())
