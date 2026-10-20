/***************************************************************************

    file                 : pit.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#ifndef _TUTORIALA_PIT_H_
#define _TUTORIALA_PIT_H_
#include "spline.h"
#include "traffic.h"

struct PitDriver {
	enum class Mode { Racing, Approach, Lane, Stopping, Service, Exit, Merging };
	Mode mode = Mode::Racing;
	bool demonstrationStop = false;
	double stintLaps = 0.0;
	double fallbackFuelPerLap = 1.5;
	bool available = false;
	bool requested = false;
	bool demonstrationDone = false;
	bool fuelInitialized = false;
	bool mergeHolding = false;
	bool missedBox = false;
	double length = 0.0;
	double entry = 0.0;
	double limitStart = 0.0;
	double limitEnd = 0.0;
	double box = 0.0;
	double boxMin = 0.0;
	double boxMax = 0.0;
	double mergeStart = 0.0;
	double exit = 0.0;
	double laneOffset = 0.0;
	double boxOffset = 0.0;
	double speedCap = 0.0;
	double entryClearDistance = 0.0;
	double progress = 0.0;
	double previousPosition = 0.0;
	double holdOffset = 0.0;
	double previousFuel = 0.0;
	double lapFuelUsed = 0.0;
	double fuelPerLap = 0.0;
	int previousLap = 0;
	int visits = 0;
	HermiteSpline route;
	HermiteSpline mergeRoute;
	tTrack* track = nullptr;
	tTrackOwnPit* ownPit = nullptr;

	void configure(tTrack* track, tCarElt* car);
	void updateStrategy(tCarElt* car);
	bool drive(SpeedDriver& driver, TrafficPlanner& traffic, tCarElt* car, tSituation* situation);
	int service(tCarElt* car);
	double estimatedFuelPerLap() const;
	double position(tCarElt* car) const;
	double relative(double position) const;
	bool entryClear(tCarElt* car, tSituation* situation, double distanceToEntry) const;
	Vector2 targetPoint(tCarElt* car, double ahead, double lateral) const;
};
#endif
