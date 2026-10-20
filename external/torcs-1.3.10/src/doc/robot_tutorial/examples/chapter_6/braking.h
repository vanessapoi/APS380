/***************************************************************************

    file                 : braking.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#ifndef _TUTORIAL6_BRAKING_H_
#define _TUTORIAL6_BRAKING_H_

enum class BrakingModel { Basic, AeroBound, AeroNumerical, AeroAnalytical };

// SI units: speeds m/s, distance m, a0 m/s^2, b 1/m.
// Nonnegative speeds and a0 > 0 are the supported braking-model domain.
// Returns infinity if positive deceleration is unavailable over the interval.
double brakingDistance(double initialSpeed, double finalSpeed, double a0,
	double b, BrakingModel model, int intervals = 8);
double allowedApproachSpeed(double finalSpeed, double distance, double a0,
	double b, BrakingModel model, double speedCap);
double cornerSpeed(double radius, double grip, double mass, double downforce,
	double speedCap);

#endif
