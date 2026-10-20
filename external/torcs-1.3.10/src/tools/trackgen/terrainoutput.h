/***************************************************************************

    file                 : terrainoutput.h
    created              : Sat Aug  1 2026
    copyright            : (C) 2002-2026 by Eric Espié, Bernhard Wymann
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

#ifndef _TERRAINOUTPUT_H_
#define _TERRAINOUTPUT_H_

#include <stdio.h>

#include "easymesh.h"

struct TerrainDomain;

typedef struct TerrainVertex {
	double x;
	double y;
	double z;
} tTerrainVertex;

typedef struct TerrainReference {
	int vertexIndex;
	double u;
	double v;
} tTerrainReference;

typedef struct TerrainSurface {
	tTerrainReference references[3];
} tTerrainSurface;

typedef struct TerrainGroup {
	int vertexCount;
	int vertexCapacity;
	tTerrainVertex *vertices;
	int surfaceCount;
	int surfaceCapacity;
	tTerrainSurface *surfaces;
} tTerrainGroup;

class TerrainOutput
{
public:
	TerrainOutput();
	~TerrainOutput();
	void configure(float groupSize, float xOffset, float yOffset,
	               int columnCount, int groupCount, const char *textureName,
	               double textureSize, bool preciseCoordinates);
	void append(const EasyMesh &mesh, const TerrainDomain *domain = NULL);
	void write(FILE *acFile, const char *name) const;

private:
	TerrainOutput(const TerrainOutput &);
	TerrainOutput &operator=(const TerrainOutput &);
	void releaseGroups();

	tTerrainGroup *Groups;
	int ActiveGroupCount;
	float GroupSize;
	float GroupXOffset;
	float GroupYOffset;
	int GroupColumnCount;
	int GroupCount;
	const char *TextureName;
	double TextureSize;
	bool PreciseCoordinates;

	void insertElement(const tMeshElement *element, const tMeshNode *nodes);
};

#endif /* _TERRAINOUTPUT_H_ */
