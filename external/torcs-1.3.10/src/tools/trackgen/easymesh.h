/***************************************************************************

    file                 : easymesh.h
    created              : Sun Feb 25 22:50:07 2001
    copyright            : Bojan NICENO & Eric Espié & Bernhard Wymann
    email                : niceno@univ.trieste.it Eric.Espie@torcs.org

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
    @brief EasyMesh constrained triangulation data and interface.

    @author <a href=mailto:torcs@free.fr>Eric Espie</a>
    @version $Id$
 */

#ifndef _EASYMESH_H_
#define _EASYMESH_H_

#include <stddef.h>

/** Physical capacity of topology arrays for input and refined nodes. */
#define EASYMESH_MAX_NODES 150000

/** @brief A point used as constrained input or as a triangulation node. */
typedef struct MeshNode
{
	double x;                       /**< X coordinate. */
	double y;                       /**< Y coordinate. */
	double z;                       /**< Elevation. */
	double spacing;                 /**< Target local edge spacing. */
	double neighbourXSum;           /**< X accumulator used by smoothing. */
	double neighbourYSum;           /**< Y accumulator used by smoothing. */
	int neighbourCount;             /**< Number of connected active nodes. */
	int marker;                     /**< Constraint/material marker or removal sentinel. */
	int nextBoundaryNode;           /**< Next node in this boundary chain. */
	int chainIndex;                 /**< Boundary chain containing this node. */
	int segmentReferenceCount;      /**< Number of input segments referencing this node. */
	int outputIndex;                /**< Compact index assigned for output. */
} tMeshNode;

/** @brief A constrained line segment between two boundary points. */
typedef struct ConstraintSegment
{
	int startNode;                  /**< Index of the first boundary point. */
	int endNode;                    /**< Index of the second boundary point. */
	int startsNewChain;             /**< Non-zero when continuity must break before this segment. */
	int recoverDisconnectedSide;    /**< Non-zero when insertion must recover a missing side. */
	int subdivisionCount;           /**< Number of mesh edges used for the segment. */
	int chainIndex;                 /**< Boundary chain containing this segment. */
	int marker;                     /**< Constraint/material marker. */
} tConstraintSegment;

/** @brief Mutable constrained input populated by track and relief sampling. */
typedef struct MeshInput
{
	tMeshNode *points;                  /**< Boundary and relief points. */
	int pointCount;                     /**< Number of populated points. */
	int pointCapacity;                  /**< Allocated point entries. */
	tConstraintSegment *segments;       /**< Constrained line segments. */
	int segmentCount;                   /**< Number of populated segments. */
	int segmentCapacity;                /**< Allocated segment entries. */
} tMeshInput;

/** @brief Triangle topology and refinement geometry. */
typedef struct MeshElement
{
	int nodeI;
	int nodeJ;
	int nodeK;
	int neighbourI;
	int neighbourJ;
	int neighbourK;
	int sideI;
	int sideJ;
	int sideK;
	int marker;
	int refinementState;
	int material;
	int refinementBlocked;
	double circumcenterX;
	double circumcenterY;
	double circumradius;
	double signedDoubleArea;
	double inradius;
	int outputIndex;
} tMeshElement;

/** @brief Edge topology shared by up to two mesh elements. */
typedef struct MeshSide
{
	int elementA;
	int elementB;
	int oppositeNodeA;
	int oppositeNodeB;
	int startNode;
	int endNode;
	int marker;
	double length;
	int outputIndex;
} tMeshSide;

/** Optional target-spacing override for each successfully refined node. */
typedef double (*tfEasyMeshSpacing)(void *context, double x, double y);

typedef struct BoundaryChain tBoundaryChain;

/** Whether insertion should interpolate spacing or retain caller input. */
typedef enum {
	INTERPOLATE_NODE_SPACING = 0,
	KEEP_NODE_SPACING = -1
} tNodeSpacingMode;

/** Result of attempting to add one refinement node. */
typedef enum {
	REFINEMENT_INSERTED,
	REFINEMENT_BLOCKED,
	REFINEMENT_STOPPED
} tRefinementResult;

/** Details collected while trying the three sides of one element. */
typedef struct RefinementAttempt {
	tRefinementResult result;
	int sideCount;
	int sides[3];
	const char *reasons[3];
	const char *stopReason;
} tRefinementAttempt;

/** @brief One reusable EasyMesh constrained triangulation context.
    @note The fixed topology arrays make this object too large for normal stack
          allocation. Construct it on the heap.
 */
class EasyMesh
{
public:
	EasyMesh();
	~EasyMesh();
	/** Generate a mesh from writable, non-empty input with valid segment
	    endpoints. The context may be reused, and input scratch fields are reset
	    as needed before each triangulation. */
	void generateMesh(tMeshInput *input, const char *domain, int quiet,
	                  tfEasyMeshSpacing spacingFunction, void *spacingContext);
	const tMeshElement *getElements() const;
	int getElementCount() const;
	const tMeshNode *getNodes() const;
	int getNodeCount() const;
	const tMeshSide *getSides() const;
	int getSideCount() const;

private:
	EasyMesh(const EasyMesh &);
	EasyMesh &operator=(const EasyMesh &);

	tMeshElement Elements[EASYMESH_MAX_NODES * 2];
	tMeshSide Sides[EASYMESH_MAX_NODES * 3];
	tMeshNode Nodes[EASYMESH_MAX_NODES];
	tMeshNode *BoundaryPoints;
	tConstraintSegment *ConstraintSegments;
	tBoundaryChain *BoundaryChains;
	int ElementCount;
	int NodeCount;
	int SideCount;
	int BoundaryPointCount;
	int ConstraintSegmentCount;
	int RefinementElement;
	const char *NodeInsertionFailureReason;
	double MeshMaxX;
	double MeshMinX;
	double MeshMaxY;
	double MeshMinY;
	int Quiet;
	tfEasyMeshSpacing SpacingFunction;
	void *SpacingContext;

	tMeshElement *getElement(int elementIndex);
	int elementIsMissingOrRemoved(int elementIndex);
	void replaceElementNeighbour(int elementIndex, int oldNeighbour,
	                             int newNeighbour);
	tMeshNode *getNode(int nodeIndex);
	tMeshSide *getSide(int sideIndex);
	int findContainingElement(const tMeshNode *candidateNode);
	void restoreDelaunayTriangulation(int nodeIndex);
	void updateElementGeometry(int elementIndex);
	void interpolateNodeSpacing(int elementIndex, int nodeIndex);
	int insertNode(double x, double y, double z, tNodeSpacingMode spacingMode,
	               int previousNodeIndex, int previousSideMarker, int nodeMarker,
	               int nextSideMarker, int nextNodeIndex);
	void flipSide(int sideIndex);
	void eraseOutsideDomain();
	void completeDiamondElements();
	void classifyElements();
	int getPreferredRefinementSide(int elementIndex);
	tRefinementResult tryRefinementSide(int elementIndex, int sideIndex,
	                                    const char **reason);
	tRefinementAttempt tryInsertRefinementNode();
	void countNodeNeighbours();
	void assignMaterials();
	void relaxConnectivity();
	int smoothNodePositions();
	void renumberMesh();
	int loadConstrainedMesh();
	void resetMeshStorage();
	void calculateMeshBounds();
	int buildBoundaryChains();
	void prepareConstraintSegments();
	void classifyBoundaryChains(int chainCount);
	void initializeSupertriangle();
	int recoverConstraintSide(int startNodeIndex, int endNodeIndex,
	                         int marker);
	void insertConstraintChains(int chainCount);
	void reportRefinementDiagnostics(const char *domain, const char *stopReason,
	                                 int iterations, int attemptedElement,
	                                 int insertions, int rejectedCandidates,
	                                 int blockEvents);
	void triangulate(const char *domain);
};

#endif /* _EASYMESH_H_ */ 
