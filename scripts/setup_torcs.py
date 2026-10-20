#!/usr/bin/env python3
"""Install the pinned TORCS distribution locally, without building or running it."""
import argparse
import hashlib
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

VERSION = "1.3.10"
NAME = "torcs-" + VERSION
ARCHIVE = NAME + ".tar.bz2"
URL = "https://sourceforge.net/projects/torcs/files/all-in-one/1.3.10/torcs-1.3.10.tar.bz2/download"
# Fingerprint of the user's downloaded archive; not an upstream signature.
SHA256 = "a1d41035fe62a7e8db0191f13615e7ca68945449f8bf6a2161d17aff2ffe8a2b"
ROOT = Path(__file__).resolve().parents[1]


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def unpack(archive, destination):
    with tarfile.open(str(archive), "r:bz2") as bundle:
        members = bundle.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != NAME:
                raise ValueError("Unexpected archive path: " + member.name)
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError("Unsupported archive member: " + member.name)
            if member.issym() or member.islnk():
                target = (destination / path.parent / member.linkname if member.issym()
                          else destination / member.linkname).resolve()
                if not target.is_relative_to((destination / NAME).resolve()):
                    raise ValueError("Archive link leaves source tree: " + member.name)
        # Only the exact pinned archive is accepted, after path/link checks above.
        bundle.extractall(str(destination), members=members)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use an existing archive instead of downloading")
    parser.add_argument("--verify-only", action="store_true", help="Check archive SHA-256 without extracting")
    args = parser.parse_args()
    external = ROOT / "external"
    target = external / NAME
    if target.exists() and not args.verify_only:
        parser.error(str(target) + " already exists; refusing to overwrite local changes")
    with tempfile.TemporaryDirectory(prefix="aps380-torcs-") as temporary:
        archive = args.archive.expanduser().resolve() if args.archive else Path(temporary) / ARCHIVE
        if not args.archive:
            print("Downloading " + URL, flush=True)
            with urllib.request.urlopen(URL, timeout=60) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        if checksum(archive) != SHA256:
            raise ValueError("Archive SHA-256 mismatch; nothing was installed")
        print("Verified SHA-256: " + SHA256, flush=True)
        if args.verify_only:
            return
        external.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".torcs-", dir=str(external)) as staging:
            unpack(archive, Path(staging))
            (Path(staging) / NAME).rename(target)
        print("Source installed at " + str(target))
        print("No build or simulator execution was performed.")


if __name__ == "__main__":
    main()
