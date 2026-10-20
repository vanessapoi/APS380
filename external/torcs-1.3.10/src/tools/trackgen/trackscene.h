/***************************************************************************

    file                 : trackscene.h
    created              : Wed Aug 12 2026
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

#ifndef _TRACKSCENE_H_
#define _TRACKSCENE_H_

#include <stdio.h>
#include <track.h>

int TrackSceneInit(tTrack *track, void *trackHandle, int bump, int raceline,
		tdble trackStep);
void TrackSceneSave(FILE *file, int bump, int raceline);
int TrackSceneGetActiveGroupCount(void);

#ifdef TRACKSCENE_TEST
void TrackSceneTestSaveObject(FILE *file, int vertexCount,
		const float *vertices, const float *texCoords);
#endif

#endif /* _TRACKSCENE_H_ */
