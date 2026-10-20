/***************************************************************************

    file                 : planning_mesh_test.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/
/***************************************************************************
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 ***************************************************************************/
#include <gtest/gtest.h>
#include <algorithm>
#include <limits>
#include <stdexcept>
#include "PlanningMesh.h"

static const double kEps = 1e-5; // Float native coordinates evaluated in double.
static const double kPathEps = 1e-4; // Native re-anchoring ULPs through optimization.

static tTrack linkTrack(std::vector<tTrackSeg>& segments)
{
	for (size_t i = 0; i < segments.size(); ++i) {
		segments[i].id = (int)i;
		segments[i].next = &segments[(i+1)%segments.size()];
		segments[i].prev = &segments[(i+segments.size()-1)%segments.size()];
	}
	tTrack track = {};
	track.seg = segments.data(); track.nseg = (int)segments.size();
	return track;
}

TEST(PlanningMesh, SubdivisionPreservesOptimizedPathAndRuntimeQueries)
{
	// Tangent-continuous stadium, both directions; include 15.625 mm intervals.
	for (int type : {TR_LFT, TR_RGT}) {
		double sign = type == TR_LFT ? 1 : -1;
		std::vector<tTrackSeg> coarse(4), split(12);
		PlanningPoint right = {0, 0};
		double heading = 0, station = 0;
		for (int i = 0; i < 4; ++i) {
			tTrackSeg& seg = coarse[i];
			seg.type = i%2 ? type : TR_STR;
			seg.radius = 40; seg.radiusr = (float)(40+sign*5);
			seg.startWidth = 10; seg.length = i%2 ? (float)(40*acos(-1.0)) : 100;
			seg.angle[TR_ZS] = (float)heading; seg.lgfromstart = (float)station;
			seg.vertex[TR_SR].x = (float)right.x; seg.vertex[TR_SR].y = (float)right.y;
			PlanningSection start = PlanningMesh::evaluate(seg, 0);
			seg.vertex[TR_SL].x = (float)start.left.x; seg.vertex[TR_SL].y = (float)start.left.y;
			double offsets[] = {0, seg.length/2.0, seg.length-0.015625};
			for (int j = 0; j < 3; ++j) {
				tTrackSeg& part = split[3*i+j]; part = seg;
				PlanningSection section = PlanningMesh::evaluate(seg, offsets[j]);
				part.vertex[TR_SR].x = (float)section.right.x; part.vertex[TR_SR].y = (float)section.right.y;
				part.vertex[TR_SL].x = (float)section.left.x; part.vertex[TR_SL].y = (float)section.left.y;
				part.angle[TR_ZS] = (float)(seg.angle[TR_ZS]+(i%2 ? sign*offsets[j]/seg.radius : 0));
				part.length = (float)((j == 2 ? seg.length : offsets[j+1])-offsets[j]);
				part.lgfromstart = (float)(station+offsets[j]);
			}
			right = PlanningMesh::evaluate(seg, seg.length).right;
			heading = seg.angle[TR_ZS]+(i%2 ? sign*seg.length/seg.radius : 0);
			station += seg.length;
		}
		tTrack a = linkTrack(coarse), b = linkTrack(split);
		for (double spacing : {4.0, 5.0, 2.0}) {
			PlanningMesh first(a, spacing), second(b, spacing);
			first.optimise(); second.optimise();
			ASSERT_EQ(first.path.size(), second.path.size());
			double positionError = 0, curvatureError = 0, targetError = 0;
			for (double s = -11.3; s < first.length+12; s += 1.7) {
				double positionDelta = (first.position(s)-second.position(s)).length();
				double curvatureDelta = fabs(first.pathCurvature(s)-second.pathCurvature(s));
				ASSERT_TRUE(std::isfinite(positionDelta));
				ASSERT_TRUE(std::isfinite(curvatureDelta));
				positionError = (std::max)(positionError, positionDelta);
				curvatureError = (std::max)(curvatureError, curvatureDelta);
				EXPECT_NEAR((first.position(s)-first.position(s-3*first.length)).length(), 0, kPathEps);
				for (double offset : {-2.0, 0.0, 2.0}) {
					double targetDelta = (first.target(s, offset, false, false)-second.target(s, offset, false, false)).length();
					ASSERT_TRUE(std::isfinite(targetDelta));
					targetError = (std::max)(targetError, targetDelta);
				}
			}
			EXPECT_NEAR(positionError, 0, kPathEps);
			EXPECT_NEAR(curvatureError, 0, kPathEps);
			EXPECT_NEAR(targetError, 0, kPathEps);
		}
	}
}

TEST(PlanningMesh, WarmStartMatchesIndependentCoarseSeedAndRefinement)
{
	for (int n : {5, 15, 16}) {
		std::vector<tTrackSeg> segs(1);
		tTrackSeg& seg = segs[0]; seg.type = TR_LFT; seg.length = (float)(4*n);
		seg.radius = (float)(seg.length/(2*acos(-1.0))); seg.radiusr = seg.radius+0.5f; seg.startWidth = 1;
		tTrack track = linkTrack(segs); PlanningMesh mesh(track);
		std::vector<int> anchors = n == 5 ? std::vector<int>{0,1,2,3,4} :
			n == 15 ? std::vector<int>{0,3,6,9,12} : std::vector<int>{0,2,5,8,10,13};
		std::vector<TrajectorySection> fine, coarse;
		for (const PlanningSection& s : mesh.sections) fine.push_back({{s.left.x,s.left.y},{s.right.x,s.right.y}});
		for (int i : anchors) coarse.push_back(fine[i]);
		Trajectory seed, expected;
		seed.optimise(coarse, 500);
		for (size_t i = 0; i < anchors.size(); ++i) {
			int end = i+1 == anchors.size() ? n : anchors[i+1];
			for (int j = anchors[i]; j < end; ++j) {
				double f = double(j-anchors[i])/(end-anchors[i]);
				expected.weights.push_back((1-f)*seed.weights[i]+f*seed.weights[(i+1)%anchors.size()]);
			}
		}
		expected.optimise(fine, 1000, 0.0, false);
		mesh.optimise();
		EXPECT_EQ(mesh.trajectory.weights, expected.weights);
	}
}

TEST(PlanningMesh, HugeArcsAndVariableWidthsAreResolved)
{
	for (int type : {TR_LFT, TR_RGT}) for (float radius : {30.0f, 1e9f, 1e12f}) {
		tTrackSeg seg = {}; seg.type = type; seg.radius = seg.radiusr = radius;
		seg.angle[TR_ZS] = 0.73f; seg.startWidth = 10; seg.Kyl = radius/20;
		seg.vertex[TR_SR].x = 1234.5f; seg.vertex[TR_SR].y = -876.25f;
		double d = radius > 1e8 ? 4000 : 4, a = d/radius, sign = type == TR_LFT ? 1 : -1;
		PlanningSection section = PlanningMesh::evaluate(seg, d);
		double dx = section.right.x-seg.vertex[TR_SR].x, dy = section.right.y-seg.vertex[TR_SR].y;
		double h = seg.angle[TR_ZS];
		EXPECT_NEAR(dx*cos(h)+dy*sin(h), radius*sin(a), 1e-9);
		EXPECT_NEAR(-dx*sin(h)+dy*cos(h), sign*2*radius*pow(sin(a/2),2), 1e-9);
		EXPECT_NEAR((section.left-section.right).length(), seg.startWidth+a*seg.Kyl, 1e-9);
	}
}

TEST(PlanningMesh, WideOvalDoesNotInventTightOrOppositeBends)
{
	// A constant-radius oval has no chicanes. Exercise both directions and
	// different world headings: width must not destabilize the fine optimizer.
	for (double width : {5.0, 10.0, 18.0, 30.0}) for (int type : {TR_LFT, TR_RGT}) {
		for (double spacing : {2.0, 4.0, 8.0}) for (double heading : {0.0, 0.7}) {
			SCOPED_TRACE(::testing::Message() << "width=" << width << " type=" << type << " spacing=" << spacing << " heading=" << heading);
			const double radius = 300.0, sign = type == TR_LFT ? 1.0 : -1.0;
			std::vector<tTrackSeg> segments(4);
			PlanningPoint right = {100, 200};
			double station = 0;
			for (tTrackSeg& seg : segments) {
				seg.type = type; seg.radius = (float)radius;
				seg.radiusr = (float)(radius + sign*width/2);
				seg.startWidth = (float)width;
				seg.length = (float)(radius*acos(-1.0)/2);
				seg.lgfromstart = (float)station; seg.angle[TR_ZS] = (float)heading;
				seg.vertex[TR_SR].x = (float)right.x; seg.vertex[TR_SR].y = (float)right.y;
				right = PlanningMesh::evaluate(seg, seg.length).right;
				heading += sign*seg.length/radius;
				station += seg.length;
			}
			tTrack track = linkTrack(segments); PlanningMesh mesh(track, spacing);
			const double margin = 1.1; // 1.8 m car plus 0.2 m edge clearance.
			mesh.optimise(margin);
			double maximumClearanceError = 0;
			for (double w : mesh.trajectory.weights) {
				ASSERT_TRUE(std::isfinite(w));
				// The minimum-energy circle is the outer usable road edge. A
				// centered or artificially narrowed line is not an acceptable fix.
				double clearance = (type == TR_LFT ? w : 1-w)*width;
				maximumClearanceError = (std::max)(maximumClearanceError, fabs(clearance-margin));
			}
			EXPECT_NEAR(maximumClearanceError, 0, 0.05); // 5 cm geometric convergence tolerance.
			double minimumSigned = 1.0, maximum = 0.0;
			for (size_t i = 0; i < mesh.path.size(); ++i) {
				PlanningPoint a = mesh.path[i]-mesh.path[(i+mesh.path.size()-1)%mesh.path.size()];
				PlanningPoint b = mesh.path[(i+1)%mesh.path.size()]-mesh.path[i];
				double k = sign*2*a.cross(b)/(a.length()*b.length()*(a+b).length());
				ASSERT_TRUE(std::isfinite(k));
				minimumSigned = (std::min)(minimumSigned, k);
				maximum = (std::max)(maximum, fabs(k));
			}
			EXPECT_GE(minimumSigned, -kEps);
			// Allow 25% over the tightest road-edge curvature for imperfect
			// convergence; reject the artificial 50-100 m bends on a 300 m oval.
			EXPECT_LT(maximum, 1.25/(radius-width/2));
		}
	}
}

TEST(PlanningMesh, LongStraightUsesInteriorCurvatureAndPreservesOffsets)
{
	std::vector<tTrackSeg> segs(1); segs[0].type = TR_STR; segs[0].length = 150.015625f; segs[0].startWidth = 10;
	tTrack track = linkTrack(segs); PlanningMesh mesh(track);
	EXPECT_NEAR(mesh.length-mesh.spacing*(mesh.sections.size()-1), mesh.spacing, kEps);
	mesh.trajectory.weights.assign(mesh.sections.size(), 0.3); mesh.finish();
	for (size_t i = 0; i < mesh.curvature.size(); ++i) mesh.curvature[i] = 0.014/(i+1);
	EXPECT_EQ(&mesh.source(0), &mesh.source(80));
	EXPECT_NEAR(mesh.pathRadius(0), 1/0.014, kEps); EXPECT_GT(mesh.pathRadius(80), 1000);
	for (double offset : {-2.0, 0.0, 2.0}) {
		EXPECT_NEAR(mesh.target(81.3, offset, false, false).y, 3+tanh(fabs(offset))*(2+offset), kEps);
		EXPECT_NEAR(mesh.target(81.3, offset, true, true).y, 5+offset, kEps);
	}
	mesh.curvature.assign(mesh.sections.size(), 0);
	EXPECT_TRUE(std::isinf(mesh.pathRadius(80)));
}

TEST(PlanningMesh, NativeIDsTinySurfacePatchAndWrapArePreserved)
{
	std::vector<tTrackSeg> segs(3); tTrackSurface surfaces[3] = {};
	const double starts[] = {0, 15, 15.015625};
	for (int i = 0; i < 3; ++i) {
		segs[i].type = TR_STR; segs[i].startWidth = 10; segs[i].length = (float)((i == 2 ? 40 : starts[i+1])-starts[i]);
		segs[i].lgfromstart = (float)starts[i]; segs[i].vertex[TR_SR].x = (float)starts[i];
		segs[i].surface = &surfaces[i]; surfaces[i].kFriction = i == 1 ? 0.2f : 1;
	}
	tTrack track = linkTrack(segs); track.seg = &segs[2];
	for (int i = 0; i < 3; ++i) segs[i].id = (i+1)%3;
	PlanningMesh mesh(track);
	EXPECT_NEAR(mesh.station(segs[1], 0.0078125), 15.0078125, kEps);
	for (double origin : {-30.0, 10.0, 4000010.0}) {
		bool patch = false; int count = 0;
		for (double s = origin; s < origin+40 && count++ < 30;) {
			double next = mesh.nextStation(s); ASSERT_GT(next, s); s = next;
			if (mesh.source(s).surface->kFriction < 0.5) patch = true;
		}
		EXPECT_TRUE(patch); EXPECT_LT(count, 30);
	}
}

TEST(PlanningMesh, GradeDerivativeUsesPhysicalSupportAndSine)
{
	for (bool split : {false, true}) {
		std::vector<double> starts = split ? std::vector<double>{0,24,47.984375,48,72,95.984375} : std::vector<double>{0,48};
		std::vector<tTrackSeg> segs(starts.size());
		for (size_t i = 0; i < starts.size(); ++i) {
			double a = starts[i], b = i+1 == starts.size() ? 96 : starts[i+1];
			segs[i].type = TR_STR; segs[i].startWidth = 10; segs[i].length = (float)(b-a); segs[i].lgfromstart = (float)a;
			segs[i].vertex[TR_SL].z = segs[i].vertex[TR_SR].z = (float)(0.75*(a <= 48 ? a : 96-a));
			segs[i].vertex[TR_EL].z = segs[i].vertex[TR_ER].z = (float)(0.75*(b <= 48 ? b : 96-b));
		}
		tTrack track = linkTrack(segs); PlanningMesh mesh(track);
		EXPECT_NEAR(mesh.grade(44), atan(0.75), kEps);
		EXPECT_NEAR(mesh.gradeDerivative(48), -0.15, kEps);
		EXPECT_NEAR(mesh.gradeDerivative(0), 0.15, kEps);
		EXPECT_NEAR(mesh.gradeDerivative(-144), -0.15, kEps);
	}
}

TEST(PlanningMesh, MappingUsesStoredBordersAndRejectsInvalidProjection)
{
	std::vector<tTrackSeg> segs(1); segs[0].type = TR_STR; segs[0].length = 20; segs[0].startWidth = 10;
	tTrack track = linkTrack(segs); PlanningMesh mesh(track);
	mesh.trajectory.weights.assign(mesh.sections.size(), 0.5); mesh.finish();
	tTrackSeg native = segs[0]; native.vertex[TR_SR].x = 4.4f; native.vertex[TR_SL].x = 4.6f; native.vertex[TR_SL].y = 12;
	float w, k; mesh.map(native, 4.5, w, k);
	EXPECT_NEAR(w, 5.0/12, kEps); EXPECT_NEAR(k, 0, kEps);
	native.vertex[TR_SR].y = native.vertex[TR_SL].y = 20;
	EXPECT_THROW(mesh.map(native, 4.5, w, k), std::runtime_error);
	for (double spacing : {0.0,-1.0,100.0,std::numeric_limits<double>::denorm_min()})
		EXPECT_THROW(PlanningMesh(track, spacing), std::runtime_error);
	segs[0].lgfromstart = 1;
	EXPECT_THROW(PlanningMesh{track}, std::runtime_error);
}
