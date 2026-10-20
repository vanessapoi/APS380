/***************************************************************************

    file                 : terraindomain_test.cpp
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

#include <gtest/gtest.h>

#include <math.h>
#include <string.h>

#include <vector>

#include "terraindomain.h"


static const double kDomainEpsilon = 1e-8;


static TerrainDomainPoint
domainPoint(double x, double y, double z = 0.0, int marker = 1)
{
	TerrainDomainPoint point;
	point.x = x;
	point.y = y;
	point.z = z;
	point.spacing = 5.0;
	point.marker = marker;
	return point;
}


static void
appendDomainTriangle(const TerrainDomainPoint &first,
	                 const TerrainDomainPoint &second,
	                 const TerrainDomainPoint &third,
	                 std::vector<TerrainDomainTriangle> *triangles)
{
	TerrainDomainTriangle triangle;
	triangle.points[0] = first;
	triangle.points[1] = second;
	triangle.points[2] = third;
	triangles->push_back(triangle);
}


static void
appendDomainBoundary(const TerrainDomainPoint &first,
	                const TerrainDomainPoint &second,
	                std::vector<TerrainDomainSegment> *boundaries)
{
	TerrainDomainSegment boundary;
	boundary.points[0] = first;
	boundary.points[1] = second;
	boundaries->push_back(boundary);
}


static std::vector<TerrainDomainSegment>
buildDomainBoundaries(const std::vector<TerrainDomainTriangle> &triangles)
{
	std::vector<TerrainDomainSegment> boundaries;
	for (size_t triangleIndex = 0; triangleIndex < triangles.size();
	        triangleIndex++) {
		const TerrainDomainTriangle &triangle = triangles[triangleIndex];
		double area =
		        (triangle.points[1].x - triangle.points[0].x) *
		        (triangle.points[2].y - triangle.points[0].y) -
		        (triangle.points[1].y - triangle.points[0].y) *
		        (triangle.points[2].x - triangle.points[0].x);
		if (fabs(area) <= kDomainEpsilon) {
			continue;
		}
		for (int edgeIndex = 0; edgeIndex < 3; edgeIndex++) {
			TerrainDomainSegment boundary;
			boundary.points[0] = triangle.points[edgeIndex];
			boundary.points[1] = triangle.points[
			        (edgeIndex + 1) % 3];
			boundaries.push_back(boundary);
		}
	}
	return boundaries;
}


static std::vector<TerrainDomainBoundaryGroup>
buildDomainGroups(
		const std::vector<TerrainDomainTriangle> &triangles,
		const std::vector<TerrainDomainSegment> &boundaries,
		bool preserveBoundaries = false)
{
	TerrainDomainBoundaryGroup group;
	group.triangles = triangles;
	group.boundaries = boundaries;
	group.preserveBoundaries = preserveBoundaries;
	return std::vector<TerrainDomainBoundaryGroup>(1, group);
}


static void
appendDomainRectangle(double minimumX, double minimumY,
	                  double maximumX, double maximumY,
	                  double z, int marker,
	                  std::vector<TerrainDomainTriangle> *triangles)
{
	TerrainDomainPoint lowerLeft = domainPoint(minimumX, minimumY, z, marker);
	TerrainDomainPoint lowerRight = domainPoint(maximumX, minimumY, z, marker);
	TerrainDomainPoint upperRight = domainPoint(maximumX, maximumY, z, marker);
	TerrainDomainPoint upperLeft = domainPoint(minimumX, maximumY, z, marker);
	appendDomainTriangle(lowerLeft, lowerRight, upperRight, triangles);
	appendDomainTriangle(lowerLeft, upperRight, upperLeft, triangles);
}


static void
appendOccupiedFrame(std::vector<TerrainDomainTriangle> *triangles)
{
	appendDomainRectangle(0.0, 0.0, 10.0, 2.0, 0.0, 1, triangles);
	appendDomainRectangle(8.0, 2.0, 10.0, 8.0, 0.0, 1, triangles);
	appendDomainRectangle(0.0, 8.0, 10.0, 10.0, 0.0, 1, triangles);
	appendDomainRectangle(0.0, 2.0, 2.0, 8.0, 0.0, 1, triangles);
}


static TerrainDomainRing
buildDomainBorder()
{
	TerrainDomainRing border;
	border.points.push_back(domainPoint(-5.0, -5.0));
	border.points.push_back(domainPoint(15.0, -5.0));
	border.points.push_back(domainPoint(15.0, 15.0));
	border.points.push_back(domainPoint(-5.0, 15.0));
	return border;
}


static int
domainCountContaining(const std::vector<TerrainDomain> &domains,
	                  double x, double y)
{
	int count = 0;
	for (size_t domainIndex = 0; domainIndex < domains.size(); domainIndex++) {
		if (TerrainDomainContainsPoint(domains[domainIndex], x, y)) {
			count++;
		}
	}
	return count;
}


TEST(TerrainDomainTest, DiscoversExteriorAndClosedTrackInterior)
{
	std::vector<TerrainDomainTriangle> occupiedTriangles;
	std::vector<TerrainDomain> domains;
	TerrainDomainRing border = buildDomainBorder();
	char errorMessage[256];
	appendOccupiedFrame(&occupiedTriangles);

	ASSERT_EQ(0, BuildTerrainDomains(buildDomainGroups(
	                                occupiedTriangles,
	                                buildDomainBoundaries(occupiedTriangles)),
	                                border, &domains,
	                                errorMessage, sizeof(errorMessage)))
	        << errorMessage;
	ASSERT_EQ(2u, domains.size());
	EXPECT_TRUE(domains[0].exterior);
	EXPECT_FALSE(domains[1].exterior);
	ASSERT_EQ(1u, domains[0].holes.size());
	EXPECT_EQ(1, domainCountContaining(domains, -2.0, -2.0));
	EXPECT_EQ(1, domainCountContaining(domains, 5.0, 5.0));
	EXPECT_EQ(0, domainCountContaining(domains, 1.0, 1.0));

	TerrainDomainSegment relief;
	relief.points[0] = domainPoint(-2.0, 5.0, 0.0, 9);
	relief.points[1] = domainPoint(12.0, 5.0, 14.0, 9);
	std::vector<TerrainDomainSegment> exteriorPieces;
	std::vector<TerrainDomainSegment> interiorPieces;
	ClipTerrainDomainSegment(domains[0], relief, &exteriorPieces);
	ClipTerrainDomainSegment(domains[1], relief, &interiorPieces);
	ASSERT_EQ(2u, exteriorPieces.size());
	ASSERT_EQ(1u, interiorPieces.size());
	EXPECT_NEAR(-2.0, exteriorPieces[0].points[0].x, kDomainEpsilon);
	EXPECT_NEAR(0.0, exteriorPieces[0].points[1].x, kDomainEpsilon);
	EXPECT_NEAR(10.0, exteriorPieces[1].points[0].x, kDomainEpsilon);
	EXPECT_NEAR(12.0, exteriorPieces[1].points[1].x, kDomainEpsilon);
	EXPECT_NEAR(2.0, interiorPieces[0].points[0].x, kDomainEpsilon);
	EXPECT_NEAR(8.0, interiorPieces[0].points[1].x, kDomainEpsilon);
	EXPECT_NEAR(4.0, interiorPieces[0].points[0].z, kDomainEpsilon);
	EXPECT_NEAR(10.0, interiorPieces[0].points[1].z, kDomainEpsilon);
	EXPECT_FALSE(TerrainDomainContainsSegment(domains[0], relief));
	EXPECT_FALSE(TerrainDomainContainsSegment(domains[1], relief));
	EXPECT_TRUE(TerrainDomainContainsSegment(domains[0], exteriorPieces[0]));
	EXPECT_TRUE(TerrainDomainContainsSegment(domains[1], interiorPieces[0]));
	EXPECT_TRUE(TerrainDomainCoversPoint(domains[0], 0.0, 5.0));
}


TEST(TerrainDomainTest, UsesExactPerimetersWithoutTriangleDiagonals)
{
	std::vector<TerrainDomainTriangle> occupiedTriangles;
	std::vector<TerrainDomainSegment> occupiedBoundaries;
	std::vector<TerrainDomain> domains;
	TerrainDomainRing border = buildDomainBorder();
	char errorMessage[256];
	appendOccupiedFrame(&occupiedTriangles);
	appendDomainBoundary(domainPoint(0.0, 0.0), domainPoint(10.0, 0.0),
	                     &occupiedBoundaries);
	appendDomainBoundary(domainPoint(10.0, 0.0), domainPoint(10.0, 10.0),
	                     &occupiedBoundaries);
	appendDomainBoundary(domainPoint(10.0, 10.0), domainPoint(0.0, 10.0),
	                     &occupiedBoundaries);
	appendDomainBoundary(domainPoint(0.0, 10.0), domainPoint(0.0, 0.0),
	                     &occupiedBoundaries);
	appendDomainBoundary(domainPoint(2.0, 2.0), domainPoint(8.0, 2.0),
	                     &occupiedBoundaries);
	appendDomainBoundary(domainPoint(8.0, 2.0), domainPoint(8.0, 8.0),
	                     &occupiedBoundaries);
	appendDomainBoundary(domainPoint(8.0, 8.0), domainPoint(2.0, 8.0),
	                     &occupiedBoundaries);
	appendDomainBoundary(domainPoint(2.0, 8.0), domainPoint(2.0, 2.0),
	                     &occupiedBoundaries);

	ASSERT_EQ(0, BuildTerrainDomains(
	        buildDomainGroups(occupiedTriangles, occupiedBoundaries),
	        border, &domains,
	        errorMessage, sizeof(errorMessage))) << errorMessage;
	ASSERT_EQ(2u, domains.size());
	ASSERT_EQ(1u, domains[0].holes.size());
	EXPECT_EQ(1, domainCountContaining(domains, -2.0, -2.0));
	EXPECT_EQ(1, domainCountContaining(domains, 5.0, 5.0));
	EXPECT_EQ(0, domainCountContaining(domains, 1.0, 1.0));
}


TEST(TerrainDomainTest, FiltersInternalAndZeroAreaCandidateEdges)
{
	std::vector<TerrainDomainTriangle> occupiedTriangles;
	std::vector<TerrainDomainSegment> occupiedBoundaries;
	std::vector<TerrainDomain> domains;
	TerrainDomainRing border = buildDomainBorder();
	char errorMessage[256];
	TerrainDomainPoint first = domainPoint(3.0, 5.0, 0.0, 7);
	TerrainDomainPoint second = domainPoint(7.0, 5.0, 2.0, 7);
	TerrainDomainPoint third = domainPoint(5.0, 5.0, 4.0, 7);

	appendDomainRectangle(2.0, 2.0, 8.0, 8.0, 0.0, 1,
	                      &occupiedTriangles);
	occupiedBoundaries = buildDomainBoundaries(occupiedTriangles);
	appendDomainTriangle(first, second, third, &occupiedTriangles);
	appendDomainBoundary(first, second, &occupiedBoundaries);
	appendDomainBoundary(second, third, &occupiedBoundaries);
	appendDomainBoundary(third, first, &occupiedBoundaries);

	ASSERT_EQ(0, BuildTerrainDomains(
	        buildDomainGroups(occupiedTriangles, occupiedBoundaries),
	        border, &domains,
	        errorMessage, sizeof(errorMessage))) << errorMessage;
	ASSERT_EQ(1u, domains.size());
	ASSERT_EQ(1u, domains[0].holes.size());
	EXPECT_EQ(4u, domains[0].holes[0].points.size());
	EXPECT_EQ(1, domainCountContaining(domains, 0.0, 0.0));
	EXPECT_EQ(0, domainCountContaining(domains, 5.0, 5.0));
}


TEST(TerrainDomainTest, SplitsInteriorAtOverlappingCrossingStrips)
{
	std::vector<TerrainDomainTriangle> occupiedTriangles;
	std::vector<TerrainDomain> domains;
	TerrainDomainRing border = buildDomainBorder();
	char errorMessage[256];
	appendOccupiedFrame(&occupiedTriangles);
	appendDomainRectangle(4.0, 1.0, 5.0, 9.0, 3.0, 7,
	                      &occupiedTriangles);
	appendDomainRectangle(6.0, 1.0, 7.0, 9.0, 3.0, 7,
	                      &occupiedTriangles);

	ASSERT_EQ(0, BuildTerrainDomains(buildDomainGroups(
	                                occupiedTriangles,
	                                buildDomainBoundaries(occupiedTriangles)),
	                                border, &domains,
	                                errorMessage, sizeof(errorMessage)))
	        << errorMessage;
	ASSERT_EQ(4u, domains.size());
	EXPECT_TRUE(domains[0].exterior);
	EXPECT_EQ(1, domainCountContaining(domains, 3.0, 5.0));
	EXPECT_EQ(1, domainCountContaining(domains, 5.5, 5.0));
	EXPECT_EQ(1, domainCountContaining(domains, 7.5, 5.0));
	EXPECT_EQ(0, domainCountContaining(domains, 4.5, 5.0));
	EXPECT_EQ(0, domainCountContaining(domains, 6.5, 5.0));

	bool foundCrossingJunction = false;
	for (size_t domainIndex = 0; domainIndex < domains.size(); domainIndex++) {
		const TerrainDomainRing &ring = domains[domainIndex].outer;
		for (size_t pointIndex = 0; pointIndex < ring.points.size(); pointIndex++) {
			const TerrainDomainPoint &point = ring.points[pointIndex];
			if ((fabs(point.x - 4.0) <= kDomainEpsilon) &&
			        (fabs(point.y - 2.0) <= kDomainEpsilon)) {
				EXPECT_NEAR(3.0, point.z, kDomainEpsilon);
				EXPECT_EQ(7, point.marker);
				foundCrossingJunction = true;
			}
		}
	}
	EXPECT_TRUE(foundCrossingJunction);
}


TEST(TerrainDomainTest, PreservesNarrowFreeFaceNearCrossingEndpoint)
{
	std::vector<TerrainDomainTriangle> occupiedTriangles;
	std::vector<TerrainDomain> domains;
	TerrainDomainRing border = buildDomainBorder();
	char errorMessage[256];
	appendOccupiedFrame(&occupiedTriangles);
	appendDomainRectangle(2.0005, 1.0, 3.0, 9.0, 3.0, 7,
	                      &occupiedTriangles);

	ASSERT_EQ(0, BuildTerrainDomains(buildDomainGroups(
	                                occupiedTriangles,
	                                buildDomainBoundaries(occupiedTriangles)),
	                                border, &domains,
	                                errorMessage, sizeof(errorMessage)))
	        << errorMessage;
	ASSERT_EQ(3u, domains.size());
	EXPECT_EQ(1, domainCountContaining(domains, 2.00025, 5.0));
	EXPECT_EQ(0, domainCountContaining(domains, 2.5, 5.0));
	EXPECT_EQ(1, domainCountContaining(domains, 4.0, 5.0));
}


TEST(TerrainDomainTest, IgnoresOccupiedTrianglesWithoutProjectedArea)
{
	std::vector<TerrainDomainTriangle> occupiedTriangles;
	std::vector<TerrainDomain> domains;
	TerrainDomainRing border = buildDomainBorder();
	char errorMessage[256];
	appendOccupiedFrame(&occupiedTriangles);
	appendDomainTriangle(domainPoint(2.0, 5.0, 0.0, 7),
	                     domainPoint(8.0, 5.0, 2.0, 7),
	                     domainPoint(5.0, 5.0, 4.0, 7),
	                     &occupiedTriangles);

	ASSERT_EQ(0, BuildTerrainDomains(buildDomainGroups(
	                                occupiedTriangles,
	                                buildDomainBoundaries(occupiedTriangles)),
	                                border, &domains,
	                                errorMessage, sizeof(errorMessage)))
	        << errorMessage;
	ASSERT_EQ(2u, domains.size());
	EXPECT_EQ(1, domainCountContaining(domains, 5.0, 4.0));
	EXPECT_EQ(1, domainCountContaining(domains, 5.0, 6.0));
}
