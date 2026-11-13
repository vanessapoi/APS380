"""One-shot OFF-only commissioning check. No ARM or telemetry control path."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from instrument import BK8500
from live_control import LatestDemand, LiveConfig, LiveController, MockLiveLoad, positive


def low_config():
    return LiveConfig(max_current_A=.10, reference_current_A=.05,
                      voltage_min_V=4.5, voltage_max_V=5.5, max_power_W=.6,
                      control_hz=1, slew_A_per_s=.02, tracking_tolerance_A=.01)


class OffOnlyDevice:
    """Allow only OFF and zero writes, including during shutdown."""
    def __init__(self, device):
        self.device = device

    def identify(self): return self.device.identify()
    def remote(self): return self.device.remote()
    def fixed_cc(self): return self.device.fixed_cc()
    def current_setting(self): return self.device.current_setting()
    def protection_limits(self): return self.device.protection_limits()
    def measure(self): return self.device.measure()

    def input(self, enabled):
        if enabled is not False:
            raise ValueError('OFF-only preflight forbids input ON')
        return self.device.input(False)

    def set_current(self, current_A):
        if current_A != 0:
            raise ValueError('OFF-only preflight forbids nonzero settings')
        return self.device.set_current(0)

    def shutdown(self):
        # Reuse the existing retry/readback logic through this restricted facade.
        return BK8500.shutdown(self)


def check(device, config, expected_serial=None):
    controller = LiveController(OffOnlyDevice(device), LatestDemand(), config)
    try:
        controller.initialize()
        if (controller.state == 'READY' and expected_serial is not None
                and controller.identity.get('serial_number') != expected_serial):
            controller.trip('INSTRUMENT_SERIAL_MISMATCH')
        ready = controller.state == 'READY'
    finally:
        controller.stop('OFF_PREFLIGHT_COMPLETE')
    return dict(
        scope='OFF-only preflight; not authorization or validation of current draw',
        result='PASS' if ready and controller.shutdown.get('verified') else 'FAIL',
        current_draw_assessed=False, arming_available=False,
        identity=getattr(controller, 'identity', None), fault=controller.fault,
        startup_measurement=getattr(controller, 'startup_measurement', None),
        observed_protection_limits=getattr(controller, 'observed_limits', None),
        verified_protection_limits=getattr(controller, 'limits', None),
        shutdown=controller.shutdown)


def inspect(device, config, expected_serial=None):
    """Queries only: no mode, remote, setting, protection or input writes."""
    identity = device.identify()
    if identity.get('model') != '8500' or (expected_serial is not None
            and identity.get('serial_number') != expected_serial):
        raise ValueError('Unexpected instrument identity')
    measurement = device.measure()
    if (measurement.get('input_on') is not False
            or not config.voltage_min_V <= positive('voltage', measurement.get('voltage_V')) <= config.voltage_max_V
            or type(measurement.get('measured_A')) not in (int, float)
            or not 0 <= measurement['measured_A'] <= .002
            or type(measurement.get('power_W')) not in (int, float)
            or not 0 <= measurement['power_W'] <= config.max_power_W
            or measurement.get('status', 0) & 31):
        raise ValueError('OFF-state measurement outside inspection bounds')
    limits = device.protection_limits()
    for key in ('voltage_V', 'current_A', 'power_W'): positive(key, limits.get(key))
    return dict(result='PASS', scope='Read-only inspection; protection suitability NOT ASSESSED',
                identity=identity, measurement=measurement, observed_protection_limits=limits,
                input_off_verified=True, current_draw_assessed=False, arming_available=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', choices=('mock', 'hardware'), default='mock')
    parser.add_argument('--port')
    parser.add_argument('--baud', type=int, choices=(4800, 9600, 19200, 38400), default=9600)
    parser.add_argument('--address', type=int, choices=range(255), default=0)
    parser.add_argument('--confirm-ttl', action='store_true')
    parser.add_argument('--expected-serial')
    parser.add_argument('--inspect-only', action='store_true',
                        help='Queries only; report actual protections without exact matching or writes')
    parser.add_argument('--setup-record', type=Path,
                        help='Optional factual setup record; does not authorize ARM')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.device == 'hardware' and (not args.port or not args.confirm_ttl):
        parser.error('Hardware requires an explicit port and --confirm-ttl')
    if args.device == 'mock' and (args.port or args.confirm_ttl):
        parser.error('Serial options are hardware-only')
    setup = json.loads(args.setup_record.read_text(encoding='utf-8-sig')) if args.setup_record else None
    config = low_config()
    link = None
    try:
        if args.device == 'mock':
            device = MockLiveLoad(config, delay_s=0)
        else:
            import serial
            link = serial.Serial(port=None, baudrate=args.baud,
                                 timeout=config.io_timeout_s, write_timeout=config.io_timeout_s)
            link.port = args.port
            link.dtr = link.rts = True
            link.open()
            device = BK8500(link, args.address, max_setpoint_A=.10)
        report = (inspect if args.inspect_only else check)(device, config, args.expected_serial)
    except Exception as exc:
        report = dict(result='FAIL', error=repr(exc), arming_available=False,
                      shutdown=dict(verified=False), current_draw_assessed=False)
    finally:
        if link is not None:
            link.close()
    report.update(device=args.device, setup_record=setup,
                  recorded_utc=datetime.now(timezone.utc).isoformat())
    output = args.output or Path('.local/bk8500-off-preflight') / (
        datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    print('Saved:', output)
    return 0 if report['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
