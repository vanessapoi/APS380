/***************************************************************************

	file                 : PlanningMesh.h
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

/** @file PlanningMesh.h
 * @brief Interface to regular periodic track geometry and runtime path queries.
 * @ingroup olethros_planning
 */

#ifndef _PLANNINGMESH_H_
#define _PLANNINGMESH_H_

#include <cstddef>
#include <vector>
#include <track.h>
#include "Trajectory.h"

/** @brief Double-precision Cartesian point/vector in world XY meters. */
struct PlanningPoint {
	double x, y;
	PlanningPoint operator+(PlanningPoint p) const;
	PlanningPoint operator-(PlanningPoint p) const;
	PlanningPoint operator*(double scale) const;
	double cross(PlanningPoint p) const;
	double length() const;
};

/** @brief Road cross-section ordered from right border to left border. */
struct PlanningSection {
	PlanningPoint right, left;
	/** @brief Interpolate a point; weight 0 is right, 1 is left. */
	PlanningPoint point(double weight) const;
};

/** @brief Driver-owned regular mesh with borrowed native track correspondence.
 * @details Samples track station, not racing-line arclength. The track must
 * outlive this object. Call optimise() before path queries, or supply weights
 * and call finish(). Native IDs select metadata/learning; regular indices select
 * optimization samples. Curvature is a polygon estimate, not the analytic
 * derivative of the road-following position interpolant.
 */
class PlanningMesh {
private:
	bool diagnosticsEnabled; ///< Environment flag cached at construction for this mesh's lifetime.
	std::vector<const tTrackSeg*> segments; ///< Borrowed intervals in start-line order.
	std::vector<double> starts; ///< Double-accumulated native starts, sorted.
	std::vector<double> startsById; ///< Native-ID to accumulated station mapping.
	std::vector<double> stations; ///< Sorted union of native/regular scan boundaries.

public:
	double length, spacing; ///< Lap length and uniform planning interval in meters.
	std::vector<PlanningSection> sections; ///< Regular native-road cross-sections.
	std::vector<PlanningPoint> path; ///< Optimized world points at regular stations.
	std::vector<double> curvature; ///< Unsigned circumcircle curvature in inverse meters.
	Trajectory trajectory; ///< Optimizer state and regular lateral weights.

	/** @brief Build regular stations and native-track correspondence.
	 * @param[in] track Live cyclic track with valid IDs and a zero-station segment.
	 * @param[in] nominal Requested maximum spacing in meters; runtime uses 4 m.
	 * @throws std::runtime_error Invalid geometry, start station or sample count.
	 */
	explicit PlanningMesh(const tTrack& track, double nominal = 4.0);

	/** @brief Coarse initialization and fine optimization, followed by finish().
	 * @param[in] edgeMargin Reference-point clearance from each road edge, in meters.
	 */
	void optimise(double edgeMargin = 0.0);
	/** @brief Recompute world points and periodic curvature from trajectory.weights.
	 * @pre One weight per section.
	 * @throws std::runtime_error Nonfinite curvature from degenerate path geometry.
	 */
	void finish();

	/** @brief Wrap finite station meters into [0,length). */
	double wrap(double s) const;
	/** @brief Locate the native traversal index, choosing the entering side at joins. */
	size_t nativeIndex(double s) const;
	/** @brief Borrow native surface, banking and learning metadata at station s. */
	const tTrackSeg& source(double s) const;
	/** @brief Convert native segment/local meters into unwrapped station.
	 * @pre seg belongs to this track; convert curve-local radians before calling.
	 */
	double station(const tTrackSeg& seg, double local = 0) const;
	/** @brief Locate the regular interval for wrapped station s.
	 * @param[in] s Track station in meters.
	 * @param[out] fraction Fraction toward the next periodic point.
	 * @return Regular index, not a native ID.
	 */
	size_t interval(double s, double& fraction) const;
	/** @brief Next unwrapped scan station, strictly after s on the entering side.
	 * @details Uses the union of regular stations and every native boundary,
	 * including surface patches shorter than the mesh spacing.
	 */
	double nextStation(double s) const;

	/** @brief Interpolated dimensionless right-to-left weight at station s. */
	double weight(double s) const;
	/** @brief Road-following world position at the actual station, in meters. */
	PlanningPoint position(double s) const;
	/** @brief Interpolated unsigned regular-path curvature, in inverse meters. */
	double pathCurvature(double s) const;
	/** @brief Path radius in meters; zero curvature intentionally gives infinity. */
	double pathRadius(double s) const;
	/** @brief Apply the selected avoidance/pit offset law.
	 * @param[in] s Track station in meters.
	 * @param[in] offset Signed centerline displacement in meters, positive left.
	 * @param[in] inLane Select center weight instead of the racing line.
	 * @param[in] inPit Apply pit displacement directly.
	 * @return World XY target in meters.
	 * @pre The evaluated cross-section has nonzero width.
	 */
	PlanningPoint target(double s, double offset, bool inLane, bool inPit) const;

	/** @brief Average-border road elevation at s, in meters. */
	double elevation(double s) const;
	/** @brief Grade angle in radians over one regular spacing centered at s. */
	double grade(double s) const;
	/** @brief Derivative of sin(grade) over regular support, in inverse meters. */
	double gradeDerivative(double s) const;

	/** @brief Evaluate native borders with stable anchored arc geometry.
	 * @param[in] seg Native interval with valid radii and width law.
	 * @param[in] distance Centerline meters from its start, not radians.
	 * @return Right/left world border coordinates in meters.
	 */
	static PlanningSection evaluate(const tTrackSeg& seg, double distance);
	/** @brief Read stored native start vertices, including float rounding. */
	static PlanningSection nativeSection(const tTrackSeg& seg);
	/** @brief Evaluate native borders at wrapped station s in meters. */
	PlanningSection at(double s) const;
	/** @brief Map a regular solution to native compatibility data.
	 * @param[in] seg Native cross-section to intersect/project onto.
	 * @param[in] s Its station in meters within the lap.
	 * @param[out] weight Native right-to-left weight.
	 * @param[out] k Unsigned regular curvature in inverse meters.
	 * @throws std::runtime_error Projection misses the stored native section.
	 * @details Uses checked road-following projection if the polygon chord does
	 * not intersect the road section. Runtime queries still use the retained mesh.
	 */
	void map(const tTrackSeg& seg, double s, float& weight, float& k) const;
	/** @brief Native traversal index to accumulated station in meters. */
	double nativeStart(int i) const;
	/** @brief Borrow native segment by traversal index, not native ID. */
	const tTrackSeg& nativeSegment(int i) const;

};

#endif
