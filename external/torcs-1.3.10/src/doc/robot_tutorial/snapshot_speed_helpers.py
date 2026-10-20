#!/usr/bin/env python3
"""Reproduce Chapter 4's longitudinal controller from Chapter 3.

Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
The steering/path changes remain explicit below; readers build supplied sources.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    source = (HERE / 'examples/chapter_3/speed.cpp').read_text(encoding='utf-8')
    for name in ('speed', 'braking'):
        for suffix in ('.h', '.cpp'):
            source = source.replace(name + suffix, name + '4' + suffix)
    source = source.replace('#include "speed4.h"', '#include "speed4.h"\n#include "steering4.h"')
    start = source.index('static double\ndistanceToSegmentEnd')
    end = source.index('void\nSpeedDriver::configure', start)
    source = source[:start] + source[end:]
    source = source.replace('static constexpr bool AERO_CORNERS',
        'static constexpr bool USE_SHORT_TURN_HEURISTIC = false;\nstatic constexpr bool AERO_CORNERS')
    source = source.replace('\t// Apply the margin to the uncapped model speed, then the driving cap.',
        '\tconst double progress = segment == car->_trkPos.seg ? segmentProgress(car->_trkPos) : 0.0;\n'
        '\tconst double radius = USE_SHORT_TURN_HEURISTIC ? experimentalRadius(segment, progress, segmentCount) : segment->radius;')
    source = source.replace('cornerSpeed(segment->radius,', 'cornerSpeed(radius,')
    source = source.replace('distanceToSegmentEnd(car->_trkPos)',
                            'segment->length - segmentProgress(car->_trkPos)')
    start = source.index('\t// Keep the familiar steering rule;')
    end = source.index('\tcar->ctrl.gear = chooseGear', start)
    source = source[:start] + ('\tcar->ctrl.steer = static_cast<tdble>(chooseSteering(car, segmentCount, trackLength));\n'
        '\tapplySpeedTarget(car, edgeSpeedLimit(car, chooseTargetSpeed(car)));\n') + source[end:]
    target = HERE / 'examples/chapter_4/speed4.cpp'
    if args.check:
        if target.read_text(encoding='utf-8') != source:
            raise SystemExit(f'Snapshot differs: {target}')
    else:
        target.write_bytes(source.encode('utf-8'))


if __name__ == '__main__':
    main()
