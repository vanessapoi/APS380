/***************************************************************************

    file                 : cardata_test.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/***************************************************************************
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 ***************************************************************************/

#include <gtest/gtest.h>
#include <cmath>
#include "cardata.h"

static const float kEps = 1e-5f;

struct WidthCase {
	const char* name;
	double yaw;
	double expected;
};

class CardataWidthTest : public testing::TestWithParam<WidthCase> {};

TEST_P(CardataWidthTest, RectangleProjectionMatchesAnalyticExtent)
{
	// A 4 m by 2 m rectangle: at 30 degrees its extent is 2 + sqrt(3).
	// Repeat in a rotated world frame to check that only relative yaw matters.
	for (float heading : {0.0f, 1.2f}) {
		SCOPED_TRACE(heading);
		tTrackSeg segment = {};
		segment.type = TR_STR;
		segment.angle[TR_ZS] = heading;
		tCarElt car = {};
		car._trkPos.seg = &segment;
		car._dimension_x = 4;
		car._dimension_y = 2;
		car._yaw = (float)(heading + GetParam().yaw);
		SingleCardata observation;
		observation.init(&car);
		observation.update();
		EXPECT_GT(observation.getWidthOnTrack(), 0);
		EXPECT_NEAR(observation.getWidthOnTrack(), GetParam().expected, kEps);
	}
}

INSTANTIATE_TEST_SUITE_P(Orientations, CardataWidthTest, testing::Values(
	WidthCase{"Aligned", 0, 2},
	WidthCase{"LeftThirty", PI/6, 2 + std::sqrt(3.0)},
	WidthCase{"RightThirty", -PI/6, 2 + std::sqrt(3.0)},
	WidthCase{"LeftNinety", PI/2, 4},
	WidthCase{"RightNinety", -PI/2, 4},
	WidthCase{"Reversed", PI, 2}),
	[](const testing::TestParamInfo<WidthCase>& info) { return info.param.name; });
