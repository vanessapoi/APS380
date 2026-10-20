/***************************************************************************

    file                 : torcsdoc.h
    created              : Sat Jul 27 14:24:31 CEST 2002
    copyright            : (C) 2001-2026 by Eric Espié, Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 
/** @file    
    @author Bernhard Wymann, Eric Espié
*/

#ifndef _TORCSDOC_H_
#define _TORCSDOC_H_

/**
   @defgroup ctrl Control Device Management API
   This is the API to use control devices (Keyboard, mouse and joysticks).
*/

/**
   @defgroup dir Directory Management API
   This is used for directory manipulation.
*/

/**
   @defgroup module Dynamic Modules API
        
    This is the interface to load/unload the shared libraries (or DLLs).
    Two modes are allowed, the access by filename, of the access by the entire directory.
    When the directory mode is used, the filenames are not known in advance, this allows
    more flexibility at runtime.

    The generic information can be retrieved, without keeping the DLL loaded.
    The gfid parameter is used to differentiate the modules using different includes. This
    functionality is not used yet. This API is not used for shared libraries linked
    staticaly at compilation time.
*/

/**
   @defgroup gui GUI Management API
   Create and manage menu screens, widgets and input callbacks. Include
   <tt>tgfclient.h</tt> and use the API after the GUI/fonts and OpenGL context
   have been initialized, on the GUI event thread.

   @par Screens and widgets
   Create a screen with GfuiScreenCreate, GfuiScreenCreateExAction or
   GfuiMenuScreenCreate, add widgets, then call GfuiScreenActivate.
   Widget identifiers are local to their owning screen. Release a screen and
   its widgets with GfuiScreenRelease; GfuiScreenDeactivate only stops its use.
   GfuiScreenReplace releases the old screen before activating a different one.
   Callback-only hooks use GfuiHookCreateAction and GfuiHookRelease.
   Unless a function explicitly documents otherwise, pass a valid, non-NULL
   screen handle and identifiers of the required widget type. Functions that
   operate on the current screen require an active screen.

   @par Coordinates and text
   Screens use a 640 by 480 logical coordinate system, scaled to the viewport,
   with the origin at the lower-left corner. GfuiMouseSetPos is an exception:
   it accepts GLUT window pixels with a top-left origin. Alignment support is
   widget-specific; text labels/buttons use horizontal alignment only.
   Text capacities are byte counts excluding the terminating NUL, not Unicode
   character counts. Label/edit-box text is copied; scroll-list element names
   and associated data are borrowed from the caller.

   @par Callbacks and ownership
   The Action variants copy a tGfuiAction (std::function), allowing lambdas.
   The callback variants store a function pointer and caller-supplied data.
   Captured references and borrowed data must remain valid while callbacks can
   run. Empty actions and NULL callbacks do nothing; they do not automatically
   disable widgets. Use GfuiEnable with GFUI_DISABLE for that.
   Releasing a screen destroys its stored actions, but does not free raw user
   data pointers. Callbacks run synchronously during GUI event processing.

   @par Parameter directions
   Input values and borrowed pointers are marked <tt>[in]</tt>. A screen whose
   contents are modified is marked <tt>[in,out]</tt>. Output pointers, such as
   a scroll-list lookup's userData argument, are marked <tt>[out]</tt> and are
   written only on success. These markers do not transfer memory ownership.
*/

/**
   @defgroup hash Hash Tables API
   Hash tables API.
*/

/**
   @defgroup img Image Management API
   Load and store png images with easy interface.
*/


/**
    @defgroup params Parameter Handling API
    @brief With this API you can handle parameter sets in TORCS, this includes
    manipulation of data in memory, and writing into/reading from XML files.
    
    The parameters are structured in:
    <br><b>section</b> - containing a family of parameters on the same topic.
    <br><b>list</b> (subsections) - containing <b>elements</b>
    of <b>numerical attributes</b> and <b>string attributes</b>.
    <br>
    <br>The API is not thread safe, because parameter sets and handles carry internal
    state regarding iteration and XML parsing. The parameter sets are reference counted,
	so usually multiple handles can refer to the same parameter set.

    @par Handles and ownership
    Include tgf.h. TORCS initializes the library before robot callbacks. Read a
    file with GfParmReadFile and check for NULL before using the result. Each
    successful read returns an owned handle to release with GfParmReleaseHandle;
    do not release handles borrowed from the race manager. Most functions require
    a valid non-NULL handle, even getters with a fallback value.
    Non-private reads with the same filename share data: modifying, cleaning or
    rereading through one handle affects the others. GFPARM_RMODE_PRIVATE requests
    independent data. GFPARM_RMODE_CREAT creates only an in-memory set; persistence
    requires GfParmWriteFile. Releasing a handle does not save it.

    @par Paths, strings and units
    Paths are slash-separated section names such as "Gearbox/gears/1", without
    a leading or trailing slash. Keys identify attributes within that section;
    use the constants in car.h and other interface headers where available.
    String getters return borrowed storage (or the exact fallback pointer), not
    a copy. Copy strings before retaining them across mutations, rereads or release.
    Numeric values are stored in SI units. Getter unit arguments select output
    units; setter unit arguments describe input units. NULL means SI. Defaults
    are returned unchanged, so express them in the requested output unit.
    GfParmGetNumBoundaries always returns SI bounds. GfParmSetNum also sets both
    bounds to the value; use GfParmSetNumEx to preserve an adjustable range.

    @par Reading a robot setting
    @code{.cpp}
    void *settings = GfParmReadFile("drivers/myrobot/default.xml",
                                  GFPARM_RMODE_STD | GFPARM_RMODE_PRIVATE);
    if (settings != NULL) {
        tdble fuel = GfParmGetNum(settings, SECT_CAR, PRM_FUEL, NULL, 50.0f);
        // Use fuel here; copy any strings needed after releasing settings.
        GfParmReleaseHandle(settings);
    }
    @endcode

    @par Lists and validation
    A list is a section whose immediate child sections are its elements, not an
    array of attributes. Its cursor is shared by all handles to that parameter
    set. GfParmListSeekFirst can succeed on an empty list; check the current name
    before processing it (see @ref paramslist).
    Setters do not enforce setup constraints. See GfParmCheckHandle for the
    limitations of its checks and return status, and GfParmMergeHandles for
    merge modes, range adjustment and optional input-handle release.

    @par Parameter directions
    [in] means read-only input, [out] means a caller-provided output destination,
    and [in,out] includes mutation of data, iteration state or handle lifetime.
*/
/**
   @defgroup conf Parameter Handling API Setup
   Initialize and shutdown the Parameter Handling API
   @ingroup params
*/
/**
   @defgroup paramsfile Parameter File Handling API
   Create, read and write parameter files
   @ingroup params
*/
/**
   @defgroup paramsdata Parameter Data Handling API
   Handling of data in parameter sets 
   @ingroup params
*/
/**
   @defgroup paramslist Parameter List Handling API
   Handling of multiple sections or subsections and the elements in parameter sets
   @ingroup params
   @par Iterating safely over an empty or nonempty list
   @code{.cpp}
   const char *path = "Gearbox/gears";
   if (GfParmListSeekFirst(settings, path) == 0) {
       while (GfParmListGetCurEltName(settings, path) != NULL) {
           tdble ratio = GfParmGetCurNum(settings, path, PRM_RATIO, NULL, 0.0f);
           // Use ratio for this gear. Do not mutate the list while iterating.
           if (GfParmListSeekNext(settings, path) != 0) {
               break;
           }
       }
   }
   @endcode
   settings must be a valid handle. Nested iteration of different sections is
   possible, but another iterator over the same section replaces its cursor.
*/
/**
   @defgroup paramshelper Parameter Helper Functions
   Internal (not exported) helper functions, not part of the API
   @ingroup params
*/

/**
    @defgroup racemantools Race Managers API
    Common functions for race managers.
*/

/**
   @defgroup robottools Robottools API
   API for gathering track information and handling car setups. Include robottools.h.

   @par Track coordinates
   Global X/Y/Z positions and lateral distances are in meters. A tTrkLocPos
   contains a borrowed segment pointer and local coordinates: toStart is a
   distance in meters on a straight but an angle in radians on a curve.
   toRight increases toward the left, toLeft increases toward the right, and
   toMiddle is positive to the left of the segment center. TR_TORIGHT,
   TR_TOLEFT and TR_TOMIDDLE select which lateral field a local-to-global
   conversion uses; they are distinct from the TR_LPOS_* output modes of
   global-to-local conversion. Use a main segment as the search seed.
   Most helpers require valid segment/position pointers and do not clamp
   off-road positions or advance a local position into the next segment.

   @par Typical robot queries
   @code{.cpp}
   tdble heading = RtTrackSideTgAngleL(&car->_trkPos);
   tdble distance = RtGetDistFromStart(car);  // meters, without completed laps
   tdble forward, lateral;
   if (RtDistToPit(car, track, &forward, &lateral) == 0) {
       // The car has an assigned pit; both distances are now valid.
   }
   @endcode

   @par Setup ownership and units
   Setup values and bounds in tCarPitSetup use SI units. Initialize the struct
   before populating it: missing attributes do not initialize every field.
   Setup helpers use the Parameter Handling API; handles returned by
   RtLoadOriginalCarSettings and RtParmReadSetup must be released with
   GfParmReleaseHandle. Handles passed as master setups are borrowed.
   See @ref setuptools for saved setup loading and naming, and @ref tracktools
   for geometry queries. The legacy @ref telemetry wrappers currently do nothing.
*/

/**
   @defgroup screen Screen Management API
*/

/**
   @defgroup tailq	Tail Queue Management API
   This is the management of tail queues.
*/

/**
   @defgroup definitions Global Definitions
   This is the global definitions used in TORCS.
*/
/**
   @defgroup trackstruct Track Structure
   This is the tracks structure definition.
   <br><b>tTrack</b> is the main track structure.
   <br><b>trackSeg</b> is the segment structure.
   @ingroup definitions
*/
/**
   @defgroup carstruct Car Structure
   This is the cars structure definition.
   <br><b>CarElt</b> is the main car structure.
   @ingroup definitions
*/
/**
   @defgroup raceinfo Race Information Structure
   This is the race information structures definition.
   @ingroup definitions
*/

/**
   @defgroup modint	Modules Interfaces
   These are the interfaces for dynamic modules.
*/

/** 
    @defgroup OS OS Dependant Functions
    OS specific function table
*/

/**
   @defgroup trace		Trace Management
   Allow the trace in the file <tt>trace.txt</tt>
*/

/**
    @mainpage	Welcome to the TORCS Documentation

    @section archlist Architecture
    
    - [Architecture Overview](@ref architecture)
    
    @section doclist Other Documentation
     
    - [Changelogs](@ref changelogs)
    - [Track Manual](@ref track_manual)
    - [Track Tools Guide](@ref track_tools)
    - [Robot Tutorial](@ref robot_tutorial)
    - [FAQ](@ref faq)
    - [Car Creation Tutorial](http://www.youtube.com/playlist?list=PLq-L0hhLuRI04BLdNW0QrSxhvuyPml8zp)
    - [Research Papers](http://scholar.google.com/scholar?q=torcs+car)

    The most recent links and news can be found on the [TORCS site](http://www.torcs.org).
    
    @section robotlist Robots API
    
    - [Robot Module Interface](@ref robotmodint)
    - [Robottools API](@ref robottools)
    - [Parameter Handling API](@ref params)
    - [Track Structure](@ref trackstruct)
    - [Car Structure](@ref carstruct)

    @section racemanlist Race Manager API

    - [Race Managers API](@ref racemantools)
    - [Parameter Handling API](@ref params)
    - [Tracks structure](@ref trackstruct)
    
    @section modlist Module Interfaces
    - [Graphic Module Interface](@ref graphicmodint)
    - [Robot Module Interface](@ref robotmodint)
    - [Simulation Module Interface](@ref simumodint)
    - [Track Loader Module Interface](@ref trackmodint)

*/

#endif /* _TORCSDOC_H_ */ 
