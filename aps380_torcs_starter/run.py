"""Command-line offline profile generation."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
from battery_model import read_telemetry, process, process_auto_scaled, save_results
from ev_model import VehicleParameters
from cell_scaling import CellParameters

BASE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description='APS380 offline profile (NO hardware control)')
    parser.add_argument('--input', type=Path, default=BASE / 'data/demo_synthetic.csv')
    parser.add_argument('--config', type=Path, default=BASE / 'config.json')
    parser.add_argument('--output-dir', type=Path, default=BASE / 'output')
    parser.add_argument('--target-current-a', type=float,
                        help='Optional positive absolute-current target for a complete offline profile')
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())
        if set(config) != {'vehicle', 'cell'}:
            raise ValueError('Config requires exactly vehicle and cell sections')
        vehicle = VehicleParameters(**config['vehicle'])
        cell = CellParameters(**config['cell'])
        telemetry = read_telemetry(args.input)
        automatic = None
        if args.target_current_a is None:
            rows = process(telemetry, vehicle, cell)
        else:
            rows, automatic = process_auto_scaled(telemetry, args.target_current_a, vehicle, cell)
            cell = replace(cell, experiment_scale=automatic['scale'])
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    save_results(rows, args.output_dir / 'current_profile.csv')
    parameters = {'vehicle': asdict(vehicle), 'cell': asdict(cell)}
    if automatic is not None:
        parameters['automatic_scaling'] = automatic
    (args.output_dir / 'model_parameters.json').write_text(json.dumps(parameters, indent=2) + '\n')
    currents = [r['cell_current_command_A'] for r in rows]
    print(f"Samples: {len(rows)}; duration: {rows[-1]['time_s'] - rows[0]['time_s']:.1f} s")
    print(f'Offline current range: {min(currents):+.2f} to {max(currents):+.2f} A; '
          f"limited samples: {sum(r['command_saturated'] for r in rows)}")
    if automatic is not None:
        print(f"Automatic offline scale: {automatic['scale']:.12g}; "
              f"original absolute peak: {automatic['original_current_peak_A']:.6g} A; "
              f"scaled absolute peak: {automatic['scaled_current_peak_A']:.6g} A; "
              f"remaining clipped samples: {automatic['remaining_clipped_samples']}")
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print('CSV saved; install requirements.txt to generate plots.')
        return
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    times = [r['time_s'] for r in rows]
    axes[0].plot(times, [r['speed_mps'] * 3.6 for r in rows])
    axes[0].set_ylabel('Speed (km/h)')
    axes[1].plot(times, [r['wheel_power_W'] / 1000 for r in rows], label='Wheel demand', alpha=.7)
    axes[1].plot(times, [r['vehicle_battery_power_W'] / 1000 for r in rows], label='Battery demand')
    axes[1].set_ylabel('Vehicle power (kW)')
    axes[1].legend()
    axes[2].plot(times, [r['cell_current_unclamped_A'] for r in rows], label='Requested', alpha=.6)
    axes[2].plot(times, currents, label='Limited command')
    axes[2].axhline(cell.discharge_limit_A, color='red', linestyle=':', label='Offline limits')
    axes[2].axhline(-cell.charge_limit_A, color='red', linestyle=':')
    axes[2].set_ylabel('Cell current (A)\n+ discharge / − charge')
    axes[2].set_xlabel('Time (s)')
    axes[2].legend()
    for axis in axes:
        axis.axhline(0, color='black', linewidth=.6)
        axis.grid(alpha=.3)
    fig.suptitle(f'APS380 offline demand profile — {args.input.name}')
    fig.tight_layout()
    fig.savefig(args.output_dir / 'current_profile.png', dpi=145)
    plt.close(fig)
    print(f'CSV, configuration and plot saved in {args.output_dir}')


if __name__ == '__main__':
    main()
