/***************************************************************************

    file                 : easymesh.cpp
    author               : Bojan NICENO
    Original Location    : http://www-dinma.univ.trieste.it/~nirftc/research/easymesh/easymesh.html
    modified             : Eric Espié (eric.espie@torcs.org), Bernhard Wymann
    copyright            : Bojan NICENO & Eric Espié & Bernhard Wymann

 ***************************************************************************/

/** @file
    @brief EasyMesh constrained triangulation.

    See EASYMESH.md for the pipeline, refinement policy, and maintenance
    invariants.
 */


#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "easymesh.h"
#include "easymesh_checks.h"


#ifndef max
#define max(a,b)  (((a) > (b)) ? (a) : (b))
#endif
#ifndef min
#define min(a,b)  (((a) < (b)) ? (a) : (b))
#endif
/** Tolerance for degenerate geometric lengths and areas. */
#define GEOMETRY_EPSILON 1e-10

/** Initial magnitude used while accumulating mesh coordinate bounds. */
#define INITIAL_BOUNDING_VALUE 1e+10

/** Circumradius factor for an ideal equilateral triangle at target spacing. */
#define IDEAL_TRIANGLE_RADIUS_FACTOR 0.577

/** Largest accepted circumradius-to-target-spacing ratio. */
#define ACCEPTED_RADIUS_SPACING_RATIO 0.700

/** Number of Laplacian position-smoothing passes. */
#define SMOOTHING_ITERATION_COUNT 10

/** Vertical extent of the containing supertriangle above the mesh center. */
#define SUPERTRIANGLE_TOP_HEIGHT_MULTIPLIER 2.8

/** Horizontal half-width of the containing supertriangle. */
#define SUPERTRIANGLE_HALF_WIDTH_MULTIPLIER 2.0

/** Vertical extent of the containing supertriangle below the mesh center. */
#define SUPERTRIANGLE_BOTTOM_HEIGHT_MULTIPLIER 1.4

/** Practical per-domain refinement budget; finalization still runs at it. */
#define MAX_REFINEMENT_NODES 35000

/** Refinement classification values retained from the original algorithm. */
typedef enum {
	ELEMENT_ACTIVE = 3,                 /**< Eligible for the next insertion. */
	ELEMENT_DONE = 4,                   /**< Accepted by the refinement strategy. */
	ELEMENT_WAITING = 5                 /**< Not yet reachable from accepted topology. */
} tElementRefinementState;

/** Boundary-chain topology values retained from the original algorithm. */
typedef enum {
	BOUNDARY_CHAIN_CLOSED = 0,          /**< Closed domain boundary. */
	BOUNDARY_CHAIN_OPEN = 1,            /**< Open chain connected to other constraints. */
	BOUNDARY_CHAIN_INTERNAL_OPEN = 2    /**< Internal open constraint chain. */
} tBoundaryChainType;

/** @brief Contiguous range of constraint segments forming one chain. */
struct BoundaryChain {
	int startSegment;                 /**< First segment in the chain. */
	int endSegment;                   /**< Last segment in the chain. */
	int type;                         /**< tBoundaryChainType value. */
};


EasyMesh::EasyMesh()
:
	BoundaryPoints(NULL),
	ConstraintSegments(NULL),
	BoundaryChains(NULL),
	ElementCount(0),
	NodeCount(0),
	SideCount(0),
	BoundaryPointCount(0),
	ConstraintSegmentCount(0),
	RefinementElement(MISSING_MESH_INDEX),
	NodeInsertionFailureReason(NULL),
	MeshMaxX(0.0),
	MeshMinX(0.0),
	MeshMaxY(0.0),
	MeshMinY(0.0),
	Quiet(0),
	SpacingFunction(NULL),
	SpacingContext(NULL)
{
}


EasyMesh::~EasyMesh()
{
	free(BoundaryChains);
	BoundaryChains = NULL;
}


void
EasyMesh::generateMesh(tMeshInput *input, const char *domain, int quiet,
                       tfEasyMeshSpacing spacingFunction, void *spacingContext)
{
	BoundaryPoints = input->points;
	BoundaryPointCount = input->pointCount;
	ConstraintSegments = input->segments;
	ConstraintSegmentCount = input->segmentCount;
	Quiet = quiet;
	SpacingFunction = spacingFunction;
	SpacingContext = spacingContext;
	triangulate(domain);
}


const tMeshElement *
EasyMesh::getElements() const
{
	return Elements;
}


int
EasyMesh::getElementCount() const
{
	return ElementCount;
}


const tMeshNode *
EasyMesh::getNodes() const
{
	return Nodes;
}


int
EasyMesh::getNodeCount() const
{
	return NodeCount;
}


const tMeshSide *
EasyMesh::getSides() const
{
	return Sides;
}


int
EasyMesh::getSideCount() const
{
	return SideCount;
}


tMeshElement *
EasyMesh::getElement(int elementIndex)
{
	return getEasyMeshItem(Elements, ElementCount, elementIndex, "element");
}


int
EasyMesh::elementIsMissingOrRemoved(int elementIndex)
{
	return easyMeshItemIsMissingOrRemoved(Elements, ElementCount, elementIndex,
	                                      "element");
}


/** @brief Replace every matching neighbour slot in one element.
    @param[in] elementIndex Element whose neighbour links are updated.
    @param[in] oldNeighbour Neighbour index to replace.
    @param[in] newNeighbour Replacement neighbour index.
    @note All three slots are checked independently so malformed duplicate
          references are updated consistently with the original code.
 */
void
EasyMesh::replaceElementNeighbour(int elementIndex,
                                                   int oldNeighbour,
                                                   int newNeighbour)
{
	if (Elements[elementIndex].neighbourI == oldNeighbour) {
		Elements[elementIndex].neighbourI = newNeighbour;
	}
	if (Elements[elementIndex].neighbourJ == oldNeighbour) {
		Elements[elementIndex].neighbourJ = newNeighbour;
	}
	if (Elements[elementIndex].neighbourK == oldNeighbour) {
		Elements[elementIndex].neighbourK = newNeighbour;
	}
}


tMeshNode *
EasyMesh::getNode(int nodeIndex)
{
	return getEasyMeshItem(Nodes, NodeCount, nodeIndex, "node");
}


tMeshSide *
EasyMesh::getSide(int sideIndex)
{
	return getEasyMeshItem(Sides, SideCount, sideIndex, "side");
}


/** @brief Compute the signed XY area of a triangle.
    @param[in] firstNode First triangle node.
    @param[in] secondNode Second triangle node.
    @param[in] thirdNode Third triangle node.
    @return Positive area for counter-clockwise winding.
 */
static double
signedTriangleArea(const tMeshNode *firstNode, const tMeshNode *secondNode,
                   const tMeshNode *thirdNode)
{
	return 0.5 * ((secondNode->x - firstNode->x) * (thirdNode->y - firstNode->y)
	              - (secondNode->y - firstNode->y) * (thirdNode->x - firstNode->x));
}


/** @brief Test whether two points lie strictly on opposite sides of a line. */
static bool
nodesAreOnOppositeSides(const tMeshNode *lineStart,
	                  const tMeshNode *lineEnd,
	                  const tMeshNode *first,
	                  const tMeshNode *second)
{
	double firstArea = signedTriangleArea(lineStart, lineEnd, first);
	double secondArea = signedTriangleArea(lineStart, lineEnd, second);
	return ((firstArea > GEOMETRY_EPSILON) &&
	        (secondArea < -GEOMETRY_EPSILON)) ||
	       ((firstArea < -GEOMETRY_EPSILON) &&
	        (secondArea > GEOMETRY_EPSILON));
}


/** @brief Test whether two open line segments cross away from endpoints. */
static bool
meshSegmentsProperlyIntersect(const tMeshNode *firstStart,
	                        const tMeshNode *firstEnd,
	                        const tMeshNode *secondStart,
	                        const tMeshNode *secondEnd)
{
	return nodesAreOnOppositeSides(firstStart, firstEnd,
	                               secondStart, secondEnd) &&
	       nodesAreOnOppositeSides(secondStart, secondEnd,
	                               firstStart, firstEnd);
}


/** @brief Compute the XY distance between two mesh nodes.
    @param[in] firstNode First node.
    @param[in] secondNode Second node.
    @return Euclidean XY distance.
 */
static double
nodeDistance(const tMeshNode *firstNode, const tMeshNode *secondNode)
{
	return sqrt((secondNode->x-firstNode->x)*(secondNode->x-firstNode->x)
	            + (secondNode->y-firstNode->y)*(secondNode->y-firstNode->y) );
}


/** @brief Find the first triangle containing a node in the XY plane.
    @param[in] candidateNode Node to locate.
    @return Element index, or ElementCount when no element contains the node.
 */
int
EasyMesh::findContainingElement(const tMeshNode *candidateNode)
{
	int elementIndex;

	for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
		if (signedTriangleArea(candidateNode, &Nodes[Elements[elementIndex].nodeI], &Nodes[Elements[elementIndex].nodeJ]) >= 0.0
		        && signedTriangleArea(candidateNode, &Nodes[Elements[elementIndex].nodeJ], &Nodes[Elements[elementIndex].nodeK]) >= 0.0
		        && signedTriangleArea(candidateNode, &Nodes[Elements[elementIndex].nodeK], &Nodes[Elements[elementIndex].nodeI]) >= 0.0) {
			break;
		}
	}
	return elementIndex;
}


/** @brief Flip unconstrained sides until a newly inserted node is Delaunay.
    @param[in] nodeIndex Index of the newly inserted node.
    @note Mutates Elements and Sides without changing their counts.
 */
void
EasyMesh::restoreDelaunayTriangulation(int nodeIndex)
{
	int adjacentElementIndex;
	int sideIndex;
	bool sideFlipped;
	tMeshNode circumcenter;

	do {
		sideFlipped = false;
		for (sideIndex = 0; sideIndex < SideCount; sideIndex++) {
			if (Sides[sideIndex].marker == 0) {
				if (Sides[sideIndex].oppositeNodeA == nodeIndex) {
					adjacentElementIndex = Sides[sideIndex].elementB;
					if (adjacentElementIndex != MISSING_MESH_INDEX) {
						circumcenter.x = Elements[adjacentElementIndex].circumcenterX;
						circumcenter.y = Elements[adjacentElementIndex].circumcenterY;
						if (nodeDistance(&circumcenter, &Nodes[nodeIndex]) < Elements[adjacentElementIndex].circumradius) {
							flipSide(sideIndex);
							sideFlipped = true;
						}
					}
				} else {
					if (Sides[sideIndex].oppositeNodeB == nodeIndex) {
						adjacentElementIndex = Sides[sideIndex].elementA;
						if (adjacentElementIndex != MISSING_MESH_INDEX) {
							circumcenter.x = Elements[adjacentElementIndex].circumcenterX;
							circumcenter.y = Elements[adjacentElementIndex].circumcenterY;
							if (nodeDistance(&circumcenter, &Nodes[nodeIndex]) < Elements[adjacentElementIndex].circumradius) {
								flipSide(sideIndex);
								sideFlipped = true;
							}
						}
					}
				}
			}
		}
	} while (sideFlipped);

}


/** @brief Update one element's circumcenter, circumradius, and inradius.
    @param[in] elementIndex Element whose geometry is recalculated.
    @note Reads Nodes and Sides and mutates the selected Elements entry.
 */
void
EasyMesh::updateElementGeometry(int elementIndex)
{
	double circumcenterX, circumcenterY;
	double nodeIX, nodeIY, nodeJX, nodeJY, nodeKX, nodeKY;
	double midpointIJX, midpointIJY, midpointJKX, midpointJKY;
	double numerator, denominator;
	double sideILength, sideJLength, sideKLength, perimeter;

	nodeIX = Nodes[Elements[elementIndex].nodeI].x;
	nodeIY = Nodes[Elements[elementIndex].nodeI].y;
	nodeJX = Nodes[Elements[elementIndex].nodeJ].x;
	nodeJY = Nodes[Elements[elementIndex].nodeJ].y;
	nodeKX = Nodes[Elements[elementIndex].nodeK].x;
	nodeKY = Nodes[Elements[elementIndex].nodeK].y;

	midpointIJX = 0.5 * (nodeIX + nodeJX);
	midpointIJY = 0.5 * (nodeIY + nodeJY);
	midpointJKX = 0.5 * (nodeJX + nodeKX);
	midpointJKY = 0.5 * (nodeJY + nodeKY);

	numerator = (midpointIJX - midpointJKX) * (nodeJX - nodeIX) +
	            (midpointIJY - midpointJKY) * (nodeJY - nodeIY);
	denominator = (nodeJX - nodeIX) * (nodeKY - nodeJY) -
	              (nodeKX - nodeJX) * (nodeJY - nodeIY);

	if (denominator > 0) {
		Elements[elementIndex].circumcenterX = circumcenterX = midpointJKX + numerator / denominator * (nodeKY - nodeJY);
		Elements[elementIndex].circumcenterY = circumcenterY = midpointJKY - numerator / denominator * (nodeKX - nodeJX);
		Elements[elementIndex].circumradius = sqrt((nodeIX - circumcenterX) * (nodeIX - circumcenterX) +
		                                                (nodeIY - circumcenterY) * (nodeIY - circumcenterY));
	}

	sideILength = Sides[Elements[elementIndex].sideI].length;
	sideJLength = Sides[Elements[elementIndex].sideJ].length;
	sideKLength = Sides[Elements[elementIndex].sideK].length;
	perimeter = sideILength + sideJLength + sideKLength;
	Elements[elementIndex].signedDoubleArea =
	        nodeIX * (nodeJY - nodeKY) - nodeJX * (nodeIY - nodeKY) +
	        nodeKX * (nodeIY - nodeJY);
	Elements[elementIndex].inradius = Elements[elementIndex].signedDoubleArea / perimeter;
}


/** @brief Interpolate target spacing for a node inside an element.
    @param[in] elementIndex Element containing the node.
    @param[in] nodeIndex Node whose spacing is written.
    @note Uses a linear interpolation of the element's three node spacings.
 */
void
EasyMesh::interpolateNodeSpacing(int elementIndex, int nodeIndex)
{
	double edgeIJX, edgeIJY, edgeIKX, edgeIKY;
	double offsetX, offsetY, determinant;
	double nodeJWeight, nodeKWeight;

	edgeIJX = Nodes[Elements[elementIndex].nodeJ].x - Nodes[Elements[elementIndex].nodeI].x;
	edgeIJY = Nodes[Elements[elementIndex].nodeJ].y - Nodes[Elements[elementIndex].nodeI].y;
	edgeIKX = Nodes[Elements[elementIndex].nodeK].x - Nodes[Elements[elementIndex].nodeI].x;
	edgeIKY = Nodes[Elements[elementIndex].nodeK].y - Nodes[Elements[elementIndex].nodeI].y;
	offsetX = Nodes[nodeIndex].x - Nodes[Elements[elementIndex].nodeI].x;
	offsetY = Nodes[nodeIndex].y - Nodes[Elements[elementIndex].nodeI].y;

	determinant = edgeIJX * edgeIKY - edgeIKX * edgeIJY;

	nodeJWeight = (+edgeIKY * offsetX - edgeIKX * offsetY) / determinant;
	nodeKWeight = (-edgeIJY * offsetX + edgeIJX * offsetY) / determinant;

	Nodes[nodeIndex].spacing = Nodes[Elements[elementIndex].nodeI].spacing +
	            nodeJWeight * (Nodes[Elements[elementIndex].nodeJ].spacing - Nodes[Elements[elementIndex].nodeI].spacing) +
	            nodeKWeight * (Nodes[Elements[elementIndex].nodeK].spacing - Nodes[Elements[elementIndex].nodeI].spacing);
}


/** @brief Insert a node and split its containing element into three.
    @param[in] x New node X coordinate.
    @param[in] y New node Y coordinate.
    @param[in] z New node elevation.
    @param[in] spacingMode Whether target spacing is interpolated.
    @param[in] previousNodeIndex Previous constrained-chain node, or MISSING_MESH_INDEX.
    @param[in] previousSideMarker Marker for the preceding constrained side.
    @param[in] nodeMarker Marker assigned to the new node.
    @param[in] nextSideMarker Marker for the following constrained side.
    @param[in] nextNodeIndex Following constrained-chain node, or MISSING_MESH_INDEX.
    @return Index of the split element, or MISSING_MESH_INDEX when a refinement
            candidate is rejected.
    @note Successful insertion increments NodeCount by one, ElementCount by
          two, and SideCount by three, then restores Delaunay connectivity.
 */
int
EasyMesh::insertNode(double x, double y, double z, tNodeSpacingMode spacingMode,
           int previousNodeIndex, int previousSideMarker, int nodeMarker, int nextSideMarker, int nextNodeIndex)
{
	int oldNodeI, oldNodeJ, oldNodeK, containingElement;
	int oldNeighbourJ, oldNeighbourK, sideIndex;
	int oldSideI, oldSideJ, oldSideK;
	double sideDeltaX, sideDeltaY;

	if (spacingMode == INTERPOLATE_NODE_SPACING) {
		NodeInsertionFailureReason = "unknown-insertion-failure";
	}

	if (NodeCount >= EASYMESH_MAX_NODES) {
		if (spacingMode == INTERPOLATE_NODE_SPACING) {
			NodeInsertionFailureReason = "node-capacity";
			return MISSING_MESH_INDEX;
		}
		printf("\nResize EASYMESH_MAX_NODES... > %d\n", EASYMESH_MAX_NODES);
		exit(1);
	}

	if ((x < MeshMinX) || (x > MeshMaxX) || (y < MeshMinY) || (y > MeshMaxY)) {
		if (spacingMode == KEEP_NODE_SPACING) {
			printf("\nDon't Insert %f %f\n", x, y);
			exit(1);
		}
		NodeInsertionFailureReason = "outside-mesh-bounds";
		return MISSING_MESH_INDEX;
	}

	Nodes[NodeCount].x = x;
	Nodes[NodeCount].y = y;
	Nodes[NodeCount].z = z;
	Nodes[NodeCount].marker = nodeMarker;

	containingElement = findContainingElement(&Nodes[NodeCount]);
	if (containingElement >= ElementCount) {
		if (spacingMode == KEEP_NODE_SPACING) {
			fprintf(stderr, "\nEasyMesh: no element contains node (%f, %f)\n", x, y);
			exit(1);
		}
		NodeInsertionFailureReason = "no-containing-element";
		return MISSING_MESH_INDEX;
	}
	if ((spacingMode == INTERPOLATE_NODE_SPACING) &&
	        elementIsMissingOrRemoved(containingElement)) {
		NodeInsertionFailureReason = "candidate-outside-active-domain";
		return MISSING_MESH_INDEX;
	}
	if ((spacingMode == INTERPOLATE_NODE_SPACING) &&
	        (easyMeshPointsAreNear(x, y, Nodes[Elements[containingElement].nodeI].x, Nodes[Elements[containingElement].nodeI].y, GEOMETRY_EPSILON) ||
	         easyMeshPointsAreNear(x, y, Nodes[Elements[containingElement].nodeJ].x, Nodes[Elements[containingElement].nodeJ].y, GEOMETRY_EPSILON) ||
	         easyMeshPointsAreNear(x, y, Nodes[Elements[containingElement].nodeK].x, Nodes[Elements[containingElement].nodeK].y, GEOMETRY_EPSILON))) {
		NodeInsertionFailureReason = "near-existing-vertex";
		return MISSING_MESH_INDEX;
	}
	if ((spacingMode == INTERPOLATE_NODE_SPACING) &&
	        ((signedTriangleArea(&Nodes[NodeCount], &Nodes[Elements[containingElement].nodeI], &Nodes[Elements[containingElement].nodeJ]) <= GEOMETRY_EPSILON) ||
	         (signedTriangleArea(&Nodes[NodeCount], &Nodes[Elements[containingElement].nodeJ], &Nodes[Elements[containingElement].nodeK]) <= GEOMETRY_EPSILON) ||
	         (signedTriangleArea(&Nodes[NodeCount], &Nodes[Elements[containingElement].nodeK], &Nodes[Elements[containingElement].nodeI]) <= GEOMETRY_EPSILON))) {
		NodeInsertionFailureReason = "near-existing-edge";
		return MISSING_MESH_INDEX;
	}

	NodeCount++;
	if (!Quiet) {
		printf("\r%d Nodes", NodeCount);
		fflush(stdout);
	}

	if(spacingMode==INTERPOLATE_NODE_SPACING) {
		interpolateNodeSpacing(containingElement, NodeCount-1);
		if (!easyMeshValueIsFinite(Nodes[NodeCount - 1].spacing)) {
			NodeCount--;
			NodeInsertionFailureReason = "non-finite-refinement-spacing";
			return MISSING_MESH_INDEX;
		}
	}

	oldNodeI  = Elements[containingElement].nodeI;
	oldNodeJ  = Elements[containingElement].nodeJ;
	oldNodeK  = Elements[containingElement].nodeK;
	oldNeighbourJ = Elements[containingElement].neighbourJ;
	oldNeighbourK = Elements[containingElement].neighbourK;
	oldSideI = Elements[containingElement].sideI;
	oldSideJ = Elements[containingElement].sideJ;
	oldSideK = Elements[containingElement].sideK;

	clearEasyMeshRefinementBlock(Elements, ElementCount, containingElement);

	ElementCount += 2;
	SideCount += 3;
	Elements[ElementCount-2].refinementBlocked = 0;
	Elements[ElementCount-1].refinementBlocked = 0;

	/* Add the other two triangles created by splitting the containing element. */
	Elements[ElementCount-2].nodeI = NodeCount - 1;
	Elements[ElementCount-2].nodeJ = oldNodeK;
	Elements[ElementCount-2].nodeK = oldNodeI;
	Elements[ElementCount-1].nodeI = NodeCount - 1;
	Elements[ElementCount-1].nodeJ = oldNodeI;
	Elements[ElementCount-1].nodeK = oldNodeJ;

	Elements[ElementCount-2].neighbourI = oldNeighbourJ;
	Elements[ElementCount-2].neighbourJ = ElementCount - 1;
	Elements[ElementCount-2].neighbourK = containingElement;
	Elements[ElementCount-1].neighbourI = oldNeighbourK;
	Elements[ElementCount-1].neighbourJ = containingElement;
	Elements[ElementCount-1].neighbourK = ElementCount - 2;

	Elements[ElementCount-2].sideI = oldSideJ;
	Elements[ElementCount-2].sideJ = SideCount - 2;
	Elements[ElementCount-2].sideK = SideCount - 3;
	Elements[ElementCount-1].sideI = oldSideK;
	Elements[ElementCount-1].sideJ = SideCount - 1;
	Elements[ElementCount-1].sideK = SideCount - 2;

	/* Add the three sides from the inserted node to the original vertices. */
	Sides[SideCount-3].startNode  = oldNodeK;
	Sides[SideCount-3].endNode  = NodeCount - 1;
	Sides[SideCount-3].oppositeNodeA  = oldNodeJ;
	Sides[SideCount-3].oppositeNodeB  = oldNodeI;
	Sides[SideCount-3].elementA = containingElement;
	Sides[SideCount-3].elementB = ElementCount - 2;

	Sides[SideCount-2].startNode  = oldNodeI;
	Sides[SideCount-2].endNode  = NodeCount - 1;
	Sides[SideCount-2].oppositeNodeA  = oldNodeK;
	Sides[SideCount-2].oppositeNodeB  = oldNodeJ;
	Sides[SideCount-2].elementA = ElementCount - 2;
	Sides[SideCount-2].elementB = ElementCount - 1;

	Sides[SideCount-1].startNode  = oldNodeJ;
	Sides[SideCount-1].endNode  = NodeCount - 1;
	Sides[SideCount-1].oppositeNodeA  = oldNodeI;
	Sides[SideCount-1].oppositeNodeB  = oldNodeK;
	Sides[SideCount-1].elementA = ElementCount - 1;
	Sides[SideCount-1].elementB = containingElement;

	for (sideIndex = 1; sideIndex <= 3; sideIndex++) {
		sideDeltaX = Nodes[Sides[SideCount-sideIndex].startNode].x - Nodes[Sides[SideCount-sideIndex].endNode].x;
		sideDeltaY = Nodes[Sides[SideCount-sideIndex].startNode].y - Nodes[Sides[SideCount-sideIndex].endNode].y;
		Sides[SideCount-sideIndex].length = sqrt(sideDeltaX * sideDeltaX + sideDeltaY * sideDeltaY);
	}

	Elements[containingElement].nodeI  = NodeCount - 1;
	Elements[containingElement].neighbourJ = ElementCount - 2;
	Elements[containingElement].neighbourK = ElementCount - 1;
	Elements[containingElement].sideJ = SideCount - 3;
	Elements[containingElement].sideK = SideCount - 1;

	if (Sides[oldSideI].oppositeNodeA == oldNodeI) {
		Sides[oldSideI].oppositeNodeA  = NodeCount - 1;
		Sides[oldSideI].elementA = containingElement;
	}
	if (Sides[oldSideI].oppositeNodeB == oldNodeI) {
		Sides[oldSideI].oppositeNodeB  = NodeCount - 1;
		Sides[oldSideI].elementB = containingElement;
	}

	if (Sides[oldSideJ].oppositeNodeA == oldNodeJ) {
		Sides[oldSideJ].oppositeNodeA  = NodeCount - 1;
		Sides[oldSideJ].elementA = ElementCount - 2;
	}
	if (Sides[oldSideJ].oppositeNodeB == oldNodeJ) {
		Sides[oldSideJ].oppositeNodeB  = NodeCount - 1;
		Sides[oldSideJ].elementB = ElementCount - 2;
	}

	if (Sides[oldSideK].oppositeNodeA == oldNodeK) {
		Sides[oldSideK].oppositeNodeA = NodeCount - 1;
		Sides[oldSideK].elementA = ElementCount - 1;
	}
	if (Sides[oldSideK].oppositeNodeB == oldNodeK) {
		Sides[oldSideK].oppositeNodeB = NodeCount - 1;
		Sides[oldSideK].elementB = ElementCount - 1;
	}

	if (oldNeighbourJ != MISSING_MESH_INDEX) {
		replaceElementNeighbour(oldNeighbourJ, containingElement,
		                        ElementCount - 2);
	}

	if (oldNeighbourK != MISSING_MESH_INDEX) {
		replaceElementNeighbour(oldNeighbourK, containingElement,
		                        ElementCount - 1);
	}

	/* Refresh geometry for all three triangles produced by the split. */
	updateElementGeometry(containingElement);
	updateElementGeometry(ElementCount - 2);
	updateElementGeometry(ElementCount - 1);

	restoreDelaunayTriangulation(NodeCount - 1);

	/* Restore constrained markers after Delaunay side flips. */
	for (sideIndex = 3; sideIndex < SideCount; sideIndex++) {
		if (Sides[sideIndex].startNode == previousNodeIndex && Sides[sideIndex].endNode == NodeCount - 1) {
			Sides[sideIndex].marker = previousSideMarker;
		}
		if (Sides[sideIndex].endNode == previousNodeIndex && Sides[sideIndex].startNode == NodeCount - 1) {
			Sides[sideIndex].marker = previousSideMarker;
		}
		if (Sides[sideIndex].startNode == nextNodeIndex && Sides[sideIndex].endNode == NodeCount - 1) {
			Sides[sideIndex].marker = nextSideMarker;
		}
		if (Sides[sideIndex].endNode == nextNodeIndex && Sides[sideIndex].startNode == NodeCount - 1) {
			Sides[sideIndex].marker = nextSideMarker;
		}
	}

	if (spacingMode == INTERPOLATE_NODE_SPACING) {
		NodeInsertionFailureReason = NULL;
	}
	return containingElement;
}


/** @brief Replace one shared diagonal by the other diagonal of its quadrilateral.
    @param[in] sideIndex Side to flip.
    @note Preserves element and side counts while updating both adjacent
          elements, all affected neighbour links, and side correspondence.
 */
void
EasyMesh::flipSide(int sideIndex)
{
	int oppositeNodeAIndex, oppositeNodeBIndex, startNodeIndex, endNodeIndex;
	int elementAIndex, elementBIndex;
	int elementAcrossAC = 0, elementAcrossAD = 0;
	int elementAcrossBC = 0, elementAcrossBD = 0;
	int sideAD = 0, sideAC = 0, sideBC = 0, sideBD = 0;
	double sideDeltaX, sideDeltaY;

	elementAIndex=Sides[sideIndex].elementA;
	elementBIndex=Sides[sideIndex].elementB;
	oppositeNodeAIndex = Sides[sideIndex].oppositeNodeA;
	oppositeNodeBIndex = Sides[sideIndex].oppositeNodeB;
	startNodeIndex = Sides[sideIndex].startNode;
	endNodeIndex = Sides[sideIndex].endNode;

	if (Elements[elementAIndex].neighbourI == elementBIndex) {
		elementAcrossAD = Elements[elementAIndex].neighbourJ;
		elementAcrossAC = Elements[elementAIndex].neighbourK;
		sideAD = Elements[elementAIndex].sideJ;
		sideAC = Elements[elementAIndex].sideK;
	}

	if (Elements[elementAIndex].neighbourJ == elementBIndex) {
		elementAcrossAD = Elements[elementAIndex].neighbourK;
		elementAcrossAC = Elements[elementAIndex].neighbourI;
		sideAD = Elements[elementAIndex].sideK;
		sideAC = Elements[elementAIndex].sideI;
	}

	if (Elements[elementAIndex].neighbourK == elementBIndex) {
		elementAcrossAD = Elements[elementAIndex].neighbourI;
		elementAcrossAC = Elements[elementAIndex].neighbourJ;
		sideAD = Elements[elementAIndex].sideI;
		sideAC = Elements[elementAIndex].sideJ;
	}

	if (Elements[elementBIndex].neighbourI == elementAIndex) {
		elementAcrossBC = Elements[elementBIndex].neighbourJ;
		elementAcrossBD = Elements[elementBIndex].neighbourK;
		sideBC = Elements[elementBIndex].sideJ;
		sideBD = Elements[elementBIndex].sideK;
	}

	if (Elements[elementBIndex].neighbourJ == elementAIndex) {
		elementAcrossBC = Elements[elementBIndex].neighbourK;
		elementAcrossBD = Elements[elementBIndex].neighbourI;
		sideBC = Elements[elementBIndex].sideK;
		sideBD = Elements[elementBIndex].sideI;
	}

	if (Elements[elementBIndex].neighbourK == elementAIndex) {
		elementAcrossBC = Elements[elementBIndex].neighbourI;
		elementAcrossBD = Elements[elementBIndex].neighbourJ;
		sideBC = Elements[elementBIndex].sideI;
		sideBD = Elements[elementBIndex].sideJ;
	}

	clearEasyMeshRefinementBlock(Elements, ElementCount, elementAIndex);
	clearEasyMeshRefinementBlock(Elements, ElementCount, elementBIndex);

	Elements[elementAIndex].nodeI  = oppositeNodeAIndex;
	Elements[elementAIndex].nodeJ  = oppositeNodeBIndex;
	Elements[elementAIndex].nodeK  = endNodeIndex;
	Elements[elementAIndex].neighbourI = elementAcrossBD;
	Elements[elementAIndex].neighbourJ = elementAcrossAD;
	Elements[elementAIndex].neighbourK = elementBIndex;
	Elements[elementAIndex].sideI = sideBD;
	Elements[elementAIndex].sideJ = sideAD;
	Elements[elementAIndex].sideK = sideIndex;

	Elements[elementBIndex].nodeI  = oppositeNodeAIndex;
	Elements[elementBIndex].nodeJ  = startNodeIndex;
	Elements[elementBIndex].nodeK  = oppositeNodeBIndex;
	Elements[elementBIndex].neighbourI = elementAcrossBC;
	Elements[elementBIndex].neighbourJ = elementAIndex;
	Elements[elementBIndex].neighbourK = elementAcrossAC;
	Elements[elementBIndex].sideI = sideBC;
	Elements[elementBIndex].sideJ = sideIndex;
	Elements[elementBIndex].sideK = sideAC;

	if (elementAcrossAC != MISSING_MESH_INDEX) {
		replaceElementNeighbour(elementAcrossAC, elementAIndex, elementBIndex);
	}

	if (elementAcrossBD != MISSING_MESH_INDEX) {
		replaceElementNeighbour(elementAcrossBD, elementBIndex, elementAIndex);
	}

	if (Sides[sideAD].elementA == elementAIndex) {
		Sides[sideAD].oppositeNodeA = oppositeNodeBIndex;
	}
	if (Sides[sideAD].elementB == elementAIndex) {
		Sides[sideAD].oppositeNodeB = oppositeNodeBIndex;
	}

	if (Sides[sideBC].elementA == elementBIndex) {
		Sides[sideBC].oppositeNodeA = oppositeNodeAIndex;
	}
	if (Sides[sideBC].elementB == elementBIndex) {
		Sides[sideBC].oppositeNodeB = oppositeNodeAIndex;
	}

	if (Sides[sideBD].elementA == elementBIndex) {
		Sides[sideBD].elementA = elementAIndex;
		Sides[sideBD].oppositeNodeA = oppositeNodeAIndex;
	}
	if (Sides[sideBD].elementB == elementBIndex) {
		Sides[sideBD].elementB = elementAIndex;
		Sides[sideBD].oppositeNodeB = oppositeNodeAIndex;
	}

	if (oppositeNodeAIndex < oppositeNodeBIndex) {
		Sides[sideIndex].startNode  = oppositeNodeAIndex;
		Sides[sideIndex].endNode  = oppositeNodeBIndex;
		Sides[sideIndex].oppositeNodeA  = endNodeIndex;
		Sides[sideIndex].oppositeNodeB  = startNodeIndex;
		Sides[sideIndex].elementA = elementAIndex;
		Sides[sideIndex].elementB = elementBIndex;
	} else {
		Sides[sideIndex].startNode  = oppositeNodeBIndex;
		Sides[sideIndex].endNode  = oppositeNodeAIndex;
		Sides[sideIndex].oppositeNodeA  = startNodeIndex;
		Sides[sideIndex].oppositeNodeB  = endNodeIndex;
		Sides[sideIndex].elementA = elementBIndex;
		Sides[sideIndex].elementB = elementAIndex;
	}

	sideDeltaX = Nodes[Sides[sideIndex].startNode].x - Nodes[Sides[sideIndex].endNode].x;
	sideDeltaY = Nodes[Sides[sideIndex].startNode].y - Nodes[Sides[sideIndex].endNode].y;
	Sides[sideIndex].length = sqrt(sideDeltaX * sideDeltaX + sideDeltaY * sideDeltaY);

	if (Sides[sideAC].elementA == elementAIndex) {
		Sides[sideAC].elementA = elementBIndex;
		Sides[sideAC].oppositeNodeA = oppositeNodeBIndex;
	}
	if (Sides[sideAC].elementB == elementAIndex) {
		Sides[sideAC].elementB = elementBIndex;
		Sides[sideAC].oppositeNodeB = oppositeNodeBIndex;
	}

	if (Sides[sideAD].elementA == elementAIndex) {
		Sides[sideAD].oppositeNodeA = oppositeNodeBIndex;
	}
	if (Sides[sideAD].elementB == elementAIndex) {
		Sides[sideAD].oppositeNodeB = oppositeNodeBIndex;
	}

	if (Sides[sideBC].elementA == elementBIndex) {
		Sides[sideBC].oppositeNodeA = oppositeNodeAIndex;
	}
	if (Sides[sideBC].elementB == elementBIndex) {
		Sides[sideBC].oppositeNodeB = oppositeNodeAIndex;
	}

	if (Sides[sideBD].elementA == elementBIndex) {
		Sides[sideBD].elementA = elementAIndex;
		Sides[sideBD].oppositeNodeA = oppositeNodeAIndex;
	}
	if (Sides[sideBD].elementB == elementBIndex) {
		Sides[sideBD].elementB = elementAIndex;
		Sides[sideBD].oppositeNodeB = oppositeNodeAIndex;
	}

	updateElementGeometry(elementAIndex);
	updateElementGeometry(elementBIndex);
}


/** @brief Eliminate supertriangle and out-of-domain topology.
    @note Marks removed Elements, Sides, and Nodes with MISSING_MESH_INDEX and
          clears neighbour links that cross outside the active domain.
 */
void
EasyMesh::eraseOutsideDomain()
{
	int sideIndex, nodeIndex, elementIndex;
	int lowestNodeIndex, middleNodeIndex, highestNodeIndex;

	/* Closed chains retain only triangles with the active winding. */
	for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
		if ((Nodes[Elements[elementIndex].nodeI].chainIndex == Nodes[Elements[elementIndex].nodeJ].chainIndex) &&
		        (Nodes[Elements[elementIndex].nodeJ].chainIndex == Nodes[Elements[elementIndex].nodeK].chainIndex) &&
		        (BoundaryChains[Nodes[Elements[elementIndex].nodeI].chainIndex].type == BOUNDARY_CHAIN_CLOSED)) {
			lowestNodeIndex = min(min(Elements[elementIndex].nodeI, Elements[elementIndex].nodeJ), Elements[elementIndex].nodeK);
			highestNodeIndex = max(max(Elements[elementIndex].nodeI, Elements[elementIndex].nodeJ), Elements[elementIndex].nodeK);
			middleNodeIndex = Elements[elementIndex].nodeI + Elements[elementIndex].nodeJ + Elements[elementIndex].nodeK - lowestNodeIndex - highestNodeIndex;

			if (lowestNodeIndex < 3) {
				Elements[elementIndex].marker = MISSING_MESH_INDEX;
			} else {
				if (signedTriangleArea(&Nodes[lowestNodeIndex], &Nodes[middleNodeIndex], &Nodes[highestNodeIndex]) < 0.0) {
					Elements[elementIndex].marker = MISSING_MESH_INDEX;
				}
			}
		}
	}


	for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
		if (elementIsMissingOrRemoved(Elements[elementIndex].neighbourI)) {
			Elements[elementIndex].neighbourI = MISSING_MESH_INDEX;
		}
		if (elementIsMissingOrRemoved(Elements[elementIndex].neighbourJ)) {
			Elements[elementIndex].neighbourJ = MISSING_MESH_INDEX;
		}
		if (elementIsMissingOrRemoved(Elements[elementIndex].neighbourK)) {
			Elements[elementIndex].neighbourK = MISSING_MESH_INDEX;
		}
	}

	/* Remove sides with no active adjacent element. */
	for (sideIndex = 0; sideIndex < 3; sideIndex++) {
		Sides[sideIndex].marker = MISSING_MESH_INDEX;
	}

	for (sideIndex = 3; sideIndex < SideCount; sideIndex++) {
		if (elementIsMissingOrRemoved(Sides[sideIndex].elementA) &&
		        elementIsMissingOrRemoved(Sides[sideIndex].elementB)) {
			Sides[sideIndex].marker = MISSING_MESH_INDEX;
		}
	}


	for (sideIndex = 3; sideIndex < SideCount; sideIndex++) {
		if (Sides[sideIndex].marker != MISSING_MESH_INDEX) {
			if (elementIsMissingOrRemoved(Sides[sideIndex].elementA)) {
				Sides[sideIndex].elementA = MISSING_MESH_INDEX;
				Sides[sideIndex].oppositeNodeA = MISSING_MESH_INDEX;
			}
			if (elementIsMissingOrRemoved(Sides[sideIndex].elementB)) {
				Sides[sideIndex].elementB = MISSING_MESH_INDEX;
				Sides[sideIndex].oppositeNodeB = MISSING_MESH_INDEX;
			}
		}
	}


	/* Remove the three containing-supertriangle nodes. */
	for (nodeIndex = 0; nodeIndex < 3; nodeIndex++) {
		Nodes[nodeIndex].marker = MISSING_MESH_INDEX;
	}


}


/** @brief Mark adjacent element pairs done when their surrounding diamond is done.
    @note Invalid adjacency blocks both elements to protect later refinement.
 */
void
EasyMesh::completeDiamondElements()
{
	int elementAIndex, elementBIndex;
	int elementACIndex, elementADIndex, elementBCIndex, elementBDIndex;
	int sideIndex;
	tMeshElement *elementA, *elementB, *elementAC, *elementAD, *elementBC, *elementBD;

	for (sideIndex = 0; sideIndex < SideCount; sideIndex++) {
		if (Sides[sideIndex].marker != MISSING_MESH_INDEX) {
			elementAIndex = Sides[sideIndex].elementA;
			elementBIndex = Sides[sideIndex].elementB;
			elementA = getElement(elementAIndex);
			elementB = getElement(elementBIndex);
			if ((elementA == NULL) || (elementB == NULL) ||
			        (elementA->marker == MISSING_MESH_INDEX) || (elementB->marker == MISSING_MESH_INDEX)) {
				continue;
			}
			if ((getEasyMeshOppositeNeighbours(elementA, elementBIndex, &elementACIndex, &elementADIndex) != 1) ||
			        (getEasyMeshOppositeNeighbours(elementB, elementAIndex, &elementBCIndex, &elementBDIndex) != 1)) {
				fprintf(stderr,
				        "EasyMesh: inconsistent adjacency for side %d (%d, %d, %d, %d) "
				        "between elements %d (%d, %d, %d) and %d (%d, %d, %d)\n",
				        sideIndex, Sides[sideIndex].oppositeNodeA, Sides[sideIndex].oppositeNodeB,
				        Sides[sideIndex].startNode, Sides[sideIndex].endNode,
				        elementAIndex, elementA->neighbourI, elementA->neighbourJ, elementA->neighbourK,
				        elementBIndex, elementB->neighbourI, elementB->neighbourJ, elementB->neighbourK);
				elementA->refinementBlocked = 1;
				elementB->refinementBlocked = 1;
				elementA->refinementState = ELEMENT_DONE;
				elementB->refinementState = ELEMENT_DONE;
				continue;
			}

			elementAC = getElement(elementACIndex);
			elementAD = getElement(elementADIndex);
			elementBC = getElement(elementBCIndex);
			elementBD = getElement(elementBDIndex);
			if (((elementAC == NULL) || (elementAC->refinementState == ELEMENT_DONE)) &&
			        ((elementBC == NULL) || (elementBC->refinementState == ELEMENT_DONE)) &&
			        ((elementAD == NULL) || (elementAD->refinementState == ELEMENT_DONE)) &&
			        ((elementBD == NULL) || (elementBD->refinementState == ELEMENT_DONE))) {
				elementA->refinementState = ELEMENT_DONE;
				elementB->refinementState = ELEMENT_DONE;
			}
		}
	}

}


/** @brief Classify elements and select the next refinement candidate.
    @note Scans every active element, updates refinementState, and stores the
          worst eligible element in RefinementElement.
 */
void
EasyMesh::classifyElements()
{
	int elementIndex, neighbourI, neighbourJ, neighbourK;
	int sideIIndex, sideJIndex, sideKIndex;
	double worstQualityRatio = ACCEPTED_RADIUS_SPACING_RATIO, targetSpacing;

	RefinementElement = MISSING_MESH_INDEX;

	for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
		if (Elements[elementIndex].marker != MISSING_MESH_INDEX) {
			neighbourI = Elements[elementIndex].neighbourI;
			neighbourJ = Elements[elementIndex].neighbourJ;
			neighbourK = Elements[elementIndex].neighbourK;

			targetSpacing = (Nodes[Elements[elementIndex].nodeI].spacing + Nodes[Elements[elementIndex].nodeJ].spacing + Nodes[Elements[elementIndex].nodeK].spacing) / 3.0;
			if (!easyMeshValueIsFinite(targetSpacing) ||
			        !easyMeshValueIsFinite(Elements[elementIndex].circumradius) ||
			        !easyMeshValueIsFinite(Elements[elementIndex].inradius)) {
				fprintf(stderr,
				        "EasyMesh: non-finite refinement geometry at element %d "
				        "(spacing=%g, circumradius=%g, inradius=%g)\n",
				        elementIndex, targetSpacing, Elements[elementIndex].circumradius, Elements[elementIndex].inradius);
				Elements[elementIndex].refinementBlocked = 1;
				Elements[elementIndex].refinementState = ELEMENT_DONE;
				continue;
			}

			Elements[elementIndex].refinementState = ELEMENT_WAITING;

			if (Elements[elementIndex].refinementBlocked ||
			        (Elements[elementIndex].circumradius < ACCEPTED_RADIUS_SPACING_RATIO * targetSpacing)) {
				Elements[elementIndex].refinementState = ELEMENT_DONE;
			}

			/* An element surrounded by done neighbours is also done. */
			if (neighbourI != MISSING_MESH_INDEX && neighbourJ != MISSING_MESH_INDEX && neighbourK != MISSING_MESH_INDEX) {
				if (Elements[neighbourI].refinementState == ELEMENT_DONE && Elements[neighbourJ].refinementState == ELEMENT_DONE && Elements[neighbourK].refinementState == ELEMENT_DONE) {
					Elements[elementIndex].refinementState=ELEMENT_DONE;
				}
			}
		}
	}


	completeDiamondElements();

	/* Prefer the worst active element touching a constrained boundary. */
	for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
		if (Elements[elementIndex].marker != MISSING_MESH_INDEX && Elements[elementIndex].refinementState != ELEMENT_DONE) {
			sideIIndex = Elements[elementIndex].sideI;
			sideJIndex = Elements[elementIndex].sideJ;
			sideKIndex = Elements[elementIndex].sideK;

			if (Sides[sideIIndex].marker != 0) {
				Elements[elementIndex].refinementState = ELEMENT_ACTIVE;
			}
			if (Sides[sideJIndex].marker != 0) {
				Elements[elementIndex].refinementState = ELEMENT_ACTIVE;
			}
			if (Sides[sideKIndex].marker != 0) {
				Elements[elementIndex].refinementState = ELEMENT_ACTIVE;
			}

			if (Elements[elementIndex].refinementState == ELEMENT_ACTIVE && Elements[elementIndex].circumradius / Elements[elementIndex].inradius > worstQualityRatio) {
				worstQualityRatio = max(worstQualityRatio, Elements[elementIndex].circumradius/Elements[elementIndex].inradius);
				RefinementElement = elementIndex;
			}
		}
	}


	/* Search inward from done neighbours only when the boundary is accepted. */
	if (RefinementElement == MISSING_MESH_INDEX) {
		for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
			if (Elements[elementIndex].marker != MISSING_MESH_INDEX) {
				if (Elements[elementIndex].refinementState != ELEMENT_DONE) {
					neighbourI = Elements[elementIndex].neighbourI;
					neighbourJ = Elements[elementIndex].neighbourJ;
					neighbourK = Elements[elementIndex].neighbourK;

					if (neighbourI != MISSING_MESH_INDEX) {
						if (Elements[neighbourI].refinementState == ELEMENT_DONE) {
							Elements[elementIndex].refinementState = ELEMENT_ACTIVE;
						}
					}
					if (neighbourJ != MISSING_MESH_INDEX) {
						if (Elements[neighbourJ].refinementState == ELEMENT_DONE) {
							Elements[elementIndex].refinementState = ELEMENT_ACTIVE;
						}
					}
					if (neighbourK != MISSING_MESH_INDEX) {
						if (Elements[neighbourK].refinementState == ELEMENT_DONE) {
							Elements[elementIndex].refinementState = ELEMENT_ACTIVE;
						}
					}
					if (Elements[elementIndex].refinementState == ELEMENT_ACTIVE && Elements[elementIndex].circumradius/Elements[elementIndex].inradius > worstQualityRatio) {
						worstQualityRatio = max(worstQualityRatio, Elements[elementIndex].circumradius / Elements[elementIndex].inradius);
						RefinementElement = elementIndex;
					}
				}
			}
		}
	}
}


/** @brief Choose the preferred side for one refinement element.
    @param[in] elementIndex Element being refined.
    @return A constrained side or a side next to a done neighbour, otherwise
            MISSING_MESH_INDEX.
 */
int
EasyMesh::getPreferredRefinementSide(int elementIndex)
{
	tMeshElement *element = getElement(elementIndex);
	tMeshElement *neighbour;
	tMeshSide *elementSide;
	int preferredSide = MISSING_MESH_INDEX;

	if (element == NULL) {
		return MISSING_MESH_INDEX;
	}
	neighbour = getElement(element->neighbourI);
	if ((neighbour != NULL) && (neighbour->refinementState == ELEMENT_DONE)) {
		preferredSide = element->sideI;
	}
	neighbour = getElement(element->neighbourJ);
	if ((neighbour != NULL) && (neighbour->refinementState == ELEMENT_DONE)) {
		preferredSide = element->sideJ;
	}
	neighbour = getElement(element->neighbourK);
	if ((neighbour != NULL) && (neighbour->refinementState == ELEMENT_DONE)) {
		preferredSide = element->sideK;
	}
	elementSide = getSide(element->sideI);
	if ((elementSide != NULL) && (elementSide->marker > 0)) {
		preferredSide = element->sideI;
	}
	elementSide = getSide(element->sideJ);
	if ((elementSide != NULL) && (elementSide->marker > 0)) {
		preferredSide = element->sideJ;
	}
	elementSide = getSide(element->sideK);
	if ((elementSide != NULL) && (elementSide->marker > 0)) {
		preferredSide = element->sideK;
	}
	return preferredSide;
}


/** @brief Try to construct and insert a candidate opposite one element side.
    @param[in] elementIndex Element being refined.
    @param[in] sideIndex Side used to construct the candidate.
    @param[out] reason Rejection or invariant-failure description, or NULL.
    @return Result indicating insertion, recoverable rejection, or stop.
 */
tRefinementResult
EasyMesh::tryRefinementSide(int elementIndex, int sideIndex,
	                        const char **reason)
{
	tMeshElement *element = getElement(elementIndex);
	tMeshSide *candidateSide = getSide(sideIndex);
	tMeshNode *firstNode;
	tMeshNode *secondNode;
	tMeshNode *oppositeNode;
	tMeshNode circumcenter;
	int oppositeNodeIndex = MISSING_MESH_INDEX;
	int oppositeMatches = 0;
	int insertedElement;
	double midpointX, midpointY, midpointZ;
	double halfSideLength, circumcenterOffset, offsetX, offsetY;
	double idealRadius, limitedRadius, candidateDistance;
	double areaProduct, radicand, candidateX, candidateY;

	*reason = NULL;
	if ((element == NULL) || (candidateSide == NULL)) {
		*reason = "missing-refinement-topology";
		return REFINEMENT_STOPPED;
	}
	if (sideIndex == element->sideI) {
		oppositeNodeIndex = element->nodeI;
		oppositeMatches++;
	}
	if (sideIndex == element->sideJ) {
		oppositeNodeIndex = element->nodeJ;
		oppositeMatches++;
	}
	if (sideIndex == element->sideK) {
		oppositeNodeIndex = element->nodeK;
		oppositeMatches++;
	}
	if (oppositeMatches != 1) {
		*reason = "inconsistent-element-side-map";
		return REFINEMENT_STOPPED;
	}
	firstNode = getNode(candidateSide->startNode);
	secondNode = getNode(candidateSide->endNode);
	oppositeNode = getNode(oppositeNodeIndex);
	if ((firstNode == NULL) || (secondNode == NULL) ||
	        (oppositeNode == NULL)) {
		*reason = "missing-refinement-node";
		return REFINEMENT_STOPPED;
	}
	if ((candidateSide->startNode == candidateSide->endNode) ||
	        (candidateSide->startNode == oppositeNodeIndex) ||
	        (candidateSide->endNode == oppositeNodeIndex) ||
	        ((candidateSide->startNode != element->nodeI) &&
	         (candidateSide->startNode != element->nodeJ) &&
	         (candidateSide->startNode != element->nodeK)) ||
	        ((candidateSide->endNode != element->nodeI) &&
	         (candidateSide->endNode != element->nodeJ) &&
	         (candidateSide->endNode != element->nodeK))) {
		*reason = "refinement-side-endpoint-mismatch";
		return REFINEMENT_STOPPED;
	}

	midpointX = 0.5 * (firstNode->x + secondNode->x);
	midpointY = 0.5 * (firstNode->y + secondNode->y);
	midpointZ = 0.5 * (firstNode->z + secondNode->z);
	circumcenter.x = element->circumcenterX;
	circumcenter.y = element->circumcenterY;
	halfSideLength = 0.5 * candidateSide->length;
	offsetX = circumcenter.x - midpointX;
	offsetY = circumcenter.y - midpointY;
	circumcenterOffset = sqrt(offsetX * offsetX + offsetY * offsetY);
	if (!easyMeshValueIsFinite(midpointX) || !easyMeshValueIsFinite(midpointY) ||
	        !easyMeshValueIsFinite(midpointZ) ||
	        !easyMeshValueIsFinite(circumcenter.x) ||
	        !easyMeshValueIsFinite(circumcenter.y) ||
	        !easyMeshValueIsFinite(firstNode->spacing) ||
	        !easyMeshValueIsFinite(secondNode->spacing) ||
	        !easyMeshValueIsFinite(halfSideLength) ||
	        !easyMeshValueIsFinite(circumcenterOffset)) {
		*reason = "non-finite-refinement-geometry";
		return REFINEMENT_STOPPED;
	}
	if (halfSideLength <= GEOMETRY_EPSILON) {
		*reason = "unusable-side-length";
		return REFINEMENT_BLOCKED;
	}
	if (circumcenterOffset <= GEOMETRY_EPSILON) {
		*reason = "unusable-circumcenter-offset";
		return REFINEMENT_BLOCKED;
	}

	idealRadius = IDEAL_TRIANGLE_RADIUS_FACTOR * 0.5 * (firstNode->spacing + secondNode->spacing);
	limitedRadius = min(max(idealRadius, halfSideLength),
	                    0.5 * (halfSideLength * halfSideLength +
	                           circumcenterOffset * circumcenterOffset) /
	                    circumcenterOffset);
	if (!easyMeshValueIsFinite(idealRadius) ||
	        !easyMeshValueIsFinite(limitedRadius)) {
		*reason = "non-finite-refinement-geometry";
		return REFINEMENT_STOPPED;
	}
	if (limitedRadius < halfSideLength) {
		candidateDistance = limitedRadius;
	} else {
		radicand = limitedRadius * limitedRadius - halfSideLength * halfSideLength;
		if (!easyMeshValueIsFinite(radicand)) {
			*reason = "non-finite-refinement-geometry";
			return REFINEMENT_STOPPED;
		}
		if (radicand < 0.0) {
			*reason = "unusable-candidate-distance";
			return REFINEMENT_BLOCKED;
		}
		candidateDistance = limitedRadius + sqrt(radicand);
	}
	if (!easyMeshValueIsFinite(candidateDistance)) {
		*reason = "non-finite-refinement-geometry";
		return REFINEMENT_STOPPED;
	}

	/* Keep candidate points on the same side of the edge as the triangle. */
	areaProduct = signedTriangleArea(firstNode, secondNode, &circumcenter) *
	              signedTriangleArea(firstNode, secondNode, oppositeNode);
	if (!easyMeshValueIsFinite(areaProduct)) {
		*reason = "non-finite-refinement-geometry";
		return REFINEMENT_STOPPED;
	}
	if (areaProduct <= 0.0) {
		*reason = "candidate-outside-domain";
		return REFINEMENT_BLOCKED;
	}

	candidateX = midpointX + candidateDistance * offsetX / circumcenterOffset;
	candidateY = midpointY + candidateDistance * offsetY / circumcenterOffset;
	if (!easyMeshValueIsFinite(candidateX) ||
	        !easyMeshValueIsFinite(candidateY)) {
		*reason = "non-finite-refinement-geometry";
		return REFINEMENT_STOPPED;
	}
	insertedElement = insertNode(candidateX, candidateY, midpointZ,
	                              INTERPOLATE_NODE_SPACING,
	                              MISSING_MESH_INDEX, 0, 0, 0, MISSING_MESH_INDEX);
	if (insertedElement == MISSING_MESH_INDEX) {
		*reason = NodeInsertionFailureReason;
		return REFINEMENT_BLOCKED;
	}
	if (SpacingFunction != NULL) {
		Nodes[NodeCount - 1].spacing = SpacingFunction(
		        SpacingContext, candidateX, candidateY);
	}
	return REFINEMENT_INSERTED;
}


/** @brief Try each side of RefinementElement in deterministic order.
    @return Combined attempt details for diagnostics and progress checks.
    @note A blocked side does not mutate topology; a successful attempt inserts
          exactly one node.
 */
tRefinementAttempt
EasyMesh::tryInsertRefinementNode()
{
	tRefinementAttempt attempt;
	tMeshElement *element = getElement(RefinementElement);
	int orderedSides[3];
	int preferredSide;
	int sideCount;
	int sideAttemptIndex;

	attempt.result = REFINEMENT_BLOCKED;
	attempt.sideCount = 0;
	attempt.stopReason = NULL;
	for (sideAttemptIndex = 0; sideAttemptIndex < 3; sideAttemptIndex++) {
		attempt.sides[sideAttemptIndex] = MISSING_MESH_INDEX;
		attempt.reasons[sideAttemptIndex] = NULL;
	}
	if (element == NULL) {
		attempt.result = REFINEMENT_STOPPED;
		attempt.stopReason = "missing-refinement-element";
		return attempt;
	}

	preferredSide = getPreferredRefinementSide(RefinementElement);
	sideCount = getEasyMeshRefinementSideOrder(
	        preferredSide, element->sideI, element->sideJ, element->sideK,
	        orderedSides);
	if (sideCount != 3) {
		attempt.result = REFINEMENT_STOPPED;
		attempt.stopReason = "invalid-element-sides";
		return attempt;
	}

	for (sideAttemptIndex = 0; sideAttemptIndex < sideCount; sideAttemptIndex++) {
		attempt.sides[attempt.sideCount] = orderedSides[sideAttemptIndex];
		attempt.result = tryRefinementSide(
		        RefinementElement, orderedSides[sideAttemptIndex],
		        &attempt.reasons[attempt.sideCount]);
		attempt.sideCount++;
		if (attempt.result == REFINEMENT_INSERTED) {
			return attempt;
		}
		if (attempt.result == REFINEMENT_STOPPED) {
			attempt.stopReason = attempt.reasons[attempt.sideCount - 1];
			return attempt;
		}
	}
	return attempt;
}


/** @brief Count unmarked side connections for unconstrained active nodes.
    @note Populates tMeshNode::neighbourCount for relaxation and smoothing;
          constrained nodes and marked sides are intentionally ignored.
 */
void
EasyMesh::countNodeNeighbours()
{
	int sideIndex;

	for (sideIndex = 0; sideIndex < SideCount; sideIndex++) {
		countEasyMeshSideNeighbours(&Sides[sideIndex], Nodes, NodeCount);
	}
}


/** @brief Seed and propagate material markers across open sides.
    @note Writes tMeshElement::material for every reachable active element.
 */
void
EasyMesh::assignMaterials()
{
	int elementIndex, pointIndex;
	int neighbourI, neighbourJ, neighbourK;
	int sideI, sideJ, sideK;
	bool propagationComplete;

	for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
		if (Elements[elementIndex].marker != MISSING_MESH_INDEX) {
			Elements[elementIndex].material = MISSING_MESH_INDEX;
		}
	}

	for (pointIndex = 0; pointIndex < BoundaryPointCount; pointIndex++) {
		if (BoundaryPoints[pointIndex].segmentReferenceCount == 0) {
			Elements[findContainingElement(&BoundaryPoints[pointIndex])].material = BoundaryPoints[pointIndex].marker;
		}
	}

	for(;;) {
		propagationComplete = true;
		for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
			if (Elements[elementIndex].marker != MISSING_MESH_INDEX && Elements[elementIndex].material == MISSING_MESH_INDEX) {
				neighbourI = Elements[elementIndex].neighbourI;
				neighbourJ = Elements[elementIndex].neighbourJ;
				neighbourK = Elements[elementIndex].neighbourK;

				sideI = Elements[elementIndex].sideI;
				sideJ = Elements[elementIndex].sideJ;
				sideK = Elements[elementIndex].sideK;

				if (neighbourI != MISSING_MESH_INDEX) {
					if (Elements[neighbourI].material != MISSING_MESH_INDEX && Sides[sideI].marker == 0) {
						Elements[elementIndex].material = Elements[neighbourI].material;
						propagationComplete = false;
					}
				}

				if (neighbourJ != MISSING_MESH_INDEX) {
					if (Elements[neighbourJ].material != MISSING_MESH_INDEX && Sides[sideJ].marker == 0) {
						Elements[elementIndex].material = Elements[neighbourJ].material;
						propagationComplete = false;
					}
				}

				if (neighbourK != MISSING_MESH_INDEX) {
					if (Elements[neighbourK].material != MISSING_MESH_INDEX && Sides[sideK].marker == 0) {
						Elements[elementIndex].material = Elements[neighbourK].material;
						propagationComplete = false;
					}
				}
			}
		}
		if (propagationComplete) {
			break;
		}
	}
}


/** @brief Improve node valence by flipping eligible unconstrained sides.
    @note Mutates connectivity and neighbour counts without moving nodes.
 */
void
EasyMesh::relaxConnectivity()
{
	int sideIndex, targetImprovement, valenceImprovement;
	tMeshNode *nodeA, *nodeB, *nodeC, *nodeD;

	for (targetImprovement = 6; targetImprovement >= 3; targetImprovement--) {
		for (sideIndex = 0; sideIndex < SideCount; sideIndex++) {
			if (Sides[sideIndex].marker == 0) {
				nodeA = getNode(Sides[sideIndex].oppositeNodeA);
				nodeB = getNode(Sides[sideIndex].oppositeNodeB);
				nodeC = getNode(Sides[sideIndex].startNode);
				nodeD = getNode(Sides[sideIndex].endNode);
				if ((nodeA != NULL) && (nodeB != NULL) &&
				        (nodeC != NULL) && (nodeD != NULL) &&
				        (nodeA->marker == 0) && (nodeB->marker == 0) &&
				        (nodeC->marker == 0) && (nodeD->marker == 0)) {
					valenceImprovement = nodeC->neighbourCount + nodeD->neighbourCount - nodeA->neighbourCount - nodeB->neighbourCount;

					if (valenceImprovement == targetImprovement) {
						nodeA->neighbourCount++;
						nodeB->neighbourCount++;
						nodeC->neighbourCount--;
						nodeD->neighbourCount--;
						flipSide(sideIndex);
					}
				}
			}
		}
	}
}


/** @brief Smooth unconstrained node positions with fixed iteration count.
    @return Always 0.
    @note Moves only nodes whose marker is zero, then refreshes active element
          geometry.
 */
int
EasyMesh::smoothNodePositions()
{
	int iteration, sideIndex, nodeIndex, elementIndex;
	tMeshNode *nodeC, *nodeD;

	for (iteration = 0; iteration < SMOOTHING_ITERATION_COUNT; iteration++) {
		for (sideIndex = 0; sideIndex < SideCount; sideIndex++) {
			if (Sides[sideIndex].marker == 0) {
				nodeC = getNode(Sides[sideIndex].startNode);
				nodeD = getNode(Sides[sideIndex].endNode);
				if ((nodeC == NULL) || (nodeD == NULL)) {
					continue;
				}
				if (nodeC->marker == 0) {
					nodeC->neighbourXSum += nodeD->x;
					nodeC->neighbourYSum += nodeD->y;
				}
				if (nodeD->marker == 0) {
					nodeD->neighbourXSum += nodeC->x;
					nodeD->neighbourYSum += nodeC->y;
				}
			}
		}
		for (nodeIndex = 0; nodeIndex < NodeCount; nodeIndex++) {
			if(Nodes[nodeIndex].marker == 0) {
				Nodes[nodeIndex].x = Nodes[nodeIndex].neighbourXSum/Nodes[nodeIndex].neighbourCount;
				Nodes[nodeIndex].y = Nodes[nodeIndex].neighbourYSum/Nodes[nodeIndex].neighbourCount;
				Nodes[nodeIndex].neighbourXSum = 0.0;
				Nodes[nodeIndex].neighbourYSum = 0.0;
			}
		}
	}

	for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
		if (Elements[elementIndex].marker != MISSING_MESH_INDEX) {
			updateElementGeometry(elementIndex);
		}
	}

	return 0;
}


/** @brief Assign compact output indices to active nodes, elements, and sides.
    @note Traversal order is deterministic and does not reorder storage.
 */
void
EasyMesh::renumberMesh()
{
	int nodeIndex, sideIndex, elementIndex;
	int startOutputIndex, endOutputIndex;
	int nodeIOutputIndex, nodeJOutputIndex, nodeKOutputIndex;
	int nextElementOutputIndex = 0;
	int nextNodeOutputIndex = 0;
	int nextSideOutputIndex = 0;
	int nextElementIndex, nextSideIndex, lowestIndexSum;

	for (nodeIndex = 0; nodeIndex < NodeCount; nodeIndex++) {
		Nodes[nodeIndex].outputIndex = MISSING_MESH_INDEX;
	}
	for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
		Elements[elementIndex].outputIndex = MISSING_MESH_INDEX;
	}
	for (sideIndex = 0; sideIndex < SideCount; sideIndex++) {
		Sides[sideIndex].outputIndex = MISSING_MESH_INDEX;
	}

	/* Seed traversal with the first active element. */
	for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
		if (Elements[elementIndex].marker != MISSING_MESH_INDEX) {
			break;
		}
	}

	/* Number the first two nodes of the seed element. */
	Nodes[Elements[elementIndex].nodeI].outputIndex = nextNodeOutputIndex;
	nextNodeOutputIndex++;
	Nodes[Elements[elementIndex].nodeJ].outputIndex = nextNodeOutputIndex;
	nextNodeOutputIndex++;

	/* Number nodes by repeatedly taking the lowest adjacent output indices. */
	printf("\nRenum Nodes, ");
	fflush(stdout);
	do {
		lowestIndexSum = NodeCount + NodeCount;
		nextElementIndex = MISSING_MESH_INDEX;

		for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
			if (Elements[elementIndex].marker != MISSING_MESH_INDEX && Elements[elementIndex].outputIndex == MISSING_MESH_INDEX) {
				nodeIOutputIndex = Nodes[Elements[elementIndex].nodeI].outputIndex;
				nodeJOutputIndex = Nodes[Elements[elementIndex].nodeJ].outputIndex;
				nodeKOutputIndex = Nodes[Elements[elementIndex].nodeK].outputIndex;

				if (nodeIOutputIndex + nodeJOutputIndex + nodeKOutputIndex + 2 ==
				        abs(nodeIOutputIndex) + abs(nodeJOutputIndex) + abs(nodeKOutputIndex)) {
					if ((nodeIOutputIndex == MISSING_MESH_INDEX) && (nodeJOutputIndex + nodeKOutputIndex) < lowestIndexSum) {
						nextElementIndex = elementIndex;
						lowestIndexSum = nodeJOutputIndex + nodeKOutputIndex;
					}
					if ((nodeJOutputIndex == MISSING_MESH_INDEX) && (nodeIOutputIndex + nodeKOutputIndex) < lowestIndexSum) {
						nextElementIndex = elementIndex;
						lowestIndexSum = nodeIOutputIndex + nodeKOutputIndex;
					}
					if ((nodeKOutputIndex == MISSING_MESH_INDEX) && (nodeIOutputIndex + nodeJOutputIndex) < lowestIndexSum) {
						nextElementIndex = elementIndex;
						lowestIndexSum = nodeIOutputIndex + nodeJOutputIndex;
					}
				}
			}
		}

		if (nextElementIndex != MISSING_MESH_INDEX) {
			nodeIOutputIndex = Nodes[Elements[nextElementIndex].nodeI].outputIndex;
			nodeJOutputIndex = Nodes[Elements[nextElementIndex].nodeJ].outputIndex;
			nodeKOutputIndex = Nodes[Elements[nextElementIndex].nodeK].outputIndex;

			/* Assign the next index to the one unnumbered node. */
			if (nodeIOutputIndex == MISSING_MESH_INDEX) {
				Nodes[Elements[nextElementIndex].nodeI].outputIndex = nextNodeOutputIndex;
				nextNodeOutputIndex++;
			}
			if (nodeJOutputIndex == MISSING_MESH_INDEX) {
				Nodes[Elements[nextElementIndex].nodeJ].outputIndex = nextNodeOutputIndex;
				nextNodeOutputIndex++;
			}
			if (nodeKOutputIndex == MISSING_MESH_INDEX) {
				Nodes[Elements[nextElementIndex].nodeK].outputIndex = nextNodeOutputIndex;
				nextNodeOutputIndex++;
			}
		}
	} while (nextElementIndex != MISSING_MESH_INDEX);

	/* Number triangles by the sum of their node output indices. */
	printf("Triangles, ");
	fflush(stdout);
	do {
		lowestIndexSum = NodeCount + NodeCount + NodeCount;
		nextElementIndex = MISSING_MESH_INDEX;

		for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
			if (Elements[elementIndex].marker != MISSING_MESH_INDEX && Elements[elementIndex].outputIndex == MISSING_MESH_INDEX) {
				nodeIOutputIndex = Nodes[Elements[elementIndex].nodeI].outputIndex;
				nodeJOutputIndex = Nodes[Elements[elementIndex].nodeJ].outputIndex;
				nodeKOutputIndex = Nodes[Elements[elementIndex].nodeK].outputIndex;

				if ((nodeIOutputIndex + nodeJOutputIndex + nodeKOutputIndex) < lowestIndexSum) {
					nextElementIndex = elementIndex;
					lowestIndexSum = nodeIOutputIndex + nodeJOutputIndex + nodeKOutputIndex;
				}
			}
		}

		if (nextElementIndex != MISSING_MESH_INDEX) {
			Elements[nextElementIndex].outputIndex = nextElementOutputIndex;
			nextElementOutputIndex++;
		}
	} while (nextElementIndex != MISSING_MESH_INDEX);



	/* Number sides by the sum of their endpoint output indices. */
	printf("Sides");
	fflush(stdout);
	do {
		lowestIndexSum = NodeCount + NodeCount;
		nextSideIndex = MISSING_MESH_INDEX;

		for (sideIndex = 0; sideIndex < SideCount; sideIndex++) {
			if (Sides[sideIndex].marker != MISSING_MESH_INDEX && Sides[sideIndex].outputIndex == MISSING_MESH_INDEX) {
				startOutputIndex = Nodes[Sides[sideIndex].startNode].outputIndex;
				endOutputIndex = Nodes[Sides[sideIndex].endNode].outputIndex;

				if ((startOutputIndex + endOutputIndex) < lowestIndexSum) {
					lowestIndexSum = startOutputIndex + endOutputIndex;
					nextSideIndex = sideIndex;
				}
			}
		}

		if (nextSideIndex != MISSING_MESH_INDEX) {
			Sides[nextSideIndex].outputIndex = nextSideOutputIndex;
			nextSideOutputIndex++;
		}
	} while (nextSideIndex != MISSING_MESH_INDEX);
	printf("\n");
}



/** @brief Clear per-domain topology and initialize an empty bounding box.
    @note Counts are initialized by the subsequent supertriangle stage.
 */
void
EasyMesh::resetMeshStorage()
{
	memset(Elements, 0, sizeof(Elements));
	memset(Sides, 0, sizeof(Sides));
	memset(Nodes, 0, sizeof(Nodes));

	MeshMaxX = -INITIAL_BOUNDING_VALUE;
	MeshMinX = +INITIAL_BOUNDING_VALUE;
	MeshMaxY = -INITIAL_BOUNDING_VALUE;
	MeshMinY = +INITIAL_BOUNDING_VALUE;
}


/** @brief Calculate XY bounds covering every constrained input point.
    @note resetMeshStorage() must initialize the bound accumulators first.
 */
void
EasyMesh::calculateMeshBounds()
{
	int pointIndex;

	for (pointIndex = 0; pointIndex < BoundaryPointCount; pointIndex++) {
		MeshMaxX = max(MeshMaxX, BoundaryPoints[pointIndex].x);
		MeshMaxY = max(MeshMaxY, BoundaryPoints[pointIndex].y);
		MeshMinX = min(MeshMinX, BoundaryPoints[pointIndex].x);
		MeshMinY = min(MeshMinY, BoundaryPoints[pointIndex].y);
	}
	printf("xmin = %f   ymin = %f\n", MeshMinX, MeshMinY);
	printf("xmax = %f   ymax = %f\n", MeshMaxX, MeshMaxY);
}


/** @brief Split the ordered constraint array into contiguous chains.
    @return Number of completed chains stored in BoundaryChains.
    @note A chain ends at the final segment or when one segment's end node
          differs from the next segment's start node. The pass also assigns
          each segment's chainIndex and counts references to each endpoint for
          later open-chain classification.
 */
int
EasyMesh::buildBoundaryChains()
{
	int chainCount = 0;
	int pointIndex;
	int segmentIndex;

	free(BoundaryChains);
	BoundaryChains = NULL;
	BoundaryChains = (tBoundaryChain *)calloc(ConstraintSegmentCount + 1,
	                                          sizeof(tBoundaryChain));
	if (BoundaryChains == NULL) {
		fprintf(stderr, "Cannot allocate EasyMesh boundary chain storage\n");
		exit(1);
	}
	for (pointIndex = 0; pointIndex < BoundaryPointCount; pointIndex++) {
		BoundaryPoints[pointIndex].segmentReferenceCount = 0;
	}
	BoundaryChains[chainCount].startSegment = 0;
	for (segmentIndex = 0; segmentIndex < ConstraintSegmentCount; segmentIndex++) {
		BoundaryPoints[ConstraintSegments[segmentIndex].startNode].segmentReferenceCount++;
		BoundaryPoints[ConstraintSegments[segmentIndex].endNode].segmentReferenceCount++;

		ConstraintSegments[segmentIndex].chainIndex = chainCount;

		if ((segmentIndex == ConstraintSegmentCount - 1) ||
		        ConstraintSegments[segmentIndex + 1].startsNewChain ||
		        (ConstraintSegments[segmentIndex].endNode != ConstraintSegments[segmentIndex + 1].startNode)) {
			BoundaryChains[chainCount].endSegment = segmentIndex;
			chainCount++;
			BoundaryChains[chainCount].startSegment = segmentIndex + 1;
		}
	}
	printf("Chains = %d\n", chainCount);
	return chainCount;
}


/** @brief Prepare target spacing and subdivision counts for all constraints.
    @note Endpoint spacing is first clamped to short segment lengths. A second
          pass computes the number of mesh edges needed for every segment;
          topology is not modified here.
 */
void
EasyMesh::prepareConstraintSegments()
{
	int segmentIndex;
	double baseSubsegmentLength;
	double deltaX, deltaY;
	double endX, endY;
	double segmentLength;
	double startX, startY;

	/* Clamp endpoint spacing where a segment is shorter than its targets. */
	for (segmentIndex = 0; segmentIndex < ConstraintSegmentCount; segmentIndex++) {
		startX = BoundaryPoints[ConstraintSegments[segmentIndex].startNode].x;
		startY = BoundaryPoints[ConstraintSegments[segmentIndex].startNode].y;
		endX = BoundaryPoints[ConstraintSegments[segmentIndex].endNode].x;
		endY = BoundaryPoints[ConstraintSegments[segmentIndex].endNode].y;

		deltaX = (endX - startX);
		deltaY = (endY - startY);
		segmentLength  = sqrt(deltaX * deltaX + deltaY * deltaY);

		if ((BoundaryPoints[ConstraintSegments[segmentIndex].startNode].spacing + BoundaryPoints[ConstraintSegments[segmentIndex].endNode].spacing > segmentLength ) &&
		        (ConstraintSegments[segmentIndex].startNode != ConstraintSegments[segmentIndex].endNode)) {
			BoundaryPoints[ConstraintSegments[segmentIndex].startNode].spacing = min(BoundaryPoints[ConstraintSegments[segmentIndex].startNode].spacing,segmentLength);
			BoundaryPoints[ConstraintSegments[segmentIndex].endNode].spacing = min(BoundaryPoints[ConstraintSegments[segmentIndex].endNode].spacing,segmentLength);
		}
	}

	/* Determine how many mesh edges each constrained segment requires. */
	for (segmentIndex = 0; segmentIndex < ConstraintSegmentCount; segmentIndex++) {
		startX = BoundaryPoints[ConstraintSegments[segmentIndex].startNode].x;
		startY = BoundaryPoints[ConstraintSegments[segmentIndex].startNode].y;
		endX = BoundaryPoints[ConstraintSegments[segmentIndex].endNode].x;
		endY = BoundaryPoints[ConstraintSegments[segmentIndex].endNode].y;

		deltaX = (endX - startX);
		deltaY = (endY - startY);
		segmentLength  = sqrt(deltaX * deltaX + deltaY * deltaY);

		if (BoundaryPoints[ConstraintSegments[segmentIndex].endNode].spacing + BoundaryPoints[ConstraintSegments[segmentIndex].startNode].spacing <= segmentLength) {
			baseSubsegmentLength = 0.5 * (BoundaryPoints[ConstraintSegments[segmentIndex].startNode].spacing + BoundaryPoints[ConstraintSegments[segmentIndex].endNode].spacing);
			ConstraintSegments[segmentIndex].subdivisionCount = (int)ceil(segmentLength / baseSubsegmentLength);
		} else {
			ConstraintSegments[segmentIndex].subdivisionCount = 1;
		}
	}
}


/** @brief Classify contiguous constraints as closed, open, or internal-open.
    @param[in] chainCount Number of initialized BoundaryChains entries.
    @note Closed chains join their final endpoint to their first start point.
          An open chain whose two endpoints each occur once is internal-open.
 */
void
EasyMesh::classifyBoundaryChains(int chainCount)
{
	int chainIndex;

	for (chainIndex = 0; chainIndex < chainCount; chainIndex++) {
		if (ConstraintSegments[BoundaryChains[chainIndex].startSegment].startNode == ConstraintSegments[BoundaryChains[chainIndex].endSegment].endNode) {
			BoundaryChains[chainIndex].type = BOUNDARY_CHAIN_CLOSED;
		}

		if (ConstraintSegments[BoundaryChains[chainIndex].startSegment].startNode != ConstraintSegments[BoundaryChains[chainIndex].endSegment].endNode) {
			BoundaryChains[chainIndex].type = BOUNDARY_CHAIN_OPEN;
		}

		if ((BoundaryPoints[ConstraintSegments[BoundaryChains[chainIndex].startSegment].startNode].segmentReferenceCount == 1) &&
		        (BoundaryPoints[ConstraintSegments[BoundaryChains[chainIndex].endSegment].endNode].segmentReferenceCount == 1)) {
			BoundaryChains[chainIndex].type = BOUNDARY_CHAIN_INTERNAL_OPEN;
		}
	}
}


/** @brief Initialize the containing triangle for constrained insertion.
    @note Creates exactly three nodes, one element, and three sides around the
          previously calculated input bounds. Input elevation is taken from the
          first boundary point.
 */
void
EasyMesh::initializeSupertriangle()
{
	double meshCenterX, meshCenterY, meshSpan;

	meshCenterX = 0.5 * (MeshMaxX + MeshMinX);
	meshCenterY = 0.5 * (MeshMaxY + MeshMinY);

	meshSpan = max((MeshMaxX - MeshMinX), (MeshMaxY - MeshMinY));

	NodeCount = 3;
	Nodes[2].x = meshCenterX;
	Nodes[2].y = meshCenterY + SUPERTRIANGLE_TOP_HEIGHT_MULTIPLIER * meshSpan;
	Nodes[2].z = BoundaryPoints[0].z;

	Nodes[0].x = meshCenterX - SUPERTRIANGLE_HALF_WIDTH_MULTIPLIER * meshSpan;
	Nodes[0].y = meshCenterY - SUPERTRIANGLE_BOTTOM_HEIGHT_MULTIPLIER * meshSpan;
	Nodes[0].z = BoundaryPoints[0].z;

	Nodes[1].x = meshCenterX + SUPERTRIANGLE_HALF_WIDTH_MULTIPLIER * meshSpan;
	Nodes[1].y = meshCenterY - SUPERTRIANGLE_BOTTOM_HEIGHT_MULTIPLIER * meshSpan;
	Nodes[1].z = BoundaryPoints[0].z;

	Nodes[2].segmentReferenceCount = 2;
	Nodes[1].segmentReferenceCount = 2;
	Nodes[0].segmentReferenceCount = 2;

	Nodes[2].nextBoundaryNode = 1;
	Nodes[1].nextBoundaryNode = 0;
	Nodes[0].nextBoundaryNode = 2;

	ElementCount = 1;
	Elements[0].nodeI  = 0;
	Elements[0].nodeJ  = 1;
	Elements[0].nodeK  = 2;
	Elements[0].neighbourI = MISSING_MESH_INDEX;
	Elements[0].neighbourJ = MISSING_MESH_INDEX;
	Elements[0].neighbourK = MISSING_MESH_INDEX;
	Elements[0].sideI = 1;
	Elements[0].sideJ = 2;
	Elements[0].sideK = 0;
	Elements[0].refinementBlocked = 0;

	SideCount = 3;
	Sides[0].startNode  = 0;
	Sides[0].endNode  = 1;
	Sides[0].oppositeNodeA  = 2;
	Sides[0].oppositeNodeB  = MISSING_MESH_INDEX;

	Sides[1].startNode  = 1;
	Sides[1].endNode  = 2;
	Sides[1].oppositeNodeA  = 0;
	Sides[1].oppositeNodeB  = MISSING_MESH_INDEX;

	Sides[2].startNode  = 0;
	Sides[2].endNode  = 2;
	Sides[2].oppositeNodeA  = MISSING_MESH_INDEX;
	Sides[2].oppositeNodeB  = 1;

	Sides[0].elementA =  0;
	Sides[0].elementB = MISSING_MESH_INDEX;
	Sides[1].elementA =  0;
	Sides[1].elementB = MISSING_MESH_INDEX;
	Sides[2].elementA = MISSING_MESH_INDEX;
	Sides[2].elementB = 0;
}


/** @brief Recover and mark a constraint between two existing mesh nodes.
    @return Side index on success, or MISSING_MESH_INDEX when recovery stalls.
 */
int
EasyMesh::recoverConstraintSide(int startNodeIndex, int endNodeIndex,
	                          int marker)
{
	int maximumFlips = SideCount * 2;
	int flipCount;
	int sideIndex;

	for (flipCount = 0; flipCount <= maximumFlips; flipCount++) {
		for (sideIndex = 3; sideIndex < SideCount; sideIndex++) {
			if (((Sides[sideIndex].startNode == startNodeIndex) &&
			     (Sides[sideIndex].endNode == endNodeIndex)) ||
			        ((Sides[sideIndex].startNode == endNodeIndex) &&
			         (Sides[sideIndex].endNode == startNodeIndex))) {
				Sides[sideIndex].marker = marker;
				return sideIndex;
			}
		}
		for (sideIndex = 3; sideIndex < SideCount; sideIndex++) {
			int oppositeNodeA;
			int oppositeNodeB;
			int sideStart;
			int sideEnd;
			if ((Sides[sideIndex].marker != 0) ||
			        (Sides[sideIndex].elementA == MISSING_MESH_INDEX) ||
			        (Sides[sideIndex].elementB == MISSING_MESH_INDEX)) {
				continue;
			}
			sideStart = Sides[sideIndex].startNode;
			sideEnd = Sides[sideIndex].endNode;
			if (!meshSegmentsProperlyIntersect(
			        &Nodes[startNodeIndex], &Nodes[endNodeIndex],
			        &Nodes[sideStart], &Nodes[sideEnd])) {
				continue;
			}
			oppositeNodeA = Sides[sideIndex].oppositeNodeA;
			oppositeNodeB = Sides[sideIndex].oppositeNodeB;
			if ((oppositeNodeA == MISSING_MESH_INDEX) ||
			        (oppositeNodeB == MISSING_MESH_INDEX) ||
			        !nodesAreOnOppositeSides(
			         &Nodes[oppositeNodeA], &Nodes[oppositeNodeB],
			         &Nodes[sideStart], &Nodes[sideEnd]) ||
			        meshSegmentsProperlyIntersect(
			         &Nodes[startNodeIndex], &Nodes[endNodeIndex],
			         &Nodes[oppositeNodeA], &Nodes[oppositeNodeB])) {
				continue;
			}
			flipSide(sideIndex);
			break;
		}
		if (sideIndex == SideCount) {
			break;
		}
	}
	return MISSING_MESH_INDEX;
}


/** @brief Build constrained topology from BoundaryPoints and ConstraintSegments.
    @return Always 0 after successful construction.
    @note Resets Elements, Sides, and Nodes; computes BoundaryChains; inserts
          the containing supertriangle and every constrained node; and updates
          all topology counts.
 */
int
EasyMesh::loadConstrainedMesh()
{
	int chainCount;

	resetMeshStorage();
	printf("Segments = %d\n", ConstraintSegmentCount);
	calculateMeshBounds();
	chainCount = buildBoundaryChains();
	prepareConstraintSegments();
	classifyBoundaryChains(chainCount);

	initializeSupertriangle();
	insertConstraintChains(chainCount);
	return 0;
}


/** @brief Insert every constrained chain into the containing triangulation.
    @param[in] chainCount Number of classified boundary chains to insert.
    @note Chains and their segments are processed in input order. Segment
          subdivision preserves the original spacing progression and records
          nextBoundaryNode links used when removing out-of-domain topology.
 */
void
EasyMesh::insertConstraintChains(int chainCount)
{
	int chainIndex, itemIndex, segmentIndex, spacingStepIndex = 0;
	int previousNodeIndex;
	int previousSideMarker;
	int nextNodeIndex;
	int nextSideMarker;
	int subdivisionIndex;
	double startX, startY, startZ, endX, endY, endZ, segmentLength;
	double deltaX, deltaY, deltaZ, baseSubsegmentLength;
	double spacingDelta = 0, distanceAlongSegment;
	for (itemIndex = 0; itemIndex < BoundaryPointCount; itemIndex++) {
		BoundaryPoints[itemIndex].outputIndex = MISSING_MESH_INDEX;
	}


	for (chainIndex = 0; chainIndex < chainCount; chainIndex++) {
		for (segmentIndex = BoundaryChains[chainIndex].startSegment; segmentIndex <= BoundaryChains[chainIndex].endSegment; segmentIndex++) {
			startX = BoundaryPoints[ConstraintSegments[segmentIndex].startNode].x;
			startY = BoundaryPoints[ConstraintSegments[segmentIndex].startNode].y;
			startZ = BoundaryPoints[ConstraintSegments[segmentIndex].startNode].z;
			endX = BoundaryPoints[ConstraintSegments[segmentIndex].endNode].x;
			endY = BoundaryPoints[ConstraintSegments[segmentIndex].endNode].y;
			endZ = BoundaryPoints[ConstraintSegments[segmentIndex].endNode].z;

			/* Insert the segment's first point if an earlier segment did not. */
			if (BoundaryPoints[ConstraintSegments[segmentIndex].startNode].outputIndex == MISSING_MESH_INDEX ) {
				previousNodeIndex = MISSING_MESH_INDEX;
				previousSideMarker = MISSING_MESH_INDEX;
				if (segmentIndex != BoundaryChains[chainIndex].startSegment) {
					previousNodeIndex =
					        ConstraintSegments[segmentIndex - 1].subdivisionCount == 1
					        ? BoundaryPoints[ConstraintSegments[segmentIndex - 1].startNode].outputIndex
					        : NodeCount - 1;
					previousSideMarker = ConstraintSegments[segmentIndex - 1].marker;
				}
				nextNodeIndex = MISSING_MESH_INDEX;
				nextSideMarker = MISSING_MESH_INDEX;
				if (ConstraintSegments[segmentIndex].subdivisionCount == 1) {
					nextNodeIndex = BoundaryPoints[
					        ConstraintSegments[segmentIndex].endNode].outputIndex;
					if (nextNodeIndex != MISSING_MESH_INDEX) {
						nextSideMarker = ConstraintSegments[segmentIndex].marker;
					}
				}
				insertNode(startX, startY, startZ, KEEP_NODE_SPACING,
				           previousNodeIndex, previousSideMarker,
				           BoundaryPoints[ConstraintSegments[segmentIndex].startNode].marker,
				           nextSideMarker, nextNodeIndex);

				Nodes[NodeCount-1].nextBoundaryNode =
				        nextNodeIndex == MISSING_MESH_INDEX ?
				        NodeCount : nextNodeIndex;
				Nodes[NodeCount-1].chainIndex    = ConstraintSegments[segmentIndex].chainIndex;
				Nodes[NodeCount-1].spacing        = BoundaryPoints[ConstraintSegments[segmentIndex].startNode].spacing;
				BoundaryPoints[ConstraintSegments[segmentIndex].startNode].outputIndex = NodeCount-1;
				if ((segmentIndex != BoundaryChains[chainIndex].startSegment) &&
				        ConstraintSegments[segmentIndex - 1].recoverDisconnectedSide &&
				        (previousNodeIndex != MISSING_MESH_INDEX) &&
				        (recoverConstraintSide(previousNodeIndex, NodeCount - 1,
				         previousSideMarker) == MISSING_MESH_INDEX)) {
					fprintf(stderr,
					        "EasyMesh: cannot recover preceding constraint side\n");
					exit(1);
				}
			}
			if ((ConstraintSegments[segmentIndex].subdivisionCount == 1) &&
			        (BoundaryPoints[ConstraintSegments[segmentIndex].endNode].outputIndex !=
			         MISSING_MESH_INDEX)) {
				int startNodeIndex = BoundaryPoints[
				        ConstraintSegments[segmentIndex].startNode].outputIndex;
				int endNodeIndex = BoundaryPoints[
				        ConstraintSegments[segmentIndex].endNode].outputIndex;
				if (recoverConstraintSide(startNodeIndex, endNodeIndex,
				        ConstraintSegments[segmentIndex].marker) ==
				        MISSING_MESH_INDEX) {
					fprintf(stderr,
					        "EasyMesh: cannot recover existing constraint endpoints\n");
					exit(1);
				}
				continue;
			}

			deltaX = (endX - startX);
			deltaY = (endY - startY);
			deltaZ = (endZ - startZ);
			segmentLength  = sqrt(deltaX * deltaX + deltaY * deltaY);
			baseSubsegmentLength=segmentLength/ConstraintSegments[segmentIndex].subdivisionCount;

			if (BoundaryPoints[ConstraintSegments[segmentIndex].startNode].spacing + BoundaryPoints[ConstraintSegments[segmentIndex].endNode].spacing <= segmentLength) {
				if (BoundaryPoints[ConstraintSegments[segmentIndex].startNode].spacing > BoundaryPoints[ConstraintSegments[segmentIndex].endNode].spacing) {
					spacingStepIndex = -ConstraintSegments[segmentIndex].subdivisionCount / 2;
					spacingDelta = (BoundaryPoints[ConstraintSegments[segmentIndex].endNode].spacing-baseSubsegmentLength) / spacingStepIndex;
				} else {
					spacingStepIndex = +ConstraintSegments[segmentIndex].subdivisionCount / 2;
					spacingDelta = (baseSubsegmentLength - BoundaryPoints[ConstraintSegments[segmentIndex].startNode].spacing) / spacingStepIndex;
				}
			}

			/* Insert intermediate points using the original spacing progression. */
			distanceAlongSegment = 0;
			if (BoundaryPoints[ConstraintSegments[segmentIndex].startNode].spacing + BoundaryPoints[ConstraintSegments[segmentIndex].endNode].spacing <= segmentLength) {
				for (subdivisionIndex = 1; subdivisionIndex < abs(ConstraintSegments[segmentIndex].subdivisionCount); subdivisionIndex++) {
					distanceAlongSegment += (baseSubsegmentLength - spacingStepIndex * spacingDelta);

					if (BoundaryPoints[ConstraintSegments[segmentIndex].startNode].spacing > BoundaryPoints[ConstraintSegments[segmentIndex].endNode].spacing) {
						spacingStepIndex++;
						if (spacingStepIndex == 0 && ConstraintSegments[segmentIndex].subdivisionCount % 2 == 0) {
							spacingStepIndex++;
						}
					} else {
						spacingStepIndex--;
						if (spacingStepIndex == 0 && ConstraintSegments[segmentIndex].subdivisionCount % 2 == 0) {
							spacingStepIndex--;
						}
					}

					if ((subdivisionIndex ==
					        (abs(ConstraintSegments[segmentIndex].subdivisionCount) - 1)) &&
					        (BoundaryPoints[ConstraintSegments[segmentIndex].endNode].outputIndex !=
					         MISSING_MESH_INDEX)) {
						insertNode(startX + deltaX / segmentLength * distanceAlongSegment, startY + deltaY / segmentLength * distanceAlongSegment, startZ + deltaZ / segmentLength * distanceAlongSegment, KEEP_NODE_SPACING,
						            NodeCount - 1, ConstraintSegments[segmentIndex].marker, ConstraintSegments[segmentIndex].marker, ConstraintSegments[segmentIndex].marker, BoundaryPoints[ConstraintSegments[segmentIndex].endNode].outputIndex);
						Nodes[NodeCount - 1].nextBoundaryNode =
						        BoundaryPoints[ConstraintSegments[segmentIndex].endNode].outputIndex;
					} else {
						if(subdivisionIndex == 1) {
							insertNode(startX + deltaX / segmentLength * distanceAlongSegment, startY + deltaY / segmentLength * distanceAlongSegment, startZ + deltaZ / segmentLength * distanceAlongSegment, KEEP_NODE_SPACING,
							            BoundaryPoints[ConstraintSegments[segmentIndex].startNode].outputIndex, ConstraintSegments[segmentIndex].marker, ConstraintSegments[segmentIndex].marker, MISSING_MESH_INDEX, MISSING_MESH_INDEX);
							Nodes[NodeCount - 1].nextBoundaryNode = NodeCount;
						} else {
							insertNode(startX + deltaX / segmentLength * distanceAlongSegment, startY + deltaY / segmentLength * distanceAlongSegment, startZ + deltaZ / segmentLength * distanceAlongSegment, KEEP_NODE_SPACING,
							            NodeCount - 1, ConstraintSegments[segmentIndex].marker, ConstraintSegments[segmentIndex].marker, MISSING_MESH_INDEX, MISSING_MESH_INDEX);
							Nodes[NodeCount - 1].nextBoundaryNode = NodeCount;
						}
					}
					if (ConstraintSegments[segmentIndex].recoverDisconnectedSide) {
						previousNodeIndex = subdivisionIndex == 1
						        ? BoundaryPoints[ConstraintSegments[segmentIndex].startNode].outputIndex
						        : NodeCount - 2;
						if (recoverConstraintSide(previousNodeIndex, NodeCount - 1,
						        ConstraintSegments[segmentIndex].marker) ==
						        MISSING_MESH_INDEX) {
							fprintf(stderr,
							        "EasyMesh: cannot recover subdivided constraint side\n");
							exit(1);
						}
						if ((subdivisionIndex ==
						        (abs(ConstraintSegments[segmentIndex].subdivisionCount) - 1)) &&
						        (BoundaryPoints[ConstraintSegments[segmentIndex].endNode].outputIndex !=
						         MISSING_MESH_INDEX) &&
						        (recoverConstraintSide(NodeCount - 1,
						         BoundaryPoints[ConstraintSegments[segmentIndex].endNode].outputIndex,
						         ConstraintSegments[segmentIndex].marker) ==
						         MISSING_MESH_INDEX)) {
							fprintf(stderr,
							        "EasyMesh: cannot recover final subdivided constraint side\n");
							exit(1);
						}
					}


					Nodes[NodeCount - 1].chainIndex    = ConstraintSegments[segmentIndex].chainIndex;
					Nodes[NodeCount - 1].spacing        = 0.5 * (Nodes[NodeCount - 2].spacing + (baseSubsegmentLength-spacingStepIndex * spacingDelta));
				}
			}

			/* Open internal chains need an explicit final point. */
			if ((BoundaryPoints[ConstraintSegments[segmentIndex].endNode].outputIndex == MISSING_MESH_INDEX) && (segmentIndex==BoundaryChains[chainIndex].endSegment)) {
				insertNode(endX, endY, endZ, KEEP_NODE_SPACING,
				            ConstraintSegments[segmentIndex].subdivisionCount == 1
				            ? BoundaryPoints[ConstraintSegments[segmentIndex].startNode].outputIndex
				            : NodeCount - 1,
				            ConstraintSegments[segmentIndex].marker, BoundaryPoints[ConstraintSegments[segmentIndex].endNode].marker, MISSING_MESH_INDEX, MISSING_MESH_INDEX);
				BoundaryPoints[ConstraintSegments[segmentIndex].endNode].outputIndex =
				        NodeCount - 1;
				if (ConstraintSegments[segmentIndex].recoverDisconnectedSide) {
					previousNodeIndex = ConstraintSegments[segmentIndex].subdivisionCount == 1
					        ? BoundaryPoints[ConstraintSegments[segmentIndex].startNode].outputIndex
					        : NodeCount - 2;
					if (recoverConstraintSide(previousNodeIndex, NodeCount - 1,
					        ConstraintSegments[segmentIndex].marker) ==
					        MISSING_MESH_INDEX) {
						fprintf(stderr,
						        "EasyMesh: cannot recover terminal constraint side\n");
						exit(1);
					}
				}
				Nodes[NodeCount - 1].nextBoundaryNode = MISSING_MESH_INDEX;
				Nodes[NodeCount - 1].chainIndex    = ConstraintSegments[segmentIndex].chainIndex;
				Nodes[NodeCount - 1].spacing        = BoundaryPoints[ConstraintSegments[segmentIndex].endNode].spacing;
			}

			if (BoundaryChains[chainIndex].type == BOUNDARY_CHAIN_CLOSED && segmentIndex == BoundaryChains[chainIndex].endSegment) {
				Nodes[NodeCount - 1].nextBoundaryNode = BoundaryPoints[ConstraintSegments[BoundaryChains[chainIndex].startSegment].startNode].outputIndex;
			}

		}
	}
}

/** @brief Print a summary of refinement progress and remaining mesh quality.
    @param[in] domain Domain name used in diagnostics.
    @param[in] stopReason Reason refinement ended.
    @param[in] iterations Number of refinement loop iterations.
    @param[in] attemptedElement Last attempted element index.
    @param[in] insertions Number of successful node insertions.
    @param[in] rejectedCandidates Number of rejected side candidates.
    @param[in] blockEvents Number of elements blocked after all side attempts.
 */
void
EasyMesh::reportRefinementDiagnostics(const char *domain, const char *stopReason,
                            int iterations, int attemptedElement,
                            int insertions, int rejectedCandidates,
                            int blockEvents)
{
	int activeElements = 0;
	int blockedElements = 0;
	int unfinishedElements = 0;
	int oversizedElements = 0;
	int doneOversizedElements = 0;
	int worstQualityElement = MISSING_MESH_INDEX;
	int worstSizeElement = MISSING_MESH_INDEX;
	int elementIndex;
	double targetSpacing;
	double qualityRatio;
	double sizeRatio;
	double worstQualityRatio = 0.0;
	double worstSizeRatio = 0.0;

	if (Quiet) {
		return;
	}

	for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
		if (Elements[elementIndex].marker == MISSING_MESH_INDEX) {
			continue;
		}
		activeElements++;
		if (Elements[elementIndex].refinementBlocked) {
			blockedElements++;
		}
		if (Elements[elementIndex].refinementState != ELEMENT_DONE) {
			unfinishedElements++;
		}

		targetSpacing = (Nodes[Elements[elementIndex].nodeI].spacing + Nodes[Elements[elementIndex].nodeJ].spacing + Nodes[Elements[elementIndex].nodeK].spacing) / 3.0;
		if (targetSpacing > GEOMETRY_EPSILON) {
			sizeRatio = Elements[elementIndex].circumradius / targetSpacing;
			if (sizeRatio > worstSizeRatio) {
				worstSizeRatio = sizeRatio;
				worstSizeElement = elementIndex;
			}
			if (sizeRatio >= ACCEPTED_RADIUS_SPACING_RATIO) {
				oversizedElements++;
				if (Elements[elementIndex].refinementState == ELEMENT_DONE) {
					doneOversizedElements++;
				}
			}
		}
		if (Elements[elementIndex].inradius > GEOMETRY_EPSILON) {
			qualityRatio = Elements[elementIndex].circumradius / Elements[elementIndex].inradius;
			if (qualityRatio > worstQualityRatio) {
				worstQualityRatio = qualityRatio;
				worstQualityElement = elementIndex;
			}
		}
	}

	printf("\nEasyMesh diagnostics: domain=%s stop=%s iterations=%d "
	       "insertions=%d rejected-candidates=%d block-events=%d "
	       "nodes=%d active-elements=%d blocked=%d unfinished=%d "
	       "oversized=%d done-oversized=%d attempted=%d next-candidate=%d\n",
	       domain, stopReason, iterations, insertions, rejectedCandidates,
	       blockEvents, NodeCount, activeElements, blockedElements,
	       unfinishedElements, oversizedElements, doneOversizedElements,
	       attemptedElement, RefinementElement);
	printf("EasyMesh diagnostics: domain=%s worst-radius/inradius=%g element=%d "
	       "worst-radius/spacing=%g element=%d\n",
	       domain, worstQualityRatio, worstQualityElement,
	       worstSizeRatio, worstSizeElement);
}


/** @brief Report all rejected side candidates for one blocked element.
    @param[in] domain Domain name used in diagnostics.
    @param[in] elementIndex Blocked element index.
    @param[in] attempt Side-attempt details.
 */
static void
reportBlockedRefinement(const char *domain, int elementIndex,
                        const tRefinementAttempt *attempt, int quiet)
{
	int attemptIndex;

	if (quiet) {
		return;
	}

	fprintf(stderr,
	        "EasyMesh: domain=%s blocked element %d after %d candidates:",
	        domain, elementIndex, attempt->sideCount);
	for (attemptIndex = 0; attemptIndex < attempt->sideCount; attemptIndex++) {
		fprintf(stderr, " side %d (%s)", attempt->sides[attemptIndex],
		        attempt->reasons[attemptIndex] ? attempt->reasons[attemptIndex] : "unknown-failure");
	}
	fprintf(stderr, "\n");
}


/** @brief Report the invariant failure that stopped refinement.
    @param[in] domain Domain name used in diagnostics.
    @param[in] elementIndex Element being refined when processing stopped.
    @param[in] attempt Attempt containing the stop reason.
 */
static void
reportStoppedRefinement(const char *domain, int elementIndex,
                        const tRefinementAttempt *attempt)
{
	fprintf(stderr, "EasyMesh: domain=%s stopped refinement at element %d (%s); "
	        "writing the current mesh\n",
	        domain, elementIndex,
	        attempt->stopReason ? attempt->stopReason : "unknown-failure");
}


/** @brief Execute the constrained-mesh pipeline for one domain.
    @param[in] domain Domain name used in diagnostics.
    @note Rebuilds mesh topology within the practical node budget and finalizes
          connectivity, numbering, and materials after a recoverable stop.
 */
void
EasyMesh::triangulate(const char *domain)
{
	tRefinementAttempt attempt;
	int blockEvents = 0;
	int elementIndex;
	int attemptIndex;
	int insertions = 0;
	int nodeCountBeforeAttempt;
	int attemptedElement = MISSING_MESH_INDEX;
	int iterations = 0;
	int rejectedCandidates = 0;
	const char *stopReason = "completed";

	printf("Load Chains\n");
	loadConstrainedMesh();
	eraseOutsideDomain();
	for (elementIndex = 0; elementIndex < ElementCount; elementIndex++) {
		Elements[elementIndex].refinementBlocked = 0;
	}
	classifyElements();

	while (RefinementElement != MISSING_MESH_INDEX) {
		nodeCountBeforeAttempt = NodeCount;
		attemptedElement = RefinementElement;
		attempt = tryInsertRefinementNode();
		iterations++;
		for (attemptIndex = 0; attemptIndex < attempt.sideCount; attemptIndex++) {
			if (attempt.reasons[attemptIndex] != NULL) {
				rejectedCandidates++;
			}
		}
		if (attempt.result == REFINEMENT_STOPPED) {
			reportStoppedRefinement(domain, attemptedElement, &attempt);
			stopReason = "refinement-error";
			break;
		}
		if (attempt.result == REFINEMENT_INSERTED) {
			if (NodeCount != nodeCountBeforeAttempt + 1) {
				fprintf(stderr,
				        "EasyMesh: domain=%s insertion at element %d changed "
				        "node count from %d to %d\n",
				        domain, attemptedElement, nodeCountBeforeAttempt, NodeCount);
				stopReason = "inconsistent-node-count";
				break;
			}
			insertions++;
		} else {
			if (NodeCount != nodeCountBeforeAttempt) {
				fprintf(stderr,
				        "EasyMesh: domain=%s blocked element %d changed "
				        "node count from %d to %d\n",
				        domain, attemptedElement, nodeCountBeforeAttempt, NodeCount);
				stopReason = "inconsistent-node-count";
				break;
			}
			Elements[attemptedElement].refinementBlocked = 1;
			blockEvents++;
			reportBlockedRefinement(domain, attemptedElement, &attempt, Quiet);
		}
		classifyElements();
		if (easyMeshShouldStopRefinement(
		        RefinementElement, NodeCount, MAX_REFINEMENT_NODES)) {
			if (RefinementElement == MISSING_MESH_INDEX) {
				stopReason = "completed";
			} else if (NodeCount >= MAX_REFINEMENT_NODES) {
				stopReason = "node-limit";
			}
			break;
		}
	}
	reportRefinementDiagnostics(domain, stopReason, iterations, attemptedElement,
	                            insertions, rejectedCandidates, blockEvents);

	countNodeNeighbours();
	relaxConnectivity();
	smoothNodePositions();
	renumberMesh();
	fflush(stdout);
	assignMaterials();
}
