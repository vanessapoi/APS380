"""Flat-road longitudinal EV model, SI units throughout."""
from dataclasses import dataclass, asdict
import math

@dataclass(frozen=True)
class VehicleParameters:
    mass_kg: float = 2100.0
    drag_area_m2: float = 0.65
    rolling_coefficient: float = 0.012
    air_density_kg_m3: float = 1.225
    gravity_mps2: float = 9.81
    drive_efficiency: float = 0.88
    regen_efficiency: float = 0.65
    regen_fraction: float = 0.7
    max_regen_wheel_power_W: float = 60000.0
    auxiliary_power_W: float = 300.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.mass_kg <= 0 or self.gravity_mps2 <= 0:
            raise ValueError("Mass and gravity must be positive")
        if not 0 < self.drive_efficiency <= 1 or not 0 <= self.regen_efficiency <= 1 or not 0 <= self.regen_fraction <= 1:
            raise ValueError("Invalid efficiency or regeneration fraction")


def vehicle_power(speed_mps, accel_mps2, params=VehicleParameters()):
    """Speed is interval mean; acceleration is interval finite difference.

    Negative wheel power is braking demand after passive road losses.
    The remainder after regeneration is assigned to friction brakes.
    """
    force = (params.mass_kg * accel_mps2
             + params.mass_kg * params.gravity_mps2 * params.rolling_coefficient
             + 0.5 * params.air_density_kg_m3 * params.drag_area_m2 * speed_mps**2)
    wheel = force * speed_mps
    regen = min(max(-wheel, 0) * params.regen_fraction, params.max_regen_wheel_power_W)
    electrical = (wheel / params.drive_efficiency if wheel >= 0
                  else -regen * params.regen_efficiency)
    return {"wheel_power_W": wheel, "regen_wheel_power_W": regen,
            "friction_brake_power_W": max(-wheel, 0) - regen,
            "vehicle_battery_power_W": electrical + params.auxiliary_power_W}
