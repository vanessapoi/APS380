/***************************************************************************

    file        : racetrackselect.cpp
    created     : Mon Jun  1 20:00:00 CET 2026
    copyright   : (C) 2026 by Bernhard Wymann
    email       : berniw@bluewin.ch

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
    Helpers for selecting a valid race-manager track.
*/

#include <stdio.h>
#include <string.h>

#include <tgf.h>
#include <track.h>
#include <raceman.h>

#include "racetrackselect.h"


tReTrackCandidate::tReTrackCandidate(const char *trackCategory, const char *trackName)
	: category(trackCategory ? trackCategory : ""),
	  name(trackName ? trackName : "")
{
}


tReTrackSelection::tReTrackSelection()
	: fallback(false)
{
}


/** Build the track XML path for a category/name pair.
    @param[in] category Track category directory name
    @param[in] trackName Track directory and XML base name
    @param[in,out] trackFile Buffer receiving the generated track XML path
    @param[in] trackFileSize Size of @p trackFile in bytes
    @return true if the path was generated without truncation
 */
static bool
reBuildTrackFileName(const char *category, const char *trackName, char *trackFile, int trackFileSize)
{
	if (!category || !category[0] || !trackName || !trackName[0] || !trackFile || trackFileSize <= 0) {
		return false;
	}

	const int written = snprintf(trackFile, trackFileSize, "tracks/%s/%s/%s.%s", category, trackName, trackName, TRKEXT);
	return written >= 0 && written < trackFileSize;
}


bool
ReTrackFileExists(const char *category, const char *trackName, char *trackFile, int trackFileSize)
{
	const int BUFSIZE = 1024;
	char localTrackFile[BUFSIZE];
	char *fileName = trackFile ? trackFile : localTrackFile;
	const int fileNameSize = trackFile ? trackFileSize : BUFSIZE;

	if (!reBuildTrackFileName(category, trackName, fileName, fileNameSize)) {
		return false;
	}

	void *trackHandle = GfParmReadFile(fileName, GFPARM_RMODE_STD | GFPARM_RMODE_PRIVATE);
	if (!trackHandle) {
		return false;
	}

	GfParmReleaseHandle(trackHandle);
	return true;
}


std::vector<tReTrackCandidate>
ReFindAvailableTracks(void)
{
	std::vector<tReTrackCandidate> tracks;
	tFList *categoryList = GfDirGetList("tracks");

	if (!categoryList) {
		return tracks;
	}

	tFList *category = categoryList;
	do {
		const int BUFSIZE = 1024;
		char path[BUFSIZE];
		snprintf(path, BUFSIZE, "tracks/%s", category->name);

		tFList *trackList = GfDirGetList(path);
		if (trackList) {
			tFList *track = trackList;
			do {
				if (ReTrackFileExists(category->name, track->name, NULL, 0)) {
					tracks.push_back(tReTrackCandidate(category->name, track->name));
				}
				track = track->next;
			} while (track != trackList);

			GfDirFreeList(trackList, NULL, true, true);
		}

		category = category->next;
	} while (category != categoryList);

	GfDirFreeList(categoryList, NULL, true, true);
	return tracks;
}


bool
ReResolveTrackSelection(void *params, int curTrackIndex, const std::vector<tReTrackCandidate>& availableTracks, tReTrackSelection *selection, bool updateParams)
{
	if (!selection) {
		return false;
	}

	selection->category.clear();
	selection->name.clear();
	selection->fallback = false;

	if (availableTracks.empty()) {
		return false;
	}

	const int BUFSIZE = 1024;
	char path[BUFSIZE];
	snprintf(path, BUFSIZE, "%s/%d", RM_SECT_TRACKS, curTrackIndex);

	const char *currentCategory = params ? GfParmGetStr(params, path, RM_ATTR_CATEGORY, "") : "";
	const char *currentTrack = params ? GfParmGetStr(params, path, RM_ATTR_NAME, "") : "";
	const tReTrackCandidate *firstTrack = NULL;
	const tReTrackCandidate *firstSameCategoryTrack = NULL;
	const tReTrackCandidate *selectedTrack = NULL;

	for (std::vector<tReTrackCandidate>::const_iterator it = availableTracks.begin(); it != availableTracks.end(); ++it) {
		if (it->category.empty() || it->name.empty()) {
			continue;
		}

		if (!firstTrack) {
			firstTrack = &(*it);
		}

		if (currentCategory[0] && it->category == currentCategory && !firstSameCategoryTrack) {
			firstSameCategoryTrack = &(*it);
		}

		if (currentCategory[0] && currentTrack[0] && it->category == currentCategory && it->name == currentTrack) {
			selectedTrack = &(*it);
			break;
		}
	}

	if (!selectedTrack) {
		selectedTrack = firstSameCategoryTrack ? firstSameCategoryTrack : firstTrack;
	}

	if (!selectedTrack) {
		return false;
	}

	selection->category = selectedTrack->category;
	selection->name = selectedTrack->name;
	selection->fallback = currentCategory[0] == 0 || currentTrack[0] == 0 || selection->category != currentCategory || selection->name != currentTrack;

	if (selection->fallback && updateParams && params) {
		GfParmSetStr(params, path, RM_ATTR_CATEGORY, selection->category.c_str());
		GfParmSetStr(params, path, RM_ATTR_NAME, selection->name.c_str());
	}

	return true;
}
