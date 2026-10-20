#!/usr/bin/env python3
"""Snapshot Appendix A's complete driver for the artwork checkpoint.

Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
Maintainer tool; readers build the supplied directory directly.
"""
from pathlib import Path
import argparse

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'examples/appendix_a'
DEST = HERE / 'examples/appendix_b'


def contents():
    names = ['Makefile', 'tutoriala.cpp', 'tutoriala.mk', 'tutoriala.xml',
             'tutoriala.def', 'tutoriala.vcxproj', 'default.xml', 'g-track-1.xml']
    names += [n + ext for n in ('settings', 'pit', 'spline', 'traffic', 'speed',
                               'braking', 'steering', 'geometry', 'recovery') for ext in ('.h', '.cpp')]
    result = {}
    for name in names:
        text = (SOURCE / name).read_text(encoding='utf-8').replace('tutoriala', 'tutorialb').replace('TUTORIALA', 'TUTORIALB')
        text = text.replace('Tutorial A', 'Tutorial B')
        text = text.replace('The complete tutorial racing driver', 'The tutorial artwork checkpoint')
        text = text.replace('Car setup and private driver parameters', 'Car textures and pit logos')
        if name == 'tutoriala.xml':
            text = text.replace('name="race number" val="6"', 'name="race number" val="8"')
        elif name == 'tutoriala.mk':
            text = text.replace('SHIP = tutorialb.xml default.xml g-track-1.xml',
                                'SHIP = tutorialb.xml default.xml g-track-1.xml car1-stock1.rgb logo.rgb ARTWORK.txt')
        elif name == 'tutoriala.vcxproj':
            text = text.replace('2F4CBB89-89BC-4FC6-93A1-C9BF19C5D053', 'C5A28323-BC63-46DF-963C-7D448DE586D9')
            text = text.replace('$(MSBuildThisFileDirectory)g-track-1.xml"',
                '$(MSBuildThisFileDirectory)g-track-1.xml;$(MSBuildThisFileDirectory)car1-stock1.rgb;'
                '$(MSBuildThisFileDirectory)logo.rgb;$(MSBuildThisFileDirectory)ARTWORK.txt"')
        result[name.replace('tutoriala', 'tutorialb')] = text
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
    print('Appendix B source snapshot ' + ('checked.' if args.check else 'generated.'))


if __name__ == '__main__':
    main()
