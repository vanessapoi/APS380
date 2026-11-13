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
from configure_tesla import RUNTIME
from run_tesla_ai import prepare_profile
from live_control import (BK8500, LiveConfig, LiveService, MockLiveLoad,
                          validate_approval, INITIAL_HARDWARE_CURRENT_MAX_A,
                          EXTENDED_PSU_ONLY_CURRENT_MAX_A)
from live_presentation import LoadMonitor, ConsoleStatus


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    defaults = LiveConfig()
    p.add_argument('--device', choices=('mock', 'hardware'), default='mock')
    p.add_argument('--torcs', choices=('ai', 'g29', 'keyboard', 'listen'), default='ai')
    p.add_argument('--keyboard-profile', choices=('5s','3s','8s'),
                   help='Keyboard-only accelerator rise preset; default 5s')
    p.add_argument('--duration', type=float, default=30.)
    p.add_argument('--telemetry-port', type=int, default=50001)
    p.add_argument('--port', help='Hardware serial port; never automatically selected')
    p.add_argument('--baud', type=int, choices=(4800, 9600, 19200, 38400), default=9600)
    p.add_argument('--address', type=int, choices=range(255), default=0)
    p.add_argument('--approval', type=Path, help='Verified setup and lab approval JSON')
    p.add_argument('--extended-psu-only', action='store_true',
                   help='Opt-in <=1 A commissioning; requires approved existing protection envelope')
    p.add_argument('--protection-voltage-ceiling-V', type=float)
    p.add_argument('--protection-current-ceiling-A', type=float)
    p.add_argument('--protection-power-ceiling-W', type=float)
    p.add_argument('--max-current-A', type=float, default=defaults.max_current_A)
    p.add_argument('--max-power-W', type=float, default=defaults.max_power_W)
    p.add_argument('--voltage-min-V', type=float, default=defaults.voltage_min_V)
    p.add_argument('--voltage-max-V', type=float, default=defaults.voltage_max_V)
    p.add_argument('--reference-current-A', type=float, default=defaults.reference_current_A,
                   help='Fixed original discharge magnitude mapped to --max-current-A before clipping')
    p.add_argument('--slew-A-per-s', type=float, default=defaults.slew_A_per_s)
    p.add_argument('--control-hz', type=float, default=defaults.control_hz)
    p.add_argument('--max-cycle-s', type=float, default=defaults.max_cycle_s)
    p.add_argument('--tracking-tolerance-A', type=float, default=defaults.tracking_tolerance_A)
    p.add_argument('--tracking-timeout-s', type=float, default=defaults.tracking_timeout_s)
    p.add_argument('--mock-transaction-delay-s', type=float, default=.064,
                   help='Mock-only imposed transaction delay, not a hardware timing guarantee')
    p.add_argument('--output', type=Path)
    p.add_argument('--auto-arm-mock', action='store_true')
    p.add_argument('--no-console', action='store_true')
    p.add_argument('--dashboard', action='store_true', help='Open the existing APS380 Tk dashboard with separate eLoad monitoring')
    p.add_argument('--status-interval-s', type=float, default=5., help='Console RUNNING summary interval (dashboard prints transitions only)')
    p.add_argument('--json-status', action='store_true', help='Opt-in machine-readable status instead of readable summaries')
    p.add_argument('--inject-telemetry-loss-after', type=float, help='Mock-only: terminate own TORCS process')
    p.add_argument('--expect-telemetry-fault', action='store_true', help='Mock fault-response experiment only')
    args = p.parse_args(argv)
    if args.keyboard_profile and args.torcs != 'keyboard':
        p.error('--keyboard-profile requires --torcs keyboard')
    if not math.isfinite(args.status_interval_s) or args.status_interval_s < 1:
        p.error('Status interval must be finite and at least 1 second')
    if not 0 < args.duration <= 3600 or not 0 <= args.telemetry_port <= 65535:
        p.error('Invalid duration or UDP port')
    if not math.isfinite(args.mock_transaction_delay_s) or not 0 <= args.mock_transaction_delay_s <= .25:
        p.error('Mock transaction delay must be between 0 and 0.25 s')
    try:
        envelope = (args.protection_voltage_ceiling_V, args.protection_current_ceiling_A,
                    args.protection_power_ceiling_W)
        if args.extended_psu_only:
            if any(v is None for v in envelope):
                p.error('Extended mode requires all three approved protection ceilings')
            if args.max_current_A > EXTENDED_PSU_ONLY_CURRENT_MAX_A:
                p.error('Extended PSU-only commissioning is capped at 1.0 A')
        elif any(v is not None for v in envelope):
            p.error('Protection ceilings require --extended-psu-only')
        args.config = LiveConfig(max_current_A=args.max_current_A,
            max_power_W=args.max_power_W, voltage_min_V=args.voltage_min_V,
            voltage_max_V=args.voltage_max_V, reference_current_A=args.reference_current_A,
            slew_A_per_s=args.slew_A_per_s, control_hz=args.control_hz, max_cycle_s=args.max_cycle_s,
            tracking_tolerance_A=args.tracking_tolerance_A, tracking_timeout_s=args.tracking_timeout_s,
            protection_envelope=envelope if args.extended_psu_only else ())
        args.approval_data = json.loads(args.approval.read_text()) if args.approval else None
        if args.device == 'hardware':
            if not args.extended_psu_only and args.config.max_current_A > INITIAL_HARDWARE_CURRENT_MAX_A:
                p.error('Initial physical live commissioning requires --max-current-A <= 0.10; higher currents remain mock-only')
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


def prepare_launch_profile(mode, keyboard_profile=None):
    """Reuse saved G29 preferences without calling its mutating setup helper."""
    saved = ROOT/'.local/tesla-profile'
    for name in ('drivers/human/human.xml', 'drivers/human/preferences.xml', 'config/raceman/practice.xml'):
        if not (saved/name).is_file():
            raise FileNotFoundError('Prepared G29 profile required; missing '+str(saved/name))
    if mode == 'g29': return saved
    if mode == 'keyboard':
        from configure_keyboard import prepare_keyboard, keyboard_config
        return (prepare_keyboard(keyboard_config(keyboard_profile)) if keyboard_profile
                else prepare_keyboard())
    if mode != 'ai': raise ValueError('No launch profile for '+mode)
    local = ROOT/'.local/tesla-bk8500-ai-profile'
    prepare_profile(local, manual_profile=saved)
    return local


def close_receiver(receiver, output):
    """Preserve the instrument result if receiver plotting/reporting fails."""
    if receiver is None: return None, None
    try:
        return receiver.close(), None
    except Exception as exc:
        timing = None
        path = output/'telemetry/timing_report.json'
        try:
            if path.exists(): timing = json.loads(path.read_text())
        except (OSError, ValueError): pass
        return timing, repr(exc)


def console(service, quit_event, arm_phrase):
    instructions = 'Commands: '+arm_phrase+' | DISARM | STOP | RESET | QUIT | HELP. Type here, then press Enter. Ctrl+C also stops.'
    print(instructions+'\nInput remains OFF until explicitly armed.', flush=True)
    while not quit_event.is_set():
        try: command = input('BK8500> ').strip()
        except EOFError:
            print('Console input closed; requesting STOP and shutdown.', flush=True)
            service.request('stop'); quit_event.set(); return
        if command == arm_phrase:
            service.request('arm')
            print('ARM requested; worker verifies telemetry and interlocks before input ON.', flush=True)
        elif command.upper() in ('DISARM', 'STOP', 'RESET'):
            service.request(command.lower())
            print(command.upper()+' requested.', flush=True)
        elif command.upper() == 'QUIT':
            quit_event.set(); return
        elif command.upper() == 'HELP': print(instructions, flush=True)
        elif command: print('No action: command not recognized. '+instructions, flush=True)


def artifacts(output, service):
    """Separate logs/plots; no changes to existing live or replay output formats."""
    import csv
    rows = [e for e in service.events if e['event']=='cycle' and e['state']=='RUNNING' and 'readback_setting_A' in e]
    if not rows: return
    keys = ('host_s', 'recorded_utc', 'torcs_time_s', 'source_session', 'source_sequence', 'source_received_s',
        'original_cell_current_A', 'limited_cell_current_A', 'scaled_load_demand_A',
        'original_eload_demand_A', 'eload_range_scale',
        'limited_load_target_A', 'power_limited_load_target_A', 'commanded_load_A',
        'readback_setting_A', 'measured_A', 'voltage_V', 'power_W', 'input_on',
        'command_roundtrip_ms', 'setting_read_roundtrip_ms', 'measurement_roundtrip_ms',
        'cycle_ms', 'command_age_s', 'tracking_error_A', 'demand_error_A', 'regen_suppressed', 'saturated',
        'command_acknowledged', 'command_started_host_s', 'command_ack_received_host_s',
        'setpoint_read_received_host_s', 'measurement_received_host_s',
        'previous_commanded_load_A', 'slew_reference_ack_host_s', 'slew_elapsed_s', 'slew_budget_A')
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


def write_manifest(args, output):
    sources = [Path(__file__), Path(__file__).with_name('live_control.py'), Path(__file__).with_name('instrument.py'),
               Path(__file__).with_name('live_presentation.py'), ROOT/'aps380_torcs_starter/live_display.py',
               ROOT/'aps380_torcs_starter/torcs_live.py', ROOT/'aps380_torcs_starter/cell_scaling.py',
               ROOT/'aps380_torcs_starter/prototype_current_config.py', RUNTIME/'modules/simu/simuv2.dll']
    if args.torcs in ('g29', 'keyboard'):
        sources += [RUNTIME/'drivers/human/human.dll']
    if args.torcs == 'keyboard':
        from configure_keyboard import keyboard_config
        sources += [ROOT/'scripts/configure_keyboard.py',
                    keyboard_config(args.keyboard_profile or '5s')]
    (output/'manifest.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sources}, indent=2)+'\n')


def main(argv=None):
    args = parse_args(argv)
    output = (args.output or ROOT/'.local/bk8500-live'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')).resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'.local/matplotlib'))
    (output/'config.json').write_text(json.dumps(dict(device=args.device, **asdict(args.config),
        mock_transaction_delay_s=args.mock_transaction_delay_s if args.device=='mock' else None,
        approval=args.approval_data, psu_readback_available=False,
        mapping='clamp(-original_charging_positive_cell_A * max_current_A / reference_current_A, 0, max_current_A)',
        physical_live_current_ceiling_A=(EXTENDED_PSU_ONLY_CURRENT_MAX_A if args.extended_psu_only
                                        else INITIAL_HARDWARE_CURRENT_MAX_A),
        dashboard=args.dashboard, torcs_mode=args.torcs, console_enabled=not args.no_console,
        keyboard_profile=(args.keyboard_profile or '5s') if args.torcs=='keyboard' else None,
        scope='PSU to eLoad only; no battery, PSU bias or regenerative charging'), indent=2)+'\n')
    write_manifest(args, output)
    link = None; receiver = None; service = None; child = None; report = None
    quit_event = threading.Event()
    log = (output/'torcs.log').open('w')
    injected = False
    injected_at = None
    stop_reason = 'startup_error'
    terminated_by_launcher = False
    receiver_report_error = None
    runtime_error = None
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
        receiver = LiveReceiver(args.telemetry_port, output/'telemetry', demand_sink=service.demands,
            peer_exit_status=lambda: child.poll() if child is not None and not injected else None)
        receiver.start(); service.start()
        if args.torcs != 'listen':
            local = (prepare_launch_profile(args.torcs, args.keyboard_profile) if args.keyboard_profile
                     else prepare_launch_profile(args.torcs))
            if args.torcs == 'keyboard':
                (output/'keyboard_driving.json').write_bytes((local/'keyboard_driving.json').read_bytes())
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
        monitor = LoadMonitor(service, args.device == 'hardware')
        hint = ('Mock auto-arm pending fresh telemetry/interlocks.' if args.auto_arm_mock else
                'Use the Arm mock dashboard button; console disabled.' if args.no_console and args.dashboard else
                'Monitoring only: no arming source selected.' if args.no_console else
                'Type '+phrase+' in this terminal and press Enter.'+(' Or use Arm mock in the dashboard.' if args.dashboard and args.device=='mock' else ''))
        presenter = ConsoleStatus(args.status_interval_s, args.json_status, args.dashboard, hint)
        if args.no_console:
            print('Console disabled. '+('MOCK automatic arming requested.' if args.auto_arm_mock else
                'Use Arm mock in the dashboard.' if args.dashboard else 'No arming source selected; monitoring only.'), flush=True)
        started = time.perf_counter(); armed_once = False; injected_at = None

        def poll():
            nonlocal armed_once, injected, injected_at, stop_reason
            c = service.controller
            if child and child.poll() is not None and not injected:
                if child.returncode == 0: receiver.begin_shutdown()
                stop_reason = 'process_exit'
                return True
            if args.auto_arm_mock and not armed_once and c.state=='READY' and service.demands.snapshot()[0] is not None:
                service.request('arm'); armed_once = True
            if args.inject_telemetry_loss_after and not injected and time.perf_counter()-started >= args.inject_telemetry_loss_after:
                if child and child.poll() is None:
                    child.terminate(); child.wait(timeout=10); injected_at = time.perf_counter(); injected = True
            message = presenter.render(monitor, receiver.processor.state())
            if message: print(message, flush=True)
            if receiver.failed:
                if c.state=='RUNNING': service.request('stop')
                stop_reason = 'receiver_error'; return True
            if c.state=='FAULT' and args.expect_telemetry_fault:
                stop_reason = 'expected_fault'; return True
            if quit_event.is_set() or time.perf_counter()-started >= args.duration:
                stop_reason = 'operator_quit' if quit_event.is_set() else 'duration_elapsed'
                return True
            return False

        if args.dashboard:
            from live_display import LiveDisplay
            display = LiveDisplay(receiver, finished=poll, duration=args.duration+5, load_service=monitor)
            display.run()
            if stop_reason == 'startup_error': stop_reason = 'operator_quit'
        else:
            while not poll(): time.sleep(.02)
    except KeyboardInterrupt:
        stop_reason = 'operator_interrupt'
        if service: service.request('stop')
    except Exception as exc:
        runtime_error = repr(exc)
        stop_reason = 'runtime_error'
        print('Controller error: '+runtime_error, file=sys.stderr, flush=True)
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
            timing, receiver_report_error = close_receiver(receiver, output)
        if service:
            result = dict(device=args.device, instrument=report, telemetry=timing,
                          process_exit_code=child.returncode if child else None,
                          stop_reason=stop_reason, terminated_by_launcher=terminated_by_launcher,
                          deliberate_interruption=injected,
                          runtime_error=runtime_error,
                          hardware_control_selected=args.device == 'hardware',
                          hardware_commands_may_have_been_sent=bool(args.device == 'hardware' and service.controller.identity_verified),
                          hardware_input_on_acknowledged=bool(args.device == 'hardware' and service.controller.input_on_acknowledgements),
                          telemetry_report_scope='Receiver only; its hardware_commands_sent field does not describe the instrument worker',
                          independent_hardware_protection='Not implemented or verified by this software')
            telemetry_ok = bool(timing and timing['samples'] and timing['receiver_error'] is None and
                timing['statistics']['invalid']==0 and timing['statistics']['missing']==0 and
                not timing['stale_intervals'])
            process_ok = child is None or child.returncode==0 or (
                terminated_by_launcher and stop_reason in ('duration_elapsed', 'operator_quit', 'operator_interrupt'))
            result['acceptance'] = dict(telemetry='PASS' if telemetry_ok else 'FAIL',
                instruments=report.get('control_status', 'FAIL'),
                process='PASS' if process_ok else 'FAIL', full_course='NOT ASSESSED',
                normal_operation_passed=bool(report['passed'] and telemetry_ok and process_ok and not runtime_error))
            try:
                artifacts(output, service)
                if receiver_report_error: raise RuntimeError(receiver_report_error)
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
