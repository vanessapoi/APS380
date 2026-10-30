"""Live TORCS -> standalone PSU/eLoad tracking. Mock default; no automatic hardware ARM."""
import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'aps380_torcs_starter'))
sys.path.insert(0, str(ROOT/'scripts'))
from torcs_live import LiveReceiver
from configure_tesla import RUNTIME, configure
from run_tesla_ai import prepare_profile
from live_control import BK8500, LiveConfig, LiveService, MockLiveLoad, validate_approval


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    defaults = LiveConfig()
    p.add_argument('--device', choices=('mock', 'hardware'), default='mock')
    p.add_argument('--torcs', choices=('ai', 'g29', 'keyboard', 'listen'), default='ai')
    p.add_argument('--duration', type=float, default=30.)
    p.add_argument('--telemetry-port', type=int, default=50001)
    p.add_argument('--port', help='Hardware serial port; never automatically selected')
    p.add_argument('--baud', type=int, choices=(4800, 9600, 19200, 38400), default=9600)
    p.add_argument('--address', type=int, choices=range(255), default=0)
    p.add_argument('--approval', type=Path, help='Verified setup and lab approval JSON')
    p.add_argument('--max-current-A', type=float, default=defaults.max_current_A)
    p.add_argument('--max-power-W', type=float, default=defaults.max_power_W)
    p.add_argument('--voltage-min-V', type=float, default=defaults.voltage_min_V)
    p.add_argument('--voltage-max-V', type=float, default=defaults.voltage_max_V)
    p.add_argument('--reference-current-A', type=float, default=defaults.reference_current_A,
                   help='Fixed original discharge magnitude mapped to 3 A; selected before session')
    p.add_argument('--slew-A-per-s', type=float, default=defaults.slew_A_per_s)
    p.add_argument('--control-hz', type=float, default=defaults.control_hz)
    p.add_argument('--max-cycle-s', type=float, default=defaults.max_cycle_s)
    p.add_argument('--mock-transaction-delay-s', type=float, default=.064,
                   help='Mock-only imposed transaction delay, not a hardware timing guarantee')
    p.add_argument('--output', type=Path)
    p.add_argument('--auto-arm-mock', action='store_true')
    p.add_argument('--no-console', action='store_true')
    p.add_argument('--inject-telemetry-loss-after', type=float, help='Mock-only: terminate own TORCS process')
    p.add_argument('--expect-telemetry-fault', action='store_true', help='Mock fault-response experiment only')
    args = p.parse_args(argv)
    if not 0 < args.duration <= 3600 or not 0 <= args.telemetry_port <= 65535:
        p.error('Invalid duration or UDP port')
    if not math.isfinite(args.mock_transaction_delay_s) or not 0 <= args.mock_transaction_delay_s <= .25:
        p.error('Mock transaction delay must be between 0 and 0.25 s')
    try:
        args.config = LiveConfig(max_current_A=args.max_current_A,
            max_power_W=args.max_power_W, voltage_min_V=args.voltage_min_V,
            voltage_max_V=args.voltage_max_V, reference_current_A=args.reference_current_A,
            slew_A_per_s=args.slew_A_per_s, control_hz=args.control_hz, max_cycle_s=args.max_cycle_s)
        args.approval_data = json.loads(args.approval.read_text()) if args.approval else None
        if args.device == 'hardware':
            if args.auto_arm_mock or args.no_console or args.inject_telemetry_loss_after is not None or args.expect_telemetry_fault:
                p.error('Hardware requires supervised console ARM; mock automation/injection forbidden')
            if not args.port or not args.approval_data: p.error('Hardware requires --port and --approval')
            validate_approval(args.approval_data, args.config)
            if not sys.stdin.isatty(): p.error('Hardware ARM requires an interactive supervised terminal')
        elif args.port or args.approval:
            p.error('Do not provide serial port or lab approval in mock mode')
        if args.inject_telemetry_loss_after is not None:
            if args.torcs == 'listen' or not 1 < args.inject_telemetry_loss_after < args.duration-1:
                p.error('Injection requires own TORCS process and time within trial')
        if args.expect_telemetry_fault and args.inject_telemetry_loss_after is None:
            p.error('Expected-fault acceptance requires deliberate mock injection')
    except (ValueError, OSError, TypeError) as exc:
        p.error(str(exc))
    return args


def console(service, quit_event, arm_phrase):
    print('Commands: '+arm_phrase+' | DISARM | STOP | RESET | QUIT. Ctrl+C also stops.', flush=True)
    while not quit_event.is_set():
        try: command = input().strip()
        except EOFError:
            service.request('stop'); quit_event.set(); return
        if command == arm_phrase: service.request('arm')
        elif command.upper() in ('DISARM', 'STOP', 'RESET'):
            service.request(command.lower())
        elif command.upper() == 'QUIT':
            quit_event.set(); return
        else: print('No action: command not recognized.', flush=True)


def artifacts(output, service):
    """Separate logs/plots; no changes to existing live or replay output formats."""
    import csv
    rows = [e for e in service.events if e['event']=='cycle' and e['state']=='RUNNING' and 'readback_setting_A' in e]
    if not rows: return
    keys = ('host_s', 'torcs_time_s', 'source_session', 'source_sequence',
        'original_cell_current_A', 'limited_cell_current_A', 'scaled_load_demand_A',
        'limited_load_target_A', 'power_limited_load_target_A', 'commanded_load_A',
        'readback_setting_A', 'measured_A', 'voltage_V', 'power_W', 'input_on',
        'command_roundtrip_ms', 'setting_read_roundtrip_ms', 'measurement_roundtrip_ms',
        'cycle_ms', 'command_age_s', 'tracking_error_A', 'demand_error_A', 'regen_suppressed', 'saturated')
    with (output/'load_tracking.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(3, 1, sharex=True)
    t = [r['host_s']-rows[0]['host_s'] for r in rows]
    for key in ('original_cell_current_A', 'scaled_load_demand_A'):
        ax[0].plot(t, [r[key] for r in rows], label=key)
    for key in ('power_limited_load_target_A', 'commanded_load_A', 'readback_setting_A', 'measured_A'):
        ax[1].plot(t, [r[key] for r in rows], label=key)
    ax[2].plot(t, [r['cycle_ms'] for r in rows], label='complete cycle ms')
    ax[0].set_ylabel('Original / mapped A'); ax[1].set_ylabel('eLoad A')
    ax[2].set_ylabel('ms'); ax[2].set_xlabel('Host elapsed s')
    for a in ax: a.legend(fontsize=7); a.grid(True)
    fig.tight_layout(); fig.savefig(output/'load_tracking.png'); plt.close(fig)


def main(argv=None):
    args = parse_args(argv)
    output = (args.output or ROOT/'.local/bk8500-live'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')).resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'.local/matplotlib'))
    (output/'config.json').write_text(json.dumps(dict(device=args.device, **asdict(args.config),
        mock_transaction_delay_s=args.mock_transaction_delay_s if args.device=='mock' else None,
        approval=args.approval_data, psu_readback_available=False,
        mapping='clamp(-original_charging_positive_cell_A * 3 / fixed_reference_A, 0, approved_max_A)',
        scope='PSU to eLoad only; no battery, PSU bias or regenerative charging'), indent=2)+'\n')
    sources = [Path(__file__), Path(__file__).with_name('live_control.py'), Path(__file__).with_name('instrument.py'),
               ROOT/'aps380_torcs_starter/torcs_live.py', ROOT/'aps380_torcs_starter/cell_scaling.py',
               ROOT/'aps380_torcs_starter/prototype_current_config.py', RUNTIME/'modules/simu/simuv2.dll']
    (output/'manifest.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sources}, indent=2)+'\n')
    link = None; receiver = None; service = None; child = None; report = None
    quit_event = threading.Event()
    log = (output/'torcs.log').open('w')
    injected = False
    stop_reason = 'startup_error'
    terminated_by_launcher = False
    try:
        if args.device == 'mock':
            device = MockLiveLoad(args.config, delay_s=args.mock_transaction_delay_s)
        else:
            # No serial import or port opening occurs in mock mode.
            import serial
            link = serial.Serial(port=None, baudrate=args.baud,
                                 timeout=args.config.io_timeout_s, write_timeout=args.config.io_timeout_s)
            link.port = args.port; link.dtr = link.rts = True; link.open()
            device = BK8500(link, args.address, max_setpoint_A=args.config.max_current_A)
        service = LiveService(device, args.config, output/'instruments')
        receiver = LiveReceiver(args.telemetry_port, output/'telemetry', demand_sink=service.demands)
        receiver.start(); service.start()
        if args.torcs != 'listen':
            local = ROOT/'.local/tesla-bk8500-ai-profile'
            if args.torcs == 'ai': prepare_profile(local)
            elif args.torcs == 'keyboard':
                from configure_keyboard import prepare_keyboard
                local = prepare_keyboard()
            else: local = configure()
            env = dict(os.environ, APS380_LIVE_PORT=str(receiver.port),
                APS380_LIVE_REALTIME='1' if args.torcs=='ai' else '0',
                APS380_TORCS_PROFILE=str(local), APS380_AI_LOG=str(output/'driver.csv'))
            command = [str(RUNTIME/'wtorcs.exe')]
            if args.torcs == 'ai': command += ['-r', str(local/'race.xml')]
            child = subprocess.Popen(command, cwd=RUNTIME, env=env, stdout=log, stderr=subprocess.STDOUT)
        phrase = 'ARM' if args.device=='mock' else 'ARM '+args.approval_data['approval_reference']
        print(f'Output: {output}\nTelemetry UDP: {receiver.port}. Starts with input OFF.', flush=True)
        if not args.no_console:
            threading.Thread(target=console, args=(service, quit_event, phrase), daemon=True).start()
        started = time.perf_counter(); notice = started; armed_once = False; injected_at = None
        while time.perf_counter()-started < args.duration and not quit_event.is_set():
            c = service.controller
            if args.auto_arm_mock and not armed_once and c.state=='READY' and service.demands.snapshot()[0] is not None:
                service.request('arm'); armed_once = True
            if args.inject_telemetry_loss_after and not injected and time.perf_counter()-started >= args.inject_telemetry_loss_after:
                if child and child.poll() is None:
                    child.terminate(); child.wait(timeout=10); injected_at = time.perf_counter(); injected = True
            if time.perf_counter() >= notice:
                record = service.events[-1] if service.events else {}
                keys = ('torcs_time_s', 'original_cell_current_A', 'scaled_load_demand_A',
                        'commanded_load_A', 'readback_setting_A', 'measured_A', 'voltage_V',
                        'power_W', 'input_on', 'cycle_ms', 'measurements_retained')
                print(json.dumps(dict(state=c.state, fault=c.fault, telemetry=receiver.processor.state(),
                    last_complete_event=record.get('event'), **{k:record[k] for k in keys if k in record})), flush=True)
                notice = time.perf_counter()+1
            if receiver.failed:
                if c.state=='RUNNING': service.request('stop')
                stop_reason = 'receiver_error'; break
            if c.state=='FAULT' and args.expect_telemetry_fault:
                stop_reason = 'expected_fault'; break
            if child and child.poll() is not None and not injected:
                stop_reason = 'process_exit'; break
            time.sleep(.02)
        else:
            stop_reason = 'operator_quit' if quit_event.is_set() else 'duration_elapsed'
    except KeyboardInterrupt:
        stop_reason = 'operator_interrupt'
        if service: service.request('stop')
    finally:
        # Stop the load before stopping healthy telemetry / native simulation.
        try:
            if service: report = service.close()
        finally:
            if receiver: receiver.begin_shutdown()
            if child and child.poll() is None:
                child.terminate(); child.wait(timeout=10); terminated_by_launcher = True
            log.close()
            if link and (not service or not service.worker.is_alive()): link.close()
            timing = receiver.close() if receiver else None
        if service:
            result = dict(device=args.device, instrument=report, telemetry=timing,
                          process_exit_code=child.returncode if child else None,
                          stop_reason=stop_reason, terminated_by_launcher=terminated_by_launcher,
                          deliberate_interruption=injected,
                          independent_hardware_protection='Not implemented or verified by this software')
            telemetry_ok = bool(timing and timing['samples'] and timing['receiver_error'] is None and
                timing['statistics']['invalid']==0 and timing['statistics']['missing']==0 and
                not timing['stale_intervals'])
            process_ok = child is None or child.returncode==0 or (
                terminated_by_launcher and stop_reason in ('duration_elapsed', 'operator_quit', 'operator_interrupt'))
            result['acceptance'] = dict(telemetry='PASS' if telemetry_ok else 'FAIL',
                instruments=report.get('control_status', 'FAIL'),
                process='PASS' if process_ok else 'FAIL', full_course='NOT ASSESSED',
                normal_operation_passed=bool(report['passed'] and telemetry_ok and process_ok))
            try:
                artifacts(output, service)
                result['acceptance']['artifacts'] = 'PASS'
            except Exception as exc:
                result['artifact_error'] = repr(exc)
                result['acceptance']['artifacts'] = 'FAIL'
                result['acceptance']['normal_operation_passed'] = False
            if args.expect_telemetry_fault:
                faults = report.get('faults', [])
                expected = bool(faults) and all(f in ('TELEMETRY_EXPIRED', 'STALE_TELEMETRY',
                    'DEMAND_INVALIDATED_OR_EXPIRED_DURING_IO') for f in faults)
                result['fault_response_passed'] = bool(injected and expected and report.get('running_cycles') and report.get('shutdown_verified'))
                result['interruption_host_s'] = injected_at
            (output/'trial.json').write_text(json.dumps(result, indent=2)+'\n')
            print(json.dumps(result['instrument'], indent=2), flush=True)
    if not report: return 1
    if args.expect_telemetry_fault: return 0 if result['fault_response_passed'] else 1
    return 0 if result['acceptance']['normal_operation_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
