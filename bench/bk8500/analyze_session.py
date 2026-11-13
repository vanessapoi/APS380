"""Offline BK8500 capture analysis. Never imports serial or opens instruments.

Only completed RUNNING CSV samples enter tracking metrics. Configured limits,
actual sampled range and whole-session acceptance are deliberately separate.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def read_csv(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def values(rows, key):
    result = np.array([float(row[key]) for row in rows])
    if not len(result) or not np.isfinite(result).all():
        raise ValueError('Missing/nonfinite samples: ' + key)
    return result


def error_metrics(error, full_scale):
    return dict(MAE_A=float(np.mean(abs(error))),
                RMSE_A=float(np.sqrt(np.mean(error**2))),
                max_abs_A=float(np.max(abs(error))),
                p95_abs_A=float(np.percentile(abs(error), 95)),
                bias_A=float(np.mean(error)),
                MAE_percent_full_scale=float(np.mean(abs(error))/full_scale*100))


def load_run(folder):
    folder = Path(folder)
    config = json.loads((folder/'config.json').read_text(encoding='utf-8-sig'))
    trial = json.loads((folder/'trial.json').read_text(encoding='utf-8-sig'))
    if config.get('device') not in ('mock', 'hardware') or trial.get('device') != config['device']:
        raise ValueError('Missing or inconsistent mock/hardware provenance')
    rows = read_csv(folder/'load_tracking.csv')
    telemetry = read_csv(folder/'telemetry/live_profile.csv')
    if len(rows) < 2:
        raise ValueError('At least two completed RUNNING samples required; tracking NOT ASSESSED')
    events = [json.loads(line) for line in (folder/'instruments/control.jsonl').read_text().splitlines()]
    complete = [e for e in events if e['event'] == 'cycle' and e['state'] == 'RUNNING'
                and e.get('last_operation') == 'complete']
    if len(complete) != len(rows):
        raise ValueError('CSV and completed RUNNING event counts differ')
    if any(e.get('mock_only') is not (config['device'] == 'mock') for e in events):
        raise ValueError('Event provenance conflicts with device selection')
    command, measured, target = [values(rows, key) for key in
        ('commanded_load_A', 'measured_A', 'power_limited_load_target_A')]
    times = values(rows, 'measurement_received_host_s')
    if np.any(np.diff(times) <= 0):
        raise ValueError('Measurement receipt times must increase')
    full_scale = config['max_current_A']
    if type(full_scale) not in (float, int) or not math.isfinite(full_scale) or full_scale <= 0:
        raise ValueError('Invalid configured full scale')
    index = {(row['session_id'], int(row['sequence'])): row for row in telemetry}
    joined = [index[(row['source_session'], int(row['source_sequence']))] for row in rows]
    if np.max(abs(values(joined, 'cell_current_unclamped_A')-values(rows, 'original_cell_current_A'))) > 1e-10:
        raise ValueError('Source-sequence join disagrees with captured demand')
    step = abs(command-values(rows, 'previous_commanded_load_A'))
    quantized = np.floor(target*10000+1e-9)/10000
    metrics = dict(label=folder.name, device=config['device'], samples=len(rows),
        full_scale_A=full_scale, observed_current_min_A=float(measured.min()),
        observed_current_max_A=float(measured.max()), observed_current_mean_A=float(measured.mean()),
        target_max_A=float(target.max()), commanded_max_A=float(command.max()),
        measured_minus_command=error_metrics(measured-command, full_scale),
        measured_minus_target=error_metrics(measured-target, full_scale),
        setting_max_error_A=float(np.max(abs(values(rows, 'readback_setting_A')-command))),
        voltage_min_V=float(values(rows, 'voltage_V').min()),
        voltage_max_V=float(values(rows, 'voltage_V').max()),
        power_max_W=float(values(rows, 'power_W').max()),
        update_hz=float((len(rows)-1)/(times[-1]-times[0])),
        mean_ACK_ms=float(values(rows, 'command_roundtrip_ms').mean()),
        max_cycle_ms=float(values(rows, 'cycle_ms').max()),
        max_source_age_s=float(values(rows, 'command_age_s').max()),
        mean_ACK_to_measured_receipt_ms=float(np.mean(times-values(rows, 'command_ack_received_host_s'))*1000),
        slew_A_per_s=config['slew_A_per_s'],
        slew_binding_percent=float(np.mean(abs(command-quantized)>1e-8)*100),
        slew_budget_violations=int(np.sum(step>values(rows, 'slew_budget_A')+1e-10)),
        current_range_violations=int(np.sum((measured<0)|(measured>full_scale))),
        voltage_violations=int(np.sum((values(rows, 'voltage_V')<config['voltage_min_V'])|
                                     (values(rows, 'voltage_V')>config['voltage_max_V']))),
        power_violations=int(np.sum((values(rows, 'power_W')<0)|
                                   (values(rows, 'power_W')>config['max_power_W']))),
        simulated_pack_soc_initial_percent=float(telemetry[0]['soc'])*100,
        simulated_pack_soc_final_percent=float(telemetry[-1]['soc'])*100,
        telemetry_statistics=trial['telemetry']['statistics'],
        stale_intervals=trial['telemetry'].get('stale_intervals', []),
        faults=trial['instrument']['faults'],
        shutdown=trial['instrument']['shutdown'], acceptance=trial['acceptance'])
    # No config approval/identity/port data is copied into reports.
    filenames = ('config.json', 'trial.json', 'load_tracking.csv',
                 'telemetry/live_profile.csv', 'instruments/control.jsonl')
    hashes = {name: hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in filenames}
    return dict(folder=folder, config=config, rows=rows, telemetry=telemetry,
                command=command, measured=measured, target=target, times=times,
                metrics=metrics, hashes=hashes)


def slew_comparison(run, rates, response_s):
    """Counterfactual only; use existing slew logic and in-memory instrument.

    Default response constant is an unvalidated model assumption, not an
    identified physical settling time. All rows are simulated even on real input.
    """
    from live_control import LiveConfig, MockLiveLoad, slew_target
    class Clock:
        t = 0.
        def __call__(self): return self.t
        def sleep(self, seconds): self.t += seconds
    rows, config = run['rows'], run['config']
    ack = values(rows, 'command_ack_received_host_s')
    origin = ack[0]
    summaries = []
    for rate in rates:
        clock = Clock()
        cfg = LiveConfig(max_current_A=config['max_current_A'],
            reference_current_A=config['reference_current_A'], max_power_W=config['max_power_W'],
            voltage_min_V=config['voltage_min_V'], voltage_max_V=config['voltage_max_V'],
            control_hz=config['control_hz'], slew_A_per_s=rate)
        device = MockLiveLoad(cfg, clock, clock.sleep, delay_s=0, response_s=response_s)
        device.input(True)  # Only an in-memory model; no transport exists.
        command, measured, previous = [], [], 0.
        for row, target in zip(rows, run['target']):
            requested, _ = slew_target(previous, float(target), cfg.max_current_A,
                                       float(row['slew_elapsed_s']), cfg)
            clock.t = float(row['command_ack_received_host_s'])-origin
            device.set_current(requested)
            clock.t = float(row['measurement_received_host_s'])-origin
            command.append(requested); measured.append(device.measure()['measured_A'])
            previous = requested
        command, measured = np.array(command), np.array(measured)
        assert device.shutdown()['verified']
        summaries.append(dict(slew_A_per_s=rate, provenance='MOCK counterfactual, not physical evidence',
            assumed_response_s=response_s, peak_command_A=float(command.max()),
            max_command_step_A=float(np.max(abs(np.diff(np.r_[0., command])))),
            mock_measured_minus_command=error_metrics(measured-command, cfg.max_current_A),
            mock_measured_minus_target=error_metrics(measured-run['target'], cfg.max_current_A)))
    return summaries


def render(runs, output, counterfactuals):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output.mkdir(parents=True, exist_ok=True)
    figures = []
    for name, mode in [('current_tracking.png', 'current'), ('driving.png', 'driving'), ('soc_availability.png', 'soc')]:
        count = 3 if mode == 'current' else 4 if mode == 'driving' else 2
        fig, axes = plt.subplots(count, len(runs), figsize=(7*len(runs), 3*count), squeeze=False)
        for col, run in enumerate(runs):
            r, t = run['rows'], run['telemetry']
            elapsed = run['times']-float(t[0]['received_qpc_s'])
            tx = values(t, 'received_qpc_s')-float(t[0]['received_qpc_s'])
            ax = axes[:, col]
            if mode == 'current':
                ax[0].plot(values(r, 'source_received_s')-float(t[0]['received_qpc_s']), values(r, 'original_cell_current_A'), label='Signed MODEL demand')
                ax[0].set_ylabel('Model cell A, charging positive')
                ax[1].plot(elapsed, run['target'], '--', label='Target before slew')
                ax[1].step(values(r, 'command_ack_received_host_s')-float(t[0]['received_qpc_s']), run['command'], where='post', label='Command at ACK')
                ax[1].plot(values(r, 'setpoint_read_received_host_s')-float(t[0]['received_qpc_s']), values(r, 'readback_setting_A'), '.', label='Setting readback')
                ax[1].plot(elapsed, run['measured'], label=run['config']['device'].upper()+' measured')
                ax[1].set_ylabel('Load branch A')
                ax[2].plot(elapsed, (run['measured']-run['command'])*1000, label='Measured - command')
                ax[2].set_ylabel('mA')
            elif mode == 'driving':
                ax[0].plot(tx, values(t, 'speed_mps')*3.6, label='Vehicle speed km/h')
                ax[1].plot(tx, values(t, 'throttle'), label='Applied throttle')
                ax[1].plot(tx, values(t, 'brake'), label='Applied brake')
                ax[2].plot(tx, values(t, 'pack_power_W')/1000, label='Simulated pack kW')
                ax[3].plot(elapsed, run['target'], label='Load target A')
                ax[3].plot(elapsed, run['measured'], label='Measured load A')
            else:
                ax[0].plot(tx, values(t, 'soc')*100, label='TORCS simulated PACK SOC %')
                ax[0].ticklabel_format(useOffset=False, axis='y')
                ax[1].text(.5, .5, 'Cell SOC / OCV / SOP / propulsion fraction\nNOT RECORDED in this standalone pipeline\nNo physical battery values inferred', ha='center', transform=ax[1].transAxes)
            ax[0].set_title(run['folder'].name+' | '+run['config']['device'].upper())
            for dest in ax:
                dest.grid(alpha=.25)
                if dest.get_legend_handles_labels()[0]: dest.legend(fontsize=8)
            ax[-1].set_xlabel('Host seconds since first telemetry receipt')
        fig.suptitle('Recorded sessions; different manual inputs are not a controlled pedal A/B test')
        fig.tight_layout(); fig.savefig(output/name, dpi=140); plt.close(fig); figures.append(name)
    metrics = [run['metrics'] for run in runs]
    (output/'metrics.json').write_text(json.dumps(dict(sessions=metrics, mock_slew_comparison=counterfactuals), indent=2, allow_nan=False)+'\n')
    report = '# Offline BK8500 session analysis\n\n'
    for m in metrics:
        report += f"## {m['label']} ({m['device']})\n\n"
        report += f"Completed samples: {m['samples']}; measured range {m['observed_current_min_A']:.4f}..{m['observed_current_max_A']:.4f} A; mean {m['observed_current_mean_A']:.6f} A. Configured cap {m['full_scale_A']} A is not proof that full scale was exercised.\n\n"
        report += '| Error | MAE mA | RMSE mA | Max absolute mA | P95 absolute mA |\n|---|---:|---:|---:|---:|\n'
        for key in ('measured_minus_command', 'measured_minus_target'):
            e = m[key]
            report += f"| {key} | {e['MAE_A']*1000:.4f} | {e['RMSE_A']*1000:.4f} | {e['max_abs_A']*1000:.4f} | {e['p95_abs_A']*1000:.4f} |\n"
        report += f"\nAcceptance: `{json.dumps(m['acceptance'])}`. Faults: `{m['faults']}`. Verified shutdown: `{m['shutdown']['verified']}`. Stale intervals: {len(m['stale_intervals'])}. These are retained as recorded, not overridden by good tracking.\n\n"
        report += f"Slew binding {m['slew_binding_percent']:.2f}% of cycles; budget violations {m['slew_budget_violations']}. Effective rate {m['update_hz']:.4f} Hz. ACK-to-measurement receipt averages {m['mean_ACK_to_measured_receipt_ms']:.2f} ms, including queries/wait: not hardware settling time. No independent ADC timestamps or subsecond response identification.\n\n"
    report += '## Interpretation and provenance\n\nOnly matching completed RUNNING events are assessed. Source telemetry is joined by session and sequence; target, ACK and measurement receipt times remain distinct. Stopped or partial-cycle readings are not substituted for shutdown evidence. SOC is simulated PACK SOC only; no battery SOC, OCV, SOP or propulsion fraction is invented. Mock current is never treated as physical measurement. Different manual trajectories cannot establish a causal throttle-profile effect.\n\n'
    if counterfactuals:
        report += '## Optional slew counterfactuals\n\nThe existing in-memory response model is an unvalidated assumption. Faster rates are not physical evidence or permission to change approvals. Results compare all captured samples, not whether a real controller would avoid a persistent tracking fault.\n\n| Slew A/s | Assumed response s | MOCK command MAE mA | MOCK target MAE mA | Max step mA |\n|---:|---:|---:|---:|---:|\n'
        for r in counterfactuals:
            report += f"| {r['slew_A_per_s']} | {r['assumed_response_s']} | {r['mock_measured_minus_command']['MAE_A']*1000:.4f} | {r['mock_measured_minus_target']['MAE_A']*1000:.4f} | {r['max_command_step_A']*1000:.4f} |\n"
    report += '\n'+''.join(f'![{name}]({name})\n\n' for name in figures)
    (output/'REPORT.md').write_text(report, encoding='utf-8')
    hashes = {run['folder'].name: run['hashes'] for run in runs}
    (output/'source_hashes.json').write_text(json.dumps(hashes, indent=2)+'\n')
    for run in runs:
        assert all(hashlib.sha256((run['folder']/name).read_bytes()).hexdigest() == digest for name, digest in run['hashes'].items())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--slew-rates', type=float, nargs='+')
    parser.add_argument('--mock-response-s', type=float, default=.04)
    args = parser.parse_args(argv)
    run = load_run(args.run_dir)
    runs = [load_run(args.compare), run] if args.compare else [run]
    if len({r['config']['device'] for r in runs}) != 1:
        parser.error('Keep hardware comparisons separate from mock sessions')
    output = args.output or args.run_dir/'analysis_offline'
    if any(output.resolve() == r['folder'].resolve() for r in runs):
        parser.error('Use a separate analysis output folder')
    if not math.isfinite(args.mock_response_s) or args.mock_response_s <= 0:
        parser.error('Mock response must be finite and positive')
    simulated = slew_comparison(run, args.slew_rates, args.mock_response_s) if args.slew_rates else []
    render(runs, output, simulated)
    print('Offline analysis saved:', output/'REPORT.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
