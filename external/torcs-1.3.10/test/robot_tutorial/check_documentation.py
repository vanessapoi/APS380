#!/usr/bin/env python3
"""Fresh Doxygen, snapshot, download, snippet and optional Linux build checks.
Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
"""
import argparse
from functools import lru_cache
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from maintenance import ROOT, DOCS, Run, digest, check_archives


def match(pattern, text, flags=0):
    result = re.search(pattern, text, flags)
    assert result is not None, ('Expected pattern not found', pattern)
    return result


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.ids, self.links, self.text = set(), [], []
        self.feed(Path(path).read_text(encoding='utf-8'))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        attribute = {'a': 'href', 'img': 'src', 'script': 'src', 'object': 'data'}.get(tag)
        if attribute and attrs.get(attribute):
            self.links.append(attrs[attribute])

    def handle_data(self, data):
        self.text.append(data)


@lru_cache(None)
def page(path):
    return Page(path)


def validate(output):
    from urllib.parse import unquote, urlsplit
    normalize = lambda text: re.sub(r'\s+', '', text)
    count = 0
    for md in sorted(DOCS.glob('*.md')):
        text = md.read_text(encoding='utf-8')
        anchor = match(r'^# .*?\{#([^}]+)\}', text).group(1)
        html = output / (anchor + '.html')
        parsed = page(html)
        for href in parsed.links:
            parts = urlsplit(href)
            if parts.scheme or parts.netloc:
                continue
            target = output / unquote(parts.path) if parts.path else html
            assert target.is_file(), (html.name, href)
            if parts.fragment and target.suffix == '.html':
                assert unquote(parts.fragment) in page(target).ids, (html.name, href)
        for code in re.findall(r'```[^\n]*\n(.*?)```', text, re.S):
            assert normalize(code) in normalize(''.join(parsed.text)), (md.name, code[:80])
        # These chapters quote literal source, rather than illustrative pseudocode.
        example = {'chapter_2': 'chapter_2', 'chapter_4': 'chapter_4',
                   'appendix_c': 'appendix_c'}.get(md.stem)
        if example:
            corpus = '\n'.join(p.read_text(encoding='utf-8') for p in (DOCS/'examples'/example).glob('*.cpp'))
            for code in re.findall(r'```cpp\n(.*?)```', text, re.S):
                assert normalize(code) in normalize(corpus), (md.name, 'source snippet drift')
        if md.stem == 'chapter_1':
            corpus = '\n'.join(p.read_text(encoding='utf-8') for p in (DOCS/'examples/chapter_1').glob('*.cpp'))
            for code in re.findall(r'```cpp\n(.*?)```', text, re.S):
                if 'driveCar(tCarElt* car)' in code:
                    assert normalize(code) in normalize(corpus)
        assert not re.search(r'headless|TUTORIAL_VERIFY|VERIFY=1|raceengine\.xml|LD_LIBRARY_PATH|doc/tutorials/robot', text, re.I), md
        count += 1
    for entry in ('index.html', 'group__robotmodint.html'):
        assert 'robot_tutorial.html' in page(output/entry).links
    # Download collisions such as Makefile are deliberately resolved in Doxygen's explicit list.
    config = (ROOT/'src/doc/torcsdoc.conf').read_text(encoding='utf-8')
    template = (ROOT/'src/doc/torcsdoc.conf.in').read_text(encoding='utf-8')
    pattern = r'HTML_EXTRA_FILES\s*=.*?(?=\n\n)'
    extra = match(pattern, config, re.S).group()
    assert extra == match(pattern, template, re.S).group()
    for relative in re.findall(r'src/[^\s\\]+', extra):
        file = ROOT/relative
        assert file.read_bytes() == (output/file.name).read_bytes(), file
    for file in (DOCS/'images').iterdir():
        if file.suffix in ('.svg', '.png', '.jpg'):
            assert file.read_bytes() == (output/file.name).read_bytes(), file
    for file in (DOCS/'examples').rglob('*'):
        if file.suffix in ('.xml', '.vcxproj', '.svg'):
            ET.parse(file)
    check_archives()
    nav = json.loads(match(r'var NAVTREE =\s*(.*?);', (output/'navtreedata.js').read_text(), re.S)[1])
    def nodes(items):
        for title, href, children in items:
            parts = urlsplit(href)
            target = output/parts.path
            assert target.is_file(), href
            if parts.fragment:
                assert parts.fragment in page(target).ids, href
            if isinstance(children, str):
                children = json.loads(match(r'var \w+ =\s*(.*?);', (output/(children+'.js')).read_text(), re.S)[1])
            if children:
                nodes(children)
    guide = next(n for n in nav[0][2] if n[1] == 'robot_tutorial.html')
    nodes([guide])
    return count


def manifests_and_builds(run, build):
    ns = {'m': 'http://schemas.microsoft.com/developer/msbuild/2003'}
    built = 0
    guids = set()
    for folder in sorted((DOCS/'examples').iterdir()):
        project = next(folder.glob('*.vcxproj'))
        xml = ET.parse(project)
        guid = xml.findtext('.//m:ProjectGuid', namespaces=ns)
        assert guid and guid not in guids, project
        guids.add(guid)
        assert {e.get('Include') for e in xml.findall('.//m:ProjectConfiguration', ns)} == {
            'Release|x64', 'Release|Win32', 'Debug|x64', 'Debug|Win32'}
        assert xml.findtext('.//m:LanguageStandard', namespaces=ns) == 'stdcpp14'
        assert xml.findtext('.//m:PlatformToolset', namespaces=ns) == 'v143'
        dest = run.work/folder.name
        shutil.copytree(folder, dest)
        if folder.name == 'chapter_5':
            for stem in ('speed4', 'steering4', 'braking4', 'geometry4', 'recovery4'):
                for extension in ('.cpp', '.h'):
                    shutil.copy(DOCS/'examples/chapter_4'/(stem+extension), dest)
        variants = ['skeleton', 'driving'] if folder.name == 'chapter_1' else ['tutorial5', 'tutorial5pace'] if folder.name == 'chapter_5' else ['default']
        for variant in variants:
            robot = variant if folder.name == 'chapter_5' else project.stem
            for tag in ('ClCompile', 'ClInclude'):
                for e in xml.findall(f'.//m:{tag}[@Include]', ns):
                    assert (dest/e.attrib['Include'].replace('$(TutorialRobot)', robot)).is_file()
            for e in xml.findall('.//m:Copy', ns):
                for value in e.attrib['SourceFiles'].split(';'):
                    if value != '$(TargetPath)':
                        value = value.replace('$(MSBuildThisFileDirectory)', '').replace('$(TutorialRobot)', robot).replace('\\', '/')
                        assert (dest/value).is_file(), value
            if build:
                flags = ['CHECKPOINT='+variant] if folder.name == 'chapter_1' else ['ROBOT='+variant] if folder.name == 'chapter_5' else []
                log = run.command(folder.name+'-'+variant, ['make', '-C', dest, f'TORCS_BASE={ROOT}', '-B', *flags, robot+'.so'])
                assert 'warning:' not in log.lower(), dest
                built += 1
        if build:
            for cpp in dest.glob('*.cpp'):
                if cpp.stem.startswith('tutorial'):
                    continue
                run.command(folder.name+'-'+cpp.stem+'-declarations',
                    ['g++', '-std=c++14', '-Wall', '-Werror=missing-declarations', '-fsyntax-only',
                     '-I'+str(ROOT/'export/include'), cpp])
    return built


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-root', type=Path, required=True, help='Existing artifact parent; each run gets a new child')
    parser.add_argument('--build', action='store_true', help='Build Linux modules without installing')
    args = parser.parse_args()
    if args.build and sys.platform != 'linux':
        parser.error('--build executes Linux builds; use check_windows.py for native Windows builds')
    with Run(args.work_root, 'documentation') as run:
        for name in ('speed', 'final', 'setup', 'texture', 'multi'):
            run.command('snapshot-'+name, [sys.executable, '-B', DOCS/f'snapshot_{name}_helpers.py', '--check'])
        images = run.work/'images'
        shutil.copytree(DOCS/'images', images)
        for name in ('speed', 'path', 'traffic', 'pit'):
            run.command('figures-'+name, [sys.executable, '-B', images/f'generate_{name}_figures.py'])
        for file in images.glob('*.svg'):
            assert digest(file) == digest(DOCS/'images'/file.name), file
        bundle = ROOT/'src/doc/mathjax'
        assert digest(bundle/'tex-svg.js') == match(r'SHA-256: (\w+)', (bundle/'README.txt').read_text())[1]
        warnings = run.work/'warnings.log'
        output = run.work/'html'
        config = run.work/'Doxyfile'
        config.write_text(f'@INCLUDE = "{ROOT / "src/doc/torcsdoc.conf"}"\nOUTPUT_DIRECTORY = "{output}"\nWARNINGS = YES\nWARN_IF_UNDOCUMENTED = NO\nWARN_LOGFILE = "{warnings}"\n', encoding='utf-8')
        run.command('doxygen', ['doxygen', config])
        assert not warnings.read_text().strip(), warnings
        run.report.update(pages=validate(output), linux_builds=manifests_and_builds(run, args.build),
                          windows_execution='not executed (manifests inspected)', html=str(output))
        print('PASS: fresh documentation, links, snippets, downloads, snapshots and project manifests.')
        print('Linux builds:', run.report['linux_builds'], '(not requested)' if not args.build else '')


if __name__ == '__main__':
    main()
