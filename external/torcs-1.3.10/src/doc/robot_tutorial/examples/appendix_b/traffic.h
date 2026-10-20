/***************************************************************************

    file                 : traffic.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#ifndef _TUTORIALB_TRAFFIC_H_
#define _TUTORIALB_TRAFFIC_H_

#include <vector>
#include "speed.h"
#include "steering.h"

struct TrafficCar {
	tCarElt* car = nullptr;
	double along = 0.0;        // signed center distance from our car, metres
	double lateral = 0.0;      // center offset from road centerline, positive left
	double speed = 0.0;        // world velocity projected along the road, m/s
	double lateralSpeed = 0.0; // world velocity projected onto the left normal, m/s
	double halfLength = 0.0;   // footprint projection onto the road tangent
	double halfWidth = 0.0;    // footprint projection onto the left normal
};

double wrappedDistance(double distance, double length);
TrafficCar describeCar(tCarElt* car);
double approach(double value, double target, double maximumChange);
bool offsetTarget(tCarElt* car, double offset, int count, double length, Vector2& target, double base, double time);
void applySpeedTarget(SpeedDriver& driver, tCarElt* car, double target, double brakeLimit);

struct TrafficPlanner {
	enum class Mode { Cruising, Following, Passing, Returning, Holding };
	Mode mode = Mode::Cruising;
	std::vector<TrafficCar> opponents;
	TrafficCar self;
	tCarElt* passingCar = nullptr;
	double offset = 0.0;
	double passOffset = 0.0;
	double holdOffset = 0.0;
	double holdUntil = 0.0;
	double previousTime = 0.0;
	double speedLimit = 0.0;
	bool nearby = false;
	bool emergency = false;
	bool corridorAvailable = true; // geometric check, not a swept-path guarantee

	void reset(double time);
	void observe(tCarElt* car, tSituation* situation, double trackLength);
	bool corridorFree(double target, const tCarElt* except, double seconds) const;
	void lateralBounds(double roadHalfWidth, double& low, double& high) const;
	void plan(double time, double freeSpeed, double roadHalfWidth,
		double currentHalfWidth = -1.0, double narrowingDistance = 0.0);
	void drive(SpeedDriver& driver, tCarElt* car, tSituation* situation);
};

#endif
