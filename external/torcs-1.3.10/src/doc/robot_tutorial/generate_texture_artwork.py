#!/usr/bin/env python3
"""Maintain Tutorial B's artwork from the stock1 XCF and editable SVG overlays.

Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
Requires GIMP 3, Inkscape, and Pillow. The exported artwork is under FAL 1.3.
This recreates the supplied baseline, not a reader prerequisite or an editor
for a student's modified XCF. --work selects a disposable build directory.
"""
from pathlib import Path
import argparse
import os
import subprocess
from PIL import Image

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'examples/appendix_b'
MODEL = HERE.parents[2] / 'data/cars/models/car1-stock1/car1-stock1.xcf'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    for name in ('decals', 'logo'):
        subprocess.run(['inkscape', str(SOURCE / 'artwork' / (name + '.svg')),
                        '--export-type=png', '--export-filename=' + str(work / (name + '.png'))], check=True)
    # Keep GIMP's application state separate from the user's editor session.
    script = work / 'compose.py'
    script.write_text(f'''
from gi.repository import Gimp, Gio, Gegl
image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path({str(MODEL)!r}))
assert image
remove = ['17#1','39#1','40#1','37#2','38#1','ads','ads2','torcs',
          'Software Engineering','www.berniw.org','www.berniw.org#1',
          'www.berniw.org#2','www.berniw.org#3','berniw#2','berniw','noise (metallic)',
          'AC3D Texture Coordinate Editor copy']
colours = {{'basic color':'#db5947', 'Decal Mask 1 copy#2':'#fff4db',
            'Decal 1 Border line':'#243c4b'}}
for layer in image.get_layers():
    name = layer.get_name()
    if name in remove or (not layer.get_visible() and name != 'AC3D Texture Coordinate Editor'):
        image.remove_layer(layer)
        continue
    if name in colours:
        layer.set_lock_alpha(True)
        Gimp.context_set_foreground(Gegl.Color.new(colours[name]))
        assert layer.edit_fill(Gimp.FillType.FOREGROUND)
    if name == 'basic color': layer.set_name('Body paint — red')
    if name == 'Decal Mask 1 copy#2': layer.set_name('Side panels — cream')
    if name == 'Decal 1 Border line': layer.set_name('Panel border — dark blue')
    if name == 'AC3D Texture Coordinate Editor': layer.set_name('UV guide — HIDE BEFORE EXPORT')
decals = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image,
                            Gio.File.new_for_path({str(work / 'decals.png')!r}))
assert decals
image.insert_layer(decals, None, 0)
decals.set_name('Number 8 and lettering — source: decals.svg')
for procedure, output in [('gimp-xcf-save', {str(SOURCE / 'artwork/livery.xcf')!r}),
                          ('file-png-export', {str(work / 'livery.png')!r})]:
    proc = Gimp.get_pdb().lookup_procedure(procedure)
    config = proc.create_config()
    config.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
    config.set_property('image', image)
    config.set_property('file', Gio.File.new_for_path(output))
    result = proc.run(config)
    assert result.index(0) == Gimp.PDBStatusType.SUCCESS, (procedure, result.index(0))
image.delete()
''', encoding='utf-8')
    env = dict(os.environ, XDG_CONFIG_HOME=str(work / 'gimp-config'))
    (work / 'livery.png').unlink(missing_ok=True)
    result = subprocess.run(['gimp', '--new-instance', '--no-interface', '--no-data', '--no-fonts',
                             '--batch-interpreter=python-fu-eval',
                             '--batch=exec(open(' + repr(str(script)) + ', encoding="utf-8").read())', '--quit'],
                            env=env, capture_output=True, text=True)
    (work / 'gimp.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    assert result.returncode == 0 and (work / 'livery.png').exists(), result.stdout + result.stderr
    for source, destination, size, mode in [('livery', 'car1-stock1', (1024, 1024), 'RGBA'),
                                           ('logo', 'logo', (256, 256), 'RGB')]:
        image = Image.open(work / (source + '.png')).convert(mode)
        assert image.size == size
        image.save(SOURCE / (destination + '.rgb'), format='SGI')
        # Decoding the actual export checks the format, channels and orientation.
        exported = Image.open(SOURCE / (destination + '.rgb'))
        assert exported.mode == mode and exported.size == size
        assert exported.tobytes() == image.tobytes()
    print('Generated layered XCF and checked 1024x1024 RGBA / 256x256 RGB SGI exports.')


if __name__ == '__main__':
    main()
