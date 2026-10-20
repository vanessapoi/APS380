/***************************************************************************

    file                 : exitmenu.cpp
    created              : Sat Mar 18 23:42:12 CET 2000
    copyright            : (C) 2000-2026 by Eric Espié, Bernhard Wymann
    email                : berniw@bluwin.ch

 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/


#include <stdio.h>
#include <tgfclient.h>
#include <musicplayer/musicplayer.h>
#include "exitmenu.h"
#include "mainmenu.h"

static void 
endofprog(void)
{
    STOP_ACTIVE_PROFILES();
    PRINT_PROFILE();
/*     glutSetKeyRepeat(GLUT_KEY_REPEAT_ON); */
    stopMenuMusic();
    GfScrShutdown();
    exit(0);
}

static void *exitmenuHandle = NULL;
static void *exitMainMenuHandle = NULL;


void * exitMenuInit(void *menu, void *menuHandle, void (*onQuit)(void))
{
    if (menuHandle) {
		GfuiScreenRelease(menuHandle);
    }
    
    menuHandle = GfuiMenuScreenCreate("Quit ?");
    GfuiScreenAddBgImg(menuHandle, "data/img/splash-quit.png");

    GfuiMenuButtonCreateAction(menuHandle,
		      "No, Back to Game",
		      "Return to TORCS",
		      [menu] { GfuiScreenActivate(menu); });
    
    GfuiMenuButtonCreateAction(menuHandle,
		      "Yes, Let's Quit",
		      "Exit of TORCS",
		      [onQuit] {
			      if (onQuit) {
				      onQuit();
			      }
			      endofprog();
		      });
    return menuHandle;
}

/*
 * Function
 *	TorcsExitMenuInit
 *
 * Description
 *	init the exit menus
 *
 * Parameters
 *	none
 *
 * Return
 *	0 ok -1 nok
 *
 * Remarks
 *	
 */
void * TorcsExitMenuInit(void *menu, void (*onQuit)(void))
{
	exitmenuHandle = exitMenuInit(menu, exitmenuHandle, onQuit);
	return exitmenuHandle;
}


void * TorcsMainExitMenuInit(void *mainMenu)
{
	exitMainMenuHandle = exitMenuInit(mainMenu, exitMainMenuHandle, NULL);
	return exitMainMenuHandle;
}
