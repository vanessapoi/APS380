/***************************************************************************

    file         : trackscenemain.cpp
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

/** @brief Generate the textured main-track surface.
 *
 * Traverses every main segment and emits a longitudinal triangle strip from
 * the left edge to the right edge. Straight and curved segments are sampled
 * at approximately `scene.trackStep` intervals. Normal generation uses the material's
 * texture mapping settings; raceline generation maps one texture across the
 * track width and applies the requested width scale and lateral offset.
 * Display-list and texture state in the scene context are updated as material
 * changes and strip-length limits require new ranges.
 *
 * @param[in,out] scene Scene context and output buffers updated by generation.
 * @param[in] raceline Non-zero to generate raceline texture coordinates.
 * @param[in] rlWidthScale Scale applied to raceline lateral texture offsets.
 * @param[in] rlOffset Base lateral raceline texture offset.
 */
void
generateMainTrack(tTrackSceneContext &scene, int raceline, double rlWidthScale, double rlOffset)
{
	int i;
	tTrackSeg *seg;
	tdble width = scene.track->width;
	tdble anz, ts = 0;
	tdble step;
	tTrkLocPos trkpos;
	tdble x, y;
	tdble texLen;
	tdble texStep;
	tdble texMaxT = 0;
	tdble curTexSeg;
	tdble runninglentgh;

	trkpos.type = TR_LPOS_MAIN;

	/* Main track */
	scene.prevTexId = 0;
	texLen = 0;
	scene.startNeeded = 1;
	runninglentgh = 0;
	for (i = 0, seg = scene.track->seg->next; i < scene.track->nseg; i++, seg = seg->next) {
		checkDispList(scene, seg->surface->material, "tkMn", i, seg->lgfromstart);
		if (!scene.curTexLink) {
			curTexSeg = 0;
		} else {
			curTexSeg = seg->lgfromstart;
		}
		curTexSeg += scene.curTexOffset;

		if (raceline) {
			// Required if some smaller than width tiled texture is used.
			scene.curTexSize = seg->width;
		}

		texLen = curTexSeg / scene.curTexSize;

		if (scene.startNeeded || (runninglentgh > LG_STEP_MAX)) {
			newDispList(scene, 0, "tkMn", i);
			runninglentgh = 0;
			ts = 0;
			if (raceline) {
				// Required if some smaller than width tiled texture is used.
				texMaxT = 1.0;
			} else {
				// Normal case
				texMaxT = (scene.curTexType == 1 ? width / scene.curTexSize : 1.0 + floor(width / scene.curTexSize));
			}

			double rlto = getTexureOffset(seg->lgfromstart)/rlWidthScale;
			setPoint(scene.curTexElt, texLen, texMaxT - rlOffset + rlto, seg->vertex[TR_SL].x, seg->vertex[TR_SL].y, seg->vertex[TR_SL].z, scene.nbvert);
			setPoint(scene.curTexElt, texLen, 0.0 + rlOffset + rlto, seg->vertex[TR_SR].x, seg->vertex[TR_SR].y, seg->vertex[TR_SR].z, scene.nbvert);
		}

		switch (seg->type) {
			case TR_STR:
				ts = scene.trackStep;
				texStep = scene.trackStep / scene.curTexSize;
				trkpos.seg = seg;
				while (ts < seg->length) {
					texLen += texStep;
					trkpos.toStart = ts;

					trkpos.toRight = width;
					RtTrackLocal2Global(&trkpos, &x, &y, TR_TORIGHT);

					double rlto = getTexureOffset(seg->lgfromstart + ts)/rlWidthScale;
					setPoint(scene.curTexElt, texLen, texMaxT - rlOffset + rlto, x, y, RtTrackHeightL(&trkpos), scene.nbvert);

					trkpos.toRight = 0;
					RtTrackLocal2Global(&trkpos, &x, &y, TR_TORIGHT);

					setPoint(scene.curTexElt, texLen, 0.0 + rlOffset + rlto, x, y, RtTrackHeightL(&trkpos), scene.nbvert);

					ts += scene.trackStep;
				}
				ts = seg->length;
				break;
			case TR_LFT:
			case TR_RGT:
			{
				const int turnSign = seg->type == TR_LFT ? 1 : -1;
				step = scene.trackStep / (seg->type == TR_LFT ? seg->radiusr : seg->radiusl);
				texStep = step * seg->radius / scene.curTexSize;
				anz = seg->angle[TR_ZS] + turnSign * step;
				ts = step;
				trkpos.seg = seg;
				while (turnSign * anz < turnSign * seg->angle[TR_ZE]) {
					texLen += texStep;
					trkpos.toStart = ts;

					double rlto = getTexureOffset(seg->lgfromstart + ts*seg->radius)/rlWidthScale;
					/* left */
					trkpos.toRight = width;
					setPoint(scene.curTexElt, texLen, texMaxT - rlOffset + rlto, seg->center.x + turnSign * seg->radiusl * sin(anz), seg->center.y - turnSign * seg->radiusl * cos(anz), RtTrackHeightL(&trkpos), scene.nbvert);

					/* right */
					trkpos.toRight = 0;
					setPoint(scene.curTexElt, texLen, 0.0 + rlOffset + rlto, seg->center.x + turnSign * seg->radiusr * sin(anz), seg->center.y - turnSign * seg->radiusr * cos(anz), RtTrackHeightL(&trkpos), scene.nbvert);

					ts += step;
					anz += turnSign * step;
				}
				ts = seg->arc;
				break;
			}
		}
		texLen = (curTexSeg + seg->length) / scene.curTexSize;

		double rlto = getTexureOffset(seg->lgfromstart + seg->length)/rlWidthScale;
		setPoint(scene.curTexElt, texLen, texMaxT - rlOffset + rlto, seg->vertex[TR_EL].x, seg->vertex[TR_EL].y, seg->vertex[TR_EL].z, scene.nbvert);
		setPoint(scene.curTexElt, texLen, 0 + rlOffset + rlto, seg->vertex[TR_ER].x, seg->vertex[TR_ER].y, seg->vertex[TR_ER].z, scene.nbvert);

		scene.startNeeded = 0;
		runninglentgh += seg->length;
	}
}
