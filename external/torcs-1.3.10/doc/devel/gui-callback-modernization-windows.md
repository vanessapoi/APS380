# GUI Callback Modernization Plan: Windows

## Purpose

Modernize the Windows TORCS GUI callback path so UI actions no longer pass
integer commands through `void *` userdata. The immediate target is the x64
warning set around pointer truncation, but the design should also prepare the
GUI layer for removing `tfuiCallback(void *)` entirely.

This file is the Windows-first execution plan. The Linux follow-up is documented
separately in `doc/devel/gui-callback-modernization-linux.md`.

## Current State

The low-level GUI API is declared in `src/libs/tgfclient/tgfclient.h` and uses:

```cpp
typedef void (*tfuiCallback)(void *);
```

The implementation stores callback function pointers and `void *` userdata in
internal structs from `src/libs/tgfclient/gui.h`, then calls the stored callback
later from files such as `gui.cpp`, `guiobject.cpp`, `guibutton.cpp`,
`guiscrollist.cpp`, and `screen.cpp`.

The Win64 warnings come from call sites that pass small integer commands as
`void *` and decode them with `(long)`. This is unsafe on Windows x64 because
`long` remains 32-bit while pointers are 64-bit.

Representative warning-producing files:

```text
src/modules/graphic/ssggraph/grmain.cpp
src/libs/confscreens/driverconfig.cpp
src/libs/confscreens/openglconfig.cpp
src/libs/raceengineclient/raceengine.cpp
src/libs/raceengineclient/racestate.cpp
src/libs/racescreens/driverselect.cpp
src/libs/racescreens/pitmenu.cpp
src/libs/tgfclient/gui.cpp
src/libs/tgfclient/guiobject.cpp
src/libs/tgfclient/screen.cpp
```

Valid real pointer userdata also exists, for example screen handles, previous
menus, driver records, scroll list elements, and callback context data. These
must not be treated as integer tokens.

## C++ Standard Decision

The core Visual Studio projects currently use the `v143` toolset but do not set
an explicit `<LanguageStandard>` in the project files. Test projects already use
`stdcpp17`.

For the Windows modernization step, set the core projects that include or depend
on `tgfclient.h` to at least C++14 in Visual Studio project files:

```xml
<LanguageStandard>stdcpp14</LanguageStandard>
```

Reason: Visual Studio has project settings for C++14 and newer, not a precise
portable C++11 mode. The new code should still use only C++11 language/library
features: lambdas, captures, and `std::function<void()>`.

## Target Design

Add a no-argument GUI action type:

```cpp
#include <functional>

typedef std::function<void()> tGfuiAction;
```

GUI APIs should store callable actions directly and invoke them without userdata:

```cpp
if (curKey->onPressAction) {
    curKey->onPressAction();
}
```

New call sites should capture any needed data explicitly:

```cpp
GfuiAddKeyAction(reScreenHandle, '+', "Accelerate Time", [] {
    ReTimeMod(1);
}, tGfuiAction());
```

```cpp
GfuiButtonCreateAction(scrHandle, "Back", GFUI_FONT_LARGE, 430, 40, 150,
                       GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP, [precMenu] {
    GfuiScreenActivate(precMenu);
}, tGfuiAction(), tGfuiAction());
```

This removes integer-pointer casts and makes each UI callback express the actual
operation it performs.

## API Migration Shape

Add action-based APIs beside the legacy APIs first. Do not remove the old APIs
in the first Windows step.

Recommended new names, to avoid overload ambiguity in old code:

```cpp
GfuiAddKeyAction
GfuiRegisterKeyAction
GfuiAddSKeyAction
GfuiScreenCreateAction
GfuiHookCreateAction
GfuiButtonCreateAction
GfuiLeanButtonCreateAction
GfuiButtonStateCreateAction
GfuiGrButtonCreateAction
GfuiEditboxCreateAction
GfuiScrollListCreateAction
GfuiMenuButtonCreateAction
GfuiMenuBackQuitButtonCreateAction
```

Keep the existing names for the legacy `void *` APIs until all call sites are
migrated.

## Internal Struct Changes

Update `src/libs/tgfclient/gui.h` to add action fields while retaining legacy
fields during migration.

For `tGfuiKey`, add:

```cpp
tGfuiAction onPressAction;
tGfuiAction onReleaseAction;
```

For `tGfuiButton` and `tGfuiGrButton`, add:

```cpp
tGfuiAction onPushAction;
tGfuiAction onFocusAction;
tGfuiAction onFocusLostAction;
```

For `tGfuiEditbox`, add:

```cpp
tGfuiAction onFocusAction;
tGfuiAction onFocusLostAction;
```

For `tGfuiScrollList`, add:

```cpp
tGfuiAction onSelectAction;
```

For `tGfuiScreen`, add:

```cpp
tGfuiAction onActivateAction;
tGfuiAction onDeactivateAction;
```

Existing `void *` userdata and `tfuiCallback` fields can stay temporarily so the
legacy API keeps working while call sites are migrated.

## Bridge Legacy APIs

Implement the old APIs as wrappers around the new action storage. This reduces
the number of dispatch paths and keeps the migration incremental.

Suggested helper in a private `tgfclient` implementation file:

```cpp
static tGfuiAction
gfuiMakeAction(void *userData, tfuiCallback callback)
{
    if (!callback) {
        return tGfuiAction();
    }

    return [userData, callback] {
        callback(userData);
    };
}
```

Example legacy wrapper:

```cpp
void
GfuiAddKey(void *scr, unsigned char key, const char *descr, void *userData,
           tfuiCallback onKeyPressed, tfuiCallback onKeyReleased)
{
    GfuiAddKeyAction(scr, key, descr,
                     gfuiMakeAction(userData, onKeyPressed),
                     gfuiMakeAction(userData, onKeyReleased));
}
```

## Windows Implementation Steps

1. Update the relevant Visual Studio projects to use `<LanguageStandard>stdcpp14</LanguageStandard>`.
2. Add `#include <functional>` and `typedef std::function<void()> tGfuiAction;` to `src/libs/tgfclient/tgfclient.h`.
3. Add action fields to internal structs in `src/libs/tgfclient/gui.h`.
4. Implement `GfuiAddKeyAction`, `GfuiRegisterKeyAction`, and `GfuiAddSKeyAction` first.
5. Change key dispatch in `src/libs/tgfclient/gui.cpp` to call action fields.
6. Keep legacy key APIs as wrappers through `gfuiMakeAction`.
7. Convert the warning-producing key callbacks in `grmain.cpp`, `racegl.cpp`, and `screen.cpp`.
8. Implement action-based button and graph-button APIs in `guibutton.cpp`.
9. Update button dispatch in `guiobject.cpp` and related button action code to use action fields.
10. Convert warning-producing button callbacks in `driverconfig.cpp`, `openglconfig.cpp`, `driverselect.cpp`, `pitmenu.cpp`, and `screen.cpp`.
11. Add action support for screen activation/deactivation, hooks, edit boxes, menus, and scroll lists as separate follow-up commits.
12. After each batch, build Windows x64 Release and inspect warnings before proceeding.

## First Conversion Targets

Start with the warning-producing integer command callbacks because they are the
highest-value and easiest to validate.

Examples to convert:

```cpp
static void ResPrevNext(void *vdelta)
{
    long delta = (long)vdelta;
    curRes += (int)delta;
}
```

Becomes:

```cpp
static void ResPrevNext(int delta)
{
    curRes += delta;
}
```

And registration becomes:

```cpp
GfuiAddSKeyAction(scrHandle, GLUT_KEY_LEFT, "Previous Resolution", [] {
    ResPrevNext(-1);
}, tGfuiAction());
```

For direct mouse action calls in `gui.cpp`, prefer a typed helper over callback
userdata:

```cpp
static void
gfuiMouseAction(int action)
{
    ...
}
```

Then call it directly:

```cpp
gfuiMouseAction(1 - GfuiScreen->mouse);
```

## Exported Headers

Do not edit files under `export/` directly.

After changing `src/libs/tgfclient/tgfclient.h`, refresh exported headers with
the normal Windows setup workflow, for example `setup_win32.bat` or the matching
debug script when needed.

## Build Commands

Use the full MSBuild path through PowerShell so output is captured.

Release x64:

```powershell
powershell -Command "& 'C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe' TORCS.sln /p:Configuration=Release /p:Platform=x64 2>&1"
```

Release Win32:

```powershell
powershell -Command "& 'C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe' TORCS.sln /p:Configuration=Release /p:Platform=Win32 2>&1"
```

Run from `torcs/torcs/`.

## Validation Searches

Search for remaining pointer/integer callback patterns:

```text
rg "\(long\).*v|\(void\*\)\s*-?[0-9]|\(void\*\)\s*[A-Z_]+" src
```

Search for remaining legacy callback API usage:

```text
rg "tfuiCallback|userDataOn|GfuiAddKey\(|GfuiAddSKey\(|GfuiButtonCreate\(|GfuiGrButtonCreate\(" src
```

Do not expect the second search to be empty until the full migration is complete.

## Risks

Adding `std::function` to `tgfclient.h` makes that public GUI API C++-only. The
current source tree includes `tgfclient.h` from C++ sources, not C sources, but
this should be checked again before removing legacy APIs.

Captured raw pointers preserve the current lifetime assumptions. They remove
fake userdata casts but do not create new ownership semantics.

Using C++ callables in the GUI API means all GUI clients and modules must be
compiled with compatible C++ settings. The Windows solution already builds these
projects together with the same toolset.

## Non-Goals For The Windows First Step

Do not remove `tfuiCallback` immediately.

Do not change Linux build flags in the Windows-first commit series.

Do not introduce visitor or heap-owned message classes.

Do not edit `export/` by hand.
