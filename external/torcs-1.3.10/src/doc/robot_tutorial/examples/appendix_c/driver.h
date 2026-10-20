/***************************************************************************

    file                 : driver.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#ifndef _TUTORIALC_DRIVER_H_
#define _TUTORIALC_DRIVER_H_

#include <robot.h>
#include "settings.h"
#include "recovery.h"
#include "pit.h"

class TutorialDriver {
public:
	explicit TutorialDriver(int robotIndex);
	void initTrack(tTrack* track, void* carSettings, void** settings);
	void newRace(tCarElt* car, tSituation* situation);
	void drive(tCarElt* car, tSituation* situation);
	int pitCommand(tCarElt* car);

private:
	const int index;
	tTrack* currentTrack = nullptr; // Borrowed; the engine owns track and car.
	tCarElt* activeCar = nullptr;
	DriverSettings configuration;
	SpeedDriver speed;
	Recovery recovery;
	TrafficPlanner traffic;
	PitDriver pits;
};

#endif
