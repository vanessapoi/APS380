#!/usr/bin/env python3
"""Check graphics-plugin loading in the actual executable; no window or race."""
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PREFIX = ROOT/'.local/torcs-macos/install'


def main():
    if platform.system() != 'Darwin':
        raise SystemExit('This loader check is for macOS')
    env = dict(os.environ, DYLD_LIBRARY_PATH=str(PREFIX/'lib/torcs/lib'))
    subprocess.run([str(PREFIX/'lib/torcs/torcs-bin'), '-L', str(PREFIX/'lib/torcs'),
                    '--check-graphics'], env=env, check=True)


if __name__ == '__main__':
    main()
