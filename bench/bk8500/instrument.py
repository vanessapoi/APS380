"""Small original BK 8500 binary-protocol driver; branch current is nonnegative.

No connection is opened on import. Use only with a verified TTL interface.
"""
import math
import time


class ProtocolError(RuntimeError):
    pass


def packet(command, data=b'', address=0):
    if not 0 <= address <= 254 or not 0 <= command <= 255 or len(data) > 22:
        raise ValueError('Invalid command, address or payload')
    result = bytearray(26)
    result[:3] = bytes((0xAA, address, command))
    result[3:3 + len(data)] = data
    result[25] = sum(result[:25]) & 255
    return bytes(result)


class BK8500:
    """Transport is an already-open pyserial-compatible object."""
    def __init__(self, transport, address=0):
        self.transport = transport
        self.address = address
        self.last_roundtrip_ms = None

    def query(self, command, data=b'', setter=False):
        self.transport.reset_input_buffer()
        request = packet(command, data, self.address)
        start = time.monotonic()
        if self.transport.write(request) != len(request):
            raise ProtocolError('Incomplete command write')
        self.transport.flush()
        reply = self.transport.read(26)
        self.last_roundtrip_ms = (time.monotonic() - start) * 1000
        if (len(reply) != 26 or reply[0] != 0xAA or reply[1] != self.address
                or reply[25] != sum(reply[:25]) & 255):
            raise ProtocolError('Invalid response length, header, address or checksum')
        if setter:
            if reply[2] != 0x12 or reply[3] != 0x80:
                raise ProtocolError('Instrument rejected command: ' + reply.hex())
        elif reply[2] != command:
            raise ProtocolError('Unexpected response command: ' + reply.hex())
        return reply

    def identify(self):
        r = self.query(0x6A)
        return {'model': r[3:8].decode('ascii').strip('\0 '),
                'firmware_raw': int.from_bytes(r[8:10], 'little'),
                'serial_number': r[10:20].decode('ascii').strip('\0 ')}

    def remote(self):
        self.query(0x20, b'\x01', setter=True)

    def input(self, enabled):
        self.query(0x21, bytes((int(enabled),)), setter=True)

    def fixed_cc(self):
        self.query(0x5D, b'\x00', setter=True)
        self.query(0x28, b'\x00', setter=True)
        if self.query(0x5E)[3] != 0 or self.query(0x29)[3] != 0:
            raise ProtocolError('FIXED/CC readback failed')

    def set_current(self, current_A):
        # Deliberately restricted to the range exercised on this bench.
        if not math.isfinite(current_A) or not 0 <= current_A <= .1:
            raise ValueError('This bench tool permits only 0 to 0.10 A')
        self.query(0x2A, round(current_A * 10000).to_bytes(4, 'little'), setter=True)

    def current_setting(self):
        return int.from_bytes(self.query(0x2B)[3:7], 'little') / 10000

    def measure(self):
        r = self.query(0x5F)
        return {'voltage_V': int.from_bytes(r[3:7], 'little') / 1000,
                'measured_A': int.from_bytes(r[7:11], 'little') / 10000,
                'power_W': int.from_bytes(r[11:15], 'little') / 1000,
                'input_on': bool(r[15] & 8),
                'remote_enabled': bool(r[15] & 4),
                'status': int.from_bytes(r[16:18], 'little')}

    def shutdown(self):
        """Best effort: retry OFF; attempt zero even if OFF fails; verify readback.

        Cannot guarantee shutdown if USB, PC or instrument stops functioning.
        """
        errors = []
        for attempt in range(2):
            try:
                self.input(False)
                break
            except Exception as exc:
                errors.append('OFF attempt %d: %s' % (attempt + 1, exc))
        try:
            self.set_current(0)
        except Exception as exc:
            errors.append('Zero setpoint: ' + str(exc))
        try:
            time.sleep(.3)
            measurement = self.measure()
            setting = self.current_setting()
            verified = not measurement['input_on'] and setting == 0 and measurement['measured_A'] <= .002
            return {'verified': verified, 'measurement': measurement,
                    'setpoint_A': setting, 'errors': errors}
        except Exception as exc:
            errors.append('Shutdown readback: ' + str(exc))
            return {'verified': False, 'errors': errors}
