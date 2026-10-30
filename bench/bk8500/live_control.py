"""PSU-only live load control. No battery bias mapping or automatic arming.

All instrument access belongs to one worker. Transport loss may prevent OFF;
software is not an independent emergency stop or hardware protection system.
"""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sys
import threading
import time

from instrument import BK8500
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'aps380_torcs_starter'))
from instrument_control import LatestDemand
from prototype_current_config import PROTOTYPE


class OrderlyStop(RuntimeError):
    pass


def positive(name, value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('Invalid positive setting: ' + name)
    return value


@dataclass(frozen=True)
class LiveConfig:
    max_current_A: float = PROTOTYPE.eload_current_max_A
    reference_current_A: float = PROTOTYPE.discharge_limit_A
    control_hz: float = 1.
    expiry_s: float = .5
    io_timeout_s: float = .25
    measurement_delay_s: float = .1
    slew_A_per_s: float = .5
    tracking_tolerance_A: float = .05
    tracking_timeout_s: float = 2.
    max_cycle_s: float = .8
    voltage_min_V: float = 4.5
    voltage_max_V: float = 5.5
    max_power_W: float = 18.

    def __post_init__(self):
        for name, value in asdict(self).items():
            positive(name, value)
        if self.max_current_A > PROTOTYPE.eload_current_max_A:
            raise ValueError('This live bench tool is restricted to 0..3 A')
        if self.voltage_min_V >= self.voltage_max_V:
            raise ValueError('Invalid voltage interval')
        if self.control_hz > 2 or self.max_cycle_s >= 1 / self.control_hz:
            raise ValueError('Rate must be <=2 Hz and cycle budget shorter than period')
        if self.io_timeout_s >= self.expiry_s:
            raise ValueError('Each I/O timeout must be shorter than demand expiry')

    def map_current(self, signed_cell_A):
        if type(signed_cell_A) not in (int, float) or not math.isfinite(signed_cell_A):
            raise ValueError('Invalid original current')
        # Direct branch demand: negative CELL means propulsion; regen draws zero.
        scaled = (-signed_cell_A / self.reference_current_A) * PROTOTYPE.eload_current_max_A
        if not math.isfinite(scaled):
            raise ValueError('Scaled current overflow')
        return scaled, max(0., min(self.max_current_A, scaled))


def validate_approval(profile, config):
    """Human attestations, not remote PSU verification or proof of lab approval."""
    for key in ('approved_by', 'approval_reference', 'psu_model', 'psu_output'):
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            raise ValueError('Hardware approval requires ' + key)
    if profile['psu_output'] not in ('CH1_independent', 'CH2_independent', 'CH3_fixed'):
        raise ValueError('Specify the actual PSU output; tracking modes not supported')
    for key in ('no_battery', 'ttl_verified', 'wiring_polarity_and_ratings_verified',
                'independent_protection_and_estop_verified', 'psu_settings_verified',
                'supervised_lab_approval'):
        if profile.get(key) is not True:
            raise ValueError('Hardware approval requires explicit true: ' + key)
    checks = dict(psu_channel_voltage_rating_V=config.voltage_max_V,
                  psu_channel_current_rating_A=config.max_current_A,
                  psu_channel_power_rating_W=config.max_power_W,
                  verified_source_current_ceiling_A=config.max_current_A,
                  wiring_current_rating_A=config.max_current_A,
                  approved_current_A=config.max_current_A,
                  approved_voltage_max_V=config.voltage_max_V,
                  approved_power_W=config.max_power_W,
                  approved_control_hz=config.control_hz,
                  approved_slew_A_per_s=config.slew_A_per_s)
    for key, needed in checks.items():
        if positive(key, profile.get(key)) < needed:
            raise ValueError('Requested operating envelope exceeds ' + key)
    voltage = positive('verified_output_voltage_V', profile.get('verified_output_voltage_V'))
    if not config.voltage_min_V <= voltage <= config.voltage_max_V:
        raise ValueError('Verified PSU voltage outside selected envelope')
    if profile['psu_output'] == 'CH3_fixed' and profile.get('source_limit_kind') != 'fixed_output_rating':
        raise ValueError('CH3 has a fixed output rating, not an adjustable current setting')
    if profile['psu_output'] != 'CH3_fixed' and profile.get('source_limit_kind') != 'adjustable_current_limit':
        raise ValueError('Verify the adjustable channel current limit')


class MockLiveLoad:
    """Imposed response/latency/CV envelope, not an electrical PSU simulation."""
    mock_only = True

    def __init__(self, config, clock=time.perf_counter, sleep=time.sleep,
                 delay_s=.01, response_s=.04):
        self.config, self.clock, self.sleep = config, clock, sleep
        self.delay_s, self.response_s = delay_s, response_s
        self.enabled, self.setting, self.current = False, 0., 0.
        self.updated = clock()
        self.failure = None
        self.source_voltage_V, self.source_limit_A = 5., 3.
        self.readback_offset_A = 0.
        self.last_roundtrip_ms = None
        self.commands = []

    def _exchange(self, name):
        started = self.clock()
        self.commands.append((name, started))
        self.sleep(self.config.io_timeout_s if self.failure == 'timeout' else self.delay_s)
        self.last_roundtrip_ms = (self.clock()-started) * 1000
        if self.failure:
            raise TimeoutError('Mock communication ' + self.failure)
        now = self.clock()
        target = min(self.setting, self.source_limit_A) if self.enabled else 0.
        fraction = 1. if self.response_s == 0 else -math.expm1(-(now-self.updated)/self.response_s)
        self.current += (target-self.current) * fraction
        self.updated = now

    def identify(self):
        self._exchange('identify')
        return dict(model='8500', serial_number='MOCK_ONLY')

    def remote(self): self._exchange('remote')
    def fixed_cc(self): self._exchange('fixed_cc')

    def input(self, enabled):
        self._exchange('input_' + str(enabled))
        self.enabled = enabled
        if not enabled: self.current = 0.

    def set_current(self, current_A):
        if not math.isfinite(current_A) or not 0 <= current_A <= self.config.max_current_A:
            raise ValueError('Mock current outside range')
        self._exchange('set_current')
        self.setting = current_A

    def current_setting(self):
        self._exchange('current_setting')
        return self.setting + self.readback_offset_A

    def measure(self):
        self._exchange('measure')
        voltage = self.source_voltage_V
        if self.enabled and self.setting > self.source_limit_A: voltage = 4.
        return dict(voltage_V=voltage, measured_A=self.current,
                    power_W=voltage*self.current, input_on=self.enabled,
                    remote_enabled=True, status=64 if self.enabled else 0)

    def protection_limits(self):
        self._exchange('protection_limits')
        return dict(voltage_V=self.config.voltage_max_V,
                    current_A=self.config.max_current_A, power_W=self.config.max_power_W)

    def shutdown(self):
        errors = []
        for operation in (lambda: self.input(False), lambda: self.set_current(0)):
            try: operation()
            except Exception as exc: errors.append(str(exc))
        try:
            m, setting = self.measure(), self.current_setting()
            verified = not m['input_on'] and setting == 0 and m['measured_A'] <= .002
            return dict(verified=verified, measurement=m, setpoint_A=setting, errors=errors)
        except Exception as exc:
            return dict(verified=False, errors=errors+[str(exc)])


class LiveController:
    def __init__(self, device, demands, config, clock=time.perf_counter, sleep=time.sleep):
        self.device, self.demands, self.config = device, demands, config
        self.clock, self.sleep = clock, sleep
        self.state, self.fault = 'DISARMED', ''
        self.shutdown = dict(verified=False, errors=['Not checked yet'])
        self.last = {}
        self.applied = 0.
        self.session = None
        self.rearm_after = float('-inf')
        self.bad_tracking_since = None
        self.stop_reason = ''
        self.identity_verified = False
        self.closing = False
        self.abort = threading.Event()

    def stop(self, reason='', fault=False):
        if fault and not self.fault: self.fault = reason
        self.state = 'FAULT' if self.fault else 'DISARMED'
        self.stop_reason = reason
        try:
            self.shutdown = (self.device.shutdown() if self.identity_verified else
                             dict(verified=False, errors=['Identity not verified; no commands sent']))
        except Exception as exc:
            self.shutdown = dict(verified=False, errors=['Shutdown raised: '+str(exc)])
        self.applied = 0.
        self.rearm_after = self.clock()
        if not self.shutdown.get('verified'):
            self.fault = self.fault or 'SHUTDOWN_UNVERIFIED'
            self.state = 'FAULT'

    def trip(self, reason): self.stop(reason, fault=True)

    def measurement(self, m, enabled):
        for key in ('voltage_V', 'measured_A', 'power_W'):
            v = m.get(key)
            if type(v) not in (int, float) or not math.isfinite(v):
                raise RuntimeError('INVALID_MEASUREMENT')
        if m.get('input_on') is not enabled or not m.get('remote_enabled'):
            raise RuntimeError('UNEXPECTED_INPUT_OR_REMOTE_STATE')
        if type(m.get('status')) is not int or m['status'] & 63:
            raise RuntimeError('INSTRUMENT_PROTECTION_STATUS')
        if m['status'] & (128 | 256 | 512):
            raise RuntimeError('UNEXPECTED_LOAD_MODE')
        c = self.config
        if not c.voltage_min_V <= m['voltage_V'] <= c.voltage_max_V:
            raise RuntimeError('VOLTAGE_OUTSIDE_ENVELOPE_POSSIBLE_SOURCE_LIMIT')
        if not 0 <= m['measured_A'] <= c.max_current_A + .002 or not 0 <= m['power_W'] <= c.max_power_W:
            raise RuntimeError('MEASURED_CURRENT_OR_POWER_LIMIT')
        if not enabled and m['measured_A'] > .002:
            raise RuntimeError('CURRENT_WITH_INPUT_OFF')

    def initialize(self):
        if self.state != 'DISARMED': raise ValueError('Initialize only while disarmed')
        try:
            self.identity = self.device.identify()
            if self.identity['model'] != '8500': raise RuntimeError('WRONG_INSTRUMENT')
            self.identity_verified = True
            self.device.remote()
            self.device.input(False)
            self.device.fixed_cc()
            self.device.set_current(0)
            if self.device.current_setting() != 0: raise RuntimeError('ZERO_SETTING_MISMATCH')
            self.startup_measurement = self.device.measure()
            self.measurement(self.startup_measurement, False)
            self.verify_limits()
            self.state = 'READY'
        except Exception as exc:
            self.trip(str(exc))

    def verify_limits(self):
        limits = self.device.protection_limits()
        for key, ceiling in (('voltage_V', self.config.voltage_max_V),
                             ('current_A', self.config.max_current_A),
                             ('power_W', self.config.max_power_W)):
            if abs(positive(key, limits.get(key))-ceiling) > .0001:
                raise RuntimeError('Configure and verify load protection: ' + key)
        self.limits = limits

    def fresh(self, demand=None, revision=None):
        latest, reason, current_revision = self.demands.snapshot()
        if self.abort.is_set():
            if self.closing: raise OrderlyStop('SERVICE_STOP')
            raise RuntimeError('EMERGENCY_STOP')
        if latest is None: raise RuntimeError(reason or 'TELEMETRY_UNAVAILABLE')
        if not 0 <= self.clock()-latest.received_s <= self.config.expiry_s:
            raise RuntimeError('TELEMETRY_EXPIRED')
        if self.session is not None and latest.session_id != self.session:
            raise RuntimeError('TELEMETRY_SESSION_CHANGED')
        if demand is not None and (current_revision != revision or
                not self.demands.valid(demand, revision) or
                not 0 <= self.clock()-demand.received_s <= self.config.expiry_s):
            raise RuntimeError('DEMAND_INVALIDATED_OR_EXPIRED_DURING_IO')
        return latest, current_revision

    def arm(self):
        if self.state != 'READY': return False
        try:
            demand, revision = self.fresh()
            if demand.received_s <= self.rearm_after: return False
        except RuntimeError:
            return False  # A premature ARM does not enable, latch or auto-retry.
        try:
            def checked(operation):
                value = operation()
                self.fresh()
                # A healthy 50 Hz stream can replace the old sample during a
                # longer preflight; invalid/session epochs must never be erased.
                if not self.demands.valid(demand, revision):
                    raise RuntimeError('DEMAND_INVALIDATED_OR_EXPIRED_DURING_IO')
                return value
            checked(lambda: self.device.input(False))
            self.measurement(checked(self.device.measure), False)
            checked(self.device.fixed_cc)
            checked(self.verify_limits)
            checked(lambda: self.device.set_current(0))
            if checked(self.device.current_setting) != 0: raise RuntimeError('ZERO_SETTING_MISMATCH')
            # Freeze the newest sample only for the actual enable transaction.
            newest, newest_revision = self.fresh()
            if newest_revision != revision:
                raise RuntimeError('DEMAND_INVALIDATED_OR_EXPIRED_DURING_IO')
            demand, revision = newest, newest_revision
            self.device.input(True)  # The only ON path; explicit arm() only.
            self.fresh(demand, revision)
            self.measurement(self.device.measure(), True)
            self.fresh(demand, revision)
            self.session = demand.session_id
            self.state, self.applied = 'RUNNING', 0.
            return True
        except OrderlyStop:
            self.stop('SERVICE_STOP')
            return False
        except Exception as exc:
            self.trip(str(exc))
            return False

    def reset(self):
        if self.state != 'FAULT': return
        self.stop('EXPLICIT_RESET')
        if not self.shutdown.get('verified'): return
        self.fault, self.session, self.bad_tracking_since = '', None, None
        self.abort.clear()
        self.state = 'DISARMED'
        self.initialize()  # READY only; requires a new explicit ARM.

    def cycle(self):
        if self.state != 'RUNNING': return
        start = self.clock()
        try:
            demand, revision = self.fresh()
            c = self.config
            self.last = dict(cycle_start_s=start, last_operation='pre_measurement')
            before = self.device.measure()
            self.measurement(before, True)
            self.fresh(demand, revision)
            pre_ms = (self.clock()-start)*1000
            # Voltage validation is independent work. Consume the newest demand
            # AFTER it, keeping the same continuity epoch, just before the write.
            newest, newest_revision = self.fresh()
            if newest_revision != revision:
                raise RuntimeError('DEMAND_INVALIDATED_OR_EXPIRED_DURING_IO')
            demand, revision = newest, newest_revision
            raw = demand.requested_current_A
            if raw is None: raw = demand.current_A
            scaled, limited = c.map_current(raw)
            allowed = min(limited, c.max_power_W / before['voltage_V'])
            # One nominal step at most; no catch-up ramps after slow operations.
            delta = c.slew_A_per_s / c.control_hz
            target = max(0., self.applied + max(-delta, min(delta, allowed-self.applied)))
            target = min(target, c.max_power_W / before['voltage_V'])
            quantized = min(round(target*10000), math.floor(min(c.max_current_A,
                            c.max_power_W/before['voltage_V'])*10000)) / 10000
            self.last = dict(torcs_time_s=demand.sim_time_s, source_session=demand.session_id,
                source_sequence=demand.sequence, source_received_s=demand.received_s,
                original_cell_current_A=raw, limited_cell_current_A=demand.current_A,
                scaled_load_demand_A=scaled, limited_load_target_A=limited,
                power_limited_load_target_A=allowed, commanded_load_A=quantized,
                regen_suppressed=raw > 0, saturated=scaled > limited,
                pre_measurement_ms=pre_ms, last_operation='set_current',
                mapping='direct_discharge_only_load; no battery or PSU bias')
            self.fresh(demand, revision)
            self.device.set_current(quantized)
            write_ms = self.device.last_roundtrip_ms
            self.last['command_roundtrip_ms'] = write_ms
            self.fresh(demand, revision)
            self.last['last_operation'] = 'read_setting'
            setting = self.device.current_setting()
            read_ms = self.device.last_roundtrip_ms
            self.last.update(readback_setting_A=setting, setting_read_roundtrip_ms=read_ms)
            if not math.isfinite(setting) or abs(setting-quantized) > .00005:
                raise RuntimeError('SETPOINT_READBACK_MISMATCH')
            end_wait = self.clock()+c.measurement_delay_s
            self.last['last_operation'] = 'measurement_delay'
            while self.clock() < end_wait:
                self.fresh(demand, revision)
                self.sleep(min(.02, end_wait-self.clock()))
            self.last['last_operation'] = 'read_measurement'
            m = self.device.measure()
            measure_ms = self.device.last_roundtrip_ms
            self.last.update(**m, measurement_roundtrip_ms=measure_ms)
            self.fresh(demand, revision)
            self.measurement(m, True)
            elapsed = self.clock()-start
            self.last.update(readback_setting_A=setting, **m, command_roundtrip_ms=write_ms,
                last_operation='complete',
                setting_read_roundtrip_ms=read_ms, measurement_roundtrip_ms=measure_ms,
                cycle_ms=elapsed*1000, command_age_s=self.clock()-demand.received_s,
                tracking_error_A=m['measured_A']-quantized,
                demand_error_A=m['measured_A']-allowed)
            if elapsed > c.max_cycle_s: raise RuntimeError('CONTROL_CYCLE_OVERRUN')
            self.applied = quantized
            if abs(m['measured_A']-quantized) > c.tracking_tolerance_A:
                if self.bad_tracking_since is None: self.bad_tracking_since = self.clock()
                if self.clock()-self.bad_tracking_since >= c.tracking_timeout_s:
                    raise RuntimeError('CURRENT_TRACKING_TIMEOUT_POSSIBLE_PSU_CC')
            else:
                self.bad_tracking_since = None
        except OrderlyStop:
            self.stop('SERVICE_STOP')
        except Exception as exc:
            self.last['failed_cycle_ms'] = (self.clock()-start)*1000
            self.trip(str(exc))


class LiveService:
    def __init__(self, device, config, output):
        self.device, self.config = device, config
        self.demands = LatestDemand()
        self.controller = LiveController(device, self.demands, config)
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.log = (self.output/'control.jsonl').open('w', encoding='utf-8')
        self.actions = []
        self.lock = threading.Lock()
        self.done, self.wake = threading.Event(), threading.Event()
        self.events = []
        self.worker = threading.Thread(target=self._run, name='bk8500-live-owner', daemon=True)
        self.worker_error = None

    def request(self, action):
        if action not in ('arm', 'disarm', 'reset', 'stop'): raise ValueError('Unknown action')
        if action == 'stop': self.controller.abort.set()
        with self.lock:
            if action in ('stop', 'disarm'): self.actions.clear()
            self.actions.append(action)
        self.wake.set()

    def record(self, event):
        c = self.controller
        row = dict(event=event, host_s=time.perf_counter(), state=c.state, fault=c.fault,
                   **c.last, shutdown=c.shutdown, mock_only=bool(getattr(self.device, 'mock_only', False)))
        row['measurements_retained'] = bool(c.last) and c.state != 'RUNNING'
        row['measurement_context'] = 'retained_pre_fault_or_stop' if row['measurements_retained'] else 'live'
        row['startup_measurement'] = getattr(c, 'startup_measurement', None)
        row['verified_load_protection_limits'] = getattr(c, 'limits', None)
        row['shutdown_context'] = 'last_stop_evidence' if c.state in ('RUNNING', 'READY') else 'stop_evidence'
        self.events.append(row)
        self.log.write(json.dumps(row, allow_nan=False)+'\n'); self.log.flush()

    def _run(self):
        c = self.controller
        try:
            c.initialize(); self.record('initialized')
            next_cycle = time.perf_counter()
            while not self.done.is_set():
                with self.lock:
                    actions, self.actions = self.actions, []
                # A stop/disarm takes precedence over any concurrent ARM.
                if 'stop' in actions: c.trip('EMERGENCY_STOP')
                elif 'disarm' in actions:
                    c.stop('OPERATOR_DISARM'); c.session = None
                    if c.state != 'FAULT': c.initialize()
                elif 'reset' in actions: c.reset()
                elif 'arm' in actions: c.arm()
                if actions: self.record('operator_action')
                if c.state == 'RUNNING':
                    if self.demands.snapshot()[:2] == (None, 'ENDED'):
                        c.stop('TELEMETRY_ENDED'); self.record('ended')
                    else:
                        try: c.fresh()
                        except OrderlyStop:
                            c.stop('SERVICE_STOP'); self.record('supervision_stop')
                        except RuntimeError as exc:
                            c.trip(str(exc)); self.record('supervision_fault')
                    if c.state == 'RUNNING' and time.perf_counter() >= next_cycle:
                        c.cycle(); self.record('cycle')
                        # Schedule from cycle START; skip missed periods, never queue.
                        next_cycle += 1/self.config.control_hz
                        if next_cycle <= time.perf_counter():
                            next_cycle = time.perf_counter()+1/self.config.control_hz
                else:
                    next_cycle = time.perf_counter()
                self.wake.wait(.02); self.wake.clear()
        except Exception as exc:
            self.worker_error = repr(exc)
            c.trip('WORKER_ERROR: '+str(exc))
        finally:
            c.stop('SERVICE_STOP'); self.record('stopped')

    def start(self): self.worker.start()

    def close(self):
        self.controller.closing = True
        self.done.set(); self.controller.abort.set(); self.wake.set()
        if self.worker.ident is not None: self.worker.join(timeout=10)
        if self.worker.is_alive():
            report = dict(passed=False, shutdown_verified=False,
                          error='WORKER_DID_NOT_STOP: use independent physical OFF')
        else:
            cycles = [e for e in self.events if e['event']=='cycle' and e['state']=='RUNNING' and 'readback_setting_A' in e]
            faults = sorted({e['fault'] for e in self.events if e['fault']})
            report = dict(passed=bool(cycles) and not faults and self.worker_error is None and
                self.controller.shutdown.get('verified') is True,
                running_cycles=len(cycles), faults=faults, worker_error=self.worker_error,
                shutdown_verified=self.controller.shutdown.get('verified') is True,
                shutdown=self.controller.shutdown,
                max_tracking_error_A=max((abs(e['tracking_error_A']) for e in cycles), default=None),
                max_cycle_ms=max((e['cycle_ms'] for e in cycles), default=None),
                max_command_roundtrip_ms=max((e['command_roundtrip_ms'] for e in cycles), default=None))
            report['control_status'] = 'FAIL' if faults or self.worker_error else 'PASS' if cycles else 'NOT ASSESSED'
            self.log.close()
        (self.output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
        return report
