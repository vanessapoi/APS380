// -*- Mode: C++ -*-
/***************************************************************************

    file                 : driver.h
    created              : Thu Dec 20 01:20:19 CET 2002
    copyright            : (C) 2002-2004 Bernhard Wymann
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

/** @file driver.h
 * @brief Per-bot orchestration, retained planning geometry and control state.
 * @ingroup olethros_control
 */
#ifndef _DRIVER_H_
#define _DRIVER_H_

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <memory>
#include <vector>

#include <tgf.h>
#include <track.h>
#include <car.h>
#include <raceman.h>
#include <robottools.h>
#include <robot.h>

#include "linalg.h"
#include "opponent.h"
#include "pit.h"
#include "learn.h"
#include "strategy.h"
#include "cardata.h"

static const char OLETHROS_SECT_PRIV[] = "olethros private";
static const char OLETHROS_ATT_FUELPERLAP[] = "fuel per lap";
static const char OLETHROS_ATT_FUELCONSUMPTION[] = "fuel consumption";
static const char OLETHROS_ATT_MUFACTOR[] = "mufactor";

class Opponents;
class Opponent;
class Pit;
class AbstractStrategy;
class PlanningMesh;

/**
   @brief One Olethros robot instance, derived from the BT control architecture.
   @details Owns planning, opponents, pit, strategy, learning and native radii.
   The TORCS track/car are borrowed. Cardata is shared across instances;
   its SingleCardata lookups are borrowed. Call initTrack(), then newRace(),
   before drive(). The TORCS callback lifecycle controls destruction.
*/
class Driver {
public:
	/** @brief Construct the bot slot; index 6 is the displayed Olethros 7. */
	Driver(int index);
	~Driver();

	/** @brief Select setup and initial fuel for a new track/session.
	 * @param[in] t Borrowed TORCS track, which must outlive the race.
	 * @param[in] carHandle TORCS car parameter handle.
	 * @param[out] carParmHandle Selected robot setup handle for TORCS.
	 * @param[in] s Session type and race configuration.
	 */
	void initTrack(tTrack* t, void *carHandle, void **carParmHandle, tSituation *s);
	/** @brief Initialize car constants, the regular path, opponents, pit and learning.
	 * @param[in] car Borrowed car controlled by this instance.
	 * @param[in] s Initial race state.
	 * @details Loads a brain outside practice; test isolation belongs to the runner.
	 */
	void newRace(tCarElt* car, tSituation *s);
	/** @brief Update observations and write steering, gear, pedals and clutch for this tick.
	 * @param[in] s Current simulation state and time in seconds.
	 * @details Also updates learning, speed history and pit requests; see README.md
	 * for the actual filter order and the stuck/reverse branch.
	 */
	void drive(tSituation *s);
	/** @brief Request repair/refuel amounts, clear the pit request and return ROB_PIT_IM. */
	int pitCommand(tSituation *s);
	/** @brief End-race callback; currently has no action (saving occurs at destruction). */
	void endRace(tSituation *s);

	/** @brief Borrow the controlled TORCS car; valid after newRace(). */
	tCarElt *getCarPtr() { return car; }
	/** @brief Borrow the current TORCS track. */
	tTrack *getTrackPtr() { return track; }
	/** @brief Signed velocity projected onto the native track tangent, in m/s. */
	float getSpeed() { return mycardata->getSpeedInTrackDirection(); /*speed;*/ }

protected:
	// Utility functions.
	/** @brief Format the session setup path; unknown session types use default.xml. */
	void getSetupFileName(char* buffer, size_t size, const char* filename, int raceType) const;
	/** @brief Update stuck counter and decide whether to use reverse recovery. */
	bool isStuck();
	/** @brief Refresh shared car facts, relative opponents, strategy and derived car state. */
	void update(tSituation *s);
	/** @brief Build and retain the regular path; logs and terminates on planning failure. */
	void prepareTrack();
	/** @brief Allowed speed (m/s) at station (m), combining path curvature and native metadata. */
	float getAllowedSpeed(double station);
	/** @brief Current track station (m); converts curve-local toStart from radians. */
	double currentStation() const;
	/** @brief Interpolated regular-grid adaptive speed cap in m/s; not persisted in a brain. */
	float pathSpeedHistory(double station) const;
	std::unique_ptr<PlanningMesh> planningMesh; ///< Owned retained planning/query representation.
	std::vector<float> meshSpeedHistory; ///< Per-regular-sample in-memory speed caps in m/s.
	/** @brief Compute throttle demand from speed lookahead, history and strategy. */
	float getAccel();
	/** @brief Remaining centerline distance in meters to the native segment end. */
	float getDistToSegEnd();
	/** @brief Strongest braking demand over regular stations and native boundaries. */
	float getBrake();
	/** @brief Select forward gear using engine limits and wheel speed. */
	int getGear();
	/** @brief Interpolate the retained engine torque table at the supplied engine speed. */
	float EstimateTorque (float rpm);
	/** @brief Pure steering calculation for a frozen world target and current car observations. */
	float getSteer(const v2d& target) const;
	/** @brief Compute clutch disengagement demand, including launch timing. */
	float getClutch();
	/** @brief Advance avoidance/lookahead once and return the tick's world XY target. */
	v2d updateTargetPoint();
	/** @brief Update signed lateral offset in meters for passing and yielding. */
	float getOffset();
	/** @brief Estimated distance (m) to allowedspeed (m/s), with friction mu and aero terms. */
	float brakedist(float allowedspeed, float mu);

	/** @brief Modify braking to avoid predicted opponent contact. */
	float filterBColl(float brake);
	/** @brief Reduce braking when average wheel slip exceeds the ABS thresholds. */
	float filterABS(float brake);
	/** @brief Apply pit entry, speed limit and stopping constraints to braking. */
	float filterBPit(float brake);
	/** @brief Scale brake demand with aerodynamic load and speed. */
	float filterBrakeSpeed(float brake);

	/** @brief Advance TCL state and reduce throttle for slip; called once per normal tick. */
	float filterTCL(float accel);
	/** @brief Update track-error learning and emergency steering once outside the pit.
	 * @param[in] s Current observations and simulation time.
	 * @param[in] baseSteer Uncorrected steering from this tick's frozen target.
	 * @details Does not query a new target or advance traction control.
	 */
	void updateTrackFeedback(tSituation* s, float baseSteer);
	/** @brief Restrict throttle while stopping in the pit. */
	float filterAPit(float accel);

	/** @brief Adjust steering for adjacent opponents. */
	float filterSColl(float steer);

	/** @brief Rear driven-wheel circumferential speed in m/s. */
	float filterTCL_RWD();
	/** @brief Front driven-wheel circumferential speed in m/s. */
	float filterTCL_FWD();
	/** @brief Four-wheel average driven-wheel circumferential speed in m/s. */
	float filterTCL_4WD();
	/** @brief Select the driven-wheel speed callback from the drivetrain setup. */
	void initTCLfilter();

	/** @brief Read aerodynamic setup and calculate downforce coefficient. */
	void initCa();
	/** @brief Calculate aerodynamic drag coefficient from car setup. */
	void initCw();
	/** @brief Read tire friction coefficients used by speed planning. */
	void initTireMu();

	/** @brief Determine whether nearby opponents require coupled driving behavior. */
	int isAlone();


	float current_allowed_speed;
	unsigned long long diagnosticTick; ///< Race-local callback sequence for complete telemetry.
	bool diagnosticsEnabled; ///< Environment flag cached at construction for this driver's lifetime.
	// Per robot global data.
	int race_type;
	int stuck;
	float speedangle;		///< the angle of the speed vector relative to trackangle, > 0.0 points to right.
	float mass;				///< Mass of car + fuel.
	float myoffset;			///< Offset to the track middle.
	tCarElt *car;			///< Pointer to tCarElt struct.

	Opponents *opponents;	///< The container for opponents.
	Opponent *opponent;		///< The array of opponents.

	Pit *pit;						///< Pointer to the pit instance.
	float pit_exit_timer;
	AbstractStrategy *strategy;		///< Pit stop strategy.

	static Cardata *cardata;		///< Data about all cars shared by all instances.
	SingleCardata *mycardata;		///< Pointer to "global" data about my car.
	static double currentsimtime;	///< Store time to avoid useless updates.

	float currentspeedsqr;	///< Square of the current speed_x.
	float clutchtime;		///< Clutch timer.
	float oldlookahead;		///< Lookahead for steering in the previous step.

	float speed_factor; ///< speed factor to use.

	float *radius; ///< Owned native-ID compatibility radii in meters.
	SegLearn *learn; ///< handle to learning module
	int alone; ///< whether we are alone
	bool overtaking; ///< are we overtaking?
	float prev_steer; ///< for steering filter
	float prev_toleft; ///< previous left margin
	float prev_toright; ///< previous right margin
	float u_toleft; ///< speed to left side
	float u_toright; ///< speed to right side
	float dt; ///< Engine robot interval in seconds, assigned for this bot on every update.
	float TCL_status; ///< traction control
	float alone_count; 

	// Data that should stay constant after first initialization.
	int MAX_UNSTUCK_COUNT;
	int INDEX;
	float CARMASS;		///< Mass of the car only [kg].
	float CA;			///< Aerodynamic downforce coefficient.
	float CW;			///< Aerodynamic drag coefficient.
	float TIREMU;		///< Friction coefficient of tires.
	float (Driver::*GET_DRIVEN_WHEEL_SPEED)();
	float OVERTAKE_OFFSET_INC;		///< [m/timestep]
	float MU_FACTOR;				///< [-]

	// Class constants.
	static const float MAX_UNSTUCK_ANGLE;
	static const float UNSTUCK_TIME_LIMIT;
	static const float MAX_UNSTUCK_SPEED;
	static const float MIN_UNSTUCK_DIST;
	static const float G;
	static const float FULL_ACCEL_MARGIN;
	static const float SHIFT;
	static const float SHIFT_MARGIN;
	static const float ABS_SLIP;
	static const float ABS_RANGE ;
	static const float ABS_MINSPEED;
	static const float TCL_SLIP;
	static const float LOOKAHEAD_CONST;
	static const float LOOKAHEAD_FACTOR;
	static const float WIDTHDIV;
	static const float SIDECOLL_MARGIN;
	static const float BORDER_OVERTAKE_MARGIN;
	static const float OVERTAKE_OFFSET_SPEED;
	static const float OVERTAKE_TIME;
	static const float PIT_LOOKAHEAD;
	static const float PIT_MU;
	static const float MAX_SPEED;
	static const float TCL_RANGE;
	static const float MAX_FUEL_PER_METER;
	static const float CLUTCH_SPEED;
	static const float CENTERDIV;
	static const float DISTCUTOFF;
	static const float MAX_INC_FACTOR;
	static const float CATCH_FACTOR;
	static const float CLUTCH_FULL_MAX_TIME;
	static const float USE_LEARNED_OFFSET_RANGE;
	static const float ACCELERATOR_LETGO_TIME;
	static const float MIN_BRAKE_FOLLOW_DISTANCE;
	static const float MAX_BRAKE_FOLLOW_DISTANCE;
	static const float STEER_DIRECTION_GAIN;
	static const float STEER_PREDICT_GAIN;
	static const float STEER_DRIFT_GAIN;
	static const float STEER_AVOIDANCE_GAIN;
	static const float STEER_EMERGENCY_GAIN;
	static const float FILTER_STEER_FEEDBACK;
	static const float FILTER_PREDICT_FEEDBACK;
	static const float FILTER_TARGET_FEEDBACK;
	// Track variables.
	tTrack* track;
};

#endif // _DRIVER_H_
