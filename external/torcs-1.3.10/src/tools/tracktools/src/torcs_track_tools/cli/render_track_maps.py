#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : render_track_maps.py
#     created              : 24 Sep 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Regenerate menu PNGs in a category/track directory tree."""

from __future__ import annotations

import argparse
import pathlib
import shutil
import tempfile

from PIL import Image  # type: ignore[import-not-found]

from torcs_track_tools.cli.render_track_map import add_render_arguments
from torcs_track_tools.core.track_map import TrackMapScene, render_png, scene_from_xml, validate_render_settings


def replace_png(scene: TrackMapScene, output: pathlib.Path) -> None:
    """Replace a verified map, preserving permissions or using normal creation mode."""
    # Keep the staging directory on the destination filesystem for atomic replace.
    # Unlike NamedTemporaryFile, a fresh PNG gets normal permissions under umask.
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=f".{output.stem}-") as directory:
        temporary = pathlib.Path(directory) / output.name
        render_png(scene, temporary)
        with Image.open(temporary) as image:
            if image.size != (scene.size, scene.size) or image.mode != "RGBA":
                raise ValueError("Rendered map has unexpected dimensions or pixel format")
            image.verify()
        if output.exists():
            shutil.copymode(output, temporary)
        temporary.replace(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or overwrite all TORCS menu PNGs beneath a tracks root")
    parser.add_argument("--tracks-root", required=True, type=pathlib.Path, help="Directory containing category/track/track.xml")
    add_render_arguments(parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    margin = validate_render_settings(args.size, args.margin, args.sample_step)
    root = args.tracks_root
    if not root.is_dir():
        raise SystemExit(f"Tracks root is not a directory: {root}")
    directories = sorted(path for path in root.glob("*/*") if path.is_dir())
    if not directories:
        raise SystemExit(f"No track directories found beneath: {root}")

    created = overwritten = failed = 0
    for directory in directories:
        xml = directory / f"{directory.name}.xml"
        output = directory / f"{directory.name}.png"
        label = directory.relative_to(root)
        existed = output.exists()
        try:
            if not xml.is_file():
                raise ValueError(f"Missing track XML: {xml.name}")
            scene = scene_from_xml(xml, size=args.size, margin=margin, sample_step=args.sample_step)
            replace_png(scene, output)
        except (Exception, SystemExit) as error:
            # Geometry validation uses SystemExit; one bad track must not stop the batch.
            failed += 1
            print(f"FAILED {label}: {error}")
            continue
        if existed:
            overwritten += 1
        else:
            created += 1
        print(f"{'UPDATED' if existed else 'CREATED'} {output.relative_to(root)}")

    print(f"Summary: {created} created, {overwritten} overwritten, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
