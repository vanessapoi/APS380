# Experimental native TORCS build on Apple Silicon

## Verified checkpoint, October 27, 2026

On this Apple Silicon Mac running macOS 26.6, our modified TORCS 1.3.10 source
compiled, installed locally and opened a 640×480 window. The operator confirmed
that the TORCS main menu was visible. This is a native arm64 executable, not a
Windows VM. No instrument or battery is connected by these build/launch tools.

A subsequent native console run completed the Model 3 reference/AI course and
passed all 11 existing protocol gates; see the AI instructions below. This does
**not** validate keyboard driving, G29 steering/pedals/force feedback, frame rate,
audio quality, live UDP/HUD feedback, or live current playback. The current publisher and HUD network implementation
remain Windows-specific; their non-Windows implementations are disabled. Native
EV CSV recording and effective-configuration/model auditing passed for that
autonomous console run. The graphical AI race also started successfully and produced driver/EV telemetry;
its full course completion has not yet been independently checked. Existing Windows launch scripts still launch the Windows executable.

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

## Model 3 reference with autonomous driver

The Mac runner reuses `configure_tesla.py`, the same frozen vehicle profile,
`prepare_profile` and `validate_protocol` as the Windows workflow. Those shared
helpers now accept explicit runtime/profile/driver paths; Windows defaults are
preserved. No model parameters or controller gains were changed for Mac.
The visible car remains a TORCS proxy body, not a Tesla 3D asset or validated
Tesla digital twin. The driver is deterministic feedback control, not a learned
self-driving system.

Use Python 3.10+ for this project's validation modules. Python 3.13 was installed
on this Mac; the Command Line Tools' Python 3.9 remains suitable for the simple
build helper but cannot import the full project. Prepare the ignored environment:

```sh
brew install python@3.13
/opt/homebrew/bin/python3.13 -m venv .local/torcs-macos/venv
.local/torcs-macos/venv/bin/python -m pip install -r aps380_torcs_starter/requirements.txt
```

For the existing Python dashboard tests, Homebrew also needs
`brew install python-tk@3.13`; the autonomous simulator itself does not need Tk.

Run one automated console course (two laps, no graphics, 120-second wall timeout):

```sh
.local/torcs-macos/venv/bin/python scripts/macos/run_tesla_ai.py
```

Watch the AI in the graphical simulator:

```sh
open -a XQuartz
.local/torcs-macos/venv/bin/python scripts/macos/run_tesla_ai.py --visible
```

Choose **Race > Practice > New Race**. The selected driver is `aps380_ai`, using
`aps380-model3-rwd`; do not select the human driver. Console `-r` in the Unix entry
point deliberately runs without graphics, so the visible command opens the
prepared menu instead. Use a single console/visible race at a time: the native
recorder and generated runtime assets are shared. Starting a new race replaces
the visible session's driver log; use a new launcher session for separate captures.

Every invocation creates `.local/torcs-macos/ai-runs/<timestamp>/`. Console runs
preserve `driver.csv`, `drive.csv`, effective `drive.xml`, frozen profile,
`metadata.json` with binary hashes, `protocol.json`, simulator log and
`protocol.png`. Visible runs log the AI driver and native runtime telemetry, but
are not automatically postprocessed or declared a passing course.

The first checked Mac console run was `20261027_171745_346342`:

| Check | Observed result |
| --- | --- |
| Existing protocol gates | 11/11 passed |
| Distance / simulation duration | 4218.37 m / 442.08 s |
| Qualified 30 km/h hold | 13.96 s |
| Qualified 50 km/h hold | 12.00 s |
| Stationary hold | 6.00 s |
| Lift-off regeneration and isolated friction braking | Passed |
| Post-start contacts, damage and speed-jump gates | Passed |
| Net simulated pack energy | 557.784 Wh |

These describe this simulator run, not measured vehicle/battery performance.
A single successful Mac run does not establish statistical repeatability or
cross-platform numerical equivalence to Windows. The two portable setup fixture
tests run without TORCS or hardware:

```sh
.local/torcs-macos/venv/bin/python -m unittest discover -s scripts/macos -p 'test_*.py' -v
```

The 164 existing Python tests and two portable setup tests passed in the complete
Python 3.13 environment. The initial graphical race exposed a missing shared
sound-priority helper when legacy PLIB audio was excluded. That helper now lives
in common sound code so OpenAL also links it. An executable-level plugin loader
check catches this failure before race startup:

```sh
.local/torcs-macos/venv/bin/python scripts/macos/check_graphics.py
```

It uses the real simulator's `--check-graphics` path and does not start a window,
race or hardware connection. After the fix, the visible race produced over 1,600
AI samples, progressing through the speed-hold stages with zero damage at the
observed checkpoint. This is startup/ongoing-driving evidence, not a claim that
the graphical run completed every protocol gate.

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
