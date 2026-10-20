/***************************************************************************

    file                 : braking.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#include <algorithm>
#include <cmath>
#include <limits>
#include "braking.h"

// Optional numerical-integration experiment: try 1, 4, 8, and 32 intervals.
static constexpr int NUMERICAL_INTERVALS = 8;

double
brakingDistance(double initialSpeed, double finalSpeed, double a0,
	double b, BrakingModel model, int intervals)
{
	if (!std::isfinite(initialSpeed) || !std::isfinite(finalSpeed) ||
		initialSpeed < 0.0 || finalSpeed < 0.0) {
		return std::numeric_limits<double>::infinity();
	}
	if (initialSpeed <= finalSpeed) {
		return 0.0;
	}
	const double initialSquared = initialSpeed * initialSpeed;
	const double finalSquared = finalSpeed * finalSpeed;
	const double difference = (initialSpeed - finalSpeed) * (initialSpeed + finalSpeed);
	if (model == BrakingModel::Basic) {
		b = 0.0;
	}
	if (a0 <= 0.0 || !std::isfinite(initialSquared) ||
		!std::isfinite(a0) || !std::isfinite(b) ||
		std::min(a0 + b * initialSquared, a0 + b * finalSquared) <= 0.0) {
		return std::numeric_limits<double>::infinity();
	}
	if (b == 0.0) {
		return difference / (2.0 * a0);
	}
	if (model == BrakingModel::AeroBound) {
		const double weakest = std::min(a0 + b * initialSquared, a0 + b * finalSquared);
		return difference / (2.0 * weakest);
	}
	if (model == BrakingModel::AeroNumerical) {
		// Rectangle sums in u = v^2. Use the weaker endpoint in each interval.
		const int count = std::max(1, intervals);
		const double step = difference / count;
		double distance = 0.0;
		for (int i = 0; i < count; ++i) {
			const double low = std::min(initialSquared, finalSquared + i * step);
			const double high = std::min(initialSquared, finalSquared + (i + 1) * step);
			const double weakest = std::min(a0 + b * low, a0 + b * high);
			distance += step / (2.0 * weakest);
		}
		return distance;
	}

	// log1p avoids loss of precision when the speed change or aero term is small.
	const double z = b * difference / (a0 + b * finalSquared);
	if (z <= -1.0) {
		return std::numeric_limits<double>::infinity();
	}
	if (std::fabs(z) < 1e-8) {
		// log(1+z)/z = 1-z/2+z^2/3...; also covers underflow to zero.
		return difference / (2.0 * (a0 + b * finalSquared)) * (1.0 - z / 2.0);
	}
	return std::log1p(z) / (2.0 * b);
}

double
allowedApproachSpeed(double finalSpeed, double distance, double a0,
	double b, BrakingModel model, double speedCap)
{
	const double target = std::max(0.0, std::min(finalSpeed, speedCap));
	if (distance <= 0.0 || target >= speedCap) {
		return target;
	}
	if (model == BrakingModel::Basic) {
		return std::min(speedCap, std::sqrt(target * target + 2.0 * std::max(0.0, a0) * distance));
	}
	// The same bounded search works for all three aerodynamic distance models.
	double low = target;
	double high = speedCap;
	for (int i = 0; i < 24; ++i) {
		const double candidate = 0.5 * (low + high);
		if (brakingDistance(candidate, target, a0, b, model, NUMERICAL_INTERVALS) <= distance) {
			low = candidate;
		} else {
			high = candidate;
		}
	}
	return low;
}

double
cornerSpeed(double radius, double grip, double mass, double downforce, double speedCap)
{
	if (radius <= 0.0 || grip <= 0.0 || mass <= 0.0) {
		return 0.0;
	}
	const double denominator = 1.0 - grip * downforce * radius / mass;
	if (denominator <= 0.0) {
		// This model supplies no finite cornering bound; the driving cap still applies.
		return speedCap;
	}
	return std::min(speedCap, std::sqrt(grip * 9.81 * radius / denominator));
}
