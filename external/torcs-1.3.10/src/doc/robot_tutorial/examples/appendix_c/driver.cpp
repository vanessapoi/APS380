/***************************************************************************

    file                 : driver.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#include <cmath>
#include <robottools.h>
#include "driver.h"

TutorialDriver::TutorialDriver(int robotIndex) : index(robotIndex)
{
}

void
TutorialDriver::initTrack(tTrack* track, void* carSettings, void** settings)
{
	// Reset only this instance; another selected robot may already be initialized.
	activeCar = nullptr;
	speed = SpeedDriver{};
	recovery = Recovery{};
	traffic = TrafficPlanner{};
	pits = PitDriver{};
	currentTrack = track;
	*settings = loadSettings(index, track, carSettings, configuration);
}

void
TutorialDriver::newRace(tCarElt* car, tSituation* situation)
{
	if (!currentTrack) {
		return;
	}
	activeCar = car;
	speed.configure(currentTrack, car);
	recovery.reset(situation->currentTime);
	traffic.reset(situation->currentTime);
	pits.configure(currentTrack, car);
	configuration.apply(speed, pits);
	GfOut("Tutorial C[%d] effective: fuel=%.3f l, rear wing=%.3f deg\n",
		index, GfParmGetNum(car->_carHandle, SECT_CAR, PRM_FUEL, "l", 0.0f),
		GfParmGetNum(car->_carHandle, SECT_REARWING, PRM_WINGANGLE, "deg", 0.0f));
}

void
TutorialDriver::drive(tCarElt* car, tSituation* situation)
{
	if (!currentTrack || car != activeCar) {
		car->ctrl = tCarCtrl{};
		car->ctrl.brakeCmd = 1.0f;
		return;
	}
	// The pit state machine owns approach, intentional stopping, service and exit.
	traffic.observe(car, situation, speed.trackLength);
	const bool travellingInPits = pits.mode == PitDriver::Mode::Approach ||
		pits.mode == PitDriver::Mode::Lane || pits.mode == PitDriver::Mode::Exit;
	if (travellingInPits && !traffic.nearby && recovery.driveIfNeeded(car, situation)) {
		speed.resumeAfterRecovery(situation->currentTime);
		traffic.reset(situation->currentTime);
		return;
	}
	if (pits.drive(speed, traffic, car, situation)) {
		if (!travellingInPits || traffic.nearby) {
			recovery.reset(situation->currentTime);
		}
		return;
	}
	traffic.observe(car, situation, speed.trackLength);
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
		speed.resumeAfterRecovery(situation->currentTime);
		traffic.reset(situation->currentTime);
		return;
	}
	traffic.drive(speed, car, situation);
}

int
TutorialDriver::pitCommand(tCarElt* car)
{
	return car == activeCar ? pits.service(car) : ROB_PIT_IM;
}
