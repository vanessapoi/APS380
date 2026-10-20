# file: brain_state.py; created: September 2026
# Copyright (C) 2026 by Bernhard Wymann <berniw@bluewin.ch>
# This program is free software under the GNU General Public License,
# version 2 or (at your option) any later version.
"""Transactional brain isolation for serial Windows race tests, never driver policy."""
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def local_torcs_dir() -> Path:
    if os.name != "nt":
        raise RuntimeError("This process runner targets Windows wtorcs.exe")
    # Match the Windows application; changing LOCALAPPDATA alone does not redirect it.
    buffer = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x1C, None, 0, buffer) != 0:
        raise RuntimeError("Cannot resolve TORCS local application directory")
    return Path(buffer.value)/"torcs"


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@contextlib.contextmanager
def exclusive_session(directory):
    """OS-held lock survives no process: no stale PID-file guessing on recovery.

    The lock serializes runners; the process check rejects already running TORCS.
    Do not launch an interactive race until this context has restored the brain.
    """
    import msvcrt
    output = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq wtorcs.exe", "/FO", "CSV", "/NH"], text=True)
    if '"wtorcs.exe"' in output.lower():
        raise RuntimeError("Close TORCS before running or recovering driver tests")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/"olethros-regression.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0"); handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Another Olethros runner owns the brain-isolation lock") from exc
        try:
            yield
        finally:
            handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def recover_brain(journal):
    """Recover only the adjacent, named brain after validating the saved digest.

    The journal is written/fsynced before the original is moved. Recovery is
    idempotent if interrupted before the move or after the restoration rename.
    Unexpected contents are preserved and reported, never guessed away.
    """
    journal = Path(journal)
    try:
        data = json.loads(journal.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a journal object")
        name, digest = data["name"], data["original_sha256"]
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ValueError("invalid adjacent brain name")
        if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or
                                   any(c not in "0123456789abcdef" for c in digest)):
            raise ValueError("invalid original digest")
        brain = journal.with_name(name)
        if journal != brain.with_name(brain.name+".regression.json"):
            raise ValueError("journal name does not match brain")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"Invalid or unreadable brain recovery journal '{journal}'; "
                           "preserve the journal, brain and backup for inspection") from exc
    backup = brain.with_name(brain.name+".regression-backup")
    if data["original_sha256"] is not None:
        if backup.exists():
            if fingerprint(backup) != data["original_sha256"]:
                raise RuntimeError(f"Brain backup failed its hash check: {backup}")
            os.replace(backup, brain)
        elif fingerprint(brain) != data["original_sha256"]:
            raise RuntimeError(f"Original brain unavailable; preserve journal: {journal}")
    else:
        brain.unlink(missing_ok=True)
    if fingerprint(brain) != data["original_sha256"]:
        raise RuntimeError("Brain restoration verification failed")
    journal.unlink()


def publish_journal(journal, report):
    """Publish complete, flushed metadata before moving any brain (Windows runner)."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=journal.parent,
                                         prefix=journal.name+".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle)
            handle.flush()
            os.fsync(handle.fileno())
        # Same-directory rename is atomic and refuses an existing destination on
        # Windows. The caller also holds the runner's exclusive-session lock.
        os.rename(temporary, journal)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class BrainState:
    def __init__(self, brain, mode):
        if mode not in ("clean", "persisted"):
            raise ValueError(mode)
        self.brain = Path(brain)
        self.mode = mode
        self.journal = self.brain.with_name(self.brain.name+".regression.json")
        self.backup = self.brain.with_name(self.brain.name+".regression-backup")
        self.report = {}

    def __enter__(self):
        self.brain.parent.mkdir(parents=True, exist_ok=True)
        if self.journal.exists() or self.backup.exists():
            raise RuntimeError(f"Recover the interrupted test before proceeding: {self.journal}")
        digest = fingerprint(self.brain)
        if self.mode == "persisted" and digest is None:
            raise RuntimeError(f"Persisted-state test requires an existing brain: {self.brain}")
        self.report = {"name": self.brain.name, "mode": self.mode, "original_sha256": digest}
        publish_journal(self.journal, self.report)
        try:
            if digest is not None:
                os.replace(self.brain, self.backup)
                if self.mode == "persisted":
                    shutil.copy2(self.backup, self.brain)
            return self
        except BaseException:
            recover_brain(self.journal)
            raise

    def __exit__(self, *error):
        recover_brain(self.journal)
        self.report["restored_sha256"] = fingerprint(self.brain)
