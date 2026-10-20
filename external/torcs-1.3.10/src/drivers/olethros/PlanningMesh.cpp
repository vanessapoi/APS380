/***************************************************************************

	file                 : PlanningMesh.cpp
	created              : September 2026
	copyright            : (C) 2006-2026 by Christos Dimitrakakis, Bernhard Wymann
	email                : dimitrak@idiap.ch, berniw@bluewin.ch

 ***************************************************************************/

/***************************************************************************
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 ***************************************************************************/

/** @file PlanningMesh.cpp
 * @brief Regular track sampling, optimization, mapping and runtime path queries.
 * @ingroup olethros_planning
 */

#include "PlanningMesh.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <stdexcept>

PlanningPoint PlanningPoint::operator+(PlanningPoint p) const { return { x + p.x, y + p.y }; }
PlanningPoint PlanningPoint::operator-(PlanningPoint p) const { return { x - p.x, y - p.y }; }
PlanningPoint PlanningPoint::operator*(double a) const { return { x * a, y * a }; }
double PlanningPoint::cross(PlanningPoint p) const { return x * p.y - y * p.x; }
double PlanningPoint::length() const { return std::hypot(x, y); }
PlanningPoint PlanningSection::point(double w) const { return right + (left - right) * w; }

double
PlanningMesh::wrap(double s) const
{
	s = fmod(s, length);
	return s < 0 ? s + length : s;
}

size_t
PlanningMesh::nativeIndex(double s) const
{
	return std::upper_bound(starts.begin(), starts.end(), wrap(s)) - starts.begin() - 1;
}

const tTrackSeg& PlanningMesh::source(double s) const { return *segments[nativeIndex(s)]; }
double PlanningMesh::station(const tTrackSeg& seg, double local) const { return startsById[seg.id] + local; }
double PlanningMesh::nativeStart(int i) const { return starts[i]; }
const tTrackSeg& PlanningMesh::nativeSegment(int i) const { return *segments[i]; }

size_t
PlanningMesh::interval(double s, double& fraction) const
{
	double coordinate = wrap(s) / spacing;
	size_t i = (std::min)((size_t)coordinate, sections.size() - 1);
	fraction = coordinate - i;
	return i;
}

double
PlanningMesh::weight(double s) const
{
	double f;
	size_t i = interval(s, f), j = (i + 1) % sections.size();
	return (1 - f) * trajectory.weights[i] + f * trajectory.weights[j];
}

PlanningPoint
PlanningMesh::position(double s) const
{
	// Follow the actual road at s rather than rotating a held entry weight.
	return at(s).point(weight(s));
}

double
PlanningMesh::pathCurvature(double s) const
{
	double f;
	size_t i = interval(s, f), j = (i + 1) % sections.size();
	return (1 - f) * curvature[i] + f * curvature[j];
}

double PlanningMesh::pathRadius(double s) const { return 1.0 / pathCurvature(s); }

PlanningPoint
PlanningMesh::target(double s, double offset, bool inLane, bool inPit) const
{
	PlanningSection road = at(s);
	PlanningPoint across = road.left - road.right;
	double width = across.length();
	double w = inLane ? 0.5 : weight(s);
	double adjustment = tanh(fabs(offset)) * ((0.5 - w) * width + offset);
	// The pit spline is a displacement from the lane centerline.
	if (inPit) adjustment = offset;
	return road.point(w) + across * (adjustment / width);
}

double
PlanningMesh::elevation(double s) const
{
	size_t i = nativeIndex(s);
	const tTrackSeg& seg = *segments[i];
	double f = (wrap(s) - starts[i]) / seg.length;
	double start = 0.5 * ((double)seg.vertex[TR_SL].z + seg.vertex[TR_SR].z);
	double end = 0.5 * ((double)seg.vertex[TR_EL].z + seg.vertex[TR_ER].z);
	return (1 - f) * start + f * end;
}

double
PlanningMesh::grade(double s) const
{
	return atan2(elevation(s + 0.5 * spacing) - elevation(s - 0.5 * spacing), spacing);
}

double
PlanningMesh::gradeDerivative(double s) const
{
	// Differentiate the vertical unit-slope component, not the grade angle.
	return (sin(grade(s + spacing)) - sin(grade(s - spacing))) / (2 * spacing);
}

double
PlanningMesh::nextStation(double s) const
{
	double local = wrap(s), base = s - local;
	std::vector<double>::const_iterator next = std::upper_bound(stations.begin(), stations.end(), local);
	double result = next == stations.end() ? base + length : base + *next;
	// Choose the entering side and avoid rounding back onto the same boundary.
	return std::nextafter(result, std::numeric_limits<double>::infinity());
}

PlanningSection
PlanningMesh::evaluate(const tTrackSeg& seg, double distance)
{
	double heading = seg.angle[TR_ZS];
	double parameter = distance;
	PlanningPoint right = { seg.vertex[TR_SR].x, seg.vertex[TR_SR].y };
	if (seg.type == TR_STR) {
		right = right + PlanningPoint{ cos(heading), sin(heading) }*distance;
	}
	else {
		double sign = seg.type == TR_LFT ? 1.0 : -1.0;
		parameter = distance / seg.radius;
		double turn = sign * parameter;
		// sin(b)-sin(a), cos(a)-cos(b), without a huge center subtraction.
		double chord = 2.0 * sign * seg.radiusr * sin(0.5 * turn);
		right = right + PlanningPoint{ cos(heading + 0.5 * turn), sin(heading + 0.5 * turn) }*chord;
		heading += turn;
	}
	double width = fabs((double)seg.startWidth + parameter * seg.Kyl);
	return { right, right + PlanningPoint{-sin(heading), cos(heading)}*width };
}

PlanningSection
PlanningMesh::nativeSection(const tTrackSeg& seg)
{
	return { {seg.vertex[TR_SR].x, seg.vertex[TR_SR].y},
		{seg.vertex[TR_SL].x, seg.vertex[TR_SL].y} };
}

PlanningSection
PlanningMesh::at(double s) const
{
	s = wrap(s);
	size_t i = nativeIndex(s);
	return evaluate(*segments[i], s - starts[i]);
}

PlanningMesh::PlanningMesh(const tTrack& track, double nominal)
{
	diagnosticsEnabled = getenv("OLETHROS_DIAGNOSTICS") != NULL;
	if (track.nseg <= 0 || !track.seg)
		throw std::runtime_error("Planning mesh needs a native track");
	const tTrackSeg* first = track.seg;
	for (int i = 0; i < track.nseg && first; ++i, first = first->next) {
		if (first->lgfromstart == 0.0f) break;
	}
	if (!first || first->lgfromstart != 0.0f)
		throw std::runtime_error("Planning mesh needs a zero-station start segment");
	length = 0;
	startsById.resize(track.nseg);
	const tTrackSeg* seg = first;
	for (int i = 0; i < track.nseg; ++i, seg = seg->next) {
		if (!seg || !(seg->length > 0) || !std::isfinite(seg->length))
			throw std::runtime_error("Invalid native planning interval");
		starts.push_back(length);
		if (seg->id < 0 || seg->id >= track.nseg)
			throw std::runtime_error("Invalid native planning ID");
		startsById[seg->id] = length;
		segments.push_back(seg);
		length += seg->length;
	}
	if (!(length > 0 && nominal > 0) || !std::isfinite(length) || !std::isfinite(nominal))
		throw std::runtime_error("Invalid planning mesh length");
	double requestedCount = ceil(length / nominal);
	// Periodic index expressions also add two indices before taking modulo.
	if (!(requestedCount >= 5 && requestedCount <= (std::numeric_limits<int>::max)() / 2)
		|| requestedCount > sections.max_size())
		throw std::runtime_error("Planning mesh point count is out of range");
	int count = (int)requestedCount;
	spacing = length / count;
	for (int i = 0; i < count; ++i) sections.push_back(at(i * spacing));
	stations = starts;
	for (int i = 0; i < count; ++i) stations.push_back(i * spacing);
	std::sort(stations.begin(), stations.end());
	stations.erase(std::unique(stations.begin(), stations.end()), stations.end());
	if (diagnosticsEnabled)
		fprintf(stderr, "OlethrosRegular mesh count=%d length=%.17g nominal=%.17g spacing=%.17g\n", count, length, nominal, spacing);
}

void
PlanningMesh::optimise(double edgeMargin)
{
	std::vector<TrajectorySection> mesh;
	for (const PlanningSection& section : sections) {
		mesh.push_back({ {section.left.x, section.left.y}, {section.right.x, section.right.y} });
	}
	int n = (int)sections.size();
	int stride = (int)(std::min)((double)n, ceil(10.0 / spacing));
	stride = (std::max)(1, stride);
	int count = (std::max)(5, (n + stride - 1) / stride);
	std::vector<TrajectorySection> coarse;
	std::vector<int> anchors;
	// Balanced integer strides keep the coarse wrap interval comparable.
	for (int i = 0; i < count; ++i) {
		int anchor = (int)((long long)i * n / count);
		anchors.push_back(anchor);
		coarse.push_back(mesh[anchor]);
	}
	Trajectory seed;
	seed.optimise(coarse, 500, edgeMargin);
	trajectory.weights.resize(n);
	for (int i = 0; i < count; ++i) {
		int a = anchors[i], b = i + 1 < count ? anchors[i + 1] : n;
		for (int j = a; j < b; ++j) {
			double fraction = (double)(j - a) / (b - a);
			trajectory.weights[j] = (1 - fraction) * seed.weights[i] + fraction * seed.weights[(i + 1) % count];
		}
	}
	trajectory.optimise(mesh, 1000, edgeMargin, false);
	if (diagnosticsEnabled) {
		fprintf(stderr, "OlethrosOptimization pass=coarse steps=%zu initial=%.17g final=%.17g stop=%s\n",
			seed.costHistory.size()-1, seed.costHistory.front(), seed.costHistory.back(), seed.termination);
		fprintf(stderr, "OlethrosOptimization pass=fine steps=%zu initial=%.17g final=%.17g stop=%s\n",
			trajectory.costHistory.size()-1, trajectory.costHistory.front(), trajectory.costHistory.back(), trajectory.termination);
	}
	finish();
}

void
PlanningMesh::finish()
{
	int n = (int)sections.size();
	path.resize(n);
	curvature.resize(n);
	for (int i = 0; i < n; ++i) path[i] = sections[i].point(trajectory.weights[i]);
	for (int i = 0; i < n; ++i) {
		PlanningPoint a = path[i] - path[(i + n - 1) % n], b = path[(i + 1) % n] - path[i];
		// Circumcircle curvature is evaluated only on the regular mesh.
		curvature[i] = 2.0 * fabs(a.cross(b)) / (a.length() * b.length() * (a + b).length());
		if (!std::isfinite(curvature[i])) throw std::runtime_error("Invalid planning curvature");
		if (diagnosticsEnabled)
			fprintf(stderr, "OlethrosRegular path i=%d s=%.17g x=%.17g y=%.17g w=%.9g curvature=%.17g\n",
				i, i * spacing, path[i].x, path[i].y, trajectory.weights[i], curvature[i]);
	}
}

void
PlanningMesh::map(const tTrackSeg& seg, double s, float& weight, float& k) const
{
	double coordinate = fmod(s + length, length) / spacing;
	int i = (int)floor(coordinate), j = (i + 1) % (int)path.size();
	double fraction = coordinate - i;
	// Match stored native vertices, including their float-coordinate rounding.
	PlanningSection native = nativeSection(seg);
	PlanningPoint d = native.left - native.right, chord = path[j] - path[i];
	double determinant = chord.cross(d);
	double t = (native.right - path[i]).cross(d) / determinant;
	double w = (native.right - path[i]).cross(chord) / determinant;
	if (!(t >= -1e-5 && t <= 1.00001 && w >= 0 && w <= 1)) {
		// Tight curved roads can exclude the polygon chord. Evaluate the road-
		// following path instead, then project onto the stored native section.
		PlanningSection road = at(s);
		PlanningPoint p = road.point((1 - fraction) * trajectory.weights[i] + fraction * trajectory.weights[j]);
		w = ((p - native.right).x * d.x + (p - native.right).y * d.y) / (d.x * d.x + d.y * d.y);
		if (!(w >= -1e-5 && w <= 1.00001) || fabs((p - native.right).cross(d)) / d.length() > 0.01)
			throw std::runtime_error("Planning path misses native cross-section");
		w = (std::max)(0.0, (std::min)(1.0, w));
		if (diagnosticsEnabled)
			fprintf(stderr, "OlethrosMapping road-evaluation seg=%d s=%.17g w=%.17g\n", seg.id, s, w);
	}
	weight = (float)w;
	k = (float)((1 - fraction) * curvature[i] + fraction * curvature[j]);
}
