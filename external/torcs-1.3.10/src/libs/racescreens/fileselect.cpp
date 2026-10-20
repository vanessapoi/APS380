/***************************************************************************

    file        : fileselect.cpp
    created     : Sun Feb 16 13:09:23 CET 2003
    copyright   : (C) 2003-2026 by Eric Espié, Bernhard Wymann                        
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
    Files selection screen.
    @author	Bernhard Wymann, Eric Espie
*/


#include <stdlib.h>
#include <stdio.h>
#include <sys/stat.h>
#ifdef WIN32
#include <windows.h>
#endif
#include <tgfclient.h>
#include <racescreens.h>

static void *scrHandle = NULL;
static int fileScrollList;
static tRmFileSelect *rmFs;
static tFList *FileList = NULL;
static tFList *FileSelected;


static void rmActivate(void)
{
}


static void rmClickOnFile(void)
{
    GfuiScrollListGetSelectedElement(scrHandle, fileScrollList, (void**)&FileSelected);
}


static void rmSelect(void)
{
	if (FileList) {
		rmFs->select(FileSelected->name);
		GfDirFreeList(FileList, NULL, true, false);
		FileList = NULL;
	} else {
		rmFs->select(NULL);
	}
}

static void rmDeactivate(void)
{
	if (FileList) {
		GfDirFreeList(FileList, NULL, true, false);
		FileList = NULL;
	}
	GfuiScreenActivate(rmFs->prevScreen);
}


/** @brief File selection
 * 
 *  The files listed are the ones contained in the directory given by the path in tRmFileSelect.path
 *  @ingroup racemantools
 *  @param[in,out] vs Pointer on tRmFileSelect structure (cast to void)
 */
void RmFileSelect(void *vs)
{
	tFList *FileCur;

	rmFs = (tRmFileSelect*)vs;

	if (scrHandle) {
		GfuiScreenRelease(scrHandle);
	}
	scrHandle = GfuiScreenCreateExAction((float*)NULL, rmActivate, tGfuiAction(), 1);
	GfuiScreenAddBgImg(scrHandle, "data/img/splash-filesel.png");
	GfuiTitleCreate(scrHandle, rmFs->title, 0);

	/* Scroll List containing the File list */
	fileScrollList = GfuiScrollListCreateAction(scrHandle, GFUI_FONT_MEDIUM_C, 120, 80, GFUI_ALIGN_HC_VB,
						400, 310, GFUI_SB_RIGHT, rmClickOnFile);

	FileList = GfDirGetList(rmFs->path);
	if (FileList == NULL) {
		GfuiScreenActivate(rmFs->prevScreen);
		return;
	}
	
	FileSelected = FileList;
	FileCur = FileList;
	do {
		FileCur = FileCur->next;
		GfuiScrollListInsertElement(scrHandle, fileScrollList, FileCur->name, 1000, (void*)FileCur);
	} while (FileCur != FileList);

	/* Bottom buttons */
	GfuiButtonCreateAction(scrHandle, "Select", GFUI_FONT_LARGE, 210, 40, 150, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
				rmSelect, tGfuiAction(), tGfuiAction());

	GfuiButtonCreateAction(scrHandle, "Cancel", GFUI_FONT_LARGE, 430, 40, 150, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
				rmDeactivate, tGfuiAction(), tGfuiAction());

	/* Default menu keyboard actions */
	GfuiMenuDefaultKeysAdd(scrHandle);
	GfuiScreenActivate(scrHandle);
}
