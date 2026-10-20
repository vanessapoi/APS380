/***************************************************************************

    file                 : terraindomain.h
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
    @brief Planar terrain-domain discovery before EasyMesh triangulation.
 */

#ifndef _TERRAINDOMAIN_H_
#define _TERRAINDOMAIN_H_

#include <stddef.h>

#include <vector>


/** @brief One constrained terrain-domain point. */
struct TerrainDomainPoint
{
	double x;
	double y;
	double z;
	double spacing;
	int marker;
};


/** @brief One projected triangle occupied by track-owned geometry. */
struct TerrainDomainTriangle
{
	TerrainDomainPoint points[3];
};


/** @brief One ordered constraint segment clipped to a terrain domain. */
struct TerrainDomainSegment
{
	TerrainDomainPoint points[2];
};


/** @brief One independently rendered occupied layer and its candidate edges. */
struct TerrainDomainBoundaryGroup
{
	std::vector<TerrainDomainTriangle> triangles;
	std::vector<TerrainDomainSegment> boundaries;
	bool preserveBoundaries;
};


/** @brief One simple closed terrain boundary without a repeated end point. */
struct TerrainDomainRing
{
	std::vector<TerrainDomainPoint> points;
};


/** @brief One connected terrain region presented to EasyMesh. */
struct TerrainDomain
{
	TerrainDomainRing outer;
	std::vector<TerrainDomainRing> holes;
	bool exterior;
};


/** @brief Find connected terrain regions inside a border and outside occupied
           projected triangles.
    @param[in] occupiedGroups Independently rendered occupied layers. Candidate
                              edges are filtered against triangles in the same
                              group unless preserveBoundaries is true.
    @param[in] border Counter-clockwise outer terrain border.
    @param[out] domains Replaced with deterministic connected terrain domains.
    @param[out] errorMessage Optional failure description.
    @param[in] errorMessageSize Size of @p errorMessage in bytes.
    @return 0 on success, -1 for invalid or inconsistent planar geometry.
 */
int BuildTerrainDomains(
		const std::vector<TerrainDomainBoundaryGroup> &occupiedGroups,
		const TerrainDomainRing &border,
		std::vector<TerrainDomain> *domains,
		char *errorMessage, size_t errorMessageSize);


/** @brief Test whether a point is inside a terrain domain, excluding holes. */
bool TerrainDomainContainsPoint(const TerrainDomain &domain,
	                           double x, double y);


/** @brief Test whether a point is inside or on any boundary of a domain. */
bool TerrainDomainCoversPoint(const TerrainDomain &domain,
	                        double x, double y);


/** @brief Clip one constraint segment to the connected area of a domain.
    @param[in] domain Terrain domain including any occupied holes.
    @param[in] segment Constraint segment to split and classify.
    @param[out] clippedSegments Appended with all positive-length pieces inside
                               @p domain.
 */
void ClipTerrainDomainSegment(
		const TerrainDomain &domain, const TerrainDomainSegment &segment,
		std::vector<TerrainDomainSegment> *clippedSegments);


/** @brief Test whether a complete segment stays inside or on a domain. */
bool TerrainDomainContainsSegment(
		const TerrainDomain &domain, const TerrainDomainSegment &segment);

#endif /* _TERRAINDOMAIN_H_ */
