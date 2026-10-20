#!/usr/bin/env python3
"""Create Tutorial C's two editable liveries from the accepted Tutorial B artwork.

Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
Generated artwork: Free Art License 1.3. Requires GIMP 3, Inkscape and Pillow.
Maintainer baseline regeneration only; it overwrites the supplied C artwork.
"""
from pathlib import Path
import argparse
import os
import subprocess
from PIL import Image

HERE = Path(__file__).resolve().parent
BASE = HERE / 'examples/appendix_b'
DEST = HERE / 'examples/appendix_c'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True, type=Path)
    work = parser.parse_args().work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    (DEST / 'artwork').mkdir(exist_ok=True)
    for index, number, colour, label in [(1, 81, '#db5947', 'red'), (2, 82, '#278c9d', 'teal')]:
        art = DEST / 'artwork' / str(index)
        art.mkdir(exist_ok=True)
        svg = (BASE / 'artwork/decals.svg').read_text(encoding='utf-8').replace('Tutorial B', 'Tutorial C ' + label.title())
        svg = svg.replace('TUTORIAL B', 'TUTORIAL C').replace('>8</text>', f'>{number}</text>')
        svg = svg.replace('y="29"', 'y="20"').replace('font-size="82"', 'font-size="54"')
        svg = svg.replace('../ARTWORK.txt', '../../ARTWORK.txt')
        (art / 'decals.svg').write_bytes(svg.encode('utf-8'))
        png = work / f'decals-{index}.png'
        subprocess.run(['inkscape', str(art / 'decals.svg'), '--export-type=png', '--export-filename=' + str(png)], check=True)
        output = work / f'livery-{index}.png'
        output.unlink(missing_ok=True)
        script = work / f'compose-{index}.py'
        script.write_text(f'''
from gi.repository import Gimp, Gio, Gegl
image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path({str(BASE / 'artwork/livery.xcf')!r}))
found = 0
for layer in image.get_layers():
    if layer.get_name().startswith('Number 8 and lettering'):
        image.remove_layer(layer)
        found += 1
    elif layer.get_name() == 'Body paint — red':
        layer.set_lock_alpha(True)
        Gimp.context_set_foreground(Gegl.Color.new({colour!r}))
        assert layer.edit_fill(Gimp.FillType.FOREGROUND)
        layer.set_name('Body paint — {label}')
assert found == 1
decals = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path({str(png)!r}))
image.insert_layer(decals, None, 0)
decals.set_name('Number {number} and lettering — source: decals.svg')
for name, path in [('gimp-xcf-save', {str(art / 'livery.xcf')!r}), ('file-png-export', {str(output)!r})]:
    proc = Gimp.get_pdb().lookup_procedure(name)
    config = proc.create_config()
    config.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
    config.set_property('image', image)
    config.set_property('file', Gio.File.new_for_path(path))
    assert proc.run(config).index(0) == Gimp.PDBStatusType.SUCCESS
image.delete()
''', encoding='utf-8')
        result = subprocess.run(['gimp', '--new-instance', '--no-interface', '--no-data', '--no-fonts',
                                 '--batch-interpreter=python-fu-eval', '--batch=exec(open(' + repr(str(script)) + ', encoding="utf-8").read())', '--quit'],
                                env=dict(os.environ, XDG_CONFIG_HOME=str(work / 'gimp-config')), capture_output=True, text=True)
        (work / f'gimp-{index}.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        assert result.returncode == 0 and output.exists(), result.stdout + result.stderr
        image = Image.open(output).convert('RGBA')
        image.save(DEST / str(index) / 'car1-stock1.rgb', format='SGI')
        assert Image.open(DEST / str(index) / 'car1-stock1.rgb').tobytes() == image.tobytes()
    logo = (BASE / 'artwork/logo.svg').read_text(encoding='utf-8').replace('Tutorial B', 'Tutorial C').replace('>B</text>', '>C</text>')
    needle = '<text x="128" y="73"'
    logo = logo.replace(needle, '<path d="M128 8 H240 Q248 8 248 16 V30 H128 Z" fill="#278c9d"/>\n    ' + needle)
    (DEST / 'artwork/logo.svg').write_bytes(logo.encode('utf-8'))
    subprocess.run(['inkscape', str(DEST / 'artwork/logo.svg'), '--export-type=png', '--export-filename=' + str(work / 'logo.png')], check=True)
    Image.open(work / 'logo.png').convert('RGB').save(DEST / 'logo.rgb', format='SGI')
    print('Generated red 81, teal 82, shared team logo and editable XCF/SVG sources.')


if __name__ == '__main__':
    main()
