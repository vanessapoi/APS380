/***************************************************************************

    file        : simuconfig.cpp
    created     : Wed Nov  3 21:48:26 CET 2004
    copyright   : (C) 2004 by Eric Espié, Bernhard Wymann                     
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

#include <stdio.h>
#include <stdlib.h>
#include <tgfclient.h>
#include <raceinit.h>

#include "simuconfig.h"
#include <portability.h>

static float LabelColor[] = {1.0, 0.0, 1.0, 1.0};

/* list of available simulation engine */
static const char *simuVersionList[] = {"simuv2", "simuv3"};
static const int nbVersions = sizeof(simuVersionList) / sizeof(simuVersionList[0]);
static int curVersion = 0;

/* gui label id */
static int SimuVersionId;

/* gui screen handles */
static void	*scrHandle = NULL;
static void	*prevHandle = NULL;


static void ReadSimuCfg(void)
{
	const char *versionName;
	int i;

	const int BUFSIZE = 1024;
	char buf[BUFSIZE];
	snprintf(buf, BUFSIZE, "%s%s", GetLocalDir(), RACE_ENG_CFG);

	void *paramHandle = GfParmReadFile(buf, GFPARM_RMODE_REREAD | GFPARM_RMODE_CREAT);
	versionName = GfParmGetStr(paramHandle, "Modules", "simu", simuVersionList[0]);

	for (i = 0; i < nbVersions; i++) {
		if (strcmp(versionName, simuVersionList[i]) == 0) {
			curVersion = i;
			break;
		}
	}

	GfParmReleaseHandle(paramHandle);

	GfuiLabelSetText(scrHandle, SimuVersionId, simuVersionList[curVersion]);
}


/* Save the choosen values in the corresponding parameter file */
static void SaveSimuVersion(void)
{
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];
	snprintf(buf, BUFSIZE, "%s%s", GetLocalDir(), RACE_ENG_CFG);

	void *paramHandle = GfParmReadFile(buf, GFPARM_RMODE_REREAD | GFPARM_RMODE_CREAT);
	GfParmSetStr(paramHandle, "Modules", "simu", simuVersionList[curVersion]);
	GfParmWriteFile(NULL, paramHandle, "raceengine");
	GfParmReleaseHandle(paramHandle);
	
	/* return to previous screen */
	GfuiScreenActivate(prevHandle);
	return;
}

/* change the simulation version */
static void
ChangeSimuVersion(int delta)
{
	if (delta < 0) {
	curVersion--;
	if (curVersion < 0) {
	    curVersion = nbVersions - 1;
	}
	} else {
	curVersion++;
	if (curVersion == nbVersions) {
	    curVersion = 0;
	}
	}
	GfuiLabelSetText(scrHandle, SimuVersionId, simuVersionList[curVersion]);
}


static void onActivate(void)
{
        ReadSimuCfg();
}


/* Menu creation */
void *
SimuMenuInit(void *prevMenu)
{
    int		x, y, x2, x3, x4, dy;

    /* screen already created */
    if (scrHandle) {
	return scrHandle;
    }
    prevHandle = prevMenu;

    scrHandle = GfuiScreenCreateExAction((float*)NULL, onActivate, tGfuiAction(), 1);
    GfuiTitleCreate(scrHandle, "Simulation Configuration", 0);
    GfuiScreenAddBgImg(scrHandle, "data/img/splash-simucfg.png");

    x = 20;
    x2 = 240;
    x3 = x2 + 100;
    x4 = x2 + 200;
    y = 370;
    dy = 30;

    y -= dy;
    GfuiLabelCreate(scrHandle, "Simulation version:", GFUI_FONT_MEDIUM, x, y, GFUI_ALIGN_HL_VB, 0);
    GfuiGrButtonCreateAction(scrHandle, "data/img/arrow-left.png", "data/img/arrow-left.png",
		       "data/img/arrow-left.png", "data/img/arrow-left-pushed.png",
		       x2, y, GFUI_ALIGN_HL_VB, 1,
		       [] { ChangeSimuVersion(-1); }, tGfuiAction(), tGfuiAction());
    GfuiGrButtonCreateAction(scrHandle, "data/img/arrow-right.png", "data/img/arrow-right.png",
		       "data/img/arrow-right.png", "data/img/arrow-right-pushed.png",
		       x4, y, GFUI_ALIGN_HR_VB, 1,
		       [] { ChangeSimuVersion(1); }, tGfuiAction(), tGfuiAction());
    SimuVersionId = GfuiLabelCreate(scrHandle, "", GFUI_FONT_MEDIUM_C, x3, y, GFUI_ALIGN_HC_VB, 32);
    GfuiLabelSetColor(scrHandle, SimuVersionId, LabelColor);

    GfuiButtonCreateAction(scrHandle, "Accept", GFUI_FONT_LARGE, 210, 40, 150, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
     SaveSimuVersion, tGfuiAction(), tGfuiAction());

    GfuiButtonCreateAction(scrHandle, "Cancel", GFUI_FONT_LARGE, 430, 40, 150, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
     [prevMenu] { GfuiScreenActivate(prevMenu); }, tGfuiAction(), tGfuiAction());

    GfuiAddKeyAction(scrHandle, 13, "Save", SaveSimuVersion, tGfuiAction());
    GfuiAddKeyAction(scrHandle, 27, "Cancel Selection", [prevMenu] { GfuiScreenActivate(prevMenu); }, tGfuiAction());
    GfuiAddSKeyAction(scrHandle, GLUT_KEY_F12, "Screen-Shot", [] { GfuiScreenShot(NULL); }, tGfuiAction());
    GfuiAddSKeyAction(scrHandle, GLUT_KEY_LEFT, "Previous Version in list", [] { ChangeSimuVersion(-1); }, tGfuiAction());
    GfuiAddSKeyAction(scrHandle, GLUT_KEY_RIGHT, "Next Version in list", [] { ChangeSimuVersion(1); }, tGfuiAction());

    ReadSimuCfg();
  
    return scrHandle;  
}
