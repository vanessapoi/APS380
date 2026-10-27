"""Explicit software acceptance; never a physical safety certification."""
import math


def _distribution(values):
    values = sorted(values)
    if not values:
        return None
    return dict(max=values[-1], p95=values[math.ceil(.95*len(values))-1])


def instrument_acceptance(events, config, final, worker_error=None, require_running=False):
    """A recovered or deliberately injected fault still fails normal operation.
    Fault-response evidence is separate and cannot override that result.
    """
    active = [e for e in events if e['state'] == 'RUNNING']
    faults = sorted({e['fault'] for e in events if e.get('fault')})
    failures = [v for e in events for device in e.get('transactions', {}).values()
                for v in device if v.get('event') == 'transaction' and v.get('failure')]
    command_ages = [e['command_age_s'] for e in events if 'command_age_s' in e]
    measurement_ages = [e[key] for e in events for key in
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
    checks = dict(
        worker_healthy=worker_error is None,
        coordinator_fault_free=not faults and not fault_records and final['state'] != 'FAULT',
        communication_healthy=not failures,
        tracking_within_policy=not tracking_faults and all(v <= config.tracking_tolerance_A for v in tracking),
        current_direction_expected=all(e.get('direction_ok', True) for e in active),
        commands_fresh=not command_faults and all(0 <= v <= config.command_expiry_s for v in command_ages),
        measurements_fresh=not measurement_faults and all(0 <= v <= config.measurement_expiry_s for v in measurement_ages),
        outputs_disabled=shutdown.get('outputs_disabled') is True,
        isolation_open=shutdown.get('is_open') is True,
        shutdown_verified=final.get('shutdown_verified') is True,
        shutdown_commands_healthy=not final.get('shutdown_errors'),
        running_observed=bool(active) if require_running else True)
    return dict(passed=all(checks.values()), checks=checks, final_state=final['state'],
                faults=faults, worker_error=worker_error, running_cycles=len(active),
                communication_failure_count=len(failures),
                tracking_error_abs_A=_distribution(tracking), demand_error_abs_A=_distribution(demand_errors),
                command_age_s=_distribution(command_ages), measurement_age_s=_distribution(measurement_ages),
                freshness_faults=freshness_faults,
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
    telemetry = dict(passed=all(telemetry_checks.values()), checks=telemetry_checks)
    full_course = dict(required=policy == 'full-course', assessed=course is not None,
                       completed=bool(course.get('passed')) if course is not None else None)
    instrument_ok = instruments is None or instruments['passed']
    passed = (telemetry['passed'] and process_ok and instrument_ok and
              (policy == 'smoke' or full_course['completed'] is True))
    return dict(policy=policy, passed=passed, telemetry=telemetry,
                process=dict(passed=process_ok, **process),
                instruments=instruments if instruments is not None else dict(status='not_enabled', passed=None),
                full_course=full_course)
