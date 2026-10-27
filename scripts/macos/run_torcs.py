#!/usr/bin/env python3
"""Launch the local Mac build with isolated preferences and no live/hardware link."""
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.local/torcs-macos'


def main():
    if platform.system() != 'Darwin':
        raise SystemExit('This launcher is for macOS')
    prefix = WORK / 'install'
    binary = prefix / 'lib/torcs/torcs-bin'
    data = prefix / 'share/games/torcs'
    user = WORK / 'user'
    if not binary.exists() or not (data / 'config/screen.xml').exists():
        raise SystemExit('Build/install first: python3 scripts/macos/build_torcs.py')
    user.mkdir(parents=True, exist_ok=True)
    subprocess.run(['/bin/bash', str(prefix / 'lib/torcs/setup_linux.sh'), str(user)], cwd=data, check=True)
    env = dict(os.environ)
    env['DYLD_LIBRARY_PATH'] = str(prefix / 'lib/torcs/lib')
    # Newly installed XQuartz may require a new login before DISPLAY propagates.
    if not env.get('DISPLAY'):
        display = subprocess.check_output(['launchctl', 'getenv', 'DISPLAY'], text=True).strip()
        env['DISPLAY'] = display or ':0'
    env.pop('APS380_LIVE_PORT', None)
    env.pop('APS380_LIVE_REALTIME', None)
    os.chdir(data)
    os.execve(str(binary), [str(binary), '-l', str(user), '-L', str(prefix / 'lib/torcs'), '-D', str(data), *sys.argv[1:]], env)


if __name__ == '__main__':
    main()
