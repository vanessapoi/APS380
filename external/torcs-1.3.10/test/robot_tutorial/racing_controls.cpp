/***************************************************************************

    file                 : racing_controls.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#include <cassert>
#include <cmath>
#include <cstdio>
#include <initializer_list>
#include <tgf.h>
#ifndef SPEED_HEADER
#define SPEED_HEADER "../../src/doc/robot_tutorial/examples/chapter_3/speed.h"
#endif
#include SPEED_HEADER
#ifdef TRAFFIC_HEADER
#include TRAFFIC_HEADER
#endif
#ifdef PIT_HEADER
#include PIT_HEADER
#endif

static constexpr double EPS = 1e-5;

static void
rolling(tCarElt& car, double speed)
{
	car._speed_x = static_cast<tdble>(speed);
	for (int i = 0; i < 4; ++i) {
		car._wheelRadius(i) = 0.3f;
		car._wheelSpinVel(i) = static_cast<tdble>(speed / car._wheelRadius(i));
	}
}

int main()
{
	tTrackSurface surface{};
	surface.kFriction = 1.0f;
	tTrackSeg straight{};
	straight.type = TR_STR;
	straight.length = 1000.0f;
	straight.width = 15.0f;
	straight.surface = &surface;
	straight.next = straight.prev = &straight;
	tTrack track{};
	track.seg = &straight;
	track.nseg = 1;
	track.length = straight.length;
	tCarElt car{};
	car._trkPos.seg = &straight;
	car._carHandle = GfParmReadFile("", GFPARM_RMODE_CREAT | GFPARM_RMODE_PRIVATE);
	assert(car._carHandle);
	car._gearOffset = 1;
	car._gearNb = 3;
	car._gearRatio[2] = 10.0f;
	car._gearRatio[3] = 5.0f;
	car._enginerpmRedLine = 1000.0f;
	rolling(car, 40.0);
	SpeedDriver driver;
	driver.configure(&track, &car);
	// A clear straight must not inherit the old 32 m/s teaching ceiling.
	assert(std::fabs(driver.chooseTargetSpeed(&car) - 60.0) < EPS);
	driver.applySpeedTarget(&car, driver.chooseTargetSpeed(&car));
	assert(std::fabs(car.ctrl.accelCmd - 1.0) < EPS && car.ctrl.brakeCmd == 0.0f);
	driver.applySpeedTarget(&car, 0.0);
	assert(std::fabs(car.ctrl.brakeCmd - 1.0) < EPS && car.ctrl.accelCmd == 0.0f);
	// The completed checkpoint must actually use downforce, and anticipate bends.
	tTrackSeg bend = straight;
	bend.type = TR_LFT;
	bend.radius = 50.0f;
	bend.length = 50.0f;
	bend.arc = 1.0f;
	bend.next = bend.prev = &straight;
	straight.next = straight.prev = &bend;
	driver.segmentCount = 2;
	driver.trackLength = 1050.0;
	driver.downforce = 0.0;
	const double gravitySpeed = driver.speedForSegment(&car, &bend);
	driver.downforce = 20.0;
	assert(driver.speedForSegment(&car, &bend) > gravitySpeed + 1.0);
	driver.downforce = 0.0;
	car._trkPos.toStart = 980.0f;
	assert(std::fabs(driver.chooseTargetSpeed(&car) - gravitySpeed) < EPS);
	car._trkPos.toStart = 950.0f;
	driver.drag = 0.0;
	const double withoutDrag = driver.chooseTargetSpeed(&car);
	driver.drag = 20.0;
	assert(driver.chooseTargetSpeed(&car) > withoutDrag + 0.1);
	driver.drag = 0.0;
	car._trkPos.toStart = 0.0f;
	assert(driver.chooseTargetSpeed(&car) > gravitySpeed + 1.0);
	// Traffic restrictions change the target, not the available pedal authority.
#ifdef TRAFFIC_HEADER
	driver.targetSpeed = 60.0;
	applySpeedTarget(driver, &car, 55.0, 1.0);
	assert(std::fabs(car.ctrl.accelCmd - 1.0) < EPS);
	assert(std::fabs(driver.targetSpeed - 55.0) < EPS);
	applySpeedTarget(driver, &car, 0.0, 1.0);
	assert(std::fabs(car.ctrl.brakeCmd - 1.0) < EPS);
	// Fixed 60 m rear / 150 m front windows are insufficient at racing speed.
	tCarElt self = car;
	tCarElt other = car;
	self._trkPos.toStart = 0.0f;
	other._trkPos.toStart = 800.0f;
	self._dimension_x = other._dimension_x = 4.0f;
	self._dimension_y = other._dimension_y = 2.0f;
	self._speed_X = 10.0f;
	other._speed_X = 50.0f;
	tCarElt* cars[] = {&self, &other};
	tSituation situation{};
	situation._ncars = 2;
	situation.cars = cars;
	TrafficPlanner traffic;
	traffic.observe(&self, &situation, 1000.0);
	assert(traffic.opponents.size() == 1);
	assert(!traffic.corridorFree(0.0, nullptr, 6.0));
	other._trkPos.toStart = 250.0f;
	other._speed_X = 0.0f;
	self._speed_X = 40.0f;
	traffic.observe(&self, &situation, 1000.0);
	traffic.plan(0.1, 60.0, 7.5);
	assert(traffic.speedLimit < 50.0);
	// A blocked starting corridor must not undo the adjacent-car lateral bound.
	other._trkPos.toStart = 0.0f;
	self._speed_X = other._speed_X = 10.0f;
	for (int side : {-1, 1}) {
		other._trkPos.toMiddle = 2.1f * side;
		self._speed_Y = static_cast<tdble>(-side);
		traffic.reset(0.0);
		traffic.observe(&self, &situation, 1000.0);
		traffic.mode = TrafficPlanner::Mode::Holding;
		traffic.holdUntil = 10.0;
		traffic.plan(0.1, 60.0, 7.5);
		assert(traffic.offset * side < 0.0); // steer away, never back toward the adjacent car
	}
#endif
	// FWD/RWD/AWD: free rolling, driven slip, and non-driven slip.
	for (auto layout : {SpeedDriver::DrivenWheels::Front, SpeedDriver::DrivenWheels::Rear,
		SpeedDriver::DrivenWheels::All}) {
		driver.drivenWheels = layout;
		for (double speed : {0.0, 10.0, 40.0}) {
			rolling(car, speed);
			assert(std::fabs(driver.filterTraction(&car, 1.0) - 1.0) < EPS);
			for (int i = 0; i < 4; ++i) {
				const bool front = i == FRNT_RGT || i == FRNT_LFT;
				const bool driven = layout == SpeedDriver::DrivenWheels::All ||
					(front == (layout == SpeedDriver::DrivenWheels::Front));
				car._wheelSpinVel(i) = static_cast<tdble>((speed + (driven ? 4.0 : 0.0)) / car._wheelRadius(i));
			}
			const double reduced = driver.filterTraction(&car, 1.0);
			assert(reduced > 0.0 && reduced < 1.0);
			rolling(car, speed);
			if (layout != SpeedDriver::DrivenWheels::All) {
				for (int i = 0; i < 4; ++i) {
					const bool front = i == FRNT_RGT || i == FRNT_LFT;
					if (front != (layout == SpeedDriver::DrivenWheels::Front)) {
						car._wheelSpinVel(i) = 500.0f;
					}
				}
				assert(std::fabs(driver.filterTraction(&car, 1.0) - 1.0) < EPS);
			}
		}
	}
	rolling(car, 0.0);
	driver.applySpeedTarget(&car, 0.0);
	assert(car.ctrl.accelCmd == 0.0f && car.ctrl.brakeCmd > 0.0f);
#ifdef PIT_HEADER
	PitDriver pits;
	pits.length = track.length;
	car._remainingLaps = 10;
	car._fuel = 2.0f;
	car._tank = 60.0f;
	pits.service(&car);
	// Default refuelling must cover the race rather than force three-lap stints.
	assert(car._pitFuel > 10.0f && car._pitFuel <= car._tank - car._fuel);
#endif
	GfParmReleaseHandle(car._carHandle);
	std::puts("PASS: racing authority, gearing bound, traction layouts/launch, stop holding and strategy");
}
