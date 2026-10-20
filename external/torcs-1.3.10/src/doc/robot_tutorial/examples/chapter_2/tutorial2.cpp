/***************************************************************************

    file                 : tutorial2.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#include <cstring>
#include <tgf.h>
#include <robot.h>
#include "recovery.h"
#include "practice.h"

// This module registers one car. Multiple independent robots come in Chapter 9.
static Recovery recovery;
static PracticeMistake mistake;

static void
initTrack(int, tTrack*, void*, void** settings, tSituation*)
{
	*settings = nullptr;
}

static void
newRace(int, tCarElt*, tSituation* situation)
{
	recovery.reset(situation->currentTime);
	mistake.reset();
}

static void
drive(int, tCarElt* car, tSituation* situation)
{
	if (mistake.drive(car, situation)) {
		recovery.reset(situation->currentTime);
		return;
	}
	recovery.drive(car, situation);
}

static void
shutdown(int)
{
	// No allocated resources to release.
}

static int
initInterface(int index, void* interfacePointer)
{
	auto* itf = static_cast<tRobotItf*>(interfacePointer);
	*itf = tRobotItf{};
	itf->rbNewTrack = initTrack;
	itf->rbNewRace = newRace;
	itf->rbDrive = drive;
	itf->rbShutdown = shutdown;
	itf->index = index;
	return 0;
}

extern "C" int
tutorial2(tModInfo* modInfo)
{
	for (int i = 0; i < 10; ++i) {
		modInfo[i] = tModInfo{};
	}
	modInfo[0].name = strdup("Tutorial 2");
	modInfo[0].desc = strdup("A robot that gets back on track");
	modInfo[0].fctInit = initInterface;
	modInfo[0].gfId = ROB_IDENT;
	modInfo[0].index = 1;
	return 0;
}
