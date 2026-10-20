/***************************************************************************

    file                 : track.cpp
    created              : Sun Dec 24 12:14:18 CET 2000
    copyright            : (C) 2000-2026 by Eric Espie, Bernhard Wymann
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

#include <stdio.h>
#include <tgfclient.h>
#include <track.h>

#include "ac3d.h"
#include "trackgen.h"
#include "trackscene.h"

void CalculateTrack(tTrack *Track, void *TrackHandle)
{
	const tdble trackStep = GfParmGetNum(TrackHandle, TRK_SECT_TERRAIN, TRK_ATT_TSTEP,
			NULL, DEFAULT_TRACK_STEP);
	if (!TrackgenQuiet) {
		GfOut("Track step: %.2f ", trackStep);
	}
	TrackSceneInit(Track, TrackHandle, 0, 0, trackStep);
	printf("Calculation finished\n");
}

void
GenerateTrack(tTrack *Track, void *TrackHandle, char *outFile, FILE *AllFd,
		int bump, int raceline, const TrackCrossingModel *crossingModel)
{
	FILE *curFd;
	int crossingCount = crossingModel == NULL
			? 0 : (int)crossingModel->crossings.size();

	const tdble trackStep = GfParmGetNum(TrackHandle, TRK_SECT_TERRAIN, TRK_ATT_TSTEP,
			NULL, DEFAULT_TRACK_STEP);
	if (!TrackgenQuiet) {
		GfOut("Track step: %.2f ", trackStep);
	}
	TrackSceneInit(Track, TrackHandle, bump, raceline, trackStep);

	if (outFile) {
		curFd = Ac3dOpen(outFile, 1);
		Ac3dGroup(curFd, "track", TrackSceneGetActiveGroupCount() + crossingCount);
		TrackSceneSave(curFd, bump, raceline);
		WriteTrackCrossingModel(curFd, crossingModel);
		Ac3dClose(curFd);
	}
	if (AllFd) {
		Ac3dGroup(AllFd, "track", TrackSceneGetActiveGroupCount() + crossingCount);
		TrackSceneSave(AllFd, bump, raceline);
		WriteTrackCrossingModel(AllFd, crossingModel);
	}
}
