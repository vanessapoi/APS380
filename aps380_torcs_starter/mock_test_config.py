"""Session-local Battery Bias MOCK configuration; never a hardware approval.

Only experiment inputs are editable. Protection, timing, model equations and
physical-controller settings cannot be supplied through this schema.
"""
from dataclasses import asdict, dataclass, replace
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from battery_bias import BIAS_CONTROL, MockBiasQualification
from cell_sop import RintEstimator, RintParameters
from torcs_live import BASE, LiveProcessor

FIELDS = {
    'initial_soc_fraction', 'maximum_charge_A', 'maximum_discharge_A',
    'sop_discharge_ceiling_A', 'mock_psu_contribution_A',
    'eload_min_A', 'eload_max_A', 'experiment_scale',
}
MOCK_CAPABILITIES = {
    'prototype': dict(label='Prototype MOCK (2 A discharge / 3 A load)', discharge_A=2.,load_A=3.),
    'extended-5a': dict(label='Extended MOCK ONLY (5 A discharge / 6 A load)', discharge_A=5.,load_A=6.),
}


def required_eload_range(discharge_A, charge_A, source_A):
    """Required steady-state branch span, not instrument capacity or a command.

    Negative minimum is deliberately retained: clipping it would hide an
    impossible charging request. Preview may calculate wider, unsupported spans.
    """
    for name,value in (('Discharge',discharge_A),('Charge',charge_A),('Source',source_A)):
        try: valid=type(value) in (int,float) and math.isfinite(value) and value>=0
        except OverflowError: valid=False
        if not valid:raise ValueError(name+' must be a finite nonnegative current in A')
    high=source_A+discharge_A
    try: valid_high=math.isfinite(high)
    except OverflowError: valid_high=False
    if not valid_high:raise ValueError('Required eLoad range overflow')
    return dict(minimum_A=source_A-charge_A,maximum_A=high)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result: raise ValueError('Duplicate configuration field: '+key)
        result[key] = value
    return result


def _constant(value):
    raise ValueError('Nonfinite JSON value: '+value)


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      object_pairs_hook=_pairs, parse_constant=_constant)


@dataclass(frozen=True)
class MockTestConfig:
    control: object
    model: dict
    scaling: dict
    source_A: float
    audit: dict


def load_mock_test_config(path):
    """Validate fully before a service, socket, output directory or TORCS starts."""
    path = Path(path)
    raw = path.read_bytes()
    requested = json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_constant)
    return resolve_mock_test_config(requested,source_file=path.name,
                                    source_sha256=hashlib.sha256(raw).hexdigest())


def resolve_mock_test_config(requested, *, source_file='mock-setup-gui', source_sha256=None):
    """One validator/resolver for file and GUI inputs; no controller or file writes."""
    requested=deepcopy(requested)
    if not isinstance(requested, dict): raise ValueError('Expected a mock experiment JSON object')
    required = FIELDS | {'schema_version', 'purpose'}
    if set(requested)-required-{'description','mock_capability'}:
        raise ValueError('Unknown mock fields: '+', '.join(sorted(set(requested)-required-{'description','mock_capability'})))
    if required-set(requested):
        raise ValueError('Missing mock fields: '+', '.join(sorted(required-set(requested))))
    if type(requested['schema_version']) is not int or requested['schema_version'] != 1:
        raise ValueError('Only mock schema_version 1 is supported')
    if requested['purpose'] != 'battery_bias_mock_experiment':
        raise ValueError('Expected purpose battery_bias_mock_experiment; never a hardware profile')
    if 'description' in requested and not isinstance(requested['description'], str):
        raise ValueError('description must be text')
    capability=requested.get('mock_capability','prototype')
    if not isinstance(capability,str) or capability not in MOCK_CAPABILITIES:
        raise ValueError('Unknown mock_capability; choose prototype or extended-5a')
    limits=MOCK_CAPABILITIES[capability]
    for key in FIELDS:
        value = requested[key]
        try: valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError: valid = False
        if not valid:
            raise ValueError(key+' must be a finite number, not text or boolean')
    z, charge, discharge, sop, source, low, high, scale = (
        requested[k] for k in ('initial_soc_fraction','maximum_charge_A','maximum_discharge_A',
        'sop_discharge_ceiling_A','mock_psu_contribution_A','eload_min_A','eload_max_A','experiment_scale'))
    # The wider envelope is explicit and session-local, never a global change.
    if not 0 <= z <= 1: raise ValueError('Initial SOC must be a fraction in [0,1]')
    if not 0 <= charge <= BIAS_CONTROL.charge_limit_A: raise ValueError('Charge magnitude must be 0..1 A')
    if not 0 <= discharge <= limits['discharge_A']: raise ValueError(f'Discharge magnitude must be 0..{limits["discharge_A"]:g} A for {capability}')
    if not 0 <= sop <= discharge: raise ValueError('SOP ceiling must be 0..maximum_discharge_A')
    if not 0 <= source <= BIAS_CONTROL.psu_cc_setpoint_A: raise ValueError('Mock source contribution must be 0..1 A')
    if not 0 <= low <= high <= limits['load_A']: raise ValueError(f'eLoad range must lie within 0..{limits["load_A"]:g} A for {capability}')
    if high < BIAS_CONTROL.psu_cc_setpoint_A:
        raise ValueError('eLoad maximum must support the unchanged 1 A configured PSU bias limit')
    if not 0 < scale <= 1: raise ValueError('experiment_scale must be >0 and <=1')
    if not low <= source <= high: raise ValueError('Source/load cannot establish neutral startup balance')
    required_load=required_eload_range(discharge,charge,source)
    if required_load['minimum_A']<0:
        raise ValueError(f'Charge request {charge:g} A exceeds imposed source {source:g} A; required eLoad minimum {required_load["minimum_A"]:g} A is negative')
    if required_load['minimum_A'] < low or required_load['maximum_A'] > high:
        raise ValueError(f'Required eLoad range {required_load["minimum_A"]:g} to {required_load["maximum_A"]:g} A is not covered by selected mock capability {low:g} to {high:g} A')
    control_options=dict(battery_current_min_A=-discharge,
        battery_current_max_A=charge, eload_current_min_A=low, eload_current_max_A=high)
    if capability=='extended-5a':control_options['transition_timeout_s']=None
    control = replace(BIAS_CONTROL,**control_options)
    if control.transition_timeout_s < BIAS_CONTROL.transition_timeout_s:
        control=replace(control,transition_timeout_s=BIAS_CONTROL.transition_timeout_s)
    # Includes existing neutral-bias and transition-timeout validation; no timeout
    # or slew override is accepted, and no physical limit is edited.
    startup_estimate = ((source-low)/MockBiasQualification().branch_slew_A_per_s
                        + control.settling_timeout_s + control.neutral_hold_s)
    if startup_estimate >= control.ready_timeout_s:
        raise ValueError('Cannot qualify startup within the unchanged READY timeout')
    model_path = BASE/'profiles/rint_sop_live_mock_example.json'
    scaling_path = BASE/'profiles/live_scaling_demo.json'
    vehicle_path = BASE/'profiles/tesla_model3_rwd.json'
    model = _read(model_path)
    model['mock_state']['soc_fraction'] = z
    model['parameters']['maximum_discharge_A'] = sop
    model['notes'] = 'Session-local MOCK experiment overrides; synthetic initial SOC/V/T and unvalidated model parameters; not physical protection.'
    scaling = _read(scaling_path)
    scaling['cell']['experiment_scale'] = scale
    processor = LiveProcessor(vehicle_path.read_bytes(), scaling, current_config=control)
    if processor.cell.capacity_Ah != model['parameters']['capacity_Ah']:
        raise ValueError('Scaling and SOC/SOP capacity assumptions differ')
    RintEstimator(RintParameters(**model['parameters'])).estimate(z, model['mock_state']['temperature_C'])
    audit = dict(schema_version=1, purpose='battery_bias_mock_experiment',
        physical_operation_enabled=False, source_file=source_file,
        source_sha256=source_sha256 or hashlib.sha256(json.dumps(requested,sort_keys=True,allow_nan=False).encode()).hexdigest(), requested=requested,
        overrides={key:requested[key] for key in sorted(FIELDS)} | ({'mock_capability':capability} if 'mock_capability' in requested else {}),
        effective=dict(control=asdict(control), sop_model=model, scaling=scaling,
            mock_capability=capability, mock_capability_label=limits['label'],
            timing_policy='Existing slew/freshness/tracking; extended-only transition budget derived by existing ControlConfig formula; never below baseline',
            minimum_transition_budget_s=control.minimum_transition_timeout_s,
            cell_parameters=asdict(processor.cell), mock_psu_contribution_A=source,
            psu_current_limit_A=control.psu_cc_setpoint_A,
            measured_psu_current='Runtime mock readbacks only; never inferred from setpoint',
            required_eload_range_A=required_load,
            startup_estimate_s=startup_estimate,
            startup_estimate_scope='Nominal ramp plus settling allowance, not an OS/I/O timing guarantee; runtime READY timeout remains enforced'),
        base_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (model_path,scaling_path,vehicle_path)})
    return MockTestConfig(control, model, scaling, source, audit)
