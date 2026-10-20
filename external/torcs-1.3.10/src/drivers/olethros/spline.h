/***************************************************************************

    file                 : spline.h
    created              : Wed Mai 14 19:53:00 CET 2003
    copyright            : (C) 2003-2004 by Bernhard Wymann
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

/** @file spline.h
 * @brief Small cubic Hermite interpolator used for pit lateral displacement.
 * @ingroup olethros_pits
 */
#ifndef _SPLINE_H_
#define _SPLINE_H_

/** @brief One Hermite knot: x station, y displacement and s=dy/dx. */
class SplinePoint {
	public:
		float x;	///< Longitudinal coordinate (meters for the pit spline).
		float y;	///< Interpolated value (lateral meters for the pit spline).
		float s;	///< Derivative dy/dx.
};


/** @brief Piecewise cubic Hermite interpolation over borrowed knots.
 * @details At least two knots are required. The chosen interval must have
 * strictly increasing x coordinates. Queries beyond the knot range extrapolate
 * using the first/last interval; no clamping or bounds validation is performed.
 */
class Spline {
	public:
		/** @brief Borrow dim knots; their storage must outlive the spline. */
		Spline(int dim, SplinePoint *s);

		/** @brief Binary-search the interval and evaluate the Hermite polynomial at z. */
		float evaluate(float z);

	private:
		SplinePoint *s;
		int dim;
};

#endif // _SPLINE_H_
