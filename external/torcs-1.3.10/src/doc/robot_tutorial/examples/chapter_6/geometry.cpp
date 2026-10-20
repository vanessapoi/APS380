/***************************************************************************

    file                 : geometry.cpp
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
#include "geometry.h"

Vector2
Vector2::operator+(const Vector2& other) const
{
	return {x + other.x, y + other.y};
}

Vector2
Vector2::operator-(const Vector2& other) const
{
	return {x - other.x, y - other.y};
}

Vector2
Vector2::operator-() const
{
	return {-x, -y};
}

Vector2
Vector2::operator*(double scale) const
{
	return {x * scale, y * scale};
}

Vector2
operator*(double scale, const Vector2& vector)
{
	return vector * scale;
}

double
Vector2::dot(const Vector2& other) const
{
	return x * other.x + y * other.y;
}

double
Vector2::cross(const Vector2& other) const
{
	return x * other.y - y * other.x;
}

double
Vector2::length() const
{
	return std::hypot(x, y);
}

double
Vector2::distance(const Vector2& other) const
{
	return (*this - other).length();
}

bool
Vector2::normalize()
{
	const double size = length();
	if (!std::isfinite(size) || size <= 1e-12) {
		return false;
	}
	x /= size;
	y /= size;
	return true;
}

bool
Vector2::cosineAt(const Vector2& other, const Vector2& center, double& cosine) const
{
	Vector2 a = *this - center;
	Vector2 b = other - center;
	if (!a.normalize() || !b.normalize()) {
		return false;
	}
	cosine = std::max(-1.0, std::min(1.0, a.dot(b)));
	return true;
}

Vector2
Vector2::rotated(const Vector2& center, double angle) const
{
	const Vector2 delta = *this - center;
	const double c = std::cos(angle);
	const double s = std::sin(angle);
	return center + Vector2{delta.x * c - delta.y * s, delta.x * s + delta.y * c};
}

Line2::Line2(const Vector2& anchor, const Vector2& direction)
	: anchor(anchor), direction(direction), valid(this->direction.normalize())
{
}

bool
Line2::intersect(const Line2& other, Vector2& point) const
{
	const double denominator = direction.cross(other.direction);
	if (!valid || !other.valid || std::fabs(denominator) < 1e-10) {
		return false;
	}
	const double t = (other.anchor - anchor).cross(other.direction) / denominator;
	point = anchor + direction * t;
	return true;
}

double
Line2::distance(const Vector2& point) const
{
	if (!valid) {
		return std::numeric_limits<double>::infinity();
	}
	const Vector2 delta = point - anchor;
	return (delta - direction * delta.dot(direction)).length();
}
