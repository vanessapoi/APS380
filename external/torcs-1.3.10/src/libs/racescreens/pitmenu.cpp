/***************************************************************************

    file                 : pitmenu.cpp
    created              : Mon Apr 24 18:16:37 CEST 2000
    copyright            : (C) 2013-2026 by Eric Espié, Bernhard Wymann
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
    Pit menu
    @author Bernhard Wymann, Eric Espie
*/

#include <stdlib.h>
#ifdef WIN32
#include <windows.h>
#endif
#include <tgfclient.h>
#include <car.h>
#include <portability.h>
#include <racescreens.h>

static void *menuHandle = NULL;
static int fuelId;
static int repairId;
static tCarElt *rmCar;
static tRmInfo *rmInfo;
static int tireChangeId;
static int serviceButtonId = -1;
static int stopAndGoButtonId = -1;
static int setupButtonId = -1;
static int serviceTipLabelId = -1;
static int stopAndGoTipLabelId = -1;
static int stopAndGoDisabledTipLabelId = -1;
static int setupTipLabelId = -1;
static int setupDisabledTipLabelId = -1;
static bool stopAndGoAvailable = false;
static bool setupAvailable = false;

static float LabelColor[] = {1.0, 0.0, 1.0, 1.0};
static float DisabledTipColor[] = {1.0, 0.0, 0.0, 1.0};
static const char *ServiceTipMessage = "Perform selected pit service";
static const char *StopAndGoTipMessage = "Serve current Stop & Go penalty";
static const char *NoStopAndGoMessage = "No current Stop & Go penalty to serve";
static const char *SetupTipMessage = "Change car setup";
static const char *SetupDisabledMessage = "Only available in practice and qualifying sessions";

// list of tire change options.
static const char *tireChangeLabel[] = {
	"All",
	"None"
};
static const tCarPitCmd::TireChange tireChangeList[] = {
	tCarPitCmd::ALL,
	tCarPitCmd::NONE
};
static const int nbtireChangeOptions = sizeof(tireChangeLabel) / sizeof(tireChangeLabel[0]);
static int currentTireChangeOption = 0;


static void rmClampPitFuel(void)
{
	if (!rmCar) {
		return;
	}

	tdble maxFuel = rmCar->_tank - rmCar->_fuel;
	if (maxFuel < 0.0f) {
		maxFuel = 0.0f;
	}
	if (rmCar->_pitFuel < 0.0f) {
		rmCar->_pitFuel = 0.0f;
	} else if (rmCar->_pitFuel > maxFuel) {
		rmCar->_pitFuel = maxFuel;
	}
}


static void rmClampPitRepair(void)
{
	if (!rmCar) {
		return;
	}

	int maxRepair = rmCar->_dammage;
	if (maxRepair < 0) {
		maxRepair = 0;
	}
	if (rmCar->_pitRepair < 0) {
		rmCar->_pitRepair = 0;
	} else if (rmCar->_pitRepair > maxRepair) {
		rmCar->_pitRepair = maxRepair;
	}
}


static void rmClampPitCmd(void)
{
	rmClampPitFuel();
	rmClampPitRepair();
}


static void rmSetFuelText(void)
{
	const int BUFSIZE = 32;
	char buf[BUFSIZE];

	snprintf(buf, BUFSIZE, "%.1f", rmCar->_pitFuel);
	GfuiEditboxSetString(menuHandle, fuelId, buf);
}


static void rmSetRepairText(void)
{
	const int BUFSIZE = 32;
	char buf[BUFSIZE];

	snprintf(buf, BUFSIZE, "%d", rmCar->_pitRepair);
	GfuiEditboxSetString(menuHandle, repairId, buf);
}

static void rmUpdtFuel(void)
{
	char *val;

	val = GfuiEditboxGetString(menuHandle, fuelId);
	rmCar->pitcmd.fuel = (tdble)strtod(val, (char **)NULL);
	rmClampPitFuel();
	rmSetFuelText();
}


static void rmUpdtRepair(void)
{
	char *val;

	val = GfuiEditboxGetString(menuHandle, repairId);
	rmCar->pitcmd.repair = strtol(val, (char **)NULL, 0);
	rmClampPitRepair();
	rmSetRepairText();
}


static void rmHideButtonTips(void)
{
	if (serviceTipLabelId >= 0) {
		GfuiVisibilitySet(menuHandle, serviceTipLabelId, GFUI_INVISIBLE);
	}
	if (stopAndGoTipLabelId >= 0) {
		GfuiVisibilitySet(menuHandle, stopAndGoTipLabelId, GFUI_INVISIBLE);
	}
	if (stopAndGoDisabledTipLabelId >= 0) {
		GfuiVisibilitySet(menuHandle, stopAndGoDisabledTipLabelId, GFUI_INVISIBLE);
	}
	if (setupTipLabelId >= 0) {
		GfuiVisibilitySet(menuHandle, setupTipLabelId, GFUI_INVISIBLE);
	}
	if (setupDisabledTipLabelId >= 0) {
		GfuiVisibilitySet(menuHandle, setupDisabledTipLabelId, GFUI_INVISIBLE);
	}
}


static void rmShowButtonTip(int buttonId, int tipLabelId, int disabledTipLabelId, bool available)
{
	rmHideButtonTips();
	if (!GfuiScreenIsActive(menuHandle) || GfuiButtonGetFocused() != buttonId) {
		return;
	}

	int labelId = available ? tipLabelId : disabledTipLabelId;
	if (labelId >= 0) {
		GfuiVisibilitySet(menuHandle, labelId, GFUI_VISIBLE);
	}
}


static void rmServiceFocus(void)
{
	rmShowButtonTip(serviceButtonId, serviceTipLabelId, -1, true);
}


static void rmStopAndGoFocus(void)
{
	rmShowButtonTip(stopAndGoButtonId, stopAndGoTipLabelId, stopAndGoDisabledTipLabelId, stopAndGoAvailable);
}


static void rmSetupFocus(void)
{
	rmShowButtonTip(setupButtonId, setupTipLabelId, setupDisabledTipLabelId, setupAvailable);
}


static tGfuiAction rmCallback;


static void rmStopAndGo(void)
{
	rmCar->_pitStopType = RM_PIT_STOPANDGO;
	if (rmCallback) {
		rmCallback();
	}
}


static void rmService(void)
{
	rmClampPitCmd();
	rmCar->_pitStopType = RM_PIT_REPAIR;
	if (rmCallback) {
		rmCallback();
	}
}

// Manage tire change state.
static void changeTireState(int i)
{
	if (i > 0) {
		currentTireChangeOption++;
		if (currentTireChangeOption >= nbtireChangeOptions) {
			currentTireChangeOption = 0;
		}
	} else {
		currentTireChangeOption--;
		if (currentTireChangeOption < 0) {
			currentTireChangeOption = nbtireChangeOptions - 1;
		}
	}

	rmCar->pitcmd.tireChange = tireChangeList[currentTireChangeOption];
	GfuiLabelSetText(menuHandle, tireChangeId, tireChangeLabel[currentTireChangeOption]);
}



/** @brief Pit menu
 *  @ingroup racemantools
 *  @param[in,out] car Car data is returned in tCarElt.pitcmd
 *  @param[in] reInfo Required for passing data to car setup screen, RmCarSetupScreenInit
 *  @param[in] callback Callback to take action on the changes made
 */ 
void RmPitMenuStartAction(tCarElt *car, tRmInfo *reInfo, const tGfuiAction &callback)
{
	const int BUFSIZE = 256;
	char buf[BUFSIZE];
	int	y, x, dy;

	rmCar = car;
	rmInfo = reInfo;
	rmClampPitCmd();

	if (menuHandle) {
		GfuiScreenRelease(menuHandle);
	}
	serviceButtonId = -1;
	stopAndGoButtonId = -1;
	setupButtonId = -1;
	serviceTipLabelId = -1;
	stopAndGoTipLabelId = -1;
	stopAndGoDisabledTipLabelId = -1;
	setupTipLabelId = -1;
	setupDisabledTipLabelId = -1;
	menuHandle = GfuiMenuScreenCreate("Pit Stop Info");

	x = 80;
	y = 380;
	snprintf(buf, BUFSIZE, "Driver: %s", car->_name);
	GfuiLabelCreate(menuHandle, buf, GFUI_FONT_LARGE_C, x, y, GFUI_ALIGN_HL_VB, 0);
	dy = GfuiFontHeight(GFUI_FONT_LARGE_C) + 5;

	y -= dy;
	snprintf(buf, BUFSIZE, "Remaining Laps: %d", car->_remainingLaps);
	GfuiLabelCreate(menuHandle, buf, GFUI_FONT_MEDIUM_C, x, y, GFUI_ALIGN_HL_VB, 0);

	y -= dy;
	snprintf(buf, BUFSIZE, "Remaining Fuel: %.1f l", car->_fuel);
	GfuiLabelCreate(menuHandle, buf, GFUI_FONT_MEDIUM_C, x, y, GFUI_ALIGN_HL_VB, 0);

	y -= dy;
	GfuiLabelCreate(menuHandle, "Fuel amount (liters):", GFUI_FONT_MEDIUM_C, x, y, GFUI_ALIGN_HL_VB, 0);

	int dx = GfuiFontWidth(GFUI_FONT_MEDIUM_C, "Fuel amount (liters)") + 20;
	snprintf(buf, BUFSIZE, "%.1f", car->pitcmd.fuel);
	fuelId = GfuiEditboxCreateAction(menuHandle, buf, GFUI_FONT_MEDIUM_C,
					x + dx, y,
					100, 10, tGfuiAction(), rmUpdtFuel);

	y -= dy;
	GfuiLabelCreate(menuHandle, "Repair amount:", GFUI_FONT_MEDIUM_C, x, y, GFUI_ALIGN_HL_VB, 0);

	snprintf(buf, BUFSIZE, "%d", (int)car->pitcmd.repair);
	repairId = GfuiEditboxCreateAction(menuHandle, buf, GFUI_FONT_MEDIUM_C,
					x + dx, y,
					100, 10, tGfuiAction(), rmUpdtRepair);

	y -= dy;

	int x2 = x + dx - 15;
	int x3 = x + dx + 100 + 14;
	int x4 = (x2+x3)/2;

	GfuiLabelCreate(menuHandle, "Tire change:", GFUI_FONT_MEDIUM_C, x, y, GFUI_ALIGN_HL_VB, 0);

	if (!(reInfo->raceRules.tireFactor > 0.0f) || car->info.skillLevel != 3) {
		currentTireChangeOption = tCarPitCmd::NONE;
		rmCar->pitcmd.tireChange = tCarPitCmd::NONE;
		tireChangeId = GfuiLabelCreate(menuHandle, "Tire wear is off", GFUI_FONT_MEDIUM_C, x + dx, y, GFUI_ALIGN_HL_VB, 32);
	} else {
		tireChangeId = GfuiLabelCreate(menuHandle, tireChangeLabel[currentTireChangeOption], GFUI_FONT_MEDIUM_C, x4, y, GFUI_ALIGN_HC_VB, 32);

		GfuiGrButtonCreateAction(menuHandle, "data/img/arrow-left.png", "data/img/arrow-left.png",
			"data/img/arrow-left.png", "data/img/arrow-left-pushed.png",
			x2, y-5, GFUI_ALIGN_HL_VB, 1,
			[] { changeTireState(-1); },
			tGfuiAction(), tGfuiAction());
		GfuiGrButtonCreateAction(menuHandle, "data/img/arrow-right.png", "data/img/arrow-right.png",
			"data/img/arrow-right.png", "data/img/arrow-right-pushed.png",
			x3, y-5, GFUI_ALIGN_HR_VB, 1,
			[] { changeTireState(1); },
			tGfuiAction(), tGfuiAction());

		rmCar->pitcmd.tireChange = tireChangeList[currentTireChangeOption];
		GfuiLabelSetColor(menuHandle, tireChangeId, LabelColor);
	}

	serviceButtonId = GfuiButtonCreateAction(menuHandle, "Service", GFUI_FONT_LARGE, 160, 40, 130, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
				rmService, rmServiceFocus, rmHideButtonTips);
	rmCallback = callback;

	// Just enable stop and go if penalty is pending
	tCarPenalty *penalty = GF_TAILQ_FIRST(&(car->_penaltyList));
	stopAndGoAvailable = penalty && penalty->penalty == RM_PENALTY_STOPANDGO;
	stopAndGoButtonId = GfuiButtonCreateAction(menuHandle, "Stop & Go", GFUI_FONT_LARGE, 320, 40, 130, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
				rmStopAndGo, rmStopAndGoFocus, rmHideButtonTips);
	if (!stopAndGoAvailable) {
		GfuiEnable(menuHandle, stopAndGoButtonId, GFUI_DISABLE);
	}

	// Just enable car setup button in practice and qualifying sessions
	void *setupScreen = RmCarSetupScreenInit(menuHandle, rmCar, rmInfo);
	setupAvailable = reInfo->s->raceInfo.type == RM_TYPE_PRACTICE || reInfo->s->raceInfo.type == RM_TYPE_QUALIF;
	setupButtonId = GfuiButtonCreateAction(menuHandle, "Setup", GFUI_FONT_LARGE, 480, 40, 130, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
		[setupScreen] { GfuiScreenActivate(setupScreen); }, rmSetupFocus, rmHideButtonTips);
	if (!setupAvailable) {
		GfuiEnable(menuHandle, setupButtonId, GFUI_DISABLE);
	}

	serviceTipLabelId = GfuiTipCreate(menuHandle, ServiceTipMessage, 64);
	GfuiVisibilitySet(menuHandle, serviceTipLabelId, GFUI_INVISIBLE);
	stopAndGoTipLabelId = GfuiTipCreate(menuHandle, StopAndGoTipMessage, 64);
	GfuiVisibilitySet(menuHandle, stopAndGoTipLabelId, GFUI_INVISIBLE);
	stopAndGoDisabledTipLabelId = GfuiLabelCreateEx(menuHandle, NoStopAndGoMessage, DisabledTipColor, GFUI_FONT_SMALL,
							320, 15, GFUI_ALIGN_HC_VB, 64);
	GfuiVisibilitySet(menuHandle, stopAndGoDisabledTipLabelId, GFUI_INVISIBLE);
	setupTipLabelId = GfuiTipCreate(menuHandle, SetupTipMessage, 64);
	GfuiVisibilitySet(menuHandle, setupTipLabelId, GFUI_INVISIBLE);
	setupDisabledTipLabelId = GfuiLabelCreateEx(menuHandle, SetupDisabledMessage, DisabledTipColor, GFUI_FONT_SMALL,
						  320, 15, GFUI_ALIGN_HC_VB, 64);
	GfuiVisibilitySet(menuHandle, setupDisabledTipLabelId, GFUI_INVISIBLE);
	
	GfuiScreenActivate(menuHandle);
}

void RmPitMenuStart(tCarElt *car, tRmInfo *reInfo, void *userdata, tfuiCallback callback)
{
	RmPitMenuStartAction(car, reInfo,
		callback ? tGfuiAction([userdata, callback] { callback(userdata); }) : tGfuiAction());
}
