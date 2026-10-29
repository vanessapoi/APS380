#!/usr/bin/env python3
"""Experimental Apple Silicon TORCS build, isolated under .local/torcs-macos.

Install Homebrew prerequisites from docs/torcs-macos.md first. No instruments,
serial connections, system installation, or changes to shell settings.
"""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.local/torcs-macos'
SOURCE = ROOT / 'external/torcs-1.3.10'
PLIB_SHA = '485b22bf6fdc0da067e34ead5e26f002b76326f6371e2ae006415dea6a380a32'


def run(command, cwd, env, logfile):
    print('Running:', ' '.join(map(str, command)), flush=True)
    with (WORK / logfile).open('w') as log:
        result = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                                stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((WORK / logfile).read_text(errors='replace')[-5000:])
        raise SystemExit('Failed; see ' + str(WORK / logfile))


def sdk_environment(override=None):
    env = dict(os.environ)
    major = platform.mac_ver()[0].split('.')[0]
    matching = Path('/Library/Developer/CommandLineTools/SDKs') / ('MacOSX' + major + '.sdk')
    sdk = str(override) if override else (str(matching) if matching.exists() else env.get('SDKROOT') or subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip())
    env['SDKROOT'] = sdk
    # Test the actual compiler/linker pair, not just clang --version.
    with tempfile.TemporaryDirectory(prefix='aps380-compiler-') as folder:
        source = Path(folder) / 'check.c'
        source.write_text('int main(void) { return 0; }\n')
        subprocess.run(['clang', str(source), '-o', str(Path(folder) / 'check')], env=env, check=True)
    print('SDKROOT:', sdk, flush=True)
    return env


def prepare_plib(env):
    archive = WORK / 'downloads/plib-1.8.5.tar.gz'
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        subprocess.run(['curl', '-fL', '--retry', '2', 'https://plib.sourceforge.net/dist/plib-1.8.5.tar.gz', '-o', str(archive)], check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != PLIB_SHA:
        raise SystemExit('PLIB archive checksum mismatch')
    tree = WORK / 'plib-1.8.5'
    if not tree.exists():
        subprocess.run(['tar', '-xzf', str(archive), '-C', str(WORK)], check=True)
    # Keep the downloaded source local. Do not modify the Windows dependency copy.
    for name in ('src/ssg/ssg.h', 'src/fnt/fnt.h'):
        p = tree / name
        p.write_text(p.read_text().replace('#  include <OpenGL/gl.h>', '#  include <GL/gl.h>'))
    for name in ('src/ssg/ssg.cxx', 'src/fnt/fntTXF.cxx'):
        p = tree / name
        p.write_text(p.read_text().replace('#  include <OpenGL/CGLCurrent.h>', '#  include <GL/glx.h>').replace('return ( CGLGetCurrentContext () != NULL ) ;', 'return ( glXGetCurrentContext () != NULL ) ;'))
    p = tree / 'src/ssg/ssgLoadFLT.cxx'
    p.write_text(p.read_text().replace('#ifdef UL_WIN32\ntypedef unsigned short ushort;', '#if defined(UL_WIN32) || defined(__APPLE__)\ntypedef unsigned short ushort;'))
    plib_env = dict(env, CPPFLAGS='-I/opt/homebrew/opt/mesa/include -I/opt/homebrew/include -I/opt/X11/include', CXXFLAGS='-O2 -fPIC -std=c++11', CFLAGS='-O2 -fPIC')
    run(['./configure', '--prefix=' + str(WORK / 'deps'), '--disable-pw', '--disable-net', '--disable-psl', '--disable-pui', '--disable-puaux', '--disable-sl'], tree, plib_env, 'plib-configure.log')
    run(['make', 'clean'], tree, plib_env, 'plib-clean.log')
    run(['make', '-j4'], tree, plib_env, 'plib-build.log')
    run(['make', 'install'], tree, plib_env, 'plib-install.log')
    # Match FreeGLUT's Mesa libGL: GLU's static archive avoids bringing a second
    # libGL implementation into the process via XQuartz's dynamic GLU library.
    shutil.copy2('/opt/X11/lib/libGLU.a', WORK / 'deps/lib/libGLU.a')


def prepare_source():
    def ignore(folder, names):
        excluded = {'windows', 'runtime', 'runtimed', 'export', '__pycache__', 'autom4te.cache', '.depend', '.torcs.rc', 'Make-config', 'config.h', 'config.log', 'config.status', 'config.cache'}
        if Path(folder) == SOURCE:
            excluded.update(('data', 'doc', 'test'))
        return [n for n in names if n in excluded or n.endswith(('.o', '.obj', '.a', '.so', '.dll', '.exe'))]
    destination = WORK / 'source'
    shutil.copytree(SOURCE, destination, ignore=ignore, dirs_exist_ok=True)
    if not (destination / 'data').exists():
        (destination / 'data').symlink_to(SOURCE / 'data', target_is_directory=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['all', 'dependencies', 'configure', 'build', 'install'], default='all')
    parser.add_argument('--sdk', type=Path, help='Explicit SDK override; default prefers the installed OS-major SDK')
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        parser.error('This experimental recipe has been checked only on Apple Silicon macOS')
    if not Path('/opt/X11/lib/libGLU.a').exists():
        parser.error('Install XQuartz first: brew install --cask xquartz')
    required = ['/opt/homebrew/include/GL/freeglut.h', '/opt/homebrew/opt/mesa/include/GL/gl.h', '/opt/homebrew/include/AL/alut.h', '/opt/homebrew/opt/openal-soft/include/AL/al.h']
    if any(not Path(p).exists() for p in required):
        parser.error('Missing Homebrew dependencies; see docs/torcs-macos.md')
    WORK.mkdir(parents=True, exist_ok=True)
    env = sdk_environment(args.sdk)
    if args.stage in ('all', 'dependencies'):
        prepare_plib(env)
    if args.stage == 'dependencies':
        return
    tree = WORK / 'source'
    deps = WORK / 'deps'
    env.update(CPPFLAGS=f'-I{deps}/include -I/opt/homebrew/opt/mesa/include -I/opt/homebrew/include -I/opt/homebrew/opt/openal-soft/include -I/opt/X11/include', LDFLAGS=f'-L{deps}/lib -L/opt/homebrew/opt/mesa/lib -L/opt/homebrew/lib -L/opt/homebrew/opt/openal-soft/lib -framework IOKit -framework CoreFoundation')
    if args.stage in ('all', 'configure'):
        tree = prepare_source()
        run(['./configure', '--disable-xrandr', '--prefix=' + str(WORK / 'install')], tree, env, 'torcs-configure.log')
    if args.stage in ('all', 'build'):
        # First export pass is not parallel-safe in this legacy build system.
        run(['make', '-j1'], tree, env, 'torcs-build.log')
    if args.stage in ('all', 'install'):
        run(['make', 'install'], tree, env, 'torcs-install.log')
        run(['make', 'datainstall'], tree, env, 'torcs-data-install.log')
    print('Stage completed:', args.stage)


if __name__ == '__main__':
    main()
