#!/usr/bin/env python3
"""Native Windows Release/x64 tutorial build, deployment and headless smoke checks.
Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.

Linux instrumentation/scenarios remain in run_races.py. This runner exercises
the documented PowerShell workflow and real wtorcs.exe in a private runtime.
"""
import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

from maintenance import ROOT, DOCS, Run, digest, check_archives
from race_support import replace_once, write_race, read_ranks, require, race_entries

MODULES = ['tutorial'+s for s in '23456abc']


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def powershell(run, label, script, cwd):
    script = "$ErrorActionPreference = 'Stop'\n" + script
    (run.work/(label+'.ps1')).write_text(script, encoding='utf-8-sig')
    # Keep compiler scratch separate from persistent outputs (MSB8029).
    scratch = run.work/'tmp'
    scratch.mkdir(exist_ok=True)
    return run.command(label, ['powershell', '-NoProfile', '-Command', script],
                       cwd=cwd, env=dict(os.environ, VSLANG='1033', TEMP=str(scratch), TMP=str(scratch)))


def junction(run, target, link):
    assert target.is_dir() and not link.exists(), (target, link)
    link.parent.mkdir(parents=True, exist_ok=True)
    powershell(run, 'junction-'+str(len(run.report['checks'])),
               f'New-Item -ItemType Junction -Path {quote(link)} -Target {quote(target)} | Out-Null', ROOT)


def blocks(anchor):
    text = (DOCS/'windows.md').read_text(encoding='utf-8')
    sections = re.split(r'^## ', text, flags=re.M)
    found = [s for s in sections if '{#'+anchor+'}' in s.split('\n')[0]]
    assert len(found) == 1, ('Missing/ambiguous documentation section', anchor)
    return re.findall(r'```powershell\n(.*?)```', found[0], re.S)


def workflow(module):
    suffix = module[-1]
    anchor = 'robot_tutorial_windows_'+('appendix_' if suffix in 'abc' else 'chapter_')+suffix
    commands = blocks(anchor)
    copy = [b for b in commands if b.startswith('if (Test-Path')]
    build = [b for b in commands if b.startswith('& $msbuild')]
    assert len(copy) == len(build) == 1, anchor
    return copy[0], build[0], [b for b in commands if b.startswith('Copy-Item')]


def verify_build_summary(output, count):
    for kind in ('Warning', 'Error'):
        assert len(re.findall(r'^\s*0 '+kind+r'\(s\)\s*$', output, re.M)) == count, output


def build(run, fixture, module, discovery, label):
    output = powershell(run, label, discovery+'\n'+workflow(module)[1], fixture)
    count = 2 if module == 'tutorial5' else 1
    verify_build_summary(output, count)
    source = fixture/'src/drivers'/module
    modules = [module] + (['tutorial5pace'] if module == 'tutorial5' else [])
    binaries = {}
    for name in modules:
        target = source/'build'
        if module == 'tutorial5': target /= name
        target = target/'x64/Release'/(name+'.dll')
        installed = fixture/'runtime/drivers'/name/(name+'.dll')
        assert digest(target) == digest(installed), installed
        binaries[name] = digest(installed)
    run.report['builds'].append({'name': label, 'binaries': binaries,
        'sources': {p.name: digest(p) for p in source.iterdir() if p.suffix in ('.cpp', '.h', '.vcxproj', '.def')}})
    run.save()
    return output


def prepare(run, runtime):
    image = (runtime/'wtorcs.exe').read_bytes()
    offset = int.from_bytes(image[60:64], 'little')
    assert image[:2] == b'MZ' and image[offset:offset+4] == b'PE\0\0', 'Invalid wtorcs.exe'
    assert int.from_bytes(image[offset+4:offset+6], 'little') == 0x8664, 'Release/x64 runtime required'
    fixture = run.work/'tree'
    (fixture/'src/drivers').mkdir(parents=True)
    (fixture/'src/doc/robot_tutorial').mkdir(parents=True)
    shutil.copytree(DOCS/'examples', fixture/'src/doc/robot_tutorial/examples')
    for path in [ROOT/'Directory.Build.props', *ROOT.glob('*.h')]:
        shutil.copy2(path, fixture/path.name)
    # Read-only dependencies: all build outputs and install targets are private.
    junction(run, ROOT/'export', fixture/'export')
    junction(run, ROOT/'src/windows', fixture/'src/windows')
    private = fixture/'runtime'
    (private/'drivers').mkdir(parents=True)
    for p in runtime.iterdir():
        if p.is_file() and p.suffix.lower() in ('.exe', '.dll'):
            shutil.copy2(p, private/p.name)
    shutil.copytree(runtime/'config', private/'config')
    for name in ('cars', 'tracks', 'data', 'modules'):
        junction(run, runtime/name, private/name)
    return fixture


def installed_assets(fixture, module):
    source = fixture/'src/drivers'/module
    return [(p, fixture/'runtime/drivers'/('tutorial5pace' if p.name == 'tutorial5pace.xml' else module)/p.relative_to(source))
            for p in source.rglob('*') if 'build' not in p.relative_to(source).parts
            and (p.suffix in ('.xml', '.rgb') or p.name == 'ARTWORK.txt')]


def deployment(run, fixture, discovery):
    for module in MODULES:
        for source, installed in installed_assets(fixture, module):
            assert source.read_bytes() == installed.read_bytes(), installed
    for module in ('tutoriala', 'tutorialb', 'tutorialc'):
        assets = installed_assets(fixture, module)
        dll = fixture/'runtime/drivers'/module/(module+'.dll')
        before = digest(dll)
        # Remove only disposable fixture assets, then test the up-to-date target.
        for _, installed in assets: installed.unlink()
        output = build(run, fixture, module, discovery, module+'-redeploy')
        assert 'CL.exe ' not in output and 'link.exe ' not in output, module
        assert digest(dll) == before, module
        for source, installed in assets:
            assert source.read_bytes() == installed.read_bytes(), installed
        for n, command in enumerate(workflow(module)[2]):
            powershell(run, module+f'-copy-assets-{n}', command, fixture)
        run.report['deployment'][module] = {'assets': len(assets), 'status': 'passed'}
        run.save()


def profile_path():
    # Match main.cpp's SHGetFolderPath rather than assuming LOCALAPPDATA overrides it.
    buffer = ctypes.create_unicode_buffer(260)
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x1c, None, 0, buffer)
    assert result == 0, ('SHGetFolderPathW failed', result)
    profile = Path(buffer.value)/'torcs'
    # main.cpp otherwise initializes missing files in the user's profile. Require
    # a prepared installation so this runner never creates/changes user settings.
    for name in ('drivers/human/car.xml', 'drivers/human/human.xml', 'drivers/human/preferences.xml',
                 'config/graph.xml', 'config/raceengine.xml', 'config/screen.xml',
                 'config/sound.xml', 'config/style.xsl'):
        assert (profile/name).is_file(), f'Launch TORCS once to prepare the profile: {profile/name}'
    # Legacy shipped comments contain Latin-1 bytes despite the UTF-8 declaration.
    # Ignore comments for inspection, without rewriting or relaxing setting values.
    engine = ET.fromstring(re.sub(rb'<!--.*?-->', b'',
                                 (profile/'config/raceengine.xml').read_bytes(), flags=re.S))
    for name, expected in [('track', 'track'), ('simu', 'simuv2')]:
        assert require(engine, f"./section[@name='Modules']/attstr[@name='{name}']").get('val') == expected
    for module in MODULES+['tutorial5pace']:
        assert not (profile/'drivers'/module).exists(), f'Local driver override would affect the check: {module}'
    assert (profile/'results').is_dir(), 'Run a TORCS race once to prepare the results directory'
    return profile


def validate_ranks(ranks, entries, laps, demo=False):
    assert len(ranks) == len(entries), ranks
    assert {(r['module'], int(r['idx'])) for r in ranks} == set(entries), ranks
    for rank in ranks:
        # A deliberately slow pace car is lapped; the tested primary must finish.
        expected = 1 if rank['module'] == 'tutorial5pace' else laps
        assert int(rank['laps']) >= expected, rank
        assert all(math.isfinite(float(rank[key])) and float(rank[key]) > 0
                   for key in ('best lap time', 'top speed')), rank
        if rank['module'] != 'tutorial2':
            assert int(rank['dammages']) == 0 and float(rank['penaltytime']) == 0, rank
        assert int(rank['pits stops']) == (1 if demo else 0), rank


def race(run, fixture, profile, case, timeout):
    name, entries, laps = case['name'], race_entries(case), case.get('laps', 6)
    work = run.work/name
    work.mkdir()
    results = work/'results'
    results.mkdir()
    config = work/(run.work.name+'-'+name+'.xml')
    write_race(config, entries, track=case.get('track', 'g-track-1'), laps=laps)
    link = profile/'results'/config.stem
    assert not link.exists(), link
    record = {'scenario': case, 'entries': entries, 'laps': laps, 'status': 'running',
              'config_sha256': digest(config), 'modules': {
                  m: digest(fixture/'runtime/drivers'/m/(m+'.dll')) for m, _ in entries}}
    run.report['races'].append(record)
    run.save()
    junction(run, results, link)
    try:
        run.command(name+'-race', [fixture/'runtime/wtorcs.exe', '-r', config],
                    cwd=fixture/'runtime', timeout=timeout)
        files = list(results.glob('*.xml'))
        assert len(files) == 1, ('Expected one fresh result', files)
        ranks = read_ranks(files[0])
        record.update(ranks=ranks, result_sha256=digest(files[0]))
        run.save()
        validate_ranks(ranks, entries, laps, case.get('demo', False))
        record['status'] = 'passed'
        print('PASS:', name, flush=True)
    except Exception as error:
        record.update(status='failed', error=str(error))
        raise
    finally:
        # Remove the junction itself, never its artifact target. No existing
        # profile results or settings are modified; preserve all fresh evidence.
        os.rmdir(link)
        run.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-root', type=Path, required=True, help='Existing artifact parent')
    parser.add_argument('--runtime', type=Path, default=ROOT/'runtime', help='Prepared Release/x64 runtime')
    parser.add_argument('--checks', choices=('build', 'deployment', 'races', 'all'), default='all',
                        help='All modes build fresh DLLs; deployment/races add the selected checks')
    parser.add_argument('--timeout', type=int, default=180, help='Per-race timeout in seconds')
    args = parser.parse_args()
    if sys.platform != 'win32': parser.error('Windows only; use run_races.py for native Linux scenarios')
    runtime = args.runtime.resolve(strict=True)
    with Run(args.work_root, 'win') as run:
        run.report.update(configuration='Release', architecture='x64', checks_requested=args.checks,
                          deployment={}, races=[], builds=[], linux_execution='not requested',
                          deployment_status='pending' if args.checks in ('deployment', 'all') else 'not requested',
                          race_status='pending' if args.checks in ('races', 'all') else 'not requested',
                          archives=check_archives())
        fixture = prepare(run, runtime)
        discovery = [b for b in blocks('robot_tutorial_windows_build') if b.startswith('$vswhere')]
        assert len(discovery) == 1
        discovery = discovery[0]
        for module in MODULES:
            powershell(run, module+'-copy', workflow(module)[0], fixture)
            build(run, fixture, module, discovery, module+'-build')
            print('PASS:', module, 'build', flush=True)
        if args.checks in ('deployment', 'all'):
            deployment(run, fixture, discovery)
            run.report['deployment_status'] = 'passed'
        if args.checks in ('races', 'all'):
            profile = profile_path()
            for p in (fixture/'runtime/config/raceman').glob('*.xml'):
                assert (profile/'config/raceman'/p.name).is_file(), f'Profile not initialized: {p.name}'
            run.report.update(binary_sha256=digest(fixture/'runtime/wtorcs.exe'),
                              physics_sha256=digest(runtime/'modules/simu/simuv2.dll'),
                              profile=str(profile), raceengine_sha256=digest(profile/'config/raceengine.xml'))
            scenarios = json.loads((Path(__file__).parent/'scenarios.json').read_text(encoding='utf-8'))
            selected = ['ch3-g1', 'ch4-g1', 'ch5-pace', 'ch6-g1', 'appendix-a',
                        'appendix-b', 'multi-red', 'multi-teal', 'multi-pair', 'pit-demo']
            cases = {name: next(c for c in scenarios if c['name'] == name) for name in selected}
            # Extra early recovery checkpoint; Linux's instrumented racing checks
            # do not assert crash-free behavior for this deliberate mistake.
            race(run, fixture, profile, {'name': 'ch2-recovery', 'module': 'tutorial2', 'laps': 3}, args.timeout)
            for case in cases.values():
                if case.get('demo'): continue
                assert set(case) <= {'name', 'module', 'track', 'laps', 'indices', 'opponent', 'opponent_first'}, case
                race(run, fixture, profile, case, args.timeout)
            pit = fixture/'src/drivers/tutorial6/pit.cpp'
            original = pit.read_bytes()
            try:
                pit.write_text(replace_once(original.decode('utf-8'), 'DEMONSTRATION_STOP = false',
                                            'DEMONSTRATION_STOP = true'), encoding='utf-8', newline='\n')
                build(run, fixture, 'tutorial6', discovery, 'ch6-demo-build')
                race(run, fixture, profile, cases['pit-demo'], args.timeout)
            finally:
                pit.write_bytes(original)
                build(run, fixture, 'tutorial6', discovery, 'ch6-restore-build')
            run.report['race_status'] = 'passed'
        run.save()


if __name__ == '__main__':
    main()
