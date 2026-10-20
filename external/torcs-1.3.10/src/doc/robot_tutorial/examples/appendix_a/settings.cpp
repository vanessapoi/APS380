/***************************************************************************

    file                 : settings.cpp
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
#include <cstring>
#include <string>
#include <tgf.h>
#include <car.h>
#include "settings.h"
#include "pit.h"

static const char* PRIVATE_SECTION = "Tutorial A";

static double
readNumber(void* handle, const char* section, const char* key, const char* unit,
	double previous, double minimum, double maximum)
{
	const double value = GfParmGetNum(handle, section, key, unit, static_cast<tdble>(previous));
	// Compare to representable tdble endpoints (e.g. 0.6 is not exact in float).
	if (!std::isfinite(value) || value < static_cast<tdble>(minimum) || value > static_cast<tdble>(maximum)) {
		GfError("Tutorial A: ignoring %s/%s outside [%g, %g]; keeping %g\n",
			section, key, minimum, maximum, previous);
		return previous;
	}
	return value;
}

static void
readCarNumber(void* input, void* reference, void* output, const char* section, const char* key)
{
	tdble minimum = 0.0f, maximum = 0.0f;
	if (GfParmGetNumBoundaries(reference, section, key, &minimum, &maximum) != 0) {
		return;
	}
	// Both the boundaries and unit=nullptr values use the API's internal units.
	const double baseline = GfParmGetNum(reference, section, key, nullptr, minimum);
	const double previous = GfParmGetNum(output, section, key, nullptr, static_cast<tdble>(baseline));
	const double value = readNumber(input, section, key, nullptr, previous, minimum, maximum);
	GfParmSetNum(output, section, key, nullptr, static_cast<tdble>(value));
}

static void
readLayer(const std::string& path, void* carSettings, void* overrides, DriverSettings& settings)
{
	// PRIVATE gives us an independent, fresh read on every initTrack call.
	void* input = GfParmReadFile(path.c_str(), GFPARM_RMODE_STD | GFPARM_RMODE_PRIVATE);
	if (!input) {
		GfOut("Tutorial A: no readable layer %s; retaining previous values\n", path.c_str());
		return;
	}
	GfOut("Tutorial A: loading %s\n", path.c_str());
	settings.lookaheadBase = readNumber(input, PRIVATE_SECTION, "lookahead base", "m", settings.lookaheadBase, 4.0, 12.0);
	settings.lookaheadTime = readNumber(input, PRIVATE_SECTION, "lookahead time", "s", settings.lookaheadTime, 0.1, 0.6);
	const double stint = readNumber(input, "Tutorial A/Strategy", "stint laps", nullptr, settings.stintLaps, 0.0, 10.0);
	if (stint == 0.0 || stint >= 2.0) {
		settings.stintLaps = stint;
	} else {
		GfError("Tutorial A: stint laps must be zero (fuel to finish) or 2-10; retaining previous value\n");
	}
	settings.fallbackFuelPerLap = readNumber(input, "Tutorial A/Strategy", "fuel per lap", "l", settings.fallbackFuelPerLap, 0.1, 10.0);
	const char* demo = GfParmGetStr(input, "Tutorial A/Strategy", "demonstration stop", nullptr);
	if (demo) {
		if (std::strcmp(demo, "yes") == 0 || std::strcmp(demo, "no") == 0) {
			settings.demonstrationStop = std::strcmp(demo, "yes") == 0;
		} else {
			GfError("Tutorial A: demonstration stop must be yes or no; retaining previous value\n");
		}
	}
	// Explicit whitelist: private sections never become physical car overrides.
	readCarNumber(input, carSettings, overrides, SECT_CAR, PRM_FUEL);
	readCarNumber(input, carSettings, overrides, SECT_REARWING, PRM_WINGANGLE);
	GfParmReleaseHandle(input);
}

void*
loadSettings(tTrack* track, void* carSettings, DriverSettings& settings)
{
	settings = DriverSettings{};
	void* overrides = GfParmReadFile("", GFPARM_RMODE_CREAT | GFPARM_RMODE_PRIVATE);
	if (!overrides) {
		GfError("Tutorial A: cannot allocate car overrides; using standard car and driver settings\n");
		return nullptr;
	}
	const std::string directory = "drivers/tutoriala/";
	readLayer(directory + "default.xml", carSettings, overrides, settings);
	if (track->internalname && track->internalname[0]) {
		readLayer(directory + track->internalname + ".xml", carSettings, overrides, settings);
	}
	// Preserve Chapter 6's full-tank fallback on tracks without supported side pits.
	if (track->pits.type != TR_PIT_ON_TRACK_SIDE || track->pits.nMaxPits <= 0) {
		const tdble tank = GfParmGetNum(carSettings, SECT_CAR, PRM_TANK, "l", 60.0f);
		const tdble baseline = GfParmGetNum(carSettings, SECT_CAR, PRM_FUEL, "l", tank);
		tdble minimum = 0.0f, maximum = 0.0f;
		const bool allowed = GfParmGetNumBoundaries(carSettings, SECT_CAR, PRM_FUEL, &minimum, &maximum) == 0;
		const tdble fuel = allowed ? static_cast<tdble>(std::max(double(minimum), std::min(double(maximum), double(tank)))) : baseline;
		GfParmSetNum(overrides, SECT_CAR, PRM_FUEL, "l", fuel);
		GfOut("Tutorial A: no supported side pits; starting fuel reset to %.3f l\n", double(fuel));
	}
	if (GfParmCheckHandle(carSettings, overrides)) {
		GfError("Tutorial A: invalid physical overrides; retaining standard car setup\n");
		GfParmReleaseHandle(overrides);
		overrides = nullptr;
	}
	GfOut("Tutorial A settings: lookahead=%g m + %g s * speed, demo=%s, stint=%g laps, fallback=%g l/lap\n",
		settings.lookaheadBase, settings.lookaheadTime, settings.demonstrationStop ? "yes" : "no",
		settings.stintLaps, settings.fallbackFuelPerLap);
	return overrides;
}

void
DriverSettings::apply(SpeedDriver& driver, PitDriver& pits) const
{
	driver.lookaheadBase = lookaheadBase;
	driver.lookaheadTime = lookaheadTime;
	// Apply AFTER configure(), which resets the pit state for each new race.
	pits.demonstrationStop = demonstrationStop;
	pits.stintLaps = stintLaps;
	pits.fallbackFuelPerLap = fallbackFuelPerLap;
}
