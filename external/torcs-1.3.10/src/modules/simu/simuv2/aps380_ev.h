/* SPDX-License-Identifier: GPL-2.0-or-later
 * APS380 reduced-order electric motor/battery model. Not Tesla firmware. */
#ifndef APS380_EV_H
#define APS380_EV_H
#include <algorithm>
#include <cmath>

namespace aps380 {
struct EvParameters {
    double maxTorque, maxPower, maxRegenPower, regenTorque;
    double driveEfficiency, regenEfficiency, auxiliaryPower;
    double capacityWh, voltage, maxSpeed, neutralPedal;
};
struct EvStep { double torque, shaftPower, packPower, energyWh; };
inline EvStep electricStep(const EvParameters &p, double energyWh,
                          double omega, double speed, double throttle,
                          double dt, bool engaged, double brake = 0.0)
{
    const double w = std::fabs(omega);
    double torque = 0.0;
    const double available = (std::min)(p.maxTorque, p.maxPower / (std::max)(w, 1.0));
    if (engaged && energyWh > 0.0 && throttle > p.neutralPedal && brake <= 0.05 && speed < p.maxSpeed) {
        torque = available * (throttle-p.neutralPedal)/(1.0-p.neutralPedal);
        // Prevent the last time step from drawing energy below zero.
        if (w > 0.0 && dt > 0.0)
            torque = (std::min)(torque, (std::max)(0.0, energyWh*3600.0/dt-p.auxiliaryPower)*p.driveEfficiency/w);
    } else if (engaged && throttle <= p.neutralPedal && speed > 0.0 && energyWh < p.capacityWh) {
        // Accelerator-release regeneration; pedal braking remains friction.
        const double fade = (std::min)(speed / 2.0, 1.0);
        double regen = (std::min)(p.regenTorque, p.maxRegenPower/(std::max)(w, 1.0))*fade
            *(1.0-throttle/p.neutralPedal);
        if (w > 0.0 && dt > 0.0)
            regen = (std::min)(regen, ((p.capacityWh-energyWh)*3600.0/dt+p.auxiliaryPower)/(p.regenEfficiency*w));
        torque = omega < 0.0 ? regen : -regen;
    }
    // Account for signed shaft work, including a vehicle rolling backwards.
    double shaft = torque*omega;
    if (shaft < 0.0 && w > 0.0) {
        double recovered = (std::min)(-shaft, p.maxRegenPower);
        if (dt > 0.0)
            recovered = (std::min)(recovered, ((p.capacityWh-energyWh)*3600.0/dt+p.auxiliaryPower)/p.regenEfficiency);
        shaft = -recovered;
        torque = shaft/omega;
    }
    double pack = (shaft >= 0.0 ? shaft/p.driveEfficiency : shaft*p.regenEfficiency) + p.auxiliaryPower;
    if (dt > 0.0)
        pack = (std::min)(pack, energyWh*3600.0/dt);
    const double next = (std::max)(0.0, (std::min)(p.capacityWh, energyWh-pack*dt/3600.0));
    return {torque, shaft, pack, next};
}
}
#endif
