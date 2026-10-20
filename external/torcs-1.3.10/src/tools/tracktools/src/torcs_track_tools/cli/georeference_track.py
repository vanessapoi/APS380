# /***************************************************************************
#     file                 : georeference_track.py
#     created              : 24 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2, or (at your option) any later version.

"""Metadata-only enrichment of existing v4 track XML; dry run by default."""

import argparse
import json
import pathlib

from torcs_track_tools.core.overlay import parse_track_root
from torcs_track_tools.core.track_georeference import enrich_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track-xml", type=pathlib.Path)
    parser.add_argument("--source", type=pathlib.Path)
    parser.add_argument("--tracks-root", type=pathlib.Path)
    parser.add_argument("--max-rmse", type=float, default=20.0)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if bool(args.track_xml) == bool(args.tracks_root):
        parser.error("Choose --track-xml or --tracks-root")
    return args


def candidate_sources(track: pathlib.Path, explicit: pathlib.Path | None) -> list[pathlib.Path]:
    if explicit:
        return [explicit]
    directory = track.parent / "source"
    centerlines = sorted(directory.glob("*centerline*.json"), key=lambda p: ("prepared" not in p.name, p.name))
    return centerlines + sorted(directory.rglob("*profile*.json"))


def process_track(track: pathlib.Path, args: argparse.Namespace) -> dict:
    root = parse_track_root(track.read_text(encoding="utf-8-sig")) if track.is_file() else None
    if root is not None and root.find("section[@name='Georeference']") is not None:
        return {"track": str(track), "status": "already-present"}
    result = {"track": str(track), "status": "unavailable", "attempts": []}
    for source in candidate_sources(track, args.source):
        try:
            report = enrich_file(track, source, args.max_rmse, args.write)
        except (ValueError, KeyError, OSError) as error:
            result["attempts"].append({"source": source.name, "reason": str(error)})
            continue
        result.update(report)
        result["status"] = "written" if args.write else "ready"
        break
    return result


def main() -> int:
    args = parse_args()
    tracks = [args.track_xml] if args.track_xml else sorted(p.parent / f"{p.parent.name}.xml" for p in args.tracks_root.glob("*/*/source") if p.is_dir())
    results = []
    for track in tracks:
        result = process_track(track, args)
        results.append(result)
        print(f"{track.parent.name}: {result['status']}" + (f" ({result['rmse_m']:.2f} m RMSE)" if "rmse_m" in result else ""))
        if args.write and result["status"] == "written" and (track.parent / "source").is_dir():
            (track.parent / "source" / "georeference-report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
