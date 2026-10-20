/***************************************************************************

    file                 : trackcrossing.cpp
    created              : Sun Aug 2 2026
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
    @brief Automatic grade-separated track-crossing geometry.
 */

#include <algorithm>
#include <float.h>
#include <math.h>
#include <new>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <robottools.h>
#include <tgf.h>

#include "trackcrossing.h"

#ifdef min
#undef min
#endif
#ifdef max
#undef max
#endif


static const double CROSSING_PI = 3.14159265358979323846;
static const double CROSSING_PLAN_EPSILON = 1e-7;
static const double CROSSING_POINT_EPSILON = 1e-4;
static const double CROSSING_RENDERED_ENDPOINT_EPSILON = 1e-3;
static const double CROSSING_HEIGHT_EPSILON = 1e-5;
static const double CROSSING_TEXTURE_SIZE = 15.0;


struct CrossingPlanPoint
{
	double x;
	double y;
};


struct CrossingSegment
{
	tTrackSeg *segment;
	int index;
	double startDistance;
};


struct CrossingCandidate
{
	int firstIndex;
	int secondIndex;
	double firstToStart;
	double secondToStart;
	double x;
	double y;
};


struct CrossingBoundaryPoint
{
	double distance;
	double x;
	double y;
	double z;
	double minimumSurfaceZ;
	double maximumSurfaceZ;
	double barrierTopZ;
	bool renderedVertex;
};


struct CrossingBoundaryLine
{
	std::vector<CrossingBoundaryPoint> points;
};


struct CrossingSampleDistance
{
	double distance;
	bool renderedVertex;
	tTrackSeg *segment;
	double toStart;
};


struct CrossingLineIntersection
{
	bool found;
	double firstDistance;
	double secondDistance;
	double x;
	double y;
	double distanceSquared;

	CrossingLineIntersection() : found(false), firstDistance(0.0),
		secondDistance(0.0), x(0.0), y(0.0), distanceSquared(DBL_MAX)
	{
	}
};


static double
crossingCross(double firstX, double firstY, double secondX, double secondY)
{
	return firstX * secondY - firstY * secondX;
}


static double
crossingDistanceSquared(double firstX, double firstY,
	                    double secondX, double secondY)
{
	double deltaX = firstX - secondX;
	double deltaY = firstY - secondY;
	return deltaX * deltaX + deltaY * deltaY;
}


static double
crossingClamp(double value, double minimum, double maximum)
{
	if (value < minimum) {
		return minimum;
	}
	if (value > maximum) {
		return maximum;
	}
	return value;
}


static bool
crossingFinite(double value)
{
#ifdef WIN32
	return _finite(value) != 0;
#else
	return isfinite(value) != 0;
#endif
}


static void
setCrossingError(char *errorMessage, size_t errorMessageSize,
	             const char *message)
{
	if ((errorMessage == NULL) || (errorMessageSize == 0)) {
		return;
	}
	snprintf(errorMessage, errorMessageSize, "%s", message);
}


static double
positiveAngle(double angle)
{
	double normalized = fmod(angle, 2.0 * CROSSING_PI);
	if (normalized < 0.0) {
		normalized += 2.0 * CROSSING_PI;
	}
	return normalized;
}


static double
segmentEndToStart(const tTrackSeg *segment)
{
	if (segment->type == TR_STR) {
		return segment->length;
	}
	return segment->arc;
}


static double
segmentPhysicalOffset(const tTrackSeg *segment, double toStart)
{
	if (segment->type == TR_STR) {
		return toStart;
	}
	return toStart * segment->radius;
}


static double
segmentToStart(const tTrackSeg *segment, double physicalOffset)
{
	if (segment->type == TR_STR) {
		return physicalOffset;
	}
	if (fabs(segment->radius) <= CROSSING_PLAN_EPSILON) {
		return 0.0;
	}
	return physicalOffset / segment->radius;
}


static void
crossingLocalToGlobal(tTrkLocPos *position, double *x, double *y)
{
	tdble trackX;
	tdble trackY;
	RtTrackLocal2Global(position, &trackX, &trackY, TR_TORIGHT);
	*x = trackX;
	*y = trackY;
}


static void
getTrackCenterPoint(tTrackSeg *segment, double toStart,
	                CrossingPlanPoint *point, double *height)
{
	tTrkLocPos position;
	position.seg = segment;
	position.toStart = toStart;
	position.toRight = RtTrackGetWidth(segment, toStart) / 2.0;
	crossingLocalToGlobal(&position, &point->x, &point->y);
	if (height != NULL) {
		*height = RtTrackHeightL(&position);
	}
}


static CrossingPlanPoint
getTrackTangent(const tTrackSeg *segment, double toStart)
{
	CrossingPlanPoint tangent;
	double angle = segment->angle[TR_ZS];
	if (segment->type == TR_LFT) {
		angle += toStart;
	} else if (segment->type == TR_RGT) {
		angle -= toStart;
	}
	tangent.x = cos(angle);
	tangent.y = sin(angle);
	return tangent;
}


static bool
getCurveToStart(const tTrackSeg *segment, double x, double y,
	            double *toStart)
{
	double angle;
	double offset;
	double sign = segment->type == TR_LFT ? 1.0 : -1.0;
	angle = atan2(sign * (x - segment->center.x),
	              -sign * (y - segment->center.y));
	if (segment->type == TR_LFT) {
		offset = positiveAngle(angle - segment->angle[TR_ZS]);
	} else {
		offset = positiveAngle(segment->angle[TR_ZS] - angle);
	}
	if (offset > segment->arc + CROSSING_PLAN_EPSILON) {
		return false;
	}
	*toStart = crossingClamp(offset, 0.0, segment->arc);
	return true;
}


static void
appendCandidate(std::vector<CrossingCandidate> *candidates,
	            int firstIndex, int secondIndex,
	            double firstToStart, double secondToStart,
	            double x, double y)
{
	CrossingCandidate candidate;
	candidate.firstIndex = firstIndex;
	candidate.secondIndex = secondIndex;
	candidate.firstToStart = firstToStart;
	candidate.secondToStart = secondToStart;
	candidate.x = x;
	candidate.y = y;
	candidates->push_back(candidate);
}


static void
intersectStraightStraight(const CrossingSegment &first,
	                      const CrossingSegment &second,
	                      std::vector<CrossingCandidate> *candidates)
{
	CrossingPlanPoint firstEnd;
	CrossingPlanPoint firstStart;
	CrossingPlanPoint secondEnd;
	CrossingPlanPoint secondStart;
	double denominator;
	double firstParameter;
	double secondParameter;
	double firstX;
	double firstY;
	double secondX;
	double secondY;
	double startX;
	double startY;

	getTrackCenterPoint(first.segment, 0.0, &firstStart, NULL);
	getTrackCenterPoint(first.segment, first.segment->length, &firstEnd, NULL);
	getTrackCenterPoint(second.segment, 0.0, &secondStart, NULL);
	getTrackCenterPoint(second.segment, second.segment->length, &secondEnd, NULL);
	firstX = firstEnd.x - firstStart.x;
	firstY = firstEnd.y - firstStart.y;
	secondX = secondEnd.x - secondStart.x;
	secondY = secondEnd.y - secondStart.y;
	denominator = crossingCross(firstX, firstY, secondX, secondY);
	if (fabs(denominator) <= CROSSING_PLAN_EPSILON) {
		return;
	}
	startX = secondStart.x - firstStart.x;
	startY = secondStart.y - firstStart.y;
	firstParameter = crossingCross(startX, startY, secondX, secondY) /
	                 denominator;
	secondParameter = crossingCross(startX, startY, firstX, firstY) /
	                  denominator;
	if ((firstParameter < -CROSSING_PLAN_EPSILON) ||
	        (firstParameter > 1.0 + CROSSING_PLAN_EPSILON) ||
	        (secondParameter < -CROSSING_PLAN_EPSILON) ||
	        (secondParameter > 1.0 + CROSSING_PLAN_EPSILON)) {
		return;
	}
	firstParameter = crossingClamp(firstParameter, 0.0, 1.0);
	secondParameter = crossingClamp(secondParameter, 0.0, 1.0);
	appendCandidate(candidates, first.index, second.index,
	                firstParameter * first.segment->length,
	                secondParameter * second.segment->length,
	                firstStart.x + firstParameter * firstX,
	                firstStart.y + firstParameter * firstY);
}


static void
intersectStraightCurve(const CrossingSegment &straight,
	                   const CrossingSegment &curve, bool straightIsFirst,
	                   std::vector<CrossingCandidate> *candidates)
{
	CrossingPlanPoint lineEnd;
	CrossingPlanPoint lineStart;
	double a;
	double b;
	double c;
	double curveToStart;
	double discriminant;
	double lineParameter[2];
	double lineX;
	double lineY;
	double offsetX;
	double offsetY;
	int rootCount;
	int rootIndex;

	getTrackCenterPoint(straight.segment, 0.0, &lineStart, NULL);
	getTrackCenterPoint(straight.segment, straight.segment->length,
	                    &lineEnd, NULL);
	lineX = lineEnd.x - lineStart.x;
	lineY = lineEnd.y - lineStart.y;
	offsetX = lineStart.x - curve.segment->center.x;
	offsetY = lineStart.y - curve.segment->center.y;
	a = lineX * lineX + lineY * lineY;
	if (a <= CROSSING_PLAN_EPSILON) {
		return;
	}
	b = 2.0 * (offsetX * lineX + offsetY * lineY);
	c = offsetX * offsetX + offsetY * offsetY -
	    curve.segment->radius * curve.segment->radius;
	discriminant = b * b - 4.0 * a * c;
	if (discriminant < -CROSSING_PLAN_EPSILON) {
		return;
	}
	if (discriminant <= CROSSING_PLAN_EPSILON) {
		lineParameter[0] = -b / (2.0 * a);
		rootCount = 1;
	} else {
		discriminant = sqrt(discriminant);
		lineParameter[0] = (-b - discriminant) / (2.0 * a);
		lineParameter[1] = (-b + discriminant) / (2.0 * a);
		rootCount = 2;
	}
	for (rootIndex = 0; rootIndex < rootCount; rootIndex++) {
		double parameter = lineParameter[rootIndex];
		double x;
		double y;
		if ((parameter < -CROSSING_PLAN_EPSILON) ||
		        (parameter > 1.0 + CROSSING_PLAN_EPSILON)) {
			continue;
		}
		parameter = crossingClamp(parameter, 0.0, 1.0);
		x = lineStart.x + parameter * lineX;
		y = lineStart.y + parameter * lineY;
		if (!getCurveToStart(curve.segment, x, y, &curveToStart)) {
			continue;
		}
		if (straightIsFirst) {
			appendCandidate(candidates, straight.index, curve.index,
			                parameter * straight.segment->length,
			                curveToStart, x, y);
		} else {
			appendCandidate(candidates, curve.index, straight.index,
			                curveToStart,
			                parameter * straight.segment->length, x, y);
		}
	}
}


static void
intersectCurveCurve(const CrossingSegment &first,
	                const CrossingSegment &second,
	                std::vector<CrossingCandidate> *candidates)
{
	double centerDistance;
	double centerDistanceSquared;
	double deltaX = second.segment->center.x - first.segment->center.x;
	double deltaY = second.segment->center.y - first.segment->center.y;
	double firstRadius = first.segment->radius;
	double secondRadius = second.segment->radius;
	double along;
	double height;
	double middleX;
	double middleY;
	double normalX;
	double normalY;
	double firstToStart;
	double secondToStart;
	int pointCount;
	int pointIndex;

	centerDistanceSquared = deltaX * deltaX + deltaY * deltaY;
	if (centerDistanceSquared <= CROSSING_PLAN_EPSILON) {
		return;
	}
	centerDistance = sqrt(centerDistanceSquared);
	if ((centerDistance > firstRadius + secondRadius + CROSSING_PLAN_EPSILON) ||
	        (centerDistance < fabs(firstRadius - secondRadius) -
	         CROSSING_PLAN_EPSILON)) {
		return;
	}
	along = (firstRadius * firstRadius - secondRadius * secondRadius +
	         centerDistanceSquared) / (2.0 * centerDistance);
	height = firstRadius * firstRadius - along * along;
	if (height < -CROSSING_PLAN_EPSILON) {
		return;
	}
	height = height <= 0.0 ? 0.0 : sqrt(height);
	middleX = first.segment->center.x + along * deltaX / centerDistance;
	middleY = first.segment->center.y + along * deltaY / centerDistance;
	normalX = -deltaY / centerDistance;
	normalY = deltaX / centerDistance;
	pointCount = height <= CROSSING_PLAN_EPSILON ? 1 : 2;
	for (pointIndex = 0; pointIndex < pointCount; pointIndex++) {
		double direction = pointIndex == 0 ? 1.0 : -1.0;
		double x = middleX + direction * height * normalX;
		double y = middleY + direction * height * normalY;
		if (getCurveToStart(first.segment, x, y, &firstToStart) &&
		        getCurveToStart(second.segment, x, y, &secondToStart)) {
			appendCandidate(candidates, first.index, second.index,
			                firstToStart, secondToStart, x, y);
		}
	}
}


static bool
segmentIndicesAreAdjacent(int first, int second, int segmentCount)
{
	int difference = abs(first - second);
	return (difference <= 1) || (difference == segmentCount - 1);
}


static bool
candidateBranchesMatch(const CrossingCandidate &first,
	                   const CrossingCandidate &second, int segmentCount)
{
	bool direct = segmentIndicesAreAdjacent(first.firstIndex,
	                                      second.firstIndex, segmentCount) &&
	              segmentIndicesAreAdjacent(first.secondIndex,
	                                      second.secondIndex, segmentCount);
	bool reversed = segmentIndicesAreAdjacent(first.firstIndex,
	                                        second.secondIndex, segmentCount) &&
	                segmentIndicesAreAdjacent(first.secondIndex,
	                                        second.firstIndex, segmentCount);
	return direct || reversed;
}


static bool
candidateLess(const CrossingCandidate &first,
	          const CrossingCandidate &second)
{
	if (first.firstIndex != second.firstIndex) {
		return first.firstIndex < second.firstIndex;
	}
	if (first.secondIndex != second.secondIndex) {
		return first.secondIndex < second.secondIndex;
	}
	if (first.firstToStart != second.firstToStart) {
		return first.firstToStart < second.firstToStart;
	}
	return first.secondToStart < second.secondToStart;
}


static void
findCrossingCandidates(const std::vector<CrossingSegment> &segments,
	                  std::vector<CrossingCandidate> *candidates)
{
	std::vector<CrossingCandidate> rawCandidates;
	size_t firstIndex;
	size_t secondIndex;

	for (firstIndex = 0; firstIndex < segments.size(); firstIndex++) {
		for (secondIndex = firstIndex + 1;
		        secondIndex < segments.size(); secondIndex++) {
			const CrossingSegment &first = segments[firstIndex];
			const CrossingSegment &second = segments[secondIndex];
			if (segmentIndicesAreAdjacent(first.index, second.index,
			                              (int)segments.size())) {
				continue;
			}
			if ((first.segment->type == TR_STR) &&
			        (second.segment->type == TR_STR)) {
				intersectStraightStraight(first, second, &rawCandidates);
			} else if (first.segment->type == TR_STR) {
				intersectStraightCurve(first, second, true, &rawCandidates);
			} else if (second.segment->type == TR_STR) {
				intersectStraightCurve(second, first, false, &rawCandidates);
			} else {
				intersectCurveCurve(first, second, &rawCandidates);
			}
		}
	}
	std::sort(rawCandidates.begin(), rawCandidates.end(), candidateLess);
	for (firstIndex = 0; firstIndex < rawCandidates.size(); firstIndex++) {
		bool duplicate = false;
		for (secondIndex = 0; secondIndex < candidates->size(); secondIndex++) {
			if (crossingDistanceSquared(rawCandidates[firstIndex].x,
			        rawCandidates[firstIndex].y,
			        (*candidates)[secondIndex].x,
			        (*candidates)[secondIndex].y) <=
			        CROSSING_POINT_EPSILON * CROSSING_POINT_EPSILON &&
			        candidateBranchesMatch(rawCandidates[firstIndex],
			            (*candidates)[secondIndex], (int)segments.size())) {
				duplicate = true;
				break;
			}
		}
		if (!duplicate) {
			candidates->push_back(rawCandidates[firstIndex]);
		}
	}
}


static double
wrapTrackDistance(double distance, double trackLength)
{
	double wrapped = fmod(distance, trackLength);
	if (wrapped < 0.0) {
		wrapped += trackLength;
	}
	if (wrapped >= trackLength) {
		wrapped = 0.0;
	}
	return wrapped;
}


static bool
locateTrackDistance(const std::vector<CrossingSegment> &segments,
	                double trackLength, double distance,
	                tTrackSeg **segment, double *toStart)
{
	double wrapped = wrapTrackDistance(distance, trackLength);
	size_t index;
	for (index = 0; index < segments.size(); index++) {
		double start = segments[index].startDistance;
		double end = start + segments[index].segment->length;
		if ((wrapped >= start - CROSSING_PLAN_EPSILON) &&
		        ((wrapped < end - CROSSING_PLAN_EPSILON) ||
		         (index == segments.size() - 1))) {
			double physicalOffset = crossingClamp(wrapped - start, 0.0,
			        segments[index].segment->length);
			*segment = segments[index].segment;
			*toStart = segmentToStart(*segment, physicalOffset);
			return true;
		}
	}
	return false;
}


static tdble
getRenderedToStartStep(const tTrackSeg *segment, tdble trackStep)
{
	tdble radius;
	if (segment->type == TR_STR) {
		return trackStep;
	}
	radius = segment->type == TR_LFT ? segment->radiusr : segment->radiusl;
	if ((radius <= CROSSING_PLAN_EPSILON) ||
	        (segment->radius <= CROSSING_PLAN_EPSILON)) {
		return trackStep;
	}
	return trackStep / radius;
}


static void
appendSampleDistance(std::vector<CrossingSampleDistance> *distances,
	                 double distance, bool renderedVertex,
	                 tTrackSeg *segment, double toStart,
	                 double rangeStart, double rangeEnd)
{
	if ((distance >= rangeStart - CROSSING_PLAN_EPSILON) &&
	        (distance <= rangeEnd + CROSSING_PLAN_EPSILON)) {
		CrossingSampleDistance sample;
		sample.distance = crossingClamp(distance, rangeStart, rangeEnd);
		sample.renderedVertex = renderedVertex;
		sample.segment = segment;
		sample.toStart = toStart;
		distances->push_back(sample);
	}
}


static void
collectSampleDistances(const std::vector<CrossingSegment> &segments,
	                  double trackLength, double rangeStart, double rangeEnd,
	                  double trackStep,
	                  std::vector<CrossingSampleDistance> *distances)
{
	int firstLap = (int)floor(rangeStart / trackLength) - 1;
	int lastLap = (int)ceil(rangeEnd / trackLength) + 1;
	int lap;
	size_t index;

	appendSampleDistance(distances, rangeStart, false, NULL, 0.0,
	                     rangeStart, rangeEnd);
	appendSampleDistance(distances, rangeEnd, false, NULL, 0.0,
	                     rangeStart, rangeEnd);
	for (lap = firstLap; lap <= lastLap; lap++) {
		for (index = 0; index < segments.size(); index++) {
			double segmentStart = segments[index].startDistance +
			        lap * trackLength;
			double segmentEnd = segmentStart + segments[index].segment->length;
			tdble sampleStep;
			tdble sampleOffset;
			double sampleDistance;
			if ((segmentEnd < rangeStart) || (segmentStart > rangeEnd)) {
				continue;
			}
			appendSampleDistance(distances, segmentStart, true,
			                     segments[index].segment, 0.0,
			                     rangeStart, rangeEnd);
			appendSampleDistance(distances, segmentEnd, true,
			                     segments[index].segment,
			                     segmentEndToStart(segments[index].segment),
			                     rangeStart, rangeEnd);
			sampleStep = (tdble)getRenderedToStartStep(
			        segments[index].segment, trackStep);
			if (!crossingFinite(sampleStep) ||
			        (sampleStep <= CROSSING_PLAN_EPSILON)) {
				continue;
			}
			for (sampleOffset = sampleStep;
			        sampleOffset < segmentEndToStart(segments[index].segment) -
			        CROSSING_PLAN_EPSILON; sampleOffset += sampleStep) {
				sampleDistance = segmentStart + segmentPhysicalOffset(
				        segments[index].segment, sampleOffset);
				appendSampleDistance(distances, sampleDistance, true,
				                     segments[index].segment, sampleOffset,
				                     rangeStart, rangeEnd);
			}
		}
	}
	std::stable_sort(distances->begin(), distances->end(),
	        [](const CrossingSampleDistance &first,
	           const CrossingSampleDistance &second) {
		        return first.distance < second.distance;
	        });
	for (index = 1; index < distances->size();) {
		CrossingSampleDistance &previous = (*distances)[index - 1];
		CrossingSampleDistance &current = (*distances)[index];
		if (fabs(previous.distance - current.distance) <=
		        CROSSING_PLAN_EPSILON) {
			if (previous.renderedVertex && current.renderedVertex &&
			        (previous.segment != current.segment)) {
				index++;
				continue;
			}
			bool previousAtSegmentEnd = previous.renderedVertex &&
			        (previous.segment != NULL) &&
			        (fabs(previous.toStart -
			         segmentEndToStart(previous.segment)) <=
			         CROSSING_PLAN_EPSILON);
			bool currentAtSegmentEnd = current.renderedVertex &&
			        (current.segment != NULL) &&
			        (fabs(current.toStart -
			         segmentEndToStart(current.segment)) <=
			         CROSSING_PLAN_EPSILON);
			if (current.renderedVertex &&
			        (!previous.renderedVertex ||
			         (currentAtSegmentEnd && !previousAtSegmentEnd))) {
				previous = current;
			} else {
				previous.renderedVertex = previous.renderedVertex ||
				        current.renderedVertex;
			}
			distances->erase(distances->begin() + index);
		} else {
			index++;
		}
	}
}


static tTrackSeg *
getOutermostSegment(tTrackSeg *mainSegment, int side)
{
	tTrackSeg *segment = mainSegment;
	while (segment->side[side] != NULL) {
		segment = segment->side[side];
	}
	return segment;
}


static CrossingBoundaryPoint
sampleSegmentBoundaryHeight(tTrackSeg *segment, double toStart,
	                        double toRight)
{
	CrossingBoundaryPoint point;
	tTrkLocPos position;
	position.seg = segment;
	position.toStart = toStart;
	position.toRight = toRight;
	crossingLocalToGlobal(&position, &point.x, &point.y);
	point.z = RtTrackHeightL(&position);
	point.distance = 0.0;
	point.minimumSurfaceZ = point.z;
	point.maximumSurfaceZ = point.z;
	point.barrierTopZ = point.z;
	point.renderedVertex = false;
	return point;
}


static void
includeSegmentSurfaceHeights(tTrackSeg *segment, double toStart,
	                         double *minimumZ, double *maximumZ)
{
	CrossingBoundaryPoint right = sampleSegmentBoundaryHeight(segment,
	        toStart, 0.0);
	CrossingBoundaryPoint left = sampleSegmentBoundaryHeight(segment,
	        toStart, RtTrackGetWidth(segment, toStart));
	*minimumZ = std::min(*minimumZ, std::min(right.z, left.z));
	*maximumZ = std::max(*maximumZ, std::max(right.z, left.z));
}


static CrossingBoundaryPoint
sampleOuterBoundary(tTrackSeg *mainSegment, double toStart, int side,
	                bool renderedVertex)
{
	CrossingBoundaryPoint point;
	tTrackBarrier *barrier = mainSegment->barrier[side];
	tTrackSeg *outerSegment = getOutermostSegment(mainSegment, side);
	tTrkLocPos position;
	double edgeToRight;
	double wallWidth = 0.0;
	double segmentEnd = segmentEndToStart(mainSegment);
	bool atStart = fabs(toStart) <= CROSSING_PLAN_EPSILON;
	bool atEnd = fabs(toStart - segmentEnd) <= CROSSING_PLAN_EPSILON;
	int surfaceSide;
	int vertexIndex;

	position.seg = outerSegment;
	position.toStart = toStart;
	edgeToRight = side == TR_SIDE_RGT
	        ? 0.0 : RtTrackGetWidth(outerSegment, toStart);
	if (renderedVertex && (atStart || atEnd)) {
		if (side == TR_SIDE_RGT) {
			vertexIndex = atStart ? TR_SR : TR_ER;
		} else {
			vertexIndex = atStart ? TR_SL : TR_EL;
		}
		point.x = outerSegment->vertex[vertexIndex].x;
		point.y = outerSegment->vertex[vertexIndex].y;
		point.z = outerSegment->vertex[vertexIndex].z;
	} else {
		position.toRight = edgeToRight;
		crossingLocalToGlobal(&position, &point.x, &point.y);
		point.z = RtTrackHeightL(&position);
	}
	point.minimumSurfaceZ = DBL_MAX;
	point.maximumSurfaceZ = -DBL_MAX;
	includeSegmentSurfaceHeights(mainSegment, toStart,
	                            &point.minimumSurfaceZ,
	                            &point.maximumSurfaceZ);
	for (surfaceSide = 0; surfaceSide < 2; surfaceSide++) {
		tTrackSeg *surfaceSegment = mainSegment->side[surfaceSide];
		while (surfaceSegment != NULL) {
			includeSegmentSurfaceHeights(surfaceSegment, toStart,
			                            &point.minimumSurfaceZ,
			                            &point.maximumSurfaceZ);
			surfaceSegment = surfaceSegment->side[surfaceSide];
		}
	}
	point.barrierTopZ = point.maximumSurfaceZ;
	if (barrier != NULL) {
		if ((barrier->style == TR_WALL) && crossingFinite(barrier->width) &&
		        (barrier->width > 0.0)) {
			wallWidth = barrier->width;
		}
		if (crossingFinite(barrier->height) && (barrier->height > 0.0)) {
			point.barrierTopZ = std::max(point.barrierTopZ,
			        point.z + barrier->height);
		}
	}
	if (wallWidth > 0.0) {
		position.toRight = side == TR_SIDE_RGT
		        ? edgeToRight - wallWidth : edgeToRight + wallWidth;
		crossingLocalToGlobal(&position, &point.x, &point.y);
	}
	if (renderedVertex) {
		point.x = (float)point.x;
		point.y = (float)point.y;
		point.z = (float)point.z;
	}
	point.distance = 0.0;
	point.renderedVertex = renderedVertex;
	return point;
}


static bool
sampleBoundaryLine(const std::vector<CrossingSegment> &segments,
	               double trackLength, double centerDistance,
	               double halfExtent, double trackStep, int side,
	               CrossingBoundaryLine *line)
{
	std::vector<CrossingSampleDistance> distances;
	size_t index;
	double rangeStart = centerDistance - halfExtent;
	double rangeEnd = centerDistance + halfExtent;

	collectSampleDistances(segments, trackLength, rangeStart, rangeEnd,
	                       trackStep, &distances);
	for (index = 0; index < distances.size(); index++) {
		tTrackSeg *segment;
		double toStart;
		CrossingBoundaryPoint point;
		if (distances[index].renderedVertex &&
		        (distances[index].segment != NULL)) {
			segment = distances[index].segment;
			toStart = distances[index].toStart;
		} else {
			if (!locateTrackDistance(segments, trackLength,
			        distances[index].distance, &segment, &toStart)) {
				return false;
			}
		}
		point = sampleOuterBoundary(segment, toStart, side,
		                            distances[index].renderedVertex);
		point.distance = distances[index].distance;
		if (!line->points.empty()) {
			CrossingBoundaryPoint &previous = line->points.back();
			if ((fabs(previous.distance - point.distance) <=
			        CROSSING_PLAN_EPSILON) &&
			        (crossingDistanceSquared(previous.x, previous.y,
			         point.x, point.y) <=
			         CROSSING_RENDERED_ENDPOINT_EPSILON *
			         CROSSING_RENDERED_ENDPOINT_EPSILON)) {
				previous.minimumSurfaceZ = std::min(previous.minimumSurfaceZ,
				                                    point.minimumSurfaceZ);
				previous.maximumSurfaceZ = std::max(previous.maximumSurfaceZ,
				                                    point.maximumSurfaceZ);
				previous.barrierTopZ = std::max(previous.barrierTopZ,
				                               point.barrierTopZ);
				previous.renderedVertex = previous.renderedVertex ||
				        point.renderedVertex;
				continue;
			}
		}
		line->points.push_back(point);
	}
	return line->points.size() >= 2;
}


static CrossingPlanPoint
getOffsetNormal(const CrossingBoundaryPoint &first,
	            const CrossingBoundaryPoint &second, int side)
{
	CrossingPlanPoint normal;
	double deltaX = second.x - first.x;
	double deltaY = second.y - first.y;
	double length = sqrt(deltaX * deltaX + deltaY * deltaY);
	if (length <= CROSSING_PLAN_EPSILON) {
		normal.x = 0.0;
		normal.y = 0.0;
		return normal;
	}
	if (side == TR_SIDE_RGT) {
		normal.x = deltaY / length;
		normal.y = -deltaX / length;
	} else {
		normal.x = -deltaY / length;
		normal.y = deltaX / length;
	}
	return normal;
}


static CrossingPlanPoint
getBoundaryNormal(const CrossingBoundaryLine &line, double distance, int side)
{
	size_t index;
	if (line.points.size() < 2) {
		CrossingPlanPoint normal = {0.0, 0.0};
		return normal;
	}
	for (index = 0; index + 1 < line.points.size(); index++) {
		if (distance <= line.points[index + 1].distance +
		        CROSSING_PLAN_EPSILON) {
			return getOffsetNormal(line.points[index],
			                       line.points[index + 1], side);
		}
	}
	return getOffsetNormal(line.points[line.points.size() - 2],
	                       line.points.back(), side);
}


static CrossingBoundaryLine
offsetBoundaryLine(const CrossingBoundaryLine &line, int side, double gap)
{
	CrossingBoundaryLine offset;
	size_t index;
	offset.points = line.points;
	if ((gap <= CROSSING_PLAN_EPSILON) || (line.points.size() < 2)) {
		return offset;
	}
	for (index = 0; index < line.points.size(); index++) {
		CrossingPlanPoint firstNormal;
		CrossingPlanPoint secondNormal;
		CrossingPlanPoint miter;
		double denominator;
		double miterLength;
		if (index == 0) {
			firstNormal = getOffsetNormal(line.points[0], line.points[1], side);
			secondNormal = firstNormal;
		} else if (index == line.points.size() - 1) {
			firstNormal = getOffsetNormal(line.points[index - 1],
			                              line.points[index], side);
			secondNormal = firstNormal;
		} else {
			firstNormal = getOffsetNormal(line.points[index - 1],
			                              line.points[index], side);
			secondNormal = getOffsetNormal(line.points[index],
			                               line.points[index + 1], side);
		}
		miter.x = firstNormal.x + secondNormal.x;
		miter.y = firstNormal.y + secondNormal.y;
		miterLength = sqrt(miter.x * miter.x + miter.y * miter.y);
		if (miterLength <= CROSSING_PLAN_EPSILON) {
			miter = secondNormal;
		} else {
			miter.x /= miterLength;
			miter.y /= miterLength;
		}
		denominator = miter.x * secondNormal.x +
		              miter.y * secondNormal.y;
		if (denominator <= CROSSING_PLAN_EPSILON) {
			miter = secondNormal;
			denominator = 1.0;
		}
		offset.points[index].x += miter.x * gap / denominator;
		offset.points[index].y += miter.y * gap / denominator;
	}
	return offset;
}


static CrossingBoundaryPoint
interpolateBoundaryPoint(const CrossingBoundaryLine &line, double distance)
{
	size_t index;
	if (distance <= line.points.front().distance) {
		return line.points.front();
	}
	if (distance >= line.points.back().distance) {
		return line.points.back();
	}
	for (index = 0; index + 1 < line.points.size(); index++) {
		const CrossingBoundaryPoint &first = line.points[index];
		const CrossingBoundaryPoint &second = line.points[index + 1];
		if (distance <= second.distance + CROSSING_PLAN_EPSILON) {
			if (fabs(distance - first.distance) <=
			        CROSSING_PLAN_EPSILON) {
				return first;
			}
			if (fabs(distance - second.distance) <=
			        CROSSING_PLAN_EPSILON) {
				return second;
			}
			double length = second.distance - first.distance;
			double parameter = length <= CROSSING_PLAN_EPSILON ? 0.0 :
			        (distance - first.distance) / length;
			CrossingBoundaryPoint result;
			result.distance = distance;
			result.x = first.x + parameter * (second.x - first.x);
			result.y = first.y + parameter * (second.y - first.y);
			result.z = first.z + parameter * (second.z - first.z);
			result.minimumSurfaceZ = first.minimumSurfaceZ + parameter *
			        (second.minimumSurfaceZ - first.minimumSurfaceZ);
			result.maximumSurfaceZ = first.maximumSurfaceZ + parameter *
			        (second.maximumSurfaceZ - first.maximumSurfaceZ);
			result.barrierTopZ = first.barrierTopZ + parameter *
			        (second.barrierTopZ - first.barrierTopZ);
			result.renderedVertex = false;
			return result;
		}
	}
	return line.points.back();
}


static std::vector<CrossingBoundaryPoint>
sliceBoundaryLine(const CrossingBoundaryLine &line,
	             double startDistance, double endDistance)
{
	std::vector<CrossingBoundaryPoint> result;
	bool reverse = startDistance > endDistance;
	double minimum = reverse ? endDistance : startDistance;
	double maximum = reverse ? startDistance : endDistance;
	size_t index;

	result.push_back(interpolateBoundaryPoint(line, minimum));
	for (index = 0; index < line.points.size(); index++) {
		if (line.points[index].renderedVertex &&
		        (line.points[index].distance > minimum +
		         CROSSING_POINT_EPSILON) &&
		        (line.points[index].distance < maximum -
		         CROSSING_POINT_EPSILON)) {
			result.push_back(line.points[index]);
		}
	}
	result.push_back(interpolateBoundaryPoint(line, maximum));
	if (reverse) {
		std::reverse(result.begin(), result.end());
	}
	return result;
}


static bool
findRenderedExtension(const CrossingBoundaryLine &line,
	                 double endpointDistance, double interiorDistance,
	                 CrossingBoundaryPoint *extension)
{
	bool searchBefore = interiorDistance > endpointDistance;
	bool found = false;
	size_t index;
	for (index = 0; index < line.points.size(); index++) {
		const CrossingBoundaryPoint &point = line.points[index];
		if (point.renderedVertex &&
		        (fabs(point.distance - endpointDistance) <=
		         CROSSING_POINT_EPSILON)) {
			*extension = point;
			return true;
		}
	}
	for (index = 0; index < line.points.size(); index++) {
		const CrossingBoundaryPoint &point = line.points[index];
		if (!point.renderedVertex) {
			continue;
		}
		if (searchBefore) {
			if (point.distance >= endpointDistance -
			        CROSSING_PLAN_EPSILON) {
				continue;
			}
			if (!found || (point.distance > extension->distance)) {
				*extension = point;
				found = true;
			}
		} else {
			if (point.distance <= endpointDistance +
			        CROSSING_PLAN_EPSILON) {
				continue;
			}
			if (!found || (point.distance < extension->distance)) {
				*extension = point;
				found = true;
			}
		}
	}
	return found;
}


static double
outerPortalDistance(double socketDistance, double boundaryDistance,
	                double interiorDistance)
{
	return interiorDistance > socketDistance
	        ? std::min(socketDistance, boundaryDistance)
	        : std::max(socketDistance, boundaryDistance);
}


static CrossingLineIntersection
findBoundaryIntersection(const CrossingBoundaryLine &first,
	                     const CrossingBoundaryLine &second,
	                     double crossingX, double crossingY)
{
	CrossingLineIntersection result;
	size_t firstIndex;
	size_t secondIndex;
	for (firstIndex = 0; firstIndex + 1 < first.points.size(); firstIndex++) {
		const CrossingBoundaryPoint &firstStart = first.points[firstIndex];
		const CrossingBoundaryPoint &firstEnd = first.points[firstIndex + 1];
		double firstX = firstEnd.x - firstStart.x;
		double firstY = firstEnd.y - firstStart.y;
		for (secondIndex = 0; secondIndex + 1 < second.points.size();
		        secondIndex++) {
			const CrossingBoundaryPoint &secondStart = second.points[secondIndex];
			const CrossingBoundaryPoint &secondEnd = second.points[secondIndex + 1];
			double secondX = secondEnd.x - secondStart.x;
			double secondY = secondEnd.y - secondStart.y;
			double denominator = crossingCross(firstX, firstY,
			                                   secondX, secondY);
			double startX;
			double startY;
			double firstParameter;
			double secondParameter;
			double x;
			double y;
			double distanceSquared;
			if (fabs(denominator) <= CROSSING_PLAN_EPSILON) {
				continue;
			}
			startX = secondStart.x - firstStart.x;
			startY = secondStart.y - firstStart.y;
			firstParameter = crossingCross(startX, startY, secondX, secondY) /
			                 denominator;
			secondParameter = crossingCross(startX, startY, firstX, firstY) /
			                  denominator;
			if ((firstParameter < -CROSSING_PLAN_EPSILON) ||
			        (firstParameter > 1.0 + CROSSING_PLAN_EPSILON) ||
			        (secondParameter < -CROSSING_PLAN_EPSILON) ||
			        (secondParameter > 1.0 + CROSSING_PLAN_EPSILON)) {
				continue;
			}
			firstParameter = crossingClamp(firstParameter, 0.0, 1.0);
			secondParameter = crossingClamp(secondParameter, 0.0, 1.0);
			x = firstStart.x + firstParameter * firstX;
			y = firstStart.y + firstParameter * firstY;
			distanceSquared = crossingDistanceSquared(x, y,
			                                           crossingX, crossingY);
			if (distanceSquared < result.distanceSquared) {
				result.found = true;
				result.firstDistance = firstStart.distance + firstParameter *
				        (firstEnd.distance - firstStart.distance);
				result.secondDistance = secondStart.distance + secondParameter *
				        (secondEnd.distance - secondStart.distance);
				result.x = x;
				result.y = y;
				result.distanceSquared = distanceSquared;
			}
		}
	}
	return result;
}


static void
appendPolygonSlice(std::vector<CrossingBoundaryPoint> *polygon,
	               const std::vector<CrossingBoundaryPoint> &slice)
{
	size_t index;
	for (index = 0; index < slice.size(); index++) {
		if (!polygon->empty() &&
		        crossingDistanceSquared(polygon->back().x, polygon->back().y,
		            slice[index].x, slice[index].y) <=
		        CROSSING_PLAN_EPSILON * CROSSING_PLAN_EPSILON) {
			continue;
		}
		polygon->push_back(slice[index]);
	}
}


static void
simplifyPolygon(std::vector<CrossingBoundaryPoint> *polygon)
{
	bool changed = true;
	if ((polygon->size() > 1) &&
	        (crossingDistanceSquared(polygon->front().x, polygon->front().y,
	            polygon->back().x, polygon->back().y) <=
	         CROSSING_PLAN_EPSILON * CROSSING_PLAN_EPSILON)) {
		polygon->pop_back();
	}
	while (changed && (polygon->size() > 3)) {
		size_t index;
		changed = false;
		for (index = 0; index < polygon->size(); index++) {
			const CrossingBoundaryPoint &previous =
			        (*polygon)[(index + polygon->size() - 1) % polygon->size()];
			const CrossingBoundaryPoint &current = (*polygon)[index];
			const CrossingBoundaryPoint &next =
			        (*polygon)[(index + 1) % polygon->size()];
			double firstX = current.x - previous.x;
			double firstY = current.y - previous.y;
			double secondX = next.x - current.x;
			double secondY = next.y - current.y;
			if ((crossingDistanceSquared(previous.x, previous.y,
			        current.x, current.y) <=
			        CROSSING_PLAN_EPSILON * CROSSING_PLAN_EPSILON) ||
			        (!current.renderedVertex &&
			         fabs(crossingCross(firstX, firstY, secondX, secondY)) <=
			         CROSSING_PLAN_EPSILON *
			         (sqrt(firstX * firstX + firstY * firstY) +
			          sqrt(secondX * secondX + secondY * secondY)))) {
				polygon->erase(polygon->begin() + index);
				changed = true;
				break;
			}
		}
	}
}


static double
polygonArea(const std::vector<CrossingBoundaryPoint> &polygon)
{
	double area = 0.0;
	size_t index;
	for (index = 0; index < polygon.size(); index++) {
		const CrossingBoundaryPoint &first = polygon[index];
		const CrossingBoundaryPoint &second = polygon[(index + 1) % polygon.size()];
		area += first.x * second.y - second.x * first.y;
	}
	return area / 2.0;
}


static bool
pointInsideTriangle(const CrossingBoundaryPoint &point,
	                const CrossingBoundaryPoint &first,
	                const CrossingBoundaryPoint &second,
	                const CrossingBoundaryPoint &third, double orientation)
{
	double firstCross = crossingCross(second.x - first.x,
	                                 second.y - first.y,
	                                 point.x - first.x,
	                                 point.y - first.y) * orientation;
	double secondCross = crossingCross(third.x - second.x,
	                                  third.y - second.y,
	                                  point.x - second.x,
	                                  point.y - second.y) * orientation;
	double thirdCross = crossingCross(first.x - third.x,
	                                 first.y - third.y,
	                                 point.x - third.x,
	                                 point.y - third.y) * orientation;
	return (firstCross > CROSSING_PLAN_EPSILON) &&
	       (secondCross > CROSSING_PLAN_EPSILON) &&
	       (thirdCross > CROSSING_PLAN_EPSILON);
}


static bool
triangulatePolygon(const std::vector<CrossingBoundaryPoint> &polygon,
	               std::vector<TrackCrossingTriangle> *triangles)
{
	std::vector<int> indices;
	double area = polygonArea(polygon);
	double orientation = area >= 0.0 ? 1.0 : -1.0;
	size_t index;
	int guard = 0;

	if ((polygon.size() < 3) || (fabs(area) <= CROSSING_PLAN_EPSILON)) {
		return false;
	}
	for (index = 0; index < polygon.size(); index++) {
		indices.push_back((int)index);
	}
	while (indices.size() > 3 && guard < (int)(polygon.size() * polygon.size())) {
		bool earFound = false;
		for (index = 0; index < indices.size(); index++) {
			int previousIndex = indices[(index + indices.size() - 1) % indices.size()];
			int currentIndex = indices[index];
			int nextIndex = indices[(index + 1) % indices.size()];
			const CrossingBoundaryPoint &previous = polygon[previousIndex];
			const CrossingBoundaryPoint &current = polygon[currentIndex];
			const CrossingBoundaryPoint &next = polygon[nextIndex];
			double corner = crossingCross(current.x - previous.x,
			                              current.y - previous.y,
			                              next.x - current.x,
			                              next.y - current.y) * orientation;
			bool containsPoint = false;
			size_t testIndex;
			TrackCrossingTriangle triangle;
			if (corner <= CROSSING_PLAN_EPSILON) {
				continue;
			}
			for (testIndex = 0; testIndex < indices.size(); testIndex++) {
				int vertexIndex = indices[testIndex];
				if ((vertexIndex == previousIndex) ||
				        (vertexIndex == currentIndex) ||
				        (vertexIndex == nextIndex)) {
					continue;
				}
				if (pointInsideTriangle(polygon[vertexIndex], previous,
				                        current, next, orientation)) {
					containsPoint = true;
					break;
				}
			}
			if (containsPoint) {
				continue;
			}
			triangle.vertex[0] = previousIndex;
			triangle.vertex[1] = currentIndex;
			triangle.vertex[2] = nextIndex;
			triangles->push_back(triangle);
			indices.erase(indices.begin() + index);
			earFound = true;
			break;
		}
		if (!earFound) {
			return false;
		}
		guard++;
	}
	if (indices.size() == 3) {
		TrackCrossingTriangle triangle;
		triangle.vertex[0] = indices[0];
		triangle.vertex[1] = indices[1];
		triangle.vertex[2] = indices[2];
		triangles->push_back(triangle);
	}
	return !triangles->empty();
}


static std::string
resolveSurfaceTexture(tTrack *track, void *trackHandle, const char *material,
	                 double *textureSize)
{
	const int BUFSIZE = 256;
	char path[BUFSIZE];
	const char *defaultTexture = strcmp(material, TRK_VAL_CONCRETE) == 0
	        ? "tr-concrete_nmm.rgb" : "tr-asphalt.rgb";
	if (textureSize != NULL) {
		*textureSize = CROSSING_TEXTURE_SIZE;
	}
	if (trackHandle == NULL) {
		return defaultTexture;
	}
	if (track->version < 4) {
		snprintf(path, BUFSIZE, "%s/%s/%s", TRK_SECT_SURFACES,
		         TRK_LST_SURF, material);
	} else {
		snprintf(path, BUFSIZE, "%s/%s", TRK_SECT_SURFACES, material);
	}
	if (textureSize != NULL) {
		*textureSize = GfParmGetNum(trackHandle, path, TRK_ATT_TEXSIZE,
		                               (char *)NULL, CROSSING_TEXTURE_SIZE);
		if (!crossingFinite(*textureSize) || (*textureSize <= 0.0)) {
			*textureSize = CROSSING_TEXTURE_SIZE;
		}
	}
	return GfParmGetStr(trackHandle, path, TRK_ATT_TEXTURE, defaultTexture);
}


static const char *
getBoundaryMaterial(tTrackSeg *mainSegment, int side)
{
	tTrackSeg *outer = getOutermostSegment(mainSegment, side);
	if ((outer->surface != NULL) && (outer->surface->material != NULL)) {
		return outer->surface->material;
	}
	if ((mainSegment->surface != NULL) &&
	        (mainSegment->surface->material != NULL)) {
		return mainSegment->surface->material;
	}
	return TRK_VAL_ASPHALT;
}


struct CrossingTexture
{
	std::string name;
	double sizeU;
	double sizeV;
};


/** @brief Resolve a visual crossing surface, retaining legacy material fallback. */
static CrossingTexture
resolveCrossingTexture(tTrack *track, void *trackHandle, const char *selector,
                      const char *defaultSurface, const char *fallbackSurface)
{
	CrossingTexture texture;
	texture.name = resolveSurfaceTexture(track, trackHandle, fallbackSurface, &texture.sizeU);
	texture.sizeV = texture.sizeU;
	if (trackHandle == NULL) {
		return texture;
	}
	const char *surface = GfParmGetStr(trackHandle, TRK_SECT_TERRAIN, selector, defaultSurface);
	if (*surface == '\0') {
		surface = defaultSurface;
	}
	char path[256];
	if (track->version < 4) {
		snprintf(path, sizeof(path), "%s/%s/%s", TRK_SECT_SURFACES, TRK_LST_SURF, surface);
	} else {
		snprintf(path, sizeof(path), "%s/%s", TRK_SECT_SURFACES, surface);
	}
	const char *name = GfParmGetStr(trackHandle, path, TRK_ATT_TEXTURE, NULL);
	if (name == NULL || *name == '\0') {
		return texture;
	}
	texture.name = name;
	double size = GfParmGetNum(trackHandle, path, TRK_ATT_TEXSIZE, (char *)NULL, texture.sizeU);
	if (crossingFinite(size) && size > 0.0) {
		texture.sizeU = size;
	}
	size = GfParmGetNum(trackHandle, path, TRK_ATT_TEXSIZE_V, (char *)NULL, texture.sizeU);
	texture.sizeV = crossingFinite(size) && size > 0.0 ? size : texture.sizeU;
	return texture;
}


/** @brief Horizontal arclength at a point projected onto a sampled boundary. */
static double
boundaryTextureDistance(const CrossingBoundaryLine &line, double x, double y)
{
	double along = 0.0;
	double closest = DBL_MAX;
	double result = 0.0;
	for (size_t index = 0; index + 1 < line.points.size(); index++) {
		const CrossingBoundaryPoint &first = line.points[index];
		const CrossingBoundaryPoint &second = line.points[index + 1];
		double dx = second.x - first.x;
		double dy = second.y - first.y;
		double squaredLength = dx * dx + dy * dy;
		double length = sqrt(squaredLength);
		if (length > CROSSING_PLAN_EPSILON) {
			double parameter = crossingClamp(((x - first.x) * dx + (y - first.y) * dy) /
			        squaredLength, 0.0, 1.0);
			double distance = crossingDistanceSquared(x, y,
			        first.x + parameter * dx, first.y + parameter * dy);
			if (distance < closest) {
				closest = distance;
				result = along + parameter * length;
			}
		}
		along += length;
	}
	return result;
}


static double
boundaryTextureOrigin(const CrossingBoundaryLine &line, double distance)
{
	CrossingBoundaryPoint point = interpolateBoundaryPoint(line, distance);
	return boundaryTextureDistance(line, point.x, point.y);
}


/** @brief Fit the complete material family vertically without changing aspect ratio. */
static CrossingTexture
fitVerticalTexture(CrossingTexture texture, TrackCrossingObject *const *parts,
                   size_t count, double *top)
{
	double minimum = DBL_MAX;
	double maximum = -DBL_MAX;
	for (size_t part = 0; part < count; part++) {
		for (size_t index = 0; index < parts[part]->vertices.size(); index++) {
			double z = parts[part]->vertices[index].z;
			minimum = std::min(minimum, z);
			maximum = std::max(maximum, z);
		}
	}
	*top = maximum;
	double scale = std::max(1.0, (maximum - minimum) / texture.sizeV);
	texture.sizeU *= scale;
	texture.sizeV *= scale;
	return texture;
}


static void
mapVerticalTexture(TrackCrossingObject *object, const CrossingBoundaryLine &line,
                   double origin, const CrossingTexture &texture, double top)
{
	object->texture = texture.name;
	for (size_t index = 0; index < object->vertices.size(); index++) {
		TrackCrossingPoint &point = object->vertices[index];
		point.u = (boundaryTextureDistance(line, point.x, point.y) - origin) / texture.sizeU;
		point.v = 1.0 + (point.z - top) / texture.sizeV;
	}
}


/** @brief Map a return in its own vertical frame, anchored to the socket edge. */
static void
mapFillerTexture(TrackCrossingObject *object, const CrossingBoundaryPoint &corner,
                 const CrossingBoundaryLine &socket, double origin,
                 const CrossingPlanPoint &lowerTangent,
                 const CrossingTexture &texture, double top)
{
	object->texture = texture.name;
	CrossingPlanPoint horizontal = lowerTangent;
	double largest = 0.0;
	for (size_t index = 0; index < object->triangles.size(); index++) {
		const TrackCrossingTriangle &triangle = object->triangles[index];
		const TrackCrossingPoint &a = object->vertices[triangle.vertex[0]];
		const TrackCrossingPoint &b = object->vertices[triangle.vertex[1]];
		const TrackCrossingPoint &c = object->vertices[triangle.vertex[2]];
		double nx = (b.y - a.y) * (c.z - a.z) - (b.z - a.z) * (c.y - a.y);
		double ny = (b.z - a.z) * (c.x - a.x) - (b.x - a.x) * (c.z - a.z);
		double length = sqrt(nx * nx + ny * ny);
		if (length > largest) {
			largest = length;
			horizontal.x = ny / length;
			horizontal.y = -nx / length;
		}
	}
	if (horizontal.x * lowerTangent.x + horizontal.y * lowerTangent.y < 0.0) {
		horizontal.x = -horizontal.x;
		horizontal.y = -horizontal.y;
	}
	double anchor = boundaryTextureDistance(socket, corner.x, corner.y) - origin;
	for (size_t index = 0; index < object->vertices.size(); index++) {
		TrackCrossingPoint &point = object->vertices[index];
		point.u = (anchor + (point.x - corner.x) * horizontal.x +
		        (point.y - corner.y) * horizontal.y) / texture.sizeU;
		point.v = 1.0 + (point.z - top) / texture.sizeV;
	}
}


/** @brief Apply role-specific UVs only after all crossing geometry is complete. */
static void
mapCrossingTextures(tTrack *track, void *trackHandle, tTrackSeg *lowerSegment,
                    const CrossingPlanPoint &center, const CrossingPlanPoint &upperTangent,
                    const CrossingPlanPoint &lowerTangent,
                    const CrossingBoundaryLine *const *upperLines,
                    const CrossingBoundaryLine *const *socketLines,
                    double upperDistance, double lowerDistance,
                    const CrossingBoundaryPoint corners[2][2], TrackCrossingGeometry *geometry)
{
	CrossingTexture underside = resolveCrossingTexture(track, trackHandle,
	        TRK_ATT_CROSSING_UNDERSIDE_SURFACE, TRK_VAL_BRIDGE_UNDERSIDE, TRK_VAL_CONCRETE);
	CrossingPlanPoint across = {-upperTangent.y, upperTangent.x};
	double minimumU = DBL_MAX;
	double maximumU = -DBL_MAX;
	double minimumV = DBL_MAX;
	for (size_t index = 0; index < geometry->underside.vertices.size(); index++) {
		const TrackCrossingPoint &point = geometry->underside.vertices[index];
		double x = point.x - center.x;
		double y = point.y - center.y;
		double u = x * across.x + y * across.y;
		minimumU = std::min(minimumU, u);
		maximumU = std::max(maximumU, u);
		minimumV = std::min(minimumV, x * upperTangent.x + y * upperTangent.y);
	}
	double scale = std::max(1.0, (maximumU - minimumU) / underside.sizeU);
	geometry->underside.texture = underside.name;
	for (size_t index = 0; index < geometry->underside.vertices.size(); index++) {
		TrackCrossingPoint &point = geometry->underside.vertices[index];
		double x = point.x - center.x;
		double y = point.y - center.y;
		point.u = (x * across.x + y * across.y - minimumU) / (underside.sizeU * scale);
		point.v = (x * upperTangent.x + y * upperTangent.y - minimumV) / (underside.sizeV * scale);
	}

	TrackCrossingObject *fascia[] = {&geometry->bridgeRight, &geometry->bridgeLeft};
	TrackCrossingObject *sockets[] = {&geometry->socketRight, &geometry->socketLeft};
	TrackCrossingObject *socketParts[] = {sockets[0], sockets[1],
	        &geometry->filler[0][0], &geometry->filler[0][1],
	        &geometry->filler[1][0], &geometry->filler[1][1]};
	TrackCrossingObject *floors[] = {&geometry->floorRight, &geometry->floorLeft};
	double sideTop;
	double socketTop;
	CrossingTexture sideTexture = fitVerticalTexture(resolveCrossingTexture(track, trackHandle,
	        TRK_ATT_CROSSING_SIDE_SURFACE, TRK_VAL_BRIDGE_SIDE, TRK_VAL_CONCRETE),
	        fascia, 2, &sideTop);
	CrossingTexture socketTexture = fitVerticalTexture(resolveCrossingTexture(track, trackHandle,
	        TRK_ATT_CROSSING_SOCKET_SURFACE, TRK_VAL_BRIDGE_SOCKET, TRK_VAL_CONCRETE),
	        socketParts, 6, &socketTop);
	for (int side = 0; side < 2; side++) {
		mapVerticalTexture(fascia[side], *upperLines[side],
		        boundaryTextureOrigin(*upperLines[side], upperDistance), sideTexture, sideTop);
		double socketOrigin = boundaryTextureOrigin(*socketLines[side], lowerDistance);
		mapVerticalTexture(sockets[side], *socketLines[side], socketOrigin, socketTexture, socketTop);
		for (int upperSide = 0; upperSide < 2; upperSide++) {
			mapFillerTexture(&geometry->filler[upperSide][side], corners[upperSide][side],
			        *socketLines[side], socketOrigin, lowerTangent, socketTexture, socketTop);
		}
		CrossingTexture floorTexture = resolveCrossingTexture(track, trackHandle,
		        TRK_ATT_CROSSING_FLOOR_SURFACE, TRK_VAL_BRIDGE_FLOOR,
		        getBoundaryMaterial(lowerSegment, side));
		floors[side]->texture = floorTexture.name;
		for (size_t index = 0; index < floors[side]->vertices.size(); index++) {
			TrackCrossingPoint &point = floors[side]->vertices[index];
			double x = point.x - center.x;
			double y = point.y - center.y;
			point.u = (x * lowerTangent.x + y * lowerTangent.y) / floorTexture.sizeU;
			point.v = (-x * lowerTangent.y + y * lowerTangent.x) / floorTexture.sizeV;
		}
	}
}


static void
appendObjectPoint(TrackCrossingObject *object, double x, double y, double z,
	              double u, double v)
{
	TrackCrossingPoint point;
	point.x = x;
	point.y = y;
	point.z = z;
	point.u = u;
	point.v = v;
	object->vertices.push_back(point);
}


static void
appendStripTriangles(TrackCrossingObject *object, size_t stationCount)
{
	size_t station;
	for (station = 0; station + 1 < stationCount; station++) {
		TrackCrossingTriangle first;
		TrackCrossingTriangle second;
		first.vertex[0] = (int)(2 * station);
		first.vertex[1] = (int)(2 * station + 1);
		first.vertex[2] = (int)(2 * station + 2);
		second.vertex[0] = (int)(2 * station + 1);
		second.vertex[1] = (int)(2 * station + 3);
		second.vertex[2] = (int)(2 * station + 2);
		object->triangles.push_back(first);
		object->triangles.push_back(second);
	}
}


static size_t
appendObjectTriangle(TrackCrossingObject *object,
	                int first, int second, int third)
{
	TrackCrossingTriangle triangle;
	triangle.vertex[0] = first;
	triangle.vertex[1] = second;
	triangle.vertex[2] = third;
	object->triangles.push_back(triangle);
	return object->triangles.size() - 1;
}


static int
findPolygonVertex(const std::vector<CrossingBoundaryPoint> &polygon,
	             const CrossingBoundaryPoint &point)
{
	size_t index;
	for (index = 0; index < polygon.size(); index++) {
		if (crossingDistanceSquared(polygon[index].x, polygon[index].y,
		        point.x, point.y) <=
		        CROSSING_POINT_EPSILON * CROSSING_POINT_EPSILON) {
			return (int)index;
		}
	}
	return -1;
}


static bool
collectPolygonIndices(const std::vector<CrossingBoundaryPoint> &polygon,
	                 const std::vector<CrossingBoundaryPoint> &line,
	                 std::vector<int> *indices)
{
	size_t index;
	for (index = 0; index < line.size(); index++) {
		int vertexIndex = findPolygonVertex(polygon, line[index]);
		if (vertexIndex < 0) {
			return false;
		}
		if (indices->empty() || (indices->back() != vertexIndex)) {
			indices->push_back(vertexIndex);
		}
	}
	return !indices->empty();
}


static bool
appendBridgeStripTriangles(
		const std::vector<CrossingBoundaryPoint> &polygon,
		const std::vector<CrossingBoundaryPoint> &right,
		const std::vector<CrossingBoundaryPoint> &left,
		TrackCrossingObject *object)
{
	/* Zip longitudinal boundaries by station instead of fanning from one point. */
	std::vector<int> rightIndices;
	std::vector<int> leftIndices;
	double rightSpan;
	double leftSpan;
	double direction;
	size_t rightIndex = 0;
	size_t leftIndex = 0;
	if (!collectPolygonIndices(polygon, right, &rightIndices) ||
	        !collectPolygonIndices(polygon, left, &leftIndices) ||
	        (rightIndices.size() != right.size()) ||
	        (leftIndices.size() != left.size()) ||
	        rightIndices.empty() || leftIndices.empty()) {
		return false;
	}
	if (rightIndices.size() == 1) {
		for (leftIndex = 0; leftIndex + 1 < leftIndices.size(); leftIndex++) {
			appendObjectTriangle(object, rightIndices[0],
			                     leftIndices[leftIndex],
			                     leftIndices[leftIndex + 1]);
		}
		return true;
	}
	if (leftIndices.size() == 1) {
		for (rightIndex = 0; rightIndex + 1 < rightIndices.size();
		        rightIndex++) {
			appendObjectTriangle(object, rightIndices[rightIndex],
			                     leftIndices[0],
			                     rightIndices[rightIndex + 1]);
		}
		return true;
	}
	rightSpan = right.back().distance - right.front().distance;
	leftSpan = left.back().distance - left.front().distance;
	if ((fabs(rightSpan) <= CROSSING_PLAN_EPSILON) ||
	        (rightSpan * leftSpan <= 0.0)) {
		return false;
	}
	direction = rightSpan > 0.0 ? 1.0 : -1.0;
	while ((rightIndex + 1 < rightIndices.size()) ||
	        (leftIndex + 1 < leftIndices.size())) {
		if (rightIndex + 1 >= rightIndices.size()) {
			appendObjectTriangle(object, rightIndices[rightIndex],
			                     leftIndices[leftIndex],
			                     leftIndices[leftIndex + 1]);
			leftIndex++;
		} else if (leftIndex + 1 >= leftIndices.size()) {
			appendObjectTriangle(object, rightIndices[rightIndex],
			                     leftIndices[leftIndex],
			                     rightIndices[rightIndex + 1]);
			rightIndex++;
		} else {
			double rightDistance = direction * right[rightIndex + 1].distance;
			double leftDistance = direction * left[leftIndex + 1].distance;
			if (fabs(rightDistance - leftDistance) <=
			        CROSSING_POINT_EPSILON) {
				appendObjectTriangle(object, rightIndices[rightIndex],
				                     leftIndices[leftIndex],
				                     rightIndices[rightIndex + 1]);
				appendObjectTriangle(object, leftIndices[leftIndex],
				                     leftIndices[leftIndex + 1],
				                     rightIndices[rightIndex + 1]);
				rightIndex++;
				leftIndex++;
			} else if (rightDistance < leftDistance) {
				appendObjectTriangle(object, rightIndices[rightIndex],
				                     leftIndices[leftIndex],
				                     rightIndices[rightIndex + 1]);
				rightIndex++;
			} else {
				appendObjectTriangle(object, rightIndices[rightIndex],
				                     leftIndices[leftIndex],
				                     leftIndices[leftIndex + 1]);
				leftIndex++;
			}
		}
	}
	return true;
}


static bool
orientBridgeCap(const std::vector<CrossingBoundaryPoint> &cap,
	           const CrossingBoundaryPoint &right,
	           const CrossingBoundaryPoint &left,
	           std::vector<CrossingBoundaryPoint> *row)
{
	if (cap.size() < 2) {
		return false;
	}
	*row = cap;
	if ((crossingDistanceSquared(row->front().x, row->front().y,
	        right.x, right.y) <=
	        CROSSING_POINT_EPSILON * CROSSING_POINT_EPSILON) &&
	        (crossingDistanceSquared(row->back().x, row->back().y,
	         left.x, left.y) <=
	         CROSSING_POINT_EPSILON * CROSSING_POINT_EPSILON)) {
		return true;
	}
	if ((crossingDistanceSquared(row->front().x, row->front().y,
	        left.x, left.y) <=
	        CROSSING_POINT_EPSILON * CROSSING_POINT_EPSILON) &&
	        (crossingDistanceSquared(row->back().x, row->back().y,
	         right.x, right.y) <=
	         CROSSING_POINT_EPSILON * CROSSING_POINT_EPSILON)) {
		std::reverse(row->begin(), row->end());
		return true;
	}
	return false;
}


static bool
collectRowProgress(const std::vector<CrossingBoundaryPoint> &row,
	              std::vector<double> *progress)
{
	double total = 0.0;
	size_t index;
	if (row.size() < 2) {
		return false;
	}
	progress->push_back(0.0);
	for (index = 1; index < row.size(); index++) {
		total += sqrt(crossingDistanceSquared(row[index - 1].x,
		        row[index - 1].y, row[index].x, row[index].y));
		progress->push_back(total);
	}
	if (total <= CROSSING_PLAN_EPSILON) {
		return false;
	}
	for (index = 1; index < progress->size(); index++) {
		(*progress)[index] /= total;
	}
	return true;
}


static bool
appendBridgeRowTriangles(
		const std::vector<CrossingBoundaryPoint> &polygon,
		const std::vector<CrossingBoundaryPoint> &firstRow,
		const std::vector<CrossingBoundaryPoint> &secondRow,
		TrackCrossingObject *object)
{
	/* Fold a multi-vertex cap into its adjacent longitudinal station row. */
	std::vector<int> firstIndices;
	std::vector<int> secondIndices;
	std::vector<double> firstProgress;
	std::vector<double> secondProgress;
	size_t firstIndex = 0;
	size_t secondIndex = 0;
	if (!collectPolygonIndices(polygon, firstRow, &firstIndices) ||
	        !collectPolygonIndices(polygon, secondRow, &secondIndices) ||
	        (firstIndices.size() != firstRow.size()) ||
	        (secondIndices.size() != secondRow.size()) ||
	        !collectRowProgress(firstRow, &firstProgress) ||
	        !collectRowProgress(secondRow, &secondProgress)) {
		return false;
	}
	while ((firstIndex + 1 < firstIndices.size()) ||
	        (secondIndex + 1 < secondIndices.size())) {
		if (firstIndex + 1 >= firstIndices.size()) {
			appendObjectTriangle(object, firstIndices[firstIndex],
			                     secondIndices[secondIndex],
			                     secondIndices[secondIndex + 1]);
			secondIndex++;
		} else if (secondIndex + 1 >= secondIndices.size()) {
			appendObjectTriangle(object, firstIndices[firstIndex],
			                     secondIndices[secondIndex],
			                     firstIndices[firstIndex + 1]);
			firstIndex++;
		} else if (fabs(firstProgress[firstIndex + 1] -
		        secondProgress[secondIndex + 1]) <=
		        CROSSING_POINT_EPSILON) {
			appendObjectTriangle(object, firstIndices[firstIndex],
			                     secondIndices[secondIndex],
			                     firstIndices[firstIndex + 1]);
			appendObjectTriangle(object, firstIndices[firstIndex + 1],
			                     secondIndices[secondIndex],
			                     secondIndices[secondIndex + 1]);
			firstIndex++;
			secondIndex++;
		} else if (firstProgress[firstIndex + 1] <
		        secondProgress[secondIndex + 1]) {
			appendObjectTriangle(object, firstIndices[firstIndex],
			                     secondIndices[secondIndex],
			                     firstIndices[firstIndex + 1]);
			firstIndex++;
		} else {
			appendObjectTriangle(object, firstIndices[firstIndex],
			                     secondIndices[secondIndex],
			                     secondIndices[secondIndex + 1]);
			secondIndex++;
		}
	}
	return true;
}


static bool
appendBridgeCapTriangles(
		const std::vector<CrossingBoundaryPoint> &polygon,
		const std::vector<CrossingBoundaryPoint> &cap,
		TrackCrossingObject *object)
{
	std::vector<int> capIndices;
	std::vector<CrossingBoundaryPoint> capPolygon;
	std::vector<TrackCrossingTriangle> capTriangles;
	size_t index;
	if (!collectPolygonIndices(polygon, cap, &capIndices)) {
		return false;
	}
	if (capIndices.size() < 3) {
		return true;
	}
	for (index = 0; index < capIndices.size(); index++) {
		capPolygon.push_back(polygon[capIndices[index]]);
	}
	if (fabs(polygonArea(capPolygon)) <= CROSSING_PLAN_EPSILON) {
		return true;
	}
	if (!triangulatePolygon(capPolygon, &capTriangles)) {
		return false;
	}
	for (index = 0; index < capTriangles.size(); index++) {
		appendObjectTriangle(object,
		        capIndices[capTriangles[index].vertex[0]],
		        capIndices[capTriangles[index].vertex[1]],
		        capIndices[capTriangles[index].vertex[2]]);
	}
	return true;
}


static bool
triangulateBridgeUnderside(
		const std::vector<CrossingBoundaryPoint> &polygon,
		const std::vector<CrossingBoundaryPoint> &right,
		const std::vector<CrossingBoundaryPoint> &left,
		const std::vector<CrossingBoundaryPoint> &firstCap,
		const std::vector<CrossingBoundaryPoint> &secondCap,
		TrackCrossingObject *object)
{
	/* Cap rows become end cells; only the interior remains a regular strip. */
	size_t firstTriangle = object->triangles.size();
	std::vector<CrossingBoundaryPoint> firstRow;
	std::vector<CrossingBoundaryPoint> secondRow;
	std::vector<CrossingBoundaryPoint> firstInteriorRow;
	std::vector<CrossingBoundaryPoint> secondInteriorRow;
	std::vector<CrossingBoundaryPoint> middleRight;
	std::vector<CrossingBoundaryPoint> middleLeft;
	if ((right.size() < 3) || (left.size() < 3)) {
		return appendBridgeStripTriangles(polygon, right, left, object) &&
		       appendBridgeCapTriangles(polygon, firstCap, object) &&
		       appendBridgeCapTriangles(polygon, secondCap, object) &&
		       (object->triangles.size() > firstTriangle);
	}
	if (!orientBridgeCap(firstCap, right.front(), left.front(), &firstRow) ||
	        !orientBridgeCap(secondCap, right.back(), left.back(),
	                         &secondRow)) {
		return false;
	}
	firstInteriorRow.push_back(right[1]);
	firstInteriorRow.push_back(left[1]);
	secondInteriorRow.push_back(right[right.size() - 2]);
	secondInteriorRow.push_back(left[left.size() - 2]);
	middleRight.assign(right.begin() + 1, right.end() - 1);
	middleLeft.assign(left.begin() + 1, left.end() - 1);
	return appendBridgeRowTriangles(polygon, firstRow, firstInteriorRow,
	                                object) &&
	       appendBridgeStripTriangles(polygon, middleRight, middleLeft,
	                                  object) &&
	       appendBridgeRowTriangles(polygon, secondInteriorRow, secondRow,
	                                object) &&
	       (object->triangles.size() > firstTriangle);
}


static void
orientObjectTriangle(TrackCrossingObject *object, size_t triangleIndex,
	                 double targetX, double targetY, double targetZ)
{
	TrackCrossingTriangle &triangle = object->triangles[triangleIndex];
	const TrackCrossingPoint &first = object->vertices[triangle.vertex[0]];
	const TrackCrossingPoint &second = object->vertices[triangle.vertex[1]];
	const TrackCrossingPoint &third = object->vertices[triangle.vertex[2]];
	double firstX = second.x - first.x;
	double firstY = second.y - first.y;
	double firstZ = second.z - first.z;
	double secondX = third.x - first.x;
	double secondY = third.y - first.y;
	double secondZ = third.z - first.z;
	double normalX = firstY * secondZ - firstZ * secondY;
	double normalY = firstZ * secondX - firstX * secondZ;
	double normalZ = firstX * secondY - firstY * secondX;
	if (normalX * targetX + normalY * targetY + normalZ * targetZ < 0.0) {
		std::swap(triangle.vertex[1], triangle.vertex[2]);
	}
}


static void
orientObjectVertically(TrackCrossingObject *object, double direction)
{
	size_t triangleIndex;
	for (triangleIndex = 0; triangleIndex < object->triangles.size();
	        triangleIndex++) {
		orientObjectTriangle(object, triangleIndex, 0.0, 0.0, direction);
	}
}


static void
removeCollapsedPlanTriangles(TrackCrossingObject *object)
{
	std::vector<TrackCrossingTriangle>::iterator triangle =
	        object->triangles.begin();
	while (triangle != object->triangles.end()) {
		const TrackCrossingPoint &first = object->vertices[triangle->vertex[0]];
		const TrackCrossingPoint &second = object->vertices[triangle->vertex[1]];
		const TrackCrossingPoint &third = object->vertices[triangle->vertex[2]];
		double doubledArea = fabs(crossingCross(second.x - first.x,
		        second.y - first.y, third.x - first.x, third.y - first.y));
		if (doubledArea <= CROSSING_PLAN_EPSILON) {
			triangle = object->triangles.erase(triangle);
		} else {
			triangle++;
		}
	}
}


static void
buildSocketWall(const CrossingBoundaryLine &boundary,
	            const CrossingBoundaryLine &socket,
	            double firstDistance, double secondDistance,
	            int side, double undersideZ, double textureSize,
	            TrackCrossingObject *object)
{
	std::vector<CrossingBoundaryPoint> boundaryPoints = sliceBoundaryLine(
	        boundary, firstDistance, secondDistance);
	std::vector<CrossingBoundaryPoint> socketPoints = sliceBoundaryLine(
	        socket, firstDistance, secondDistance);
	double along = 0.0;
	size_t firstTriangle = object->triangles.size();
	size_t index;
	if (boundaryPoints.size() != socketPoints.size()) {
		return;
	}
	for (index = 0; index < socketPoints.size(); index++) {
		const CrossingBoundaryPoint &point = socketPoints[index];
		if (index > 0) {
			const TrackCrossingPoint &previous =
			        object->vertices[object->vertices.size() - 2];
			along += sqrt(crossingDistanceSquared(previous.x, previous.y,
			                                      point.x, point.y));
		}
		appendObjectPoint(object, point.x, point.y, point.z,
		                  along / textureSize, 0.0);
		appendObjectPoint(object, point.x, point.y, undersideZ,
		                  along / textureSize,
		                  (undersideZ - point.z) / textureSize);
	}
	appendStripTriangles(object, socketPoints.size());
	for (index = 0; index + 1 < socketPoints.size(); index++) {
		const CrossingBoundaryPoint &firstBoundary = boundaryPoints[index];
		const CrossingBoundaryPoint &secondBoundary = boundaryPoints[index + 1];
		const CrossingBoundaryPoint &firstSocket = socketPoints[index];
		const CrossingBoundaryPoint &secondSocket = socketPoints[index + 1];
		double targetX = firstBoundary.x + secondBoundary.x -
		        firstSocket.x - secondSocket.x;
		double targetY = firstBoundary.y + secondBoundary.y -
		        firstSocket.y - secondSocket.y;
		if (targetX * targetX + targetY * targetY <=
		        CROSSING_PLAN_EPSILON * CROSSING_PLAN_EPSILON) {
			CrossingPlanPoint normal = getBoundaryNormal(boundary,
			        (firstBoundary.distance + secondBoundary.distance) / 2.0, side);
			targetX = -normal.x;
			targetY = -normal.y;
		}
		orientObjectTriangle(object, firstTriangle + 2 * index,
		                     targetX, targetY, 0.0);
		orientObjectTriangle(object, firstTriangle + 2 * index + 1,
		                     targetX, targetY, 0.0);
	}
}


static void
buildFloorStrip(const CrossingBoundaryLine &boundary,
	            const CrossingBoundaryLine &socket,
	            double firstDistance, double secondDistance,
	            const CrossingBoundaryPoint &firstExtension,
	            const CrossingBoundaryPoint &secondExtension,
	            double textureSize, TrackCrossingObject *object)
{
	/* Endpoint substitutions retain the renderer's outer boundary vertices. */
	std::vector<CrossingBoundaryPoint> boundaryPoints;
	std::vector<CrossingBoundaryPoint> socketPoints;
	CrossingBoundaryPoint previousBoundary;
	double along = 0.0;
	bool hasGap = false;
	size_t index;
	boundaryPoints = sliceBoundaryLine(boundary, firstDistance, secondDistance);
	socketPoints = sliceBoundaryLine(socket, firstDistance, secondDistance);
	if (boundaryPoints.size() != socketPoints.size()) {
		return;
	}
	/* Inspect the actual floor span. The sampling window's first two points
	 * can coincide after renderer rounding, giving its end offset a zero normal. */
	for (index = 0; index < boundaryPoints.size(); index++) {
		if (crossingDistanceSquared(boundaryPoints[index].x,
		        boundaryPoints[index].y, socketPoints[index].x,
		        socketPoints[index].y) >
		        CROSSING_PLAN_EPSILON * CROSSING_PLAN_EPSILON) {
			hasGap = true;
			break;
		}
	}
	if (!hasGap) {
		return;
	}
	for (index = 0; index < boundaryPoints.size(); index++) {
		CrossingBoundaryPoint boundaryPoint;
		const CrossingBoundaryPoint &socketPoint = socketPoints[index];
		double width;
		if (index == 0) {
			boundaryPoint = firstExtension;
		} else if (index + 1 == boundaryPoints.size()) {
			boundaryPoint = secondExtension;
		} else {
			boundaryPoint = boundaryPoints[index];
		}
		if (index > 0) {
			along += sqrt(crossingDistanceSquared(previousBoundary.x,
			        previousBoundary.y, boundaryPoint.x, boundaryPoint.y));
		}
		width = sqrt(crossingDistanceSquared(boundaryPoint.x,
		        boundaryPoint.y, socketPoint.x, socketPoint.y));
		appendObjectPoint(object, boundaryPoint.x, boundaryPoint.y,
		                  boundaryPoint.z, along / textureSize, 0.0);
		appendObjectPoint(object, socketPoint.x, socketPoint.y,
		                  socketPoint.z, along / textureSize,
		                  width / textureSize);
		previousBoundary = boundaryPoint;
	}
	appendStripTriangles(object, boundaryPoints.size());
	orientObjectVertically(object, 1.0);
}


static int
findObjectVertex(const TrackCrossingObject &object,
	            const CrossingBoundaryPoint &point, double z)
{
	size_t index;
	for (index = 0; index < object.vertices.size(); index++) {
		const TrackCrossingPoint &vertex = object.vertices[index];
		if ((crossingDistanceSquared(vertex.x, vertex.y,
		        point.x, point.y) <=
		        CROSSING_PLAN_EPSILON * CROSSING_PLAN_EPSILON) &&
		        (fabs(vertex.z - z) <= CROSSING_HEIGHT_EPSILON)) {
			return (int)index;
		}
	}
	return -1;
}


/** @brief Copy one face between parts, retaining winding and per-vertex UVs. */
static void
appendObjectFace(const TrackCrossingObject &source, size_t triangleIndex,
                 TrackCrossingObject *object)
{
	int vertices[3];
	for (int reference = 0; reference < 3; reference++) {
		const TrackCrossingPoint &point = source.vertices[
		        source.triangles[triangleIndex].vertex[reference]];
		size_t index;
		for (index = 0; index < object->vertices.size(); index++) {
			const TrackCrossingPoint &existing = object->vertices[index];
			if (existing.x == point.x && existing.y == point.y &&
			        existing.z == point.z && existing.u == point.u && existing.v == point.v) {
				break;
			}
		}
		vertices[reference] = (int)index;
		if (index == object->vertices.size()) {
			object->vertices.push_back(point);
		}
	}
	appendObjectTriangle(object, vertices[0], vertices[1], vertices[2]);
}


/** @brief Close a portal, separating the fascia extension from the return. */
static void
appendSocketPortal(const CrossingBoundaryPoint &bridgeTop,
                   const CrossingBoundaryPoint &socketCorner,
                   const CrossingBoundaryPoint &floorExtension,
                   const CrossingPlanPoint &fasciaNormal,
                   double undersideZ, double textureSize,
                   const TrackCrossingObject &socket,
                   TrackCrossingObject *fascia, TrackCrossingObject *filler)
{
	/* The existing fascia, wall and floor each end in one edge, regardless
	 * of the number of samples inside their strips. Close that four-edge
	 * boundary, retaining the vertical wall edge at the underside corner.
	 * A single copy of the terrain-mask triangle would miss this edge. */
	TrackCrossingObject portal;
	TrackCrossingObject *object = &portal;
	int firstVertex = 0;
	int baseVertex = findObjectVertex(socket, socketCorner, socketCorner.z);
	int topVertex = findObjectVertex(socket, socketCorner, undersideZ);
	bool reverse = false;
	/* Continue the wall's winding across its end edge. A projected-area sign
	 * is unstable when the portal is vertical or nearly aligned to a sample. */
	for (size_t index = 0; index < socket.triangles.size(); index++) {
		const TrackCrossingTriangle &triangle = socket.triangles[index];
		for (int edge = 0; edge < 3; edge++) {
			if (triangle.vertex[edge] == topVertex &&
			        triangle.vertex[(edge + 1) % 3] == baseVertex) {
				reverse = true;
			}
		}
	}
	double upperU = sqrt(crossingDistanceSquared(bridgeTop.x, bridgeTop.y,
	        socketCorner.x, socketCorner.y)) / textureSize;
	double floorU = -sqrt(crossingDistanceSquared(floorExtension.x,
	        floorExtension.y, socketCorner.x, socketCorner.y)) / textureSize;
	appendObjectPoint(object, bridgeTop.x, bridgeTop.y, bridgeTop.z,
	                  upperU, (bridgeTop.z - socketCorner.z) / textureSize);
	appendObjectPoint(object, socketCorner.x, socketCorner.y, undersideZ,
	                  0.0, (undersideZ - socketCorner.z) / textureSize);
	appendObjectPoint(object, socketCorner.x, socketCorner.y, socketCorner.z,
	                  0.0, 0.0);
	appendObjectPoint(object, floorExtension.x, floorExtension.y, floorExtension.z,
	                  floorU, (floorExtension.z - socketCorner.z) / textureSize);
	/* If the upper endpoint is exactly above the socket corner, retain the
	 * underside vertex by using the other diagonal instead of a collinear ear. */
	const int regular[2][3] = { {0, 1, 2}, {0, 2, 3} };
	const int aligned[2][3] = { {0, 1, 3}, {1, 2, 3} };
	bool alignedEndpoint = upperU * textureSize <= CROSSING_POINT_EPSILON;
	const int (*triangles)[3] = alignedEndpoint ? aligned : regular;
	/* The usual first face continues the upper side's vertical plane. If
	 * the floor endpoint also lies in that plane, the whole closure is fascia.
	 * At an aligned endpoint the alternate diagonal subdivides the return;
	 * keep both faces together unless that return is coplanar with the fascia. */
	bool coplanarReturn = fabs((floorExtension.x - socketCorner.x) * fasciaNormal.x +
	        (floorExtension.y - socketCorner.y) * fasciaNormal.y) <= CROSSING_POINT_EPSILON;
	for (int index = 0; index < 2; index++) {
		int first = firstVertex + triangles[index][0];
		int second = firstVertex + triangles[index][1];
		int third = firstVertex + triangles[index][2];
		const TrackCrossingPoint &a = object->vertices[first];
		const TrackCrossingPoint &b = object->vertices[second];
		const TrackCrossingPoint &c = object->vertices[third];
		double nx = (b.y - a.y) * (c.z - a.z) - (b.z - a.z) * (c.y - a.y);
		double ny = (b.z - a.z) * (c.x - a.x) - (b.x - a.x) * (c.z - a.z);
		double nz = crossingCross(b.x - a.x, b.y - a.y, c.x - a.x, c.y - a.y);
		if (nx * nx + ny * ny + nz * nz <=
		        CROSSING_PLAN_EPSILON * CROSSING_PLAN_EPSILON) {
			continue;
		}
		appendObjectTriangle(object, first, reverse ? third : second,
		                     reverse ? second : third);
		appendObjectFace(portal, portal.triangles.size() - 1,
		        coplanarReturn || (!alignedEndpoint && index == 0) ? fascia : filler);
	}
}


/** @brief Close one portal footprint using only rendered crossing vertices. */
static void
appendTerrainPortalMask(const CrossingBoundaryPoint &bridgeTop,
	                  const CrossingBoundaryPoint &socketCorner,
	                  const CrossingBoundaryPoint &floorExtension,
	                  TrackCrossingObject *object)
{
	int firstVertex = (int)object->vertices.size();
	appendObjectPoint(object, bridgeTop.x, bridgeTop.y, bridgeTop.z, 0.0, 0.0);
	appendObjectPoint(object, socketCorner.x, socketCorner.y,
	                  socketCorner.z, 0.0, 0.0);
	appendObjectPoint(object, floorExtension.x, floorExtension.y,
	                  floorExtension.z, 0.0, 0.0);
	appendObjectTriangle(object, firstVertex, firstVertex + 1,
	                     firstVertex + 2);
}


static bool
buildBridgeSide(const CrossingBoundaryLine &boundary,
	           const std::vector<CrossingBoundaryPoint> &slice,
	           const CrossingBoundaryPoint &firstExtension,
	           const CrossingBoundaryPoint &secondExtension,
	           int side, double undersideZ, double textureSize,
	           const TrackCrossingObject &underside,
	           TrackCrossingObject *object)
{
	std::vector<int> bottomIndices;
	std::vector<int> topIndices;
	std::vector<CrossingBoundaryPoint> topPoints;
	size_t firstTriangle = object->triangles.size();
	size_t index;

	if ((slice.size() < 2) ||
	        (firstExtension.z <= undersideZ + CROSSING_HEIGHT_EPSILON) ||
	        (secondExtension.z <= undersideZ + CROSSING_HEIGHT_EPSILON)) {
		return false;
	}
	topPoints = slice;
	topPoints.front() = firstExtension;
	topPoints.back() = secondExtension;
	for (index = 0; index < slice.size(); index++) {
		int bottomIndex = findObjectVertex(underside, slice[index], undersideZ);
		const TrackCrossingPoint *bottom;
		if ((bottomIndex < 0) ||
		        (topPoints[index].z <=
		         undersideZ + CROSSING_HEIGHT_EPSILON)) {
			return false;
		}
		bottom = &underside.vertices[bottomIndex];
		bottomIndices.push_back((int)object->vertices.size());
		object->vertices.push_back(*bottom);
		topIndices.push_back((int)object->vertices.size());
		appendObjectPoint(object, topPoints[index].x, topPoints[index].y,
		                  topPoints[index].z, bottom->u,
		                  bottom->v + (topPoints[index].z - undersideZ) /
		                  textureSize);
	}
	for (index = 0; index + 1 < slice.size(); index++) {
		appendObjectTriangle(object, topIndices[index], bottomIndices[index],
		                     topIndices[index + 1]);
		appendObjectTriangle(object, bottomIndices[index],
		                     bottomIndices[index + 1], topIndices[index + 1]);
	}

	for (index = firstTriangle; index < object->triangles.size(); index++) {
		size_t segmentIndex = (index - firstTriangle) / 2;
		double distance = (topPoints[segmentIndex].distance +
		        topPoints[segmentIndex + 1].distance) / 2.0;
		CrossingPlanPoint normal;
		normal = getBoundaryNormal(boundary, distance, side);
		orientObjectTriangle(object, index, normal.x, normal.y, 0.0);
	}
	return true;
}


static double
pointToSegmentDistance(double pointX, double pointY,
	                  const CrossingBoundaryPoint &first,
	                  const CrossingBoundaryPoint &second)
{
	double segmentX = second.x - first.x;
	double segmentY = second.y - first.y;
	double lengthSquared = segmentX * segmentX + segmentY * segmentY;
	double parameter = 0.0;
	if (lengthSquared > CROSSING_PLAN_EPSILON) {
		parameter = ((pointX - first.x) * segmentX +
		             (pointY - first.y) * segmentY) / lengthSquared;
		parameter = crossingClamp(parameter, 0.0, 1.0);
	}
	return sqrt(crossingDistanceSquared(pointX, pointY,
	        first.x + parameter * segmentX,
	        first.y + parameter * segmentY));
}


static double
minimumLineDistance(const std::vector<CrossingBoundaryPoint> &first,
	                const std::vector<CrossingBoundaryPoint> &second)
{
	double minimum = DBL_MAX;
	size_t pointIndex;
	size_t segmentIndex;
	for (pointIndex = 0; pointIndex < first.size(); pointIndex++) {
		for (segmentIndex = 0; segmentIndex + 1 < second.size();
		        segmentIndex++) {
			minimum = std::min(minimum, pointToSegmentDistance(
			        first[pointIndex].x, first[pointIndex].y,
			        second[segmentIndex], second[segmentIndex + 1]));
		}
	}
	for (pointIndex = 0; pointIndex < second.size(); pointIndex++) {
		for (segmentIndex = 0; segmentIndex + 1 < first.size();
		        segmentIndex++) {
			minimum = std::min(minimum, pointToSegmentDistance(
			        second[pointIndex].x, second[pointIndex].y,
			        first[segmentIndex], first[segmentIndex + 1]));
		}
	}
	return minimum == DBL_MAX ? 0.0 : minimum;
}


static double
minimumZ(const std::vector<CrossingBoundaryPoint> &points)
{
	double minimum = DBL_MAX;
	size_t index;
	for (index = 0; index < points.size(); index++) {
		minimum = std::min(minimum, points[index].minimumSurfaceZ);
	}
	return minimum;
}


static double
maximumBarrierTopZ(const std::vector<CrossingBoundaryPoint> &points)
{
	double maximum = -DBL_MAX;
	size_t index;
	for (index = 0; index < points.size(); index++) {
		maximum = std::max(maximum, points[index].barrierTopZ);
	}
	return maximum;
}


static bool
buildCrossingGeometry(tTrack *track, void *trackHandle,
	                 const std::vector<CrossingSegment> &segments,
	                 double trackLength, const CrossingCandidate &candidate,
	                 bool firstIsUpper, double trackStep,
	                 const TrackCrossingSettings &settings, int crossingIndex,
	                 TrackCrossingGeometry *geometry)
{
	const CrossingSegment &upperSegment = segments[firstIsUpper
	        ? candidate.firstIndex : candidate.secondIndex];
	const CrossingSegment &lowerSegment = segments[firstIsUpper
	        ? candidate.secondIndex : candidate.firstIndex];
	double upperToStart = firstIsUpper
	        ? candidate.firstToStart : candidate.secondToStart;
	double lowerToStart = firstIsUpper
	        ? candidate.secondToStart : candidate.firstToStart;
	double upperCenterDistance = upperSegment.startDistance +
	        segmentPhysicalOffset(upperSegment.segment, upperToStart);
	double lowerCenterDistance = lowerSegment.startDistance +
	        segmentPhysicalOffset(lowerSegment.segment, lowerToStart);
	CrossingPlanPoint upperCenter;
	CrossingPlanPoint lowerCenter;
	CrossingPlanPoint upperTangent = getTrackTangent(upperSegment.segment,
	                                                upperToStart);
	CrossingPlanPoint lowerTangent = getTrackTangent(lowerSegment.segment,
	                                                lowerToStart);
	CrossingBoundaryPoint upperRightCenter = sampleOuterBoundary(
	        upperSegment.segment, upperToStart, TR_SIDE_RGT, false);
	CrossingBoundaryPoint upperLeftCenter = sampleOuterBoundary(
	        upperSegment.segment, upperToStart, TR_SIDE_LFT, false);
	CrossingBoundaryPoint lowerRightCenter = sampleOuterBoundary(
	        lowerSegment.segment, lowerToStart, TR_SIDE_RGT, false);
	CrossingBoundaryPoint lowerLeftCenter = sampleOuterBoundary(
	        lowerSegment.segment, lowerToStart, TR_SIDE_LFT, false);
	double sine = fabs(crossingCross(upperTangent.x, upperTangent.y,
	                                lowerTangent.x, lowerTangent.y));
	double upperWidth;
	double lowerWidth;
	double halfExtent;
	double branchDistance;
	double maximumExtent;
	int attempt;

	getTrackCenterPoint(upperSegment.segment, upperToStart, &upperCenter, NULL);
	getTrackCenterPoint(lowerSegment.segment, lowerToStart, &lowerCenter, NULL);
	if (sine <= CROSSING_PLAN_EPSILON) {
		return false;
	}
	upperWidth = std::max(sqrt(crossingDistanceSquared(upperCenter.x,
	        upperCenter.y, upperRightCenter.x, upperRightCenter.y)),
	        sqrt(crossingDistanceSquared(upperCenter.x, upperCenter.y,
	        upperLeftCenter.x, upperLeftCenter.y)));
	lowerWidth = std::max(sqrt(crossingDistanceSquared(lowerCenter.x,
	        lowerCenter.y, lowerRightCenter.x, lowerRightCenter.y)),
	        sqrt(crossingDistanceSquared(lowerCenter.x, lowerCenter.y,
	        lowerLeftCenter.x, lowerLeftCenter.y))) + settings.socketGap;
	halfExtent = 1.5 * (upperWidth + lowerWidth) / sine + 5.0;
	branchDistance = fabs(upperCenterDistance - lowerCenterDistance);
	branchDistance = std::min(branchDistance, trackLength - branchDistance);
	maximumExtent = std::min(trackLength * 0.2, branchDistance * 0.45);
	if (maximumExtent <= 0.0) {
		return false;
	}
	halfExtent = std::min(halfExtent, maximumExtent);

	for (attempt = 0; attempt < 3; attempt++) {
		CrossingBoundaryLine upperRight;
		CrossingBoundaryLine upperLeft;
		CrossingBoundaryLine lowerRight;
		CrossingBoundaryLine lowerLeft;
		CrossingBoundaryLine socketRight;
		CrossingBoundaryLine socketLeft;
		CrossingLineIntersection rightRight;
		CrossingLineIntersection rightLeft;
		CrossingLineIntersection leftRight;
		CrossingLineIntersection leftLeft;
		CrossingLineIntersection rightRightBoundary;
		CrossingLineIntersection rightLeftBoundary;
		CrossingLineIntersection leftRightBoundary;
		CrossingLineIntersection leftLeftBoundary;
		CrossingBoundaryPoint upperRightFirstExtension;
		CrossingBoundaryPoint upperRightSecondExtension;
		CrossingBoundaryPoint upperLeftFirstExtension;
		CrossingBoundaryPoint upperLeftSecondExtension;
		CrossingBoundaryPoint lowerRightFirstExtension;
		CrossingBoundaryPoint lowerRightSecondExtension;
		CrossingBoundaryPoint lowerLeftFirstExtension;
		CrossingBoundaryPoint lowerLeftSecondExtension;
		std::vector<CrossingBoundaryPoint> bridgePolygon;
		std::vector<CrossingBoundaryPoint> bridgeRightCap;
		std::vector<CrossingBoundaryPoint> bridgeLeftCap;
		std::vector<CrossingBoundaryPoint> upperRightSlice;
		std::vector<CrossingBoundaryPoint> upperLeftSlice;
		std::vector<CrossingBoundaryPoint> lowerRightSlice;
		std::vector<CrossingBoundaryPoint> lowerLeftSlice;
		double concreteTextureSize;
		double rightFloorTextureSize;
		double leftFloorTextureSize;
		double lowerMaximumZ;
		double undersideZ;
		size_t vertexIndex;
		char name[64];

		if (!sampleBoundaryLine(segments, trackLength, upperCenterDistance,
		        halfExtent, trackStep, TR_SIDE_RGT, &upperRight) ||
		        !sampleBoundaryLine(segments, trackLength, upperCenterDistance,
		        halfExtent, trackStep, TR_SIDE_LFT, &upperLeft) ||
		        !sampleBoundaryLine(segments, trackLength, lowerCenterDistance,
		        halfExtent, trackStep, TR_SIDE_RGT, &lowerRight) ||
		        !sampleBoundaryLine(segments, trackLength, lowerCenterDistance,
		        halfExtent, trackStep, TR_SIDE_LFT, &lowerLeft)) {
			return false;
		}
		socketRight = offsetBoundaryLine(lowerRight, TR_SIDE_RGT,
		                                 settings.socketGap);
		socketLeft = offsetBoundaryLine(lowerLeft, TR_SIDE_LFT,
		                                settings.socketGap);
		rightRight = findBoundaryIntersection(upperRight, socketRight,
		        candidate.x, candidate.y);
		rightLeft = findBoundaryIntersection(upperRight, socketLeft,
		        candidate.x, candidate.y);
		leftRight = findBoundaryIntersection(upperLeft, socketRight,
		        candidate.x, candidate.y);
		leftLeft = findBoundaryIntersection(upperLeft, socketLeft,
		        candidate.x, candidate.y);
		rightRightBoundary = findBoundaryIntersection(upperRight, lowerRight,
		        candidate.x, candidate.y);
		rightLeftBoundary = findBoundaryIntersection(upperRight, lowerLeft,
		        candidate.x, candidate.y);
		leftRightBoundary = findBoundaryIntersection(upperLeft, lowerRight,
		        candidate.x, candidate.y);
		leftLeftBoundary = findBoundaryIntersection(upperLeft, lowerLeft,
		        candidate.x, candidate.y);
		if (!rightRight.found || !rightLeft.found ||
		        !leftRight.found || !leftLeft.found ||
		        !rightRightBoundary.found || !rightLeftBoundary.found ||
		        !leftRightBoundary.found || !leftLeftBoundary.found) {
			if (halfExtent >= maximumExtent - CROSSING_PLAN_EPSILON) {
				return false;
			}
			halfExtent = std::min(halfExtent * 2.0, maximumExtent);
			continue;
		}
		if (!findRenderedExtension(upperRight,
		        rightRight.firstDistance, rightLeft.firstDistance,
		        &upperRightFirstExtension) ||
		        !findRenderedExtension(upperRight,
		        rightLeft.firstDistance, rightRight.firstDistance,
		        &upperRightSecondExtension) ||
		        !findRenderedExtension(upperLeft,
		        leftRight.firstDistance, leftLeft.firstDistance,
		        &upperLeftFirstExtension) ||
		        !findRenderedExtension(upperLeft,
		        leftLeft.firstDistance, leftRight.firstDistance,
		        &upperLeftSecondExtension) ||
		        !findRenderedExtension(lowerRight,
		        outerPortalDistance(rightRight.secondDistance,
		                rightRightBoundary.secondDistance,
		                leftRight.secondDistance), leftRight.secondDistance,
		        &lowerRightFirstExtension) ||
		        !findRenderedExtension(lowerRight,
		        outerPortalDistance(leftRight.secondDistance,
		                leftRightBoundary.secondDistance,
		                rightRight.secondDistance), rightRight.secondDistance,
		        &lowerRightSecondExtension) ||
		        !findRenderedExtension(lowerLeft,
		        outerPortalDistance(rightLeft.secondDistance,
		                rightLeftBoundary.secondDistance,
		                leftLeft.secondDistance), leftLeft.secondDistance,
		        &lowerLeftFirstExtension) ||
		        !findRenderedExtension(lowerLeft,
		        outerPortalDistance(leftLeft.secondDistance,
		                leftLeftBoundary.secondDistance,
		                rightLeft.secondDistance), rightLeft.secondDistance,
		        &lowerLeftSecondExtension)) {
			if (halfExtent >= maximumExtent - CROSSING_PLAN_EPSILON) {
				return false;
			}
			halfExtent = std::min(halfExtent * 2.0, maximumExtent);
			continue;
		}

		upperRightSlice = sliceBoundaryLine(upperRight,
		        rightRight.firstDistance, rightLeft.firstDistance);
		upperLeftSlice = sliceBoundaryLine(upperLeft,
		        leftRight.firstDistance, leftLeft.firstDistance);
		lowerRightSlice = sliceBoundaryLine(lowerRight,
		        rightRight.secondDistance, leftRight.secondDistance);
		lowerLeftSlice = sliceBoundaryLine(lowerLeft,
		        rightLeft.secondDistance, leftLeft.secondDistance);
		geometry->minimumUpperZ = std::min(minimumZ(upperRightSlice),
		                                   minimumZ(upperLeftSlice));
		undersideZ = geometry->minimumUpperZ - settings.bridgeThickness;
		lowerMaximumZ = std::max(maximumBarrierTopZ(lowerRightSlice),
		                               maximumBarrierTopZ(lowerLeftSlice));
		if (undersideZ <= lowerMaximumZ + CROSSING_HEIGHT_EPSILON) {
			return false;
		}

		bridgeLeftCap = sliceBoundaryLine(socketLeft,
		        rightLeft.secondDistance, leftLeft.secondDistance);
		bridgeRightCap = sliceBoundaryLine(socketRight,
		        leftRight.secondDistance, rightRight.secondDistance);
		appendPolygonSlice(&bridgePolygon, upperRightSlice);
		appendPolygonSlice(&bridgePolygon, bridgeLeftCap);
		appendPolygonSlice(&bridgePolygon, sliceBoundaryLine(upperLeft,
		        leftLeft.firstDistance, leftRight.firstDistance));
		appendPolygonSlice(&bridgePolygon, bridgeRightCap);
		simplifyPolygon(&bridgePolygon);
		if (bridgePolygon.size() < 3) {
			return false;
		}

		geometry->underside.texture = resolveSurfaceTexture(track, trackHandle,
		        TRK_VAL_CONCRETE, &concreteTextureSize);
		for (vertexIndex = 0; vertexIndex < bridgePolygon.size(); vertexIndex++) {
			appendObjectPoint(&geometry->underside, bridgePolygon[vertexIndex].x,
			        bridgePolygon[vertexIndex].y, undersideZ,
			        bridgePolygon[vertexIndex].x / concreteTextureSize,
			        bridgePolygon[vertexIndex].y / concreteTextureSize);
		}
		if (!triangulateBridgeUnderside(bridgePolygon, upperRightSlice,
		        upperLeftSlice, bridgeRightCap, bridgeLeftCap,
		        &geometry->underside)) {
			geometry->underside.vertices.clear();
			geometry->underside.triangles.clear();
			return false;
		}
		removeCollapsedPlanTriangles(&geometry->underside);
		if (geometry->underside.triangles.empty()) {
			geometry->underside.vertices.clear();
			return false;
		}
		orientObjectVertically(&geometry->underside, -1.0);
		geometry->bridgeRight.texture = geometry->underside.texture;
		geometry->bridgeLeft.texture = geometry->underside.texture;
		if (!buildBridgeSide(upperRight, upperRightSlice,
		        upperRightFirstExtension, upperRightSecondExtension,
		        TR_SIDE_RGT, undersideZ, concreteTextureSize,
		        geometry->underside, &geometry->bridgeRight) ||
		        !buildBridgeSide(upperLeft, upperLeftSlice,
		        upperLeftFirstExtension, upperLeftSecondExtension,
		        TR_SIDE_LFT, undersideZ, concreteTextureSize,
		        geometry->underside, &geometry->bridgeLeft)) {
			return false;
		}

		geometry->socketRight.texture = geometry->underside.texture;
		geometry->socketLeft.texture = geometry->underside.texture;
		geometry->floorRight.texture = resolveSurfaceTexture(track,
		        trackHandle, getBoundaryMaterial(lowerSegment.segment,
		        TR_SIDE_RGT), &rightFloorTextureSize);
		geometry->floorLeft.texture = resolveSurfaceTexture(track,
		        trackHandle, getBoundaryMaterial(lowerSegment.segment,
		        TR_SIDE_LFT), &leftFloorTextureSize);
		buildSocketWall(lowerRight, socketRight, rightRight.secondDistance,
		                leftRight.secondDistance, TR_SIDE_RGT, undersideZ,
		                concreteTextureSize, &geometry->socketRight);
		buildSocketWall(lowerLeft, socketLeft, rightLeft.secondDistance,
		                leftLeft.secondDistance, TR_SIDE_LFT, undersideZ,
		                concreteTextureSize, &geometry->socketLeft);
		buildFloorStrip(lowerRight, socketRight,
		                rightRight.secondDistance, leftRight.secondDistance,
		                lowerRightFirstExtension,
		                lowerRightSecondExtension,
		                rightFloorTextureSize, &geometry->floorRight);
		buildFloorStrip(lowerLeft, socketLeft,
		                rightLeft.secondDistance, leftLeft.secondDistance,
		                lowerLeftFirstExtension,
		                lowerLeftSecondExtension,
		                leftFloorTextureSize, &geometry->floorLeft);
		appendSocketPortal(upperRightFirstExtension,
		        interpolateBoundaryPoint(socketRight, rightRight.secondDistance),
		        lowerRightFirstExtension,
		        getBoundaryNormal(upperRight, rightRight.firstDistance, TR_SIDE_RGT),
		        undersideZ, concreteTextureSize, geometry->socketRight,
		        &geometry->bridgeRight, &geometry->filler[TR_SIDE_RGT][TR_SIDE_RGT]);
		appendSocketPortal(upperLeftFirstExtension,
		        interpolateBoundaryPoint(socketRight, leftRight.secondDistance),
		        lowerRightSecondExtension,
		        getBoundaryNormal(upperLeft, leftRight.firstDistance, TR_SIDE_LFT),
		        undersideZ, concreteTextureSize, geometry->socketRight,
		        &geometry->bridgeLeft, &geometry->filler[TR_SIDE_LFT][TR_SIDE_RGT]);
		appendSocketPortal(upperRightSecondExtension,
		        interpolateBoundaryPoint(socketLeft, rightLeft.secondDistance),
		        lowerLeftFirstExtension,
		        getBoundaryNormal(upperRight, rightLeft.firstDistance, TR_SIDE_RGT),
		        undersideZ, concreteTextureSize, geometry->socketLeft,
		        &geometry->bridgeRight, &geometry->filler[TR_SIDE_RGT][TR_SIDE_LFT]);
		appendSocketPortal(upperLeftSecondExtension,
		        interpolateBoundaryPoint(socketLeft, leftLeft.secondDistance),
		        lowerLeftSecondExtension,
		        getBoundaryNormal(upperLeft, leftLeft.firstDistance, TR_SIDE_LFT),
		        undersideZ, concreteTextureSize, geometry->socketLeft,
		        &geometry->bridgeLeft, &geometry->filler[TR_SIDE_LFT][TR_SIDE_LFT]);
		if (!geometry->floorRight.triangles.empty()) {
			appendTerrainPortalMask(upperRightFirstExtension,
			        interpolateBoundaryPoint(socketRight,
			                rightRight.secondDistance),
			        lowerRightFirstExtension, &geometry->terrainMask);
			appendTerrainPortalMask(upperLeftFirstExtension,
			        interpolateBoundaryPoint(socketRight,
			                leftRight.secondDistance),
			        lowerRightSecondExtension, &geometry->terrainMask);
		}
		if (!geometry->floorLeft.triangles.empty()) {
			appendTerrainPortalMask(upperRightSecondExtension,
			        interpolateBoundaryPoint(socketLeft,
			                rightLeft.secondDistance),
			        lowerLeftFirstExtension, &geometry->terrainMask);
			appendTerrainPortalMask(upperLeftSecondExtension,
			        interpolateBoundaryPoint(socketLeft,
			                leftLeft.secondDistance),
			        lowerLeftSecondExtension, &geometry->terrainMask);
		}

		geometry->upperSegmentId = upperSegment.segment->id;
		geometry->lowerSegmentId = lowerSegment.segment->id;
		geometry->crossingX = candidate.x;
		geometry->crossingY = candidate.y;
		geometry->undersideZ = undersideZ;
		geometry->minimumBridgeThickness = geometry->minimumUpperZ - undersideZ;
		geometry->measuredSocketGap[TR_SIDE_RGT] = settings.socketGap <=
		        CROSSING_PLAN_EPSILON ? 0.0 : minimumLineDistance(
		        sliceBoundaryLine(socketRight, rightRight.secondDistance,
		                          leftRight.secondDistance), lowerRight.points);
		geometry->measuredSocketGap[TR_SIDE_LFT] = settings.socketGap <=
		        CROSSING_PLAN_EPSILON ? 0.0 : minimumLineDistance(
		        sliceBoundaryLine(socketLeft, rightLeft.secondDistance,
		                          leftLeft.secondDistance), lowerLeft.points);
		snprintf(name, sizeof(name), "TRKBRIDGE_UNDERSIDE%d", crossingIndex);
		geometry->underside.name = name;
		snprintf(name, sizeof(name), "TRKBRIDGE_R%d", crossingIndex);
		geometry->bridgeRight.name = name;
		snprintf(name, sizeof(name), "TRKBRIDGE_L%d", crossingIndex);
		geometry->bridgeLeft.name = name;
		snprintf(name, sizeof(name), "TRKSOCKET_WALL_R%d", crossingIndex);
		geometry->socketRight.name = name;
		snprintf(name, sizeof(name), "TRKSOCKET_WALL_L%d", crossingIndex);
		geometry->socketLeft.name = name;
		for (int upperSide = 0; upperSide < 2; upperSide++) {
			for (int lowerSide = 0; lowerSide < 2; lowerSide++) {
				snprintf(name, sizeof(name), "TRKFILLER_%c%c%d",
				        upperSide == TR_SIDE_RGT ? 'R' : 'L',
				        lowerSide == TR_SIDE_RGT ? 'R' : 'L', crossingIndex);
				geometry->filler[upperSide][lowerSide].name = name;
				geometry->filler[upperSide][lowerSide].texture = geometry->underside.texture;
			}
		}
		snprintf(name, sizeof(name), "TRKFLOOR_R%d", crossingIndex);
		geometry->floorRight.name = name;
		snprintf(name, sizeof(name), "TRKFLOOR_L%d", crossingIndex);
		geometry->floorLeft.name = name;
		const CrossingBoundaryLine *upperLines[] = {&upperRight, &upperLeft};
		const CrossingBoundaryLine *socketLines[] = {&socketRight, &socketLeft};
		const CrossingBoundaryPoint corners[2][2] = {
			{interpolateBoundaryPoint(socketRight, rightRight.secondDistance),
			 interpolateBoundaryPoint(socketLeft, rightLeft.secondDistance)},
			{interpolateBoundaryPoint(socketRight, leftRight.secondDistance),
			 interpolateBoundaryPoint(socketLeft, leftLeft.secondDistance)}
		};
		mapCrossingTextures(track, trackHandle, lowerSegment.segment, upperCenter,
		        upperTangent, lowerTangent, upperLines, socketLines,
		        upperCenterDistance, lowerCenterDistance, corners, geometry);
		return true;
	}
	return false;
}


int
ReadTrackCrossingSettings(void *trackHandle,
	                     TrackCrossingSettings *settings,
	                     char *errorMessage, size_t errorMessageSize)
{
	tdble minimum;
	tdble maximum;
	bool hasGap;
	bool hasThickness;

	if ((trackHandle == NULL) || (settings == NULL)) {
		setCrossingError(errorMessage, errorMessageSize,
		                 "Track crossing settings require a track handle");
		return -1;
	}
	hasGap = GfParmGetNumBoundaries(trackHandle, TRK_SECT_TERRAIN,
	        TRK_ATT_CROSSING_BRIDGE_SOCKET_GAP, &minimum, &maximum) == 0;
	hasThickness = GfParmGetNumBoundaries(trackHandle, TRK_SECT_TERRAIN,
	        TRK_ATT_CROSSING_BRIDGE_THICKNESS, &minimum, &maximum) == 0;
	settings->socketGap = hasGap ? GfParmGetNum(trackHandle,
	        TRK_SECT_TERRAIN, TRK_ATT_CROSSING_BRIDGE_SOCKET_GAP,
	        (char *)NULL, 0.5f) : 0.5f;
	settings->bridgeThickness = hasThickness ? GfParmGetNum(trackHandle,
	        TRK_SECT_TERRAIN, TRK_ATT_CROSSING_BRIDGE_THICKNESS,
	        (char *)NULL, 1.0f) : 1.0f;
	if (!crossingFinite(settings->socketGap) || (settings->socketGap < 0.0)) {
		setCrossingError(errorMessage, errorMessageSize,
		        "Graphic/Terrain Generation: crossing bridge socket gap must be finite and non-negative");
		return -1;
	}
	if (!crossingFinite(settings->bridgeThickness) ||
	        (settings->bridgeThickness <= 0.0)) {
		setCrossingError(errorMessage, errorMessageSize,
		        "Graphic/Terrain Generation: crossing bridge thickness must be finite and positive");
		return -1;
	}
	if ((errorMessage != NULL) && (errorMessageSize > 0)) {
		errorMessage[0] = '\0';
	}
	return 0;
}


int
BuildTrackCrossingModel(tTrack *track, void *trackHandle,
	                   tdble trackStep,
	                   const TrackCrossingSettings *settings,
	                   TrackCrossingModel *model,
	                   char *errorMessage, size_t errorMessageSize)
{
	std::vector<CrossingSegment> segments;
	std::vector<CrossingCandidate> candidates;
	tTrackSeg *segment;
	double trackLength = 0.0;
	int index;

	if ((track == NULL) || (settings == NULL) || (model == NULL) ||
	        (track->seg == NULL) || (track->nseg < 1)) {
		setCrossingError(errorMessage, errorMessageSize,
		                 "Track crossing detection requires a valid track");
		return -1;
	}
	if (!crossingFinite(trackStep) || (trackStep <= 0.0)) {
		setCrossingError(errorMessage, errorMessageSize,
		                 "Track crossing detection requires a positive finite track step");
		return -1;
	}
	if (!crossingFinite(settings->socketGap) || (settings->socketGap < 0.0) ||
	        !crossingFinite(settings->bridgeThickness) ||
	        (settings->bridgeThickness <= 0.0)) {
		setCrossingError(errorMessage, errorMessageSize,
		                 "Track crossing settings are invalid");
		return -1;
	}
	model->candidateCount = 0;
	model->settings = *settings;
	model->crossings.clear();
	try {
		for (index = 0, segment = track->seg->next; index < track->nseg;
		        index++, segment = segment->next) {
			CrossingSegment crossingSegment;
			crossingSegment.segment = segment;
			crossingSegment.index = index;
			crossingSegment.startDistance = trackLength;
			segments.push_back(crossingSegment);
			trackLength += segment->length;
		}
		if (trackLength <= CROSSING_PLAN_EPSILON) {
			setCrossingError(errorMessage, errorMessageSize,
			                 "Track crossing detection found zero track length");
			return -1;
		}
		findCrossingCandidates(segments, &candidates);
		model->candidateCount = (int)candidates.size();
		for (index = 0; index < (int)candidates.size(); index++) {
			CrossingPlanPoint firstPoint;
			CrossingPlanPoint secondPoint;
			double firstHeight;
			double secondHeight;
			bool firstIsUpper;
			TrackCrossingGeometry geometry;
			getTrackCenterPoint(segments[candidates[index].firstIndex].segment,
			        candidates[index].firstToStart, &firstPoint, &firstHeight);
			getTrackCenterPoint(segments[candidates[index].secondIndex].segment,
			        candidates[index].secondToStart, &secondPoint, &secondHeight);
			if (fabs(firstHeight - secondHeight) <= CROSSING_HEIGHT_EPSILON) {
				continue;
			}
			firstIsUpper = firstHeight > secondHeight;
			if (buildCrossingGeometry(track, trackHandle, segments, trackLength,
			        candidates[index], firstIsUpper, trackStep, *settings,
			        (int)model->crossings.size(), &geometry)) {
				model->crossings.push_back(geometry);
			}
		}
	} catch (const std::bad_alloc &) {
		setCrossingError(errorMessage, errorMessageSize,
		                 "Track crossing geometry allocation failed");
		return -1;
	}
	if ((errorMessage != NULL) && (errorMessageSize > 0)) {
		errorMessage[0] = '\0';
	}
	return 0;
}


static void
writeCrossingObject(FILE *acFile, const TrackCrossingObject &object)
{
	size_t index;
	fprintf(acFile, "OBJECT poly\n");
	fprintf(acFile, "name \"%s\"\n", object.name.c_str());
	fprintf(acFile, "texture \"%s\"\n", object.texture.c_str());
	fprintf(acFile, "numvert %d\n", (int)object.vertices.size());
	for (index = 0; index < object.vertices.size(); index++) {
		const TrackCrossingPoint &point = object.vertices[index];
		fprintf(acFile, "%f %f %f\n", point.x, point.z, -point.y);
	}
	fprintf(acFile, "numsurf %d\n", (int)object.triangles.size());
	for (index = 0; index < object.triangles.size(); index++) {
		const TrackCrossingTriangle &triangle = object.triangles[index];
		int reference;
		fprintf(acFile, "SURF 0x10\n");
		fprintf(acFile, "mat 0\n");
		fprintf(acFile, "refs 3\n");
		for (reference = 0; reference < 3; reference++) {
			int vertexIndex = triangle.vertex[reference];
			const TrackCrossingPoint &point = object.vertices[vertexIndex];
			fprintf(acFile, "%d %f %f\n", vertexIndex, point.u, point.v);
		}
	}
	fprintf(acFile, "kids 0\n");
}


void
WriteTrackCrossingModel(FILE *acFile, const TrackCrossingModel *model)
{
	size_t index;
	char name[64];
	if ((acFile == NULL) || (model == NULL)) {
		return;
	}
	for (index = 0; index < model->crossings.size(); index++) {
		const TrackCrossingGeometry &crossing = model->crossings[index];
		snprintf(name, sizeof(name), "TRKCROSS%d", (int)index);
		fprintf(acFile, "OBJECT group\n");
		fprintf(acFile, "name \"%s\"\n", name);
		fprintf(acFile, "kids 5\n");
		fprintf(acFile, "OBJECT group\nname \"TRKBRIDGE%d\"\nkids 3\n", (int)index);
		writeCrossingObject(acFile, crossing.underside);
		writeCrossingObject(acFile, crossing.bridgeRight);
		writeCrossingObject(acFile, crossing.bridgeLeft);
		fprintf(acFile, "OBJECT group\nname \"TRKSOCKET_R%d\"\nkids 3\n", (int)index);
		writeCrossingObject(acFile, crossing.socketRight);
		writeCrossingObject(acFile, crossing.filler[TR_SIDE_RGT][TR_SIDE_RGT]);
		writeCrossingObject(acFile, crossing.filler[TR_SIDE_LFT][TR_SIDE_RGT]);
		fprintf(acFile, "OBJECT group\nname \"TRKSOCKET_L%d\"\nkids 3\n", (int)index);
		writeCrossingObject(acFile, crossing.socketLeft);
		writeCrossingObject(acFile, crossing.filler[TR_SIDE_RGT][TR_SIDE_LFT]);
		writeCrossingObject(acFile, crossing.filler[TR_SIDE_LFT][TR_SIDE_LFT]);
		writeCrossingObject(acFile, crossing.floorRight);
		writeCrossingObject(acFile, crossing.floorLeft);
	}
}
