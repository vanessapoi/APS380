# TORCS 1.3.10 source setup

## Provenance and storage

The local download is `torcs-1.3.10.tar.bz2`, obtained from SourceForge's TORCS `all-in-one/1.3.10` release directory. The download location was recovered from the file's macOS download metadata on 2026-10-20.

- Release archive: https://sourceforge.net/projects/torcs/files/all-in-one/1.3.10/torcs-1.3.10.tar.bz2/download
- SHA-256: `a1d41035fe62a7e8db0191f13615e7ca68945449f8bf6a2161d17aff2ffe8a2b`

This checksum fingerprints the supplied download; it is not an independently verified upstream signature. The package is approximately 816 MB compressed / 2.4 GB extracted, including approximately 2 GB of game assets. Git tracks the setup code and documentation, not this large third-party distribution. A fresh clone must run setup to obtain it.

## Install locally

From the repository root, with Python 3.9 or newer:

```bash
python3 scripts/setup_torcs.py --archive ~/Downloads/torcs-1.3.10.tar.bz2
# Alternatively, download the archive:
python3 scripts/setup_torcs.py
```

The complete archive is extracted into `external/torcs-1.3.10/`. An existing directory is never overwritten. The original Downloads files are retained. To verify an archive without extracting:

```bash
python3 scripts/setup_torcs.py --archive ~/Downloads/torcs-1.3.10.tar.bz2 --verify-only
```

Open `APS380.code-workspace` in VS Code. Automatic CMake configuration is disabled: the distribution documents an Autotools/Make build on Linux and a Visual Studio solution on Windows. The external tree remains visible in Explorer but is excluded from default searches and file watching. Clear the search exclusion when inspecting upstream code.

## Build and integration status

Source installation is not a successful build. Follow the extracted `README` for platform dependencies, `./configure` / Make on Linux, or `TORCS.sln` on Windows. Some upstream instructions still name version 1.3.9; use the installed 1.3.10 directory. A native macOS build has not been validated here.

No simulator build, G29 setup, live telemetry exporter, Python simulator bridge or hardware control is added by this setup. The existing Python pipeline remains independent; see its README and PROJECT_CONTEXT.md for implemented behaviour and planned work.

Keep upstream `COPYING` and per-directory notices intact. The upstream README identifies GPL/Free Art licensed content and some artwork with separate non-free terms. Future TORCS modifications should be captured as reviewed patches or an intentional source fork; edits inside the ignored external tree are not backed up to GitHub.
