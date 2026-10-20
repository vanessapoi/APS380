/***************************************************************************

    file                 : tutorial3.cpp
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
#include "recovery3.h"
#include "speed.h"

static tTrack* currentTrack = nullptr;
static Recovery recovery;
static SpeedDriver driver;

static void
initTrack(int, tTrack* track, void*, void** settings, tSituation*)
{
	currentTrack = track;
	*settings = nullptr;
}

static void
newRace(int, tCarElt* car, tSituation* situation)
{
	recovery.reset(situation->currentTime);
	driver.configure(currentTrack, car);
}

static void
drive(int, tCarElt* car, tSituation* situation)
{
	if (recovery.driveIfNeeded(car, situation)) {
		driver.resumeAfterRecovery(situation->currentTime);
		return;
	}
	driver.drive(car, situation);
}

static void
shutdown(int)
{
	currentTrack = nullptr;
}

static int
initInterface(int index, void* pointer)
{
	auto* itf = static_cast<tRobotItf*>(pointer);
	*itf = tRobotItf{};
	itf->rbNewTrack = initTrack;
	itf->rbNewRace = newRace;
	itf->rbDrive = drive;
	itf->rbShutdown = shutdown;
	itf->index = index;
	return 0;
}

extern "C" int
tutorial3(tModInfo* modInfo)
{
	for (int i = 0; i < 10; ++i) {
		modInfo[i] = tModInfo{};
	}
	modInfo[0].name = strdup("Tutorial 3");
	modInfo[0].desc = strdup("A robot that chooses its speed");
	modInfo[0].fctInit = initInterface;
	modInfo[0].gfId = ROB_IDENT;
	modInfo[0].index = 1;
	return 0;
}
