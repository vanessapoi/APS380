/***************************************************************************

    file                 : steering.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#ifndef _TUTORIALA_STEERING_H_
#define _TUTORIALA_STEERING_H_

#include <car.h>
#include "geometry.h"

double segmentProgress(const tTrkLocPos& position);
Vector2 centerlinePoint(const tTrackSeg* segment, double distance);
bool targetAhead(const tTrkLocPos& position, double distance, int segmentCount, Vector2& target);
double steerToward(const tCarElt* car, const Vector2& target);
double chooseSteering(tCarElt* car, int segmentCount, double trackLength, double base, double time);
double roadClearance(tCarElt* car);
double edgeSpeedLimit(tCarElt* car, double targetSpeed);
double experimentalRadius(const tTrackSeg* segment, double progress, int segmentCount);

#endif
