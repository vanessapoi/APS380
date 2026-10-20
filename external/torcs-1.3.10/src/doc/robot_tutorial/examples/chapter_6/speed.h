/***************************************************************************

    file                 : speed.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#ifndef _TUTORIAL6_SPEED_H_
#define _TUTORIAL6_SPEED_H_

#include <car.h>
#include <raceman.h>
#include "braking.h"

struct SpeedDriver {
	enum class DrivenWheels { Front, Rear, All };
	DrivenWheels drivenWheels = DrivenWheels::Rear;
	double dryMass = 1000.0;
	double tyreGrip = 1.0;
	double minimumSurfaceGrip = 1.0;
	double downforce = 0.0;
	double drag = 0.0;
	double trackLength = 0.0;
	int segmentCount = 1;
	double lastShiftTime = -10.0;
	int requestedGear = 1;
	double targetSpeed = 0.0;
	double speedBound = 0.0; // gearing/redline bound for the finite braking search

	void configure(tTrack* track, tCarElt* car);
	void resumeAfterRecovery(double time);
	void drive(tCarElt* car, tSituation* situation);
	void applySpeedTarget(tCarElt* car, double target, double brakeLimit = 1.0);
	double chooseTargetSpeed(tCarElt* car) const;
	double speedForSegment(tCarElt* car, tTrackSeg* segment) const;
	int chooseGear(tCarElt* car, double time);
	double filterABS(tCarElt* car, double brake) const;
	double filterTraction(tCarElt* car, double throttle) const;
};

#endif
