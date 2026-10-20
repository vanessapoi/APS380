#!/usr/bin/env python3
"""Isolated Linux tutorial race scenarios with fresh telemetry and result evidence.
Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from maintenance import ROOT, DOCS, Run, digest
from race_support import require, replace_once, example, write_race, read_ranks, race_entries

HERE = Path(__file__).resolve().parent


def link_children(source, dest, excluded=()):
    dest.mkdir()
    for entry in source.iterdir():
        if entry.name not in excluded:
            (dest/entry.name).symlink_to(entry, target_is_directory=entry.is_dir())


def build_module(run, case, module, lib, data):
    source = example(module)
    build = lib.parent/(module+'-source')
    shutil.copytree(source, build)
    if module in ('tutorial5', 'tutorial5pace', 'tutorial5rear'):
        for stem in ('speed4', 'steering4', 'braking4', 'geometry4', 'recovery4'):
            for ext in ('.cpp', '.h'):
                shutil.copy(DOCS/'examples/chapter_4'/(stem+ext), build)
    main = build/(module+'.cpp')
    code = (build/('tutorial5pace.cpp' if module == 'tutorial5rear' else module+'.cpp')).read_text(encoding='utf-8')
    if module == 'tutorial5rear':
        code = code.replace('tutorial5pace', module).replace('Tutorial Pace', 'Maintenance Rear')
        code = replace_once(code, 'PACE_SPEED = 18.0', 'PACE_SPEED = 40.0')
        code = replace_once(code, '\tapplySpeedTarget(driver, car, PACE_SPEED, 1.0);', '''
    Vector2 target;
    const double lateral = REVIEW_RETURN ? 0 : REVIEW_SIDE * 4;
    if (offsetTarget(car, lateral, driver.segmentCount, driver.trackLength, target)) car->ctrl.steer = steerToward(car, target);
    applySpeedTarget(driver, car, PACE_SPEED, 1.0);''')
    if case.get('motion') and module in ('tutorial5pace', 'tutorial5rear'):
        code = replace_once(code, '\tdriver.drive(car, situation);', '''
    if (situation->currentTime < .5) { car->ctrl = tCarCtrl{}; car->ctrl.brakeCmd = 1; return; }
    driver.requestedGear = car->_gear;
    driver.drive(car, situation);''')
    if case.get('motion') and module == 'tutorial5':
        shutil.copy(HERE/'traffic_motion.h', build)
        code = replace_once(code, 'static TrafficPlanner traffic;', 'static TrafficPlanner traffic;\n#include "traffic_motion.h"')
        code = replace_once(code, '\ttraffic.observe(car, situation, driver.trackLength);',
                            '\tif (reviewArrange(car, situation)) return;\n\ttraffic.observe(car, situation, driver.trackLength);')
        code = replace_once(code, '\ttraffic.drive(driver, car, situation);',
                            '\ttraffic.drive(driver, car, situation);\n\treviewSample(car, situation);')
    if module == 'tutorial6':
        if 'fuel' in case:
            code = replace_once(code, 'STARTING_FUEL = 60.0', 'STARTING_FUEL = '+str(float(case['fuel'])))
        if case.get('demo'):
            pit = build/'pit.cpp'
            pit.write_text(replace_once(pit.read_text(), 'DEMONSTRATION_STOP = false', 'DEMONSTRATION_STOP = true'), encoding='utf-8')
    for name in ('drive', 'shutdown', 'initTrack', 'newRace'):
        code = replace_once(code, '\n'+name+'(', '\nmaintenanceOriginal'+name+'(')
    wrappers = '''
static void initTrack(int index, tTrack* track, void* carSettings, void** settings, tSituation* s)
{
    MaintenanceTrack = track;
    maintenanceOriginalinitTrack(index, track, carSettings, settings, s);
}
static void newRace(int index, tCarElt* car, tSituation* s)
{
#ifdef MAINTENANCE_LAST_PIT
    auto& p = MaintenanceTrack->pits;
    if (p.nMaxPits <= 1) std::abort();
    auto* last = &p.driversPits[p.nMaxPits-1];
    const double center = last->pos.seg->lgfromstart + last->pos.toStart;
    last->lmin = center-p.len/2+car->_dimension_x/2;
    last->lmax = center+p.len/2-car->_dimension_x/2;
    last->freeCarIndex = 1; last->car[0] = car;
    last->pitCarIndex = TR_PIT_STATE_FREE; car->_pit = last;
#endif
    MaintenanceStatsByIndex[index] = MaintenanceStats{};
    maintenanceOriginalnewRace(index, car, s);
    std::printf("MAINTENANCE PIT %s %d %p\\n", MAINTENANCE_ID, index, static_cast<void*>(car->_pit));
}
static void drive(int index, tCarElt* car, tSituation* s)
{
    maintenanceBefore(index, car, s);
    maintenanceOriginaldrive(index, car, s);
    maintenanceObserve(index, car, s);
}
static void shutdown(int index)
{
    maintenanceReport(index);
    maintenanceOriginalshutdown(index);
}
'''
    if module in ('tutorial5', 'tutorial6', 'tutoriala', 'tutorialb'):
        modes = ', int(traffic.mode)' + (', int(pits.mode)' if module != 'tutorial5' else '')
        wrappers = replace_once(wrappers, 'maintenanceObserve(index, car, s);', 'maintenanceObserve(index, car, s'+modes+');')
    code = '#include "observer.h"\n#include <cstdlib>\n' + replace_once(code, 'static int\ninitInterface', wrappers+'\nstatic int\ninitInterface')
    main.write_text(code, encoding='utf-8')
    shutil.copy(HERE/'observer.h', build)
    files = [p for p in build.glob('*.cpp') if not p.stem.startswith('tutorial') or p.stem == module]
    if module == 'tutorial1':
        files = [p for p in files if p.name != 'skeleton.cpp']
    compiled_sources = {str(p.relative_to(build)): digest(p) for p in build.iterdir() if p.suffix in ('.cpp', '.h')}
    identity = hashlib.sha256(json.dumps({'sources':compiled_sources, 'scenario':case, 'module':module},
                                         sort_keys=True).encode('utf-8')).hexdigest()
    (lib/'drivers'/module).mkdir()
    binary = lib/'drivers'/module/(module+'.so')
    flags = []
    if case.get('motion'):
        flags += ['-DREVIEW_SIDE='+str(case['side']), '-DREVIEW_RETURN='+str(int(case['returning'])),
                  '-I'+str(ROOT/'src/modules/simu/simuv2'), '-I'+str(ROOT/'src/modules/simu/simuv2/SOLID-2.0/include')]
    if case.get('last_pit') and module == case['module']: flags.append('-DMAINTENANCE_LAST_PIT')
    if case.get('occupied') and module == case['module']: flags.append('-DMAINTENANCE_OCCUPIED')
    log = run.command(case['name']+'-'+module+'-build', ['g++', '-std=c++14', '-O2', '-Wall', '-fPIC', '-fno-strict-aliasing', '-shared',
        '-I'+str(ROOT/'export/include'), '-I'+str(ROOT), f'-DMAINTENANCE_ID="{identity}"', *flags,
        *map(str, files), '-o', binary])
    assert 'warning:' not in log.lower(), module
    runtime = data/'drivers'/module
    runtime.mkdir()
    for file in source.rglob('*'):
        if file.suffix in ('.xml', '.rgb'):
            target = runtime/file.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(file, target)
    if module == 'tutorial5rear':
        metadata = (source/'tutorial5pace.xml').read_text()
        (runtime/(module+'.xml')).write_text(metadata.replace('Tutorial Pace', 'Maintenance Rear'), encoding='utf-8')
    return {'observer_id': identity, 'binary_sha256': digest(binary), 'compiled_sources': compiled_sources}


def settings(path, module, values):
    root = ET.Element('params', name='Isolated maintenance scenario')
    if 'fuel' in values:
        car = ET.SubElement(root, 'section', name='Car')
        ET.SubElement(car, 'attnum', name='initial fuel', unit='l', val=str(values['fuel']))
    private = ET.SubElement(root, 'section', name='Tutorial '+module[-1].upper())
    strategy = ET.SubElement(private, 'section', name='Strategy')
    if 'demo' in values:
        ET.SubElement(strategy, 'attstr', name='demonstration stop', val='yes' if values['demo'] else 'no')
    if 'stint' in values:
        ET.SubElement(strategy, 'attnum', name='stint laps', val=str(values['stint']))
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def track_variant(case, data, installed):
    variant = case.get('variant')
    if not variant: return
    # Replace only the fixture's symlink, never its target.
    (data/'tracks').unlink()
    link_children(installed/'tracks', data/'tracks', ('road',))
    track = case.get('track', 'g-track-1')
    link_children(installed/'tracks/road', data/'tracks/road', (track,))
    folder = data/'tracks/road'/track
    shutil.copytree(installed/'tracks/road'/track, folder)
    file = folder/(track+'.xml')
    text = file.read_text(encoding='utf-8')
    for entity, name in [('default-surfaces', 'surfaces.xml'), ('default-objects', 'objects.xml')]:
        content = (installed/'data/tracks'/name).read_text(encoding='latin1')
        text = text.replace('&'+entity+';', re.sub(r'<\?xml.*?\?>', '', content))
    xml = ET.ElementTree(ET.fromstring(text))
    main = require(xml, "./section[@name='Main Track']")
    if variant in ('no-pits', 'flat'):
        main.remove(require(main, "section[@name='Pits']"))
        if variant == 'flat':
            for e in xml.findall('.//attnum'):
                if e.get('name', '').startswith(('z ', 'banking ')): e.set('val', '0')
            for e in require(main, "section[@name='Track Segments']"):
                profile = e.find("attstr[@name='profil']")
                if profile is None: profile = ET.SubElement(e, 'attstr', name='profil')
                profile.set('val', 'linear')
    elif variant == 'left':
        for e in xml.iter():
            name = e.get('name', '')
            if name.startswith('Left '): e.set('name', name.replace('Left ', 'Right ', 1))
            elif name.startswith('Right '): e.set('name', name.replace('Right ', 'Left ', 1))
            if e.tag == 'attstr' and name in ('type', 'side'):
                e.set('val', {'left':'right', 'right':'left', 'lft':'rgt', 'rgt':'lft'}.get(e.attrib['val'], e.attrib['val']))
            if e.tag == 'attnum' and name.startswith('banking'): e.set('val', str(-float(e.attrib['val'])))
    elif variant == 'wrap':
        require(main, "section[@name='Right Side']/attnum[@name='width']").set('val', '15')
        segments = require(main, "section[@name='Track Segments']")
        items = list(segments)
        cut = next(i for i, e in enumerate(items) if e.get('name') == 'segment line6c')
        for e in items: segments.remove(e)
        for e in items[cut:]+items[:cut]:
            profile = e.find("attstr[@name='profil']")
            if profile is None: profile = ET.SubElement(e, 'attstr', name='profil')
            profile.set('val', 'linear'); segments.append(e)
        for e in xml.findall('.//attnum'):
            if e.get('name', '').startswith(('z ', 'banking ')): e.set('val', '0')
    else: raise ValueError(variant)
    xml.write(file, encoding='utf-8', xml_declaration=True)


def run_case(run, args, case):
    work = run.work/case['name']; work.mkdir()
    own = case['module']
    modules = [own] + ([case['opponent']] if case.get('opponent') else [])
    if case.get('motion'): modules = ['tutorial5pace', own, 'tutorial5rear']
    tutorials = [m for m in modules if m.startswith('tutorial')]
    lib, data = work/'libroot', work/'data'
    link_children(args.lib_root, lib, ('drivers',))
    link_children(args.lib_root/'drivers', lib/'drivers', tutorials)
    link_children(args.data_root, data, ('drivers',))
    link_children(args.data_root/'drivers', data/'drivers', tutorials)
    evidence = {m: build_module(run, case, m, lib, data) for m in tutorials}
    for m in modules:
        assert (lib/'drivers'/m/(m+'.so')).is_file(), ('Missing installed opponent', m)
        if m not in evidence:
            evidence[m] = {'binary_sha256': digest(lib/'drivers'/m/(m+'.so')),
                           'metadata_sha256': digest(data/'drivers'/m/(m+'.xml'))}
    track = case.get('track', 'g-track-1')
    if own in ('tutoriala', 'tutorialb', 'tutorialc'):
        settings(data/'drivers'/own/(track+'.xml'), own, case)
        for index, values in case.get('individual', {}).items():
            settings(data/'drivers'/own/index/(track+'.xml'), own, values)
    track_variant(case, data, args.data_root)
    entries = race_entries(case)
    write_race(work/'race.xml', entries, track, case.get('laps', 6), case.get('shared', 1))
    profile = work/'profile'; (profile/'config').mkdir(parents=True)
    (profile/'config/raceengine.xml').write_text('<params name="Maintenance"><section name="Modules"><attstr name="track" val="track"/><attstr name="simu" val="simuv2"/><attstr name="graphic" val="ssggraph"/></section></params>', encoding='utf-8')
    env = dict(os.environ, LD_LIBRARY_PATH=str(args.lib_root/'lib')+':'+os.environ.get('LD_LIBRARY_PATH', ''),
               TORCS_MAINT_SIMU=str(args.lib_root/'modules/simu/simuv2.so'))
    output = run.command(case['name']+'-race', [args.binary, '-l', profile, '-L', lib, '-D', data, '-r', work/'race.xml'], cwd=data, env=env, timeout=args.timeout)
    if case.get('motion'):
        identity = evidence[own]['observer_id']
        assert 'MAINTENANCE MOTION SEEDED '+identity in output, 'Motion fixture did not execute'
        marker = next((line for line in output.splitlines() if line.startswith('MAINTENANCE MOTION PASS '+identity)), None)
        assert marker, 'Missing current motion result; race completion is not this experiment'
        (work/'evidence.json').write_text(json.dumps({'scenario':case, 'modules':evidence, 'motion_result':marker,
            'race_sha256':digest(work/'race.xml'), 'track_sha256':digest(data/'tracks/road'/track/(track+'.xml'))}, indent=2))
        print('PASS:', case['name'], marker, flush=True)
        return
    result_files = list(profile.glob('results/**/*.xml'))
    assert len(result_files) == 1, ('Expected one fresh result', result_files)
    ranks = read_ranks(result_files[0])
    rows = [line.split() for line in output.splitlines() if line.startswith('MAINTENANCE '+evidence[own]['observer_id']+' ')]
    assert {int(r[2]) for r in rows} == set(case.get('indices', [1])), 'Missing current instrumented-module telemetry'
    names = ('speed', 'throttle', 'brake', 'min_road_clearance', 'min_fuel', 'initial_fuel', 'ticks', 'contacts', 'penalties', 'speeding', 'invalid_controls', 'max_damage', 'shared_conflicts')
    stats = {int(row[2]): dict(zip(names, map(float, row[3:]))) for row in rows}
    assignments = [line.split() for line in output.splitlines() if line.startswith('MAINTENANCE PIT '+evidence[own]['observer_id']+' ')]
    pit_ids = {int(row[3]): row[4] for row in assignments}
    record = {'scenario': case, 'modules': evidence, 'ranks': ranks, 'telemetry': stats, 'pit_assignments':pit_ids,
              'race_sha256': digest(work/'race.xml'), 'result_sha256': digest(result_files[0]),
              'track_sha256': digest(data/'tracks/road'/track/(track+'.xml')),
              'car_parameters': {rank['car']: digest(data/'cars'/rank['car']/(rank['car']+'.xml')) for rank in ranks}}
    (work/'evidence.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    own_ranks = [r for r in ranks if r['module'] == own]
    assert len(own_ranks) == len(case.get('indices', [1]))
    for rank in own_ranks:
        s = stats[int(rank['idx'])]
        assert s['ticks'] > 0 and s['min_fuel'] > 0, s
        assert all(s[k] == 0 for k in ('contacts', 'penalties', 'speeding', 'invalid_controls', 'max_damage', 'shared_conflicts')), s
        expected_fuel = case.get('individual', {}).get(rank['idx'], {}).get('fuel', case.get('fuel'))
        if expected_fuel is not None: assert abs(s['initial_fuel'] - expected_fuel) < 0.1, (rank['idx'], s)
        assert int(rank['dammages']) == 0 and float(rank['penaltytime']) == 0, rank
        assert int(rank['laps']) >= (case.get('laps', 6) if len(entries) == 1 else max(1, case.get('laps', 6)-3)), rank
        stops = int(rank['pits stops'])
        assert stops >= case.get('min_stops', 0), rank
        if not case.get('min_stops'): assert stops == 0, rank
        if case.get('performance', True):
            assert s['throttle'] >= 0.999 and s['speed'] > 32.0, s
        if not case.get('min_stops') and len(entries) == 1: assert s['min_road_clearance'] >= 0, s
    if case.get('occupied'): assert 'occupied-box fixture activated' in output
    if case.get('shared', 1) > 1:
        assert set(pit_ids) == set(case['indices']) and len(set(pit_ids.values())) == 1, pit_ids
        assert all(value not in ('(nil)', '0x0') for value in pit_ids.values()), pit_ids
    print('PASS:', case['name'], json.dumps(stats), flush=True)


def main():
    scenarios = json.loads((HERE/'scenarios.json').read_text())
    parser = argparse.ArgumentParser(description=__doc__,
        epilog='Scenario names: '+', '.join(case['name'] for case in scenarios))
    for name in ('binary', 'lib-root', 'data-root', 'work-root'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--scenario', action='append', help='Repeatable scenario name; all includes known failing stress cases')
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    if sys.platform != 'linux': parser.error('Linux only; use check_windows.py for native Windows checks')
    for name in ('binary', 'lib_root', 'data_root', 'work_root'):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    selected = args.scenario or ['ch6-g1', 'ch6-e2', 'pit-fuel']
    assert 'all' in selected or set(selected) <= {s['name'] for s in scenarios}, selected
    with Run(args.work_root, 'races') as run:
        run.report.update(binary_sha256=digest(args.binary), physics_sha256=digest(args.lib_root/'modules/simu/simuv2.so'), scenarios=[],
                          installation={'binary':str(args.binary), 'lib_root':str(args.lib_root), 'data_root':str(args.data_root)},
                          shared_track_parameters={p.name:digest(p) for p in (args.data_root/'data/tracks').glob('*.xml')})
        failures = []
        for case in scenarios:
            if 'all' not in selected and case['name'] not in selected: continue
            try:
                run_case(run, args, case)
                run.report['scenarios'].append({'name': case['name'], 'status': 'passed'})
            except Exception as error:
                failures.append(case['name'])
                run.report['scenarios'].append({'name': case['name'], 'status': 'failed', 'error': str(error)})
                print('FAIL:', case['name'], str(error), flush=True)
            run.save()
        if failures: raise RuntimeError('Failed scenarios: '+', '.join(failures))


if __name__ == '__main__':
    main()
