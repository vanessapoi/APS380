/***************************************************************************

    file                 : rttrack_global2local_test.cpp
    created              : Sun Jun 07 10:30:00 CET 2026
    copyright            : (C) 2026-2026 by Bernhard Wymann
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
#include <cmath>
#include <string>

#include <track.h>
#include <robottools.h>


static const float kEps = 1e-5f;


struct GlobalPoint {
	tdble x;
	tdble y;
};


static tTrackSeg MakeStraightSegment(tdble length, tdble width, tdble angle, tdble startX, tdble startY)
{
	tTrackSeg seg{};
	seg.type = TR_STR;
	seg.type2 = TR_MAIN;
	seg.length = length;
	seg.width = width;
	seg.startWidth = width;
	seg.endWidth = width;
	seg.angle[TR_ZS] = angle;
	seg.vertex[TR_SR].x = startX;
	seg.vertex[TR_SR].y = startY;
	return seg;
}


static tTrackSeg MakeCurveSegment(int type, tdble arc, tdble width, tdble radiusr,
	tdble centerX, tdble centerY, tdble centerAngle)
{
	tTrackSeg seg{};
	seg.type = type;
	seg.type2 = TR_MAIN;
	seg.arc = arc;
	seg.length = arc * (radiusr + width / 2.0f);
	seg.width = width;
	seg.startWidth = width;
	seg.endWidth = width;
	seg.radiusr = radiusr;
	seg.radiusl = radiusr + width;
	seg.radius = radiusr + width / 2.0f;
	seg.center.x = centerX;
	seg.center.y = centerY;
	seg.angle[TR_CS] = centerAngle;
	return seg;
}


static tTrackSeg MakeSideSegment(int type2, tdble width)
{
	tTrackSeg seg{};
	seg.type = TR_STR;
	seg.type2 = type2;
	seg.width = width;
	seg.startWidth = width;
	seg.endWidth = width;
	return seg;
}


static tTrackSeg MakeStraightSegmentForPoint(const GlobalPoint& point, tdble toStart, tdble toRight)
{
	return MakeStraightSegment(10.0f, 8.0f, 0.0f, point.x - toStart, point.y - toRight);
}


static GlobalPoint StraightPoint(const tTrackSeg& seg, tdble toStart, tdble toRight)
{
	tdble cosine = static_cast<tdble>(std::cos(seg.angle[TR_ZS]));
	tdble sine = static_cast<tdble>(std::sin(seg.angle[TR_ZS]));
	return GlobalPoint{
		seg.vertex[TR_SR].x + toStart * cosine - toRight * sine,
		seg.vertex[TR_SR].y + toStart * sine + toRight * cosine
	};
}


static GlobalPoint CurvePoint(const tTrackSeg& seg, tdble toStart, tdble toRight)
{
	tdble radius = (seg.type == TR_LFT) ? seg.radiusr - toRight : seg.radiusr + toRight;
	tdble angle = (seg.type == TR_LFT) ? seg.angle[TR_CS] + toStart : seg.angle[TR_CS] - toStart;
	return GlobalPoint{
		seg.center.x + radius * static_cast<tdble>(std::cos(angle)),
		seg.center.y + radius * static_cast<tdble>(std::sin(angle))
	};
}


static GlobalPoint SegmentPoint(const tTrackSeg& seg, tdble toStart, tdble toRight)
{
	if (seg.type == TR_STR) {
		return StraightPoint(seg, toStart, toRight);
	}

	return CurvePoint(seg, toStart, toRight);
}


static void ExpectLocalPosition(const tTrkLocPos& pos, const tTrackSeg *seg, int type,
	tdble toStart, tdble toRight, tdble width)
{
	EXPECT_EQ(seg, pos.seg);
	EXPECT_EQ(type, pos.type);
	EXPECT_NEAR(pos.toStart, toStart, kEps);
	EXPECT_NEAR(pos.toRight, toRight, kEps);
	EXPECT_NEAR(pos.toMiddle, toRight - width / 2.0f, kEps);
	EXPECT_NEAR(pos.toLeft, width - toRight, kEps);
}


TEST(RtTrackGlobal2LocalDoubleTest, PreservesSubFloatOffsetAtLargeCoordinates)
{
	tTrackSeg seg = MakeStraightSegment(30.0f, 10.0f, 0.0f, 15000.0f, 15000.0f);
	seg.next = &seg;
	seg.prev = &seg;
	tTrkLocPos pos{};

	RtTrackGlobal2LocalD(&seg, 15012.5, 15003.2503, &pos, TR_LPOS_MAIN);

	ExpectLocalPosition(pos, &seg, TR_LPOS_MAIN, 12.5f, 3.2503f, seg.width);
}


TEST(RtTrackGlobal2LocalDoubleTest, PreservesSubFloatOffsetOnWrappedCurve)
{
	tTrackSeg seg = MakeCurveSegment(TR_LFT, 1.2f, 10.0f, 30.0f, 15000.0f, 15000.0f, 3.0f);
	seg.next = &seg;
	seg.prev = &seg;
	const double toStart = 0.8;
	const double toRight = 2.2503;
	const double radius = (double)seg.radiusr - toRight;
	const double angle = (double)seg.angle[TR_CS] + toStart;
	tTrkLocPos pos{};

	RtTrackGlobal2LocalD(&seg,
		(double)seg.center.x + radius * std::cos(angle),
		(double)seg.center.y + radius * std::sin(angle),
		&pos, TR_LPOS_MAIN);

	ExpectLocalPosition(pos, &seg, TR_LPOS_MAIN, (tdble)toStart, (tdble)toRight, seg.width);
}


struct MainSegmentCase {
	int segType;
	tdble toStart;
	tdble toRight;
	tdble angle;
	const char *name;
};


static std::string MainSegmentCaseName(const ::testing::TestParamInfo<MainSegmentCase>& info)
{
	return info.param.name;
}


class RtTrackGlobal2LocalMainSegmentTest : public ::testing::TestWithParam<MainSegmentCase> {
};


TEST_P(RtTrackGlobal2LocalMainSegmentTest, ConvertsGlobalPointToMainSegmentLocalPosition)
{
	MainSegmentCase c = GetParam();
	tTrackSeg seg = (c.segType == TR_STR)
		? MakeStraightSegment(30.0f, 10.0f, c.angle, 12.0f, -4.0f)
		: MakeCurveSegment(c.segType, 1.2f, 10.0f, 30.0f, 5.0f, -6.0f, c.angle);
	GlobalPoint point = SegmentPoint(seg, c.toStart, c.toRight);

	tTrkLocPos pos{};
	RtTrackGlobal2Local(&seg, point.x, point.y, &pos, TR_LPOS_MAIN);

	ExpectLocalPosition(pos, &seg, TR_LPOS_MAIN, c.toStart, c.toRight, seg.width);
}


INSTANTIATE_TEST_SUITE_P(
	BaseGeometry,
	RtTrackGlobal2LocalMainSegmentTest,
	::testing::Values(
		MainSegmentCase{ TR_STR, 12.5f, 3.25f, 0.35f, "StraightInside" },
		MainSegmentCase{ TR_STR, 6.0f, -2.0f, 0.35f, "StraightNegativeToRight" },
		MainSegmentCase{ TR_LFT, 0.35f, 2.25f, 0.4f, "LeftCurveInside" },
		MainSegmentCase{ TR_LFT, 0.75f, -1.5f, 0.4f, "LeftCurveNegativeToRight" },
		MainSegmentCase{ TR_LFT, 0.8f, 2.25f, 3.0f, "LeftCurveAngleWrap" },
		MainSegmentCase{ TR_RGT, 0.35f, 2.25f, 0.4f, "RightCurveInside" },
		MainSegmentCase{ TR_RGT, 0.75f, -1.5f, 0.4f, "RightCurveNegativeToRight" },
		MainSegmentCase{ TR_RGT, 0.8f, 2.25f, -3.0f, "RightCurveAngleWrap" }
	),
	MainSegmentCaseName);


struct BoundaryCase {
	int segType;
	tdble toStart;
	const char *name;
};


static std::string BoundaryCaseName(const ::testing::TestParamInfo<BoundaryCase>& info)
{
	return info.param.name;
}


class RtTrackGlobal2LocalBoundaryTest : public ::testing::TestWithParam<BoundaryCase> {
};


TEST_P(RtTrackGlobal2LocalBoundaryTest, KeepsExactSegmentBoundaryOnCurrentSegment)
{
	BoundaryCase c = GetParam();
	tTrackSeg seg = (c.segType == TR_STR)
		? MakeStraightSegment(30.0f, 10.0f, 0.0f, 20.0f, -3.0f)
		: MakeCurveSegment(c.segType, 1.0f, 10.0f, 30.0f, 0.0f, 0.0f, 0.0f);
	GlobalPoint point = SegmentPoint(seg, c.toStart, 2.5f);
	tTrackSeg prev = MakeStraightSegmentForPoint(point, 5.0f, 2.0f);
	tTrackSeg next = MakeStraightSegmentForPoint(point, 5.0f, 2.0f);
	seg.prev = &prev;
	seg.next = &next;

	tTrkLocPos pos{};
	RtTrackGlobal2Local(&seg, point.x, point.y, &pos, TR_LPOS_MAIN);

	ExpectLocalPosition(pos, &seg, TR_LPOS_MAIN, c.toStart, 2.5f, seg.width);
}


INSTANTIATE_TEST_SUITE_P(
	ExactBoundaries,
	RtTrackGlobal2LocalBoundaryTest,
	::testing::Values(
		BoundaryCase{ TR_STR, 0.0f, "StraightStart" },
		BoundaryCase{ TR_STR, 30.0f, "StraightEnd" },
		BoundaryCase{ TR_LFT, 0.0f, "LeftCurveStart" },
		BoundaryCase{ TR_LFT, 1.0f, "LeftCurveEnd" },
		BoundaryCase{ TR_RGT, 0.0f, "RightCurveStart" },
		BoundaryCase{ TR_RGT, 1.0f, "RightCurveEnd" }
	),
	BoundaryCaseName);


struct SegmentSearchCase {
	int segType;
	bool moveToPrev;
	const char *name;
};


static std::string SegmentSearchCaseName(const ::testing::TestParamInfo<SegmentSearchCase>& info)
{
	return info.param.name;
}


class RtTrackGlobal2LocalSegmentSearchTest : public ::testing::TestWithParam<SegmentSearchCase> {
};


TEST_P(RtTrackGlobal2LocalSegmentSearchTest, SearchesPreviousOrNextSegmentWhenPointIsOutsideCurrentSegment)
{
	SegmentSearchCase c = GetParam();
	tTrackSeg current = (c.segType == TR_STR)
		? MakeStraightSegment(10.0f, 8.0f, 0.2f, 20.0f, -3.0f)
		: MakeCurveSegment(c.segType, 1.0f, 8.0f, 20.0f, 0.0f, 0.0f, 0.3f);
	tdble outsideToStart = c.moveToPrev ? -0.25f : ((c.segType == TR_STR) ? 10.25f : 1.25f);
	GlobalPoint point = SegmentPoint(current, outsideToStart, 1.5f);
	tTrackSeg target = MakeStraightSegmentForPoint(point, 5.0f, 2.0f);

	if (c.moveToPrev) {
		current.prev = &target;
	} else {
		current.next = &target;
	}

	tTrkLocPos pos{};
	RtTrackGlobal2Local(&current, point.x, point.y, &pos, TR_LPOS_MAIN);

	ExpectLocalPosition(pos, &target, TR_LPOS_MAIN, 5.0f, 2.0f, target.width);
}


INSTANTIATE_TEST_SUITE_P(
	SearchDirections,
	RtTrackGlobal2LocalSegmentSearchTest,
	::testing::Values(
		SegmentSearchCase{ TR_STR, true, "StraightToPrevious" },
		SegmentSearchCase{ TR_STR, false, "StraightToNext" },
		SegmentSearchCase{ TR_LFT, true, "LeftCurveToPrevious" },
		SegmentSearchCase{ TR_LFT, false, "LeftCurveToNext" },
		SegmentSearchCase{ TR_RGT, true, "RightCurveToPrevious" },
		SegmentSearchCase{ TR_RGT, false, "RightCurveToNext" }
	),
	SegmentSearchCaseName);


TEST(RtTrackGlobal2LocalPositionTypeTest, TrackPositionAccumulatesWidthsOnBothSides)
{
	tTrackSeg main = MakeStraightSegment(30.0f, 10.0f, 0.0f, 0.0f, 0.0f);
	tTrackSeg rightSide = MakeSideSegment(TR_RSIDE, 3.0f);
	tTrackSeg rightBorder = MakeSideSegment(TR_RBORDER, 2.0f);
	tTrackSeg leftSide = MakeSideSegment(TR_LSIDE, 4.0f);
	main.side[TR_SIDE_RGT] = &rightSide;
	rightSide.side[TR_SIDE_RGT] = &rightBorder;
	main.side[TR_SIDE_LFT] = &leftSide;
	GlobalPoint point = StraightPoint(main, 7.0f, 2.0f);

	tTrkLocPos pos{};
	RtTrackGlobal2Local(&main, point.x, point.y, &pos, TR_LPOS_TRACK);

	EXPECT_EQ(&main, pos.seg);
	EXPECT_EQ(TR_LPOS_TRACK, pos.type);
	EXPECT_NEAR(pos.toStart, 7.0f, kEps);
	EXPECT_NEAR(pos.toRight, 7.0f, kEps);
	EXPECT_NEAR(pos.toMiddle, -3.0f, kEps);
	EXPECT_NEAR(pos.toLeft, 12.0f, kEps);
}


TEST(RtTrackGlobal2LocalPositionTypeTest, SegmentPositionInsideMainTrackStaysOnMainSegment)
{
	tTrackSeg main = MakeStraightSegment(30.0f, 10.0f, 0.0f, 0.0f, 0.0f);
	tTrackSeg rightSide = MakeSideSegment(TR_RSIDE, 4.0f);
	tTrackSeg leftSide = MakeSideSegment(TR_LSIDE, 5.0f);
	main.side[TR_SIDE_RGT] = &rightSide;
	main.side[TR_SIDE_LFT] = &leftSide;
	GlobalPoint point = StraightPoint(main, 7.0f, 5.0f);

	tTrkLocPos pos{};
	RtTrackGlobal2Local(&main, point.x, point.y, &pos, TR_LPOS_SEGMENT);

	ExpectLocalPosition(pos, &main, TR_LPOS_SEGMENT, 7.0f, 5.0f, main.width);
}


TEST(RtTrackGlobal2LocalPositionTypeTest, SegmentPositionTraversesToRightSideSegment)
{
	tTrackSeg main = MakeStraightSegment(30.0f, 10.0f, 0.0f, 0.0f, 0.0f);
	tTrackSeg rightSide = MakeSideSegment(TR_RSIDE, 4.0f);
	main.side[TR_SIDE_RGT] = &rightSide;
	GlobalPoint point = StraightPoint(main, 7.0f, -2.0f);

	tTrkLocPos pos{};
	RtTrackGlobal2Local(&main, point.x, point.y, &pos, TR_LPOS_SEGMENT);

	ExpectLocalPosition(pos, &rightSide, TR_LPOS_SEGMENT, 7.0f, 2.0f, rightSide.width);
}


TEST(RtTrackGlobal2LocalPositionTypeTest, SegmentPositionTraversesMultipleRightSideSegments)
{
	tTrackSeg main = MakeStraightSegment(30.0f, 10.0f, 0.0f, 0.0f, 0.0f);
	tTrackSeg rightSide = MakeSideSegment(TR_RSIDE, 4.0f);
	tTrackSeg rightBorder = MakeSideSegment(TR_RBORDER, 3.0f);
	main.side[TR_SIDE_RGT] = &rightSide;
	rightSide.side[TR_SIDE_RGT] = &rightBorder;
	GlobalPoint point = StraightPoint(main, 7.0f, -6.0f);

	tTrkLocPos pos{};
	RtTrackGlobal2Local(&main, point.x, point.y, &pos, TR_LPOS_SEGMENT);

	ExpectLocalPosition(pos, &rightBorder, TR_LPOS_SEGMENT, 7.0f, 1.0f, rightBorder.width);
}


TEST(RtTrackGlobal2LocalPositionTypeTest, SegmentPositionTraversesToLeftSideSegment)
{
	tTrackSeg main = MakeStraightSegment(30.0f, 10.0f, 0.0f, 0.0f, 0.0f);
	tTrackSeg leftSide = MakeSideSegment(TR_LSIDE, 5.0f);
	main.side[TR_SIDE_LFT] = &leftSide;
	GlobalPoint point = StraightPoint(main, 7.0f, 13.0f);

	tTrkLocPos pos{};
	RtTrackGlobal2Local(&main, point.x, point.y, &pos, TR_LPOS_SEGMENT);

	ExpectLocalPosition(pos, &leftSide, TR_LPOS_SEGMENT, 7.0f, 3.0f, leftSide.width);
}


TEST(RtTrackGlobal2LocalPositionTypeTest, SegmentPositionTraversesMultipleLeftSideSegments)
{
	tTrackSeg main = MakeStraightSegment(30.0f, 10.0f, 0.0f, 0.0f, 0.0f);
	tTrackSeg leftSide = MakeSideSegment(TR_LSIDE, 5.0f);
	tTrackSeg leftBorder = MakeSideSegment(TR_LBORDER, 4.0f);
	main.side[TR_SIDE_LFT] = &leftSide;
	leftSide.side[TR_SIDE_LFT] = &leftBorder;
	GlobalPoint point = StraightPoint(main, 7.0f, 16.0f);

	tTrkLocPos pos{};
	RtTrackGlobal2Local(&main, point.x, point.y, &pos, TR_LPOS_SEGMENT);

	ExpectLocalPosition(pos, &leftBorder, TR_LPOS_SEGMENT, 7.0f, 1.0f, leftBorder.width);
}
