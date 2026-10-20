/***************************************************************************

    file         : trackscenebarrier.cpp
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

/** @brief Emit one fence or wall cross-section without changing vertex order.
 *
 * Wall offset vertices intentionally reuse the barrier-edge height. This
 * preserves the legacy vertical wall geometry on sloped terrain.
 *
 * @param[in,out] scene Scene output state.
 * @param[in] barrier Barrier style, width, and height.
 * @param[in] side Barrier side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 * @param[in] layer Surface layer in the range 0 to 2.
 * @param[in] texLen Longitudinal texture distance.
 * @param[in] edgeX Barrier-edge X coordinate.
 * @param[in] edgeY Barrier-edge Y coordinate.
 * @param[in] offsetX Width-offset X coordinate used by walls.
 * @param[in] offsetY Width-offset Y coordinate used by walls.
 * @param[in] baseHeight Barrier base height.
 */
static void
emitBarrierCrossSection(tTrackSceneContext &scene, tTrackBarrier *barrier,
		int side, int layer, tdble texLen, tdble edgeX, tdble edgeY,
		tdble offsetX, tdble offsetY, tdble baseHeight)
{
	const bool rightSide = side == TR_SIDE_RGT;
	const tdble texS = trackSceneTexS(side, texLen);
	const tdble top = baseHeight + barrier->height;

	if (barrier->style == TR_FENCE) {
		if (layer < 2) {
			const bool firstIsTop = rightSide ? layer == 1 : layer == 0;
			setPoint(scene.curTexElt, texS, firstIsTop ? 1.0 : 0.0,
					edgeX, edgeY, firstIsTop ? top : baseHeight, scene.nbvert);
			setPoint(scene.curTexElt, texS, firstIsTop ? 0.0 : 1.0,
					edgeX, edgeY, firstIsTop ? baseHeight : top, scene.nbvert);
		}
		return;
	}

	const tdble outerX = rightSide ? edgeX : offsetX;
	const tdble outerY = rightSide ? edgeY : offsetY;
	const tdble innerX = rightSide ? offsetX : edgeX;
	const tdble innerY = rightSide ? offsetY : edgeY;
	emitWallCrossSection(scene, side, layer, texLen,
			outerX, outerY, baseHeight, innerX, innerY, baseHeight, barrier->height);
}

/** @brief Resolve one sampled barrier section and emit its selected layer.
 * @param[in,out] scene Scene output state.
 * @param[in] seg Segment carrying the barrier geometry.
 * @param[in] barrier Barrier style, width, and height.
 * @param[in,out] trkpos Local track position updated during resolution.
 * @param[in] side Barrier side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 * @param[in] layer Surface layer in the range 0 to 2.
 * @param[in] texLen Longitudinal texture distance.
 * @param[in] toStart Distance or angle from the segment start.
 */
static void
emitBarrierSample(tTrackSceneContext &scene, tTrackSeg *seg,
		tTrackBarrier *barrier, tTrkLocPos &trkpos, int side, int layer,
		tdble texLen, tdble toStart)
{
	const bool rightSide = side == TR_SIDE_RGT;
	trkpos.toStart = toStart;
	trkpos.toRight = rightSide ? 0 : RtTrackGetWidth(seg, toStart);
	tdble edgeX, edgeY;
	RtTrackLocal2Global(&trkpos, &edgeX, &edgeY, TR_TORIGHT);
	const tdble baseHeight = RtTrackHeightL(&trkpos);
	trkpos.toRight += rightSide ? -barrier->width : barrier->width;
	tdble offsetX, offsetY;
	RtTrackLocal2Global(&trkpos, &offsetX, &offsetY, TR_TORIGHT);
	emitBarrierCrossSection(scene, barrier, side, layer, texLen,
			edgeX, edgeY, offsetX, offsetY, baseHeight);
}

/** @brief Generate textured barrier geometry for one side of the track.
 *
 * Traverses each main segment and emits fences as two opposite-facing layers
 * or walls as three layers. Wall style and height transitions receive caps;
 * geometry is suppressed where the selected side is occupied by a pit lane.
 *
 * @param[in,out] scene Scene context and output buffers updated by generation.
 * @param[in] side Barrier side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 */
void
generateBarriers(tTrackSceneContext &scene, int side)
{
	int i, j;
	tTrackSeg *seg;
	tTrackSeg *mseg;
	tdble anz, ts = 0;
	tdble step;
	tTrkLocPos trkpos;
	tTrackBarrier *curBarrier;
	tdble texLen;
	tdble texStep;
	tdble curTexSeg;
	tdble runninglentgh;
	const int BUFSIZE = 256;
	char sname[BUFSIZE];

	trkpos.type = TR_LPOS_MAIN;

	for (j = 0; j < 3; j++) {
		scene.prevTexId = 0;
		texLen = 0;
		scene.startNeeded = 1;
		runninglentgh = 0;
		snprintf(sname, BUFSIZE, side == TR_SIDE_RGT ? "B%dRt" : "B%dLt", j);
		for (i = 0, mseg = scene.track->seg->next; i < scene.track->nseg; i++, mseg = mseg->next) {
			if ((mseg->side[side] != NULL) && (mseg->side[side]->raceInfo & TR_PIT)) {
				runninglentgh = 0;
				newDispList(scene, 1, sname, i);
			} else {
				curBarrier = mseg->barrier[side];
				checkDispList(scene, curBarrier->surface->material, sname, i, mseg->lgfromstart);

				if (!scene.curTexLink) {
					curTexSeg = 0;
				} else {
					curTexSeg = mseg->lgfromstart;
				}
				curTexSeg += scene.curTexOffset;
				texLen = curTexSeg / scene.curTexSize;
				if (mseg->side[side]) {
					seg = mseg->side[side];
					if (seg->side[side]) {
						seg = seg->side[side];
					}
				} else {
					seg = mseg;
				}
				trkpos.seg = seg;
				if (scene.startNeeded || (runninglentgh > LG_STEP_MAX)) {
					newDispList(scene, 0, sname, i);
					runninglentgh = 0;
					if (scene.curTexType == 0) texLen = 0;
					const bool rightSide = side == TR_SIDE_RGT;
					const int edgeVertex = rightSide ? TR_SR : TR_SL;
					const t3Dd &edge = seg->vertex[edgeVertex];
					trkpos.toStart = 0;
					trkpos.toRight = rightSide ? -curBarrier->width :
							RtTrackGetWidth(seg, 0) + curBarrier->width;
					tdble offsetX, offsetY;
					RtTrackLocal2Global(&trkpos, &offsetX, &offsetY, TR_TORIGHT);
					const int capLayer = rightSide ? 2 : 0;
					const bool startsWall = mseg->prev->barrier[side]->style != TR_WALL ||
							mseg->prev->barrier[side]->height != curBarrier->height;
					if (curBarrier->style == TR_WALL && startsWall && j == capLayer) {
						const tdble capTexS = trackSceneTexS(side,
								texLen - curBarrier->width / scene.curTexSize);
						emitWallCap(scene, side, capTexS,
								edge.x, edge.y, edge.z, curBarrier->height);
					}
					emitBarrierCrossSection(scene, curBarrier, side, j, texLen,
							edge.x, edge.y, offsetX, offsetY, edge.z);
				}
				switch (seg->type) {
					case TR_STR:
						ts = scene.trackStep;
						texStep = scene.trackStep / scene.curTexSize;
						texLen += texStep;
						trkpos.seg = seg;
						while (ts < seg->length) {
							emitBarrierSample(scene, seg, curBarrier, trkpos, side, j, texLen, ts);
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
							emitBarrierSample(scene, seg, curBarrier, trkpos, side, j, texLen, ts);
							ts += step;
							texLen += texStep;
							anz += turnSign * step;
						}
						ts = seg->arc;
						break;
					}
				}
				texLen = (curTexSeg + mseg->length) / scene.curTexSize;
				const bool rightSide = side == TR_SIDE_RGT;
				const int edgeVertex = rightSide ? TR_ER : TR_EL;
				const t3Dd &edge = seg->vertex[edgeVertex];
				trkpos.toStart = ts;
				trkpos.toRight = rightSide ? -curBarrier->width :
						RtTrackGetWidth(seg, ts) + curBarrier->width;
				tdble offsetX, offsetY;
				RtTrackLocal2Global(&trkpos, &offsetX, &offsetY, TR_TORIGHT);
				emitBarrierCrossSection(scene, curBarrier, side, j, texLen,
						edge.x, edge.y, offsetX, offsetY, edge.z);

				const int capLayer = rightSide ? 2 : 0;
				const bool endsWall = mseg->next->barrier[side]->style != TR_WALL ||
						mseg->next->barrier[side]->height != curBarrier->height;
				if (curBarrier->style == TR_WALL && endsWall && j == capLayer) {
					const tdble capTexS = trackSceneTexS(side,
							texLen + curBarrier->width / scene.curTexSize);
					emitWallCap(scene, side, capTexS,
							edge.x, edge.y, edge.z, curBarrier->height);
				}
				scene.startNeeded = 0;
				runninglentgh += seg->length;
			}
		}
	}
}
