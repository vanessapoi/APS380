/***************************************************************************

    file                 : optionmenu.cpp
    created              : Mon Apr 24 14:22:53 CEST 2000
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
#include "optionmenu.h"
#include <graphconfig.h>
#include <simuconfig.h>
#include <soundconfig.h>
#include <openglconfig.h>

static void *optionHandle = NULL;

void *
TorcsOptionOptionInit(void *precMenu)
{
    if (optionHandle) return optionHandle;

    optionHandle = GfuiMenuScreenCreate("OPTIONS");

    GfuiScreenAddBgImg(optionHandle, "data/img/splash-options.png");

	void *graphicMenu = GraphMenuInit(optionHandle);
    GfuiMenuButtonCreateAction(optionHandle,
			 "Graphic", "Configure graphic parameters",
			 [graphicMenu] { GfuiScreenActivate(graphicMenu); });

	void *displayMenu = GfScrMenuInit(optionHandle);
    GfuiMenuButtonCreateAction(optionHandle,
			 "Display", "Configure display parameters",
			 [displayMenu] { GfuiScreenActivate(displayMenu); });

/*
    GfuiMenuButtonCreate(optionHandle,
			 "Simulation", "Configure simulation parameters",
			 SimuMenuInit(optionHandle), GfuiScreenActivate);
*/

	void *soundMenu = SoundMenuInit(optionHandle);
    GfuiMenuButtonCreateAction(optionHandle,
			 "Sound", "Configure sound parameters",
			 [soundMenu] { GfuiScreenActivate(soundMenu); });

	void *openGLMenu = OpenGLMenuInit(optionHandle);
    GfuiMenuButtonCreateAction(optionHandle,
			 "OpenGL", "Configure OpenGL parameters",
			 [openGLMenu] { GfuiScreenActivate(openGLMenu); });

    GfuiMenuBackQuitButtonCreateAction(optionHandle,
				 "Back",
				 "Back to Main",
				 [precMenu] { GfuiScreenActivate(precMenu); });

    return optionHandle;
}
