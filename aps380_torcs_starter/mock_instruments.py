"""In-memory instruments only. No serial, VISA, sockets, or physical outputs.

CC/CV is an imposed mock operating envelope, not a battery/circuit simulation.
The local isolation trip deliberately remains effective during transport failure.
"""
from dataclasses import asdict
import math
import time

from instrument_interfaces import (InstrumentError, InstrumentTimeout,
                                   InstrumentMeasurement, InstrumentStatus, IsolationStatus)
from numerical_validation import finite_number
from prototype_current_config import PROTOTYPE


class MockCurrentInstrument:
    mock_only = True

    def __init__(self, max_current_A=PROTOTYPE.eload_current_max_A, response_delay_s=.02, communication_delay_s=0.,
                 clock=time.monotonic, sleep=time.sleep):
        for name, value in locals().copy().items():
            if name.endswith(('_A', '_s')):
                if finite_number(name, value) < 0:
                    raise ValueError(f'{name} must be nonnegative')
        self.max_current_A = max_current_A
        self.response_delay_s = response_delay_s
        self.communication_delay_s = communication_delay_s
        self.clock, self.sleep = clock, sleep
        self.setpoint_A = 0.
        self.output_enabled = False
        self.current_A = 0.
        self.voltage_V = 3.65
        self.failure = None  # None, 'communication', or 'timeout'; persists until cleared
        self.measurement_age_s = 0.
        self.current_offset_A = 0.
        self._updated = clock()
        self.log = []

    def _exchange(self, operation, timeout_s):
        if finite_number('timeout_s', timeout_s) <= 0:
            raise ValueError('timeout_s must be positive')
        self.log.append(dict(event='transaction', operation=operation, time_s=self.clock(),
                             failure=('timeout' if self.communication_delay_s > timeout_s else self.failure)))
        if self.failure == 'timeout' or self.communication_delay_s > timeout_s:
            self.sleep(timeout_s)
            raise InstrumentTimeout(f'{type(self).__name__}: {operation} timed out')
        self.sleep(self.communication_delay_s)
        if self.failure:
            raise InstrumentError(f'{type(self).__name__}: communication failed')

    def _target(self):
        return self.setpoint_A if self.output_enabled else 0.

    def _advance(self):
        now = self.clock()
        target = self._target()
        fraction = 1. if self.response_delay_s == 0 else -math.expm1(-max(0., now-self._updated)/self.response_delay_s)
        self.current_A += (target-self.current_A)*fraction
        self._updated = now

    def set_current(self, current_A, timeout_s):
        if not 0 <= finite_number('current_A', current_A) <= self.max_current_A:
            raise InstrumentError('Instrument current setpoint outside capability')
        self._exchange('set_current', timeout_s)
        self._advance()
        self.setpoint_A = current_A
        self.log.append(dict(event='command', time_s=self.clock(), setpoint_A=current_A))

    def set_output(self, enabled, timeout_s):
        if type(enabled) is not bool:
            raise ValueError('Output state must be boolean')
        self._exchange('set_output', timeout_s)
        self._advance()
        self.output_enabled = enabled
        if not enabled:
            self.current_A = 0.
        self.log.append(dict(event='output', time_s=self.clock(), enabled=enabled))

    def _local_disable(self):
        """Mock independent interlock; not a transport command or real protection."""
        self.output_enabled = False
        self.current_A = 0.
        self.log.append(dict(event='local_trip', time_s=self.clock()))

    def read(self, timeout_s):
        self._exchange('read', timeout_s)
        self._advance()
        mode = 'OFF' if not self.output_enabled else 'CC'
        if isinstance(self, MockPSU) and self.output_enabled and self.cv_available_A < self.setpoint_A:
            mode = 'CV'
        measurement = InstrumentMeasurement(self.clock()-self.measurement_age_s,
            self.current_A+self.current_offset_A, self.voltage_V, self.setpoint_A,
            InstrumentStatus(self.output_enabled, mode))
        self.log.append(dict(event='measurement', **asdict(measurement)))
        return measurement


class MockPSU(MockCurrentInstrument):
    def __init__(self, **kwargs):
        kwargs.setdefault('max_current_A', PROTOTYPE.psu_current_max_A)
        super().__init__(**kwargs)
        self.cv_available_A = self.max_current_A

    def _target(self):
        if finite_number('cv_available_A', self.cv_available_A) < 0:
            raise InstrumentError('Invalid mock CV envelope')
        return min(self.setpoint_A, self.cv_available_A) if self.output_enabled else 0.


class MockBK8500(MockCurrentInstrument):
    def __init__(self, **kwargs):
        kwargs.setdefault('max_current_A', PROTOTYPE.eload_current_max_A)
        super().__init__(**kwargs)


class MockIsolation:
    mock_only = True

    def __init__(self, psu, load):
        self.psu, self.load = psu, load
        self.is_open = True

    def open(self):
        self.is_open = True
        self.psu._local_disable()
        self.load._local_disable()

    def close(self):
        self.is_open = False

    def verify(self):
        return IsolationStatus(self.is_open,
                               not self.psu.output_enabled and not self.load.output_enabled)
