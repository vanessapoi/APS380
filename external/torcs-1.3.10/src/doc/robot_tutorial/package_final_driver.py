#!/usr/bin/env python3
"""Package the supplied final checkpoint for the offline documentation.

Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
Maintainer operation, not a reader build prerequisite. Deterministic timestamps
and an explicit manifest keep build artifacts and unrelated files out of the zip.
"""
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'examples/chapter_6'
FILES = ['tutorial6.cpp', 'tutorial6.mk', 'tutorial6.xml', 'tutorial6.def',
         'tutorial6.vcxproj', 'Makefile', 'README.txt']
FILES += [name+suffix for name in ('pit','spline','traffic','speed','braking','steering','geometry','recovery')
          for suffix in ('.cpp','.h')]


def main():
    contents = {name: (SOURCE/name).read_bytes() for name in FILES}
    contents['COPYING'] = (HERE.parents[2]/'COPYING').read_bytes()
    with zipfile.ZipFile(HERE/'tutorial6.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            entry = zipfile.ZipInfo('tutorial6/'+name, date_time=(2026,9,28,0,0,0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry,data)
    print(f'Packaged {len(contents)} source, build, README and license files in tutorial6.zip.')


if __name__ == '__main__':
    main()
