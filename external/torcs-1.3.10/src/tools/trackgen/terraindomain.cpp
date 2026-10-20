/***************************************************************************

    file                 : terraindomain.cpp
    created              : Sun Aug 2 2026
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
    @brief Planar terrain-domain discovery before EasyMesh triangulation.
 */

#include <algorithm>
#include <float.h>
#include <math.h>
#include <stdio.h>

#include "terraindomain.h"


static const double DOMAIN_GEOMETRY_EPSILON = 1e-8;
static const double DOMAIN_POINT_EPSILON = 1e-4;
static const double DOMAIN_MINIMUM_AREA = 1e-6;
static const double DOMAIN_BOUNDARY_EPSILON = 1e-7;
static const double DOMAIN_FACE_AREA_EPSILON =
		DOMAIN_GEOMETRY_EPSILON * DOMAIN_POINT_EPSILON;


struct TerrainDomainInputTriangle
{
	TerrainDomainTriangle triangle;
	double minimumX;
	double minimumY;
	double maximumX;
	double maximumY;
	int groupIndex;
};


struct TerrainDomainRawEdge
{
	TerrainDomainPoint start;
	TerrainDomainPoint end;
	std::vector<double> splits;
	double minimumX;
	double minimumY;
	double maximumX;
	double maximumY;
	int groupIndex;
	bool preserve;
};


struct TerrainDomainEdge
{
	int startNode;
	int endNode;
	bool used;
};


struct TerrainDomainLoop
{
	TerrainDomainRing ring;
	double area;
};


struct TerrainDomainOutgoingEdge
{
	int edgeIndex;
	double angle;
	double lengthSquared;
};


static void
setDomainError(char *errorMessage, size_t errorMessageSize,
	          const char *message)
{
	if ((errorMessage != NULL) && (errorMessageSize > 0)) {
		snprintf(errorMessage, errorMessageSize, "%s", message);
	}
}


static double
domainCross(double firstX, double firstY, double secondX, double secondY)
{
	return firstX * secondY - firstY * secondX;
}


static double
domainDistanceSquared(const TerrainDomainPoint &first,
	                 const TerrainDomainPoint &second)
{
	double deltaX = first.x - second.x;
	double deltaY = first.y - second.y;
	return deltaX * deltaX + deltaY * deltaY;
}


static TerrainDomainPoint
interpolateDomainPoint(const TerrainDomainPoint &start,
	                  const TerrainDomainPoint &end, double parameter)
{
	TerrainDomainPoint point;
	point.x = start.x + parameter * (end.x - start.x);
	point.y = start.y + parameter * (end.y - start.y);
	point.z = start.z + parameter * (end.z - start.z);
	point.spacing = start.spacing + parameter * (end.spacing - start.spacing);
	point.marker = parameter < 0.5 ? start.marker : end.marker;
	return point;
}


static double
signedRingArea(const TerrainDomainRing &ring)
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


static bool
pointInRing(const TerrainDomainRing &ring, double x, double y)
{
	bool inside = false;
	size_t firstIndex;
	size_t secondIndex;
	if (ring.points.size() < 3) {
		return false;
	}
	for (firstIndex = 0, secondIndex = ring.points.size() - 1;
	        firstIndex < ring.points.size(); secondIndex = firstIndex++) {
		const TerrainDomainPoint &first = ring.points[firstIndex];
		const TerrainDomainPoint &second = ring.points[secondIndex];
		bool crosses = ((first.y > y) != (second.y > y));
		if (crosses && (x < (second.x - first.x) * (y - first.y) /
		        (second.y - first.y) + first.x)) {
			inside = !inside;
		}
	}
	return inside;
}


bool
TerrainDomainContainsPoint(const TerrainDomain &domain, double x, double y)
{
	size_t holeIndex;
	if (!pointInRing(domain.outer, x, y)) {
		return false;
	}
	for (holeIndex = 0; holeIndex < domain.holes.size(); holeIndex++) {
		if (pointInRing(domain.holes[holeIndex], x, y)) {
			return false;
		}
	}
	return true;
}


static bool
pointOnRing(const TerrainDomainRing &ring, double x, double y)
{
	size_t pointIndex;
	for (pointIndex = 0; pointIndex < ring.points.size(); pointIndex++) {
		const TerrainDomainPoint &start = ring.points[pointIndex];
		const TerrainDomainPoint &end =
		        ring.points[(pointIndex + 1) % ring.points.size()];
		double edgeX = end.x - start.x;
		double edgeY = end.y - start.y;
		double pointX = x - start.x;
		double pointY = y - start.y;
		double lengthSquared = edgeX * edgeX + edgeY * edgeY;
		double parameter;
		double nearestX;
		double nearestY;
		if (lengthSquared <= DOMAIN_GEOMETRY_EPSILON *
		        DOMAIN_GEOMETRY_EPSILON) {
			continue;
		}
		parameter = (pointX * edgeX + pointY * edgeY) / lengthSquared;
		if ((parameter < -DOMAIN_GEOMETRY_EPSILON) ||
		        (parameter > 1.0 + DOMAIN_GEOMETRY_EPSILON)) {
			continue;
		}
		nearestX = start.x + parameter * edgeX;
		nearestY = start.y + parameter * edgeY;
		if ((x - nearestX) * (x - nearestX) +
		        (y - nearestY) * (y - nearestY) <=
		        DOMAIN_BOUNDARY_EPSILON * DOMAIN_BOUNDARY_EPSILON) {
			return true;
		}
	}
	return false;
}


bool
TerrainDomainCoversPoint(const TerrainDomain &domain, double x, double y)
{
	size_t holeIndex;
	if (pointOnRing(domain.outer, x, y)) {
		return true;
	}
	for (holeIndex = 0; holeIndex < domain.holes.size(); holeIndex++) {
		if (pointOnRing(domain.holes[holeIndex], x, y)) {
			return true;
		}
	}
	return TerrainDomainContainsPoint(domain, x, y);
}


static void appendSplit(std::vector<double> *splits, double parameter);
static double edgeParameter(const TerrainDomainRawEdge &edge,
	                       double x, double y);
static void sortUniqueSplits(std::vector<double> *splits);


static void
appendRingIntersections(const TerrainDomainRing &ring,
	                  const TerrainDomainSegment &segment,
	                  std::vector<double> *parameters)
{
	double segmentX = segment.points[1].x - segment.points[0].x;
	double segmentY = segment.points[1].y - segment.points[0].y;
	size_t pointIndex;
	for (pointIndex = 0; pointIndex < ring.points.size(); pointIndex++) {
		const TerrainDomainPoint &edgeStart = ring.points[pointIndex];
		const TerrainDomainPoint &edgeEnd =
		        ring.points[(pointIndex + 1) % ring.points.size()];
		double edgeX = edgeEnd.x - edgeStart.x;
		double edgeY = edgeEnd.y - edgeStart.y;
		double offsetX = edgeStart.x - segment.points[0].x;
		double offsetY = edgeStart.y - segment.points[0].y;
		double denominator = domainCross(segmentX, segmentY, edgeX, edgeY);
		if (fabs(denominator) > DOMAIN_GEOMETRY_EPSILON) {
			double segmentParameter = domainCross(
			        offsetX, offsetY, edgeX, edgeY) / denominator;
			double edgeParameterValue = domainCross(
			        offsetX, offsetY, segmentX, segmentY) / denominator;
			if ((segmentParameter >= -DOMAIN_GEOMETRY_EPSILON) &&
			        (segmentParameter <= 1.0 + DOMAIN_GEOMETRY_EPSILON) &&
			        (edgeParameterValue >= -DOMAIN_GEOMETRY_EPSILON) &&
			        (edgeParameterValue <= 1.0 + DOMAIN_GEOMETRY_EPSILON)) {
				appendSplit(parameters, segmentParameter);
			}
		} else if (fabs(domainCross(offsetX, offsetY,
		                           segmentX, segmentY)) <=
		        DOMAIN_POINT_EPSILON *
		        (fabs(segmentX) + fabs(segmentY) + 1.0)) {
			TerrainDomainRawEdge segmentEdge;
			segmentEdge.start = segment.points[0];
			segmentEdge.end = segment.points[1];
			appendSplit(parameters, edgeParameter(
			        segmentEdge, edgeStart.x, edgeStart.y));
			appendSplit(parameters, edgeParameter(
			        segmentEdge, edgeEnd.x, edgeEnd.y));
		}
	}
}


void
ClipTerrainDomainSegment(
		const TerrainDomain &domain, const TerrainDomainSegment &segment,
		std::vector<TerrainDomainSegment> *clippedSegments)
{
	std::vector<double> parameters;
	size_t holeIndex;
	size_t parameterIndex;
	if ((clippedSegments == NULL) ||
	        (domainDistanceSquared(segment.points[0], segment.points[1]) <=
	         DOMAIN_GEOMETRY_EPSILON * DOMAIN_GEOMETRY_EPSILON)) {
		return;
	}
	parameters.push_back(0.0);
	parameters.push_back(1.0);
	appendRingIntersections(domain.outer, segment, &parameters);
	for (holeIndex = 0; holeIndex < domain.holes.size(); holeIndex++) {
		appendRingIntersections(domain.holes[holeIndex], segment, &parameters);
	}
	sortUniqueSplits(&parameters);
	for (parameterIndex = 0; parameterIndex + 1 < parameters.size();
	        parameterIndex++) {
		double startParameter = parameters[parameterIndex];
		double endParameter = parameters[parameterIndex + 1];
		double middleParameter = (startParameter + endParameter) / 2.0;
		TerrainDomainPoint middle = interpolateDomainPoint(
		        segment.points[0], segment.points[1], middleParameter);
		if ((endParameter - startParameter > DOMAIN_GEOMETRY_EPSILON) &&
		        TerrainDomainCoversPoint(domain, middle.x, middle.y)) {
			TerrainDomainSegment clipped;
			clipped.points[0] = interpolateDomainPoint(
			        segment.points[0], segment.points[1], startParameter);
			clipped.points[1] = interpolateDomainPoint(
			        segment.points[0], segment.points[1], endParameter);
			clippedSegments->push_back(clipped);
		}
	}
}


bool
TerrainDomainContainsSegment(
		const TerrainDomain &domain, const TerrainDomainSegment &segment)
{
	std::vector<TerrainDomainSegment> clipped;
	double deltaX = segment.points[1].x - segment.points[0].x;
	double deltaY = segment.points[1].y - segment.points[0].y;
	double segmentLength = sqrt(deltaX * deltaX + deltaY * deltaY);
	double clippedLength = 0.0;
	size_t segmentIndex;
	if (segmentLength <= DOMAIN_BOUNDARY_EPSILON) {
		return TerrainDomainCoversPoint(
		        domain, segment.points[0].x, segment.points[0].y);
	}
	ClipTerrainDomainSegment(domain, segment, &clipped);
	for (segmentIndex = 0; segmentIndex < clipped.size(); segmentIndex++) {
		double clippedX = clipped[segmentIndex].points[1].x -
		        clipped[segmentIndex].points[0].x;
		double clippedY = clipped[segmentIndex].points[1].y -
		        clipped[segmentIndex].points[0].y;
		clippedLength += sqrt(clippedX * clippedX + clippedY * clippedY);
	}
	return clippedLength >= segmentLength -
	        std::max(DOMAIN_BOUNDARY_EPSILON, segmentLength * 1e-10);
}


static bool
pointInTriangle(const TerrainDomainInputTriangle &input,
	            double x, double y)
{
	const TerrainDomainPoint &first = input.triangle.points[0];
	const TerrainDomainPoint &second = input.triangle.points[1];
	const TerrainDomainPoint &third = input.triangle.points[2];
	double firstCross;
	double secondCross;
	double thirdCross;
	if ((x < input.minimumX - DOMAIN_GEOMETRY_EPSILON) ||
	        (x > input.maximumX + DOMAIN_GEOMETRY_EPSILON) ||
	        (y < input.minimumY - DOMAIN_GEOMETRY_EPSILON) ||
	        (y > input.maximumY + DOMAIN_GEOMETRY_EPSILON)) {
		return false;
	}
	firstCross = domainCross(second.x - first.x, second.y - first.y,
	                         x - first.x, y - first.y);
	secondCross = domainCross(third.x - second.x, third.y - second.y,
	                          x - second.x, y - second.y);
	thirdCross = domainCross(first.x - third.x, first.y - third.y,
	                         x - third.x, y - third.y);
	return ((firstCross >= -DOMAIN_FACE_AREA_EPSILON) &&
	        (secondCross >= -DOMAIN_FACE_AREA_EPSILON) &&
	        (thirdCross >= -DOMAIN_FACE_AREA_EPSILON)) ||
	       ((firstCross <= DOMAIN_FACE_AREA_EPSILON) &&
	        (secondCross <= DOMAIN_FACE_AREA_EPSILON) &&
	        (thirdCross <= DOMAIN_FACE_AREA_EPSILON));
}


static bool
pointInOccupiedTriangles(
		const std::vector<TerrainDomainInputTriangle> &triangles,
		double x, double y)
{
	size_t triangleIndex;
	for (triangleIndex = 0; triangleIndex < triangles.size(); triangleIndex++) {
		if (pointInTriangle(triangles[triangleIndex], x, y)) {
			return true;
		}
	}
	return false;
}


static bool
pointInOccupiedGroup(
		const std::vector<TerrainDomainInputTriangle> &triangles,
		int groupIndex, double x, double y)
{
	size_t triangleIndex;
	for (triangleIndex = 0; triangleIndex < triangles.size(); triangleIndex++) {
		if ((triangles[triangleIndex].groupIndex == groupIndex) &&
		        pointInTriangle(triangles[triangleIndex], x, y)) {
			return true;
		}
	}
	return false;
}


static void
appendSplit(std::vector<double> *splits, double parameter)
{
	if (parameter < 0.0) {
		parameter = 0.0;
	} else if (parameter > 1.0) {
		parameter = 1.0;
	}
	splits->push_back(parameter);
}


static double
edgeParameter(const TerrainDomainRawEdge &edge, double x, double y)
{
	double deltaX = edge.end.x - edge.start.x;
	double deltaY = edge.end.y - edge.start.y;
	if (fabs(deltaX) >= fabs(deltaY)) {
		return fabs(deltaX) <= DOMAIN_GEOMETRY_EPSILON
		        ? 0.0 : (x - edge.start.x) / deltaX;
	}
	return fabs(deltaY) <= DOMAIN_GEOMETRY_EPSILON
	        ? 0.0 : (y - edge.start.y) / deltaY;
}


static void
splitIntersectingEdges(TerrainDomainRawEdge *first,
	                  TerrainDomainRawEdge *second)
{
	double firstX = first->end.x - first->start.x;
	double firstY = first->end.y - first->start.y;
	double secondX = second->end.x - second->start.x;
	double secondY = second->end.y - second->start.y;
	double startX = second->start.x - first->start.x;
	double startY = second->start.y - first->start.y;
	double denominator = domainCross(firstX, firstY, secondX, secondY);
	if ((first->maximumX < second->minimumX - DOMAIN_POINT_EPSILON) ||
	        (second->maximumX < first->minimumX - DOMAIN_POINT_EPSILON) ||
	        (first->maximumY < second->minimumY - DOMAIN_POINT_EPSILON) ||
	        (second->maximumY < first->minimumY - DOMAIN_POINT_EPSILON)) {
		return;
	}
	if (fabs(denominator) > DOMAIN_GEOMETRY_EPSILON) {
		double firstParameter = domainCross(startX, startY,
		                                   secondX, secondY) / denominator;
		double secondParameter = domainCross(startX, startY,
		                                    firstX, firstY) / denominator;
		if ((firstParameter >= -DOMAIN_GEOMETRY_EPSILON) &&
		        (firstParameter <= 1.0 + DOMAIN_GEOMETRY_EPSILON) &&
		        (secondParameter >= -DOMAIN_GEOMETRY_EPSILON) &&
		        (secondParameter <= 1.0 + DOMAIN_GEOMETRY_EPSILON)) {
			appendSplit(&first->splits, firstParameter);
			appendSplit(&second->splits, secondParameter);
		}
		return;
	}
	if (fabs(domainCross(startX, startY, firstX, firstY)) >
	        DOMAIN_POINT_EPSILON *
	        (fabs(firstX) + fabs(firstY) + 1.0)) {
		return;
	}
	appendSplit(&first->splits,
	            edgeParameter(*first, second->start.x, second->start.y));
	appendSplit(&first->splits,
	            edgeParameter(*first, second->end.x, second->end.y));
	appendSplit(&second->splits,
	            edgeParameter(*second, first->start.x, first->start.y));
	appendSplit(&second->splits,
	            edgeParameter(*second, first->end.x, first->end.y));
}


static bool
splitLess(double first, double second)
{
	return first < second;
}


static void
sortUniqueSplits(std::vector<double> *splits)
{
	std::vector<double> unique;
	size_t splitIndex;
	std::sort(splits->begin(), splits->end(), splitLess);
	for (splitIndex = 0; splitIndex < splits->size(); splitIndex++) {
		if (unique.empty() ||
		        (fabs(unique.back() - (*splits)[splitIndex]) >
		         DOMAIN_GEOMETRY_EPSILON)) {
			unique.push_back((*splits)[splitIndex]);
		}
	}
	*splits = unique;
}


static void
mergeDomainPoint(TerrainDomainPoint *target,
	            const TerrainDomainPoint &candidate)
{
	if (candidate.spacing < target->spacing) {
		target->spacing = candidate.spacing;
	}
	if (candidate.marker > target->marker) {
		target->x = candidate.x;
		target->y = candidate.y;
		target->marker = candidate.marker;
	}
	/* At a portal corner the upper seam safely hides the lower coincident seam. */
	if (candidate.z > target->z + DOMAIN_GEOMETRY_EPSILON) {
		target->z = candidate.z;
	}
}


static int
findOrAppendNode(std::vector<TerrainDomainPoint> *nodes,
	            const TerrainDomainPoint &point)
{
	size_t nodeIndex;
	for (nodeIndex = 0; nodeIndex < nodes->size(); nodeIndex++) {
		if (domainDistanceSquared((*nodes)[nodeIndex], point) <=
		        DOMAIN_POINT_EPSILON * DOMAIN_POINT_EPSILON) {
			mergeDomainPoint(&(*nodes)[nodeIndex], point);
			return (int)nodeIndex;
		}
	}
	nodes->push_back(point);
	return (int)nodes->size() - 1;
}


static bool
edgeAlreadyPresent(const std::vector<TerrainDomainEdge> &edges,
	               int startNode, int endNode)
{
	size_t edgeIndex;
	for (edgeIndex = 0; edgeIndex + 1 < edges.size(); edgeIndex += 2) {
		if (((edges[edgeIndex].startNode == startNode) &&
		     (edges[edgeIndex].endNode == endNode)) ||
		        ((edges[edgeIndex].startNode == endNode) &&
		         (edges[edgeIndex].endNode == startNode))) {
			return true;
		}
	}
	return false;
}


static bool
outgoingEdgeOrder(const TerrainDomainOutgoingEdge &first,
	             const TerrainDomainOutgoingEdge &second)
{
	if (first.angle != second.angle) {
		return first.angle < second.angle;
	}
	if (first.lengthSquared != second.lengthSquared) {
		return first.lengthSquared < second.lengthSquared;
	}
	return first.edgeIndex < second.edgeIndex;
}


static int
chooseNextEdge(const std::vector<TerrainDomainPoint> &nodes,
	          const std::vector<TerrainDomainEdge> &edges,
	          int currentEdge)
{
	int currentNode = edges[currentEdge].endNode;
	int twinEdge = (currentEdge % 2) == 0 ? currentEdge + 1 : currentEdge - 1;
	std::vector<TerrainDomainOutgoingEdge> outgoing;
	size_t edgeIndex;
	for (edgeIndex = 0; edgeIndex < edges.size(); edgeIndex++) {
		if (edges[edgeIndex].startNode != currentNode) {
			continue;
		}
		TerrainDomainOutgoingEdge candidate;
		double deltaX = nodes[edges[edgeIndex].endNode].x -
		        nodes[currentNode].x;
		double deltaY = nodes[edges[edgeIndex].endNode].y -
		        nodes[currentNode].y;
		candidate.edgeIndex = (int)edgeIndex;
		candidate.angle = atan2(deltaY, deltaX);
		candidate.lengthSquared = deltaX * deltaX + deltaY * deltaY;
		outgoing.push_back(candidate);
	}
	if (outgoing.empty()) {
		return twinEdge;
	}
	std::sort(outgoing.begin(), outgoing.end(), outgoingEdgeOrder);
	for (edgeIndex = 0; edgeIndex < outgoing.size(); edgeIndex++) {
		if (outgoing[edgeIndex].edgeIndex == twinEdge) {
			return outgoing[(edgeIndex + outgoing.size() - 1) %
			        outgoing.size()].edgeIndex;
		}
	}
	return twinEdge;
}


static bool
traceBoundaryLoop(const std::vector<TerrainDomainPoint> &nodes,
	              std::vector<TerrainDomainEdge> *edges, int firstEdge,
	              TerrainDomainRing *ring)
{
	int currentEdge = firstEdge;
	int firstNode = (*edges)[firstEdge].startNode;
	int currentNode;
	size_t guard = 0;
	ring->points.push_back(nodes[firstNode]);
	while (guard <= edges->size()) {
		TerrainDomainEdge &edge = (*edges)[currentEdge];
		if (edge.used && (currentEdge != firstEdge)) {
			return false;
		}
		if (edge.used && (currentEdge == firstEdge)) {
			return ring->points.size() >= 3;
		}
		edge.used = true;
		currentNode = edge.endNode;
		currentEdge = chooseNextEdge(nodes, *edges, currentEdge);
		if (currentEdge == firstEdge) {
			return (currentNode == firstNode) && (ring->points.size() >= 3);
		}
		ring->points.push_back(nodes[currentNode]);
		guard++;
	}
	return false;
}


static TerrainDomainPoint
getRingInteriorPoint(const TerrainDomainLoop &loop)
{
	TerrainDomainPoint result = loop.ring.points[0];
	size_t pointIndex;
	for (pointIndex = 0; pointIndex < loop.ring.points.size(); pointIndex++) {
		const TerrainDomainPoint &first = loop.ring.points[pointIndex];
		const TerrainDomainPoint &second =
		        loop.ring.points[(pointIndex + 1) % loop.ring.points.size()];
		double deltaX = second.x - first.x;
		double deltaY = second.y - first.y;
		double length = sqrt(deltaX * deltaX + deltaY * deltaY);
		double direction = loop.area > 0.0 ? 1.0 : -1.0;
		double probe;
		int attempt;
		if (length <= DOMAIN_POINT_EPSILON) {
			continue;
		}
		probe = DOMAIN_POINT_EPSILON * 4.0;
		for (attempt = 0; attempt < 5; attempt++) {
			result.x = (first.x + second.x) / 2.0 -
			        direction * deltaY / length * probe;
			result.y = (first.y + second.y) / 2.0 +
			        direction * deltaX / length * probe;
			if (pointInRing(loop.ring, result.x, result.y)) {
				return result;
			}
			probe *= 4.0;
		}
	}
	return result;
}


static void
reverseRing(TerrainDomainRing *ring)
{
	std::reverse(ring->points.begin(), ring->points.end());
}


static bool
ringOrder(const TerrainDomainRing &first, const TerrainDomainRing &second)
{
	double firstMinimumX = DBL_MAX;
	double firstMinimumY = DBL_MAX;
	double secondMinimumX = DBL_MAX;
	double secondMinimumY = DBL_MAX;
	size_t index;
	for (index = 0; index < first.points.size(); index++) {
		firstMinimumX = std::min(firstMinimumX, first.points[index].x);
		firstMinimumY = std::min(firstMinimumY, first.points[index].y);
	}
	for (index = 0; index < second.points.size(); index++) {
		secondMinimumX = std::min(secondMinimumX, second.points[index].x);
		secondMinimumY = std::min(secondMinimumY, second.points[index].y);
	}
	if (firstMinimumX != secondMinimumX) {
		return firstMinimumX < secondMinimumX;
	}
	if (firstMinimumY != secondMinimumY) {
		return firstMinimumY < secondMinimumY;
	}
	return first.points.size() < second.points.size();
}


static bool
domainOrder(const TerrainDomain &first, const TerrainDomain &second)
{
	if (first.exterior != second.exterior) {
		return first.exterior;
	}
	return ringOrder(first.outer, second.outer);
}


static void
appendBoundaryEdges(const std::vector<TerrainDomainSegment> &boundaries,
	               int groupIndex, bool preserve,
	               std::vector<TerrainDomainRawEdge> *edges)
{
	size_t boundaryIndex;
	for (boundaryIndex = 0; boundaryIndex < boundaries.size();
	        boundaryIndex++) {
		TerrainDomainRawEdge edge;
		edge.start = boundaries[boundaryIndex].points[0];
		edge.end = boundaries[boundaryIndex].points[1];
		if (domainDistanceSquared(edge.start, edge.end) <=
		        DOMAIN_GEOMETRY_EPSILON * DOMAIN_GEOMETRY_EPSILON) {
			continue;
		}
		edge.splits.push_back(0.0);
		edge.splits.push_back(1.0);
		edge.minimumX = std::min(edge.start.x, edge.end.x);
		edge.minimumY = std::min(edge.start.y, edge.end.y);
		edge.maximumX = std::max(edge.start.x, edge.end.x);
		edge.maximumY = std::max(edge.start.y, edge.end.y);
		edge.groupIndex = groupIndex;
		edge.preserve = preserve;
		edges->push_back(edge);
	}
}


static void
appendRingEdges(const TerrainDomainRing &ring,
	           std::vector<TerrainDomainRawEdge> *edges)
{
	size_t pointIndex;
	for (pointIndex = 0; pointIndex < ring.points.size(); pointIndex++) {
		TerrainDomainRawEdge edge;
		edge.start = ring.points[pointIndex];
		edge.end = ring.points[(pointIndex + 1) % ring.points.size()];
		if (domainDistanceSquared(edge.start, edge.end) <=
		        DOMAIN_GEOMETRY_EPSILON * DOMAIN_GEOMETRY_EPSILON) {
			continue;
		}
		edge.splits.push_back(0.0);
		edge.splits.push_back(1.0);
		edge.minimumX = std::min(edge.start.x, edge.end.x);
		edge.minimumY = std::min(edge.start.y, edge.end.y);
		edge.maximumX = std::max(edge.start.x, edge.end.x);
		edge.maximumY = std::max(edge.start.y, edge.end.y);
		edge.groupIndex = -1;
		edge.preserve = true;
		edges->push_back(edge);
	}
}


static TerrainDomainPoint
getEdgeLeftFacePoint(const TerrainDomainPoint &start,
	                const TerrainDomainPoint &end, double maximumProbe)
{
	TerrainDomainPoint result = start;
	double deltaX = end.x - start.x;
	double deltaY = end.y - start.y;
	double length = sqrt(deltaX * deltaX + deltaY * deltaY);
	double probe = std::max(DOMAIN_GEOMETRY_EPSILON * 16.0,
	        std::min(maximumProbe, length * 0.0001));
	if (length > DOMAIN_GEOMETRY_EPSILON) {
		result.x = (start.x + end.x) / 2.0 - deltaY / length * probe;
		result.y = (start.y + end.y) / 2.0 + deltaX / length * probe;
	}
	return result;
}


static bool
edgeSeparatesOccupiedSpace(
		const TerrainDomainPoint &start, const TerrainDomainPoint &end,
		const std::vector<TerrainDomainInputTriangle> &triangles,
		int groupIndex)
{
	TerrainDomainPoint left = getEdgeLeftFacePoint(
	        start, end, DOMAIN_POINT_EPSILON * 0.01);
	TerrainDomainPoint right = getEdgeLeftFacePoint(
	        end, start, DOMAIN_POINT_EPSILON * 0.01);
	return pointInOccupiedGroup(triangles, groupIndex, left.x, left.y) !=
	       pointInOccupiedGroup(triangles, groupIndex, right.x, right.y);
}


static bool
ringHasFreeLeftFace(
		const TerrainDomainRing &ring, const TerrainDomainRing &border,
		const std::vector<TerrainDomainInputTriangle> &triangles)
{
	size_t blockedEdgeCount = 0;
	size_t freeEdgeCount = 0;
	size_t pointIndex;
	for (pointIndex = 0; pointIndex < ring.points.size(); pointIndex++) {
		TerrainDomainPoint facePoint = getEdgeLeftFacePoint(
		        ring.points[pointIndex],
		        ring.points[(pointIndex + 1) % ring.points.size()],
		        DOMAIN_POINT_EPSILON * 0.01);
		bool insideBorder = pointInRing(border, facePoint.x, facePoint.y);
		bool occupied = pointInOccupiedTriangles(
		        triangles, facePoint.x, facePoint.y);
		if (!insideBorder) {
			return false;
		}
		if (insideBorder && occupied) {
			TerrainDomainPoint fartherPoint = getEdgeLeftFacePoint(
			        ring.points[pointIndex],
			        ring.points[(pointIndex + 1) % ring.points.size()],
			        DOMAIN_POINT_EPSILON);
			if (pointInRing(border, fartherPoint.x, fartherPoint.y) &&
			        !pointInOccupiedTriangles(
			                triangles, fartherPoint.x, fartherPoint.y)) {
				occupied = false;
			}
		}
		if (occupied) {
			blockedEdgeCount++;
		} else {
			freeEdgeCount++;
		}
	}
	/* A single quantized seam must not reject an otherwise free long face. */
	return (freeEdgeCount > 0) &&
	       (freeEdgeCount > blockedEdgeCount * 100);
}


static bool
prepareInputTriangle(const TerrainDomainTriangle &source,
	                int groupIndex, TerrainDomainInputTriangle *triangle)
{
	double area = domainCross(
	        source.points[1].x - source.points[0].x,
	        source.points[1].y - source.points[0].y,
	        source.points[2].x - source.points[0].x,
	        source.points[2].y - source.points[0].y);
	triangle->triangle = source;
	triangle->minimumX = std::min(source.points[0].x,
	        std::min(source.points[1].x, source.points[2].x));
	triangle->minimumY = std::min(source.points[0].y,
	        std::min(source.points[1].y, source.points[2].y));
	triangle->maximumX = std::max(source.points[0].x,
	        std::max(source.points[1].x, source.points[2].x));
	triangle->maximumY = std::max(source.points[0].y,
	        std::max(source.points[1].y, source.points[2].y));
	triangle->groupIndex = groupIndex;
	return fabs(area) > DOMAIN_GEOMETRY_EPSILON;
}


int
BuildTerrainDomains(
		const std::vector<TerrainDomainBoundaryGroup> &occupiedGroups,
		const TerrainDomainRing &sourceBorder,
		std::vector<TerrainDomain> *domains,
		char *errorMessage, size_t errorMessageSize)
{
	std::vector<TerrainDomainInputTriangle> triangles;
	std::vector<TerrainDomainRawEdge> rawEdges;
	std::vector<TerrainDomainPoint> nodes;
	std::vector<TerrainDomainEdge> edges;
	std::vector<TerrainDomainLoop> loops;
	TerrainDomainRing border = sourceBorder;
	bool hasBoundaries = false;
	bool hasTriangles = false;
	size_t firstIndex;
	size_t secondIndex;

	if ((domains == NULL) || occupiedGroups.empty() ||
	        (border.points.size() < 3)) {
		setDomainError(errorMessage, errorMessageSize,
		               "Terrain domain discovery requires occupied triangles and a border");
		return -1;
	}
	if ((errorMessage != NULL) && (errorMessageSize > 0)) {
		errorMessage[0] = '\0';
	}
	domains->clear();
	if (signedRingArea(border) < 0.0) {
		reverseRing(&border);
	}
	if (fabs(signedRingArea(border)) <= DOMAIN_MINIMUM_AREA) {
		setDomainError(errorMessage, errorMessageSize,
		               "Terrain domain border has zero area");
		return -1;
	}
	for (firstIndex = 0; firstIndex < occupiedGroups.size(); firstIndex++) {
		const TerrainDomainBoundaryGroup &group = occupiedGroups[firstIndex];
		hasBoundaries = hasBoundaries || !group.boundaries.empty();
		hasTriangles = hasTriangles || !group.triangles.empty();
		for (secondIndex = 0; secondIndex < group.triangles.size();
		        secondIndex++) {
			TerrainDomainInputTriangle triangle;
			if (prepareInputTriangle(group.triangles[secondIndex],
			        (int)firstIndex, &triangle)) {
				triangles.push_back(triangle);
			}
		}
		appendBoundaryEdges(group.boundaries, (int)firstIndex,
		                    group.preserveBoundaries, &rawEdges);
	}
	appendRingEdges(border, &rawEdges);
	if (!hasTriangles || !hasBoundaries || triangles.empty() ||
	        rawEdges.empty()) {
		setDomainError(errorMessage, errorMessageSize,
		               "Terrain domain occupied geometry has no planar area");
		return -1;
	}
	for (firstIndex = 0; firstIndex < rawEdges.size(); firstIndex++) {
		for (secondIndex = firstIndex + 1; secondIndex < rawEdges.size();
		        secondIndex++) {
			splitIntersectingEdges(&rawEdges[firstIndex],
			                       &rawEdges[secondIndex]);
		}
	}
	for (firstIndex = 0; firstIndex < rawEdges.size(); firstIndex++) {
		TerrainDomainRawEdge &rawEdge = rawEdges[firstIndex];
		sortUniqueSplits(&rawEdge.splits);
		for (secondIndex = 0; secondIndex + 1 < rawEdge.splits.size();
		        secondIndex++) {
			TerrainDomainPoint start = interpolateDomainPoint(
			        rawEdge.start, rawEdge.end, rawEdge.splits[secondIndex]);
			TerrainDomainPoint end = interpolateDomainPoint(
			        rawEdge.start, rawEdge.end, rawEdge.splits[secondIndex + 1]);
			int startNode;
			int endNode;
			TerrainDomainEdge forward;
			TerrainDomainEdge reverse;
			if (!rawEdge.preserve && !edgeSeparatesOccupiedSpace(
			        start, end, triangles, rawEdge.groupIndex)) {
				continue;
			}
			startNode = findOrAppendNode(&nodes, start);
			endNode = findOrAppendNode(&nodes, end);
			if ((startNode == endNode) ||
			        edgeAlreadyPresent(edges, startNode, endNode)) {
				continue;
			}
			forward.startNode = startNode;
			forward.endNode = endNode;
			forward.used = false;
			reverse.startNode = endNode;
			reverse.endNode = startNode;
			reverse.used = false;
			edges.push_back(forward);
			edges.push_back(reverse);
		}
	}
	if (edges.empty()) {
		setDomainError(errorMessage, errorMessageSize,
		               "Terrain domain discovery found no occupied boundary");
		return -1;
	}
	for (firstIndex = 0; firstIndex < edges.size(); firstIndex++) {
		TerrainDomainLoop loop;
		if (edges[firstIndex].used) {
			continue;
		}
		if (!traceBoundaryLoop(nodes, &edges, (int)firstIndex,
		                           &loop.ring)) {
			setDomainError(errorMessage, errorMessageSize,
			               "Terrain domain boundary graph contains an open chain");
			return -1;
		}
		loop.area = signedRingArea(loop.ring);
		if ((fabs(loop.area) > DOMAIN_MINIMUM_AREA) &&
		        ringHasFreeLeftFace(loop.ring, border, triangles)) {
			loops.push_back(loop);
		}
	}

	bool foundExterior = false;
	double borderArea = fabs(signedRingArea(border));
	for (firstIndex = 0; firstIndex < loops.size(); firstIndex++) {
		if (loops[firstIndex].area > 0.0) {
			TerrainDomain domain;
			domain.outer = loops[firstIndex].ring;
			domain.exterior = fabs(loops[firstIndex].area - borderArea) <=
			        std::max(1e-4, borderArea * 1e-9);
			foundExterior = foundExterior || domain.exterior;
			domains->push_back(domain);
		}
	}
	if (!foundExterior) {
		setDomainError(errorMessage, errorMessageSize,
		               "Terrain domain discovery lost the exterior border");
		return -1;
	}
	for (firstIndex = 0; firstIndex < loops.size(); firstIndex++) {
		TerrainDomainPoint representative;
		double smallestArea = DBL_MAX;
		int containingDomain = -1;
		if (loops[firstIndex].area >= 0.0) {
			continue;
		}
		representative = getRingInteriorPoint(loops[firstIndex]);
		for (secondIndex = 0; secondIndex < domains->size(); secondIndex++) {
			double area = fabs(signedRingArea((*domains)[secondIndex].outer));
			if ((area < smallestArea) && pointInRing(
			        (*domains)[secondIndex].outer,
			        representative.x, representative.y)) {
				smallestArea = area;
				containingDomain = (int)secondIndex;
			}
		}
		if (containingDomain < 0) {
			setDomainError(errorMessage, errorMessageSize,
			               "Terrain occupied boundary lies outside the terrain border");
			return -1;
		}
		(*domains)[containingDomain].holes.push_back(loops[firstIndex].ring);
	}
	for (firstIndex = 0; firstIndex < domains->size(); firstIndex++) {
		std::sort((*domains)[firstIndex].holes.begin(),
		          (*domains)[firstIndex].holes.end(), ringOrder);
	}
	std::sort(domains->begin(), domains->end(), domainOrder);
	if ((errorMessage != NULL) && (errorMessageSize > 0)) {
		errorMessage[0] = '\0';
	}
	return 0;
}
