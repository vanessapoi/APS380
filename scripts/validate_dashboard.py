"""Actual TORCS / Tk dashboard acceptance, mocked instruments only. No hardware."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
from unittest.mock import patch

from configure_tesla import ROOT,RUNTIME
from run_tesla_ai import prepare_profile
from validate_keyboard import fingerprint,G29_PROFILE
sys.path.insert(0,str(ROOT/'aps380_torcs_starter'))
import live_display
import run_vehicle_power_limit as power_launcher
import run_tesla_live as original_launcher


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--screenshots',action='store_true',help='Capture only the test dashboard window, never the full desktop')
    args=p.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.local/matplotlib'))
    protected=list((ROOT/'bench/bk8500').glob('*.py'))
    protected += [p for p in (ROOT/'aps380_torcs_starter').glob('*.py') if p.name not in ('live_display.py','test_dashboard.py')]
    protected += list((ROOT/'aps380_torcs_starter/profiles').glob('*.json'))
    protected += [ROOT/'scripts/run_tesla_live.py',ROOT/'scripts/run_vehicle_power_limit.py',
        RUNTIME/'drivers/human/human.dll',RUNTIME/'modules/simu/simuv2.dll']
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    profiles={str(p):fingerprint(p) for p in (G29_PROFILE,Path(os.environ['LOCALAPPDATA'])/'torcs')}
    sources=[Path(__file__),ROOT/'aps380_torcs_starter/live_display.py',ROOT/'aps380_torcs_starter/test_dashboard.py']
    (output/'manifest.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},indent=2)+'\n')
    results={};capture={}
    for name in ('prototype','bk8500','fixed_rint','live_rint','demo','bk8500_loss'):
        folder=output/name
        class RecordingDisplay(live_display.LiveDisplay):
            def __init__(self,*a,**kw):
                super().__init__(*a,**kw)
                self.started=time.perf_counter();self.observations=[];self.screenshots=[];self.saved=set()
                if args.screenshots:self.root.geometry('+20+20');self.root.lift()
                else:self.root.withdraw()
            def refresh(self):
                elapsed=time.perf_counter()-self.started
                if elapsed>=2:
                    names=list(self.tabs);selected=names[min(int((elapsed-2)/1.8),len(names)-1)]
                    if name=='bk8500_loss' and elapsed>=7:selected='Safety & Logs'
                    self.notebook.select(self.tabs[selected])
                super().refresh()
                self.observations.append(dict(host_s=time.perf_counter(),tab=self.notebook.tab(self.notebook.select(),'text'),
                    state=self.state_label.cget('text'),readouts={k:v.cget('text') for k,v in self.readouts.items()},
                    health=self.health_label.cget('text'),redraw_ms=self.render_times[-1],diagnostics=self.values.cget('text')))
                selected=self.observations[-1]['tab']
                wanted={'prototype':('Battery','Instruments'),'bk8500':('Instruments','BK8500 current'),
                        'fixed_rint':('SOC & SOP',),'live_rint':('SOC & SOP','Safety & Logs'),'demo':('Vehicle',)}.get(name,())
                # Wait for a refresh after switching, then capture only our Tk client area.
                if args.screenshots and selected in wanted and selected not in self.saved and elapsed>3:
                    self.saved.add(selected)
                    def grab(tab=selected):
                        from PIL import ImageGrab
                        import inspect
                        self.root.update_idletasks()
                        # Window-buffer capture avoids both DPI cropping and
                        # accidentally recording another app/notification over us.
                        if os.name!='nt' or 'window' not in inspect.signature(ImageGrab.grab).parameters:
                            raise RuntimeError('Screenshots require Windows/Pillow window capture; omit --screenshots')
                        import ctypes
                        from ctypes import wintypes
                        ancestor=ctypes.windll.user32.GetAncestor
                        ancestor.argtypes=[wintypes.HWND,wintypes.UINT];ancestor.restype=wintypes.HWND
                        window=ancestor(self.root.winfo_id(),2)
                        file=folder/(re.sub(r'[^a-z0-9]+','-',tab.lower()).strip('-')+'.png')
                        ImageGrab.grab(window=int(window)).save(file)
                        self.screenshots.append(file.name)
                    self.root.after(150,grab)
            def run(self):
                try:super().run()
                finally:capture.update(observations=self.observations,screenshots=self.screenshots)
        with (output/(name+'-console.log')).open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log),patch.object(live_display,'LiveDisplay',RecordingDisplay):
            if name=='prototype':
                def prepare(destination):return prepare_profile(destination,manual_profile=G29_PROFILE)
                with patch.object(original_launcher,'prepare_profile',side_effect=prepare),patch.object(sys,'argv',
                    ['run_tesla_live.py','--mode','ai','--duration','14','--skip-build','--mock-instruments','--mock-arm',
                     '--acceptance','smoke','--output-dir',str(folder)]):original_launcher.main()
                report=json.loads((folder/'trial.json').read_text());assert report['all_software_gates_passed']
                timing=json.loads((folder/'timing_report.json').read_text())
                shutdown=report['mock_instruments']['final']['shutdown_verified'] if 'mock_instruments' in report else json.loads((folder/'mock_instruments/summary.json').read_text())['final']['shutdown_verified']
            elif name.startswith('bk8500'):
                sys.path.insert(0,str(ROOT/'bench/bk8500'));import live_torcs as bk
                argv=['--device','mock','--torcs','ai','--duration','14','--dashboard','--auto-arm-mock','--no-console',
                    '--max-current-A','.1','--reference-current-A','.05','--max-power-W','.6','--slew-A-per-s','.02',
                    '--tracking-tolerance-A','.01','--output',str(folder)]
                if name=='bk8500_loss':argv+=['--inject-telemetry-loss-after','8','--expect-telemetry-fault']
                code=bk.main(argv)
                assert code==0
                report=json.loads((folder/'trial.json').read_text());shutdown=report['instrument']['shutdown_verified']
                if name=='bk8500_loss':assert report['fault_response_passed'] and not report['acceptance']['normal_operation_passed']
                timing=json.loads((folder/'telemetry/timing_report.json').read_text())
            else:
                argv=['--mode','ai','--duration','12','--skip-build','--no-console','--output',str(folder)]
                if name!='demo':
                    config='rint_sop_live_mock_example.json' if name=='live_rint' else 'rint_sop_mock_example.json'
                    argv+=['--policy','rint-live-mock' if name=='live_rint' else 'rint','--sop-config',str(ROOT/'aps380_torcs_starter/profiles'/config)]
                if name=='live_rint':argv+=['--mock-arm']
                assert power_launcher.main(argv)==0
                report=json.loads((folder/'trial.json').read_text());shutdown=report['shutdown_zero_verified']
                timing=json.loads((folder/'telemetry/timing_report.json').read_text())
        observations=capture['observations']
        assert any(o['state']=='RECEIVING' for o in observations)
        assert not timing['receiver_error'] and timing['statistics']['invalid']==timing['statistics']['missing']==0
        if name!='bk8500_loss':assert not timing['stale_intervals']
        else:assert any(o['state'].startswith('STALE') for o in observations)
        if name=='live_rint':
            values={o['readouts']['cell_soc'] for o in observations if 'NOT AVAILABLE' not in o['readouts']['cell_soc']}
            assert len(values)>1 and any('MOCK counted' in v for v in values)
        if name in ('demo','prototype','bk8500','bk8500_loss'):
            assert all('NOT CONNECTED' in o['readouts']['cell_soc'] for o in observations)
        times=[o['redraw_ms'] for o in observations]
        p95=sorted(times)[int(.95*(len(times)-1))]
        assert p95<100,('UI exceeded its nominal 100 ms refresh budget',p95)
        (folder/'dashboard_observations.json').write_text(json.dumps(observations,indent=2)+'\n')
        results[name]=dict(passed=True,telemetry_samples=timing['samples'],telemetry_hz=timing['received_hz'],
            refreshes=len(observations),redraw_median_ms=statistics.median(times),redraw_p95_ms=p95,
            shutdown_verified=shutdown,screenshots=capture['screenshots'])
        if name=='bk8500_loss':results[name].update(normal_operation_passed=False,expected_fault_response_passed=True)
        assert shutdown
        print(name,results[name],flush=True)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    assert all(fingerprint(p)==h for p,h in profiles.items())
    result=dict(mock_only=True,passed=True,cases=results,protected_source_files=len(hashes),
                control_profiles_unchanged=True,physical_instruments_accessed=False,
                screenshot_scope='Own test Tk window only; no physical controls invoked')
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS',output,flush=True)


if __name__=='__main__':main()
