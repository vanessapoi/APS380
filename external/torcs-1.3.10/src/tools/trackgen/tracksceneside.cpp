/***************************************************************************

    file         : tracksceneside.cpp
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

/** @brief Emit one side-surface cross-section with mirrored texture orientation.
 * @param[in,out] scene Scene output state.
 * @param[in] side Track side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 * @param[in] texLen Longitudinal texture distance.
 * @param[in] texMaxT Texture span across the side width.
 * @param[in] outerX Outer-edge X coordinate.
 * @param[in] outerY Outer-edge Y coordinate.
 * @param[in] outerZ Outer-edge height.
 * @param[in] innerX Inner-edge X coordinate.
 * @param[in] innerY Inner-edge Y coordinate.
 * @param[in] innerZ Inner-edge height.
 */
static void
emitSideCrossSection(tTrackSceneContext &scene, int side, tdble texLen,
		tdble texMaxT, tdble outerX, tdble outerY, tdble outerZ,
		tdble innerX, tdble innerY, tdble innerZ)
{
	const tdble texS = trackSceneTexS(side, texLen);
	const bool rightSide = side == TR_SIDE_RGT;
	setPoint(scene.curTexElt, texS, rightSide ? 0 : texMaxT,
			outerX, outerY, outerZ, scene.nbvert);
	setPoint(scene.curTexElt, texS, rightSide ? texMaxT : 0,
			innerX, innerY, innerZ, scene.nbvert);
}

/** @brief Resolve and emit one sampled side-surface cross-section.
 * @param[in,out] scene Scene output state.
 * @param[in,out] trkpos Local track position updated during resolution.
 * @param[in] side Track side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 * @param[in] width Side width at the sampled position.
 * @param[in] texLen Longitudinal texture distance.
 * @param[in] texMaxT Texture span across the side width.
 */
static void
emitSideSample(tTrackSceneContext &scene, tTrkLocPos &trkpos, int side,
		tdble width, tdble texLen, tdble texMaxT)
{
	tdble outerX, outerY, innerX, innerY;
	trkpos.toRight = width;
	RtTrackLocal2Global(&trkpos, &outerX, &outerY, TR_TORIGHT);
	const tdble outerZ = RtTrackHeightL(&trkpos);
	trkpos.toRight = 0;
	RtTrackLocal2Global(&trkpos, &innerX, &innerY, TR_TORIGHT);
	const tdble innerZ = RtTrackHeightL(&trkpos);
	emitSideCrossSection(scene, side, texLen, texMaxT,
			outerX, outerY, outerZ, innerX, innerY, innerZ);
}

/** @brief Generate the textured outer side surface for one track side.
 *
 * Traverses each available side segment, following the outer link when a
 * border occupies the inner link. Straight and curved segments are sampled at
 * `scene.trackStep` intervals. Width or link transitions start new strips,
 * while left/right texture orientation and vertex order remain mirrored.
 *
 * @param[in,out] scene Scene context and output buffers updated by generation.
 * @param[in] side Track side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 */
void
generateSide(tTrackSceneContext &scene, int side)
{
	int i;
	tTrackSeg *seg;
	tTrackSeg *mseg;
	tdble width;
	tdble anz, ts = 0;
	tdble step;
	tTrkLocPos trkpos;
	tdble texLen;
	tdble texStep;
	tdble texMaxT = 0;
	tdble curTexSeg;
	tdble runninglentgh;
	int hasBorder;
	const int sideType = side == TR_SIDE_RGT ? TR_RSIDE : TR_LSIDE;
	const char *name = side == TR_SIDE_RGT ? "tkRS" : "tkLS";

	trkpos.type = TR_LPOS_MAIN;

	scene.prevTexId = 0;
	texLen = 0;
	scene.startNeeded = 1;
	runninglentgh = 0;
	hasBorder = 0;
	for (i = 0, mseg = scene.track->seg->next; i < scene.track->nseg; i++, mseg = mseg->next) {
		if ((mseg->side[side] != NULL) &&
		        ((mseg->side[side]->type2 == sideType) || (mseg->side[side]->side[side] != NULL))) {
			seg = mseg->side[side];
			if (seg->side[side] != NULL) {
				seg = seg->side[side];
				if (hasBorder == 0) {
					scene.startNeeded = 1;
					hasBorder = 1;
				} else if (mseg->side[side]->width != mseg->prev->side[side]->width) {
					// If border width changes we need a new start as well
					scene.startNeeded = 1;
				}
			} else {
				if (hasBorder) {
					scene.startNeeded = 1;
					hasBorder = 0;
				}
			}
			checkDispList(scene, seg->surface->material, name, i, mseg->lgfromstart);

			if (!scene.curTexLink) {
				curTexSeg = 0;
			} else {
				curTexSeg = mseg->lgfromstart;
			}
			curTexSeg += scene.curTexOffset;
			texLen = curTexSeg / scene.curTexSize;
			if (scene.startNeeded || (runninglentgh > LG_STEP_MAX)) {
				newDispList(scene, 0, name, i);

				runninglentgh = 0;
				ts = 0;

				width = RtTrackGetWidth(seg, ts);
				texMaxT = (scene.curTexType == 1 ? width / scene.curTexSize : 1.0 + floor(width / scene.curTexSize));

				emitSideCrossSection(scene, side, texLen, texMaxT,
						seg->vertex[TR_SL].x, seg->vertex[TR_SL].y, seg->vertex[TR_SL].z,
						seg->vertex[TR_SR].x, seg->vertex[TR_SR].y, seg->vertex[TR_SR].z);
			}

			switch (seg->type) {
				case TR_STR:
					ts = scene.trackStep;
					texStep = scene.trackStep / scene.curTexSize;
					texLen += texStep;
					trkpos.seg = seg;
					while (ts < seg->length) {
						trkpos.toStart = ts;

						width = RtTrackGetWidth(seg, ts);
						texMaxT = (scene.curTexType == 1 ? width / scene.curTexSize : 1.0 + floor(width / scene.curTexSize));

						emitSideSample(scene, trkpos, side, width, texLen, texMaxT);

						ts += scene.trackStep;
						texLen += texStep;
					}
					ts = seg->length;
					break;
				case TR_LFT:
				case TR_RGT:
				{
					const int turnSign = seg->type == TR_LFT ? 1 : -1;
					step = scene.trackStep / (seg->type == TR_LFT ? mseg->radiusr : mseg->radiusl);
					texStep = step * mseg->radius / scene.curTexSize;
					anz = seg->angle[TR_ZS] + turnSign * step;
					ts = step;
					texLen += texStep;
					trkpos.seg = seg;
					while (turnSign * anz < turnSign * seg->angle[TR_ZE]) {
						trkpos.toStart = ts;
						width = RtTrackGetWidth(seg, ts);
						texMaxT = (scene.curTexType == 1 ? width / scene.curTexSize : 1.0 + floor(width / scene.curTexSize));

						emitSideSample(scene, trkpos, side, width, texLen, texMaxT);

						ts += step;
						texLen += texStep;
						anz += turnSign * step;
					}
					ts = seg->arc;
					break;
				}
			}
			texLen = (curTexSeg + mseg->length) / scene.curTexSize;

			width = RtTrackGetWidth(seg, ts);
			texMaxT = (scene.curTexType == 1 ? width / scene.curTexSize : 1.0 + floor(width / scene.curTexSize));

			emitSideCrossSection(scene, side, texLen, texMaxT,
					seg->vertex[TR_EL].x, seg->vertex[TR_EL].y, seg->vertex[TR_EL].z,
					seg->vertex[TR_ER].x, seg->vertex[TR_ER].y, seg->vertex[TR_ER].z);

			scene.startNeeded = 0;
			runninglentgh += seg->length;
		} else {
			scene.startNeeded = 1;
		}
	}
}
