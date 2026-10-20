"""Shared maintenance-test utilities. Copyright (C) 2026 Bernhard Wymann.
GPL-2.0-or-later. No installed assets or existing result directories are modified.
"""
import hashlib
import json
import subprocess
import tempfile
import platform
import sys
import zipfile
from pathlib import Path

if not __debug__:
    raise RuntimeError('Maintenance checks require assertions; do not run Python with -O.')

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'src/doc/robot_tutorial'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_archives():
    """Portable exact-manifest/content check, shared by docs and native runners."""
    counts = {}
    for name, directory in [('tutorial6', 'chapter_6'), ('tutoriala', 'appendix_a'),
                            ('tutorialb', 'appendix_b'), ('tutorialc', 'appendix_c')]:
        folder = DOCS/'examples'/directory
        files = {p.relative_to(folder).as_posix(): p for p in folder.rglob('*') if p.is_file()}
        with zipfile.ZipFile(DOCS/(name+'.zip')) as archive:
            expected = {name+'/'+p for p in files} | {name+'/COPYING'}
            assert len(archive.namelist()) == len(expected) and set(archive.namelist()) == expected, name
            for relative, file in files.items():
                assert archive.read(name+'/'+relative) == file.read_bytes(), file
            assert archive.read(name+'/COPYING') == (ROOT/'COPYING').read_bytes(), name
            counts[name] = {'files': len(expected), 'sha256': digest(DOCS/(name+'.zip'))}
    return counts


class Run:
    def __init__(self, parent, name):
        parent = Path(parent).resolve(strict=True)
        self.work = Path(tempfile.mkdtemp(prefix=name + '-', dir=parent))
        tools = Path(__file__).parent
        self.report = {'status': 'running', 'work': str(self.work), 'checks': [],
                       'python': sys.version, 'platform': platform.platform(),
                       'tools': {str(p.relative_to(ROOT)): digest(p)
                                 for p in list(tools.iterdir()) + list((tools/'browser').iterdir())
                                 if p.is_file() and p.suffix in ('.py', '.cpp', '.h', '.cjs', '.json')},
                       'sources': {str(p.relative_to(ROOT)): digest(p)
                                   for p in DOCS.rglob('*') if p.is_file() and
                                   p.suffix in ('.cpp', '.h', '.xml', '.py', '.md', '.zip', '.vcxproj')}}
        self.save()

    def save(self):
        (self.work / 'report.json').write_text(json.dumps(self.report, indent=2), encoding='utf-8')

    def command(self, label, command, cwd=ROOT, env=None, timeout=600):
        entry = {'name': label, 'command': list(map(str, command)), 'cwd': str(cwd)}
        self.report['checks'].append(entry)
        self.save()
        try:
            result = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                                    capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            entry['status'] = 'timed out'
            self.save()
            partial = [value.encode('utf-8') if isinstance(value, str) else value or b''
                       for value in (error.stdout, error.stderr)]
            (self.work / (label + '.log')).write_bytes(
                b''.join(partial))
            raise RuntimeError(f'{label}: timed out; see {self.work}') from error
        except OSError as error:
            entry.update(status='failed to start', error=str(error))
            self.save()
            raise
        (self.work / (label + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
        entry.update(returncode=result.returncode, status='passed' if result.returncode == 0 else 'failed')
        self.save()
        if result.returncode:
            raise RuntimeError(f'{label}: exit {result.returncode}; see {self.work / (label + ".log")}')
        return result.stdout + result.stderr

    def __enter__(self):
        print('Artifacts:', self.work, flush=True)
        return self

    def __exit__(self, kind, error, traceback):
        self.report['status'] = 'failed' if error else 'passed'
        if error:
            self.report['error'] = str(error)
        self.save()
