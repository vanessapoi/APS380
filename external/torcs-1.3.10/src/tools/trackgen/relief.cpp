/***************************************************************************

	file                 : relief.cpp
	created              : Tue Mar  6 23:15:19 CET 2001
	copyright            : (C) 2000-2026 by Eric Espié, Bernhard Wymann
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

  /** @file
	  @brief Load relief constraint lines for EasyMesh terrain generation.

	  @author <a href=mailto:eric.espie@torcs.org>Eric Espie</a>
   */

#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>
#include <string.h>
#ifndef WIN32
#include <unistd.h>
#else
#include <windows.h>
#endif
#include <math.h>
#include <plib/ssg.h>
#include <GL/glut.h>

#include <tgfclient.h>
#include <track.h>
#include "trackgen.h"
#include "easymesh.h"
#include "terrain.h"

#include "relief.h"

typedef struct Line
{
	GF_TAILQ_ENTRY(struct Line) link;
	ssgBranch* branch;
} tLine;

GF_TAILQ_HEAD(RingListHead, tLine);

static tRingListHead InteriorList;
static tRingListHead ExteriorList;

static tdble ReliefGridStep;

static ssgEntity* Root = NULL;

/** @brief Create a relief branch and classify it by AC3D object name.
	@param[in] objectName AC3D object name.
	@return Branch that receives the object's geometry.
 */
static ssgBranch*
hookNode(char* objectName)
{
	tLine* line;

	line = (tLine*)calloc(1, sizeof(tLine));
	line->branch = new ssgBranch();

	if (strncmp(objectName, "interior", 8) == 0) {
		GF_TAILQ_INSERT_TAIL(&InteriorList, line, link);
	}
	else {
		GF_TAILQ_INSERT_TAIL(&ExteriorList, line, link);
	}
	return line->branch;
}


/** @brief Load and classify relief constraints from an AC3D file.
	@param[in] TrackHandle Track parameter handle.
	@param[in] reliefFile Relief AC3D file path.
	@note Reinitializes InteriorList, ExteriorList, and Root.
 */
void
LoadRelief(void* TrackHandle, char* reliefFile)
{
	GF_TAILQ_INIT(&InteriorList);
	GF_TAILQ_INIT(&ExteriorList);

	ReliefGridStep = GfParmGetNum(TrackHandle, TRK_SECT_TERRAIN,
		TRK_ATT_BSTEP, NULL, ReliefGridStep);

	ssgLoaderOptions* loaderopt = new ssgLoaderOptions();

	loaderopt->setCreateBranchCallback(hookNode);

	if (!TrackgenQuiet) {
		printf("\nLoading relief file %s\n", reliefFile);
	}

	Root = ssgLoadAC(reliefFile, loaderopt);
}

/** @brief Recursively count relief vertices and line segments.
	@param[in] entity Scene-graph entity to inspect.
	@param[in,out] vertexCount Accumulated vertex count.
	@param[in,out] segmentCount Accumulated line-segment count.
 */
static void
countRec(ssgEntity* entity, int* vertexCount, int* segmentCount)
{
	if (entity->isAKindOf(_SSG_TYPE_BRANCH)) {
		ssgBranch* br = (ssgBranch*)entity;

		for (int i = 0; i < br->getNumKids(); i++) {
			countRec(br->getKid(i), vertexCount, segmentCount);
		}
	}
	else {
		if (entity->isAKindOf(_SSG_TYPE_VTXTABLE)) {
			ssgVtxTable* vt = (ssgVtxTable*)entity;
			*vertexCount += vt->getNumVertices();
			*segmentCount += vt->getNumLines();
		}
	}
}

/** @brief Count relief input required by one terrain domain.
	@param[in] interior Non-zero selects interior relief, zero selects exterior.
	@param[out] nb_vert Number of relief vertices.
	@param[out] nb_seg Number of relief line segments.
	@note Flattens each selected relief branch before counting it.
 */
void
CountRelief(int interior, int* nb_vert, int* nb_seg)
{
	tLine* curLine;
	tRingListHead* curHead;

	*nb_vert = *nb_seg = 0;

	if (Root == NULL) {
		return;
	}

	if (interior) {
		curHead = &InteriorList;
	}
	else {
		curHead = &ExteriorList;
	}

	curLine = GF_TAILQ_FIRST(curHead);
	while (curLine != NULL) {
		ssgBranch* br = curLine->branch->getParent(0);
		ssgBranch* br2 = new ssgBranch();

		br2->addKid(br);
		ssgFlatten(br);
		curLine->branch = br2;

		countRec((ssgEntity*)curLine->branch, nb_vert, nb_seg);

		curLine = GF_TAILQ_NEXT(curLine, link);
	}
}

/** @brief Append one scene-graph subtree to EasyMesh constrained input.
	@param[in] entity Scene-graph entity to append recursively.
	@param[in,out] input Bounded point and segment arrays receiving relief.
 */
static void
genRec(ssgEntity* entity, tMeshInput* input)
{
	if (entity->isAKindOf(_SSG_TYPE_BRANCH)) {
		ssgBranch* br = (ssgBranch*)entity;

		for (int i = 0; i < br->getNumKids(); i++) {
			genRec(br->getKid(i), input);
		}
	}
	else {
		if (entity->isAKindOf(_SSG_TYPE_VTXTABLE)) {
			ssgVtxTable* vt = (ssgVtxTable*)entity;
			int nv = vt->getNumVertices();
			int nl = vt->getNumLines();
			int firstPointIndex = input->pointCount;
			int i;

			for (i = 0; i < nv; i++) {
				if (input->pointCount >= input->pointCapacity) {
					GfFatal("Relief exceeds terrain point capacity\n");
					exit(1);
				}
				float* vtx = vt->getVertex(i);
				input->points[input->pointCount].x = vtx[0];
				input->points[input->pointCount].y = vtx[1];
				input->points[input->pointCount].z = vtx[2];
				input->points[input->pointCount].spacing = ReliefGridStep;
				input->points[input->pointCount].marker = RELIEF_BOUNDARY_MARK;
				input->pointCount++;
			}

			for (i = 0; i < nl; i++) {
				short vv0, vv1;
				if (input->segmentCount >= input->segmentCapacity) {
					GfFatal("Relief exceeds terrain segment capacity\n");
					exit(1);
				}

				vt->getLine(i, &vv0, &vv1);

				input->segments[input->segmentCount].startNode = vv0 + firstPointIndex;
				input->segments[input->segmentCount].endNode = vv1 + firstPointIndex;
				input->segments[input->segmentCount].marker = RELIEF_BOUNDARY_MARK;

				input->segmentCount++;
			}
		}
	}
}



/** @brief Append relief constraints for one terrain domain.
	@param[in] interior Non-zero selects interior relief, zero selects exterior.
	@param[in,out] input Bounded point and segment arrays receiving relief.
 */
void
GenRelief(int interior, tMeshInput* input)
{
	tLine* curLine;
	tRingListHead* curHead;


	if (Root == NULL) {
		return;
	}

	if (interior) {
		curHead = &InteriorList;
	}
	else {
		curHead = &ExteriorList;
	}

	curLine = GF_TAILQ_FIRST(curHead);
	while (curLine != NULL) {
		genRec((ssgEntity*)curLine->branch, input);

		curLine = GF_TAILQ_NEXT(curLine, link);
	}
}
