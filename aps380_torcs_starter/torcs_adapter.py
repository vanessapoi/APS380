"""Adapt raw SCR telemetry without altering its clock or joining laps/sessions."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from battery_model import validate_telemetry, save_results

BASE = Path(__file__).resolve().parent
SOURCE_URL = 'https://raw.githubusercontent.com/CognitiaAI/TORCS-Self-Driving-Agent/master/Torcs_Sample_Data.csv'
REQUIRED = ('curLapTime', 'speedX', 'accel', 'brake')


def adapt_rows(raw_rows, max_gap_s=0.03):
    """Return independently processable segments and an explicit audit report.

    A gap threshold is a policy, not an invented sample period. Negative time
    and reverse speed are excluded, never clamped; every exclusion breaks the
    derivative chain. Optional diagnostics help identify lap/session boundaries.
    """
    if not math.isfinite(max_gap_s) or max_gap_s <= 0:
        raise ValueError('max_gap_s must be finite and positive')
    segments, current, source_rows = [], [], []
    report = {'max_gap_s': max_gap_s, 'excluded_rows': [], 'boundaries': [],
              'segments': [], 'source_samples': 0, 'tracks': [],
              'units': {'curLapTime': 's', 'speedX': 'km/h', 'accel': '0–1 pedal', 'brake': '0–1 pedal'}}
    tracks, positive_dt = set(), []
    previous = None

    def finish():
        if current:
            segments.append(validate_telemetry(current))
            report['segments'].append({'segment': len(segments), 'samples': len(current),
                'source_first_row': source_rows[0], 'source_last_row': source_rows[-1],
                'start_time_s': current[0]['time_s'], 'end_time_s': current[-1]['time_s'],
                'duration_s': current[-1]['time_s']-current[0]['time_s']})
            current.clear()
            source_rows.clear()

    for row_number, row in enumerate(raw_rows, 2):
        report['source_samples'] += 1
        try:
            values = {key: float(row[key]) for key in REQUIRED}
            for key in ('distRaced', 'distFromStart', 'lastLapTime'):
                if key in row:
                    values[key] = float(row[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f'Invalid TORCS numeric data at source row {row_number}') from exc
        if not all(math.isfinite(x) for x in values.values()):
            raise ValueError(f'Nonfinite TORCS data at source row {row_number}')
        if not 0 <= values['accel'] <= 1 or not 0 <= values['brake'] <= 1:
            raise ValueError(f'Invalid TORCS pedals at source row {row_number}')
        track = row.get('trackName')
        if track is not None:
            tracks.add(track)
        reasons = []
        if previous is not None:
            prev, prev_track = previous
            dt = values['curLapTime'] - prev['curLapTime']
            if dt > 0:
                positive_dt.append(dt)
            if dt <= 0:
                reasons.append('lap_clock_reset' if dt < 0 else 'duplicate_timestamp')
            elif dt > max_gap_s:
                reasons.append('timestamp_gap')
            if track != prev_track:
                reasons.append('track_change')
            if 'distRaced' in values and values['distRaced'] < prev['distRaced']:
                reasons.append('race_distance_decrease')
            if reasons:
                finish()
                report['boundaries'].append({'source_row': row_number, 'reasons': reasons,
                    'clock_delta_s': dt, 'previous': prev, 'current': values})
        previous = (values, track)
        invalid = []
        if values['curLapTime'] < 0:
            invalid.append('negative_time')
        if values['speedX'] < 0:
            invalid.append('negative_longitudinal_speed')
        if invalid:
            finish()
            report['excluded_rows'].append({'source_row': row_number, 'reasons': invalid})
            continue
        current.append({'time_s': values['curLapTime'], 'speed_mps': values['speedX']/3.6,
                        'throttle': values['accel'], 'brake': values['brake']})
        source_rows.append(row_number)
    finish()
    if not report['source_samples']:
        raise ValueError('Empty TORCS recording')
    report['tracks'] = sorted(tracks)
    report['positive_clock_interval_counts'] = {
        str(dt): sum(round(x, 6) == dt for x in positive_dt)
        for dt in sorted({round(x, 6) for x in positive_dt})}
    report['retained_samples'] = sum(len(segment) for segment in segments)
    return segments, report


def adapt_file(path, output_dir, max_gap_s=0.03):
    with open(path, newline='') as stream:
        reader = csv.DictReader(stream)
        if not set(REQUIRED).issubset(reader.fieldnames or []):
            raise ValueError(f'Expected TORCS columns: {REQUIRED}')
        segments, report = adapt_rows(reader, max_gap_s)
    report['source_path'] = str(Path(path).resolve())
    report['source_sha256'] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for number, segment in enumerate(segments, 1):
        name = f'segment_{number:02d}.csv'
        save_results(segment, out/name)
        report['segments'][number-1]['normalized_csv'] = name
    (out/'inspection.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=BASE/'data/Torcs_Sample_Data.csv')
    parser.add_argument('--output-dir', type=Path, default=BASE/'data/torcs_normalized')
    parser.add_argument('--max-gap-s', type=float, default=0.03)
    args = parser.parse_args()
    try:
        report = adapt_file(args.input, args.output_dir, args.max_gap_s)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Source: {report['source_samples']} samples; retained: {report['retained_samples']}; "
          f"excluded: {len(report['excluded_rows'])}; segments: {len(report['segments'])}")
    print(f'Normalized CSVs and inspection.json saved in {args.output_dir}')


if __name__ == '__main__':
    main()
