/***************************************************************************

    file                 : driving.cpp
    created              : September 2026
    copyright            : (C) 2003-2004, 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the Free
 * Software Foundation; either version 2 of the License, or (at your option)
 * any later version. Distributed WITHOUT ANY WARRANTY; without even the
 * implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See <https://www.gnu.org/licenses/> for the GNU General Public License.
 */

#include <algorithm>
#include <tgf.h>
#include <robottools.h>
#include "driver.h"

void
driveCar(tCarElt* car)
{
	car->ctrl = tCarCtrl{};

	const double correction = 1.0;
	double angle = RtTrackSideTgAngleL(&car->_trkPos) - car->_yaw;
	NORM_PI_PI(angle);
	angle -= correction * car->_trkPos.toMiddle / car->_trkPos.seg->width;

	const double steer = angle / car->_steerLock;
	car->ctrl.steer = static_cast<tdble>(std::max(-1.0, std::min(1.0, steer)));
	car->ctrl.gear = 1;
	car->ctrl.accelCmd = 0.3f;
}
