#!/usr/bin/env python3
"""Maintainer tool: reproduce the final checkpoint's included helper sources.

Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
Readers build the supplied checkpoint directly; this script is not a build step.
Run with --check to verify snapshots without changing files. Review and test
changes in the earlier checkpoints before deliberately regenerating snapshots.
"""
from pathlib import Path
import argparse

HERE = Path(__file__).resolve().parent
SOURCES = {name: 4 for name in ('geometry', 'steering', 'speed', 'braking', 'recovery')}
SOURCES['traffic'] = 5


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    destination = HERE / 'examples/chapter_6'
    if not args.check:
        destination.mkdir(parents=True, exist_ok=True)
    for name, chapter in SOURCES.items():
        for suffix in ('.h', '.cpp'):
            source = HERE / f'examples/chapter_{chapter}/{name}{chapter}{suffix}'
            content = source.read_text(encoding='utf-8')
            for helper, origin in SOURCES.items():
                for extension in ('.h', '.cpp'):
                    content = content.replace(f'{helper}{origin}{extension}', helper + extension)
            content = content.replace('_TUTORIAL4_', '_TUTORIAL6_').replace('_TUTORIAL5_', '_TUTORIAL6_')
            target = destination / (name + suffix)
            if args.check:
                if not target.is_file() or target.read_text(encoding='utf-8') != content:
                    raise SystemExit(f'Snapshot differs: {target}')
            else:
                target.write_bytes(content.encode('utf-8'))
    print('Verified final helper snapshots.' if args.check else 'Generated twelve self-contained final helper files.')


if __name__ == '__main__':
    main()
