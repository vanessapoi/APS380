"""Process native EV telemetry; never infer regenerative energy from speed loss."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from numerical_validation import DEFAULT_TIMING, field_number, finite_number

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
    if 'neutral_pedal' in u:
        checks[('Electric Powertrain', 'neutral pedal')] = u['neutral_pedal']
    for (section, name), expected in checks.items():
        item = root.find(f"section[@name='{section}']/attnum[@name='{name}']")
        finite_number(f'Expected {section}/{name}', expected)
        if item is None or not math.isclose(field_number(f'{section}/{name}', item.get('val')), expected, rel_tol=1e-6, abs_tol=.001):
            raise ValueError(f'Effective simulator configuration mismatch: {section}/{name}')


def numeric_ev_row(raw):
    """Validate CSV or direct-call numeric data before any derived arithmetic."""
    try:
        row = {key: field_number(key, raw[key]) for key in NUMERIC}
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f'Invalid native EV numeric data: {error}') from error
    if not 0 <= row['soc'] <= 1 or not 0 <= row['throttle'] <= 1 or not 0 <= row['brake'] <= 1:
        raise ValueError('SOC/pedal range error')
    if row['time_s'] < 0 or row['speed_mps'] < 0 or row['pack_voltage_V'] <= 0:
        raise ValueError('Invalid time/speed/voltage')
    return row


def read_ev(path, profile_path, *, timing=DEFAULT_TIMING):
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
            row = numeric_ev_row(raw)
            p, u = profile['published'], profile['unvalidated']
            finite_number('profile nominal voltage', p['pack_nominal_voltage_V'])
            finite_number('profile capacity', u['capacity_Wh'])
            checks = [
                (row['pack_power_W'], finite_number('V*I power', row['pack_current_A']*row['pack_voltage_V']), .01),
                (row['pack_voltage_V'], p['pack_nominal_voltage_V'], .001),
                (row['pack_energy_Wh'], finite_number('SOC*capacity energy', row['soc']*u['capacity_Wh']), .001),
                (row['motor_power_W'], finite_number('shaft power', row['motor_radps']*row['motor_torque_Nm']), .1)]
            if any(abs(finite_number('consistency residual', a-b)) > tol for a, b, tol in checks):
                raise ValueError(f'EV power/energy consistency error at CSV row {line}')
            if rows:
                prev = rows[-1]
                timing.interval(prev['time_s'], row['time_s'])
                if row['discharge_Wh'] < prev['discharge_Wh'] or row['charge_Wh'] < prev['charge_Wh']:
                    raise ValueError(f'Energy counters reset at CSV row {line}')
                used = interval_net_energy(prev, row)
                change = finite_number('pack energy change', prev['pack_energy_Wh']-row['pack_energy_Wh'])
                if abs(finite_number('energy closure residual', change-used)) > .00001:
                    raise ValueError(f'Battery energy not conserved at CSV row {line}')
            rows.append(row)
    if len(rows) < 2:
        raise ValueError('Need at least two EV samples')
    return profile, rows


def interval_net_energy(previous, row):
    discharge = finite_number('discharge energy change', row['discharge_Wh']-previous['discharge_Wh'])
    charge = finite_number('charge energy change', row['charge_Wh']-previous['charge_Wh'])
    return finite_number('net interval energy', discharge-charge)


def process_ev(rows, *, timing=DEFAULT_TIMING):
    """Calculate finite native intervals, optionally enforcing acquisition bounds."""
    out = []
    prev = None
    for raw in rows:
        numeric = numeric_ev_row(raw)
        row = {**raw, **numeric}
        dt = timing.interval(prev['time_s'], row['time_s']) if prev is not None else 0.0
        speed_change = finite_number('longitudinal speed change', row['longitudinal_mps']-prev['longitudinal_mps']) if prev is not None else 0.0
        accel = finite_number('native interval acceleration', speed_change/dt if dt else 0)
        # Energy differences capture all physics substeps between CSV samples.
        energy_Ws = finite_number('interval energy in watt-seconds', interval_net_energy(prev, row)*3600) if prev is not None else 0.0
        mean_power = finite_number('interval pack power', energy_Ws/dt if dt else row['pack_power_W'])
        out.append({**row, 'interval_s': dt, 'accel_mps2': accel,
                    'interval_pack_power_W': mean_power,
                    'impact_flag': int(row['collision'] != 0 or (prev is not None and row['damage'] > prev['damage'])),
                    'lateral_motion_flag': int(abs(row['lateral_mps']) > 1),
                    'speed_jump_flag': int(abs(accel) > 15)})
        prev = row
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
        result = process_ev(rows)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        parser.error(str(exc))
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
