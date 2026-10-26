"""Equivalent-energy scaling; limits are offline examples, not cell ratings."""
from dataclasses import dataclass, asdict, replace
import math
from numerical_validation import finite_number

@dataclass(frozen=True)
class CellParameters:
    nominal_voltage_V: float = 3.6
    capacity_Ah: float = 3.0
    equivalent_pack_energy_Wh: float = 75000.0
    discharge_limit_A: float = 4.0
    charge_limit_A: float = 1.0
    experiment_scale: float = 1.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            finite_number(name, value)
            is_limit = name in ('discharge_limit_A', 'charge_limit_A')
            if value < 0 or (value == 0 and not is_limit):
                raise ValueError(f"{name} must be {'nonnegative' if is_limit else 'positive'}")


def scale_to_cell(vehicle_power_W, params=CellParameters()):
    finite_number('vehicle_power_W', vehicle_power_W)
    energy = finite_number('nominal cell energy', params.nominal_voltage_V * params.capacity_Ah)
    ratio = finite_number('cell-to-pack energy ratio', energy / params.equivalent_pack_energy_Wh)
    if energy <= 0 or ratio <= 0:
        raise ValueError('Cell energy scaling underflowed to zero')
    scaled_power = finite_number('scaled cell power', vehicle_power_W * ratio)
    requested_power = finite_number('requested cell power', scaled_power * params.experiment_scale)
    raw = finite_number('requested cell current', requested_power / params.nominal_voltage_V)
    command = max(-params.charge_limit_A, min(params.discharge_limit_A, raw))
    command_power = finite_number('command cell power', command * params.nominal_voltage_V)
    return {"cell_power_requested_W": requested_power,
            "cell_current_unclamped_A": raw, "cell_current_command_A": command,
            "cell_power_command_W": command_power,
            "command_saturated": int(raw != command)}


def auto_scale_profile(vehicle_powers_W, target_current_A, params=CellParameters()):
    """Scale one complete offline power profile; return (cell rows, summary).

    Compute raw currents at experiment_scale=1, then replace the configured
    experiment scale with min(1, target/absolute_peak). Do not multiply an old
    experiment scale into the result. Both directions share one factor; final
    directional clipping is independent. This is not a live normalization API.
    """
    if finite_number('target_current_A', target_current_A) <= 0:
        raise ValueError('target_current_A must be positive')
    if isinstance(vehicle_powers_W, (str, bytes)):
        raise ValueError('Expected a nonempty offline power profile')
    try:
        powers = list(vehicle_powers_W)
    except TypeError as error:
        raise ValueError('Expected a nonempty offline power profile') from error
    if not powers:
        raise ValueError('Expected a nonempty offline power profile')

    baseline_params = replace(params, experiment_scale=1.0)
    baseline = [scale_to_cell(power, baseline_params) for power in powers]
    if any(power != 0 and row['cell_current_unclamped_A'] == 0
           for power, row in zip(powers, baseline)):
        raise ValueError('Unscaled current profile underflowed a nonzero power sample')
    original_peak = max(abs(row['cell_current_unclamped_A']) for row in baseline)
    # Avoid target/peak overflow for already-small or all-zero profiles.
    calculated_scale = 1.0 if original_peak <= target_current_A else target_current_A/original_peak
    if finite_number('automatic experiment scale', calculated_scale) <= 0:
        raise ValueError('Automatic experiment scale underflowed to zero')

    scale = calculated_scale
    for _ in range(8):
        effective = replace(params, experiment_scale=scale)
        result = [scale_to_cell(power, effective) for power in powers]
        scaled_peak = max(abs(row['cell_current_unclamped_A']) for row in result)
        if scaled_peak <= target_current_A:
            break
        # P*r*scale/V can exceed the exact target by floating-point roundoff.
        # Adjust the single common factor downward, never individual samples.
        scale = math.nextafter(scale, 0.0)
        if scale <= 0:
            raise ValueError('Target is too small for representable profile scaling')
    else:
        raise ValueError('Unable to represent profile within target current')

    if any(before['cell_current_unclamped_A'] != 0 and after['cell_current_unclamped_A'] == 0
           for before, after in zip(baseline, result)):
        raise ValueError('Automatic scaling underflowed a nonzero profile sample')
    clipped = sum(row['command_saturated'] for row in result)
    summary = {
        'mode': 'complete_offline_profile',
        'target_current_A': target_current_A,
        'scale': scale,
        'calculated_scale': calculated_scale,
        'roundoff_adjusted': scale != calculated_scale,
        'original_current_peak_A': original_peak,
        'scaled_current_peak_A': scaled_peak,
        'command_current_peak_A': max(abs(row['cell_current_command_A']) for row in result),
        'samples': len(result),
        'remaining_clipped_samples': clipped,
        'remaining_clipped_fraction': clipped/len(result),
        'discharge_clipped_samples': sum(row['cell_current_unclamped_A'] > params.discharge_limit_A for row in result),
        'charge_clipped_samples': sum(row['cell_current_unclamped_A'] < -params.charge_limit_A for row in result),
        'discharge_limit_A': params.discharge_limit_A,
        'charge_limit_A': params.charge_limit_A,
        'configured_experiment_scale': params.experiment_scale,
        'baseline_experiment_scale': 1.0,
        'scale_policy': 'Replace configured experiment_scale; reduce only; independent final clipping',
        'status': 'Offline experiment target; not a cell rating or hardware safety limit',
    }
    return result, summary
