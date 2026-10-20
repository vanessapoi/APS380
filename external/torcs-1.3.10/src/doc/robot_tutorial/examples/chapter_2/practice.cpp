/***************************************************************************

    file                 : practice.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#include <cmath>
#include "practice.h"
#include "recovery.h"

// A repeatable, visible mistake made using ordinary steering and pedals.
// Change these settings, rebuild, and start a new Practice session.
static constexpr bool START_WITH_MISTAKE = true;
static constexpr bool REVERSE_INTO_BARRIER = false;
static constexpr bool BARRIER_ON_LEFT = true;

void
PracticeMistake::reset()
{
	finished = !START_WITH_MISTAKE;
}

bool
PracticeMistake::drive(tCarElt* car, tSituation* situation)
{
	if (finished) {
		return false;
	}
	const BarrierClearance clearance = measureClearance(car);
	const double endSpace = REVERSE_INTO_BARRIER ? clearance.rear : clearance.front;
	if (situation->currentTime > 1.0 &&
		((endSpace < 0.1 && std::hypot(car->_speed_x, car->_speed_y) < 0.3) ||
		 situation->currentTime > 20.0)) {
		finished = true;
		return false;
	}
	moveSlowly(car, REVERSE_INTO_BARRIER ? -1 : 1, BARRIER_ON_LEFT ? 0.65 : -0.65);
	return true;
}
