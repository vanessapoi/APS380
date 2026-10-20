/***************************************************************************

    file         : tracksceneborder.cpp
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

/** @brief Select a texture coordinate from a mirrored left/right pair.
 *
 * @param[in] side Border side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 * @param[in] rightValue Value used for a right-side border.
 * @param[in] leftValue Value used for a left-side border.
 * @return The value corresponding to `side`.
 */
static tdble
borderTexT(int side, tdble rightValue, tdble leftValue)
{
	return side == TR_SIDE_RGT ? rightValue : leftValue;
}

/** @brief Emit one longitudinal cross-section for a border surface layer.
 *
 * The outer point is `TR_SL`/`TR_EL` and the inner point is
 * `TR_SR`/`TR_ER` in the border segment's local orientation. The side selects
 * mirrored heights and texture coordinates without changing vertex order.
 * Plan borders use layer 0, curbs use layers 0 and 1, and walls use all three
 * layers for their outer face, top, and inner face.
 *
 * @param[in,out] scene Scene output state.
 * @param[in] seg Border segment defining style and height.
 * @param[in] side Border side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 * @param[in] layer Border surface layer in the range 0 to 2.
 * @param[in] texLen Longitudinal texture distance.
 * @param[in] texMaxT Texture span across the border width.
 * @param[in] outerX Outer-edge X coordinate.
 * @param[in] outerY Outer-edge Y coordinate.
 * @param[in] outerZ Outer-edge base height.
 * @param[in] innerX Inner-edge X coordinate.
 * @param[in] innerY Inner-edge Y coordinate.
 * @param[in] innerZ Inner-edge base height.
 */
static void
emitBorderCrossSection(tTrackSceneContext &scene, tTrackSeg *seg, int side,
		int layer, tdble texLen, tdble texMaxT, tdble outerX, tdble outerY,
		tdble outerZ, tdble innerX, tdble innerY, tdble innerZ)
{
	const tdble texS = trackSceneTexS(side, texLen);
	const tdble height = seg->height;

	switch (seg->style) {
		case TR_PLAN:
			if (layer == 0) {
				setPoint(scene.curTexElt, texS, borderTexT(side, 0, texMaxT),
						outerX, outerY, outerZ, scene.nbvert);
				setPoint(scene.curTexElt, texS, borderTexT(side, texMaxT, 0),
						innerX, innerY, innerZ, scene.nbvert);
			}
			break;
		case TR_CURB:
		{
			const int slopeLayer = side == TR_SIDE_RGT ? 0 : 1;
			const int verticalLayer = 1 - slopeLayer;
			if (layer == slopeLayer) {
				setPoint(scene.curTexElt, texS, borderTexT(side, 0, texMaxT),
						outerX, outerY, outerZ + (side == TR_SIDE_LFT ? height : 0), scene.nbvert);
				setPoint(scene.curTexElt, texS, borderTexT(side, texMaxT, 0),
						innerX, innerY, innerZ + (side == TR_SIDE_RGT ? height : 0), scene.nbvert);
			} else if (layer == verticalLayer && height > 0.0f) {
				const bool rightSide = side == TR_SIDE_RGT;
				setPoint(scene.curTexElt, texS, texMaxT,
						rightSide ? innerX : outerX, rightSide ? innerY : outerY,
						(rightSide ? innerZ + height : outerZ), scene.nbvert);
				setPoint(scene.curTexElt, texS, texMaxT,
						rightSide ? innerX : outerX, rightSide ? innerY : outerY,
						(rightSide ? innerZ : outerZ + height), scene.nbvert);
			}
			break;
		}
		case TR_WALL:
			emitWallCrossSection(scene, side, layer, texLen,
					outerX, outerY, outerZ, innerX, innerY, innerZ, height);
			break;
	}
}

/** @brief Resolve a sampled local position and emit its border cross-section.
 *
 * @param[in,out] scene Scene output state.
 * @param[in] seg Border segment being sampled.
 * @param[in,out] trkpos Local track position; `toRight` is updated.
 * @param[in] side Border side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 * @param[in] layer Border surface layer in the range 0 to 2.
 * @param[in] width Border width at the sampled position.
 * @param[in] texLen Longitudinal texture distance.
 * @param[in] texMaxT Texture span across the border width.
 */
static void
emitBorderSample(tTrackSceneContext &scene, tTrackSeg *seg, tTrkLocPos &trkpos,
		int side, int layer, tdble width, tdble texLen, tdble texMaxT)
{
	tdble outerX, outerY, innerX, innerY;
	trkpos.toRight = width;
	RtTrackLocal2Global(&trkpos, &outerX, &outerY, TR_TORIGHT);
	const tdble outerZ = RtTrackHeightL(&trkpos);
	trkpos.toRight = 0;
	RtTrackLocal2Global(&trkpos, &innerX, &innerY, TR_TORIGHT);
	const tdble innerZ = RtTrackHeightL(&trkpos);
	emitBorderCrossSection(scene, seg, side, layer, texLen, texMaxT,
			outerX, outerY, outerZ, innerX, innerY, innerZ);
}

/** @brief Generate textured border geometry for one side of the track.
 *
 * Traverses every main track segment and emits the matching left or right
 * border as longitudinal triangle strips. Plan borders use one surface layer,
 * curbs use two, and walls use three. Style transitions add start and end caps
 * while preserving the legacy rule that a missing next border has no end cap.
 *
 * @param[in,out] scene Scene context and output buffers updated by generation.
 * @param[in] side Border side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 */
void
generateBorders(tTrackSceneContext &scene, int side)
{
	int i, j;
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
	const int BUFSIZE = 256;
	char sname[BUFSIZE];
	const int borderType = side == TR_SIDE_RGT ? TR_RBORDER : TR_LBORDER;
	const char *nameFormat = side == TR_SIDE_RGT ? "t%dRB" : "t%dLB";

	trkpos.type = TR_LPOS_MAIN;

	for (j = 0; j < 3; j++) {
		scene.prevTexId = 0;
		texLen = 0;
		scene.startNeeded = 1;
		runninglentgh = 0;
		snprintf(sname, BUFSIZE, nameFormat, j);
		for (i = 0, mseg = scene.track->seg->next; i < scene.track->nseg; i++, mseg = mseg->next) {
			if ((mseg->side[side] != NULL) && (mseg->side[side]->type2 == borderType)) {
				seg = mseg->side[side];
				checkDispList(scene, seg->surface->material, sname, i, mseg->lgfromstart);
				if (!scene.curTexLink) {
					curTexSeg = 0;
				} else {
					curTexSeg = mseg->lgfromstart;
				}
				curTexSeg += scene.curTexOffset;
				texLen = curTexSeg / scene.curTexSize;
				if (scene.startNeeded || (runninglentgh > LG_STEP_MAX)) {
					newDispList(scene, 0, sname, i);
					runninglentgh = 0;
					ts = 0;

					width = RtTrackGetWidth(seg, ts);
					texMaxT = (scene.curTexType == 1 ? width / scene.curTexSize : 1.0 + floor(width / scene.curTexSize));

					const bool startsBorder = !mseg->prev->side[side] ||
							mseg->prev->side[side]->type2 != borderType ||
							mseg->prev->side[side]->style != seg->style;
					const int slopeLayer = side == TR_SIDE_RGT ? 0 : 1;
					const int innerWallLayer = side == TR_SIDE_RGT ? 2 : 0;
					const tdble texS = trackSceneTexS(side, texLen);
					// Start caps precede the regular section to preserve strip winding.
					if (startsBorder && seg->height > 0.0f && seg->style == TR_CURB && j == slopeLayer) {
						setPoint(scene.curTexElt, texS, borderTexT(side, 0, texMaxT),
								seg->vertex[TR_SL].x, seg->vertex[TR_SL].y,
								seg->vertex[TR_SL].z - (side == TR_SIDE_RGT ? 0.1 : 0.0), scene.nbvert);
						setPoint(scene.curTexElt, texS, borderTexT(side, texMaxT, 0),
								seg->vertex[TR_SR].x, seg->vertex[TR_SR].y,
								seg->vertex[TR_SR].z - (side == TR_SIDE_LFT ? 0.1 : 0.0), scene.nbvert);
					}
					if (startsBorder && seg->style == TR_WALL && j == innerWallLayer) {
						const bool rightSide = side == TR_SIDE_RGT;
						const t3Dd &vertex = seg->vertex[rightSide ? TR_SL : TR_SR];
						const tdble capTexS = trackSceneTexS(side, texLen - seg->width / scene.curTexSize);
						emitWallCap(scene, side, capTexS,
								vertex.x, vertex.y, vertex.z, seg->height);
					}
					emitBorderCrossSection(scene, seg, side, j, texLen, texMaxT,
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

							emitBorderSample(scene, seg, trkpos, side, j, width, texLen, texMaxT);

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

							emitBorderSample(scene, seg, trkpos, side, j, width, texLen, texMaxT);

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
				emitBorderCrossSection(scene, seg, side, j, texLen, texMaxT,
						seg->vertex[TR_EL].x, seg->vertex[TR_EL].y, seg->vertex[TR_EL].z,
						seg->vertex[TR_ER].x, seg->vertex[TR_ER].y, seg->vertex[TR_ER].z);

				const bool endsBorder = mseg->next->side[side] &&
						(mseg->next->side[side]->type2 != borderType ||
						mseg->next->side[side]->style != seg->style);
				const int slopeLayer = side == TR_SIDE_RGT ? 0 : 1;
				const int innerWallLayer = side == TR_SIDE_RGT ? 2 : 0;
				const tdble texS = trackSceneTexS(side, texLen);
				// A missing next border intentionally does not produce an end cap.
				if (endsBorder && seg->height > 0.0f && seg->style == TR_CURB && j == slopeLayer) {
					setPoint(scene.curTexElt, texS, borderTexT(side, 0, texMaxT),
							seg->vertex[TR_EL].x, seg->vertex[TR_EL].y,
							seg->vertex[TR_EL].z - (side == TR_SIDE_RGT ? 0.1 : 0.0), scene.nbvert);
					setPoint(scene.curTexElt, texS, borderTexT(side, texMaxT, 0),
							seg->vertex[TR_ER].x, seg->vertex[TR_ER].y,
							seg->vertex[TR_ER].z - (side == TR_SIDE_LFT ? 0.1 : 0.0), scene.nbvert);
				}
				if (endsBorder && seg->style == TR_WALL && j == innerWallLayer) {
					const bool rightSide = side == TR_SIDE_RGT;
					const t3Dd &vertex = seg->vertex[rightSide ? TR_EL : TR_ER];
					const tdble capTexS = trackSceneTexS(side, texLen + seg->width / scene.curTexSize);
					emitWallCap(scene, side, capTexS,
							vertex.x, vertex.y, vertex.z, seg->height);
				}

				scene.startNeeded = 0;
				runninglentgh += seg->length;
			} else {
				scene.startNeeded = 1;
			}
		}
	}
}
