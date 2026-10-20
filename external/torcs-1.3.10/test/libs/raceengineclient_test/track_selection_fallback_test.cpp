/***************************************************************************

    file                 : track_selection_fallback_test.cpp
    created              : Mon Jun  1 20:00:00 CET 2026
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

/**
    Unit tests for race-manager track fallback selection.
*/

#include <cstdio>
#include <vector>

#include <gtest/gtest.h>

#include <tgf.h>
#include <raceman.h>

#include "racetrackselect.h"


static const char *kTestParmFile = "raceengineclient_track_selection_test.xml";


class TrackSelectionFallbackTest : public testing::Test {
protected:
	TrackSelectionFallbackTest()
	{
		params = GfParmReadFile(kTestParmFile, GFPARM_RMODE_CREAT | GFPARM_RMODE_PRIVATE);
	}

	~TrackSelectionFallbackTest() override
	{
		if (params) {
			GfParmReleaseHandle(params);
			params = nullptr;
		}
		std::remove(kTestParmFile);
	}

	void setTrack(int index, const char *category, const char *name)
	{
		char path[128];
		snprintf(path, sizeof(path), "%s/%d", RM_SECT_TRACKS, index);
		if (category) {
			GfParmSetStr(params, path, RM_ATTR_CATEGORY, category);
		}
		if (name) {
			GfParmSetStr(params, path, RM_ATTR_NAME, name);
		}
	}

	const char *trackCategory(int index) const
	{
		char path[128];
		snprintf(path, sizeof(path), "%s/%d", RM_SECT_TRACKS, index);
		return GfParmGetStr(params, path, RM_ATTR_CATEGORY, "");
	}

	const char *trackName(int index) const
	{
		char path[128];
		snprintf(path, sizeof(path), "%s/%d", RM_SECT_TRACKS, index);
		return GfParmGetStr(params, path, RM_ATTR_NAME, "");
	}

	void *params;
};


TEST_F(TrackSelectionFallbackTest, KeepsExistingSelectedTrack)
{
	setTrack(1, "road", "forza");

	std::vector<tReTrackCandidate> availableTracks;
	availableTracks.push_back(tReTrackCandidate("road", "forza"));
	availableTracks.push_back(tReTrackCandidate("road", "alpine-1"));

	tReTrackSelection selection;
	EXPECT_TRUE(ReResolveTrackSelection(params, 1, availableTracks, &selection, true));

	EXPECT_FALSE(selection.fallback);
	EXPECT_EQ("road", selection.category);
	EXPECT_EQ("forza", selection.name);
	EXPECT_STREQ("road", trackCategory(1));
	EXPECT_STREQ("forza", trackName(1));
}


TEST_F(TrackSelectionFallbackTest, FallsBackToSameCategoryWhenTrackMissing)
{
	setTrack(1, "road", "deleted-track");

	std::vector<tReTrackCandidate> availableTracks;
	availableTracks.push_back(tReTrackCandidate("oval", "michigan"));
	availableTracks.push_back(tReTrackCandidate("road", "alpine-1"));
	availableTracks.push_back(tReTrackCandidate("road", "forza"));

	tReTrackSelection selection;
	EXPECT_TRUE(ReResolveTrackSelection(params, 1, availableTracks, &selection, true));

	EXPECT_TRUE(selection.fallback);
	EXPECT_EQ("road", selection.category);
	EXPECT_EQ("alpine-1", selection.name);
	EXPECT_STREQ("road", trackCategory(1));
	EXPECT_STREQ("alpine-1", trackName(1));
}


TEST_F(TrackSelectionFallbackTest, FallsBackToFirstTrackWhenCategoryMissing)
{
	setTrack(1, "missing-category", "deleted-track");

	std::vector<tReTrackCandidate> availableTracks;
	availableTracks.push_back(tReTrackCandidate("oval", "michigan"));
	availableTracks.push_back(tReTrackCandidate("road", "forza"));

	tReTrackSelection selection;
	EXPECT_TRUE(ReResolveTrackSelection(params, 1, availableTracks, &selection, true));

	EXPECT_TRUE(selection.fallback);
	EXPECT_EQ("oval", selection.category);
	EXPECT_EQ("michigan", selection.name);
	EXPECT_STREQ("oval", trackCategory(1));
	EXPECT_STREQ("michigan", trackName(1));
}


TEST_F(TrackSelectionFallbackTest, FallsBackWhenTrackAttributesAreMissing)
{
	std::vector<tReTrackCandidate> availableTracks;
	availableTracks.push_back(tReTrackCandidate("road", "forza"));

	tReTrackSelection selection;
	EXPECT_TRUE(ReResolveTrackSelection(params, 1, availableTracks, &selection, true));

	EXPECT_TRUE(selection.fallback);
	EXPECT_EQ("road", selection.category);
	EXPECT_EQ("forza", selection.name);
	EXPECT_STREQ("road", trackCategory(1));
	EXPECT_STREQ("forza", trackName(1));
}


TEST_F(TrackSelectionFallbackTest, UpdatesOnlyCurrentTrackSection)
{
	setTrack(1, "road", "deleted-track");
	setTrack(2, "road", "forza");

	std::vector<tReTrackCandidate> availableTracks;
	availableTracks.push_back(tReTrackCandidate("road", "alpine-1"));

	tReTrackSelection selection;
	EXPECT_TRUE(ReResolveTrackSelection(params, 1, availableTracks, &selection, true));

	EXPECT_TRUE(selection.fallback);
	EXPECT_STREQ("road", trackCategory(1));
	EXPECT_STREQ("alpine-1", trackName(1));
	EXPECT_STREQ("road", trackCategory(2));
	EXPECT_STREQ("forza", trackName(2));
}


TEST_F(TrackSelectionFallbackTest, ReturnsFalseWhenNoTracksAreAvailable)
{
	setTrack(1, "road", "deleted-track");

	std::vector<tReTrackCandidate> availableTracks;
	tReTrackSelection selection;
	EXPECT_FALSE(ReResolveTrackSelection(params, 1, availableTracks, &selection, true));

	EXPECT_FALSE(selection.fallback);
	EXPECT_TRUE(selection.category.empty());
	EXPECT_TRUE(selection.name.empty());
	EXPECT_STREQ("road", trackCategory(1));
	EXPECT_STREQ("deleted-track", trackName(1));
}


TEST_F(TrackSelectionFallbackTest, ReturnsFalseWhenOnlyInvalidCandidatesAreAvailable)
{
	setTrack(1, "road", "deleted-track");

	std::vector<tReTrackCandidate> availableTracks;
	availableTracks.push_back(tReTrackCandidate("", ""));
	availableTracks.push_back(tReTrackCandidate("road", ""));
	tReTrackSelection selection;
	EXPECT_FALSE(ReResolveTrackSelection(params, 1, availableTracks, &selection, true));

	EXPECT_FALSE(selection.fallback);
	EXPECT_TRUE(selection.category.empty());
	EXPECT_TRUE(selection.name.empty());
	EXPECT_STREQ("road", trackCategory(1));
	EXPECT_STREQ("deleted-track", trackName(1));
}


TEST_F(TrackSelectionFallbackTest, LeavesParamsUnchangedWhenUpdateIsDisabled)
{
	setTrack(1, "road", "deleted-track");

	std::vector<tReTrackCandidate> availableTracks;
	availableTracks.push_back(tReTrackCandidate("road", "alpine-1"));

	tReTrackSelection selection;
	EXPECT_TRUE(ReResolveTrackSelection(params, 1, availableTracks, &selection, false));

	EXPECT_TRUE(selection.fallback);
	EXPECT_EQ("road", selection.category);
	EXPECT_EQ("alpine-1", selection.name);
	EXPECT_STREQ("road", trackCategory(1));
	EXPECT_STREQ("deleted-track", trackName(1));
}
