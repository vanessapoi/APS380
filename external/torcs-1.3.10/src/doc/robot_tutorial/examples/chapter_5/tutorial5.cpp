/***************************************************************************

    file                 : tutorial5.cpp
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
#include "recovery4.h"
#include "traffic5.h"

static tTrack* currentTrack = nullptr;
static SpeedDriver driver;
static Recovery recovery;
static TrafficPlanner traffic;

static void
initTrack(int, tTrack* track, void*, void** settings, tSituation*)
{
	currentTrack = track;
	*settings = nullptr;
}

static void
newRace(int, tCarElt* car, tSituation* situation)
{
	driver.configure(currentTrack, car);
	recovery.reset(situation->currentTime);
	traffic.reset(situation->currentTime);
}

static void
drive(int, tCarElt* car, tSituation* situation)
{
	traffic.observe(car, situation, driver.trackLength);
	if (traffic.nearby) {
		double angle = RtTrackSideTgAngleL(&car->_trkPos) - car->_yaw;
		NORM_PI_PI(angle);
		if (recovery.mode != Recovery::Mode::Driving ||
			(std::fabs(angle) > 0.3 && std::hypot(car->_speed_x, car->_speed_y) < 1.0)) {
			// Pause an awkward recovery while another car occupies nearby space.
			recovery.previousTime = situation->currentTime;
			traffic.previousTime = situation->currentTime;
			car->ctrl = tCarCtrl{};
			car->ctrl.gear = car->_gear;
			car->ctrl.brakeCmd = 1.0f;
			return;
		}
		recovery.reset(situation->currentTime); // Waiting in traffic is not a stuck timer.
	} else if (recovery.driveIfNeeded(car, situation)) {
		driver.resumeAfterRecovery(situation->currentTime);
		traffic.reset(situation->currentTime);
		return;
	}
	traffic.drive(driver, car, situation);
}

static void
shutdown(int)
{
	currentTrack = nullptr;
	traffic.reset(0.0);
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
tutorial5(tModInfo* modInfo)
{
	for (int i = 0; i < 10; ++i) {
		modInfo[i] = tModInfo{};
	}
	modInfo[0].name = strdup("Tutorial 5");
	modInfo[0].desc = strdup("Following and overtaking");
	modInfo[0].fctInit = initInterface;
	modInfo[0].gfId = ROB_IDENT;
	modInfo[0].index = 1;
	return 0;
}
