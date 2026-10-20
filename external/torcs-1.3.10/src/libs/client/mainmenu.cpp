/***************************************************************************

    file                 : mainmenu.cpp
    created              : Sat Mar 18 23:42:38 CET 2000
    copyright            : (C) 2000-2026 by Eric Espié, Bernhard Wymann
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


#include <stdio.h>
#include <tgfclient.h>
#include <singleplayer.h>
#include <driverconfig.h>

#include "mainmenu.h"
#include "exitmenu.h"
#include "optionmenu.h"


void *menuHandle = NULL;
tModList *RacemanModLoaded = (tModList*)NULL;

static void
TorcsMainMenuActivate(void)
{
	if (RacemanModLoaded != NULL) {
		GfModUnloadList(&RacemanModLoaded);
	}
}

/*
 * Function
 *	TorcsMainMenuInit
 *
 * Description
 *	init the main menus
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
int
TorcsMainMenuInit(void)
{
    menuHandle = GfuiScreenCreateExAction((float*)NULL,
				    TorcsMainMenuActivate,
				    tGfuiAction(),
				    1);

    GfuiScreenAddBgImg(menuHandle, "data/img/splash-main.png");

    GfuiTitleCreate(menuHandle, "TORCS", 0);

    GfuiLabelCreate(menuHandle,
		    "The Open Racing Car Simulator",
		    GFUI_FONT_LARGE,
		    320,
		    420,
		    GFUI_ALIGN_HC_VB,
		    0);

	void *raceMenu = ReSinglePlayerInit(menuHandle);
    GfuiMenuButtonCreateAction(menuHandle,
			 "Race", "Races Menu",
			 [raceMenu] { GfuiScreenActivate(raceMenu); });

	void *driverMenu = TorcsDriverMenuInit(menuHandle);
    GfuiMenuButtonCreateAction(menuHandle,
			 "Configure Players", "Players configuration menu",
			 [driverMenu] { GfuiScreenActivate(driverMenu); });

	void *optionMenu = TorcsOptionOptionInit(menuHandle);
    GfuiMenuButtonCreateAction(menuHandle,
			 "Options", "Configure",
			 [optionMenu] { GfuiScreenActivate(optionMenu); });
    
    GfuiMenuDefaultKeysAdd(menuHandle);

    GfuiMenuBackQuitButtonCreateAction(menuHandle,
				 "Quit", "Quit TORCS",
				 [] { GfuiScreenActivate(TorcsMainExitMenuInit(menuHandle)); });

    return 0;
}

/*
 * Function
 *	
 *
 * Description
 *	
 *
 * Parameters
 *	
 *
 * Return
 *	
 *
 * Remarks
 *	
 */
int
TorcsMainMenuRun(void)
{
    GfuiScreenActivate(menuHandle);
    return 0;
}
