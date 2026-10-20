/***************************************************************************

    file                 : pit.h
    created              : Thu Mai 15 2:41:00 CET 2003
    copyright            : (C) 2003-2004 by Bernhard Wymann
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

/** @file pit.h
 * @brief Pit trajectory, request state, speed limit and service timeout.
 * @ingroup olethros_pits
 */
#ifndef _PIT_H_
#define _PIT_H_

#include "driver.h"
#include "spline.h"

class Driver;

/** @brief Maneuver derived by Pit from its service request and lane occupancy. */
enum PitState {
	NONE=0x0, APPROACHING, IN_LANE, PIT_EXIT
};


/** @brief Driver-owned pit adapter with a seven-point lateral Hermite spline.
 * @details Borrows track, car and TORCS pit descriptors; owns the Spline that
 * borrows this object's point array. No-pit tracks bypass the guarded operations.
 * Callers must not use initialized-pit-only getters when the car has no own pit.
 */
class Pit {
	public:
		/** @brief Build pit trajectory from the driver's assigned pit and track metadata. */
		Pit(tSituation *s, Driver *driver);
		~Pit();

		static const float BRAKE_AHEAD; ///< Entry braking/approach range in meters.
		/** @brief Current maneuver, refreshed before steering and when a request is cleared. */
		enum PitState getState (void) {return pit_state;}
		/** @brief Set a stop request outside the pit range, or clear it anywhere. */
		void setPitstop(bool pitstop);
		/** @brief Whether a service stop is requested. */
		bool getPitstop() { return pitstop; }

		/** @brief Current pit-lane occupancy flag. */
		bool getInPit() { return inpitlane; }

		/** @brief Return the active pit spline displacement, otherwise the supplied offset.
		 * @param[in] offset Normal lateral displacement in meters, positive left.
		 * @param[in] fromstart Native track station in meters from the start line.
		 * @return Signed displacement from the road centerline, in meters.
		 * @details Lookahead at or beyond the last knot uses the final displacement.
		 */
		float getPitOffset(float offset, float fromstart);

		/** @brief Test native station against the pit-entry/exit range, including lap wrap. */
		bool isBetween(float fromstart);
		/** @brief Detect failure to be captured at a requested stop.
		 * @param[in] distance Signed longitudinal meters to the stop, positive ahead.
		 * @details Advances/resets a seconds timer using the robot timestep.
		 */
		bool isTimeout(float distance);

		/** @brief Pit-lane start in spline-coordinate meters. */
		float getNPitStart() { return p[1].x; }
		/** @brief Own service stop in spline-coordinate meters. */
		float getNPitLoc() { return p[3].x; }
		/** @brief Pit-lane end in spline-coordinate meters. */
		float getNPitEnd() { return p[5].x; }

		/** @brief Convert native station meters into nonnegative meters after pit entry. */
		float toSplineCoord(float x);

		/** @brief Safety-reduced squared speed limit in (m/s)^2. */
		float getSpeedlimitSqr() { return speedlimitsqr; }
		/** @brief Safety-reduced speed limit in m/s. */
		float getSpeedlimit() { return speedlimit; }
		/** @brief Unclamped normalized brake demand between reduced and official squared limits. */
		float getSpeedLimitBrake(float speedsqr);

		/** @brief Refresh occupancy/maneuver and send RM_CMD_PIT_ASKED while a stop is requested. */
		void update();

	private:
		void updateManeuver();
		enum PitState pit_state;
		tTrack *track;
		tCarElt *car;
		tTrackOwnPit *mypit;			// Pointer to my pit.
		tTrackPitInfo *pitinfo;			// General pit info.

		enum { NPOINTS = 7 };
		SplinePoint p[NPOINTS];			// Spline points.
		Spline *spline;					// Spline.

		bool pitstop;					// Pitstop planned.
		bool inpitlane;					// We are still in the pit lane.
		float pitentry;					// Distance to start line of the pit entry.
		float pitexit;					// Distance to the start line of the pit exit.

		float speedlimitsqr;			// Pit speed limit squared.
		float speedlimit;				// Pit speed limit.
		float pitspeedlimitsqr;			// The original speedlimit squared.

		float pittimer;					// Timer for pit timeouts.

		static const float SPEED_LIMIT_MARGIN;
};

#endif // _PIT_H_
