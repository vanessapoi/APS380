#!/usr/bin/env python3
"""Reproduce Appendix C's inherited helpers and integrated driver methods.

Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
Maintainer tool; the shipped checkpoint builds directly without this script.
Module registration and the driver class declaration are maintained separately.
"""
from pathlib import Path
import argparse
import re

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'examples/appendix_b'
DEST = HERE / 'examples/appendix_c'


def change(text, old, new):
    assert old in text, old
    return text.replace(old, new)


def contents():
    names = ['Makefile', 'tutorialb.mk', 'tutorialb.def', 'tutorialb.vcxproj', 'default.xml', 'g-track-1.xml']
    names += [n + ext for n in ('settings', 'pit', 'spline', 'traffic', 'speed',
                               'braking', 'steering', 'geometry', 'recovery') for ext in ('.h', '.cpp')]
    result = {}
    for name in names:
        text = (SOURCE / name).read_text(encoding='utf-8').replace('tutorialb', 'tutorialc').replace('TUTORIALB', 'TUTORIALC')
        text = text.replace('Tutorial B', 'Tutorial C')
        if name in ('settings.h', 'settings.cpp'):
            text = change(text, 'loadSettings(tTrack* track,', 'loadSettings(int index, tTrack* track,')
            if name.endswith('.cpp'):
                text = change(text, 'static const char* PRIVATE_SECTION', 'static const char* const PRIVATE_SECTION')
                needle = '\t// Preserve Chapter 6\'s full-tank fallback'
                addition = ('\tconst std::string individual = directory + std::to_string(index) + "/";\n'
                            '\treadLayer(individual + "default.xml", carSettings, overrides, settings);\n'
                            '\tif (track->internalname && track->internalname[0]) {\n'
                            '\t\treadLayer(individual + track->internalname + ".xml", carSettings, overrides, settings);\n'
                            '\t}\n')
                text = change(text, needle, addition + needle)
                text = change(text, 'GfOut("Tutorial C settings:', 'GfOut("Tutorial C[%d] settings:')
                text = change(text, '\t\tsettings.lookaheadBase, settings.lookaheadTime,', '\t\tindex, settings.lookaheadBase, settings.lookaheadTime,')
        elif name == 'tutorialb.mk':
            text = change(text, 'SOURCES = settings.cpp', 'SOURCES = driver.cpp settings.cpp')
            text = change(text, ' car1-stock1.rgb logo.rgb', ' logo.rgb')
            text = change(text, 'SHIPSUBDIRS =', 'SHIPSUBDIRS = 1 2')
            text += '\ndriver.o tutorialc.o: driver.h\ndriver.o: settings.h pit.h spline.h traffic.h speed.h braking.h steering.h geometry.h recovery.h\n'
        elif name == 'tutorialb.vcxproj':
            text = text.replace('C5A28323-BC63-46DF-963C-7D448DE586D9', 'E1A6BE78-887F-437E-A9EA-9D782CEAF751')
            text = change(text, '<ClCompile Include="settings.cpp"/>', '<ClCompile Include="driver.cpp"/><ClCompile Include="settings.cpp"/>')
            text = change(text, '<ClInclude Include="settings.h"/>', '<ClInclude Include="driver.h"/><ClInclude Include="settings.h"/>')
            text = change(text, ';$(MSBuildThisFileDirectory)car1-stock1.rgb', '')
            needle = '    <MakeDir Directories="$(TorcsRuntimeDir)drivers\\tutorialc" />'
            text = change(text, needle, needle + '\n    <MakeDir Directories="$(TorcsRuntimeDir)drivers\\tutorialc\\1;$(TorcsRuntimeDir)drivers\\tutorialc\\2" />')
            copies = ''.join('    <Copy SourceFiles="' + ';'.join('$(MSBuildThisFileDirectory)' + str(i) + '\\' + n for n in ('default.xml','g-track-1.xml','car1-stock1.rgb')) + '" DestinationFolder="$(TorcsRuntimeDir)drivers\\tutorialc\\' + str(i) + '" />\n' for i in (1,2))
            text = change(text, '  </Target>', copies + '  </Target>')
        result[name.replace('tutorialb', 'tutorialc')] = text

    original = (SOURCE / 'tutorialb.cpp').read_text(encoding='utf-8')
    header = original[:original.index('#include')].replace('tutorialb.cpp', 'driver.cpp')
    def body(name):
        start = original.index('{', original.index('\n' + name + '('))
        end = original.index('\n}', start) + 2
        return re.sub(r'\bdriver\b', 'speed', original[start:end]).replace('Tutorial B', 'Tutorial C')
    new_race = body('newRace')
    new_race = new_race.replace('{\n', '{\n\tif (!currentTrack) {\n\t\treturn;\n\t}\n\tactiveCar = car;\n', 1)
    new_race = change(new_race, 'Tutorial C effective:', 'Tutorial C[%d] effective:')
    new_race = change(new_race, '\t\tGfParmGetNum(car->_carHandle, SECT_CAR', '\t\tindex, GfParmGetNum(car->_carHandle, SECT_CAR')
    drive = body('drive')
    drive = drive.replace('{\n', '{\n\tif (!currentTrack || car != activeCar) {\n\t\tcar->ctrl = tCarCtrl{};\n\t\tcar->ctrl.brakeCmd = 1.0f;\n\t\treturn;\n\t}\n', 1)
    result['driver.cpp'] = header + '''#include <cmath>
#include <robottools.h>
#include "driver.h"

TutorialDriver::TutorialDriver(int robotIndex) : index(robotIndex)
{
}

void
TutorialDriver::initTrack(tTrack* track, void* carSettings, void** settings)
{
	// Reset only this instance; another selected robot may already be initialized.
	activeCar = nullptr;
	speed = SpeedDriver{};
	recovery = Recovery{};
	traffic = TrafficPlanner{};
	pits = PitDriver{};
	currentTrack = track;
	*settings = loadSettings(index, track, carSettings, configuration);
}

void
TutorialDriver::newRace(tCarElt* car, tSituation* situation)
''' + new_race + '\n\nvoid\nTutorialDriver::drive(tCarElt* car, tSituation* situation)\n' + drive + '''

int
TutorialDriver::pitCommand(tCarElt* car)
{
	return car == activeCar ? pits.service(car) : ROB_PIT_IM;
}
'''
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
    print('Appendix C helper/class-method snapshot ' + ('checked.' if args.check else 'generated.'))


if __name__ == '__main__':
    main()
