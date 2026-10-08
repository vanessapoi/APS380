"""Reproducible offline modelling/conditioning/scaling comparison."""
import argparse
from dataclasses import replace, asdict
import json
import math
from pathlib import Path
from battery_model import read_telemetry, process, save_results
from ev_model import VehicleParameters
from cell_scaling import CellParameters
from telemetry_conditioning import smooth_speed

BASE = Path(__file__).resolve().parent


def metrics(rows):
    duration = sum(r['interval_s'] for r in rows)
    return {
        'duration_s': duration,
        'min_accel_mps2': min(r['accel_mps2'] for r in rows),
        'max_accel_mps2': max(r['accel_mps2'] for r in rows),
        'peak_vehicle_power_kW': max(r['vehicle_battery_power_W'] for r in rows)/1000,
        'peak_raw_current_A': max(r['cell_current_unclamped_A'] for r in rows),
        'min_raw_current_A': min(r['cell_current_unclamped_A'] for r in rows),
        'limited_samples_percent': 100*sum(r['command_saturated'] for r in rows)/len(rows),
        'limited_time_percent': 100*sum(r['interval_s']*r['command_saturated'] for r in rows)/duration if duration else 0,
        'command_rms_A': math.sqrt(sum(r['cell_current_command_A']**2*r['interval_s'] for r in rows)/duration) if duration else 0,
        **{f'{kind}_{direction}_Wh': sum(max(sign*r[field],0)*r['interval_s']/3600 for r in rows)
           for kind,field in [('requested','cell_power_requested_W'),('command','cell_power_command_W')]
           for direction,sign in [('discharge',1),('charge',-1)]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window-s', type=float, default=.2)
    parser.add_argument('--experiment-scale', type=float, default=.2)
    parser.add_argument('--output-dir', type=Path, default=BASE/'output/torcs_comparison')
    args = parser.parse_args()
    baseline = json.loads((BASE/'config.json').read_text())
    candidate = json.loads((BASE/'config_torcs.json').read_text())
    vehicle = VehicleParameters(**candidate['vehicle'])
    cell = CellParameters(**candidate['cell'])
    cases = [('baseline_raw', VehicleParameters(**baseline['vehicle']), CellParameters(**baseline['cell']), 0),
             ('candidate_raw', vehicle, cell, 0),
             ('candidate_smoothed', vehicle, cell, args.window_s),
             ('candidate_smoothed_scaled', vehicle, replace(cell, experiment_scale=args.experiment_scale), args.window_s)]
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    summary = []
    paths = sorted((BASE/'data/torcs_normalized').glob('segment_*.csv'))
    if not paths:
        parser.error('Run torcs_adapter.py first')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        raw = read_telemetry(path)
        fig, axes = plt.subplots(4, 1, figsize=(12, 11), sharex=True)
        for name, v, c, window in cases:
            processed = process(smooth_speed(raw, window), v, c)
            out = args.output_dir/path.stem/name
            save_results(processed, out/'current_profile.csv')
            (out/'parameters.json').write_text(json.dumps({'vehicle':asdict(v), 'cell':asdict(c), 'smoothing_window_s':window},indent=2)+'\n')
            summary.append({'segment':path.stem,'case':name,**metrics(processed)})
            for ax, field, factor in zip(axes, ['speed_mps','accel_mps2','vehicle_battery_power_W','cell_current_command_A'],[3.6,1,.001,1]):
                ax.plot([r['time_s'] for r in processed], [r[field]*factor for r in processed], label=name, alpha=.75)
        for ax,label in zip(axes,['Speed (km/h)','Acceleration (m/s²)','Battery demand (kW)','Limited current (A)']):
            ax.set_ylabel(label)
            ax.grid(alpha=.3)
        axes[0].legend(fontsize=8)
        axes[-1].axhline(cell.discharge_limit_A,color='black',linestyle=':')
        axes[-1].axhline(-cell.charge_limit_A,color='black',linestyle=':')
        axes[-1].set_xlabel('Recorded lap time (s)')
        fig.suptitle(f'{path.stem}: illustrative EV equivalents; offline limits')
        fig.tight_layout()
        fig.savefig(args.output_dir/f'{path.stem}_comparison.png',dpi=145)
        plt.close(fig)
    save_results(summary,args.output_dir/'summary.csv')
    print(f'Wrote {len(summary)} comparisons and three plots to {args.output_dir}')


if __name__ == '__main__':
    main()
