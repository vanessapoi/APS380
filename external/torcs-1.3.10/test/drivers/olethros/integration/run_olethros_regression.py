#!/usr/bin/env python3
# file: run_olethros_regression.py; created: 2026
# Copyright (C) 2026 by Bernhard Wymann <berniw@bluewin.ch>
# This program is free software under the GNU General Public License,
# version 2 or (at your option) any later version.
"""Run focused and multi-bot Olethros compatibility checks on runtime tracks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterable
from brain_state import BrainState, exclusive_session, local_torcs_dir, recover_brain
from behavior import check_behavior


SUMMARY_RE = re.compile(
    r"Sim Time:\s*(?P<sim_time>[0-9.]+)\s*\[s\],\s*"
    r"Leader Laps:\s*(?P<laps>[0-9]+),\s*"
    r"Leader Distance:\s*(?P<distance>[0-9.]+)\s*\[km\]"
)


@dataclass(frozen=True)
class Track:
    category: str
    name: str
    xml: Path


@dataclass
class Result:
    category: str
    track: str
    status: str
    elapsed_s: float
    driver_idx: int = 6
    sim_time_s: str = ""
    laps: str = ""
    top_speed_mps: str = ""
    exit_code: str = ""
    timed_out: bool = False
    result_xml: str = ""
    log: str = ""
    message: str = ""
    session: str = "race"


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[4]


def default_runtime_dir() -> Path:
    return repo_root_from_script() / "runtime"


def xml_attr(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def sanitize_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def track_artifact_stem(track: Track) -> str:
    readable = sanitize_name(f"{track.category}-{track.name}")[:64] or "track"
    identity = f"{track.category}/{track.name}".encode("utf-8")
    return readable+"-"+hashlib.sha256(identity).hexdigest()[:12]


def create_output_dir(requested: Path | None, root: Path) -> Path:
    if requested is not None:
        requested.mkdir(parents=True, exist_ok=False)
        return requested
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S-"), dir=root))


def discover_tracks(runtime_dir: Path, categories: set[str] | None) -> list[Track]:
    tracks: list[Track] = []
    tracks_dir = runtime_dir / "tracks"
    for category_dir in sorted(path for path in tracks_dir.iterdir() if path.is_dir()):
        if categories and category_dir.name not in categories:
            continue
        for track_dir in sorted(path for path in category_dir.iterdir() if path.is_dir()):
            xml = track_dir / f"{track_dir.name}.xml"
            if xml.exists():
                tracks.append(Track(category_dir.name, track_dir.name, xml))
    return tracks


def filter_tracks(tracks: Iterable[Track], names: set[str] | None) -> list[Track]:
    if not names:
        return list(tracks)
    return [
        track
        for track in tracks
        if track.name in names or f"{track.category}/{track.name}" in names
    ]


def build_raceman_xml(track: Track, laps: int, driver_idx: int, opponent_indices=(), session="race") -> str:
    if session not in ("race", "practice") or (session == "practice" and opponent_indices):
        raise ValueError("require race or single-bot practice")
    session_name = session.capitalize()
    title = f"Olethros compatibility {track.category}/{track.name}"
    indices = [driver_idx, *opponent_indices]
    entries = "\n".join(f'''\t\t<section name="{i}">
\t\t\t<attnum name="idx" val="{idx}"/>
\t\t\t<attstr name="module" val="olethros"/>
\t\t</section>''' for i, idx in enumerate(indices, 1))
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE params SYSTEM "../libs/tgf/params.dtd">

<params name="{xml_attr(title)}" type="param" mode="mw">
\t<section name="Header">
\t\t<attstr name="name" val="{xml_attr(title)}"/>
\t\t<attstr name="description" val="Generated Olethros compatibility check"/>
\t\t<attnum name="priority" val="100"/>
\t</section>
\t<section name="Tracks">
\t\t<attnum name="maximum number" val="1"/>
\t\t<section name="1">
\t\t\t<attstr name="name" val="{xml_attr(track.name)}"/>
\t\t\t<attstr name="category" val="{xml_attr(track.category)}"/>
\t\t</section>
\t</section>
\t<section name="Races">
\t\t<section name="1"><attstr name="name" val="{session_name}"/></section>
\t</section>
\t<section name="{session_name}">
\t\t<attnum name="laps" val="{laps}"/>
\t\t<attnum name="distance" val="0"/>
\t\t<attstr name="type" val="{session}"/>
\t\t<attstr name="starting order" val="drivers list"/>
\t\t<attstr name="restart" val="yes"/>
\t\t<attstr name="display mode" val="results only"/>
\t\t<attstr name="display results" val="yes"/>
\t\t<section name="Starting Grid">
\t\t\t<attnum name="rows" val="1"/>
\t\t\t<attnum name="distance to start" val="25"/>
\t\t\t<attnum name="distance between columns" val="20"/>
\t\t\t<attnum name="offset within a column" val="10"/>
\t\t\t<attnum name="initial speed" unit="km/h" val="0"/>
\t\t\t<attnum name="initial height" unit="m" val="0.2"/>
\t\t</section>
\t</section>
\t<section name="Drivers">
\t\t<attnum name="maximum number" val="{len(indices)}"/>
\t\t<attstr name="focused module" val="olethros"/>
\t\t<attnum name="focused idx" val="{driver_idx}"/>
{entries}
\t</section>
</params>
'''


def result_xml_mtimes(runtime_dir: Path, config: Path) -> dict[Path, int]:
    result_dir = local_torcs_dir() / "results" / config.stem
    try:
        return {
            candidate: candidate.stat().st_mtime_ns
            for candidate in result_dir.glob("results-*.xml")
        }
    except OSError:
        return {}


def latest_result_xml(
    runtime_dir: Path, config: Path, previous_mtimes: dict[Path, int]
) -> Path | None:
    changed = [
        candidate
        for candidate, mtime in result_xml_mtimes(runtime_dir, config).items()
        if candidate not in previous_mtimes or mtime > previous_mtimes[candidate]
    ]
    return max(changed, key=lambda path: path.stat().st_mtime_ns) if changed else None


def child_value(section: ET.Element, tag: str, name: str) -> str | None:
    for child in section:
        if child.tag == tag and child.attrib.get("name") == name:
            return child.attrib.get("val")
    return None


def parse_driver_result(path: Path, driver_idx: int, session="race") -> tuple[int | None, float | None, str]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return None, None, f"could not parse result XML: {exc}"

    if session == "practice":
        # Practice stores per-lap results, with identity in the track's Drivers
        # list instead of a race Rank. Only single-bot practice is supported.
        for circuit in root.findall("section"):
            drivers = circuit.findall("./section[@name='Drivers']/section")
            if len(drivers) != 1 or child_value(drivers[0], "attstr", "dll name") != "olethros":
                continue
            if child_value(drivers[0], "attnum", "index") != str(driver_idx):
                continue
            practice = circuit.find("./section[@name='Results']/section[@name='Practice']")
            if practice is None or not child_value(practice, "attstr", "driver name"):
                continue
            try:
                rows = practice.findall("section")
                numbers = sorted(int(row.attrib["name"]) for row in rows)
                if not numbers or numbers != list(range(1, len(numbers)+1)):
                    raise ValueError("incomplete practice lap sequence")
                times = [float(child_value(row, "attnum", "time") or "nan") for row in rows]
                speeds = [float(child_value(row, "attnum", "top speed") or "nan") for row in rows]
                if any(not math.isfinite(t) or t <= 0 for t in times):
                    raise ValueError("invalid practice lap time")
                if any(not math.isfinite(v) or v < 0 for v in speeds):
                    raise ValueError("invalid practice top speed")
                return len(rows), max(speeds), ""
            except (ValueError, TypeError, KeyError) as exc:
                return None, None, f"invalid practice result: {exc}"
        return None, None, f"no olethros idx {driver_idx} practice result"

    for section in root.iter("section"):
        if section.attrib.get("name") != "Rank":
            continue
        for entry in section:
            if entry.tag != "section":
                continue
            module = child_value(entry, "attstr", "module")
            idx = child_value(entry, "attnum", "idx")
            if module != "olethros" or idx is None or int(float(idx)) != driver_idx:
                continue
            laps = child_value(entry, "attnum", "laps")
            top_speed = child_value(entry, "attnum", "top speed")
            return (
                int(float(laps)) if laps is not None else None,
                float(top_speed) if top_speed is not None else None,
                "",
            )
    return None, None, f"no olethros idx {driver_idx} race result"


def add_failure(result: Result, message: str) -> None:
    result.status = "fail"
    result.message = f"{result.message}; {message}" if result.message else message


def parse_run(
    track: Track,
    output: str,
    elapsed_s: float,
    exit_code: int | None,
    timed_out: bool,
    timeout_s: int,
    result_xml: Path | None,
    driver_idx: int,
    expected_laps: int,
    min_top_speed: float,
    max_sim_time: float,
    log: Path,
    session: str = "race",
) -> Result:
    summary = list(SUMMARY_RE.finditer(output))
    match = summary[-1] if summary else None
    result = Result(
        category=track.category,
        track=track.name,
        status="pass" if match else "fail",
        elapsed_s=elapsed_s,
        driver_idx=driver_idx,
        exit_code="" if exit_code is None else str(exit_code),
        timed_out=timed_out,
        log=str(log),
        session=session,
    )
    if timed_out:
        add_failure(result, f"timed out after {timeout_s}s")
    elif exit_code not in (None, 0):
        add_failure(result, f"wtorcs exited with code {exit_code}")
    if match:
        result.sim_time_s = match.group("sim_time")
        sim_time = float(result.sim_time_s)
        if max_sim_time > 0.0 and sim_time > max_sim_time:
            add_failure(result, f"simulation time {sim_time:.3f} > allowed {max_sim_time:.3f}")
    else:
        add_failure(result, "race summary missing")

    if result_xml is None:
        add_failure(result, "fresh result XML missing")
        return result
    result.result_xml = str(result_xml)
    laps, top_speed, error = parse_driver_result(result_xml, driver_idx, session)
    if error:
        add_failure(result, error)
        return result
    if laps is None:
        add_failure(result, "lap count missing")
    else:
        result.laps = str(laps)
        if laps < expected_laps:
            add_failure(result, f"olethros laps {laps} < requested {expected_laps}")
    if top_speed is not None:
        result.top_speed_mps = f"{top_speed:.6g}"
        if not math.isfinite(top_speed):
            add_failure(result, "nonfinite top speed")
        elif top_speed < min_top_speed:
            add_failure(result, f"top speed {top_speed:.3f} < required {min_top_speed:.3f}")
    elif min_top_speed > 0.0:
        add_failure(result, "top speed missing")
    return result


def run_track(args: argparse.Namespace, track: Track, out_dir: Path) -> Result:
    session = getattr(args, "session", "race")
    indices = [args.olethros_idx, *args.opponent_idx]
    suffix = "-".join(str(idx) for idx in indices)
    stem = track_artifact_stem(track)
    config_name = f"olethros-compat-{stem}-{suffix}-{session}.xml"
    config = args.runtime_dir / "config" / "raceman" / config_name
    log = out_dir / f"{stem}.log"
    # Only enter cleanup after exclusive creation succeeds: an existing user
    # configuration must neither be overwritten nor removed on an open failure.
    handle = config.open("x", encoding="utf-8")
    try:
        with handle:
            handle.write(build_raceman_xml(track, args.laps, args.olethros_idx, args.opponent_idx, session))
        shutil.copyfile(config, out_dir / config_name)
        previous_mtimes = result_xml_mtimes(args.runtime_dir, config)
        command = [str(args.wtorcs), "-r", f"config/raceman/{config_name}"]
        start = time.monotonic()
        exit_code: int | None = None
        timed_out = False
        launch_error = None
        try:
            env = os.environ.copy()
            env["OLETHROS_DIAGNOSTICS"] = "1"
            completed = subprocess.run(
                command,
                cwd=args.runtime_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=args.timeout,
            )
            raw_output = completed.stdout or b""
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            raw_output = exc.stdout or b""
            timed_out = True
        except OSError as exc:
            launch_error = f"could not launch {args.wtorcs}: {exc}"
            raw_output = (launch_error+"\n").encode("utf-8")
    finally:
        config.unlink(missing_ok=True)
    elapsed = time.monotonic() - start
    log.write_bytes(raw_output)
    output = raw_output.decode(errors="replace")
    result_xml = None if launch_error else latest_result_xml(args.runtime_dir, config, previous_mtimes)
    if result_xml is not None:
        snapshot = out_dir / f"{stem}.results.xml"
        shutil.copyfile(result_xml, snapshot)
        result_xml = snapshot
    results = [parse_run(track, output, elapsed, exit_code, timed_out, args.timeout,
                         result_xml, idx, args.laps, args.min_top_speed, args.max_sim_time, log, session)
               for idx in indices]
    if launch_error:
        for result in results:
            result.message = launch_error
    (out_dir / f"{stem}.drivers.json").write_text(
        json.dumps([vars(r) for r in results], indent=2), encoding="utf-8")
    result = results[0]
    for other in results[1:]:
        if other.status != "pass":
            add_failure(result, f"bot {other.driver_idx}: {other.message}")
    report = check_behavior(output, f"{track.category}/{track.name}", args.laps, args.brain_state, indices)
    (out_dir / f"{stem}.behavior.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not launch_error:
        for failure in report["failures"]:
            add_failure(result, failure)
    return result


@contextmanager
def isolate_track_brains(local_dir: Path, track_name: str, indices, mode: str):
    """Restore every acquired brain even if a later bot cannot enter isolation."""
    with ExitStack() as stack:
        isolations = {}
        for idx in indices:
            brain = local_dir/"drivers"/"olethros"/str(idx)/(track_name+".brain")
            isolations[idx] = stack.enter_context(BrainState(brain, mode))
        yield isolations


def write_summary(out_dir: Path, results: list[Result]) -> Path:
    summary = out_dir / "summary.csv"
    with summary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Result.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(vars(result) for result in results)
    return summary


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, default=default_runtime_dir())
    parser.add_argument("--wtorcs", type=Path)
    parser.add_argument("--track", action="append", help="Track name or category/name; repeatable")
    parser.add_argument("--category", action="append", help="Track category; repeatable")
    parser.add_argument("--classic", action="store_true", help="Select the 28 checked-in reference tracks")
    parser.add_argument("--compare-reference", action="store_true", help="Require exact two-lap clean-state time/top-speed reference fields")
    parser.add_argument("--olethros-idx", type=int, default=6, help="Robot index; 6 is Olethros 7")
    parser.add_argument("--opponent-idx", type=int, action="append", default=[],
                        help="Additional Olethros bot index; repeatable, unique indices 0..9")
    parser.add_argument("--laps", type=int, default=3)
    parser.add_argument("--session", choices=("race", "practice"), default="race",
                        help="Single-bot practice includes radius learning and brain saving")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--min-top-speed", type=float, default=0.0, help="Optional minimum speed in m/s")
    parser.add_argument("--max-sim-time", type=float, default=0.0, help="Optional maximum simulation time in seconds")
    parser.add_argument("--brain-state", choices=("clean", "persisted"), default="clean",
                        help="Runner isolates/restores the specific brain; production I/O is unchanged")
    parser.add_argument("--recover-brain", type=Path, help="Recover an interrupted run from its .regression.json journal")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)
    if args.recover_brain:
        with exclusive_session(local_torcs_dir()):
            recover_brain(args.recover_brain)
        return 0
    indices = [args.olethros_idx, *args.opponent_idx]
    if args.laps < 2 or args.timeout <= 0 or any(not 0 <= idx < 10 for idx in indices) or len(set(indices)) != len(indices):
        parser.error("require laps >= 2, timeout > 0, and unique bot indices 0..9")
    if args.session == "practice" and args.opponent_idx:
        parser.error("practice requires a single bot")

    args.runtime_dir = args.runtime_dir.resolve()
    args.wtorcs = args.wtorcs.resolve() if args.wtorcs else args.runtime_dir / ("wtorcs.exe" if os.name == "nt" else "torcs")
    categories = set(args.category) if args.category else None
    names = set(args.track) if args.track else None
    reference_file = Path(__file__).resolve().parents[1]/"fixtures"/"classic-reference.csv"
    reference = {}
    if args.classic or args.compare_reference:
        with reference_file.open(newline="", encoding="utf-8") as handle:
            reference = {f"{r['category']}/{r['track']}": r for r in csv.DictReader(handle)}
    if args.classic:
        if names or categories:
            parser.error("--classic cannot be combined with --track or --category")
        names = set(reference)
    if args.compare_reference and (args.laps != 2 or args.brain_state != "clean" or indices != [6] or args.session != "race"):
        parser.error("reference comparison requires --laps 2 --brain-state clean --session race and only bot 6")
    tracks = filter_tracks(discover_tracks(args.runtime_dir, categories), names)
    if names:
        missing = names - {t.name for t in tracks} - {f"{t.category}/{t.name}" for t in tracks}
        if missing:
            parser.error(f"tracks not found: {sorted(missing)}")
    if args.limit > 0:
        tracks = tracks[: args.limit]
    if args.list:
        for track in tracks:
            print(f"{track.category}/{track.name}")
        return 0
    if not args.wtorcs.exists() or not tracks:
        print("wtorcs executable or selected tracks missing", file=sys.stderr)
        return 2

    out_dir = create_output_dir(args.out_dir, repo_root_from_script() / "test-results" / "olethros")
    results: list[Result] = []
    (out_dir / "settings.json").write_text(json.dumps({"brain_state": args.brain_state,
        "laps": args.laps, "session": args.session, "idx": args.olethros_idx, "driver_indices": indices, "runtime": str(args.runtime_dir),
        "tracks": [f"{t.category}/{t.name}" for t in tracks]}, indent=2), encoding="utf-8")
    try:
        with exclusive_session(local_torcs_dir()):
            for track in tracks:
                with isolate_track_brains(local_torcs_dir(), track.name, indices, args.brain_state) as isolations:
                    result = run_track(args, track, out_dir)
                if args.compare_reference:
                    expected = reference.get(f"{track.category}/{track.name}")
                    if expected is None:
                        add_failure(result, "no reference for track")
                    else:
                        for field in ("laps", "sim_time_s", "top_speed_mps"):
                            if getattr(result, field) != expected[field]:
                                add_failure(result, f"reference {field}: {getattr(result, field)} != {expected[field]}")
                results.append(result)
                reports = {str(idx): isolation.report for idx, isolation in isolations.items()}
                (out_dir / f"{track_artifact_stem(track)}.brain.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
                print(f"{track.category}/{track.name}: {result.status} top={result.top_speed_mps}m/s {result.message}")
    finally:
        summary = write_summary(out_dir, results)
    failed = sum(result.status != "pass" for result in results)
    print(f"summary: {summary}")
    print(f"passed={len(results) - failed} failed={failed} total={len(results)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
