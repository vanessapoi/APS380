/***************************************************************************

    file                 : racepit.cpp
    created              : Sun Jul 12 20:00:00 CET 2026
    copyright            : (C) 2026 by Bernhard Wymann
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

/** @file
    Pit stop command normalization and timing helpers.
    @author Bernhard Wymann
*/

#include "racepit.h"


void
ReNormalizePitStop(tCarElt *car)
{
	if (!car) {
		return;
	}

	tdble maxFuel = car->_tank - car->_fuel;
	if (maxFuel < 0.0f) {
		maxFuel = 0.0f;
	}
	if (car->_pitFuel < 0.0f) {
		car->_pitFuel = 0.0f;
	} else if (car->_pitFuel > maxFuel) {
		car->_pitFuel = maxFuel;
	}

	int maxRepair = car->_dammage;
	if (maxRepair < 0) {
		maxRepair = 0;
	}
	if (car->_pitRepair < 0) {
		car->_pitRepair = 0;
	} else if (car->_pitRepair > maxRepair) {
		car->_pitRepair = maxRepair;
	}
}


tdble
ReComputePitStopServiceTime(const tCarElt *car, const tRmRaceRules *raceRules)
{
	if (!car || !raceRules) {
		return 0.0f;
	}

	return raceRules->pitstopBaseTime + car->_pitFuel / raceRules->refuelFuelFlow +
		(tdble)car->_pitRepair * raceRules->damageRepairFactor + car->_penaltyTime;
}
