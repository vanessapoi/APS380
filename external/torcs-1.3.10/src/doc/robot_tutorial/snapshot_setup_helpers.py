#!/usr/bin/env python3
"""Reproduce Appendix A's Chapter 6 baseline plus explicit configuration hooks.

Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
Maintainer tool; readers build the supplied complete directory directly.
"""
from pathlib import Path
import argparse

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'examples/chapter_6'
DEST = HERE / 'examples/appendix_a'


def replace(text, old, new):
    assert old in text, old
    return text.replace(old, new)


def contents():
    names = ['Makefile', 'tutorial6.cpp', 'tutorial6.mk', 'tutorial6.xml',
             'tutorial6.def', 'tutorial6.vcxproj']
    names += [n + ext for n in ('pit', 'spline', 'traffic', 'speed', 'braking',
                               'steering', 'geometry', 'recovery') for ext in ('.h', '.cpp')]
    result = {}
    for name in names:
        text = (SOURCE / name).read_text(encoding='utf-8').replace('tutorial6', 'tutoriala').replace('TUTORIAL6', 'TUTORIALA')
        text = text.replace('Tutorial 6', 'Tutorial A')
        if name == 'tutorial6.cpp':
            text = replace(text, '#include "pit.h"', '#include "pit.h"\n#include "settings.h"')
            start = text.index('// Start with a full reference-car tank')
            end = text.index('static tTrack*', start)
            text = text[:start] + 'static DriverSettings configuration;\n' + text[end:]
            start = text.index('\t*settings = GfParmReadFile')
            end = text.index('\n}\n', start)
            text = text[:start] + '\t*settings = loadSettings(track, carSettings, configuration);' + text[end:]
            text = replace(text, '\tpits.configure(currentTrack, car);',
                '\tpits.configure(currentTrack, car);\n\tconfiguration.apply(driver, pits);\n'
                '\tGfOut("Tutorial A effective: fuel=%.3f l, rear wing=%.3f deg\\n",\n'
                '\t\tGfParmGetNum(car->_carHandle, SECT_CAR, PRM_FUEL, "l", 0.0f),\n'
                '\t\tGfParmGetNum(car->_carHandle, SECT_REARWING, PRM_WINGANGLE, "deg", 0.0f));')
            text = text.replace('The complete tutorial racing driver', 'Car setup and private driver parameters')
        elif name == 'speed.h':
            text = replace(text, '\tdouble targetSpeed = 0.0;', '\tdouble targetSpeed = 0.0;\n\tdouble lookaheadBase = 8.0;\n\tdouble lookaheadTime = 0.33;')
        elif name == 'speed.cpp':
            text = replace(text, 'chooseSteering(car, segmentCount, trackLength)', 'chooseSteering(car, segmentCount, trackLength, lookaheadBase, lookaheadTime)')
        elif name in ('steering.h', 'steering.cpp'):
            text = replace(text, 'chooseSteering(tCarElt* car, int segmentCount, double trackLength)',
                           'chooseSteering(tCarElt* car, int segmentCount, double trackLength, double base, double time)')
            if name.endswith('.cpp'):
                text = replace(text, 'static constexpr double LOOKAHEAD_BASE = 8.0;     // metres\n', '')
                text = replace(text, 'static constexpr double LOOKAHEAD_TIME = 0.33;    // seconds\n', '')
                text = replace(text, 'LOOKAHEAD_BASE + LOOKAHEAD_TIME', 'base + time')
        elif name == 'traffic.h':
            text = replace(text, 'double length, Vector2& target);',
                           'double length, Vector2& target, double base, double time);')
        elif name == 'traffic.cpp':
            text = replace(text, 'double length, Vector2& target)', 'double length, Vector2& target, double base, double time)')
            text = replace(text, '8.0 + 0.33 *', 'base + time *')
            text = replace(text, 'driver.trackLength, target)', 'driver.trackLength, target, driver.lookaheadBase, driver.lookaheadTime)')
        elif name == 'pit.h':
            text = replace(text, '\tbool available = false;', '\tbool demonstrationStop = false;\n\tdouble stintLaps = 0.0;\n\tdouble fallbackFuelPerLap = 1.5;\n\tbool available = false;')
        elif name == 'pit.cpp':
            text = replace(text, '// Enable only for the explicit pit-route exercise; racing uses fuel/damage strategy.',
                           '// Each instance receives its demonstration-stop setting from configuration.')
            text = replace(text, 'static constexpr bool DEMONSTRATION_STOP = false;\n', '')
            text = replace(text, 'static constexpr double STINT_LAPS = 0.0;        // zero: fuel to finish, bounded by tank capacity\n', '')
            text = text.replace('DEMONSTRATION_STOP', 'demonstrationStop').replace('STINT_LAPS', 'stintLaps')
            text = replace(text, '1.15 * fuelPerLap : 1.5', '1.15 * fuelPerLap : fallbackFuelPerLap')
        elif name == 'tutorial6.mk':
            text = replace(text, 'SOURCES = tutoriala.cpp', 'SOURCES = settings.cpp tutoriala.cpp')
            text = replace(text, 'SHIP = tutoriala.xml', 'SHIP = tutoriala.xml default.xml g-track-1.xml')
            text += '\nsettings.o tutoriala.o: settings.h\nsettings.o: pit.h speed.h\n'
        elif name == 'tutorial6.vcxproj':
            text = text.replace('F694735A-9D0A-46C7-8434-BCF86B16E386', '2F4CBB89-89BC-4FC6-93A1-C9BF19C5D053')
            text = replace(text, '<ClCompile Include="tutoriala.cpp"/>', '<ClCompile Include="settings.cpp"/><ClCompile Include="tutoriala.cpp"/>')
            text = replace(text, '<ClInclude Include="pit.h"/>', '<ClInclude Include="settings.h"/><ClInclude Include="pit.h"/>')
            text = replace(text, '$(MSBuildThisFileDirectory)tutoriala.xml"', '$(MSBuildThisFileDirectory)tutoriala.xml;$(MSBuildThisFileDirectory)default.xml;$(MSBuildThisFileDirectory)g-track-1.xml"')
        result[name.replace('tutorial6', 'tutoriala')] = text
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    DEST.mkdir(exist_ok=True)
    for name, text in contents().items():
        path = DEST / name
        if args.check:
            assert path.read_text(encoding='utf-8') == text, f'{path}: snapshot differs'
        else:
            path.write_bytes(text.encode('utf-8'))
    print('Appendix A baseline/configuration hooks ' + ('checked.' if args.check else 'generated.'))


if __name__ == '__main__':
    main()
