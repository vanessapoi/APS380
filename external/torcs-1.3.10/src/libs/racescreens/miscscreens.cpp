/***************************************************************************

    file        : miscscreens.cpp
    created     : Sun Dec  8 13:01:47 CET 2002
    copyright   : (C) 2000-2026 by Eric Espié, Bernhard Wymann                        
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
    Common screens for race manager menus
    @author bernhard Wymann, Eric Espie
*/

#include <stdio.h>
#include <tgfclient.h>
#include <robot.h>

#include <racescreens.h>
#include <portability.h>

static void *twoStateHdle = 0;
static void *triStateHdle = 0;
static void *fourStateHdle = 0;
static void *nStateHandle = 0;


/** @brief Screen with 2 menu options (buttons)
 *  @ingroup racemantools
 *  @param[in] title Title of the screen
 *  @param[in] label1 Button text for first option
 *  @param[in] tip1 Description for first option
 *  @param[in] screen1 Target screen to activate for first option
 *  @param[in] label2 Button text for second option
 *  @param[in] tip2 Description for second option
 *  @param[in] screen2 Target screen to activate for second option
 *  @return Handle to screen
 */
void *RmTwoStateScreen(
	const char *title,
	const char *label1, const char *tip1, void *screen1,
	const char *label2, const char *tip2, void *screen2)
{
	if (twoStateHdle) {
		GfuiScreenRelease(twoStateHdle);
	}
	
	twoStateHdle = GfuiMenuScreenCreate(title);
	GfuiScreenAddBgImg(twoStateHdle, "data/img/splash-quit.png");
	GfuiMenuButtonCreateAction(twoStateHdle, label1, tip1, [screen1] { GfuiScreenActivate(screen1); });
	GfuiMenuButtonCreateAction(twoStateHdle, label2, tip2, [screen2] { GfuiScreenActivate(screen2); });
	GfuiAddKeyAction(twoStateHdle, 27, tip2, [screen2] { GfuiScreenActivate(screen2); }, tGfuiAction());
	GfuiScreenActivate(twoStateHdle);

	return twoStateHdle;
}


/** @brief Screen with 3 menu options (buttons)
 *  @ingroup racemantools
 *  @param[in] title Title of the screen
 *  @param[in] label1 Button text for first option
 *  @param[in] tip1 Description for first option
 *  @param[in] screen1 Target screen to activate for first option
 *  @param[in] label2 Button text for second option
 *  @param[in] tip2 Description for second option
 *  @param[in] screen2 Target screen to activate for second option
 *  @param[in] label3 Button text for third option
 *  @param[in] tip3 Description for third option
 *  @param[in] screen3 Target screen to activate for third option
 *  @return Handle to screen
 */
void *RmTriStateScreen(
	const char *title,
	const char *label1, const char *tip1, void *screen1,
	const char *label2, const char *tip2, void *screen2,
	const char *label3, const char *tip3, void *screen3)
{
	if (triStateHdle) {
		GfuiScreenRelease(triStateHdle);
	}
	
	triStateHdle = GfuiMenuScreenCreate(title);
	GfuiScreenAddBgImg(triStateHdle, "data/img/splash-quit.png");
	GfuiMenuButtonCreateAction(triStateHdle, label1, tip1, [screen1] { GfuiScreenActivate(screen1); });
	GfuiMenuButtonCreateAction(triStateHdle, label2, tip2, [screen2] { GfuiScreenActivate(screen2); });
	GfuiMenuButtonCreateAction(triStateHdle, label3, tip3, [screen3] { GfuiScreenActivate(screen3); });
	GfuiAddKeyAction(triStateHdle, 27, tip3, [screen3] { GfuiScreenActivate(screen3); }, tGfuiAction());
	GfuiScreenActivate(triStateHdle);
	
	return triStateHdle;
}


/** @brief Screen with 4 menu options (buttons)
 *  @ingroup racemantools
 *  @param[in] title Title of the screen
 *  @param[in] label1 Button text for first option
 *  @param[in] tip1 Description for first option
 *  @param[in] screen1 Target screen to activate for first option
 *  @param[in] label2 Button text for second option
 *  @param[in] tip2 Description for second option
 *  @param[in] screen2 Target screen to activate for second option
 *  @param[in] label3 Button text for third option
 *  @param[in] tip3 Description for third option
 *  @param[in] screen3 Target screen to activate for third option
 *  @param[in] label4 Button text for fourth option
 *  @param[in] tip4 Description for fourth option
 *  @param[in] screen4 Target screen to activate for fourth option
 *  @return Handle to screen
 */
void *RmFourStateScreen(
	const char *title,
	const char *label1, const char *tip1, void *screen1,
	const char *label2, const char *tip2, void *screen2,
	const char *label3, const char *tip3, void *screen3,
	const char *label4, const char *tip4, void *screen4)
{
	if (fourStateHdle) {
		GfuiScreenRelease(fourStateHdle);
	}
	
	fourStateHdle = GfuiMenuScreenCreate(title);
	GfuiScreenAddBgImg(fourStateHdle, "data/img/splash-quit.png");
	GfuiMenuButtonCreateAction(fourStateHdle, label1, tip1, [screen1] { GfuiScreenActivate(screen1); });
	GfuiMenuButtonCreateAction(fourStateHdle, label2, tip2, [screen2] { GfuiScreenActivate(screen2); });
	GfuiMenuButtonCreateAction(fourStateHdle, label3, tip3, [screen3] { GfuiScreenActivate(screen3); });
	GfuiMenuButtonCreateAction(fourStateHdle, label4, tip4, [screen4] { GfuiScreenActivate(screen4); });
	GfuiAddKeyAction(fourStateHdle, 27, tip4, [screen4] { GfuiScreenActivate(screen4); }, tGfuiAction());
	GfuiScreenActivate(fourStateHdle);
	
	return fourStateHdle;
}


/** @brief Screen with N menu options (buttons)
 *  @ingroup racemantools
 *  @param[in] title Title of the screen
 *  @param[in] label Array of n button texts
 *  @param[in] tip Array of n descriptions
 *  @param[in] screen Array of n screens
 *  @param[in] n Size of arrays
 *  @return Handle to screen
 */
void *RmNStateScreen(
	const char *title,
	const char** label,
	const char** tip,
	void** screen,
	const int n
)
{
	if (nStateHandle) {
		GfuiScreenRelease(nStateHandle);
	}
	
	nStateHandle = GfuiMenuScreenCreate(title);
	GfuiScreenAddBgImg(nStateHandle, "data/img/splash-quit.png");

	int i;
	for (i = 0; i < n; i++) {
		void *target = screen[i];
		GfuiMenuButtonCreateAction(nStateHandle, label[i], tip[i], [target] { GfuiScreenActivate(target); });
	}

	void *backTarget = screen[n-1];
	GfuiAddKeyAction(nStateHandle, 27, tip[n-1], [backTarget] { GfuiScreenActivate(backTarget); }, tGfuiAction());
	GfuiScreenActivate(nStateHandle);

	return nStateHandle;
}


/*********************************************************
 * Start screen
 */

#define MAX_LINES 20

typedef struct 
{
    void	*startScr;
    void	*abortScr;
    tRmInfo	*info;
    int		start;
} tStartRaceCall;

static tStartRaceCall	nextStartRace, prevStartRace;
static void		*rmScrHdle = 0;

static void rmDisplayStartRace(tRmInfo *info, void *startScr, void *abortScr, int start);

static void
rmChgStartScreen(tStartRaceCall *psrc)
{
	void		*prevScr = rmScrHdle;
	
	rmDisplayStartRace(psrc->info, psrc->startScr, psrc->abortScr, psrc->start);
	GfuiScreenRelease(prevScr);
}

static void
rmDisplayStartRace(tRmInfo *info, void *startScr, void *abortScr, int start)
{
	const int BUFSIZE = 1024;
	char path[BUFSIZE];
	int nCars;
	int i;
	int y;
	int x, dx;
	int rows, curRow;
	int robotIdx;
	void *robhdle;
	void *carHdle;
	void *params = info->params;
	const char *race = info->_reRaceName;
	
	rmScrHdle = GfuiScreenCreate();
	GfuiTitleCreate(rmScrHdle, race, strlen(race));	
	
	const char* img = GfParmGetStr(params, RM_SECT_HEADER, RM_ATTR_STARTIMG, 0);
	if (img) {
		GfuiScreenAddBgImg(rmScrHdle, img);
	}
	
	if (!strcmp(GfParmGetStr(params, race, RM_ATTR_DISP_START_GRID, RM_VAL_YES), RM_VAL_YES)) {
		GfuiLabelCreate(rmScrHdle, "Starting Grid", GFUI_FONT_MEDIUM_C, 320, 420, GFUI_ALIGN_HC_VB, 0);
		snprintf(path, BUFSIZE, "%s/%s", race, RM_SECT_STARTINGGRID);
		rows = (int)GfParmGetNum(params, path, RM_ATTR_ROWS, (char*)NULL, 2);
		
		dx = 0;
		x = 40;
		y = 400;
		curRow = 0;
		nCars = GfParmGetEltNb(params, RM_SECT_DRIVERS_RACING);
		
		for (i = start; i < MIN(start + MAX_LINES, nCars); i++) {
			/* Find starting driver's name */
			snprintf(path, BUFSIZE, "%s/%d", RM_SECT_DRIVERS_RACING, i + 1);
			const char* name = GfParmGetStr(info->params, path, RM_ATTR_MODULE, "");
			robotIdx = (int)GfParmGetNum(info->params, path, RM_ATTR_IDX, NULL, 0);
			
			snprintf(path, BUFSIZE, "%sdrivers/%s/%s.xml", GetLocalDir(), name, name);
			robhdle = GfParmReadFile(path, GFPARM_RMODE_STD);
			if (!robhdle) {
				snprintf(path, BUFSIZE, "drivers/%s/%s.xml", name, name);
				robhdle = GfParmReadFile(path, GFPARM_RMODE_STD);
			}

			if (robhdle) {
				snprintf(path, BUFSIZE, "%s/%s/%d", ROB_SECT_ROBOTS, ROB_LIST_INDEX, robotIdx);
				name = GfParmGetStr(robhdle, path, ROB_ATTR_NAME, "<none>");
				const char* carName = GfParmGetStr(robhdle, path, ROB_ATTR_CAR, "");
				
				snprintf(path, BUFSIZE, "cars/%s/%s.xml", carName, carName);
				carHdle = GfParmReadFile(path, GFPARM_RMODE_STD);
				carName = GfParmGetName(carHdle);
			
				snprintf(path, BUFSIZE, "%d - %s - (%s)", i + 1, name, carName);
				GfuiLabelCreate(rmScrHdle, path, GFUI_FONT_MEDIUM_C,
						x + curRow * dx, y, GFUI_ALIGN_HL_VB, 0);

				GfParmReleaseHandle(carHdle);
				GfParmReleaseHandle(robhdle);
			}
			curRow = (curRow + 1) % rows;
			y -= 15;
		}
		
		
		if (start > 0) {
			prevStartRace.startScr = startScr;
			prevStartRace.abortScr = abortScr;
			prevStartRace.info     = info;
			prevStartRace.start    = start - MAX_LINES;
			GfuiGrButtonCreateAction(rmScrHdle, "data/img/arrow-up.png", "data/img/arrow-up.png",
						"data/img/arrow-up.png", "data/img/arrow-up-pushed.png",
						80, 40, GFUI_ALIGN_HL_VB, 1,
						[] { rmChgStartScreen(&prevStartRace); }, tGfuiAction(), tGfuiAction());
			GfuiAddSKeyAction(rmScrHdle, GLUT_KEY_PAGE_UP, "Previous drivers", [] { rmChgStartScreen(&prevStartRace); }, tGfuiAction());
		}
		
		if (i < nCars) {
			nextStartRace.startScr = startScr;
			nextStartRace.abortScr = abortScr;
			nextStartRace.info     = info;
			nextStartRace.start    = start + MAX_LINES;
			GfuiGrButtonCreateAction(rmScrHdle, "data/img/arrow-down.png", "data/img/arrow-down.png",
						"data/img/arrow-down.png", "data/img/arrow-down-pushed.png",
						540, 40, GFUI_ALIGN_HL_VB, 1,
						[] { rmChgStartScreen(&nextStartRace); }, tGfuiAction(), tGfuiAction());
			GfuiAddSKeyAction(rmScrHdle, GLUT_KEY_PAGE_DOWN, "Next Drivers", [] { rmChgStartScreen(&nextStartRace); }, tGfuiAction());
		}
	}
	
	GfuiButtonCreateAction(rmScrHdle,
				"Start",
				GFUI_FONT_LARGE,
				210,
				40,
				150,
				GFUI_ALIGN_HC_VB,
				0,
				[startScr] { GfuiScreenReplace(startScr); },
				tGfuiAction(),
				tGfuiAction());
	GfuiAddKeyAction(rmScrHdle, (unsigned char)13, "Start", [startScr] { GfuiScreenReplace(startScr); }, tGfuiAction());

	GfuiButtonCreateAction(rmScrHdle,
				"Abandon",
				GFUI_FONT_LARGE,
				430,
				40,
				150,
				GFUI_ALIGN_HC_VB,
				0,
				[abortScr] { GfuiScreenReplace(abortScr); },
				tGfuiAction(),
				tGfuiAction());
	GfuiAddKeyAction(rmScrHdle, (unsigned char)27, "Abandon", [abortScr] { GfuiScreenReplace(abortScr); }, tGfuiAction());

	GfuiAddSKeyAction(rmScrHdle, GLUT_KEY_F12, "Take a Screen Shot", [] { GfuiScreenShot(NULL); }, tGfuiAction());
	
	GfuiScreenActivate(rmScrHdle);
}


void
RmDisplayStartRace(tRmInfo *info, void *startScr, void *abortScr)
{
    rmDisplayStartRace(info, startScr, abortScr, 0);
}
