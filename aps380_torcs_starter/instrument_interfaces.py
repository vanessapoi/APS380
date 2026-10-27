"""Transport-independent contracts. No hardware transport or commands are supplied."""
from dataclasses import dataclass
from typing import Protocol


class InstrumentError(RuntimeError):
    pass


class InstrumentTimeout(InstrumentError):
    pass


@dataclass(frozen=True)
class InstrumentStatus:
    output_enabled: bool
    mode: str
    fault: str = ''


@dataclass(frozen=True)
class InstrumentMeasurement:
    acquired_s: float
    current_A: float
    voltage_V: float
    setpoint_A: float
    status: InstrumentStatus


class CurrentInstrument(Protocol):
    max_current_A: float

    def set_current(self, current_A: float, timeout_s: float) -> None: ...
    def set_output(self, enabled: bool, timeout_s: float) -> None: ...
    def read(self, timeout_s: float) -> InstrumentMeasurement: ...


class ProgrammablePSU(CurrentInstrument, Protocol):
    """The current setpoint is a limit; readback may differ in CV operation."""


class BK8500Load(CurrentInstrument, Protocol):
    """CC sinking-current interface, not an implementation of the BK protocol."""


@dataclass(frozen=True)
class IsolationStatus:
    is_open: bool
    outputs_disabled: bool


class CellIsolation(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def verify(self) -> IsolationStatus: ...
