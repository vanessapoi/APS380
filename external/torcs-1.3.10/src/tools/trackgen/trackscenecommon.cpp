/***************************************************************************

    file         : trackscenecommon.cpp
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

/** @brief Allocate the next process-local texture identifier.
 * @return A unique, monotonically increasing texture identifier.
 */
static unsigned int newTextureId()
{
	static unsigned int GenTexId = 1;
	return GenTexId++;
}




/** @brief Select or register a texture-name combination.
 *
 * Texture entries are identified by their base, bump, and raceline names. A
 * missing combination is allocated and inserted into the circular texture
 * list; an existing combination is reused.
 *
 * @param[in,out] texList Head of the circular texture list.
 * @param[out] curTexElt Selected or newly allocated texture entry.
 * @param[out] curTexId Identifier of the selected texture entry.
 * @param[in] texname Base texture filename.
 * @param[in] texnamebump Bump texture filename, or an empty string.
 * @param[in] texnameraceline Raceline texture filename, or an empty string.
 */
static void setTexture(tTexElt **texList, tTexElt **curTexElt, unsigned int &curTexId, const char *texname, const char *texnamebump, const char *texnameraceline)
{
	int found = 0;
	*curTexElt = *texList;

	// First time, create first texture
	if (*curTexElt == NULL) {
		*curTexElt = (tTexElt *)calloc(1, sizeof(tTexElt));
		(*curTexElt)->next = *curTexElt;
		*texList = *curTexElt;
		(*curTexElt)->name = strdup(texname);
		(*curTexElt)->namebump = strdup(texnamebump);
		(*curTexElt)->nameraceline = strdup(texnameraceline);

		(*curTexElt)->texid = newTextureId();
	} else {
		// Search for texture, already registered?
		do {
			if (
				strcmp(texname, (*curTexElt)->name) == 0 &&
				strcmp(texnamebump, (*curTexElt)->namebump) == 0 &&
				strcmp(texnameraceline, (*curTexElt)->nameraceline) == 0
			) {
				found = 1;
				break;
			}
			if (*curTexElt == (*curTexElt)->next) {
				break;
			}
			*curTexElt = (*curTexElt)->next;
		} while (true);

		if (!found) {
			// Texture not known, register, insert new element on head
			*curTexElt = (tTexElt *)calloc(1, sizeof(tTexElt));
			(*curTexElt)->next = *texList;
			*texList = *curTexElt;
			(*curTexElt)->name = strdup(texname);
			(*curTexElt)->namebump = strdup(texnamebump);
			(*curTexElt)->nameraceline = strdup(texnameraceline);
			(*curTexElt)->texid = newTextureId();
		}
	}
	curTexId = (*curTexElt)->texid;
}




/** @brief Start a display-list range at the current vertex position.
 *
 * Finalizes a non-empty current range before appending a new range to the
 * selected group. If the current range is still empty, only its texture is
 * updated. Bump generation is skipped when the texture has no bump map.
 *
 * @param[in] texchange Non-zero when the caller requires a new strip start.
 * @param[in,out] scene Scene display-list and texture state.
 * @param[in] name Display-list object name.
 * @param[in] id Group index receiving the display-list range.
 */
void
newDispList(tTrackSceneContext &scene, int texchange, const char *name, int id)
{
	tDispElt *aDispElt;

	if (!scene.bump || (*(scene.curTexElt->namebump) != 0)) {
		if (scene.curDispElt != NULL) {
			scene.startNeeded = texchange;
			if (scene.curDispElt->start != scene.nbvert) {
				scene.curDispElt->nb = scene.nbvert - scene.curDispElt->start;
				scene.curDispElt = aDispElt = (tDispElt *)malloc(sizeof(tDispElt));
				aDispElt->start = scene.nbvert;
				aDispElt->nb = 0;
				aDispElt->name = strdup(name);
				aDispElt->id = id;
				aDispElt->texture = scene.curTexElt;
				if (Groups[id].nb == 0) {
					ActiveGroups++;
					aDispElt->next = aDispElt;
					Groups[id].dispList = aDispElt;
				} else {
					aDispElt->next = Groups[id].dispList->next;
					Groups[id].dispList->next = aDispElt;
					Groups[id].dispList = aDispElt;
				}
				Groups[id].nb++;
			} else {
				scene.curDispElt->texture = scene.curTexElt;
			}
		} else {
			scene.curDispElt = aDispElt = (tDispElt *)malloc(sizeof(tDispElt));
			aDispElt->start = scene.nbvert;
			aDispElt->nb = 0;
			aDispElt->name = strdup(name);
			aDispElt->id = id;
			aDispElt->texture = scene.curTexElt;
			aDispElt->next = aDispElt;
			Groups[id].dispList = aDispElt;
			Groups[id].nb++;
			ActiveGroups++;
		}
	}
}




/** @brief Select a material texture and start a display list when it changes.
 *
 * Resolves the material path according to the track format version, registers
 * its base, bump, and raceline textures, and updates texture mapping settings.
 * A texture change or requested strip start opens a new display-list range.
 * Test builds with a null parameter handle use deterministic texture defaults.
 *
 * @param[in,out] scene Scene texture and display-list state.
 * @param[in] mat Surface material name.
 * @param[in] name Display-list object name.
 * @param[in] id Group index receiving a new display-list range.
 * @param[in] off Longitudinal material offset.
 */
void
checkDispList(tTrackSceneContext &scene, const char *mat,
		const char *name, int id, tdble off)
{
	const char *texname;
	const char *texnamebump;
	const char *texnameraceline;
	const int BUFSIZE = 256;
	char path_[BUFSIZE];

#ifdef TRACKSCENE_TEST
	if (scene.trackHandle == NULL) {
		setTexture(&scene.texList, &scene.curTexElt, scene.curTexId, "test.rgb", "", "");
		if ((scene.curTexId != scene.prevTexId) || scene.startNeeded) {
			scene.curTexType = 1;
			scene.curTexLink = 1;
			scene.curTexOffset = 0;
			scene.curTexSize = 20.0;
			scene.prevTexId = scene.curTexId;
			newDispList(scene, 1, name, id);
		}
		return;
	}
#endif

	if (scene.track->version < 4) {
		snprintf(path_, BUFSIZE, "%s/%s/%s", TRK_SECT_SURFACES, TRK_LST_SURF, mat);
	} else {
		snprintf(path_, BUFSIZE, "%s/%s", TRK_SECT_SURFACES, mat);
	}
	texnamebump = GfParmGetStr(scene.trackHandle, path_, TRK_ATT_BUMPNAME, "");
	texnameraceline = GfParmGetStr(scene.trackHandle, path_, TRK_ATT_RACELINENAME, "");
	texname = GfParmGetStr(scene.trackHandle, path_, TRK_ATT_TEXTURE, "tr-asphalt.rgb");
	setTexture(&scene.texList, &scene.curTexElt, scene.curTexId, texname, texnamebump, texnameraceline);
	if ((scene.curTexId != scene.prevTexId) || scene.startNeeded) {
		const char *textype;
		if (scene.bump) {
			scene.curTexType = 1;
			scene.curTexLink = 1;
			scene.curTexOffset = -off;
			scene.curTexSize = GfParmGetNum(scene.trackHandle, path_, TRK_ATT_BUMPSIZE, (char *)NULL, 20.0);
		} else {
			textype = GfParmGetStr(scene.trackHandle, path_, TRK_ATT_TEXTYPE, "continuous");
			if (strcmp(textype, "continuous") == 0) {
				scene.curTexType = 1;
			} else {
				scene.curTexType = 0;
			}

			textype = GfParmGetStr(scene.trackHandle, path_, TRK_ATT_TEXLINK, TRK_VAL_YES);
			if (strcmp(textype, TRK_VAL_YES) == 0) {
				scene.curTexLink = 1;
			} else {
				scene.curTexLink = 0;
			}

			textype = GfParmGetStr(scene.trackHandle, path_, TRK_ATT_TEXSTARTBOUNDARY, TRK_VAL_NO);
			if (strcmp(textype, TRK_VAL_YES) == 0) {
				scene.curTexOffset = -off;
			} else {
				scene.curTexOffset = 0;
			}

			scene.curTexSize = GfParmGetNum(scene.trackHandle, path_, TRK_ATT_TEXSIZE, (char *)NULL, 20.0);
		}

		scene.prevTexId = scene.curTexId;
		newDispList(scene, 1, name, id);
	}
}




/** @brief Select a texture by basename and start a display list if required.
 *
 * Appends the `.rgb` extension before selecting the texture. No bump or
 * raceline texture is associated with the entry.
 *
 * @param[in,out] scene Scene texture and display-list state.
 * @param[in] texture Texture basename without an extension.
 * @param[in] name Display-list object name.
 * @param[in] id Group index receiving a new display-list range.
 */
void
checkDispList2(tTrackSceneContext &scene, const char *texture,
		const char *name, int id)
{
	const int TEXNAMESIZE = 256;
	char texname[TEXNAMESIZE];
	snprintf(texname, TEXNAMESIZE, "%s.rgb", texture);
	setTexture(&scene.texList, &scene.curTexElt, scene.curTexId, texname, "", "");
	if ((scene.curTexId != scene.prevTexId) || scene.startNeeded) {
		scene.prevTexId = scene.curTexId;
		newDispList(scene, 1, name, id);
	}
}




/** @brief Select a texture filename and start a display list if required.
 *
 * Uses the supplied filename unchanged and associates no bump or raceline
 * texture with the entry.
 *
 * @param[in,out] scene Scene texture and display-list state.
 * @param[in] texture Complete texture filename.
 * @param[in] name Display-list object name.
 * @param[in] id Group index receiving a new display-list range.
 */
void
checkDispList3(tTrackSceneContext &scene, const char *texture,
		const char *name, int id)
{
	setTexture(&scene.texList, &scene.curTexElt, scene.curTexId, texture, "", "");
	if ((scene.curTexId != scene.prevTexId) || scene.startNeeded) {
		scene.prevTexId = scene.curTexId;
		newDispList(scene, 1, name, id);
	}
}




/** @brief Append one textured vertex to the track-scene buffers.
 *
 * Empty texture names suppress emission. Otherwise the texture coordinate,
 * position, and matching sequential index are written at `nbvert`, which is
 * then incremented.
 *
 * @param[in] curTexElt Texture controlling whether the point is emitted.
 * @param[in] t1 Texture S coordinate.
 * @param[in] t2 Texture T coordinate.
 * @param[in] x World X coordinate.
 * @param[in] y World Y coordinate.
 * @param[in] z World Z coordinate.
 * @param[in,out] nbvert Current vertex count and destination index.
 */
void setPoint(tTexElt *curTexElt, float t1, float t2, float x, float y, float z, unsigned int &nbvert)
{
	if (*(curTexElt->name) != 0) {
		tracktexcoord[2*nbvert]   = t1;
		tracktexcoord[2*nbvert+1] = t2;
		trackvertices[3*nbvert]   = x;
		trackvertices[3*nbvert+1] = y;
		trackvertices[3*nbvert+2] = z;
		trackindices[nbvert]      = nbvert;
		++nbvert;
	}
}

/** @brief Convert longitudinal distance to the side-specific texture coordinate.
 *
 * Right-side textures run in the opposite direction to left-side textures.
 *
 * @param[in] side Track side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 * @param[in] texLen Longitudinal texture distance.
 * @return Texture S coordinate preserving the existing side orientation.
 */
tdble
trackSceneTexS(int side, tdble texLen)
{
	return side == TR_SIDE_RGT ? 1.0 - texLen : texLen;
}

/** @brief Emit one mirrored three-layer wall cross-section.
 *
 * Layer 0 emits the outer face, layer 1 the top, and layer 2 the inner face.
 * The side mirrors texture T coordinates without changing point order. Outer
 * and inner base heights are independent so borders can follow sloped terrain;
 * barriers pass the same height for both edges to preserve legacy geometry.
 *
 * @param[in,out] scene Scene output state.
 * @param[in] side Track side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 * @param[in] layer Wall surface layer in the range 0 to 2.
 * @param[in] texLen Longitudinal texture distance.
 * @param[in] outerX Outer-edge X coordinate.
 * @param[in] outerY Outer-edge Y coordinate.
 * @param[in] outerZ Outer-edge base height.
 * @param[in] innerX Inner-edge X coordinate.
 * @param[in] innerY Inner-edge Y coordinate.
 * @param[in] innerZ Inner-edge base height.
 * @param[in] height Wall height above each edge's base height.
 */
void
emitWallCrossSection(tTrackSceneContext &scene, int side, int layer,
		tdble texLen, tdble outerX, tdble outerY, tdble outerZ,
		tdble innerX, tdble innerY, tdble innerZ, tdble height)
{
	const tdble rightT[] = { 0.0, 0.33, 0.66, 1.0 };
	const tdble leftT[] = { 1.0, 0.66, 0.33, 0.0 };
	const bool rightSide = side == TR_SIDE_RGT;
	const tdble texS = trackSceneTexS(side, texLen);
	const tdble firstT = rightSide ? rightT[layer] : leftT[layer];
	const tdble secondT = rightSide ? rightT[layer + 1] : leftT[layer + 1];

	if (layer == 0) {
		setPoint(scene.curTexElt, texS, firstT,
				outerX, outerY, outerZ, scene.nbvert);
		setPoint(scene.curTexElt, texS, secondT,
				outerX, outerY, outerZ + height, scene.nbvert);
	} else if (layer == 1) {
		setPoint(scene.curTexElt, texS, firstT,
				outerX, outerY, outerZ + height, scene.nbvert);
		setPoint(scene.curTexElt, texS, secondT,
				innerX, innerY, innerZ + height, scene.nbvert);
	} else {
		setPoint(scene.curTexElt, texS, firstT,
				innerX, innerY, innerZ + height, scene.nbvert);
		setPoint(scene.curTexElt, texS, secondT,
				innerX, innerY, innerZ, scene.nbvert);
	}
}

/** @brief Emit a mirrored wall transition cap without changing point order.
 *
 * The side selects the cap winding and texture T direction. Callers provide
 * the already-oriented texture S coordinate because start and end caps apply
 * different longitudinal offsets before emission.
 *
 * @param[in,out] scene Scene output state.
 * @param[in] side Track side (`TR_SIDE_LFT` or `TR_SIDE_RGT`).
 * @param[in] texS Oriented longitudinal texture coordinate.
 * @param[in] x Cap base X coordinate.
 * @param[in] y Cap base Y coordinate.
 * @param[in] z Cap base height.
 * @param[in] height Wall height above the cap base.
 */
void
emitWallCap(tTrackSceneContext &scene, int side, tdble texS,
		tdble x, tdble y, tdble z, tdble height)
{
	const bool rightSide = side == TR_SIDE_RGT;
	setPoint(scene.curTexElt, texS, rightSide ? 0.66 : 1.0,
			x, y, z + (rightSide ? height : 0), scene.nbvert);
	setPoint(scene.curTexElt, texS, rightSide ? 1.0 : 0.66,
			x, y, z + (rightSide ? 0 : height), scene.nbvert);
}

/** @brief Estimate the vertex-buffer capacity required for a track scene.
 *
 * Counts longitudinal samples for every main segment, scales for the worst
 * combination of borders and barriers, then reserves space for the start
 * bridge, pit buildings, and a fixed safety margin.
 *
 * @param[in] track Track whose segments and pit count determine the estimate.
 * @param[in] trackStep Longitudinal sampling distance.
 * @return Conservative number of vertices to allocate.
 */
unsigned int
countTrackVertices(tTrack *track, tdble trackStep)
{
	unsigned int nbvert = 0;
	tTrackSeg *seg;
	int i;

	for (i = 0, seg = track->seg->next; i < track->nseg; i++, seg = seg->next) {
		nbvert++;
		switch (seg->type) {
			case TR_STR:
				nbvert += (int)(seg->length / trackStep);
				break;
			case TR_LFT:
				nbvert += (int)(seg->arc * seg->radiusr / trackStep);
				break;
			case TR_RGT:
				nbvert += (int)(seg->arc * seg->radiusl / trackStep);
				break;
		}
	}

	nbvert++;
	// Worst case (walls as barrier plus wall on each side -> (4*4 + 3*2)*2), can be less
	// 4*4: 4 Walls, 4 vertices per slice, and 3 flat surfaces, 2 vertices per slice,
	// *2: beginning and end (in worst case).
	nbvert *= 44;
	nbvert += 58; /* start bridge */
	nbvert += 12 + 10 * track->pits.driversPitsNb;
	nbvert += 10000; /* safety margin */
	return nbvert;
}
