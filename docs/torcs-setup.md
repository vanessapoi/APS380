# TORCS 1.3.10 source setup

## Provenance and storage

The local download is `torcs-1.3.10.tar.bz2`, obtained from SourceForge's TORCS `all-in-one/1.3.10` release directory. The download location was recovered from the file's macOS download metadata on 2026-10-20.

- Release archive: https://sourceforge.net/projects/torcs/files/all-in-one/1.3.10/torcs-1.3.10.tar.bz2/download
- SHA-256: `a1d41035fe62a7e8db0191f13615e7ca68945449f8bf6a2161d17aff2ffe8a2b`

This checksum fingerprints the supplied download; it is not an independently verified upstream signature. The package is approximately 816 MB compressed / 2.4 GB extracted, including approximately 2 GB of game assets. The complete extracted distribution is tracked in Git, including source, assets, bundled dependencies and tests. A fresh clone already contains it; no Git LFS or separate asset download is required.

## Clone and collaborate

Open `APS380.code-workspace` after cloning. Edit `external/torcs-1.3.10/` directly and commit changes on a feature branch for team review. This is the canonical working copy; the Downloads copy is separate and should not be used for ongoing project edits.

The full upstream distribution is preserved, including per-directory license notices. OS metadata, Python environments/caches and new local compiler output are ignored. Upstream files included in the initial import remain tracked even if a build-output ignore pattern matches their names.

The workspace disables automatic CMake configuration: TORCS documents an Autotools/Make build on Linux and a Visual Studio solution on Windows. Its bundled Google Test directory is not the simulator's build root. Only the large game asset directory is excluded from default searches and file watching; simulator source is searchable.

## Optional archive verification and recovery

Normal clones do not need the setup script. To verify the original archive with Python 3.9 or newer:

```bash
python3 scripts/setup_torcs.py --archive ~/Downloads/torcs-1.3.10.tar.bz2 --verify-only
```

The script can install the original distribution only when `external/torcs-1.3.10/` is absent. It refuses to overwrite existing source changes. Prefer Git restore/revert workflows for tracked files; do not replace a modified working tree with the upstream archive. Original Downloads files have been retained.

## Build and integration status

Source installation is not a successful build. Follow the extracted `README` for platform dependencies, `./configure` / Make on Linux, or `TORCS.sln` on Windows. Some upstream instructions still name version 1.3.9; use the installed 1.3.10 directory. An experimental Apple Silicon build now compiles and opens the main menu; see [Mac build instructions and validation limits](torcs-macos.md). Racing and live telemetry remain unvalidated on Mac.

No simulator build, G29 setup, live telemetry exporter, Python simulator bridge or hardware control is added by this setup. The existing Python pipeline remains independent; see its README and PROJECT_CONTEXT.md for implemented behaviour and planned work.

Keep upstream `COPYING` and per-directory notices intact. The upstream README identifies GPL/Free Art licensed content and some artwork with separate non-free terms. TORCS modifications inside `external/torcs-1.3.10/` are version-controlled alongside the Python project; commit and push them to share with the team.
