/***************************************************************************

    file                 : tutorialc.cpp
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
#include <memory>
#include <robot.h>
#include "driver.h"

static constexpr int ROBOT_COUNT = 2;
static std::unique_ptr<TutorialDriver> Drivers[ROBOT_COUNT];

static int
slotFor(int index)
{
	return index >= 1 && index <= ROBOT_COUNT ? index - 1 : -1;
}

static TutorialDriver*
getDriver(int index)
{
	const int slot = slotFor(index);
	return slot >= 0 ? Drivers[slot].get() : nullptr;
}

static void
initTrack(int index, tTrack* track, void* carSettings, void** settings, tSituation*)
{
	*settings = nullptr;
	if (auto* driver = getDriver(index)) {
		driver->initTrack(track, carSettings, settings);
	}
}

static void
newRace(int index, tCarElt* car, tSituation* situation)
{
	if (auto* driver = getDriver(index)) {
		driver->newRace(car, situation);
	}
}

static void
drive(int index, tCarElt* car, tSituation* situation)
{
	if (auto* driver = getDriver(index)) {
		driver->drive(car, situation);
	} else {
		car->ctrl = tCarCtrl{};
		car->ctrl.brakeCmd = 1.0f;
	}
}

static int
pitCommand(int index, tCarElt* car, tSituation*)
{
	auto* driver = getDriver(index);
	return driver ? driver->pitCommand(car) : ROB_PIT_IM;
}

static void
shutdown(int index)
{
	const int slot = slotFor(index);
	if (slot >= 0) {
		Drivers[slot].reset(); // Destroy this instance, not its teammates.
	}
}

static int
initInterface(int index, void* pointer)
{
	const int slot = slotFor(index);
	if (slot < 0 || !pointer) {
		GfError("Tutorial C: invalid interface index %d or null interface\n", index);
		return -1;
	}
	Drivers[slot] = std::make_unique<TutorialDriver>(index);
	auto* itf = static_cast<tRobotItf*>(pointer);
	*itf = tRobotItf{};
	itf->rbNewTrack = initTrack;
	itf->rbNewRace = newRace;
	itf->rbDrive = drive;
	itf->rbPitCmd = pitCommand;
	itf->rbShutdown = shutdown;
	itf->index = index;
	return 0;
}

extern "C" int
tutorialc(tModInfo* modInfo)
{
	// Discovery publishes metadata; it must not reset live driver instances.
	for (int slot = 0; slot < MAX_MOD_ITF; ++slot) {
		modInfo[slot] = tModInfo{};
	}
	const char* names[ROBOT_COUNT] = {"Tutorial C Red", "Tutorial C Teal"};
	for (int slot = 0; slot < ROBOT_COUNT; ++slot) {
		modInfo[slot].name = strdup(names[slot]);
		modInfo[slot].desc = strdup("Independent robots sharing one tutorial module");
		modInfo[slot].fctInit = initInterface;
		modInfo[slot].gfId = ROB_IDENT;
		modInfo[slot].index = slot + 1;
	}
	return 0;
}
