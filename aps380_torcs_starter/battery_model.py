"""Offline CSV pipeline. No physical hardware communication."""
import csv
from dataclasses import replace
from pathlib import Path
from ev_model import VehicleParameters, vehicle_power
from cell_scaling import CellParameters, scale_to_cell, auto_scale_profile
from numerical_validation import DEFAULT_TIMING, field_number, finite_number

FIELDS = ("time_s", "speed_mps", "throttle", "brake")


def validate_telemetry(rows, *, timing=DEFAULT_TIMING):
    result = []
    last_t = None
    for n, row in enumerate(rows, 2):
        try:
            item = {field: field_number(field, row[field]) for field in FIELDS}
        except (KeyError, ValueError, TypeError) as ex:
            raise ValueError(f"Missing or invalid numeric telemetry at row {n}") from ex
        if item['time_s'] < 0 or item['speed_mps'] < 0:
            raise ValueError(f"Negative time or speed at row {n}")
        if last_t is not None:
            try:
                timing.interval(last_t, item['time_s'])
            except ValueError as error:
                raise ValueError(f"Invalid time interval at row {n}: {error}") from error
        if not 0 <= item['throttle'] <= 1 or not 0 <= item['brake'] <= 1:
            raise ValueError(f"Pedals must be between 0 and 1 at row {n}")
        result.append(item)
        last_t = item['time_s']
    if not result:
        raise ValueError("Expected nonempty telemetry")
    return result


def read_telemetry(path, *, timing=DEFAULT_TIMING):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError(f"Expected CSV columns: {FIELDS}")
        return validate_telemetry(reader, timing=timing)


def process(rows, vehicle=VehicleParameters(), cell=CellParameters(), *, timing=DEFAULT_TIMING):
    """Calculate one batch; optional TimingPolicy bounds never fill missing data."""
    out = []
    prev = None
    for x in validate_telemetry(rows, timing=timing):
        t, v = x['time_s'], x['speed_mps']
        dt = 0.0 if prev is None else t - prev['time_s']
        a = finite_number('interval acceleration', 0.0 if prev is None else (v - prev['speed_mps']) / dt)
        mean_v = finite_number('interval mean speed', v if prev is None else (v + prev['speed_mps']) / 2)
        power = vehicle_power(mean_v, a, vehicle)
        out.append({**x, 'interval_s': dt, 'model_speed_mps': mean_v,
                    'accel_mps2': a, **power,
                    **scale_to_cell(power['vehicle_battery_power_W'], cell)})
        prev = x
    return out


def process_auto_scaled(rows, target_current_A, vehicle=VehicleParameters(),
                        cell=CellParameters(), *, timing=DEFAULT_TIMING):
    """Optional complete-profile processing, returning (rows, scaling summary).

    Existing process() stays unchanged. Timing, vehicle calculations and Stage 1
    checks run before choosing a factor from the entire unclipped profile.
    """
    baseline = process(rows, vehicle, replace(cell, experiment_scale=1.0), timing=timing)
    scaled, summary = auto_scale_profile(
        (row['vehicle_battery_power_W'] for row in baseline), target_current_A, cell)
    return [dict(row, **cell_row) for row, cell_row in zip(baseline, scaled)], summary


def save_results(rows, filename):
    if not rows:
        raise ValueError("Cannot save empty results")
    Path(filename).parent.mkdir(parents=True, exist_ok=True)
    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
