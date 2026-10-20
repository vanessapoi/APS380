#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : fetch_track_layout.py
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

"""Fetch OpenStreetMap circuit layouts and export one ordered centerline cache.

Use this script when raw way-id lists are noisy or include extra loops.
It discovers circuit relations, lists candidate layouts by member role, and
selects one layout (default: metadata-driven "main").

The important design choice is that relation discovery is treated as a layout
selection problem, not just a download.  Many OSM circuit relations contain pit
lanes, kart loops, service roads, alternate chicanes, or role-tagged variants.
``--list-layouts`` prints those candidates with length and closure diagnostics;
the accepted cache should contain only the intended racing loop.  Pit lanes are
fetched later as a separate source for ``integrate_pitlane``.
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
    osm_point_distance_m as point_distance_m,
)
from torcs_track_tools.core.osm import (
    osm_signed_area as signed_area,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch OpenStreetMap track layout from circuit relations",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Input modes:\n"
            "- By relation identifier: --relation-id 284560\n"
            "- By exact or partial name: --name \"Suzuka Circuit\"\n"
            "- By location search: --lat 50.4372 --lon 5.9714\n\n"
            "Layout selection:\n"
            "- --layout main (default): prefer metadata-labeled main or grand-prix-like roles\n"
            "- --layout all: use all relation way members\n"
            "- --layout <role>: use one specific member role from --list-layouts output\n"
            "- --include-roles forward,unlabeled --exclude-roles pit_lane: build a custom role composite\n"
            "- --list-layouts: discover and print choices without writing output"
        ),
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--relation-id", type=int, help="OpenStreetMap relation identifier")
    src.add_argument("--name", help="Track name to search in circuit relations")
    src.add_argument("--lat", type=float, help="Latitude for nearby relation search")
    parser.add_argument("--lon", type=float, help="Longitude for nearby relation search (required with --lat)")
    parser.add_argument("--radius-m", type=float, default=8000.0, help="Search radius for --lat/--lon mode")
    parser.add_argument("--layout", default="main", help="Layout choice: main|all|<role>")
    parser.add_argument("--include-roles", default="", help="Comma-separated relation roles for a custom composite layout")
    parser.add_argument("--exclude-roles", default="", help="Comma-separated relation roles to exclude from custom/all-except-pit composites")
    parser.add_argument("--exclude-way-ids", default="", help="Comma-separated OSM way IDs to exclude from custom/all-except-pit composites")
    parser.add_argument("--list-layouts", action="store_true", help="Only print discovered layout choices")
    parser.add_argument("--output", default="", help="Output JSON cache path")
    parser.add_argument(
        "--overpass-url",
        default="https://overpass-api.de/api/interpreter",
        help="Overpass interpreter URL",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing output")
    return parser.parse_args()


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenCode-CLI/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_json_with_retries(url: str, retries: int = 4, delay_s: float = 1.5) -> dict:
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


def overpass_query(overpass_url: str, query: str) -> dict:
    url = f"{overpass_url}?data={urllib.parse.quote(query, safe='')}"
    return fetch_json_with_retries(url)


def relation_center(rel: dict) -> tuple[float, float] | None:
    center = rel.get("center")
    if center and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def resolve_relations(args: argparse.Namespace) -> list[dict]:
    if args.relation_id is not None:
        query = f"[out:json][timeout:60];relation({args.relation_id});out body center;"
        payload = overpass_query(args.overpass_url, query)
        return [e for e in payload.get("elements", []) if e.get("type") == "relation"]

    if args.name:
        name = args.name.replace('"', '\\"')
        query = (
            "[out:json][timeout:60];"
            f"(relation[\"type\"=\"circuit\"][\"name\"~\"{name}\",i];"
            f"relation[\"circuit\"][\"name\"~\"{name}\",i];"
            f"relation[\"route\"=\"raceway\"][\"name\"~\"{name}\",i];);"
            "out body center;"
        )
        payload = overpass_query(args.overpass_url, query)
        return [e for e in payload.get("elements", []) if e.get("type") == "relation"]

    if args.lat is None or args.lon is None:
        raise SystemExit("--lat requires --lon")

    radius = max(1000.0, float(args.radius_m))
    query = (
        "[out:json][timeout:60];"
        f"(relation(around:{radius},{args.lat},{args.lon})[\"type\"=\"circuit\"];"
        f"relation(around:{radius},{args.lat},{args.lon})[\"circuit\"];"
        f"relation(around:{radius},{args.lat},{args.lon})[\"route\"=\"raceway\"];);"
        "out body center;"
    )
    payload = overpass_query(args.overpass_url, query)
    return [e for e in payload.get("elements", []) if e.get("type") == "relation"]


def choose_relation(relations: list[dict], args: argparse.Namespace) -> dict:
    if not relations:
        raise SystemExit("No matching circuit relation found")

    if len(relations) == 1:
        return relations[0]

    def rel_score(rel: dict) -> tuple[float, int, int]:
        members = rel.get("members") or []
        n_way = sum(1 for m in members if m.get("type") == "way")
        n_total = len(members)
        dist_score = 0.0
        if args.lat is not None and args.lon is not None:
            c = relation_center(rel)
            if c is not None:
                d = point_distance_m(args.lat, args.lon, c[0], c[1])
                dist_score = -d
        return dist_score, n_way, n_total

    ranked = sorted(relations, key=rel_score, reverse=True)
    return ranked[0]


def fetch_relation_ways(overpass_url: str, relation_id: int) -> tuple[dict, list[dict]]:
    query = (
        "[out:json][timeout:60];"
        f"relation({relation_id});"
        "out body center;"
        "way(r);"
        "out geom tags;"
    )
    payload = overpass_query(overpass_url, query)
    rels = [e for e in payload.get("elements", []) if e.get("type") == "relation"]
    ways = [e for e in payload.get("elements", []) if e.get("type") == "way"]
    if not rels:
        raise SystemExit(f"Relation {relation_id} not found")
    return rels[0], ways


def role_key(role: str) -> str:
    r = (role or "").strip().lower()
    return r if r else "unlabeled"


def parse_csv_keys(value: str) -> set[str]:
    return {role_key(v) for v in value.split(",") if v.strip()}


def parse_csv_ints(value: str) -> set[int]:
    ids: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if item:
            ids.add(int(item))
    return ids


def is_pit_like(role: str) -> bool:
    r = role_key(role)
    return any(k in r for k in ("pit", "service", "connector", "link", "access", "entry", "exit"))


def order_ways(ways: list[dict]) -> tuple[list[dict], dict]:
    return order_osm_ways(ways)


def flatten_points(ways: list[dict]) -> list[dict]:
    points: list[dict] = []
    for wi, way in enumerate(ways):
        geom = way.get("geometry") or []
        name = (way.get("tags") or {}).get("name", "")
        role = way.get("member_role", "")
        for pi, pt in enumerate(geom):
            if wi > 0 and pi == 0:
                continue
            points.append(
                {
                    "lat": float(pt["lat"]),
                    "lon": float(pt["lon"]),
                    "way_id": int(way.get("id", 0)),
                    "way_name": name,
                    "member_role": role,
                }
            )
    return points


def polyline_length(points: list[dict]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(points)):
        total += point_distance_m(points[i - 1]["lat"], points[i - 1]["lon"], points[i]["lat"], points[i]["lon"])
    return total


def closure_gap(points: list[dict]) -> float:
    if len(points) < 2:
        return 1e9
    return point_distance_m(points[0]["lat"], points[0]["lon"], points[-1]["lat"], points[-1]["lon"])


def role_priority_score(role: str) -> float:
    r = role_key(role)
    score = 0.0
    if any(k in r for k in ("main", "gp", "grand", "prix", "international", "full", "race", "track", "course")):
        score += 8.0
    if any(k in r for k in ("short", "club", "national", "inner", "outer")):
        score += 1.5
    if any(k in r for k in ("pit", "service", "connector", "link", "access", "entry", "exit")):
        score -= 10.0
    if r == "unlabeled":
        score += 0.2
    return score


def relation_way_role_ids(relation: dict, way_by_id: dict[int, dict]) -> tuple[dict[str, list[int]], dict[int, str], list[int]]:
    role_to_ids: dict[str, list[int]] = {}
    role_by_id: dict[int, str] = {}
    all_ids: list[int] = []
    members = [m for m in (relation.get("members") or []) if m.get("type") == "way"]
    for member in members:
        wid = int(member.get("ref", 0))
        if wid not in way_by_id:
            continue
        role = role_key(member.get("role", ""))
        role_to_ids.setdefault(role, []).append(wid)
        role_by_id[wid] = role
        all_ids.append(wid)
    return role_to_ids, role_by_id, all_ids


def layout_candidate_score(role: str, coverage: float, gap: float) -> float:
    score = role_priority_score(role) + 2.0 * coverage
    if gap < 5.0:
        score += 4.0
    elif gap < 20.0:
        score += 2.0
    score -= min(3.0, gap / 200.0)
    return score


def layout_candidate_ways(unique_ids: list[int], way_by_id: dict[int, dict], role_by_id: dict[int, str], role: str) -> list[dict]:
    ways = []
    for wid in unique_ids:
        way = dict(way_by_id[wid])
        way["member_role"] = role_by_id.get(wid, "") if role in ("all", "composite", "racing") else role
        ways.append(way)
    return ways


def build_layout_candidate(
    label: str,
    ids: list[int],
    role: str,
    preferred: bool,
    way_by_id: dict[int, dict],
    role_by_id: dict[int, str],
    seen_sets: set[tuple[int, ...]],
) -> dict | None:
    unique_ids = list(dict.fromkeys(ids))
    key = tuple(unique_ids)
    if not unique_ids or key in seen_sets:
        return None
    seen_sets.add(key)
    ordered, ordering = order_ways(layout_candidate_ways(unique_ids, way_by_id, role_by_id, role))
    points = flatten_points(ordered)
    total_len = polyline_length(points)
    gap = closure_gap(points)
    coverage = len(ordered) / len(unique_ids)
    return {
        "label": label,
        "role": role,
        "preferred": preferred,
        "way_ids": unique_ids,
        "ordered_ways": ordered,
        "ordering": ordering,
        "polyline": points,
        "length_m": total_len,
        "closure_gap_m": gap,
        "coverage": coverage,
        "score": layout_candidate_score(role, coverage, gap),
    }


def add_layout_candidate(
    candidates: list[dict],
    seen_sets: set[tuple[int, ...]],
    label: str,
    ids: list[int],
    role: str,
    preferred: bool,
    way_by_id: dict[int, dict],
    role_by_id: dict[int, str],
) -> None:
    candidate = build_layout_candidate(label, ids, role, preferred, way_by_id, role_by_id, seen_sets)
    if candidate is not None:
        candidates.append(candidate)


def custom_role_ids(role_to_ids: dict[str, list[int]], include_roles: set[str], excluded_roles: set[str], excluded_ids: set[int]) -> list[int]:
    return [wid for role in sorted(include_roles) for wid in role_to_ids.get(role, []) if role not in excluded_roles and wid not in excluded_ids]


def add_unlabeled_composite_candidates(
    candidates: list[dict],
    seen_sets: set[tuple[int, ...]],
    role_to_ids: dict[str, list[int]],
    excluded_roles: set[str],
    excluded_ids: set[int],
    way_by_id: dict[int, dict],
    role_by_id: dict[int, str],
) -> None:
    unlabeled_ids = role_to_ids.get("unlabeled", [])
    if not unlabeled_ids:
        return
    for role in sorted(role_to_ids):
        if role == "unlabeled" or is_pit_like(role) or role in excluded_roles:
            continue
        composite_ids = [wid for wid in role_to_ids[role] + unlabeled_ids if wid not in excluded_ids]
        add_layout_candidate(candidates, seen_sets, f"role:{role}+unlabeled", composite_ids, "composite", True, way_by_id, role_by_id)


def nonpit_role_ids(role_to_ids: dict[str, list[int]], excluded_roles: set[str], excluded_ids: set[int]) -> list[int]:
    nonpit_roles = [role for role in sorted(role_to_ids) if not is_pit_like(role) and role not in excluded_roles]
    return [wid for role in nonpit_roles for wid in role_to_ids.get(role, []) if wid not in excluded_ids]


def build_layout_candidates(
    relation: dict,
    way_by_id: dict[int, dict],
    include_roles: set[str] | None = None,
    exclude_roles: set[str] | None = None,
    exclude_way_ids: set[int] | None = None,
) -> list[dict]:
    role_to_ids, role_by_id, all_ids = relation_way_role_ids(relation, way_by_id)
    candidates: list[dict] = []
    seen_sets: set[tuple[int, ...]] = set()

    for role, ids in sorted(role_to_ids.items()):
        add_layout_candidate(candidates, seen_sets, f"role:{role}", ids, role, role != "unlabeled", way_by_id, role_by_id)

    excluded_roles = set(exclude_roles or set())
    excluded_ids = set(exclude_way_ids or set())
    if include_roles:
        add_layout_candidate(candidates, seen_sets, "custom-roles", custom_role_ids(role_to_ids, include_roles, excluded_roles, excluded_ids), "composite", True, way_by_id, role_by_id)

    add_unlabeled_composite_candidates(candidates, seen_sets, role_to_ids, excluded_roles, excluded_ids, way_by_id, role_by_id)
    add_layout_candidate(candidates, seen_sets, "all-except-pit-like", nonpit_role_ids(role_to_ids, excluded_roles, excluded_ids), "racing", True, way_by_id, role_by_id)
    add_layout_candidate(candidates, seen_sets, "all-members", all_ids, "all", False, way_by_id, role_by_id)

    return candidates


def layout_by_label(candidates: list[dict], label: str) -> dict | None:
    return next((candidate for candidate in candidates if candidate["label"] == label), None)


def requested_layout_candidate(candidates: list[dict], layout: str) -> dict:
    wanted = layout.strip().lower()
    for candidate in candidates:
        if candidate["role"] == wanted or candidate["label"].lower() == wanted:
            return candidate
    raise SystemExit(f"Requested layout '{layout}' not found in candidates")


def default_layout_candidate(candidates: list[dict]) -> dict:
    non_all = [candidate for candidate in candidates if candidate["role"] != "all"]
    if not non_all:
        return max(candidates, key=lambda candidate: (candidate["score"], candidate["length_m"]))

    preferred = [candidate for candidate in non_all if not is_pit_like(candidate["role"])]
    pool = preferred if preferred else non_all
    return max(pool, key=lambda candidate: (candidate["score"], candidate["length_m"]))


def layout_with_all_members_guard(best: dict, candidates: list[dict]) -> dict:
    all_members = layout_by_label(candidates, "all-members")
    if all_members is not None and best["length_m"] < 0.45 * all_members["length_m"] and all_members["closure_gap_m"] < 40.0:
        return all_members
    return best


def pick_layout(candidates: list[dict], layout: str) -> dict:
    if not candidates:
        raise SystemExit("No layout candidates available")

    if layout == "all":
        all_members = layout_by_label(candidates, "all-members")
        if all_members is not None:
            return all_members

    if layout not in ("", "main", "all"):
        return requested_layout_candidate(candidates, layout)

    # Metadata-driven default (option 2): prefer role-based candidates, but avoid
    # pit/service-only selections and tiny partial layouts.
    return layout_with_all_members_guard(default_layout_candidate(candidates), candidates)


def print_layouts(candidates: list[dict]) -> None:
    print("Discovered layout candidates:")
    ranked = sorted(candidates, key=lambda c: (c["score"], c["length_m"]), reverse=True)
    for c in ranked:
        print(
            "- "
            f"{c['label']}: ways={len(c['way_ids'])}, "
            f"length={c['length_m']:.1f}m, "
            f"closure_gap={c['closure_gap_m']:.1f}m, "
            f"coverage={100.0 * c['coverage']:.1f}%, "
            f"score={c['score']:.2f}"
        )


def print_bad_join_details(candidate: dict) -> None:
    joins = (candidate.get("ordering") or {}).get("joins") or []
    bad = [j for j in joins if float(j.get("gap_m", 0.0)) > 5.0]
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
    if args.lat is not None and args.lon is None:
        raise SystemExit("--lat requires --lon")
    if not args.list_layouts and not args.output:
        raise SystemExit("--output is required unless --list-layouts is used")

    relations = resolve_relations(args)
    relation = choose_relation(relations, args)
    relation_id = int(relation.get("id", 0))

    rel_full, ways = fetch_relation_ways(args.overpass_url, relation_id)
    way_by_id = {int(w.get("id", 0)): w for w in ways}
    include_roles = parse_csv_keys(args.include_roles)
    exclude_roles = parse_csv_keys(args.exclude_roles)
    exclude_way_ids = parse_csv_ints(args.exclude_way_ids)
    candidates = build_layout_candidates(rel_full, way_by_id, include_roles, exclude_roles, exclude_way_ids)
    if not candidates:
        raise SystemExit("No usable way members found in relation")

    print(f"Chosen relation: {relation_id} ({(rel_full.get('tags') or {}).get('name', '')})")
    print_layouts(candidates)
    if args.list_layouts:
        return 0

    chosen = pick_layout(candidates, args.layout.strip().lower())
    print(f"Selected layout: {chosen['label']}")
    if chosen.get("ordering", {}).get("bad_join"):
        print_bad_join_details(chosen)
        raise SystemExit("Selected layout has disconnected or ambiguous joins; aborting fetch cache write")

    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not args.force:
        print(f"Output exists, skipping: {out_path}")
        print("Use --force to overwrite")
        return 0

    ordered = chosen["ordered_ways"]
    points = chosen["polyline"]
    out_obj = {
        "schema": 2,
        "source": {
            "type": "osm-overpass-circuit",
            "overpass_url": args.overpass_url,
            "relation_id": relation_id,
            "relation_name": (rel_full.get("tags") or {}).get("name", ""),
            "layout_request": args.layout,
            "layout_selected": chosen["label"],
        },
        "layouts": [
            {
                "label": c["label"],
                "role": c["role"],
                "way_count": len(c["way_ids"]),
                "length_m": c["length_m"],
                "closure_gap_m": c["closure_gap_m"],
                "coverage": c["coverage"],
                "score": c["score"],
            }
            for c in sorted(candidates, key=lambda x: (x["score"], x["length_m"]), reverse=True)
        ],
        "ways_ordered": [
            {
                "id": int(w.get("id", 0)),
                "name": (w.get("tags") or {}).get("name", ""),
                "member_role": w.get("member_role", ""),
                "n_points": len(w.get("geometry") or []),
            }
            for w in ordered
        ],
        "ordering": chosen.get("ordering", {}),
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
    print(f"Approximate length: {chosen['length_m']:.1f} m")
    print(f"Closure gap: {chosen['closure_gap_m']:.1f} m")
    print(f"Potential overlap runs: {out_obj['overlap_diagnostics']['count']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        print(f"HTTP error {exc.code}: {body}", file=sys.stderr)
        raise
