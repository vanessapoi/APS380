"""Portable race fixtures; platform launch/build logic belongs in each runner.
Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
"""
import re
import xml.etree.ElementTree as ET
from maintenance import ROOT, DOCS


def require(tree, path):
    value = tree.find(path)
    assert value is not None, ('Missing fixture XML element', path)
    return value


def replace_once(text, old, new):
    assert text.count(old) == 1, ('fixture hook missing/ambiguous', old)
    return text.replace(old, new)


def example(module):
    if module in ('tutoriala', 'tutorialb', 'tutorialc'):
        return DOCS/'examples'/('appendix_'+module[-1])
    if module in ('tutorial5pace', 'tutorial5rear'):
        return DOCS/'examples/chapter_5'
    assert re.fullmatch(r'tutorial[1-6]', module), module
    return DOCS/'examples'/('chapter_'+module[-1])


def write_race(path, entries, track='g-track-1', laps=6, shared=1):
    race = ET.parse(ROOT/'src/raceman/quickrace.xml')
    require(race, ".//section[@name='Tracks']/section/attstr[@name='name']").set('val', track)
    session = require(race, "./section[@name='Quick Race']")
    require(session, "attnum[@name='laps']").set('val', str(laps))
    ET.SubElement(session, 'attnum', name='cars per pit', val=str(shared))
    drivers = require(race, "./section[@name='Drivers']")
    for child in list(drivers): drivers.remove(child)
    for n, (module, index) in enumerate(entries, 1):
        node = ET.SubElement(drivers, 'section', name=str(n))
        ET.SubElement(node, 'attstr', name='module', val=module)
        ET.SubElement(node, 'attnum', name='idx', val=str(index))
    race.write(path, encoding='utf-8', xml_declaration=True)


def race_entries(case):
    own = case['module']
    entries = [(own, i) for i in case.get('indices', [1])]
    if case.get('motion'): entries = [(m, 1) for m in ('tutorial5pace', own, 'tutorial5rear')]
    if case.get('opponent'):
        opponent = (case['opponent'], case.get('opponent_index', 1))
        entries.insert(0, opponent) if case.get('opponent_first') else entries.append(opponent)
    return entries


def read_ranks(path):
    return [{e.attrib['name']: e.attrib['val'] for e in node}
            for node in ET.parse(path).findall(".//section[@name='Rank']/section")]
