"""Bounded discharge-only playback of an existing offline TORCS-derived profile."""
import argparse, csv, hashlib, json, math, time
from datetime import datetime
from pathlib import Path
ROOT = Path('/Users/vanessa/Documents/VSCode/APS380')
SOURCE = ROOT/'aps380_torcs_starter/output/torcs_comparison/segment_03/candidate_smoothed_scaled/current_profile.csv'
PARAMS = SOURCE.with_name('parameters.json')

def prepare():
    with SOURCE.open() as f:
        rows = list(csv.DictReader(f))
    values = [(float(r['time_s']), float(r['cell_current_unclamped_A'])) for r in rows]
    if len(values)<2 or not all(math.isfinite(x) for v in values for x in v):
        raise ValueError('Invalid profile values')
    gaps = [b[0]-a[0] for a,b in zip(values,values[1:])]
    if min(gaps)<=0 or max(gaps)>.03:
        raise ValueError('Timestamp reset, duplicate or gap; no playback')
    t0 = values[0][0]; duration = values[-1][0]-t0
    bins=[]
    for n in range(math.ceil(duration)):
        start=t0+n; end=min(start+1,values[-1][0]); width=end-start
        signed=positive=negative_duration=0.0
        for (t,i),(next_t,_) in zip(values,values[1:]):
            overlap=max(0.0,min(end,next_t)-max(start,t))
            signed+=i*overlap; positive+=max(0,i)*overlap
            if i<0: negative_duration+=overlap
        bins.append({'step':n,'scheduled_s':float(n),'duration_s':width,'source_start_s':start,'source_end_s':end,'source_signed_mean_A':signed/width,'source_discharge_mean_A':positive/width,'regen_fraction':negative_duration/width})
    gain=.1/max(b['source_discharge_mean_A'] for b in bins)
    for b in bins:
        b['requested_A']=round(min(.1,max(0,b['source_discharge_mean_A']*gain))*10000)/10000
    meta={'source_csv':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'source_parameters':json.loads(PARAMS.read_text()),'source_samples':len(rows),'source_start_s':t0,'duration_s':duration,'maximum_source_gap_s':max(gaps),'current_column':'cell_current_unclamped_A','interval_method':'Source current held until next source timestamp; positive current integrated over each one-second interval; last interval retains actual remaining duration. No session stitching or time compression.','negative_current_handling':'Rectified to zero BEFORE interval averaging; signed mean and negative-duration fraction retained. No physical regeneration.','bench_gain_A_per_source_A':gain,'peak_limit_A':.1,'quantization_A':.0001,'purpose':'Low-current instrument playback test, not validation of cell scaling, model fidelity, live telemetry or battery feedback.'}
    return bins,meta

def run(output):
    import serial
    bins,meta=prepare()
    output.mkdir(parents=True,exist_ok=False)
    (output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
    with (output/'planned_profile.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(bins[0]));w.writeheader();w.writerows(bins)
    results=[]; outcome={'completed':False,'shutdown_verified':False}
    def query(s,cmd,data=b'',setter=False):
        p=bytearray(26);p[:3]=bytes([0xAA,0,cmd]);p[3:3+len(data)]=data;p[25]=sum(p[:25])&255
        s.reset_input_buffer();tick=time.monotonic();s.write(p);s.flush();r=s.read(26);elapsed=time.monotonic()-tick
        if len(r)!=26 or r[0]!=0xAA or r[1]!=0 or r[25]!=(sum(r[:25])&255):raise RuntimeError('Invalid response '+hex(cmd))
        if setter:
            if r[2]!=0x12 or r[3]!=0x80:raise RuntimeError('Command rejected '+hex(cmd))
        elif r[2]!=cmd:raise RuntimeError('Unexpected response '+hex(cmd))
        return r,elapsed
    def measure(s):
        r,_=query(s,0x5F)
        return {'voltage_V':int.from_bytes(r[3:7],'little')/1000,'measured_A':int.from_bytes(r[7:11],'little')/10000,'power_W':int.from_bytes(r[11:15],'little')/1000,'input_on':bool(r[15]&8),'status':int.from_bytes(r[16:18],'little')}
    try:
        with serial.Serial(port=None,baudrate=9600,timeout=1,write_timeout=1) as s:
            s.port='/dev/cu.usbserial-110';s.dtr=True;s.rts=True;s.open();time.sleep(.2)
            ident,_=query(s,0x6A)
            if ident[3:8].rstrip(b'\0 ')!=b'8500':raise RuntimeError('Unexpected instrument')
            try:
                query(s,0x20,b'\x01',True);query(s,0x21,b'\x00',True)
                mode,_=query(s,0x29);function,_=query(s,0x5E)
                if mode[3]!=0 or function[3]!=0:raise RuntimeError('Expected CC and FIXED function')
                before=measure(s);outcome['before']=before;print(json.dumps({'before':before}),flush=True)
                if before['input_on'] or not 4.5<=before['voltage_V']<=5.5 or before['status']&31:raise RuntimeError('Preflight failed')
                query(s,0x2A,(0).to_bytes(4,'little'),True);query(s,0x21,b'\x01',True)
                origin=time.monotonic()
                with (output/'measurements.csv').open('w',newline='') as f:
                    writer=None
                    for b in bins:
                        scheduled=origin+b['scheduled_s'];time.sleep(max(0,scheduled-time.monotonic()))
                        tick=time.monotonic()
                        if tick-scheduled>.25:raise RuntimeError('Replay schedule over 250 ms late')
                        _,rtt=query(s,0x2A,round(b['requested_A']*10000).to_bytes(4,'little'),True)
                        time.sleep(max(0,scheduled+.5-time.monotonic()))
                        m=measure(s)
                        row={**b,'command_start_s':tick-origin,'command_roundtrip_ms':rtt*1000,'measurement_received_s':time.monotonic()-origin,**m}
                        if writer is None:writer=csv.DictWriter(f,fieldnames=list(row));writer.writeheader()
                        writer.writerow(row);f.flush();results.append(row)
                        print(json.dumps({'step':b['step'],'requested_A':b['requested_A'],**m}),flush=True)
                        if not m['input_on'] or not 4.5<=m['voltage_V']<=5.5 or m['measured_A']>.15 or m['power_W']>1 or m['status']&31:raise RuntimeError('Measurement outside test bounds')
                    time.sleep(max(0,origin+meta['duration_s']-time.monotonic()))
                outcome['completed']=True
            finally:
                # OFF is attempted before zeroing or further readback.
                query(s,0x21,b'\x00',True)
                query(s,0x2A,(0).to_bytes(4,'little'),True);time.sleep(.3)
                after=measure(s);outcome['after']=after
                outcome['shutdown_verified']=not after['input_on']
                print(json.dumps({'after':after}),flush=True)
                if after['input_on']:raise RuntimeError('Input OFF not confirmed; use front panel OFF')
    except BaseException as exc:
        outcome['error']=str(exc)
        raise
    finally:
        outcome['samples']=len(results)
        if results:
            outcome['max_abs_tracking_error_A']=max(abs(r['measured_A']-r['requested_A']) for r in results)
            outcome['mean_command_roundtrip_ms']=sum(r['command_roundtrip_ms'] for r in results)/len(results)
            outcome['max_command_roundtrip_ms']=max(r['command_roundtrip_ms'] for r in results)
            outcome['max_command_schedule_lateness_ms']=max((r['command_start_s']-r['scheduled_s'])*1000 for r in results)
        (output/'result.json').write_text(json.dumps(outcome,indent=2)+'\n')
        print(json.dumps({'output_folder':str(output),'result':outcome}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');args=parser.parse_args()
    if args.run:
        run(Path('/Users/vanessa/Desktop/BK8500_Test')/('torcs_profile_'+datetime.now().strftime('%Y%m%d_%H%M%S')))
    else:
        bins,meta=prepare();print(json.dumps(meta,indent=2));print(json.dumps(bins,indent=2))
