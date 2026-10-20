#!/usr/bin/env python3
# Copyright (C) 2026 by Bernhard Wymann <berniw@bluewin.ch>
# GPL version 2 or (at your option) any later version.
"""Process-level check of real DLL construction/shutdown before race initialization.

This intentionally does not supply fake track pointers or unsupported callback
indices. Run in a disposable process: the registration descriptors remain owned
by the loaded module/process. This is an access-safety test, not a heap-leak count.
"""
import ctypes
import _ctypes
import os
from pathlib import Path


class ModInfo(ctypes.Structure):
    _fields_ = [("name", ctypes.c_void_p), ("description", ctypes.c_void_p),
                ("initialize", ctypes.c_void_p), ("framework", ctypes.c_uint),
                ("index", ctypes.c_int), ("priority", ctypes.c_int), ("magic", ctypes.c_int)]


class RobotInterface(ctypes.Structure):
    _fields_ = [(name, ctypes.c_void_p) for name in
                 ("track", "race", "end", "drive", "pit", "shutdown")] + [("index", ctypes.c_int)]


def require_callback(pointer, name, index):
    if not pointer:
        raise RuntimeError(f"Missing {name} callback for bot {index}")
    return pointer


def main():
    runtime = Path(__file__).resolve().parents[4]/"runtime"
    with os.add_dll_directory(str(runtime)):
        module = ctypes.CDLL(str(runtime/"drivers"/"olethros"/"olethros.dll"))
        entries = (ModInfo*10)()
        module.olethros.argtypes = [ctypes.POINTER(ModInfo)]
        module.olethros.restype = ctypes.c_int
        if module.olethros(entries) != 0:
            raise RuntimeError("Module registration failed")
        initialize = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
        shutdown = ctypes.CFUNCTYPE(None, ctypes.c_int)
        for cycle in range(1000):
            interfaces = []
            for index in range(10):
                interface = RobotInterface()
                callback = require_callback(entries[index].initialize, "initialize", index)
                if initialize(callback)(index, ctypes.byref(interface)) != 0:
                    raise RuntimeError("Interface initialization failed")
                interfaces.append(interface)
            # Same sequential teardown contract as the race engine. Also
            # exercise distinct cache-independent bot slots before a race starts.
            for index, interface in enumerate(interfaces):
                shutdown(require_callback(interface.shutdown, "shutdown", index))(index)
        # Rejected car setups may leave initialized interfaces outside the
        # engine's successful-car shutdown list. Module teardown owns them.
        for index in range(10):
            interface = RobotInterface()
            callback = require_callback(entries[index].initialize, "initialize", index)
            if initialize(callback)(index, ctypes.byref(interface)) != 0:
                raise RuntimeError("Interface initialization failed")
        _ctypes.FreeLibrary(module._handle)
    print("Passed: 1000 ten-driver construction/shutdown cycles and module unload with unclaimed slots")


if __name__ == "__main__":
    main()
