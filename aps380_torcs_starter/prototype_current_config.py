"""Prototype mock experiment policy, NOT verified hardware safety ratings.

Cell current is charging-positive. Native TORCS pack current retains its
discharge-positive source convention. No physical drivers are provided.
"""
from dataclasses import dataclass, asdict
import math
from numerical_validation import finite_number

CELL_CURRENT_CONVENTION = 'charging_positive'
NATIVE_CURRENT_CONVENTION = 'discharge_positive'
CURRENT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class PrototypeCurrentConfig:
    psu_current_min_A: float = 0.
    psu_current_max_A: float = 1.
    psu_cc_setpoint_A: float = 1.
    battery_current_min_A: float = -2.
    battery_current_max_A: float = 1.
    eload_current_min_A: float = 0.
    eload_current_max_A: float = 3.
    control_hz: float = 10.
    command_expiry_s: float = .5
    measurement_expiry_s: float = .2
    io_timeout_s: float = .02
    settling_timeout_s: float = .6
    ready_timeout_s: float = 30.
    tracking_tolerance_A: float = .03
    slew_rate_A_per_s: float = .2
    neutral_tolerance_A: float = .002
    direction_tolerance_A: float = .002
    neutral_hold_s: float = .1
    transition_timeout_s: float | None = None
    numeric_tolerance_A: float = 1e-9

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name == 'transition_timeout_s' and value is None:
                continue
            finite_number(name, value)
            if name == 'battery_current_min_A':
                continue
            if value < 0 or (value == 0 and name not in (
                    'psu_current_min_A', 'eload_current_min_A',
                    'battery_current_max_A', 'tracking_tolerance_A')):
                raise ValueError(f'Invalid prototype setting: {name}')
        if not self.battery_current_min_A <= 0 <= self.battery_current_max_A:
            raise ValueError('Battery interval must contain neutral current')
        if not 0 <= self.psu_current_min_A <= self.psu_cc_setpoint_A <= self.psu_current_max_A:
            raise ValueError('PSU setpoint outside prototype interval')
        if not 0 <= self.eload_current_min_A <= self.psu_cc_setpoint_A <= self.eload_current_max_A:
            raise ValueError('Neutral bias outside eLoad operating interval')
        if self.control_hz > 100 or self.io_timeout_s > self.command_expiry_s:
            raise ValueError('Control rate must be <=100 Hz and I/O timeout <= command expiry')
        if self.neutral_tolerance_A > self.tracking_tolerance_A:
            raise ValueError('Neutral tolerance must not exceed tracking tolerance')
        if self.numeric_tolerance_A >= min(self.neutral_tolerance_A,self.direction_tolerance_A,self.tracking_tolerance_A):
            raise ValueError('Numerical tolerance must be smaller than control tolerances')
        if self.transition_timeout_s is None:
            object.__setattr__(self,'transition_timeout_s',float(math.floor(self.minimum_transition_timeout_s)+1))
        if self.transition_timeout_s <= self.minimum_transition_timeout_s:
            raise ValueError('Transition timeout too short for slew, bounded I/O and neutral dwell')

    @property
    def minimum_transition_timeout_s(self):
        # The worker caps each slew step to one nominal period and waits AFTER
        # four bounded transactions. Account for that wall time, not just A/s.
        steps=math.ceil(finite_number('slew steps',
            max(abs(self.battery_current_min_A),self.battery_current_max_A)*self.control_hz/self.slew_rate_A_per_s))
        dwell_steps=math.ceil(self.neutral_hold_s*self.control_hz)
        return finite_number('transition budget',
            (steps+dwell_steps+2)*(1/self.control_hz+4*self.io_timeout_s)+self.settling_timeout_s)

    @property
    def discharge_limit_A(self):
        """Positive magnitude, for generic offline scaling compatibility."""
        return -self.battery_current_min_A

    @property
    def charge_limit_A(self):
        return self.battery_current_max_A


PROTOTYPE = PrototypeCurrentConfig()


def current_metadata():
    return dict(current_schema_version=CURRENT_SCHEMA_VERSION,
                cell_current_convention=CELL_CURRENT_CONVENTION,
                native_pack_current_convention=NATIVE_CURRENT_CONVENTION)
