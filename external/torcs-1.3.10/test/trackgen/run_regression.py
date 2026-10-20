#!/usr/bin/env python3

##############################################################################
#
#    file                 : run_regression.py
#    created              : Mon Jul 27 2026
#    copyright            : (C) 2026 by Bernhard Wymann
#    email                : berniw@bluewin.ch
#
##############################################################################

##############################################################################
#                                                                            #
#   This program is free software; you can redistribute it and/or modify     #
#   it under the terms of the GNU General Public License as published by     #
#   the Free Software Foundation; either version 2 of the License, or        #
#   (at your option) any later version.                                      #
#                                                                            #
##############################################################################

"""Run trackgen fixtures sequentially with durable progress reporting.

Each fixture runs in its own process with an optional timeout. The runner keeps
per-track output logs and updates a JSON report throughout the run so crashes or
interruptions do not erase results from tracks that already completed.
"""

import argparse
import datetime
import json
import pathlib
import subprocess
import sys
import time


def write_report(report_path, report):
    """Write a report snapshot, preserving progress when replacement is blocked."""
    serialized = json.dumps(report, indent=2) + "\n"
    temporary_path = report_path.with_suffix(".tmp")
    temporary_path.write_text(serialized, encoding="utf-8")
    try:
        temporary_path.replace(report_path)
    except PermissionError:
        # Windows file watchers can briefly prevent replacement of an open file.
        report_path.write_text(serialized, encoding="utf-8")
        temporary_path.unlink(missing_ok=True)


def find_tracks(source_root, requested_tracks):
    """Return fixture directories matching optional category/name labels."""
    requested = set(requested_tracks)
    tracks = []
    for xml_path in sorted(source_root.rglob("*.xml")):
        relative_directory = xml_path.parent.relative_to(source_root)
        label = relative_directory.as_posix()
        if not requested or label in requested:
            tracks.append((label, xml_path.parent))
    found = {label for label, unused_path in tracks}
    missing = sorted(requested - found)
    if missing:
        raise RuntimeError("Unknown tracks: " + ", ".join(missing))
    return tracks


def parse_arguments():
    """Parse command-line options for a monitored regression run."""
    parser = argparse.ArgumentParser(
        description=(
            "Run trackgen fixtures sequentially with per-track timeouts, logs, "
            "and an incremental JSON report."
        ),
        epilog="""examples:
  %(prog)s --trackgen runtime/trackgen.exe --report-dir trackgen-report
  %(prog)s --trackgen runtime/trackgen.exe --report-dir trackgen-report --track road/brondehach
  %(prog)s --trackgen /opt/torcs/bin/trackgen --report-dir /tmp/trackgen-report --timeout 120
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--trackgen",
        required=True,
        type=pathlib.Path,
        help="path to the trackgen executable",
    )
    parser.add_argument(
        "--test-root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent,
        help="fixture root containing source/ and generated/ (default: script directory)",
    )
    parser.add_argument(
        "--report-dir",
        required=True,
        type=pathlib.Path,
        help="directory for report.json and per-track output logs",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="maximum seconds allowed per track (default: %(default)s)",
    )
    parser.add_argument(
        "--track",
        action="append",
        default=[],
        metavar="CATEGORY/NAME",
        help="run one fixture; repeat to select multiple fixtures (default: all)",
    )
    return parser.parse_args()


def main():
    """Run selected fixtures and return a process exit status."""
    args = parse_arguments()
    trackgen = args.trackgen.resolve()
    test_root = args.test_root.resolve()
    source_root = test_root / "source"
    generated_root = test_root / "generated"
    report_directory = args.report_dir.resolve()

    if not trackgen.is_file():
        raise RuntimeError(f"Trackgen executable not found: {trackgen}")
    if not source_root.is_dir():
        raise RuntimeError(f"Source directory not found: {source_root}")
    if not generated_root.is_dir():
        raise RuntimeError(f"Generated directory not found: {generated_root}")
    report_directory.mkdir(parents=True, exist_ok=True)

    tracks = find_tracks(source_root, args.track)
    started_utc = datetime.datetime.now(datetime.timezone.utc)
    report_path = report_directory / "report.json"
    report = {
        "startedUtc": started_utc.isoformat(),
        "updatedUtc": started_utc.isoformat(),
        "trackgen": str(trackgen),
        "testRoot": str(test_root),
        "timeoutSeconds": args.timeout,
        "results": [],
    }
    write_report(report_path, report)
    print(f"REPORT {report_path}", flush=True)
    print(f"TRACKS {len(tracks)} TIMEOUT_SECONDS {args.timeout:g}", flush=True)

    for index, (label, input_directory) in enumerate(tracks, start=1):
        category, name = label.split("/", 1)
        output_directory = generated_root / category / name
        output_directory.mkdir(parents=True, exist_ok=True)
        log_prefix = f"{index:02d}-{category}-{name}"
        stdout_path = report_directory / f"{log_prefix}.stdout.log"
        stderr_path = report_directory / f"{log_prefix}.stderr.log"
        started = datetime.datetime.now(datetime.timezone.utc)
        result = {
            "index": index,
            "track": label,
            "status": "running",
            "startedUtc": started.isoformat(),
            "finishedUtc": None,
            "durationSeconds": None,
            "exitCode": None,
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            "error": None,
        }
        report["results"].append(result)
        report["updatedUtc"] = started.isoformat()
        write_report(report_path, report)
        print(f"START {index}/{len(tracks)} {label} {result['startedUtc']}", flush=True)

        command = [
            str(trackgen),
            "-q",
            "-c",
            category,
            "-n",
            name,
            "-i",
            str(input_directory),
            "-o",
            str(output_directory),
            "-a",
        ]
        start_time = time.monotonic()
        try:
            with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_file:
                with stderr_path.open("w", encoding="utf-8", errors="replace") as stderr_file:
                    completed = subprocess.run(
                        command,
                        cwd=trackgen.parent,
                        stdin=subprocess.DEVNULL,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        timeout=args.timeout,
                        check=False,
                    )
            result["exitCode"] = completed.returncode
            result["status"] = "passed" if completed.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            result["status"] = "timed_out"
        except OSError as error:
            result["status"] = "launch_failed"
            result["error"] = str(error)

        finished = datetime.datetime.now(datetime.timezone.utc)
        result["finishedUtc"] = finished.isoformat()
        result["durationSeconds"] = round(time.monotonic() - start_time, 3)
        report["updatedUtc"] = finished.isoformat()
        write_report(report_path, report)
        print(
            f"END   {index}/{len(tracks)} {label} {result['status']} "
            f"{result['durationSeconds']:.3f}s exit={result['exitCode']}",
            flush=True,
        )

    report["totalSeconds"] = round(
        (datetime.datetime.now(datetime.timezone.utc) - started_utc).total_seconds(), 3
    )
    report["summary"] = {
        status: sum(result["status"] == status for result in report["results"])
        for status in ("passed", "failed", "timed_out", "launch_failed")
    }
    report["updatedUtc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    write_report(report_path, report)
    summary = report["summary"]
    print(
        "SUMMARY "
        + " ".join(f"{status}={summary[status]}" for status in summary)
        + f" total_seconds={report['totalSeconds']:.3f}",
        flush=True,
    )
    return 0 if summary["failed"] == summary["timed_out"] == summary["launch_failed"] == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
