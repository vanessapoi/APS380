/***************************************************************************

    file                 : tutorial6.cpp
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
#include <cmath>
#include <robot.h>
#include <robottools.h>
#include "recovery.h"
#include "pit.h"

// Start with a full reference-car tank for the route exercise; try 4.0 for strategy.
static constexpr double STARTING_FUEL = 60.0; // litres, within this car's permitted range
static tTrack* currentTrack = nullptr;
static SpeedDriver driver;
static Recovery recovery;
static TrafficPlanner traffic;
static PitDriver pits;

static void
initTrack(int, tTrack* track, void* carSettings, void** settings, tSituation*)
{
	currentTrack = track;
	*settings = GfParmReadFile("", GFPARM_RMODE_CREAT | GFPARM_RMODE_PRIVATE);
	if (*settings) {
		const double tank = GfParmGetNum(carSettings, SECT_CAR, PRM_TANK, "l", 60.0f);
		const bool supported = track->pits.type == TR_PIT_ON_TRACK_SIDE && track->pits.nMaxPits > 0;
		GfParmSetNum(*settings, SECT_CAR, PRM_FUEL, "l", static_cast<tdble>(supported ? std::min(tank, STARTING_FUEL) : tank));
	}
}

static void
newRace(int, tCarElt* car, tSituation* situation)
{
	driver.configure(currentTrack, car);
	recovery.reset(situation->currentTime);
	traffic.reset(situation->currentTime);
	pits.configure(currentTrack, car);
}

static void
drive(int, tCarElt* car, tSituation* situation)
{
	// The pit state machine owns approach, intentional stopping, service and exit.
	traffic.observe(car, situation, driver.trackLength);
	const bool travellingInPits = pits.mode == PitDriver::Mode::Approach ||
		pits.mode == PitDriver::Mode::Lane || pits.mode == PitDriver::Mode::Exit;
	if (travellingInPits && !traffic.nearby && recovery.driveIfNeeded(car, situation)) {
		driver.resumeAfterRecovery(situation->currentTime);
		traffic.reset(situation->currentTime);
		return;
	}
	if (pits.drive(driver, traffic, car, situation)) {
		if (!travellingInPits || traffic.nearby) {
			recovery.reset(situation->currentTime);
		}
		return;
	}
	traffic.observe(car, situation, driver.trackLength);
	if (traffic.nearby) {
		double angle = RtTrackSideTgAngleL(&car->_trkPos) - car->_yaw;
		NORM_PI_PI(angle);
		if (recovery.mode != Recovery::Mode::Driving ||
			(std::fabs(angle) > 0.3 && std::hypot(car->_speed_x, car->_speed_y) < 1.0)) {
			recovery.previousTime = situation->currentTime;
			traffic.previousTime = situation->currentTime;
			car->ctrl = tCarCtrl{};
			car->ctrl.gear = car->_gear;
			car->ctrl.brakeCmd = 1.0f;
			return;
		}
		recovery.reset(situation->currentTime);
	} else if (recovery.driveIfNeeded(car, situation)) {
		driver.resumeAfterRecovery(situation->currentTime);
		traffic.reset(situation->currentTime);
		return;
	}
	traffic.drive(driver, car, situation);
}

static int
pitCommand(int, tCarElt* car, tSituation*)
{
	return pits.service(car);
}

static void
shutdown(int)
{
	currentTrack = nullptr;
	traffic.reset(0.0);
	pits = PitDriver{};
}

static int
initInterface(int index, void* pointer)
{
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
tutorial6(tModInfo* modInfo)
{
	for (int i = 0; i < 10; ++i) {
		modInfo[i] = tModInfo{};
	}
	modInfo[0].name = strdup("Tutorial 6");
	modInfo[0].desc = strdup("The complete tutorial racing driver");
	modInfo[0].fctInit = initInterface;
	modInfo[0].gfId = ROB_IDENT;
	modInfo[0].index = 1;
	return 0;
}
