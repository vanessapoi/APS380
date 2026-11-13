"""Read-only presentation of completed worker records; never instrument I/O."""
import json
import time


class LoadMonitor:
    def __init__(self, service, hardware=False):
        self.service, self.hardware = service, hardware
        self.config = service.config

    @property
    def latest(self):
        c = self.service.controller
        row = dict(self.service.events[-1]) if self.service.events else {}
        row.update(state=c.state, fault=c.fault)
        row['measurements_retained'] = bool('measured_A' in row and c.state != 'RUNNING')
        return row

    @property
    def history(self):
        # Completed records only. Do not display a partially executed I/O cycle.
        return [r for r in self.service.events[-200:] if r['event'] == 'cycle'
                and r['state'] == 'RUNNING' and 'measured_A' in r]

    def request(self, action):
        if self.hardware and action == 'arm':
            raise ValueError('Hardware ARM requires the supervised terminal approval phrase')
        self.service.request(action)


class ConsoleStatus:
    def __init__(self, interval=5., json_output=False, dashboard=False, arm_hint=None):
        self.interval, self.json_output, self.dashboard = interval, json_output, dashboard
        self.arm_hint = arm_hint or 'Enter command in this terminal and press Enter.'
        self.previous, self.next_notice = None, 0.

    def render(self, monitor, telemetry, now=None):
        now = time.perf_counter() if now is None else now
        row = monitor.latest
        phase = (row['state'], row['fault'], telemetry)
        changed = phase != self.previous
        if not changed and (self.dashboard or row['state'] != 'RUNNING' or now < self.next_notice):
            return None
        self.previous, self.next_notice = phase, now + self.interval
        if self.json_output:
            return json.dumps(dict(row, telemetry=telemetry))
        prefix = 'BK8500 REAL' if monitor.hardware else 'BK8500 MOCK'
        line = f"{prefix}: {row['state']} | telemetry {telemetry}"
        if row['fault']:
            line += ' | FAULT: ' + row['fault']
        elif row['state'] == 'READY':
            line += ' | INPUT OFF; waiting for ARM. '+self.arm_hint
        if 'measured_A' in row:
            line += (f" | target {row.get('power_limited_load_target_A', 0):.4f} A"
                     f" | command {row['commanded_load_A']:.4f} A"
                     f" | setting {row['readback_setting_A']:.4f} A"
                     f" | measured {row['measured_A']:.4f} A"
                     f" | input {'ON' if row['input_on'] else 'OFF'}")
            if row.get('measurements_retained'):
                line += ' | RETAINED readbacks, not live'
        return line
