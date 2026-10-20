# /***************************************************************************
#
#     file                 : trackgen.py
#     created              : 27 Apr 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass


def installed_track_xml(runtime_dir: pathlib.Path, category: str, name: str) -> pathlib.Path:
    return runtime_dir / "tracks" / category / name / f"{name}.xml"


def trackgen_executable(runtime_dir: pathlib.Path) -> pathlib.Path:
    exe = runtime_dir / "trackgen.exe"
    if exe.exists():
        return exe
    exe = runtime_dir / "trackgen"
    if exe.exists():
        return exe
    raise RuntimeError(f"trackgen executable not found in runtime directory: {runtime_dir}")


def lock_path_for_track(runtime_dir: pathlib.Path, category: str, name: str) -> pathlib.Path:
    return runtime_dir / f".trackgen-{category}-{name}.lock"


def acquire_file_lock(lock_path: pathlib.Path, timeout_s: float = 120.0, stale_s: float = 900.0) -> None:
    deadline = time.perf_counter() + timeout_s
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
            finally:
                os.close(fd)
            return
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > stale_s:
                    lock_path.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.perf_counter() >= deadline:
                raise RuntimeError(f"Timed out waiting for trackgen XML lock: {lock_path}") from None
            time.sleep(0.2)


def release_file_lock(lock_path: pathlib.Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


@contextmanager
def trackgen_xml_lock(runtime_dir: pathlib.Path, category: str, name: str) -> Iterator[None]:
    lock_path = lock_path_for_track(runtime_dir, category, name)
    acquire_file_lock(lock_path)
    try:
        yield
    finally:
        release_file_lock(lock_path)


def parse_trackgen_output(out: str) -> dict:
    def parse_num(label: str) -> float:
        m = re.search(rf"^{re.escape(label)}\s*=\s*([-+0-9.eE]+)", out, re.MULTILINE)
        if not m:
            raise RuntimeError(f"Could not parse '{label}' from trackgen output")
        return float(m.group(1))

    def parse_delta_ang_deg() -> float:
        m = re.search(r"^Delta Ang\s*=\s*[-+0-9.eE]+\s*\(([-+0-9.eE]+)\)", out, re.MULTILINE)
        if m:
            return float(m.group(1))
        return parse_num("Delta Ang")

    return {
        "delta_x": parse_num("Delta X"),
        "delta_y": parse_num("Delta Y"),
        "delta_z": parse_num("Delta Z"),
        "delta_ang_deg": parse_delta_ang_deg(),
        "length": parse_num("length"),
        "pits": int(round(parse_num("pits"))),
    }


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class TrackgenStats:
    calls: int = 0
    seconds: float = 0.0
    cache_hits: int = 0


class TrackgenRunner:
    """Run ``trackgen -z`` while safely swapping a candidate XML into runtime.

    TORCS ``trackgen`` resolves track XML by category/name from the runtime tree.
    This runner serializes temporary live-XML replacement with the same lock used
    by other tools, restores the previous live XML, and optionally caches metrics
    by candidate XML hash.
    """

    def __init__(
        self,
        runtime_dir: pathlib.Path,
        timeout_s: float | None = None,
        cache: dict[tuple[str, str, str], tuple[dict, str]] | None = None,
        stats: TrackgenStats | None = None,
        allow_missing_live_xml: bool = False,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.runtime_dir = runtime_dir
        self.timeout_s = timeout_s
        self.cache = cache
        self.stats = stats or TrackgenStats()
        self.allow_missing_live_xml = allow_missing_live_xml
        self.log = log

    def cache_key_for(self, category: str, name: str, under_test: pathlib.Path) -> tuple[str, str, str] | None:
        if self.cache is not None:
            if not under_test.exists():
                raise RuntimeError(f"Track XML under test not found: {under_test}")
            return category, name, bytes_sha256(under_test.read_bytes())
        return None

    def cached_result(self, cache_key: tuple[str, str, str] | None) -> tuple[dict, str] | None:
        if cache_key is not None and self.cache is not None and cache_key in self.cache:
            self.stats.cache_hits += 1
            metrics, out = self.cache[cache_key]
            return dict(metrics), out
        return None

    def store_cache(self, cache_key: tuple[str, str, str] | None, metrics: dict, out: str) -> None:
        if cache_key is not None and self.cache is not None:
            self.cache[cache_key] = (dict(metrics), out)

    def execute_trackgen(self, cmd: list[str], cache_key: tuple[str, str, str] | None) -> tuple[dict, str]:
        start = time.perf_counter()
        self.stats.calls += 1
        if self.log is not None:
            self.log(f"trackgen #{self.stats.calls}: start")
        proc = subprocess.run(
            cmd,
            cwd=str(self.runtime_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=self.timeout_s,
        )
        elapsed = time.perf_counter() - start
        self.stats.seconds += elapsed
        if proc.returncode != 0:
            raise RuntimeError(f"trackgen failed ({proc.returncode})\n{proc.stdout}")
        metrics = parse_trackgen_output(proc.stdout)
        if self.log is not None:
            self.log(
                f"trackgen #{self.stats.calls}: {elapsed:.3f}s "
                f"dx={metrics['delta_x']:.6f} dy={metrics['delta_y']:.6f} "
                f"ang={metrics['delta_ang_deg']:.6f}"
            )
        self.store_cache(cache_key, metrics, proc.stdout)
        return metrics, proc.stdout

    def restore_live_track_xml(self, live_track_xml: pathlib.Path, backup_xml: pathlib.Path, had_live_xml: bool) -> None:
        if backup_xml.exists():
            shutil.copyfile(backup_xml, live_track_xml)
        elif not had_live_xml:
            live_track_xml.unlink(missing_ok=True)

    def run_with_temporary_live_xml(
        self,
        live_track_xml: pathlib.Path,
        under_test: pathlib.Path,
        cmd: list[str],
        cache_key: tuple[str, str, str] | None,
    ) -> tuple[dict, str]:
        had_live_xml = live_track_xml.exists()
        if not had_live_xml and not self.allow_missing_live_xml:
            raise RuntimeError(f"Installed runtime track XML not found: {live_track_xml}")

        backup_dir = pathlib.Path(tempfile.mkdtemp(prefix="trackgen_z_", dir=str(self.runtime_dir)))
        backup_xml = backup_dir / live_track_xml.name
        try:
            live_track_xml.parent.mkdir(parents=True, exist_ok=True)
            if had_live_xml:
                shutil.copyfile(live_track_xml, backup_xml)
            shutil.copyfile(under_test, live_track_xml)
            return self.execute_trackgen(cmd, cache_key)
        finally:
            self.restore_live_track_xml(live_track_xml, backup_xml, had_live_xml)
            shutil.rmtree(backup_dir, ignore_errors=True)

    def run_z(self, category: str, name: str, track_xml_under_test: pathlib.Path | None = None) -> tuple[dict, str]:
        exe = trackgen_executable(self.runtime_dir)
        cmd = [str(exe), "-c", category, "-n", name, "-z"]
        live_track_xml = installed_track_xml(self.runtime_dir, category, name)
        under_test = track_xml_under_test.resolve() if track_xml_under_test is not None else live_track_xml.resolve()
        live_resolved = live_track_xml.resolve()

        cache_key = self.cache_key_for(category, name, under_test)
        cached = self.cached_result(cache_key)
        if cached is not None:
            return cached

        if under_test == live_resolved:
            return self.execute_trackgen(cmd, cache_key)

        if not under_test.exists():
            raise RuntimeError(f"Track XML under test not found: {under_test}")

        with trackgen_xml_lock(self.runtime_dir, category, name):
            return self.run_with_temporary_live_xml(live_track_xml, under_test, cmd, cache_key)


def run_trackgen_z(runtime_dir: pathlib.Path, category: str, name: str, track_xml_under_test: pathlib.Path | None = None) -> tuple[dict, str]:
    return TrackgenRunner(runtime_dir).run_z(category, name, track_xml_under_test)
