/***************************************************************************
    file                 : observer.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch
 ***************************************************************************/
/* GPL version 2 or later. Distributed WITHOUT ANY WARRANTY.
 * See <https://www.gnu.org/licenses/>. Private maintenance instrumentation. */
#ifndef _TUTORIAL_MAINTENANCE_OBSERVER_H_
#define _TUTORIAL_MAINTENANCE_OBSERVER_H_
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <map>
#include <robot.h>
#include <robottools.h>

struct MaintenanceStats {
	double speed = 0.0, throttle = 0.0, brake = 0.0, clearance = 1e9, fuel = 1e9;
	double occupiedUntil = 0.0;
	double initialFuel = -1.0;
	int ticks = 0, contacts = 0, penalties = 0, speeding = 0, invalid = 0, damage = 0;
	int sharedConflicts = 0;
};
static std::map<int, MaintenanceStats> MaintenanceStatsByIndex;
static tTrack* MaintenanceTrack = nullptr;

static void
maintenanceBefore(int index, tCarElt* car, tSituation* situation)
{
#ifdef MAINTENANCE_OCCUPIED
	auto& stats = MaintenanceStatsByIndex[index];
	if (car->_pit && (car->ctrl.raceCmd & RM_CMD_PIT_ASKED) && stats.occupiedUntil == 0.0) {
		stats.occupiedUntil = situation->currentTime + 20.0;
		car->_pit->pitCarIndex = 0;
		std::puts("MAINTENANCE occupied-box fixture activated");
	}
	if (stats.occupiedUntil > 0.0 && situation->currentTime > stats.occupiedUntil) {
		car->_pit->pitCarIndex = TR_PIT_STATE_FREE;
		stats.occupiedUntil = -1.0;
	}
#else
	(void)index; (void)car; (void)situation;
#endif
}

static void
maintenanceObserve(int index, tCarElt* car, tSituation* situation, int trafficMode = -1, int pitMode = -1)
{
	if (situation->currentTime <= 0.0) return;
	auto& stats = MaintenanceStatsByIndex[index];
	++stats.ticks;
	if (stats.initialFuel < 0.0 && car->_fuel > 0.0) stats.initialFuel = car->_fuel;
	stats.speed = std::max(stats.speed, double(car->_speed_x));
	stats.throttle = std::max(stats.throttle, double(car->ctrl.accelCmd));
	stats.brake = std::max(stats.brake, double(car->ctrl.brakeCmd));
	stats.damage = std::max(stats.damage, car->_dammage);
	const bool contact = (car->priv.collision & (SEM_COLLISION_CAR | SEM_COLLISION_XYSCENE)) != 0;
	if (contact && stats.contacts == 0) {
		std::fprintf(stderr, "MAINTENANCE FIRST_CONTACT time=%g index=%d traffic=%d pit=%d flags=%d\n",
			situation->currentTime, index, trafficMode, pitMode, car->priv.collision);
		for (int i = 0; i < situation->_ncars; ++i) {
			const auto* c = situation->cars[i];
			if (!c->_trkPos.seg) continue;
			const double along = c->_trkPos.seg->lgfromstart + (c->_trkPos.seg->type == TR_STR ?
				c->_trkPos.toStart : c->_trkPos.toStart * c->_trkPos.seg->radius);
			std::fprintf(stderr, "POSE %s along=%g lateral=%g world-v=(%g,%g) yaw=%g damage=%d steer=%g brake=%g\n",
				c->_name, along, c->_trkPos.toMiddle, c->_speed_X, c->_speed_Y, c->_yaw, c->_dammage,
				c->ctrl.steer, c->ctrl.brakeCmd);
		}
	}
	stats.contacts += contact;
	stats.penalties += GF_TAILQ_FIRST(&car->_penaltyList) != nullptr;
	if (car->_pit && (car->_state & RM_CAR_STATE_PIT)) {
		for (int i = 0; i < situation->_ncars; ++i) {
			const auto* other = situation->cars[i];
			if (other != car && other->_pit == car->_pit && (other->_state & RM_CAR_STATE_PIT)) ++stats.sharedConflicts;
		}
	}
	if (!std::isfinite(car->ctrl.accelCmd) || !std::isfinite(car->ctrl.brakeCmd) ||
		car->ctrl.accelCmd < 0 || car->ctrl.accelCmd > 1 || car->ctrl.brakeCmd < 0 || car->ctrl.brakeCmd > 1 ||
		(car->ctrl.accelCmd > 0 && car->ctrl.brakeCmd > 0)) ++stats.invalid;
	if (situation->currentTime > 1.0 && !(car->_state & RM_CAR_STATE_FINISH)) stats.fuel = std::min(stats.fuel, double(car->_fuel));
	for (int i = 0; i < 4; ++i) {
		tTrkLocPos position{};
		RtTrackGlobal2Local(car->_trkPos.seg, car->_corner_x(i), car->_corner_y(i), &position, TR_LPOS_MAIN);
		stats.clearance = std::min(stats.clearance, double(std::min(position.toLeft, position.toRight)));
	}
	tTrkLocPos actual{};
	RtTrackGlobal2Local(car->_trkPos.seg, car->_pos_X, car->_pos_Y, &actual, TR_LPOS_SEGMENT);
	if ((actual.seg->raceInfo & TR_SPEEDLIMIT) && MaintenanceTrack->pits.speedLimit > 0 &&
		std::fabs(car->_speed_x) > MaintenanceTrack->pits.speedLimit + 0.05) ++stats.speeding;
}

static void
maintenanceReport(int index)
{
	const auto& s = MaintenanceStatsByIndex[index];
	std::printf("MAINTENANCE %s %d %.9g %.9g %.9g %.9g %.9g %.9g %d %d %d %d %d %d %d\n",
		MAINTENANCE_ID, index, s.speed, s.throttle, s.brake, s.clearance, s.fuel, s.initialFuel,
		s.ticks, s.contacts, s.penalties, s.speeding, s.invalid, s.damage, s.sharedConflicts);
}
#endif
