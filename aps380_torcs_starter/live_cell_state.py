"""Opt-in synthetic cell measurements from mock branch readbacks, never hardware.

Voltage/temperature are imposed mock values, not a circuit/thermal model.
SOC uses real elapsed perf-counter time, not accelerated simulation time.
"""
from dataclasses import asdict, dataclass
import json
import threading
import time
import uuid

from cell_soc import CellMeasurement, CoulombCounter, finite
from cell_sop import RintPolicy

SOURCE = 'prototype_mock_branch_readbacks'
MOCK_QUALIFICATIONS = {
    'prototype-mock': (SOURCE, 'mock_readbacks', 'imposed_mock_voltage', 'imposed_mock_temperature'),
    'battery-bias-mock': ('battery_bias_mock_sensor', 'mock_independent_sensor',
                          'mock_sensor_voltage', 'mock_sensor_temperature'),
}


@dataclass(frozen=True)
class CellSample:
    measurement: CellMeasurement
    sequence: int
    received_s: float
    source: str = SOURCE
    quality: str = 'mock_readbacks'
    isolation_open: bool = False
    voltage_source: str = 'imposed_mock_voltage'
    temperature_source: str = 'imposed_mock_temperature'


class LiveCellObserver:
    """Single sequence, no interpolation across loss; errors require explicit reset.

    A supplied initial SOC is a MOCK assertion, never an inferred rested OCV.
    Reset discards the unknown interval and anchors at the next fresh sample.
    """
    def __init__(self, capacity_Ah, initial_soc, *, freshness_s=.2, max_gap_s=.5,
                 clock=time.perf_counter, source_profile='prototype-mock'):
        if source_profile not in MOCK_QUALIFICATIONS:
            raise ValueError('Only explicitly qualified mock sources are supported')
        self.required_source, self.required_quality, self.voltage_source, self.temperature_source = MOCK_QUALIFICATIONS[source_profile]
        for name, value in (('capacity', capacity_Ah), ('freshness', freshness_s), ('gap', max_gap_s)):
            if finite(name, value) <= 0:
                raise ValueError(name + ' must be positive')
        if not 0 <= finite('initial SOC', initial_soc) <= 1:
            raise ValueError('Initial SOC must be fractional')
        self.capacity, self.initial_soc = capacity_Ah, initial_soc
        self.freshness, self.max_gap, self.clock = freshness_s, max_gap_s, clock
        self.lock = threading.RLock()
        self.counter = None
        self.sample = None
        self.estimate = None
        self.error = ''
        self.accepted = 0
        self.generation = 0
        self.reset_floor = float('-inf')

    def unavailable(self, reason):
        with self.lock:
            if not self.error:
                self.error = reason

    def reset(self, initial_soc):
        if not 0 <= finite('reset MOCK SOC', initial_soc) <= 1:
            raise ValueError('Reset SOC must be fractional')
        with self.lock:
            self.initial_soc = initial_soc
            self.counter = self.sample = self.estimate = None
            self.error = ''
            self.generation += 1
            self.reset_floor = self.clock()

    def accept(self, sample):
        with self.lock:
            if self.error:
                return False
            try:
                m = sample.measurement
                if not isinstance(m,CellMeasurement):
                    raise ValueError('INVALID_CELL_MEASUREMENT_TYPE')
                now = self.clock()
                if sample.source != self.required_source or sample.quality != self.required_quality:
                    raise ValueError('UNQUALIFIED_MEASUREMENT_SOURCE')
                if (sample.voltage_source != self.voltage_source or
                        sample.temperature_source != self.temperature_source):
                    raise ValueError('UNQUALIFIED_MOCK_STATE_SOURCE')
                if type(sample.sequence) is not int or sample.sequence < 0:
                    raise ValueError('INVALID_MEASUREMENT_SEQUENCE')
                finite('receipt time', sample.received_s)
                if not m.time_s >= self.reset_floor:
                    raise ValueError('MEASUREMENT_PREDATES_RESET')
                if (not 0 <= now-sample.received_s <= self.freshness or
                        not 0 <= sample.received_s-m.time_s <= self.freshness or
                        not 0 <= now-m.time_s <= self.freshness):
                    raise ValueError('STALE_OR_FUTURE_MEASUREMENT')
                if type(sample.isolation_open) is not bool or (sample.isolation_open and m.net_cell_current_A != 0):
                    raise ValueError('ISOLATION_CURRENT_CONTRADICTION')
                if self.sample is not None:
                    if m.session_id != self.sample.measurement.session_id:
                        raise ValueError('CELL_SESSION_CHANGED_REINITIALIZE')
                    if sample.sequence != self.sample.sequence+1:
                        raise ValueError('MISSING_DUPLICATE_OR_REORDERED_CELL_SAMPLE')
                    if sample.received_s < self.sample.received_s:
                        raise ValueError('RECEIPT_CLOCK_REVERSED')
                    estimate = self.counter.update(m)
                else:
                    self.counter = CoulombCounter(self.capacity, self.max_gap, self.initial_soc, m)
                    estimate = self.counter.initial_estimate()
                self.sample, self.estimate = sample, estimate
                self.accepted += 1
                if estimate.boundary_clipped:
                    raise ValueError('SOC_BOUNDARY_CLIPPED_REINITIALIZE')
                return True
            except (ValueError, TypeError, AttributeError) as exc:
                self.unavailable(str(exc))
                return False

    def snapshot(self):
        with self.lock:
            age = self.clock()-self.sample.measurement.time_s if self.sample else None
            if age is not None and (age < 0 or age > self.freshness):
                self.unavailable('CELL_MEASUREMENT_EXPIRED')
            return dict(state='FAULT' if self.error else 'VALID' if self.sample else 'WAITING',
                error=self.error, accepted=self.accepted, generation=self.generation,
                age_s=age, sample=asdict(self.sample) if self.sample else None,
                estimate=asdict(self.estimate) if self.estimate else None,
                initial_soc_basis='Explicit MOCK assertion; no rested OCV initialization',
                retained=bool(self.error and self.sample))


class MockCellStream:
    """Called once per worker record; never polls devices or queues samples."""
    def __init__(self, observer, output, *, voltage_V, temperature_C,
                 max_skew_s=.05, clock=time.perf_counter):
        if finite('mock voltage', voltage_V) <= 0:
            raise ValueError('Mock voltage must be positive')
        finite('mock temperature', temperature_C)
        if finite('readback skew', max_skew_s) <= 0:
            raise ValueError('Readback skew bound must be positive')
        self.observer, self.voltage, self.temperature = observer, voltage_V, temperature_C
        self.max_skew, self.clock = max_skew_s, clock
        self.session = 'mock-cell-'+uuid.uuid4().hex
        self.sequence = 0
        self.previous_pair = None
        self.closed = False
        self.lock = threading.Lock()
        self.log = output.open('w', encoding='utf-8')

    def __call__(self, snapshot):
        with self.lock:
            self._publish(snapshot)

    def _publish(self, snapshot):
        if self.closed:
            return
        sample = None
        try:
            if snapshot['state'] not in ('READY', 'RUNNING') or snapshot['measurements_retained']:
                if self.observer.sample is not None or snapshot['state']=='FAULT':
                    raise ValueError('MOCK_READBACKS_UNAVAILABLE_'+snapshot['state'])
                return
            if 'psu' not in snapshot or 'load' not in snapshot:
                return
            p, e = snapshot['psu'], snapshot['load']
            pair = (p['acquired_s'], e['acquired_s'])
            if pair == self.previous_pair:
                return  # Cached records never refresh freshness or increment sequence.
            if self.previous_pair and any(a <= b for a, b in zip(pair, self.previous_pair)):
                raise ValueError('BRANCH_MEASUREMENT_CLOCK_REVERSED')
            for value in pair:
                finite('branch timestamp', value)
            if abs(pair[0]-pair[1]) > self.max_skew:
                raise ValueError('BRANCH_READBACK_SKEW')
            for branch in (p, e):
                if finite('branch current', branch['current_A']) < 0 or branch['status']['fault']:
                    raise ValueError('INVALID_BRANCH_READBACK')
                if self.clock()-branch['acquired_s'] > self.observer.freshness:
                    raise ValueError('STALE_BRANCH_READBACK')
            opened = snapshot['isolation']['is_open']
            # The mock isolation truth is explicit. An open cell path carries 0 A
            # even while the two branch currents are balancing during startup.
            current = 0. if opened else p['current_A']-e['current_A']
            m = CellMeasurement(self.session, max(pair), self.voltage, current, self.temperature)
            sample = CellSample(m, self.sequence, self.clock(), isolation_open=opened)
            self.sequence += 1
            self.previous_pair = pair
            accepted = self.observer.accept(sample)
        except (ValueError, TypeError, KeyError) as exc:
            self.observer.unavailable(str(exc))
            accepted = False
        self.log.write(json.dumps(dict(sample=asdict(sample) if sample else None,
            accepted=accepted, observer=self.observer.snapshot()), allow_nan=False)+'\n')
        self.log.flush()

    def close(self):
        with self.lock:
            self.closed = True
            self.log.close()


class LiveRintPolicy(RintPolicy):
    label = 'LIVE MOCK COULOMB COUNTING + RINT; NOT PHYSICAL PROTECTION'

    def __init__(self, parameters, initial_soc, temperature_C, observer):
        super().__init__(parameters, initial_soc, temperature_C)
        self.observer = observer
        self.on_fault = None
        self.notified_generation = None

    def describe(self):
        return dict(super().describe(), policy='rint-live-mock',
                    soc_source='Coulomb Counter using qualified mock branch readbacks',
                    measurement_freshness_s=self.observer.freshness,
                    maximum_measurement_gap_s=self.observer.max_gap)

    def evaluate_row(self, row):
        state = self.observer.snapshot()
        if state['state']=='FAULT' and self.on_fault and self.notified_generation!=state['generation']:
            self.on_fault()
            self.notified_generation=state['generation']
        valid = state['state'] == 'VALID'
        self.mock_soc = state['estimate']['soc'] if valid else float('nan')
        self.mock_temperature_C = state['sample']['measurement']['cell_temperature_C'] if valid else 25.
        soc, fraction, details = super().evaluate_row(row)
        details.update(cell_observer_state=state['state'], cell_observer_error=state['error'],
            cell_measurement_age_s=state['age_s'], cell_measurement_source=SOURCE,
            cell_measurement_sequence=state['sample']['sequence'] if state['sample'] else None,
            cell_measurement_session=state['sample']['measurement']['session_id'] if state['sample'] else None,
            cell_soc_net_discharged_Ah=state['estimate']['net_discharged_Ah'] if state['estimate'] else None,
            cell_observer_generation=state['generation'], cell_measurements_retained=state['retained'],
            sop_waiting_for_measurement=state['state']=='WAITING')
        details['cell_mock_measured_current_A'] = state['sample']['measurement']['net_cell_current_A'] if state['sample'] else None
        details['cell_voltage_source'] = 'imposed_mock_voltage'
        details['cell_temperature_source'] = 'imposed_mock_temperature'
        if not valid:
            details['sop_reason'] = state['error'] or 'WAITING_FOR_FRESH_MOCK_MEASUREMENTS'
        return soc, fraction, details
