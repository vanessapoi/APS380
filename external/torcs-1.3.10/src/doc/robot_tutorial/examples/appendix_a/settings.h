/***************************************************************************

    file                 : settings.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#ifndef _TUTORIALA_SETTINGS_H_
#define _TUTORIALA_SETTINGS_H_

#include <track.h>
struct SpeedDriver;
struct PitDriver;

struct DriverSettings {
	double lookaheadBase = 8.0;
	double lookaheadTime = 0.33;
	bool demonstrationStop = false;
	double stintLaps = 0.0; // zero means fuel to finish
	double fallbackFuelPerLap = 1.5;
	void apply(SpeedDriver& driver, PitDriver& pits) const;
};

// Borrow carSettings; return a new override handle for the engine to consume.
void* loadSettings(tTrack* track, void* carSettings, DriverSettings& settings);

#endif
