/***************************************************************************

    file                 : trackboundary.cpp
    created              : Thu Jul 30 2026
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
    @brief Track-boundary sampling for constrained terrain input.
 */

#include <float.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include <robottools.h>

#include "trackboundary.h"


/** Plan-view tolerance for coincident rendered segment endpoints. */
static const double TRACK_BOUNDARY_TRANSITION_EPSILON = 1e-3;


/** @brief Ensure point storage can hold a requested entry count. */
static int
reserveBoundaryPoints(tMeshInput *input, int minimumCapacity)
{
	int newCapacity;
	int oldCapacity;
	tMeshNode *resizedPoints;

	if (minimumCapacity <= input->pointCapacity) {
		return 0;
	}
	oldCapacity = input->pointCapacity;
	newCapacity = input->pointCapacity * 2;
	if (newCapacity < 1) {
		newCapacity = 1;
	}
	if (newCapacity < minimumCapacity) {
		newCapacity = minimumCapacity;
	}
	resizedPoints = (tMeshNode *)realloc(
	        input->points, newCapacity * sizeof(tMeshNode));
	if (resizedPoints == NULL) {
		return -1;
	}
	input->points = resizedPoints;
	memset(&input->points[oldCapacity], 0,
	       (newCapacity - oldCapacity) * sizeof(tMeshNode));
	input->pointCapacity = newCapacity;
	return 0;
}


/** @brief Append one sampled point to constrained input. */
static int
appendBoundaryPoint(tMeshInput *input, double x, double y, double z,
	                double spacing, int marker)
{
	if (reserveBoundaryPoints(input, input->pointCount + 1) != 0) {
		return -1;
	}
	input->points[input->pointCount].x = x;
	input->points[input->pointCount].y = y;
	input->points[input->pointCount].z = z;
	input->points[input->pointCount].spacing = spacing;
	input->points[input->pointCount].marker = marker;
	input->pointCount++;
	return 0;
}


/** @brief Test whether one boundary coordinate is finite. */
static bool
trackBoundaryFinite(tdble value)
{
#ifdef WIN32
	return _finite(value) != 0;
#else
	return isfinite(value) != 0;
#endif
}


/** @brief Return the wall width included outside one track boundary. */
static tdble
getWallExteriorWidth(tTrackSeg *mainSegment, int side,
	                 bool includeWallExterior)
{
	tTrackBarrier *barrier = mainSegment->barrier[side];
	if (includeWallExterior && (barrier != NULL) &&
	        (barrier->style == TR_WALL) &&
	        trackBoundaryFinite(barrier->width) && (barrier->width > 0.0f)) {
		return barrier->width;
	}
	return 0.0f;
}


/** @brief Resolve the outermost rendered side segment. */
static tTrackSeg *
getRenderedBoundarySegment(tTrackSeg *mainSegment, int side)
{
	tTrackSeg *boundarySegment = mainSegment;
	if (boundarySegment->side[side] != NULL) {
		boundarySegment = boundarySegment->side[side];
		if (boundarySegment->side[side] != NULL) {
			boundarySegment = boundarySegment->side[side];
		}
	}
	return boundarySegment;
}


/** @brief Append one sampled local track position to constrained input. */
static int
appendTrackPosition(tMeshInput *input, tTrackSeg *mainSegment,
	                tTrackSeg *boundarySegment, int side,
	                tdble sampleOffset, tdble terrainGridStep, int marker,
	                bool includeWallExterior)
{
	tdble sampleX;
	tdble sampleY;
	tdble sampleZ;
	tdble edgeToRight;
	tdble wallWidth = getWallExteriorWidth(mainSegment, side,
	                                         includeWallExterior);
	tTrkLocPos trackPosition;

	trackPosition.seg = boundarySegment;
	trackPosition.toStart = sampleOffset;
	edgeToRight = side == TR_SIDE_LFT
	        ? RtTrackGetWidth(boundarySegment, sampleOffset) : 0.0f;
	trackPosition.toRight = edgeToRight;
	RtTrackLocal2Global(&trackPosition, &sampleX, &sampleY, TR_TORIGHT);
	sampleZ = RtTrackHeightL(&trackPosition);
	if (wallWidth > 0.0f) {
		trackPosition.toRight = side == TR_SIDE_RGT
		        ? edgeToRight - wallWidth : edgeToRight + wallWidth;
		RtTrackLocal2Global(&trackPosition, &sampleX, &sampleY, TR_TORIGHT);
	}
	return appendBoundaryPoint(input, sampleX, sampleY, sampleZ,
	                           terrainGridStep, marker);
}


/** @brief Sample one exact rendered endpoint, optionally outside its wall. */
static void
sampleTrackEndpoint(tTrackSeg *mainSegment, tTrackSeg *boundarySegment,
	                int side, int vertexIndex, tdble toStart,
	                tdble terrainGridStep, int marker,
	                bool includeWallExterior, tMeshNode *point)
{
	tdble wallWidth = getWallExteriorWidth(mainSegment, side,
	                                         includeWallExterior);
	memset(point, 0, sizeof(*point));
	if (wallWidth > 0.0f) {
		tTrkLocPos trackPosition;
		tdble x;
		tdble y;
		trackPosition.seg = boundarySegment;
		trackPosition.toStart = toStart;
		trackPosition.toRight = side == TR_SIDE_RGT ? -wallWidth :
		        RtTrackGetWidth(boundarySegment, toStart) + wallWidth;
		RtTrackLocal2Global(&trackPosition, &x, &y, TR_TORIGHT);
		point->x = x;
		point->y = y;
	} else {
		point->x = boundarySegment->vertex[vertexIndex].x;
		point->y = boundarySegment->vertex[vertexIndex].y;
	}
	point->z = boundarySegment->vertex[vertexIndex].z;
	point->spacing = terrainGridStep;
	point->marker = marker;
}


/** @brief Append one exact rendered track endpoint. */
static int
appendTrackEndpoint(tMeshInput *input, tTrackSeg *mainSegment,
	                tTrackSeg *boundarySegment, int side, int vertexIndex,
	                tdble toStart, tdble terrainGridStep, int marker,
	                bool includeWallExterior)
{
	tMeshNode point;
	sampleTrackEndpoint(mainSegment, boundarySegment, side, vertexIndex,
	                    toStart, terrainGridStep, marker,
	                    includeWallExterior, &point);
	return appendBoundaryPoint(input, point.x, point.y, point.z,
	                           point.spacing, point.marker);
}


double
getTrackBoundaryTargetSpacing(const tMeshNode *points,
	                          int firstPointIndex, int pointCount,
	                          double x, double y, double maximumSpacing,
	                          double nearTrackSpacingFloor,
	                          double transitionDistance)
{
	double deltaX;
	double deltaY;
	double distanceFactor;
	double distanceSquared;
	double nearestDistanceSquared = DBL_MAX;
	double nearestSpacing = maximumSpacing;
	double projectedSpacing;
	double projection;
	double segmentLengthSquared;
	int nextPointIndex;
	int pointIndex;
	const tMeshNode *firstPoint;
	const tMeshNode *secondPoint;

	if ((points == NULL) || (pointCount <= 0) ||
	        (transitionDistance <= 0.0)) {
		return maximumSpacing;
	}
	for (pointIndex = 0; pointIndex < pointCount; pointIndex++) {
		firstPoint = &points[firstPointIndex + pointIndex];
		nextPointIndex = (pointIndex + 1) % pointCount;
		secondPoint = &points[firstPointIndex + nextPointIndex];
		deltaX = secondPoint->x - firstPoint->x;
		deltaY = secondPoint->y - firstPoint->y;
		segmentLengthSquared = deltaX * deltaX + deltaY * deltaY;
		projection = 0.0;
		if (segmentLengthSquared > 0.0) {
			projection = ((x - firstPoint->x) * deltaX +
			              (y - firstPoint->y) * deltaY) /
			             segmentLengthSquared;
			if (projection < 0.0) {
				projection = 0.0;
			} else if (projection > 1.0) {
				projection = 1.0;
			}
		}
		deltaX = x - (firstPoint->x + projection * deltaX);
		deltaY = y - (firstPoint->y + projection * deltaY);
		distanceSquared = deltaX * deltaX + deltaY * deltaY;
		projectedSpacing = firstPoint->spacing + projection *
		        (secondPoint->spacing - firstPoint->spacing);
		if ((distanceSquared < nearestDistanceSquared) ||
		        ((distanceSquared == nearestDistanceSquared) &&
		         (projectedSpacing < nearestSpacing))) {
			nearestDistanceSquared = distanceSquared;
			nearestSpacing = projectedSpacing;
		}
	}
	if (nearestSpacing < nearTrackSpacingFloor) {
		nearestSpacing = nearTrackSpacingFloor;
	}
	if (maximumSpacing <= nearestSpacing) {
		return nearestSpacing;
	}
	distanceFactor = sqrt(nearestDistanceSquared) / transitionDistance;
	if (distanceFactor > 1.0) {
		distanceFactor = 1.0;
	}
	return nearestSpacing +
	       (maximumSpacing - nearestSpacing) * distanceFactor;
}


int
sampleTrackBoundary(tTrack *track, int side, tdble trackSamplingStep,
	                tdble terrainGridStep, bool includeWallExterior,
	                tMeshInput *input, tMeshNode *closurePoint,
	                std::vector<TrackBoundaryTransition> *transitions)
{
	int endVertex;
	int index;
	int startPointNeeded = 1;
	int startVertex;
	tdble curveDirection;
	tdble sampleAngle;
	tdble sampleOffset;
	tdble sampleStep;
	tTrackSeg *boundarySegment;
	tTrackSeg *mainSegment;

	startVertex = side == TR_SIDE_RGT ? TR_SR : TR_SL;
	endVertex = side == TR_SIDE_RGT ? TR_ER : TR_EL;
	for (index = 0, mainSegment = track->seg->next;
	        index < track->nseg;
	        index++, mainSegment = mainSegment->next) {
		boundarySegment = getRenderedBoundarySegment(mainSegment, side);
		if ((index > 0) && includeWallExterior && (transitions != NULL)) {
			TrackBoundaryTransition transition;
			double deltaX;
			double deltaY;
			transition.pointIndex = input->pointCount - 1;
			sampleTrackEndpoint(mainSegment, boundarySegment, side,
			                    startVertex, 0.0f, terrainGridStep,
			                    index + 1, true, &transition.point);
			deltaX = transition.point.x -
			        input->points[transition.pointIndex].x;
			deltaY = transition.point.y -
			        input->points[transition.pointIndex].y;
			if (deltaX * deltaX + deltaY * deltaY >
			        TRACK_BOUNDARY_TRANSITION_EPSILON *
			        TRACK_BOUNDARY_TRANSITION_EPSILON) {
				transitions->push_back(transition);
			}
		}
		if (startPointNeeded && appendTrackEndpoint(input, mainSegment,
		        boundarySegment, side, startVertex, 0.0f, terrainGridStep,
		        index + 1, includeWallExterior) != 0) {
			return -1;
		}
		switch (boundarySegment->type) {
			case TR_STR:
				sampleOffset = trackSamplingStep;
				while (sampleOffset < boundarySegment->length) {
					if (appendTrackPosition(input, mainSegment, boundarySegment,
					        side, sampleOffset, terrainGridStep, index + 1,
					        includeWallExterior) != 0) {
						return -1;
					}
					sampleOffset += trackSamplingStep;
				}
				break;
			case TR_LFT:
			case TR_RGT:
				curveDirection = boundarySegment->type == TR_LFT ? 1.0f : -1.0f;
				sampleStep = trackSamplingStep /
				        (boundarySegment->type == TR_LFT
				         ? mainSegment->radiusr : mainSegment->radiusl);
				sampleAngle = boundarySegment->angle[TR_ZS] +
				        curveDirection * sampleStep;
				sampleOffset = sampleStep;
				while ((curveDirection > 0.0f &&
				        sampleAngle < boundarySegment->angle[TR_ZE]) ||
				        (curveDirection < 0.0f &&
				         sampleAngle > boundarySegment->angle[TR_ZE])) {
					if (appendTrackPosition(input, mainSegment, boundarySegment,
					        side, sampleOffset, terrainGridStep, index + 1,
					        includeWallExterior) != 0) {
						return -1;
					}
					sampleOffset += sampleStep;
					sampleAngle += curveDirection * sampleStep;
				}
				break;
		}
		if (index != (track->nseg - 1)) {
			tdble endOffset = boundarySegment->type == TR_STR
			        ? boundarySegment->length : boundarySegment->arc;
			if (appendTrackEndpoint(input, mainSegment, boundarySegment, side,
			        endVertex, endOffset, terrainGridStep, index + 1,
			        includeWallExterior) != 0) {
				return -1;
			}
			startPointNeeded = 0;
		} else if (closurePoint != NULL) {
			tdble endOffset = boundarySegment->type == TR_STR
			        ? boundarySegment->length : boundarySegment->arc;
			sampleTrackEndpoint(mainSegment, boundarySegment, side, endVertex,
			                    endOffset, terrainGridStep, index + 1,
			                    includeWallExterior, closurePoint);
		}
	}
	return 0;
}
