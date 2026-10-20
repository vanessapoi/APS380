/***************************************************************************

    file                 : race_penalties_test.cpp
    created              : Mon Jun  8 20:00:00 CET 2026
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
    Unit tests for race time penalty application and result ordering.
*/

#include <cstring>

#include <gtest/gtest.h>

#include "racepenalties.h"


static const float kEps = 1e-5f;


static void
initCar(tCarElt *car, int laps, double curTime, tdble penaltyTime, int pos, int damage = 0)
{
	memset(car, 0, sizeof(*car));
	GF_TAILQ_INIT(&(car->_penaltyList));
	car->_laps = laps;
	car->_curTime = curTime;
	car->_penaltyTime = penaltyTime;
	car->_pos = pos;
	car->_dammage = damage;
}


static void
initSituation(tSituation *s, tCarElt **cars, int nCars, int totLaps = 10, int maxDamage = 10000)
{
	memset(s, 0, sizeof(*s));
	s->_ncars = nCars;
	s->_totLaps = totLaps;
	s->_maxDammage = maxDamage;
	s->cars = cars;
}


static tTrackPitInfo
makePitInfo(int type = TR_PIT_ON_TRACK_SIDE, tdble speedLimit = 42.0f)
{
	tTrackPitInfo pits;
	memset(&pits, 0, sizeof(pits));
	pits.type = type;
	pits.nMaxPits = 2;
	pits.len = 42.0f;
	pits.speedLimit = speedLimit;
	return pits;
}


static void
addPenalty(tCarElt *car, tCarPenalty *penalty, int type)
{
	memset(penalty, 0, sizeof(*penalty));
	penalty->penalty = type;
	GF_TAILQ_INSERT_TAIL(&(car->_penaltyList), penalty, link);
}


TEST(RacePenaltiesTest, LeavesCleanRaceOrderUnchanged)
{
	tCarElt first;
	tCarElt second;
	tCarElt lapped;
	initCar(&first, 6, 100.0, 0.0f, 1);
	initCar(&second, 6, 101.0, 0.0f, 2);
	initCar(&lapped, 5, 80.0, 0.0f, 3);
	tCarElt *cars[] = {&first, &second, &lapped};
	tSituation s;
	initSituation(&s, cars, 3);
	tTrackPitInfo pits = makePitInfo(TR_PIT_NONE);

	ReApplyRaceTimePenalties(&s, &pits);

	EXPECT_EQ(&first, cars[0]);
	EXPECT_EQ(&second, cars[1]);
	EXPECT_EQ(&lapped, cars[2]);
	EXPECT_EQ(1, first._pos);
	EXPECT_EQ(2, second._pos);
	EXPECT_EQ(3, lapped._pos);
}


TEST(RacePenaltiesTest, MovesPenalizedCarBehindSameLapOpponent)
{
	tCarElt penalized;
	tCarElt opponent;
	initCar(&penalized, 6, 100.0, 10.0f, 1);
	initCar(&opponent, 6, 105.0, 0.0f, 2);
	tCarElt *cars[] = {&penalized, &opponent};
	tSituation s;
	initSituation(&s, cars, 2);
	tTrackPitInfo pits = makePitInfo(TR_PIT_NONE);

	ReApplyRaceTimePenalties(&s, &pits);

	EXPECT_EQ(&opponent, cars[0]);
	EXPECT_EQ(&penalized, cars[1]);
	EXPECT_EQ(1, opponent._pos);
	EXPECT_EQ(2, penalized._pos);
}


TEST(RacePenaltiesTest, KeepsPenalizedCarAheadWhenAdjustedTimeIsStillBetter)
{
	tCarElt penalized;
	tCarElt opponent;
	initCar(&penalized, 6, 100.0, 3.0f, 1);
	initCar(&opponent, 6, 105.0, 0.0f, 2);
	tCarElt *cars[] = {&penalized, &opponent};
	tSituation s;
	initSituation(&s, cars, 2);
	tTrackPitInfo pits = makePitInfo(TR_PIT_NONE);

	ReApplyRaceTimePenalties(&s, &pits);

	EXPECT_EQ(&penalized, cars[0]);
	EXPECT_EQ(&opponent, cars[1]);
	EXPECT_EQ(1, penalized._pos);
	EXPECT_EQ(2, opponent._pos);
}


TEST(RacePenaltiesTest, MovesPenalizedCarDownMultipleSameLapPlaces)
{
	tCarElt penalized;
	tCarElt second;
	tCarElt third;
	tCarElt fourth;
	initCar(&penalized, 6, 100.0, 35.0f, 1);
	initCar(&second, 6, 110.0, 0.0f, 2);
	initCar(&third, 6, 120.0, 0.0f, 3);
	initCar(&fourth, 6, 130.0, 0.0f, 4);
	tCarElt *cars[] = {&penalized, &second, &third, &fourth};
	tSituation s;
	initSituation(&s, cars, 4);
	tTrackPitInfo pits = makePitInfo(TR_PIT_NONE);

	ReApplyRaceTimePenalties(&s, &pits);

	EXPECT_EQ(&second, cars[0]);
	EXPECT_EQ(&third, cars[1]);
	EXPECT_EQ(&fourth, cars[2]);
	EXPECT_EQ(&penalized, cars[3]);
	EXPECT_EQ(1, second._pos);
	EXPECT_EQ(2, third._pos);
	EXPECT_EQ(3, fourth._pos);
	EXPECT_EQ(4, penalized._pos);
}


TEST(RacePenaltiesTest, DoesNotMovePenalizedCarBehindLowerLapOpponent)
{
	tCarElt penalized;
	tCarElt lapped;
	initCar(&penalized, 6, 100.0, 1000.0f, 1);
	initCar(&lapped, 5, 50.0, 0.0f, 2);
	tCarElt *cars[] = {&penalized, &lapped};
	tSituation s;
	initSituation(&s, cars, 2);
	tTrackPitInfo pits = makePitInfo(TR_PIT_NONE);

	ReApplyRaceTimePenalties(&s, &pits);

	EXPECT_EQ(&penalized, cars[0]);
	EXPECT_EQ(&lapped, cars[1]);
	EXPECT_EQ(1, penalized._pos);
	EXPECT_EQ(2, lapped._pos);
}


TEST(RacePenaltiesTest, KeepsStableOrderForEqualAdjustedTimes)
{
	tCarElt penalized;
	tCarElt opponent;
	initCar(&penalized, 6, 100.0, 10.0f, 1);
	initCar(&opponent, 6, 110.0, 0.0f, 2);
	tCarElt *cars[] = {&penalized, &opponent};
	tSituation s;
	initSituation(&s, cars, 2);
	tTrackPitInfo pits = makePitInfo(TR_PIT_NONE);

	ReApplyRaceTimePenalties(&s, &pits);

	EXPECT_EQ(&penalized, cars[0]);
	EXPECT_EQ(&opponent, cars[1]);
	EXPECT_EQ(1, penalized._pos);
	EXPECT_EQ(2, opponent._pos);
}


TEST(RacePenaltiesTest, AccumulatesMultiplePendingPitPenaltiesForOneCar)
{
	tCarElt car;
	initCar(&car, 6, 100.0, 2.0f, 1);
	tCarPenalty driveThrough1;
	tCarPenalty driveThrough2;
	tCarPenalty stopAndGo;
	addPenalty(&car, &driveThrough1, RM_PENALTY_DRIVETHROUGH);
	addPenalty(&car, &driveThrough2, RM_PENALTY_DRIVETHROUGH);
	addPenalty(&car, &stopAndGo, RM_PENALTY_STOPANDGO);
	tCarElt *cars[] = {&car};
	tSituation s;
	initSituation(&s, cars, 1);
	tTrackPitInfo pits = makePitInfo(TR_PIT_ON_TRACK_SIDE, 42.0f);

	ReApplyRaceTimePenalties(&s, &pits);

	// With two 42m pits and a 42m/s pit limit, the pit-lane delta is exactly 1s.
	EXPECT_NEAR(car._penaltyTime, 2.0f + 11.0f + 11.0f + 17.0f, kEps);
}


TEST(RacePenaltiesTest, DoesNotConvertPendingPitPenaltiesWithoutOnTrackSidePits)
{
	tCarElt car;
	initCar(&car, 6, 100.0, 5.0f, 1);
	tCarPenalty driveThrough;
	addPenalty(&car, &driveThrough, RM_PENALTY_DRIVETHROUGH);
	tCarElt *cars[] = {&car};
	tSituation s;
	initSituation(&s, cars, 1);
	tTrackPitInfo pits = makePitInfo(TR_PIT_NONE);

	ReApplyRaceTimePenalties(&s, &pits);

	EXPECT_NEAR(car._penaltyTime, 5.0f, kEps);
}


TEST(RacePenaltiesTest, UsesBasePenaltyWhenPitSpeedDeltaIsInvalid)
{
	tCarElt car;
	initCar(&car, 6, 100.0, 0.0f, 1);
	tCarPenalty driveThrough;
	tCarPenalty stopAndGo;
	addPenalty(&car, &driveThrough, RM_PENALTY_DRIVETHROUGH);
	addPenalty(&car, &stopAndGo, RM_PENALTY_STOPANDGO);
	tCarElt *cars[] = {&car};
	tSituation s;
	initSituation(&s, cars, 1);
	tTrackPitInfo pits = makePitInfo(TR_PIT_ON_TRACK_SIDE, 100.0f);

	ReApplyRaceTimePenalties(&s, &pits);

	EXPECT_NEAR(car._penaltyTime, 10.0f + 16.0f, kEps);
}


TEST(RacePenaltiesTest, DoesNotReorderWreckedCarsByPenaltyTime)
{
	tCarElt wrecked;
	tCarElt opponent;
	initCar(&wrecked, 6, 100.0, 20.0f, 1, 101);
	initCar(&opponent, 6, 105.0, 0.0f, 2, 0);
	tCarElt *cars[] = {&wrecked, &opponent};
	tSituation s;
	initSituation(&s, cars, 2, 10, 100);
	tTrackPitInfo pits = makePitInfo(TR_PIT_NONE);

	ReApplyRaceTimePenalties(&s, &pits);

	EXPECT_EQ(&wrecked, cars[0]);
	EXPECT_EQ(&opponent, cars[1]);
	EXPECT_EQ(1, wrecked._pos);
	EXPECT_EQ(2, opponent._pos);
}
