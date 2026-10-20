#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : fetch_centerline.py
#     created              : 19 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Fetch and cache ordered OSM way geometry for TORCS conversion.

This is the manual escape hatch for cases where relation layout discovery cannot
separate the wanted racing loop from pit lanes, service roads, shortcuts, or
other variants.  The user supplies way IDs; the script fetches geometry in small
Overpass chunks, orders connected ways into a loop, projects lat/lon to local
x/y meters, and writes the same centerline cache consumed by the fitter.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from torcs_track_tools.core.osm import (
    order_osm_ways,
)
from torcs_track_tools.core.osm import (
    osm_detect_near_overlaps as detect_near_overlaps,
)
from torcs_track_tools.core.osm import (
    osm_signed_area as signed_area,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch OpenStreetMap centerline way geometry and cache as JSON",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "What are way identifiers?\n"
            "- A way identifier is the numeric OpenStreetMap ID of one line geometry ('way').\n"
            "- A race track centerline is usually split into multiple connected ways.\n"
            "- Pass all relevant way identifiers in driving order or any order; this script reorders them.\n\n"
            "How to get way identifiers manually:\n"
            "1) Open https://www.openstreetmap.org and navigate to the track.\n"
            "2) Open the Layers panel and enable 'Map Data'.\n"
            "3) Click each centerline piece of the track.\n"
            "4) In the side panel, note the 'Way <number>' value.\n"
            "5) Collect those numbers and pass them to --way-ids as comma-separated values.\n\n"
            "Alternative manual method (Overpass Turbo):\n"
            "- Open https://overpass-turbo.eu and run a query like:\n"
            "  [out:json][timeout:60];way[\"highway\"=\"raceway\"](south,west,north,east);out ids tags;\n"
            "- Copy the way ID numbers from the result list."
        ),
    )
    parser.add_argument(
        "--way-ids",
        required=True,
        help="Comma-separated OpenStreetMap way identifiers (numeric IDs)",
    )
    parser.add_argument("--output", required=True, help="Output JSON cache path")
    parser.add_argument(
        "--overpass-url",
        default="https://overpass-api.de/api/interpreter",
        help="Overpass interpreter URL",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=6,
        help="Number of way identifiers per Overpass request chunk",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing cache file")
    return parser.parse_args()


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenCode-CLI/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_json_with_retries(url: str, retries: int = 3, delay_s: float = 1.5) -> dict:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fetch_json(url)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(delay_s * attempt)
    if last_exc is None:
        raise RuntimeError("Overpass request retry loop completed without an exception")
    raise last_exc


def order_ways(ways: list[dict]) -> tuple[list[dict], dict]:
    return order_osm_ways(ways)


def flatten_points(ways: list[dict]) -> list[dict]:
    points: list[dict] = []
    for wi, way in enumerate(ways):
        geom = way.get("geometry") or []
        name = (way.get("tags") or {}).get("name", "")
        for pi, pt in enumerate(geom):
            if wi > 0 and pi == 0:
                continue
            points.append(
                {
                    "lat": float(pt["lat"]),
                    "lon": float(pt["lon"]),
                    "way_id": int(way.get("id", 0)),
                    "way_name": name,
                }
            )
    return points


def print_bad_join_details(ordering: dict) -> None:
    bad = [j for j in ordering.get("joins", []) if float(j.get("gap_m", 0.0)) > 5.0]
    if not bad:
        return
    print("Bad joins:", file=sys.stderr)
    for join in bad[:8]:
        print(
            f"- way {join['from_way_id']} -> way {join['to_way_id']}: "
            f"gap={float(join['gap_m']):.1f}m matched_endpoint={join.get('matched_endpoint')}",
            file=sys.stderr,
        )
    if len(bad) > 8:
        print(f"- ... {len(bad) - 8} more bad joins", file=sys.stderr)


def main() -> int:
    args = parse_args()
    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not args.force:
        print(f"Cache exists, skipping fetch: {out_path}")
        print("Use --force to refresh.")
        return 0

    way_ids = [w.strip() for w in args.way_ids.split(",") if w.strip()]
    if not way_ids:
        print("No way IDs provided", file=sys.stderr)
        return 2

    # Query in chunks to reduce Overpass timeout risk.
    chunk_size = max(1, int(args.chunk_size))
    ways: list[dict] = []
    for i in range(0, len(way_ids), chunk_size):
        chunk = way_ids[i : i + chunk_size]
        query = f"[out:json][timeout:25];way(id:{','.join(chunk)});out geom tags;"
        url = f"{args.overpass_url}?data={urllib.parse.quote(query, safe='')}"
        try:
            payload = fetch_json_with_retries(url)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:400]
            print(f"HTTP error {exc.code} on chunk {chunk}: {body}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"Fetch failed on chunk {chunk}: {exc}", file=sys.stderr)
            return 1

        chunk_ways = [e for e in payload.get("elements", []) if e.get("type") == "way"]
        ways.extend(chunk_ways)

    # Deduplicate way objects by id after chunked fetch.
    by_id: dict[int, dict] = {}
    for w in ways:
        by_id[int(w.get("id", 0))] = w
    ways = list(by_id.values())
    if not ways:
        print("No ways in response", file=sys.stderr)
        return 1

    ordered, ordering = order_ways(ways)
    points = flatten_points(ordered)
    if ordering.get("bad_join"):
        print_bad_join_details(ordering)
        print("Ordered OSM ways contain disconnected or ambiguous joins; aborting.", file=sys.stderr)
        return 1

    out_obj = {
        "schema": 1,
        "source": {
            "type": "osm-overpass",
            "overpass_url": args.overpass_url,
            "way_ids": [int(w) for w in way_ids],
        },
        "ways_ordered": [
            {
                "id": int(w.get("id", 0)),
                "name": (w.get("tags") or {}).get("name", ""),
                "n_points": len(w.get("geometry") or []),
            }
            for w in ordered
        ],
        "ordering": ordering,
        "orientation": {
            "signed_area": signed_area(points),
            "direction": "ccw" if signed_area(points) > 0 else "cw",
        },
        "overlap_diagnostics": detect_near_overlaps(points),
        "polyline": points,
    }

    out_path.write_text(json.dumps(out_obj, indent=2), encoding="utf-8")
    print(f"Wrote cache: {out_path}")
    print(f"Ordered ways: {len(ordered)}")
    print(f"Polyline points: {len(points)}")
    print(f"Potential overlap runs: {out_obj['overlap_diagnostics']['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
