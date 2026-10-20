/***************************************************************************

    file         : tracksceneprivate.h
    created      : Sun Dec 24 12:14:18 CET 2000
    copyright    : (C) 2000-2026 by Eric Espie, Bernhard Wymann
    email        : berniw@bluewin.ch

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

    @author	<a href=mailto:eric.espie@torcs.org>Eric Espie</a>
*/

#ifndef _TRACKSCENEPRIVATE_H_
#define _TRACKSCENEPRIVATE_H_

#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>
#ifndef WIN32
#include <unistd.h>
#endif
#include <math.h>
#include <string.h>

#include <tgfclient.h>
#include <track.h>
#include <robottools.h>
#include <portability.h>

#include "ac3d.h"
#include "util.h"
#include "trackgen.h"
#include "trackscene.h"

typedef struct texElt {
	char *name;
	char *namebump;
	char *nameraceline;
	unsigned int texid;
	struct texElt *next;
} tTexElt;

typedef struct dispElt {
	unsigned int start;
	int nb;
	char *name;
	int id;
	tTexElt *texture;
	struct dispElt *next;
} tDispElt;

typedef struct group {
	int nb;
	tDispElt *dispList;
} tGroup;

typedef struct {
	tdble tx, ty;
	tdble x, y, z;
} tPoint;

typedef struct trackSceneContext {
	tTrack *track;
	void *trackHandle;
	int bump;
	tdble trackStep;
	unsigned int &nbvert;
	tTexElt *&texList;
	tTexElt *&curTexElt;
	tDispElt *&curDispElt;
	unsigned int &curTexId;
	unsigned int &prevTexId;
	int &startNeeded;
	int &curTexType;
	int &curTexLink;
	tdble &curTexOffset;
	tdble &curTexSize;
} tTrackSceneContext;

extern tGroup *Groups;
extern int ActiveGroups;
extern int GroupNb;
extern float *trackvertices;
extern float *tracktexcoord;
extern unsigned int *trackindices;
#define LG_STEP_MAX 50.0
#define PIT_HEIGHT 5.0f
#define PIT_DEEP 10.0f
#define PIT_TOP 0.2f

unsigned int countTrackVertices(tTrack *track, tdble trackStep);
void generateMainTrack(tTrackSceneContext &scene, int raceline, double rlWidthScale, double rlOffset);
void generateBorders(tTrackSceneContext &scene, int side);
void generateSide(tTrackSceneContext &scene, int side);
void generateBarriers(tTrackSceneContext &scene, int side);
void generateTurnMarks(tTrackSceneContext &scene);
void generateStartBridge(tTrackSceneContext &scene);
void generatePits(tTrackSceneContext &scene);

void newDispList(tTrackSceneContext &scene, int texchange, const char *name, int id);
void checkDispList(tTrackSceneContext &scene, const char *mat,
		const char *name, int id, tdble off);
void checkDispList2(tTrackSceneContext &scene, const char *texture,
		const char *name, int id);
void checkDispList3(tTrackSceneContext &scene, const char *texture,
		const char *name, int id);
void setPoint(tTexElt *curTexElt, float t1, float t2, float x, float y, float z, unsigned int &nbvert);
tdble trackSceneTexS(int side, tdble texLen);
void emitWallCrossSection(tTrackSceneContext &scene, int side, int layer,
		tdble texLen, tdble outerX, tdble outerY, tdble outerZ,
		tdble innerX, tdble innerY, tdble innerZ, tdble height);
void emitWallCap(tTrackSceneContext &scene, int side, tdble texS,
		tdble x, tdble y, tdble z, tdble height);

#ifdef TRACKSCENE_TEST
unsigned int TrackSceneTestGeneratePitCap(int clockwise, tdble x, tdble y,
		tdble z, tdble normalX, tdble normalY, float *vertices,
		float *texCoords);
void TrackSceneTestInitPits(tTrackPitInfo *pits);
#endif

#endif /* _TRACKSCENEPRIVATE_H_ */
