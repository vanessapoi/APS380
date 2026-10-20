// -*- Mode: c++ -*-
/***************************************************************************

    file                 : strategy.h
    created              : Wed Sep 22 15:31:51 CET 2004
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
  Pit strategy for drivers. It defines an abstract base class, such that one can easily plug in
  different strategies.
*/

/** @file strategy.h
 * @brief Fuel/repair strategy interfaces independent of the pit maneuver spline.
 * @ingroup olethros_pits
 */
#ifndef _STRATEGY_H_
#define _STRATEGY_H_

#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#include <tgf.h>
#include <track.h>
#include <car.h>
#include <raceman.h>
#include <robottools.h>
#include <robot.h>

#include "driver.h"

// forward declarations
class Opponents;


/** @brief Driver-owned strategy interface; all car/track/situation/opponent arguments are borrowed.
 * @details Strategy decides whether/how much to service, while Pit and Driver
 * execute entry, braking, the stop and exit. Fuel values use TORCS fuel units
 * (liters), damage values use simulator damage units, and speed factors are
 * dimensionless. Implementations mutate their own observed fuel/history state.
 */
class AbstractStrategy {
public:

	virtual ~AbstractStrategy() {};
	/** @brief Write initial fuel into the selected car parameter handle.
	 * @param[in] t Native track and length.
	 * @param[in,out] carParmHandle Selected setup handle used to set fuel.
	 * @param[in] s Session length and type.
	 */
	virtual void setFuelAtRaceStart(tTrack* t, void **carParmHandle, tSituation *s) = 0;
	/// Update internal data at every timestep.
	virtual void update(tCarElt* car, tSituation *s) = 0;
	/// Do we need a pit stop? Can be called less frequently.
	virtual bool needPitstop(tCarElt* car, tSituation *s,
							 Opponents* opponents) = 0;
	/// Return additional fuel in liters, not target total fuel; updates fuel-stop accounting.
	virtual float pitRefuel(tCarElt* car, tSituation *s) = 0;
	/// Return requested repair in simulator damage units.
	virtual int pitRepair(tCarElt* car, tSituation *s) = 0;
	/// Speed factor can depend on fuel economy needs, overtaking.. etc.
	virtual float getSpeedFactor(tCarElt* car, tSituation* s, Opponents* opponents) = 0;
};

/** @brief Fuel-per-lap and damage-threshold strategy used outside race sessions.
 * @details Observes consumption across lap transitions, accounts for refueling,
 * and requests stops when fuel or damage thresholds require service.
 */
class SimpleStrategy : public AbstractStrategy {
public:
	SimpleStrategy();
	~SimpleStrategy();

	virtual void setFuelAtRaceStart(tTrack* t, void **carParmHandle, tSituation *s);
	virtual void update(tCarElt* car, tSituation *s);
	virtual bool needPitstop(tCarElt* car, tSituation *s, Opponents* opponents);
	virtual float pitRefuel(tCarElt* car, tSituation *s);
	virtual int pitRepair(tCarElt* car, tSituation *s);
	virtual float getSpeedFactor(tCarElt* car, tSituation* s, Opponents* opponents);

protected:
	bool fuelchecked;				// Fuel statistics updated.
	float fuelperlap;				// The maximum amount of fuel we needed for a lap.
	float lastpitfuel;				// Amount refueled, special case when we refuel.
	float lastfuel;					// the fuel available when we cross the start lane.
	float expectedfuelperlap;		// Expected fuel per lap (may be very inaccurate).

	static const float MAX_FUEL_PER_METER;	// [kg/m] fuel consumtion.
	static const int PIT_DAMMAGE;			// If damage > we request a pit stop.
};



/** @brief Race strategy extending fuel checks with position-sensitive repair decisions.
 * @details Uses logistic heuristics and opponent estimates, not a solved race-time
 * optimization problem. getSpeedFactor() exposes the current dimensionless pace factor.
 */
class ManagedStrategy : public SimpleStrategy
{
public:
	ManagedStrategy();
	virtual ~ManagedStrategy();
	virtual bool needPitstop(tCarElt* car, tSituation *s, Opponents* opponents);
	virtual float getSpeedFactor(tCarElt* car, tSituation* s, Opponents* opponents);
protected:
	float speed_factor;
	/** @brief Decide whether damage merits service using position, gaps and fuel-stop context. */
	virtual bool RepairDamage(tCarElt* car, Opponents* opponents);

};



#endif // _STRATEGY_H_
