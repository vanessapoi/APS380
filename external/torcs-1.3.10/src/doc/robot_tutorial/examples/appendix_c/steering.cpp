/***************************************************************************

    file                 : steering.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#include <algorithm>
#include <cmath>
#include <limits>
#include <robottools.h>
#include "steering.h"

// Compare the baseline first, then change one setting at a time.
static constexpr bool USE_LOOKAHEAD = true;
static constexpr bool ENABLE_EDGE_FEEDBACK = true;
static constexpr double EDGE_MARGIN = 1.0;        // metres from the car's corners
static constexpr double REJOIN_SPEED = 5.0;       // m/s at or beyond a road edge

double
segmentProgress(const tTrkLocPos& position)
{
	const tTrackSeg* segment = position.seg;
	const double distance = segment->type == TR_STR ? position.toStart :
		position.toStart * segment->radius;
	return std::max(0.0, std::min(double(segment->length), distance));
}

Vector2
centerlinePoint(const tTrackSeg* segment, double distance)
{
	const Vector2 start{(segment->vertex[TR_SL].x + segment->vertex[TR_SR].x) / 2.0,
		(segment->vertex[TR_SL].y + segment->vertex[TR_SR].y) / 2.0};
	const double along = std::max(0.0, std::min(double(segment->length), distance));
	if (segment->type == TR_STR) {
		const Vector2 end{(segment->vertex[TR_EL].x + segment->vertex[TR_ER].x) / 2.0,
			(segment->vertex[TR_EL].y + segment->vertex[TR_ER].y) / 2.0};
		return segment->length > 0.0 ? start + (end - start) * (along / segment->length) : start;
	}
	const Vector2 center{segment->center.x, segment->center.y};
	const double sign = segment->type == TR_LFT ? 1.0 : -1.0;
	return segment->radius > 0.0 ? start.rotated(center, sign * along / segment->radius) : start;
}

bool
targetAhead(const tTrkLocPos& position, double distance, int segmentCount, Vector2& target)
{
	const tTrackSeg* segment = position.seg;
	if (!segment || !std::isfinite(distance) || distance < 0.0) {
		return false;
	}
	double along = segmentProgress(position) + distance;
	// One complete lap may finish in the starting segment: allow nseg + 1 visits.
	for (int visited = 0; visited <= segmentCount && segment; ++visited) {
		if (segment->length > 0.0 && along <= segment->length) {
			target = centerlinePoint(segment, along);
			return true;
		}
		along -= std::max(0.0, double(segment->length));
		segment = segment->next;
	}
	return false;
}

double
steerToward(const tCarElt* car, const Vector2& target)
{
	const Vector2 direction = target - Vector2{car->_pos_X, car->_pos_Y};
	if (direction.length() < 1e-6 || car->_steerLock <= 0.0) {
		return 0.0;
	}
	double angle = std::atan2(direction.y, direction.x) - car->_yaw;
	NORM_PI_PI(angle);
	return std::max(-1.0, std::min(1.0, angle / car->_steerLock));
}

double
chooseSteering(tCarElt* car, int segmentCount, double trackLength, double base, double time)
{
	const double requested = base + time * std::max(0.0, double(car->_speed_x));
	const double lookahead = std::min(std::max(0.0, requested), std::max(0.0, trackLength * 0.5));
	Vector2 target;
	if (USE_LOOKAHEAD && targetAhead(car->_trkPos, lookahead, segmentCount, target)) {
		return steerToward(car, target);
	}
	double angle = RtTrackSideTgAngleL(&car->_trkPos) - car->_yaw;
	NORM_PI_PI(angle);
	angle -= car->_trkPos.toMiddle / std::max(1.0, double(car->_trkPos.seg->width));
	return car->_steerLock > 0.0 ? std::max(-1.0, std::min(1.0, angle / car->_steerLock)) : 0.0;
}

double
roadClearance(tCarElt* car)
{
	double clearance = std::numeric_limits<double>::infinity();
	for (int i = 0; i < 4; ++i) {
		tTrkLocPos corner{};
		// MAIN measures against the racing road; TRACK includes sides up to barriers.
		RtTrackGlobal2Local(car->_trkPos.seg, car->_corner_x(i), car->_corner_y(i), &corner, TR_LPOS_MAIN);
		clearance = std::min(clearance, double(std::min(corner.toLeft, corner.toRight)));
	}
	return clearance;
}

double
edgeSpeedLimit(tCarElt* car, double targetSpeed)
{
	if (!ENABLE_EDGE_FEEDBACK) {
		return targetSpeed;
	}
	const double fraction = std::max(0.0, std::min(1.0, roadClearance(car) / EDGE_MARGIN));
	const double slow = std::min(targetSpeed, REJOIN_SPEED);
	return slow + fraction * (targetSpeed - slow);
}

double
experimentalRadius(const tTrackSeg* segment, double progress, int segmentCount)
{
	if (segment->type == TR_STR || segment->radius <= 0.0) {
		return segment->radius;
	}
	double arc = std::max(0.0, double(segment->arc) - progress / segment->radius);
	const tTrackSeg* next = segment->next;
	for (int i = 1; i < segmentCount && next && next != segment &&
		next->type == segment->type && arc < PI / 2.0; ++i, next = next->next) {
		arc += std::max(0.0, double(next->arc));
	}
	const double fraction = std::max(0.05, std::min(1.0, arc / (PI / 2.0)));
	const double estimate = (segment->radius + segment->width / 2.0) / std::sqrt(fraction);
	// An experiment, not a measured path radius. Limit its optimistic speed boost.
	return std::min(1.5 * segment->radius, estimate);
}
