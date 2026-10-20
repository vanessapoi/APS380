# /***************************************************************************
#     file                 : batch_repair_track_radii.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""Run complete, resumable track repairs through the existing toolchain."""

import argparse
from pathlib import Path

from torcs_track_tools.core.geometry import MAX_TORCS_RADIUS_M
from torcs_track_tools.core.radius_batch import Batch, eligible_keys


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--track", action="append", help="category/name; repeat for a bounded batch")
    selection.add_argument("--all", action="store_true", help="Queue all affected tracks; unsupported tracks are reported as blocked")
    parser.add_argument("--resume", action="store_true", help="Resume the existing manifest")
    parser.add_argument("--diagnose", action="store_true", help="With --resume, measure failed tracks' original closure and summarize failures only")
    parser.add_argument("--deploy", action="store_true", help="Deploy complete successful tracks, with per-track rollback on failure")
    parser.add_argument("--jobs", type=int, default=2, help="Independent fitting/generation workers; merges are serialized")
    parser.add_argument("--timeout", type=int, default=1800, help="Seconds allowed for each external command")
    parser.add_argument("--curve-radius", type=float,
                        help=f"Fitting radius in (0, {MAX_TORCS_RADIUS_M:g}] m; changing it starts a fresh fit for rejected candidates")
    parser.add_argument("--accept-existing-clearance", action="append", default=[], metavar="CATEGORY/TRACK:SEGMENT",
                        help="Accept only the explicitly named, byte-unchanged baseline clearance condition")
    return parser


def validate_arguments(args, parser):
    if not 1 <= args.jobs <= 4 or args.timeout <= 0:
        parser.error("Use 1-4 workers and a positive timeout")
    if not (args.track or args.all or args.resume):
        parser.error("Select --track, --all, or --resume")
    if args.diagnose and (not args.resume or args.deploy):
        parser.error("--diagnose requires --resume and cannot deploy")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_arguments(args, parser)
    try:
        runtime = args.runtime_dir.resolve()
        tracks = eligible_keys(runtime) if args.all else args.track
        acceptances = parse_clearance_acceptances(args.accept_existing_clearance)
        runner = Batch(runtime, args.work_dir, tracks, args.resume, args.deploy, args.jobs, args.timeout, acceptances, args.curve_radius)
        return runner.diagnose() if args.diagnose else runner.run()
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Batch failed: {error}\n")


def parse_clearance_acceptances(values):
    result = {}
    for value in values:
        key, separator, name = value.partition(":")
        if not separator or not key or not name:
            raise ValueError("Use CATEGORY/TRACK:SEGMENT for clearance acceptance")
        result.setdefault(key, set()).add(name)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
