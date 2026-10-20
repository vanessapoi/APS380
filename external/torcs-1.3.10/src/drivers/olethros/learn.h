// -*- Mode: c++ -*-
/***************************************************************************

    file                 : learn.h
    created              : Wed Aug 28 16:36:00 CET 2004
    copyright            : (C) 2004-2026 by Bernhard Wymann
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


/** @file learn.h
 * @brief Native-segment learning, eligibility traces and brain persistence.
 * @ingroup olethros_learning
 */
#ifndef _SEGLEARN_H_
#define _SEGLEARN_H_

#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#include <tgf.h>
#include <track.h>
#include <car.h>
#include <raceman.h>
#include <robottools.h>
#include <robot.h>


/** @brief Driver-owned adaptive state indexed by native segments and quantums.
 * @details Borrows the track, owns numerical arrays. A quantum groups native
 * IDs; regular planning indices never index these arrays. Training and output
 * consumption are separate: some retained predictions currently return zero.
 */
class SegLearn {
public:
	/** @brief Allocate fresh initialized state for the borrowed track. */
	SegLearn(tTrack* t);
	~SegLearn();
	/// Return the learned additive radius correction in meters for native segment s.
	float getRadius(tTrackSeg *s) { return radius[s->id]; }
	/** @brief Update radius corrections and their backward eligibility grouping.
	 * @param[in] s Race state, including lap and remaining laps.
	 * @param[in] t Borrowed native track.
	 * @param[in] car Observed car.
	 * @param[in] alone Whether learning has an uncontested path observation.
	 * @param[in] offset Current avoidance displacement in meters.
	 * @param[in] outside Measured outside-path allowance in meters.
	 * @param[in] r Native-ID nominal radii in meters.
	 * @param[in] alpha Planned lateral weight, dimensionless.
	 * @param[in] speed Current speed in m/s.
	 * @param[in] limit Driver speed-limit argument in m/s.
	 * @details Driver calls this radius update outside race sessions only.
	 */
	void update(tSituation *s, tTrack *t, tCarElt *car, int alone, float offset, float outside, float *r, float alpha, float speed, float limit);
	/** @brief Update quantum prediction/eligibility state; currently returns zero.
	 * @param[in] s Current simulation time/state.
	 * @param[in] car Car whose native segment chooses the quantum.
	 * @param[in] taccel Proposed signed pedal demand.
	 * @param[in] derr Steering-control error signal.
	 * @param[in] dtm Lateral path-error signal.
	 * @return Zero; state updates and predictedError() remain active.
	 */
	float updateAccel (tSituation* s, tCarElt* car, float taccel, float derr, float dtm);
	/// Return learned steering-error feedback for the car's quantum.
	float predictedError (tCarElt* car);
	/// Retained acceleration predictor; currently returns zero for every segment.
	float predictedAccel (tTrackSeg* seg);
	/** @brief Update the friction/braking model from successive observations.
	 * @param[in] s Native segment supplying metadata and segment-indexed coefficients.
	 * @param[in] G Gravitational acceleration in m/s^2.
	 * @param[in] mass_ Car plus fuel mass in kg.
	 * @param[in] CA_ Aerodynamic downforce coefficient.
	 * @param[in] CW_ Aerodynamic drag coefficient.
	 * @param[in] u_ Track-direction velocity in m/s.
	 * @param[in] brake_ Positive braking or negative throttle demand.
	 * @param[in] learning_rate Update gain; zero suppresses coefficient learning.
	 */
	void AdjustFriction (tTrackSeg* s, float G, float mass_, float CA_, float CW_, float u_, float brake_, float learning_rate = 1.0);
	/// Get friction coefficient
	float GetFrictionDm(tTrackSeg* s) {return (dm + segdm[s->id]);}
	/// Get friction coefficient
	float GetFrictionDm2(tTrackSeg* s) {return (dm2 + segdm2[s->id]);}
	/// Get friction coefficient
	float GetFrictionDm3(tTrackSeg* s) {return (dm3 + segdm3[s->id]);}
	enum LoadResult { BRAIN_MISSING, BRAIN_LOADED, BRAIN_REJECTED, BRAIN_IO_ERROR };
	/** @brief Load complete, finite, compatible native binary state if fname exists.
	 * @param[in] fname Brain filename, including directory.
	 * @details Uses native float/int layout. Invalid files leave all prior state
	 * unchanged and produce a diagnostic; missing files are normal.
	 * @return Whether the brain was missing, adopted, rejected or could not be opened.
	 */
	LoadResult loadParameters (const char* fname);
	/** @brief Write finite state via a sibling temporary file and replace fname on success.
	 * @details Failures retain the prior brain and report a diagnostic. Session
	 * policy belongs to Driver; the native binary layout is unchanged.
	 */
	void saveParameters (const char* fname);

	/** @brief Set the dimensionless radius-update safety threshold. */
	void SetSafetyThreshold (float st) {safety_threshold = st;}
private:
	/** @brief Saturate a scalar to [-1,1]. */
	float tand(float x)
	{
		if (x>1.0) {
			return 1.0;
		} else if (x<-1.0) {
			return -1.0;
		}
		return x;
	}

	/** @brief Piecewise derivative of tand(), using one at both endpoints. */
	float tand_der(float x)
	{
		if (x>1.0) {
			return 0.0;
		} else if (x<-1.0) {
			return 0.0;
		}
		return 1.0;
	}
	float safety_threshold;

	/** @brief Spread a radius update backward over at most max_length track meters. */
	void PropagateUpdateBackwards (tTrackSeg* pseg, float d, float beta, float max_length);
	float time_since_accident;
	/// Class for computing averages of measured values
	class Averages {
	public:
		Averages ()
		{
			k=0;
			taccel = derr = dtm = 0.0;
		}
		int k; ///< number of measurements
		float taccel; ///< acceleration
		float derr; ///< steering error
		float dtm; ///< path error
		/// Add measurements to list.
		void Measure(float taccel_, float derr_, float dtm_)
		{
			float r = (float) k;
			float d = 1.0f/(1.0f + (float) k);
			taccel = d *(taccel * r + taccel_);
			derr = d *(derr * r + derr_);
			dtm = d *(dtm * r + dtm_);
			k++;
		}
	};
	Averages averages; ///< holds average measurements
	tTrack* track; ///< A pointer to the current track
	int n_quantums; ///< number of quantums the track is split for learning
	int segments_per_quantum; ///< number of segments each quantum contains
	int prev_quantum; ///< id of the previous quantum
	float prev_accel; ///< previous acceleration
	double previous_time; ///< previous time
	int segQuantum (int segid); ///< The quantum ID of a given segment ID
	float *radius; ///< Array holding the radi of segments
	int *updateid; ///< Array holding the segments to be update
	float* accel; ///< Accelerations for each quantum
	float* derror; ///< Steering control for each quantum
	float* elig; ///< Eligibility of previously visited quantums for updates

	// estimates for friction
	float* segdm; ///< friction coefficient 1
	float* segdm2; ///< friction coefficient 2
	float* segdm3; ///< friction coefficient 3
	int prevsegid; ///< id of previous segment
	float W_brake;
	float W_accel;
	float dm; ///< global friction coefficient 1
	float dm2; ///< gloabal friction coefficient 2
	float dm3; ///< global friction coefficient 3
	float mu; ///< friction constant
	float mass; ///< mass
	float CA; ///< downforce constant
	float CW; ///< drag constant
	float u; ///< speed
	float brake; ///< brake input
	double prev_time; ///< time of previous friction estimate
	double delta_time; ///< dt for friction estimate
	double time_since_left_turn;
	double time_since_right_turn;
	bool check; ///< whether we should update radius
	float rmin; ///< current estimated minimum radius
	int lastturn; ///< type of last turn entered
	int prevtype;  ///< type of previous segment
	int n_seg; ///< total number of track segments
	bool new_lap; ///< we made a new lap
	int remaining_laps; ///< remaining_laps
    int lap; ///< current lap
};




#endif //_SEGLEARN_H_
