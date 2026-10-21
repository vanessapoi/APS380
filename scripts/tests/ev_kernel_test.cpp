#include "../../external/torcs-1.3.10/src/modules/simu/simuv2/aps380_ev.h"
#include <cassert>
#include <iostream>

int main()
{
    const aps380::EvParameters p = {404, 202000, 60000, 100, .92, .85, 300, 50000, 355, 62.5};
    const auto launch = aps380::electricStep(p, 40000, 0, 0, 1, .002, true);
    assert(launch.torque == 404);
    const auto fast = aps380::electricStep(p, 40000, 1000, 35, 1, .002, true);
    assert(fast.shaftPower <= 202000.00001);
    assert(std::fabs(fast.packPower-(202000/.92+300)) < .001);
    assert(std::fabs((40000-fast.energyWh)*3600/.002-fast.packPower) < .001);
    const auto regen = aps380::electricStep(p, 40000, 1000, 35, 0, .002, true);
    assert(regen.shaftPower == -60000);
    assert(regen.packPower == -50700);
    assert(regen.energyWh > 40000);
    const auto full = aps380::electricStep(p, 50000, 1000, 35, 0, .002, true);
    assert(full.torque == 0 && full.energyWh <= 50000);
    const auto nearFull = aps380::electricStep(p, 49999.999, 1000, 35, 0, 1, true);
    assert(nearFull.energyWh <= 50000 && nearFull.energyWh >= 49999.999);
    const auto empty = aps380::electricStep(p, 0, 1000, 35, 1, .002, true);
    assert(empty.torque == 0 && empty.packPower == 0 && empty.energyWh == 0);
    const auto nearlyEmpty = aps380::electricStep(p, .001, 1000, 35, 1, 1, true);
    assert(nearlyEmpty.energyWh >= 0 && nearlyEmpty.packPower <= 3.60001);
    const auto stopped = aps380::electricStep(p, 40000, 0, 0, 0, .002, true);
    assert(stopped.torque == 0 && stopped.packPower == 300);
    const auto neutral = aps380::electricStep(p, 40000, 1000, 35, 1, .002, false);
    assert(neutral.torque == 0);
    const auto braking = aps380::electricStep(p, 40000, 1000, 35, 1, .002, true, 1);
    assert(braking.torque == 0);
    const auto limited = aps380::electricStep(p, 40000, 1000, 63, 1, .002, true);
    assert(limited.torque == 0);
    const auto fade = aps380::electricStep(p, 40000, 10, 1, 0, .002, true);
    assert(fade.torque == -50);
    const auto backward = aps380::electricStep(p, 40000, -1000, 35, 0, .002, true);
    assert(backward.torque > 0 && backward.shaftPower < 0);
    assert(backward.energyWh > 40000);
    std::cout << "14 EV kernel checks passed\n";
}
