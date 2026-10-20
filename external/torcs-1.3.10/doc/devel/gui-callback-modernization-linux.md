# GUI Callback Modernization Plan: Linux

## Purpose

This file contains the Linux-side follow-up plan for modernizing TORCS GUI
callbacks after the Windows-first work introduces action-based callbacks in
`tgfclient`.

It is intentionally self-contained so the Linux work can start from this file on
a Linux machine without needing the Windows discussion history.

## Background

The existing GUI callback model uses:

```cpp
typedef void (*tfuiCallback)(void *);
```

This is declared in `src/libs/tgfclient/tgfclient.h`. The internal GUI structs
live in `src/libs/tgfclient/gui.h` and currently store callback function
pointers plus `void *` userdata. The callback is executed later by GUI event
dispatch code.

The model is problematic because many TORCS call sites pass small integer
commands through `void *`, then decode them with casts such as `(long)userdata`.
That creates Win64 warnings and keeps the API weakly typed. Linux x64 usually
does not warn because `long` is 64-bit there, but the design issue is the same.

The target design is to store no-argument commands:

```cpp
#include <functional>

typedef std::function<void()> tGfuiAction;
```

Call sites then capture exactly the state they need:

```cpp
GfuiAddSKeyAction(scrHandle, GLUT_KEY_LEFT, "Previous Resolution", [] {
    ResPrevNext(-1);
}, tGfuiAction());
```

The Windows plan is in `doc/devel/gui-callback-modernization-windows.md`.

## Linux C++ Standard Policy

Do not assume the compiler default dialect.

Modern GCC defaults are already newer than C++11, but older GCC defaults may be
`gnu++98`. The Linux build should probe for C++11 support and only add a `-std`
flag when needed.

Recommended policy:

1. Try compiling a C++11 snippet with the current `CXXFLAGS`.
2. If it works, leave `CXXFLAGS` unchanged.
3. If it fails, try again with `-std=gnu++11`.
4. If that works, append `-std=gnu++11` to `CXXFLAGS`.
5. If that fails, stop configure with a clear error.

Use `gnu++11`, not `c++11`, because TORCS and old dependencies may rely on GNU
or POSIX extensions.

## Autotools Change

The top-level configure input is `configure.in`. It currently has:

```m4
AC_LANG_CPLUSPLUS
AC_PROG_CXX
```

and later builds `CXXFLAGS` without adding a C++ standard flag.

Add a C++11 feature check after `AC_PROG_CXX` and before final `CXXFLAGS`
substitution.

Suggested configure snippet:

```m4
AC_MSG_CHECKING([whether $CXX supports C++11 by default])
save_CXXFLAGS="$CXXFLAGS"
AC_COMPILE_IFELSE(
    [AC_LANG_PROGRAM(
        [[#include <functional>]],
        [[std::function<void()> f = [] {}; f();]])],
    [AC_MSG_RESULT([yes])],
    [AC_MSG_RESULT([no])
     AC_MSG_CHECKING([whether $CXX supports C++11 with -std=gnu++11])
     CXXFLAGS="$save_CXXFLAGS -std=gnu++11"
     AC_COMPILE_IFELSE(
        [AC_LANG_PROGRAM(
            [[#include <functional>]],
            [[std::function<void()> f = [] {}; f();]])],
        [AC_MSG_RESULT([yes])],
        [AC_MSG_RESULT([no])
         AC_MSG_ERROR([TORCS requires a C++11-capable compiler])])])
```

This leaves modern GCC defaults alone and only adds `-std=gnu++11` for older
defaults.

After editing `configure.in`, regenerate `configure` on Linux using the repo's
normal autotools workflow.

## Source Migration Expectations

By the time Linux work starts, the Windows-first branch should ideally have:

```cpp
typedef std::function<void()> tGfuiAction;
```

and action-based APIs such as:

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

The old `void *` APIs may still exist during migration and can be wrappers around
the new action APIs.

Recommended wrapper pattern:

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

## Linux Work Steps

1. Pull or merge the Windows action-callback work.
2. Run `./configure` before local changes and record whether the existing build still configures.
3. Add the conditional C++11 check to `configure.in`.
4. Regenerate `configure` using the project's autotools setup.
5. Run `./configure` again with the default compiler.
6. Confirm the configure output reports C++11 support by default or with `-std=gnu++11`.
7. Build with `make`.
8. Fix any Linux compile errors caused by exposing `std::function` through `tgfclient.h`.
9. Run a second configure/build with an explicit modern dialect if desired, for example `CXXFLAGS='-std=gnu++17' ./configure`, to ensure the conditional check does not fight user-provided flags.
10. Continue migrating remaining legacy `void *` GUI callbacks after the Linux build is stable.

## Build Commands

Run from `torcs/torcs/` on Linux:

```sh
./configure
make
```

For a clean rebuild:

```sh
make clean
make
```

For testing an explicit user-provided dialect:

```sh
make distclean
CXXFLAGS='-std=gnu++17' ./configure
make
```

## Validation Searches

Find legacy integer-through-pointer patterns:

```sh
rg '\(long\).*v|\(void\*\)\s*-?[0-9]|\(void\*\)\s*[A-Z_]+' src
```

Find remaining legacy callback API use:

```sh
rg 'tfuiCallback|userDataOn|GfuiAddKey\(|GfuiAddSKey\(|GfuiButtonCreate\(|GfuiGrButtonCreate\(' src
```

Find action API use:

```sh
rg 'tGfuiAction|Gfui.*Action' src/libs/tgfclient src/libs src/modules src/drivers
```

The legacy callback search does not need to be empty until the final migration
phase.

## Likely Linux Compile Issues

`std::function` in `tgfclient.h` means any source that includes that header must
compile as C++11 or newer. Current TORCS usage appears to include `tgfclient.h`
from C++ source files, not C source files, but check this again on Linux with:

```sh
rg '#include\s+[<"]tgfclient.h[>"]' src --glob '*.c'
```

If any C file includes `tgfclient.h`, either remove that include from the C file
or split the C++ action API into a C++-only header.

Older GCC may require the conditional `-std=gnu++11` path. That is expected.

If a system compiler is too old to support lambdas and `std::function`, configure
should fail with `TORCS requires a C++11-capable compiler`.

## Lifetime And Ownership Notes

Action callbacks should capture raw pointers only when the legacy callback
already stored the same raw pointer in `void *` userdata. This preserves existing
lifetime assumptions.

Do not capture references to local stack variables when the action is stored in a
screen or widget. GUI callbacks execute later.

Safe captures:

```cpp
[precMenu] { GfuiScreenActivate(precMenu); }
[delta] { ResPrevNext(delta); }
```

Unsafe captures:

```cpp
[&] { ResPrevNext(delta); }
[&localStruct] { Use(localStruct); }
```

## Completion Criteria

Linux work is complete when:

1. `./configure` detects C++11 support without forcing unnecessary flags.
2. `./configure && make` succeeds on the Linux target machine.
3. The build succeeds with the action-based GUI APIs from the Windows work.
4. No Linux-specific compile errors remain from `std::function`, lambdas, or captured callbacks.
5. Remaining `void *` callback uses are known migration work, not platform build blockers.

## Non-Goals For The Linux Follow-Up

Do not reintroduce integer-through-pointer casts to avoid Linux build issues.

Do not change Windows project files from the Linux step unless a shared source
change makes it necessary.

Do not convert the action callback model to visitor/message classes.

Do not edit `export/` by hand.
