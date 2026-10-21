"""Reproducible internal validation and parameter sensitivity of a native EV drive.

This does not fit a simulator to its own generated pack measurements or claim
external vehicle calibration. Frozen source data and settings are preserved.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from battery_model import save_results
from run_ev import BASE, process_ev, read_ev, verify_configuration


def contiguous_intervals(rows, predicate):
    """Return runs of qualifying intervals, assigning each to its end sample."""
    groups = []
    for i in range(1, len(rows)):
        if predicate(rows[i]):
            if groups and groups[-1][-1] == i-1:
                groups[-1].append(i)
            else:
                groups.append([i])
    return groups


def phase(row):
    if row['time_s'] < .1:
        return 'startup'
    if abs(row['longitudinal_mps']) < .5:
        return 'near_stop'
    if row['brake'] > .05:
        return 'brake_pedal_active'
    if row['motor_power_W'] < -100:
        return 'regenerative_liftoff'
    if abs(row['accel_mps2']) <= .15 and row['longitudinal_mps'] >= 5:
        return 'near_steady'
    if row['accel_mps2'] > .15:
        return 'acceleration'
    return 'other_transient'


def phase_summary(rows):
    groups = []
    for i in range(1, len(rows)):
        label = phase(rows[i])
        if groups and groups[-1][0] == label:
            groups[-1][1].append(i)
        else:
            groups.append((label, [i]))
    result = []
    for label, indices in groups:
        a, b = rows[indices[0]-1], rows[indices[-1]]
        result.append({'phase': label, 'start_s': a['time_s'], 'end_s': b['time_s'],
                       'duration_s': b['time_s']-a['time_s'],
                       'start_speed_kmh': a['longitudinal_mps']*3.6,
                       'end_speed_kmh': b['longitudinal_mps']*3.6,
                       'discharge_Wh': b['discharge_Wh']-a['discharge_Wh'],
                       'recovered_Wh': b['charge_Wh']-a['charge_Wh']})
    return result


def replay_electrical(rows, drive_efficiency, regen_efficiency, auxiliary_power_W,
                      capacity_Wh, voltage_V):
    """Conditional electrical replay of a fixed shaft-work trace, no physics rerun.

    Trapezoidal integration is an approximation to native substep counters.
    Capacity changes only SOC here. No temperature/voltage/BMS map is inferred.
    """
    powers = [(r['motor_power_W']/drive_efficiency if r['motor_power_W'] >= 0
               else r['motor_power_W']*regen_efficiency)+auxiliary_power_W for r in rows]
    used, recovered = 0., 0.
    for i in range(1, len(rows)):
        dt = rows[i]['time_s']-rows[i-1]['time_s']
        used += (max(powers[i-1], 0)+max(powers[i], 0))*.5*dt/3600
        recovered += (max(-powers[i-1], 0)+max(-powers[i], 0))*.5*dt/3600
    return {'discharge_Wh': used, 'recovered_Wh': recovered, 'net_Wh': used-recovered,
            'soc_drop_percentage_points': (used-recovered)/capacity_Wh*100,
            'peak_discharge_current_A': max(powers)/voltage_V,
            'peak_charge_current_A': min(powers)/voltage_V}


def audit_drive(profile, rows):
    p, r, u = profile['published'], profile['reference_choices'], profile['unvalidated']
    radius = r['rim_in']*.0254/2 + r['tire_width_mm']*.001*r['tire_aspect_percent']/100
    clean = [x for x in rows if x['longitudinal_mps'] > 5 and abs(x['lateral_mps']) < .2]
    ratios = [x['motor_radps']*radius/(p['reduction_ratio']*x['longitudinal_mps']) for x in clean]
    steady = contiguous_intervals(rows, lambda x: x['time_s'] >= .1 and x['longitudinal_mps'] >= 5
                                 and abs(x['accel_mps2']) <= .15 and not x['impact_flag'])
    longest = max((sum(rows[i]['interval_s'] for i in group) for group in steady), default=0.)
    closure = max(abs((a['pack_energy_Wh']-b['pack_energy_Wh'])-
                      ((b['discharge_Wh']-a['discharge_Wh'])-(b['charge_Wh']-a['charge_Wh'])))
                  for a, b in zip(rows, rows[1:]))
    power_residual = max(abs(x['pack_power_W'] -
                             ((x['motor_power_W']/u['drive_efficiency'] if x['motor_power_W'] >= 0
                               else x['motor_power_W']*u['regen_efficiency'])+u['auxiliary_power_W']))
                         for x in rows)
    motor_power_overshoot = max(max(x['motor_power_W'], 0)-p['motor_max_power_W'] for x in rows)
    regen_overshoot = max(max(-x['motor_power_W'], 0)-u['max_regen_shaft_power_W'] for x in rows)
    torque_overshoot = max(abs(x['motor_torque_Nm'])-p['motor_max_torque_Nm'] for x in rows)
    return {
        'status': 'internal_verification_complete_external_calibration_pending',
        'samples': len(rows), 'duration_s': rows[-1]['time_s']-rows[0]['time_s'],
        'energy_closure_max_error_Wh': closure,
        'electrical_equation_max_residual_W': power_residual,
        'motor_power_cap_overshoot_W': max(0., motor_power_overshoot),
        'regeneration_cap_overshoot_W': max(0., regen_overshoot),
        'motor_torque_cap_overshoot_Nm': max(0., torque_overshoot),
        'nominal_unloaded_tire_radius_m': radius,
        'motor_to_nominal_rolling_speed_ratio_median': statistics.median(ratios) if ratios else None,
        'kinematic_ratio_sample_count': len(ratios),
        'kinematic_interpretation': 'A diagnostic for gearing/radius mismatch. Tire deformation, slip and time staggering prevent exact equality; not a calibrated loaded radius.',
        'longest_near_steady_interval_s': longest,
        'near_steady_definition': 'Speed >=5 m/s, |dv_longitudinal/dt|<=0.15 m/s^2, no impact, after 0.1 s startup; contiguous unsmoothed intervals.',
        'startup_contact_samples': sum(x['impact_flag'] for x in rows if x['time_s'] < .1),
        'post_startup_contact_samples': sum(x['impact_flag'] for x in rows if x['time_s'] >= .1),
        'damage_end': rows[-1]['damage'],
        'lateral_motion_samples': sum(x['lateral_motion_flag'] for x in rows),
        'speed_jump_samples': sum(x['speed_jump_flag'] for x in rows),
        'internal_checks_pass': closure <= .00001 and power_residual < .1 and
                                motor_power_overshoot < 1 and regen_overshoot < 1 and torque_overshoot < .01,
        'steady_state_test_ready': longest >= 10,
        'real_vehicle_calibration_ready': False,
        'external_calibration_blockers': [
            'No independent real-car speed/pack power/voltage measurements for this exact year, trim and motor.',
            'No verified usable capacity or efficiency/regen maps for this exact configuration.',
            'Simulation-generated SOC and pack power reproduce configured equations; fitting them cannot validate those assumptions.',
            'The drive contains no qualifying 10-second near-steady interval.' if longest < 10 else
            'Near-steady driving exists, but a matched real-car reference remains necessary.',
            'Elevation/grade and wheel-level forces are absent from this recording; road load cannot be uniquely identified.'
        ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=BASE/'data/tesla_drive_04/drive.csv')
    parser.add_argument('--profile', type=Path, default=BASE/'data/tesla_drive_04/vehicle_profile.json')
    parser.add_argument('--output-dir', type=Path, default=BASE/'output/tesla_drive_04_validation')
    args = parser.parse_args()
    profile, raw = read_ev(args.input, args.profile)
    verify_configuration(args.input.with_suffix('.xml'), profile)
    rows = process_ev(raw)
    audit = audit_drive(profile, rows)
    audit['source_sha256'] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    audit['profile_sha256'] = hashlib.sha256(args.profile.read_bytes()).hexdigest()
    audit['analysis_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out/'audit.json').write_text(json.dumps(audit, indent=2)+'\n')
    phases = phase_summary(rows)
    save_results(phases, out/'phases.csv')
    u, p = profile['unvalidated'], profile['published']
    baseline = {'drive_efficiency': u['drive_efficiency'], 'regen_efficiency': u['regen_efficiency'],
                'auxiliary_power_W': u['auxiliary_power_W'], 'capacity_Wh': u['capacity_Wh'],
                'voltage_V': p['pack_nominal_voltage_V']}
    cases = [('configured_replay', baseline)]
    # Deliberately declared scenarios, not measured uncertainty intervals.
    for key, values in [('drive_efficiency', (.85, .97)), ('regen_efficiency', (.65, .95)),
                        ('auxiliary_power_W', (0, 1000)), ('capacity_Wh', (45000, 55000)),
                        ('voltage_V', (330, 380))]:
        for value in values:
            cases.append((f'{key}={value}', {**baseline, key: value}))
    sensitivity = [{'case': name, **parameters, **replay_electrical(rows, **parameters)}
                   for name, parameters in cases]
    save_results(sensitivity, out/'parameter_sensitivity.csv')
    native_net = rows[-1]['discharge_Wh']-rows[0]['discharge_Wh']-(rows[-1]['charge_Wh']-rows[0]['charge_Wh'])
    audit['sampled_replay_minus_native_net_Wh'] = sensitivity[0]['net_Wh']-native_net
    (out/'audit.json').write_text(json.dumps(audit, indent=2)+'\n')
    report = f'''# Tesla drive 04: verification and calibration readiness

The recording passes the implemented profile and energy checks. It does not
establish real-Tesla accuracy. No physical parameters were fitted or changed.

- Samples: {len(rows)}; duration: {audit['duration_s']:.2f} s.
- Native net pack energy: {native_net:.3f} Wh.
- Maximum interval energy closure error: {audit['energy_closure_max_error_Wh']:.3g} Wh.
- Maximum configured electrical-equation residual: {audit['electrical_equation_max_residual_W']:.3g} W.
- Post-startup contact samples: {audit['post_startup_contact_samples']}; final damage: {audit['damage_end']:.0f}.
- Longest near-steady interval: {audit['longest_near_steady_interval_s']:.2f} s; target: 10 s.
- Median motor speed / nominal rolling-speed ratio: {audit['motor_to_nominal_rolling_speed_ratio_median']:.4f}.

## What is established

The saved simulator configuration matches this recording's profile. Torque and
power obey the configured caps. Pack current, power, energy counters and SOC
are internally consistent. Gearing and nominal tire dimensions produce a
reasonable speed ratio; its departure from 1 may include tire slip/deformation.
It is not an independently measured effective rolling radius.

## What remains uncalibrated

'''+''.join(f'- {item}\n' for item in audit['external_calibration_blockers'])+'''
## Sensitivity interpretation

`parameter_sensitivity.csv` holds one-at-a-time scenarios for efficiency,
auxiliaries, nominal voltage and assumed working capacity. These are chosen
stress-test values, not measured bounds or confidence intervals. They replay
the same sampled shaft-work trace, without rerunning vehicle physics or BMS
limits. The difference between configured replay and native energy counters
is reported in `audit.json` to expose sampling approximation.

Changing capacity affects SOC change, not consumed energy in this replay;
changing nominal voltage affects current, not consumed energy. Mass, tire,
road-load, regeneration-control and power-limit changes require new simulator
runs. Do not select a parameter merely because its output looks smoother.

## Next controlled simulator protocol

On a straight, accelerate gently to 30 km/h, hold speed for at least 10 s,
release the accelerator and coast under the current lift-off control, then
brake to rest. Repeat at 50 km/h where track conditions allow. Start from a
known SOC, avoid impacts, and record the same scenario for comparison.
This supports simulator repeatability; physical calibration additionally needs
matched independent real-car or laboratory measurements and track grade.

The previous description of this recording as clean remains correct for
impact/speed-jump screening; it was not evidence of a sustained cruise phase
or of externally validated Tesla behavior.
'''
    (out/'report.md').write_text(report, encoding='utf-8')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    t = [r['time_s'] for r in rows]
    axes[0].plot(t, [r['longitudinal_mps']*3.6 for r in rows], label='Recorded longitudinal speed')
    axes[0].set_ylabel('Speed (km/h)')
    axes[0].set_xlabel('Simulation time (s)')
    axes[1].plot(t, [r['throttle'] for r in rows], label='Throttle')
    axes[1].plot(t, [r['brake'] for r in rows], label='Brake')
    axes[1].set_ylabel('Command')
    axes[1].set_xlabel('Simulation time (s)')
    labels = [x['case'] for x in sensitivity]
    values = [x['net_Wh'] for x in sensitivity]
    axes[2].barh(labels, values)
    axes[2].axvline(native_net, color='red', linestyle=':', label='Native counter total')
    axes[2].set_xlabel('Net pack energy (Wh); conditional scenarios, not measured uncertainty')
    for ax in axes:
        ax.grid(alpha=.3)
        ax.legend(fontsize=8)
    fig.suptitle('Tesla reference: internal verification and sensitivity\nExternal vehicle calibration pending')
    fig.tight_layout()
    fig.savefig(out/'validation.png', dpi=145)
    plt.close(fig)
    print(json.dumps(audit, indent=2))
    if not audit['internal_checks_pass']:
        raise SystemExit('Internal model verification failed; inspect audit.json')


if __name__ == '__main__':
    main()
