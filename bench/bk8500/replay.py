"""Standalone PSU-to-eLoad bench replay. Default is offline preparation only."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import time
from datetime import datetime

from instrument import BK8500

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / 'aps380_torcs_starter/output/torcs_comparison/segment_03/candidate_smoothed_scaled/current_profile.csv'
LEGACY_SHA256 = '72b672386e012384293a9d9c0c2df7b776d64a0c6c2d174f4066b1c53b0d1c76'
SYNTHETIC = [0, .02, .05, .10, .06, .06, .03, 0, .08, 0]


def prepare_torcs(source, convention=None):
    """Rectify discharge before one-second ZOH time averaging; fixed peak gain.

    CSV alone cannot reveal its current sign. Only the historical capture's
    exact hash has an implicit convention; other files require an explicit one.
    """
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if convention is None:
        if digest != LEGACY_SHA256:
            raise ValueError('Specify --source-sign for this CSV; do not infer sign from its filename')
        convention = 'discharge-positive'
    with source.open(newline='') as f:
        rows = list(csv.DictReader(f))
    values = [(float(r['time_s']), float(r['cell_current_unclamped_A'])) for r in rows]
    if len(values) < 2 or not all(math.isfinite(x) for v in values for x in v):
        raise ValueError('Need at least two finite timestamp/current samples')
    gaps = [b[0] - a[0] for a, b in zip(values, values[1:])]
    if values[0][0] < 0 or min(gaps) <= 0 or max(gaps) > .03:
        raise ValueError('Negative time, reset, duplicate or >30 ms gap; select one continuous segment')
    if convention not in ('charging-positive', 'discharge-positive'):
        raise ValueError('Unknown current sign convention')
    # Convert at this boundary only. Internal source current is discharge-positive.
    sign = -1 if convention == 'charging-positive' else 1
    values = [(t, i * sign) for t, i in values]
    t0 = values[0][0]
    duration = values[-1][0] - t0
    if duration > 60:
        raise ValueError('First bench replays are limited to 60 seconds')
    bins = []
    for n in range(math.ceil(duration)):
        start = t0 + n
        end = min(start + 1, values[-1][0])
        width = end - start
        signed = positive = negative_duration = 0.
        for (t, i), (next_t, _) in zip(values, values[1:]):
            overlap = max(0., min(end, next_t) - max(start, t))
            signed += i * overlap
            positive += max(0., i) * overlap
            if i < 0:
                negative_duration += overlap
        bins.append(dict(step=n, scheduled_s=float(n), duration_s=width,
                         source_start_s=start, source_end_s=end,
                         source_discharge_positive_signed_mean_A=signed / width,
                         source_discharge_mean_A=positive / width,
                         regen_fraction=negative_duration / width))
    peak = max(b['source_discharge_mean_A'] for b in bins)
    gain = .1 / peak if peak else 0.
    for b in bins:
        b['requested_A'] = round(min(.1, b['source_discharge_mean_A'] * gain) * 10000) / 10000
    try:
        source_name = source.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        source_name = str(source.resolve())
    metadata = dict(source_csv=source_name, source_sha256=digest,
                    source_current_convention=convention,
                    internal_source_convention='discharge-positive',
                    commanded_quantity='nonnegative eLoad branch current; not net cell current',
                    source_samples=len(rows), duration_s=duration,
                    maximum_source_gap_s=max(gaps), bench_gain=gain,
                    peak_limit_A=.1, quantization_A=.0001,
                    averaging='Rectify negative discharge demand to zero, then time-average source ZOH over one-second bins; retain final partial bin. No session stitching or time compression.',
                    limitations='Offline smoothed model with assumed parameters. Not live TORCS, physical regeneration, battery feedback or validated cell scaling.')
    params = source.with_name('parameters.json')
    if params.exists():
        metadata['source_parameters'] = json.loads(params.read_text())
    return bins, metadata


def write_csv(path, rows):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def check_measurement(m, expected_on, target=None):
    if (m['input_on'] != expected_on or not 4.5 <= m['voltage_V'] <= 5.5
            or m['status'] & 31 or not 0 <= m['measured_A'] <= .15
            or not 0 <= m['power_W'] <= 1):
        raise RuntimeError('Measurement outside bench bounds: ' + str(m))
    if target is not None and abs(m['measured_A'] - target) > .01:
        raise RuntimeError('Reported current differs from request by >10 mA')


def run_profile(device, bins, folder, clock=time.monotonic, sleep=time.sleep):
    outcome = {'completed': False, 'samples': 0}
    measurements = []
    try:
        identity = device.identify()
        outcome['identity'] = identity
        if identity['model'] != '8500':
            raise RuntimeError('Expected original BK 8500; no settings changed')
        try:
            device.remote()
            device.input(False)
            before = device.measure()
            check_measurement(before, False)
            outcome['before'] = before
            device.fixed_cc()
            device.set_current(0)
            if device.current_setting() != 0:
                raise RuntimeError('Zero setpoint readback failed')
            device.input(True)
            origin = clock()
            with (folder / 'measurements.csv').open('w', newline='') as f:
                writer = None
                for b in bins:
                    scheduled = origin + b['scheduled_s']
                    sleep(max(0., scheduled - clock()))
                    tick = clock()
                    if tick - scheduled > .25:
                        raise RuntimeError('Schedule over 250 ms late; stopping')
                    device.set_current(b['requested_A'])
                    rtt = device.last_roundtrip_ms
                    # Poll once near the middle of each interval; not a settling-time test.
                    sleep(max(0., scheduled + min(.5, b['duration_s'] / 2) - clock()))
                    m = device.measure()
                    row = dict(b, command_start_s=tick - origin,
                               command_roundtrip_ms=rtt,
                               measurement_received_s=clock() - origin, **m)
                    if writer is None:
                        writer = csv.DictWriter(f, fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    f.flush()
                    measurements.append(row)
                    print(json.dumps(row), flush=True)
                    check_measurement(m, True, b['requested_A'])
                sleep(max(0., origin + bins[-1]['scheduled_s'] + bins[-1]['duration_s'] - clock()))
            outcome['completed'] = True
        finally:
            outcome['shutdown'] = device.shutdown()
            if not outcome['shutdown']['verified']:
                outcome['completed'] = False
                raise RuntimeError('Shutdown not verified: use front-panel OFF and disable PSU')
    except BaseException as exc:
        outcome['error'] = str(exc)
        raise
    finally:
        outcome['samples'] = len(measurements)
        if measurements:
            outcome['max_abs_tracking_error_A'] = max(abs(r['measured_A'] - r['requested_A']) for r in measurements)
            outcome['mean_command_roundtrip_ms'] = sum(r['command_roundtrip_ms'] for r in measurements) / len(measurements)
            outcome['max_command_roundtrip_ms'] = max(r['command_roundtrip_ms'] for r in measurements)
        (folder / 'result.json').write_text(json.dumps(outcome, indent=2) + '\n')
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=['torcs', 'synthetic'], default='torcs')
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--source-sign', choices=['discharge-positive', 'charging-positive'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--ports', action='store_true', help='List adapters only')
    parser.add_argument('--identify', action='store_true', help='Read-only identification and measurement')
    parser.add_argument('--port', help='Explicit COM or /dev/cu.* device; never auto-selected')
    parser.add_argument('--baud', type=int, choices=[4800, 9600, 19200, 38400], default=9600)
    parser.add_argument('--address', type=int, choices=range(255), default=0)
    parser.add_argument('--run', action='store_true', help='Actually enable the eLoad')
    parser.add_argument('--confirm-ttl', action='store_true', help='Verified compatible TTL adapter, e.g. IT-E132')
    parser.add_argument('--confirm-psu-only', action='store_true', help='Only current-limited 5 V PSU connected; no battery')
    args = parser.parse_args()
    if args.run and (args.identify or args.ports):
        parser.error('--run cannot be combined with --identify or --ports')
    if args.ports:
        from serial.tools import list_ports
        for p in list_ports.comports():
            print(p.device, p.description, p.hwid)
        return
    if args.run or args.identify:
        if not args.port or not args.confirm_ttl:
            parser.error('Hardware access requires --port and --confirm-ttl')
    if args.run and not args.confirm_psu_only:
        parser.error('--run requires --confirm-psu-only; this tool does not support batteries')
    if args.identify:
        import serial
        with serial.Serial(port=None, baudrate=args.baud, timeout=1, write_timeout=1) as link:
            link.port = args.port
            link.dtr = link.rts = True
            link.open()
            device = BK8500(link, args.address)
            print(json.dumps({'identity': device.identify(), 'measurement': device.measure()}, indent=2))
        return
    if args.profile == 'torcs':
        bins, metadata = prepare_torcs(args.source, args.source_sign)
    else:
        bins = [dict(step=n, scheduled_s=float(n), duration_s=1., requested_A=i) for n, i in enumerate(SYNTHETIC)]
        metadata = dict(profile='Synthetic ten-second bench sequence', duration_s=10., peak_limit_A=.1,
                        commanded_quantity='nonnegative eLoad branch current; no net cell current')
    folder = args.output or Path(__file__).parent / 'runs' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    folder.mkdir(parents=True, exist_ok=False)
    metadata.update(execution='hardware' if args.run else 'offline_only',
                    settings_restored=False, final_policy='input OFF; CC setpoint zero; remote mode retained',
                    port=args.port, baud=args.baud, address=args.address)
    (folder / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    write_csv(folder / 'planned_profile.csv', bins)
    print('Prepared %d steps in %s' % (len(bins), folder), flush=True)
    if not args.run:
        print('OFFLINE ONLY: no serial connection opened. Review planned_profile.csv before --run.')
        return
    import serial
    with serial.Serial(port=None, baudrate=args.baud, timeout=1, write_timeout=1) as link:
        link.port = args.port
        link.dtr = link.rts = True
        link.open()
        print(json.dumps(run_profile(BK8500(link, args.address), bins, folder), indent=2))


if __name__ == '__main__':
    main()
