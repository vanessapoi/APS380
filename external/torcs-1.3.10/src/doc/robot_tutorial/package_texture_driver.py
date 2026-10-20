#!/usr/bin/env python3
"""Package Appendix B's complete source and editable artwork.
Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
Artwork retains its separate Free Art License; see the packaged ARTWORK.txt.
"""
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'examples/appendix_b'
FILES = ['tutorialb.cpp', 'tutorialb.mk', 'tutorialb.xml', 'tutorialb.def',
         'tutorialb.vcxproj', 'Makefile', 'README.txt', 'default.xml', 'g-track-1.xml',
         'car1-stock1.rgb', 'logo.rgb', 'ARTWORK.txt',
         'artwork/livery.xcf', 'artwork/decals.svg', 'artwork/logo.svg']
FILES += [name + suffix for name in ('settings', 'pit', 'spline', 'traffic', 'speed',
                                    'braking', 'steering', 'geometry', 'recovery')
          for suffix in ('.cpp', '.h')]


def main():
    contents = {name: (SOURCE / name).read_bytes() for name in FILES}
    contents['COPYING'] = (HERE.parents[2] / 'COPYING').read_bytes()
    with zipfile.ZipFile(HERE / 'tutorialb.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            entry = zipfile.ZipInfo('tutorialb/' + name, date_time=(2026, 9, 28, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    print(f'Packaged {len(contents)} source, build, configuration, artwork and license files in tutorialb.zip.')


if __name__ == '__main__':
    main()
