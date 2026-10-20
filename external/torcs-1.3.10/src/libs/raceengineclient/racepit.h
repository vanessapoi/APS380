/***************************************************************************

    file                 : racepit.h
    created              : Sun Jul 12 20:00:00 CET 2026
    copyright            : (C) 2026 by Bernhard Wymann
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

/** @file
    Pit stop command normalization and timing helpers.
    @author Bernhard Wymann
*/

#ifndef _RACEPIT_H_
#define _RACEPIT_H_

#include <car.h>
#include <raceman.h>


extern void ReNormalizePitStop(tCarElt *car);
extern tdble ReComputePitStopServiceTime(const tCarElt *car, const tRmRaceRules *raceRules);

#endif /* _RACEPIT_H_ */
