"""PC-side candidate OCV initialization and measured-net-current SOC counting.

SOC is a fraction, charging current is positive, timestamps are measurement
times in seconds. No instrument communication or current commands are present.
"""
from bisect import bisect_left
from dataclasses import dataclass, field
import json
import math
from pathlib import Path

DEFAULT_REFERENCE = Path(__file__).parent / "profiles/eve_35v_ocv_candidate.json"


def finite(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


@dataclass(frozen=True)
class OcvReference:
    reference_id: str
    coefficients_descending: tuple
    temperature_C: float
    min_rest_duration_s: float
    temperature_tolerance_C: float
    max_abs_rest_current_A: float
    lookup: tuple = field(init=False, repr=False)

    def __post_init__(self):
        if not self.reference_id or not self.coefficients_descending:
            raise ValueError("Reference identity and polynomial are required")
        for coefficient in self.coefficients_descending:
            finite("coefficient", coefficient)
        finite("temperature_C", self.temperature_C)
        for name in ("min_rest_duration_s", "temperature_tolerance_C", "max_abs_rest_current_A"):
            if finite(name, getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")
        table = tuple((i / 1000, self.voltage(i / 1000)) for i in range(1001))
        if any(b[1] <= a[1] for a, b in zip(table, table[1:])):
            raise ValueError("OCV lookup must be strictly increasing")
        object.__setattr__(self, "lookup", table)

    def voltage(self, soc):
        if not 0 <= finite("soc", soc) <= 1:
            raise ValueError("SOC must be a fraction in [0, 1]")
        voltage = 0.0
        for coefficient in self.coefficients_descending:
            voltage = voltage * (soc * 100) + coefficient
        return finite("polynomial voltage", voltage)

    def soc_from_ocv(self, ocv_V):
        """Invert the bounded lookup by interpolation; never clamp/extrapolate."""
        finite("ocv_V", ocv_V)
        voltages = tuple(row[1] for row in self.lookup)
        # Admit endpoint roundoff only (e.g. printed 4.182 versus binary Horner
        # result 4.1819999999999995), never a materially out-of-range voltage.
        if math.isclose(ocv_V, voltages[0], rel_tol=0, abs_tol=1e-12):
            return 0.0
        if math.isclose(ocv_V, voltages[-1], rel_tol=0, abs_tol=1e-12):
            return 1.0
        if not voltages[0] <= ocv_V <= voltages[-1]:
            raise ValueError(f"OCV outside candidate range [{voltages[0]:.6f}, {voltages[-1]:.6f}] V")
        index = bisect_left(voltages, ocv_V)
        if index == 0:
            return 0.0
        low, high = self.lookup[index - 1:index + 1]
        return low[0] + (ocv_V - low[1]) * (high[0] - low[0]) / (high[1] - low[1])


def load_reference(path=DEFAULT_REFERENCE):
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    policy = profile["initialization_policy"]
    return OcvReference(profile["id"], tuple(profile["coefficients_descending"]),
                        profile["paper_temperature_C"], profile["paper_rest_duration_s"],
                        policy["temperature_tolerance_C"], policy["max_abs_rest_current_A"])


@dataclass(frozen=True)
class CellMeasurement:
    session_id: str
    time_s: float
    cell_voltage_V: float
    net_cell_current_A: float
    cell_temperature_C: float

    def __post_init__(self):
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("Nonempty measurement session_id is required")
        for name in ("time_s", "cell_voltage_V", "net_cell_current_A", "cell_temperature_C"):
            finite(name, getattr(self, name))
        if self.time_s < 0 or self.cell_voltage_V <= 0:
            raise ValueError("Measurement time must be nonnegative and voltage positive")


@dataclass(frozen=True)
class RestEvidence:
    """Caller-attested observed history, not inferred from the first sample."""
    duration_s: float
    max_abs_current_A: float
    min_temperature_C: float
    max_temperature_C: float

    def validate(self, reference, measurement):
        for name in ("duration_s", "max_abs_current_A", "min_temperature_C", "max_temperature_C"):
            finite(name, getattr(self, name))
        if self.duration_s < reference.min_rest_duration_s:
            raise ValueError("Insufficient observed rest duration for candidate initialization")
        if not 0 <= self.max_abs_current_A <= reference.max_abs_rest_current_A:
            raise ValueError("Rest current exceeds candidate qualification policy")
        if abs(measurement.net_cell_current_A) > self.max_abs_current_A:
            raise ValueError("Initial sample contradicts rest-current evidence")
        low = reference.temperature_C - reference.temperature_tolerance_C
        high = reference.temperature_C + reference.temperature_tolerance_C
        if not low <= self.min_temperature_C <= measurement.cell_temperature_C <= self.max_temperature_C <= high:
            raise ValueError("Rest temperature evidence is outside candidate qualification policy")


@dataclass(frozen=True)
class SocEstimate:
    time_s: float
    interval_s: float
    soc: float
    soc_unclamped: float
    boundary_clipped: bool
    net_discharged_Ah: float
    interval_net_discharge_Ah: float


class CoulombCounter:
    """Trapezoidal integration between measurements, unity charge efficiency.

    Capacity and maximum measurement gap must be explicitly supplied. Invalid
    updates leave state unchanged. A missing interval must be backfilled with
    real measurements or a new counter initialized; it is never reconstructed.
    """

    def __init__(self, capacity_Ah, max_gap_s, initial_soc, initial_measurement):
        for name, value in (("capacity_Ah", capacity_Ah), ("max_gap_s", max_gap_s)):
            if finite(name, value) <= 0:
                raise ValueError(f"{name} must be positive")
        if not 0 <= finite("initial_soc", initial_soc) <= 1:
            raise ValueError("Initial SOC must be in [0, 1]")
        self.capacity_Ah = capacity_Ah
        self.max_gap_s = max_gap_s
        self.soc = initial_soc
        self.previous = initial_measurement
        self.net_discharged_Ah = 0.0

    @classmethod
    def from_rest(cls, reference, measurement, evidence, *, capacity_Ah, max_gap_s):
        evidence.validate(reference, measurement)
        return cls(capacity_Ah, max_gap_s, reference.soc_from_ocv(measurement.cell_voltage_V), measurement)

    def initial_estimate(self):
        return SocEstimate(self.previous.time_s, 0.0, self.soc, self.soc, False, self.net_discharged_Ah, 0.0)

    def update(self, measurement):
        if measurement.session_id != self.previous.session_id:
            raise ValueError("Session changed: explicit SOC reinitialization is required")
        dt = measurement.time_s - self.previous.time_s
        if not 0 < dt <= self.max_gap_s:
            raise ValueError("Measurement time must increase without exceeding max_gap_s")
        # Midpoint-form average avoids unnecessary overflow when currents match.
        mean_current = self.previous.net_cell_current_A / 2 + measurement.net_cell_current_A / 2
        delta_Ah = finite("interval charge", mean_current * dt / 3600)
        raw_soc = finite("updated SOC", self.soc + delta_Ah / self.capacity_Ah)
        # Named discharge totals remain discharge-positive quantities.
        total_Ah = finite("total charge", self.net_discharged_Ah - delta_Ah)
        soc = max(0.0, min(1.0, raw_soc))
        result = SocEstimate(measurement.time_s, dt, soc, raw_soc, soc != raw_soc, total_Ah, -delta_Ah)
        self.soc, self.previous, self.net_discharged_Ah = soc, measurement, total_Ah
        return result
