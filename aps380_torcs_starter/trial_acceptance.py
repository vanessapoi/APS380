"""Explicit software acceptance; never a physical safety certification."""
import math
from prototype_current_config import CELL_CURRENT_CONVENTION, CURRENT_SCHEMA_VERSION


def _distribution(values):
    values = sorted(values)
    if not values:
        return None
    return dict(max=values[-1], p95=values[math.ceil(.95*len(values))-1])


def assessment(value):
    return 'NOT ASSESSED' if value is None else 'PASS' if value else 'FAIL'


def _observed_check(values, predicate, faults=()):
    if faults:
        return False
    return all(predicate(v) for v in values) if values else None


def _complete_running_record(event):
    """Missing or malformed evidence must not become an operational PASS."""
    numeric=('requested_A','permitted_A','applied_target_A','branch_net_A',
             'mock_cell_current_A','tracking_error_A','demand_error_A',
             'command_age_s','psu_measurement_age_s','load_measurement_age_s')
    def number(v):
        return type(v) in (int,float) and math.isfinite(v)
    if not all(number(event.get(k)) for k in numeric):return False
    if type(event.get('direction_ok')) is not bool:return False
    if type(event.get('active_direction')) is not int or event['active_direction'] not in (-1,0,1):return False
    if not isinstance(event.get('isolation'),dict):return False
    for key in ('psu','load'):
        branch=event.get(key)
        if not isinstance(branch,dict):return False
        if not all(number(branch.get(k)) for k in ('current_A','setpoint_A')):return False
        if not isinstance(branch.get('status'),dict):return False
        status=branch['status']
        if type(status.get('output_enabled')) is not bool:return False
        if not all(isinstance(status.get(k),str) for k in ('mode','fault')):return False
    return True


def instrument_acceptance(events, config, final, worker_error=None, require_running=False):
    """A recovered or deliberately injected fault still fails normal operation.
    Fault-response evidence is separate and cannot override that result.
    """
    active = [e for e in events if e['state'] == 'RUNNING']
    faults = sorted({e['fault'] for e in events if e.get('fault')})
    transactions = [v for e in events for device in e.get('transactions', {}).values()
                    for v in device if v.get('event') == 'transaction']
    failures = [v for v in transactions if v.get('failure')]
    # Fault/disarmed snapshots retain historical readbacks for diagnosis. Their
    # original acquisition ages are not new evidence of healthy communication.
    measured = [e for e in events if not e.get('measurements_retained', e['state'] not in ('READY', 'RUNNING'))]
    command_ages = [e['command_age_s'] for e in events if 'command_age_s' in e and
                    not e.get('measurements_retained', False)]
    measurement_ages = [e[key] for e in measured for key in
                        ('psu_measurement_age_s', 'load_measurement_age_s') if key in e]
    tracking = [abs(e['tracking_error_A']) for e in active if 'tracking_error_A' in e]
    demand_errors = [abs(e['demand_error_A']) for e in active if 'demand_error_A' in e]
    freshness_faults = [f for f in faults if any(word in f for word in
                       ('EXPIRED', 'STALE', 'FUTURE', 'INVALIDATED', 'SESSION_CHANGED'))]
    measurement_faults = [f for f in freshness_faults if 'MEASUREMENT' in f or 'READBACK' in f]
    command_faults = [f for f in freshness_faults if f not in measurement_faults]
    tracking_faults = [f for f in faults if any(word in f for word in
                      ('TRACKING', 'DIRECTION', 'TRANSITION', 'LIMIT'))]
    fault_records = [e for e in events if e['state'] == 'FAULT']
    shutdown = final.get('isolation', {})
    branches=[e for e in active if _complete_running_record(e)]
    def mapping_consistent(e):
        net=e['psu']['current_A']-e['load']['current_A']
        return all(abs(a-b)<=config.numeric_tolerance_A for a,b in (
            (e['branch_net_A'],net),(e['mock_cell_current_A'],net),
            (e['tracking_error_A'],net-e['applied_target_A']),
            (e['demand_error_A'],net-e['permitted_A']),
            (e['load']['setpoint_A'],e['psu']['current_A']-e['applied_target_A'])))
    checks = dict(
        worker_healthy=worker_error is None,
        coordinator_fault_free=not faults and not fault_records and final['state'] != 'FAULT',
        communication_healthy=_observed_check(transactions,lambda t:not t.get('failure')),
        running_records_complete=_observed_check(active,_complete_running_record),
        current_convention_consistent=_observed_check(active,lambda e:
            e.get('cell_current_convention')==CELL_CURRENT_CONVENTION and
            type(e.get('current_schema_version')) is int and e['current_schema_version']==CURRENT_SCHEMA_VERSION),
        readback_mapping_consistent=_observed_check(branches,mapping_consistent),
        running_path_enabled=_observed_check(branches,lambda e:
            e['isolation'].get('is_open') is False and e['isolation'].get('outputs_disabled') is False and
            all(e[k]['status'].get('output_enabled') is True for k in ('psu','load'))),
        tracking_within_policy=_observed_check(tracking, lambda v: v <= config.tracking_tolerance_A, tracking_faults),
        current_direction_expected=_observed_check(branches,lambda e: e['direction_ok'] and
            (abs(e['branch_net_A'])<=config.direction_tolerance_A or
             (e['branch_net_A']>0)-(e['branch_net_A']<0)==e['active_direction']),
            [f for f in faults if 'DIRECTION' in f]),
        commands_fresh=_observed_check(command_ages, lambda v: 0 <= v <= config.command_expiry_s, command_faults),
        measurements_fresh=_observed_check(measurement_ages, lambda v: 0 <= v <= config.measurement_expiry_s, measurement_faults),
        instruments_in_cc=_observed_check(branches, lambda e: all(e[k]['status']['mode']=='CC' for k in ('psu','load')),
            [f for f in faults if 'NOT_CC' in f]),
        psu_setpoint_fixed=_observed_check(branches, lambda e: abs(e['psu']['setpoint_A']-config.psu_cc_setpoint_A)<=config.numeric_tolerance_A,
            [f for f in faults if 'SETPOINT_CHANGED' in f]),
        branch_setpoints_in_range=_observed_check(branches, lambda e:
            config.psu_current_min_A<=e['psu']['setpoint_A']<=config.psu_current_max_A and
            config.eload_current_min_A<=e['load']['setpoint_A']<=config.eload_current_max_A),
        measured_battery_in_range=_observed_check([e['branch_net_A'] for e in active if 'branch_net_A' in e],
            lambda v: config.battery_current_min_A-config.tracking_tolerance_A<=v<=config.battery_current_max_A+config.tracking_tolerance_A,
            [f for f in faults if 'MEASURED_DIRECTIONAL_LIMIT' in f]),
        outputs_disabled=shutdown.get('outputs_disabled') is True,
        isolation_open=shutdown.get('is_open') is True,
        shutdown_verified=final.get('shutdown_verified') is True,
        shutdown_commands_healthy=not final.get('shutdown_errors'),
        running_observed=bool(active) if require_running or active else None)
    control_checks = ('tracking_within_policy', 'current_direction_expected',
        'commands_fresh', 'measurements_fresh', 'running_observed',
        'running_records_complete','current_convention_consistent','readback_mapping_consistent',
        'running_path_enabled','instruments_in_cc','psu_setpoint_fixed','branch_setpoints_in_range',
        'measured_battery_in_range','communication_healthy')
    passed = all(v is not False for v in checks.values()) and (
        not require_running or all(checks[k] is True for k in control_checks))
    control_ok = (False if any(checks[k] is False for k in control_checks+('worker_healthy','coordinator_fault_free')) else
                  True if all(checks[k] is True for k in control_checks) else None)
    return dict(passed=passed, status=assessment(passed), control_status=assessment(control_ok),
                checks=checks, check_status={k:assessment(v) for k,v in checks.items()}, final_state=final['state'],
                faults=faults, worker_error=worker_error, running_cycles=len(active),
                communication_failure_count=len(failures),
                tracking_error_abs_A=_distribution(tracking), demand_error_abs_A=_distribution(demand_errors),
                command_age_s=_distribution(command_ages), measurement_age_s=_distribution(measurement_ages),
                freshness_faults=freshness_faults,
                retained_measurement_records=sum(bool(e.get('measurements_retained',
                    e['state'] == 'FAULT' and ('psu' in e or 'load' in e))) for e in events),
                final_measurement_context=final.get('measurement_context', 'not_recorded'),
                settling_cycles=sum(e.get('transition_phase') != 'TRACK' for e in active),
                directional_saturation_cycles=sum(bool(e.get('directional_saturated')) for e in active),
                fault_handling=dict(fault_observed=bool(fault_records),
                    every_fault_shutdown_verified=all(e.get('shutdown_verified') and
                        e['isolation']['is_open'] and e['isolation']['outputs_disabled'] for e in fault_records)
                        if fault_records else None))


def trial_acceptance(telemetry_checks, process, policy, instruments=None, course=None):
    if policy not in ('smoke', 'full-course'):
        raise ValueError('Unknown acceptance policy')
    # Duration/operator stops are intentional only when this launcher actually
    # terminated its own still-running process. An observed crash never qualifies.
    process_ok = (not process['launched'] or process['exit_code'] == 0 or
                  (process['terminated_by_launcher'] and process['stop_reason'] in
                   ('duration_elapsed', 'operator_stop')))
    telemetry = dict(passed=all(v is True for v in telemetry_checks.values()), checks=telemetry_checks,
                     check_status={k:assessment(v) for k,v in telemetry_checks.items()})
    telemetry['status'] = assessment(telemetry['passed'])
    full_course = dict(required=policy == 'full-course', assessed=course is not None,
                       completed=bool(course.get('passed')) if course is not None else None)
    full_course['status'] = assessment(full_course['completed'])
    instrument_ok = instruments is None or instruments['passed']
    passed = (telemetry['passed'] and process_ok and instrument_ok and
              (policy == 'smoke' or full_course['completed'] is True))
    return dict(policy=policy, passed=passed, status=assessment(passed), telemetry=telemetry,
                process=dict(passed=process_ok, status=assessment(process_ok), **process),
                instruments=instruments if instruments is not None else dict(status='NOT ASSESSED', passed=None),
                full_course=full_course)
