/***************************************************************************

    file                 : spline.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#ifndef _TUTORIALB_SPLINE_H_
#define _TUTORIALB_SPLINE_H_
#include <vector>

struct SplineKnot {
	double distance;
	double offset;
	double slope; // d(offset)/d(distance), not derivative in normalized t
};

class HermiteSpline {
public:
	bool setKnots(const std::vector<SplineKnot>& points);
	double value(double distance) const;
	double derivative(double distance) const;
private:
	std::vector<SplineKnot> knots;
	int interval(double distance) const;
	double evaluate(double distance, bool derivative) const;
};
#endif
