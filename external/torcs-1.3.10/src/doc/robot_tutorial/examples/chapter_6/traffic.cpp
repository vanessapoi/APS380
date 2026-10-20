/***************************************************************************

    file                 : traffic.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#include <algorithm>
#include <cmath>
#include <robottools.h>
#include "traffic.h"

// The completed checkpoint includes passing; disable it only for the following exercise.
static constexpr bool ENABLE_PASSING = true;
static constexpr double MIN_GAP = 5.0;             // metres between footprints
static constexpr double FOLLOW_TIME = 1.0;         // seconds
static constexpr double SIDE_GAP = 1.2;            // metres between footprints
static constexpr double ROAD_MARGIN = 1.2;         // metres outside our footprint
static constexpr double OFFSET_RATE = 0.8;         // metres per second
static constexpr double PREDICTION_TIME = 3.0;      // seconds, constant-speed estimate
static constexpr double FOLLOW_DECELERATION = 3.0; // m/s^2, allowance for an uncertain leader
static constexpr double LATERAL_RESPONSE = 0.6;    // seconds of drift allowance / damping
static constexpr double HOLD_TIME = 1.0;           // seconds before reconsidering a cancelled manoeuvre
static constexpr double CLEAR_REJOIN_SPEED = 2.0;  // m/s, finish centering after space becomes available

double
wrappedDistance(double distance, double length)
{
	return length > 0.0 ? std::remainder(distance, length) : distance;
}

TrafficCar
describeCar(tCarElt* car)
{
	TrafficCar result;
	result.car = car;
	const double tangent = RtTrackSideTgAngleL(&car->_trkPos);
	const double angle = car->_yaw - tangent;
	const double c = std::fabs(std::cos(angle));
	const double s = std::fabs(std::sin(angle));
	result.along = car->_trkPos.seg->lgfromstart + segmentProgress(car->_trkPos);
	result.lateral = car->_trkPos.toMiddle;
	result.speed = car->_speed_X * std::cos(tangent) + car->_speed_Y * std::sin(tangent);
	result.lateralSpeed = -car->_speed_X * std::sin(tangent) + car->_speed_Y * std::cos(tangent);
	result.halfLength = 0.5 * (car->_dimension_x * c + car->_dimension_y * s);
	result.halfWidth = 0.5 * (car->_dimension_x * s + car->_dimension_y * c);
	return result;
}

double
approach(double value, double target, double maximumChange)
{
	const double change = std::max(0.0, maximumChange);
	return value + std::max(-change, std::min(change, target - value));
}

bool
offsetTarget(tCarElt* car, double offset, int count, double length, Vector2& target)
{
	const tTrackSeg* segment = car->_trkPos.seg;
	double along = segmentProgress(car->_trkPos) +
		std::min(8.0 + 0.33 * std::max(0.0, double(car->_speed_x)), length * 0.5);
	for (int visited = 0; visited <= count && segment; ++visited) {
		if (segment->length > 0.0 && along <= segment->length) {
			double tangent = segment->angle[TR_ZS];
			if (segment->type != TR_STR && segment->radius > 0.0) {
				tangent += (segment->type == TR_LFT ? 1.0 : -1.0) * along / segment->radius;
			}
			target = centerlinePoint(segment, along) + Vector2{-std::sin(tangent), std::cos(tangent)} * offset;
			return true;
		}
		along -= std::max(0.0, double(segment->length));
		segment = segment->next;
	}
	return false;
}

void
applySpeedTarget(SpeedDriver& driver, tCarElt* car, double target, double brakeLimit)
{
	if (car->_speed_x < -0.3) {
		return; // Chapter 4 already brakes before requesting a forward gear.
	}
	driver.applySpeedTarget(car, std::min(driver.targetSpeed, target), brakeLimit);
}

void
TrafficPlanner::reset(double time)
{
	mode = Mode::Cruising;
	opponents.clear();
	passingCar = nullptr;
	offset = passOffset = 0.0;
	holdOffset = holdUntil = 0.0;
	previousTime = time;
	speedLimit = 0.0;
	nearby = emergency = false;
	corridorAvailable = true;
}

void
TrafficPlanner::observe(tCarElt* car, tSituation* situation, double trackLength)
{
	self = describeCar(car);
	opponents.clear();
	nearby = false;
	for (int i = 0; i < situation->_ncars; ++i) {
		tCarElt* other = situation->cars[i];
		if (other == car || (other->_state & RM_CAR_STATE_NO_SIMU)) {
			continue;
		}
		TrafficCar observation = describeCar(other);
		observation.along = wrappedDistance(observation.along - self.along, trackLength);
		// Keep the whole field: fixed distance windows can hide a stopped leader
		// at racing speed or a fast rear car during the six-second pit merge.
		opponents.push_back(observation);
		if (std::fabs(observation.along) < 18.0 &&
			std::fabs(observation.lateral - self.lateral) < self.halfWidth + observation.halfWidth + 3.0) {
			nearby = true;
		}
	}
}

bool
TrafficPlanner::corridorFree(double target, const tCarElt* except, double seconds) const
{
	const double drift = self.lateral + LATERAL_RESPONSE * self.lateralSpeed;
	const double low = std::min({self.lateral, target, drift}) - self.halfWidth - SIDE_GAP;
	const double high = std::max({self.lateral, target, drift}) + self.halfWidth + SIDE_GAP;
	for (const TrafficCar& other : opponents) {
		if (other.car == except) {
			continue;
		}
		const double future = other.along + (other.speed - self.speed) * seconds;
		const double extent = self.halfLength + other.halfLength + MIN_GAP;
		const bool longitudinal = std::min(other.along, future) < extent &&
			std::max(other.along, future) > -extent;
		if (longitudinal && other.lateral + other.halfWidth > low &&
			other.lateral - other.halfWidth < high) {
			return false;
		}
	}
	return true;
}

void
TrafficPlanner::lateralBounds(double roadHalfWidth, double& low, double& high) const
{
	const double limit = std::max(0.0, roadHalfWidth - self.halfWidth - ROAD_MARGIN);
	low = -limit;
	high = limit;
	for (const TrafficCar& other : opponents) {
		if (std::fabs(other.along) < self.halfLength + other.halfLength + 4.0) {
			const double separation = self.halfWidth + other.halfWidth + SIDE_GAP;
			if (other.lateral >= self.lateral) {
				high = std::min(high, other.lateral - separation);
			} else {
				low = std::max(low, other.lateral + separation);
			}
		}
	}
}

void
TrafficPlanner::plan(double time, double freeSpeed, double roadHalfWidth,
	double currentHalfWidth, double narrowingDistance)
{
	const double elapsed = std::max(0.0, std::min(0.1, time - previousTime));
	previousTime = time;
	speedLimit = freeSpeed;
	emergency = false;
	corridorAvailable = true;
	if (currentHalfWidth < 0.0) {
		currentHalfWidth = roadHalfWidth;
	}
	const double roadLimit = std::max(0.0, roadHalfWidth - self.halfWidth - ROAD_MARGIN);
	double low, high;
	lateralBounds(roadHalfWidth, low, high);
	double currentLow, currentHigh;
	lateralBounds(currentHalfWidth, currentLow, currentHigh);
	const TrafficCar* leader = nullptr;
	const TrafficCar* focus = nullptr;
	for (const TrafficCar& other : opponents) {
		if (other.car == passingCar) {
			focus = &other;
		}
		const bool overlap = std::fabs(other.lateral - self.lateral) < self.halfWidth + other.halfWidth + SIDE_GAP;
		if (other.along > 0.0 && overlap && (!leader || other.along < leader->along)) {
			leader = &other;
		}
	}
	if (mode == Mode::Passing && (!focus ||
		focus->along + focus->halfLength + self.halfLength < -8.0)) {
		mode = Mode::Returning;
		passingCar = nullptr;
	}
	if (mode != Mode::Passing && mode != Mode::Returning && mode != Mode::Holding) {
		mode = leader ? Mode::Following : Mode::Cruising;
		if (ENABLE_PASSING && leader && freeSpeed - leader->speed > 1.5 && leader->along > 18.0) {
			const double separation = self.halfWidth + leader->halfWidth + SIDE_GAP + 0.5;
			const double passTime = std::max(PREDICTION_TIME, separation / OFFSET_RATE + 1.0);
			const double passDistance = std::max(70.0, std::max(0.0, self.speed - leader->speed) * passTime + MIN_GAP);
			const double candidates[] = {leader->lateral + separation, leader->lateral - separation};
			for (double candidate : candidates) {
				if (leader->along < passDistance && candidate >= low && candidate <= high && corridorFree(candidate, leader->car, passTime)) {
					passOffset = candidate;
					passingCar = leader->car;
					mode = Mode::Passing;
					break;
				}
			}
		}
	}
	if (mode == Mode::Holding && time >= holdUntil && std::fabs(self.lateralSpeed) < 0.3 && low <= high) {
		const double returning = std::max(low, std::min(high, 0.0));
		if (corridorFree(returning, nullptr, PREDICTION_TIME)) {
			mode = Mode::Returning;
		}
	}
	double wanted = mode == Mode::Passing ? passOffset : 0.0;
	if (mode == Mode::Passing && focus && focus->along > 18.0 &&
		(focus->speed > freeSpeed + 2.0 || std::fabs(passOffset) > roadLimit)) {
		// The opportunity has gone. Return only if the swept lateral corridor is free.
		if (corridorFree(0.0, nullptr, PREDICTION_TIME)) {
			mode = Mode::Returning;
			passingCar = nullptr;
			wanted = 0.0;
		}
	}
	if (mode != Mode::Holding) {
		wanted = std::max(low, std::min(high, wanted));
		const double next = approach(offset, wanted, OFFSET_RATE * elapsed);
		const tCarElt* except = mode == Mode::Passing ? passingCar : nullptr;
		// The leader exemption is valid only if the constrained passing lane still clears it.
		bool clearsLeader = true;
		for (const TrafficCar& other : opponents) {
			if (other.car == except && std::fabs(wanted - other.lateral) <
				self.halfWidth + other.halfWidth + SIDE_GAP) {
				clearsLeader = false;
			}
		}
		// Validate after ALL constraints, including the actual rate-limited next target.
		// Staying in the same lane behind a leader is handled by following-speed control.
		const bool movingSideways = std::fabs(wanted - self.lateral) > 0.15 ||
			std::fabs(next - self.lateral) > 0.15 || std::fabs(self.lateralSpeed) > 0.3;
		if (low <= high && currentLow <= currentHigh && next >= currentLow && next <= currentHigh && clearsLeader &&
			(!movingSideways || (corridorFree(wanted, except, PREDICTION_TIME) &&
			corridorFree(next, except, PREDICTION_TIME)))) {
			offset = next;
		} else {
			mode = Mode::Holding;
			passingCar = nullptr;
			holdOffset = self.lateral;
			holdUntil = time + HOLD_TIME;
		}
	}
	if (mode == Mode::Holding) {
		// Withdraw the stale target immediately. Freezing it would keep steering toward it.
		// Anchor the hold to the entry position; do not chase the car's continuing drift.
		const double currentLimit = std::max(0.0, currentHalfWidth - self.halfWidth - ROAD_MARGIN);
		const double damped = holdOffset - LATERAL_RESPONSE * self.lateralSpeed;
		double hold = std::max(currentLow, std::min(currentHigh, damped));
		corridorAvailable = currentLow <= currentHigh && corridorFree(hold, nullptr, PREDICTION_TIME);
		if (!corridorAvailable) {
			// No checked lateral alternative: oppose drift in our present lane, not in the old target lane.
			hold = std::max(-currentLimit, std::min(currentLimit, self.lateral - LATERAL_RESPONSE * self.lateralSpeed));
			// An occupied starting corridor can reject even a move away from an
			// adjacent car. Never let the fallback steer back into that car's bounds.
			if (currentLow <= currentHigh) {
				hold = std::max(currentLow, std::min(currentHigh, hold));
			}
			corridorAvailable = currentLow <= currentHigh && hold >= currentLow && hold <= currentHigh &&
				corridorFree(hold, nullptr, PREDICTION_TIME);
		}
		offset = hold;
	}
	// Keep this bound while returning, too: a safe destination is not an instant lane change.
	// The intermediate target may use the present road width; slow before the narrower boundary.
	if ((currentHalfWidth > roadHalfWidth && std::fabs(self.lateral) > roadLimit) || low > high) {
		const double distance = currentHalfWidth > roadHalfWidth ? narrowingDistance : 0.0;
		const double available = std::max(0.0, distance - MIN_GAP - 0.5 * std::max(0.0, self.speed));
		speedLimit = std::min(speedLimit, std::sqrt(2.0 * FOLLOW_DECELERATION * available));
		if (available == 0.0) {
			// A cleared return must not get stranded merely outside the preferred margin.
			// Creep only if the actual projected body already fits the upcoming road.
			if (mode == Mode::Returning && corridorAvailable &&
				std::fabs(self.lateral) + self.halfWidth + 0.3 < roadHalfWidth) {
				speedLimit = std::min(freeSpeed, CLEAR_REJOIN_SPEED);
			} else {
				emergency = true;
			}
		}
	}
	if (mode == Mode::Returning && std::fabs(offset) < 0.05 && std::fabs(self.lateral) < 0.5) {
		mode = leader ? Mode::Following : Mode::Cruising;
	}
	// Check cars ahead throughout the current-to-target corridor, including residual drift.
	// A rear approaching car alone does not request braking in front of it.
	const double drift = self.lateral + LATERAL_RESPONSE * self.lateralSpeed;
	const double corridorLow = std::min({self.lateral, offset, drift}) - self.halfWidth - SIDE_GAP;
	const double corridorHigh = std::max({self.lateral, offset, drift}) + self.halfWidth + SIDE_GAP;
	for (const TrafficCar& other : opponents) {
		if (other.along <= 0.0 || other.lateral + other.halfWidth <= corridorLow ||
			other.lateral - other.halfWidth >= corridorHigh) {
			continue;
		}
		const double gap = other.along - self.halfLength - other.halfLength;
		const double desired = MIN_GAP + FOLLOW_TIME * std::max(0.0, self.speed);
		const double following = std::max(0.0, other.speed + 0.5 * (gap - desired));
		const double stoppedBound = std::sqrt(2.0 * FOLLOW_DECELERATION * std::max(0.0, gap - MIN_GAP));
		// Matching a moving leader uses its speed; a stopped leader uses the stop bound.
		const double brakingBound = std::sqrt(std::max(0.0, other.speed) * std::max(0.0, other.speed) +
			stoppedBound * stoppedBound);
		speedLimit = std::min(speedLimit, std::min(following, brakingBound));
		if (gap < MIN_GAP) {
			speedLimit = 0.0;
			emergency = true;
		}
	}
}

void
TrafficPlanner::drive(SpeedDriver& driver, tCarElt* car, tSituation* situation)
{
	driver.drive(car, situation);
	// Reserve space over at least six seconds of travel, not a low-speed-only window.
	double halfWidth = car->_trkPos.seg->width / 2.0;
	const double roadHorizon = std::min(driver.trackLength, std::max(80.0, 6.0 * std::max(0.0, double(car->_speed_x))));
	double narrowingDistance = roadHorizon;
	double distance = car->_trkPos.seg->length - segmentProgress(car->_trkPos);
	const tTrackSeg* segment = car->_trkPos.seg->next;
	for (int i = 1; i < driver.segmentCount && segment && distance < roadHorizon; ++i, segment = segment->next) {
		if (segment->width / 2.0 < halfWidth) {
			narrowingDistance = std::min(narrowingDistance, distance);
			halfWidth = segment->width / 2.0;
		}
		distance += std::max(0.0, double(segment->length));
	}
	plan(situation->currentTime, driver.targetSpeed, halfWidth, car->_trkPos.seg->width / 2.0, narrowingDistance);
	if (car->_speed_x < -0.3) {
		return;
	}
	Vector2 target;
	if (offsetTarget(car, offset, driver.segmentCount, driver.trackLength, target)) {
		car->ctrl.steer = static_cast<tdble>(steerToward(car, target));
	}
	if (speedLimit < driver.targetSpeed) {
		applySpeedTarget(driver, car, speedLimit, 1.0);
	}
	if (emergency) {
		car->ctrl.accelCmd = 0.0f;
		car->ctrl.brakeCmd = static_cast<tdble>(driver.filterABS(car, 1.0));
	}
}
