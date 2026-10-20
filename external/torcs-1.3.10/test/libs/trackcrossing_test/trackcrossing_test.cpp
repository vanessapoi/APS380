/***************************************************************************

    file                 : trackcrossing_test.cpp
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

#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>

#include <tgf.h>

#include "trackcrossing.h"


static const double kEps = 1e-5;
static const double kPi = 3.14159265358979323846;


static t3Dd
triangleNormal(const TrackCrossingObject &object, size_t triangleIndex)
{
	const TrackCrossingTriangle &triangle = object.triangles[triangleIndex];
	const TrackCrossingPoint &first = object.vertices[triangle.vertex[0]];
	const TrackCrossingPoint &second = object.vertices[triangle.vertex[1]];
	const TrackCrossingPoint &third = object.vertices[triangle.vertex[2]];
	t3Dd normal;
	double firstX = second.x - first.x;
	double firstY = second.y - first.y;
	double firstZ = second.z - first.z;
	double secondX = third.x - first.x;
	double secondY = third.y - first.y;
	double secondZ = third.z - first.z;
	normal.x = (tdble)(firstY * secondZ - firstZ * secondY);
	normal.y = (tdble)(firstZ * secondX - firstX * secondZ);
	normal.z = (tdble)(firstX * secondY - firstY * secondX);
	return normal;
}


static bool
triangleUsesVertex(const TrackCrossingTriangle &triangle, int vertexIndex)
{
	return (triangle.vertex[0] == vertexIndex) ||
	       (triangle.vertex[1] == vertexIndex) ||
	       (triangle.vertex[2] == vertexIndex);
}


static bool
triangleUsesVertices(const TrackCrossingTriangle &triangle,
	                int first, int second, int third)
{
	return triangleUsesVertex(triangle, first) &&
	       triangleUsesVertex(triangle, second) &&
	       triangleUsesVertex(triangle, third);
}


static int
findVertexNear(const TrackCrossingObject &object,
	          double x, double y, double z)
{
	for (size_t index = 0; index < object.vertices.size(); index++) {
		const TrackCrossingPoint &vertex = object.vertices[index];
		if ((fabs(vertex.x - x) <= kEps) &&
		        (fabs(vertex.y - y) <= kEps) &&
		        (fabs(vertex.z - z) <= kEps)) {
			return (int)index;
		}
	}
	return -1;
}


static bool
hasVertexNear(const TrackCrossingObject &object,
	         double x, double y, double z)
{
	return findVertexNear(object, x, y, z) >= 0;
}


static bool
hasTriangleVertices(const TrackCrossingObject &object,
	               int first, int second, int third)
{
	for (size_t index = 0; index < object.triangles.size(); index++) {
		if (triangleUsesVertices(object.triangles[index],
		                         first, second, third)) {
			return true;
		}
	}
	return false;
}


static bool
matchesLeftCurveSample(const TrackCrossingPoint &point,
	                  double radius, double startAngle, double arc,
	                  double sampleAngleStep)
{
	double endAngle = startAngle + arc;
	double angle;
	for (angle = startAngle; angle < endAngle; angle += sampleAngleStep) {
		double expectedX = radius * sin(angle);
		double expectedY = -radius * cos(angle);
		if ((fabs(point.x - expectedX) <= kEps) &&
		        (fabs(point.y - expectedY) <= kEps)) {
			return true;
		}
	}
	return (fabs(point.x - radius * sin(endAngle)) <= kEps) &&
	       (fabs(point.y + radius * cos(endAngle)) <= kEps);
}


class SyntheticCrossingTrack
{
public:
	explicit SyntheticCrossingTrack(int segmentCount) :
		segments(segmentCount), surfaces(segmentCount),
		barriers(segmentCount * 2)
	{
		memset(&track, 0, sizeof(track));
		memset(segments.data(), 0, segments.size() * sizeof(tTrackSeg));
		memset(surfaces.data(), 0, surfaces.size() * sizeof(tTrackSurface));
		memset(barriers.data(), 0, barriers.size() * sizeof(tTrackBarrier));
		for (int index = 0; index < segmentCount; index++) {
			segments[index].id = index;
			segments[index].type2 = TR_MAIN;
			segments[index].style = TR_PLAN;
			segments[index].surface = &surfaces[index];
			surfaces[index].material = TRK_VAL_ASPHALT;
			surfaces[index].kRoughWaveLen = 1.0f;
		}
		track.version = 4;
		track.width = 8.0f;
	}

	void configureStraight(int index, double startX, double startY,
	                     double endX, double endY, double elevation,
	                     double width = 8.0)
	{
		tTrackSeg &segment = segments[index];
		double deltaX = endX - startX;
		double deltaY = endY - startY;
		double length = sqrt(deltaX * deltaX + deltaY * deltaY);
		double leftX = -deltaY / length;
		double leftY = deltaX / length;
		segment.type = TR_STR;
		segment.length = (tdble)length;
		segment.width = (tdble)width;
		segment.startWidth = (tdble)width;
		segment.endWidth = (tdble)width;
		segment.angle[TR_ZS] = (tdble)atan2(deltaY, deltaX);
		segment.angle[TR_ZE] = segment.angle[TR_ZS];
		segment.rgtSideNormal.x = (tdble)-leftX;
		segment.rgtSideNormal.y = (tdble)-leftY;
		setVertex(segment.vertex[TR_SL], startX + leftX * width / 2.0,
		          startY + leftY * width / 2.0, elevation);
		setVertex(segment.vertex[TR_SR], startX - leftX * width / 2.0,
		          startY - leftY * width / 2.0, elevation);
		setVertex(segment.vertex[TR_EL], endX + leftX * width / 2.0,
		          endY + leftY * width / 2.0, elevation);
		setVertex(segment.vertex[TR_ER], endX - leftX * width / 2.0,
		          endY - leftY * width / 2.0, elevation);
	}

	void configureLeftCurve(int index, double centerX, double centerY,
	                      double radius, double startAngle, double arc,
	                      double elevation, double width = 8.0)
	{
		tTrackSeg &segment = segments[index];
		segment.type = TR_LFT;
		segment.length = (tdble)(radius * arc);
		segment.width = (tdble)width;
		segment.startWidth = (tdble)width;
		segment.endWidth = (tdble)width;
		segment.radius = (tdble)radius;
		segment.radiusr = (tdble)(radius + width / 2.0);
		segment.radiusl = (tdble)(radius - width / 2.0);
		segment.arc = (tdble)arc;
		segment.center.x = (tdble)centerX;
		segment.center.y = (tdble)centerY;
		segment.angle[TR_ZS] = (tdble)startAngle;
		segment.angle[TR_ZE] = (tdble)(startAngle + arc);
		setCurveVertex(segment.vertex[TR_SL], centerX, centerY,
		               radius - width / 2.0, startAngle, elevation);
		setCurveVertex(segment.vertex[TR_SR], centerX, centerY,
		               radius + width / 2.0, startAngle, elevation);
		setCurveVertex(segment.vertex[TR_EL], centerX, centerY,
		               radius - width / 2.0, startAngle + arc, elevation);
		setCurveVertex(segment.vertex[TR_ER], centerX, centerY,
		               radius + width / 2.0, startAngle + arc, elevation);
	}

	void configureGrade(int index, double slope, double banking)
	{
		tTrackSeg &segment = segments[index];
		segment.Kzl = (tdble)slope;
		segment.angle[TR_XS] = (tdble)banking;
		segment.angle[TR_XE] = (tdble)banking;
		segment.vertex[TR_ER].z += (tdble)(slope * segment.length);
		segment.vertex[TR_SL].z += (tdble)(segment.width * tan(banking));
		segment.vertex[TR_EL].z += (tdble)(slope * segment.length +
		        segment.width * tan(banking));
	}

	void configureWall(int segmentIndex, int side, double width, double height)
	{
		tTrackBarrier &barrier = barriers[segmentIndex * 2 + side];
		barrier.style = TR_WALL;
		barrier.width = (tdble)width;
		barrier.height = (tdble)height;
		barrier.surface = &surfaces[segmentIndex];
		segments[segmentIndex].barrier[side] = &barrier;
	}

	void finish()
	{
		double length = 0.0;
		track.nseg = (int)segments.size();
		for (int index = 0; index < track.nseg; index++) {
			segments[index].lgfromstart = (tdble)length;
			segments[index].next = &segments[(index + 1) % track.nseg];
			segments[index].prev = &segments[(index + track.nseg - 1) %
			                                    track.nseg];
			length += segments[index].length;
		}
		track.length = (tdble)length;
		track.seg = &segments.back();
	}

	tTrack *getTrack()
	{
		return &track;
	}

private:
	static void setVertex(t3Dd &vertex, double x, double y, double z)
	{
		vertex.x = (tdble)x;
		vertex.y = (tdble)y;
		vertex.z = (tdble)z;
	}

	static void setCurveVertex(t3Dd &vertex, double centerX, double centerY,
	                         double radius, double angle, double z)
	{
		setVertex(vertex, centerX + radius * sin(angle),
		          centerY - radius * cos(angle), z);
	}

	tTrack track;
	std::vector<tTrackSeg> segments;
	std::vector<tTrackSurface> surfaces;
	std::vector<tTrackBarrier> barriers;
};


static TrackCrossingModel
buildModel(SyntheticCrossingTrack *syntheticTrack,
	       double socketGap = 0.5, double bridgeThickness = 1.0,
	       double trackStep = 5.0, void *handle = NULL)
{
	TrackCrossingSettings settings;
	TrackCrossingModel model;
	char error[256];
	settings.socketGap = (tdble)socketGap;
	settings.bridgeThickness = (tdble)bridgeThickness;
	EXPECT_EQ(0, BuildTrackCrossingModel(syntheticTrack->getTrack(), handle,
	                                    (tdble)trackStep, &settings, &model, error,
	                                    sizeof(error))) << error;
	return model;
}


static void
configureStraightCrossing(SyntheticCrossingTrack *track,
	                      double upperElevation = 10.0,
	                      double lowerElevation = 0.0)
{
	track->configureStraight(0, -30.0, 0.0, 30.0, 0.0, upperElevation);
	track->configureStraight(1, 100.0, 100.0, 110.0, 100.0, 0.0);
	track->configureStraight(2, 0.0, -30.0, 0.0, 30.0, lowerElevation);
	track->configureStraight(3, 100.0, 120.0, 110.0, 120.0, 0.0);
	track->configureWall(2, TR_SIDE_RGT, 2.0, 1.0);
	track->configureWall(2, TR_SIDE_LFT, 2.0, 1.0);
	track->finish();
}


static std::vector<const TrackCrossingObject *>
crossingParts(const TrackCrossingGeometry &crossing)
{
	return { &crossing.underside, &crossing.bridgeRight, &crossing.bridgeLeft,
	         &crossing.socketRight, &crossing.socketLeft,
	         &crossing.filler[TR_SIDE_RGT][TR_SIDE_RGT],
	         &crossing.filler[TR_SIDE_LFT][TR_SIDE_RGT],
	         &crossing.filler[TR_SIDE_RGT][TR_SIDE_LFT],
	         &crossing.filler[TR_SIDE_LFT][TR_SIDE_LFT],
	         &crossing.floorRight, &crossing.floorLeft };
}


TEST(TrackCrossingStraightTest, BuildsBridgeSocketsAndFloorsOutsideWalls)
{
	SyntheticCrossingTrack track(4);
	configureStraightCrossing(&track);
	TrackCrossingModel model = buildModel(&track);

	ASSERT_EQ(1, model.candidateCount);
	ASSERT_EQ(1u, model.crossings.size());
	const TrackCrossingGeometry &crossing = model.crossings[0];
	EXPECT_EQ(0, crossing.upperSegmentId);
	EXPECT_EQ(2, crossing.lowerSegmentId);
	EXPECT_NEAR(9.0, crossing.undersideZ, kEps);
	EXPECT_NEAR(1.0, crossing.minimumBridgeThickness, kEps);
	EXPECT_NEAR(0.5, crossing.measuredSocketGap[TR_SIDE_RGT], kEps);
	EXPECT_NEAR(0.5, crossing.measuredSocketGap[TR_SIDE_LFT], kEps);
	EXPECT_EQ("TRKBRIDGE_UNDERSIDE0", crossing.underside.name);
	EXPECT_EQ("TRKBRIDGE_R0", crossing.bridgeRight.name);
	EXPECT_EQ("TRKBRIDGE_L0", crossing.bridgeLeft.name);
	EXPECT_EQ("TRKSOCKET_WALL_R0", crossing.socketRight.name);
	EXPECT_EQ("TRKSOCKET_WALL_L0", crossing.socketLeft.name);
	EXPECT_EQ("TRKFILLER_RR0", crossing.filler[TR_SIDE_RGT][TR_SIDE_RGT].name);
	EXPECT_EQ("TRKFILLER_LR0", crossing.filler[TR_SIDE_LFT][TR_SIDE_RGT].name);
	EXPECT_EQ("TRKFILLER_RL0", crossing.filler[TR_SIDE_RGT][TR_SIDE_LFT].name);
	EXPECT_EQ("TRKFILLER_LL0", crossing.filler[TR_SIDE_LFT][TR_SIDE_LFT].name);
	EXPECT_EQ("TRKFLOOR_R0", crossing.floorRight.name);
	EXPECT_EQ("TRKFLOOR_L0", crossing.floorLeft.name);
	ASSERT_EQ(6u, crossing.floorRight.vertices.size());
	ASSERT_EQ(4u, crossing.floorRight.triangles.size());
	ASSERT_EQ(6u, crossing.floorLeft.vertices.size());
	ASSERT_EQ(4u, crossing.floorLeft.triangles.size());
	ASSERT_EQ(12u, crossing.terrainMask.vertices.size());
	ASSERT_EQ(4u, crossing.terrainMask.triangles.size());
	EXPECT_NEAR(6.0, crossing.floorRight.vertices[0].x, kEps);
	EXPECT_NEAR(-5.0, crossing.floorRight.vertices[0].y, kEps);
	EXPECT_NEAR(6.5, crossing.floorRight.vertices[1].x, kEps);
	EXPECT_NEAR(-4.0, crossing.floorRight.vertices[1].y, kEps);
	EXPECT_NEAR(6.0, crossing.floorRight.vertices[4].x, kEps);
	EXPECT_NEAR(5.0, crossing.floorRight.vertices[4].y, kEps);
	EXPECT_NEAR(6.5, crossing.floorRight.vertices[5].x, kEps);
	EXPECT_NEAR(4.0, crossing.floorRight.vertices[5].y, kEps);
	EXPECT_NEAR(-6.0, crossing.floorLeft.vertices[0].x, kEps);
	EXPECT_NEAR(-5.0, crossing.floorLeft.vertices[0].y, kEps);
	EXPECT_NEAR(-6.0, crossing.floorLeft.vertices[4].x, kEps);
	EXPECT_NEAR(5.0, crossing.floorLeft.vertices[4].y, kEps);
	EXPECT_TRUE(triangleUsesVertices(crossing.floorRight.triangles[0],
	                                0, 1, 2));
	EXPECT_TRUE(triangleUsesVertices(crossing.floorRight.triangles[1],
	                                1, 2, 3));
	EXPECT_TRUE(triangleUsesVertices(crossing.floorRight.triangles[2],
	                                2, 3, 4));
	EXPECT_TRUE(triangleUsesVertices(crossing.floorRight.triangles[3],
	                                3, 4, 5));
	EXPECT_TRUE(triangleUsesVertices(crossing.floorLeft.triangles[0],
	                                0, 1, 2));
	EXPECT_TRUE(triangleUsesVertices(crossing.floorLeft.triangles[1],
	                                1, 2, 3));
	EXPECT_TRUE(triangleUsesVertices(crossing.floorLeft.triangles[2],
	                                2, 3, 4));
	EXPECT_TRUE(triangleUsesVertices(crossing.floorLeft.triangles[3],
	                                3, 4, 5));
	EXPECT_FALSE(crossing.underside.triangles.empty());
	EXPECT_FALSE(crossing.socketRight.triangles.empty());
	EXPECT_FALSE(crossing.floorRight.triangles.empty());
	EXPECT_LT(triangleNormal(crossing.underside, 0).z, 0.0f);
	EXPECT_LT(triangleNormal(crossing.socketRight, 0).x, 0.0f);
	EXPECT_GT(triangleNormal(crossing.socketLeft, 0).x, 0.0f);
	for (size_t triangleIndex = 0;
	        triangleIndex < crossing.floorRight.triangles.size();
	        triangleIndex++) {
		EXPECT_GT(triangleNormal(crossing.floorRight, triangleIndex).z,
		          kEps);
	}
	for (size_t triangleIndex = 0;
	        triangleIndex < crossing.floorLeft.triangles.size();
	        triangleIndex++) {
		EXPECT_GT(triangleNormal(crossing.floorLeft, triangleIndex).z,
		          kEps);
	}

	const TrackCrossingObject &underside = crossing.underside;
	std::vector<int> undersideTriangleIncidence(underside.vertices.size(), 0);
	for (size_t triangleIndex = 0; triangleIndex < underside.triangles.size(); triangleIndex++) {
		EXPECT_LT(triangleNormal(underside, triangleIndex).z, -kEps);
		for (int reference = 0; reference < 3; reference++) {
			undersideTriangleIncidence[underside.triangles[triangleIndex].vertex[reference]]++;
		}
	}
	EXPECT_LE(*std::max_element(undersideTriangleIncidence.begin(),
	                           undersideTriangleIncidence.end()), 4);
	int rightFirst = findVertexNear(underside, 5.0, -4.0, 9.0);
	int leftFirst = findVertexNear(underside, 5.0, 4.0, 9.0);
	int rightSecond = findVertexNear(underside, 0.0, -4.0, 9.0);
	int leftSecond = findVertexNear(underside, 0.0, 4.0, 9.0);
	ASSERT_GE(rightFirst, 0);
	ASSERT_GE(leftFirst, 0);
	ASSERT_GE(rightSecond, 0);
	ASSERT_GE(leftSecond, 0);
	EXPECT_TRUE(hasTriangleVertices(underside,
	                                rightFirst, leftFirst, rightSecond));
	EXPECT_TRUE(hasTriangleVertices(underside,
	                                leftFirst, leftSecond, rightSecond));
	EXPECT_TRUE(hasVertexNear(crossing.bridgeRight, -10.0, -4.0, 10.0));
	EXPECT_TRUE(hasVertexNear(crossing.bridgeRight, 10.0, -4.0, 10.0));
	EXPECT_TRUE(hasVertexNear(crossing.bridgeLeft, -10.0, 4.0, 10.0));
	EXPECT_TRUE(hasVertexNear(crossing.bridgeLeft, 10.0, 4.0, 10.0));
	EXPECT_FALSE(hasVertexNear(crossing.bridgeRight, -6.5, -4.0, 10.0));
	EXPECT_FALSE(hasVertexNear(crossing.bridgeRight, 6.5, -4.0, 10.0));
	EXPECT_FALSE(hasVertexNear(crossing.bridgeLeft, -6.5, 4.0, 10.0));
	EXPECT_FALSE(hasVertexNear(crossing.bridgeLeft, 6.5, 4.0, 10.0));
	for (int side = 0; side < 2; side++) {
		const TrackCrossingObject &fascia = side == TR_SIDE_RGT
		        ? crossing.bridgeRight : crossing.bridgeLeft;
		ASSERT_FALSE(fascia.triangles.empty());
		for (size_t index = 0; index < fascia.triangles.size(); index++) {
			t3Dd normal = triangleNormal(fascia, index);
			EXPECT_NEAR(normal.z, 0.0, kEps);
			EXPECT_GT(side == TR_SIDE_RGT ? -normal.y : normal.y, kEps);
		}
		for (int lowerSide = 0; lowerSide < 2; lowerSide++) {
			const TrackCrossingObject &filler = crossing.filler[side][lowerSide];
			ASSERT_EQ(1u, filler.triangles.size());
			EXPECT_GT(triangleNormal(filler, 0).z, kEps);
			EXPECT_EQ(filler.texture, fascia.texture);
		}
	}
	for (size_t vertexIndex = 0;
	        vertexIndex < crossing.terrainMask.vertices.size(); vertexIndex++) {
		const TrackCrossingPoint &vertex =
		        crossing.terrainMask.vertices[vertexIndex];
		bool found = false;
		for (const TrackCrossingObject *part : crossingParts(crossing)) {
			found |= hasVertexNear(*part, vertex.x, vertex.y, vertex.z);
		}
		EXPECT_TRUE(found);
	}
	for (size_t triangleIndex = 0;
	        triangleIndex < crossing.terrainMask.triangles.size();
	        triangleIndex++) {
		EXPECT_GT(fabs(triangleNormal(
		        crossing.terrainMask, triangleIndex).z), kEps);
	}
}


/* Count geometric edges, including copies at object/texture seams. */
static int
edgeIncidence(const TrackCrossingObject &object,
              const TrackCrossingPoint &first, const TrackCrossingPoint &second,
              bool signedCount = false)
{
	int count = 0;
	for (size_t index = 0; index < object.triangles.size(); index++) {
		const TrackCrossingTriangle &triangle = object.triangles[index];
		int firstReference = -1;
		int secondReference = -1;
		for (int reference = 0; reference < 3; reference++) {
			const TrackCrossingPoint &point = object.vertices[triangle.vertex[reference]];
			if (fabs(point.x - first.x) <= kEps &&
			        fabs(point.y - first.y) <= kEps && fabs(point.z - first.z) <= kEps) {
				firstReference = reference;
			}
			if (fabs(point.x - second.x) <= kEps &&
			        fabs(point.y - second.y) <= kEps && fabs(point.z - second.z) <= kEps) {
				secondReference = reference;
			}
		}
		if (firstReference >= 0 && secondReference >= 0) {
			count += !signedCount || (firstReference + 1) % 3 == secondReference ? 1 : -1;
		}
	}
	return count;
}


static void
expectClosedPortals(const TrackCrossingGeometry &crossing)
{
	ASSERT_EQ(12u, crossing.terrainMask.vertices.size());
	for (size_t corner = 0; corner < 4; corner++) {
		SCOPED_TRACE(corner);
		const TrackCrossingPoint &upper = crossing.terrainMask.vertices[3 * corner];
		const TrackCrossingPoint &base = crossing.terrainMask.vertices[3 * corner + 1];
		const TrackCrossingPoint &floor = crossing.terrainMask.vertices[3 * corner + 2];
		TrackCrossingPoint top = base;
		top.z = crossing.undersideZ;
		const TrackCrossingPoint edges[4][2] = {
			{ top, base }, { upper, top }, { base, floor }, { upper, floor }
		};
		for (int edge = 0; edge < 4; edge++) {
			int incidence = 0;
			int winding = 0;
			for (const TrackCrossingObject *part : crossingParts(crossing)) {
				incidence += edgeIncidence(*part, edges[edge][0], edges[edge][1]);
				winding += edgeIncidence(*part, edges[edge][0], edges[edge][1], true);
			}
			EXPECT_EQ(edge == 3 ? 1 : 2, incidence);
			if (edge != 3) {
				EXPECT_EQ(0, winding);
			}
		}
	}
	for (const TrackCrossingObject *socket : crossingParts(crossing)) {
		for (size_t index = 0; index < socket->triangles.size(); index++) {
			t3Dd normal = triangleNormal(*socket, index);
			EXPECT_GT(sqrt(normal.x * normal.x + normal.y * normal.y +
			               normal.z * normal.z), kEps);
			const TrackCrossingTriangle &triangle = socket->triangles[index];
			const TrackCrossingPoint &a = socket->vertices[triangle.vertex[0]];
			const TrackCrossingPoint &b = socket->vertices[triangle.vertex[1]];
			const TrackCrossingPoint &c = socket->vertices[triangle.vertex[2]];
			// UV area has different units from geometric area; retain small but valid charts.
			EXPECT_GT(fabs((b.u - a.u) * (c.v - a.v) - (b.v - a.v) * (c.u - a.u)), 1e-12);
		}
	}
}


TEST(TrackCrossingPortalTest, ClosesAllFourCornersAcrossSamplingAndCrossingAngles)
{
	const double steps[] = { 0.5, 2.0, 5.0, 20.0 };
	const double angles[] = { kPi / 2.0, 2.0 * kPi / 7.0, -2.0 * kPi / 7.0 };
	for (double step : steps) {
		for (double angle : angles) {
			SCOPED_TRACE(step);
			SCOPED_TRACE(angle);
			SyntheticCrossingTrack track(4);
			// Keep the sampled window clear of the disconnected filler segments.
			track.configureStraight(0, -100.0, 0.0, 100.0, 0.0, 10.0, 8.3);
			track.configureStraight(1, 100.0, 100.0, 110.0, 100.0, 0.0);
			track.configureStraight(2, -97.8 * cos(angle), -97.8 * sin(angle),
			                        102.2 * cos(angle), 102.2 * sin(angle), 0.0, 9.1);
			track.configureStraight(3, 100.0, 120.0, 110.0, 120.0, 0.0);
			track.finish();
			TrackCrossingModel model = buildModel(&track, 0.5, 1.0, step);
			ASSERT_EQ(1u, model.crossings.size());
			expectClosedPortals(model.crossings[0]);
		}
	}
}


TEST(TrackCrossingPortalTest, ClosesSlopedAndBankedApproaches)
{
	SyntheticCrossingTrack track(4);
	configureStraightCrossing(&track);
	track.configureGrade(0, 0.02, 0.08);
	track.configureGrade(2, -0.01, -0.04);
	TrackCrossingModel model = buildModel(&track);
	ASSERT_EQ(1u, model.crossings.size());
	expectClosedPortals(model.crossings[0]);
}


TEST(TrackCrossingPortalTest, FineSamplingDoesNotSuppressFloorAtRoundedWindowEnd)
{
	SyntheticCrossingTrack track(4);
	track.configureStraight(0, -30.0, 0.0, 30.0, 0.0, 10.0, 8.3);
	track.configureStraight(1, 100.0, 100.0, 110.0, 100.0, 0.0);
	track.configureStraight(2, 0.0, -27.8, 0.0, 32.2, 0.0, 9.1);
	track.configureStraight(3, 100.0, 120.0, 110.0, 120.0, 0.0);
	track.finish();
	TrackCrossingModel model = buildModel(&track, 0.5, 1.0, 0.5);
	ASSERT_EQ(1u, model.crossings.size());
	expectClosedPortals(model.crossings[0]);
}


TEST(TrackCrossingRenderedEndpointTest,
     KeepsIntersectionVertexWithoutExtendingPastIt)
{
	SyntheticCrossingTrack track(4);
	track.configureStraight(0, -30.0, 0.0, 30.0, 0.0, 10.0, 10.0);
	track.configureStraight(1, 100.0, 100.0, 110.0, 100.0, 0.0);
	track.configureStraight(2, 0.0, -30.0, 0.0, 30.0, 0.0, 9.0);
	track.configureStraight(3, 100.0, 120.0, 110.0, 120.0, 0.0);
	track.finish();
	TrackCrossingModel model = buildModel(&track);

	ASSERT_EQ(1u, model.crossings.size());
	const TrackCrossingGeometry &crossing = model.crossings[0];
	ASSERT_EQ(6u, crossing.floorRight.vertices.size());
	ASSERT_EQ(4u, crossing.floorRight.triangles.size());
	EXPECT_TRUE(hasVertexNear(crossing.floorRight, 4.5, -5.0, 0.0));
	EXPECT_TRUE(hasVertexNear(crossing.floorRight, 4.5, 5.0, 0.0));
	EXPECT_FALSE(hasVertexNear(crossing.floorRight, 4.5, -10.0, 0.0));
	EXPECT_FALSE(hasVertexNear(crossing.floorRight, 4.5, 10.0, 0.0));
	EXPECT_TRUE(hasVertexNear(crossing.bridgeRight, -5.0, -5.0, 10.0));
	EXPECT_TRUE(hasVertexNear(crossing.bridgeRight, 5.0, -5.0, 10.0));
	EXPECT_TRUE(hasVertexNear(crossing.bridgeLeft, -5.0, 5.0, 10.0));
	EXPECT_TRUE(hasVertexNear(crossing.bridgeLeft, 5.0, 5.0, 10.0));
	EXPECT_FALSE(hasVertexNear(crossing.bridgeRight, -10.0, -5.0, 10.0));
	EXPECT_FALSE(hasVertexNear(crossing.bridgeRight, 10.0, -5.0, 10.0));
	for (int upperSide = 0; upperSide < 2; upperSide++) {
		for (int lowerSide = 0; lowerSide < 2; lowerSide++) {
			EXPECT_TRUE(crossing.filler[upperSide][lowerSide].triangles.empty());
		}
	}
	expectClosedPortals(crossing);
}


TEST(TrackCrossingPortalTest, AlignedObliqueReturnStaysTogetherOutsideFasciaPlane)
{
	SyntheticCrossingTrack track(4);
	double angle = kPi / 4.0;
	// The lower right socket intersects the upper right edge at (5, -4),
	// exactly on an upper renderer station, but the floor end lies farther out.
	double lowerWidth = 2.0 * (9.0 / sqrt(2.0) - 0.5);
	track.configureStraight(0, -100.0, 0.0, 100.0, 0.0, 10.0);
	track.configureStraight(1, 150.0, 150.0, 160.0, 150.0, 0.0);
	track.configureStraight(2, -97.8 * cos(angle), -97.8 * sin(angle),
	                        102.2 * cos(angle), 102.2 * sin(angle), 0.0, lowerWidth);
	track.configureStraight(3, 150.0, 170.0, 160.0, 170.0, 0.0);
	track.finish();
	TrackCrossingModel model = buildModel(&track);
	ASSERT_EQ(1u, model.crossings.size());
	const TrackCrossingGeometry &crossing = model.crossings[0];
	const TrackCrossingObject &filler = crossing.filler[TR_SIDE_RGT][TR_SIDE_RGT];
	ASSERT_EQ(2u, filler.triangles.size());
	EXPECT_TRUE(hasVertexNear(filler, 5.0, -4.0, 10.0));
	EXPECT_TRUE(hasVertexNear(filler, 5.0, -4.0, 9.0));
	EXPECT_TRUE(hasVertexNear(filler, 5.0, -4.0, 0.0));
	EXPECT_FALSE(hasVertexNear(crossing.bridgeRight, 5.0, -4.0, 0.0));
	expectClosedPortals(crossing);
}


TEST(TrackCrossingRenderedEndpointTest,
     ExtendsPortalPastRawBoundaryAtObliqueCrossing)
{
	SyntheticCrossingTrack track(4);
	double angle = 2.0 * kPi / 7.0;
	double directionX = cos(angle);
	double directionY = sin(angle);
	double lowerStart = -27.8;
	double lowerEnd = 32.2;
	track.configureStraight(0, -30.0, 0.0, 30.0, 0.0, 10.0, 10.0);
	track.configureStraight(1, 100.0, 100.0, 110.0, 100.0, 0.0);
	track.configureStraight(2, lowerStart * directionX,
	                        lowerStart * directionY,
	                        lowerEnd * directionX,
	                        lowerEnd * directionY, 0.0, 10.0);
	track.configureStraight(3, 100.0, 120.0, 110.0, 120.0, 0.0);
	track.finish();
	TrackCrossingModel model = buildModel(&track);

	ASSERT_EQ(1u, model.crossings.size());
	const TrackCrossingGeometry &crossing = model.crossings[0];
	ASSERT_EQ(12u, crossing.terrainMask.vertices.size());
	const TrackCrossingPoint &floorExtension =
	        crossing.terrainMask.vertices[11];
	EXPECT_GT(floorExtension.y, 5.0 + kEps);
	EXPECT_TRUE(hasVertexNear(crossing.floorLeft, floorExtension.x,
	                          floorExtension.y, floorExtension.z));
}


TEST(TrackCrossingRenderedEndpointTest,
     PreservesWallWidthStepInsideBridgeSpan)
{
	SyntheticCrossingTrack track(5);
	track.configureStraight(0, -30.0, 0.0, 0.0, 0.0, 10.0);
	track.configureStraight(1, 0.0, 0.0, 30.0, 0.0, 10.0);
	track.configureStraight(2, 100.0, 100.0, 110.0, 100.0, 0.0);
	track.configureStraight(3, 0.0, -30.0, 0.0, 30.0, 0.0);
	track.configureStraight(4, 100.0, 120.0, 110.0, 120.0, 0.0);
	track.configureWall(0, TR_SIDE_RGT, 1.0, 1.0);
	track.configureWall(0, TR_SIDE_LFT, 1.0, 1.0);
	track.configureWall(1, TR_SIDE_RGT, 3.0, 1.0);
	track.configureWall(1, TR_SIDE_LFT, 3.0, 1.0);
	track.configureWall(3, TR_SIDE_RGT, 2.0, 1.0);
	track.configureWall(3, TR_SIDE_LFT, 2.0, 1.0);
	track.finish();
	TrackCrossingModel model = buildModel(&track);

	ASSERT_EQ(1u, model.crossings.size());
	const TrackCrossingObject &bridge = model.crossings[0].underside;
	EXPECT_TRUE(hasVertexNear(bridge, 0.0, -5.0, 9.0));
	EXPECT_TRUE(hasVertexNear(bridge, 0.0, -7.0, 9.0));
	EXPECT_TRUE(hasVertexNear(bridge, 0.0, 5.0, 9.0));
	EXPECT_TRUE(hasVertexNear(bridge, 0.0, 7.0, 9.0));
	expectClosedPortals(model.crossings[0]);
}


TEST(TrackCrossingRenderedEndpointTest,
     PreservesWallWidthStepInsideFloorSpan)
{
	SyntheticCrossingTrack track(6);
	track.configureStraight(0, -30.0, 0.0, 30.0, 0.0, 10.0);
	track.configureStraight(1, 100.0, 100.0, 110.0, 100.0, 0.0);
	track.configureStraight(2, 100.0, 110.0, 110.0, 110.0, 0.0);
	track.configureStraight(3, 0.0, -30.0, 0.0, 0.0, 0.0);
	track.configureStraight(4, 0.0, 0.0, 0.0, 30.0, 0.0);
	track.configureStraight(5, 100.0, 120.0, 110.0, 120.0, 0.0);
	track.configureWall(3, TR_SIDE_RGT, 1.0, 1.0);
	track.configureWall(3, TR_SIDE_LFT, 1.0, 1.0);
	track.configureWall(4, TR_SIDE_RGT, 3.0, 1.0);
	track.configureWall(4, TR_SIDE_LFT, 3.0, 1.0);
	track.finish();
	TrackCrossingModel model = buildModel(&track);

	ASSERT_EQ(1u, model.crossings.size());
	const TrackCrossingGeometry &crossing = model.crossings[0];
	EXPECT_TRUE(hasVertexNear(crossing.floorRight, 5.0, 0.0, 0.0));
	EXPECT_TRUE(hasVertexNear(crossing.floorRight, 7.0, 0.0, 0.0));
	EXPECT_TRUE(hasVertexNear(crossing.floorLeft, -5.0, 0.0, 0.0));
	EXPECT_TRUE(hasVertexNear(crossing.floorLeft, -7.0, 0.0, 0.0));
	expectClosedPortals(crossing);
}


TEST(TrackCrossingGapTest, ZeroGapKeepsNamedWallsWithoutDegenerateFloors)
{
	SyntheticCrossingTrack track(4);
	configureStraightCrossing(&track);
	TrackCrossingModel model = buildModel(&track, 0.0);

	ASSERT_EQ(1u, model.crossings.size());
	const TrackCrossingGeometry &crossing = model.crossings[0];
	EXPECT_NEAR(0.0, crossing.measuredSocketGap[TR_SIDE_RGT], kEps);
	EXPECT_NEAR(0.0, crossing.measuredSocketGap[TR_SIDE_LFT], kEps);
	EXPECT_EQ("TRKFLOOR_R0", crossing.floorRight.name);
	EXPECT_EQ("TRKFLOOR_L0", crossing.floorLeft.name);
	EXPECT_TRUE(crossing.floorRight.triangles.empty());
	EXPECT_TRUE(crossing.floorLeft.triangles.empty());
	EXPECT_FALSE(crossing.socketRight.triangles.empty());
	EXPECT_FALSE(crossing.socketLeft.triangles.empty());
	EXPECT_TRUE(crossing.terrainMask.triangles.empty());
	EXPECT_LT(triangleNormal(crossing.socketRight, 0).x, 0.0f);
	EXPECT_GT(triangleNormal(crossing.socketLeft, 0).x, 0.0f);
	EXPECT_TRUE(hasVertexNear(crossing.bridgeRight, 10.0, -4.0, 10.0));
	EXPECT_TRUE(hasVertexNear(crossing.bridgeRight, -10.0, -4.0, 10.0));
}


TEST(TrackCrossingElevationTest, RejectsSameLevelIntersection)
{
	SyntheticCrossingTrack track(4);
	configureStraightCrossing(&track, 0.0, 0.0);
	TrackCrossingModel model = buildModel(&track);

	EXPECT_EQ(1, model.candidateCount);
	EXPECT_TRUE(model.crossings.empty());
}


TEST(TrackCrossingElevationTest, RejectsStructureWithoutLowerClearance)
{
	SyntheticCrossingTrack track(4);
	configureStraightCrossing(&track);
	TrackCrossingModel model = buildModel(&track, 0.5, 9.0);

	EXPECT_EQ(1, model.candidateCount);
	EXPECT_TRUE(model.crossings.empty());
}


TEST(TrackCrossingAdjacencyTest, IgnoresSegmentsAdjacentAcrossRingClosure)
{
	SyntheticCrossingTrack track(4);
	track.configureStraight(0, -30.0, 0.0, 30.0, 0.0, 10.0);
	track.configureStraight(1, 100.0, 100.0, 110.0, 100.0, 0.0);
	track.configureStraight(2, 100.0, 120.0, 110.0, 120.0, 0.0);
	track.configureStraight(3, 0.0, -30.0, 0.0, 30.0, 0.0);
	track.finish();
	TrackCrossingModel model = buildModel(&track);

	EXPECT_EQ(0, model.candidateCount);
	EXPECT_TRUE(model.crossings.empty());
}


TEST(TrackCrossingDeduplicationTest, MergesIntersectionAtSplitSegmentEndpoint)
{
	SyntheticCrossingTrack track(5);
	track.configureStraight(0, -30.0, 0.0, 0.0, 0.0, 10.0);
	track.configureStraight(1, 0.0, 0.0, 30.0, 0.0, 10.0);
	track.configureStraight(2, 100.0, 100.0, 110.0, 100.0, 0.0);
	track.configureStraight(3, 0.0, -30.0, 0.0, 30.0, 0.0);
	track.configureStraight(4, 100.0, 120.0, 110.0, 120.0, 0.0);
	track.finish();
	TrackCrossingModel model = buildModel(&track);

	EXPECT_EQ(1, model.candidateCount);
	EXPECT_EQ(1u, model.crossings.size());
}


TEST(TrackCrossingCurveTest, DetectsStraightCurveCrossing)
{
	SyntheticCrossingTrack track(4);
	track.configureStraight(0, -50.0, 0.0, 50.0, 0.0, 10.0);
	track.configureStraight(1, 100.0, 100.0, 110.0, 100.0, 0.0);
	track.configureLeftCurve(2, 0.0, 0.0, 30.0, kPi / 4.0,
	                         kPi / 2.0, 0.0);
	track.configureStraight(3, 100.0, 120.0, 110.0, 120.0, 0.0);
	track.finish();
	TrackCrossingModel model = buildModel(&track);

	ASSERT_EQ(1, model.candidateCount);
	ASSERT_EQ(1u, model.crossings.size());
	EXPECT_NEAR(30.0, model.crossings[0].crossingX, kEps);
	EXPECT_NEAR(0.0, model.crossings[0].crossingY, kEps);
	const TrackCrossingGeometry &crossing = model.crossings[0];
	ASSERT_GE(crossing.floorRight.vertices.size(), 2u);
	expectClosedPortals(crossing);
	ASSERT_GE(crossing.floorLeft.vertices.size(), 2u);
	double sampleAngleStep = 5.0 / 34.0;
	for (size_t index = 0; index < crossing.floorRight.vertices.size();
	        index += 2) {
		EXPECT_TRUE(matchesLeftCurveSample(crossing.floorRight.vertices[index],
		        34.0, kPi / 4.0, kPi / 2.0, sampleAngleStep));
	}
	for (size_t index = 0; index < crossing.floorLeft.vertices.size();
	        index += 2) {
		EXPECT_TRUE(matchesLeftCurveSample(crossing.floorLeft.vertices[index],
		        26.0, kPi / 4.0, kPi / 2.0, sampleAngleStep));
	}
}


TEST(TrackCrossingCurveTest, DetectsCurveCurveCrossing)
{
	SyntheticCrossingTrack track(4);
	double firstAngle = 5.0 * kPi / 6.0;
	double secondAngle = 7.0 * kPi / 6.0;
	track.configureLeftCurve(0, -10.0, 0.0, 20.0,
	                         firstAngle - 1.0, 2.0, 10.0);
	track.configureStraight(1, 100.0, 100.0, 110.0, 100.0, 0.0);
	track.configureLeftCurve(2, 10.0, 0.0, 20.0,
	                         secondAngle - 1.0, 2.0, 0.0);
	track.configureStraight(3, 100.0, 120.0, 110.0, 120.0, 0.0);
	track.finish();
	TrackCrossingModel model = buildModel(&track);

	ASSERT_EQ(1, model.candidateCount);
	ASSERT_EQ(1u, model.crossings.size());
	EXPECT_NEAR(0.0, model.crossings[0].crossingX, kEps);
	EXPECT_NEAR(sqrt(300.0), model.crossings[0].crossingY, kEps);
	expectClosedPortals(model.crossings[0]);
}


TEST(TrackCrossingMultipleTest, PreservesTwoIntersectionsOfSameBranches)
{
	SyntheticCrossingTrack track(4);
	track.configureStraight(0, -50.0, 0.0, 50.0, 0.0, 10.0);
	track.configureStraight(1, 100.0, 100.0, 110.0, 100.0, 0.0);
	track.configureLeftCurve(2, 0.0, 0.0, 20.0, 0.0,
	                         2.0 * kPi, 0.0);
	track.configureStraight(3, 100.0, 120.0, 110.0, 120.0, 0.0);
	track.finish();
	TrackCrossingModel firstModel = buildModel(&track);
	TrackCrossingModel secondModel = buildModel(&track);

	ASSERT_EQ(2, firstModel.candidateCount);
	ASSERT_EQ(2u, firstModel.crossings.size());
	ASSERT_EQ(firstModel.crossings.size(), secondModel.crossings.size());
	for (size_t index = 0; index < firstModel.crossings.size(); index++) {
		EXPECT_EQ(firstModel.crossings[index].underside.name,
		          secondModel.crossings[index].underside.name);
		EXPECT_NEAR(firstModel.crossings[index].crossingX,
		            secondModel.crossings[index].crossingX, kEps);
		EXPECT_NEAR(firstModel.crossings[index].crossingY,
		            secondModel.crossings[index].crossingY, kEps);
	}
}


class TrackCrossingTextureTest : public testing::Test
{
protected:
	void SetUp() override
	{
		handle = GfParmReadFile("", GFPARM_RMODE_CREAT | GFPARM_RMODE_PRIVATE);
		ASSERT_NE(nullptr, handle);
		defineSurface(TRK_VAL_BRIDGE_UNDERSIDE, "bridge-underside.png", 14.0, 7.0);
		defineSurface(TRK_VAL_BRIDGE_SIDE, "bridge-side.png", 14.0, 7.0);
		defineSurface(TRK_VAL_BRIDGE_SOCKET, "bridge-socket.png", 14.0, 7.0);
		defineSurface(TRK_VAL_BRIDGE_FLOOR, "bridge-floor.png", 4.0, 4.0);
	}

	void TearDown() override
	{
		if (handle != nullptr) {
			GfParmReleaseHandle(handle);
		}
	}

	void defineSurface(const char *name, const char *image, double u, double v,
	                   bool includeV = true, bool legacy = false)
	{
		std::string path = std::string(TRK_SECT_SURFACES) + "/";
		if (legacy) {
			path += std::string(TRK_LST_SURF) + "/";
		}
		path += name;
		ASSERT_EQ(0, GfParmSetStr(handle, path.c_str(), TRK_ATT_TEXTURE, image));
		ASSERT_EQ(0, GfParmSetNum(handle, path.c_str(), TRK_ATT_TEXSIZE, NULL, (tdble)u));
		if (includeV) {
			ASSERT_EQ(0, GfParmSetNum(handle, path.c_str(), TRK_ATT_TEXSIZE_V, NULL, (tdble)v));
		}
	}

	void selectSurface(const char *selector, const char *name)
	{
		ASSERT_EQ(0, GfParmSetStr(handle, TRK_SECT_TERRAIN, selector, name));
	}

	void expectUV(const TrackCrossingObject &object, double x, double y, double z,
	              double u, double v)
	{
		int index = findVertexNear(object, x, y, z);
		ASSERT_GE(index, 0) << object.name;
		EXPECT_NEAR(object.vertices[index].u, u, kEps) << object.name;
		EXPECT_NEAR(object.vertices[index].v, v, kEps) << object.name;
	}

	void expectProtectedAxes(const TrackCrossingGeometry &crossing)
	{
		for (const TrackCrossingObject *part : crossingParts(crossing)) {
			for (const TrackCrossingPoint &point : part->vertices) {
				EXPECT_TRUE(std::isfinite(point.u));
				EXPECT_TRUE(std::isfinite(point.v));
				if (part == &crossing.underside) {
					EXPECT_GE(point.u, -kEps);
					EXPECT_LE(point.u, 1.0 + kEps);
				} else if (part != &crossing.floorRight && part != &crossing.floorLeft) {
					EXPECT_GE(point.v, -kEps) << part->name;
					EXPECT_LE(point.v, 1.0 + kEps) << part->name;
				}
			}
		}
	}

	void *handle = nullptr;
};


TEST_F(TrackCrossingTextureTest, DefaultsFitWholeFamiliesAndAnchorFillersWithoutChangingGeometry)
{
	SyntheticCrossingTrack track(4);
	configureStraightCrossing(&track);
	TrackCrossingModel baseline = buildModel(&track);
	TrackCrossingModel model = buildModel(&track, 0.5, 1.0, 5.0, handle);
	ASSERT_EQ(1u, model.crossings.size());
	const TrackCrossingGeometry &crossing = model.crossings[0];
	EXPECT_EQ("bridge-underside.png", crossing.underside.texture);
	EXPECT_EQ("bridge-side.png", crossing.bridgeRight.texture);
	EXPECT_EQ("bridge-side.png", crossing.bridgeLeft.texture);
	EXPECT_EQ("bridge-socket.png", crossing.socketRight.texture);
	EXPECT_EQ("bridge-socket.png", crossing.socketLeft.texture);
	EXPECT_EQ("bridge-floor.png", crossing.floorRight.texture);
	EXPECT_EQ("bridge-floor.png", crossing.floorLeft.texture);
	// Width is 8 m: crop the 14 m U axis. Span repeats every 7 m along X.
	expectUV(crossing.underside, 5.0, -4.0, 9.0, 0.0, 11.5 / 7.0);
	expectUV(crossing.underside, 5.0, 4.0, 9.0, 8.0 / 14.0, 11.5 / 7.0);
	// Closures extend from Z=0 to Z=10, so both wall families scale to 20 x 10 m.
	expectUV(crossing.bridgeRight, 10.0, -4.0, 10.0, 0.5, 1.0);
	expectUV(crossing.bridgeRight, 6.5, -4.0, 0.0, 6.5 / 20.0, 0.0);
	expectUV(crossing.socketRight, 6.5, -4.0, 9.0, -4.0 / 20.0, 0.9);
	// Both floor strips use the same lower-track frame, including texture phase.
	expectUV(crossing.floorRight, 6.0, -5.0, 0.0, -5.0 / 4.0, -6.0 / 4.0);
	expectUV(crossing.floorLeft, -6.0, -5.0, 0.0, -5.0 / 4.0, 6.0 / 4.0);
	for (int upper = 0; upper < 2; upper++) {
		for (int lower = 0; lower < 2; lower++) {
			const TrackCrossingObject &filler = crossing.filler[upper][lower];
			EXPECT_EQ("bridge-socket.png", filler.texture);
			double x = lower == TR_SIDE_RGT ? 6.5 : -6.5;
			double y = upper == TR_SIDE_RGT ? -4.0 : 4.0;
			expectUV(filler, x, y, 0.0, y / 20.0, 0.0);
		}
	}
	ASSERT_EQ(1u, baseline.crossings.size());
	auto oldParts = crossingParts(baseline.crossings[0]);
	auto newParts = crossingParts(crossing);
	for (size_t part = 0; part < oldParts.size(); part++) {
		ASSERT_EQ(oldParts[part]->vertices.size(), newParts[part]->vertices.size());
		ASSERT_EQ(oldParts[part]->triangles.size(), newParts[part]->triangles.size());
		for (size_t index = 0; index < oldParts[part]->vertices.size(); index++) {
			const TrackCrossingPoint &a = oldParts[part]->vertices[index];
			const TrackCrossingPoint &b = newParts[part]->vertices[index];
			EXPECT_NEAR(a.x, b.x, kEps);
			EXPECT_NEAR(a.y, b.y, kEps);
			EXPECT_NEAR(a.z, b.z, kEps);
		}
		for (size_t index = 0; index < oldParts[part]->triangles.size(); index++) {
			for (int corner = 0; corner < 3; corner++) {
				EXPECT_EQ(oldParts[part]->triangles[index].vertex[corner],
				          newParts[part]->triangles[index].vertex[corner]);
			}
		}
	}
	expectProtectedAxes(crossing);
	expectClosedPortals(crossing);
}


TEST_F(TrackCrossingTextureTest, SmallHeightsCropRatherThanStretchAndTallHeightsGrowUniformly)
{
	for (double height : {3.0, 20.0}) {
		SCOPED_TRACE(height);
		SyntheticCrossingTrack track(4);
		configureStraightCrossing(&track, height);
		TrackCrossingModel model = buildModel(&track, 0.5, 1.0, 5.0, handle);
		ASSERT_EQ(1u, model.crossings.size());
		const TrackCrossingGeometry &crossing = model.crossings[0];
		double sizeV = (std::max)(7.0, height);
		double sizeU = 2.0 * sizeV;
		expectUV(crossing.bridgeRight, 10.0, -4.0, height, 10.0 / sizeU, 1.0);
		expectUV(crossing.bridgeRight, 6.5, -4.0, 0.0, 6.5 / sizeU, 1.0 - height / sizeV);
		expectProtectedAxes(crossing);
		expectClosedPortals(crossing);
	}
}


TEST_F(TrackCrossingTextureTest, WideUndersideEnlargesBothAxesWithoutRepeatingAcrossWidth)
{
	SyntheticCrossingTrack track(4);
	track.configureStraight(0, -100.0, 0.0, 100.0, 0.0, 10.0, 28.0);
	track.configureStraight(1, 150.0, 150.0, 160.0, 150.0, 0.0);
	track.configureStraight(2, 0.0, -100.0, 0.0, 100.0, 0.0, 30.0);
	track.configureStraight(3, 150.0, 170.0, 160.0, 170.0, 0.0);
	track.finish();
	TrackCrossingModel model = buildModel(&track, 0.5, 1.0, 5.0, handle);
	ASSERT_EQ(1u, model.crossings.size());
	const TrackCrossingGeometry &crossing = model.crossings[0];
	expectUV(crossing.underside, 0.0, -14.0, 9.0, 0.0, 15.5 / 14.0);
	expectUV(crossing.underside, 0.0, 14.0, 9.0, 1.0, 15.5 / 14.0);
	expectProtectedAxes(crossing);
	expectClosedPortals(crossing);
}


TEST_F(TrackCrossingTextureTest, SurfaceOverridesAndMissingVSizeUseTheConfiguredSurface)
{
	defineSurface("custom", "custom.png", 20.0, 0.0, false);
	defineSurface("custom-floor", "floor.png", 2.0, 8.0);
	selectSurface(TRK_ATT_CROSSING_UNDERSIDE_SURFACE, "custom");
	selectSurface(TRK_ATT_CROSSING_SIDE_SURFACE, "custom");
	selectSurface(TRK_ATT_CROSSING_SOCKET_SURFACE, "custom");
	selectSurface(TRK_ATT_CROSSING_FLOOR_SURFACE, "custom-floor");
	SyntheticCrossingTrack track(4);
	configureStraightCrossing(&track);
	TrackCrossingModel model = buildModel(&track, 0.5, 1.0, 5.0, handle);
	ASSERT_EQ(1u, model.crossings.size());
	const TrackCrossingGeometry &crossing = model.crossings[0];
	EXPECT_EQ("custom.png", crossing.underside.texture);
	EXPECT_EQ("custom.png", crossing.bridgeRight.texture);
	EXPECT_EQ("custom.png", crossing.socketLeft.texture);
	EXPECT_EQ("floor.png", crossing.floorRight.texture);
	expectUV(crossing.underside, 5.0, 4.0, 9.0, 8.0 / 20.0, 11.5 / 20.0);
	expectUV(crossing.bridgeRight, 6.5, -4.0, 0.0, 6.5 / 20.0, 0.5);
	expectUV(crossing.floorLeft, -6.0, -5.0, 0.0, -5.0 / 2.0, 6.0 / 8.0);
	expectProtectedAxes(crossing);
}


TEST_F(TrackCrossingTextureTest, MissingSurfacesAndInvalidSizesHaveFiniteLegacyFallbacks)
{
	SyntheticCrossingTrack track(4);
	configureStraightCrossing(&track);
	selectSurface(TRK_ATT_CROSSING_UNDERSIDE_SURFACE, "missing");
	selectSurface(TRK_ATT_CROSSING_FLOOR_SURFACE, "missing");
	TrackCrossingModel fallback = buildModel(&track, 0.5, 1.0, 5.0, handle);
	ASSERT_EQ(1u, fallback.crossings.size());
	EXPECT_EQ("tr-concrete_nmm.rgb", fallback.crossings[0].underside.texture);
	EXPECT_EQ("tr-asphalt.rgb", fallback.crossings[0].floorRight.texture);
	selectSurface(TRK_ATT_CROSSING_UNDERSIDE_SURFACE, "invalid");
	for (double size : {0.0, -1.0, std::numeric_limits<double>::quiet_NaN()}) {
		defineSurface("invalid", "invalid.png", size, size);
		TrackCrossingModel model = buildModel(&track, 0.5, 1.0, 5.0, handle);
		ASSERT_EQ(1u, model.crossings.size());
		expectUV(model.crossings[0].underside, 5.0, 4.0, 9.0, 8.0 / 15.0, 11.5 / 15.0);
		expectProtectedAxes(model.crossings[0]);
	}
}


TEST_F(TrackCrossingTextureTest, VersionThreeSurfaceLookupUsesListSection)
{
	defineSurface("legacy", "legacy.png", 22.0, 11.0, true, true);
	selectSurface(TRK_ATT_CROSSING_UNDERSIDE_SURFACE, "legacy");
	SyntheticCrossingTrack track(4);
	configureStraightCrossing(&track);
	track.getTrack()->version = 3;
	TrackCrossingModel model = buildModel(&track, 0.5, 1.0, 5.0, handle);
	ASSERT_EQ(1u, model.crossings.size());
	EXPECT_EQ("legacy.png", model.crossings[0].underside.texture);
	expectUV(model.crossings[0].underside, 5.0, 4.0, 9.0, 8.0 / 22.0, 11.5 / 11.0);
}
