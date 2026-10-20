/***************************************************************************
                  trackselect.cpp -- interactive track selection
                             -------------------
    created              : Mon Aug 16 21:43:00 CEST 1999
    copyright            : (C) 1999-2026 by Eric Espié, Bernhard Wymann
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
    @author Bernhard Wymann, Eric Espie
*/


#include <stdlib.h>
#include <stdio.h>
#ifdef WIN32
#include <windows.h>
#endif
#include <tgfclient.h>
#include <track.h>
#include <osspec.h>
#include <raceman.h>
#include <racescreens.h>
#include <portability.h>


/* Tracks Categories */
static tFList *CategoryList;
static void *scrHandle;
static int TrackLabelId;
static int CatLabelId;
static int MapId;
static int AuthorId;
static int LengthId;
static int WidthId;
static int DescId;
static int PitsId;
static tRmTrackSelect *ts;


static void rmtsActivate(void)
{
	/* call display function of graphic */
	//gfuiReleaseImage(MapId);
}


static void rmtsFreeLists(void *vl)
{
	GfDirFreeList((tFList*)vl, NULL, true, true);
}


static int rmtsListLength(tFList *list)
{
	int length = 0;
	tFList *cur;

	if (!list) {
		return 0;
	}

	cur = list;
	do {
		length++;
		cur = cur->next;
	} while (cur != list);

	return length;
}


static tFList *rmtsRemoveListEntry(tFList *list, tFList *entry, tfDirfreeUserData freeUserData)
{
	tFList *nextEntry;
	bool lastEntry;
	bool headEntry;

	if (!list || !entry) {
		return list;
	}

	nextEntry = entry->next;
	lastEntry = entry->next == entry;
	headEntry = list == entry;

	if (!lastEntry) {
		entry->prev->next = entry->next;
		entry->next->prev = entry->prev;
	}
	if (freeUserData && entry->userData) {
		freeUserData(entry->userData);
	}
	if (entry->name) {
		free(entry->name);
	}
	if (entry->dispName) {
		free(entry->dispName);
	}
	free(entry);

	if (lastEntry) {
		return NULL;
	}
	if (headEntry) {
		return nextEntry;
	}
	return list;
}


static char * rmGetMapName(char* buf, const int BUFSIZE)
{
	snprintf(buf, BUFSIZE, "tracks/%s/%s/%s.png", CategoryList->name,
		((tFList*)CategoryList->userData)->name, ((tFList*)CategoryList->userData)->name);
	return buf;
}


static void rmtsDeactivate(void *screen)
{
	GfuiScreenRelease(scrHandle);

	GfDirFreeList(CategoryList, rmtsFreeLists, true, true);
	if (screen) {
		GfuiScreenActivate(screen);
	}
}


static void rmUpdateTrackInfo(void)
{
	void *trackHandle;
	float tmp;
	tTrack *trk;
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];
	
	snprintf(buf, BUFSIZE, "tracks/%s/%s/%s.%s", CategoryList->name, ((tFList*)CategoryList->userData)->name,
		((tFList*)CategoryList->userData)->name, TRKEXT);
	trackHandle = GfParmReadFile(buf, GFPARM_RMODE_STD); /* COMMENT VALID? don't release, the name is used later */

	if (!trackHandle) {
		GfTrace("File %s has pb\n", buf);
		return;
	}
	trk = ts->trackItf.trkBuild(buf);

	GfuiLabelSetText(scrHandle, DescId, GfParmGetStr(trackHandle, TRK_SECT_HDR, TRK_ATT_DESCR, ""));
	GfuiLabelSetText(scrHandle, AuthorId, GfParmGetStr(trackHandle, TRK_SECT_HDR, TRK_ATT_AUTHOR, ""));

	tmp = GfParmGetNum(trackHandle, TRK_SECT_MAIN, TRK_ATT_WIDTH, NULL, 0);
	snprintf(buf, BUFSIZE, "%.2f m", tmp);
	GfuiLabelSetText(scrHandle, WidthId, buf);
	tmp = trk->length;
	snprintf(buf, BUFSIZE, "%.2f m", tmp);
	GfuiLabelSetText(scrHandle, LengthId, buf);

	if (trk->pits.nMaxPits != 0) {
		snprintf(buf, BUFSIZE, "%d", trk->pits.nMaxPits);
		GfuiLabelSetText(scrHandle, PitsId, buf);
	} else {
		GfuiLabelSetText(scrHandle, PitsId, "none");
	}

	ts->trackItf.trkShutdown();
	GfParmReleaseHandle(trackHandle);
}


static void rmtsPrevNext(int delta)
{
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];
	
	if (delta < 0) {
		CategoryList->userData = (void*)(((tFList*)CategoryList->userData)->prev);
	} else {
		CategoryList->userData = (void*)(((tFList*)CategoryList->userData)->next);
	}

	GfuiLabelSetText(scrHandle, TrackLabelId, ((tFList*)CategoryList->userData)->dispName);
	GfuiStaticImageSet(scrHandle, MapId, rmGetMapName(buf, BUFSIZE));
	rmUpdateTrackInfo();
}


static void rmCatPrevNext(int delta)
{
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];

	if (delta < 0) {
		CategoryList = CategoryList->prev;
	} else {
		CategoryList = CategoryList->next;
	}

	GfuiLabelSetText(scrHandle, CatLabelId, CategoryList->dispName);
	GfuiLabelSetText(scrHandle, TrackLabelId, ((tFList*)CategoryList->userData)->dispName);
	GfuiStaticImageSet(scrHandle, MapId, rmGetMapName(buf, BUFSIZE));
	rmUpdateTrackInfo();
}


void rmtsSelect(void)
{
	int curTrkIdx;
	const int BUFSIZE = 1024;
	char path[BUFSIZE];

	curTrkIdx = (int)GfParmGetNum(ts->param, RM_SECT_TRACKS, RE_ATTR_CUR_TRACK, NULL, 1);
	snprintf(path, BUFSIZE, "%s/%d", RM_SECT_TRACKS, curTrkIdx);
	GfParmSetStr(ts->param, path, RM_ATTR_CATEGORY, CategoryList->name);
	GfParmSetStr(ts->param, path, RM_ATTR_NAME, ((tFList*)CategoryList->userData)->name);

	rmtsDeactivate(ts->nextScreen);
}


static void rmtsAddKeys(void)
{
	GfuiAddKeyAction(scrHandle, 13, "Select Track", rmtsSelect, tGfuiAction());
	GfuiAddKeyAction(scrHandle, 27, "Cancel Selection", [] { rmtsDeactivate(ts->prevScreen); }, tGfuiAction());
	GfuiAddSKeyAction(scrHandle, GLUT_KEY_LEFT, "Previous Track", [] { rmtsPrevNext(-1); }, tGfuiAction());
	GfuiAddSKeyAction(scrHandle, GLUT_KEY_RIGHT, "Next Track", [] { rmtsPrevNext(1); }, tGfuiAction());
	GfuiAddSKeyAction(scrHandle, GLUT_KEY_F12, "Screen-Shot", [] { GfuiScreenShot(NULL); }, tGfuiAction());
	GfuiAddSKeyAction(scrHandle, GLUT_KEY_UP, "Previous Track Category", [] { rmCatPrevNext(-1); }, tGfuiAction());
	GfuiAddSKeyAction(scrHandle, GLUT_KEY_DOWN, "Next Track Category", [] { rmCatPrevNext(1); }, tGfuiAction());
}


/** @brief Get the track name defined in the parameters
 *  @ingroup racemantools
 *  @param[in] category Track category directory
 *  @param[in] trackName Track file name
 *  @return Long track name on success
 *  <br>Empty string on failure
 *  @note The returned string is allocated on the heap and must be released by the caller at some point
 */
char* RmGetTrackName(char *category, char *trackName)
{
	void *trackHandle;
	char *name;
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];

	snprintf(buf, BUFSIZE, "tracks/%s/%s/%s.%s", category, trackName, trackName, TRKEXT);
	trackHandle = GfParmReadFile(buf, GFPARM_RMODE_STD); /* don't release, the name is used later */

	if (trackHandle) {
		name = strdup(GfParmGetStr(trackHandle, TRK_SECT_HDR, TRK_ATT_NAME, trackName));
	} else {
		GfTrace("File %s has pb\n", buf);
		return strdup("");
	}

	GfParmReleaseHandle(trackHandle);
	return name;
}


/** @brief Get the track category name from the track category file
 *  @ingroup racemantools
 *  @param[in] category Track category file
 *  @return Category display name on success
 *  <br>Empty string on failure
 *  @note The returned string is allocated on the heap and must be released by the caller at some point   
 */
char* RmGetCategoryName(char *category)
{
	void *categoryHandle;
	char *name;
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];

	snprintf(buf, BUFSIZE, "data/tracks/%s.%s", category, TRKEXT);
	categoryHandle = GfParmReadFile(buf, GFPARM_RMODE_STD); /* don't release, the name is used later */

	if (categoryHandle) {
		name = strdup(GfParmGetStr(categoryHandle, TRK_SECT_HDR, TRK_ATT_NAME, category));
	} else {
		GfTrace("File %s has pb\n", buf);
		return strdup("");
	}

	GfParmReleaseHandle(categoryHandle);
	return name;
}


static tFList *rmtsFilterTracks(char *category, tFList *trackList)
{
	tFList *trackCur;
	int nbTrack;
	int i;

	nbTrack = rmtsListLength(trackList);
	trackCur = trackList;
	for (i = 0; i < nbTrack && trackList; i++) {
		tFList *nextTrack = trackCur->next;

		trackCur->dispName = RmGetTrackName(category, trackCur->name);
		if (strlen(trackCur->dispName) == 0) {
			GfTrace("RmTrackSelect: Skipping track %s/%s without a readable definition\n", category, trackCur->name);
			trackList = rmtsRemoveListEntry(trackList, trackCur, NULL);
		}
		trackCur = nextTrack;
	}

	return trackList ? trackList->next : NULL;
}


/** @brief Track selection, the race manager parameter set is handed over in vs, tRmTrackSelect.param
 *  @ingroup racemantools
 *  @param[in,out] vs Pointer on a tRmTrackSelect structure (cast to void *)
 *  @note The race manager parameter set is modified in memory but not persisted.
 *  @note If the remembered track is no longer present, the selector falls back
 *  to the first available track and updates the current track entry in memory.
 */
void RmTrackSelect(void *vs)
{
	const char *defaultTrack;
	const char *defaultCategory;
	tFList *CatCur;
	tFList *TrList, *TrCur;
	int Xpos, Ypos, DX, DY;
	int curTrkIdx;
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];
	char path[BUFSIZE];
	bool foundCategory = false;
	bool foundTrack = false;

	ts = (tRmTrackSelect*)vs;

	/* Get the list of categories directories */
	CategoryList = GfDirGetList("tracks");
	if (CategoryList == NULL) {
		GfTrace("RmTrackSelect: No track category available\n");
		return;
	}

	const int nbCategory = rmtsListLength(CategoryList);
	CatCur = CategoryList;
	for (int i = 0; i < nbCategory && CategoryList; i++) {
		tFList *nextCategory = CatCur->next;

		CatCur->dispName = RmGetCategoryName(CatCur->name);
		if (strlen(CatCur->dispName) == 0) {
			GfTrace("RmTrackSelect: Skipping track category %s without a readable definition\n", CatCur->name);
			CategoryList = rmtsRemoveListEntry(CategoryList, CatCur, rmtsFreeLists);
			CatCur = nextCategory;
			continue;
		}

		/* get the tracks in the category directory */
		snprintf(buf, BUFSIZE, "tracks/%s", CatCur->name);
		TrList = GfDirGetList(buf);
		if (TrList == NULL) {
			GfTrace("RmTrackSelect: No track for category %s available\n", CatCur->name);
			CategoryList = rmtsRemoveListEntry(CategoryList, CatCur, rmtsFreeLists);
			CatCur = nextCategory;
			continue;
		}
		TrList = rmtsFilterTracks(CatCur->name, TrList);
		if (TrList == NULL) {
			GfTrace("RmTrackSelect: No valid track for category %s available\n", CatCur->name);
			CategoryList = rmtsRemoveListEntry(CategoryList, CatCur, rmtsFreeLists);
			CatCur = nextCategory;
			continue;
		}
		CatCur->userData = (void*)TrList;

		CatCur = CatCur->next;
	}
	if (CategoryList == NULL) {
		GfTrace("RmTrackSelect: No valid track category available\n");
		return;
	}

	curTrkIdx = (int)GfParmGetNum(ts->param, RM_SECT_TRACKS, RE_ATTR_CUR_TRACK, NULL, 1);
	snprintf(path, BUFSIZE, "%s/%d", RM_SECT_TRACKS, curTrkIdx);
	defaultCategory = GfParmGetStr(ts->param, path, RM_ATTR_CATEGORY, CategoryList->name);
	defaultTrack = GfParmGetStr(ts->param, path, RM_ATTR_NAME, ((tFList*)CategoryList->userData)->name);

	tFList *categoryHead = CategoryList;
	CatCur = categoryHead;
	do {
		if (strcmp(CatCur->name, defaultCategory) == 0) {
			CategoryList = CatCur;
			foundCategory = true;
			tFList *trackHead = (tFList*)(CatCur->userData);
			TrCur = trackHead;
			do {
				if (strcmp(TrCur->name, defaultTrack) == 0) {
					CatCur->userData = (void*)TrCur;
					foundTrack = true;
					break;
				}
				TrCur = TrCur->next;
			} while (TrCur != trackHead);
			break;
		}
		CatCur = CatCur->next;
	} while (CatCur != categoryHead);

	if (!foundCategory || !foundTrack) {
		GfTrace("RmTrackSelect: Selected track %s/%s is not available, falling back to %s/%s\n",
			defaultCategory,
			defaultTrack,
			CategoryList->name,
			((tFList*)CategoryList->userData)->name);
		GfParmSetStr(ts->param, path, RM_ATTR_CATEGORY, CategoryList->name);
		GfParmSetStr(ts->param, path, RM_ATTR_NAME, ((tFList*)CategoryList->userData)->name);
	}

	scrHandle = GfuiScreenCreateExAction((float*)NULL, rmtsActivate, tGfuiAction(), 1);
	GfuiScreenAddBgImg(scrHandle, "data/img/splash-qrtrk.png");

	rmtsAddKeys();

	GfuiTitleCreate(scrHandle, "Select Track", 0);

	GfuiGrButtonCreateAction(scrHandle,
			"data/img/arrow-left.png",
			"data/img/arrow-left.png",
			"data/img/arrow-left.png",
			"data/img/arrow-left-pushed.png",
			80, 400, GFUI_ALIGN_HC_VB, 0,
			[] { rmCatPrevNext(-1); }, tGfuiAction(), tGfuiAction());


	CatLabelId = GfuiLabelCreate(scrHandle,
				CategoryList->dispName,
				GFUI_FONT_LARGE_C,
				320, 400, GFUI_ALIGN_HC_VB,
				30);

	GfuiGrButtonCreateAction(scrHandle,
			"data/img/arrow-right.png",
			"data/img/arrow-right.png",
			"data/img/arrow-right.png",
			"data/img/arrow-right-pushed.png",
			540, 400, GFUI_ALIGN_HC_VB, 0,
			[] { rmCatPrevNext(1); }, tGfuiAction(), tGfuiAction());

	GfuiGrButtonCreateAction(scrHandle,
			"data/img/arrow-left.png",
			"data/img/arrow-left.png",
			"data/img/arrow-left.png",
			"data/img/arrow-left-pushed.png",
			80, 370, GFUI_ALIGN_HC_VB, 0,
			[] { rmtsPrevNext(-1); }, tGfuiAction(), tGfuiAction());


	TrackLabelId = GfuiLabelCreate(scrHandle,
				((tFList*)CategoryList->userData)->dispName,
				GFUI_FONT_LARGE_C,
				320, 370, GFUI_ALIGN_HC_VB,
				30);

	GfuiGrButtonCreateAction(scrHandle,
			"data/img/arrow-right.png",
			"data/img/arrow-right.png",
			"data/img/arrow-right.png",
			"data/img/arrow-right-pushed.png",
			540, 370, GFUI_ALIGN_HC_VB, 0,
			[] { rmtsPrevNext(1); }, tGfuiAction(), tGfuiAction());

	int scrw, scrh, vw, vh;
	GfScrGetSize(&scrw, &scrh, &vw, &vh);
	MapId = GfuiStaticImageCreate(scrHandle,
				320, 100, (int) (vh*260.0f/vw), 195,
				rmGetMapName(buf, BUFSIZE));

	GfuiButtonCreateAction(scrHandle, "Accept", GFUI_FONT_LARGE, 210, 40, 150, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
			rmtsSelect, tGfuiAction(), tGfuiAction());

	GfuiButtonCreateAction(scrHandle, "Back", GFUI_FONT_LARGE, 430, 40, 150, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
			[] { rmtsDeactivate(ts->prevScreen); }, tGfuiAction(), tGfuiAction());

	Xpos = 20;
	Ypos = 320;
	DX = 110;
	DY = 30;

	GfuiLabelCreate(scrHandle,
			"Description:",
			GFUI_FONT_MEDIUM,
			Xpos, Ypos,
			GFUI_ALIGN_HL_VB, 0);

	DescId =  GfuiLabelCreate(scrHandle,
				"",
				GFUI_FONT_MEDIUM_C,
				Xpos + DX, Ypos,
				GFUI_ALIGN_HL_VB, 50);

	Ypos -= DY;

	GfuiLabelCreate(scrHandle,
			"Author:",
			GFUI_FONT_MEDIUM,
			Xpos, Ypos,
			GFUI_ALIGN_HL_VB, 0);

	AuthorId = GfuiLabelCreate(scrHandle,
				"",
				GFUI_FONT_MEDIUM_C,
				Xpos + DX, Ypos,
				GFUI_ALIGN_HL_VB, 20);

	Ypos -= DY;

	GfuiLabelCreate(scrHandle,
			"Length:",
			GFUI_FONT_MEDIUM,
			Xpos, Ypos,
			GFUI_ALIGN_HL_VB, 0);

	LengthId = GfuiLabelCreate(scrHandle,
				"",
				GFUI_FONT_MEDIUM_C,
				Xpos + DX, Ypos,
				GFUI_ALIGN_HL_VB, 20);

	Ypos -= DY;

	GfuiLabelCreate(scrHandle,
			"Width:",
			GFUI_FONT_MEDIUM,
			Xpos, Ypos,
			GFUI_ALIGN_HL_VB, 0);

	WidthId = GfuiLabelCreate(scrHandle,
				"",
				GFUI_FONT_MEDIUM_C,
				Xpos + DX, Ypos,
				GFUI_ALIGN_HL_VB, 20);

	Ypos -= DY;

	GfuiLabelCreate(scrHandle,
			"Pits:",
			GFUI_FONT_MEDIUM,
			Xpos, Ypos,
			GFUI_ALIGN_HL_VB, 0);

	PitsId = GfuiLabelCreate(scrHandle,
				"",
				GFUI_FONT_MEDIUM_C,
				Xpos + DX, Ypos,
				GFUI_ALIGN_HL_VB, 20);

	rmUpdateTrackInfo();

	GfuiScreenActivate(scrHandle);
}
