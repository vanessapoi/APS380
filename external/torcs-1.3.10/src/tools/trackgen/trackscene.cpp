/***************************************************************************

    file         : trackscene.cpp
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

#include "tracksceneprivate.h"

tGroup *Groups;
int ActiveGroups;
int GroupNb;
float *trackvertices;
float *tracktexcoord;
unsigned int *trackindices;
int TrackSceneInit(tTrack *Track, void *TrackHandle, int bump, int raceline, tdble trackStep)
{
	unsigned int nbvert;
	int startNeeded;

	unsigned int prevTexId;
	unsigned int curTexId = 0;
	int	curTexType = 0;
	int	curTexLink = 0;
	tdble curTexOffset = 0;
	tdble curTexSize = 0;
	tTexElt *texList = (tTexElt *)NULL;
	tTexElt *curTexElt = NULL;

	tDispElt *theCurDispElt = NULL;
	printf("++++++++++++ Track ++++++++++++\n");
	printf("name      = %s\n", Track->name);
	printf("author    = %s\n", Track->author);
	printf("filename  = %s\n", Track->filename);
	printf("nseg      = %d\n", Track->nseg);
	printf("version   = %d\n", Track->version);
	printf("length    = %f\n", Track->length);
	printf("width     = %f\n", Track->width);
	printf("pits      = %d\n", Track->pits.nMaxPits);
	printf("XSize     = %f\n", Track->max.x);
	printf("YSize     = %f\n", Track->max.y);
	printf("ZSize     = %f\n", Track->max.z);

	tdble delatx = Track->seg->next->vertex[TR_SL].x - Track->seg->vertex[TR_EL].x;
	tdble delaty = Track->seg->next->vertex[TR_SL].y - Track->seg->vertex[TR_EL].y;
	tdble delatz = Track->seg->next->vertex[TR_SL].z - Track->seg->vertex[TR_EL].z;
	tdble delata = Track->seg->next->angle[TR_ZS] - Track->seg->angle[TR_ZE];
	NORM_PI_PI(delata);

	printf("Delta X   = %f\n", delatx);
	printf("Delta Y   = %f\n", delaty);
	printf("Delta Z   = %f\n", delatz);
	printf("Delta Ang = %f (%f)\n", delata, RAD2DEG(delata));

	Groups = (tGroup *)calloc(Track->nseg, sizeof(tGroup));
	ActiveGroups = 0;
	GroupNb = Track->nseg;

	double rlWidthScale = 1.0;
	double rlOffset = 0.0;

	if (raceline) {
		double SideDistExt = GfParmGetNum(TrackHandle, TRK_SECT_MAIN, TRK_ATT_RLEXT, (char*)NULL, 2.0);
		double SideDistInt = GfParmGetNum(TrackHandle, TRK_SECT_MAIN, TRK_ATT_RLINT, (char*)NULL, 2.0);
		rlWidthScale = GfParmGetNum(TrackHandle, TRK_SECT_MAIN, TRK_ATT_RLWIDTHSCALE, (char*)NULL, 1.0);
		rlOffset = (1.0 - 1.0/rlWidthScale)/2.0;

		generateRaceLine(Track, SideDistExt, SideDistInt);
	}

#define CLOSEDISPLIST() do {					\
	theCurDispElt->nb = nbvert - theCurDispElt->start;	\
    }  while (0)

	/* Count the number of vertices to allocate */
	nbvert = countTrackVertices(Track, trackStep);
	if (!TrackgenQuiet) {
		printf("=== Indices Array Size   = %d\n", nbvert);
		printf("=== Vertex Array Size    = %d\n", nbvert * 3);
		printf("=== Tex Coord Array Size = %d\n", nbvert * 2);
	}
	trackindices  = (unsigned int *)malloc(sizeof(unsigned int) * nbvert);
	trackvertices = (float *)malloc(sizeof(GLfloat)*(nbvert * 3));
	tracktexcoord = (float *)malloc(sizeof(GLfloat)*(nbvert * 2));

	nbvert = 0;

	tTrackSceneContext scene = {
		Track, TrackHandle, bump, trackStep, nbvert, texList, curTexElt, theCurDispElt,
		curTexId, prevTexId, startNeeded, curTexType, curTexLink, curTexOffset, curTexSize
	};
	generateMainTrack(scene, raceline, rlWidthScale, rlOffset);

	if (raceline) {
		CLOSEDISPLIST();
		if (!TrackgenQuiet) {
			printf("=== Indices really used = %d\n", nbvert);
		}
		return 0;
	}

	generateBorders(scene, TR_SIDE_RGT);
	generateSide(scene, TR_SIDE_RGT);
	generateBorders(scene, TR_SIDE_LFT);
	generateSide(scene, TR_SIDE_LFT);
	generateBarriers(scene, TR_SIDE_RGT);
	generateBarriers(scene, TR_SIDE_LFT);

	if (!bump) {

		/* Turn Marks */
		generateTurnMarks(scene);



		generateStartBridge(scene);
		generatePits(scene);
	}

	CLOSEDISPLIST();
	if (!TrackgenQuiet) {
		printf("=== Indices really used = %d\n", nbvert);
	}
	return 0;
}

int
TrackSceneGetActiveGroupCount(void)
{
	return ActiveGroups;
}
