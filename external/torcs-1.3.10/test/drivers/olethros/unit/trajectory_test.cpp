/***************************************************************************

    file                 : trajectory_test.cpp
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
#include "Trajectory.h"

static const double kEps = 1e-7;

static std::vector<TrajectorySection>
circle(int count, double radius, double width, double heading = 0.0)
{
	std::vector<TrajectorySection> track;
	for (int i = 0; i < count; ++i) {
		double angle = heading+2*acos(-1.0)*i/count;
		track.push_back({{(radius-width/2)*cos(angle), (radius-width/2)*sin(angle)},
			{(radius+width/2)*cos(angle), (radius+width/2)*sin(angle)}});
	}
	return track;
}

TEST(Trajectory, CircleEnergyMatchesAnalyticValueIncludingTinyGeometry)
{
	for (double radius : {0.005, 0.05, 30.0, 300.0}) {
		auto track = circle(16, radius, radius/5);
		double expected = 32*sin(acos(-1.0)/16)/radius;
		double actual = Trajectory::bendingEnergy(track, std::vector<double>(16, 0.0));
		EXPECT_NEAR(actual, expected, expected*kEps);
		Trajectory trajectory; trajectory.optimise(track, 100);
		for (double w : trajectory.weights) EXPECT_NEAR(w, 0, kEps);
	}
}

TEST(Trajectory, AnalyticGradientMatchesIndependentCentralDifferences)
{
	for (double width : {5.0, 30.0}) {
		auto track = circle(17, 40, width, 0.7);
		std::vector<double> x(17), gradient;
		for (size_t i = 0; i < x.size(); ++i) x[i] = 0.4*sin(1.3*i);
		Trajectory::bendingEnergy(track, x, &gradient);
		for (size_t i = 0; i < x.size(); ++i) {
			auto plus = x, minus = x;
			plus[i] += 1e-4; minus[i] -= 1e-4;
			double finiteDifference = (Trajectory::bendingEnergy(track, plus)-Trajectory::bendingEnergy(track, minus))/2e-4;
			EXPECT_NEAR(gradient[i], finiteDifference, kEps);
		}
	}
}

TEST(Trajectory, EveryAcceptedStepLowersEnergyAndRemovesSeedWiggles)
{
	for (double width : {5.0, 10.0, 18.0, 30.0}) {
		SCOPED_TRACE(width);
		auto track = circle(160, 100, width);
		Trajectory trajectory;
		for (int i = 0; i < 160; ++i) trajectory.weights.push_back(0.5+0.2*sin(i*0.7));
		trajectory.optimise(track, 1000, 1.1, false);
		ASSERT_GT(trajectory.costHistory.size(), 1u);
		for (size_t i = 1; i < trajectory.costHistory.size(); ++i)
			EXPECT_LT(trajectory.costHistory[i], trajectory.costHistory[i-1]);
		EXPECT_LT(trajectory.costHistory.back(), trajectory.costHistory.front()*0.5);
		double maximumClearanceError = 0;
		for (double w : trajectory.weights) {
			ASSERT_TRUE(std::isfinite(w));
			maximumClearanceError = (std::max)(maximumClearanceError, fabs(w*width-1.1));
		}
		EXPECT_NEAR(maximumClearanceError, 0, 0.05);
	}
}

TEST(Trajectory, RigidRotationAndTranslationPreserveTheOptimizedLine)
{
	auto first = circle(64, 50, 30), second = circle(64, 50, 30, 0.7);
	for (auto& section : second) {
		section.left = section.left+TrajectoryPoint{100, -200};
		section.right = section.right+TrajectoryPoint{100, -200};
	}
	Trajectory a, b;
	a.optimise(first, 500, 1.1); b.optimise(second, 500, 1.1);
	for (size_t i = 0; i < first.size(); ++i) EXPECT_NEAR(a.weights[i], b.weights[i], kEps);
}

TEST(Trajectory, ZeroIterationsPreserveFeasibleSeedAndResetCentersIt)
{
	auto track = circle(8, 30, 10);
	Trajectory trajectory;
	for (int i = 0; i < 8; ++i) trajectory.weights.push_back(0.2+0.05*i);
	auto seed = trajectory.weights;
	trajectory.optimise(track, 0, 0.0, false);
	for (size_t i = 0; i < seed.size(); ++i) EXPECT_NEAR(trajectory.weights[i], seed[i], kEps);
	trajectory.optimise(track, 0);
	for (double w : trajectory.weights) EXPECT_NEAR(w, 0.5, kEps);
}

TEST(Trajectory, VaryingWidthsUseWideSectionsWhileRespectingNarrowOnes)
{
	const int count = 128;
	auto track = circle(count, 100, 5);
	std::vector<double> widths;
	for (int i = 0; i < count; ++i) {
		double angle = 2*acos(-1.0)*i/count;
		double width = 5+12.5*(1+cos(angle));
		widths.push_back(width);
		track[i] = {{(100-width/2)*cos(angle), (100-width/2)*sin(angle)},
			{(100+width/2)*cos(angle), (100+width/2)*sin(angle)}};
	}
	Trajectory trajectory; trajectory.optimise(track, 500, 1.1);
	double largestOffset = 0;
	for (int i = 0; i < count; ++i) {
		double offset = fabs((trajectory.weights[i]-0.5)*widths[i]);
		EXPECT_LE(offset, widths[i]/2-1.1+kEps);
		largestOffset = (std::max)(largestOffset, offset);
	}
	EXPECT_GT(largestOffset, 10.0);
	EXPECT_LT(trajectory.costHistory.back(), trajectory.costHistory.front());
}

TEST(Trajectory, InvalidSeedsAndDegenerateGeometryAreRejected)
{
	auto track = circle(8, 30, 5);
	Trajectory trajectory; trajectory.weights.assign(8, 0.5);
	trajectory.weights[3] = std::numeric_limits<double>::quiet_NaN();
	EXPECT_THROW(trajectory.optimise(track, 10, 1.1, false), std::runtime_error);
	EXPECT_THROW(trajectory.optimise(track, 10, -1.0), std::runtime_error);
	track[3] = track[2];
	EXPECT_THROW(trajectory.optimise(track, 10), std::runtime_error);
}
