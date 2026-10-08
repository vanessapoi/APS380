"""Offline window sensitivity and raw-signal braking diagnostics."""
import csv
import hashlib
import json
from dataclasses import replace, asdict
from pathlib import Path
from battery_model import read_telemetry, process, save_results
from ev_model import VehicleParameters
from cell_scaling import CellParameters
from telemetry_conditioning import smooth_speed
from compare_profiles import metrics

BASE = Path(__file__).resolve().parent
WINDOWS = (0., .1, .2, .5)


def fidelity(raw, conditioned):
    """Time-weighted speed error and timing of the strongest deceleration."""
    duration = sum(r['interval_s'] for r in raw)
    raw_event = min(raw[1:], key=lambda r: r['accel_mps2'])
    event = min(conditioned[1:], key=lambda r: r['accel_mps2'])
    local = min((r for r in conditioned[1:] if abs(r['time_s']-raw_event['time_s']) <= 1.5), key=lambda r:r['accel_mps2'])
    return {'local_decel_peak_shift_s': local['time_s']-raw_event['time_s'],
            'speed_rms_error_mps': (sum((a['speed_mps']-b['speed_mps'])**2*a['interval_s']
            for a,b in zip(raw,conditioned))/duration)**.5,
            'max_speed_error_mps': max(abs(a['speed_mps']-b['speed_mps']) for a,b in zip(raw,conditioned)),
            'strongest_decel_time_s': event['time_s'],
            'strongest_decel_time_shift_s': event['time_s']-raw_event['time_s']}


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    config = json.loads((BASE/'config_torcs.json').read_text())
    vehicle = VehicleParameters(**config['vehicle'])
    cell = replace(CellParameters(**config['cell']), experiment_scale=.2)
    inspection = json.loads((BASE/'data/torcs_normalized/inspection.json').read_text())
    source_path = BASE/'data/Torcs_Sample_Data.csv'
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != inspection['source_sha256']:
        raise ValueError('Source changed: regenerate the adapter audit before analysis')
    with source_path.open(newline='') as stream:
        source = list(csv.DictReader(stream))
    out = BASE/'output/torcs_analysis'
    out.mkdir(parents=True,exist_ok=True)
    summary, events = [], []
    for segment in inspection['segments']:
        path = BASE/'data/torcs_normalized'/segment['normalized_csv']
        raw = read_telemetry(path)
        if len(raw) != segment['source_last_row']-segment['source_first_row']+1:
            raise ValueError('Segment row mapping is not contiguous')
        original_slice = source[segment['source_first_row']-2:segment['source_last_row']-1]
        for normalized, original in zip(raw,original_slice):
            if normalized['time_s'] != float(original['curLapTime']) or normalized['speed_mps'] != float(original['speedX'])/3.6:
                raise ValueError('Normalized segment differs from source; regenerate adapter output')
        baseline = process(raw,vehicle,cell)
        results = {window: process(smooth_speed(raw,window),vehicle,cell) for window in WINDOWS}
        base_metrics = metrics(baseline)
        for window, rows in results.items():
            m = metrics(rows)
            summary.append({'segment':path.stem, 'window_s':window, **m, **fidelity(baseline,rows),
                **{f'{direction}_energy_change_percent': 100*(m[f'requested_{direction}_Wh']/base_metrics[f'requested_{direction}_Wh']-1)
                   if base_metrics[f'requested_{direction}_Wh'] else 0 for direction in ('discharge','charge')}})
        # One strongest deceleration per segment; exact row mapping from adapter audit.
        index = min(range(1,len(baseline)),key=lambda i:baseline[i]['accel_mps2'])
        source_index = segment['source_first_row']-2+index
        event = source[source_index]
        events.append({'segment':path.stem,'source_row':source_index+2,
                       'time_s':baseline[index]['time_s'],'accel_mps2':baseline[index]['accel_mps2'],
                       **{key:float(event[key]) for key in ('speedX','speedY','brake','accel','steer','angle','trackPos','damage')}})
        center = baseline[index]['time_s']
        selected = [i for i,r in enumerate(raw) if abs(r['time_s']-center)<=1.5]
        fig, axes = plt.subplots(4,1,figsize=(11,10),sharex=True)
        for window,rows in results.items():
            for ax,field in zip(axes[:2],('speed_mps','accel_mps2')):
                ax.plot([rows[i]['time_s'] for i in selected],[rows[i][field] for i in selected],label=f'{window:g} s')
        originals = [source[segment['source_first_row']-2+i] for i in selected]
        t = [raw[i]['time_s'] for i in selected]
        for key in ('brake','accel','steer'):
            axes[2].plot(t,[float(r[key]) for r in originals],label=key)
        axes[3].plot(t,[float(r['speedY'])/3.6 for r in originals],label='Lateral speed (m/s)')
        for ax,label in zip(axes,('Longitudinal speed (m/s)','Acceleration (m/s²)','Pedal / steering command','Lateral speed (m/s)')):
            ax.set_ylabel(label)
            ax.axvline(center,color='black',linestyle=':',linewidth=.8)
            ax.legend(fontsize=8)
            ax.grid(alpha=.3)
        axes[-1].set_xlabel('Recorded lap time (s)')
        fig.suptitle(f'{path.stem}: strongest raw deceleration — source row {source_index+2}')
        fig.tight_layout()
        fig.savefig(out/f'{path.stem}_braking.png',dpi=145)
        plt.close(fig)
    save_results(summary,out/'window_sensitivity.csv')
    save_results(events,out/'braking_events.csv')
    (out/'parameters.json').write_text(json.dumps({'vehicle':asdict(vehicle),'cell':asdict(cell),
        'windows_s':WINDOWS,'source_sha256':inspection['source_sha256'],
        'event_selection':'strongest raw deceleration in each segment; ±1.5 s plots'},indent=2)+'\n')
    print(f'Wrote sensitivity metrics and three braking plots to {out}')


if __name__ == '__main__':
    main()
