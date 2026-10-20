/***************************************************************************

    file                 : geometry.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#ifndef _TUTORIALC_GEOMETRY_H_
#define _TUTORIALC_GEOMETRY_H_

struct Vector2 {
	double x = 0.0;
	double y = 0.0;
	Vector2 operator+(const Vector2& other) const;
	Vector2 operator-(const Vector2& other) const;
	Vector2 operator-() const;
	Vector2 operator*(double scale) const;
	double dot(const Vector2& other) const;
	double cross(const Vector2& other) const;
	double length() const;
	double distance(const Vector2& other) const;
	bool normalize();
	bool cosineAt(const Vector2& other, const Vector2& center, double& cosine) const;
	Vector2 rotated(const Vector2& center, double angle) const;
};

Vector2 operator*(double scale, const Vector2& vector);

class Line2 {
public:
	Line2(const Vector2& anchor, const Vector2& direction);
	bool intersect(const Line2& other, Vector2& point) const;
	double distance(const Vector2& point) const;
private:
	Vector2 anchor;
	Vector2 direction;
	bool valid;
};

#endif
