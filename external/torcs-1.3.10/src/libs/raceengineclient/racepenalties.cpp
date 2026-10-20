/***************************************************************************

    file                 : racepenalties.cpp
    created              : Mon Jun  8 20:00:00 CET 2026
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
    Race penalty application and penalty-aware race result ordering.
    @author Bernhard Wymann
*/

#include "racepenalties.h"


/**
 * @brief Return the result lap count used for final classification.
 *
 * Race result storage caps cars at one lap beyond the configured race distance
 * and writes completed laps as `_laps - 1`; penalty ordering uses the same lap
 * group to avoid moving cars across lap boundaries.
 *
 * @param[in] s Current race situation.
 * @param[in] car Car to inspect.
 * @return Completed lap count used for result ordering.
 */
static int
completedResultLaps(const tSituation *s, const tCarElt *car)
{
	return MIN(car->_laps, s->_totLaps + 1) - 1;
}


/**
 * @brief Swap adjacent cars and refresh their result positions.
 *
 * @param[in,out] cars Ordered car pointer array.
 * @param[in] j Index of the lower-ranked car before the swap.
 */
static void
swapAdjacentCars(tCarElt **cars, int j)
{
	tCarElt *car = cars[j];
	cars[j] = cars[j - 1];
	cars[j - 1] = car;
	cars[j]->_pos = j + 1;
	cars[j - 1]->_pos = j;
}


/**
 * @brief Apply pending drive-through and stop-and-go penalties as time.
 *
 * The estimate assumes 300 km/h on track, the configured pit speed in the pit
 * lane, 10 seconds for pit entry/exit, and 6 extra seconds for a stop-and-go.
 *
 * @param[in,out] s Current race situation.
 * @param[in] pits Pit lane information.
 */
static void
applyPendingPitPenalties(tSituation *s, const tTrackPitInfo *pits)
{
	if (!pits || pits->type != TR_PIT_ON_TRACK_SIDE) {
		return;
	}

	const tdble drivethrough = 10.0f;
	const tdble stopandgo = 6.0f + drivethrough;
	const tdble v0 = 84.0f;
	const tdble v1 = pits->speedLimit;
	const tdble dv = v0 - v1;
	tdble dt = 0.0f;

	if (dv > 1.0f && v1 > 1.0f) {
		dt = (pits->nMaxPits * pits->len) * dv / (v0 * v1);
	}

	for (int i = 0; i < s->_ncars; i++) {
		tCarElt *car = s->cars[i];
		tCarPenalty *penalty = GF_TAILQ_FIRST(&(car->_penaltyList));
		while (penalty) {
			if (penalty->penalty == RM_PENALTY_DRIVETHROUGH) {
				car->_penaltyTime += dt + drivethrough;
			} else if (penalty->penalty == RM_PENALTY_STOPANDGO) {
				car->_penaltyTime += dt + stopandgo;
			} else {
				GfError("Unknown penalty.");
			}
			penalty = GF_TAILQ_NEXT(penalty, link);
		}
	}
}


void
ReApplyRaceTimePenalties(tSituation *s, const tTrackPitInfo *pits)
{
	if (!s || !s->cars) {
		return;
	}

	applyPendingPitPenalties(s, pits);

	for (int i = 1; i < s->_ncars; i++) {
		int j = i;
		while (j > 0) {
			tCarElt *previous = s->cars[j - 1];
			tCarElt *current = s->cars[j];

			// The race order is already valid without penalties, so only penalized cars move down.
			if (previous->_penaltyTime <= 0.0f) {
				break;
			}

			const int previousLaps = completedResultLaps(s, previous);
			const int currentLaps = completedResultLaps(s, current);
			if (previousLaps != currentLaps) {
				break;
			}

			// No penalty reordering is applied before one completed lap or for wrecked cars.
			if (previousLaps < 1 ||
				(s->raceInfo.maxDammage < previous->_dammage) ||
				(s->raceInfo.maxDammage < current->_dammage))
			{
				i = s->_ncars;	// Break outer loop.
				break;
			}

			const double previousTime = previous->_curTime + previous->_penaltyTime;
			const double currentTime = current->_curTime + current->_penaltyTime;

			if (previousTime <= currentTime) {
				break;
			}

			swapAdjacentCars(s->cars, j);
			j--;
		}
	}
}
