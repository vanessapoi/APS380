"""Process native EV telemetry; never infer regenerative energy from speed loss."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent
NUMERIC = ('time_s', 'speed_mps', 'throttle', 'brake', 'longitudinal_mps',
           'lateral_mps', 'vertical_mps', 'damage', 'collision', 'motor_radps',
           'motor_torque_Nm', 'motor_power_W', 'pack_power_W', 'pack_voltage_V',
           'pack_current_A', 'soc', 'pack_energy_Wh', 'discharge_Wh', 'charge_Wh')


def verify_configuration(path, profile):
    """Verify the effective car parameters saved by the running simulator."""
    root = ET.parse(path).getroot()
    p, r, u = profile['published'], profile['reference_choices'], profile['unvalidated']
    checks = {('Car', 'mass'): r['curb_mass_kg']+r['driver_mass_kg']-.001,
              ('Rear Differential', 'ratio'): p['reduction_ratio'],
              ('Electric Powertrain', 'max torque Nm'): p['motor_max_torque_Nm'],
              ('Electric Powertrain', 'max power W'): p['motor_max_power_W'],
              ('Electric Powertrain', 'nominal voltage V'): p['pack_nominal_voltage_V'],
              ('Electric Powertrain', 'capacity Wh'): u['capacity_Wh'],
              ('Electric Powertrain', 'drive efficiency'): u['drive_efficiency'],
              ('Electric Powertrain', 'regen efficiency'): u['regen_efficiency'],
              ('Electric Powertrain', 'max regen shaft power W'): u['max_regen_shaft_power_W'],
              ('Electric Powertrain', 'lift off torque Nm'): u['lift_off_torque_Nm'],
              ('Electric Powertrain', 'auxiliary power W'): u['auxiliary_power_W']}
    for (section, name), expected in checks.items():
        item = root.find(f"section[@name='{section}']/attnum[@name='{name}']")
        if item is None or not math.isclose(float(item.get('val')), expected, rel_tol=1e-6, abs_tol=.001):
            raise ValueError(f'Effective simulator configuration mismatch: {section}/{name}')


def read_ev(path, profile_path):
    profile_bytes = Path(profile_path).read_bytes()
    profile = json.loads(profile_bytes)
    identity = profile['id']+'-'+hashlib.sha256(profile_bytes).hexdigest()[:12]
    with Path(path).open(newline='') as stream:
        reader = csv.DictReader(stream)
        required = set(NUMERIC) | {'profile_id', 'car_id'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Native EV telemetry required; legacy four-column CSVs cannot identify pack energy')
        rows = []
        for line, raw in enumerate(reader, 2):
            if raw['profile_id'] != identity or raw['car_id'] != profile['car_id']:
                raise ValueError(f'Car/profile mismatch at CSV row {line}')
            row = {key: float(raw[key]) for key in NUMERIC}
            if not all(math.isfinite(v) for v in row.values()):
                raise ValueError(f'Nonfinite value at CSV row {line}')
            if not 0 <= row['soc'] <= 1 or not 0 <= row['throttle'] <= 1 or not 0 <= row['brake'] <= 1:
                raise ValueError(f'SOC/pedal range error at CSV row {line}')
            if row['time_s'] < 0 or row['speed_mps'] < 0 or row['pack_voltage_V'] <= 0:
                raise ValueError(f'Invalid time/speed/voltage at CSV row {line}')
            p, u = profile['published'], profile['unvalidated']
            checks = [
                (row['pack_power_W'], row['pack_current_A']*row['pack_voltage_V'], .01),
                (row['pack_voltage_V'], p['pack_nominal_voltage_V'], .001),
                (row['pack_energy_Wh'], row['soc']*u['capacity_Wh'], .001),
                (row['motor_power_W'], row['motor_radps']*row['motor_torque_Nm'], .1)]
            if any(abs(a-b) > tol for a, b, tol in checks):
                raise ValueError(f'EV power/energy consistency error at CSV row {line}')
            if rows and row['time_s'] <= rows[-1]['time_s']:
                raise ValueError(f'Non-increasing simulation time at CSV row {line}')
            if rows:
                prev = rows[-1]
                if row['discharge_Wh'] < prev['discharge_Wh'] or row['charge_Wh'] < prev['charge_Wh']:
                    raise ValueError(f'Energy counters reset at CSV row {line}')
                used = row['discharge_Wh']-prev['discharge_Wh']-(row['charge_Wh']-prev['charge_Wh'])
                if abs(prev['pack_energy_Wh']-row['pack_energy_Wh']-used) > .00001:
                    raise ValueError(f'Battery energy not conserved at CSV row {line}')
            rows.append(row)
    if len(rows) < 2:
        raise ValueError('Need at least two EV samples')
    return profile, rows


def process_ev(rows):
    out = []
    for i, row in enumerate(rows):
        prev = rows[i-1] if i else row
        dt = row['time_s']-prev['time_s']
        accel = (row['longitudinal_mps']-prev['longitudinal_mps'])/dt if dt else 0
        # Energy differences capture all physics substeps between CSV samples.
        mean_power = ((row['discharge_Wh']-prev['discharge_Wh']) -
                      (row['charge_Wh']-prev['charge_Wh']))*3600/dt if dt else row['pack_power_W']
        out.append({**row, 'interval_s': dt, 'accel_mps2': accel,
                    'interval_pack_power_W': mean_power,
                    'impact_flag': int(row['collision'] != 0 or row['damage'] > prev['damage']),
                    'lateral_motion_flag': int(abs(row['lateral_mps']) > 1),
                    'speed_jump_flag': int(abs(accel) > 15)})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--profile', type=Path, default=BASE/'profiles/tesla_model3_rwd.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        profile, rows = read_ev(args.input, args.profile)
        verify_configuration(args.input.with_suffix('.xml'), profile)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        parser.error(str(exc))
    result = process_ev(rows)
    from battery_model import save_results
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    save_results(result, out/'pack_profile.csv')
    (out/'vehicle_profile.json').write_bytes(args.profile.read_bytes())
    (out/'effective_car.xml').write_bytes(args.input.with_suffix('.xml').read_bytes())
    summary = {
        'vehicle': profile['name'], 'status': profile['status'],
        'source_sha256': hashlib.sha256(args.input.read_bytes()).hexdigest(),
        'samples': len(rows), 'duration_s': rows[-1]['time_s']-rows[0]['time_s'],
        'discharge_Wh': rows[-1]['discharge_Wh']-rows[0]['discharge_Wh'],
        'recovered_Wh': rows[-1]['charge_Wh']-rows[0]['charge_Wh'],
        'current_min_A': min(r['pack_current_A'] for r in rows),
        'current_max_A': max(r['pack_current_A'] for r in rows),
        'impact_samples': sum(r['impact_flag'] for r in result),
        'speed_jump_samples': sum(r['speed_jump_flag'] for r in result),
        'lateral_motion_samples': sum(r['lateral_motion_flag'] for r in result),
        'energy_method': 'Native physics-step pack-energy counters; not speed-differenced regeneration',
        'current_method': 'Pack power / constant nominal pack voltage; no 18650 scaling or clipping',
        'unvalidated_parameters': profile['unvalidated'], 'limitations': profile['limitations']}
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    t = [r['time_s'] for r in rows]
    fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True)
    for ax, key, scale, label in zip(axes, ['longitudinal_mps', 'pack_power_W', 'pack_current_A', 'soc'],
                                    [3.6, .001, 1, 100], ['Speed (km/h)', 'Pack power (kW)', 'Pack current (A)', 'SOC (%)']):
        ax.plot(t, [r[key]*scale for r in rows])
        ax.set_ylabel(label)
        ax.grid(alpha=.3)
    axes[-1].set_xlabel('Simulation time (s)')
    fig.suptitle(profile['name']+'\nReduced-order reference; calibration pending')
    fig.tight_layout()
    fig.savefig(out/'pack_profile.png', dpi=145)
    plt.close(fig)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
