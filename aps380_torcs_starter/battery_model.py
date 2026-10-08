"""Offline CSV pipeline. No physical hardware communication."""
import csv
import math
from pathlib import Path
from ev_model import VehicleParameters, vehicle_power
from cell_scaling import CellParameters, scale_to_cell

FIELDS = ("time_s", "speed_mps", "throttle", "brake")


def validate_telemetry(rows):
    result = []
    last_t = None
    for n, row in enumerate(rows, 2):
        try:
            item = {field: float(row[field]) for field in FIELDS}
        except (KeyError, ValueError, TypeError) as ex:
            raise ValueError(f"Missing or invalid numeric telemetry at row {n}") from ex
        if not all(math.isfinite(x) for x in item.values()):
            raise ValueError(f"Nonfinite telemetry at row {n}")
        if item['time_s'] < 0 or item['speed_mps'] < 0:
            raise ValueError(f"Negative time or speed at row {n}")
        if last_t is not None and item['time_s'] <= last_t:
            raise ValueError(f"time_s must increase strictly at row {n}")
        if not 0 <= item['throttle'] <= 1 or not 0 <= item['brake'] <= 1:
            raise ValueError(f"Pedals must be between 0 and 1 at row {n}")
        result.append(item)
        last_t = item['time_s']
    if not result:
        raise ValueError("Expected nonempty telemetry")
    return result


def read_telemetry(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError(f"Expected CSV columns: {FIELDS}")
        return validate_telemetry(reader)


def process(rows, vehicle=VehicleParameters(), cell=CellParameters()):
    out = []
    prev = None
    for x in validate_telemetry(rows):
        t, v = x['time_s'], x['speed_mps']
        dt = 0.0 if prev is None else t - prev['time_s']
        a = 0.0 if prev is None else (v - prev['speed_mps']) / dt
        mean_v = v if prev is None else (v + prev['speed_mps']) / 2
        power = vehicle_power(mean_v, a, vehicle)
        out.append({**x, 'interval_s': dt, 'model_speed_mps': mean_v,
                    'accel_mps2': a, **power,
                    **scale_to_cell(power['vehicle_battery_power_W'], cell)})
        prev = x
    return out


def save_results(rows, filename):
    if not rows:
        raise ValueError("Cannot save empty results")
    Path(filename).parent.mkdir(parents=True, exist_ok=True)
    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
