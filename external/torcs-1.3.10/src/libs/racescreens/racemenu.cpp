/***************************************************************************

    file                 : racemenu.cpp
    created              : Thu May  2 22:02:51 CEST 2002
    copyright            : (C) 2001-2026 by Eric Espié, Bernhard Wymann
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
    Race options menu.
    @author Bernhard Wymann, Eric Espie
*/

#include <stdlib.h>
#include <stdio.h>
#ifdef WIN32
#include <windows.h>
#endif
#include <tgfclient.h>
#include <track.h>
#include <car.h>
#include <raceman.h>
#include <robot.h>
#include <racescreens.h>
#include <portability.h>

static void *scrHandle;
static tRmRaceParam *rp;
static int rmrpDistance;
static int rmrpLaps;
static int rmrpDistId;
static int rmrpLapsId;
static int rmDispModeEditId;
static int rmCurDispMode;
static const char *rmCurDispModeList[] = { RM_VAL_VISIBLE, RM_VAL_INVISIBLE };


static void rmrpDeactivate(void *screen)
{
	GfuiScreenRelease(scrHandle);

	if (screen) {
		GfuiScreenActivate(screen);
	}
}


static void rmrpUpdDist(void)
{
	char *val;
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];

	val = GfuiEditboxGetString(scrHandle, rmrpDistId);
	rmrpDistance = strtol(val, (char **)NULL, 0);
	if (rmrpDistance == 0) {
		strcpy(buf, "---");
	} else {
		snprintf(buf, BUFSIZE, "%d", rmrpDistance);
		rmrpLaps = 0;
		GfuiEditboxSetString(scrHandle, rmrpLapsId, "---");
	}
	GfuiEditboxSetString(scrHandle, rmrpDistId, buf);
}


static void rmrpUpdLaps(void)
{
	char *val;
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];

	val = GfuiEditboxGetString(scrHandle, rmrpLapsId);
	rmrpLaps = strtol(val, (char **)NULL, 0);
	if (rmrpLaps == 0) {
		strcpy(buf, "---");
	} else {
		snprintf(buf, BUFSIZE, "%d", rmrpLaps);
		rmrpDistance = 0;
		GfuiEditboxSetString(scrHandle, rmrpDistId, "---");
	}
	GfuiEditboxSetString(scrHandle, rmrpLapsId, buf);
}


static void rmrpValidate(void)
{
	if (rp->confMask & RM_CONF_RACE_LEN) {
		rmrpUpdDist();
		rmrpUpdLaps();
		GfParmSetNum(rp->param, rp->title, RM_ATTR_DISTANCE, "km", rmrpDistance);
		GfParmSetNum(rp->param, rp->title, RM_ATTR_LAPS, (char*)NULL, rmrpLaps);
	}

	if (rp->confMask & RM_CONF_DISP_MODE) {
		GfParmSetStr(rp->param, rp->title, RM_ATTR_DISPMODE, rmCurDispModeList[rmCurDispMode]);
	}

	rmrpDeactivate(rp->nextScreen);
}


static void rmrpAddKeys(void)
{
	GfuiAddKeyAction(scrHandle, 27, "Cancel Modifications", [] { rmrpDeactivate(rp->prevScreen); }, tGfuiAction());
	GfuiAddSKeyAction(scrHandle, GLUT_KEY_F1, "Help", [] { GfuiHelpScreen(scrHandle); }, tGfuiAction());
	GfuiAddSKeyAction(scrHandle, GLUT_KEY_F12, "Screen-Shot", [] { GfuiScreenShot(NULL); }, tGfuiAction());
	GfuiAddKeyAction(scrHandle, 13, "Validate Modifications", rmrpValidate, tGfuiAction());
}


void rmChangeDisplayMode(void)
{
	rmCurDispMode = 1 - rmCurDispMode;
	GfuiLabelSetText(scrHandle, rmDispModeEditId, rmCurDispModeList[rmCurDispMode]);
}


/** @brief Race options menu
 *  @ingroup racemantools
 *  @param[in,out] vrp Pointer on tRmRaceParam structure (cast to void)
 *  @note The race manager parameter set is modified in memory but not persisted.
 */
void RmRaceParamMenu(void *vrp)
{
	int y, x, x2, dy, dx;
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];

	rp = (tRmRaceParam*)vrp;
	
	snprintf(buf, BUFSIZE, "%s Options", rp->title);
	scrHandle = GfuiMenuScreenCreate(buf);
	GfuiScreenAddBgImg(scrHandle, "data/img/splash-raceopt.png");

	x = 80;
	x2 = 240;
	y = 380;
	dx = 200;
	dy = GfuiFontHeight(GFUI_FONT_LARGE) + 5;

	if (rp->confMask & RM_CONF_RACE_LEN) {
		GfuiLabelCreate(scrHandle, "Race Distance (km):", GFUI_FONT_MEDIUM_C, x, y, GFUI_ALIGN_HL_VB, 0);
		rmrpDistance = (int)GfParmGetNum(rp->param, rp->title, RM_ATTR_DISTANCE, "km", 0);
		if (rmrpDistance == 0) {
			strcpy(buf, "---");
			rmrpLaps = (int)GfParmGetNum(rp->param, rp->title, RM_ATTR_LAPS, NULL, 25);
		} else {
			snprintf(buf, BUFSIZE, "%d", rmrpDistance);
			rmrpLaps = 0;
		}
		
		rmrpDistId = GfuiEditboxCreateAction(scrHandle, buf, GFUI_FONT_MEDIUM_C,
						x + dx, y,
						0, 8, tGfuiAction(), rmrpUpdDist);

		y -= dy;
		GfuiLabelCreate(scrHandle, "Laps:", GFUI_FONT_MEDIUM_C, x, y, GFUI_ALIGN_HL_VB, 0);
		if (rmrpLaps == 0) {
			strcpy(buf, "---");
		} else {
			snprintf(buf, BUFSIZE, "%d", rmrpLaps);
		}
		
		rmrpLapsId = GfuiEditboxCreateAction(scrHandle, buf, GFUI_FONT_MEDIUM_C,
						x + dx, y,
						0, 8, tGfuiAction(), rmrpUpdLaps);
		y -= dy;
	}

	if (rp->confMask & RM_CONF_DISP_MODE) {
		GfuiLabelCreate(scrHandle, "Display:", GFUI_FONT_MEDIUM_C, x, y, GFUI_ALIGN_HL_VB, 0);
		GfuiGrButtonCreateAction(scrHandle, "data/img/arrow-left.png", "data/img/arrow-left.png",
				"data/img/arrow-left.png", "data/img/arrow-left-pushed.png",
				x2, y, GFUI_ALIGN_HL_VB, 1,
				rmChangeDisplayMode, tGfuiAction(), tGfuiAction());
		GfuiGrButtonCreateAction(scrHandle, "data/img/arrow-right.png", "data/img/arrow-right.png",
				"data/img/arrow-right.png", "data/img/arrow-right-pushed.png",
				x2 + 150, y, GFUI_ALIGN_HL_VB, 1,
				rmChangeDisplayMode, tGfuiAction(), tGfuiAction());
		if (!strcmp(GfParmGetStr(rp->param, rp->title, RM_ATTR_DISPMODE, RM_VAL_VISIBLE), RM_VAL_INVISIBLE)) {
			rmCurDispMode = 1;
		} else {
			rmCurDispMode = 0;
		}
		rmDispModeEditId = GfuiLabelCreate(scrHandle, rmCurDispModeList[rmCurDispMode], GFUI_FONT_MEDIUM_C, x2 + 35, y, GFUI_ALIGN_HL_VB, 20);
		y -= dy;
	}

	GfuiButtonCreateAction(scrHandle, "Accept", GFUI_FONT_LARGE, 210, 40, 150, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
				rmrpValidate, tGfuiAction(), tGfuiAction());

	GfuiButtonCreateAction(scrHandle, "Cancel", GFUI_FONT_LARGE, 430, 40, 150, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
				[] { rmrpDeactivate(rp->prevScreen); }, tGfuiAction(), tGfuiAction());

	rmrpAddKeys();

	GfuiScreenActivate(scrHandle);
}
