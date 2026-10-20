# /***************************************************************************
#     file                 : audit_track_radii.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""List oversized track curves without modifying XML."""

import argparse
import json
from pathlib import Path

from torcs_track_tools.core.geometry import MAX_TORCS_RADIUS_M
from torcs_track_tools.core.radius_audit import audit_tree


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracks-root", type=Path, required=True)
    parser.add_argument("--limit", type=float, default=MAX_TORCS_RADIUS_M, help="Screening radius in metres")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--preflight", action="store_true", help="Classify static repair-tool eligibility and list blockers")
    args = parser.parse_args(argv)
    try:
        report = audit_tree(args.tracks_root, args.limit, args.preflight)
        if args.report:
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    for track in report["tracks"]:
        status = f" [{track['repair_preflight']['status']}]" if args.preflight else ""
        print(f"{track['path']}: {len(track['segments'])} segments, maximum {track['maximum_radius_m']:.3f} m{status}")
    print(f"Scanned {report['tracks_scanned']}; affected {report['affected_tracks']} tracks / {report['affected_segments']} segments")
    if args.preflight:
        print(f"Preflight: {report['preflight']['eligible_tracks']} eligible tracks; {report['preflight']['blocked_tracks']} blocked")
    for error in report["errors"]:
        print(f"ERROR {error['path']}: {error['error']}")
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
