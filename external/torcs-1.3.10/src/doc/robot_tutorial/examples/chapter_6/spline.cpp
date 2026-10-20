/***************************************************************************

    file                 : spline.cpp
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
#include "spline.h"

bool
HermiteSpline::setKnots(const std::vector<SplineKnot>& points)
{
	knots.clear();
	if (points.size() < 2) {
		return false;
	}
	for (std::size_t i = 0; i < points.size(); ++i) {
		const auto& p = points[i];
		if (!std::isfinite(p.distance) || !std::isfinite(p.offset) || !std::isfinite(p.slope) ||
			(i && p.distance - points[i - 1].distance < 1e-4)) {
			return false;
		}
	}
	knots = points;
	return true;
}

int
HermiteSpline::interval(double distance) const
{
	int low = 0;
	int high = static_cast<int>(knots.size()) - 1;
	while (high - low > 1) {
		const int middle = low + (high - low) / 2;
		if (distance < knots[middle].distance) {
			high = middle;
		} else {
			low = middle;
		}
	}
	return low;
}

double
HermiteSpline::evaluate(double distance, bool slope) const
{
	if (knots.size() < 2 || !std::isfinite(distance)) {
		return 0.0;
	}
	if (distance < knots.front().distance) {
		return slope ? 0.0 : knots.front().offset;
	}
	if (distance > knots.back().distance) {
		return slope ? 0.0 : knots.back().offset;
	}
	const int i = interval(distance);
	const auto& p = knots[i];
	const auto& q = knots[i + 1];
	const double h = q.distance - p.distance;
	const double t = (distance - p.distance) / h;
	const double difference = q.offset - p.offset;
	const double a = -2.0 * difference + h * (p.slope + q.slope);
	const double b = 3.0 * difference - h * (2.0 * p.slope + q.slope);
	const double c = h * p.slope;
	return slope ? ((3.0 * a * t + 2.0 * b) * t + c) / h :
		((a * t + b) * t + c) * t + p.offset;
}

double
HermiteSpline::value(double distance) const
{
	return evaluate(distance, false);
}

double
HermiteSpline::derivative(double distance) const
{
	return evaluate(distance, true);
}
