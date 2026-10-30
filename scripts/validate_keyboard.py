"""Scripted headless human-input comparison, actual TORCS, mock instruments only.

The separate fixture DLL compiles the real human.cpp. It substitutes GUI callback
registration and mouse polling for headless operation, supplies scripted key
states/fake axes, and never replaces human.dll or sends OS keyboard events.
"""
import argparse
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from configure_tesla import ROOT, RUNTIME, TORCS, section, attribute, write
from configure_keyboard import prepare_keyboard, G29_PROFILE
from run_tesla_ai import build
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.local/matplotlib'))
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
from torcs_live import LiveReceiver
from instrument_control import MockInstrumentService


def fingerprint(folder):
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(folder).rglob('*') if p.is_file()}


def trial(output, enabled=True, analog=False, standalone=False, slow=False):
    config=ROOT/'aps380_torcs_starter/profiles/keyboard_driving.json'
    if slow:
        rates=json.loads(config.read_text());rates['throttle_rise_per_s']=.25
        config=output/'slow.json';config.write_text(json.dumps(rates))
    profile=prepare_keyboard(config,destination=output/'profile')
    prefs=profile/'drivers/human/preferences.xml'
    tree=ET.parse(prefs).getroot()
    driver=section(section(section(tree,'Preferences'),'Drivers'),'1')
    attribute(driver,'aps380 keyboard pedal ramp','yes' if enabled else 'no')
    if analog:
        for pedal,axis in (('throttle','AXIS2-0'),('brake','AXIS3-0')):
            attribute(driver,pedal,axis)
            for key,value in (('min',1),('max',-1),('power',1),('sensitivity',1)):
                attribute(driver,pedal+' '+key,value)
    write(tree,prefs)
    fixture='aps380_keyboard_fixture'
    binary=RUNTIME/'drivers'/fixture/(fixture+'.dll')
    binary.parent.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'.local/keyboard-tests'/binary.name,binary)
    # Definition and preferences are copied into this isolated fixture profile.
    robot=ET.parse(profile/'drivers/human/human.xml').getroot()
    # Console races reject type=human. Only this separate scripted test module
    # is declared a robot; the real human definition/profile is unchanged.
    for entry in robot.findall("section[@name='Robots']/section[@name='index']/section"):
        attribute(entry,'type','robot')
    write(robot,profile/'drivers'/fixture/(fixture+'.xml'))
    race=ET.parse(profile/'config/raceman/practice.xml').getroot()
    for name in ('Drivers','Drivers Start List'):
        group=section(race,name)
        for child in list(group):
            if child.tag=='section':group.remove(child)
        entry=section(group,'1');attribute(entry,'module',fixture);attribute(entry,'idx',1)
    attribute(section(race,'Drivers'),'focused module',fixture)
    track=section(section(race,'Tracks'),'1')
    attribute(track,'name','g-track-1');attribute(track,'category','road')
    attribute(section(race,'Practice'),'display mode','results only')
    write(race,profile/'race.xml')
    if standalone:
        sys.path.insert(0,str(ROOT/'bench/bk8500'))
        from live_control import LiveConfig,LiveService,MockLiveLoad
        cfg=LiveConfig(reference_current_A=.05)
        service=LiveService(MockLiveLoad(cfg,delay_s=.064),cfg,output/'instruments')
    else:service=MockInstrumentService(output/'instruments')
    receiver=LiveReceiver(0,output/'telemetry',demand_sink=service.demands)
    env=dict(os.environ,APS380_LIVE_PORT=str(receiver.port),APS380_LIVE_REALTIME='1',
        APS380_TORCS_PROFILE=str(profile),APS380_FIXTURE_TRACE=str(output/'pedals.csv'))
    env.pop('APS380_FIXTURE_ANALOG',None)
    if analog:env['APS380_FIXTURE_ANALOG']='1'
    proc=None;armed=False;service.start();receiver.start()
    try:
        with (output/'torcs.log').open('w') as log:
            proc=subprocess.Popen([str(RUNTIME/'wtorcs.exe'),'-r',str(profile/'race.xml')],
                cwd=RUNTIME,env=env,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.perf_counter()+35
            while time.perf_counter()<deadline:
                row=receiver.processor.current
                if row and not armed:service.request('arm');armed=True
                if row and row['time_s']>=14:break
                if receiver.failed or proc.poll() is not None:raise RuntimeError('Fixture/telemetry failed; inspect '+str(output))
                time.sleep(.02)
            else:raise RuntimeError('Fixture did not reach 14 simulation seconds')
    finally:
        report=service.close();receiver.begin_shutdown()
        if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=10)
        timing=receiver.close()
    assert timing['samples']>600 and timing['statistics']['missing']==timing['statistics']['invalid']==0
    assert not timing['receiver_error'] and not timing['stale_intervals']
    if standalone:
        assert report['passed'] and report['shutdown_verified'],report
    else:
        assert report['acceptance']['passed'] and report['final']['shutdown_verified'],report['acceptance']
    summary=dict(enabled=enabled,analog=analog,standalone=standalone,slow=slow,
        mock_only=True,telemetry=timing,instruments=report)
    (output/'trial.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


def read_rows(path):
    with Path(path).open() as f:return [{k:float(v) for k,v in r.items()} for r in csv.DictReader(f)]


def compare(output):
    before=read_rows(output/'legacy/pedals.csv');after=read_rows(output/'smoothed/pedals.csv')
    slow=read_rows(output/'slow/pedals.csv')
    def at(rows,t):return min(rows,key=lambda r:abs(r['time_s']-t))
    rates=json.loads((output/'smoothed/profile/keyboard_driving.json').read_text())
    # Compare the measured native trace with the selected fixed rates, allowing
    # one robot callback of discretization at each scripted key edge.
    expected_throttle=min(1.,2*rates['throttle_rise_per_s'])
    assert abs(at(after,1.)['ramp_throttle']-min(1.,rates['throttle_rise_per_s']))<.03
    assert abs(at(after,2.5)['ramp_throttle']-max(0.,expected_throttle-.5*rates['throttle_fall_per_s']))<.03
    assert abs(at(after,4.5)['ramp_brake']-min(1.,.5*rates['brake_rise_per_s']))<.03
    assert abs(at(after,5.25)['ramp_brake']-max(0.,min(1.,rates['brake_rise_per_s'])-.25*rates['brake_fall_per_s']))<.03
    assert .20<at(slow,1.)['ramp_throttle']<.30
    assert at(before,.5)['applied_throttle']>at(after,.5)['applied_throttle']+.2
    assert at(before,2.1)['applied_throttle']==0
    assert abs(at(after,2.1)['ramp_throttle']-max(0.,expected_throttle-.1*rates['throttle_fall_per_s']))<.03
    a=read_rows(output/'analog-legacy/pedals.csv');b=read_rows(output/'analog-opt-in/pedals.csv')
    n=min(len(a),len(b));assert n>600
    assert all(x['time_s']==y['time_s'] and abs(x['applied_throttle']-y['applied_throttle'])<1e-9
        and abs(x['applied_brake']-y['applied_brake'])<1e-9 for x,y in zip(a[:n],b[:n]))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,1,sharex=True,figsize=(10,8))
    for label,rows,name in [('Legacy',before,'legacy'),('Smoothed',after,'smoothed')]:
        axes[0].plot([r['time_s'] for r in rows],[r['applied_throttle'] for r in rows],label=label)
        axes[1].plot([r['time_s'] for r in rows],[r['applied_brake'] for r in rows],label=label)
        samples=[json.loads(x)['row'] for x in (output/name/'telemetry/received.jsonl').read_text().splitlines() if json.loads(x)['kind']=='sample']
        axes[2].plot([r['time_s'] for r in samples],[r['cell_current_unclamped_A'] for r in samples],label=label)
    for ax,label in zip(axes,('Applied throttle','Applied brake','Signed cell demand (A)')):
        ax.set_ylabel(label);ax.grid();ax.legend()
    axes[2].set_xlabel('Simulation seconds');fig.tight_layout();fig.savefig(output/'comparison.png');plt.close(fig)
    return dict(keyboard_press_release_passed=True,configured_rate_passed=True,
        analog_bypass_identical_samples=n,
        interpretation='Identical scripted key states; different trajectories/speeds cause current curves to differ. Not a matched-speed electrical benchmark.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path)
    args=p.parse_args();output=(args.output_dir or ROOT/'.local/keyboard-validation'/datetime.now().strftime('%Y%m%d_%H%M%S')).resolve()
    output.mkdir(parents=True,exist_ok=False)
    protected={str(root):fingerprint(root) for root in (G29_PROFILE,Path(os.environ['LOCALAPPDATA'])/'torcs')}
    build(ROOT/'scripts/tests/keyboard_fixture.vcxproj',output/'fixture-build.log')
    sources=[Path(__file__),ROOT/'scripts/tests/keyboard_fixture.cpp',
        ROOT/'scripts/configure_keyboard.py',ROOT/'aps380_torcs_starter/profiles/keyboard_driving.json',
        TORCS/'src/drivers/human/human.cpp',TORCS/'src/drivers/human/human.h',
        TORCS/'src/drivers/human/aps380_keyboard.h',RUNTIME/'drivers/human/human.dll',
        ROOT/'.local/keyboard-tests/aps380_keyboard_fixture.dll',RUNTIME/'modules/simu/simuv2.dll']
    (output/'manifest.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sources},indent=2)+'\n')
    results={}
    try:
        for name,options in [('legacy',dict(enabled=False)),('smoothed',{}),('slow',dict(slow=True)),
                ('analog-legacy',dict(enabled=False,analog=True)),('analog-opt-in',dict(analog=True)),
                ('standalone',dict(standalone=True))]:
            folder=output/name;folder.mkdir()
            results[name]=trial(folder,**options)
            print(name,'PASS',results[name]['telemetry']['samples'],'samples',flush=True)
        results['comparison']=compare(output)
    finally:
        # Remove only our generated fixture DLL, never the real human module.
        fixture_binary=RUNTIME/'drivers/aps380_keyboard_fixture/aps380_keyboard_fixture.dll'
        if fixture_binary.exists():
            assert hashlib.sha256(fixture_binary.read_bytes()).digest()==hashlib.sha256(
                (ROOT/'.local/keyboard-tests/aps380_keyboard_fixture.dll').read_bytes()).digest()
            fixture_binary.unlink()
            if not any(fixture_binary.parent.iterdir()):fixture_binary.parent.rmdir()
        preserved=all(fingerprint(root)==hashes for root,hashes in protected.items())
        results['g29_profiles_byte_preserved']=preserved
        (output/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
        assert preserved,'Protected G29 profile changed'
    print('PASS:',output,flush=True)


if __name__=='__main__':main()
