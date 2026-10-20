/***************************************************************************

    file         : tracksceneoutput.cpp
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

static void
saveObject(FILE *curFd, int nb, unsigned int start, char *texture, char *name)
{
	int	i, index;

	fprintf(curFd, "OBJECT poly\n");
	fprintf(curFd, "name \"%s\"\n", name);
	fprintf(curFd, "texture \"%s\"\n", texture);
	fprintf(curFd, "numvert %d\n", nb);

	for (i = 0; i < nb; i++) {
		const size_t vertexOffset = 3 * ((size_t)start + i);
		fprintf(curFd, "%f %f %f\n", trackvertices[vertexOffset], trackvertices[vertexOffset+2], -trackvertices[vertexOffset+1]);
	}

	fprintf(curFd, "numsurf %d\n", nb - 2);
	fprintf(curFd, "SURF 0x10\n");
	fprintf(curFd, "mat 0\n");
	fprintf(curFd, "refs 3\n");
	fprintf(curFd, "%d %f %f\n", 0, tracktexcoord[2*start], tracktexcoord[2*start+1]);
	fprintf(curFd, "%d %f %f\n", 1, tracktexcoord[2*(start+1)], tracktexcoord[2*(start+1)+1]);
	fprintf(curFd, "%d %f %f\n", 2, tracktexcoord[2*(start+2)], tracktexcoord[2*(start+2)+1]);

	/* triangle strip conversion to triangles */
	for (i = 2; i < nb-1; i++) {
		fprintf(curFd, "SURF 0x10\n");
		fprintf(curFd, "mat 0\n");
		fprintf(curFd, "refs 3\n");
		if ((i % 2) == 0) {
			index = i;
			fprintf(curFd, "%d %f %f\n", index, tracktexcoord[2*(start+index)], tracktexcoord[2*(start+index)+1]);
			index = i - 1;
			fprintf(curFd, "%d %f %f\n", index, tracktexcoord[2*(start+index)], tracktexcoord[2*(start+index)+1]);
			index = i + 1;
			fprintf(curFd, "%d %f %f\n", index, tracktexcoord[2*(start+index)], tracktexcoord[2*(start+index)+1]);
		} else {
			index = i - 1;
			fprintf(curFd, "%d %f %f\n", index, tracktexcoord[2*(start+index)], tracktexcoord[2*(start+index)+1]);
			index = i;
			fprintf(curFd, "%d %f %f\n", index, tracktexcoord[2*(start+index)], tracktexcoord[2*(start+index)+1]);
			index = i + 1;
			fprintf(curFd, "%d %f %f\n", index, tracktexcoord[2*(start+index)], tracktexcoord[2*(start+index)+1]);
		}
	}
	fprintf(curFd, "kids 0\n");
}


void
TrackSceneSave(FILE *curFd, int bump, int raceline)
{
	tDispElt		*aDispElt;
	const int BUFSIZE = 256;
	char		buf[BUFSIZE];
	int			i;

	for (i = 0; i < GroupNb; i++) {
		if (Groups[i].nb != 0) {
			aDispElt = Groups[i].dispList;
			snprintf(buf, BUFSIZE, "TKMN%d", i);
			Ac3dGroup(curFd, buf, Groups[i].nb);
			do {
				aDispElt = aDispElt->next;
				if (aDispElt->nb != 0) {
					snprintf(buf, BUFSIZE, "%s%d", aDispElt->name, aDispElt->id);
					if (bump) {
						saveObject(curFd, aDispElt->nb, aDispElt->start, aDispElt->texture->namebump, buf);
					} else if (raceline) {
						saveObject(curFd, aDispElt->nb, aDispElt->start, aDispElt->texture->nameraceline, buf);
					} else {
						saveObject(curFd, aDispElt->nb, aDispElt->start, aDispElt->texture->name, buf);
					}
				}
			} while (aDispElt != Groups[i].dispList);
		}
	}
}

#ifdef TRACKSCENE_TEST
void
TrackSceneTestSaveObject(FILE *file, int vertexCount, const float *vertices,
		const float *texCoords)
{
	trackvertices = const_cast<float *>(vertices);
	tracktexcoord = const_cast<float *>(texCoords);
	saveObject(file, vertexCount, 0, const_cast<char *>("test.rgb"),
			const_cast<char *>("test"));
}
#endif
