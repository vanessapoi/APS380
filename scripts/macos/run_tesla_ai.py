#!/usr/bin/env python3
"""Run the existing Model 3 reference/AI protocol on the native Mac build.

Default: bounded console run with saved telemetry and existing protocol checks.
--visible: open the isolated AI profile; choose Race > Practice to start.
--monitor opens the simulation-only live dashboard alongside the visible race.
No instrument connection is made.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from configure_tesla import PROFILE, configure
from run_tesla_ai import prepare_profile, validate_protocol, plot_protocol

WORK = ROOT / '.local/torcs-macos'



def monitor(command, env, runtime, out, duration):
    from torcs_live import LiveReceiver
    from live_display import LiveDisplay
    receiver = LiveReceiver(0, out/'live')
    if not receiver.processor.shared_clock:
        receiver.socket.close()
        receiver.log.close()
        raise RuntimeError('Native/Python clock agreement was not verified')
    receiver.start()
    live_env = dict(env, APS380_LIVE_PORT=str(receiver.port), APS380_LIVE_REALTIME='0')
    child = None
    try:
        with (out/'torcs.log').open('w') as log:
            child = subprocess.Popen(command,cwd=runtime,env=live_env,stdout=log,stderr=subprocess.STDOUT)
            display = LiveDisplay(receiver,lambda: child.poll() is not None,duration)
            width = display.root.winfo_screenwidth()
            height = display.root.winfo_screenheight()
            pane = max(600, min(800, width//2))
            display.root.geometry(f'{pane}x{min(850,height-70)}+{max(0,width-pane)}+30')
            display.values.config(wraplength=pane-40,font=('Menlo',10))
            display.details.config(wraplength=pane-40)
            print(f'Dashboard listening on 127.0.0.1:{receiver.port}; choose Race > Practice > New Race.',flush=True)
            display.run()
    finally:
        receiver.begin_shutdown()
        try:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill();child.wait(timeout=5)
        finally:
            report = receiver.close()
            print('Live report:',out/'live/timing_report.json',flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--visible', action='store_true')
    parser.add_argument('--monitor', action='store_true', help='Visible race plus current-demand dashboard; no hardware')
    parser.add_argument('--duration', type=float, default=1800, help='Monitor wall-clock limit in seconds')
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args()
    if args.monitor:
        args.visible = True
    if not 1 <= args.duration <= 3600:
        parser.error('--duration must be 1 to 3600 seconds')
    if platform.system() != 'Darwin':
        parser.error('This launcher is for macOS')
    if not 1 <= args.timeout <= 600:
        parser.error('--timeout must be between 1 and 600 seconds')
    prefix = WORK / 'install'
    runtime = prefix / 'share/games/torcs'
    binary = prefix / 'lib/torcs/torcs-bin'
    driver = prefix / 'lib/torcs/drivers/aps380_ai/aps380_ai.so'
    if not binary.exists() or not driver.exists():
        parser.error('Build and install the native simulator first')
    template = WORK / 'user'
    template.mkdir(parents=True, exist_ok=True)
    subprocess.run(['/bin/bash', str(prefix / 'lib/torcs/setup_linux.sh'), str(template)], cwd=runtime, check=True)
    local = WORK / 'tesla-ai-profile'
    manual = configure(runtime=runtime, local=WORK/'tesla-manual-profile', existing=template)
    prepare_profile(local, runtime=runtime, manual_profile=manual, driver_binary=driver)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    out = WORK / 'ai-runs' / stamp
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, DYLD_LIBRARY_PATH=str(prefix/'lib/torcs/lib'),
               APS380_AI_LOG=str(out/'driver.csv'), MPLCONFIGDIR=str(WORK/'matplotlib'))
    env.pop('APS380_LIVE_PORT', None)
    env.pop('APS380_LIVE_REALTIME', None)
    # Linux/Mac entry point takes an explicit local profile; it does not read
    # the Windows-only APS380_TORCS_PROFILE environment variable.
    env.pop('APS380_TORCS_PROFILE', None)
    if args.visible and not env.get('DISPLAY'):
        env['DISPLAY'] = subprocess.check_output(['launchctl','getenv','DISPLAY'], text=True).strip() or ':0'
    command = [str(binary), '-l', str(local), '-L', str(prefix/'lib/torcs'), '-D', str(runtime)]
    metadata = dict(mode='visible_monitor' if args.monitor else 'visible' if args.visible else 'console',
                    profile_sha256=hashlib.sha256(PROFILE.read_bytes()).hexdigest(),
                    driver_sha256=hashlib.sha256(driver.read_bytes()).hexdigest(),
                    simulator_sha256=hashlib.sha256((prefix/'lib/torcs/modules/simu/simuv2.so').read_bytes()).hexdigest(),
                    instruments_connected_by_software=False,
                    limitations='Reduced-order Tesla reference with proxy body; no independent Tesla calibration. Live telemetry is enabled only with --monitor; physical hardware remains disabled.')
    (out/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    shutil.copy2(PROFILE, out/'vehicle_profile.json')
    print('Artifacts:', out, flush=True)
    if args.monitor:
        monitor(command,env,runtime,out,args.duration)
        return
    if args.visible:
        print('AI profile ready. Choose Race > Practice and start the race.', flush=True)
        os.chdir(runtime)
        os.execve(str(binary), command, env)
    before = set((runtime/'telemetry').glob('aps380_ev_*.csv'))
    command += ['-r', str(local/'race.xml')]
    with (out/'torcs.log').open('w') as log:
        result = subprocess.run(command,cwd=runtime,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=args.timeout)
    new = set((runtime/'telemetry').glob('aps380_ev_*.csv')) - before
    if result.returncode or len(new) != 1:
        raise RuntimeError('Race failed or missing unique telemetry; see '+str(out/'torcs.log'))
    source = new.pop()
    shutil.copy2(source,out/'drive.csv')
    shutil.copy2(source.with_suffix('.xml'),out/'drive.xml')
    summary = validate_protocol(out/'drive.csv',out/'vehicle_profile.json',out/'driver.csv')
    (out/'protocol.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    if not summary['passed']:
        raise SystemExit('Course did not pass every protocol gate; evidence preserved above')
    plot_protocol(out)
    print('PASS: autonomous course completed and existing protocol gates passed.',flush=True)


if __name__ == '__main__':
    main()
