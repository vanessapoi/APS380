/***************************************************************************

    file                 : simu.cpp
    created              : Sun Mar 19 00:07:53 CET 2000
    copyright            : (C) 2000-2017 by Eric Espie, Bernhard Wymann
    email                : torcs@free.fr
    version              : $Id$

 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/

#include <stdlib.h>
#include <stdio.h>
#include <memory.h>
#include <math.h>
#include "aps380_live.h"
#ifdef WIN32
#include <windows.h>
#include <float.h>
#define isnan _isnan
#endif

#include <tgf.h>
#include <robottools.h>
#include "sim.h"

tCar *SimCarTable = 0;
tdble SimDeltaTime;
int SimTelemetry;
static int SimNbCars = 0;

tdble rulesFuelFactor = 1.0f;
tdble rulesDamageFactor = 1.0f;
tdble rulesTireFactor = 0.0f;

/*
 * Check the input control from robots
 */
static void
ctrlCheck(tCar *car)
{
    tTransmission	*trans = &(car->transmission);
    tClutch		*clutch = &(trans->clutch);

    /* sanity check */
#if defined WIN32 || defined sun
    if (isnan(car->ctrl->accelCmd)) car->ctrl->accelCmd = 0;
    if (isnan(car->ctrl->brakeCmd)) car->ctrl->brakeCmd = 0;
    if (isnan(car->ctrl->clutchCmd)) car->ctrl->clutchCmd = 0;
    if (isnan(car->ctrl->steer)) car->ctrl->steer = 0;
#else
    if (isnan(car->ctrl->accelCmd) || isinf(car->ctrl->accelCmd)) car->ctrl->accelCmd = 0;
    if (isnan(car->ctrl->brakeCmd) || isinf(car->ctrl->brakeCmd)) car->ctrl->brakeCmd = 0;
    if (isnan(car->ctrl->clutchCmd) || isinf(car->ctrl->clutchCmd)) car->ctrl->clutchCmd = 0;
    if (isnan(car->ctrl->steer) || isinf(car->ctrl->steer)) car->ctrl->steer = 0;
#endif

    /* When the car is broken try to send it on the track side */
    if (car->carElt->_state & RM_CAR_STATE_BROKEN) {
	car->ctrl->accelCmd = 0.0f;
	car->ctrl->brakeCmd = 0.1f;
	car->ctrl->gear = 0;
	if (car->trkPos.toRight >  car->trkPos.seg->width / 2.0) {
	    car->ctrl->steer = 0.1f;
	} else {
	    car->ctrl->steer = -0.1f;
	}
    } else if (car->carElt->_state & RM_CAR_STATE_ELIMINATED) {
	car->ctrl->accelCmd = 0.0f;
	car->ctrl->brakeCmd = 0.1f;
	car->ctrl->gear = 0;
	if (car->trkPos.toRight >  car->trkPos.seg->width / 2.0) {
	    car->ctrl->steer = 0.1f;
	} else {
	    car->ctrl->steer = -0.1f;
	}
    } else if (car->carElt->_state & RM_CAR_STATE_FINISH) {
	/* when the finish line is passed, continue at "slow" pace */
	car->ctrl->accelCmd = MIN(car->ctrl->accelCmd, 0.20);
	if (car->DynGC.vel.x > 30.0) {
	    car->ctrl->brakeCmd = MAX(car->ctrl->brakeCmd, 0.05);
	}
    }

    /* check boundaries */
    if (car->ctrl->accelCmd > 1.0) {
	car->ctrl->accelCmd = 1.0;
    } else if (car->ctrl->accelCmd < 0.0) {
	car->ctrl->accelCmd = 0.0;
    }
    if (car->ctrl->brakeCmd > 1.0) {
	car->ctrl->brakeCmd = 1.0;
    } else if (car->ctrl->brakeCmd < 0.0) {
	car->ctrl->brakeCmd = 0.0;
    }
    if (car->ctrl->clutchCmd > 1.0) {
	car->ctrl->clutchCmd = 1.0;
    } else if (car->ctrl->clutchCmd < 0.0) {
	car->ctrl->clutchCmd = 0.0;
    }
    if (car->ctrl->steer > 1.0) {
	car->ctrl->steer = 1.0;
    } else if (car->ctrl->steer < -1.0) {
	car->ctrl->steer = -1.0;
    }

    clutch->transferValue = 1.0 - car->ctrl->clutchCmd;
}

/* Initial configuration */
void
SimConfig(tCarElt *carElt, RmInfo *info)
{
    tCar *car = &(SimCarTable[carElt->index]);

    memset(car, 0, sizeof(tCar));

    car->carElt = carElt;
    car->DynGCg = car->DynGC = carElt->_DynGC;
    car->worldPosX = car->DynGCg.pos.x;
    car->worldPosY = car->DynGCg.pos.y;
    car->publishedPosX = car->DynGCg.pos.x;
    car->publishedPosY = car->DynGCg.pos.y;
    carElt->_pos_X_D = carElt->_pos_X;
    carElt->_pos_Y_D = carElt->_pos_Y;
    car->trkPos = carElt->_trkPos;
    car->ctrl   = &carElt->ctrl;
    car->params = carElt->_carHandle;

    SimCarConfig(car);

    SimCarCollideConfig(car, info->track);
    sgMakeCoordMat4(carElt->pub.posMat, carElt->_pos_X, carElt->_pos_Y, carElt->_pos_Z - carElt->_statGC_z,
		    RAD2DEG(carElt->_yaw), RAD2DEG(carElt->_roll), RAD2DEG(carElt->_pitch));
}

/* After pit stop */
void SimReConfig(tCarElt *carElt)
{
	tCar *car = &(SimCarTable[carElt->index]);
	if (carElt->pitcmd.fuel > 0) {
		car->fuel += carElt->pitcmd.fuel;
		if (car->fuel > car->tank) car->fuel = car->tank;
	}

	if (carElt->pitcmd.repair > 0) {
		car->dammage -= carElt->pitcmd.repair;
		if (car->dammage < 0) car->dammage = 0;
	}

	int i;
	SimSteerReConfig(car);
	SimBrakeSystemReConfig(car);
	
	for (i = 0; i < 2; i++) {
		SimWingReConfig(car, i);
		SimAxleReConfig(car, i);
	}

	for (i = 0; i < 4; i++) {
		SimWheelReConfig(car, i);
		if (carElt->pitcmd.tireChange == tCarPitCmd::ALL) {
			SimWheelResetWear(car, i);
		}
	}

	SimTransmissionReConfig(car);
}


static void
RemoveCar(tCar *car, tSituation *s)
{
	int i;
	tCarElt *carElt;
	tTrkLocPos trkPos;
	int trkFlag;
	tdble travelTime;
	tdble dang;

	static tdble PULL_Z_OFFSET = 3.0;
	static tdble PULL_SPD = 0.5;

	carElt = car->carElt;

	if (carElt->_state & RM_CAR_STATE_PULLUP) {
		carElt->_pos_Z += car->restPos.vel.z * SimDeltaTime;
		carElt->_yaw += car->restPos.vel.az * SimDeltaTime;
		carElt->_roll += car->restPos.vel.ax * SimDeltaTime;
		carElt->_pitch += car->restPos.vel.ay * SimDeltaTime;
		sgMakeCoordMat4(carElt->pub.posMat, carElt->_pos_X, carElt->_pos_Y, carElt->_pos_Z - carElt->_statGC_z,
			RAD2DEG(carElt->_yaw), RAD2DEG(carElt->_roll), RAD2DEG(carElt->_pitch));

		if (carElt->_pos_Z > (car->restPos.pos.z + PULL_Z_OFFSET)) {
			carElt->_state &= ~RM_CAR_STATE_PULLUP;
			carElt->_state |= RM_CAR_STATE_PULLSIDE;
			// Moved pullside velocity computation down due to floating point error accumulation.
		}
		return;
	}


	if (carElt->_state & RM_CAR_STATE_PULLSIDE) {
		// Recompute velocity to converge on the parking point without overshooting.
		travelTime = DIST(car->restPos.pos.x, car->restPos.pos.y, carElt->_pos_X_D, carElt->_pos_Y_D) / PULL_SPD;
		car->restPos.vel.x = (car->restPos.pos.x - carElt->_pos_X_D) / travelTime;
		car->restPos.vel.y = (car->restPos.pos.y - carElt->_pos_Y_D) / travelTime;

		carElt->_pos_X_D += (double)car->restPos.vel.x * SimDeltaTime;
		carElt->_pos_Y_D += (double)car->restPos.vel.y * SimDeltaTime;
		carElt->_pos_X = (tdble)carElt->_pos_X_D;
		carElt->_pos_Y = (tdble)carElt->_pos_Y_D;
		sgMakeCoordMat4(carElt->pub.posMat, carElt->_pos_X, carElt->_pos_Y, carElt->_pos_Z - carElt->_statGC_z,
			RAD2DEG(carElt->_yaw), RAD2DEG(carElt->_roll), RAD2DEG(carElt->_pitch));

		if ((fabs(car->restPos.pos.x - carElt->_pos_X_D) < 0.5) && (fabs(car->restPos.pos.y - carElt->_pos_Y_D) < 0.5)) {
			carElt->_state &= ~RM_CAR_STATE_PULLSIDE;
			carElt->_state |= RM_CAR_STATE_PULLDN;
		}
		return;
	}


	if (carElt->_state & RM_CAR_STATE_PULLDN) {
		carElt->_pos_Z -= car->restPos.vel.z * SimDeltaTime;
		sgMakeCoordMat4(carElt->pub.posMat, carElt->_pos_X, carElt->_pos_Y, carElt->_pos_Z - carElt->_statGC_z,
			RAD2DEG(carElt->_yaw), RAD2DEG(carElt->_roll), RAD2DEG(carElt->_pitch));

		if (carElt->_pos_Z < car->restPos.pos.z) {
			carElt->_state &= ~RM_CAR_STATE_PULLDN;
			carElt->_state |= RM_CAR_STATE_OUT;
		}
		return;
	}


	if (carElt->_state & (RM_CAR_STATE_NO_SIMU & ~RM_CAR_STATE_PIT)) {
		return;
	}

	if (carElt->_state & RM_CAR_STATE_PIT) {
		if ((s->_maxDammage) && (car->dammage > s->_maxDammage)) {
			// Broken during pit stop.
			carElt->_state &= ~RM_CAR_STATE_PIT;
			carElt->_pit->pitCarIndex = TR_PIT_STATE_FREE;
		} else {
			return;
		}
	}

	if ((s->_maxDammage) && (car->dammage > s->_maxDammage)) {
		carElt->_state |= RM_CAR_STATE_BROKEN;
	} else {
		carElt->_state |= RM_CAR_STATE_OUTOFGAS;
	}

	carElt->_gear = car->transmission.gearbox.gear = 0;
	carElt->_enginerpm = car->engine.rads = 0;

	if (!(carElt->_state & RM_CAR_STATE_DNF)) {
		if (fabs(carElt->_speed_x) > 1.0) {
			return;
		}
	}

	carElt->_state |= RM_CAR_STATE_PULLUP;
	// RM_CAR_STATE_NO_SIMU evaluates to > 0 from here, so we remove the car from the
	// collision detection.
	SimCollideRemoveCar(car, s->_ncars);

	carElt->priv.simcollision = carElt->priv.collision = car->collision = 0;
	for(i = 0; i < 4; i++) {
		carElt->_skid[i] = 0;
		carElt->_wheelSpinVel(i) = 0;
		carElt->_brakeTemp(i) = 0;
	}

	carElt->pub.DynGC = car->DynGC;
	carElt->_speed_x = 0;

	// Compute the target zone for the wrecked car.
	trkPos = car->trkPos;
	if (trkPos.toRight >  trkPos.seg->width / 2.0) {
		while (trkPos.seg->lside != 0) {
			trkPos.seg = trkPos.seg->lside;
		}
		trkPos.toLeft = -3.0;
		trkFlag = TR_TOLEFT;
	} else {
		while (trkPos.seg->rside != 0) {
			trkPos.seg = trkPos.seg->rside;
		}
		trkPos.toRight = -3.0;
		trkFlag = TR_TORIGHT;
	}

	trkPos.type = TR_LPOS_SEGMENT;
	RtTrackLocal2Global(&trkPos, &(car->restPos.pos.x), &(car->restPos.pos.y), trkFlag);
	car->restPos.pos.z = RtTrackHeightL(&trkPos) + carElt->_statGC_z;
	car->restPos.pos.az = RtTrackSideTgAngleL(&trkPos);
	car->restPos.pos.ax = 0;
	car->restPos.pos.ay = 0;

	car->restPos.vel.z = PULL_SPD;
	travelTime = (car->restPos.pos.z + PULL_Z_OFFSET - carElt->_pos_Z) / car->restPos.vel.z;
	dang = car->restPos.pos.az - carElt->_yaw;
	NORM_PI_PI(dang);
	car->restPos.vel.az = dang / travelTime;
	dang = car->restPos.pos.ax - carElt->_roll;
	NORM_PI_PI(dang);
	car->restPos.vel.ax = dang / travelTime;
	dang = car->restPos.pos.ay - carElt->_pitch;
	NORM_PI_PI(dang);
	car->restPos.vel.ay = dang / travelTime;
}



void
SimUpdate(tSituation *s, double deltaTime, int telemetry)
{
	int i;
	int ncar;
	tCarElt *carElt;
	tCar *car;
	
	SimDeltaTime = deltaTime;
	SimTelemetry = telemetry;
    const bool aps380ActiveRace =
        (s->_raceState & (RM_RACE_RUNNING | RM_RACE_FINISHING | RM_RACE_ENDED)) != 0
        && (s->_raceState & RM_RACE_PAUSED) == 0;
    if (aps380_live::sampleReady(s->currentTime, aps380ActiveRace))
        aps380_live::pace(s->currentTime);
	for (ncar = 0; ncar < s->_ncars; ncar++) {
		SimCarTable[ncar].collision = 0;
		SimCarTable[ncar].blocked = 0;
	}
	
	for (ncar = 0; ncar < s->_ncars; ncar++) {
		car = &(SimCarTable[ncar]);
		carElt = car->carElt;
	
		if (carElt->_state & RM_CAR_STATE_NO_SIMU) {
			RemoveCar(car, s);
			continue;
		} else if (((s->_maxDammage) && (car->dammage > s->_maxDammage)) ||
			(car->fuel == 0) ||
			(car->carElt->_state & RM_CAR_STATE_ELIMINATED))  {
			RemoveCar(car, s);
			if (carElt->_state & RM_CAR_STATE_NO_SIMU) {
				continue;
			}
		}
	
		if (s->_raceState & RM_RACE_PRESTART) {
			car->ctrl->gear = 0;
		}
		
		SimAtmosphereUpdate(car, s);
		CHECK(car);
		ctrlCheck(car);
		CHECK(car);
		SimSteerUpdate(car);
		CHECK(car);
		if (car->engine.electric && !(s->_raceState & RM_RACE_PRESTART)) {
			// Forward-only experiment: no simulated clutch or multi-gear shifts.
			car->ctrl->gear = 1;
			car->ctrl->clutchCmd = 0.0;
			car->transmission.clutch.transferValue = 1.0;
		}
		SimGearboxUpdate(car);
		CHECK(car);
		if (car->engine.electric) {
			tEngine &e = car->engine;
			const bool active = s->currentTime >= 0.0 && !(s->_raceState & RM_RACE_PRESTART);
			e.evMotorOmega = e.rads;
			const bool engaged = active && car->transmission.gearbox.gear != 0 &&
				!(carElt->_state & (RM_CAR_STATE_BROKEN | RM_CAR_STATE_ELIMINATED));
			aps380::EvStep step = aps380::electricStep(e.ev, e.evEnergyWh, e.rads,
				fabs(car->DynGC.vel.x), car->ctrl->accelCmd, active ? SimDeltaTime : 0.0, engaged, car->ctrl->brakeCmd);
			e.Tq = (tdble)step.torque;
			e.evPackPower = step.packPower;
			e.evShaftPower = step.shaftPower;
			if (active) {
				e.evEnergyWh = step.energyWh;
				e.evUsedWh += MAX(step.packPower, 0.0)*SimDeltaTime/3600.0;
				e.evRecoveredWh += MAX(-step.packPower, 0.0)*SimDeltaTime/3600.0;
			}
		}
		SimEngineUpdateTq(car);
		CHECK(car);
	
		if (!(s->_raceState & RM_RACE_PRESTART)) {
	
			SimCarUpdateWheelPos(car);
			CHECK(car);
			SimBrakeSystemUpdate(car);
			CHECK(car);
			SimAeroUpdate(car, s);
			CHECK(car);
			for (i = 0; i < 2; i++){
				SimWingUpdate(car, i, s);
			}
			CHECK(car);
			for (i = 0; i < 4; i++){
				SimWheelUpdateRide(car, i);
			}
			CHECK(car);
			for (i = 0; i < 2; i++){
				SimAxleUpdate(car, i);
			}
			CHECK(car);
			for (i = 0; i < 4; i++){
				SimWheelUpdateForce(car, i);
				SimWheelUpdateTire(car, i);
				
				// Reset tire damage in pre simulation state (when the model is thrown in the world) 
				if (s->_raceState == 0) {
					SimWheelResetWear(car, i);
				}
			}
			CHECK(car);
			SimTransmissionUpdate(car);
			CHECK(car);
			SimWheelUpdateRotation(car);
			CHECK(car);
			SimCarUpdate(car, s);
			CHECK(car);
		} else {
			SimEngineUpdateRpm(car, 0.0);
		}
	}
	
	SimCarCollideCars(s);
	
	/* printf ("%f - ", s->currentTime); */
	
	for (ncar = 0; ncar < s->_ncars; ncar++) {
		car = &(SimCarTable[ncar]);
		CHECK(car);
		carElt = car->carElt;
	
		if (carElt->_state & RM_CAR_STATE_NO_SIMU) {
			continue;
		}
	
		CHECK(car);
		SimCarUpdate2(car, s); /* telemetry */
	
		/* copy back the data to carElt */
		car->worldPosX += (double)car->DynGCg.pos.x - car->publishedPosX;
		car->worldPosY += (double)car->DynGCg.pos.y - car->publishedPosY;
		car->publishedPosX = car->DynGCg.pos.x;
		car->publishedPosY = car->DynGCg.pos.y;
		carElt->pub.DynGC = car->DynGC;
		carElt->pub.DynGCg = car->DynGCg;
		carElt->_pos_X_D = car->worldPosX + (double)carElt->_pos_X - car->DynGCg.pos.x;
		carElt->_pos_Y_D = car->worldPosY + (double)carElt->_pos_Y - car->DynGCg.pos.y;
		carElt->pub.speed = car->speed;
		sgMakeCoordMat4(carElt->pub.posMat, carElt->_pos_X, carElt->_pos_Y, carElt->_pos_Z - carElt->_statGC_z,
				RAD2DEG(carElt->_yaw), RAD2DEG(carElt->_roll), RAD2DEG(carElt->_pitch));
		carElt->_trkPos = car->trkPos;

		for (i = 0; i < 4; i++) {
			tWheelState* const wheelState = &(carElt->priv.wheel[i]);
			const tWheel* const wheel = &(car->wheel[i]);

			wheelState->relPos = wheel->relPos;
			wheelState->seg = wheel->trkPos.seg;
			wheelState->brakeTemp = wheel->brake.temp;
			wheelState->currentGraining = wheel->currentGraining;
			wheelState->currentPressure = wheel->currentPressure;
			wheelState->currentTemperature = wheel->currentTemperature;
			wheelState->currentWear = wheel->currentWear;

			carElt->pub.corner[i] = car->corner[i].pos;
		}

		carElt->_gear = car->transmission.gearbox.gear;
		carElt->_enginerpm = car->engine.electric ? fabs(car->engine.rads) : car->engine.rads;
		carElt->_fuel = car->fuel;
		carElt->priv.collision |= car->collision;
		carElt->priv.simcollision = car->collision;
		carElt->_dammage = car->dammage;
		carElt->priv.localPressure = car->localPressure;
		carElt->priv.repCmdMaxClicks = car->brkSyst.repCmdMaxClicks;
		carElt->priv.brakeRepartitionCmd = car->ctrl->brakeRepartitionCmd;
		if (car->engine.electric && aps380_live::sampleReady(s->currentTime, aps380ActiveRace)) {
			tEngine &e = car->engine;
			e.evCollision |= car->collision;
			if (!e.evFile) {
				// Never replace a previous session, including within the same process.
				char path[256];
				for (int recording = 1; recording < 100000; ++recording) {
					snprintf(path, sizeof(path), "telemetry/aps380_ev_%d_car%d.csv", recording, ncar);
					FILE *existing = fopen(path, "r");
					if (existing) { fclose(existing); continue; }
					e.evFile = fopen(path, "w");
					if (e.evFile) {
						char effectiveConfig[256];
						snprintf(effectiveConfig, sizeof(effectiveConfig), "telemetry/aps380_ev_%d_car%d.xml", recording, ncar);
						GfParmWriteFile(effectiveConfig, car->params, "APS380 effective EV configuration");
					}
					break;
				}
				if (e.evFile) fprintf(e.evFile, "time_s,speed_mps,throttle,brake,car_id,profile_id,longitudinal_mps,lateral_mps,vertical_mps,damage,collision,motor_radps,motor_torque_Nm,motor_power_W,pack_power_W,pack_voltage_V,pack_current_A,soc,pack_energy_Wh,discharge_Wh,charge_Wh\n");
			}
			if (e.evLastLogTime < 0.0 || s->currentTime-e.evLastLogTime >= .0199) {
                char liveSample[2048];
				snprintf(liveSample, sizeof(liveSample), "%.6f,%.6f,%.6f,%.6f,%s,%s,%.6f,%.6f,%.6f,%d,%d,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.9f,%.9f,%.9f,%.9f\n",
					s->currentTime, (double)car->speed, (double)car->ctrl->accelCmd, (double)car->ctrl->brakeCmd,
					carElt->_carName, GfParmGetStr(car->params, "Electric Powertrain", "profile id", "unknown"),
					(double)car->DynGC.vel.x, (double)car->DynGC.vel.y, (double)car->DynGC.vel.z,
					car->dammage, e.evCollision, e.evMotorOmega, (double)e.Tq, e.evShaftPower,
					e.evPackPower, e.ev.voltage, e.evPackPower/e.ev.voltage, e.evEnergyWh/e.ev.capacityWh,
					e.evEnergyWh, e.evUsedWh, e.evRecoveredWh);
                if (e.evFile) { fputs(liveSample, e.evFile); fflush(e.evFile); }
                aps380_live::send(ncar, liveSample);
				e.evLastLogTime = s->currentTime;
				e.evCollision = 0;
			}
		}
	}
}


void
SimInit(int nbcars, tTrack* track, tdble fuelFactor, tdble damageFactor, tdble tireFactor)
{
	rulesFuelFactor = fuelFactor;
	rulesDamageFactor = damageFactor;
	rulesTireFactor = tireFactor;
    aps380_live::init(nbcars);
    SimNbCars = nbcars;
    SimCarTable = (tCar*)calloc(nbcars, sizeof(tCar));
    SimCarCollideInit(track);
}

void
SimShutdown(void)
{
    tCar *car;
    int	 ncar;

    aps380_live::shutdown();
    SimCarCollideShutdown(SimNbCars);
    if (SimCarTable) {
	for (ncar = 0; ncar < SimNbCars; ncar++) {
	    car = &(SimCarTable[ncar]);
	    SimEngineShutdown(car);
	}
	free(SimCarTable);
	SimCarTable = 0;
    }
}


bool SimAdjustPitCarSetupParam(tCarPitSetupValue* v)
{
	// If min == max there is nothing to adjust
	if (fabs(v->max - v->min) >= 0.0001f) {
		// Ensure that value is in intended borders
		if (v->value > v->max) {
			v->value = v->max;
		} else if (v->value < v->min) {
			v->value = v->min;
		}
		return true;
	}

	v->value = v->max;
	return false;
}
