#!/usr/bin/env python3

##############################################################################
#
#    file                 : compare_ac.py
#    created              : Wed Aug 12 2026
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

"""Compare generated trackgen AC files with their reviewed references."""

import argparse
import hashlib
import itertools
import json
import pathlib
import sys


def file_digest(path):
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_files(root, requested_tracks):
    """Return AC paths under selected category/name fixture directories."""
    requested = set(requested_tracks)
    files = {}
    found_tracks = set()
    for path in sorted(root.rglob("*.ac")):
        relative_path = path.relative_to(root)
        if len(relative_path.parts) < 3:
            continue
        track = pathlib.PurePath(*relative_path.parts[:2]).as_posix()
        if not requested or track in requested:
            files[relative_path.as_posix()] = path
            found_tracks.add(track)
    return files, found_tracks


def files_equal(source_path, generated_path, strict=False):
    """Compare bytes, optionally treating CRLF and LF as the same line ending.

    Binary line iteration preserves lone CRs, other whitespace, and a missing
    final newline. Normalization is in memory; neither file is rewritten.
    """
    with source_path.open("rb") as source, generated_path.open("rb") as generated:
        for first, second in itertools.zip_longest(source, generated):
            if first is None or second is None:
                return False
            if not strict:
                first = first.replace(b"\r\n", b"\n")
                second = second.replace(b"\r\n", b"\n")
            if first != second:
                return False
    return True


def compare_files(source_root, generated_root, requested_tracks, strict=False):
    """Compare selected AC files and return per-file results."""
    source_files, source_tracks = select_files(source_root, requested_tracks)
    generated_files, unused_generated_tracks = select_files(
        generated_root, requested_tracks
    )
    missing_tracks = sorted(set(requested_tracks) - source_tracks)
    if missing_tracks:
        raise RuntimeError("Unknown tracks: " + ", ".join(missing_tracks))
    if not source_files:
        raise RuntimeError("No reference AC files found")

    results = []
    for relative_path in sorted(source_files.keys() | generated_files.keys()):
        source_path = source_files.get(relative_path)
        generated_path = generated_files.get(relative_path)
        if source_path is None:
            results.append({
                "file": relative_path,
                "status": "extra",
                "referenceSha256": None,
                "generatedSha256": file_digest(generated_path),
            })
            continue
        if generated_path is None:
            results.append({
                "file": relative_path,
                "status": "missing",
                "referenceSha256": file_digest(source_path),
                "generatedSha256": None,
            })
            continue

        reference_digest = file_digest(source_path)
        generated_digest = file_digest(generated_path)
        equal = files_equal(source_path, generated_path, strict)
        results.append({
            "file": relative_path,
            "status": "equal" if equal else "changed",
            "referenceSha256": reference_digest,
            "generatedSha256": generated_digest,
            "lineEndingsOnly": equal and reference_digest != generated_digest,
        })
    return results


def parse_arguments():
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Compare generated trackgen AC files with references, treating CRLF as LF."
    )
    parser.add_argument(
        "--test-root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent,
        help="fixture root containing source/ and generated/ (default: script directory)",
    )
    parser.add_argument(
        "--report",
        type=pathlib.Path,
        help="optional JSON report path",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="require byte-for-byte equality, including line endings",
    )
    parser.add_argument(
        "--track",
        action="append",
        default=[],
        metavar="CATEGORY/NAME",
        help="compare one fixture; repeat to select multiple fixtures (default: all)",
    )
    return parser.parse_args()


def main():
    """Compare selected fixtures and return a process exit status."""
    args = parse_arguments()
    test_root = args.test_root.resolve()
    source_root = test_root / "source"
    generated_root = test_root / "generated"
    if not source_root.is_dir():
        raise RuntimeError(f"Source directory not found: {source_root}")
    if not generated_root.is_dir():
        raise RuntimeError(f"Generated directory not found: {generated_root}")

    results = compare_files(source_root, generated_root, args.track, args.strict)
    summary = {
        status: sum(result["status"] == status for result in results)
        for status in ("equal", "changed", "missing", "extra")
    }
    line_ending_only_files = sum(result.get("lineEndingsOnly", False) for result in results)
    report = {
        "testRoot": str(test_root),
        "comparison": "binary" if args.strict else "crlf-to-lf",
        "lineEndingOnlyFiles": line_ending_only_files,
        "results": results,
        "summary": summary,
    }
    if args.report:
        report_path = args.report.resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    for result in results:
        if result["status"] != "equal":
            print(f"{result['status'].upper():7} {result['file']}")
    print("SUMMARY " + " ".join(f"{key}={value}" for key, value in summary.items()))
    print(f"LINE_ENDINGS_ONLY {line_ending_only_files}")
    return 0 if summary["changed"] == summary["missing"] == summary["extra"] == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
