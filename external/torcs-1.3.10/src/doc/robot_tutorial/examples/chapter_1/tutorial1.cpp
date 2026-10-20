/***************************************************************************

    file                 : tutorial1.cpp
    created              : September 2026
    copyright            : (C) 2003-2004, 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the Free
 * Software Foundation; either version 2 of the License, or (at your option)
 * any later version. This program is distributed WITHOUT ANY WARRANTY;
 * without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
 * PARTICULAR PURPOSE. See the GNU General Public License for more details.
 * You should have received a copy of the GNU General Public License along
 * with this program; if not, see <https://www.gnu.org/licenses/>.
 */

#include <cstring>
#include <tgf.h>
#include <track.h>
#include <car.h>
#include <robot.h>
#include <robottools.h>

#include "driver.h"

static void
initTrack(int, tTrack*, void*, void** settings, tSituation*)
{
	// Use the car's standard setup.
	*settings = nullptr;
}

static void
newRace(int, tCarElt*, tSituation*)
{
	// No per-race state is needed yet.
}

static void
drive(int, tCarElt* car, tSituation*)
{
	driveCar(car);
}

static void
shutdown(int)
{
	// This first driver owns no persistent resources.
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
tutorial1(tModInfo* modInfo)
{
	// TORCS supplies ten slots; we advertise just one driver, with index 1.
	for (int i = 0; i < 10; ++i) {
		modInfo[i] = tModInfo{};
	}
	// The module loader takes ownership and frees these C strings.
	modInfo[0].name = strdup("Tutorial 1");
	modInfo[0].desc = strdup("A first centerline-following robot");
	modInfo[0].fctInit = initInterface;
	modInfo[0].gfId = ROB_IDENT;
	modInfo[0].index = 1;
	return 0;
}
