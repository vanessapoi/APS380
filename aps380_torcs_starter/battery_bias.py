"""Mock-only measured-current bias composition. No hardware transport exists.

Frames are a transport-neutral contract, not an ESP32 parser. Physical control
remains prohibited. Mock independent cell sensing is a separate channel over
the simplified plant truth; it is not an electrical/thermal battery model.
"""
from dataclasses import asdict, dataclass, replace
import json
import math
import time
import threading
import uuid

from cell_soc import CellMeasurement
from cell_sop import RintEstimator, RintParameters
from instrument_control import InstrumentCoordinator, MockInstrumentService, State, ControlConfig
from instrument_interfaces import InstrumentError
from live_cell_state import LiveCellObserver, CellSample
from numerical_validation import finite_number
from trial_acceptance import instrument_acceptance, assessment

BIAS_CONTROL = ControlConfig(slew_rate_A_per_s=.02,ready_timeout_s=90.)


@dataclass(frozen=True)
class MockBiasQualification:
    """Demonstration assumptions ONLY, never physical cell ratings/timing."""
    voltage_min_V: float = 2.5
    voltage_max_V: float = 4.2
    temperature_min_C: float = 23.
    temperature_max_C: float = 27.
    startup_voltage_difference_V: float = .02
    branch_slew_A_per_s: float = .02

    def __post_init__(self):
        for key, value in asdict(self).items(): finite_number(key,value)
        if (self.voltage_min_V<=0 or self.voltage_min_V>=self.voltage_max_V
                or self.temperature_min_C>=self.temperature_max_C
                or self.startup_voltage_difference_V<=0 or self.branch_slew_A_per_s<=0):
            raise ValueError('Invalid MOCK bias qualification')


@dataclass(frozen=True)
class BiasMeasurement:
    session_id: str
    sequence: int
    acquired_s: float
    received_s: float
    source: str
    quality: str
    psu_current_A: float
    cell_current_A: float
    cell_voltage_V: float
    cell_temperature_C: float
    cell_isolated: bool
    source_isolated: bool
    source_enabled: bool
    load_enabled: bool
    protection_ready: bool
    estop_active: bool
    hardware_faults: tuple = ()
    valid: bool = True


class MeasurementGuard:
    """Acquisition and receipt times must share a qualified monotonic timebase."""
    def __init__(self, clock=time.perf_counter, freshness_s=.2):
        self.clock, self.freshness = clock, freshness_s
        self.reset()

    def reset(self):
        self.previous = None
        self.floor = self.clock()

    def fresh(self, frame):
        now = self.clock()
        if not (self.floor <= frame.acquired_s <= frame.received_s <= now
                and now-frame.acquired_s <= self.freshness):
            raise InstrumentError('BIAS_SENSOR_STALE_OR_FUTURE')

    def accept(self, frame, *, allow_repeated=False):
        if not isinstance(frame, BiasMeasurement):
            raise InstrumentError('BIAS_SENSOR_MISSING')
        if (not isinstance(frame.session_id,str) or not frame.session_id.strip() or frame.source != 'battery_bias_mock_sensor'
                or frame.quality != 'mock_independent_sensor'):
            raise InstrumentError('BIAS_SENSOR_UNQUALIFIED_SOURCE')
        for key in ('valid','cell_isolated','source_isolated','source_enabled','load_enabled',
                    'protection_ready','estop_active'):
            if type(getattr(frame,key)) is not bool:
                raise InstrumentError('BIAS_SENSOR_INVALID_STATUS')
        if not frame.valid:
            raise InstrumentError('BIAS_SENSOR_INVALID')
        if not isinstance(frame.hardware_faults,(tuple,list)) or not all(isinstance(v,str) and v for v in frame.hardware_faults):
            raise InstrumentError('BIAS_SENSOR_INVALID_FAULT_STATUS')
        for key in ('acquired_s','received_s','psu_current_A','cell_current_A','cell_voltage_V','cell_temperature_C'):
            finite_number(key,getattr(frame,key))
        if type(frame.sequence) is not int or frame.sequence < 0 or frame.psu_current_A < 0 or frame.cell_voltage_V <= 0:
            raise InstrumentError('BIAS_SENSOR_INVALID_VALUE')
        self.fresh(frame)
        if allow_repeated and self.previous and frame == self.previous:
            return frame  # Repeated access to one immutable, still-fresh acquisition.
        if self.previous:
            if frame.session_id != self.previous.session_id:
                raise InstrumentError('BIAS_SENSOR_SESSION_CHANGED')
            if (frame.sequence != self.previous.sequence+1 or frame.acquired_s < self.previous.acquired_s
                    or frame.received_s < self.previous.received_s):
                raise InstrumentError('BIAS_SENSOR_SEQUENCE_OR_TIME')
        if not frame.protection_ready or frame.estop_active or frame.hardware_faults:
            raise InstrumentError('BIAS_HARDWARE_PROTECTION_OR_ESTOP')
        self.previous = frame
        return frame


@dataclass(frozen=True)
class SourceCapabilities:
    """Manual sources need sensing AND separately verified disconnect control."""
    programmable_current: bool = False
    programmable_output: bool = False
    independent_disconnect: bool = False


class LatestBiasMeasurement:
    """Asynchronous mock acquisition boundary; no ESP32 transport is enabled.

    Publish each incoming packet once; repeated control reads do not consume a
    new sequence. Invalid/reordered arrivals are rejected at ingestion.
    """
    mock_only = True
    def __init__(self, clock=time.perf_counter, freshness_s=.2):
        self.guard = MeasurementGuard(clock,freshness_s)
        self.lock = threading.Lock()
        self.value = None
        self.error = None

    def publish(self, frame):
        with self.lock:
            try:self.value = self.guard.accept(frame)
            except Exception as exc:
                self.error = str(exc)
                raise

    def sample(self):
        with self.lock:
            if self.error:raise InstrumentError(self.error)
            if self.value is not None:self.guard.fresh(self.value)
            return self.value


class MockBiasSafety:
    mock_only = True
    def __init__(self, isolation):
        self.isolation = isolation
        self.source_isolated = True
        self.protection_ready = True
        self.estop_active = False
        self.hardware_faults = ()
        self.source_disconnect_stuck = False
        self.actions = []

    def isolate(self):
        # Cell/source disconnect is a separate obligation BEFORE load OFF.
        self.actions.append('request_cell_isolation_open')
        error = None
        try:self.isolation.open()
        except Exception as exc:error = exc
        self.actions.append('request_source_isolation_open')
        if not self.source_disconnect_stuck:
            self.source_isolated = True
        self.actions.append('request_instrument_outputs_disabled')
        if error is not None:raise InstrumentError('CELL_DISCONNECT_FAILED: '+str(error))

    def status(self):
        status = self.isolation.verify()
        return dict(cell_isolated=status.is_open, source_isolated=self.source_isolated,
            outputs_disabled=status.outputs_disabled, protection_ready=self.protection_ready,
            estop_active=self.estop_active, hardware_faults=list(self.hardware_faults))


class MockBiasSensors:
    mock_only = True
    def __init__(self, psu, load, safety, clock=time.perf_counter, voltage_V=3.65, temperature_C=25.):
        self.psu, self.load, self.safety, self.clock = psu, load, safety, clock
        self.voltage_V, self.temperature_C = voltage_V, temperature_C
        self.session = str(uuid.uuid4()); self.sequence = 0
        self.failure = None
        self.age_s = 0.
        self.cell_offset_A = 0.
        self.psu_offset_A = 0.
        self.last = None

    def sample(self):
        if self.failure == 'missing': return None
        if self.failure == 'timeout': raise InstrumentError('BIAS_SENSOR_COMMUNICATION_TIMEOUT')
        self.psu._advance(); self.load._advance()
        state = self.safety.status()
        # These are separate mock sensor channels over plant truth, not the
        # controller's requested/applied current. Offsets permit disagreement tests.
        supplied = 0. if state['source_isolated'] else self.psu.current_A
        cell = 0. if state['cell_isolated'] else supplied-self.load.current_A
        now = self.clock()
        frame = BiasMeasurement(self.session, self.sequence, now-self.age_s, now,
            'battery_bias_mock_sensor', 'mock_independent_sensor', supplied+self.psu_offset_A,
            cell+self.cell_offset_A, self.voltage_V, self.temperature_C,
            state['cell_isolated'],state['source_isolated'],self.psu.output_enabled,
            self.load.output_enabled,state['protection_ready'],state['estop_active'],
            tuple(state['hardware_faults']),self.failure != 'invalid')
        self.sequence += 1
        if self.failure == 'duplicate' and self.last: frame = replace(frame,sequence=self.last.sequence)
        if self.failure == 'nan': frame = replace(frame,psu_current_A=float('nan'))
        self.last = frame
        return frame


class BatteryBiasCoordinator(InstrumentCoordinator):
    """Reuse mock coordinator mapping/transitions; never accept hardware devices."""
    def __init__(self, psu, load, isolation, config=None, clock=time.perf_counter,
                 *, qualification=None, source_capabilities=None):
        self.source_capabilities = source_capabilities or SourceCapabilities(True,True,True)
        if not (self.source_capabilities.programmable_current and self.source_capabilities.programmable_output):
            raise ValueError("Manual source needs a sensing/disconnect adapter; physical Battery Bias remains disabled")
        config = config or BIAS_CONTROL
        self.qualification = qualification or MockBiasQualification()
        self.safety = MockBiasSafety(isolation)
        self.sensors = MockBiasSensors(psu,load,self.safety,clock)
        self.measurements = MeasurementGuard(clock,config.measurement_expiry_s)
        self.frame = None
        self.load_command_time = None
        self.on_recover = None
        super().__init__(psu,load,isolation,config,clock)

    def _safe_stop(self):
        errors = []
        try: self.safety.isolate()
        except Exception as error: errors.append('BIAS_ISOLATION: '+str(error))
        super()._safe_stop()
        self.shutdown_errors.extend(errors)
        try:state = self.safety.status()
        except Exception as error:
            state = {}
            self.shutdown_errors.append('BIAS_FEEDBACK_UNAVAILABLE: '+str(error))
        self.shutdown_verified = bool(self.shutdown_verified and not errors
            and state.get('cell_isolated') and state.get('source_isolated') and state.get('outputs_disabled'))
        if not self.shutdown_verified:
            self.shutdown_errors.append('BIAS_CELL_SOURCE_OR_OUTPUT_SHUTDOWN_NOT_VERIFIED')

    def _sample(self):
        frame = self.measurements.accept(self.sensors.sample(),allow_repeated=True)
        if self.state == State.READY and not frame.cell_isolated:
            raise InstrumentError('BIAS_READY_CELL_CONNECTED')
        if frame.cell_isolated and abs(frame.cell_current_A)>self.config.neutral_tolerance_A:
            raise InstrumentError('BIAS_ISOLATION_CURRENT_CONTRADICTION')
        q = self.qualification
        if not q.voltage_min_V <= frame.cell_voltage_V <= q.voltage_max_V or not q.temperature_min_C <= frame.cell_temperature_C <= q.temperature_max_C:
            raise InstrumentError('BIAS_MOCK_STATE_OUTSIDE_DEMONSTRATION_ENVELOPE')
        # These V/T bounds are mock qualification assumptions, not cell ratings.
        self.frame = frame
        return frame

    def _read(self, device):
        measured = super()._read(device)
        if device is self.psu:
            frame = self._sample()
            if self.state in (State.READY, State.RUNNING) and (
                    frame.source_isolated or not frame.source_enabled or not frame.load_enabled):
                raise InstrumentError('BIAS_SOURCE_OR_LOAD_NOT_AVAILABLE')
            if abs(frame.psu_current_A-measured.current_A)>self.config.tracking_tolerance_A:
                raise InstrumentError('BIAS_PSU_SENSOR_DISAGREEMENT')
            return replace(measured,current_A=frame.psu_current_A,acquired_s=frame.acquired_s)
        return measured

    def _validate_source(self, psu):
        # Unlike the original fixed-CC prototype, this mode explicitly permits
        # bounded varying source contribution. Never substitute the current limit.
        if psu.status.mode not in ('CC','CV'):
            raise InstrumentError('BIAS_UNKNOWN_SOURCE_MODE')

    def _bias_settled(self, psu):
        # Parent also checks fresh, stable branch currents and a neutral dwell.
        return self.frame is not None and self.frame.protection_ready

    def _net_current(self, psu, load):
        frame = self._sample()
        if abs(frame.acquired_s-load.acquired_s) > self.config.measurement_expiry_s:
            raise InstrumentError('BIAS_SENSOR_LOAD_SKEW')
        if self.state == State.RUNNING:
            if frame.cell_isolated or frame.source_isolated:
                raise InstrumentError('BIAS_ISOLATION_UNEXPECTEDLY_OPEN')
            difference = frame.psu_current_A-load.current_A
            if abs(frame.cell_current_A-difference)>self.config.tracking_tolerance_A:
                raise InstrumentError('BIAS_NET_SENSOR_DISAGREEMENT')
            value = frame.cell_current_A
        else:
            # With cell isolated, measured cell current is zero even while the
            # simplified isolated mock branch currents are still balancing.
            difference = psu.current_A-load.current_A
            value = difference
        self.last.update(cell_sensor_frame=asdict(frame), independent_cell_current_A=frame.cell_current_A,
            contemporaneous_branch_net_A=difference)
        return value

    def _before_isolation_close(self):
        psu = self._read(self.psu)
        load = self._read(self.load)
        frame = self._sample()
        self._fresh_demand(self._closing_demand)
        self.measurements.fresh(frame)
        if (not frame.source_enabled or not frame.load_enabled or
                not psu.status.output_enabled or not load.status.output_enabled):
            raise InstrumentError('BIAS_STARTUP_OUTPUT_STATE')
        stamps = (psu.acquired_s,load.acquired_s,frame.acquired_s)
        if self.clock()-min(stamps)>self.config.measurement_expiry_s:
            raise InstrumentError('BIAS_STARTUP_STALE_SET')
        if abs(frame.psu_current_A-load.current_A)>self.config.neutral_tolerance_A:
            raise InstrumentError('BIAS_STARTUP_BALANCE_CHANGED')
        if not self._closing_valid():
            raise InstrumentError('BIAS_STARTUP_DEMAND_INVALIDATED')
        if not frame.cell_isolated or frame.source_isolated:
            raise InstrumentError('BIAS_STARTUP_ISOLATION_STATE')
        if abs(frame.cell_current_A)>self.config.neutral_tolerance_A:
            raise InstrumentError('BIAS_STARTUP_CELL_NOT_NEUTRAL')
        if abs(psu.voltage_V-frame.cell_voltage_V)>self.qualification.startup_voltage_difference_V:
            raise InstrumentError('BIAS_STARTUP_VOLTAGE_MISMATCH')

    def step(self, demand, unavailable='', still_valid=lambda: True):
        self._closing_demand = demand
        self._closing_valid = still_valid
        return super().step(demand,unavailable,still_valid)

    def _command_load(self, target):
        now = self.clock()
        dt = 1/self.config.control_hz if self.load_command_time is None else min(
            max(0.,now-self.load_command_time),1/self.config.control_hz)
        previous = self.load.setpoint_A
        budget = self.qualification.branch_slew_A_per_s*dt
        command = previous+max(-budget,min(budget,target-previous))
        command = max(self.config.eload_current_min_A,min(self.config.eload_current_max_A,command))
        self.load.set_current(command,self.config.io_timeout_s)
        self.load_command_time = self.clock()
        self.last.update(previous_load_command_A=previous,load_slew_budget_A=budget,
                         bias_load_target_A=target,branch_slew_limited=command!=target)
        return command

    def arm(self):
        if self.state != State.DISARMED:
            raise ValueError('Explicit recovery and disarmed state required before arming')
        try:
            self._sample()  # qualify protection/sensors before any mock enable
            super().arm()
            if self.state == State.READY:
                self.safety.source_isolated = False
                self.load_command_time = self.clock()
        except Exception as error:
            self.trip('BIAS_ARM_FAILED: '+str(error))

    def recover(self):
        if self.state != State.FAULT:
            raise ValueError('Explicit recovery only in FAULT')
        self.measurements.reset()
        super().recover()
        if self.state == State.DISARMED and self.on_recover:
            self.on_recover()  # Explicit MOCK recovery reanchors configured mock SOC.

    def snapshot(self):
        try:result = super().snapshot()
        except Exception as error:
            result = dict(state=self.state.value,fault=self.fault_reason,shutdown_verified=False,
                shutdown_errors=self.shutdown_errors+[str(error)],measurements_retained=True,
                isolation=dict(is_open=None,outputs_disabled=None))
        try:safety = self.safety.status()
        except Exception as error:safety = dict(feedback_error=str(error),cell_isolated=None,source_isolated=None,outputs_disabled=None)
        result.update(control_mode='battery_bias_mock', physical_operation_enabled=False,
            bias_safety=safety, measurement_source='MOCK independent sensor model')
        return result


class BiasCellStream:
    """Existing Coulomb Counter/OCV/Rint, driven only by independent mock channel."""
    def __init__(self, config, clock=time.perf_counter, isolation_tolerance_A=.002):
        self.isolation_tolerance_A = finite_number("isolation tolerance",isolation_tolerance_A)
        if self.isolation_tolerance_A < 0:raise ValueError("Negative isolation tolerance")
        if config.get('purpose') != 'unvalidated_mock_assumptions':
            raise ValueError('Explicit unvalidated mock model configuration required')
        self.parameters = RintParameters(**config['parameters'])
        self.initial_soc = config['mock_state']['soc_fraction']
        self.observer = LiveCellObserver(self.parameters.capacity_Ah,self.initial_soc,
            clock=clock,source_profile='battery-bias-mock',mock_pause=True)
        self.estimator = RintEstimator(self.parameters)
        self.clock = clock; self.sequence = 0; self.previous_frame = None
        self.paused = False

    def reset(self):
        self.observer.reset(self.initial_soc)
        self.sequence = 0; self.previous_frame = None

    def update(self, snapshot):
        data = snapshot.get('cell_sensor_frame')
        if snapshot['state']=='DISARMED' and not self.paused:
            safety=snapshot.get('bias_safety',{})
            if not snapshot.get('shutdown_verified') or not safety.get('cell_isolated'):
                self.observer.unavailable('BIAS_PAUSE_ISOLATION_UNVERIFIED')
            elif not self.observer.error:
                # Preserve the last estimate, explicitly exclude the isolated gap.
                soc=self.observer.estimate.soc if self.observer.estimate else self.initial_soc
                self.observer.reset(soc)
                self.sequence=0;self.previous_frame=None
            self.paused=True
        if snapshot['state'] in ('READY','RUNNING'):self.paused=False
        active = snapshot['state'] in ('READY','RUNNING') and not snapshot.get('measurements_retained')
        if data and active and (data['session_id'],data['sequence']) != self.previous_frame:
            measurement = CellMeasurement(data['session_id'],data['acquired_s'],data['cell_voltage_V'],
                0. if data['cell_isolated'] and abs(data['cell_current_A'])<=self.isolation_tolerance_A else data['cell_current_A'],data['cell_temperature_C'])
            sample = CellSample(measurement,self.sequence,data['received_s'],
                source='battery_bias_mock_sensor',quality='mock_independent_sensor',
                isolation_open=data['cell_isolated'],voltage_source='mock_sensor_voltage',
                temperature_source='mock_sensor_temperature')
            self.observer.accept(sample)
            self.sequence += 1; self.previous_frame = (data['session_id'],data['sequence'])
        if snapshot['state']=='FAULT':self.observer.unavailable('BIAS_CONTROLLER_FAULT')
        state = self.observer.snapshot()
        details = dict(cell_observer_state=state['state'],cell_observer_error=state['error'],
            cell_timing={k:state[k] for k in ('mock_pause_policy','excluded_intervals','excluded_time_s',
                'last_excluded_gap_s','publication_host_s','publication_delay_s','consumed_host_s','freshness_s','gap_fault_s',
                'observer_update_interval_s','publication_interval_s')},
            cell_observer_generation=state['generation'],cell_measurement_source='battery_bias_mock_sensor',
            cell_measurement_age_s=state['age_s'],cell_measurements_retained=state['retained'],
            isolated_gap_excluded=self.paused,raw_sensor_current_A=data['cell_current_A'] if data else None,
            isolation_noise_policy='Verified isolated current within neutral tolerance integrates as zero; raw retained',
            sop_model_valid=False)
        if state['sample']:
            m = state['sample']['measurement']
            details.update(cell_mock_measured_current_A=m['net_cell_current_A'],
                cell_sensor_voltage_V=m['cell_voltage_V'],sop_mock_temperature_C=m['cell_temperature_C'])
        if state['state']=='VALID':
            details.update(self.estimator.estimate(state['estimate']['soc'],state['sample']['measurement']['cell_temperature_C']))
        return details


class BatteryBiasService(MockInstrumentService):
    def __init__(self, output, config=None, *, sop_config=None):
        config = config or BIAS_CONTROL
        self.cell_stream = BiasCellStream(sop_config,isolation_tolerance_A=config.neutral_tolerance_A) if sop_config else None
        super().__init__(output,config,coordinator_factory=BatteryBiasCoordinator)
        if self.cell_stream:self.coordinator.on_recover=self.cell_stream.reset
        path = self.output/'config.json'
        settings = json.loads(path.read_text())
        settings.update(control_mode='battery_bias_mock',physical_operation_enabled=False,
            measurements='independent mock sensor channels; V/T synthetic; no physical cell',
            sop_config=sop_config)
        path.write_text(json.dumps(settings,indent=2)+'\n')

    def _decorate_snapshot(self, snapshot):
        if self.cell_stream:
            model = self.cell_stream.update(snapshot)
            if model['cell_observer_state']=='FAULT' and snapshot['state'] in ('READY','RUNNING'):
                self.coordinator.trip('BIAS_CELL_OBSERVER: '+model['cell_observer_error'])
                snapshot = self.coordinator.snapshot()
            snapshot['cell_model_state'] = model
        return snapshot

    def _acceptance(self, events, final):
        return bias_acceptance(events,self.config,final,self.failed,self.arming_requested)


def bias_acceptance(events,config,final,worker_error=None,require_running=False):
    """Same fault/freshness/range checks, explicit variable-source/branch-slew policy.

    The transition record retains an isolated startup sample: assess it as READY,
    not evidence of a connected cell. Preserve every FAULT/retained record.
    """
    assessed=[dict(e,state='READY') if e['state']=='RUNNING' and
              e.get('cell_sensor_frame',{}).get('cell_isolated',True) else e for e in events]
    result=instrument_acceptance(assessed,config,final,worker_error,require_running)
    running=[e for e in assessed if e['state']=='RUNNING']
    def observed(predicate):
        return all(predicate(e) for e in running) if running else None
    checks=result['checks'];checks.pop('instruments_in_cc')
    tol=config.numeric_tolerance_A
    def mapping(e):
        f=e.get('cell_sensor_frame',{})
        if not f:return False
        return (abs(e['branch_net_A']-f['cell_current_A'])<=tol and
            abs(f['cell_current_A']-e['contemporaneous_branch_net_A'])<=config.tracking_tolerance_A and
            abs(e['load']['setpoint_A']-e['load_command_A'])<=tol and
            abs(e['load_target_A']-(e['psu']['current_A']-e['applied_target_A']))<=tol and
            abs(e['tracking_error_A']-(f['cell_current_A']-e['applied_target_A']))<=tol)
    checks['readback_mapping_consistent']=observed(mapping)
    checks['instrument_modes_qualified']=observed(lambda e:e['psu']['status']['mode'] in ('CC','CV') and e['load']['status']['mode']=='CC')
    checks['branch_slew_observed']=observed(lambda e:abs(e['load_command_A']-e['previous_load_command_A'])<=e['load_slew_budget_A']+tol)
    checks['independent_sensor_qualified']=observed(lambda e:
        e['cell_sensor_frame']['source']=='battery_bias_mock_sensor' and
        e['cell_sensor_frame']['quality']=='mock_independent_sensor' and
        e['cell_sensor_frame']['valid'] and e['cell_sensor_frame']['protection_ready'] and
        not e['cell_sensor_frame']['estop_active'] and not e['cell_sensor_frame']['hardware_faults'] and
        not e['cell_sensor_frame']['source_isolated'])
    safety=final.get('bias_safety',{})
    checks['cell_source_shutdown_verified']=bool(final.get('shutdown_verified') and
        safety.get('cell_isolated') and safety.get('source_isolated') and safety.get('outputs_disabled'))
    passed=all(v is not False for v in checks.values()) and (not require_running or all(v is True for v in checks.values()))
    control=False if any(v is False for v in checks.values()) else True if all(v is True for v in checks.values()) else None
    result.update(passed=passed,status=assessment(passed),control_status=assessment(control),
        checks=checks,check_status={k:assessment(v) for k,v in checks.items()},
        assessment_basis='Battery Bias MOCK: qualified CV/CC source, branch slew and independent cell sensor')
    return result
