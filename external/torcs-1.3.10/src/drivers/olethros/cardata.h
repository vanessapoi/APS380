// -*- Mode: c++; tab-width: 4; c-basic-offset: 4 -*-
/***************************************************************************

    file                 : cardata.h
    created              : Thu Sep 23 12:31:33 CET 2004
    copyright            : (C) 2004 Bernhard Wymann
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

/*
  This class holds global facts about cars, therefore no data relative to
  each other (for that is the class Opponents/Opponent responsible).
*/

/** @file cardata.h
 * @brief Shared absolute car observations, independent of the observing driver.
 * @ingroup olethros_opponents
 */

#ifndef _OLETHROS_CARDATA_H_
#define _OLETHROS_CARDATA_H_

#include <stdio.h>
#include <math.h>
#include <car.h>
#include <robottools.h>
#include <raceman.h>

#include "linalg.h"
/** @brief Cached speed, heading and projected width for one borrowed TORCS car.
 * @details init() must precede update(). No opponent-relative quantities are
 * stored here; those belong to Opponent.
 */
class SingleCardata {
 public:
	SingleCardata() {
		speed = 0.0;
		width = 1.0;
		trackangle = 0.0;
		angle = 0.0;
		car = NULL;
	}
	/** @brief Bind the borrowed car; does not take ownership or refresh observations. */
	inline void init(CarElt *car) { this->car = car; }

	/** @brief Cached signed velocity along the track tangent, in m/s. */
	inline float getSpeedInTrackDirection() {
		return speed;
	}
	/** @brief Car's projected lateral extent on the track, in meters. */
	inline float getWidthOnTrack() { return width; }
	/** @brief Native track heading in world radians. */
	inline float getTrackangle() { return trackangle; }
	/** @brief Wrapped native tangent minus car yaw, in radians. */
	inline float getCarAngle() { return angle; }
	
	/** @brief Compare borrowed car identity, not race number or driver index. */
	inline bool thisCar(tCarElt *car) { return (car == this->car); }

	/** @brief Refresh all cached observations from the bound car and its native track position. */
	void update();

 protected:
	static float getSpeed(tCarElt *car, float trackangle);

	float speed;		// speed in direction of the track.
	float width;		// the cars needed width on the track.
	float trackangle;	// Track angle at the opponents position.
	float angle;		// The angle of the car relative to the track tangent.

	tCarElt *car;		// For identification.
};


/** @brief Owner of the per-car cache array shared by all live Olethros instances.
 * @details Driver coordinates updates once per simulation time. findCar()
 * returns borrowed storage invalidated when this container is destroyed.
 */
class Cardata {
 public:
	/** @brief Allocate/cache every car in the initial situation; the cars remain TORCS-owned. */
	Cardata(tSituation* s);
	~Cardata();
	/** @brief Refresh each cache entry; caller controls simulation-time deduplication. */
	void update();
	/** @brief Find borrowed cache storage for car, or NULL if not represented. */
	SingleCardata *findCar(tCarElt *car);

 protected:
	SingleCardata *data;	// Array with car data.
	int ncars;				// # of elements in data.
};



#endif // _OLETHROS_CARDATA_H_
