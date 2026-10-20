# /***************************************************************************
#     file                 : artifact_io.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""Shared file hashes and atomic JSON reports for staged authoring jobs.

Callers serialize writes to each destination (batch mutex/OS lock or one fitter
process per work directory). Atomic replacement prevents partial JSON reports.
"""

import hashlib
import json


def file_sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    temporary = path.with_suffix(path.suffix+".tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2)+"\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))
