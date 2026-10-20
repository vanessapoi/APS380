/***************************************************************************

    file                 : easymesh_test.cpp
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

#include <gtest/gtest.h>

#include <cmath>
#include <limits>
#include <memory>
#include <vector>

#include "easymesh.h"
#include "easymesh_checks.h"

struct TestItem {
	int marker;
};

struct TestElement {
	int neighbourI;
	int neighbourJ;
	int neighbourK;
};

struct TestNode {
	int marker;
	int neighbourCount;
};

struct TestSide {
	int startNode;
	int endNode;
	int marker;
};

struct TestRefinementElement {
	int refinementBlocked;
};


TEST(EasyMeshGetItemTest, MissingIndexReturnsNull)
{
	TestItem items[] = {{0}};

	EXPECT_EQ(nullptr, getEasyMeshItem(items, 1, MISSING_MESH_INDEX, "element"));
}


TEST(EasyMeshGetItemTest, ValidIndicesReturnRequestedItems)
{
	TestItem items[] = {{0}, {MISSING_MESH_INDEX}};

	EXPECT_EQ(&items[0], getEasyMeshItem(items, 2, 0, "element"));
	EXPECT_EQ(&items[1], getEasyMeshItem(items, 2, 1, "element"));
}


TEST(EasyMeshGetItemTest, ActiveAndRemovedItemsAreDistinguished)
{
	TestItem items[] = {{0}, {MISSING_MESH_INDEX}};

	EXPECT_FALSE(easyMeshItemIsMissingOrRemoved(items, 2, 0, "element"));
	EXPECT_TRUE(easyMeshItemIsMissingOrRemoved(items, 2, 1, "element"));
	EXPECT_TRUE(easyMeshItemIsMissingOrRemoved(
		items, 2, MISSING_MESH_INDEX, "element"));
}


TEST(EasyMeshGetItemTest, MissingAndRemovedNeighboursAreUnavailable)
{
	TestItem items[] = {{0}, {MISSING_MESH_INDEX}};
	const int neighbourI = MISSING_MESH_INDEX;
	const int neighbourJ = 0;
	const int neighbourK = 1;

	EXPECT_TRUE(easyMeshItemIsMissingOrRemoved(items, 2, neighbourI, "element"));
	EXPECT_FALSE(easyMeshItemIsMissingOrRemoved(items, 2, neighbourJ, "element"));
	EXPECT_TRUE(easyMeshItemIsMissingOrRemoved(items, 2, neighbourK, "element"));
}


TEST(EasyMeshGetItemTest, InvalidNegativeIndexReturnsNull)
{
	TestItem items[] = {{0}};

	EXPECT_EQ(nullptr, getEasyMeshItem(items, 1, -2, "element"));
}


TEST(EasyMeshGetItemTest, IndexAtItemCountReturnsNull)
{
	TestItem items[] = {{0}, {0}};

	EXPECT_EQ(nullptr, getEasyMeshItem(items, 2, 2, "node"));
}


TEST(EasyMeshOppositeNeighboursTest, ReturnsNeighboursForEachElementSlot)
{
	const TestElement element = {3, 5, 7};
	int firstNeighbour;
	int secondNeighbour;

	EXPECT_EQ(1, getEasyMeshOppositeNeighbours(&element, 3, &firstNeighbour, &secondNeighbour));
	EXPECT_EQ(5, firstNeighbour);
	EXPECT_EQ(7, secondNeighbour);

	EXPECT_EQ(1, getEasyMeshOppositeNeighbours(&element, 5, &firstNeighbour, &secondNeighbour));
	EXPECT_EQ(7, firstNeighbour);
	EXPECT_EQ(3, secondNeighbour);

	EXPECT_EQ(1, getEasyMeshOppositeNeighbours(&element, 7, &firstNeighbour, &secondNeighbour));
	EXPECT_EQ(3, firstNeighbour);
	EXPECT_EQ(5, secondNeighbour);
}


TEST(EasyMeshOppositeNeighboursTest, ReportsMissingNeighbour)
{
	const TestElement element = {3, 5, 7};
	int firstNeighbour;
	int secondNeighbour;

	EXPECT_EQ(0, getEasyMeshOppositeNeighbours(&element, 11, &firstNeighbour, &secondNeighbour));
	EXPECT_EQ(MISSING_MESH_INDEX, firstNeighbour);
	EXPECT_EQ(MISSING_MESH_INDEX, secondNeighbour);
}


TEST(EasyMeshOppositeNeighboursTest, ReportsDuplicateNeighbour)
{
	const TestElement element = {3, 3, 7};
	int firstNeighbour;
	int secondNeighbour;

	EXPECT_EQ(2, getEasyMeshOppositeNeighbours(&element, 3, &firstNeighbour, &secondNeighbour));
}


TEST(EasyMeshNeighbourCountTest, UnmarkedSideCountsBothActiveEndpoints)
{
	TestNode nodes[] = {{0, 0}, {0, 0}};
	const TestSide side = {0, 1, 0};

	countEasyMeshSideNeighbours(&side, nodes, 2);

	EXPECT_EQ(1, nodes[0].neighbourCount);
	EXPECT_EQ(1, nodes[1].neighbourCount);
}


TEST(EasyMeshNeighbourCountTest, MarkedSideCountsNeitherEndpoint)
{
	TestNode nodes[] = {{0, 0}, {0, 0}};
	const TestSide side = {0, 1, 7};

	countEasyMeshSideNeighbours(&side, nodes, 2);

	EXPECT_EQ(0, nodes[0].neighbourCount);
	EXPECT_EQ(0, nodes[1].neighbourCount);
}


TEST(EasyMeshNeighbourCountTest, CountsOnlyActiveEndpoints)
{
	TestNode nodes[] = {{MISSING_MESH_INDEX, 0}, {0, 0}};
	const TestSide side = {0, 1, 0};

	countEasyMeshSideNeighbours(&side, nodes, 2);

	EXPECT_EQ(0, nodes[0].neighbourCount);
	EXPECT_EQ(1, nodes[1].neighbourCount);
}


TEST(EasyMeshNeighbourCountTest, RemovedSideCountsNeitherEndpoint)
{
	TestNode nodes[] = {{0, 0}, {0, 0}};
	const TestSide side = {0, 1, MISSING_MESH_INDEX};

	countEasyMeshSideNeighbours(&side, nodes, 2);

	EXPECT_EQ(0, nodes[0].neighbourCount);
	EXPECT_EQ(0, nodes[1].neighbourCount);
}


TEST(EasyMeshFiniteValueTest, AcceptsFiniteValues)
{
	EXPECT_TRUE(easyMeshValueIsFinite(0.0));
	EXPECT_TRUE(easyMeshValueIsFinite(-1.0));
}


TEST(EasyMeshFiniteValueTest, RejectsNotANumberAndInfinity)
{
	EXPECT_FALSE(easyMeshValueIsFinite(
		std::numeric_limits<double>::quiet_NaN()));
	EXPECT_FALSE(easyMeshValueIsFinite(
		std::numeric_limits<double>::infinity()));
}


TEST(EasyMeshPointDistanceTest, AcceptsIdenticalPoints)
{
	EXPECT_TRUE(easyMeshPointsAreNear(12.0, -4.0, 12.0, -4.0, 1e-10));
}


TEST(EasyMeshPointDistanceTest, AcceptsPointsAtMaximumDistance)
{
	EXPECT_TRUE(easyMeshPointsAreNear(0.0, 0.0, 1e-10, 0.0, 1e-10));
}


TEST(EasyMeshPointDistanceTest, RejectsPointsBeyondMaximumDistance)
{
	EXPECT_FALSE(easyMeshPointsAreNear(0.0, 0.0, 1.01e-10, 0.0, 1e-10));
}


TEST(EasyMeshTriangleTest, AcceptsThreeDistinctVertices)
{
	EXPECT_TRUE(easyMeshTriangleHasDistinctVertices(3, 5, 7));
}


TEST(EasyMeshTriangleTest, RejectsRepeatedVertices)
{
	EXPECT_FALSE(easyMeshTriangleHasDistinctVertices(3, 5, 3));
}


TEST(EasyMeshTriangleTest, MatchesEveryWindingAndOrder)
{
	EXPECT_TRUE(easyMeshTrianglesMatch(3, 5, 7, 7, 5, 3));
	EXPECT_TRUE(easyMeshTrianglesMatch(3, 5, 7, 5, 3, 7));
}


TEST(EasyMeshTriangleTest, RejectsDifferentVertices)
{
	EXPECT_FALSE(easyMeshTrianglesMatch(3, 5, 7, 3, 5, 11));
}


TEST(EasyMeshRefinementBlockTest, ChangedElementClearsBlock)
{
	TestRefinementElement elements[] = {{1}};

	clearEasyMeshRefinementBlock(elements, 1, 0);

	EXPECT_EQ(0, elements[0].refinementBlocked);
}


TEST(EasyMeshRefinementBlockTest, MissingElementNeedsNoBlockUpdate)
{
	TestRefinementElement elements[] = {{1}};

	clearEasyMeshRefinementBlock(elements, 1, MISSING_MESH_INDEX);

	EXPECT_EQ(1, elements[0].refinementBlocked);
}


TEST(EasyMeshRefinementSideOrderTest, PreferredSideComesFirst)
{
	int orderedSides[3];

	EXPECT_EQ(3, getEasyMeshRefinementSideOrder(5, 3, 5, 7, orderedSides));
	EXPECT_EQ(5, orderedSides[0]);
	EXPECT_EQ(3, orderedSides[1]);
	EXPECT_EQ(7, orderedSides[2]);
}


TEST(EasyMeshRefinementSideOrderTest, EveryPreferredSlotPreservesFallbackOrder)
{
	int orderedSides[3];

	EXPECT_EQ(3, getEasyMeshRefinementSideOrder(3, 3, 5, 7, orderedSides));
	EXPECT_EQ(3, orderedSides[0]);
	EXPECT_EQ(5, orderedSides[1]);
	EXPECT_EQ(7, orderedSides[2]);

	EXPECT_EQ(3, getEasyMeshRefinementSideOrder(7, 3, 5, 7, orderedSides));
	EXPECT_EQ(7, orderedSides[0]);
	EXPECT_EQ(3, orderedSides[1]);
	EXPECT_EQ(5, orderedSides[2]);
}


TEST(EasyMeshRefinementSideOrderTest, NoPreferredSideUsesElementOrder)
{
	int orderedSides[3];

	EXPECT_EQ(3, getEasyMeshRefinementSideOrder(
		MISSING_MESH_INDEX, 3, 5, 7, orderedSides));
	EXPECT_EQ(3, orderedSides[0]);
	EXPECT_EQ(5, orderedSides[1]);
	EXPECT_EQ(7, orderedSides[2]);
}


TEST(EasyMeshRefinementSideOrderTest, RejectsInvalidTopology)
{
	int orderedSides[3];

	EXPECT_EQ(0, getEasyMeshRefinementSideOrder(3, 3, 3, 7, orderedSides));
	EXPECT_EQ(0, getEasyMeshRefinementSideOrder(11, 3, 5, 7, orderedSides));
	EXPECT_EQ(0, getEasyMeshRefinementSideOrder(
		3, 3, 5, MISSING_MESH_INDEX, orderedSides));
}


TEST(EasyMeshRefinementProgressTest, ActiveElementBelowNodeLimitContinuesRefinement)
{
	EXPECT_FALSE(easyMeshShouldStopRefinement(4, 10, 100));
}


TEST(EasyMeshRefinementProgressTest, NodeLimitStopsRefinement)
{
	EXPECT_TRUE(easyMeshShouldStopRefinement(4, 101, 100));
}


TEST(EasyMeshRefinementProgressTest, ExactNodeLimitStopsRefinement)
{
	EXPECT_TRUE(easyMeshShouldStopRefinement(4, 100, 100));
}


TEST(EasyMeshRefinementProgressTest, NoRefinementElementStopsRefinement)
{
	EXPECT_TRUE(easyMeshShouldStopRefinement(MISSING_MESH_INDEX, 10, 100));
}


TEST(EasyMeshCoreTest, TriangulatesClosedSquareWithoutTorcsDependencies)
{
	tMeshNode points[4] = {};
	tConstraintSegment segments[4] = {};
	tMeshInput input;
	std::unique_ptr<EasyMesh> mesh(new EasyMesh);
	const tMeshElement *elements;
	const tMeshNode *nodes;
	int activeElementCount = 0;
	int elementIndex;
	int firstElementCount;
	int firstNodeCount;
	int pointIndex;

	points[0].x = 0.0;
	points[0].y = 0.0;
	points[1].x = 10.0;
	points[1].y = 0.0;
	points[2].x = 10.0;
	points[2].y = 10.0;
	points[3].x = 0.0;
	points[3].y = 10.0;
	for (pointIndex = 0; pointIndex < 4; pointIndex++) {
		points[pointIndex].spacing = 100.0;
		points[pointIndex].marker = 1;
		segments[pointIndex].startNode = pointIndex;
		segments[pointIndex].endNode = (pointIndex + 1) % 4;
		segments[pointIndex].marker = 1;
	}
	input.points = points;
	input.pointCount = 4;
	input.pointCapacity = 4;
	input.segments = segments;
	input.segmentCount = 4;
	input.segmentCapacity = 4;

	mesh->generateMesh(&input, "unit-square", 1, nullptr, nullptr);

	elements = mesh->getElements();
	nodes = mesh->getNodes();
	EXPECT_GE(mesh->getNodeCount(), 7);
	EXPECT_GT(mesh->getElementCount(), 0);
	for (elementIndex = 0; elementIndex < mesh->getElementCount(); elementIndex++) {
		const tMeshElement &element = elements[elementIndex];
		const int elementNodes[3] = {element.nodeI, element.nodeJ, element.nodeK};
		int vertexIndex;

		if (element.marker == MISSING_MESH_INDEX) {
			continue;
		}
		activeElementCount++;
		EXPECT_TRUE(easyMeshTriangleHasDistinctVertices(
		        element.nodeI, element.nodeJ, element.nodeK));
		for (vertexIndex = 0; vertexIndex < 3; vertexIndex++) {
			ASSERT_GE(elementNodes[vertexIndex], 0);
			ASSERT_LT(elementNodes[vertexIndex], mesh->getNodeCount());
			EXPECT_TRUE(std::isfinite(nodes[elementNodes[vertexIndex]].x));
			EXPECT_TRUE(std::isfinite(nodes[elementNodes[vertexIndex]].y));
			EXPECT_TRUE(std::isfinite(nodes[elementNodes[vertexIndex]].z));
		}
	}
	EXPECT_GT(activeElementCount, 0);

	firstElementCount = mesh->getElementCount();
	firstNodeCount = mesh->getNodeCount();
	mesh->generateMesh(&input, "unit-square-reuse", 1, nullptr, nullptr);
	EXPECT_EQ(firstElementCount, mesh->getElementCount());
	EXPECT_EQ(firstNodeCount, mesh->getNodeCount());
}


TEST(EasyMeshCoreTest, SeparatesAttachedOpenConstraintFromClosedBoundary)
{
	tMeshNode points[8] = {};
	tConstraintSegment segments[10] = {};
	tMeshInput input;
	std::unique_ptr<EasyMesh> mesh(new EasyMesh);
	const tMeshSide *sides;
	bool foundAttachedConstraint = false;
	int midpointMatchCount = 0;
	int nodeIndex;
	int pointIndex;
	int sideIndex;

	points[0].x = 0.0;
	points[0].y = 0.0;
	points[1].x = 10.0;
	points[1].y = 0.0;
	points[2].x = 10.0;
	points[2].y = 10.0;
	points[3].x = 0.0;
	points[3].y = 10.0;
	points[4].x = 3.0;
	points[4].y = 4.0;
	points[5].x = 6.5;
	points[5].y = 7.0;
	points[6].x = 7.836881039375368;
	points[6].y = 8.145898033750316;
	points[7].x = 4.336881039375368;
	points[7].y = 5.145898033750316;
	for (pointIndex = 0; pointIndex < 8; pointIndex++) {
		points[pointIndex].spacing = 100.0;
		points[pointIndex].marker = pointIndex >= 4 ? 9 : 1;
	}
	for (pointIndex = 0; pointIndex < 4; pointIndex++) {
		segments[pointIndex].startNode = pointIndex;
		segments[pointIndex].endNode = (pointIndex + 1) % 4;
		segments[pointIndex].marker = 1;
	}
	segments[4].startNode = 0;
	segments[4].endNode = 4;
	segments[4].startsNewChain = 1;
	segments[4].marker = 9;
	segments[5].startNode = 1;
	segments[5].endNode = 5;
	segments[5].startsNewChain = 1;
	segments[5].marker = 11;
	segments[6].startNode = 2;
	segments[6].endNode = 6;
	segments[6].startsNewChain = 1;
	segments[6].marker = 10;
	segments[7].startNode = 6;
	segments[7].endNode = 5;
	segments[7].marker = 10;
	segments[8].startNode = 5;
	segments[8].endNode = 7;
	segments[8].marker = 10;
	segments[9].startNode = 7;
	segments[9].endNode = 4;
	segments[9].marker = 10;
	input.points = points;
	input.pointCount = 8;
	input.pointCapacity = 8;
	input.segments = segments;
	input.segmentCount = 10;
	input.segmentCapacity = 10;

	mesh->generateMesh(&input, "attached-constraint", 1, nullptr, nullptr);

	ASSERT_GE(points[0].outputIndex, 0);
	ASSERT_GE(points[4].outputIndex, 0);
	sides = mesh->getSides();
	for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
		if ((sides[sideIndex].marker == 9) &&
		        (((sides[sideIndex].startNode == points[0].outputIndex) &&
		          (sides[sideIndex].endNode == points[4].outputIndex)) ||
		         ((sides[sideIndex].startNode == points[4].outputIndex) &&
		          (sides[sideIndex].endNode == points[0].outputIndex)))) {
			foundAttachedConstraint = true;
		}
	}
	EXPECT_TRUE(foundAttachedConstraint);
	std::vector<bool> reached(mesh->getNodeCount(), false);
	reached[points[2].outputIndex] = true;
	bool changed;
	do {
		changed = false;
		for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
			if (sides[sideIndex].marker != 10) {
				continue;
			}
			if (reached[sides[sideIndex].startNode] &&
			        !reached[sides[sideIndex].endNode]) {
				reached[sides[sideIndex].endNode] = true;
				changed = true;
			}
			if (reached[sides[sideIndex].endNode] &&
			        !reached[sides[sideIndex].startNode]) {
				reached[sides[sideIndex].startNode] = true;
				changed = true;
			}
		}
	} while (changed);
	EXPECT_TRUE(reached[points[4].outputIndex]);
	for (nodeIndex = 0; nodeIndex < mesh->getNodeCount(); nodeIndex++) {
		if ((fabs(mesh->getNodes()[nodeIndex].x - points[5].x) <= 1e-10) &&
		        (fabs(mesh->getNodes()[nodeIndex].y - points[5].y) <= 1e-10)) {
			midpointMatchCount++;
		}
	}
	EXPECT_EQ(1, midpointMatchCount);
}


TEST(EasyMeshCoreTest, MarksConstraintWhoseEndpointsAlreadyExist)
{
	tMeshNode points[4] = {};
	tConstraintSegment segments[5] = {};
	tMeshInput input;
	std::unique_ptr<EasyMesh> mesh(new EasyMesh);
	const tMeshSide *sides;
	bool foundConstraint = false;
	int pointIndex;
	int sideIndex;

	points[0].x = 0.0;
	points[0].y = 0.0;
	points[1].x = 10.0;
	points[1].y = 0.0;
	points[2].x = 10.0;
	points[2].y = 10.0;
	points[3].x = 0.0;
	points[3].y = 10.0;
	for (pointIndex = 0; pointIndex < 4; pointIndex++) {
		points[pointIndex].spacing = 100.0;
		points[pointIndex].marker = 1;
		segments[pointIndex].startNode = pointIndex;
		segments[pointIndex].endNode = (pointIndex + 1) % 4;
		segments[pointIndex].marker = 1;
	}
	segments[4].startNode = 0;
	segments[4].endNode = 1;
	segments[4].startsNewChain = 1;
	segments[4].marker = 9;
	input.points = points;
	input.pointCount = 4;
	input.pointCapacity = 4;
	input.segments = segments;
	input.segmentCount = 5;
	input.segmentCapacity = 5;

	mesh->generateMesh(&input, "existing-endpoints", 1, nullptr, nullptr);

	ASSERT_GE(points[0].outputIndex, 0);
	ASSERT_GE(points[1].outputIndex, 0);
	sides = mesh->getSides();
	for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
		if ((sides[sideIndex].marker == 9) &&
		        (((sides[sideIndex].startNode == points[0].outputIndex) &&
		          (sides[sideIndex].endNode == points[1].outputIndex)) ||
		         ((sides[sideIndex].startNode == points[1].outputIndex) &&
		          (sides[sideIndex].endNode == points[0].outputIndex)))) {
			foundConstraint = true;
		}
	}
	EXPECT_TRUE(foundConstraint);
}


TEST(EasyMeshCoreTest, RecoversConstraintBetweenNonAdjacentExistingEndpoints)
{
	tMeshNode points[4] = {};
	tConstraintSegment segments[5] = {};
	tMeshInput input;
	std::unique_ptr<EasyMesh> mesh(new EasyMesh);
	const tMeshSide *sides;
	bool firstDiagonalExists = false;
	bool secondDiagonalExists = false;
	bool foundConstraint = false;
	int constraintStart;
	int constraintEnd;
	int pointIndex;
	int sideIndex;

	points[0].x = 0.0;
	points[0].y = 0.0;
	points[1].x = 10.0;
	points[1].y = 0.0;
	points[2].x = 10.0;
	points[2].y = 10.0;
	points[3].x = 0.0;
	points[3].y = 10.0;
	for (pointIndex = 0; pointIndex < 4; pointIndex++) {
		points[pointIndex].spacing = 100.0;
		points[pointIndex].marker = 1;
		segments[pointIndex].startNode = pointIndex;
		segments[pointIndex].endNode = (pointIndex + 1) % 4;
		segments[pointIndex].marker = 1;
	}
	input.points = points;
	input.pointCount = 4;
	input.pointCapacity = 4;
	input.segments = segments;
	input.segmentCount = 4;
	input.segmentCapacity = 5;

	mesh->generateMesh(&input, "diagonal-probe", 1, nullptr, nullptr);
	sides = mesh->getSides();
	for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
		firstDiagonalExists = firstDiagonalExists ||
		        (((sides[sideIndex].startNode == points[0].outputIndex) &&
		          (sides[sideIndex].endNode == points[2].outputIndex)) ||
		         ((sides[sideIndex].startNode == points[2].outputIndex) &&
		          (sides[sideIndex].endNode == points[0].outputIndex)));
		secondDiagonalExists = secondDiagonalExists ||
		        (((sides[sideIndex].startNode == points[1].outputIndex) &&
		          (sides[sideIndex].endNode == points[3].outputIndex)) ||
		         ((sides[sideIndex].startNode == points[3].outputIndex) &&
		          (sides[sideIndex].endNode == points[1].outputIndex)));
	}
	ASSERT_NE(firstDiagonalExists, secondDiagonalExists);
	constraintStart = firstDiagonalExists ? 1 : 0;
	constraintEnd = firstDiagonalExists ? 3 : 2;
	segments[4].startNode = constraintStart;
	segments[4].endNode = constraintEnd;
	segments[4].startsNewChain = 1;
	segments[4].marker = 9;
	input.segmentCount = 5;

	mesh->generateMesh(&input, "recovered-diagonal", 1, nullptr, nullptr);
	sides = mesh->getSides();
	for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
		if ((sides[sideIndex].marker == 9) &&
		        (((sides[sideIndex].startNode ==
		           points[constraintStart].outputIndex) &&
		          (sides[sideIndex].endNode ==
		           points[constraintEnd].outputIndex)) ||
		         ((sides[sideIndex].startNode ==
		           points[constraintEnd].outputIndex) &&
		          (sides[sideIndex].endNode ==
		           points[constraintStart].outputIndex)))) {
			foundConstraint = true;
		}
	}
	EXPECT_TRUE(foundConstraint);
}


TEST(EasyMeshCoreTest, RecoversSplitConstraintAroundFreshInteriorPoint)
{
	tMeshNode points[5] = {};
	tConstraintSegment segments[6] = {};
	tMeshInput input;
	std::unique_ptr<EasyMesh> mesh(new EasyMesh);
	const tMeshSide *sides;
	bool firstDiagonalExists = false;
	bool secondDiagonalExists = false;
	bool foundFirstConstraint = false;
	bool foundSecondConstraint = false;
	int constraintStart;
	int constraintEnd;
	int pointIndex;
	int sideIndex;

	points[0].x = 0.0;
	points[0].y = 0.0;
	points[1].x = 10.0;
	points[1].y = 0.0;
	points[2].x = 10.0;
	points[2].y = 10.0;
	points[3].x = 0.0;
	points[3].y = 10.0;
	for (pointIndex = 0; pointIndex < 4; pointIndex++) {
		points[pointIndex].spacing = 100.0;
		points[pointIndex].marker = 1;
		segments[pointIndex].startNode = pointIndex;
		segments[pointIndex].endNode = (pointIndex + 1) % 4;
		segments[pointIndex].marker = 1;
	}
	input.points = points;
	input.pointCount = 4;
	input.pointCapacity = 5;
	input.segments = segments;
	input.segmentCount = 4;
	input.segmentCapacity = 6;

	mesh->generateMesh(&input, "split-constraint-probe", 1, nullptr, nullptr);
	sides = mesh->getSides();
	for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
		firstDiagonalExists = firstDiagonalExists ||
		        (((sides[sideIndex].startNode == points[0].outputIndex) &&
		          (sides[sideIndex].endNode == points[2].outputIndex)) ||
		         ((sides[sideIndex].startNode == points[2].outputIndex) &&
		          (sides[sideIndex].endNode == points[0].outputIndex)));
		secondDiagonalExists = secondDiagonalExists ||
		        (((sides[sideIndex].startNode == points[1].outputIndex) &&
		          (sides[sideIndex].endNode == points[3].outputIndex)) ||
		         ((sides[sideIndex].startNode == points[3].outputIndex) &&
		          (sides[sideIndex].endNode == points[1].outputIndex)));
	}
	ASSERT_NE(firstDiagonalExists, secondDiagonalExists);
	constraintStart = firstDiagonalExists ? 1 : 0;
	constraintEnd = firstDiagonalExists ? 3 : 2;
	points[4].x = points[constraintStart].x + 0.75 *
	        (points[constraintEnd].x - points[constraintStart].x);
	points[4].y = points[constraintStart].y + 0.75 *
	        (points[constraintEnd].y - points[constraintStart].y);
	points[4].spacing = 100.0;
	points[4].marker = 9;
	segments[4].startNode = constraintStart;
	segments[4].endNode = 4;
	segments[4].startsNewChain = 1;
	segments[4].recoverDisconnectedSide = 1;
	segments[4].marker = 9;
	segments[5].startNode = 4;
	segments[5].endNode = constraintEnd;
	segments[5].recoverDisconnectedSide = 1;
	segments[5].marker = 9;
	input.pointCount = 5;
	input.segmentCount = 6;

	mesh->generateMesh(&input, "split-constraint-recovery", 1, nullptr, nullptr);
	ASSERT_GE(points[constraintStart].outputIndex, 0);
	ASSERT_GE(points[constraintEnd].outputIndex, 0);
	ASSERT_GE(points[4].outputIndex, 0);
	sides = mesh->getSides();
	for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
		if (sides[sideIndex].marker != 9) {
			continue;
		}
		foundFirstConstraint = foundFirstConstraint ||
		        (((sides[sideIndex].startNode ==
		           points[constraintStart].outputIndex) &&
		          (sides[sideIndex].endNode == points[4].outputIndex)) ||
		         ((sides[sideIndex].startNode == points[4].outputIndex) &&
		          (sides[sideIndex].endNode ==
		           points[constraintStart].outputIndex)));
		foundSecondConstraint = foundSecondConstraint ||
		        (((sides[sideIndex].startNode == points[4].outputIndex) &&
		          (sides[sideIndex].endNode ==
		           points[constraintEnd].outputIndex)) ||
		         ((sides[sideIndex].startNode ==
		           points[constraintEnd].outputIndex) &&
		          (sides[sideIndex].endNode == points[4].outputIndex)));
	}
	EXPECT_TRUE(foundFirstConstraint);
	EXPECT_TRUE(foundSecondConstraint);
}


TEST(EasyMeshCoreTest, RecoversFreshPointSideInClosedConstraintChain)
{
	tMeshNode points[8] = {};
	tConstraintSegment segments[8] = {};
	tMeshInput input;
	std::unique_ptr<EasyMesh> mesh(new EasyMesh);
	const tMeshSide *sides;
	bool firstDiagonalExists = false;
	bool foundConstraint = false;
	int pointIndex;
	int sideIndex;

	points[0].x = 0.0;
	points[0].y = 0.0;
	points[1].x = 10.0;
	points[1].y = 0.0;
	points[2].x = 10.0;
	points[2].y = 10.0;
	points[3].x = 0.0;
	points[3].y = 10.0;
	for (pointIndex = 0; pointIndex < 4; pointIndex++) {
		points[pointIndex].spacing = 100.0;
		points[pointIndex].marker = 1;
		segments[pointIndex].startNode = pointIndex;
		segments[pointIndex].endNode = (pointIndex + 1) % 4;
		segments[pointIndex].marker = 1;
	}
	input.points = points;
	input.pointCount = 4;
	input.pointCapacity = 8;
	input.segments = segments;
	input.segmentCount = 4;
	input.segmentCapacity = 8;

	mesh->generateMesh(&input, "closed-constraint-probe", 1, nullptr, nullptr);
	sides = mesh->getSides();
	for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
		firstDiagonalExists = firstDiagonalExists ||
		        (((sides[sideIndex].startNode == points[0].outputIndex) &&
		          (sides[sideIndex].endNode == points[2].outputIndex)) ||
		         ((sides[sideIndex].startNode == points[2].outputIndex) &&
		          (sides[sideIndex].endNode == points[0].outputIndex)));
	}
	points[4].x = 4.0;
	points[4].y = 5.0;
	points[5].x = 5.0;
	points[5].y = firstDiagonalExists ? 4.0 : 6.0;
	points[6].x = 6.0;
	points[6].y = 5.0;
	points[7].x = 5.0;
	points[7].y = firstDiagonalExists ? 6.0 : 4.0;
	for (pointIndex = 4; pointIndex < 8; pointIndex++) {
		points[pointIndex].spacing = 100.0;
		points[pointIndex].marker = 9;
		segments[pointIndex].startNode = pointIndex;
		segments[pointIndex].endNode = 4 + (pointIndex - 3) % 4;
		segments[pointIndex].recoverDisconnectedSide = 1;
		segments[pointIndex].marker = 9;
	}
	segments[4].startsNewChain = 1;
	input.pointCount = 8;
	input.segmentCount = 8;

	mesh->generateMesh(&input, "closed-constraint-recovery", 1,
	                   nullptr, nullptr);
	ASSERT_GE(points[4].outputIndex, 0);
	ASSERT_GE(points[5].outputIndex, 0);
	sides = mesh->getSides();
	for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
		foundConstraint = foundConstraint ||
		        ((sides[sideIndex].marker == 9) &&
		         (((sides[sideIndex].startNode == points[4].outputIndex) &&
		           (sides[sideIndex].endNode == points[5].outputIndex)) ||
		          ((sides[sideIndex].startNode == points[5].outputIndex) &&
		           (sides[sideIndex].endNode == points[4].outputIndex))));
	}
	EXPECT_TRUE(foundConstraint);
}


TEST(EasyMeshCoreTest, RecoversSubdividedConstraintEndingAtFreshPoint)
{
	tMeshNode points[5] = {};
	tConstraintSegment segments[5] = {};
	tMeshInput input;
	std::unique_ptr<EasyMesh> mesh(new EasyMesh);
	const tMeshSide *sides;
	bool firstDiagonalExists = false;
	int constraintSideCount = 0;
	int constraintStart;
	int constraintDirection;
	int pointIndex;
	int sideIndex;

	points[0].x = 0.0;
	points[0].y = 0.0;
	points[1].x = 10.0;
	points[1].y = 0.0;
	points[2].x = 10.0;
	points[2].y = 10.0;
	points[3].x = 0.0;
	points[3].y = 10.0;
	for (pointIndex = 0; pointIndex < 4; pointIndex++) {
		points[pointIndex].spacing = 100.0;
		points[pointIndex].marker = 1;
		segments[pointIndex].startNode = pointIndex;
		segments[pointIndex].endNode = (pointIndex + 1) % 4;
		segments[pointIndex].marker = 1;
	}
	input.points = points;
	input.pointCount = 4;
	input.pointCapacity = 5;
	input.segments = segments;
	input.segmentCount = 4;
	input.segmentCapacity = 5;

	mesh->generateMesh(&input, "subdivided-constraint-probe", 1,
	                   nullptr, nullptr);
	sides = mesh->getSides();
	for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
		firstDiagonalExists = firstDiagonalExists ||
		        (((sides[sideIndex].startNode == points[0].outputIndex) &&
		          (sides[sideIndex].endNode == points[2].outputIndex)) ||
		         ((sides[sideIndex].startNode == points[2].outputIndex) &&
		          (sides[sideIndex].endNode == points[0].outputIndex)));
	}
	constraintStart = firstDiagonalExists ? 1 : 0;
	constraintDirection = firstDiagonalExists ? 3 : 2;
	points[4].x = points[constraintStart].x + 0.75 *
	        (points[constraintDirection].x - points[constraintStart].x);
	points[4].y = points[constraintStart].y + 0.75 *
	        (points[constraintDirection].y - points[constraintStart].y);
	points[constraintStart].spacing = 1.0;
	points[4].spacing = 1.0;
	points[4].marker = 9;
	segments[4].startNode = constraintStart;
	segments[4].endNode = 4;
	segments[4].startsNewChain = 1;
	segments[4].recoverDisconnectedSide = 1;
	segments[4].marker = 9;
	input.pointCount = 5;
	input.segmentCount = 5;

	mesh->generateMesh(&input, "subdivided-constraint-recovery", 1,
	                   nullptr, nullptr);
	ASSERT_GE(points[constraintStart].outputIndex, 0);
	ASSERT_GE(points[4].outputIndex, 0);
	std::vector<bool> reached(mesh->getNodeCount(), false);
	reached[points[constraintStart].outputIndex] = true;
	sides = mesh->getSides();
	for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
		if (sides[sideIndex].marker == 9) {
			constraintSideCount++;
		}
	}
	EXPECT_GT(constraintSideCount, 1);
	bool changed;
	do {
		changed = false;
		for (sideIndex = 0; sideIndex < mesh->getSideCount(); sideIndex++) {
			if (sides[sideIndex].marker != 9) {
				continue;
			}
			if (reached[sides[sideIndex].startNode] &&
			        !reached[sides[sideIndex].endNode]) {
				reached[sides[sideIndex].endNode] = true;
				changed = true;
			}
			if (reached[sides[sideIndex].endNode] &&
			        !reached[sides[sideIndex].startNode]) {
				reached[sides[sideIndex].startNode] = true;
				changed = true;
			}
		}
	} while (changed);
	EXPECT_TRUE(reached[points[4].outputIndex]);
}
