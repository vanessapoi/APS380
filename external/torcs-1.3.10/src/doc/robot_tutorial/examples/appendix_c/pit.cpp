/***************************************************************************

    file                 : pit.cpp
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
#include <robot.h>
#include <robottools.h>
#include "pit.h"

// Each instance receives its demonstration-stop setting from configuration.
static constexpr int DEMONSTRATION_LAP = 1; // completed laps before requesting
static constexpr double BOX_TRAVEL_SPEED = 4.0;
static constexpr double FUEL_RESERVE = 0.5;       // litres
static constexpr int REPAIR_THRESHOLD = 3000;   // damage points

double
PitDriver::position(tCarElt* car) const
{
	return car->_trkPos.seg->lgfromstart + segmentProgress(car->_trkPos);
}

double
PitDriver::relative(double s) const
{
	double result = std::fmod(s - entry, length);
	return result < 0.0 ? result + length : result;
}

void
PitDriver::configure(tTrack* newTrack, tCarElt* car)
{
	*this = PitDriver{};
	track = newTrack;
	length = track->length;
	ownPit = car->_pit;
	const auto& p = track->pits;
	if (!ownPit || p.type != TR_PIT_ON_TRACK_SIDE || !p.pitEntry || !p.pitStart ||
		!p.pitEnd || !p.pitExit || length <= 0.0 || p.speedLimit <= 1.0) {
		GfOut("Tutorial C: no supported assigned pit; continuing ordinary driving.\n");
		return;
	}
	entry = p.pitEntry->lgfromstart;
	limitStart = relative(p.pitStart->lgfromstart);
	limitEnd = relative(p.pitEnd->lgfromstart + p.pitEnd->length);
	mergeStart = relative(p.pitEnd->next->lgfromstart + p.pitEnd->next->length);
	exit = relative(p.pitExit->lgfromstart);
	boxMin = relative(ownPit->lmin);
	boxMax = relative(ownPit->lmax);
	box = 0.5 * (boxMin + boxMax); // Match the engine's capture coordinates.
	const double sign = p.side == TR_LFT ? 1.0 : -1.0;
	boxOffset = sign * std::fabs(ownPit->pos.toMiddle);
	laneOffset = sign * std::max(0.0, std::fabs(boxOffset) - p.width);
	speedCap = double(p.speedLimit) - 1.0; // tracking margin below the legal limit
	// Coincident lane-ready/box-approach knots have the same value and slope:
	// represent them once, rather than create a zero-length spline interval.
	const double beforeBox = box - p.len;
	const double afterBox = box + p.len;
	mergeStart = std::max(mergeStart, afterBox + 1.0);
	const double laneReady = std::min(limitStart, beforeBox);
	if (!(laneReady > 30.0 && ownPit->lmin < ownPit->lmax && boxMin < boxMax && boxMin >= limitStart &&
		boxMax <= limitEnd && afterBox < mergeStart && mergeStart + 35.0 < exit && exit < length)) {
		GfOut("Tutorial C: pit geometry cannot form the supplied route; continuing ordinary driving.\n");
		return;
	}
	std::vector<SplineKnot> points{{0.0, 0.0, 0.0}, {laneReady, laneOffset, 0.0}};
	if (beforeBox - laneReady > 1e-4) {
		points.push_back({beforeBox, laneOffset, 0.0});
	}
	points.push_back({box, boxOffset, 0.0});
	points.push_back({afterBox, laneOffset, 0.0});
	points.push_back({mergeStart, laneOffset, 0.0});
	points.push_back({exit, 0.0, 0.0});
	available = route.setKnots(points);
	entryClearDistance = limitStart;
	for (double distance = 0.0; available && distance < limitStart; distance += 1.0) {
		if (std::fabs(route.value(distance)) > p.pitEntry->width / 2.0 + car->_dimension_y / 2.0 + 1.2) {
			entryClearDistance = distance;
			break;
		}
	}
	mergeRoute.setKnots({{mergeStart, laneOffset, 0.0}, {exit, 0.0, 0.0}});
}

bool
PitDriver::entryClear(tCarElt* car, tSituation* situation, double distanceToEntry) const
{
	const TrafficCar self = describeCar(car);
	const double plannedSpeed = std::min(std::max(0.0, self.speed), speedCap);
	const double horizon = (distanceToEntry + entryClearDistance) / std::max(2.0, speedCap) + 2.0;
	const double low = std::min(self.lateral, laneOffset) - self.halfWidth - 1.2;
	const double high = std::max(self.lateral, laneOffset) + self.halfWidth + 1.2;
	// Check the whole field here: an entry manoeuvre can outlast the normal racing lookahead.
	for (int i = 0; i < situation->_ncars; ++i) {
		tCarElt* otherCar = situation->cars[i];
		if (otherCar == car || (otherCar->_state & RM_CAR_STATE_NO_SIMU)) {
			continue;
		}
		const TrafficCar other = describeCar(otherCar);
		if (other.lateral + other.halfWidth <= low || other.lateral - other.halfWidth >= high) {
			continue;
		}
		const double extent = self.halfLength + other.halfLength + 5.0;
		const double separation = wrappedDistance(other.along - self.along, length);
		double behind = std::fmod(self.along - other.along + length, length);
		if (behind < 0.0) {
			behind += length;
		}
		if (std::fabs(separation) < extent ||
			(other.speed > plannedSpeed && behind < extent + (other.speed - plannedSpeed) * horizon)) {
			return false;
		}
	}
	return true;
}

double
PitDriver::estimatedFuelPerLap() const
{
	return fuelPerLap > 0.0 ? 1.15 * fuelPerLap : fallbackFuelPerLap;
}

void
PitDriver::updateStrategy(tCarElt* car)
{
	// newRace precedes the first published fuel update. Initialize here, not from zero in newRace.
	if (!fuelInitialized) {
		if (car->_fuel <= 0.0) {
			return;
		}
		previousFuel = car->_fuel;
		previousLap = car->_laps;
		fuelInitialized = true;
	}
	// Positive jumps are actual refuelling, not negative consumption. Requested
	// fuel is never added to the estimator: the engine may normalize that request.
	lapFuelUsed += std::max(0.0, previousFuel - car->_fuel);
	previousFuel = car->_fuel;
	if (car->_laps > previousLap) {
		if (previousLap >= 1) {
			fuelPerLap = std::max(fuelPerLap, lapFuelUsed);
		}
		lapFuelUsed = 0.0;
		previousLap = car->_laps;
	}
	if (!available || mode != Mode::Racing || (car->_state & RM_CAR_STATE_FINISH)) {
		return;
	}
	const double remaining = std::max(0.0, car->_remainingLaps + 1.0 - position(car) / length);
	const double estimate = estimatedFuelPerLap();
	const bool fuelNeeded = car->_fuel < 1.6 * estimate + FUEL_RESERVE &&
		car->_fuel < remaining * estimate + FUEL_RESERVE;
	const bool repairNeeded = car->_dammage > REPAIR_THRESHOLD && remaining > 1.0;
	const bool demonstrate = demonstrationStop && !demonstrationDone &&
		car->_laps - 1 >= DEMONSTRATION_LAP && remaining > 1.0;
	requested = requested || fuelNeeded || repairNeeded || demonstrate;
}

Vector2
PitDriver::targetPoint(tCarElt* car, double ahead, double lateral) const
{
	const tTrackSeg* seg = car->_trkPos.seg;
	double along = segmentProgress(car->_trkPos) + ahead;
	for (int i = 0; i <= track->nseg && seg; ++i, seg = seg->next) {
		if (seg->length > 0.0 && along <= seg->length) {
			double angle = seg->angle[TR_ZS];
			if (seg->type != TR_STR) {
				angle += (seg->type == TR_LFT ? 1.0 : -1.0) * along / seg->radius;
			}
			return centerlinePoint(seg, along) + Vector2{-std::sin(angle), std::cos(angle)} * lateral;
		}
		along -= std::max(0.0, double(seg->length));
	}
	return {car->_pos_X, car->_pos_Y};
}

int
PitDriver::service(tCarElt* car)
{
	const double remaining = std::max(0.0, car->_remainingLaps + 1.0 - position(car) / length);
	const double laps = stintLaps > 0.0 ? std::min(remaining + 0.5, stintLaps) : remaining + 0.5;
	const double desired = laps * estimatedFuelPerLap() + FUEL_RESERVE;
	car->_pitFuel = static_cast<tdble>(std::max(0.0, std::min(desired - car->_fuel, double(car->_tank - car->_fuel))));
	car->_pitRepair = std::max(0, car->_dammage);
	car->_pitStopType = RM_PIT_REPAIR;
	car->pitcmd.tireChange = tCarPitCmd::ALL;
	mode = Mode::Service;
	requested = false;
	demonstrationDone = true;
	++visits;
	return ROB_PIT_IM;
}

bool
PitDriver::drive(SpeedDriver& driver, TrafficPlanner& traffic, tCarElt* car, tSituation* situation)
{
	updateStrategy(car);
	const double s = position(car);
	if (mode == Mode::Racing) {
		double toEntry = entry - s;
		if (toEntry < 0.0) {
			toEntry += length;
		}
		const double speed = std::max(0.0, double(car->_speed_x));
		const double approachDistance = std::max(100.0, (speed * speed - speedCap * speedCap) / (2.0 * 4.0) + 20.0);
		if (!available || !requested || toEntry > approachDistance || ownPit->pitCarIndex != TR_PIT_STATE_FREE) {
			return false;
		}
		if (!entryClear(car, situation, toEntry)) {
			return false; // Keep racing rather than cut across alongside or closing traffic.
		}
		mode = Mode::Approach;
		progress = -toEntry;
		previousPosition = s;
		missedBox = false;
		mergeHolding = false;
		mergeRoute.setKnots({{mergeStart, laneOffset, 0.0}, {exit, 0.0, 0.0}});
		traffic.reset(situation->currentTime);
	}
	progress += wrappedDistance(s - previousPosition, length);
	previousPosition = s;
	if (mode == Mode::Service) {
		if (car->_state & RM_CAR_STATE_PIT) {
			car->ctrl = tCarCtrl{};
			car->ctrl.gear = 1;
			car->ctrl.brakeCmd = 1.0f;
			return true;
		}
		mode = Mode::Exit;
		driver.resumeAfterRecovery(situation->currentTime);
	}
	if (mode == Mode::Approach && progress >= 0.0) {
		mode = Mode::Lane;
	}
	if (mode == Mode::Lane && progress > box - 30.0) {
		mode = Mode::Stopping;
	}
	if (mode == Mode::Stopping && progress > boxMax) {
		// Never reverse blindly along the pit lane after missing the capture region.
		missedBox = true;
		mode = Mode::Exit;
	}
	const bool leaving = mode == Mode::Exit || mode == Mode::Merging;
	if (leaving && progress > mergeStart - 5.0) {
		mode = Mode::Merging;
	}
	traffic.observe(car, situation, length);
	double cap = std::min(speedCap, driver.chooseTargetSpeed(car));
	if (mode == Mode::Approach) {
		cap = std::min(driver.chooseTargetSpeed(car), std::sqrt(speedCap * speedCap + 2.0 * 4.0 * std::max(0.0, -progress - 20.0)));
	}
	double ahead = std::min(8.0, 2.5 + 0.25 * std::max(0.0, double(car->_speed_x)));
	double lateral = route.value(progress + ahead);
	if (mode == Mode::Lane || mode == Mode::Stopping) {
		const double remaining = std::max(0.0, box - progress - 0.5);
		cap = std::min(cap, std::sqrt(2.0 * 3.0 * remaining));
		if (remaining < 5.0) {
			cap = std::min(cap, std::min(BOX_TRAVEL_SPEED, 0.7 * remaining));
		}
		if (ownPit->pitCarIndex != TR_PIT_STATE_FREE) {
			cap = std::min(cap, std::max(0.0, 0.5 * (boxMin - progress - 5.0)));
		}
	}
	if (mode == Mode::Merging) {
		const bool clear = traffic.corridorFree(0.0, nullptr, 6.0);
		if (!clear && !mergeHolding) {
			mergeHolding = true;
			holdOffset = car->_trkPos.toMiddle;
		}
		if (clear && mergeHolding && std::fabs(traffic.self.lateralSpeed) < 0.3 && exit - progress > 25.0) {
			mergeHolding = false;
			mergeRoute.setKnots({{progress, double(car->_trkPos.toMiddle), 0.0}, {exit, 0.0, 0.0}});
		}
		if (mergeHolding) {
			lateral = holdOffset - 0.6 * traffic.self.lateralSpeed;
			cap = std::min(cap, std::max(0.0, 0.5 * (exit - progress - 30.0)));
		} else {
			lateral = mergeRoute.value(progress + ahead);
		}
		if (progress >= mergeStart && roadClearance(car) > 1.2) {
			mode = Mode::Racing;
			traffic.reset(situation->currentTime);
			traffic.offset = car->_trkPos.toMiddle;
			traffic.mode = TrafficPlanner::Mode::Returning;
			requested = missedBox;
			return false;
		}
	}
	// Pit route owns lateral motion. Ordinary main-road edge/side clamps do not apply here.
	car->ctrl = tCarCtrl{};
	if (car->_speed_x < -0.3) {
		car->ctrl.gear = car->_gear;
		car->ctrl.brakeCmd = 0.8f;
		return true;
	}
	car->ctrl.gear = driver.chooseGear(car, situation->currentTime);
	car->ctrl.steer = static_cast<tdble>(steerToward(car, targetPoint(car, ahead, lateral)));
	// Retain front-traffic restrictions along the pit route, without changing its target.
	for (const auto& other : traffic.opponents) {
		const double low = std::min(double(car->_trkPos.toMiddle), lateral) - traffic.self.halfWidth - 1.2;
		const double high = std::max(double(car->_trkPos.toMiddle), lateral) + traffic.self.halfWidth + 1.2;
		if (other.along > 0.0 && other.lateral + other.halfWidth > low && other.lateral - other.halfWidth < high) {
			const double gap = other.along - traffic.self.halfLength - other.halfLength;
			cap = std::min(cap, std::max(0.0, other.speed + 0.5 * (gap - 5.0 - std::max(0.0, traffic.self.speed))));
		}
	}
	driver.targetSpeed = std::max(0.0, cap);
	applySpeedTarget(driver, car, cap, 1.0);
	if (mode == Mode::Lane || mode == Mode::Stopping) {
		car->ctrl.raceCmd |= RM_CMD_PIT_ASKED;
	}
	return true;
}
