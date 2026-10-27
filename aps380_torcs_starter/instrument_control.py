"""Mock-only cell-current coordination and independent, latest-value worker.

No hardware drivers are accepted by this implementation. Future physical use
requires a separate reviewed arming/interlock implementation, not a mode switch.
"""
from dataclasses import asdict, dataclass
from collections import deque
from enum import Enum
import json
from pathlib import Path
import threading
import time

from instrument_interfaces import InstrumentError, ProgrammablePSU, BK8500Load, CellIsolation
from numerical_validation import finite_number
from mock_instruments import MockPSU, MockBK8500, MockIsolation
from trial_acceptance import instrument_acceptance
from prototype_current_config import (PrototypeCurrentConfig as ControlConfig,
                                      CELL_CURRENT_CONVENTION, CURRENT_SCHEMA_VERSION, current_metadata)


class State(str, Enum):
    DISARMED = 'DISARMED'
    READY = 'READY'
    RUNNING = 'RUNNING'
    FAULT = 'FAULT'


@dataclass(frozen=True)
class Demand:
    current_A: float
    received_s: float
    session_id: str
    sequence: int
    requested_current_A: float | None = None
    sim_time_s: float | None = None


class LatestDemand:
    """One immutable demand, never a queue. Called only with validated rows."""
    def __init__(self):
        self.lock = threading.Lock()
        self.value = None
        self.reason = 'WAITING'
        self.revision = 0

    def publish(self, row, reason=''):
        value = None
        if row is not None and row.get('target_available', False):
            if (row.get('cell_current_convention') != CELL_CURRENT_CONVENTION or
                    type(row.get('current_schema_version')) is not int or
                    row['current_schema_version'] != CURRENT_SCHEMA_VERSION):
                self.publish(None, 'INVALID_CURRENT_CONVENTION')
                return
            value = Demand(finite_number('cell current', row['cell_current_command_A']),
                           finite_number('receipt time', row['received_qpc_s']),
                           row['session_id'], row['sequence'],
                           finite_number('raw cell current', row.get('cell_current_unclamped_A', row['cell_current_command_A'])),
                           row.get('time_s'))
        with self.lock:
            # Only discontinuities invalidate an in-flight control operation;
            # replacing a healthy sample at 50 Hz must not starve a 10 Hz worker.
            if value is None or self.value is None or value.session_id != self.value.session_id:
                self.revision += 1
            self.value, self.reason = value, '' if value else reason or 'UNAVAILABLE'

    def snapshot(self):
        with self.lock:
            return self.value, self.reason, self.revision

    def valid(self, demand, revision):
        with self.lock:
            return (self.revision == revision and self.value is not None and
                    self.value.session_id == demand.session_id)


class InstrumentCoordinator:
    def __init__(self, psu: ProgrammablePSU, load: BK8500Load, isolation: CellIsolation,
                 config=ControlConfig(), clock=time.perf_counter):
        if not all(getattr(device, 'mock_only', False) for device in (psu, load, isolation)):
            raise ValueError('This coordinator accepts MOCK devices only')
        if config.psu_current_max_A > psu.max_current_A or config.eload_current_max_A > load.max_current_A:
            raise ValueError('Prototype range exceeds mock instrument capability')
        self.psu, self.load, self.isolation = psu, load, isolation
        self.config, self.clock = config, clock
        self.state = State.DISARMED
        self.fault_reason = ''
        self.session = None
        self.ready_since = None
        self.mismatch_since = None
        self.recovery_after = float('-inf')
        self.last = {}
        self.shutdown_verified = False
        self.shutdown_errors = []
        self._reset_transition()
        self._safe_stop()

    def _reset_transition(self):
        self.phase = 'TRACK'
        self.applied_target = 0.
        self.active_direction = 0
        self.transition_started = None
        self.neutral_since = None
        self.last_step_s = None
        self.ready_settled_since = None
        self.previous_psu_current = None
        self.previous_load_current = None

    @staticmethod
    def _sign(value):
        return (value > 0)-(value < 0)

    def _transition_target(self, target, measured_net):
        """Slew to zero, prove a continuous measured neutral dwell, then use
        the newest requested direction. No old reversal targets are queued.
        All timing/rate choices are mock experiment policy, not hardware ratings.
        """
        now, c = self.clock(), self.config
        dt = 1/c.control_hz if self.last_step_s is None else min(max(0., now-self.last_step_s), 1/c.control_hz)
        self.last_step_s = now
        direction = self._sign(target)
        if self.phase == 'TRACK' and self.active_direction and direction != self.active_direction:
            self.phase, self.transition_started = 'TO_ZERO', now
            self.neutral_since = None
        if self.phase != 'TRACK':
            if now-self.transition_started > c.transition_timeout_s:
                raise InstrumentError('SIGN_TRANSITION_TIMEOUT')
            goal = 0.
            if self.applied_target == 0. and abs(measured_net) <= c.neutral_tolerance_A:
                self.phase = 'HOLD_ZERO'
                if self.neutral_since is None:
                    self.neutral_since = now
                if now-self.neutral_since >= c.neutral_hold_s:
                    self.phase, self.active_direction = 'TRACK', 0
                    self.transition_started, self.neutral_since = None, None
                    goal = target
            else:
                self.phase, self.neutral_since = 'TO_ZERO', None
        else:
            goal = target
        delta = c.slew_rate_A_per_s*dt
        self.applied_target += max(-delta, min(delta, goal-self.applied_target))
        if self.phase == 'TRACK' and self.applied_target:
            self.active_direction = self._sign(self.applied_target)
        return self.applied_target

    def _safe_stop(self):
        # The mock local interlock opens even if all communication is broken.
        self.shutdown_errors = []
        try:
            self.isolation.open()
        except Exception as error:
            self.shutdown_errors.append(str(error))
        for device in (self.psu, self.load):
            try:
                device.set_output(False, self.config.io_timeout_s)
            except Exception as error:
                self.shutdown_errors.append(str(error))
        status = self.isolation.verify()
        self.shutdown_verified = status.is_open and status.outputs_disabled

    def trip(self, reason):
        if self.state != State.FAULT:
            self.fault_reason = reason
        self.state = State.FAULT
        self._safe_stop()

    def emergency_stop(self):
        self.trip('EMERGENCY_STOP')

    def disarm(self):
        self._safe_stop()
        self.recovery_after = self.clock()
        self.session = None
        self._reset_transition()
        if not self.shutdown_verified:
            self.trip('SHUTDOWN_NOT_VERIFIED')
        elif self.state != State.FAULT:
            self.state = State.DISARMED

    def _read(self, device):
        m = device.read(self.config.io_timeout_s)
        age = self.clock()-finite_number('measurement timestamp', m.acquired_s)
        if not 0 <= age <= self.config.measurement_expiry_s:
            raise InstrumentError('STALE_OR_FUTURE_MEASUREMENT')
        for name in ('current_A', 'voltage_V', 'setpoint_A'):
            finite_number(name, getattr(m, name))
        if m.status.fault or m.current_A < 0 or m.current_A > device.max_current_A + self.config.tracking_tolerance_A or m.voltage_V <= 0:
            raise InstrumentError('INVALID_INSTRUMENT_STATUS_OR_MEASUREMENT')
        return m

    def recover(self):
        if self.state != State.FAULT:
            raise ValueError('Recovery is only valid in FAULT')
        self._safe_stop()
        try:
            for device in (self.psu, self.load):
                measurement = self._read(device)
                if measurement.status.output_enabled or measurement.current_A > self.config.tracking_tolerance_A:
                    raise InstrumentError('Output enabled or nonzero current during recovery')
            if not self.shutdown_verified:
                raise InstrumentError('Isolation not verified')
        except Exception as error:
            self.trip(f'RECOVERY_FAILED: {error}')
            return
        self.state, self.fault_reason = State.DISARMED, ''
        self.session, self.last = None, {}
        self._reset_transition()
        self.recovery_after = self.clock()

    def arm(self):
        if self.state != State.DISARMED:
            raise ValueError('Explicit recovery and disarmed state required before arming')
        try:
            self._safe_stop()
            if not self.shutdown_verified:
                raise InstrumentError('Isolation not verified')
            self.psu.set_current(self.config.psu_cc_setpoint_A, self.config.io_timeout_s)
            self.load.set_current(self.config.eload_current_min_A, self.config.io_timeout_s)
            # Isolated while the two mock branches settle; READY is not RUNNING.
            self.psu.set_output(True, self.config.io_timeout_s)
            self.load.set_output(True, self.config.io_timeout_s)
            self.shutdown_verified = False
            self.ready_since = self.clock()
            self.mismatch_since = None
            self._reset_transition()
            self.phase = 'BALANCING'
            self.state = State.READY
        except Exception as error:
            self.trip(f'ARM_FAILED: {error}')

    def _fresh_demand(self, demand):
        now = self.clock()
        if demand is not None:
            self.last['command_age_s'] = now-demand.received_s
        if demand is None or not 0 <= now-demand.received_s <= self.config.command_expiry_s:
            raise InstrumentError('TELEMETRY_EXPIRED')
        if demand.received_s <= self.recovery_after:
            raise InstrumentError('NEW_DEMAND_REQUIRED_AFTER_DISARM_OR_RECOVERY')
        if self.session is not None and demand.session_id != self.session:
            raise InstrumentError('TELEMETRY_SESSION_CHANGED')

    def step(self, demand, unavailable='', still_valid=lambda: True):
        if self.state not in (State.READY, State.RUNNING):
            return
        try:
            if demand is None and unavailable == 'ENDED':
                # A validated native end is an orderly stop, not a lost stream.
                # New samples still require explicit rearming; crashes remain
                # failures in the independent process acceptance section.
                self.disarm()
                return
            if self.state == State.READY and self.clock()-self.ready_since > self.config.ready_timeout_s:
                raise InstrumentError('READY_TIMEOUT')
            waiting = demand is None and self.state == State.READY and unavailable == 'WAITING'
            if demand is None and not waiting:
                raise InstrumentError(unavailable or 'TELEMETRY_UNAVAILABLE')
            if demand is not None:
                self._fresh_demand(demand)
            c = self.config
            requested = finite_number('requested current', demand.requested_current_A if demand.requested_current_A is not None else demand.current_A) if demand else 0.
            target = max(c.battery_current_min_A, min(c.battery_current_max_A, demand.current_A)) if demand else 0.
            psu = self._read(self.psu)
            if not psu.status.output_enabled:
                raise InstrumentError('PSU_OUTPUT_DISABLED')
            if psu.status.mode != 'CC':
                raise InstrumentError('PSU_NOT_CC')
            if abs(psu.setpoint_A-c.psu_cc_setpoint_A) > c.numeric_tolerance_A:
                raise InstrumentError('PSU_SETPOINT_CHANGED')
            psu_lower=0. if self.state == State.READY else c.psu_current_min_A
            if not psu_lower-c.tracking_tolerance_A <= psu.current_A <= c.psu_current_max_A+c.tracking_tolerance_A:
                raise InstrumentError('PSU_MEASURED_LIMIT')
            before = self._read(self.load)
            if not before.status.output_enabled:
                raise InstrumentError('LOAD_OUTPUT_DISABLED')
            if before.status.mode != 'CC':
                raise InstrumentError('LOAD_NOT_CC')
            before_net = psu.current_A-before.current_A
            if self.state == State.RUNNING and not c.battery_current_min_A-c.tracking_tolerance_A <= before_net <= c.battery_current_max_A+c.tracking_tolerance_A:
                self.last['pre_control_cell_current_A'] = before_net
                raise InstrumentError('MEASURED_DIRECTIONAL_LIMIT')
            psu_stable = (self.previous_psu_current is not None and
                          abs(psu.current_A-self.previous_psu_current) <= c.neutral_tolerance_A)
            self.previous_psu_current = psu.current_A
            # READY balances the isolated branches at zero net current. Live
            # demand (including regeneration already present at arm time) must
            # not influence startup or be tested against an unsettled PSU.
            starting = self.state == State.READY
            applied = 0. if starting else self._transition_target(target, before_net)
            load_target = psu.current_A - applied
            if starting:
                # A configured nonzero enabled-load minimum may prevent exact
                # balance while the source rises. Remain isolated until settled.
                load_target=max(c.eload_current_min_A,min(c.eload_current_max_A,load_target))
            self.last = dict(requested_A=requested, permitted_A=target, applied_target_A=applied,
                transition_phase=self.phase, active_direction=self.active_direction,
                transition_age_s=0. if self.transition_started is None else self.clock()-self.transition_started,
                neutral_hold_elapsed_s=0. if self.neutral_since is None else self.clock()-self.neutral_since,
                directional_saturated=requested != target, psu=asdict(psu),
                feasible_min_A=max(c.battery_current_min_A, psu.current_A-c.eload_current_max_A),
                feasible_max_A=min(c.battery_current_max_A, psu.current_A-c.eload_current_min_A),
                load_target_A=load_target, demand_available=demand is not None,
                source_session=demand.session_id if demand else None,
                source_sequence=demand.sequence if demand else None,
                source_received_s=demand.received_s if demand else None,
                source_sim_time_s=demand.sim_time_s if demand else None)
            if not starting and not c.eload_current_min_A-c.numeric_tolerance_A <= psu.current_A-target <= c.eload_current_max_A+c.numeric_tolerance_A:
                # Fail closed: never claim an impossible signed demand was applied.
                raise InstrumentError('INFEASIBLE_CURRENT')
            if not c.eload_current_min_A-c.numeric_tolerance_A <= load_target <= c.eload_current_max_A+c.numeric_tolerance_A:
                raise InstrumentError('INFEASIBLE_APPLIED_CURRENT')
            sent_target = max(c.eload_current_min_A, min(c.eload_current_max_A, load_target))
            self.last['load_command_A'] = sent_target
            self.last['load_roundoff_adjustment_A'] = sent_target-load_target
            self.load.set_current(sent_target, c.io_timeout_s)
            load = self._read(self.load)
            # Recheck all ages after blocking I/O; never act on a queued old command.
            if self.clock()-psu.acquired_s > c.measurement_expiry_s:
                raise InstrumentError('STALE_PSU_READBACK_AFTER_IO')
            if demand is not None:
                self._fresh_demand(demand)
                if not still_valid():
                    raise InstrumentError('TELEMETRY_INVALIDATED_DURING_IO')
            if not load.status.output_enabled:
                raise InstrumentError('LOAD_OUTPUT_DISABLED')
            if load.status.mode != 'CC':
                raise InstrumentError('LOAD_NOT_CC')
            net = psu.current_A-load.current_A
            error = net-applied
            expected_direction = self.active_direction
            direction_ok = (abs(net) <= c.direction_tolerance_A or
                            self._sign(net) == expected_direction)
            self.last.update(load=asdict(load), branch_net_A=net, tracking_error_A=error,
                             demand_error_A=net-target, direction_ok=direction_ok,
                             psu_measurement_age_s=self.clock()-psu.acquired_s,
                             load_measurement_age_s=self.clock()-load.acquired_s,
                             readback_skew_s=load.acquired_s-psu.acquired_s)
            load_stable = (self.previous_load_current is not None and
                           abs(load.current_A-self.previous_load_current) <= c.neutral_tolerance_A)
            self.previous_load_current = load.current_A
            if starting:
                # A nearly stationary CC readback near zero is not evidence that
                # the configured bias has settled. CV cannot qualify startup.
                bias_settled = abs(psu.current_A-psu.setpoint_A) <= c.neutral_tolerance_A
                if demand is not None and abs(net) <= c.neutral_tolerance_A and psu_stable and load_stable and bias_settled:
                    if self.ready_settled_since is None:
                        self.ready_settled_since = self.clock()
                    if self.clock()-self.ready_settled_since >= c.neutral_hold_s:
                        self.isolation.close()
                        if self.isolation.verify().is_open:
                            raise InstrumentError('ISOLATION_DID_NOT_CLOSE')
                        self.state, self.session = State.RUNNING, demand.session_id
                        self.phase = 'TRACK'
                        self.last.update(transition_phase='TRACK', startup_balanced=True)
                else:
                    self.ready_settled_since = None
                return  # apply the newest operational demand on the next cycle
            if self.state == State.RUNNING and not c.battery_current_min_A-c.tracking_tolerance_A <= net <= c.battery_current_max_A+c.tracking_tolerance_A:
                raise InstrumentError('MEASURED_DIRECTIONAL_LIMIT')
            if self.state == State.RUNNING and not direction_ok:
                raise InstrumentError('UNEXPECTED_CURRENT_DIRECTION')
            if abs(error) <= c.tracking_tolerance_A:
                self.mismatch_since = None
            else:
                if self.mismatch_since is None:
                    self.mismatch_since = self.clock()
                if self.clock()-self.mismatch_since > c.settling_timeout_s:
                    raise InstrumentError('CURRENT_TRACKING_TIMEOUT')
        except Exception as error:
            self.trip(str(error))

    def snapshot(self):
        isolation = self.isolation.verify()
        # Mock truth, not an independent ESP32 measurement. Open cell path = 0 A.
        cell_current = 0. if isolation.is_open else self.last.get('branch_net_A', 0.)
        retained = bool(self.last.get('psu')) and self.state not in (State.READY, State.RUNNING)
        context = ('retained_pre_fault' if self.state == State.FAULT else 'retained_after_disarm') if retained else (
            'startup' if self.state == State.READY else 'live' if self.state == State.RUNNING else 'not_available')
        return dict(**current_metadata(), state=self.state.value, fault=self.fault_reason, mock_cell_current_A=cell_current,
                    isolation=asdict(isolation), shutdown_verified=self.shutdown_verified,
                    shutdown_errors=list(self.shutdown_errors), **self.last,
                    measurement_context=context, measurements_retained=retained,
                    cell_current_target_A=self.last.get('requested_A'),
                    cell_current_limited_A=self.last.get('permitted_A'),
                    cell_current_applied_A=self.last.get('applied_target_A'),
                    cell_current_mock_measured_A=cell_current,
                    measurement_age_at_snapshot_s={name: self.clock()-self.last[name]['acquired_s']
                        for name in ('psu', 'load') if name in self.last})


class MockInstrumentService:
    """Single-owner worker; no instrument I/O runs in the telemetry thread.

    LiveReceiver uses perf_counter, so both demand timestamps and mocks use that
    clock here. Deterministic tests may inject a different common clock directly.
    """
    def __init__(self, output, config=ControlConfig()):
        self.config = config
        self.demands = LatestDemand()
        self.psu = MockPSU(clock=time.perf_counter, max_current_A=config.psu_current_max_A)
        self.load = MockBK8500(clock=time.perf_counter, max_current_A=config.eload_current_max_A)
        self.coordinator = InstrumentCoordinator(self.psu, self.load,
            MockIsolation(self.psu, self.load), config)
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        (self.output/'config.json').write_text(json.dumps(dict(mode='mock_only', **current_metadata(), **asdict(config)), indent=2)+'\n')
        self.log = (self.output/'instruments.jsonl').open('w', encoding='utf-8')
        self.stop_event, self.wake = threading.Event(), threading.Event()
        self.action_lock = threading.Lock()
        self.pending_action = None
        self.latest = self.coordinator.snapshot()
        self.history = deque(maxlen=5000)
        self.failed = None
        self.cycles = 0
        self.arming_requested = False
        self.thread = threading.Thread(target=self._run, daemon=True, name='aps380-mock-instruments')

    def request(self, action):
        priorities = {'arm':0, 'recover':1, 'disarm':2, 'emergency_stop':3}
        if action not in priorities:
            raise ValueError('Unknown mock control action')
        if action == 'arm':
            self.arming_requested = True
        with self.action_lock:
            if self.pending_action is None or priorities[action] >= priorities[self.pending_action]:
                self.pending_action = action
        self.wake.set()

    def start(self, arm=False):
        if arm:
            self.request('arm')
        self.thread.start()

    def _record(self, event='cycle'):
        self.latest = self.coordinator.snapshot()
        self.history.append(self.latest)
        devices = {}
        for name, device in (('psu', self.psu), ('load', self.load)):
            devices[name] = list(device.log)
            device.log.clear()
        self.log.write(json.dumps(dict(event=event, host_s=time.perf_counter(), mock_only=True,
                                      **self.latest, transactions=devices), allow_nan=False)+'\n')
        self.log.flush()

    def _run(self):
        try:
            while not self.stop_event.is_set():
                with self.action_lock:
                    action, self.pending_action = self.pending_action, None
                if action:
                    try:
                        getattr(self.coordinator, action)()
                    except ValueError as error:
                        # Invalid operator actions never clear a latched fault.
                        self.coordinator.trip(f'INVALID_ACTION: {error}')
                demand, reason, revision = self.demands.snapshot()
                self.coordinator.step(demand, reason,
                    lambda: self.demands.valid(demand, revision))
                self.cycles += 1
                self._record()
                # No catch-up iterations after a slow transaction; no demand queue.
                self.wake.wait(1/self.config.control_hz)
                self.wake.clear()
        except Exception as error:
            self.failed = repr(error)
            self.coordinator.trip(f'WORKER_ERROR: {error}')
        finally:
            self.coordinator.disarm()  # preserves FAULT until explicit recovery
            self._record('stopped')

    def close(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread.is_alive():
            self.thread.join(timeout=5.)
        if self.thread.is_alive():
            raise RuntimeError('Mock worker did not stop')
        if self.cycles == 0:
            self.coordinator.disarm()
            self._record('stopped')
        report = dict(mock_only=True, physical_commands_sent=False, cycles=self.cycles,
                      worker_error=self.failed, final=self.coordinator.snapshot())
        events = [json.loads(line) for line in (self.output/'instruments.jsonl').read_text().splitlines()]
        report['acceptance'] = instrument_acceptance(events, self.config, report['final'],
                                                    self.failed, self.arming_requested)
        (self.output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
        self.log.close()
        return report
