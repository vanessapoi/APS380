/* SPDX-License-Identifier: GPL-2.0-or-later
 * Opt-in keyboard pedals only. Units are pedal fraction per simulation second. */
#ifndef APS380_KEYBOARD_H
#define APS380_KEYBOARD_H
#include <cmath>
#include <algorithm>
namespace aps380_keyboard {
inline bool enabledFor(bool enabled, int type, int ordinaryKey, int specialKey) {
    return enabled && (type == ordinaryKey || type == specialKey);
}
inline double step(double previous, bool pressed, double dt, double rise, double fall) {
    if (!std::isfinite(previous)) previous = 0.;
    previous = (std::max)(0., (std::min)(1., previous));
    if (!std::isfinite(dt) || dt <= 0.) return previous;
    const double rate = pressed ? rise : fall;
    if (!std::isfinite(rate) || rate <= 0.) return 0.;
    return pressed ? (std::min)(1., previous + rate * dt) : (std::max)(0., previous - rate * dt);
}
}
#endif
