/***************************************************************************

    file                 : recovery.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#ifndef _TUTORIALC_RECOVERY_H_
#define _TUTORIALC_RECOVERY_H_

#include <algorithm>
#include <limits>
#include <car.h>
#include <raceman.h>

struct BarrierClearance {
	double left = std::numeric_limits<double>::max();
	double right = std::numeric_limits<double>::max();
	double front = std::numeric_limits<double>::max();
	double rear = std::numeric_limits<double>::max();
	double minimum() const { return std::min(left, right); }
};

BarrierClearance measureClearance(tCarElt* car);
void moveSlowly(tCarElt* car, int direction, double steer);

struct Recovery {
	enum class Mode { Driving, Backing, MovingForward };
	Mode mode = Mode::Driving;
	double stuckTime = 0.0;
	double previousTime = 0.0;
	void reset(double time);
	// True means recovery supplied the controls; normal driving must not replace them.
	bool driveIfNeeded(tCarElt* car, tSituation* situation);
};

#endif
