/***************************************************************************

    file                 : tutorial5pace.cpp
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
#include <robot.h>
#include "traffic5.h"

// A separate, single-entry reference driver. It follows the Chapter 4 centerline.
static constexpr double PACE_SPEED = 18.0; // m/s; keep fixed for the first experiments
static tTrack* currentTrack = nullptr;
static SpeedDriver driver;

static void
initTrack(int, tTrack* track, void*, void** settings, tSituation*)
{
	currentTrack = track;
	*settings = nullptr;
}

static void
newRace(int, tCarElt* car, tSituation*)
{
	driver.configure(currentTrack, car);
}

static void
drive(int, tCarElt* car, tSituation* situation)
{
	driver.drive(car, situation);
	applySpeedTarget(driver, car, PACE_SPEED, 1.0);
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
tutorial5pace(tModInfo* modInfo)
{
	for (int i = 0; i < 10; ++i) {
		modInfo[i] = tModInfo{};
	}
	modInfo[0].name = strdup("Tutorial Pace");
	modInfo[0].desc = strdup("Chapter 5 reference opponent");
	modInfo[0].fctInit = initInterface;
	modInfo[0].gfId = ROB_IDENT;
	modInfo[0].index = 1;
	return 0;
}
