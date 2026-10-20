/***************************************************************************

    file                 : trackboundary.h
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

#ifndef _TRACKBOUNDARY_H_
#define _TRACKBOUNDARY_H_

#include <vector>

#include <track.h>

#include "easymesh.h"


/** @brief One side-local corner at a rendered wall-width transition. */
struct TrackBoundaryTransition
{
	int pointIndex; /**< Existing previous endpoint preceding the corner. */
	tMeshNode point; /**< Current segment start on the new wall exterior. */
};

/** @brief Append samples from one outermost side of a track.
    @param[in] track Track whose segments are sampled in traversal order.
    @param[in] side TR_SIDE_RGT or TR_SIDE_LFT.
    @param[in] trackSamplingStep Distance between samples.
    @param[in] terrainGridStep Target spacing assigned to appended points.
    @param[in] includeWallExterior Shift wall samples to the rendered outer face.
    @param[in,out] input Constrained input receiving sampled points.
    @param[out] closurePoint Optional final track endpoint, not appended to input.
    @param[out] transitions Optional side-local wall-width transition corners.
    @return Zero on success, -1 when point storage cannot be grown.
 */
int sampleTrackBoundary(tTrack *track, int side, tdble trackSamplingStep,
	                    tdble terrainGridStep, bool includeWallExterior,
	                    tMeshInput *input, tMeshNode *closurePoint,
	                    std::vector<TrackBoundaryTransition> *transitions);

/** @brief Calculate target spacing from distance to a closed track boundary.
    @param[in] points Constrained input points containing the boundary range.
    @param[in] firstPointIndex First point in the contiguous boundary range.
    @param[in] pointCount Number of points in the closed boundary.
    @param[in] x Candidate X coordinate.
    @param[in] y Candidate Y coordinate.
    @param[in] maximumSpacing Coarse target spacing away from the track.
    @param[in] nearTrackSpacingFloor Smallest spacing propagated from the track.
    @param[in] transitionDistance Distance over which spacing becomes coarse.
    @return Linearly transitioned target spacing at the candidate point.
 */
double getTrackBoundaryTargetSpacing(const tMeshNode *points,
	                                 int firstPointIndex, int pointCount,
	                                 double x, double y,
	                                 double maximumSpacing,
	                                 double nearTrackSpacingFloor,
	                                 double transitionDistance);

#endif /* _TRACKBOUNDARY_H_ */
