#!/usr/bin/env python3
"""Package Appendix A's complete checkpoint. Copyright (C) 2026 Bernhard Wymann.
GPL-2.0-or-later. Maintainer operation, not a reader prerequisite.
"""
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'examples/appendix_a'
FILES = ['tutoriala.cpp', 'tutoriala.mk', 'tutoriala.xml', 'tutoriala.def',
         'tutoriala.vcxproj', 'Makefile', 'README.txt', 'default.xml', 'g-track-1.xml']
FILES += [name + suffix for name in ('settings', 'pit', 'spline', 'traffic', 'speed',
                                    'braking', 'steering', 'geometry', 'recovery')
          for suffix in ('.cpp', '.h')]


def main():
    contents = {name: (SOURCE / name).read_bytes() for name in FILES}
    contents['COPYING'] = (HERE.parents[2] / 'COPYING').read_bytes()
    with zipfile.ZipFile(HERE / 'tutoriala.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            entry = zipfile.ZipInfo('tutoriala/' + name, date_time=(2026, 9, 28, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    print(f'Packaged {len(contents)} files in tutoriala.zip.')


if __name__ == '__main__':
    main()
