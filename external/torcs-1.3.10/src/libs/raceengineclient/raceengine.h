/***************************************************************************

    file        : raceengine.h
    created     : Sat Nov 23 09:35:21 CET 2002
    copyright   : (C) 2002-2026 by Eric Espié, Bernhard Wymann
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
*/

#ifndef _RACEENGINE_H_
#define _RACEENGINE_H_



extern void ReStart(void);
extern void ReStop(void);
extern int  ReUpdate(void);
extern void ReTimeMod (int cmd);

extern tRmInfo	*ReInfo;

#endif /* _RACEENGINE_H_ */ 



