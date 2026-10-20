#!/usr/bin/env python3
"""Package the complete final multi-robot checkpoint with editable artwork.
Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
Artwork retains its Free Art License; see the packaged ARTWORK.txt.
"""
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'examples/appendix_c'
FILES = ['tutorialc.cpp', 'tutorialc.mk', 'tutorialc.xml', 'tutorialc.def',
         'tutorialc.vcxproj', 'Makefile', 'README.txt', 'ARTWORK.txt',
         'default.xml', 'g-track-1.xml', 'logo.rgb', 'artwork/logo.svg']
FILES += [name + suffix for name in ('driver', 'settings', 'pit', 'spline', 'traffic',
                                    'speed', 'braking', 'steering', 'geometry', 'recovery')
          for suffix in ('.cpp', '.h')]
for index in (1, 2):
    FILES += [f'{index}/{name}' for name in ('Makefile', 'default.xml', 'g-track-1.xml', 'car1-stock1.rgb')]
    FILES += [f'artwork/{index}/{name}' for name in ('livery.xcf', 'decals.svg')]


def main():
    contents = {name: (SOURCE / name).read_bytes() for name in FILES}
    contents['COPYING'] = (HERE.parents[2] / 'COPYING').read_bytes()
    with zipfile.ZipFile(HERE / 'tutorialc.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            entry = zipfile.ZipInfo('tutorialc/' + name, date_time=(2026, 9, 28, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    print(f'Packaged {len(contents)} files in tutorialc.zip.')


if __name__ == '__main__':
    main()
