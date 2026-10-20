/***************************************************************************

    file                 : terrain.h
    created              : Sat Aug  1 2026
    copyright            : (C) 2002-2026 by Eric Espié, Bernhard Wymann
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
    @brief TORCS terrain generation integration.
 */

#ifndef _TERRAIN_H_
#define _TERRAIN_H_

#include <limits.h>
#include <stdio.h>

#include <track.h>

/** Marker used for relief constraints and the rectangular terrain border. */
#define RELIEF_BOUNDARY_MARK INT_MAX

/** Marker that preserves generated crossing seam positions and elevations. */
#define CROSSING_TERRAIN_BOUNDARY_MARK (INT_MAX - 1)

struct TrackCrossingModel;

extern void GenerateTerrain(tTrack *track, void *TrackHandle, char *outfile,
                            FILE *AllFd, int noElevation,
                            const TrackCrossingModel *crossingModel);

#endif /* _TERRAIN_H_ */
