"""Build and run the autonomous TORCS validation course without a GUI."""
import argparse
import csv
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from configure_tesla import ROOT, TORCS, RUNTIME, PROFILE, configure, section, attribute, write

PYTHON_PROJECT = ROOT/'aps380_torcs_starter'
sys.path.insert(0, str(PYTHON_PROJECT))
from run_ev import read_ev, process_ev, verify_configuration
from validate_ev_drive import audit_drive


def longest_interval(rows, predicate):
    current = best = 0.
    for previous, row in zip(rows, rows[1:]):
        dt = row['time_s']-previous['time_s']
        if dt <= 0:
            raise ValueError('Protocol timestamps must increase')
        if dt <= .05+1e-9 and predicate(row):
            current += dt
            best = max(best, current)
        else:
            current = 0.
    return best


def validate_protocol(raw_path, profile_path, driver_path):
    profile, raw = read_ev(raw_path, profile_path)
    verify_configuration(raw_path.with_suffix('.xml'), profile)
    native = process_ev(raw)
    with driver_path.open(newline='') as stream:
        driver = [{k: v if k == 'stage' else float(v) for k, v in row.items()}
                  for row in csv.DictReader(stream)]
    if len(driver) < 2:
        raise ValueError('Driver log is empty or incomplete')
    # Commands are held until the next robot callback; use the most recent one.
    joined, j = [], 0
    for row in native:
        while j+1 < len(driver) and driver[j+1]['time_s'] <= row['time_s']+1e-6:
            j += 1
        if driver[j]['time_s'] <= row['time_s']+1e-6:
            joined.append({**row, 'stage': driver[j]['stage'],
                           'target_mps': driver[j]['target_mps'],
                           'straight_remaining_m': driver[j]['straight_remaining_m']})
    holds = {}
    for label, target in [('hold_30', 30/3.6), ('hold_50', 50/3.6)]:
        holds[label+'_seconds'] = longest_interval(joined, lambda x: x['stage'] == label and
            abs(x['longitudinal_mps']-target) <= .2 and abs(x['accel_mps2']) <= .15 and
            abs(x['lateral_mps']) < .3 and x['straight_remaining_m'] > 20 and not x['impact_flag'])
    lift = [x for x in joined if x['stage'] == 'liftoff']
    friction = [x for x in joined if x['stage'] == 'friction_stop' and x['brake'] > .05]
    stationary = longest_interval(joined, lambda x: x['stage'] == 'stop_hold' and abs(x['longitudinal_mps']) <= .15)
    audit = audit_drive(profile, native)
    distance = driver[-1]['distance_m']-driver[0]['distance_m']
    checks = {
        'hold_30_at_least_10_seconds': holds['hold_30_seconds'] >= 10,
        'hold_50_at_least_10_seconds': holds['hold_50_seconds'] >= 10,
        'lift_off_without_brake_recovers_energy': bool(lift) and all(x['brake'] <= .001 for x in lift) and
             min(x['pack_power_W'] for x in lift) < -1000,
        'friction_braking_isolated_from_regeneration': bool(friction) and
             sum(abs(x['motor_power_W']) < 100 for x in friction)/len(friction) >= .95,
        'stopped_at_least_5_seconds': stationary >= 5,
        'course_completed': distance >= driver[0]['track_length_m'],
        'no_post_startup_contacts': audit['post_startup_contact_samples'] == 0,
        'no_damage': native[-1]['damage'] == 0,
        'no_speed_jumps': audit['speed_jump_samples'] == 0,
        'internal_model_consistency': audit['internal_checks_pass'],
        'protocol_completed': driver[-1]['stage'] == 'lap_follow'}
    result = {'passed': all(checks.values()), 'checks': checks, **holds,
              'stopped_seconds': stationary, 'distance_m': distance,
              'duration_s': audit['duration_s'],
              'max_abs_lane_offset_m': max(abs(x['to_middle_m']) for x in driver),
              'net_pack_Wh': native[-1]['discharge_Wh']-native[0]['discharge_Wh']-
                  (native[-1]['charge_Wh']-native[0]['charge_Wh']),
              'external_tesla_calibration': 'pending_independent_reference_data',
              'steady_definition': 'Contiguous native samples, speed within 0.2 m/s of target, abs acceleration <=0.15 m/s², lateral speed <0.3 m/s, straight road remaining >20 m, no contact.'}
    return result


def build(project, log):
    msbuild = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))/'Microsoft Visual Studio/2022/Community/MSBuild/Current/Bin/MSBuild.exe'
    if not msbuild.exists():
        raise FileNotFoundError('Visual Studio 2022 MSBuild is required')
    command = [str(msbuild), str(project), '/p:Configuration=Release', '/p:Platform=x64',
               '/p:BuildProjectReferences=false', f'/p:SolutionDir={TORCS}\\', '/verbosity:minimal', '/nologo']
    with log.open('w') as stream:
        outcome = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    if outcome.returncode:
        raise RuntimeError(f'Build failed; see {log}')


def plot_protocol(out):
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'.local/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    with (out/'driver.csv').open(newline='') as stream:
        driver = [{k: v if k == 'stage' else float(v) for k, v in row.items()}
                  for row in csv.DictReader(stream)]
    _, native = read_ev(out/'drive.csv', out/'vehicle_profile.json')
    end = next((r['time_s']+10 for r in driver if r['stage'] == 'lap_follow'), driver[-1]['time_s'])
    selected = [r for r in driver if r['time_s'] <= end]
    actual = [r for r in native if r['time_s'] <= end]
    t = [r['time_s'] for r in selected]
    nt = [r['time_s'] for r in actual]
    fig, axes = plt.subplots(5, 1, figsize=(12, 12), sharex=True)
    axes[0].plot(nt, [r['longitudinal_mps']*3.6 for r in actual], label='Actual')
    axes[0].plot(t, [r['target_mps']*3.6 for r in selected], '--', label='Target')
    axes[0].set_ylabel('Speed (km/h)')
    errors = [(r['speed_mps']-r['target_mps'])*3.6 if r['stage'] in ('hold_30', 'hold_50') else float('nan') for r in selected]
    axes[1].plot(t, errors, label='Error during requested holds')
    axes[1].axhline(.72, color='red', linestyle=':')
    axes[1].axhline(-.72, color='red', linestyle=':')
    axes[1].set_ylabel('Speed error (km/h)')
    for field in ('throttle', 'brake'):
        axes[2].plot(t, [r[field] for r in selected], label=field)
    axes[2].set_ylabel('Control command')
    axes[3].plot(nt, [r['pack_power_W']/1000 for r in actual], label='Native pack power')
    axes[3].set_ylabel('Pack power (kW)')
    axes[4].plot(t, [r['to_middle_m'] for r in selected], label='Lane-center offset')
    axes[4].set_ylabel('Offset (m)')
    axes[4].set_xlabel('Simulation time (s); protocol excerpt, two-lap course continues afterward')
    for ax in axes:
        ax.grid(alpha=.3)
        ax.legend(fontsize=8)
    fig.suptitle('Autonomous EV validation: speed holds, lift-off, friction stop\nInternal simulator validation; external Tesla calibration pending')
    fig.tight_layout()
    fig.savefig(out/'protocol.png', dpi=145)
    plt.close(fig)


def prepare_profile(destination, runtime=RUNTIME, manual_profile=None, driver_binary=None):
    # Preserve the manual G29 profile; race and robot settings are isolated.
    manual_profile = Path(manual_profile) if manual_profile is not None else configure()
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(manual_profile/'config', destination/'config', dirs_exist_ok=True)
    robot = ET.Element('params', name='aps380_ai', type='robotdef')
    entry = section(section(section(robot, 'Robots'), 'index'), '1')
    for name, value in [('name', 'APS380 validation driver'), ('car name', 'aps380-model3-rwd'),
                        ('type', 'robot'), ('skill level', 'pro')]:
        attribute(entry, name, value)
    write(robot, destination/'drivers/aps380_ai/aps380_ai.xml')
    write(robot, runtime/'drivers/aps380_ai/aps380_ai.xml')
    if driver_binary is None:
        shutil.copy2(TORCS/'src/drivers/aps380_ai/Release/aps380_ai.dll', runtime/'drivers/aps380_ai/aps380_ai.dll')
    else:
        driver_binary = Path(driver_binary)
        target = runtime/'drivers/aps380_ai'/driver_binary.name
        if driver_binary.resolve() != target.resolve():
            shutil.copy2(driver_binary, target)
    race = ET.parse(manual_profile/'config/raceman/practice.xml').getroot()
    for name in ('Drivers', 'Drivers Start List'):
        group = section(race, name)
        for child in list(group):
            if child.tag == 'section':
                group.remove(child)
        entry = section(group, '1')
        attribute(entry, 'module', 'aps380_ai')
        attribute(entry, 'idx', 1)
    attribute(section(race, 'Drivers'), 'focused module', 'aps380_ai')
    track = section(section(race, 'Tracks'), '1')
    attribute(track, 'name', 'g-track-1')
    attribute(track, 'category', 'road')
    practice = section(race, 'Practice')
    attribute(practice, 'laps', 2)
    attribute(practice, 'distance', 0, 'km')
    attribute(practice, 'display mode', 'results only')
    write(race, destination/'race.xml')
    visible = copy.deepcopy(race)
    attribute(section(visible, 'Practice'), 'display mode', 'normal')
    write(visible, destination/'config/raceman/practice.xml')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=2)
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        parser.error('--runs must be 1 through 10')
    batch = PYTHON_PROJECT/'output/tesla_ai_validation'/datetime.now().strftime('%Y%m%d_%H%M%S')
    batch.mkdir(parents=True, exist_ok=False)
    if not args.skip_build:
        print('Building electric simulator and validation driver...', flush=True)
        build(TORCS/'src/modules/simu/simuv2/simuv2.vcxproj', batch/'simulator_build.log')
        build(TORCS/'src/drivers/aps380_ai/aps380_ai.vcxproj', batch/'driver_build.log')
    local = ROOT/'.local/tesla-ai-profile'
    prepare_profile(local)
    results = []
    for number in range(1, args.runs+1):
        out = batch/f'run_{number:02d}'
        out.mkdir()
        before = set((RUNTIME/'telemetry').glob('aps380_ev_*.csv'))
        env = {**os.environ, 'APS380_TORCS_PROFILE': str(local),
               'APS380_AI_LOG': str(out/'driver.csv'), 'MPLCONFIGDIR': str(ROOT/'.local/matplotlib')}
        print(f'Running autonomous course {number}/{args.runs}...', flush=True)
        with (out/'torcs.log').open('w') as log:
            outcome = subprocess.run([str(RUNTIME/'wtorcs.exe'), '-r', str(local/'race.xml')],
                                     cwd=RUNTIME, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=60)
        new = set((RUNTIME/'telemetry').glob('aps380_ev_*.csv'))-before
        if len(new) != 1:
            raise RuntimeError(f'Expected one fresh telemetry file, got {len(new)}; see {out}')
        source = new.pop()
        shutil.copy2(source, out/'drive.csv')
        shutil.copy2(source.with_suffix('.xml'), out/'drive.xml')
        shutil.copy2(PROFILE, out/'vehicle_profile.json')
        if outcome.returncode:
            raise RuntimeError(f'Autonomous race failed ({outcome.returncode}); see {out}/torcs.log')
        summary = validate_protocol(out/'drive.csv', out/'vehicle_profile.json', out/'driver.csv')
        (out/'protocol.json').write_text(json.dumps(summary, indent=2)+'\n')
        for script, subdir in [('run_ev.py', 'analysis'), ('validate_ev_drive.py', 'validation')]:
            with (out/(script+'.log')).open('w') as log:
                subprocess.run([sys.executable, str(PYTHON_PROJECT/script), '--input', str(out/'drive.csv'),
                                '--profile', str(out/'vehicle_profile.json'), '--output-dir', str(out/subdir)],
                               cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        results.append(summary)
        plot_protocol(out)
        print(json.dumps(summary, indent=2), flush=True)
        if not summary['passed']:
            raise RuntimeError(f'Protocol did not pass all gates; see {out}/protocol.json')
    net = [result['net_pack_Wh'] for result in results]
    repeatability = (max(net)-min(net))/max(abs(sum(net)/len(net)), 1e-9)*100 if len(net) >= 2 else None
    batch_result = {'all_passed': all(r['passed'] for r in results), 'runs': results,
                    'net_energy_spread_percent': repeatability,
                    'repeatability_within_1_percent': repeatability <= 1 if repeatability is not None else None,
                    'profile_sha256': hashlib.sha256(PROFILE.read_bytes()).hexdigest(),
                    'driver_sha256': hashlib.sha256((TORCS/'src/drivers/aps380_ai/aps380_ai.cpp').read_bytes()).hexdigest(),
                    'driver_dll_sha256': hashlib.sha256((RUNTIME/'drivers/aps380_ai/aps380_ai.dll').read_bytes()).hexdigest(),
                    'simulator_dll_sha256': hashlib.sha256((RUNTIME/'modules/simu/simuv2.dll').read_bytes()).hexdigest(),
                    'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (batch/'summary.json').write_text(json.dumps(batch_result, indent=2)+'\n')
    report = '# Automated EV course validation\n\n'
    report += 'Two speed holds, lift-off regeneration, isolated friction braking, a stationary hold, and a complete course are checked from recorded native telemetry.\n\n'
    report += '| Run | 30 km/h hold | 50 km/h hold | Stopped | Net pack energy | Gates |\n| --- | --- | --- | --- | --- | --- |\n'
    for i, result in enumerate(results, 1):
        report += f"| {i} | {result['hold_30_seconds']:.2f} s | {result['hold_50_seconds']:.2f} s | {result['stopped_seconds']:.2f} s | {result['net_pack_Wh']:.3f} Wh | {'Pass' if result['passed'] else 'Fail'} |\n"
    report += f'\nNet-energy spread: {repeatability}% across {len(results)} run(s); at least two runs are needed to assess repeatability.\n\n'
    report += 'Each run folder contains the raw native CSV, effective car XML, frozen vehicle profile, driver trace, protocol gates, detailed plot, pack analysis, and readiness audit. Source and binary hashes are in summary.json.\n\n'
    report += 'The driver is a deterministic centerline follower with feedback speed control, not a racing optimizer. A hold requires contiguous native samples within ±0.2 m/s of target, |acceleration| ≤0.15 m/s², lateral speed <0.3 m/s and at least 20 m of straight road remaining. Sample gaps over 50 ms break a hold. Damage and departures from the road abort the run.\n\n'
    report += 'These are internally verified results for the configured model. Battery efficiency, capacity, regeneration and handling assumptions remain unvalidated against an independent real Tesla.\n'
    (batch/'report.md').write_text(report, encoding='utf-8')
    print(f'Artifacts: {batch}\nNet-energy spread: {repeatability}% (requires at least two runs)', flush=True)
    if repeatability is not None and repeatability > 1:
        raise SystemExit('Repeatability gate failed')


if __name__ == '__main__':
    main()
