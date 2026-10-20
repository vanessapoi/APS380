/***************************************************************************

    file                 : recovery3.cpp
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
#include <tgf.h>
#include <robottools.h>
#include "recovery3.h"

// Change one setting at a time for the chapter's experiments.
static constexpr double STUCK_DELAY = 2.0;       // seconds
static constexpr double SLOW_SPEED = 1.0;        // meters per second
static constexpr double ENTRY_ANGLE = 15.0;      // degrees
static constexpr double EXIT_ANGLE = 10.0;       // degrees
static constexpr double NEAR_BARRIER = 0.25;    // meters
static constexpr double TURNING_SPACE = 0.8;    // meters, teaching margin

BarrierClearance
measureClearance(tCarElt* car)
{
	BarrierClearance clearance;
	for (int i = 0; i < 4; ++i) {
		tTrkLocPos corner{};
		RtTrackGlobal2Local(car->_trkPos.seg, car->_corner_x(i),
			car->_corner_y(i), &corner, TR_LPOS_TRACK);
		clearance.left = std::min(clearance.left, double(corner.toLeft));
		clearance.right = std::min(clearance.right, double(corner.toRight));
		const double space = std::min(corner.toLeft, corner.toRight);
		if (i == FRNT_LFT || i == FRNT_RGT) {
			clearance.front = std::min(clearance.front, space);
		} else {
			clearance.rear = std::min(clearance.rear, space);
		}
	}
	return clearance;
}

static tdble
limitedSteering(double value)
{
	return static_cast<tdble>(std::max(-1.0, std::min(1.0, value)));
}

// Brake with straight wheels before changing direction; recover at low speed.
void
moveSlowly(tCarElt* car, int direction, double steer)
{
	car->ctrl = tCarCtrl{};
	if (direction * car->_speed_x < -0.3) {
		car->ctrl.gear = car->_gear;
		car->ctrl.brakeCmd = 0.8f;
		return;
	}
	car->ctrl.steer = limitedSteering(steer);
	car->ctrl.gear = direction;
	if (std::hypot(car->_speed_x, car->_speed_y) > 3.0) {
		car->ctrl.brakeCmd = 0.3f;
	} else {
		car->ctrl.accelCmd = 0.3f;
	}
}

void
Recovery::reset(double time)
{
	mode = Mode::Driving;
	stuckTime = 0.0;
	previousTime = time;
}

bool
Recovery::driveIfNeeded(tCarElt* car, tSituation* situation)
{
	const double elapsed = std::max(0.0, situation->currentTime - previousTime);
	previousTime = situation->currentTime;
	double angle = RtTrackSideTgAngleL(&car->_trkPos) - car->_yaw;
	NORM_PI_PI(angle);
	const BarrierClearance clearance = measureClearance(car);
	const double speed = std::hypot(car->_speed_x, car->_speed_y);

	if (mode == Mode::Driving) {
		const bool misplaced = std::fabs(angle) > ENTRY_ANGLE * PI / 180.0 ||
			clearance.minimum() < NEAR_BARRIER;
		if (situation->currentTime >= 0.0 && speed < SLOW_SPEED && misplaced) {
			stuckTime += elapsed;
		} else {
			stuckTime = 0.0;
		}
		if (stuckTime >= STUCK_DELAY) {
			const bool leftBarrier = clearance.left < clearance.right;
			const bool pointsOut = leftBarrier ? std::sin(angle) < 0.0 : std::sin(angle) > 0.0;
			mode = pointsOut ? Mode::Backing : Mode::MovingForward;
		}
	}

	if (mode != Mode::Driving) {
		// Do not keep pushing a blocked end when the other end has space.
		if (mode == Mode::Backing && clearance.rear < 0.1 && clearance.front > clearance.rear + 0.2) {
			mode = Mode::MovingForward;
		} else if (mode == Mode::MovingForward && clearance.front < 0.1 && clearance.rear > clearance.front + 0.2) {
			mode = Mode::Backing;
		}

		const bool roomToTurn = clearance.minimum() >= TURNING_SPACE;
		const bool aligned = std::fabs(angle) < EXIT_ANGLE * PI / 180.0;
		if (roomToTurn && aligned) {
			mode = Mode::MovingForward;
			if (car->_speed_x >= -0.3) {
				mode = Mode::Driving;
				stuckTime = 0.0;
			}
		}

		if (mode != Mode::Driving) {
			int direction = mode == Mode::Backing ? -1 : 1;
			double steer = direction * angle / car->_steerLock;
			if (!roomToTurn) {
				steer = 0.0;
				if (std::fabs(std::sin(angle)) < 0.15) {
					const bool leftBarrier = clearance.left < clearance.right;
					const bool reverseSeparates = leftBarrier ? std::sin(angle) < -0.01 : std::sin(angle) > 0.01;
					if (mode == Mode::Backing && !reverseSeparates) {
						mode = Mode::MovingForward;
					}
					if (mode == Mode::MovingForward) {
						// A gentle forward turn; never reverse this sign blindly.
						// A car facing against the road needs the opposite wheel angle.
						const double away = leftBarrier ? -0.1 : 0.1;
						steer = std::cos(angle) >= 0.0 ? away : -away;
					}
					// When backing already separates the car, keep the wheels straight.
				}
				direction = mode == Mode::Backing ? -1 : 1;
			}
			moveSlowly(car, direction, steer);
			return true;
		}
	}

	return false;
}
