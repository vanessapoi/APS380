"""Equivalent-energy scaling; limits are offline examples, not cell ratings."""
from dataclasses import dataclass, asdict
import math

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
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")


def scale_to_cell(vehicle_power_W, params=CellParameters()):
    ratio = params.nominal_voltage_V * params.capacity_Ah / params.equivalent_pack_energy_Wh
    requested_power = vehicle_power_W * ratio * params.experiment_scale
    raw = requested_power / params.nominal_voltage_V
    command = max(-params.charge_limit_A, min(params.discharge_limit_A, raw))
    return {"cell_power_requested_W": requested_power,
            "cell_current_unclamped_A": raw, "cell_current_command_A": command,
            "cell_power_command_W": command * params.nominal_voltage_V,
            "command_saturated": int(raw != command)}
