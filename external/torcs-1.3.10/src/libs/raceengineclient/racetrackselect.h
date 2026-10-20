/***************************************************************************

    file        : racetrackselect.h
    created     : Mon Jun  1 20:00:00 CET 2026
    copyright   : (C) 2026 by Bernhard Wymann
    email       : berniw@bluewin.ch

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
    Helpers for selecting a valid race-manager track.
*/

#ifndef _RACETRACKSELECT_H_
#define _RACETRACKSELECT_H_

#include <string>
#include <vector>



/** Track directory pair that can be selected by a race manager.
    The category and name are internal directory names, not localized display names.
*/
struct tReTrackCandidate {
	/** Build a track candidate from category and track directory names.
	    @param[in] trackCategory Track category directory name
	    @param[in] trackName Track directory and XML base name
	 */
	tReTrackCandidate(const char *trackCategory, const char *trackName);

	std::string category; /**< Track category directory name */
	std::string name;     /**< Track directory and XML base name */
};


/** Result of resolving a race-manager track selection. */
struct tReTrackSelection {
	/** Create an empty selection result. */
	tReTrackSelection();

	std::string category; /**< Selected track category directory name */
	std::string name;     /**< Selected track directory and XML base name */
	bool fallback;        /**< true if the configured track was replaced by a fallback */
};


/** Check whether a track XML file exists and can be parsed.
    @param[in] category Track category directory name
    @param[in] trackName Track directory and XML base name
    @param[in,out] trackFile Optional buffer receiving the generated track XML path
    @param[in] trackFileSize Size of @p trackFile in bytes
    @return true if the track XML exists and was read successfully
 */
extern bool ReTrackFileExists(const char *category, const char *trackName, char *trackFile, int trackFileSize);

/** Find all available tracks under the current TORCS track search path.
    @return Vector of selectable tracks whose XML files can be read
 */
extern std::vector<tReTrackCandidate> ReFindAvailableTracks(void);

/** Resolve the current race-manager track entry to an available track.
    The configured track is kept when it is present in @p availableTracks. If it is
    missing, the first available track in the same category is preferred, otherwise
    the first available track is used. When @p updateParams is true, a fallback
    selection is written back to the current race-manager track section.
    @param[in,out] params Race-manager parameter handle
    @param[in] curTrackIndex Current track section index under RM_SECT_TRACKS
    @param[in] availableTracks Ordered list of valid track candidates
    @param[in,out] selection Resolved track selection result
    @param[in] updateParams true to write fallback category/name to @p params
    @return true if a valid selection was found
 */
extern bool ReResolveTrackSelection(void *params, int curTrackIndex, const std::vector<tReTrackCandidate>& availableTracks, tReTrackSelection *selection, bool updateParams);


#endif /* _RACETRACKSELECT_H_ */
