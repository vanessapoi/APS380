# /***************************************************************************
#     file                 : track_loader_probe.py
#     created              : 25 September 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#  ***************************************************************************/
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License, version 2 or any later version.

"""Windows x64 development-build probe. Layouts come from the DLL's matching PDB.

Do not approximate runtime geometry using the Python analytical sampler: the
legacy large-radius tracks can depend on the loader's floating-point rounding.
"""

import ctypes as C
import os
import re
from pathlib import Path
from typing import Any

import numpy as np


class SymbolInfo(C.Structure):
    _fields_ = [("size", C.c_uint32), ("type_index", C.c_uint32), ("reserved", C.c_uint64 * 2),
                ("index", C.c_uint32), ("symbol_size", C.c_uint32), ("module", C.c_uint64),
                ("flags", C.c_uint32), ("value", C.c_uint64), ("address", C.c_uint64),
                ("register", C.c_uint32), ("scope", C.c_uint32), ("tag", C.c_uint32),
                ("name_len", C.c_uint32), ("max_name_len", C.c_uint32), ("name", C.c_char * 1)]


class Symbols:
    def __init__(self, dll: Path, search: Path):
        sdk = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits/10/Debuggers/x64/dbghelp.dll"
        self.api = C.WinDLL(str(sdk) if sdk.exists() else "dbghelp.dll")
        # Offline symbol session, independent of modules loaded into Python.
        self.process = C.c_void_p(id(self))
        self.api.SymInitializeW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_int]
        self.api.SymLoadModuleExW.argtypes = [C.c_void_p, C.c_void_p, C.c_wchar_p, C.c_wchar_p,
                                            C.c_uint64, C.c_uint32, C.c_void_p, C.c_uint32]
        self.api.SymLoadModuleExW.restype = C.c_uint64
        self.api.SymGetTypeFromName.argtypes = [C.c_void_p, C.c_uint64, C.c_char_p, C.c_void_p]
        self.api.SymGetTypeInfo.argtypes = [C.c_void_p, C.c_uint64, C.c_uint32, C.c_int, C.c_void_p]
        self.api.SymCleanup.argtypes = [C.c_void_p]
        # Exact symbols only; no symbol-server/network search path.
        self.api.SymSetOptions(0x10 | 0x400 | 0x200 | 0x800000)
        if not self.api.SymInitializeW(self.process, str(search), False):
            raise RuntimeError("Cannot initialize local debug symbols")
        self.base = self.api.SymLoadModuleExW(self.process, None, str(dll), None, 0x180000000, 0, None, 0)
        if not self.base:
            self.close()
            raise RuntimeError("Cannot load track DLL symbols")

    def close(self):
        self.api.SymCleanup(self.process)

    def info(self, index, kind, value_type: Any = C.c_uint32) -> Any:
        value = value_type()
        if not self.api.SymGetTypeInfo(self.process, self.base, index, kind, C.byref(value)):
            raise RuntimeError("Missing matching private PDB type information for the track DLL")
        return value.value

    def fields(self, name=None, index=None):
        if name is not None:
            buffer = C.create_string_buffer(4096)
            symbol = SymbolInfo.from_buffer(buffer)
            symbol.size, symbol.max_name_len = C.sizeof(SymbolInfo), 2000
            if not self.api.SymGetTypeFromName(self.process, self.base, name.encode(), buffer):
                raise RuntimeError(f"Matching track PDB does not expose {name}")
            index = symbol.type_index
        while self.info(index, 0) == 17:  # SymTagTypedef
            index = self.info(index, 4)
        count = self.info(index, 13)  # TI_GET_CHILDRENCOUNT
        children = (C.c_uint32 * (count + 2))()
        children[0] = count
        if not self.api.SymGetTypeInfo(self.process, self.base, index, 7, children):
            raise RuntimeError("Cannot enumerate PDB fields")
        result = {}
        kernel = C.WinDLL("kernel32.dll")
        kernel.LocalFree.argtypes = [C.c_void_p]
        for child in children[2:]:
            address = self.info(child, 1, C.c_void_p)
            field_name = C.wstring_at(address)
            kernel.LocalFree(address)
            result[field_name] = (self.info(child, 10), self.info(child, 4))
        return result


def relocated_entities(text: str, source_dir: Path, trial_dir: Path) -> str:
    """TORCS prefixes the input directory even to absolute entity names."""
    start = text.index("<params")

    def replace(match):
        target = (source_dir / match[2]).resolve()
        if "://" in match[2]:
            raise ValueError("Only local XML SYSTEM references are supported")
        relative = os.path.relpath(target, trial_dir).replace("\\", "/")
        return match[1] + relative + match[3]

    return re.sub(r"(\bSYSTEM\s+[\"'])([^\"']+)([\"'])", replace, text[:start]) + text[start:]


class TrackLoaderProbe:
    def __init__(self, runtime: Path, symbols: Path, source: Path, trial: Path, resource_dir: Path | None = None):
        if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
            raise RuntimeError("Runtime fitting requires Windows x64 Python and an x64 TORCS development build")
        self.source, self.trial = source, trial
        self.resource_dir = resource_dir or source.parent
        self.directory = os.add_dll_directory(str(runtime))
        self.tgf = C.CDLL(str(runtime / "tgf.dll"))
        self.tgf.GfInit()
        self.tgf.GfParmGetNum.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_float]
        self.tgf.GfParmGetNum.restype = C.c_float
        dll = runtime / "modules/track/track.dll"
        self.lib = C.CDLL(str(dll))
        pdb = Symbols(dll, symbols)
        try:
            track_fields = pdb.fields("tTrack")
            seg_fields = pdb.fields("trackSeg")
            pit_fields = pdb.fields(index=track_fields["pits"][1])
            # Validate scalar/array representation before interpreting any memory.
            for field, size in [("length", 4), ("vertex", 48), ("angle", 28), ("side", 16), ("name", 8)]:
                if pdb.info(seg_fields[field][1], 2, C.c_uint64) != size:
                    raise RuntimeError(f"Unsupported track ABI representation: {field}")
            self.track = {name: item[0] for name, item in track_fields.items()}
            self.seg = {name: item[0] for name, item in seg_fields.items()}
            self.pit_fields = {name: item[0] for name, item in pit_fields.items()}
        finally:
            pdb.close()

        class Mod(C.Structure):
            _fields_ = [("name", C.c_void_p), ("desc", C.c_void_p), ("init", C.c_void_p),
                        ("gf_id", C.c_int), ("index", C.c_int)]

        mod = Mod()
        if self.lib.track(C.byref(mod)):
            raise RuntimeError("Track module initialization failed")
        interface = (C.c_void_p * 9)()
        if C.CFUNCTYPE(C.c_int, C.c_int, C.c_void_p)(mod.init)(mod.index, interface):
            raise RuntimeError("Track interface initialization failed")
        self.build = C.CFUNCTYPE(C.c_void_p, C.c_char_p)(interface[0])
        self.shutdown = C.CFUNCTYPE(None)(interface[8])

    @staticmethod
    def read(pointer, offset, value_type: Any = C.c_float) -> Any:
        return value_type.from_address(pointer + offset).value

    def close(self):
        self.shutdown()
        self.directory.close()

    def starts_wall_run(self, segment, previous, side):
        wall = self.read(segment, self.seg["side"] + 8 * side, C.c_void_p)
        if not wall or self.read(wall, self.seg["style"], C.c_int) != 2:
            return False
        if not self.read(wall, self.seg["side"] + 8 * side, C.c_void_p):
            return False
        prior = self.read(previous, self.seg["side"] + 8 * side, C.c_void_p)
        if not prior or self.read(prior, self.seg["style"], C.c_int) != 2:
            return True
        # Same split conditions as simuv2 buildWalls (non-ring walls).
        vertex = self.seg["vertex"]
        displaced = any(abs(self.read(prior, vertex + 24 + v) - self.read(wall, vertex + v)) > .01 for v in (0, 12))
        return displaced or abs(self.read(prior, self.seg["height"]) - self.read(wall, self.seg["height"])) > .01

    def read_segment(self, segment):
        vertices = np.array(C.cast(segment + self.seg["vertex"], C.POINTER(C.c_float * 12)).contents).reshape(4, 3).astype(float)
        name = C.string_at(self.read(segment, self.seg["name"], C.c_void_p)).decode("utf-8")
        return {"name": name, "vertices": vertices, "outer_edges": self.outer_edges(segment), "start": vertices[:2].mean(axis=0),
                "end": vertices[2:].mean(axis=0), "angle": self.read(segment, self.seg["angle"]),
                "end_angle": self.read(segment, self.seg["angle"] + 4), "length": self.read(segment, self.seg["length"]),
                "station": self.read(segment, self.seg["lgfromstart"]),
                "race_info": self.read(segment, self.seg["raceInfo"], C.c_int)}

    def outer_edges(self, segment):
        edges = []
        for side, corner in ((0, 1), (1, 0)):
            node = segment
            following = self.read(node, self.seg["side"]+side*8, C.c_void_p)
            while following:
                node = following
                following = self.read(node, self.seg["side"]+side*8, C.c_void_p)
            edges.append([[self.read(node, self.seg["vertex"]+vertex*12+axis*4) for axis in range(3)]
                          for vertex in (corner, corner+2)])
        return np.array(edges)

    def build_track(self, text):
        self.trial.write_text(relocated_entities(text, self.resource_dir, self.trial.parent), encoding="utf-8", newline="")
        track = self.build(self.trial.as_posix().encode("utf-8"))
        if not track:
            raise RuntimeError("Track loader returned no track")
        count = self.read(track, self.track["nseg"], C.c_int)
        if not 0 < count < 1_000_000:
            raise RuntimeError("Invalid loaded segment count")
        segment = self.read(track, self.track["seg"], C.c_void_p)
        return track, count, segment

    def midpoint(self, segment, start_vertex):
        vertex = self.seg["vertex"] + start_vertex*12
        pair = np.array([[self.read(segment, vertex + side*12 + axis*4) for axis in range(3)] for side in range(2)])
        return pair.mean(axis=0)

    def endpoint(self, text, name):
        """Fitting fast path; full snapshots are still used for acceptance checks."""
        track, count, segment = self.build_track(text)
        first = self.read(segment, self.seg["next"], C.c_void_p)
        origin = self.midpoint(first, 0)
        endpoint_segment = self.indexed_endpoint(track, count, segment, name)
        if endpoint_segment is not None:
            return {"end": self.midpoint(endpoint_segment, 2)-origin,
                    "end_angle": self.read(endpoint_segment, self.seg["angle"] + 4)}
        return self.scanned_endpoint(segment, count, name, origin)

    def indexed_endpoint(self, track, count, last, name):
        """The v4 loader writes each XML section's first generated ID to params."""
        handle = self.read(track, self.track["params"], C.c_void_p)
        for label in (name+":radius-out", name):
            path = ("Main Track/Track Segments/"+label).encode("utf-8")
            index = self.tgf.GfParmGetNum(handle, path, b"id", None, -1)
            if not 0 <= index < count:
                continue
            node = last
            forward, backward = int(index)+1, count-1-int(index)
            direction = "next" if forward <= backward else "prev"
            for _ in range(min(forward, backward)):
                node = self.read(node, self.seg[direction], C.c_void_p)
            if C.string_at(self.read(node, self.seg["name"], C.c_void_p)) != label.encode("utf-8"):
                return None
            return self.last_named_subdivision(node, count, label.encode("utf-8"))
        return None

    def last_named_subdivision(self, node, count, label):
        for _ in range(count-1):
            following = self.read(node, self.seg["next"], C.c_void_p)
            if C.string_at(self.read(following, self.seg["name"], C.c_void_p)) != label:
                break
            node = following
        return node

    def scanned_endpoint(self, segment, count, name, origin):
        names = {label.encode("utf-8") for label in (name, name+":radius-in", name+":radius-turn", name+":radius-out")}
        result = None
        for _ in range(count):
            segment = self.read(segment, self.seg["next"], C.c_void_p)
            label = C.string_at(self.read(segment, self.seg["name"], C.c_void_p))
            if label in names:
                result = {"end": self.midpoint(segment, 2)-origin,
                          "end_angle": self.read(segment, self.seg["angle"] + 4)}
        if result is None:
            raise ValueError(f"Loaded segment not found: {name}")
        return result

    def load(self, text):
        track, count, segment = self.build_track(text)
        rows, wall_runs = [], 0
        for _ in range(count):
            segment = self.read(segment, self.seg["next"], C.c_void_p)
            previous = self.read(segment, self.seg["prev"], C.c_void_p)
            wall_runs += sum(self.starts_wall_run(segment, previous, side) for side in range(2))
            rows.append(self.read_segment(segment))
        origin = rows[0]["start"].copy()
        for row in rows:
            for key in ("vertices", "outer_edges", "start", "end"):
                row[key] -= origin
        return {"rows": rows, "origin": origin, "pit_count": self.read(track, self.track["pits"] + self.pit_fields["nMaxPits"], C.c_int),
                "pit_markers": self.pit_markers(track, origin),
                "extent": np.array([self.read(track, self.track["max"]+i*4)-self.read(track, self.track["min"]+i*4) for i in range(3)]),
                "wall_runs": wall_runs}

    def pit_markers(self, track, origin):
        result = {}
        pits = track + self.track["pits"]
        for name in ("pitEntry", "pitExit", "pitStart", "pitEnd"):
            pointer = self.read(pits, self.pit_fields[name], C.c_void_p)
            if pointer:
                row = self.read_segment(pointer)
                for key in ("vertices", "outer_edges", "start", "end"):
                    row[key] -= origin
                result[name] = row
        return result
