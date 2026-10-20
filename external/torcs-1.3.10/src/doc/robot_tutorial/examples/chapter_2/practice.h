/***************************************************************************

    file                 : practice.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/* This program is free software; you can redistribute it and/or modify it
 * under the GNU General Public License, version 2 or (at your option) any
 * later version. Distributed WITHOUT ANY WARRANTY, including MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See <https://www.gnu.org/licenses/>.
 */

#ifndef _TUTORIAL2_PRACTICE_H_
#define _TUTORIAL2_PRACTICE_H_

#include <car.h>
#include <raceman.h>

struct PracticeMistake {
	bool finished = false;
	void reset();
	bool drive(tCarElt* car, tSituation* situation);
};

#endif
