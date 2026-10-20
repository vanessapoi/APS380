/***************************************************************************

    file                 : easymesh_checks.h
    created              : Sun Jul 26 2026
    copyright            : (C) 2026 by Bernhard Wymann
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
    @brief Checked topology and refinement helpers shared with EasyMesh tests.
 */

#ifndef _EASYMESH_CHECKS_H_
#define _EASYMESH_CHECKS_H_

#include <float.h>
#include <stddef.h>
#include <stdio.h>

/** Missing index and removed-item marker used throughout EasyMesh topology. */
#define MISSING_MESH_INDEX -1

/** @brief Return a checked indexed item.
    @param[in] items Indexed storage.
    @param[in] itemCount Number of stored items.
    @param[in] itemIndex Requested index or MISSING_MESH_INDEX.
    @param[in] itemName Name used in diagnostics.
    @return Requested item, or NULL for missing or invalid indices.
 */
template <typename T>
static T *
getEasyMeshItem(T *items, int itemCount, int itemIndex, const char *itemName)
{
	if (itemIndex == MISSING_MESH_INDEX) {
		return NULL;
	}
	if ((itemIndex < 0) || (itemIndex >= itemCount)) {
		fprintf(stderr, "EasyMesh: invalid %s index %d (%s count %d)\n",
		        itemName, itemIndex, itemName, itemCount);
		return NULL;
	}
	return &items[itemIndex];
}


/** @brief Test whether an index is missing, invalid, or removed.
    @return Non-zero when no active item is available at the index.
 */
template <typename T>
static int
easyMeshItemIsMissingOrRemoved(T *items, int itemCount, int itemIndex,
                               const char *itemName)
{
	T *item = getEasyMeshItem(items, itemCount, itemIndex, itemName);
	return (item == NULL) || (item->marker == MISSING_MESH_INDEX);
}


/** @brief Return the two other neighbours around one element neighbour slot.
    @param[in] item Element-like item with I/J/K neighbour correspondence.
    @param[in] neighbourIndex Neighbour whose opposite pair is requested.
    @param[out] firstNeighbour First other neighbour.
    @param[out] secondNeighbour Second other neighbour.
    @return Number of matching slots; valid topology returns one.
 */
template <typename T>
static int
getEasyMeshOppositeNeighbours(const T *item, int neighbourIndex,
                              int *firstNeighbour, int *secondNeighbour)
{
	int matches = 0;

	*firstNeighbour = MISSING_MESH_INDEX;
	*secondNeighbour = MISSING_MESH_INDEX;
	if (item->neighbourI == neighbourIndex) {
		*firstNeighbour = item->neighbourJ;
		*secondNeighbour = item->neighbourK;
		matches++;
	}
	if (item->neighbourJ == neighbourIndex) {
		*firstNeighbour = item->neighbourK;
		*secondNeighbour = item->neighbourI;
		matches++;
	}
	if (item->neighbourK == neighbourIndex) {
		*firstNeighbour = item->neighbourI;
		*secondNeighbour = item->neighbourJ;
		matches++;
	}
	return matches;
}


/** @brief Increment neighbour counts at both active endpoints of an active side.
    @param[in] side Side-like item to count.
    @param[in,out] nodes Node storage receiving neighbour counts.
    @param[in] nodeCount Number of stored nodes.
 */
template <typename TSide, typename TNode>
static void
countEasyMeshSideNeighbours(const TSide *side, TNode *nodes, int nodeCount)
{
	TNode *firstNode;
	TNode *secondNode;

	if (side->marker != 0) {
		return;
	}
	firstNode = getEasyMeshItem(nodes, nodeCount, side->startNode, "node");
	secondNode = getEasyMeshItem(nodes, nodeCount, side->endNode, "node");
	if ((firstNode != NULL) && (firstNode->marker == 0)) {
		firstNode->neighbourCount++;
	}
	if ((secondNode != NULL) && (secondNode->marker == 0)) {
		secondNode->neighbourCount++;
	}
}


/** @brief Clear the persistent refinement block on one valid element. */
template <typename T>
static void
clearEasyMeshRefinementBlock(T *items, int itemCount, int itemIndex)
{
	T *item = getEasyMeshItem(items, itemCount, itemIndex, "element");

	if (item != NULL) {
		item->refinementBlocked = 0;
	}
}


/** @brief Test whether a value is finite without platform-specific functions. */
static inline int
easyMeshValueIsFinite(double value)
{
	return (value >= -DBL_MAX) && (value <= DBL_MAX);
}


/** @brief Test whether two XY points are within a maximum distance. */
static inline int
easyMeshPointsAreNear(double firstX, double firstY,
                      double secondX, double secondY, double maximumDistance)
{
	const double deltaX = secondX - firstX;
	const double deltaY = secondY - firstY;

	return deltaX * deltaX + deltaY * deltaY <= maximumDistance * maximumDistance;
}


/** @brief Test whether three topology indices identify distinct vertices. */
static inline int
easyMeshTriangleHasDistinctVertices(int first, int second, int third)
{
	return (first != second) && (first != third) && (second != third);
}


/** @brief Test whether two triangles contain the same three vertex indices. */
static inline int
easyMeshTrianglesMatch(int firstA, int firstB, int firstC,
                       int secondA, int secondB, int secondC)
{
	return ((firstA == secondA) || (firstA == secondB) || (firstA == secondC)) &&
	       ((firstB == secondA) || (firstB == secondB) || (firstB == secondC)) &&
	       ((firstC == secondA) || (firstC == secondB) || (firstC == secondC));
}


/** @brief Order three element sides with an optional preferred side first.
    @return Three for valid topology, otherwise zero.
 */
static inline int
getEasyMeshRefinementSideOrder(int preferredSide, int firstSide,
                               int secondSide, int thirdSide,
                               int orderedSides[3])
{
	const int elementSides[3] = {firstSide, secondSide, thirdSide};
	int count = 0;
	int i;

	if ((firstSide == MISSING_MESH_INDEX) || (secondSide == MISSING_MESH_INDEX) ||
	        (thirdSide == MISSING_MESH_INDEX) ||
	        (firstSide == secondSide) || (firstSide == thirdSide) ||
	        (secondSide == thirdSide)) {
		return 0;
	}
	if ((preferredSide != MISSING_MESH_INDEX) &&
	        (preferredSide != firstSide) &&
	        (preferredSide != secondSide) &&
	        (preferredSide != thirdSide)) {
		return 0;
	}
	if (preferredSide != MISSING_MESH_INDEX) {
		orderedSides[count++] = preferredSide;
	}
	for (i = 0; i < 3; i++) {
		if (elementSides[i] != preferredSide) {
			orderedSides[count++] = elementSides[i];
		}
	}
	return count;
}


/** @brief Test whether refinement is complete or has reached its node budget. */
static inline int
easyMeshShouldStopRefinement(int refinementElement, int nodeCount,
                             int maximumNodeCount)
{
	return (refinementElement == MISSING_MESH_INDEX) ||
	       (nodeCount >= maximumNodeCount);
}

#endif /* _EASYMESH_CHECKS_H_ */
