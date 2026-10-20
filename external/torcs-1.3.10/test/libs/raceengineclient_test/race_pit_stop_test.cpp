/***************************************************************************

    file                 : race_pit_stop_test.cpp
    created              : Sun Jul 12 20:00:00 CET 2026
    copyright            : (C) 2026 by Bernhard Wymann
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

/** @file
    Unit tests for pit stop command normalization and service time.
*/

#include <cstring>

#include <gtest/gtest.h>

#include "racepit.h"


static const float kEps = 1e-5f;


static void
initCar(tCarElt *car, tdble fuel, tdble tank, int damage, tdble pitFuel, int pitRepair,
		tdble penaltyTime = 0.0f)
{
	memset(car, 0, sizeof(*car));
	car->_fuel = fuel;
	car->_tank = tank;
	car->_dammage = damage;
	car->_pitFuel = pitFuel;
	car->_pitRepair = pitRepair;
	car->_penaltyTime = penaltyTime;
}


static tRmRaceRules
makeRaceRules(void)
{
	tRmRaceRules rules;
	memset(&rules, 0, sizeof(rules));
	rules.pitstopBaseTime = 2.0f;
	rules.refuelFuelFlow = 8.0f;
	rules.damageRepairFactor = 0.007f;
	return rules;
}


TEST(RacePitStopTest, CapsFuelToRemainingTankCapacityBeforeTiming)
{
	tCarElt car;
	initCar(&car, 20.0f, 70.0f, 0, 1000.0f, 0, 3.0f);
	tRmRaceRules rules = makeRaceRules();

	ReNormalizePitStop(&car);
	tdble pitTime = ReComputePitStopServiceTime(&car, &rules);

	EXPECT_NEAR(car._pitFuel, 50.0f, kEps);
	EXPECT_NEAR(pitTime, 2.0f + 50.0f / 8.0f + 3.0f, kEps);
}


TEST(RacePitStopTest, CapsRepairToCurrentDamageBeforeTiming)
{
	tCarElt car;
	initCar(&car, 10.0f, 60.0f, 1234, 0.0f, 9999);
	tRmRaceRules rules = makeRaceRules();

	ReNormalizePitStop(&car);
	tdble pitTime = ReComputePitStopServiceTime(&car, &rules);

	EXPECT_EQ(1234, car._pitRepair);
	EXPECT_NEAR(pitTime, 2.0f + 1234.0f * 0.007f, kEps);
}


TEST(RacePitStopTest, NegativeFuelAndRepairAreNoOpsBeforeTiming)
{
	tCarElt car;
	initCar(&car, 10.0f, 60.0f, 500, -100.0f, -20);
	tRmRaceRules rules = makeRaceRules();

	ReNormalizePitStop(&car);
	tdble pitTime = ReComputePitStopServiceTime(&car, &rules);

	EXPECT_NEAR(car._pitFuel, 0.0f, kEps);
	EXPECT_EQ(0, car._pitRepair);
	EXPECT_NEAR(pitTime, 2.0f, kEps);
}


TEST(RacePitStopTest, KeepsValidFuelAndRepairBeforeTiming)
{
	tCarElt car;
	initCar(&car, 10.0f, 60.0f, 500, 12.0f, 300, 4.0f);
	tRmRaceRules rules = makeRaceRules();

	ReNormalizePitStop(&car);
	tdble pitTime = ReComputePitStopServiceTime(&car, &rules);

	EXPECT_NEAR(car._pitFuel, 12.0f, kEps);
	EXPECT_EQ(300, car._pitRepair);
	EXPECT_NEAR(pitTime, 2.0f + 12.0f / 8.0f + 300.0f * 0.007f + 4.0f, kEps);
}
