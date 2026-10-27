# Experimental native TORCS build on Apple Silicon

## Verified checkpoint, October 27, 2026

On this Apple Silicon Mac running macOS 26.6, our modified TORCS 1.3.10 source
compiled, installed locally and opened a 640×480 window. The operator confirmed
that the TORCS main menu was visible. This is a native arm64 executable, not a
Windows VM. No instrument or battery is connected by these build/launch tools.

This checkpoint does **not** validate a completed race, keyboard driving, G29
steering/pedals/force feedback, frame rate, audio quality, live UDP/HUD feedback,
or live current playback. The current publisher and HUD network implementation
remain Windows-specific; their non-Windows implementations are disabled. Native
CSV/EV code is included in the build but race recordings have not yet been checked
on Mac. Existing Windows launch scripts still launch the Windows executable.

The work is on `feat/torcs-macos-build`, separate from the pushed
`feat/bk8500-bench-replay` branch. Neither branch has been merged into main by this
build task. All generated dependencies, compiler output, installed assets and
personal configuration are under the ignored `.local/torcs-macos/` directory.

The native EV kernel test also passed all 18 checks. Checked dependency versions
were XQuartz 2.8.6, FreeGLUT 3.8.0, FreeALUT 1.1.0, OpenAL Soft 1.25.2,
libpng 1.6.59, libvorbis 1.3.7 and locally built PLIB 1.8.5. These are observed
versions, not a guarantee that every future Homebrew update will be compatible.

## Prerequisites

Xcode Command Line Tools and Homebrew are required. Install missing developer
tools with `xcode-select --install`; this Mac already had them.

```sh
brew install --cask xquartz
brew install freeglut freealut openal-soft libpng libvorbis pkgconf libxext libice libsm libxt libxrender libxmu
```

XQuartz installation requires an administrator password in your own Terminal.
Follow its installer instructions about logging out/in. It was installed and
running on display `:0` during verification. Start it before launching TORCS:

```sh
open -a XQuartz
```

Homebrew may download a large dependency chain, including Mesa and LLVM. Its
FreeGLUT links Mesa libGL. PLIB is not available as a Homebrew formula, so the
helper builds the official PLIB 1.8.5 release into the local dependency prefix.
No global PLIB installation or `sudo make install` is used.

## Build and launch from the repository root

```sh
python3 scripts/macos/build_torcs.py
open -a XQuartz
python3 scripts/macos/run_torcs.py
```

The build helper runs dependency preparation, configuration, serial compilation,
executable installation and asset installation. Individual stages are available:

```sh
python3 scripts/macos/build_torcs.py --stage dependencies
python3 scripts/macos/build_torcs.py --stage configure
python3 scripts/macos/build_torcs.py --stage build
python3 scripts/macos/build_torcs.py --stage install
```

Use `--stage configure` then `--stage build` and `--stage install` after editing
shared TORCS source: configure refreshes the isolated source copy. The helper
keeps an existing build tree, so removed/renamed files may require a new clean
local build rather than an incremental copy. Do not overwrite or replace the
canonical `external/torcs-1.3.10/` tree with an upstream download.

The launcher uses `.local/torcs-macos/user/` for configuration and results, leaving
`~/.torcs` alone. It runs the generated setup script for those local preferences,
sets the dynamic-library search path and uses DISPLAY (or the XQuartz launchd
value, falling back to `:0`). A different display may require explicitly setting
DISPLAY. It removes the live-telemetry environment variables for this isolated
bring-up. It never opens USB serial ports or operates the PSU/eLoad.

Build and launch logs used in the initial investigation are in
`.local/torcs-macos/`. The Python helpers print the precise log filename on
failure. A compiler warning does not necessarily indicate failure; check the
exit status. Some legacy install rules also print harmless missing `*.xml` glob
warnings for driver directories without those assets.

## Compatibility changes and rationale

- **SDK selection:** the default `xcrun` selection on this Mac returned the 27.0
  SDK, but Clang 21's linker rejected its library architecture metadata. Selecting
  installed `MacOSX26.5.sdk` passed an actual compile/link check. The helper selects
  a Command Line Tools SDK matching the OS major version when available, unless
  `--sdk /path/to/SDK` is explicitly supplied. It tests the compiler before building, without
  changing system SDK links, developer settings or shell profiles.
- **PLIB sound:** its legacy Carbon audio types are unavailable for modern 64-bit
  macOS. PLIB is built without SL/PW and unused PUI/network components. TORCS's
  existing OpenAL path is retained on Mac; selecting obsolete PLIB sound reports
  it unavailable instead of pretending to provide sound. Other platforms retain
  their existing backend selection and links.
- **PLIB graphics:** its original Mac code uses native CGL context checks. This
  build uses X11/GLX through FreeGLUT, so the local PLIB copy uses GL/GLX headers
  and context checks consistently. The missing `uint`/`ushort` typedef fix follows
  the small Apple compatibility change used in MacPorts.
- **GLU:** the XQuartz static `libGLU.a` is copied into the local prefix, resolving
  its GL calls against the same Mesa libGL as Homebrew FreeGLUT, rather than
  bringing in a second dynamic libGL through XQuartz's GLU dylib.
- **Plugin linking:** Darwin libraries/modules use `-dynamiclib` with dynamic
  lookup for host-provided symbols, while the Linux `-shared` rule remains the
  default elsewhere. All plugins built locally; a race's complete module load
  path still needs runtime testing.
- **Headers/API:** Mac font loading uses `machine/endian.h`; its legacy ALUT WAV
  function has a five-argument signature. Both adaptations are Apple-only.
- **APS380 AI driver:** a Unix Makefile builds the same deterministic driver
  source already used by its Visual Studio project. Driver configuration/race
  setup must be checked separately before claiming a functioning AI trial.
- **Serial Make:** the first `make -j4` attempt exposed a header-export ordering
  race. The repeatable TORCS build uses `make -j1`; PLIB can still build in parallel.

The initial build, installation and startup were tested step by step. The full
`python3 scripts/macos/build_torcs.py` command subsequently passed dependency
preparation, configuration, build and both installation stages end to end.
This checks recipe reproduction without claiming race validation. Existing Windows binaries
were not rebuilt in this Mac session, and Windows regression testing remains due.

## Source provenance

The TORCS source/assets already live in the repository; see [source setup](torcs-setup.md).
The additional official archive is
[PLIB 1.8.5](https://plib.sourceforge.net/dist/plib-1.8.5.tar.gz), SHA-256
`485b22bf6fdc0da067e34ead5e26f002b76326f6371e2ae006415dea6a380a32`.
The helper verifies that fingerprint before extracting. Upstream PLIB license
notices remain in its extracted local source/install.

References: [FreeGLUT macOS build notes](https://github.com/freeglut/freeglut/blob/master/README.macos),
[XQuartz](https://www.xquartz.org/),
[Homebrew FreeGLUT recipe](https://github.com/Homebrew/homebrew-core/blob/HEAD/Formula/f/freeglut.rb),
[MacPorts PLIB recipe](https://github.com/macports/macports-ports/blob/master/devel/plib/Portfile),
and [MacPorts typedef patch](https://github.com/macports/macports-ports/blob/master/devel/plib/files/patch-src_ssg_ssgLoadFLT.cxx.diff).
