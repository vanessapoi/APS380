/***************************************************************************

    file                 : olethros.cpp
    copyright            : (C) 2002-2026 Bernhard Wymann
                               2004 Christos Dimitrakakis
    email                : berniw@bluewin.ch, dimitrak@idiap.ch

 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/

/** 
	\file olethros.cpp
	
	\brief This is the main file for the Olethros robot.
	@ingroup olethros_lifecycle
	
	The Olethros robot is basically the same as berniw's BT robot with
	added learning capabilities.
*/

#ifdef _WIN32
#include <windows.h>
#endif

#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#include <tgf.h>
#include <track.h>
#include <car.h>
#include <raceman.h>
#include <robottools.h>
#include <robot.h>

#include "driver.h"


static const int NBBOTS = 10;

static const char* botname[NBBOTS] = {
	"olethros 1", "olethros 2", "olethros 3", "olethros 4", "olethros 5",
	"olethros 6", "olethros 7", "olethros 8", "olethros 9", "olethros 10"
};

static const char* botdesc[NBBOTS] = {
	"olethros 1", "olethros 2", "olethros 3", "olethros 4", "olethros 5",
	"olethros 6", "olethros 7", "olethros 8", "olethros 9", "olethros 10"
};

// Module ownership also covers interfaces whose car setup is rejected before
// the engine adds them to the normal per-race shutdown list.
static std::unique_ptr<Driver> driver[NBBOTS];

static void initTrack(int index, tTrack* track, void *carHandle, void **carParmHandle, tSituation *s);
static void newRace(int index, tCarElt* car, tSituation *s);
static void drive(int index, tCarElt* car, tSituation *s);
static int pitcmd(int index, tCarElt* car, tSituation *s);
static void shutdown(int index);
static int InitFuncPt(int index, void *pt);
static void endRace(int index, tCarElt *car, tSituation *s);


/** @brief Register ten named robot interfaces with TORCS.
 * @param[out] modInfo Storage for ten module descriptors, supplied by TORCS.
 * @return Zero on normal registration.
 * @details Displayed bot numbers 1..10 correspond to zero-based indices 0..9.
 */
extern "C" int olethros(tModInfo *modInfo)
{
	int i;

	// Clear all structures.
	memset(modInfo, 0, 10*sizeof(tModInfo));

	for (i = 0; i < NBBOTS; i++) {
		modInfo[i].name    = strdup(botname[i]);	// name of the module (short).
		modInfo[i].desc    = strdup(botdesc[i]);	// Description of the module (can be long).
		modInfo[i].fctInit = InitFuncPt;			// Init function.
		modInfo[i].gfId    = ROB_IDENT;				// Supported framework version.
		modInfo[i].index   = i;						// Indices from 0 to 9.
	}
	return 0;
}


/** @brief Allocate the indexed Driver and fill its TORCS callback table.
 * @param[in] index Bot slot in [0,NBBOTS).
 * @param[out] pt TORCS tRobotItf storage.
 * @return Zero on normal initialization.
 */
static int InitFuncPt(int index, void *pt)
{
	tRobotItf *itf = (tRobotItf *)pt;

	// Create robot instance for index.
	driver[index].reset(new Driver(index));
	itf->rbNewTrack = initTrack;	// Give the robot the track view called.
	itf->rbNewRace  = newRace;		// Start a new race.
	itf->rbDrive    = drive;		// Drive during race.
	itf->rbPitCmd   = pitcmd;		// Pit commands.
	itf->rbEndRace  = endRace;		// End of the current race.
	itf->rbShutdown = shutdown;		// Called before the module is unloaded.
	itf->index      = index;		// Index used if multiple interfaces.
	return 0;
}


/** @brief Forward track/setup initialization to the indexed Driver; pointers stay TORCS-owned. */
static void initTrack(int index, tTrack* track, void *carHandle, void **carParmHandle, tSituation *s)
{
	driver[index]->initTrack(track, carHandle, carParmHandle, s);
}


/** @brief Bind the car and initialize race-local driver state. */
static void newRace(int index, tCarElt* car, tSituation *s)
{
	driver[index]->newRace(car, s);
}


/** @brief Forward a robot timestep; the Driver already retains the car pointer. */
static void drive(int index, tCarElt* car, tSituation *s)
{
	driver[index]->drive(s);
}


/** @brief Forward pit-service requests and return the driver's service mode. */
static int pitcmd(int index, tCarElt* car, tSituation *s)
{
	return driver[index]->pitCommand(s);
}


/** @brief Forward race completion; not the persistence callback. */
static void endRace(int index, tCarElt *car, tSituation *s)
{
	driver[index]->endRace(s);
}


/** @brief Destroy the indexed Driver before unloading; its destructor applies save policy. */
static void shutdown(int index)
{
	driver[index].reset();
}
