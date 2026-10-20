/***************************************************************************

    file                 : terrainoutput.cpp
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

#include <stdio.h>
#include <stdlib.h>

#include <tgf.h>

#include "ac3d.h"
#include "easymesh_checks.h"
#include "terrain.h"
#include "terraindomain.h"
#include "elevation.h"
#include "terrainoutput.h"

/** Number of surfaces added whenever a terrain group grows. */
#define TERRAIN_SURFACE_CAPACITY_INCREMENT 100

/** Number of vertices added whenever a terrain group grows. */
#define TERRAIN_VERTEX_CAPACITY_INCREMENT 100


TerrainOutput::TerrainOutput()
:
	Groups(NULL),
	ActiveGroupCount(0),
	GroupSize(0.0f),
	GroupXOffset(0.0f),
	GroupYOffset(0.0f),
	GroupColumnCount(0),
	GroupCount(0),
	TextureName(NULL),
	TextureSize(0.0),
	PreciseCoordinates(false)
{
}


TerrainOutput::~TerrainOutput()
{
	releaseGroups();
}


void
TerrainOutput::releaseGroups()
{
	int groupIndex;

	if (Groups != NULL) {
		for (groupIndex = 0; groupIndex < GroupCount; groupIndex++) {
			free(Groups[groupIndex].vertices);
			free(Groups[groupIndex].surfaces);
		}
		free(Groups);
		Groups = NULL;
	}
	ActiveGroupCount = 0;
	GroupCount = 0;
}


void
TerrainOutput::configure(float groupSize, float xOffset, float yOffset,
                         int columnCount, int groupCount,
                         const char *textureName, double textureSize,
                         bool preciseCoordinates)
{
	releaseGroups();
	GroupSize = groupSize;
	GroupXOffset = xOffset;
	GroupYOffset = yOffset;
	GroupColumnCount = columnCount;
	GroupCount = groupCount;
	TextureName = textureName;
	TextureSize = textureSize;
	PreciseCoordinates = preciseCoordinates;
	Groups = (tTerrainGroup *)calloc(GroupCount, sizeof(tTerrainGroup));
	if (Groups == NULL) {
		GfFatal("Cannot allocate terrain output groups\n");
		exit(1);
	}
	ActiveGroupCount = 0;
}


/** @brief Reuse or append one node in a terrain output group.
    @param[in] node Mesh node to store.
    @param[in,out] group Terrain group receiving the node.
    @return Group-local vertex index.
 */
static int
insertTerrainGroupNode(const tMeshNode *node, tTerrainGroup *group)
{
	int vertexIndex;
	tTerrainVertex *resizedVertices;

	for (vertexIndex = 0; vertexIndex < group->vertexCount; vertexIndex++) {
		if ((group->vertices[vertexIndex].x == node->x) &&
		        (group->vertices[vertexIndex].y == node->y) &&
		        (group->vertices[vertexIndex].z == node->z)) {
			return vertexIndex;
		}
	}
	if (group->vertexCount == group->vertexCapacity) {
		group->vertexCapacity += TERRAIN_VERTEX_CAPACITY_INCREMENT;
		resizedVertices = (tTerrainVertex *)realloc(
		        group->vertices,
		        group->vertexCapacity * sizeof(tTerrainVertex));
		if (resizedVertices == NULL) {
			GfFatal("Cannot grow terrain group vertex storage\n");
			exit(1);
		}
		group->vertices = resizedVertices;
	}
	group->vertices[group->vertexCount].x = node->x;
	group->vertices[group->vertexCount].y = node->y;
	group->vertices[group->vertexCount].z = node->z;
	group->vertexCount++;
	return (group->vertexCount - 1);
}


/** @brief Add one non-collapsed, non-duplicate element to its output group.
    @param[in] element Renumbered element to store.
    @param[in] nodes Renumbered node array referenced by the element.
 */
void
TerrainOutput::insertElement(const tMeshElement *element,
                             const tMeshNode *nodes)
{
	int groupColumn;
	int groupIndex;
	int groupRow;
	int groupRowCount;
	int surfaceIndex;
	int vertexIndices[3];
	double centroidX, centroidY;
	tTerrainGroup *currentGroup;
	tTerrainSurface *currentSurface;
	tTerrainSurface *resizedSurfaces;

	if (element->nodeI < 0 || element->nodeJ < 0 || element->nodeK < 0) {
		return;
	}

	centroidX = (nodes[element->nodeI].x + nodes[element->nodeJ].x + nodes[element->nodeK].x) / 3.0;
	centroidY = (nodes[element->nodeI].y + nodes[element->nodeJ].y + nodes[element->nodeK].y) / 3.0;

	groupColumn = (int)((centroidX - GroupXOffset) / GroupSize);
	groupRow = (int)((centroidY - GroupYOffset) / GroupSize);
	groupRowCount = GroupCount / GroupColumnCount;
	if ((groupColumn < 0) || (groupColumn >= GroupColumnCount) ||
	        (groupRow < 0) || (groupRow >= groupRowCount)) {
		GfFatal("Terrain element lies outside configured output groups\n");
		exit(1);
	}
	groupIndex = groupColumn + GroupColumnCount * groupRow;

	currentGroup = &(Groups[groupIndex]);
	vertexIndices[0] = insertTerrainGroupNode(&(nodes[element->nodeI]), currentGroup);
	vertexIndices[1] = insertTerrainGroupNode(&(nodes[element->nodeJ]), currentGroup);
	vertexIndices[2] = insertTerrainGroupNode(&(nodes[element->nodeK]), currentGroup);
	if (!easyMeshTriangleHasDistinctVertices(
	        vertexIndices[0], vertexIndices[1], vertexIndices[2])) {
		return;
	}
	for (surfaceIndex = 0; surfaceIndex < currentGroup->surfaceCount; surfaceIndex++) {
		if (easyMeshTrianglesMatch(
		        vertexIndices[0], vertexIndices[1], vertexIndices[2],
		        currentGroup->surfaces[surfaceIndex].references[0].vertexIndex,
		        currentGroup->surfaces[surfaceIndex].references[1].vertexIndex,
		        currentGroup->surfaces[surfaceIndex].references[2].vertexIndex)) {
			return;
		}
	}

	if (currentGroup->surfaceCount == currentGroup->surfaceCapacity) {
		if (currentGroup->surfaceCount == 0) {
			ActiveGroupCount++;
		}
		currentGroup->surfaceCapacity += TERRAIN_SURFACE_CAPACITY_INCREMENT;
		resizedSurfaces = (tTerrainSurface *)realloc(
		        currentGroup->surfaces,
		        currentGroup->surfaceCapacity * sizeof(tTerrainSurface));
		if (resizedSurfaces == NULL) {
			GfFatal("Cannot grow terrain group surface storage\n");
			exit(1);
		}
		currentGroup->surfaces = resizedSurfaces;
	}
	currentSurface = &(currentGroup->surfaces[currentGroup->surfaceCount++]);

	currentSurface->references[0].u = nodes[element->nodeI].x / TextureSize;
	currentSurface->references[0].v = nodes[element->nodeI].y / TextureSize;
	currentSurface->references[1].u = nodes[element->nodeJ].x / TextureSize;
	currentSurface->references[1].v = nodes[element->nodeJ].y / TextureSize;
	currentSurface->references[2].u = nodes[element->nodeK].x / TextureSize;
	currentSurface->references[2].v = nodes[element->nodeK].y / TextureSize;

	currentSurface->references[0].vertexIndex = vertexIndices[0];
	currentSurface->references[1].vertexIndex = vertexIndices[1];
	currentSurface->references[2].vertexIndex = vertexIndices[2];
}


/** @brief Copy active topology into renumbered arrays and collect AC3D groups.
    @note Elevation-map sampling is applied to unconstrained and relief-marker
          nodes while the original Z value is retained for other constraints.
 */
static double
terrainOutputCross(double firstX, double firstY, double secondX, double secondY)
{
	return firstX * secondY - firstY * secondX;
}


static bool
terrainElementStrictlyContainsPoint(const tMeshElement &element,
	                              const tMeshNode *nodes,
	                              double x, double y)
{
	const tMeshNode &first = nodes[element.nodeI];
	const tMeshNode &second = nodes[element.nodeJ];
	const tMeshNode &third = nodes[element.nodeK];
	double firstCross = terrainOutputCross(
	        second.x - first.x, second.y - first.y, x - first.x, y - first.y);
	double secondCross = terrainOutputCross(
	        third.x - second.x, third.y - second.y, x - second.x, y - second.y);
	double thirdCross = terrainOutputCross(
	        first.x - third.x, first.y - third.y, x - third.x, y - third.y);
	return ((firstCross > 1e-10) && (secondCross > 1e-10) &&
	        (thirdCross > 1e-10)) ||
	       ((firstCross < -1e-10) && (secondCross < -1e-10) &&
	        (thirdCross < -1e-10));
}


static bool
terrainElementStaysInDomain(const tMeshElement &element,
	                       const tMeshNode *nodes,
	                       const TerrainDomain &domain)
{
	const int nodeIndices[3] = {element.nodeI, element.nodeJ, element.nodeK};
	double centroidX = 0.0;
	double centroidY = 0.0;
	int nodeIndex;
	for (nodeIndex = 0; nodeIndex < 3; nodeIndex++) {
		centroidX += nodes[nodeIndices[nodeIndex]].x / 3.0;
		centroidY += nodes[nodeIndices[nodeIndex]].y / 3.0;
	}
	if (!TerrainDomainCoversPoint(domain, centroidX, centroidY)) {
		return false;
	}
	for (nodeIndex = 0; nodeIndex < 3; nodeIndex++) {
		TerrainDomainSegment segment;
		const tMeshNode &start = nodes[nodeIndices[nodeIndex]];
		const tMeshNode &end = nodes[nodeIndices[(nodeIndex + 1) % 3]];
		segment.points[0].x = start.x;
		segment.points[0].y = start.y;
		segment.points[0].z = start.z;
		segment.points[0].spacing = 0.0;
		segment.points[0].marker = 0;
		segment.points[1].x = end.x;
		segment.points[1].y = end.y;
		segment.points[1].z = end.z;
		segment.points[1].spacing = 0.0;
		segment.points[1].marker = 0;
		if (!TerrainDomainContainsSegment(domain, segment)) {
			return false;
		}
	}
	for (size_t holeIndex = 0; holeIndex < domain.holes.size(); holeIndex++) {
		const TerrainDomainRing &hole = domain.holes[holeIndex];
		for (size_t pointIndex = 0; pointIndex < hole.points.size(); pointIndex++) {
			const TerrainDomainPoint &point = hole.points[pointIndex];
			const TerrainDomainPoint &nextPoint =
			        hole.points[(pointIndex + 1) % hole.points.size()];
			if (terrainElementStrictlyContainsPoint(
			        element, nodes, point.x, point.y) ||
			        terrainElementStrictlyContainsPoint(
			        element, nodes, (point.x + nextPoint.x) / 2.0,
			        (point.y + nextPoint.y) / 2.0)) {
				return false;
			}
		}
	}
	return true;
}


void
TerrainOutput::append(const EasyMesh &mesh, const TerrainDomain *domain)
{
	int elementIndex, nodeIndex;
	int renumberedElementCount = 0;
	const tMeshElement *elements = mesh.getElements();
	const tMeshNode *nodes = mesh.getNodes();
	int elementCount = mesh.getElementCount();
	int nodeCount = mesh.getNodeCount();
	tMeshNode *renumberedNodes;
	tMeshElement *renumberedElements;

	renumberedNodes = (tMeshNode *)calloc(nodeCount, sizeof(tMeshNode));
	renumberedElements = (tMeshElement *)calloc(elementCount, sizeof(tMeshElement));
	if ((renumberedNodes == NULL) || (renumberedElements == NULL)) {
		free(renumberedNodes);
		free(renumberedElements);
		GfFatal("Cannot allocate terrain output scratch storage\n");
		exit(1);
	}

	for (nodeIndex = 0; nodeIndex < nodeCount; nodeIndex++) {
		if (nodes[nodeIndex].marker != MISSING_MESH_INDEX && nodes[nodeIndex].outputIndex != MISSING_MESH_INDEX) {
			renumberedNodes[nodes[nodeIndex].outputIndex].x = nodes[nodeIndex].x;
			renumberedNodes[nodes[nodeIndex].outputIndex].y = nodes[nodeIndex].y;
			if ((nodes[nodeIndex].marker == 0) || (nodes[nodeIndex].marker == RELIEF_BOUNDARY_MARK)) {
				renumberedNodes[nodes[nodeIndex].outputIndex].z = GetElevation(nodes[nodeIndex].x, nodes[nodeIndex].y, nodes[nodeIndex].z);
			} else {
				renumberedNodes[nodes[nodeIndex].outputIndex].z = nodes[nodeIndex].z;
			}
			renumberedNodes[nodes[nodeIndex].outputIndex].marker = nodes[nodeIndex].marker;
		}
	}

	for (elementIndex = 0; elementIndex < elementCount; elementIndex++) {
		if (elements[elementIndex].marker != MISSING_MESH_INDEX && elements[elementIndex].outputIndex != MISSING_MESH_INDEX) {
			renumberedElementCount++;
			renumberedElements[elements[elementIndex].outputIndex].nodeI = nodes[elements[elementIndex].nodeI].outputIndex;
			renumberedElements[elements[elementIndex].outputIndex].nodeJ = nodes[elements[elementIndex].nodeJ].outputIndex;
			renumberedElements[elements[elementIndex].outputIndex].nodeK = nodes[elements[elementIndex].nodeK].outputIndex;
		}
	}

	for (elementIndex = 0; elementIndex < renumberedElementCount; elementIndex++) {
		const tMeshElement &element = renumberedElements[elementIndex];
		if ((element.nodeI < 0) || (element.nodeI >= nodeCount) ||
		        (element.nodeJ < 0) || (element.nodeJ >= nodeCount) ||
		        (element.nodeK < 0) || (element.nodeK >= nodeCount)) {
			continue;
		}
		if ((domain == NULL) || terrainElementStaysInDomain(
		        element, renumberedNodes, *domain)) {
			insertElement(&element, renumberedNodes);
		}
	}
	free(renumberedElements);
	free(renumberedNodes);
}


/** @brief Write all non-empty spatial terrain groups in AC3D format.
    @param[out] acFile Open AC3D stream receiving terrain objects.
    @param[in] name Group and object name prefix.
 */
void
TerrainOutput::write(FILE *acFile, const char *name) const
{
	int groupIndex, surfaceIndex, referenceIndex, vertexIndex;
	const tTerrainGroup *currentGroup;

	Ac3dGroup(acFile, name, ActiveGroupCount);

	for (groupIndex = 0; groupIndex < GroupCount; groupIndex++) {
		currentGroup = &(Groups[groupIndex]);
		if (currentGroup->surfaceCount == 0) {
			continue;
		}

		fprintf(acFile, "OBJECT poly\n");
		fprintf(acFile, "name \"%s%d\"\n", name, groupIndex);
		fprintf(acFile, "texture \"%s\"\n", TextureName);
		fprintf(acFile, "numvert %d\n", currentGroup->vertexCount);
		for (vertexIndex = 0; vertexIndex < currentGroup->vertexCount; vertexIndex++) {
			if (PreciseCoordinates) {
				fprintf(acFile, "%f %f %f\n",
				        currentGroup->vertices[vertexIndex].x,
				        currentGroup->vertices[vertexIndex].z,
				        -currentGroup->vertices[vertexIndex].y);
			} else {
				fprintf(acFile, "%g %g %g\n",
				        currentGroup->vertices[vertexIndex].x,
				        currentGroup->vertices[vertexIndex].z,
				        -currentGroup->vertices[vertexIndex].y);
			}
		}
		fprintf(acFile, "numsurf %d\n", currentGroup->surfaceCount);
		for (surfaceIndex = 0; surfaceIndex < currentGroup->surfaceCount; surfaceIndex++) {
			fprintf(acFile, "SURF 0x10\n");
			fprintf(acFile, "mat 0\n");
			fprintf(acFile, "refs 3\n");
			for (referenceIndex = 0; referenceIndex < 3; referenceIndex++) {
				fprintf(acFile, "%d %f %f\n",
				        currentGroup->surfaces[surfaceIndex].references[referenceIndex].vertexIndex,
				        currentGroup->surfaces[surfaceIndex].references[referenceIndex].u,
				        currentGroup->surfaces[surfaceIndex].references[referenceIndex].v);
			}
		}
		fprintf(acFile, "kids 0\n");
	}
}
