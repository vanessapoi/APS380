/***************************************************************************

    file         : trackscenefurniture.cpp
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

/** @brief Initialize driver pit positions along the configured pit lane.
 *
 * @param[in,out] pits Pit configuration receiving allocated driver positions.
 */
static void initPits(tTrackPitInfo *pits)
{
	tTrackSeg *curMainSeg;
	tTrackSeg *curPitSeg = NULL;
	tdble toStart = 0;
	tdble offset = 0;
	tTrkLocPos curPos;
	int changeSeg;
	int i;

	switch (pits->type) {
		case TR_PIT_ON_TRACK_SIDE:
			pits->driversPits = (tTrackOwnPit *)calloc(pits->nMaxPits, sizeof(tTrackOwnPit));
			pits->driversPitsNb = pits->nMaxPits;
			curPos.type = TR_LPOS_MAIN;
			curMainSeg = pits->pitStart->prev;
			changeSeg = 1;
			toStart = 0;
			i = 0;
			while (i < pits->nMaxPits) {
				if (changeSeg) {
					changeSeg = 0;
					offset = 0;
					curMainSeg = curMainSeg->next;
					switch (pits->side) {
						case TR_RGT:
							curPitSeg = curMainSeg->rside;
							if (curPitSeg->rside) {
								offset = curPitSeg->width;
								curPitSeg = curPitSeg->rside;
							}
							break;
						case TR_LFT:
							curPitSeg = curMainSeg->lside;
							if (curPitSeg->lside) {
								offset = curPitSeg->width;
								curPitSeg = curPitSeg->lside;
							}
							break;
					}
					curPos.seg = curMainSeg;
					if (toStart >= curMainSeg->length) {
						toStart -= curMainSeg->length;
						changeSeg = 1;
						continue;
					}
				}
				/* Not the real position but the start and border one instead of center */
				curPos.toStart = toStart;
				switch (pits->side) {
					case TR_RGT:
						curPos.toRight  = -offset - RtTrackGetWidth(curPitSeg, toStart);
						curPos.toLeft   = curMainSeg->width - curPos.toRight;
						curPos.toMiddle = curMainSeg->width / 2.0 - curPos.toRight;
						break;
					case TR_LFT:
						curPos.toLeft   = -offset - RtTrackGetWidth(curPitSeg, toStart);
						curPos.toRight  = curMainSeg->width - curPos.toLeft;
						curPos.toMiddle = curMainSeg->width / 2.0 - curPos.toLeft;
						break;
				}
				memcpy(&(pits->driversPits[i].pos), &curPos, sizeof(curPos));
				toStart += pits->len;
				if (toStart >= curMainSeg->length) {
					toStart -= curMainSeg->length;
					changeSeg = 1;
				}
				i++;
			}
			break;
		case TR_PIT_ON_SEPARATE_PATH:
			break;
		case TR_PIT_NONE:
			break;
	}
}

/** @brief Emit a counterclockwise end cap for a pit building.
 *
 * @param[in,out] curTexElt Texture element receiving the cap vertices.
 * @param[in,out] nbvert Current scene vertex count.
 * @param[in] x Cap origin x coordinate.
 * @param[in] y Cap origin y coordinate.
 * @param[in] z Cap origin height.
 * @param[in] normvec Outward track-side normal.
 */
static void pitCapCCW(tTexElt *curTexElt, unsigned int &nbvert, tdble x, tdble y, tdble z, const t3Dd &normvec)
{
	tdble x2 = x + PIT_TOP * normvec.x;
	tdble y2 = y + PIT_TOP * normvec.y;

	setPoint(curTexElt, 1.0 - PIT_TOP, PIT_HEIGHT - PIT_TOP, x2, y2, z + PIT_HEIGHT - PIT_TOP, nbvert);
	setPoint(curTexElt, 1.0 - PIT_TOP, PIT_HEIGHT, x2, y2, z + PIT_HEIGHT, nbvert);

	x2 = x;
	y2 = y;

	setPoint(curTexElt, 1.0, PIT_HEIGHT - PIT_TOP, x2, y2, z + PIT_HEIGHT - PIT_TOP, nbvert);

	x2 = x - PIT_DEEP * normvec.x;
	y2 = y - PIT_DEEP * normvec.y;

	setPoint(curTexElt, 1.0 + PIT_DEEP, PIT_HEIGHT, x2, y2, z + PIT_HEIGHT, nbvert);

	x2 = x;
	y2 = y;

	setPoint(curTexElt, 1.0, 0, x2, y2, z, nbvert);

	x2 = x - PIT_DEEP * normvec.x;
	y2 = y - PIT_DEEP * normvec.y;

	setPoint(curTexElt, 1.0 + PIT_DEEP, 0, x2, y2, z, nbvert);
}




/** @brief Emit a clockwise end cap for a pit building.
 *
 * @param[in,out] curTexElt Texture element receiving the cap vertices.
 * @param[in,out] nbvert Current scene vertex count.
 * @param[in] x Cap origin x coordinate.
 * @param[in] y Cap origin y coordinate.
 * @param[in] z Cap origin height.
 * @param[in] normvec Outward track-side normal.
 */
static void pitCapCW(tTexElt *curTexElt, unsigned int &nbvert, tdble x, tdble y, tdble z, const t3Dd &normvec)
{
	tdble x2 = x + PIT_TOP * normvec.x;
	tdble y2 = y + PIT_TOP * normvec.y;

	setPoint(curTexElt, 1.0 - PIT_TOP, PIT_HEIGHT, x2, y2, z + PIT_HEIGHT, nbvert);
	setPoint(curTexElt, 1.0 - PIT_TOP, PIT_HEIGHT - PIT_TOP, x2, y2, z + PIT_HEIGHT - PIT_TOP, nbvert);

	x2 = x - PIT_DEEP * normvec.x;
	y2 = y - PIT_DEEP * normvec.y;

	setPoint(curTexElt, 1.0 + PIT_DEEP, PIT_HEIGHT, x2, y2, z + PIT_HEIGHT, nbvert);

	x2 = x;
	y2 = y;

	setPoint(curTexElt, 1.0, PIT_HEIGHT - PIT_TOP, x2, y2, z + PIT_HEIGHT - PIT_TOP, nbvert);

	x2 = x - PIT_DEEP * normvec.x;
	y2 = y - PIT_DEEP * normvec.y;

	setPoint(curTexElt, 1.0 + PIT_DEEP, 0, x2, y2, z, nbvert);

	x2 = x;
	y2 = y;

	setPoint(curTexElt, 1.0, 0, x2, y2, z, nbvert);
}

/** @brief Generate textured turn-marker signs around the track.
 *
 * Resolves each marker's distance to the containing main segment, places the
 * sign outside the marked turn, and emits front and back faces with opposite
 * point order. Texture names retain the turn distance and direction suffix.
 *
 * @param[in,out] scene Scene context and output buffers updated by generation.
 */
void
generateTurnMarks(tTrackSceneContext &scene)
{
	const int BUFSIZE = 256;
	char buf[BUFSIZE];
	tTrackSeg *seg;
	tTrackSeg *mseg;
	tTrkLocPos trkpos;
	tdble x, y, z;
	tdble tmWidth = scene.track->graphic.turnMarksInfo.width;
	tdble tmHeight = scene.track->graphic.turnMarksInfo.height;
	tdble tmVSpace = scene.track->graphic.turnMarksInfo.vSpace;
	tdble tmHSpace = scene.track->graphic.turnMarksInfo.hSpace;
	int i;

	trkpos.type = TR_LPOS_MAIN;
	for (i = 0, seg = scene.track->seg->next; i < scene.track->nseg; i++, seg = seg->next) {
		if (seg->ext) {
			t3Dd normvec;
			int nbMarks = seg->ext->nbMarks;
			int *marks = seg->ext->marks;
			int j, k;

			for (j = 0; j < nbMarks; j++) {
				/* find the segment */
				tdble lgfs = seg->lgfromstart - (tdble)marks[j];
				if (lgfs < 0) {
					lgfs += scene.track->length;
				}
				for (k = 0, mseg = scene.track->seg->next; k < scene.track->nseg; k++, mseg = mseg->next) {
					if ((lgfs >= mseg->lgfromstart) && (lgfs < (mseg->lgfromstart + mseg->length))) {
						break;
					}
				}

				if (seg->type == TR_RGT) {
					snprintf(buf, BUFSIZE, "turn%dR", marks[j]);
					trkpos.toRight = scene.track->width + tmHSpace + tmWidth;
				} else {
					snprintf(buf, BUFSIZE, "turn%dL", marks[j]);
					trkpos.toRight = -tmHSpace;
				}
				trkpos.toStart = lgfs - mseg->lgfromstart;
				if (mseg->type != TR_STR) {
					trkpos.toStart = trkpos.toStart / mseg->radius;
				}
				trkpos.seg = mseg;
				RtTrackLocal2Global(&trkpos, &x, &y, TR_TORIGHT);
				z = tmVSpace + RtTrackHeightL(&trkpos);
				if (seg->type == TR_LFT) {
					RtTrackSideNormalG(mseg, x, y, TR_RGT, &normvec);
					normvec.x = -normvec.x;
					normvec.y = -normvec.y;
				} else {
					RtTrackSideNormalG(mseg, x, y, TR_LFT, &normvec);
				}
				checkDispList2(scene, buf, "TuMk", mseg->id);

				setPoint(scene.curTexElt, 0.0, 0.0, x, y, z, scene.nbvert);
				setPoint(scene.curTexElt, 1.0, 0.0, x + tmWidth * normvec.x, y + tmWidth * normvec.y, z, scene.nbvert);
				setPoint(scene.curTexElt, 0.0, 1.0, x, y, z + tmHeight, scene.nbvert);
				setPoint(scene.curTexElt, 1.0, 1.0, x + tmWidth * normvec.x, y + tmWidth * normvec.y, z + tmHeight, scene.nbvert);

				checkDispList2(scene, "back-sign", "TuMk", mseg->id);

				setPoint(scene.curTexElt, 0.0, 0.0, x + tmWidth * normvec.x, y + tmWidth * normvec.y, z, scene.nbvert);
				setPoint(scene.curTexElt, 1.0, 0.0, x, y, z, scene.nbvert);
				setPoint(scene.curTexElt, 0.0, 1.0, x + tmWidth * normvec.x, y + tmWidth * normvec.y, z + tmHeight, scene.nbvert);
				setPoint(scene.curTexElt, 1.0, 1.0, x, y, z + tmHeight, scene.nbvert);

				if (!TrackgenQuiet) {
					printf("(%f, %f, %f), (%f, %f, %f)\n", x, y, z, x + tmWidth * normvec.x, y + tmWidth * normvec.y, z + tmHeight);
				}
			}
		}
	}
}


/** @brief Generate the start-line bridge and its supporting pylons.
 *
 * Uses the outermost linked side segments to span the complete track width.
 *
 * @param[in,out] scene Scene context and output buffers updated by generation.
 */
void
generateStartBridge(tTrackSceneContext &scene)
{
	tTrackSeg *seg;
	tTrackSeg *mseg;
	tdble x, y, z;
	tdble x2, y2, z2;

	/* Start Bridge */
	checkDispList2(scene, "pylon1", "S0Bg", 0);

#define BR_HEIGHT_1	8.0
#define BR_HEIGHT_2	6.0
#define BR_WIDTH_0	2.0
#define BR_WIDTH_1	2.0
	mseg = scene.track->seg->next;
	if (mseg->rside) {
		seg = mseg->rside;
		if (seg->rside) {
			seg = seg->rside;
		}
	} else {
		seg = mseg;
	}

	x = seg->vertex[TR_SR].x;
	y = seg->vertex[TR_SR].y - 0.1;
	z = seg->vertex[TR_SR].z;

	setPoint(scene.curTexElt, 0, 0, x, y, z, scene.nbvert);
	setPoint(scene.curTexElt, 0, 1, x, y, z + BR_HEIGHT_2, scene.nbvert);

	x += BR_WIDTH_0;

	setPoint(scene.curTexElt, 1, 0, x, y, z, scene.nbvert);
	setPoint(scene.curTexElt, 1, 1, x, y, z + BR_HEIGHT_2, scene.nbvert);

	y -= BR_WIDTH_1;

	setPoint(scene.curTexElt, 2, 0, x, y, z, scene.nbvert);
	setPoint(scene.curTexElt, 2, 1, x, y, z + BR_HEIGHT_2, scene.nbvert);

	x -= BR_WIDTH_0;

	setPoint(scene.curTexElt, 3, 0, x, y, z, scene.nbvert);
	setPoint(scene.curTexElt, 3, 1, x, y, z + BR_HEIGHT_2, scene.nbvert);

	y += BR_WIDTH_1;

	setPoint(scene.curTexElt, 4, 0, x, y, z, scene.nbvert);
	setPoint(scene.curTexElt, 4, 1, x, y, z + BR_HEIGHT_2, scene.nbvert);

	newDispList(scene, 0, "S1Bg", 0);

	if (mseg->lside) {
		seg = mseg->lside;
		if (seg->lside) {
			seg = seg->lside;
		}
	} else {
		seg = mseg;
	}
	x2 = seg->vertex[TR_SL].x;
	y2 = seg->vertex[TR_SL].y + 0.1;
	z2 = seg->vertex[TR_SL].z;

	setPoint(scene.curTexElt, 0, 1, x2, y2, z + BR_HEIGHT_2, scene.nbvert);
	setPoint(scene.curTexElt, 0, 0, x2, y2, z2, scene.nbvert);

	x2 += BR_WIDTH_0;

	setPoint(scene.curTexElt, 1, 1, x2, y2, z + BR_HEIGHT_2, scene.nbvert);
	setPoint(scene.curTexElt, 1, 0, x2, y2, z2, scene.nbvert);

	y2 += BR_WIDTH_1;

	setPoint(scene.curTexElt, 2, 1, x2, y2, z + BR_HEIGHT_2, scene.nbvert);
	setPoint(scene.curTexElt, 2, 0, x2, y2, z2, scene.nbvert);

	x2 -= BR_WIDTH_0;

	setPoint(scene.curTexElt, 3, 1, x2, y2, z + BR_HEIGHT_2, scene.nbvert);
	setPoint(scene.curTexElt, 3, 0, x2, y2, z2, scene.nbvert);

	y2 -= BR_WIDTH_1;

	setPoint(scene.curTexElt, 4, 1, x2, y2, z + BR_HEIGHT_2, scene.nbvert);
	setPoint(scene.curTexElt, 4, 0, x2, y2, z2, scene.nbvert);

	checkDispList2(scene, "pylon2", "S2Bg", 0);


	setPoint(scene.curTexElt, 0, 1, x, y, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 0, 0, x, y, z + BR_HEIGHT_2, scene.nbvert);

	y -= BR_WIDTH_1;

	setPoint(scene.curTexElt, 1, 1, x, y, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 1, 0, x, y, z + BR_HEIGHT_2, scene.nbvert);

	x += BR_WIDTH_0;

	setPoint(scene.curTexElt, 2, 1, x, y, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 2, 0, x, y, z + BR_HEIGHT_2, scene.nbvert);

	y += BR_WIDTH_1;

	setPoint(scene.curTexElt, 3, 1, x, y, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 3, 0, x, y, z + BR_HEIGHT_2, scene.nbvert);

	x -= BR_WIDTH_0;

	setPoint(scene.curTexElt, 3, 1, x + BR_WIDTH_0, y, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 3, 0, x, y, z + BR_HEIGHT_1, scene.nbvert);

	y -= BR_WIDTH_1;

	setPoint(scene.curTexElt, 4, 1, x + BR_WIDTH_0, y, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 4, 0, x, y, z + BR_HEIGHT_1, scene.nbvert);

	y += BR_WIDTH_1;	/* back to origin */

	newDispList(scene, 0, "S3Bg", 0);

	y2 += BR_WIDTH_1;

	setPoint(scene.curTexElt, 0, 1, x2 + BR_WIDTH_0, y2, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 0, 0, x2, y2, z + BR_HEIGHT_1, scene.nbvert);

	y2 -= BR_WIDTH_1;

	setPoint(scene.curTexElt, 1, 1, x2 + BR_WIDTH_0, y2, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 1, 0, x2, y2, z + BR_HEIGHT_1, scene.nbvert);

	x2 += BR_WIDTH_0;

	setPoint(scene.curTexElt, 1, 1, x2, y2, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 1, 0, x2, y2, z + BR_HEIGHT_2, scene.nbvert);

	y2 += BR_WIDTH_1;

	setPoint(scene.curTexElt, 2, 1, x2, y2, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 2, 0, x2, y2, z + BR_HEIGHT_2, scene.nbvert);

	x2 -= BR_WIDTH_0;

	setPoint(scene.curTexElt, 3, 1, x2, y2, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 3, 0, x2, y2, z + BR_HEIGHT_2, scene.nbvert);

	y2 -= BR_WIDTH_1;

	setPoint(scene.curTexElt, 4, 1, x2, y2, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 4, 0, x2, y2, z + BR_HEIGHT_2, scene.nbvert);

	/* Middle on the bridge */
	checkDispList2(scene, "pylon3", "S4Bg", 2);

	setPoint(scene.curTexElt, 0, 0, x2, y2, z + BR_HEIGHT_2, scene.nbvert);
	setPoint(scene.curTexElt, 1, 0, x, y, z + BR_HEIGHT_2, scene.nbvert);
	setPoint(scene.curTexElt, 0, 0.25, x2, y2, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 1, 0.25, x, y, z + BR_HEIGHT_1, scene.nbvert);

	x += BR_WIDTH_0;
	x2 += BR_WIDTH_0;

	setPoint(scene.curTexElt, 0, 0.5, x2, y2, z + BR_HEIGHT_1, scene.nbvert);
	setPoint(scene.curTexElt, 1, 0.5, x, y, z + BR_HEIGHT_1, scene.nbvert);


	setPoint(scene.curTexElt, 0, 0.75, x2, y2, z + BR_HEIGHT_2, scene.nbvert);
	setPoint(scene.curTexElt, 1, 0.75, x, y, z + BR_HEIGHT_2, scene.nbvert);

	x -= BR_WIDTH_0;
	x2 -= BR_WIDTH_0;

	setPoint(scene.curTexElt, 0, 1, x2, y2, z + BR_HEIGHT_2, scene.nbvert);
	setPoint(scene.curTexElt, 1, 1, x, y, z + BR_HEIGHT_2, scene.nbvert);

#undef BR_HEIGHT_1
#undef BR_HEIGHT_2
#undef BR_WIDTH_0
#undef BR_WIDTH_1
}


/** @brief Generate pit-building caps and longitudinal surfaces.
 *
 * Initializes driver pit positions and mirrors vertex winding for buildings on
 * the left and right sides of the track.
 *
 * @param[in,out] scene Scene context and output buffers updated by generation.
 */
void
generatePits(tTrackSceneContext &scene)
{
	const int BUFSIZE = 256;
	char sname[BUFSIZE];
	tTrackPitInfo *pits;
	tdble x, y;
	tdble x2, y2, z2;
	tdble x3, y3, z3;
	int i;

	/* draw the pits */

	pits = &(scene.track->pits);
	initPits(pits);

	if (pits->type == TR_PIT_ON_TRACK_SIDE) {
		int		uid = 1;
		t3Dd	normvec;

		scene.startNeeded = 1;
		snprintf(sname, BUFSIZE, "P%dts", uid++);
		checkDispList3(scene, "concrete2.rgb", sname, pits->driversPits[0].pos.seg->id);

		RtTrackLocal2Global(&(pits->driversPits[0].pos), &x, &y, pits->driversPits[0].pos.type);
		RtTrackSideNormalG(pits->driversPits[0].pos.seg, x, y, pits->side, &normvec);
		z2 = RtTrackHeightG(pits->driversPits[0].pos.seg, x, y);

		// To get the normal right choose the right winding.
		if (pits->side == TR_RGT) {
			pitCapCW(scene.curTexElt, scene.nbvert, x, y, z2, normvec);
		} else {
			pitCapCCW(scene.curTexElt, scene.nbvert, x, y, z2, normvec);
		}

		// Pit front, roof and back.
		for (i = 0; i < pits->driversPitsNb; i++) {

			scene.startNeeded = 1;
			snprintf(sname, BUFSIZE, "P%dts", uid++);
			checkDispList3(scene, "concrete.rgb", sname, pits->driversPits[i].pos.seg->id);

			RtTrackLocal2Global(&(pits->driversPits[i].pos), &x, &y, pits->driversPits[i].pos.type);
			RtTrackSideNormalG(pits->driversPits[i].pos.seg, x, y, pits->side, &normvec);
			x2 = x;
			y2 = y;
			z2 = RtTrackHeightG(pits->driversPits[i].pos.seg, x2, y2);

			// Different ordering for left and right to get correct face normals
			int leftpoints[10] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9};	// ordering for pit on the left
			int rightpoints[10] = {1, 0, 3, 2, 5, 4, 7, 6, 9, 8};	// ordering for pit on the right
			int *pindex;

			if (pits->side == TR_RGT) {
				x3 = x + pits->len * normvec.y;
				y3 = y - pits->len * normvec.x;
				pindex = rightpoints;
			} else {
				x3 = x - pits->len * normvec.y;
				y3 = y + pits->len * normvec.x;
				pindex = leftpoints;
			}

			z3 = RtTrackHeightG(pits->driversPits[i].pos.seg, x3, y3);

			tPoint parray[10] = {
				{pits->len,	0.0f,									x2,							y2,							z2 + PIT_HEIGHT - PIT_TOP},
				{0.0f,		0.0f,									x3,							y3,							z3 + PIT_HEIGHT - PIT_TOP},
				{pits->len, PIT_TOP,								x2 + PIT_TOP * normvec.x,	y2 + PIT_TOP * normvec.y,	z2 + PIT_HEIGHT - PIT_TOP},
				{0.0f,		PIT_TOP,								x3 + PIT_TOP * normvec.x,	y3 + PIT_TOP * normvec.y,	z3 + PIT_HEIGHT - PIT_TOP},
				{pits->len, 2.0f * PIT_TOP,							x2 + PIT_TOP * normvec.x,	y2 + PIT_TOP * normvec.y,	z2 + PIT_HEIGHT},
				{0.0f,		2.0f * PIT_TOP,							x3 + PIT_TOP * normvec.x,	y3 + PIT_TOP * normvec.y,	z3 + PIT_HEIGHT},
				{pits->len, 2.0f * PIT_TOP + PIT_DEEP,				x2 - PIT_DEEP * normvec.x,	y2 - PIT_DEEP * normvec.y,	z2 + PIT_HEIGHT},
				{0.0f,		2.0f * PIT_TOP + PIT_DEEP,				x3 - PIT_DEEP * normvec.x,	y3 - PIT_DEEP * normvec.y,	z3 + PIT_HEIGHT},
				{pits->len, 2.0f * PIT_TOP + PIT_DEEP + PIT_HEIGHT, x2 - PIT_DEEP * normvec.x,	y2 - PIT_DEEP * normvec.y,	z2},
				{0.0f,		2.0f * PIT_TOP + PIT_DEEP + PIT_HEIGHT, x3 - PIT_DEEP * normvec.x,	y3 - PIT_DEEP * normvec.y,	z3}
			};

			int pp;

			for (pp = 0; pp < 10; pp++) {
				tPoint &p = parray[pindex[pp]];
				setPoint(scene.curTexElt, p.tx, p.ty, p.x, p.y, p.z, scene.nbvert);
			}
		}
		scene.startNeeded = 1;
		i--;
		snprintf(sname, BUFSIZE, "P%dts", uid++);
		checkDispList3(scene, "concrete2.rgb", sname, pits->driversPits[i].pos.seg->id);

		RtTrackLocal2Global(&(pits->driversPits[i].pos), &x, &y, pits->driversPits[i].pos.type);
		RtTrackSideNormalG(pits->driversPits[i].pos.seg, x, y, pits->side, &normvec);

		if (pits->side == TR_RGT) {
			x = x + pits->len * normvec.y;
			y = y - pits->len * normvec.x;
		} else {
			x = x - pits->len * normvec.y;
			y = y + pits->len * normvec.x;
		}

		z2 = RtTrackHeightG(pits->driversPits[i].pos.seg, x, y);

		// To get the normal right choose the right winding.
		if (pits->side == TR_RGT) {
			pitCapCCW(scene.curTexElt, scene.nbvert, x, y, z2, normvec);
		} else {
			pitCapCW(scene.curTexElt, scene.nbvert, x, y, z2, normvec);
		}
	}
}

#ifdef TRACKSCENE_TEST
/** @brief Expose pit-position initialization to trackscene unit tests.
 *
 * @param[in,out] pits Pit configuration receiving allocated driver positions.
 */
void
TrackSceneTestInitPits(tTrackPitInfo *pits)
{
	initPits(pits);
}

/** @brief Generate one pit cap into caller-provided test buffers.
 *
 * @param[in] clockwise Nonzero to emit clockwise winding.
 * @param[in] x Cap origin x coordinate.
 * @param[in] y Cap origin y coordinate.
 * @param[in] z Cap origin height.
 * @param[in] normalX Outward normal x component.
 * @param[in] normalY Outward normal y component.
 * @param[out] vertices Buffer receiving generated vertex coordinates.
 * @param[out] texCoords Buffer receiving generated texture coordinates.
 * @return Number of generated vertices.
 */
unsigned int
TrackSceneTestGeneratePitCap(int clockwise, tdble x, tdble y, tdble z,
		tdble normalX, tdble normalY, float *vertices, float *texCoords)
{
	tTexElt texture = {};
	t3Dd normal = { normalX, normalY, 0.0 };
	unsigned int vertexCount = 0;
	texture.name = const_cast<char *>("test.rgb");
	trackvertices = vertices;
	tracktexcoord = texCoords;

	if (clockwise) {
		pitCapCW(&texture, vertexCount, x, y, z, normal);
	} else {
		pitCapCCW(&texture, vertexCount, x, y, z, normal);
	}
	return vertexCount;
}
#endif
