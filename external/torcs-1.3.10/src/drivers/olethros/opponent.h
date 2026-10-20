// -*- Mode: c++ -*-
/***************************************************************************

    file                 : opponent.h
    created              : Thu Apr 22 01:20:19 CET 2003
    copyright            : (C) 2003-2005 Bernhard Wymann, Christos Dimitrakakis
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

/** @file opponent.h
 * @brief Driver-relative opponent classification, catching and collision estimates.
 * @ingroup olethros_opponents
 */
#ifndef _OPPONENT_H_
#define _OPPONENT_H_

#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#include <tgf.h>
#include <track.h>
#include <car.h>
#include <raceman.h>
#include <robottools.h>
#include <robot.h>

#include "linalg.h"
#include "driver.h"
#include "cardata.h"

/** @brief Combinable relative-opponent classifications. */
enum OpponentState {
	OPP_IGNORE = 0,
	OPP_FRONT = 1<<0,
	OPP_BACK = 1<<1,
	OPP_SIDE = 1<<2,
	OPP_COLL = 1<<3,
	OPP_LETPASS = 1<<4,
	OPP_FRONT_FAST = 1<<5
};

	class Driver;

	/** @brief One opponent's state relative to the observing Driver.
	 * @details Car, shared SingleCardata and track pointers are borrowed. State
	 * combines OPP_* bits; IGNORE is zero. Distances use meters, speeds m/s and
	 * overlap timers seconds. Predictions are local approximations, not collision guarantees.
	 */
	class Opponent {
	public:
		Opponent();

		/** @brief Bind the borrowed opponent car. */
		void setCarPtr(tCarElt *car) { this->car = car; }
		/** @brief Bind its borrowed shared observation cache. */
		void setCarDataPtr(SingleCardata *cardata) { this->cardata = cardata; }
		/** @brief Bind the shared borrowed native track for relative-distance wrapping. */
		static void setTrackPtr(tTrack *track) { Opponent::track = track; }

		/** @brief Borrow the opponent's TORCS car. */
		tCarElt *getCarPtr() { return car; }
		/** @brief Current OPP_* bit mask; IGNORE is zero. */
		int getState() { return state; }
		/** @brief Estimated distance in meters before catching this opponent. */
		float getCatchDist() { return catchdist; }
		/** @brief Approximate longitudinal gap in meters; negative means behind. */
		float getDistance() { return distance; }
		/** @brief Approximate lateral center separation in meters. */
		float getSideDist() { return sidedist; }
		/** @brief Projected opponent width in meters from the shared cache. */
		float getWidth() { return cardata->getWidthOnTrack(); }
		/** @brief Opponent velocity along the track tangent, in m/s. */
		float getSpeed() { return cardata->getSpeedInTrackDirection(); }
		/** @brief Accumulated overlap/yield timer in seconds. */
		float getOverlapTimer() { return overlaptimer; }
		/** @brief Reclassify relative position, catch/collision risk and overlap timer.
		 * @param[in] s Current situation and simulation time.
		 * @param[in] driver Observer defining the relative coordinate frame.
		 */
		void update(tSituation *s, Driver *driver);
		/** @brief Current decaying collision/overtake filter state. */
		float getBrakeOvertake () { return brake_overtake_filter; }
		/** @brief Reset the collision/overtake filter to one after collision braking. */
		void brakeForCollision () { brake_overtake_filter = 1.0; }

	private:
		/** @brief Opponent's local native distance in meters, converting curve angle. */
		float getDistToSegStart();
		/** @brief Advance/reset the overlap timer from relative lap/position state. */
		void updateOverlapTimer(tSituation *s, tCarElt *mycar);

		float distance;		///< approximation of the real distance, negative if the opponent is behind.
		float catchdist;	///< distance needed to catch the opponent (linear estimate).
		float sidedist;		///< approx distance of center of gravity of the cars.
		int state;			///< State variable to characterize the relation to the opponent, e. g. opponent is behind.
		float overlaptimer;
		float brake_overtake_filter; ///< Check to see.

		tCarElt *car;
		SingleCardata *cardata;		// Pointer to global data about this opponent.

		// class variables.
		static tTrack *track;

		// constants.
		static const float FRONTCOLLDIST;
		static const float BACKCOLLDIST;
		static const float LENGTH_MARGIN;
		static const float SIDE_MARGIN;
		static const float EXACT_DIST;
		static const float LAP_BACK_TIME_PENALTY;
		static const float OVERLAP_WAIT_TIME;
		static const float SPEED_PASS_MARGIN;
		static const float TIME_MARGIN;
	};


	/** @brief Owns the observer's opponent array; borrows cars and the shared car cache. */
	class Opponents {
	public:
		/** @brief Build entries for other cars; all three arguments must outlive their use. */
		Opponents(tSituation *s, Driver *driver, Cardata *cardata);
		~Opponents();

		/** @brief Refresh all entries and relative front/back counts. */
		void update(tSituation *s, Driver *driver);
		/** @brief Borrow the contiguous array of getNOpponents() entries. */
		Opponent *getOpponentPtr() { return opponent; }
		/// Return total number of opponents
		int getNOpponents() { return nopponents; }
		/// Return relative-position count behind; the current count loop does not filter OPP_IGNORE.
		int getNOpponentsBehind() { return nopponents_behind; }
		/// Return relative-position count in front; the current count loop does not filter OPP_IGNORE.
		int getNOpponentsInFront() { return nopponents_infront;}


	private:
		Opponent *opponent;
		int nopponents;
		int nopponents_behind;
		int nopponents_infront;
	};

#endif // _OPPONENT_H_
