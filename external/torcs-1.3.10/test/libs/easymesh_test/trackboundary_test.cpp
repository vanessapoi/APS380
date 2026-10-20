/***************************************************************************

    file                 : trackboundary_test.cpp
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

#include <gtest/gtest.h>

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include <limits>
#include <string>
#include <vector>

#include "trackboundary.h"

#ifdef WIN32
#undef malloc
#undef calloc
#undef realloc
#undef free
#undef strdup
#undef _strdup

void *
_tgf_win_realloc(void *memory, size_t size)
{
	return realloc(memory, size);
}
#endif

static const tdble kEps = 1e-5f;
static const tdble kTerrainGridStep = 7.0f;

struct TrackPositionCall {
	tTrackSeg *segment;
	tdble toStart;
	tdble toRight;
	int flag;
};

struct TrackWidthCall {
	tTrackSeg *segment;
	tdble toStart;
};

static std::vector<TrackPositionCall> TrackPositionCalls;
static std::vector<TrackPositionCall> TrackHeightCalls;
static std::vector<TrackWidthCall> TrackWidthCalls;


tdble
RtTrackGetWidth(tTrackSeg *segment, tdble toStart)
{
	TrackWidthCall call = {segment, toStart};
	TrackWidthCalls.push_back(call);
	return segment->startWidth + segment->Kyl * toStart;
}


void
RtTrackLocal2Global(tTrkLocPos *position, tdble *x, tdble *y, int flag)
{
	TrackPositionCall call = {
		position->seg, position->toStart, position->toRight, flag
	};
	TrackPositionCalls.push_back(call);
	*x = position->seg->id * 100.0f + position->toStart;
	*y = position->toRight;
}


tdble
RtTrackHeightL(tTrkLocPos *position)
{
	TrackPositionCall call = {
		position->seg, position->toStart, position->toRight, 0
	};
	TrackHeightCalls.push_back(call);
	return position->seg->id * 10.0f + position->toStart + position->toRight;
}


class TrackBoundaryTest : public ::testing::Test
{
protected:
	tMeshInput input;
	tTrack track;
	tTrackSeg mainSegments[3];
	tTrackSeg firstSideSegments[3];
	tTrackSeg outerSideSegments[3];

	void SetUp() override
	{
		memset(&input, 0, sizeof(input));
		memset(&track, 0, sizeof(track));
		memset(mainSegments, 0, sizeof(mainSegments));
		memset(firstSideSegments, 0, sizeof(firstSideSegments));
		memset(outerSideSegments, 0, sizeof(outerSideSegments));
		TrackPositionCalls.clear();
		TrackHeightCalls.clear();
		TrackWidthCalls.clear();
	}

	void TearDown() override
	{
		free(input.points);
	}

	void configureSegment(tTrackSeg *segment, int id, int type)
	{
		int vertexIndex;

		memset(segment, 0, sizeof(*segment));
		segment->id = id;
		segment->type = type;
		segment->type2 = TR_MAIN;
		segment->length = 25.0f;
		segment->radiusr = 20.0f;
		segment->radiusl = 10.0f;
		segment->startWidth = 8.0f;
		segment->Kyl = 0.25f;
		if (type == TR_LFT) {
			segment->angle[TR_ZS] = 0.2f;
			segment->angle[TR_ZE] = 0.45f;
		} else if (type == TR_RGT) {
			segment->angle[TR_ZS] = 1.0f;
			segment->angle[TR_ZE] = 0.5f;
		}
		for (vertexIndex = 0; vertexIndex < 4; vertexIndex++) {
			segment->vertex[vertexIndex].x =
			        id * 1000.0f + vertexIndex * 10.0f + 1.0f;
			segment->vertex[vertexIndex].y =
			        id * 1000.0f + vertexIndex * 10.0f + 2.0f;
			segment->vertex[vertexIndex].z =
			        id * 1000.0f + vertexIndex * 10.0f + 3.0f;
		}
	}

	void configureTrack(int segmentCount)
	{
		int segmentIndex;

		track.nseg = segmentCount;
		track.seg = &mainSegments[segmentCount - 1];
		for (segmentIndex = 0; segmentIndex < segmentCount; segmentIndex++) {
			mainSegments[segmentIndex].next =
			        &mainSegments[(segmentIndex + 1) % segmentCount];
			mainSegments[segmentIndex].prev =
			        &mainSegments[(segmentIndex + segmentCount - 1) % segmentCount];
		}
	}

	int sampleBoundary(int side, tdble samplingStep)
	{
		return sampleTrackBoundary(&track, side, samplingStep,
		                           kTerrainGridStep, false, &input, NULL, NULL);
	}

	static int startVertexIndex(int side)
	{
		return side == TR_SIDE_RGT ? TR_SR : TR_SL;
	}

	static int endVertexIndex(int side)
	{
		return side == TR_SIDE_RGT ? TR_ER : TR_EL;
	}
};

struct BoundarySegmentCase {
	int side;
	int segmentType;
};

class TrackBoundarySegmentTest :
	public TrackBoundaryTest,
	public ::testing::WithParamInterface<BoundarySegmentCase>
{
};


TEST_P(TrackBoundarySegmentTest, SamplesOutermostSegmentWithLegacyOffsets)
{
	const BoundarySegmentCase testCase = GetParam();
	tTrackSeg *mainSegment = &mainSegments[0];
	tTrackSeg *firstSide = &firstSideSegments[0];
	tTrackSeg *outerSide = &outerSideSegments[0];
	tdble samplingStep;
	tdble expectedOffsets[2];

	configureSegment(mainSegment, 1, testCase.segmentType);
	configureSegment(firstSide, 2, testCase.segmentType);
	configureSegment(outerSide, 3, testCase.segmentType);
	mainSegment->side[testCase.side] = firstSide;
	firstSide->side[testCase.side] = outerSide;
	configureTrack(1);

	if (testCase.segmentType == TR_STR) {
		samplingStep = 10.0f;
		expectedOffsets[0] = 10.0f;
		expectedOffsets[1] = 20.0f;
	} else if (testCase.segmentType == TR_LFT) {
		samplingStep = 2.0f;
		expectedOffsets[0] = 0.1f;
		expectedOffsets[1] = 0.2f;
		outerSide->radiusr = 100.0f;
	} else {
		samplingStep = 2.0f;
		expectedOffsets[0] = 0.2f;
		expectedOffsets[1] = 0.4f;
		outerSide->radiusl = 100.0f;
	}

	ASSERT_EQ(0, sampleBoundary(testCase.side, samplingStep));
	ASSERT_EQ(3, input.pointCount);
	ASSERT_EQ(2U, TrackPositionCalls.size());
	ASSERT_EQ(2U, TrackHeightCalls.size());
	EXPECT_EQ(outerSide, TrackPositionCalls[0].segment);
	EXPECT_EQ(outerSide, TrackPositionCalls[1].segment);
	EXPECT_EQ(TR_TORIGHT, TrackPositionCalls[0].flag);
	EXPECT_EQ(TR_TORIGHT, TrackPositionCalls[1].flag);

	for (int sampleIndex = 0; sampleIndex < 2; sampleIndex++) {
		const tdble expectedToRight = testCase.side == TR_SIDE_LFT
		        ? outerSide->startWidth + outerSide->Kyl * expectedOffsets[sampleIndex]
		        : 0.0f;
		EXPECT_NEAR(expectedOffsets[sampleIndex],
		            TrackPositionCalls[sampleIndex].toStart, kEps);
		EXPECT_NEAR(expectedToRight,
		            TrackPositionCalls[sampleIndex].toRight, kEps);
		EXPECT_NEAR(outerSide->id * 100.0f + expectedOffsets[sampleIndex],
		            input.points[sampleIndex + 1].x, kEps);
		EXPECT_NEAR(expectedToRight, input.points[sampleIndex + 1].y, kEps);
		EXPECT_NEAR(outerSide->id * 10.0f + expectedOffsets[sampleIndex] +
		            expectedToRight, input.points[sampleIndex + 1].z, kEps);
		EXPECT_NEAR(kTerrainGridStep, input.points[sampleIndex + 1].spacing,
		            kEps);
		EXPECT_EQ(1, input.points[sampleIndex + 1].marker);
	}

	const int startVertex = startVertexIndex(testCase.side);
	EXPECT_NEAR(outerSide->vertex[startVertex].x, input.points[0].x, kEps);
	EXPECT_NEAR(outerSide->vertex[startVertex].y, input.points[0].y, kEps);
	EXPECT_NEAR(outerSide->vertex[startVertex].z, input.points[0].z, kEps);
	EXPECT_NEAR(kTerrainGridStep, input.points[0].spacing, kEps);
	EXPECT_EQ(1, input.points[0].marker);
	EXPECT_EQ(testCase.side == TR_SIDE_LFT ? 2U : 0U,
	          TrackWidthCalls.size());
}


static std::string
boundarySegmentCaseName(
	const ::testing::TestParamInfo<BoundarySegmentCase>& parameter)
{
	std::string name = parameter.param.side == TR_SIDE_RGT ? "Right" : "Left";
	if (parameter.param.segmentType == TR_STR) {
		return name + "Straight";
	}
	if (parameter.param.segmentType == TR_LFT) {
		return name + "LeftCurve";
	}
	return name + "RightCurve";
}


INSTANTIATE_TEST_SUITE_P(
	AllSidesAndSegmentTypes,
	TrackBoundarySegmentTest,
	::testing::Values(
		BoundarySegmentCase{TR_SIDE_RGT, TR_STR},
		BoundarySegmentCase{TR_SIDE_LFT, TR_STR},
		BoundarySegmentCase{TR_SIDE_RGT, TR_LFT},
		BoundarySegmentCase{TR_SIDE_LFT, TR_LFT},
		BoundarySegmentCase{TR_SIDE_RGT, TR_RGT},
		BoundarySegmentCase{TR_SIDE_LFT, TR_RGT}),
	boundarySegmentCaseName);

class TrackBoundarySideTest :
	public TrackBoundaryTest,
	public ::testing::WithParamInterface<int>
{
};


TEST_P(TrackBoundarySideTest, UsesSingleAvailableSideSegment)
{
	const int side = GetParam();
	tTrackSeg *mainSegment = &mainSegments[0];
	tTrackSeg *firstSide = &firstSideSegments[0];

	configureSegment(mainSegment, 1, TR_STR);
	configureSegment(firstSide, 2, TR_STR);
	mainSegment->side[side] = firstSide;
	firstSide->length = 10.0f;
	configureTrack(1);

	ASSERT_EQ(0, sampleBoundary(side, 10.0f));
	ASSERT_EQ(1, input.pointCount);
	const int startVertex = startVertexIndex(side);
	EXPECT_NEAR(firstSide->vertex[startVertex].x, input.points[0].x, kEps);
	EXPECT_NEAR(firstSide->vertex[startVertex].y, input.points[0].y, kEps);
	EXPECT_NEAR(firstSide->vertex[startVertex].z, input.points[0].z, kEps);
	EXPECT_TRUE(TrackPositionCalls.empty());
}


TEST_P(TrackBoundarySideTest, PreservesPrefixAndAppendsOrderedSegmentCorners)
{
	const int side = GetParam();

	for (int segmentIndex = 0; segmentIndex < 3; segmentIndex++) {
		configureSegment(&mainSegments[segmentIndex], segmentIndex + 1, TR_STR);
		mainSegments[segmentIndex].length = 10.0f;
	}
	configureTrack(3);
	input.points = (tMeshNode *)calloc(1, sizeof(tMeshNode));
	ASSERT_NE(nullptr, input.points);
	input.pointCount = 1;
	input.pointCapacity = 1;
	input.points[0].x = -123.0;
	input.points[0].marker = 99;

	ASSERT_EQ(0, sampleBoundary(side, 10.0f));
	ASSERT_EQ(4, input.pointCount);
	EXPECT_GE(input.pointCapacity, input.pointCount);
	EXPECT_NEAR(-123.0, input.points[0].x, kEps);
	EXPECT_EQ(99, input.points[0].marker);
	EXPECT_TRUE(TrackPositionCalls.empty());

	const int startVertex = startVertexIndex(side);
	const int endVertex = endVertexIndex(side);
	EXPECT_NEAR(mainSegments[0].vertex[startVertex].x, input.points[1].x,
	            kEps);
	EXPECT_NEAR(mainSegments[0].vertex[endVertex].x, input.points[2].x,
	            kEps);
	EXPECT_NEAR(mainSegments[1].vertex[endVertex].x, input.points[3].x,
	            kEps);
	EXPECT_EQ(1, input.points[1].marker);
	EXPECT_EQ(1, input.points[2].marker);
	EXPECT_EQ(2, input.points[3].marker);
	EXPECT_NEAR(kTerrainGridStep, input.points[1].spacing, kEps);
	EXPECT_NEAR(kTerrainGridStep, input.points[2].spacing, kEps);
	EXPECT_NEAR(kTerrainGridStep, input.points[3].spacing, kEps);
}


TEST_P(TrackBoundarySideTest, ReportsDiscontinuousRenderedSegmentCorner)
{
	const int side = GetParam();
	const int startVertex = startVertexIndex(side);
	const int endVertex = endVertexIndex(side);
	tMeshNode closurePoint;
	std::vector<TrackBoundaryTransition> transitions;

	configureSegment(&mainSegments[0], 1, TR_STR);
	configureSegment(&mainSegments[1], 2, TR_STR);
	mainSegments[0].length = 10.0f;
	mainSegments[1].length = 10.0f;
	mainSegments[1].vertex[startVertex] =
	        mainSegments[0].vertex[endVertex];
	mainSegments[1].vertex[startVertex].y += 2.0f;
	configureTrack(2);

	ASSERT_EQ(0, sampleTrackBoundary(
	        &track, side, 10.0f, kTerrainGridStep, true, &input,
	        &closurePoint, &transitions));
	ASSERT_EQ(1U, transitions.size());
	EXPECT_EQ(1, transitions[0].pointIndex);
	EXPECT_NEAR(mainSegments[0].vertex[endVertex].x,
	            input.points[1].x, kEps);
	EXPECT_NEAR(mainSegments[0].vertex[endVertex].y,
	            input.points[1].y, kEps);
	EXPECT_NEAR(mainSegments[1].vertex[startVertex].x,
	            transitions[0].point.x, kEps);
	EXPECT_NEAR(mainSegments[1].vertex[startVertex].y,
	            transitions[0].point.y, kEps);
}


TEST_P(TrackBoundarySideTest, IgnoresSubMillimetreEndpointQuantization)
{
	const int side = GetParam();
	const int startVertex = startVertexIndex(side);
	const int endVertex = endVertexIndex(side);
	tMeshNode closurePoint;
	std::vector<TrackBoundaryTransition> transitions;

	configureSegment(&mainSegments[0], 1, TR_STR);
	configureSegment(&mainSegments[1], 2, TR_STR);
	mainSegments[0].length = 10.0f;
	mainSegments[1].length = 10.0f;
	mainSegments[1].vertex[startVertex] =
	        mainSegments[0].vertex[endVertex];
	mainSegments[1].vertex[startVertex].y += 0.0005f;
	configureTrack(2);

	ASSERT_EQ(0, sampleTrackBoundary(
	        &track, side, 10.0f, kTerrainGridStep, true, &input,
	        &closurePoint, &transitions));
	EXPECT_TRUE(transitions.empty());
}


static std::string
boundarySideName(const ::testing::TestParamInfo<int>& parameter)
{
	return parameter.param == TR_SIDE_RGT ? "Right" : "Left";
}


INSTANTIATE_TEST_SUITE_P(
	BothSides,
	TrackBoundarySideTest,
	::testing::Values(TR_SIDE_RGT, TR_SIDE_LFT),
	boundarySideName);


class TrackBoundaryWallTest :
	public TrackBoundaryTest,
	public ::testing::WithParamInterface<int>
{
protected:
	void configureWallTrack(int side, tTrackBarrier *barrier)
	{
		configureSegment(&mainSegments[0], 1, TR_STR);
		configureSegment(&firstSideSegments[0], 2, TR_STR);
		configureSegment(&outerSideSegments[0], 3, TR_STR);
		mainSegments[0].side[side] = &firstSideSegments[0];
		firstSideSegments[0].side[side] = &outerSideSegments[0];
		mainSegments[0].barrier[side] = barrier;
		configureTrack(1);
	}
};


TEST_P(TrackBoundaryWallTest, LegacyModeStopsAtSideEdge)
{
	const int side = GetParam();
	tTrackBarrier barrier;
	memset(&barrier, 0, sizeof(barrier));
	barrier.style = TR_WALL;
	barrier.width = 3.0f;
	configureWallTrack(side, &barrier);

	ASSERT_EQ(0, sampleBoundary(side, 10.0f));
	ASSERT_EQ(3, input.pointCount);
	for (int pointIndex = 0; pointIndex < input.pointCount; pointIndex++) {
		tdble toStart = pointIndex * 10.0f;
		tdble edgeToRight = side == TR_SIDE_LFT
		        ? outerSideSegments[0].startWidth +
		          outerSideSegments[0].Kyl * toStart : 0.0f;
		if (pointIndex == 0) {
			EXPECT_NEAR(outerSideSegments[0].vertex[
			        startVertexIndex(side)].y, input.points[pointIndex].y,
			        kEps);
		} else {
			EXPECT_NEAR(edgeToRight, input.points[pointIndex].y, kEps);
		}
	}
}


TEST_P(TrackBoundaryWallTest, IgnoresInfiniteWallWidth)
{
	const int side = GetParam();
	tTrackBarrier barrier;
	tMeshNode closurePoint;
	memset(&barrier, 0, sizeof(barrier));
	barrier.style = TR_WALL;
	barrier.width = std::numeric_limits<tdble>::infinity();
	configureWallTrack(side, &barrier);

	ASSERT_EQ(0, sampleTrackBoundary(&track, side, 10.0f,
	                                 kTerrainGridStep, true, &input,
	                                 &closurePoint, NULL));
	ASSERT_EQ(3, input.pointCount);
	EXPECT_NEAR(outerSideSegments[0].vertex[startVertexIndex(side)].x,
	            input.points[0].x, kEps);
	EXPECT_NEAR(outerSideSegments[0].vertex[startVertexIndex(side)].y,
	            input.points[0].y, kEps);
	EXPECT_NEAR(side == TR_SIDE_LFT ? 10.5f : 0.0f,
	            input.points[1].y, kEps);
	EXPECT_NEAR(outerSideSegments[0].vertex[endVertexIndex(side)].x,
	            closurePoint.x, kEps);
	EXPECT_NEAR(outerSideSegments[0].vertex[endVertexIndex(side)].y,
	            closurePoint.y, kEps);
}


TEST_P(TrackBoundaryWallTest, SamplesRenderedWallExteriorAndClosure)
{
	const int side = GetParam();
	tTrackSeg *outerSide = &outerSideSegments[0];
	tTrackBarrier barrier;
	tMeshNode closurePoint;
	memset(&barrier, 0, sizeof(barrier));
	barrier.style = TR_WALL;
	barrier.width = 3.0f;

	configureWallTrack(side, &barrier);

	ASSERT_EQ(0, sampleTrackBoundary(&track, side, 10.0f,
	                                 kTerrainGridStep, true, &input,
	                                 &closurePoint, NULL));
	ASSERT_EQ(3, input.pointCount);
	for (int pointIndex = 0; pointIndex < input.pointCount; pointIndex++) {
		tdble toStart = pointIndex * 10.0f;
		tdble edgeToRight = side == TR_SIDE_LFT
		        ? outerSide->startWidth + outerSide->Kyl * toStart : 0.0f;
		tdble expectedToRight = side == TR_SIDE_RGT
		        ? edgeToRight - barrier.width : edgeToRight + barrier.width;
		EXPECT_NEAR(outerSide->id * 100.0f + toStart,
		            input.points[pointIndex].x, kEps);
		EXPECT_NEAR(expectedToRight, input.points[pointIndex].y, kEps);
		if (pointIndex == 0) {
			int startVertex = startVertexIndex(side);
			EXPECT_NEAR(outerSide->vertex[startVertex].z,
			            input.points[pointIndex].z, kEps);
		} else {
			EXPECT_NEAR(outerSide->id * 10.0f + toStart + edgeToRight,
			            input.points[pointIndex].z, kEps);
		}
	}

	tdble closureEdge = side == TR_SIDE_LFT
	        ? outerSide->startWidth + outerSide->Kyl * outerSide->length : 0.0f;
	tdble closureToRight = side == TR_SIDE_RGT
	        ? closureEdge - barrier.width : closureEdge + barrier.width;
	EXPECT_NEAR(outerSide->id * 100.0f + outerSide->length,
	            closurePoint.x, kEps);
	EXPECT_NEAR(closureToRight, closurePoint.y, kEps);
	EXPECT_NEAR(outerSide->vertex[endVertexIndex(side)].z,
	            closurePoint.z, kEps);
	EXPECT_NEAR(kTerrainGridStep, closurePoint.spacing, kEps);
	EXPECT_EQ(1, closurePoint.marker);
}


INSTANTIATE_TEST_SUITE_P(
	BothSides,
	TrackBoundaryWallTest,
	::testing::Values(TR_SIDE_RGT, TR_SIDE_LFT),
	boundarySideName);


struct WallTransitionCase
{
	int side;
	tdble firstWidth;
	tdble secondWidth;
	const char *name;
};


class TrackBoundaryTransitionTest :
	public TrackBoundaryTest,
	public ::testing::WithParamInterface<WallTransitionCase>
{
protected:
	void configureConnectedStraight(int index, int id)
	{
		tTrackSeg *segment = &mainSegments[index];
		double startX = id * 100.0;
		double endX = startX + 100.0;
		configureSegment(segment, id, TR_STR);
		segment->length = 100.0f;
		segment->startWidth = 8.0f;
		segment->Kyl = 0.0f;
		segment->vertex[TR_SR].x = (tdble)startX;
		segment->vertex[TR_SR].y = 0.0f;
		segment->vertex[TR_ER].x = (tdble)endX;
		segment->vertex[TR_ER].y = 0.0f;
		segment->vertex[TR_SL].x = (tdble)startX;
		segment->vertex[TR_SL].y = 8.0f;
		segment->vertex[TR_EL].x = (tdble)endX;
		segment->vertex[TR_EL].y = 8.0f;
	}
};


TEST_P(TrackBoundaryTransitionTest, ReportsSideLocalRenderedCorner)
{
	const WallTransitionCase testCase = GetParam();
	tTrackBarrier barriers[2];
	tMeshNode closurePoint;
	std::vector<TrackBoundaryTransition> transitions;
	memset(barriers, 0, sizeof(barriers));
	for (int segmentIndex = 0; segmentIndex < 2; segmentIndex++) {
		configureConnectedStraight(segmentIndex, segmentIndex + 1);
		barriers[segmentIndex].style = TR_WALL;
		mainSegments[segmentIndex].barrier[testCase.side] =
		        &barriers[segmentIndex];
	}
	barriers[0].width = testCase.firstWidth;
	barriers[1].width = testCase.secondWidth;
	configureTrack(2);

	ASSERT_EQ(0, sampleTrackBoundary(
	        &track, testCase.side, 100.0f, kTerrainGridStep, true,
	        &input, &closurePoint, &transitions));
	ASSERT_EQ(2, input.pointCount);
	ASSERT_EQ(1U, transitions.size());
	EXPECT_EQ(1, transitions[0].pointIndex);
	double edgeY = testCase.side == TR_SIDE_RGT ? 0.0 : 8.0;
	double previousExteriorY = testCase.side == TR_SIDE_RGT
	        ? edgeY - testCase.firstWidth : edgeY + testCase.firstWidth;
	double currentExteriorY = testCase.side == TR_SIDE_RGT
	        ? edgeY - testCase.secondWidth : edgeY + testCase.secondWidth;
	EXPECT_NEAR(200.0, input.points[1].x, kEps);
	EXPECT_NEAR(previousExteriorY, input.points[1].y, kEps);
	EXPECT_NEAR(200.0, transitions[0].point.x, kEps);
	EXPECT_NEAR(currentExteriorY, transitions[0].point.y, kEps);
	EXPECT_NEAR(mainSegments[1].vertex[startVertexIndex(testCase.side)].z,
	            transitions[0].point.z, kEps);
	EXPECT_NEAR(kTerrainGridStep, transitions[0].point.spacing, kEps);
	EXPECT_EQ(2, transitions[0].point.marker);
}


static std::string
wallTransitionCaseName(
	const ::testing::TestParamInfo<WallTransitionCase>& parameter)
{
	return parameter.param.name;
}


INSTANTIATE_TEST_SUITE_P(
	WallWidthChanges,
	TrackBoundaryTransitionTest,
	::testing::Values(
		WallTransitionCase{TR_SIDE_RGT, 3.0f, 0.3f, "RightContract"},
		WallTransitionCase{TR_SIDE_LFT, 3.0f, 0.3f, "LeftContract"},
		WallTransitionCase{TR_SIDE_RGT, 0.3f, 3.0f, "RightExpand"},
		WallTransitionCase{TR_SIDE_LFT, 0.3f, 3.0f, "LeftExpand"},
		WallTransitionCase{TR_SIDE_RGT, 3.0f, 0.0f, "RightToZero"},
		WallTransitionCase{TR_SIDE_LFT, 3.0f, 0.0f, "LeftToZero"}),
	wallTransitionCaseName);


class TrackBoundarySpacingTest : public ::testing::Test
{
protected:
	tMeshNode points[8];

	void SetUp() override
	{
		memset(points, 0, sizeof(points));
	}

	void setPoint(int index, double x, double y, double spacing)
	{
		points[index].x = x;
		points[index].y = y;
		points[index].spacing = spacing;
	}
};


TEST_F(TrackBoundarySpacingTest, OnBoundaryInterpolatesEndpointSpacing)
{
	setPoint(0, 0.0, 0.0, 10.0);
	setPoint(1, 10.0, 0.0, 20.0);

	EXPECT_NEAR(getTrackBoundaryTargetSpacing(
	                    points, 0, 2, 2.5, 0.0, 50.0, 10.0, 20.0),
	            12.5, kEps);
}


TEST_F(TrackBoundarySpacingTest, HalfTransitionBlendsToMaximumSpacing)
{
	setPoint(0, 0.0, 0.0, 10.0);
	setPoint(1, 10.0, 0.0, 10.0);

	EXPECT_NEAR(getTrackBoundaryTargetSpacing(
	                    points, 0, 2, 5.0, 5.0, 30.0, 10.0, 10.0),
	            20.0, kEps);
}


TEST_F(TrackBoundarySpacingTest, BeyondTransitionUsesMaximumSpacing)
{
	setPoint(0, 0.0, 0.0, 10.0);
	setPoint(1, 10.0, 0.0, 10.0);

	EXPECT_NEAR(getTrackBoundaryTargetSpacing(
	                    points, 0, 2, 5.0, 20.0, 30.0, 10.0, 10.0),
	            30.0, kEps);
}


TEST_F(TrackBoundarySpacingTest, NarrowRegionUsesNearestBoundary)
{
	setPoint(0, 0.0, 0.0, 10.0);
	setPoint(1, 10.0, 0.0, 10.0);
	setPoint(2, 10.0, 100.0, 10.0);
	setPoint(3, 0.0, 100.0, 10.0);

	EXPECT_NEAR(getTrackBoundaryTargetSpacing(
	                    points, 0, 4, 5.0, 50.0, 50.0, 10.0, 20.0),
	            20.0, kEps);
}


TEST_F(TrackBoundarySpacingTest, UsesOnlySelectedTrackBoundaryRange)
{
	setPoint(0, 0.0, 15.0, 100.0);
	setPoint(1, 30.0, 15.0, 100.0);
	setPoint(2, 10.0, 10.0, 10.0);
	setPoint(3, 20.0, 10.0, 10.0);
	setPoint(4, 20.0, 20.0, 10.0);
	setPoint(5, 10.0, 20.0, 10.0);

	EXPECT_NEAR(getTrackBoundaryTargetSpacing(
	                    points, 2, 4, 15.0, 15.0, 50.0, 10.0, 20.0),
	            20.0, kEps);
}


TEST_F(TrackBoundarySpacingTest, LowerMaximumDoesNotReduceBoundarySpacing)
{
	setPoint(0, 0.0, 0.0, 20.0);
	setPoint(1, 10.0, 0.0, 20.0);

	EXPECT_NEAR(getTrackBoundaryTargetSpacing(
	                    points, 0, 2, 5.0, 5.0, 10.0, 10.0, 10.0),
	            20.0, kEps);
}


TEST_F(TrackBoundarySpacingTest, ShortChordUsesNearTrackSpacingFloor)
{
	setPoint(0, 0.0, 0.0, 5.0);
	setPoint(1, 5.0, 0.0, 5.0);

	EXPECT_NEAR(getTrackBoundaryTargetSpacing(
	                    points, 0, 2, 2.5, 0.0, 50.0, 20.0, 200.0),
	            20.0, kEps);
}


TEST_F(TrackBoundarySpacingTest, FloorTransitionsToMaximumSpacing)
{
	setPoint(0, 0.0, 0.0, 5.0);
	setPoint(1, 5.0, 0.0, 5.0);

	EXPECT_NEAR(getTrackBoundaryTargetSpacing(
	                    points, 0, 2, 2.5, 100.0, 50.0, 20.0, 200.0),
	            35.0, kEps);
}
