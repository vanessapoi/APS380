/***************************************************************************

    file                 : terrain.cpp
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

/** @file
    @brief TORCS terrain generation integration.
 */

#include <algorithm>
#include <new>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <vector>

#include <tgf.h>
#include <track.h>
#include <portability.h>

#include "ac3d.h"
#include "easymesh.h"
#include "easymesh_checks.h"
#include "elevation.h"
#include "relief.h"
#include "terrain.h"
#include "terraindomain.h"
#include "terrainoutput.h"
#include "trackboundary.h"
#include "trackgen.h"

#ifndef max
#define max(a,b)  (((a) > (b)) ? (a) : (b))
#endif
#ifndef min
#define min(a,b)  (((a) < (b)) ? (a) : (b))
#endif

/** GenerateTerrain selector that loads the configured elevation map. */
#define LOAD_CONFIGURED_ELEVATION -1

/** Domain point snapping distance used when closing crossing track ribbons. */
static const double CROSSING_TERRAIN_POINT_EPSILON = 1e-3;

/** Maximum elevation mismatch at a shared relief intersection. */
static const double CROSSING_RELIEF_ELEVATION_EPSILON = 1e-6;

/** Absolute XY distance used when reusing crossing relief points. */
static const double CROSSING_RELIEF_POINT_EPSILON = 1e-8;


/** @brief One indexed line from a loaded relief file. */
typedef struct TerrainReliefSegment {
	int startPoint;
	int endPoint;
} tTerrainReliefSegment;


/** @brief Reusable relief points and lines for one legacy side class. */
typedef struct TerrainReliefData {
	std::vector<TerrainDomainPoint> points;
	std::vector<tTerrainReliefSegment> segments;
} tTerrainReliefData;


/** @brief One existing input point ordered along a relief segment. */
typedef struct TerrainReliefConstraintPoint {
	double parameter;
	int pointIndex;
} tTerrainReliefConstraintPoint;


/** @brief State owned by one GenerateTerrain call. */
class TerrainGenerationContext
{
public:
	TerrainGenerationContext();
	~TerrainGenerationContext();
	void generateTerrain(tTrack *track, void *trackHandle, char *outfile,
	                     FILE *allFd, int noElevation,
	                     const TrackCrossingModel *crossingModel);

private:
	tdble TerrainMargin;
	tdble ExteriorHeight;
	tdble TerrainGridStep;
	tdble TerrainTransition;
	tdble TrackSamplingStep;
	const char *TerrainTextureName;
	tdble TerrainTextureSize;
	tdble TerrainTextureRandomness;
	float TerrainGroupSize;
	float TerrainGroupXOffset;
	float TerrainGroupYOffset;
	int TerrainGroupColumnCount;
	int TerrainGroupCount;

	EasyMesh Mesh;
	tMeshInput Input;
	TerrainOutput Output;

	void generateTerrainDomain(tTrack *track, int side,
	                           bool reverseOrder, bool exteriorDomain);
	void appendBoundaryPoint(double x, double y, double z, double spacing,
	                         int marker);
	void reserveBoundaryPoints(int minimumCapacity);
	void appendExteriorBorder(tTrack *track, bool reverseOrder);
	void reverseBoundaryPoints(int reliefVertexCount);
	void buildDomainConstraints(bool exteriorDomain, int sampledPointCount);
	void appendReliefConstraints(int interior);
	void releaseDomainInput();
	void generateCrossingTerrain(tTrack *track,
	                            const TrackCrossingModel *crossingModel);
	void generateCrossingTerrainDomain(
	        const TerrainDomain &domain, int domainIndex,
	        const std::vector<tMeshNode> trackBoundaries[2],
	        const tTerrainReliefData &relief);
	void sampleCrossingBoundary(tTrack *track, int side,
	                          std::vector<tMeshNode> *points,
	                          tMeshNode *closurePoint,
	                          std::vector<TrackBoundaryTransition> *transitions);
};


/** @brief Track-boundary data needed by the generic EasyMesh spacing callback. */
typedef struct TerrainSpacingContext {
	const tMeshNode *points;
	int firstTrackBoundaryPoint;
	int trackBoundaryPointCount;
	double terrainGridStep;
	double nearTrackSpacingFloor;
	double terrainTransition;
} tTerrainSpacingContext;


/** @brief Both sampled track sides used by crossing-domain refinement. */
typedef struct CrossingTerrainSpacingContext {
	const std::vector<tMeshNode> *boundaries;
	double terrainGridStep;
	double nearTrackSpacingFloor;
	double terrainTransition;
} tCrossingTerrainSpacingContext;


static double
terrainTargetSpacing(void *context, double x, double y)
{
	tTerrainSpacingContext *spacing = (tTerrainSpacingContext *)context;

	return getTrackBoundaryTargetSpacing(
	        spacing->points, spacing->firstTrackBoundaryPoint,
	        spacing->trackBoundaryPointCount, x, y,
	        spacing->terrainGridStep, spacing->nearTrackSpacingFloor,
	        spacing->terrainTransition);
}


static double
crossingTerrainTargetSpacing(void *context, double x, double y)
{
	tCrossingTerrainSpacingContext *spacing =
	        (tCrossingTerrainSpacingContext *)context;
	double target = spacing->terrainGridStep;
	int side;
	for (side = 0; side < 2; side++) {
		const std::vector<tMeshNode> &boundary = spacing->boundaries[side];
		if (!boundary.empty()) {
			target = min(target, getTrackBoundaryTargetSpacing(
			        &boundary[0], 0, (int)boundary.size(), x, y,
			        spacing->terrainGridStep,
			        spacing->nearTrackSpacingFloor,
			        spacing->terrainTransition));
		}
	}
	return target;
}


TerrainGenerationContext::TerrainGenerationContext()
:
	TerrainMargin(0.0),
	ExteriorHeight(0.0),
	TerrainGridStep(0.0),
	TerrainTransition(0.0),
	TrackSamplingStep(0.0),
	TerrainTextureName(NULL),
	TerrainTextureSize(0.0),
	TerrainTextureRandomness(0.0),
	TerrainGroupSize(0.0f),
	TerrainGroupXOffset(0.0f),
	TerrainGroupYOffset(0.0f),
	TerrainGroupColumnCount(0),
	TerrainGroupCount(0)
{
	memset(&Input, 0, sizeof(Input));
}


TerrainGenerationContext::~TerrainGenerationContext()
{
	releaseDomainInput();
}


/** @brief Release constrained input owned by the current terrain domain. */
void
TerrainGenerationContext::releaseDomainInput()
{
	free(Input.points);
	Input.points = NULL;
	free(Input.segments);
	Input.segments = NULL;
	Input.pointCount = 0;
	Input.pointCapacity = 0;
	Input.segmentCount = 0;
	Input.segmentCapacity = 0;
}


/** @brief Append loaded relief geometry to the constrained input. */
void
TerrainGenerationContext::appendReliefConstraints(int interior)
{
	GenRelief(interior, &Input);
}


/** @brief Determine track winding from the signed sum of segment arcs. */
static int
getTrackOrientation(tTrack *track)
{
	tTrackSeg *segment;
	int segmentIndex;
	tdble totalAngle = 0;

	for (segmentIndex = 0, segment = track->seg->next;
	        segmentIndex < track->nseg;
	        segmentIndex++, segment = segment->next) {
		switch (segment->type) {
			case TR_STR:
				break;
			case TR_LFT:
				totalAngle += segment->arc;
				break;
			case TR_RGT:
				totalAngle -= segment->arc;
				break;
		}
	}
	if (totalAngle > 0) {
		return ANTICLOCKWISE;
	}
	return CLOCKWISE;
}


/** @brief Ensure constrained-point storage can hold a requested entry count. */
void
TerrainGenerationContext::reserveBoundaryPoints(int minimumCapacity)
{
	int oldCapacity;
	tMeshNode *resizedPoints;

	if (minimumCapacity <= Input.pointCapacity) {
		return;
	}
	oldCapacity = Input.pointCapacity;
	Input.pointCapacity = max(minimumCapacity,
	                          max(1, Input.pointCapacity * 2));
	resizedPoints = (tMeshNode *)realloc(
	        Input.points, Input.pointCapacity * sizeof(tMeshNode));
	if (resizedPoints == NULL) {
		GfFatal("Cannot grow terrain boundary point storage\n");
		exit(1);
	}
	Input.points = resizedPoints;
	memset(&Input.points[oldCapacity], 0,
	       (Input.pointCapacity - oldCapacity) * sizeof(tMeshNode));
}


/** @brief Append one sampled point to the constrained input. */
void
TerrainGenerationContext::appendBoundaryPoint(double x, double y, double z,
                                               double spacing, int marker)
{
	reserveBoundaryPoints(Input.pointCount + 1);
	Input.points[Input.pointCount].x = x;
	Input.points[Input.pointCount].y = y;
	Input.points[Input.pointCount].z = z;
	Input.points[Input.pointCount].spacing = spacing;
	Input.points[Input.pointCount].marker = marker;
	Input.pointCount++;
}


/** @brief Append the four corners of the artificial exterior rectangle. */
void
TerrainGenerationContext::appendExteriorBorder(tTrack *track, bool reverseOrder)
{
	if (reverseOrder) {
		appendBoundaryPoint(-TerrainMargin, track->max.y + TerrainMargin,
		                    ExteriorHeight, TerrainGridStep, RELIEF_BOUNDARY_MARK);
		appendBoundaryPoint(track->max.x + TerrainMargin,
		                    track->max.y + TerrainMargin, ExteriorHeight,
		                    TerrainGridStep, RELIEF_BOUNDARY_MARK);
		appendBoundaryPoint(track->max.x + TerrainMargin, -TerrainMargin,
		                    ExteriorHeight, TerrainGridStep, RELIEF_BOUNDARY_MARK);
		appendBoundaryPoint(-TerrainMargin, -TerrainMargin, ExteriorHeight,
		                    TerrainGridStep, RELIEF_BOUNDARY_MARK);
	} else {
		appendBoundaryPoint(-TerrainMargin, -TerrainMargin, ExteriorHeight,
		                    TerrainGridStep, RELIEF_BOUNDARY_MARK);
		appendBoundaryPoint(track->max.x + TerrainMargin, -TerrainMargin,
		                    ExteriorHeight, TerrainGridStep, RELIEF_BOUNDARY_MARK);
		appendBoundaryPoint(track->max.x + TerrainMargin,
		                    track->max.y + TerrainMargin, ExteriorHeight,
		                    TerrainGridStep, RELIEF_BOUNDARY_MARK);
		appendBoundaryPoint(-TerrainMargin, track->max.y + TerrainMargin,
		                    ExteriorHeight, TerrainGridStep, RELIEF_BOUNDARY_MARK);
	}
}


/** @brief Convert one sampled EasyMesh input point to domain geometry. */
static TerrainDomainPoint
toTerrainDomainPoint(const tMeshNode &node)
{
	TerrainDomainPoint point;
	point.x = node.x;
	point.y = node.y;
	point.z = node.z;
	point.spacing = node.spacing;
	point.marker = node.marker;
	return point;
}


/** @brief Copy one class of loaded relief geometry into vector storage. */
static void
loadTerrainRelief(int interior, tTerrainReliefData *relief)
{
	tMeshInput reliefInput;
	int vertexCount;
	int segmentCount;
	int pointIndex;
	int segmentIndex;
	memset(&reliefInput, 0, sizeof(reliefInput));
	relief->points.clear();
	relief->segments.clear();
	CountRelief(interior, &vertexCount, &segmentCount);
	if ((vertexCount == 0) && (segmentCount == 0)) {
		return;
	}
	reliefInput.pointCapacity = max(1, vertexCount);
	reliefInput.segmentCapacity = max(1, segmentCount);
	reliefInput.points = (tMeshNode *)calloc(
	        reliefInput.pointCapacity, sizeof(tMeshNode));
	reliefInput.segments = (tConstraintSegment *)calloc(
	        reliefInput.segmentCapacity, sizeof(tConstraintSegment));
	if ((reliefInput.points == NULL) || (reliefInput.segments == NULL)) {
		free(reliefInput.points);
		free(reliefInput.segments);
		GfFatal("Cannot allocate crossing terrain relief storage\n");
		exit(1);
	}
	GenRelief(interior, &reliefInput);
	relief->points.reserve(reliefInput.pointCount);
	for (pointIndex = 0; pointIndex < reliefInput.pointCount; pointIndex++) {
		relief->points.push_back(toTerrainDomainPoint(
		        reliefInput.points[pointIndex]));
	}
	relief->segments.reserve(reliefInput.segmentCount);
	for (segmentIndex = 0; segmentIndex < reliefInput.segmentCount;
	        segmentIndex++) {
		const tConstraintSegment &source = reliefInput.segments[segmentIndex];
		if ((source.startNode < 0) ||
		        (source.startNode >= reliefInput.pointCount) ||
		        (source.endNode < 0) ||
		        (source.endNode >= reliefInput.pointCount) ||
		        (source.startNode == source.endNode)) {
			continue;
		}
		tTerrainReliefSegment segment;
		segment.startPoint = source.startNode;
		segment.endPoint = source.endNode;
		relief->segments.push_back(segment);
	}
	free(reliefInput.points);
	free(reliefInput.segments);
}


/** @brief Return the signed area of one candidate relief ring. */
static double
terrainReliefRingArea(const TerrainDomainRing &ring)
{
	double area = 0.0;
	size_t pointIndex;
	for (pointIndex = 0; pointIndex < ring.points.size(); pointIndex++) {
		const TerrainDomainPoint &first = ring.points[pointIndex];
		const TerrainDomainPoint &second =
		        ring.points[(pointIndex + 1) % ring.points.size()];
		area += first.x * second.y - second.x * first.y;
	}
	return area / 2.0;
}


/** @brief Remove attached relief spurs and trace one unambiguous cycle. */
static bool
tracePeeledReliefCycle(
		const tTerrainReliefData &relief,
		const std::vector<std::vector<int> > &adjacency,
		const std::vector<int> &componentSegments,
		TerrainDomainRing *ring)
{
	std::vector<bool> active(relief.segments.size(), false);
	std::vector<bool> traced(relief.segments.size(), false);
	std::vector<int> degree(relief.points.size(), 0);
	std::vector<int> pendingNodes;
	int activeCount = 0;
	int firstSegment = -1;
	size_t index;
	for (index = 0; index < componentSegments.size(); index++) {
		int segmentIndex = componentSegments[index];
		const tTerrainReliefSegment &segment = relief.segments[segmentIndex];
		active[segmentIndex] = true;
		degree[segment.startPoint]++;
		degree[segment.endPoint]++;
	}
	for (index = 0; index < degree.size(); index++) {
		if (degree[index] == 1) {
			pendingNodes.push_back((int)index);
		}
	}
	for (index = 0; index < pendingNodes.size(); index++) {
		int node = pendingNodes[index];
		size_t adjacentIndex;
		if (degree[node] > 1) {
			continue;
		}
		for (adjacentIndex = 0; adjacentIndex < adjacency[node].size();
		        adjacentIndex++) {
			int segmentIndex = adjacency[node][adjacentIndex];
			int otherNode;
			if (!active[segmentIndex]) {
				continue;
			}
			const tTerrainReliefSegment &segment = relief.segments[segmentIndex];
			active[segmentIndex] = false;
			otherNode = segment.startPoint == node ?
			        segment.endPoint : segment.startPoint;
			degree[node]--;
			degree[otherNode]--;
			if (degree[otherNode] == 1) {
				pendingNodes.push_back(otherNode);
			}
		}
	}
	for (index = 0; index < componentSegments.size(); index++) {
		int segmentIndex = componentSegments[index];
		if (active[segmentIndex]) {
			activeCount++;
			firstSegment = segmentIndex;
		}
	}
	if (activeCount < 3) {
		return false;
	}
	for (index = 0; index < degree.size(); index++) {
		if ((degree[index] != 0) && (degree[index] != 2)) {
			return false;
		}
	}
	int firstNode = relief.segments[firstSegment].startPoint;
	int currentNode = firstNode;
	int currentSegment = firstSegment;
	int tracedCount = 0;
	while (tracedCount <= activeCount) {
		const tTerrainReliefSegment &segment = relief.segments[currentSegment];
		int nextNode;
		int nextSegment = -1;
		size_t adjacentIndex;
		if (traced[currentSegment]) {
			return false;
		}
		ring->points.push_back(relief.points[currentNode]);
		traced[currentSegment] = true;
		tracedCount++;
		nextNode = segment.startPoint == currentNode ?
		        segment.endPoint : segment.startPoint;
		currentNode = nextNode;
		if (currentNode == firstNode) {
			break;
		}
		for (adjacentIndex = 0; adjacentIndex < adjacency[currentNode].size();
		        adjacentIndex++) {
			int candidateSegment = adjacency[currentNode][adjacentIndex];
			if (active[candidateSegment] && !traced[candidateSegment]) {
				nextSegment = candidateSegment;
				break;
			}
		}
		if (nextSegment < 0) {
			return false;
		}
		currentSegment = nextSegment;
	}
	return (currentNode == firstNode) && (tracedCount == activeCount) &&
	        (ring->points.size() >= 3);
}


/** @brief Find the largest exterior relief chain for borderless mode. */
static bool
findTerrainReliefBorder(const tTerrainReliefData &relief,
	                  const std::vector<TerrainDomainTriangle> &occupied,
	                  TerrainDomainRing *border)
{
	std::vector<std::vector<int> > adjacency(relief.points.size());
	std::vector<bool> processed(relief.segments.size(), false);
	double largestArea = 0.0;
	size_t segmentIndex;
	for (segmentIndex = 0; segmentIndex < relief.segments.size();
	        segmentIndex++) {
		const tTerrainReliefSegment &segment = relief.segments[segmentIndex];
		adjacency[segment.startPoint].push_back((int)segmentIndex);
		adjacency[segment.endPoint].push_back((int)segmentIndex);
	}
	for (segmentIndex = 0; segmentIndex < relief.segments.size();
	        segmentIndex++) {
		std::vector<int> componentSegments;
		std::vector<int> pendingSegments;
		std::vector<bool> componentNodes(relief.points.size(), false);
		std::vector<bool> traced(relief.segments.size(), false);
		TerrainDomainRing candidate;
		int firstNode = -1;
		int currentNode;
		int degreeOneCount = 0;
		int tracedCount = 0;
		bool candidateReady = false;
		size_t pendingIndex;
		size_t pointIndex;
		if (processed[segmentIndex]) {
			continue;
		}
		pendingSegments.push_back((int)segmentIndex);
		processed[segmentIndex] = true;
		for (pendingIndex = 0; pendingIndex < pendingSegments.size();
		        pendingIndex++) {
			int currentSegment = pendingSegments[pendingIndex];
			const tTerrainReliefSegment &segment =
			        relief.segments[currentSegment];
			const int nodes[2] = {segment.startPoint, segment.endPoint};
			int endpoint;
			componentSegments.push_back(currentSegment);
			for (endpoint = 0; endpoint < 2; endpoint++) {
				componentNodes[nodes[endpoint]] = true;
				for (pointIndex = 0;
				        pointIndex < adjacency[nodes[endpoint]].size();
				        pointIndex++) {
					int adjacentSegment =
					        adjacency[nodes[endpoint]][pointIndex];
					if (!processed[adjacentSegment]) {
						processed[adjacentSegment] = true;
						pendingSegments.push_back(adjacentSegment);
					}
				}
			}
		}
		for (pointIndex = 0; pointIndex < componentNodes.size(); pointIndex++) {
			if (!componentNodes[pointIndex]) {
				continue;
			}
			if (adjacency[pointIndex].size() == 1) {
				degreeOneCount++;
				firstNode = (int)pointIndex;
			} else if (adjacency[pointIndex].size() != 2) {
				degreeOneCount = -1;
				break;
			} else if (firstNode < 0) {
				firstNode = (int)pointIndex;
			}
		}
		if ((degreeOneCount == 0) || (degreeOneCount == 2)) {
			currentNode = firstNode;
			while (candidate.points.size() <= componentSegments.size()) {
				int nextSegment = -1;
				int nextNode;
				candidate.points.push_back(relief.points[currentNode]);
				for (pointIndex = 0; pointIndex < adjacency[currentNode].size();
				        pointIndex++) {
					int candidateSegment = adjacency[currentNode][pointIndex];
					if (!traced[candidateSegment]) {
						nextSegment = candidateSegment;
						break;
					}
				}
				if (nextSegment < 0) {
					break;
				}
				traced[nextSegment] = true;
				tracedCount++;
				const tTerrainReliefSegment &segment =
				        relief.segments[nextSegment];
				nextNode = segment.startPoint == currentNode ?
				        segment.endPoint : segment.startPoint;
				currentNode = nextNode;
				if (currentNode == firstNode) {
					break;
				}
			}
			candidateReady =
			        (tracedCount == (int)componentSegments.size()) &&
			        (candidate.points.size() >= 3) &&
			        ((degreeOneCount == 2) || (currentNode == firstNode));
		} else {
			candidateReady = tracePeeledReliefCycle(
			        relief, adjacency, componentSegments, &candidate);
		}
		if (candidateReady) {
			double area = fabs(terrainReliefRingArea(candidate));
			TerrainDomain candidateDomain;
			bool containsOccupied = true;
			size_t triangleIndex;
			candidateDomain.outer = candidate;
			candidateDomain.exterior = true;
			for (triangleIndex = 0; triangleIndex < occupied.size();
			        triangleIndex++) {
				int trianglePoint;
				for (trianglePoint = 0; trianglePoint < 3; trianglePoint++) {
					const TerrainDomainPoint &point =
					        occupied[triangleIndex].points[trianglePoint];
					if (!TerrainDomainCoversPoint(
					        candidateDomain, point.x, point.y)) {
						containsOccupied = false;
						break;
					}
				}
				if (!containsOccupied) {
					break;
				}
			}
			if (containsOccupied && (area > largestArea)) {
				largestArea = area;
				*border = candidate;
			}
		}
	}
	return largestArea > 1e-6;
}


/** @brief Append one occupied triangle using three domain points. */
static void
appendOccupiedTriangle(const TerrainDomainPoint &first,
	                  const TerrainDomainPoint &second,
	                  const TerrainDomainPoint &third,
	                  std::vector<TerrainDomainTriangle> *triangles)
{
	TerrainDomainTriangle triangle;
	triangle.points[0] = first;
	triangle.points[1] = second;
	triangle.points[2] = third;
	triangles->push_back(triangle);
}


/** @brief Append one exact edge of projected occupied geometry. */
static void
appendOccupiedBoundary(const TerrainDomainPoint &first,
	                  const TerrainDomainPoint &second,
	                  std::vector<TerrainDomainSegment> *boundaries)
{
	TerrainDomainSegment boundary;
	boundary.points[0] = first;
	boundary.points[1] = second;
	boundaries->push_back(boundary);
}


/** @brief Append projected crossing occupancy and candidate edges. */
static int
appendCrossingObjectTriangles(const TrackCrossingObject &object,
	                         double spacing,
	                         TerrainDomainBoundaryGroup *group)
{
	size_t triangleIndex;
	for (triangleIndex = 0; triangleIndex < object.triangles.size();
	        triangleIndex++) {
		TerrainDomainPoint points[3];
		int reference;
		for (reference = 0; reference < 3; reference++) {
			int vertexIndex = object.triangles[triangleIndex].vertex[reference];
			if ((vertexIndex < 0) ||
			        (vertexIndex >= (int)object.vertices.size())) {
				return -1;
			}
			const TrackCrossingPoint &source = object.vertices[vertexIndex];
			points[reference].x = source.x;
			points[reference].y = source.y;
			points[reference].z = source.z;
			points[reference].spacing = spacing;
			points[reference].marker = CROSSING_TERRAIN_BOUNDARY_MARK;
		}
		appendOccupiedTriangle(points[0], points[1], points[2],
		                       &group->triangles);
		for (reference = 0; reference < 3; reference++) {
			appendOccupiedBoundary(points[reference],
			        points[(reference + 1) % 3], &group->boundaries);
		}
	}
	return 0;
}


/** @brief Sample one normal terrain boundary into reusable vector storage. */
void
TerrainGenerationContext::sampleCrossingBoundary(
		tTrack *track, int side, std::vector<tMeshNode> *points,
		tMeshNode *closurePoint,
		std::vector<TrackBoundaryTransition> *transitions)
{
	tMeshInput sampledInput;
	tdble nearTrackSpacing = min(TrackSamplingStep, TerrainGridStep);
	memset(&sampledInput, 0, sizeof(sampledInput));
	sampledInput.pointCapacity = max(1, (int)track->length);
	sampledInput.points = (tMeshNode *)calloc(sampledInput.pointCapacity,
	                                        sizeof(tMeshNode));
	if (sampledInput.points == NULL) {
		GfFatal("Cannot allocate crossing terrain boundary storage\n");
		exit(1);
	}
	if (sampleTrackBoundary(track, side, TrackSamplingStep, nearTrackSpacing,
	                        true, &sampledInput, closurePoint,
	                        transitions) != 0) {
		free(sampledInput.points);
		GfFatal("Cannot grow crossing terrain boundary storage\n");
		exit(1);
	}
	points->assign(sampledInput.points,
	               sampledInput.points + sampledInput.pointCount);
	free(sampledInput.points);
}


/** @brief Append one closed domain ring and its ordered constraints. */
static void
appendTerrainDomainRing(const TerrainDomainRing &ring,
	                   tMeshInput *input)
{
	int firstPoint = input->pointCount;
	size_t pointIndex;
	for (pointIndex = 0; pointIndex < ring.points.size(); pointIndex++) {
		const TerrainDomainPoint &source = ring.points[pointIndex];
		input->points[input->pointCount].x = source.x;
		input->points[input->pointCount].y = source.y;
		input->points[input->pointCount].z = source.z;
		input->points[input->pointCount].spacing = source.spacing;
		input->points[input->pointCount].marker = source.marker;
		input->pointCount++;
	}
	for (pointIndex = 0; pointIndex < ring.points.size(); pointIndex++) {
		int startPoint = firstPoint + (int)pointIndex;
		int endPoint = firstPoint +
		        (int)((pointIndex + 1) % ring.points.size());
		input->segments[input->segmentCount].startNode = startPoint;
		input->segments[input->segmentCount].endNode = endPoint;
		input->segments[input->segmentCount].startsNewChain =
		        pointIndex == 0 ? 1 : 0;
		input->segments[input->segmentCount].marker =
		        input->points[startPoint].marker;
		input->segmentCount++;
	}
}


/** @brief Grow crossing-domain point storage while preserving existing data. */
static void
reserveTerrainDomainPoints(tMeshInput *input, int minimumCapacity)
{
	int oldCapacity;
	int newCapacity;
	tMeshNode *resizedPoints;
	if (minimumCapacity <= input->pointCapacity) {
		return;
	}
	oldCapacity = input->pointCapacity;
	newCapacity = max(minimumCapacity, max(1, oldCapacity * 2));
	resizedPoints = (tMeshNode *)realloc(
	        input->points, newCapacity * sizeof(tMeshNode));
	if (resizedPoints == NULL) {
		GfFatal("Cannot grow crossing terrain point storage\n");
		exit(1);
	}
	input->points = resizedPoints;
	memset(&input->points[oldCapacity], 0,
	       (newCapacity - oldCapacity) * sizeof(tMeshNode));
	input->pointCapacity = newCapacity;
}


/** @brief Grow crossing-domain constraint storage while preserving order. */
static void
reserveTerrainDomainSegments(tMeshInput *input, int minimumCapacity)
{
	int oldCapacity;
	int newCapacity;
	tConstraintSegment *resizedSegments;
	if (minimumCapacity <= input->segmentCapacity) {
		return;
	}
	oldCapacity = input->segmentCapacity;
	newCapacity = max(minimumCapacity, max(1, oldCapacity * 2));
	resizedSegments = (tConstraintSegment *)realloc(
	        input->segments, newCapacity * sizeof(tConstraintSegment));
	if (resizedSegments == NULL) {
		GfFatal("Cannot grow crossing terrain constraint storage\n");
		exit(1);
	}
	input->segments = resizedSegments;
	memset(&input->segments[oldCapacity], 0,
	       (newCapacity - oldCapacity) * sizeof(tConstraintSegment));
	input->segmentCapacity = newCapacity;
}


/** @brief Reuse a domain point or insert one without constraint T-junctions. */
static int
findOrInsertTerrainDomainPoint(const TerrainDomainPoint &point,
	                         tMeshInput *input)
{
	TerrainDomainPoint candidate = point;
	int pointIndex;
	int segmentIndex;
	for (pointIndex = 0; pointIndex < input->pointCount; pointIndex++) {
		double deltaX = input->points[pointIndex].x - candidate.x;
		double deltaY = input->points[pointIndex].y - candidate.y;
		if (deltaX * deltaX + deltaY * deltaY <=
		        CROSSING_RELIEF_POINT_EPSILON *
		        CROSSING_RELIEF_POINT_EPSILON) {
			return pointIndex;
		}
	}
	reserveTerrainDomainPoints(input, input->pointCount + 1);
	reserveTerrainDomainSegments(input, input->segmentCount + 1);
	pointIndex = input->pointCount++;
	for (segmentIndex = 0; segmentIndex < input->segmentCount; segmentIndex++) {
		tConstraintSegment &segment = input->segments[segmentIndex];
		const tMeshNode &start = input->points[segment.startNode];
		const tMeshNode &end = input->points[segment.endNode];
		double edgeX = end.x - start.x;
		double edgeY = end.y - start.y;
		double lengthSquared = edgeX * edgeX + edgeY * edgeY;
		double parameter;
		double nearestX;
		double nearestY;
		int oldEndPoint;
		int segmentMarker;
		int recoverDisconnectedSide;
		if (lengthSquared <= CROSSING_RELIEF_POINT_EPSILON *
		        CROSSING_RELIEF_POINT_EPSILON) {
			continue;
		}
		parameter = ((candidate.x - start.x) * edgeX +
		             (candidate.y - start.y) * edgeY) / lengthSquared;
		if ((parameter <= 0.0) || (parameter >= 1.0)) {
			continue;
		}
		nearestX = start.x + parameter * edgeX;
		nearestY = start.y + parameter * edgeY;
		if ((candidate.x - nearestX) * (candidate.x - nearestX) +
		        (candidate.y - nearestY) * (candidate.y - nearestY) >
		        CROSSING_RELIEF_POINT_EPSILON *
		        CROSSING_RELIEF_POINT_EPSILON) {
			continue;
		}
		input->points[pointIndex].x = nearestX;
		input->points[pointIndex].y = nearestY;
		input->points[pointIndex].z = start.z + parameter * (end.z - start.z);
		input->points[pointIndex].spacing = min(start.spacing, end.spacing);
		input->points[pointIndex].marker = segment.marker;
		oldEndPoint = segment.endNode;
		segmentMarker = segment.marker;
		recoverDisconnectedSide = segment.recoverDisconnectedSide;
		memmove(&input->segments[segmentIndex + 2],
		        &input->segments[segmentIndex + 1],
		        (input->segmentCount - segmentIndex - 1) *
		        sizeof(tConstraintSegment));
		input->segments[segmentIndex].endNode = pointIndex;
		input->segments[segmentIndex + 1].startNode = pointIndex;
		input->segments[segmentIndex + 1].endNode = oldEndPoint;
		input->segments[segmentIndex + 1].startsNewChain = 0;
		input->segments[segmentIndex + 1].recoverDisconnectedSide =
		        recoverDisconnectedSide;
		input->segments[segmentIndex + 1].marker = segmentMarker;
		input->segmentCount++;
		return pointIndex;
	}
	input->points[pointIndex].x = candidate.x;
	input->points[pointIndex].y = candidate.y;
	input->points[pointIndex].z = candidate.z;
	input->points[pointIndex].spacing = candidate.spacing;
	input->points[pointIndex].marker = RELIEF_BOUNDARY_MARK;
	return pointIndex;
}


/** @brief Insert a relief point that cannot already belong to another chain. */
static int
insertFreshTerrainReliefPoint(const TerrainDomainSegment &segment,
	                        tMeshInput *input)
{
	int attempt;
	for (attempt = 1; attempt <= 64; attempt++) {
		double parameter = fmod(attempt * 0.6180339887498948482, 1.0);
		TerrainDomainPoint point;
		int oldPointCount = input->pointCount;
		int pointIndex;
		point.x = segment.points[0].x + parameter *
		        (segment.points[1].x - segment.points[0].x);
		point.y = segment.points[0].y + parameter *
		        (segment.points[1].y - segment.points[0].y);
		point.z = segment.points[0].z + parameter *
		        (segment.points[1].z - segment.points[0].z);
		point.spacing = segment.points[0].spacing + parameter *
		        (segment.points[1].spacing - segment.points[0].spacing);
		point.marker = RELIEF_BOUNDARY_MARK;
		pointIndex = findOrInsertTerrainDomainPoint(point, input);
		if (input->pointCount > oldPointCount) {
			return pointIndex;
		}
	}
	GfFatal("Crossing terrain relief cannot insert a fresh interior point\n");
	exit(1);
}


/** @brief Test whether a domain already contains an undirected constraint. */
static bool
terrainDomainConstraintExists(const tMeshInput &input,
	                         int startPoint, int endPoint)
{
	int segmentIndex;
	for (segmentIndex = 0; segmentIndex < input.segmentCount; segmentIndex++) {
		const tConstraintSegment &segment = input.segments[segmentIndex];
		if (((segment.startNode == startPoint) &&
		     (segment.endNode == endPoint)) ||
		        ((segment.startNode == endPoint) &&
		         (segment.endNode == startPoint))) {
			return true;
		}
	}
	return false;
}


/** @brief Test whether a point currently belongs to a domain-ring constraint. */
static bool
terrainDomainConstraintUsesPoint(const tMeshInput &input, int pointIndex)
{
	int segmentIndex;
	for (segmentIndex = 0; segmentIndex < input.segmentCount; segmentIndex++) {
		if ((input.segments[segmentIndex].startNode == pointIndex) ||
		        (input.segments[segmentIndex].endNode == pointIndex)) {
			return true;
		}
	}
	return false;
}


/** @brief Reconcile one planar relief intersection without moving ring heights. */
static void
reconcileTerrainReliefIntersection(
		double x, double y, double firstZ, double secondZ,
		double firstSpacing, double secondSpacing, tMeshInput *input)
{
	TerrainDomainPoint intersection;
	int pointIndex;
	if (fabs(firstZ - secondZ) > CROSSING_RELIEF_ELEVATION_EPSILON) {
		GfFatal("Intersecting terrain relief segments disagree in elevation\n");
		exit(1);
	}
	intersection.x = x;
	intersection.y = y;
	intersection.z = 0.5 * (firstZ + secondZ);
	intersection.spacing = min(firstSpacing, secondSpacing);
	intersection.marker = RELIEF_BOUNDARY_MARK;
	pointIndex = findOrInsertTerrainDomainPoint(intersection, input);
	if (!terrainDomainConstraintUsesPoint(*input, pointIndex)) {
		if (fabs(input->points[pointIndex].z - intersection.z) >
		        CROSSING_RELIEF_ELEVATION_EPSILON) {
			GfFatal("Intersecting terrain relief segments disagree in elevation\n");
			exit(1);
		}
		input->points[pointIndex].z = min(
		        input->points[pointIndex].z, min(firstZ, secondZ));
		input->points[pointIndex].spacing = min(
		        input->points[pointIndex].spacing,
		        min(firstSpacing, secondSpacing));
	}
}


/** @brief Validate and reconcile an endpoint lying on another relief segment. */
static void
reconcileTerrainReliefEndpoint(
		const TerrainDomainPoint &point,
		const TerrainDomainSegment &segment, tMeshInput *input)
{
	double deltaX = segment.points[1].x - segment.points[0].x;
	double deltaY = segment.points[1].y - segment.points[0].y;
	double lengthSquared = deltaX * deltaX + deltaY * deltaY;
	double offsetX;
	double offsetY;
	double parameter;
	double parameterTolerance;
	double nearestX;
	double nearestY;
	double segmentSpacing;
	double segmentZ;
	if (lengthSquared <= CROSSING_RELIEF_POINT_EPSILON *
	        CROSSING_RELIEF_POINT_EPSILON) {
		return;
	}
	offsetX = point.x - segment.points[0].x;
	offsetY = point.y - segment.points[0].y;
	parameter = (offsetX * deltaX + offsetY * deltaY) / lengthSquared;
	parameterTolerance = CROSSING_RELIEF_POINT_EPSILON / sqrt(lengthSquared);
	if ((parameter < -parameterTolerance) ||
	        (parameter > 1.0 + parameterTolerance)) {
		return;
	}
	parameter = max(0.0, min(1.0, parameter));
	nearestX = segment.points[0].x + parameter * deltaX;
	nearestY = segment.points[0].y + parameter * deltaY;
	if ((point.x - nearestX) * (point.x - nearestX) +
	        (point.y - nearestY) * (point.y - nearestY) >
	        CROSSING_RELIEF_POINT_EPSILON *
	        CROSSING_RELIEF_POINT_EPSILON) {
		return;
	}
	segmentZ = segment.points[0].z + parameter *
	        (segment.points[1].z - segment.points[0].z);
	segmentSpacing = segment.points[0].spacing + parameter *
	        (segment.points[1].spacing - segment.points[0].spacing);
	reconcileTerrainReliefIntersection(
	        nearestX, nearestY, point.z, segmentZ,
	        point.spacing, segmentSpacing, input);
}


/** @brief Insert shared nodes where clipped relief segments cross. */
static void
insertTerrainReliefIntersections(
		const std::vector<TerrainDomainSegment> &segments,
		tMeshInput *input)
{
	size_t firstIndex;
	for (firstIndex = 0; firstIndex < segments.size(); firstIndex++) {
		double firstX = segments[firstIndex].points[1].x -
		        segments[firstIndex].points[0].x;
		double firstY = segments[firstIndex].points[1].y -
		        segments[firstIndex].points[0].y;
		double firstLengthSquared = firstX * firstX + firstY * firstY;
		double firstEndpointTolerance;
		size_t secondIndex;
		if (firstLengthSquared <= CROSSING_RELIEF_POINT_EPSILON *
		        CROSSING_RELIEF_POINT_EPSILON) {
			continue;
		}
		firstEndpointTolerance = CROSSING_RELIEF_POINT_EPSILON /
		        sqrt(firstLengthSquared);
		for (secondIndex = firstIndex + 1; secondIndex < segments.size();
		        secondIndex++) {
			double secondX = segments[secondIndex].points[1].x -
			        segments[secondIndex].points[0].x;
			double secondY = segments[secondIndex].points[1].y -
			        segments[secondIndex].points[0].y;
			double secondLengthSquared = secondX * secondX + secondY * secondY;
			double secondEndpointTolerance;
			double denominator = firstX * secondY - firstY * secondX;
			double offsetX;
			double offsetY;
			double firstParameter;
			double secondParameter;
			double firstSpacing;
			double firstZ;
			double secondSpacing;
			double secondZ;
			if ((secondLengthSquared <= CROSSING_RELIEF_POINT_EPSILON *
			         CROSSING_RELIEF_POINT_EPSILON)) {
				continue;
			}
			secondEndpointTolerance = CROSSING_RELIEF_POINT_EPSILON /
			        sqrt(secondLengthSquared);
			reconcileTerrainReliefEndpoint(
			        segments[firstIndex].points[0], segments[secondIndex], input);
			reconcileTerrainReliefEndpoint(
			        segments[firstIndex].points[1], segments[secondIndex], input);
			reconcileTerrainReliefEndpoint(
			        segments[secondIndex].points[0], segments[firstIndex], input);
			reconcileTerrainReliefEndpoint(
			        segments[secondIndex].points[1], segments[firstIndex], input);
			if (denominator == 0.0) {
				continue;
			}
			offsetX = segments[secondIndex].points[0].x -
			        segments[firstIndex].points[0].x;
			offsetY = segments[secondIndex].points[0].y -
			        segments[firstIndex].points[0].y;
			firstParameter = (offsetX * secondY - offsetY * secondX) /
			        denominator;
			secondParameter = (offsetX * firstY - offsetY * firstX) /
			        denominator;
			if ((firstParameter < -firstEndpointTolerance) ||
			        (firstParameter > 1.0 + firstEndpointTolerance) ||
			        (secondParameter < -secondEndpointTolerance) ||
			        (secondParameter > 1.0 + secondEndpointTolerance)) {
				continue;
			}
			firstParameter = max(0.0, min(1.0, firstParameter));
			secondParameter = max(0.0, min(1.0, secondParameter));
			if ((firstParameter <= firstEndpointTolerance) ||
			        (firstParameter >= 1.0 - firstEndpointTolerance) ||
			        (secondParameter <= secondEndpointTolerance) ||
			        (secondParameter >= 1.0 - secondEndpointTolerance)) {
				continue;
			}
			firstZ = segments[firstIndex].points[0].z + firstParameter *
			        (segments[firstIndex].points[1].z -
			         segments[firstIndex].points[0].z);
			secondZ = segments[secondIndex].points[0].z + secondParameter *
			        (segments[secondIndex].points[1].z -
			         segments[secondIndex].points[0].z);
			firstSpacing = segments[firstIndex].points[0].spacing +
			        firstParameter *
			        (segments[firstIndex].points[1].spacing -
			         segments[firstIndex].points[0].spacing);
			secondSpacing = segments[secondIndex].points[0].spacing +
			        secondParameter *
			        (segments[secondIndex].points[1].spacing -
			         segments[secondIndex].points[0].spacing);
			reconcileTerrainReliefIntersection(
			        segments[firstIndex].points[0].x + firstParameter * firstX,
			        segments[firstIndex].points[0].y + firstParameter * firstY,
			        firstZ, secondZ, firstSpacing, secondSpacing, input);
		}
	}
}


/** @brief Sort existing points by parameter along one relief segment. */
static bool
terrainReliefConstraintPointOrder(
		const tTerrainReliefConstraintPoint &first,
		const tTerrainReliefConstraintPoint &second)
{
	if (first.parameter != second.parameter) {
		return first.parameter < second.parameter;
	}
	return first.pointIndex < second.pointIndex;
}


/** @brief Append one ordered relief constraint without merging adjacent chains. */
static void
appendTerrainReliefConstraint(
		int startPoint, int endPoint, tMeshInput *input,
		bool *chainActive, int *chainStartPoint, int *chainEndPoint)
{
	bool startsNewChain;
	if ((startPoint == endPoint) ||
	        terrainDomainConstraintExists(*input, startPoint, endPoint)) {
		*chainActive = false;
		return;
	}
	reserveTerrainDomainSegments(input, input->segmentCount + 1);
	startsNewChain = !*chainActive || (*chainEndPoint != startPoint);
	if (startsNewChain) {
		*chainStartPoint = startPoint;
	}
	input->segments[input->segmentCount].startNode = startPoint;
	input->segments[input->segmentCount].endNode = endPoint;
	input->segments[input->segmentCount].startsNewChain =
	        startsNewChain ? 1 : 0;
	input->segments[input->segmentCount].recoverDisconnectedSide = 1;
	input->segments[input->segmentCount].marker = RELIEF_BOUNDARY_MARK;
	input->segmentCount++;
	*chainEndPoint = endPoint;
	*chainActive = endPoint != *chainStartPoint;
}


/** @brief Triangulate and append one discovered crossing terrain domain. */
void
TerrainGenerationContext::generateCrossingTerrainDomain(
		const TerrainDomain &domain, int domainIndex,
		const std::vector<tMeshNode> trackBoundaries[2],
		const tTerrainReliefData &relief)
{
	tCrossingTerrainSpacingContext spacingContext;
	std::vector<TerrainDomainSegment> clippedRelief;
	std::vector<TerrainDomainPoint> isolatedRelief;
	std::vector<bool> referencedReliefPoints(relief.points.size(), false);
	bool reliefChainActive = false;
	char domainName[64];
	int reliefChainEndPoint = -1;
	int reliefChainStartPoint = -1;
	int pointCount = (int)domain.outer.points.size();
	size_t holeIndex;
	size_t reliefIndex;
	for (holeIndex = 0; holeIndex < domain.holes.size(); holeIndex++) {
		pointCount += (int)domain.holes[holeIndex].points.size();
	}
	for (reliefIndex = 0; reliefIndex < relief.segments.size(); reliefIndex++) {
		const tTerrainReliefSegment &reliefSegment = relief.segments[reliefIndex];
		TerrainDomainSegment segment;
		segment.points[0] = relief.points[reliefSegment.startPoint];
		segment.points[1] = relief.points[reliefSegment.endPoint];
		referencedReliefPoints[reliefSegment.startPoint] = true;
		referencedReliefPoints[reliefSegment.endPoint] = true;
		ClipTerrainDomainSegment(domain, segment, &clippedRelief);
	}
	for (reliefIndex = 0; reliefIndex < relief.points.size(); reliefIndex++) {
		const TerrainDomainPoint &point = relief.points[reliefIndex];
		if (!referencedReliefPoints[reliefIndex] &&
		        TerrainDomainContainsPoint(domain, point.x, point.y)) {
			isolatedRelief.push_back(point);
		}
	}
	Input.pointCapacity = pointCount + (int)clippedRelief.size() * 3 +
	        (int)isolatedRelief.size() + 1;
	Input.segmentCapacity = pointCount + (int)clippedRelief.size() * 5 +
	        (int)isolatedRelief.size() + 1;
	Input.points = (tMeshNode *)calloc(Input.pointCapacity, sizeof(tMeshNode));
	Input.segments = (tConstraintSegment *)calloc(
	        Input.segmentCapacity, sizeof(tConstraintSegment));
	if ((Input.points == NULL) || (Input.segments == NULL)) {
		GfFatal("Cannot allocate crossing terrain domain input\n");
		exit(1);
	}
	Input.pointCount = 0;
	Input.segmentCount = 0;
	appendTerrainDomainRing(domain.outer, &Input);
	for (holeIndex = 0; holeIndex < domain.holes.size(); holeIndex++) {
		appendTerrainDomainRing(domain.holes[holeIndex], &Input);
	}
	/* Make every relief endpoint available before resolving T-junctions. */
	for (reliefIndex = 0; reliefIndex < clippedRelief.size(); reliefIndex++) {
		findOrInsertTerrainDomainPoint(
		        clippedRelief[reliefIndex].points[0], &Input);
		findOrInsertTerrainDomainPoint(
		        clippedRelief[reliefIndex].points[1], &Input);
	}
	insertTerrainReliefIntersections(clippedRelief, &Input);
	for (reliefIndex = 0; reliefIndex < clippedRelief.size(); reliefIndex++) {
		std::vector<tTerrainReliefConstraintPoint> orderedPoints;
		std::vector<tTerrainReliefConstraintPoint> uniquePoints;
		double deltaX = clippedRelief[reliefIndex].points[1].x -
		        clippedRelief[reliefIndex].points[0].x;
		double deltaY = clippedRelief[reliefIndex].points[1].y -
		        clippedRelief[reliefIndex].points[0].y;
		double lengthSquared = deltaX * deltaX + deltaY * deltaY;
		double parameterTolerance;
		int knownPointCount = Input.pointCount;
		int pointIndex;
		size_t intervalIndex;
		if (lengthSquared <= CROSSING_RELIEF_POINT_EPSILON *
		        CROSSING_RELIEF_POINT_EPSILON) {
			reliefChainActive = false;
			continue;
		}
		parameterTolerance = CROSSING_RELIEF_POINT_EPSILON /
		        sqrt(lengthSquared);
		for (pointIndex = 0; pointIndex < knownPointCount; pointIndex++) {
			double offsetX = Input.points[pointIndex].x -
			        clippedRelief[reliefIndex].points[0].x;
			double offsetY = Input.points[pointIndex].y -
			        clippedRelief[reliefIndex].points[0].y;
			double parameter = (offsetX * deltaX + offsetY * deltaY) /
			        lengthSquared;
			double lineCross = deltaX * offsetY - deltaY * offsetX;
			if ((parameter < -parameterTolerance) ||
			        (parameter > 1.0 + parameterTolerance) ||
			        (lineCross * lineCross >
			         CROSSING_RELIEF_POINT_EPSILON *
			         CROSSING_RELIEF_POINT_EPSILON * lengthSquared)) {
				continue;
			}
			tTerrainReliefConstraintPoint orderedPoint;
			orderedPoint.parameter = max(0.0, min(1.0, parameter));
			orderedPoint.pointIndex = pointIndex;
			orderedPoints.push_back(orderedPoint);
		}
		std::sort(orderedPoints.begin(), orderedPoints.end(),
		          terrainReliefConstraintPointOrder);
		for (intervalIndex = 0; intervalIndex < orderedPoints.size();
		        intervalIndex++) {
			if (uniquePoints.empty() ||
			        (fabs(uniquePoints.back().parameter -
			              orderedPoints[intervalIndex].parameter) >
			         parameterTolerance)) {
				uniquePoints.push_back(orderedPoints[intervalIndex]);
			}
		}
		for (intervalIndex = 0; intervalIndex + 1 < uniquePoints.size();
		        intervalIndex++) {
			TerrainDomainSegment interval;
			int intervalStart = uniquePoints[intervalIndex].pointIndex;
			int intervalEnd = uniquePoints[intervalIndex + 1].pointIndex;
			int freshPoint;
			if (terrainDomainConstraintExists(
			        Input, intervalStart, intervalEnd)) {
				reliefChainActive = false;
				continue;
			}
			interval.points[0] = toTerrainDomainPoint(
			        Input.points[intervalStart]);
			interval.points[1] = toTerrainDomainPoint(
			        Input.points[intervalEnd]);
			freshPoint = insertFreshTerrainReliefPoint(interval, &Input);
			appendTerrainReliefConstraint(
			        intervalStart, freshPoint, &Input,
			        &reliefChainActive, &reliefChainStartPoint,
			        &reliefChainEndPoint);
			appendTerrainReliefConstraint(
			        freshPoint, intervalEnd,
			        &Input, &reliefChainActive, &reliefChainStartPoint,
			        &reliefChainEndPoint);
		}
	}
	for (reliefIndex = 0; reliefIndex < isolatedRelief.size(); reliefIndex++) {
		findOrInsertTerrainDomainPoint(isolatedRelief[reliefIndex], &Input);
	}
	reserveTerrainDomainSegments(&Input, Input.segmentCount + 1);
	Input.segments[Input.segmentCount].startNode = MISSING_MESH_INDEX;
	Input.segments[Input.segmentCount].endNode = MISSING_MESH_INDEX;

	spacingContext.boundaries = trackBoundaries;
	spacingContext.terrainGridStep = TerrainGridStep;
	spacingContext.nearTrackSpacingFloor =
	        min(TrackSamplingStep, TerrainGridStep);
	spacingContext.terrainTransition = TerrainTransition;
	snprintf(domainName, sizeof(domainName), "crossing-%s-%d",
	         domain.exterior ? "exterior" : "interior", domainIndex);
	Mesh.generateMesh(&Input, domainName, TrackgenQuiet,
	                  TerrainTransition > 0.0 ?
	                  crossingTerrainTargetSpacing : NULL,
	                  TerrainTransition > 0.0 ? &spacingContext : NULL);
	Output.append(Mesh, &domain);
	releaseDomainInput();
}


/** @brief Discover and triangulate all terrain regions around crossings. */
void
TerrainGenerationContext::generateCrossingTerrain(
		tTrack *track, const TrackCrossingModel *crossingModel)
{
	std::vector<tMeshNode> trackBoundaries[2];
	std::vector<TerrainDomainBoundaryGroup> occupiedGroups(1);
	std::vector<TerrainDomainTriangle> occupiedTriangles;
	std::vector<TrackBoundaryTransition> boundaryTransitions[2];
	std::vector<TerrainDomain> domains;
	tTerrainReliefData exteriorRelief;
	tTerrainReliefData interiorRelief;
	TerrainDomainRing border;
	TerrainDomainPoint borderPoint;
	char errorMessage[1024];
	double borderMaximumX;
	double borderMaximumY;
	double borderMinimumX;
	double borderMinimumY;
	int terrainGroupRowCount;
	int side;
	size_t crossingIndex;
	size_t domainIndex;
	size_t groupIndex;
	size_t pointIndex;
	size_t transitionIndex[2] = {0, 0};
	tMeshNode closurePoints[2];

	occupiedGroups[0].preserveBoundaries = true;
	sampleCrossingBoundary(track, TR_SIDE_RGT,
	                       &trackBoundaries[TR_SIDE_RGT],
	                       &closurePoints[TR_SIDE_RGT],
	                       &boundaryTransitions[TR_SIDE_RGT]);
	sampleCrossingBoundary(track, TR_SIDE_LFT,
	                       &trackBoundaries[TR_SIDE_LFT],
	                       &closurePoints[TR_SIDE_LFT],
	                       &boundaryTransitions[TR_SIDE_LFT]);
	if (trackBoundaries[TR_SIDE_RGT].empty() ||
	        trackBoundaries[TR_SIDE_LFT].empty()) {
		GfFatal("Crossing terrain track boundaries are empty\n");
		exit(1);
	}
	bool appendClosure = false;
	for (side = 0; side < 2; side++) {
		double deltaX;
		double deltaY;
		deltaX = closurePoints[side].x - trackBoundaries[side][0].x;
		deltaY = closurePoints[side].y - trackBoundaries[side][0].y;
		appendClosure = appendClosure ||
		        (deltaX * deltaX + deltaY * deltaY >
		         CROSSING_TERRAIN_POINT_EPSILON *
		         CROSSING_TERRAIN_POINT_EPSILON);
	}
	if (appendClosure) {
		trackBoundaries[TR_SIDE_RGT].push_back(
		        closurePoints[TR_SIDE_RGT]);
		trackBoundaries[TR_SIDE_LFT].push_back(
		        closurePoints[TR_SIDE_LFT]);
	}
	if ((trackBoundaries[TR_SIDE_RGT].size() < 3) ||
	        (trackBoundaries[TR_SIDE_RGT].size() !=
	         trackBoundaries[TR_SIDE_LFT].size())) {
		GfFatal("Crossing terrain track boundaries are not synchronized\n");
		exit(1);
	}
	for (pointIndex = 0;
	        pointIndex < trackBoundaries[TR_SIDE_RGT].size(); pointIndex++) {
		const TrackBoundaryTransition *transition[2] = {NULL, NULL};
		size_t nextPoint = (pointIndex + 1) %
		        trackBoundaries[TR_SIDE_RGT].size();
		for (side = 0; side < 2; side++) {
			while ((transitionIndex[side] < boundaryTransitions[side].size()) &&
			        (boundaryTransitions[side][transitionIndex[side]].pointIndex <
			         (int)pointIndex)) {
				transitionIndex[side]++;
			}
			if ((transitionIndex[side] < boundaryTransitions[side].size()) &&
			        (boundaryTransitions[side][transitionIndex[side]].pointIndex ==
			         (int)pointIndex)) {
				transition[side] =
				        &boundaryTransitions[side][transitionIndex[side]];
			}
		}
		TerrainDomainPoint right = toTerrainDomainPoint(
		        trackBoundaries[TR_SIDE_RGT][pointIndex]);
		TerrainDomainPoint left = toTerrainDomainPoint(
		        trackBoundaries[TR_SIDE_LFT][pointIndex]);
		TerrainDomainPoint nextRight = toTerrainDomainPoint(
		        trackBoundaries[TR_SIDE_RGT][nextPoint]);
		TerrainDomainPoint nextLeft = toTerrainDomainPoint(
		        trackBoundaries[TR_SIDE_LFT][nextPoint]);
		TerrainDomainPoint currentRight = right;
		TerrainDomainPoint currentLeft = left;
		if (transition[TR_SIDE_RGT] != NULL) {
			currentRight = toTerrainDomainPoint(
			        transition[TR_SIDE_RGT]->point);
		}
		if (transition[TR_SIDE_LFT] != NULL) {
			currentLeft = toTerrainDomainPoint(
			        transition[TR_SIDE_LFT]->point);
		}
		appendOccupiedBoundary(right, currentRight,
		                       &occupiedGroups[0].boundaries);
		appendOccupiedBoundary(currentRight, nextRight,
		                       &occupiedGroups[0].boundaries);
		appendOccupiedBoundary(left, currentLeft,
		                       &occupiedGroups[0].boundaries);
		appendOccupiedBoundary(currentLeft, nextLeft,
		                       &occupiedGroups[0].boundaries);
		appendOccupiedTriangle(right, left, currentRight,
		                       &occupiedGroups[0].triangles);
		appendOccupiedTriangle(left, currentLeft, currentRight,
		                       &occupiedGroups[0].triangles);
		appendOccupiedTriangle(currentRight, currentLeft, nextRight,
		                       &occupiedGroups[0].triangles);
		appendOccupiedTriangle(currentLeft, nextLeft, nextRight,
		                       &occupiedGroups[0].triangles);
	}
	for (crossingIndex = 0; crossingIndex < crossingModel->crossings.size();
	        crossingIndex++) {
		const TrackCrossingGeometry &crossing =
		        crossingModel->crossings[crossingIndex];
		const TrackCrossingObject *objects[] = {
			&crossing.underside,
			&crossing.bridgeRight,
			&crossing.bridgeLeft,
			&crossing.socketRight,
			&crossing.socketLeft,
			&crossing.filler[TR_SIDE_RGT][TR_SIDE_RGT],
			&crossing.filler[TR_SIDE_LFT][TR_SIDE_RGT],
			&crossing.filler[TR_SIDE_RGT][TR_SIDE_LFT],
			&crossing.filler[TR_SIDE_LFT][TR_SIDE_LFT],
			&crossing.floorRight,
			&crossing.floorLeft,
			&crossing.terrainMask
		};
		for (size_t objectIndex = 0; objectIndex < sizeof(objects) / sizeof(objects[0]); objectIndex++) {
			TerrainDomainBoundaryGroup group;
			group.preserveBoundaries = false;
			if (appendCrossingObjectTriangles(*objects[objectIndex],
			        TerrainGridStep, &group) != 0) {
				GfFatal("Crossing terrain geometry has an invalid triangle\n");
				exit(1);
			}
			occupiedGroups.push_back(group);
		}
	}
	for (groupIndex = 0; groupIndex < occupiedGroups.size(); groupIndex++) {
		occupiedTriangles.insert(occupiedTriangles.end(),
		        occupiedGroups[groupIndex].triangles.begin(),
		        occupiedGroups[groupIndex].triangles.end());
	}
	loadTerrainRelief(0, &exteriorRelief);
	loadTerrainRelief(1, &interiorRelief);
	if (UseBorder) {
		borderPoint.z = ExteriorHeight;
		borderPoint.spacing = TerrainGridStep;
		borderPoint.marker = RELIEF_BOUNDARY_MARK;
		borderPoint.x = -TerrainMargin;
		borderPoint.y = -TerrainMargin;
		border.points.push_back(borderPoint);
		borderPoint.x = track->max.x + TerrainMargin;
		border.points.push_back(borderPoint);
		borderPoint.y = track->max.y + TerrainMargin;
		border.points.push_back(borderPoint);
		borderPoint.x = -TerrainMargin;
		border.points.push_back(borderPoint);
	} else if (!findTerrainReliefBorder(
	        exteriorRelief, occupiedTriangles, &border)) {
		GfFatal("Crossing terrain -B requires an exterior relief ring\n");
		exit(1);
	}
	borderMinimumX = borderMaximumX = border.points[0].x;
	borderMinimumY = borderMaximumY = border.points[0].y;
	for (pointIndex = 1; pointIndex < border.points.size(); pointIndex++) {
		borderMinimumX = min(borderMinimumX, border.points[pointIndex].x);
		borderMaximumX = max(borderMaximumX, border.points[pointIndex].x);
		borderMinimumY = min(borderMinimumY, border.points[pointIndex].y);
		borderMaximumY = max(borderMaximumY, border.points[pointIndex].y);
	}
	TerrainGroupXOffset = (float)borderMinimumX;
	TerrainGroupYOffset = (float)borderMinimumY;
	TerrainGroupColumnCount =
	        (int)((borderMaximumX - borderMinimumX) / TerrainGroupSize) + 1;
	terrainGroupRowCount =
	        (int)((borderMaximumY - borderMinimumY) / TerrainGroupSize) + 1;
	TerrainGroupCount = TerrainGroupColumnCount * terrainGroupRowCount;
	Output.configure(TerrainGroupSize, TerrainGroupXOffset, TerrainGroupYOffset,
	                 TerrainGroupColumnCount, TerrainGroupCount,
	                 TerrainTextureName, TerrainTextureSize, true);

	if (BuildTerrainDomains(occupiedGroups, border, &domains,
	        errorMessage, sizeof(errorMessage)) != 0) {
		GfFatal("Cannot build crossing terrain domains: %s\n", errorMessage);
		exit(1);
	}
	printf("Crossing terrain domains: %d\n", (int)domains.size());
	for (domainIndex = 0; domainIndex < domains.size(); domainIndex++) {
		generateCrossingTerrainDomain(domains[domainIndex], (int)domainIndex,
		                              trackBoundaries,
		                              domains[domainIndex].exterior ?
		                              exteriorRelief : interiorRelief);
	}
}


/** @brief Reverse sampled boundary winding before relief points are appended. */
void
TerrainGenerationContext::reverseBoundaryPoints(int reliefVertexCount)
{
	int pointIndex;
	tMeshNode *reversedPoints;

	Input.pointCapacity = Input.pointCount + 1 + reliefVertexCount;
	reversedPoints = (tMeshNode *)calloc(Input.pointCapacity,
	                                     sizeof(tMeshNode));
	if (reversedPoints == NULL) {
		GfFatal("Cannot allocate reversed terrain boundary storage\n");
		exit(1);
	}
	for (pointIndex = 0; pointIndex < Input.pointCount; pointIndex++) {
		memcpy(&reversedPoints[pointIndex],
		       &Input.points[Input.pointCount - pointIndex - 1],
		       sizeof(tMeshNode));
	}
	free(Input.points);
	Input.points = reversedPoints;
}


/** @brief Build ordered segments for one sampled terrain domain. */
void
TerrainGenerationContext::buildDomainConstraints(bool exteriorDomain,
                                                  int sampledPointCount)
{
	int constraintIndex;
	int pointIndex;

	Input.segmentCount = 0;
	if (exteriorDomain && !UseBorder) {
		appendReliefConstraints(0);
	}
	if (exteriorDomain && UseBorder) {
		Input.segments[0].startNode = 0;
		Input.segments[0].endNode = 1;
		Input.segments[0].marker = RELIEF_BOUNDARY_MARK;
		Input.segments[1].startNode = 1;
		Input.segments[1].endNode = 2;
		Input.segments[1].marker = RELIEF_BOUNDARY_MARK;
		Input.segments[2].startNode = 2;
		Input.segments[2].endNode = 3;
		Input.segments[2].marker = RELIEF_BOUNDARY_MARK;
		Input.segments[3].startNode = 3;
		Input.segments[3].endNode = 0;
		Input.segments[3].marker = RELIEF_BOUNDARY_MARK;

		pointIndex = 0;
		constraintIndex = 0;
		do {
			Input.segments[constraintIndex + 4].startNode = pointIndex + 4;
			pointIndex = (pointIndex + 1) % (sampledPointCount - 4);
			Input.segments[constraintIndex + 4].endNode = pointIndex + 4;
			Input.segments[constraintIndex + 4].marker = 2;
			constraintIndex++;
		} while (pointIndex != 0);
	} else {
		pointIndex = 0;
		constraintIndex = Input.segmentCount;
		do {
			Input.segments[constraintIndex].startNode = pointIndex;
			pointIndex = (pointIndex + 1) % sampledPointCount;
			Input.segments[constraintIndex].endNode = pointIndex;
			Input.segments[constraintIndex].marker = 1;
			constraintIndex++;
		} while (pointIndex != 0);
		Input.segmentCount = constraintIndex;
	}
	if (exteriorDomain) {
		if (UseBorder) {
			Input.segmentCount = sampledPointCount;
			appendReliefConstraints(0);
		}
	} else {
		Input.segmentCount = sampledPointCount;
		appendReliefConstraints(1);
	}
	Input.segments[Input.segmentCount].startNode = MISSING_MESH_INDEX;
	Input.segments[Input.segmentCount].endNode = MISSING_MESH_INDEX;
}


/** @brief Generate one terrain triangulation domain. */
void
TerrainGenerationContext::generateTerrainDomain(tTrack *track, int side,
                                                 bool reverseOrder,
                                                 bool exteriorDomain)
{
	int reliefVertexCount, reliefSegmentCount;
	int sampledPointCount;
	int firstTrackBoundaryPoint;
	int trackBoundaryPointCount;
	tTerrainSpacingContext spacingContext;

	printf("GenerateMesh: ");
	if (side == TR_SIDE_RGT) {
		printf("right, ");
	} else {
		printf("left, ");
	}
	if (reverseOrder) {
		printf("reverse order, ");
	} else {
		printf("normal order, ");
	}
	if (exteriorDomain) {
		printf("exterior\n");
	} else {
		printf("interior\n");
	}

	CountRelief(1 - exteriorDomain, &reliefVertexCount, &reliefSegmentCount);

	printf("Relief: %d vtx, %d seg\n", reliefVertexCount, reliefSegmentCount);

	Input.pointCapacity = max(1, (int)(track->length) + reliefVertexCount);
	Input.points = (tMeshNode *)calloc(Input.pointCapacity, sizeof(tMeshNode));
	if (Input.points == NULL) {
		GfFatal("Cannot allocate terrain boundary point storage\n");
		exit(1);
	}
	Input.pointCount = 0;

	if (exteriorDomain && !reverseOrder && UseBorder) {
		appendExteriorBorder(track, false);
	}
	if (sampleTrackBoundary(track, side, TrackSamplingStep, TerrainGridStep,
	                        false, &Input, NULL, NULL) != 0) {
		GfFatal("Cannot grow terrain boundary point storage\n");
		exit(1);
	}
	if (exteriorDomain && reverseOrder && UseBorder) {
		appendExteriorBorder(track, true);
	}
	sampledPointCount = Input.pointCount;
	reserveBoundaryPoints(sampledPointCount + reliefVertexCount + 1);

	Input.segmentCapacity = sampledPointCount + 1 + reliefSegmentCount;
	Input.segments = (tConstraintSegment *)calloc(
	        Input.segmentCapacity, sizeof(tConstraintSegment));
	if (Input.segments == NULL) {
		GfFatal("Cannot allocate terrain constraint storage\n");
		exit(1);
	}
	Input.segments[Input.pointCount].startNode = MISSING_MESH_INDEX;
	Input.segments[Input.pointCount].endNode = MISSING_MESH_INDEX;

	if (reverseOrder) {
		reverseBoundaryPoints(reliefVertexCount);
	}
	firstTrackBoundaryPoint = exteriorDomain && UseBorder ? 4 : 0;
	trackBoundaryPointCount = sampledPointCount - firstTrackBoundaryPoint;

	buildDomainConstraints(exteriorDomain, sampledPointCount);
	spacingContext.points = Input.points;
	spacingContext.firstTrackBoundaryPoint = firstTrackBoundaryPoint;
	spacingContext.trackBoundaryPointCount = trackBoundaryPointCount;
	spacingContext.terrainGridStep = TerrainGridStep;
	spacingContext.nearTrackSpacingFloor = min(TrackSamplingStep, TerrainGridStep);
	spacingContext.terrainTransition = TerrainTransition;
	Mesh.generateMesh(&Input, exteriorDomain ? "exterior" : "interior",
	                  TrackgenQuiet,
	                  TerrainTransition > 0.0 ? terrainTargetSpacing : NULL,
	                  TerrainTransition > 0.0 ? &spacingContext : NULL);
	Output.append(Mesh);
	releaseDomainInput();
}


/** @brief Configure, generate, and write both terrain domains. */
void
TerrainGenerationContext::generateTerrain(tTrack *track, void *TrackHandle,
                                           char *outfile, FILE *AllFd,
                                           int noElevation,
                                           const TrackCrossingModel *crossingModel)
{
	const char *FileName;
	const char *mat;
	FILE *curFd = NULL;
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];

	TrackSamplingStep = GfParmGetNum(TrackHandle, TRK_SECT_TERRAIN, TRK_ATT_TSTEP, NULL, 10.0);
	GfOut("Track step: %.2f ", TrackSamplingStep);
	TerrainMargin = GfParmGetNum(TrackHandle, TRK_SECT_TERRAIN, TRK_ATT_BMARGIN, NULL, 100.0);
	TerrainGridStep = GfParmGetNum(TrackHandle, TRK_SECT_TERRAIN, TRK_ATT_BSTEP, NULL, 10.0);
	TerrainTransition = GfParmGetNum(TrackHandle, TRK_SECT_TERRAIN,
	                                 TRK_ATT_TTRANSITION, NULL, TerrainMargin);
	ExteriorHeight = GfParmGetNum(TrackHandle, TRK_SECT_TERRAIN, TRK_ATT_BHEIGHT, NULL, 0.0);
	GfOut("Border margin: %.2f    step: %.2f    transition: %.2f    height: %.2f",
	      TerrainMargin, TerrainGridStep, TerrainTransition, ExteriorHeight);

	TerrainGroupSize = GfParmGetNum(TrackHandle, TRK_SECT_TERRAIN, TRK_ATT_GRPSZ, NULL, 100.0);
	TerrainGroupXOffset = track->min.x - TerrainMargin;
	TerrainGroupYOffset = track->min.y - TerrainMargin;
	TerrainGroupColumnCount = (int)((track->max.x + TerrainMargin - (track->min.x - TerrainMargin)) / TerrainGroupSize) + 1;
	TerrainGroupCount = TerrainGroupColumnCount * ((int)((track->max.y + TerrainMargin - (track->min.y - TerrainMargin)) / TerrainGroupSize) + 1);

	mat = GfParmGetStr(TrackHandle, TRK_SECT_TERRAIN, TRK_ATT_SURF, "grass");
	if (track->version < 4) {
		snprintf(buf, BUFSIZE, "%s/%s/%s", TRK_SECT_SURFACES, TRK_LST_SURF, mat);
	} else {
		snprintf(buf, BUFSIZE, "%s/%s", TRK_SECT_SURFACES, mat);
	}
	TerrainTextureName = GfParmGetStr(TrackHandle, buf, TRK_ATT_TEXTURE, "grass.rgb");
	TerrainTextureSize = GfParmGetNum(TrackHandle, buf, TRK_ATT_TEXSIZE, (char *)NULL, 20.0);
	TerrainTextureRandomness = GfParmGetNum(TrackHandle, buf, TRK_ATT_SURFRAND,
	                                       (char *)NULL, TerrainTextureSize / 10.0);
	Output.configure(TerrainGroupSize, TerrainGroupXOffset, TerrainGroupYOffset,
	                 TerrainGroupColumnCount, TerrainGroupCount,
	                 TerrainTextureName, TerrainTextureSize,
	                 (crossingModel != NULL) &&
	                 !crossingModel->crossings.empty());

	FileName = GfParmGetStr(TrackHandle, TRK_SECT_TERRAIN, TRK_ATT_RELIEF, NULL);
	if (FileName) {
		snprintf(buf, BUFSIZE, "tracks/%s/%s/%s", track->category, track->internalname, FileName);
		LoadRelief(TrackHandle, buf);
	}
	if (noElevation == LOAD_CONFIGURED_ELEVATION) {
		FileName = GfParmGetStr(TrackHandle, TRK_SECT_TERRAIN, TRK_ATT_ELEVATION, NULL);
		if (FileName) {
			snprintf(buf, BUFSIZE, "tracks/%s/%s/%s", track->category, track->internalname, FileName);
			LoadElevation(track, TrackHandle, buf);
		}
	}

	if (outfile) {
		/* A single root group avoids an AC3D application crash on this file. */
		curFd = Ac3dOpen(outfile, 1);
	}

	if ((crossingModel != NULL) && !crossingModel->crossings.empty()) {
		generateCrossingTerrain(track, crossingModel);
		if (curFd) {
			Output.write(curFd, "TERR");
		}
		if (AllFd) {
			Output.write(AllFd, "TERR");
		}
	} else if (getTrackOrientation(track) == CLOCKWISE) {
		generateTerrainDomain(track, TR_SIDE_RGT, true, false);
		generateTerrainDomain(track, TR_SIDE_LFT, false, true);
		if (curFd) {
			Output.write(curFd, "TERR");
		}
		if (AllFd) {
			Output.write(AllFd, "TERR");
		}
	} else {
		generateTerrainDomain(track, TR_SIDE_LFT, false, false);
		generateTerrainDomain(track, TR_SIDE_RGT, true, true);
		if (curFd) {
			Output.write(curFd, "TERR");
		}
		if (AllFd) {
			Output.write(AllFd, "TERR");
		}
	}
	if (curFd) {
		Ac3dClose(curFd);
	}
}


void
GenerateTerrain(tTrack *track, void *TrackHandle, char *outfile, FILE *AllFd,
                int noElevation, const TrackCrossingModel *crossingModel)
{
	TerrainGenerationContext *context;

	context = new (std::nothrow) TerrainGenerationContext;
	if (context == NULL) {
		GfError("Cannot allocate terrain generation context\n");
		exit(1);
	}
	context->generateTerrain(track, TrackHandle, outfile, AllFd, noElevation,
	                         crossingModel);
	delete context;
}
