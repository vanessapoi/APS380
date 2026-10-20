#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : render_track_map.py
#     created              : 14 Aug 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Render a transparent TORCS menu map from final track XML geometry."""

from __future__ import annotations

import argparse
import pathlib

from torcs_track_tools.core.track_map import render_png, render_svg, scene_from_xml


def add_render_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--size", type=int, default=1024, help="Square output size in pixels")
    parser.add_argument("--margin", type=float, help="Minimum visible artwork margin in pixels (default: size/128, minimum 2)")
    parser.add_argument("--sample-step", type=float, default=2.0, help="Centerline sampling step in meters")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a TORCS menu PNG and optional review SVG from track XML")
    parser.add_argument("--track-xml", required=True, help="Input TORCS track XML")
    parser.add_argument("--output", required=True, help="Output transparent PNG path")
    parser.add_argument("--svg-output", help="Optional output SVG path using the same geometry and markers")
    add_render_arguments(parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scene = scene_from_xml(pathlib.Path(args.track_xml), size=args.size, margin=args.margin, sample_step=args.sample_step)
    output = pathlib.Path(args.output)
    render_png(scene, output)
    print(f"Wrote track map PNG: {output}")
    if args.svg_output:
        svg_output = pathlib.Path(args.svg_output)
        render_svg(scene, svg_output)
        print(f"Wrote track map SVG: {svg_output}")
    print(f"Map points: {len(scene.track)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
