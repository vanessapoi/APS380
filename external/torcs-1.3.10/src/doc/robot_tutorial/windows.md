# Getting Ready on Windows {#robot_tutorial_windows}

**Goal:** build your first robot, select it in Practice, and see it hold still.

## Before you start {#robot_tutorial_windows_before}

You need Visual Studio 2022 with the C++ tools and Windows SDK, and a working
TORCS development build with game data. To get started, use **Release / x64**.
Prepare the repository using `setup_win32.bat` and
`setup_win32-data-from-CVS.bat`, then build `TORCS.sln` with that configuration.
Confirm that `runtime/wtorcs.exe` launches normally.

Open PowerShell in the **TORCS source root**: the directory containing
`TORCS.sln` and `src/`. In a double-nested checkout this is `torcs/torcs/`.
Run the commands below from that directory.

## Copy your robot {#robot_tutorial_windows_copy}

```powershell
if (Test-Path src/drivers/tutorial1) { throw 'tutorial1 already exists; use your existing working copy' }
Copy-Item -Recurse src/doc/robot_tutorial/examples/chapter_1 src/drivers/tutorial1
```

If `src/drivers/tutorial1` already exists, use your existing copy. Keep the name
`tutorial1` for now. Edit files in this working copy, rather than the
documentation's reference copy.

## Build and install {#robot_tutorial_windows_build}

Use Microsoft's `vswhere` utility, included with the Visual Studio Installer,
to locate MSBuild automatically:

Copy this whole block once. It finds your installed build tool. You can use
this command without understanding every option yet.

```powershell
$vswhere = "${env:ProgramFiles(x86)}/Microsoft Visual Studio/Installer/vswhere.exe"
$msbuild = & $vswhere -latest -version '[17.0,18.0)' -products '*' `
    -requires Microsoft.Component.MSBuild Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -find 'MSBuild\Current\Bin\MSBuild.exe' | Select-Object -First 1
if (-not $msbuild) { throw 'Visual Studio 2022 with MSBuild and the C++ tools was not found' }
```

This finds a Visual Studio 2022 installation with the C++ tools, regardless of
edition or installation directory. See Microsoft's
[MSBuild discovery documentation](https://github.com/microsoft/vswhere/wiki/Find-MSBuild)
for details. Then build the stationary checkpoint:

```powershell
& $msbuild src/drivers/tutorial1/tutorial1.vcxproj /p:Configuration=Release /p:Platform=x64 /p:TutorialCheckpoint=skeleton
if ($LASTEXITCODE -ne 0) { throw 'Tutorial build failed' }
```

The project uses the headers and libraries from your TORCS build and installs
the driver into `runtime/drivers/tutorial1/` automatically.
Wait for the build to finish successfully before opening the game. If it
reports an error, use the help section below.

## See your robot in TORCS {#robot_tutorial_windows_practice}

```powershell
./runtime/wtorcs.exe
```

1. Open **Practice**.
2. Select the road track **CG Speedway number 1** (`g-track-1`).
3. Select **Tutorial 1** as the driver. It uses the `car1-stock1` car.
4. Start the session.

**Your car should stay still. That is success!** The skeleton deliberately
holds the brakes. You now know how to build a robot and get TORCS to load it.

**Next: [Chapter 1 — Make It Drive](chapter_1.md).** Come back to the short
rebuild instructions below when the chapter asks you to try the driving code.

## Rebuild after a change {#robot_tutorial_windows_rebuild}

Leave the Practice session and return to the menu. TORCS unloads the driver
when the session ends, so you can keep the game open. Then run this from the
source root in the same PowerShell session:

```powershell
& $msbuild src/drivers/tutorial1/tutorial1.vcxproj /p:Configuration=Release /p:Platform=x64 /p:TutorialCheckpoint=driving
if ($LASTEXITCODE -ne 0) { throw 'Tutorial build failed' }
```

If you opened a new PowerShell session, set `$msbuild` again as shown above.
This build selects `driving.cpp` instead of `skeleton.cpp`. Start a new Practice
session with the same driver and track; TORCS loads the rebuilt DLL. Use this
command again after each edit to `driving.cpp`.

[Continue making your robot drive](@ref robot_tutorial_1_driving_build).

## Continue with Chapter 2 {#robot_tutorial_windows_chapter_2}

From the source root, copy the new example into its own working directory:

```powershell
if (Test-Path src/drivers/tutorial2) { throw 'tutorial2 already exists; use your existing working copy' }
Copy-Item -Recurse src/doc/robot_tutorial/examples/chapter_2 src/drivers/tutorial2
```

If that directory already exists, use your existing copy. Leave the current
Practice session and return to the menu, then build and install:

```powershell
& $msbuild src/drivers/tutorial2/tutorial2.vcxproj /p:Configuration=Release /p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw 'Tutorial build failed' }
```

If you opened a new PowerShell session, run the MSBuild discovery block above
first. Select **Tutorial 2** on **CG Speedway number 1** in a new Practice session.
This example deliberately makes a small driving mistake at the start.
[Chapter 2 — Get Back on Track](chapter_2.md) explains what to watch for.

After edits to `recovery.cpp` or `practice.cpp`, save and use the same build command.
The Chapter 1 driver remains available as **Tutorial 1**.

## Continue with Chapter 3 {#robot_tutorial_windows_chapter_3}

From the source root, copy the new example into its own working directory:

```powershell
if (Test-Path src/drivers/tutorial3) { throw 'tutorial3 already exists; use your existing working copy' }
Copy-Item -Recurse src/doc/robot_tutorial/examples/chapter_3 src/drivers/tutorial3
```

If it already exists, use your working copy. Leave the current Practice session,
then build and install:

```powershell
& $msbuild src/drivers/tutorial3/tutorial3.vcxproj /p:Configuration=Release /p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw 'Tutorial build failed' }
```

If this is a new PowerShell session, run the MSBuild discovery block above first.
Select **Tutorial 3** on **CG Speedway number 1** in a new Practice session.
[Chapter 3 — Choose Your Speed](chapter_3.md) explains what to observe.
After changes to `speed.cpp` or `braking.cpp`, save and use the same build command.
The earlier drivers remain available for comparison.

## Continue with Chapter 4 {#robot_tutorial_windows_chapter_4}

From the source root, copy the steering example into its own working directory:

```powershell
if (Test-Path src/drivers/tutorial4) { throw 'tutorial4 already exists; use your existing working copy' }
Copy-Item -Recurse src/doc/robot_tutorial/examples/chapter_4 src/drivers/tutorial4
```

If it already exists, use your working copy. Leave the current Practice session,
then build and install:

```powershell
& $msbuild src/drivers/tutorial4/tutorial4.vcxproj /p:Configuration=Release /p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw 'Tutorial build failed' }
```

If this is a new PowerShell session, run the MSBuild discovery block above first.
Select **Tutorial 4** on **CG Speedway number 1** in a new Practice session.
[Chapter 4 — Steering and Trajectory](chapter_4.md) explains the comparison.
Edit `steering4.cpp` for lookahead experiments and `speed4.cpp` for later speed
experiments. Save and use the same build command after each change.

## Continue with Chapter 5 {#robot_tutorial_windows_chapter_5}

This chapter adds traffic decisions and a reference pace driver. Assemble a new
working folder from its files and the supplied Chapter 4 helper sources. From
the source root:

```powershell
if (Test-Path src/drivers/tutorial5) { throw 'tutorial5 already exists; use your existing working copy' }
Copy-Item -Recurse src/doc/robot_tutorial/examples/chapter_5 src/drivers/tutorial5
foreach ($helper in 'geometry4', 'steering4', 'speed4', 'braking4', 'recovery4') {
    Copy-Item "src/doc/robot_tutorial/examples/chapter_4/$helper.h" src/drivers/tutorial5/
    Copy-Item "src/doc/robot_tutorial/examples/chapter_4/$helper.cpp" src/drivers/tutorial5/
}
```

If the folder already exists, use your working copy. Copy the helpers from the
supplied examples so earlier experiments do not change this chapter's baseline.
The assembled folder contains everything needed to compile both modules.

Leave the current session, then build and install both drivers:

```powershell
& $msbuild src/drivers/tutorial5/tutorial5.vcxproj /p:Configuration=Release /p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw 'Tutorial 5 build failed' }
& $msbuild src/drivers/tutorial5/tutorial5.vcxproj /p:Configuration=Release /p:Platform=x64 /p:TutorialRobot=tutorial5pace
if ($LASTEXITCODE -ne 0) { throw 'Tutorial Pace build failed' }
```

In a new PowerShell session, run the MSBuild discovery block above first.
Follow [Chapter 5's Quick Race instructions](@ref robot_tutorial_5_start).
The drivers appear as **Tutorial 5** and **Tutorial Pace**. The project builds
two independent, single-entry DLLs into separate output directories.

For the main experiments, edit `traffic5.cpp`. `tutorial5pace.cpp` contains the
reference opponent's speed cap. Use the same two build commands after edits.

## Continue with Chapter 6 {#robot_tutorial_windows_chapter_6}

The final checkpoint contains every helper source. From the source root:

```powershell
if (Test-Path src/drivers/tutorial6) { throw 'tutorial6 already exists; use your existing working copy' }
Copy-Item -Recurse src/doc/robot_tutorial/examples/chapter_6 src/drivers/tutorial6
```

If the directory already exists, use your working copy. Leave the active session,
then build and install:

```powershell
& $msbuild src/drivers/tutorial6/tutorial6.vcxproj /p:Configuration=Release /p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw 'Tutorial 6 build failed' }
```

In a new PowerShell session, run the MSBuild discovery block above first.
Follow [Chapter 6's six-lap Quick Race exercise](@ref robot_tutorial_6_start).
Select **Tutorial 6**. Edit `tutorial6.cpp` for starting fuel and `pit.cpp` for
pit/strategy settings, then use the same rebuild command.

The downloadable `tutorial6.zip` contains the same complete folder. If using
that download, extract its `tutorial6` directory under `src/drivers/` before
building. No files or DLLs from the earlier checkpoints are required for the
solo exercise; the optional traffic exercise adds a separately selected opponent.

## Continue with Appendix A {#robot_tutorial_windows_appendix_a}

From the source root, create a separate working copy of the complete example:

```powershell
if (Test-Path src/drivers/tutoriala) { throw 'tutoriala already exists; use your existing working copy' }
Copy-Item -Recurse src/doc/robot_tutorial/examples/appendix_a src/drivers/tutoriala
```

Alternatively extract the download's `tutoriala` folder under `src/drivers/`.
Run the MSBuild discovery block above if this is a new PowerShell session. Leave
the active session, then build and install:

```powershell
& $msbuild src/drivers/tutoriala/tutoriala.vcxproj /p:Configuration=Release /p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw 'Tutorial A build failed' }
```

The project copies the module and `tutoriala.xml`, `default.xml`, and
`g-track-1.xml` into `runtime/drivers/tutoriala/` for Release. Select **Tutorial A**
for [Appendix A's baseline race](@ref robot_tutorial_a_start).

For XML-only experiments, edit `default.xml` or `g-track-1.xml` in your working
copy, save, leave the session, and deploy using the same build command. The
post-build installation target copies XML even when compilation is up to date.
Alternatively copy just those edited configuration files to the Release runtime:

```powershell
Copy-Item src/drivers/tutoriala/default.xml, src/drivers/tutoriala/g-track-1.xml runtime/drivers/tutoriala/
```

Start a new session to read them. C++ changes require the build command. Debug
uses the matching `runtimed` installation instead; keep the game's configuration
and platform consistent with the module. A new track file must also be added to
the project's install `Copy` list. Editing installed XML directly works, but the
next build/install replaces it from your working copy.

## Continue with Appendix B {#robot_tutorial_windows_appendix_b}

From the source root, create a working copy of the complete example:

```powershell
if (Test-Path src/drivers/tutorialb) { throw 'tutorialb already exists; use your existing working copy' }
Copy-Item -Recurse src/doc/robot_tutorial/examples/appendix_b src/drivers/tutorialb
```

Alternatively extract the download's `tutorialb` folder under `src/drivers/`.
In a new PowerShell session, run the MSBuild discovery block above first. Leave
the active session and build/install:

```powershell
& $msbuild src/drivers/tutorialb/tutorialb.vcxproj /p:Configuration=Release /p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw 'Tutorial B build failed' }
```

The project installs the module, configuration, `car1-stock1.rgb`, `logo.rgb`,
and artwork notice into `runtime/drivers/tutorialb/` for Release. Select
**Tutorial B** for the [appearance exercise](@ref robot_tutorial_b_start).

After editing the XCF or SVG sources, export the SGI images into your working
folder. Leave the session and use the same build command to deploy them, or copy
just those two images into the Release runtime:

```powershell
Copy-Item src/drivers/tutorialb/car1-stock1.rgb, src/drivers/tutorialb/logo.rgb runtime/drivers/tutorialb/
```

Start a new session to load the new images. Image-only edits do not require C++
compilation. Use the corresponding `runtimed` destination for a matching Debug
build. The editable artwork stays in the source folder and download; it is not
needed by the running game. If you add individual index directories later, add
their directory creation and image copies to the project's installation target.

## Continue with Appendix C {#robot_tutorial_windows_appendix_c}

From the source root, create a working copy of the complete final checkpoint:

```powershell
if (Test-Path src/drivers/tutorialc) { throw 'tutorialc already exists; use your existing working copy' }
Copy-Item -Recurse src/doc/robot_tutorial/examples/appendix_c src/drivers/tutorialc
```

Alternatively extract the download's `tutorialc` folder under `src/drivers/`.
Run the MSBuild discovery block above if needed, leave the active session, then
build and install the single module:

```powershell
& $msbuild src/drivers/tutorialc/tutorialc.vcxproj /p:Configuration=Release /p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw 'Tutorial C build failed' }
```

The project builds `driver.cpp` along with the helpers and installs one DLL,
the description XML, shared configuration, and the team logo. It creates
`runtime/drivers/tutorialc/1/` and `2/` and installs the individual settings and
textures there. Keep these folders intact in your working copy.

Select **Tutorial C Red**, **Tutorial C Teal**, or both for
[Appendix C's exercises](@ref robot_tutorial_c_start). Build the module once for
both entries. After individual XML/image edits, leave the session and use the
same build/install command; its installation target runs even when compilation
is up to date. Start a new session to read the files. C++ changes require a
rebuild. Debug uses the corresponding `runtimed` destination and matching game
build. Add new individual runtime files to the project's installation `Copy` list.

## If something goes wrong {#robot_tutorial_windows_help}

| Symptom | What to check |
| --- | --- |
| MSBuild discovery fails | Copy the whole discovery block into PowerShell again. If it still cannot find the tools, ask your teacher or the community to help check the Visual Studio installation. |
| Build cannot find headers or libraries | The initial TORCS development setup may be incomplete. Ask your teacher or the community for help and include the error text. |
| The DLL cannot be replaced | Leave the Practice session and return to the menu before rebuilding; merely pausing keeps the driver loaded. Check that another TORCS instance is not using it. |
| Tutorial 1 is missing | Launch `runtime/wtorcs.exe` from this checkout and check that the `car1-stock1` game data is present. |
| The old behaviour persists | Save the file in `src/drivers/tutorial1/`, leave the session, check that the rebuild succeeds, and start a new Practice session. |

Still stuck? [Questions and feedback](@ref robot_tutorial_feedback) explains
where to ask. You do not need to diagnose the problem first.

The project also supports Debug and Win32. If you use these later, match the
game's configuration and architecture; Debug uses the debug setup scripts,
debug libraries, and `runtimed/` rather than `runtime/`.
