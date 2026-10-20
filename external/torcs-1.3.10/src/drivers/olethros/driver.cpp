
/***************************************************************************

    file                 : driver.cpp
    created              : Thu Dec 20 01:21:49 CET 2002
    copyright            : (C) 2002-2026 Bernhard Wymann, Christos Dimitrakakis
    email                : berniw@bluewin.ch, dimitrak@idiap.ch

***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/

/**
   \file driver.cpp
   
   \brief High-level driver implementation.
   @ingroup olethros_control

   This file was derived from Bernhard's driver.cpp for the BT robot,
   with added bits for learning, plus some modifications to make driving
   smoother. The current version retains a regular PlanningMesh for runtime
   geometry queries while using native segment IDs for surfaces and learning.
   See README.md for the selected control order and planning/learning contracts.
*/
#include "driver.h"
#include <learning/ann_policy.h>
#include <learning/MathFunctions.h>
#include <stdlib.h>
#include <cmath>
#include <portability.h>
#include "PlanningMesh.h"
#include "Trajectory.h"


    const float Driver::MAX_UNSTUCK_ANGLE = 15.0/180.0*PI;		///< [radians] If the angle of the car on the track is smaller, we assume we are not stuck.
    const float Driver::UNSTUCK_TIME_LIMIT = 2.0f;				///< [s] We try to get unstuck after this time.
    const float Driver::MAX_UNSTUCK_SPEED = 5.0f;				///< [m/s] Below this speed we consider being stuck.
    const float Driver::MIN_UNSTUCK_DIST = 2.0f;					///< [m] If we are closer to the middle we assume to be not stuck.
    const float Driver::G = 9.81f;								///< [m/(s*s)] Welcome on Earth.
    const float Driver::FULL_ACCEL_MARGIN = 3.0f;				///< [m/s] Margin reduce oscillation of brake/acceleration.
    const float Driver::SHIFT = 0.98f;							///< [-] (% of rpmredline) When do we like to shift gears.
    const float Driver::SHIFT_MARGIN = 4.0f;						///< [m/s] Avoid oscillating gear changes.
    const float Driver::ABS_SLIP = 2.0f;							///< [m/s] range [0..10]
    const float Driver::ABS_RANGE = 5.0f;						///< [m/s] range [0..10]
    const float Driver::ABS_MINSPEED = 3.0f;						///< [m/s] Below this speed the ABS is disabled (numeric, division by small numbers).
    const float Driver::TCL_SLIP = 2.0f;							///< [m/s] range [0..10]
    const float Driver::TCL_RANGE = 10.0f;						///< [m/s] range [0..10]
    const float Driver::LOOKAHEAD_CONST = 17.0f;					///< [m]
    const float Driver::LOOKAHEAD_FACTOR = 0.33f;				///< [-]
    const float Driver::WIDTHDIV = 3.0f;							///< [-] Defines the percentage of the track to use (2/WIDTHDIV).
    const float Driver::SIDECOLL_MARGIN = 3.0f;					///< [m] Distance between car centers to avoid side collisions.
    const float Driver::BORDER_OVERTAKE_MARGIN = 0.5f;			///< [m]
    const float Driver::OVERTAKE_OFFSET_SPEED = 2.0f;			///< [m/s] Offset change speed.
    const float Driver::OVERTAKE_TIME = 2.0f;			        ///< [s] Approach time to consider overtaking.
    const float Driver::PIT_LOOKAHEAD = 6.0f;					///< [m] Lookahead to stop in the pit.
    const float Driver::PIT_MU = 0.4f;							///< [-] Friction of pit concrete.
    const float Driver::MAX_SPEED = 84.0f;						///< [m/s] Speed to compute the percentage of brake to apply.
    const float Driver::MAX_FUEL_PER_METER = 0.0008f;			///< [liter/m] fuel consumtion.
    const float Driver::CLUTCH_SPEED = 5.0f;						///< [m/s]
    const float Driver::CENTERDIV = 0.1f;						///< [-] (factor) [0.01..0.6].
    const float Driver::DISTCUTOFF = 200.0f;						///< [m] How far to look, terminate while loops.
    const float Driver::MAX_INC_FACTOR = 5.0f;					///< [m] Increment faster if speed is slow [1.0..10.0].
    const float Driver::CATCH_FACTOR = 10.0f;					///< [-] select MIN(catchdist, dist*CATCH_FACTOR) to overtake.
    const float Driver::CLUTCH_FULL_MAX_TIME = 1.0f;				///< [s] Time to apply full clutch.
    const float Driver::USE_LEARNED_OFFSET_RANGE = 0.2f;			///< [m] if offset < this use the learned stuff
    const float Driver::ACCELERATOR_LETGO_TIME = 0.1f;           ///< [s] Time to let go of accelerator before braking.
    const float Driver::MIN_BRAKE_FOLLOW_DISTANCE = 1.0f;        ///< [m] Predicted minimum distance from next opponent to apply full brake
    const float Driver::MAX_BRAKE_FOLLOW_DISTANCE = 2.0f;        ///< [m] Predicted minimum distance from next opponent to start applying brake.
    const float Driver::STEER_DIRECTION_GAIN = 1.0f; ///< [-] Gain to apply for basic steerin
    const float Driver::STEER_DRIFT_GAIN = 0.01f; ///< [-] Gain for drift compensation
    const float Driver::STEER_PREDICT_GAIN = 0.1f; ///< [-] Predictive gain, multiplied with yaw rate.
    const float Driver::STEER_AVOIDANCE_GAIN = 0.2f; ///< [lograd/m] Gain for border avoidance steering
    const float Driver::STEER_EMERGENCY_GAIN = 0.01f; ///< [-] Gain for emergency steering
    const float Driver::FILTER_STEER_FEEDBACK = 0.8f;        ///< [-] Feedback from steering to steer filter.
    const float Driver::FILTER_PREDICT_FEEDBACK = 0.0f;        ///< [-] Feedback from prediction error to steer filter.
    const float Driver::FILTER_TARGET_FEEDBACK = 0.2f;        ///< [-] Feedback from target error to steer filter.

    Cardata *Driver::cardata = NULL;
    double Driver::currentsimtime;

    static const int SBSIZE = 1024;

    Driver::Driver(int index)
    {
	diagnosticsEnabled = getenv("OLETHROS_DIAGNOSTICS") != NULL;
	INDEX = index;
	race_type = RM_TYPE_RACE;
	diagnosticTick = 0;
	track = NULL;
	car = NULL;
	opponents = NULL;
	opponent = NULL;
	pit = NULL;
	learn = NULL;
	strategy = NULL;
	radius = NULL;
	mycardata = NULL;
	u_toleft = 0.0f;
	u_toright = 0.0f;
	prev_toleft = 0.0f;
	prev_toright = 0.0f;
	prev_steer = 0.0f;
	speed_factor = 1.0f;
	dt = 0.0f;
	pit_exit_timer = 1.0f;
    }


    Driver::~Driver()
    {
	// The current race engine shuts robots down without calling rbEndRace.
	if (learn != NULL && diagnosticsEnabled) {
            fprintf(stderr, "OlethrosEnd bot=%d ticks=%llu\n", INDEX, diagnosticTick);
	}
	
	// Do not save learnt stuff from race itself.

	// We save only for practice and qualifying
	if (learn != NULL && track != NULL && race_type!=RM_TYPE_RACE) {
            // We save only for practice
            //if (race_type==RM_TYPE_PRACTICE) {
            char fname[SBSIZE];
            snprintf(fname, SBSIZE, "%s%s%d/%s.brain", GetLocalDir(),
                     "drivers/olethros/", INDEX, track->internalname);
            
            char path[SBSIZE];
            snprintf(path, SBSIZE, "%s%s%d", GetLocalDir(), "drivers/olethros/", INDEX);
            
            if (GfCreateDir(path) == GF_DIR_CREATED) {
                learn->saveParameters (fname);
            }
	}

	delete opponents;
	delete pit;
	delete [] radius;
	delete learn;
	delete strategy;

	if (mycardata != NULL && cardata != NULL) {
            delete cardata;
            cardata = NULL;
	}
    }


    void Driver::getSetupFileName(char* buffer, size_t size, const char* filename, int raceType) const
    {
	const char* session = NULL;
	switch (raceType) {
        case RM_TYPE_PRACTICE:
            session = "practice";
            break;
        case RM_TYPE_QUALIF:
            session = "qualifying";
            break;
        case RM_TYPE_RACE:
            session = "race";
            break;
        default:
            break;
	}
	if (session != NULL) {
            const char* separator = strrchr(filename, '/');
            const char* trackname = separator != NULL ? separator + 1 : filename;
            snprintf(buffer, size, "drivers/olethros/%d/%s/%s", INDEX, session, trackname);
	} else {
            snprintf(buffer, size, "drivers/olethros/%d/default.xml", INDEX);
	}
    }


    /// Called for every track change or new race.
    void Driver::initTrack(tTrack* t, void *carHandle, void **carParmHandle, tSituation *s)
    {
	track = t;
	const int BUFSIZE = 256;
	char buffer[BUFSIZE];
	getSetupFileName(buffer, BUFSIZE, track->filename, s->_raceType);

	//printf ("Trying %s\n", buffer);
	*carParmHandle = GfParmReadFile(buffer, GFPARM_RMODE_STD);

	if (*carParmHandle == NULL) {
            snprintf(buffer, BUFSIZE, "drivers/olethros/%d/default.xml", INDEX);
            //printf ("LOADING: %s\n", buffer);
            *carParmHandle = GfParmReadFile(buffer, GFPARM_RMODE_STD);
        } else {
            //printf ("LOADING: %s\n", buffer);
	}

	// Create a pit stop strategy object.
	if (s->_raceType == RM_TYPE_RACE) {
            strategy = new ManagedStrategy();
	} else {
            strategy = new SimpleStrategy();
	}

	// Init fuel.
	strategy->setFuelAtRaceStart(t, carParmHandle, s);

	// Load and set parameters.
	MU_FACTOR = GfParmGetNum(*carParmHandle, OLETHROS_SECT_PRIV, OLETHROS_ATT_MUFACTOR, (char*)NULL, 0.69f);

    }


    /// Start a new race.
    void Driver::newRace(tCarElt* car, tSituation *s)
    {
	float deltaTime = (float) RCM_MAX_DT_ROBOTS;
	MAX_UNSTUCK_COUNT = int(UNSTUCK_TIME_LIMIT/deltaTime);
	OVERTAKE_OFFSET_INC = OVERTAKE_OFFSET_SPEED*deltaTime;
	stuck = 0;
	alone = 1;
	clutchtime = 0.0f;
	oldlookahead = 0.0f;
	u_toleft = 0.0f;
	u_toright = 0.0f;
	prev_toleft = 0.0f;
	prev_toright = 0.0f;
	prev_steer = 0.0f;
	alone_count = 0.0f;
	diagnosticTick = 0;
	
	//printf ("INITIALISING ANOTHER CAR: ALONE_COUNT:%f\n", alone_count);
	overtaking = false;

	this->car = car;
	CARMASS = GfParmGetNum(car->_carHandle, SECT_CAR, PRM_MASS, NULL, 1000.0f);
	myoffset = 0.0f;
	initCa();
	initCw();
	initTireMu();
	initTCLfilter();
	mass = CARMASS + car->_fuel;

	radius = new float[track->nseg];
	prepareTrack();

	// Create just one instance of cardata shared by all drivers.
	if (cardata == NULL) {
            cardata = new Cardata(s);
	}
	mycardata = cardata->findCar(car);
	currentsimtime = s->currentTime;

	// initialize the list of opponents.
	opponents = new Opponents(s, this, cardata);
	opponent = opponents->getOpponentPtr();

	learn = new SegLearn(track);

	// create the pit object.
	pit = new Pit(s, this);

	// save race type - to be eaten^H^H^H^H used later perhaps
	race_type = s->_raceType;

	// Resume saved learning in every session, including successive practices.
	char fname[SBSIZE];
	snprintf(fname, SBSIZE, "%s%s%d/%s.brain", GetLocalDir(),
                 "drivers/olethros/", INDEX, track->internalname);
	SegLearn::LoadResult result = learn->loadParameters(fname);
	const char* brainStatus = "missing";
	switch (result) {
	case SegLearn::BRAIN_MISSING: brainStatus = "missing"; break;
	case SegLearn::BRAIN_LOADED: brainStatus = "loaded"; break;
	case SegLearn::BRAIN_REJECTED: brainStatus = "rejected"; break;
	case SegLearn::BRAIN_IO_ERROR: brainStatus = "io-error"; break;
	}
	learn->SetSafetyThreshold(race_type == RM_TYPE_PRACTICE ? 0.5f : 0.0f);
	if (diagnosticsEnabled) {
            fprintf(stderr, "OlethrosSession bot=%d length=%.17g\n", INDEX, planningMesh->length);
            fprintf(stderr, "OlethrosBrain bot=%d status=%s\n", INDEX, brainStatus);
	}
	 

	meshSpeedHistory.resize(planningMesh->sections.size());
	for (size_t i = 0; i < meshSpeedHistory.size(); ++i) {
            float u = getAllowedSpeed(i*planningMesh->spacing);
            meshSpeedHistory[i] = (std::isnan(u) || u > 10000.0f) ? 10000.0f : u;
	}
    }


    double Driver::currentStation() const
    {
        const tTrackSeg& seg = *car->_trkPos.seg;
        double local = car->_trkPos.toStart;
        if (seg.type != TR_STR) local *= seg.radius;
        return planningMesh->station(seg, local);
    }

    float Driver::pathSpeedHistory(double station) const
    {
        double f;
        size_t i = planningMesh->interval(station, f), j = (i+1)%meshSpeedHistory.size();
        return (float)((1-f)*meshSpeedHistory[i]+f*meshSpeedHistory[j]);
    }

    /// Drive during race.
    void Driver::drive(tSituation *s)
    {
	memset(&car->ctrl, 0, sizeof(tCarCtrl));
		
	update(s);
	++diagnosticTick;
	if (diagnosticsEnabled) {
            fprintf(stderr, "OlethrosNumeric state bot=%d tick=%llu time=%.17g seg=%d speed=%.9g middle=%.9g damage=%d\n",
                INDEX, diagnosticTick, s->currentTime, car->_trkPos.seg->id, car->_speed_x, car->_trkPos.toMiddle, car->_dammage);
	}
	if (race_type==RM_TYPE_PRACTICE) {
            if (car->_laps<200) {
                learn->SetSafetyThreshold (0.0f);
            } else {
                learn->SetSafetyThreshold (0.5f);
            }
	} else if (race_type==RM_TYPE_RACE) {
            learn->SetSafetyThreshold (0.5f);
	} else if (race_type==RM_TYPE_QUALIF) {
            learn->SetSafetyThreshold (0.5f);
        }

	bool recovery = isStuck();
	if (diagnosticsEnabled) {
            fprintf(stderr, "OlethrosTick bot=%d tick=%llu time=%.17g dt=%.9g recovery=%d gear=%d speed=%.9g\n",
                INDEX, diagnosticTick, s->currentTime, dt, recovery, car->_gear, car->_speed_x);
	}
	if (recovery) {
            car->_steerCmd = -mycardata->getCarAngle() / car->_steerLock;
            car->_gearCmd = -1;		// Reverse gear.
            car->_accelCmd = 1.0;	// 100% accelerator pedal.
            car->_brakeCmd = 0.0;	// No brakes.
            car->_clutchCmd = 0.0;	// Full clutch (gearbox connected with engine).
	} else {
            const v2d target = updateTargetPoint();
            if (diagnosticsEnabled) {
                fprintf(stderr, "OlethrosNumeric target bot=%d tick=%llu time=%.17g x=%.9g y=%.9g car=%.9g,%.9g\n",
                    INDEX, diagnosticTick, currentsimtime, target.x, target.y, car->_pos_X, car->_pos_Y);
            }
            const float baseSteer = getSteer(target);
            float steer = baseSteer;
            // Pit steering follows the prescribed spline. Main-track learning
            // and lateral avoidance must not steer through neighboring boxes.
            if (!pit->getInPit()) {
                steer = filterSColl(baseSteer - 0.2f*learn->predictedError(car));
            }
            //float gamma_steer = exp(- 0.1f * dt * fabs(getSpeed())); 
            //prev_steer = prev_steer * (1-gamma_steer) + gamma_steer * steer;
            car->_steerCmd = steer;
            car->_gearCmd = getGear();
            float fbrake = filterBrakeSpeed(getBrake());
            float faccel = getAccel();
            if (diagnosticsEnabled) {
                fprintf(stderr, "OlethrosDemand bot=%d tick=%llu time=%.17g accel=%.9g brake=%.9g rpm=%.9g gear=%d gearCmd=%d speedY=%.9g alone=%d offset=%.9g pitState=%d\n",
                    INDEX, diagnosticTick, currentsimtime, faccel, fbrake, car->_enginerpm*60.0/(2.0*PI), car->_gear,
                    car->_gearCmd, car->_speed_y, alone, myoffset, pit->getState());
            }
            // Side-collision offset changes affect speed queries and the next
            // tick's target; feedback reuses this tick's uncorrected steering.
            if (!pit->getInPit()) updateTrackFeedback(s, baseSteer);
            fbrake = filterABS(filterBColl(filterBPit(fbrake)));
            faccel = filterTCL(filterAPit(faccel));
            float trk_accel;
            if (fbrake > 0) {
                trk_accel = -fbrake;
            } else {
                trk_accel = faccel;
            }

            //trk_accel = faccel-fbrake;
		

            if (trk_accel >= 0) {
                car->_accelCmd = trk_accel;
                car->_brakeCmd = 0.0;
            } else {
                car->_accelCmd = 0.0;
                car->_brakeCmd = -trk_accel;
            }
            //printf ("fb:%f fa:%f ta:%f\n", fbrake, faccel, trk_accel);
            car->_clutchCmd = getClutch();

            //float mu = segptr->surface->kFriction;
            if (car->priv.collision) {

                //printf ("Collision, not adjusting (%d %f)\n",
                //car->_laps, s->currentTime);
                learn->AdjustFriction(car->_trkPos.seg, G, mass,CA, CW,getSpeed(), car->_brakeCmd, 0.0);
                car->priv.collision = 0;
            } else if (alone) {
                if (car->_accelCmd > 0) {
                    //float ratio =  0.0001*car->_engineMaxTq*car->_gearRatio[car->_gear + car->_gearOffset];
                    learn->AdjustFriction(car->_trkPos.seg, G, mass,CA, CW,getSpeed(), -car->_accelCmd, 0.001f);
                } else {
                    learn->AdjustFriction(car->_trkPos.seg, G, mass,CA, CW,getSpeed(), car->_brakeCmd, 0.001f);
                }
            } else {
                learn->AdjustFriction(car->_trkPos.seg, G, mass,CA, CW,getSpeed(), car->_brakeCmd, 0.0f);
            }
            //printf ("%f %f\n", car->_steerCmd, learn->predictedError(car));
            if (race_type != RM_TYPE_RACE || alone) {
                double f;
                size_t i = planningMesh->interval(currentStation(), f);
                size_t j = (i+1)%meshSpeedHistory.size();
                meshSpeedHistory[i] += 0.1 * dt * (car->_speed_x + 5.0f - meshSpeedHistory[i]);
                meshSpeedHistory[j] += 0.1 * dt * (car->_speed_x + 5.0f - meshSpeedHistory[j]);
            }

	}
	if (diagnosticsEnabled) {
            fprintf(stderr, "OlethrosNumeric controls bot=%d tick=%llu time=%.17g steer=%.9g accel=%.9g brake=%.9g clutch=%.9g\n",
                INDEX, diagnosticTick, s->currentTime, car->_steerCmd, car->_accelCmd, car->_brakeCmd, car->_clutchCmd);
	}
	if (diagnosticsEnabled) {
            fprintf(stderr, "OlethrosSeam state bot=%d tick=%llu time=%.17g lap=%d distance=%.9g seg=%d speed=%.9g radius=%.9g learned=%.9g maxspeed=%.9g accel=%.9g brake=%.9g damage=%d pit=%d gear=%d pitState=%d pitstop=%d middle=%.9g\n",
                INDEX, diagnosticTick, s->currentTime, car->_laps, car->_distFromStartLine, car->_trkPos.seg->id,
                car->_speed_x, planningMesh->pathRadius(currentStation()),
                learn->getRadius(car->_trkPos.seg), pathSpeedHistory(currentStation()),
                car->_accelCmd, car->_brakeCmd, car->_dammage, pit->getInPit(), car->_gear, pit->getState(), pit->getPitstop(), car->_trkPos.toMiddle);
	}
    }


    /// Set pitstop commands.
    int Driver::pitCommand(tSituation *s)
    {
	car->_pitRepair = strategy->pitRepair(car, s);
	car->_pitFuel = strategy->pitRefuel(car, s);
	// This should be the only place where the pit stop is set to false!
	pit->setPitstop(false);
	return ROB_PIT_IM; // return immediately.
    }


    /// End of the current race.
    void Driver::endRace(tSituation *s)
    {
	// Final diagnostics and session-dependent persistence occur at shutdown.
    }


    /***************************************************************************
     *
     * utility functions
     *
     ***************************************************************************/

    /// Compute the allowed speed on a segment.
    float Driver::getAllowedSpeed(double station)
    {
	tTrackSeg *segment = const_cast<tTrackSeg*>(&planningMesh->source(station));
	float mu = segment->surface->kFriction*TIREMU*MU_FACTOR;
	float r = (float)planningMesh->pathRadius(station);
	float dr = learn->getRadius(segment);

	if ((alone > 0) && (fabs(myoffset) < USE_LEARNED_OFFSET_RANGE)) {
            float new_r = r+dr;
            float min_r = r;
            if (segment->type!=TR_STR) {
                min_r = MIN(min_r, segment->radiusr);
                min_r = MIN(min_r, segment->radiusl);
            }
            if (new_r > min_r && !pit->getInPit()) {
                r = new_r;
            }
	} else {
            float delta_offset = fabs (myoffset);

            if (dr >= -0.5f * r) {
                r += dr * (1.0f - tanh(delta_offset));
            }
            float alpha = 2.0f * delta_offset / segment->width;
            alpha = MIN (1, alpha);
            alpha = MAX (0, alpha);
            float segrad = segment->radius;
            if (segment->type == TR_STR) {
                segrad = 1000.0f;
            }
            //printf ("%f %f %f %f %f\n", delta_offset, normal_offset, adj_offset, alpha, r);

            r = alpha == 1.0f ? segrad : alpha * segrad + (1-alpha) * r;
	}

	/// TODO - check range of predictedAccel!
            r *= exp(0.1*learn->predictedAccel (segment));
            float der = (float)planningMesh->gradeDerivative(station);
            float adj = 1 + tanh(0.1*car->_speed_x * der);

            float bank = 0.5 * (segment->angle[TR_XS] + segment->angle[TR_XE]);
            if (segment->type==TR_STR) {
		adj *= cos(bank);
            } else if (segment->type==TR_LFT) {
		adj *= 1 + tanh(-bank);
            } else {
		adj *= 1 + tanh(bank);
            }
            mu *= adj;
            // Reciprocal form also represents a straight (1/r == 0) without
            // inf/inf. The existing aero limit still allows unbounded speed.
            float inverseRadius = 1.0f/r;
            float n_speed = sqrt((mu*G)/(inverseRadius - MIN(inverseRadius, CA*mu/mass)));
            return n_speed;
    }


    // Compute the length to the end of the segment.
    float Driver::getDistToSegEnd()
    {
	if (car->_trkPos.seg->type == TR_STR) {
            return car->_trkPos.seg->length - car->_trkPos.toStart;
	} else {
            return (car->_trkPos.seg->arc - car->_trkPos.toStart)*car->_trkPos.seg->radius;
	}
    }


    /// Compute fitting acceleration.
    float Driver::getAccel()
    {
	if (car->_gear > 0) {
            double station = currentStation();
            float allowedspeed = getAllowedSpeed(station);
            const float localAllowed = allowedspeed;
            int selectedSegment = car->_trkPos.seg->id;
            float selectedDistance = 0.0f;
            {
                    tTrackSeg *segptr = car->_trkPos.seg;
                    float mu = segptr->surface->kFriction;
                    float maxlookaheaddist = currentspeedsqr/(2.0*mu*G);
                    double next = planningMesh->nextStation(station);
                    double end = station + MIN(maxlookaheaddist, planningMesh->length);
                    while (next < end) {
                        float lookaheaddist = (float)(next-station);
                        segptr = const_cast<tTrackSeg*>(&planningMesh->source(next));
                        float pallowedspeed = getAllowedSpeed(next);
                        float delta = (brakedist(pallowedspeed, mu) - lookaheaddist);
                        //printf("%f\n", delta);
                        float u = MAX(0.1f, getSpeed());
                        float t = ACCELERATOR_LETGO_TIME + (1.0f - speed_factor);
                        if (overtaking) {
                            t = -0.1f;
                        }
                        if (-delta/u<t) {
                            if (pallowedspeed < allowedspeed) {
                                allowedspeed = pallowedspeed;
                                selectedSegment = segptr->id;
                                selectedDistance = lookaheaddist;
                            }
                        }
                        next = planningMesh->nextStation(next);
                    }
		}
            float max_allowed;
            switch(race_type) {
            case RM_TYPE_PRACTICE:
                max_allowed = 1.2f*pathSpeedHistory(station);
                break;
            case RM_TYPE_QUALIF:
                max_allowed = 1.2f*pathSpeedHistory(station);
                break;
            default:
                max_allowed = 1.2f*pathSpeedHistory(station);
                break;
            }

            const float scanAllowed = allowedspeed;
            if (allowedspeed > max_allowed) {
                allowedspeed = max_allowed;
            }
            current_allowed_speed = allowedspeed;
            if (diagnosticsEnabled) {
                fprintf(stderr, "OlethrosPlan bot=%d tick=%llu time=%.17g allowed=%.9g pit=%d local=%.9g scan=%.9g cap=%.9g selected=%d distance=%.9g speedFactor=%.9g\n",
                    INDEX, diagnosticTick, currentsimtime, allowedspeed, pit->getInPit(), localAllowed, scanAllowed,
                    max_allowed, selectedSegment, selectedDistance, speed_factor);
            }
            float total_speed = sqrt(car->_speed_x*car->_speed_x + car->_speed_y*car->_speed_y);
            float delta = allowedspeed - (total_speed + FULL_ACCEL_MARGIN);
            float alpha = 0.5;
            float lambda = 2.0;
            //printf ("%.1f\n", delta);
            if (delta>0) {
                if (delta<lambda) {
                    float acc = alpha + (1-alpha)*delta/lambda;
                    //printf ("ac:%f\n", acc);
                    return acc;
                }
                //printf ("ac:1\n");
                return 1.0;//tanh(delta);
            } else {
                float acc = alpha*(1+delta/FULL_ACCEL_MARGIN);
                if (acc<0) acc = 0;
                //printf ("at:%f\n", acc);
                return acc;
            }
	} else {
            return 1.0;
	}
    }


    /// Compute initial brake value.
    float Driver::getBrake()
    {
	// Car drives backward?
	if (car->_speed_x < -MAX_UNSTUCK_SPEED) {
            // Yes, brake.
            return 1.0;
	} else {
            // We drive forward, normal braking.
            tTrackSeg *segptr = car->_trkPos.seg;
            float mu = segptr->surface->kFriction;
            float maxlookaheaddist = currentspeedsqr/(2.0*mu*G);
            double station = currentStation();
            float allowedspeed = getAllowedSpeed(station);
            float brake = 0.0f;
            if (allowedspeed < car->_speed_x) {
                float delta = (0.5f*(car->_speed_x - allowedspeed)/FULL_ACCEL_MARGIN);
                if (diagnosticsEnabled) {
                    fprintf(stderr, "OlethrosSeam brake bot=%d tick=%llu time=%.17g seg=%d distance=0 allowed=%.9g radius=%.9g delta=%.9g\n", INDEX, diagnosticTick, currentsimtime, segptr->id, allowedspeed, planningMesh->pathRadius(station), delta);
                }
                brake = tanh(delta);
            }

            double next = planningMesh->nextStation(station);
            double end = station + MIN(maxlookaheaddist, planningMesh->length);
            while (next < end) {
                float lookaheaddist = (float)(next-station);
                segptr = const_cast<tTrackSeg*>(&planningMesh->source(next));
                allowedspeed = getAllowedSpeed(next);
                if (allowedspeed < car->_speed_x) {
                    float delta = (brakedist(allowedspeed, mu) - lookaheaddist);
                    if (delta>0) {
                        if (diagnosticsEnabled) {
                            fprintf(stderr, "OlethrosSeam brake bot=%d tick=%llu time=%.17g seg=%d distance=%.9g allowed=%.9g radius=%.9g delta=%.9g\n", INDEX, diagnosticTick, currentsimtime, segptr->id, lookaheaddist, allowedspeed, planningMesh->pathRadius(next), delta);
                        }
                        // A newly inserted regular station must not hide a
                        // stronger demand farther ahead. First-hit return made
                        // braking depend on native subdivision / scan density.
                        brake = MAX(brake, tanh(0.1f*delta));
                    }
                }
                next = planningMesh->nextStation(next);
            }
            if (diagnosticsEnabled) {
                fprintf(stderr, "OlethrosBrakePlan bot=%d tick=%llu time=%.17g brake=%.9g\n", INDEX, diagnosticTick, currentsimtime, brake);
            }
            return brake;
	}
    }


    /**
       \brief Compute gear.
   
       Gear is shifted upwards in two cases:

       1) When we almost reach the revs limiter.
       2) When the overall output torque by shifting upwards will be greater than the current overall output torque.

       Gear is shifted down when our revs by shifting down would be
       somewhat below the red line at the current speed.
   
    */
    int Driver::getGear()
    {
	if (car->_gear <= 0) {
            return 1;
	}
	float gr_up = car->_gearRatio[car->_gear + car->_gearOffset];
	float omega = car->_enginerpmRedLine/gr_up;
	float wr = car->_wheelRadius(2);
	//float rpm = car->_enginerpm;
	float rpm = gr_up * car->_speed_x / wr;//car->_enginerpm;
	// gearNb is one past the highest forward gear. Check availability before
	// reading the next ratio, including at the eight-speed array boundary.
	int highestGear = MIN(car->_gearNb - 1, MAX_GEARS - 1 - car->_gearOffset);
	if (car->_gear < highestGear) {
            int nextGear = car->_gear + 1;
            float nextRatio = car->_gearRatio[nextGear + car->_gearOffset];
            float nextRpm = nextRatio * car->_speed_x / wr;
            if (omega*wr*SHIFT < car->_speed_x ||
                EstimateTorque(nextRpm)*nextRatio > EstimateTorque(rpm)*gr_up) {
                return nextGear;
            }
	}
	if (car->_gear > 1) {
            float gr_down = car->_gearRatio[car->_gear + car->_gearOffset - 1];
            float prev_rpm = gr_down * (car->_speed_x) / wr;

            if (prev_rpm < car->_enginerpmMaxPw * SHIFT
                && (EstimateTorque (prev_rpm) * gr_down
                    > EstimateTorque (rpm) * gr_up)) {
                return car->_gear - 1;
            }
	}
	return car->_gear;
    }

    /**
       \brief Estimate torque from max torque and max power ratings.

       Uses a piecewise linear model to estimate torque, given the value
       of torque at the max torque and power points and assuming that the
       torque drops to 0 at 0 revs and that it decays linearly after the
       maximum power at a rate 4 times than that of the decay between
       maximum torque and maximum power.
    */
    float Driver::EstimateTorque (float rpm)
    {
	float MaxPw = car->_engineMaxPw;
	float rpmMaxPw = car->_enginerpmMaxPw;
	float MaxTq = car->_engineMaxTq;
	float rpmMaxTq = car->_enginerpmMaxTq;
	float rpmMax = car->_enginerpmMax;
	float TqAtMaxPw = MaxPw/rpmMaxPw;
	float PwAtMaxRevs = .5*MaxPw;
	float TqAtMaxRevs = PwAtMaxRevs/rpmMax;
	//printf ("pw-estimated Tq at maxrevs: %f@%f\n", TqAtMaxRevs, car->_enginerpmMax);
	
	
	float t [] = {
            0.0,
            MaxTq,
            TqAtMaxPw,
            TqAtMaxRevs,
            0.0
	};
	float a [] = {		
            0.0,
            rpmMaxTq,
            rpmMaxPw,
            rpmMax,
            rpmMax*2.0f
	};
	int N = 5;
	for (int i=0; i<N - 1; i++) {
            if (rpm>a[i] && rpm<=a[i+1]) {
                float d = (a[i+1]-a[i]);
                float dr = (rpm - a[i]);
                float D = (dr/d);
                float est_1 = t[i] * (1-D) + D * t[i+1];
                //float est_2 = (t[i]*a[i]*(1-D) + D*t[i+1]*a[i+1])/rpm; 
                return est_1;

            }
	}
	// if rpm < 0, or rpm >maxrpm
	return 0.0;
    }

    /// Compute steer value.
    float Driver::getSteer(const v2d& target) const
    {
	float avoidance = 0.0f;
	if (!pit->getInPit()) {
            if (car->_trkPos.toRight < car->_dimension_y) {
                avoidance = tanh(STEER_AVOIDANCE_GAIN*(car->_dimension_y - car->_trkPos.toRight));
            } else 	if (car->_trkPos.toLeft < car->_dimension_y) {
                avoidance = tanh(STEER_AVOIDANCE_GAIN*(car->_trkPos.toLeft - car->_dimension_y));
            }
	}

	float targetAngle = atan2(target.y - car->_pos_Y, target.x - car->_pos_X);
	float steer_direction = STEER_DIRECTION_GAIN * (targetAngle - car->_yaw - STEER_PREDICT_GAIN * car->_yaw_rate);

	// over steer correction a la berniw
	//tTrackSeg *seg = car->_trkPos.seg;
	/*float omega = 0.0;
	if (seg->type==TR_LFT) {
            omega = getSpeed()/radius[seg->id];
	} else if (seg->type == TR_RGT) {
            omega = -getSpeed()/radius[seg->id];
	}*/
	float correct_oversteer = 0.0f;//STEER_PREDICT_GAIN * (omega - car->_yaw_rate);


	// Slip is relative to the car, not its compass heading. World velocities
	// introduced a 2*pi*gain steering jump whenever heading crossed +/-pi.
	float correct_drift = - STEER_DRIFT_GAIN * atan2(car->_speed_y, car->_speed_x);

	NORM_PI_PI(steer_direction);
	return avoidance + correct_oversteer + correct_drift + steer_direction/car->_steerLock;
    }


    /// Compute the clutch value.
    float Driver::getClutch()
    {
	if (car->_gear > 1) {
            clutchtime = 0.0;
            return 0.0;
	} else {
            float drpm = car->_enginerpm - car->_enginerpmRedLine/2.0;
            clutchtime = MIN(CLUTCH_FULL_MAX_TIME, clutchtime);
            float clutcht = (CLUTCH_FULL_MAX_TIME - clutchtime)/CLUTCH_FULL_MAX_TIME;
            if (car->_gear == 1 && car->_accelCmd > 0.0) {
                clutchtime += (float) RCM_MAX_DT_ROBOTS;
            }

            if (drpm > 0) {
                float speedr;
                if (car->_gearCmd == 1) {
                    // Compute corresponding speed to engine rpm.
                    float omega = car->_enginerpmRedLine/car->_gearRatio[car->_gear + car->_gearOffset];
                    float wr = car->_wheelRadius(2);
                    speedr = (CLUTCH_SPEED + MAX(0.0, car->_speed_x))/fabs(wr*omega);
                    float clutchr = MAX(0.0, (1.0 - speedr*2.0*drpm/car->_enginerpmRedLine));
                    return MIN(clutcht, clutchr);
                } else {
                    // For the reverse gear.
                    clutchtime = 0.0;
                    return 0.0;
                }
            } else {
                return clutcht;
            }
	}
    }

    /// Advance the target's maneuver state once per normal driving tick.
    v2d Driver::updateTargetPoint()
    {
	float lookahead;
	const bool inPit = pit->getInPit();
	float offset = 0.0f;
	if (inPit) {
            overtaking = false;
            // To stop in the pit we need special lookahead values.
            if (currentspeedsqr > pit->getSpeedlimitSqr()) {
                lookahead = PIT_LOOKAHEAD + car->_speed_x*LOOKAHEAD_FACTOR;
            } else {
                lookahead = PIT_LOOKAHEAD;
            }
	} else {
            offset = getOffset();
            // Usual lookahead.
            lookahead = LOOKAHEAD_CONST + car->_speed_x*LOOKAHEAD_FACTOR;
            // Prevent "snap back" of lookahead on harsh braking.
            float cmplookahead = oldlookahead - car->_speed_x*RCM_MAX_DT_ROBOTS;
            if (lookahead < cmplookahead) {
                lookahead = cmplookahead;
            }
	}

	oldlookahead = lookahead;

        double station = currentStation()+lookahead;
        const tTrackSeg& seg = planningMesh->source(station);
        double local = planningMesh->wrap(station)-planningMesh->station(seg);
        // Pit tables use the native cached track coordinate, not mesh L.
        float fromstart = (float)(seg.lgfromstart+local);
        offset = myoffset = pit->getPitOffset(offset, fromstart);
        // The spline is centerline-relative for the whole maneuver, including
        // PIT_EXIT after service or timeout clears the stop request.
        PlanningPoint target = planningMesh->target(station, offset,
            inPit, inPit);
        if (diagnosticsEnabled) {
            fprintf(stderr, "OlethrosTargetSection bot=%d tick=%llu time=%.17g seg=%d station=%.9g local=%.9g lookahead=%.9g alpha=%.9g nextAlpha=%.9g offset=%.9g\n",
                INDEX, diagnosticTick, currentsimtime, seg.id, station, local, lookahead, planningMesh->weight(station),
                planningMesh->weight(station+planningMesh->spacing), offset);
        }
        return v2d((float)target.x, (float)target.y);
    }


    /// Compute offset to normal target point for overtaking or let pass an opponent.
    float Driver::getOffset()
    {
	int i;
	float catchdist, mincatchdist = FLT_MAX, mindist = -1000.0;
	Opponent *o = NULL;

	// Increment speed dependent.
	float incfactor = MAX_INC_FACTOR - MIN(fabs(car->_speed_x)/MAX_INC_FACTOR, (MAX_INC_FACTOR-1.0));

	// Let overlap.
	for (i = 0; i < opponents->getNOpponents(); i++) {
            if (opponent[i].getState() & OPP_LETPASS) {
                // Behind, larger distances are smaller ("more negative").
                if (opponent[i].getDistance() > mindist) {
                    mindist = opponent[i].getDistance();
                    o = &opponent[i];
                }
            }
	}

	//myoffset = -0.2f * car->_trkPos.seg->width;
	overtaking = false;
	if (o != NULL) {
            tCarElt *ocar = o->getCarPtr();
            float side = car->_trkPos.toMiddle - ocar->_trkPos.toMiddle;
            float w = car->_trkPos.seg->width/WIDTHDIV-BORDER_OVERTAKE_MARGIN;
            if (side > 0.0) {
                if (myoffset < w) {
                    myoffset += OVERTAKE_OFFSET_INC*incfactor;
                }
            } else {
                if (myoffset > -w) {
                    myoffset -= OVERTAKE_OFFSET_INC*incfactor;
                }
            }
            //printf ("let overtake: %f\n", myoffset);
            return myoffset;
	}


	// Overtake.
	float selectedCatchTime = OVERTAKE_TIME;
	for (i = 0; i < opponents->getNOpponents(); i++) {
            if (opponent[i].getState() & OPP_FRONT) {
                catchdist = opponent[i].getCatchDist();//MIN(opponent[i].getCatchDist(), opponent[i].getDistance()*CATCH_FACTOR);
                if (getSpeed() > 0) {
                    const float candidateTime = catchdist/getSpeed();
                    if (candidateTime < OVERTAKE_TIME) {
                        // consider overtaking if we approach in OVERTAKE_TIME
                        if (catchdist < mincatchdist) {
                            mincatchdist = catchdist;
                            o = &opponent[i];
                            selectedCatchTime = candidateTime;
                        }
				 
                    } else if (opponent[i].getBrakeOvertake()>0.1f) {
                        // or if we recently were about to crash
                        //printf ("b_overtake: %f\n", opponent[i].getBrakeOvertake());
                        catchdist = opponent[i].getDistance();
                        if (catchdist < mincatchdist) {
                            mincatchdist = catchdist;
                            o = &opponent[i];
                            selectedCatchTime = candidateTime;
                        }
                    }
                }
            }
	}

	if (o != NULL) {
            overtaking = true;
            // Compute the width around the middle which we can use for overtaking.
            float w = o->getCarPtr()->_trkPos.seg->width/WIDTHDIV-BORDER_OVERTAKE_MARGIN;
            // Compute the opponents distance to the middle.
            float otm = o->getCarPtr()->_trkPos.toMiddle;
            // Define the with of the middle range.
            float wm = o->getCarPtr()->_trkPos.seg->width*CENTERDIV;

            if (selectedCatchTime > 0.0f) {
                incfactor *= (1.0f + OVERTAKE_TIME) / (1.0f + selectedCatchTime);
            } else {
                incfactor *= 2.0f;
            }

            if (otm > wm && myoffset > -w) {
                myoffset -= OVERTAKE_OFFSET_INC*incfactor;
            } else if (otm < -wm && myoffset < w) {
                myoffset += OVERTAKE_OFFSET_INC*incfactor;
            } else {
                // If the opponent is near the middle we try to move the offset toward
                // the inside of the expected turn.
                // Try to find out the characteristic of the track up to catchdist.
                float lenright = 0.0, lenleft = 0.0;
                mincatchdist = MIN(mincatchdist, DISTCUTOFF);
                double station = currentStation();
                double end = station+MAX(0.0f, mincatchdist);
                while (station < end) {
                    double next = MIN(end, planningMesh->nextStation(station));
                    double w = planningMesh->weight(0.5*(station+next));
                    lenleft += w*(next-station);
                    lenright += (1-w)*(next-station);
                    station = next;
                }

                // Because we are inside we can go to the border.
                float maxoff = (o->getCarPtr()->_trkPos.seg->width - car->_dimension_y)/2.0-BORDER_OVERTAKE_MARGIN;
                if (lenleft > lenright) {
                    if (myoffset < maxoff) {
                        myoffset += OVERTAKE_OFFSET_INC*incfactor;
                    }
                } else {
                    if (myoffset > -maxoff) {
                        myoffset -= OVERTAKE_OFFSET_INC*incfactor;
                    }
                }
            }
	} else {
            // There is no opponent to overtake, so the offset goes slowly back to zero.
            float a = 1.0;
            if (myoffset > a*OVERTAKE_OFFSET_INC) {
                myoffset -= a*OVERTAKE_OFFSET_INC;
                //myoffset= 0.0;
            } else if (myoffset < -a*OVERTAKE_OFFSET_INC) {
                myoffset += a*OVERTAKE_OFFSET_INC;
                //myoffset= 0.0;
            } else {
                myoffset = 0.0;
            }
	}

	return myoffset;
    }


    /// Update my private data every timestep.
    void Driver::update(tSituation *s)
    {
	// Every bot receives the engine's robot interval, independently of which
	// instance refreshes the shared observations below.
	dt = (float)s->deltaTime;
	if (dt < 0.0f) dt = 0.0f;

	// Update global car data (shared by all instances) just once per timestep.
	if (currentsimtime != s->currentTime) {
            currentsimtime = s->currentTime;
            cardata->update();
	}

	// Update the local data rest.
	speedangle = mycardata->getTrackangle() - atan2(car->_speed_Y, car->_speed_X);
	NORM_PI_PI(speedangle);
	mass = CARMASS + car->_fuel;
	currentspeedsqr = car->_speed_x*car->_speed_x;
	opponents->update(s, this);
	strategy->update(car, s);
	speed_factor = strategy->getSpeedFactor (car, s, opponents);
	if (!pit->getPitstop()) {
            pit->setPitstop(strategy->needPitstop(car, s, opponents));
	}
	pit->update();
	if (pit->getInPit()) {
            pit_exit_timer = 0.0f;
	} else {
            pit_exit_timer += dt;
	}

	alone = isAlone();

	if (race_type != RM_TYPE_RACE) {
            learn->update(s, track, car, alone, myoffset,
                          car->_trkPos.seg->width/WIDTHDIV-BORDER_OVERTAKE_MARGIN,
                          radius, (float)planningMesh->weight(currentStation()),
                          car->_speed_x, current_allowed_speed);
	}
    }

    /// Check if we are alone
    int Driver::isAlone()
    {
	int i;
	for (i = 0; i < opponents->getNOpponents(); i++) {
            if (opponent[i].getState() & (OPP_COLL | OPP_LETPASS)) {
                alone_count = 0.0f;
            }
	}

	if (alone_count >= 2.0f) {
            return 1;	// Alone.
	} else {
            alone_count += dt;
            return 0;
	}
    }


    /// Check if I'm stuck.
    bool Driver::isStuck()
    {
	if (fabs(mycardata->getCarAngle()) > MAX_UNSTUCK_ANGLE &&
            car->_speed_x < MAX_UNSTUCK_SPEED &&
            fabs(car->_trkPos.toMiddle) > MIN_UNSTUCK_DIST) {
            if (stuck > MAX_UNSTUCK_COUNT && car->_trkPos.toMiddle*mycardata->getCarAngle() < 0.0) {
                return true;
            } else {
                stuck++;
                return false;
            }
	} else {
            stuck = 0;
            return false;
	}
    }


    /// Compute aerodynamic downforce coefficient CA.
    void Driver::initCa()
    {
	const char *WheelSect[4] = {SECT_FRNTRGTWHEEL, SECT_FRNTLFTWHEEL, SECT_REARRGTWHEEL, SECT_REARLFTWHEEL};
	float rearwingarea = GfParmGetNum(car->_carHandle, SECT_REARWING, PRM_WINGAREA, (char*) NULL, 0.0);
	float rearwingangle = GfParmGetNum(car->_carHandle, SECT_REARWING, PRM_WINGANGLE, (char*) NULL, 0.0);
	float wingca = 1.23*rearwingarea*sin(rearwingangle);

	float cl = GfParmGetNum(car->_carHandle, SECT_AERODYNAMICS, PRM_FCL, (char*) NULL, 0.0) +
            GfParmGetNum(car->_carHandle, SECT_AERODYNAMICS, PRM_RCL, (char*) NULL, 0.0);
	float h = 0.0;
	int i;
	for (i = 0; i < 4; i++)
            h += GfParmGetNum(car->_carHandle, WheelSect[i], PRM_RIDEHEIGHT, (char*) NULL, 0.20f);
	h*= 1.5; h = h*h; h = h*h; h = 2.0 * exp(-3.0*h);
	CA = h*cl + 4.0*wingca;
    }


    /// Compute aerodynamic drag coefficient CW.
    void Driver::initCw()
    {
	float cx = GfParmGetNum(car->_carHandle, SECT_AERODYNAMICS, PRM_CX, (char*) NULL, 0.0);
	float frontarea = GfParmGetNum(car->_carHandle, SECT_AERODYNAMICS, PRM_FRNTAREA, (char*) NULL, 0.0);
	CW = 0.645*cx*frontarea;
    }


    /// Init the friction coefficient of the the tires.
    void Driver::initTireMu()
    {
	const char *WheelSect[4] = {SECT_FRNTRGTWHEEL, SECT_FRNTLFTWHEEL, SECT_REARRGTWHEEL, SECT_REARLFTWHEEL};
	float tm = FLT_MAX;
	int i;

	for (i = 0; i < 4; i++) {
            tm = MIN(tm, GfParmGetNum(car->_carHandle, WheelSect[i], PRM_MU, (char*) NULL, 1.0));
	}
	TIREMU = tm;
    }


    /// Reduces the brake value such that it fits the speed (more downforce -> more braking).
    float Driver::filterBrakeSpeed(float brake)
    {
	float weight = (CARMASS + car->_fuel)*G;
	float maxForce = weight + CA*MAX_SPEED*MAX_SPEED;
	float force = weight + CA*currentspeedsqr;
	return brake*force/maxForce;
    }

    /// Reduced
    float Driver::filterAPit(float accel)
    {
	if (pit->getPitstop() && !pit->getInPit()) {
            float dl, dw;
            RtDistToPit(car, track, &dl, &dw);
            if (dl < Pit::BRAKE_AHEAD) {
                float mu = car->_trkPos.seg->surface->kFriction*TIREMU*PIT_MU;
                accel = tanh(0.1*(dl-brakedist(0.0, mu)));
                if (accel < 0) {
                    accel = 0;
                }
            }
	}

	if (pit->getInPit()) {
            float s = pit->toSplineCoord(car->_distFromStartLine);
            if (pit->getPitstop() || s < pit->getNPitEnd()) { 
                float delta =  pit->getSpeedlimit() - getSpeed();
                if (delta>0) {
                    accel = tanh(delta);
                }

            }
	}
	return accel;
    }

    // Brake filter for pit stop.
    float Driver::filterBPit(float brake)
    {
	if (pit->getPitstop() && !pit->getInPit()) {
            float dl, dw;
            RtDistToPit(car, track, &dl, &dw);
            if (dl < Pit::BRAKE_AHEAD) {
                float mu = car->_trkPos.seg->surface->kFriction*TIREMU*PIT_MU;
                float bd = brakedist(0.0, mu);
                if (bd > dl) {
                    float br = tanh((bd-dl));
                    return br;
                }
            }
	}

	if (pit->getInPit()) {
            float s = pit->toSplineCoord(car->_distFromStartLine);
            // Pit entry.
            if (pit->getPitstop()) {
                float mu = car->_trkPos.seg->surface->kFriction*TIREMU*PIT_MU;
                if (s < pit->getNPitStart()) {
                    // Brake to pit speed limit.
                    float dist = pit->getNPitStart() - s;
                    float b =  (brakedist(pit->getSpeedlimit(), mu) - dist);
                    if (b > 0) {
                        return tanh(b);

                    }
                } else {
                    // Hold speed limit.
                    if (currentspeedsqr > pit->getSpeedlimitSqr()) {
                        float br = pit->getSpeedLimitBrake(currentspeedsqr);
                        return br;
                    }
                }
                // Brake into pit (speed limit 0.0 to stop)
                float dist = pit->getNPitLoc() - s;
                if (pit->isTimeout(dist)) {
                    pit->setPitstop(false);
                    return 0.0;
                } else {
                    if (brakedist(0.0, mu) > dist) {
                        float bd = brakedist(0.0,mu)-dist;
                        return tanh(bd);
                        //return 1.0;
                    } else if (s > pit->getNPitLoc()) {
                        // Stop in the pit.
                        return 1.0;
                    }
                }
            } else {
                // Pit exit.
                if (s < pit->getNPitEnd()) {
                    // Pit speed limit.
                    if (currentspeedsqr > pit->getSpeedlimitSqr()) {
                        float br =  pit->getSpeedLimitBrake(currentspeedsqr);
                        return br;
                    }
                }
            }
	}

	return brake;
    }


    /**
       Brake filter for collision avoidance.
   
       Given \f$u_0\f$, \f$u_t\f$, the velocities of our car and the
       opponent's, and the distance \f$d\f$ between each we calculate
       \f$s\f$, the minimum distance necessary to brake down to the
       opponent's velocity. It will take us \f$t\f$ seconds
       to perform this braking:
       \f[
       t = \frac{2s}{u_0+u_t}.
       \f]
       We also calculate the time to hit the other car if we do not brake.
       \f[
       t' = \frac{d}{u_0-u_t}
       \f]
   
       We then determine if we will be crashing or not by simply calculating
       \f[
       d_t = d + u_t t - s,
       \f]
       which is simply our current separation, plus the distance that will
       be travelled by the opponent, minus the distance that will be
       travelled by us. This quantity shows the minimum distance that we
       will ever have from the opponent if we hit the brakes now. 
   
       We define two constants related to \f$d_t\f$, \c
       MAX_BRAKE_FOLLOW_DISTANCE and \c MIN_BRAKE_FOLLOW_DISTANCE which
       determine the range we should keep from cars ahead of us.
   
    */

    float Driver::filterBColl(float brake)
    {
	float mu = car->_trkPos.seg->surface->kFriction;
	int i;
	float maxbrake = brake;
	for (i = 0; i < opponents->getNOpponents(); i++) {
            if (opponent[i].getState() & OPP_COLL) {
                float ut = opponent[i].getSpeed();
                float u0 = getSpeed();
                if (ut<u0 && u0 > 0.0f) {
                    float d = opponent[i].getDistance();
                    float s = brakedist(opponent[i].getSpeed(), mu);
                    float t = 2*s/(u0+ut);
                    float t_impact = d/(u0-ut);
                    float dt = d + ut*t - s;
                    float y = -1;
                    if (dt<2.0f * MAX_BRAKE_FOLLOW_DISTANCE || t_impact < OVERTAKE_TIME) {
                        //printf ("bcol: t_impact:%f dt:%f\n", t_impact, dt);
                        opponent[i].brakeForCollision();
                        if (dt<MAX_BRAKE_FOLLOW_DISTANCE) {
                            y = 1 - (dt-MIN_BRAKE_FOLLOW_DISTANCE)/(MAX_BRAKE_FOLLOW_DISTANCE-MIN_BRAKE_FOLLOW_DISTANCE);
                            if (y>0) {
                                maxbrake = SmoothMaxGamma (y, maxbrake, 0.5, 100.0);
                            } else {
                                // else we're going to crash anyway.. so..
                            }
                        }
                    }
                }
            }
	}
	//printf ("%f %f\n", brake, maxbrake);
	return maxbrake;
    }


    /// Steer filter for collision avoidance.
    float Driver::filterSColl(float steer)
    {
	int i;
	float minsidedist = FLT_MAX;
	Opponent *o = NULL;

	// Get the index of the nearest car (o).
	for (i = 0; i < opponents->getNOpponents(); i++) {
            if (opponent[i].getState() & OPP_SIDE) {
                float sidedist = fabs(opponent[i].getSideDist());
                if (sidedist < minsidedist) {
                    minsidedist = sidedist;
                    o = &opponent[i];
                }
            }
	}

	// If there is another car handle the situation.
	if (o != NULL) {
            float d = minsidedist - o->getWidth();
            // Near, so we need to look at it.
            if (d < 2.0 * SIDECOLL_MARGIN) {
                /* compute angle between cars */
                tCarElt *ocar = o->getCarPtr();
                float diffangle = ocar->_yaw - car->_yaw;
                float diff = (SIDECOLL_MARGIN-d)/SIDECOLL_MARGIN;
                //printf ("side: %f angle:%f\n", d, diffangle);
                NORM_PI_PI(diffangle);
                // We are near and heading toward the car.
                // always turn..
                if (diffangle*o->getSideDist() < 0.0) {
                    const float c = SIDECOLL_MARGIN;//2.0;
                    d = d - c;
                    if (d < 0.0) {
                        d = 0.0;
                    }

                    float psteer = 0.01f * diffangle/car->_steerLock;
                    /**< Distance to middle of segment (+ to left - to right) */
                    float side = car->_trkPos.toMiddle - ocar->_trkPos.toMiddle;
                    psteer = diff*tanh(0.1f*psteer+SIGN(side)*exp(-0.5* (fabs(o->getDistance()) + fabs(o->getSideDist()))));
                    myoffset = car->_trkPos.toMiddle;

                    float w = o->getCarPtr()->_trkPos.seg->width/WIDTHDIV-BORDER_OVERTAKE_MARGIN;
                    if (fabs(myoffset) > w) {
                        myoffset = (myoffset > 0.0) ? w : -w;
                    }

                    // Who is outside?
                    if (car->_trkPos.seg->type == TR_STR) {
                        if (fabs(car->_trkPos.toMiddle) > fabs(ocar->_trkPos.toMiddle)) {
                            psteer = steer*(d/c) + 1.5*psteer*(1.0-d/c);
                        } else {
                            psteer = steer*(d/c) + 2.0*psteer*(1.0-d/c);
                        }
                    } else {
                        float outside = car->_trkPos.toMiddle - ocar->_trkPos.toMiddle;
                        float sign = (car->_trkPos.seg->type == TR_RGT) ? 1.0 : -1.0;
                        if (outside*sign > 0.0) {
                            psteer = steer*(d/c) + 1.5*psteer*(1.0-d/c);
                        } else {
                            psteer = steer*(d/c) + 2.0*psteer*(1.0-d/c);
                        }
                    }

                    if (psteer*steer > 0.0 && fabs(steer) > fabs(psteer)) {
                        return steer;
                    } else {
                        return psteer;
                    }
                }
            }
	}
	return steer;
    }


    /// Antilocking filter for brakes.
    float Driver::filterABS(float brake)
    {
	if (car->_speed_x < ABS_MINSPEED) return brake;
	int i;
	float slip = 0.0;
	for (i = 0; i < 4; i++) {
            slip += car->_wheelSpinVel(i) * car->_wheelRadius(i);
	}
	slip = car->_speed_x - slip/4.0;
	if (slip > ABS_SLIP) {
            brake = brake - MIN(brake, (slip - ABS_SLIP)/ABS_RANGE);
	}
	return brake;
    }


    /// TCL filter for accelerator pedal.
    float Driver::filterTCL(float accel)
    {
	float slip = (this->*GET_DRIVEN_WHEEL_SPEED)() - car->_speed_x;
	TCL_status = 0.75 * TCL_status;
	if (TCL_status < 0.1) TCL_status = 0.0;
	if (slip > TCL_SLIP) {
            TCL_status +=  0.5 * (slip - TCL_SLIP)/TCL_RANGE;
	}
	accel = accel - MIN(accel, TCL_status);
	return accel;
    }


    /// Traction Control (TCL) setup.
    void Driver::initTCLfilter()
    {
	TCL_status = 0.0;
	const char *traintype = GfParmGetStr(car->_carHandle, SECT_DRIVETRAIN, PRM_TYPE, VAL_TRANS_RWD);
	if (strcmp(traintype, VAL_TRANS_RWD) == 0) {
            GET_DRIVEN_WHEEL_SPEED = &Driver::filterTCL_RWD;
	} else if (strcmp(traintype, VAL_TRANS_FWD) == 0) {
            GET_DRIVEN_WHEEL_SPEED = &Driver::filterTCL_FWD;
	} else if (strcmp(traintype, VAL_TRANS_4WD) == 0) {
            GET_DRIVEN_WHEEL_SPEED = &Driver::filterTCL_4WD;
	}
    }


    /// TCL filter plugin for rear wheel driven cars.
    float Driver::filterTCL_RWD()
    {
	return (car->_wheelSpinVel(REAR_RGT) + car->_wheelSpinVel(REAR_LFT)) *
            car->_wheelRadius(REAR_LFT) / 2.0;
    }


    /// TCL filter plugin for front wheel driven cars.
    float Driver::filterTCL_FWD()
    {
	return (car->_wheelSpinVel(FRNT_RGT) + car->_wheelSpinVel(FRNT_LFT)) *
            car->_wheelRadius(FRNT_LFT) / 2.0;
    }


    /// TCL filter plugin for all wheel driven cars.
    float Driver::filterTCL_4WD()
    {
	return ((car->_wheelSpinVel(FRNT_RGT) + car->_wheelSpinVel(FRNT_LFT)) *
                car->_wheelRadius(FRNT_LFT) +
                (car->_wheelSpinVel(REAR_RGT) + car->_wheelSpinVel(REAR_LFT)) *
                car->_wheelRadius(REAR_LFT)) / 4.0;
    }


    /// Update border feedback and steering-error learning from the frozen base demand.
    void Driver::updateTrackFeedback(tSituation* s, float baseSteer)
    {
	tTrackSeg* seg = car->_trkPos.seg;
	float target_x = (float)planningMesh->weight(currentStation());
	float trackR = fabs(car->_trkPos.toRight);
	float trackL = fabs(car->_trkPos.toLeft);
	float actual_x = trackR/(trackL + trackR);

	float orig_steer = baseSteer + 0.1*(target_x-actual_x);


	// Steering filter definition: these values make a huge
	// difference.  Using for example 0.1, 0.0, 1.0 makes for slower
	// driving.. I am not sure why.  i.e. on e-track-3, mclarenf1, you
	// get times in 1:14-1:15 with the currently used values but
	// around 1:16 1:17 with the others.  the -0.1 term that subtracts
	// the predicted error is there to prevent the error from growing
	// too much.
	float dtm = -( 0.1 * orig_steer
                       - 0.1 * learn->predictedError(car)
                       + 0.2 * (target_x - actual_x));//(car->_trkPos.toMiddle);
	float tm = fabs(actual_x - target_x);

        /*float speed_to_inside = 0.0;
	if (car->_trkPos.toMiddle*speedangle > 0.0) {
            speed_to_inside = 0.5;
	}*/
	if (car->_speed_x < MAX_UNSTUCK_SPEED ||		// Too slow.
            pit->getInPit())// ||							// Pit stop.
            //car->_trkPos.toMiddle*speedangle > 0.0)		// Speedvector points to the inside of the turn.
            {
		float w = car->_dimension_y/seg->width;
		if (car->_speed_x < MAX_UNSTUCK_SPEED) {
                    learn->updateAccel (s, car, -1.0, tm-w,dtm);
		}
		return;
            }
	float accident = 0.0;
	float margin = fabs(car->_trkPos.toMiddle) - 0.5*seg->width;
	if (margin > 0.0) {
            if (margin > .5*car->_dimension_y) {
                accident = -1;
            }
            if (car->_trkPos.toRight<car->_dimension_y) {
                dtm -= 10.0*tanh((car->_dimension_y - car->_trkPos.toRight));
            } else 	if (car->_trkPos.toLeft<car->_dimension_y) {
                dtm -= 10.0*tanh((car->_trkPos.toLeft - car->_dimension_y));
            }
            //printf ("%f %f %f\n", -orig_steer, dtm, margin);
			
	}
	//	printf ("%.1f %.1f %.1f %.1f | ",
	//prev_toleft, prev_toright,
	//u_toleft, u_toright);
	float uleft = 0; 

	float uright = 0;
	if (dt > 0.001) {
            uleft = (car->_trkPos.toLeft - prev_toleft)/dt;
            uright = (car->_trkPos.toRight - prev_toright)/dt;
	}
	u_toleft = .9*u_toleft + 0.1*uleft;
	u_toright = .9*u_toright + 0.1*uright;
	prev_toleft = car->_trkPos.toLeft;
	prev_toright = car->_trkPos.toRight;
	float danger = 1000.0; // larger, less danger
	float steer_adjust = 0.0;
			
	if ((seg->type == TR_RGT) ||(car->_steerCmd < 0.1f)) {
            //printf ("RIGHT: %f\n", car->_steerCmd);
            if (u_toleft<0) {
                danger = -car->_trkPos.toLeft/u_toleft;
                steer_adjust = -1.0/(1.0 + fabs(danger));
                //printf ("LCR: %fs %d\n", danger, seg->id);
            } else if (u_toright>0) {
                danger = -2.0*car->_trkPos.toRight/u_toright;
                steer_adjust = 0.1f;//(1.0 + fabs(danger));
                //printf ("RCR: %fs %d\n", danger, seg->id);
            }
	}
	if ((seg->type == TR_LFT)||(car->_steerCmd > 0.1f)) {
            //printf ("LEFT: %f\n", car->_steerCmd);
            if (u_toright<0) {
                danger = -car->_trkPos.toRight/u_toright;
                steer_adjust = 1.0f/(1.0f+fabs(danger));
                //printf ("RCL: %fs %d\n", danger, seg->id);
            } else if (u_toleft<0) {
                danger = -2.0f*car->_trkPos.toLeft/u_toleft;
                steer_adjust = -0.1f;//(1.0+fabs(danger));
                //printf ("LCL: %fs %d\n", danger, seg->id);
            }
	}
	if (danger>0) {
            if (danger<0.5) {
                car->_steerCmd += STEER_EMERGENCY_GAIN * steer_adjust;
            } else if (danger<1.0) {
                car->_steerCmd += STEER_EMERGENCY_GAIN * (danger-2) * steer_adjust;
            } 
	}
	float allowance = seg->type == TR_STR ? car->_dimension_y/seg->width : 1.0f/WIDTHDIV;
	learn->updateAccel(s, car, accident, tm-allowance, dtm);
    }


    /// Compute the needed distance to brake.
    float Driver::brakedist(float allowedspeed, float mu)
    {
	float c,d;
	if (pit->getInPit()) {
            c = mu*G;
            d = (CA*mu + CW)/mass;
            //float dm=learn->GetFrictionDm(car->_trkPos.seg);
            //float dm2=learn->GetFrictionDm2(car->_trkPos.seg);
	} else {
            //printf ("%f %f\n", learn->GetFrictionDm(car->_trkPos.seg)
            //, learn->GetFrictionDm2(car->_trkPos.seg));
            c = mu*G + learn->GetFrictionDm(car->_trkPos.seg);
            d = (CA*mu + CW)/mass;
            //+ learn->GetFrictionDm2(car->_trkPos.seg))/mass;
            //+ learn->GetFrictionDm3(car->_trkPos.seg))/mass;
	}
	float v1sqr = currentspeedsqr;
	float v2sqr = allowedspeed*allowedspeed;
	return -log((c + v2sqr*d)/(c + v1sqr*d))/(2.0*d);
    }



    /**
       \brief Prepare a car-clearance-constrained path through the track.

       The regular mesh minimizes planar bending energy using a coupled
       Gauss-Newton solve and a cost-decreasing line search. The result is a
       geometric racing line, not a minimum-lap-time solution.

    */
    void Driver::prepareTrack()
    try
    {
        planningMesh.reset(new PlanningMesh(*track));
        PlanningMesh& mesh = *planningMesh;
        mesh.optimise(0.5*car->_dimension_y + 0.2);
        for (int i = 0; i < track->nseg; ++i) {
            const tTrackSeg& seg = mesh.nativeSegment(i);
            float weight, curvature;
            // Mapping validates the native section even without diagnostics.
            mesh.map(seg, mesh.nativeStart(i), weight, curvature);
            float mappedRadius = 1.0f/curvature;
            radius[seg.id] = (std::isnan(mappedRadius) || mappedRadius > 10000.0f) ? 10000.0f : mappedRadius;
            if (diagnosticsEnabled) {
                PlanningPoint p = PlanningMesh::nativeSection(seg).point(weight);
                fprintf(stderr, "OlethrosSeam path bot=%d i=%d seg=%d distance=%.9g length=%.9g x=%.9g y=%.9g w=%.9g curvature=%.9g radius=%.9g\n",
                    INDEX, i, seg.id, seg.lgfromstart, seg.length, p.x, p.y, weight, curvature, mappedRadius);
            }
        }




    }

    catch (const std::exception& error) {
        GfError("Olethros planning initialization failed: %s\n", error.what());
        // GfFatal is only printf on Windows. Never drive a partial/default plan.
        exit(EXIT_FAILURE);
    }
