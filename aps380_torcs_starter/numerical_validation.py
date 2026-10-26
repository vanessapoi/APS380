"""Numerical and optional interval checks shared by offline calculations."""
from dataclasses import dataclass
import math
from numbers import Real


def finite_number(name, value):
    """Validate without changing arithmetic types or accepting booleans."""
    try:
        valid = isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a finite real number")
    return value


def field_number(name, value):
    """Parse numeric CSV strings while rejecting invalid direct-call values."""
    if not isinstance(value, str):
        finite_number(name, value)
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite numeric field") from error
    return finite_number(name, result)


@dataclass(frozen=True)
class TimingPolicy:
    """No arbitrary sampling bounds by default; explicit bounds are inclusive.

    Bounds are acquisition-policy choices, not validated hardware capabilities.
    First samples are initialization points and have no preceding interval.
    """
    min_interval_s: float | None = None
    max_gap_s: float | None = None

    def __post_init__(self):
        for name in ("min_interval_s", "max_gap_s"):
            value = getattr(self, name)
            if value is not None and finite_number(name, value) <= 0:
                raise ValueError(f"{name} must be positive when configured")
        if (self.min_interval_s is not None and self.max_gap_s is not None
                and self.min_interval_s > self.max_gap_s):
            raise ValueError("min_interval_s must not exceed max_gap_s")

    def interval(self, previous_s, current_s):
        for name, value in (("previous time", previous_s), ("current time", current_s)):
            if finite_number(name, value) < 0:
                raise ValueError(f"{name} must be nonnegative")
        dt = finite_number("time interval", current_s - previous_s)
        if dt <= 0:
            raise ValueError("Measurement time must increase strictly")
        if self.min_interval_s is not None and dt < self.min_interval_s:
            raise ValueError("Time interval is below min_interval_s")
        if self.max_gap_s is not None and dt > self.max_gap_s:
            raise ValueError("Time interval exceeds max_gap_s")
        return dt


DEFAULT_TIMING = TimingPolicy()
