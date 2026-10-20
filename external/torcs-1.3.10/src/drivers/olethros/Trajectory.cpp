/***************************************************************************

    file                 : Trajectory.cpp
    created              : 2006
    copyright            : (C) 2006-2026 by Christos Dimitrakakis, Bernhard Wymann
    email                : dimitrak@idiap.ch, berniw@bluewin.ch

 ***************************************************************************/

/***************************************************************************
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 ***************************************************************************/

/** @file Trajectory.cpp
 * @brief Bound-constrained minimization of discrete planar bending energy.
 * @ingroup olethros_planning
 */

#include "Trajectory.h"
#include <algorithm>
#include <array>
#include <stdexcept>

static double
dot(const TrajectoryPoint& a, const TrajectoryPoint& b)
{
	return a.x*b.x + a.y*b.y;
}

static double
dot(const std::vector<double>& a, const std::vector<double>& b)
{
	double result = 0;
	for (size_t i = 0; i < a.size(); ++i) result += a[i]*b[i];
	return result;
}

static double
clamp(double value, double limit)
{
	return (std::max)(-limit, (std::min)(limit, value));
}

// Alternating from the two ends of a cyclic sequence turns the wraparound
// pentadiagonal J'J matrix into an ordinary symmetric band matrix (bandwidth 4).
// This solves the coupled long-wavelength modes as well as local wiggles.
struct BendingSystem {
	std::vector<std::array<double, 5>> lower;
	explicit BendingSystem(size_t n) : lower(n, std::array<double, 5>{}) {}
	size_t index(size_t i) const { return i < (lower.size()+1)/2 ? 2*i : 2*(lower.size()-1-i)+1; }
	void add(size_t i, size_t j, double value) {
		i = index(i); j = index(j);
		if (i < j) std::swap(i, j);
		lower[i][i-j] += value;
	}
	void solve(const std::vector<double>& gradient, const std::vector<bool>& active,
		std::vector<double>& direction) {
		const size_t n = lower.size();
		double diagonal = 0;
		for (const auto& row : lower) diagonal = (std::max)(diagonal, row[0]);
		// Relative regularization protects near-null modes. It has no road-width
		// reference and does not change the objective tested by the line search.
		double damping = diagonal*1e-10;
		std::vector<bool> fixed(n);
		std::vector<double> rhs(n);
		for (size_t i = 0; i < n; ++i) {
			fixed[index(i)] = active[i]; rhs[index(i)] = active[i] ? 0 : -gradient[i];
		}
		for (size_t i = 0; i < n; ++i) {
			lower[i][0] = fixed[i] ? 1.0 : lower[i][0]+damping;
			for (size_t k = 1; k <= (std::min)(i, size_t(4)); ++k)
				if (fixed[i] || fixed[i-k]) lower[i][k] = 0;
		}
		// In-place banded Cholesky factorization, then forward/back substitution.
		for (size_t i = 0; i < n; ++i) {
			size_t first = i > 4 ? i-4 : 0;
			for (size_t j = first; j <= i; ++j) {
				double value = lower[i][i-j];
				for (size_t k = first; k < j; ++k) value -= lower[i][i-k]*lower[j][j-k];
				if (i == j) {
					if (!(value > 0) || !std::isfinite(value)) throw std::runtime_error("Invalid bending system");
					lower[i][0] = sqrt(value);
				} else lower[i][i-j] = value/lower[j][0];
			}
			for (size_t j = first; j < i; ++j) rhs[i] -= lower[i][i-j]*rhs[j];
			rhs[i] /= lower[i][0];
		}
		for (size_t i = n; i-- > 0;) {
			for (size_t j = i+1; j < (std::min)(n, i+5); ++j) rhs[i] -= lower[j][j-i]*rhs[j];
			rhs[i] /= lower[i][0];
		}
		for (size_t i = 0; i < n; ++i) direction[i] = rhs[index(i)];
	}
};

static double
evaluateBending(const std::vector<TrajectorySection>& track,
	const std::vector<double>& offsets, std::vector<double>* gradient, BendingSystem* system)
{
	const size_t n = track.size();
	if (n < 3 || offsets.size() != n) throw std::runtime_error("Invalid trajectory dimensions");
	std::vector<TrajectoryPoint> points(n), normals(n), directions(n);
	std::vector<double> lengths(n);
	for (size_t i = 0; i < n; ++i) {
		TrajectoryPoint across = track[i].left-track[i].right;
		double width = sqrt(dot(across, across));
		if (!(width > 0) || !std::isfinite(width)) throw std::runtime_error("Invalid trajectory width");
		normals[i] = across/width;
		points[i] = track[i].right + across*0.5 + normals[i]*offsets[i];
	}
	for (size_t i = 0; i < n; ++i) {
		TrajectoryPoint chord = points[(i+1)%n]-points[i];
		lengths[i] = sqrt(dot(chord, chord));
		if (!(lengths[i] > 0) || !std::isfinite(lengths[i]))
			throw std::runtime_error("Coincident or invalid trajectory points");
		directions[i] = chord/lengths[i];
	}
	if (gradient) gradient->assign(n, 0.0);
	double energy = 0;
	for (size_t i = 0; i < n; ++i) {
		size_t prev = (i+n-1)%n, next = (i+1)%n;
		const TrajectoryPoint& u = directions[prev];
		const TrajectoryPoint& v = directions[i];
		TrajectoryPoint change = v-u;
		double support = 0.5*(lengths[prev]+lengths[i]);
		double cost = dot(change, change)/support;
		energy += cost;
		if (gradient || system) {
			// Exact derivatives of |v-u|^2 / ((|a|+|b|)/2), including
			// both chord normalization and the variable support length.
			double root = sqrt(support);
			auto derivativeA = [&](TrajectoryPoint normal) {
				return (normal-u*dot(u, normal))*(-1.0/(root*lengths[prev]))
					- change*(dot(u, normal)/(4*support*root));
			};
			auto derivativeB = [&](TrajectoryPoint normal) {
				return (normal-v*dot(v, normal))*(1.0/(root*lengths[i]))
					- change*(dot(v, normal)/(4*support*root));
			};
			TrajectoryPoint jacobian[] = { derivativeA(normals[prev])*(-1),
				derivativeA(normals[i])-derivativeB(normals[i]), derivativeB(normals[next]) };
			size_t indices[] = {prev, i, next};
			for (int j = 0; j < 3; ++j) {
				if (gradient) (*gradient)[indices[j]] += 2*dot(jacobian[j], change/root);
				if (system) for (int k = 0; k <= j; ++k)
					system->add(indices[j], indices[k], 2*dot(jacobian[j], jacobian[k]));
			}
		}
	}
	if (!std::isfinite(energy)) throw std::runtime_error("Nonfinite trajectory energy");
	if (gradient) for (double entry : *gradient)
		if (!std::isfinite(entry)) throw std::runtime_error("Nonfinite trajectory gradient");
	return energy;
}

double
Trajectory::bendingEnergy(const std::vector<TrajectorySection>& track,
	const std::vector<double>& offsets, std::vector<double>* gradient)
{
	return evaluateBending(track, offsets, gradient, nullptr);
}

void
Trajectory::optimise(const std::vector<TrajectorySection>& track, int maxIterations,
	double edgeMargin, bool reset)
{
	const size_t n = track.size();
	if (n < 3 || maxIterations < 0 || edgeMargin < 0 || !std::isfinite(edgeMargin) || (!reset && weights.size() != n))
		throw std::runtime_error("Invalid trajectory optimization input");
	weights.resize(n);
	std::vector<double> x(n), limits(n), widths(n), gradient, trialGradient;
	double referenceLength = 0, maximumLimit = 0;
	for (size_t i = 0; i < n; ++i) {
		if (!reset && !std::isfinite(weights[i])) throw std::runtime_error("Nonfinite trajectory seed");
		TrajectoryPoint across = track[i].left-track[i].right;
		widths[i] = sqrt(dot(across, across));
		limits[i] = (std::max)(0.0, 0.5*widths[i]-edgeMargin);
		maximumLimit = (std::max)(maximumLimit, limits[i]);
		x[i] = reset ? 0.0 : clamp((weights[i]-0.5)*widths[i], limits[i]);
		TrajectoryPoint center = (track[i].left+track[i].right)*0.5;
		TrajectoryPoint next = (track[(i+1)%n].left+track[(i+1)%n].right)*0.5;
		TrajectoryPoint chord = next-center;
		referenceLength += sqrt(dot(chord, chord));
	}
	if (!(referenceLength > 0) || !std::isfinite(referenceLength))
		throw std::runtime_error("Invalid trajectory reference length");
	// A fixed geometric normalization makes the cost dimensionless. It
	// changes neither the minimizer nor its road-width-dependent feasible set.
	auto evaluate = [&](const std::vector<double>& offsets, std::vector<double>& g) {
		double value = referenceLength*bendingEnergy(track, offsets, &g);
		for (double& entry : g) entry *= referenceLength;
		return value;
	};
	double cost = evaluate(x, gradient);
	costHistory.assign(1, cost);
	std::vector<double> projected(n), direction(n), trial(n), displacement(n);
	std::vector<bool> active(n);
	termination = "iteration limit";
	for (int iteration = 0; iteration < maxIterations; ++iteration) {
		double norm = 0;
		for (size_t i = 0; i < n; ++i) {
			projected[i] = gradient[i];
			active[i] = (x[i] <= -limits[i] && gradient[i] > 0) || (x[i] >= limits[i] && gradient[i] < 0);
			if (active[i])
				projected[i] = 0;
			norm = (std::max)(norm, fabs(projected[i]));
		}
		if (norm <= 1e-10 || maximumLimit == 0) { termination = "projected gradient"; break; }
		BendingSystem system(n);
		evaluateBending(track, x, nullptr, &system);
		for (auto& row : system.lower) for (double& entry : row) entry *= referenceLength;
		system.solve(gradient, active, direction);
		for (size_t i = 0; i < n; ++i) {
			if ((x[i] <= -limits[i] && direction[i] < 0) || (x[i] >= limits[i] && direction[i] > 0))
				direction[i] = 0;
		}
		if (!(dot(direction, gradient) < 0)) {
			for (size_t i = 0; i < n; ++i) direction[i] = -projected[i]*maximumLimit/norm;
		}
		double trialCost = cost, step = 1.0;
		bool accepted = false;
		for (int attempt = 0; attempt < 50; ++attempt, step *= 0.5) {
			for (size_t i = 0; i < n; ++i) {
				trial[i] = clamp(x[i]+step*direction[i], limits[i]);
				displacement[i] = trial[i]-x[i];
			}
			double descent = dot(gradient, displacement);
			if (!(descent < 0)) continue;
			// An infeasible geometric trial (coincident points, for example) is
			// rejected just like an uphill step; the last valid path is retained.
			try { trialCost = evaluate(trial, trialGradient); }
			catch (const std::runtime_error&) { continue; }
			if (trialCost < cost && trialCost <= cost+1e-4*descent) { accepted = true; break; }
		}
		if (!accepted) { termination = "line search"; break; }
		x.swap(trial); gradient.swap(trialGradient);
		cost = trialCost;
		costHistory.push_back(cost);
	}
	for (size_t i = 0; i < n; ++i) weights[i] = 0.5+x[i]/widths[i];
}
