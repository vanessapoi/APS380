"""Audit the first G29 recording and preserve a screened, contiguous segment."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from battery_model import read_telemetry, process, save_results
from cell_scaling import CellParameters
from compare_profiles import metrics
from ev_model import VehicleParameters

BASE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=BASE/'data/g29_20261020_200536.csv')
    parser.add_argument('--output-dir', type=Path, default=BASE/'output/g29_screening')
    args = parser.parse_args()
    source = read_telemetry(args.input)
    config = json.loads((BASE/'config_torcs.json').read_text())
    vehicle, cell = VehicleParameters(**config['vehicle']), CellParameters(**config['cell'])
    full = process(source, vehicle, cell)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    # Manual screening of this recording; preserve every sample in this interval.
    indices = [i for i, row in enumerate(source) if 44.6 <= row['time_s'] <= 53.6]
    if len(indices) < 2:
        raise ValueError('Recording does not contain the documented screening interval')
    first, last = indices[0], indices[-1]
    selected = source[first:last+1]
    segment_path = out/'screened_segment.csv'
    # Copy the CSV strings, preserving the original numeric precision and times.
    with args.input.open(newline='') as stream:
        reader = csv.DictReader(stream)
        fields, original = reader.fieldnames, list(reader)
    with segment_path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(original[first:last+1])
    if read_telemetry(segment_path) != selected:
        raise ValueError('Extracted segment differs from source')
    screened = process(selected, vehicle, cell)
    save_results(screened, out/'current_profile.csv')
    (out/'model_parameters.json').write_text(json.dumps(config, indent=2)+'\n')

    # Group adjacent intervals exceeding a diagnostic threshold. This is not
    # a vehicle-specific plausibility limit or proof of collision/reset events.
    groups = []
    for i in range(1, len(full)):
        if abs(full[i]['accel_mps2']) > 20:
            if groups and groups[-1][-1] == i-1:
                groups[-1].append(i)
            else:
                groups.append([i])
    events = []
    for group in groups:
        peak = max(group, key=lambda i: abs(full[i]['accel_mps2']))
        row = full[peak]
        events.append({'start_time_s': full[group[0]-1]['time_s'],
                       'end_time_s': full[group[-1]]['time_s'],
                       'intervals': len(group), 'peak_source_csv_row': peak+2,
                       **{key: row[key] for key in ('time_s', 'accel_mps2', 'speed_mps', 'throttle', 'brake')},
                       'previous_speed_mps': full[peak-1]['speed_mps']})
    if events:
        save_results(events, out/'flagged_events.csv')
    summary = [{'case': name, 'samples': len(rows), **metrics(rows)}
               for name, rows in [('full_recording', full), ('screened_segment', screened)]]
    save_results(summary, out/'comparison.csv')
    audit = {
        'source': args.input.name,
        'source_sha256': hashlib.sha256(args.input.read_bytes()).hexdigest(),
        'source_first_csv_row': first+2, 'source_last_csv_row': last+2,
        'start_time_s': selected[0]['time_s'], 'end_time_s': selected[-1]['time_s'],
        'selection': 'Manual review: lower-speed acceleration, brief near-steady driving, braking to rest.',
        'transformations': 'None: contiguous original samples, original times, no smoothing or interpolation.',
        'diagnostic_threshold_abs_acceleration_mps2': 20,
        'flagged_event_groups': len(events),
        'limitations': [
            'Four columns cannot establish collision/reset causes or rule them out in the selected segment.',
            'Near-steady driving is brief; this is not a controlled cruise test.',
            'TORCS total speed includes lateral/vertical motion; the model assumes longitudinal motion.',
            'Selected braking still reaches about -15 m/s^2 and is not validated against a target EV.',
            'Model limits and regenerative recovery are illustrative offline assumptions.'
        ]}
    (out/'audit.json').write_text(json.dumps(audit, indent=2)+'\n')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(5, 1, figsize=(12, 12))
    axes[0].plot([r['time_s'] for r in full], [r['speed_mps']*3.6 for r in full])
    axes[0].axvspan(selected[0]['time_s'], selected[-1]['time_s'], color='green', alpha=.25)
    axes[0].set_ylabel('Full speed (km/h)')
    axes[0].set_xlabel('Original simulation time (s); shaded = selected interval')
    times = [r['time_s'] for r in screened]
    axes[1].plot(times, [r['speed_mps']*3.6 for r in screened])
    axes[1].set_ylabel('Selected speed (km/h)')
    for field in ('throttle', 'brake'):
        axes[2].plot(times, [r[field] for r in screened], label=field)
    axes[2].set_ylabel('Control command')
    axes[3].plot(times, [r['accel_mps2'] for r in screened])
    axes[3].set_ylabel('Acceleration (m/s²)')
    for field, label in [('cell_current_unclamped_A', 'Requested'), ('cell_current_command_A', 'Limited')]:
        axes[4].plot(times, [r[field] for r in screened], label=label)
    axes[4].axhline(cell.discharge_limit_A, color='red', linestyle=':')
    axes[4].axhline(-cell.charge_limit_A, color='red', linestyle=':')
    axes[4].set_ylabel('Cell current (A)')
    axes[4].set_xlabel('Original simulation time (s)')
    axes[2].legend()
    axes[4].legend()
    for ax in axes:
        ax.grid(alpha=.3)
    fig.suptitle('G29 screened segment — unchanged data; offline model')
    fig.tight_layout()
    fig.savefig(out/'screening.png', dpi=145)
    plt.close(fig)
    print(json.dumps({'audit': audit, 'comparison': summary}, indent=2))


if __name__ == '__main__':
    main()
