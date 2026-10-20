/***************************************************************************

    file                 : racepenalties.h
    created              : Mon Jun  8 20:00:00 CET 2026
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
    Race penalty application and penalty-aware race result ordering.
    @author Bernhard Wymann
*/

#ifndef _RACEPENALTIES_H_
#define _RACEPENALTIES_H_

#include <raceman.h>


/**
 * @brief Apply race time penalties and update same-lap result order.
 *
 * Existing time penalties are kept, pending drive-through and stop-and-go
 * penalties are converted into estimated time penalties when the race has
 * usable on-track-side pit information, and then penalized cars are moved down
 * only within their current completed-lap group.
 *
 * @param[in,out] s Current race situation containing the ordered car list.
 * @param[in] pits Pit lane information used to estimate pending penalty time.
 */
extern void ReApplyRaceTimePenalties(tSituation *s, const tTrackPitInfo *pits);

#endif /* _RACEPENALTIES_H_ */
