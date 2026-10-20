/***************************************************************************

    file                 : pit.cpp
    created              : Thu Mai 15 2:43:00 CET 2003
    copyright            : (C) 2003-2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/


/** @file pit.cpp
 * @brief Construct and query the seven-point pit spline and request/occupancy flags.
 * @ingroup olethros_pits
 * @details Pit owns maneuver transitions; Driver consumes the state for control.
 */
#include "pit.h"


const float Pit::SPEED_LIMIT_MARGIN = 0.5;		// [m/s] savety margin to avoid pit speeding.
const float Pit::BRAKE_AHEAD = 200.0f;        // [m] Entry braking/approach range.


Pit::Pit(tSituation *s, Driver *driver)
{
	track = driver->getTrackPtr();
	car = driver->getCarPtr();
	mypit = driver->getCarPtr()->_pit;
	pitinfo = &track->pits;
	pitstop = inpitlane = false;
	pittimer = 0.0;
	pit_state = NONE;

	if (mypit != NULL) {
		speedlimit = pitinfo->speedLimit - SPEED_LIMIT_MARGIN;
		speedlimitsqr = speedlimit*speedlimit;
		pitspeedlimitsqr = pitinfo->speedLimit*pitinfo->speedLimit;

		// Compute pit spline points along the track.
		p[3].x = mypit->pos.seg->lgfromstart + mypit->pos.toStart;
		p[2].x = p[3].x - pitinfo->len;
		p[4].x = p[3].x + pitinfo->len;
		p[0].x = pitinfo->pitEntry->lgfromstart;
		p[1].x = pitinfo->pitStart->lgfromstart;
		p[5].x = p[3].x + (pitinfo->nMaxPits - car->index)*pitinfo->len;
		p[6].x = pitinfo->pitExit->lgfromstart;

		pitentry = p[0].x;
		pitexit = p[6].x;

		// Normalizing spline segments to >= 0.0.
		int i;
		for (i = 0; i < NPOINTS; i++) {
			p[i].s = 0.0;
			p[i].x = toSplineCoord(p[i].x);
		}

		// Fix broken pit exit.
		if (p[6].x < p[5].x) {
			//printf("bt: Pitexit broken on track %s.\n", track->name);
			p[6].x = p[5].x + 50.0;
		}

		// Fix point for first pit if necessary.
		if (p[1].x > p[2].x) {
			p[1].x = p[2].x;
		}

		// Fix point for last pit if necessary.
		if (p[4].x > p[5].x) {
			p[5].x = p[4].x;
		}

		float sign = (pitinfo->side == TR_LFT) ? 1.0 : -1.0;
		p[0].y = 0.0;
		p[6].y = 0.0;
		for (i = 1; i < NPOINTS - 1; i++) {
			p[i].y = fabs(pitinfo->driversPits->pos.toMiddle) - pitinfo->width;
			p[i].y *= sign;
		}

		p[3].y = fabs(pitinfo->driversPits->pos.toMiddle)*sign;
		spline = new Spline(NPOINTS, p);
	}
}


Pit::~Pit()
{
	if (mypit != NULL) {
		delete spline;
	}
}


// Transforms track coordinates to spline parameter coordinates.
float Pit::toSplineCoord(float x)
{
	x -= pitentry;
	while (x < 0.0) {
		x += track->length;
	}
	return x;
}


// Computes offset to track middle for trajectory.
float Pit::getPitOffset(float offset, float fromstart)
{
	if (mypit != NULL) {
		if (getInPit() || (getPitstop() && isBetween(fromstart))) {
			fromstart = toSplineCoord(fromstart);
			// Lookahead can pass the exit before the car does. Extending the
			// cubic beyond its last knot would bend the target back toward pits.
			if (fromstart >= p[NPOINTS - 1].x) return p[NPOINTS - 1].y;
			return spline->evaluate(fromstart);
		}
	}
	return offset;
}


// Sets the pitstop flag if we are not in the pit range.
void Pit::setPitstop(bool pitstop)
{
	if (mypit == NULL) {
		return;
	}

	float fromstart = car->_distFromStartLine;

	if (!isBetween(fromstart)) {
		this->pitstop = pitstop;
	} else if (!pitstop) {
		this->pitstop = pitstop;
		pittimer = 0.0;
	}
	updateManeuver();
}


// Check if the argument fromstart is in the range of the pit.
bool Pit::isBetween(float fromstart)
{
	if (pitentry <= pitexit) {
		if (fromstart >= pitentry && fromstart <= pitexit) {
			return true;
		} else {
			return false;
		}
	} else {
		// Warning: TORCS reports sometimes negative values for "fromstart"!
		if (fromstart <= pitexit || fromstart >= pitentry) {
			return true;
		} else {
			return false;
		}
	}
}


// Checks if we stay too long without getting captured by the pit.
// Distance is the distance to the pit along the track, when the pit is
// ahead it is > 0, if we overshoot the pit it is < 0.
bool Pit::isTimeout(float distance)
{
	if (car->_speed_x > 1.0 || distance > 3.0 || !getPitstop()) {
		pittimer = 0.0f;
		return false;
	} else {
		pittimer += (float) RCM_MAX_DT_ROBOTS;
		if (pittimer > 3.0f) {
			pittimer = 0.0f;
			return true;
		} else {
			return false;
		}
	}
}


// Update pit data and strategy.
void Pit::update()
{
	if (mypit != NULL) {
		if (isBetween(car->_distFromStartLine)) {
			if (getPitstop()) {
				inpitlane = true;
			}
		} else {
			inpitlane = false;
		}

		if (getPitstop()) {
			car->_raceCmd = RM_CMD_PIT_ASKED;
		}
	}
	updateManeuver();
}

void Pit::updateManeuver()
{
	pit_state = NONE;
	if (mypit == NULL) return;
	if (inpitlane) {
		pit_state = pitstop ? IN_LANE : PIT_EXIT;
	} else if (pitstop) {
		float distance, lateral;
		RtDistToPit(car, track, &distance, &lateral);
		if (distance < BRAKE_AHEAD) pit_state = APPROACHING;
	}
}


float Pit::getSpeedLimitBrake(float speedsqr)
{
	return (speedsqr-speedlimitsqr)/(pitspeedlimitsqr-speedlimitsqr);
}
