#!/usr/bin/env python3
"""Compile/run tutorial control regressions against a configured Linux TORCS tree.

Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
Uses a temporary build directory; never installs instrumented drivers.
Usage: python3 test/robot_tutorial/check_racing_controls.py --lib-dir <TORCS library directory>
"""
import argparse
import os
import sys
from pathlib import Path
import tempfile
from maintenance import Run

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'src/doc/robot_tutorial/examples'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lib-dir', type=Path, default=ROOT / 'export/lib')
    parser.add_argument('--work-root', type=Path, default=Path(tempfile.gettempdir()))
    parser.add_argument('--data-root', type=Path, help='Also test the settings loader against the installed reference car')
    parser.add_argument('--valgrind', action='store_true', help='Run settings/parser checks under Valgrind (requires --data-root)')
    args = parser.parse_args()
    if sys.platform != 'linux': parser.error('Control instrumentation is Linux-only; Windows smoke checks use check_windows.py')
    if args.valgrind and not args.data_root:
        parser.error('--valgrind requires --data-root')
    lib = args.lib_dir.resolve()
    env = dict(os.environ, LD_LIBRARY_PATH=str(lib) + ':' + os.environ.get('LD_LIBRARY_PATH', ''))
    with Run(args.work_root, 'controls') as run:
        run.report['settings_execution'] = 'requested' if args.data_root else 'not requested (supply --data-root)'
        temporary = run.work
        for name in ('chapter_3', 'chapter_4', 'chapter_5', 'chapter_6', 'appendix_a', 'appendix_b', 'appendix_c'):
            folder = EXAMPLES / name
            speed = EXAMPLES / 'chapter_4' if name == 'chapter_5' else folder
            suffix = '4' if name in ('chapter_4', 'chapter_5') else ''
            files = [speed / f'speed{suffix}.cpp', speed / f'braking{suffix}.cpp']
            flags = [f'-DSPEED_HEADER="speed{suffix}.h"']
            if name != 'chapter_3':
                files += [speed / f'steering{suffix}.cpp', speed / f'geometry{suffix}.cpp']
            if name not in ('chapter_3', 'chapter_4'):
                traffic = 'traffic5' if name == 'chapter_5' else 'traffic'
                files.append(folder / (traffic + '.cpp'))
                flags.append(f'-DTRAFFIC_HEADER="{traffic}.h"')
            if (folder / 'pit.cpp').exists():
                files += [folder / 'pit.cpp', folder / 'spline.cpp']
                flags.append('-DPIT_HEADER="pit.h"')
            suites = ['racing_controls'] + (['pit_math_checks'] if (folder/'pit.cpp').exists() else [])
            if name == 'appendix_a' and args.data_root:
                suites.append('settings_checks')
                (run.work/'drivers/tutoriala').mkdir(parents=True)
            for suite in suites:
                binary = Path(temporary) / (name+'-'+suite)
                command = ['g++', '-std=c++14', '-O2', '-Wall', '-fno-strict-aliasing', *flags,
                    '-I'+str(ROOT/'export/include'), '-I'+str(folder), '-I'+str(speed),
                    str(Path(__file__).with_name(suite+'.cpp')), *map(str, files),
                    *([str(folder/'settings.cpp')] if suite == 'settings_checks' else []),
                    '-L'+str(lib), '-Wl,-rpath,'+str(lib), '-lrobottools', '-ltgf', '-ltxml', '-o', str(binary)]
                output = run.command(name+'-'+suite+'-build', command, env=env)
                assert 'warning:' not in output.lower(), output
                print(name, suite, flush=True)
                execute = [str(binary)]
                if suite == 'settings_checks':
                    execute.append(str(args.data_root.resolve(strict=True)))
                    if args.valgrind:
                        execute = ['valgrind', '--error-exitcode=1', '--leak-check=full',
                                   '--show-leak-kinds=definite,indirect', '--errors-for-leak-kinds=definite,indirect'] + execute
                output = run.command(name+'-'+suite, execute, cwd=run.work, env=env)
                print('\n'.join(line for line in output.splitlines() if line.startswith('PASS:') or 'ERROR SUMMARY:' in line))


if __name__ == '__main__':
    main()
