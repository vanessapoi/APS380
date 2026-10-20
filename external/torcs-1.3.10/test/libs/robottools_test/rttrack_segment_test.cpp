/***************************************************************************

    file                 : rttrack_segment_test.cpp
    created              : Sun Aug 30 12:00:00 CET 2026
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

#include <track.h>
#include <robottools.h>


static const float kEps = 1e-5f;


static tTrackSeg MakeSegment(int type2, tdble width, tdble height, tdble bankingSlope,
	tTrackSurface *surface)
{
	tTrackSeg seg{};
	seg.type = TR_STR;
	seg.type2 = type2;
	seg.width = width;
	seg.startWidth = width;
	seg.endWidth = width;
	seg.vertex[TR_SR].z = height;
	seg.angle[TR_XS] = static_cast<tdble>(std::atan(bankingSlope));
	seg.surface = surface;
	return seg;
}


struct TrackSegments {
	tTrackSurface surface{};
	tTrackSeg main = MakeSegment(TR_MAIN, 10.0f, 0.0f, 0.0f, &surface);
	tTrackSeg rightBorder = MakeSegment(TR_RBORDER, 2.0f, 10.0f, 0.1f, &surface);
	tTrackSeg rightSide = MakeSegment(TR_RSIDE, 3.0f, 100.0f, 0.25f, &surface);
	tTrackSeg leftBorder = MakeSegment(TR_LBORDER, 2.0f, 20.0f, 0.1f, &surface);
	tTrackSeg leftSide = MakeSegment(TR_LSIDE, 4.0f, 200.0f, -0.2f, &surface);

	TrackSegments()
	{
		main.rside = &rightBorder;
		rightBorder.rside = &rightSide;
		main.lside = &leftBorder;
		leftBorder.lside = &leftSide;
	}
};


TEST(RtTrackGetSegTest, ResolvesMainBorderAndSideSegments)
{
	TrackSegments track;
	tTrkLocPos pos{};
	pos.seg = &track.main;

	pos.toRight = 5.0f;
	EXPECT_EQ(&track.main, RtTrackGetSeg(&pos));

	pos.toRight = -1.0f;
	EXPECT_EQ(&track.rightBorder, RtTrackGetSeg(&pos));

	pos.toRight = -3.0f;
	EXPECT_EQ(&track.rightSide, RtTrackGetSeg(&pos));

	pos.toRight = 11.0f;
	EXPECT_EQ(&track.leftBorder, RtTrackGetSeg(&pos));

	pos.toRight = 13.0f;
	EXPECT_EQ(&track.leftSide, RtTrackGetSeg(&pos));
}


TEST(RtTrackGetSegTest, KeepsExactSideBoundariesOnInnerSegment)
{
	TrackSegments track;
	tTrkLocPos pos{};
	pos.seg = &track.main;

	pos.toRight = 0.0f;
	EXPECT_EQ(&track.main, RtTrackGetSeg(&pos));

	pos.toRight = -track.rightBorder.width;
	EXPECT_EQ(&track.rightBorder, RtTrackGetSeg(&pos));

	pos.toRight = track.main.width;
	EXPECT_EQ(&track.main, RtTrackGetSeg(&pos));

	pos.toRight = track.main.width + track.leftBorder.width;
	EXPECT_EQ(&track.leftBorder, RtTrackGetSeg(&pos));
}


TEST(RtTrackGetSegTest, DoesNotModifyLocalPosition)
{
	TrackSegments track;
	tTrkLocPos pos{};
	pos.seg = &track.main;
	pos.type = TR_LPOS_MAIN;
	pos.toStart = 4.0f;
	pos.toRight = -3.0f;
	pos.toMiddle = -8.0f;
	pos.toLeft = 13.0f;

	EXPECT_EQ(&track.rightSide, RtTrackGetSeg(&pos));
	EXPECT_EQ(&track.main, pos.seg);
	EXPECT_EQ(TR_LPOS_MAIN, pos.type);
	EXPECT_NEAR(pos.toStart, 4.0f, kEps);
	EXPECT_NEAR(pos.toRight, -3.0f, kEps);
	EXPECT_NEAR(pos.toMiddle, -8.0f, kEps);
	EXPECT_NEAR(pos.toLeft, 13.0f, kEps);
}


TEST(RtTrackHeightLTest, RebasesToRightVariableWidthSide)
{
	TrackSegments track;
	track.rightSide.Kyl = 0.5f;
	tTrkLocPos pos{};
	pos.seg = &track.main;
	pos.toStart = 4.0f;
	pos.toRight = -5.0f;

	tdble height = RtTrackHeightL(&pos);

	// toRight on the side is -5 + 2 + (3 + 4 * 0.5) = 2.
	EXPECT_NEAR(height, 100.0f + 2.0f * 0.25f, kEps);
}


TEST(RtTrackHeightLTest, RebasesToLeftSide)
{
	TrackSegments track;
	tTrkLocPos pos{};
	pos.seg = &track.main;
	pos.toStart = 4.0f;
	pos.toRight = 13.5f;

	tdble height = RtTrackHeightL(&pos);

	// toRight on the side is 13.5 - 10 - 2 = 1.5.
	EXPECT_NEAR(height, 200.0f + 1.5f * -0.2f, kEps);
}
