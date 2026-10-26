"""Flat-road longitudinal EV model, SI units throughout."""
from dataclasses import dataclass, asdict
from numerical_validation import finite_number

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
            if finite_number(name, value) < 0:
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
    if finite_number('speed_mps', speed_mps) < 0:
        raise ValueError('speed_mps must be nonnegative')
    finite_number('accel_mps2', accel_mps2)
    try:
        inertial = finite_number('inertial force', params.mass_kg * accel_mps2)
        weight = finite_number('weight', params.mass_kg * params.gravity_mps2)
        rolling = finite_number('rolling force', weight * params.rolling_coefficient)
        drag_factor = finite_number('drag factor', 0.5 * params.air_density_kg_m3 * params.drag_area_m2)
        speed_squared = finite_number('squared speed', speed_mps**2)
        drag = finite_number('drag force', drag_factor * speed_squared)
        force = finite_number('inertial plus rolling force', inertial + rolling)
        force = finite_number('total force', force + drag)
        wheel = finite_number('wheel power', force * speed_mps)
        requested_regen = finite_number('requested regen power', max(-wheel, 0) * params.regen_fraction)
        regen = min(requested_regen, params.max_regen_wheel_power_W)
        electrical = finite_number('electrical power', wheel / params.drive_efficiency if wheel >= 0
                                   else -regen * params.regen_efficiency)
        battery = finite_number('vehicle battery power', electrical + params.auxiliary_power_W)
    except OverflowError as error:
        raise ValueError('Vehicle power calculation overflowed') from error
    return {"wheel_power_W": wheel, "regen_wheel_power_W": regen,
            "friction_brake_power_W": max(-wheel, 0) - regen,
            "vehicle_battery_power_W": battery}
