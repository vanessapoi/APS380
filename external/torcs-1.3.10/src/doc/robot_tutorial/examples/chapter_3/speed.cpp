/***************************************************************************

    file                 : speed.cpp
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
#include <cstring>
#include <tgf.h>
#include <robottools.h>
#include "speed.h"

// Main chapter: change one setting at a time.
static constexpr double CORNER_MARGIN = 0.90;     // allowance for path/model error
static constexpr double GRIP_RESERVE = 0.85;      // allowance for the simplified tyre model
static constexpr double BRAKE_USAGE = 0.70;       // fraction of model deceleration used for planning
static constexpr double BRAKE_MARGIN = 5.0;       // meters
static constexpr double RESPONSE_TIME = 0.4;      // seconds
static constexpr double SHIFT_UP = 0.88;          // fraction of engine red line
static constexpr double SHIFT_DOWN = 0.75;        // maximum predicted fraction in the lower gear
static constexpr double SHIFT_DELAY = 0.7;        // seconds between gear requests

// Optional readings: change these to compare the supplied implementations.
static constexpr bool AERO_CORNERS = true;
static constexpr BrakingModel BRAKING_MODEL = BrakingModel::AeroAnalytical;
static constexpr bool ENABLE_ABS = true;
static constexpr bool ENABLE_TRACTION_CONTROL = true;

static double
clampUnit(double value)
{
	return std::max(0.0, std::min(1.0, value));
}

static double
distanceToSegmentEnd(const tTrkLocPos& position)
{
	const tTrackSeg* segment = position.seg;
	const double remaining = segment->type == TR_STR ?
		segment->length - position.toStart :
		(segment->arc - position.toStart) * segment->radius;
	return std::max(0.0, std::min(double(segment->length), remaining));
}

void
SpeedDriver::configure(tTrack* track, tCarElt* car)
{
	segmentCount = std::max(1, track->nseg);
	trackLength = track->length;
	lastShiftTime = -10.0;
	requestedGear = 1;
	targetSpeed = 0.0;
	dryMass = GfParmGetNum(car->_carHandle, SECT_CAR, PRM_MASS, nullptr, 1000.0f);

	const char* wheels[] = {SECT_FRNTRGTWHEEL, SECT_FRNTLFTWHEEL,
		SECT_REARRGTWHEEL, SECT_REARLFTWHEEL};
	tyreGrip = 100.0;
	double heightSum = 0.0;
	for (const char* wheel : wheels) {
		tyreGrip = std::min(tyreGrip, double(GfParmGetNum(car->_carHandle, wheel, PRM_MU, nullptr, 1.0f)));
		heightSum += GfParmGetNum(car->_carHandle, wheel, PRM_RIDEHEIGHT, nullptr, 0.2f);
	}
	tyreGrip = std::max(0.0, tyreGrip);
	minimumSurfaceGrip = std::max(0.0, double(track->seg->surface->kFriction));
	tTrackSeg* segment = track->seg;
	for (int i = 0; i < segmentCount && segment; ++i, segment = segment->next) {
		minimumSurfaceGrip = std::min(minimumSurfaceGrip, std::max(0.0, double(segment->surface->kFriction)));
	}

	const double cx = GfParmGetNum(car->_carHandle, SECT_AERODYNAMICS, PRM_CX, nullptr, 0.4f);
	const double area = GfParmGetNum(car->_carHandle, SECT_AERODYNAMICS, PRM_FRNTAREA, nullptr, 2.5f);
	const double lift = GfParmGetNum(car->_carHandle, SECT_AERODYNAMICS, PRM_FCL, nullptr, 0.0f) +
		GfParmGetNum(car->_carHandle, SECT_AERODYNAMICS, PRM_RCL, nullptr, 0.0f);
	const double heightFactor = 2.0 * std::exp(-3.0 * std::pow(1.5 * heightSum, 4));
	downforce = heightFactor * lift;
	drag = 0.645 * cx * area;
	for (const char* wing : {SECT_FRNTWING, SECT_REARWING}) {
		const double wingArea = GfParmGetNum(car->_carHandle, wing, PRM_WINGAREA, nullptr, 0.0f);
		const double wingAngle = GfParmGetNum(car->_carHandle, wing, PRM_WINGANGLE, nullptr, 0.0f);
		const double contribution = 1.23 * wingArea * std::sin(wingAngle);
		downforce += 4.0 * contribution;
		drag += contribution;
	}
	drag = std::max(0.0, drag);
	const char* layout = GfParmGetStr(car->_carHandle, SECT_DRIVETRAIN, PRM_TYPE, VAL_TRANS_RWD);
	drivenWheels = std::strcmp(layout, VAL_TRANS_FWD) == 0 ? DrivenWheels::Front :
		(std::strcmp(layout, VAL_TRANS_4WD) == 0 ? DrivenWheels::All : DrivenWheels::Rear);
	// Bound the search by the car's gearing, not a teaching speed limit.
	speedBound = 0.0;
	const double radius = car->_wheelRadius(drivenWheels == DrivenWheels::Front ? FRNT_RGT : REAR_RGT);
	for (int gear = 1; gear < car->_gearNb; ++gear) {
		const int index = gear + car->_gearOffset;
		if (index >= 0 && index < MAX_GEARS && car->_gearRatio[index] > 0.0) {
			speedBound = std::max(speedBound, double(car->_enginerpmRedLine) * radius / car->_gearRatio[index]);
		}
	}
}

void
SpeedDriver::resumeAfterRecovery(double time)
{
	requestedGear = 1;
	lastShiftTime = time;
}

double
SpeedDriver::speedForSegment(tCarElt* car, tTrackSeg* segment) const
{
	const double mass = std::max(1.0, dryMass + car->_fuel);
	const double grip = std::max(0.0, double(segment->surface->kFriction)) * tyreGrip * GRIP_RESERVE;
	const double lift = AERO_CORNERS ? downforce : 0.0;
	double cap = std::max(speedBound, double(car->_speed_x));
	if (lift < 0.0) {
		cap = std::min(cap, 0.9 * std::sqrt(mass * 9.81 / -lift));
	}
	if (segment->type == TR_STR) {
		return cap;
	}
	// Apply the margin to the uncapped model speed, then the driving cap.
	return std::min(cap, CORNER_MARGIN * cornerSpeed(segment->radius, grip, mass, lift, cap / CORNER_MARGIN));
}

double
SpeedDriver::chooseTargetSpeed(tCarElt* car) const
{
	tTrackSeg* segment = car->_trkPos.seg;
	const double grip = minimumSurfaceGrip * tyreGrip * GRIP_RESERVE;
	const double mass = std::max(1.0, dryMass + car->_fuel);
	const double a0 = BRAKE_USAGE * grip * 9.81;
	const double b = BRAKING_MODEL == BrakingModel::Basic ? 0.0 :
		BRAKE_USAGE * (grip * downforce + drag) / mass;
	const double speed = std::max(0.0, double(car->_speed_x));
	const double margin = BRAKE_MARGIN + RESPONSE_TIME * speed;
	const double fastest = std::max(speed, speedBound);
	const double weakest = std::min(a0, a0 + b * fastest * fastest);
	const double horizon = weakest > 0.0 ?
		std::min(trackLength, fastest * fastest / (2.0 * weakest) + margin) : trackLength;
	double target = speedForSegment(car, segment);
	double distance = distanceToSegmentEnd(car->_trkPos);
	tTrackSeg* start = segment;
	segment = segment->next;
	for (int i = 1; i < segmentCount && segment && segment != start && distance <= horizon; ++i) {
		const double upcoming = speedForSegment(car, segment);
		const double allowed = allowedApproachSpeed(upcoming, std::max(0.0, distance - margin),
			a0, b, BRAKING_MODEL, fastest);
		target = std::min(target, allowed);
		distance += std::max(0.0, double(segment->length));
		segment = segment->next;
	}
	return target;
}

static double
gearRatio(tCarElt* car, int gear)
{
	const int index = gear + car->_gearOffset;
	if (gear < 1 || gear >= car->_gearNb || index < 0 || index >= MAX_GEARS) {
		return 0.0;
	}
	return car->_gearRatio[index];
}

int
SpeedDriver::chooseGear(tCarElt* car, double time)
{
	if (car->_gear < 1) {
		requestedGear = 1;
		return requestedGear;
	}
	if (car->_gear != requestedGear || time - lastShiftTime < SHIFT_DELAY) {
		return requestedGear;
	}
	const int gear = car->_gear;
	const double ratio = gearRatio(car, gear);
	const double radius = car->_wheelRadius(drivenWheels == DrivenWheels::Front ? FRNT_RGT : REAR_RGT);
	if (ratio <= 0.0 || radius <= 0.0 || car->_enginerpmRedLine <= 0.0) {
		return gear;
	}
	const double wheelSpeed = std::max(0.0, double(car->_speed_x)) / radius;
	const double redLine = car->_enginerpmRedLine; // rad/s, despite the member's name
	if (gearRatio(car, gear + 1) > 0.0 && car->_enginerpm > SHIFT_UP * redLine &&
		wheelSpeed * ratio > 0.80 * redLine) {
		requestedGear = gear + 1;
	} else if (gear > 1 && gearRatio(car, gear - 1) > 0.0 &&
		car->_enginerpm < 0.55 * redLine && wheelSpeed * gearRatio(car, gear - 1) < SHIFT_DOWN * redLine) {
		requestedGear = gear - 1;
	}
	if (requestedGear != gear) {
		lastShiftTime = time;
	}
	return requestedGear;
}

double
SpeedDriver::filterABS(tCarElt* car, double brake) const
{
	if (!ENABLE_ABS || car->_speed_x < 3.0) {
		return brake;
	}
	double rollingRatio = 0.0;
	for (int i = 0; i < 4; ++i) {
		rollingRatio += car->_wheelSpinVel(i) * car->_wheelRadius(i) / car->_speed_x;
	}
	rollingRatio /= 4.0;
	return rollingRatio < 0.9 ? brake * clampUnit(rollingRatio) : brake;
}

double
SpeedDriver::filterTraction(tCarElt* car, double throttle) const
{
	if (!ENABLE_TRACTION_CONTROL || car->_speed_x < 0.0) {
		return throttle;
	}
	double drivenSpeed = 0.0;
	int count = 0;
	for (int i = 0; i < 4; ++i) {
		const bool front = i == FRNT_RGT || i == FRNT_LFT;
		if (drivenWheels == DrivenWheels::All ||
			(front && drivenWheels == DrivenWheels::Front) || (!front && drivenWheels == DrivenWheels::Rear)) {
			drivenSpeed += car->_wheelSpinVel(i) * car->_wheelRadius(i);
			++count;
		}
	}
	drivenSpeed /= count;
	// Reduce progressively rather than alternating full power and zero power.
	const double slip = drivenSpeed - car->_speed_x;
	return std::max(0.0, throttle - std::max(0.0, slip - 2.0) / 10.0);
}

void
SpeedDriver::applySpeedTarget(tCarElt* car, double target, double brakeLimit)
{
	targetSpeed = std::max(0.0, target);
	const double error = targetSpeed - car->_speed_x;
	const double throttle = error > 0.3 ? clampUnit(0.12 + 0.18 * error) : 0.0;
	double brake = error < -0.35 ? std::min(clampUnit(brakeLimit), 0.18 * (-error - 0.35)) : 0.0;
	if (targetSpeed < 0.1 && std::fabs(car->_speed_x) < 1.0) {
		brake = std::max(brake, 0.4);
	}
	car->ctrl.accelCmd = static_cast<tdble>(clampUnit(filterTraction(car, throttle)));
	car->ctrl.brakeCmd = static_cast<tdble>(clampUnit(filterABS(car, brake)));
}

void
SpeedDriver::drive(tCarElt* car, tSituation* situation)
{
	car->ctrl = tCarCtrl{};
	if (car->_speed_x < -0.3) {
		// Do not request a forward gear while still rolling backwards.
		car->ctrl.gear = car->_gear;
		car->ctrl.brakeCmd = 0.8f;
		targetSpeed = 0.0;
		return;
	}
	// Keep the familiar steering rule; this chapter changes longitudinal control.
	double angle = RtTrackSideTgAngleL(&car->_trkPos) - car->_yaw;
	NORM_PI_PI(angle);
	angle -= car->_trkPos.toMiddle / car->_trkPos.seg->width;
	car->ctrl.steer = static_cast<tdble>(std::max(-1.0, std::min(1.0, angle / car->_steerLock)));
	applySpeedTarget(car, chooseTargetSpeed(car));
	car->ctrl.gear = chooseGear(car, situation->currentTime);
}
