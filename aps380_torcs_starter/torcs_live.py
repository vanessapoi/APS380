"""Loopback native EV telemetry, fixed scaling and audit reports. No actuation."""
from collections import deque
from dataclasses import asdict
import csv
import ctypes
import hashlib
import io
import json
import math
import os
from pathlib import Path
import socket
import threading
import time

from cell_scaling import CellParameters, scale_to_cell
from numerical_validation import finite_number, TimingPolicy
from run_ev import numeric_ev_row, interval_net_energy, read_ev, verify_configuration
from driver_feedback import DriverFeedback, HUD_HELLO
from prototype_current_config import PROTOTYPE, current_metadata

CSV_FIELDS = ('time_s','speed_mps','throttle','brake','car_id','profile_id',
              'longitudinal_mps','lateral_mps','vertical_mps','damage','collision',
              'motor_radps','motor_torque_Nm','motor_power_W','pack_power_W',
              'pack_voltage_V','pack_current_A','soc','pack_energy_Wh','discharge_Wh','charge_Wh')
BASE = Path(__file__).resolve().parent


def reject_constant(value):
    raise ValueError(f'Nonfinite JSON constant: {value}')


def qpc_clock_verified():
    """Verify Python perf_counter and native QPC share the same clock here."""
    if os.name != 'nt':
        return False
    frequency, ticks = ctypes.c_longlong(), ctypes.c_longlong()
    start = time.perf_counter()
    ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(frequency))
    ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(ticks))
    stop = time.perf_counter()
    return frequency.value > 0 and start-1e-6 <= ticks.value/frequency.value <= stop+1e-6


class LiveProcessor:
    def __init__(self, profile_bytes, config, shared_clock=False, current_config=PROTOTYPE):
        self.profile = json.loads(profile_bytes, parse_constant=reject_constant)
        self.identity = self.profile['id']+'-'+hashlib.sha256(profile_bytes).hexdigest()[:12]
        if config['mode'] != 'simulation_only':
            raise ValueError('Only simulation_only mode is implemented')
        self.config = config
        self.current_config = current_config
        for key in ('stale_after_s','max_sender_age_s','max_sim_gap_s'):
            if finite_number(key, config[key]) <= 0:
                raise ValueError(f'{key} must be positive')
        if type(config.get('display_refresh_ms',100)) is not int or config.get('display_refresh_ms',100)<20:
            raise ValueError('display_refresh_ms must be an integer of at least 20')
        capacity = self.profile['unvalidated']['capacity_Wh']
        cell_config=dict(config['cell'])
        limits=dict(discharge_limit_A=current_config.discharge_limit_A,
                    charge_limit_A=current_config.charge_limit_A)
        for key,value in limits.items():
            if key in cell_config and cell_config.pop(key) != value:
                raise ValueError(f'{key} conflicts with centralized current configuration')
        self.cell = CellParameters(**cell_config, **limits, equivalent_pack_energy_Wh=capacity)
        self.timing = TimingPolicy(min_interval_s=1e-6)
        self.shared_clock = shared_clock
        self.session = None
        self.retired = set()
        self.previous = None
        self.sequence = -1
        self.sender_time = None
        self.last_receive = None
        self.status = 'WAITING'
        self.error = ''
        self.current = None
        self.history = deque(maxlen=5000)
        self.stats = dict(accepted=0, invalid=0, missing=0, reordered=0, sessions=0, gaps=0, ended=0)

    def state(self, now=None):
        now = time.perf_counter() if now is None else now
        if self.status not in ('ENDED', 'RECEIVER_ERROR', 'STOPPED') and self.last_receive is not None and now-self.last_receive > self.config['stale_after_s']:
            return 'STALE (pause or lost stream)'
        return self.status

    def accept(self, payload, received):
        finite_number('host receipt time', received)
        if len(payload) > 4096:
            raise ValueError('Oversized telemetry packet')
        packet = json.loads(payload, parse_constant=reject_constant)
        if not isinstance(packet, dict) or type(packet.get('version')) is not int or packet['version'] != 1:
            raise ValueError('Unsupported telemetry version')
        session, seq = packet['session_id'], packet['sequence']
        if not isinstance(session, str) or not session or len(session)>100:
            raise ValueError('Invalid session identity')
        if type(seq) is not int or seq < 0:
            raise ValueError('Invalid sequence')
        sender = finite_number('sender QPC time', packet['sender_qpc_s'])
        if sender<0:raise ValueError('Negative sender clock')
        if type(packet['send_errors']) is not int or packet['send_errors'] < 0:
            raise ValueError('Invalid send error counter')
        age = received-sender if self.shared_clock else None
        if age is not None and (age < -.001 or age > self.config['max_sender_age_s']):
            raise ValueError('Delayed or future-dated packet')
        if session in self.retired:
            self.stats['reordered'] += 1
            raise ValueError('Packet from retired session')
        same = session == self.session
        if same and seq <= self.sequence:
            self.stats['reordered'] += 1
            raise ValueError('Duplicate or out-of-order packet')
        if same and self.sender_time is not None and sender <= self.sender_time:
            raise ValueError('Sender clock did not advance')
        if packet['event'] == 'ended':
            if not same:
                raise ValueError('End message for unknown session')
            self.stats['missing'] += seq-self.sequence-1
            self.sequence, self.sender_time = seq, sender
            self.last_receive, self.status, self.current = received, 'ENDED', None
            self.stats['ended'] += 1
            return None
        if packet['event'] != 'sample' or (same and self.status == 'ENDED'):
            raise ValueError('Unexpected session event')
        values = next(csv.reader(io.StringIO(packet['csv'])))
        if len(values) != len(CSV_FIELDS):
            raise ValueError('Native sample field count mismatch')
        raw = dict(zip(CSV_FIELDS, values))
        if raw['car_id'] != self.profile['car_id'] or raw['profile_id'] != self.identity:
            raise ValueError('Car/profile mismatch')
        row = numeric_ev_row(raw)
        capacity = self.profile['unvalidated']['capacity_Wh']
        checks = [(row['pack_power_W'],row['pack_current_A']*row['pack_voltage_V'],.01),
                  (row['pack_voltage_V'],self.profile['published']['pack_nominal_voltage_V'],.001),
                  (row['motor_power_W'],row['motor_radps']*row['motor_torque_Nm'],.1),
                  (row['pack_energy_Wh'],row['soc']*capacity,.001)]
        for actual, expected, tolerance in checks:
            finite_number('derived electrical quantity', expected)
            if abs(finite_number('electrical residual',actual-expected)) > tolerance:
                raise ValueError('Native electrical consistency error')
        if not 0 <= row['pack_energy_Wh'] <= capacity or min(row['discharge_Wh'],row['charge_Wh']) < 0:
            raise ValueError('Invalid energy bounds')
        previous = self.previous if same else None
        dt = self.timing.interval(previous['time_s'],row['time_s']) if previous else 0
        gap = dt > self.config['max_sim_gap_s']
        if previous:
            if row['discharge_Wh'] < previous['discharge_Wh'] or row['charge_Wh'] < previous['charge_Wh']:
                raise ValueError('Native energy counters reset')
            closure = previous['pack_energy_Wh']-row['pack_energy_Wh']-interval_net_energy(previous,row)
            if abs(finite_number('energy closure',closure)) > .00001:
                raise ValueError('Native energy closure error')
        demand = scale_to_cell(row['pack_power_W'], self.cell)
        # Commit only validated packets. A large gap explicitly rebaselines the
        # valid counters but supplies no current target for that boundary sample.
        if not same:
            if self.session is not None:
                self.retired.add(self.session)
            self.stats['sessions'] += 1
        self.stats['missing'] += seq-self.sequence-1 if same else seq
        self.session, self.sequence, self.sender_time = session, seq, sender
        self.previous, self.last_receive = row, received
        self.stats['accepted'] += 1
        self.stats['gaps'] += int(gap)
        self.status, self.error = ('GAP' if gap else 'RECEIVING'), ''
        result = dict(row, **demand, **current_metadata(), session_id=session, sequence=seq, received_qpc_s=received,
                      sender_qpc_s=sender, sender_age_ms=age*1000 if age is not None else None,
                      interval_s=dt, continuity_break=gap, target_available=not gap,
                      send_errors=packet['send_errors'], native_csv=packet['csv'],
                      car_id=raw['car_id'],profile_id=raw['profile_id'])
        self.current = result if not gap else None
        self.history.append(result)
        return result


class LiveReceiver:
    def __init__(self, port, output, config_path=BASE/'profiles/live_scaling_demo.json',
                 profile_path=BASE/'profiles/tesla_model3_rwd.json', demand_sink=None,
                 current_config=PROTOTYPE):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        config_bytes, profile_bytes = Path(config_path).read_bytes(), Path(profile_path).read_bytes()
        config = json.loads(config_bytes, parse_constant=reject_constant)
        self.processor = LiveProcessor(profile_bytes,config,qpc_clock_verified(),current_config)
        self.socket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:
            self.socket.bind(('127.0.0.1',port))
        except Exception:
            self.socket.close()
            raise
        self.socket.settimeout(.1)
        self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024*1024)
        self.port = self.socket.getsockname()[1]
        (self.output/'vehicle_profile.json').write_bytes(profile_bytes)
        (self.output/'scaling_config.json').write_bytes(config_bytes)
        (self.output/'effective_current_config.json').write_text(json.dumps(
            dict(**current_metadata(), **asdict(current_config)),indent=2)+'\n')
        self.log = (self.output/'received.jsonl').open('w',encoding='utf-8')
        self.stop_event = threading.Event()
        self.shutdown_event = threading.Event()
        self.expected_shutdown_resets = 0
        self.worker = threading.Thread(target=self._receive,daemon=True)
        self.failed = None
        self._last_state = None
        self.hud_clients = {}
        self.feedback = DriverFeedback()
        # Optional latest-value mailbox only; never performs instrument I/O here.
        self.demand_sink = demand_sink
        self.hud_stats = dict(registrations=0,sent=0,errors=0,rendered_acks=0,
                             normal_acks=0,near_limit_acks=0,discharge_alert_acks=0,
                             charge_alert_acks=0,unavailable_acks=0)

    def _send_hud(self):
        if self.shutdown_event.is_set():
            return
        now=time.perf_counter()
        session=self.processor.session
        for pid,(address,seen) in list(self.hud_clients.items()):
            if now-seen>2:
                del self.hud_clients[pid];continue
            if session is not None and session.split('-',1)[0]!=str(pid):
                continue
            try:
                self.socket.sendto(self.feedback.encode(self.processor,pid,now),address)
                self.hud_stats['sent']+=1
            except (OSError,ValueError):
                self.hud_stats['errors']+=1

    def _record_state(self):
        state = self.processor.state()
        if self.shutdown_event.is_set() and state.startswith('STALE'):
            return
        if state != self._last_state:
            self.log.write(json.dumps({'kind':'state','state':state,'host_qpc_s':time.perf_counter()})+'\n')
            self.log.flush()
            self._last_state = state

    def start(self):
        self.worker.start()

    def _receive(self):
        try:
            while not self.stop_event.is_set():
                self._record_state()
                try:
                    payload, address = self.socket.recvfrom(8192)
                except socket.timeout:
                    if not self.shutdown_event.is_set() and self.demand_sink is not None and self.processor.state().startswith('STALE'):
                        self.demand_sink.publish(None, 'STALE_TELEMETRY')
                    self._send_hud()
                    continue
                except OSError as error:
                    # Windows can deliver an ICMP response to an earlier HUD
                    # send as recvfrom WSAECONNRESET after the native peer exits.
                    # Suppress only this code during an explicitly begun stop.
                    if self.shutdown_event.is_set() and (getattr(error, 'winerror', None) == 10054 or error.errno == 10054):
                        self.expected_shutdown_resets += 1
                        self.log.write(json.dumps(dict(kind='expected_shutdown_reset',
                            error=repr(error), host_qpc_s=time.perf_counter()))+'\n')
                        self.log.flush()
                        break
                    raise
                if payload.startswith(HUD_HELLO):
                    try:
                        registration=payload[len(HUD_HELLO):].split()
                        if len(registration) not in (1,4):raise ValueError('Invalid HUD fields')
                        pid=int(registration[0])
                        if address[0]!='127.0.0.1' or not 0<pid<2**32:
                            raise ValueError('Invalid HUD registration')
                        if len(self.hud_clients)<16 or pid in self.hud_clients:
                            if pid not in self.hud_clients:self.hud_stats['registrations']+=1
                            self.hud_clients[pid]=(address,time.perf_counter())
                            if len(registration)==4:
                                sequence,alarm,status=map(int,registration[1:])
                                if sequence>=0 and 0<=alarm<=3 and 0<=status<=5:
                                    self.hud_stats['rendered_acks']+=1
                                    key=('normal_acks','near_limit_acks','discharge_alert_acks','charge_alert_acks')[alarm] if status==1 else 'unavailable_acks'
                                    self.hud_stats[key]+=1
                        self._send_hud()
                    except ValueError:
                        self.hud_stats['errors']+=1
                    continue
                received = time.perf_counter()
                started = time.perf_counter()
                try:
                    row = self.processor.accept(payload, received)
                    event = {'kind':'sample' if row is not None else 'ended','row':row,
                             'processing_ms':(time.perf_counter()-started)*1000}
                except (ValueError,KeyError,TypeError,StopIteration,UnicodeError,OverflowError) as error:
                    self.processor.stats['invalid'] += 1
                    self.processor.status, self.processor.current = 'INVALID', None
                    self.processor.error = str(error)
                    event = {'kind':'invalid','error':str(error),'received_qpc_s':received,
                             'payload':payload.decode('utf-8',errors='replace')[:4096]}
                self.log.write(json.dumps(event,allow_nan=False)+'\n')
                self.log.flush()
                if self.demand_sink is not None:
                    self.demand_sink.publish(self.processor.current, self.processor.status)
                self._record_state()
                self._send_hud()
        except Exception as error:
            self.failed = repr(error)
            self.processor.status, self.processor.current = 'RECEIVER_ERROR', None
            self.log.write(json.dumps(dict(kind='receiver_error', error=self.failed,
                host_qpc_s=time.perf_counter()))+'\n')
            self.log.flush()
            self._record_state()
            if self.demand_sink is not None:
                self.demand_sink.publish(None, 'RECEIVER_ERROR')

    def begin_shutdown(self):
        """Stop HUD sends before intentionally terminating this launcher's peer.

        Deliberate telemetry-loss tests must leave this unset until after expiry.
        Unexpected network errors remain failures, including other shutdown errors.
        """
        self.shutdown_event.set()

    def close(self):
        self.begin_shutdown()
        if self.demand_sink is not None:
            self.demand_sink.publish(None, 'RECEIVER_CLOSED')
        self.stop_event.set()
        if self.worker.is_alive():
            self.worker.join(timeout=2)
        if self.worker.is_alive():
            raise RuntimeError('Live receiver did not stop')
        if not self.failed and self.processor.status != 'ENDED':
            self.processor.status, self.processor.current = 'STOPPED', None
        self._record_state()
        self.socket.close()
        self.log.close()
        return write_report(self)


def distribution(values):
    import statistics
    values = sorted(values)
    if not values:
        return None
    return {'min':values[0],'median':statistics.median(values),
            'p95':values[min(len(values)-1,math.ceil(.95*len(values))-1)],'max':values[-1]}


def replay_native(csv_path, profile_path, config_path=BASE/'profiles/live_scaling_demo.json'):
    """Run a frozen native CSV through the same validator/scaler, without sockets.

    The replay clock is synthetic: these results are not real-time timing evidence.
    """
    profile,_=read_ev(csv_path,profile_path)
    verify_configuration(Path(csv_path).with_suffix('.xml'),profile)
    processor=LiveProcessor(Path(profile_path).read_bytes(),json.loads(Path(config_path).read_bytes()))
    result=[]
    with Path(csv_path).open(newline='') as source:
        for index,row in enumerate(csv.DictReader(source)):
            line=io.StringIO();csv.writer(line).writerow([row[key] for key in CSV_FIELDS])
            clock=float(row['time_s'])
            packet={'version':1,'session_id':'offline-replay','sequence':index,'sender_qpc_s':clock,
                    'send_errors':0,'event':'sample','csv':line.getvalue().strip()}
            result.append(processor.accept(json.dumps(packet).encode(),clock))
    return result,{'source_kind':'offline_replay','statistics':processor.stats,
                   'real_time_timing_evidence':False}


def describe_stale_intervals(events):
    """Evidence only: never exempts a stale interval from safety or acceptance.

    A terminal silence has no recovery sample; sender/receiver gaps distinguish
    a publisher pause from delayed delivery without guessing the operator action.
    """
    rows=[e['row'] for e in events if e['kind']=='sample']
    result=[]
    for event in events:
        if event['kind']!='state':continue
        if event['state'].startswith('STALE'):
            previous=next((r for r in reversed(rows) if r['received_qpc_s']<=event['host_qpc_s']),None)
            result.append(dict(start_host_s=event['host_qpc_s'],end_host_s=None,
                previous_sequence=previous['sequence'] if previous else None,
                previous_sim_s=previous['time_s'] if previous else None,
                last_receipt_s=previous['received_qpc_s'] if previous else None,
                next_sequence=None,position='unresolved'))
        elif result and result[-1]['end_host_s'] is None:
            interval=result[-1];interval['end_host_s']=event['host_qpc_s']
            following=next((r for r in rows if r['received_qpc_s']>interval['start_host_s'] and
                            r['received_qpc_s']<=event['host_qpc_s']),None)
            if following is not None and interval['last_receipt_s'] is not None:
                interval.update(next_sequence=following['sequence'],next_sim_s=following['time_s'],
                    host_sample_gap_s=following['received_qpc_s']-interval['last_receipt_s'],
                    position='initial_sample_gap' if interval['previous_sequence']==0 and following['sequence']==1 else 'between_samples')
                previous=next(r for r in rows if r['received_qpc_s']==interval['last_receipt_s'])
                interval['sender_sample_gap_s']=following['sender_qpc_s']-previous['sender_qpc_s']
            else:
                interval.update(position='terminal_silence',
                    silence_at_stop_s=event['host_qpc_s']-interval['last_receipt_s'] if interval['last_receipt_s'] is not None else None)
    return result


def write_report(receiver):
    events = [json.loads(line) for line in (receiver.output/'received.jsonl').read_text().splitlines()]
    rows = [event['row'] for event in events if event['kind']=='sample']
    adjacent = [(a,b) for a,b in zip(rows,rows[1:]) if a['session_id']==b['session_id']]
    wall = sum(b['received_qpc_s']-a['received_qpc_s'] for a,b in adjacent)
    sim = sum(b['time_s']-a['time_s'] for a,b in adjacent)
    active = [(a,b) for a,b in adjacent if b['received_qpc_s']-a['received_qpc_s'] <= receiver.processor.config['stale_after_s']]
    active_wall = sum(b['received_qpc_s']-a['received_qpc_s'] for a,b in active)
    active_sim = sum(b['time_s']-a['time_s'] for a,b in active)
    report = {
        'status':'simulation_only; physical battery and real Tesla calibration pending',
        'statistics':receiver.processor.stats,'receiver_error':receiver.failed,
        'expected_shutdown_resets':receiver.expected_shutdown_resets,
        'clock_verified':receiver.processor.shared_clock,'final_state':receiver.processor.state(),
        'samples':len(rows),'sim_duration_s':sim,'wall_duration_s':wall,
        'sim_to_wall_ratio':sim/wall if wall else None,
        'active_sim_to_wall_ratio':active_sim/active_wall if active_wall else None,
        'excluded_stale_host_intervals':len(adjacent)-len(active),
        'state_transitions':[event['state'] for event in events if event['kind']=='state'],
        'stale_intervals':describe_stale_intervals(events),
        'received_hz':len(adjacent)/wall if wall else None,
        'interarrival_ms':distribution([(b['received_qpc_s']-a['received_qpc_s'])*1000 for a,b in adjacent]),
        'sender_to_receive_ms':distribution([row['sender_age_ms'] for row in rows if row['sender_age_ms'] is not None]),
        'processing_ms':distribution([event['processing_ms'] for event in events if event['kind']=='sample']),
        'fixed_cell_parameters':receiver.processor.cell.__dict__,
        'prototype_current_config':asdict(receiver.processor.current_config),
        **current_metadata(),
        'clipped_samples':sum(row['command_saturated'] for row in rows),
        'current_range_A':[min(row['cell_current_command_A'] for row in rows),max(row['cell_current_command_A'] for row in rows)] if rows else None,
        'source_sha256':hashlib.sha256((receiver.output/'received.jsonl').read_bytes()).hexdigest(),
        'profile_sha256':hashlib.sha256((receiver.output/'vehicle_profile.json').read_bytes()).hexdigest(),
        'config_sha256':hashlib.sha256((receiver.output/'scaling_config.json').read_bytes()).hexdigest(),
        'hardware_commands_sent':False,
        'publisher_send_errors':max((row['send_errors'] for row in rows),default=0),
        'visual_hud_feedback':receiver.hud_stats,
    }
    (receiver.output/'timing_report.json').write_text(json.dumps(report,indent=2)+'\n')
    if rows:
        with (receiver.output/'live_profile.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,axes=plt.subplots(3,1,sharex=True,figsize=(12,8),layout='constrained')
        t=[row['time_s'] for row in rows]
        axes[0].plot(t,[row['speed_mps']*3.6 for row in rows]);axes[0].set_ylabel('Speed (km/h)')
        axes[1].plot(t,[row['pack_power_W']/1000 for row in rows]);axes[1].set_ylabel('Simulated pack kW')
        axes[2].plot(t,[row['cell_current_unclamped_A'] for row in rows],label='Requested')
        axes[2].plot(t,[row['cell_current_command_A'] for row in rows],label='Limited')
        instrument_log=receiver.output/'mock_instruments/instruments.jsonl'
        if instrument_log.exists():
            source_times={(r['session_id'],r['sequence']):r['time_s'] for r in rows}
            controls=[json.loads(line) for line in instrument_log.read_text().splitlines()]
            controls=[e for e in controls if e['state']=='RUNNING' and (e.get('source_session'),e.get('source_sequence')) in source_times]
            ct=[source_times[e['source_session'],e['source_sequence']] for e in controls]
            axes[2].plot(ct,[e['applied_target_A'] for e in controls],label='Applied')
            axes[2].plot(ct,[e['mock_cell_current_A'] for e in controls],label='Mock measured')
        axes[2].set_ylabel('Cell demand (A)');axes[2].set_xlabel('Simulation time (s)');axes[2].legend()
        for ax in axes:ax.grid(alpha=.3)
        fig.suptitle('Live native EV telemetry: fixed scaling; simulation only')
        fig.savefig(receiver.output/'live_profile.png',dpi=140);plt.close(fig)
    text = '# Live telemetry timing report\n\nSimulation only; no physical battery measurements or commands.\n\n'
    for key in ('samples','sim_duration_s','wall_duration_s','sim_to_wall_ratio','received_hz',
                'clock_verified','sender_to_receive_ms','processing_ms','statistics','clipped_samples'):
        text += f'- {key}: `{report[key]}`\n'
    (receiver.output/'timing_report.md').write_text(text,encoding='utf-8')
    return report
