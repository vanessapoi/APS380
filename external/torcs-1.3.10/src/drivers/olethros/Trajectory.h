/***************************************************************************

    file                 : Trajectory.h
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

/** @file Trajectory.h
 * @brief Double-precision trajectory optimization for the regular planning mesh.
 * @ingroup olethros_planning
 */

#ifndef _TRAJECTORY_H_
#define _TRAJECTORY_H_

#include <cmath>
#include <vector>

/** @brief Cartesian optimizer point/vector in meters. */
struct TrajectoryPoint {
	double x, y, z;
	TrajectoryPoint(double x = 0, double y = 0, double z = 0) : x(x), y(y), z(z) {}
	TrajectoryPoint operator-(TrajectoryPoint p) const { return {x-p.x, y-p.y, z-p.z}; }
	TrajectoryPoint operator+(TrajectoryPoint p) const { return {x+p.x, y+p.y, z+p.z}; }
	TrajectoryPoint operator*(double scale) const { return {x*scale, y*scale, z*scale}; }
	TrajectoryPoint operator/(double divisor) const { return {x/divisor, y/divisor, z/divisor}; }
	double length() const { return sqrt(x*x+y*y+z*z); }
	/** @brief Normalize in place; the input chord must have nonzero length. */
	void normalize() { double inverse = 1.0/length(); x *= inverse; y *= inverse; z *= inverse; }
};

/** @brief Road cross-section available to one optimization weight. */
struct TrajectorySection {
	TrajectoryPoint left, right;
};

/** @brief Bound-constrained planar bending-energy optimizer.
 * @details Each weight is a right-to-left cross-section fraction: 0 is right,
 * 1 is left. Indexing follows the regular mesh, not native TORCS segment IDs.
 * PlanningMesh calculates final geometric curvature after optimization.
 */
class Trajectory {
public:
	std::vector<double> weights; ///< Caller-supplied coarse seed and final path weights.
	std::vector<double> costHistory; ///< Initial and accepted dimensionless bending costs.
	const char* termination = "not started"; ///< Projected gradient, line search, or iteration limit.

	/** @brief Refine a cyclic path with projected Gauss-Newton and Armijo backtracking.
	 * @param[in] track Cross-sections with distinct neighboring path points.
	 * @param[in] maxIterations Maximum number of accepted search steps.
	 * @param[in] edgeMargin Minimum reference-point clearance from each road edge, in meters.
	 * @param[in] reset Replace weights with the centerline rather than use the supplied seed.
	 * @details Variables are lateral meters, not road-width fractions. Every accepted
	 * step lowers a defined geometric cost; this does not guarantee a global minimum
	 * or minimum lap time. All coordinates are optimized, with no random traversal.
	 */
	void optimise(const std::vector<TrajectorySection>& track, int maxIterations,
		double edgeMargin = 0.0, bool reset = true);
	/** @brief Sum squared changes in unit chord directions / mean chord length.
	 * @param[in] offsets Centerline-relative lateral meters, positive toward the left edge.
	 * @param[out] gradient Optional exact derivative with respect to lateral meters.
	 * @return Discrete approximation of the integral of squared curvature (1/meters).
	 */
	static double bendingEnergy(const std::vector<TrajectorySection>& track,
		const std::vector<double>& offsets, std::vector<double>* gradient = nullptr);
};

#endif
