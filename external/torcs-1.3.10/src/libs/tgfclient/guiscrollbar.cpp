/***************************************************************************

    file                 : guiscrollbar.cpp
    created              : Mon Aug 23 22:11:37 CEST 1999
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
    		GUI scrollbar management.
    @author	<a href=mailto:torcs@free.fr>Eric Espie</a>
*/

#include <stdlib.h>
#ifdef WIN32
#include <windows.h>
#endif
#include <tgfclient.h>
#include "gui.h"

void
gfuiScrollBarInit(void)
{
}

static void
gfuiScrollPlus(tGfuiObject *object)
{
	tGfuiScrollBar	*scrollbar;
	tScrollBarInfo	info;

	if(object == NULL) {
		return;
	}

	scrollbar = &(object->u.scrollbar);
	scrollbar->pos++;

	if(scrollbar->pos > scrollbar->max) {
		scrollbar->pos = scrollbar->max;
	} else if(scrollbar->onScroll != NULL) {
		info.pos = scrollbar->pos;
		info.userData = scrollbar->userData;
		scrollbar->onScroll(&info);
	}
}

static void
gfuiScrollMinus(tGfuiObject *object)
{
	tGfuiScrollBar	*scrollbar;
	tScrollBarInfo	info;

	if(object == NULL) {
		return;
	}

	scrollbar = &(object->u.scrollbar);
	scrollbar->pos--;

	if(scrollbar->pos < scrollbar->min) {
		scrollbar->pos = scrollbar->min;
	} else if(scrollbar->onScroll != NULL) {
		info.pos = scrollbar->pos;
		info.userData = scrollbar->userData;
		scrollbar->onScroll(&info);
	}
}

static void
gfuiScrollButtonCreate(void *scr, const char *image, const char *pushed,
					   int x, int y, int align, tGfuiObject *object,
					   void (*onPush)(tGfuiObject *))
{
	GfuiGrButtonCreateAction(scr, image, image, image, pushed, x, y, align, 1,
		[object, onPush] { onPush(object); }, tGfuiAction(), tGfuiAction());
}

/** Create a new scroll bar.
    @ingroup	gui
    @param[in,out] scr Screen receiving the scroll bar.
    @param[in] x Horizontal anchor in GUI coordinates.
    @param[in] y Vertical anchor in GUI coordinates.
    @param[in] align Position of the specified point:
    			<br>GFUI_ALIGN_HR_VB	horizontal right, vertical bottom
    			<br>GFUI_ALIGN_HR_VC	horizontal right, vertical center
    			<br>GFUI_ALIGN_HR_VT	horizontal right, vertical top
    			<br>GFUI_ALIGN_HC_VB	horizontal center, vertical bottom
    			<br>GFUI_ALIGN_HC_VC	horizontal center, vertical center
    			<br>GFUI_ALIGN_HC_VT	horizontal center, vertical top
    			<br>GFUI_ALIGN_HL_VB	horizontal left, vertical bottom
    			<br>GFUI_ALIGN_HL_VC	horizontal left, vertical center
    			<br>GFUI_ALIGN_HL_VT	horizontal left, vertical top
    @param[in] width Length along the scroll axis, including arrows, in GUI units.
    @param[in] orientation Scroll bar orientation:
				<br>GFUI_HORI_SCROLLBAR	Horizontal
				<br>GFUI_VERT_SCROLLBAR	Vertical
    @param[in] min Minimum position, inclusive.
    @param[in] max Maximum position, inclusive; must be at least min.
    @param[in] len Visible length, stored as metadata; arrow clicks step by one.
    @param[in] start Initial position; caller must keep it within [min, max].
    @param[in] userData Borrowed data passed in tScrollBarInfo::userData.
    @param[in] onScroll Callback on an arrow click that changes position, or NULL.
        The tScrollBarInfo pointer passed to it is valid only during the callback.
    @return Scroll-bar identifier, local to scr.
 */
int
GfuiScrollBarCreate(void *scr, int x, int y, int align, int width, int orientation,
                    int min, int max, int len, int start,
                    void *userData, tfuiSBCallback onScroll)
{
	tGfuiObject		*object;
	tGfuiScrollBar	*scrollbar;
	tGfuiScreen		*screen = (tGfuiScreen *)scr;

	object = (tGfuiObject *)calloc(1, sizeof(tGfuiObject));
	object->widget = GFUI_SCROLLBAR;
	object->focusMode = GFUI_FOCUS_MOUSE_CLICK;
	object->id = screen->curId++;
	object->visible = 1;

	scrollbar = &(object->u.scrollbar);
	scrollbar->userData = userData;
	scrollbar->onScroll = onScroll;

	switch(orientation) {
		case GFUI_HORI_SCROLLBAR:
			switch(align) {
				case GFUI_ALIGN_HR_VB:
					gfuiScrollButtonCreate(scr, "data/img/arrow-right.png", "data/img/arrow-right-pushed.png", x, y, GFUI_ALIGN_HR_VB, object, gfuiScrollPlus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-left.png", "data/img/arrow-left-pushed.png", x - width, y, GFUI_ALIGN_HL_VB, object, gfuiScrollMinus);
					break;
				case GFUI_ALIGN_HR_VC:
					gfuiScrollButtonCreate(scr, "data/img/arrow-right.png", "data/img/arrow-right-pushed.png", x, y, GFUI_ALIGN_HR_VC, object, gfuiScrollPlus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-left.png", "data/img/arrow-left-pushed.png", x - width, y, GFUI_ALIGN_HL_VC, object, gfuiScrollMinus);
					break;
				case GFUI_ALIGN_HR_VT:
					gfuiScrollButtonCreate(scr, "data/img/arrow-right.png", "data/img/arrow-right-pushed.png", x, y, GFUI_ALIGN_HR_VT, object, gfuiScrollPlus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-left.png", "data/img/arrow-left-pushed.png", x - width, y, GFUI_ALIGN_HL_VT, object, gfuiScrollMinus);
					break;
				case GFUI_ALIGN_HC_VB:
					gfuiScrollButtonCreate(scr, "data/img/arrow-right.png", "data/img/arrow-right-pushed.png", x + width / 2, y, GFUI_ALIGN_HR_VB, object, gfuiScrollPlus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-left.png", "data/img/arrow-left-pushed.png", x - width / 2, y, GFUI_ALIGN_HL_VB, object, gfuiScrollMinus);
					break;
				case GFUI_ALIGN_HC_VC:
					gfuiScrollButtonCreate(scr, "data/img/arrow-right.png", "data/img/arrow-right-pushed.png", x + width / 2, y, GFUI_ALIGN_HR_VC, object, gfuiScrollPlus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-left.png", "data/img/arrow-left-pushed.png", x - width / 2, y, GFUI_ALIGN_HL_VC, object, gfuiScrollMinus);
					break;
				case GFUI_ALIGN_HC_VT:
					gfuiScrollButtonCreate(scr, "data/img/arrow-right.png", "data/img/arrow-right-pushed.png", x + width / 2, y, GFUI_ALIGN_HR_VT, object, gfuiScrollPlus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-left.png", "data/img/arrow-left-pushed.png", x - width / 2, y, GFUI_ALIGN_HL_VT, object, gfuiScrollMinus);
					break;
				case GFUI_ALIGN_HL_VB:
					gfuiScrollButtonCreate(scr, "data/img/arrow-right.png", "data/img/arrow-right-pushed.png", x + width, y, GFUI_ALIGN_HR_VB, object, gfuiScrollPlus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-left.png", "data/img/arrow-left-pushed.png", x, y, GFUI_ALIGN_HL_VB, object, gfuiScrollMinus);
					break;
				case GFUI_ALIGN_HL_VC:
					gfuiScrollButtonCreate(scr, "data/img/arrow-right.png", "data/img/arrow-right-pushed.png", x + width, y, GFUI_ALIGN_HR_VC, object, gfuiScrollPlus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-left.png", "data/img/arrow-left-pushed.png", x, y, GFUI_ALIGN_HL_VC, object, gfuiScrollMinus);
					break;
				case GFUI_ALIGN_HL_VT:
					gfuiScrollButtonCreate(scr, "data/img/arrow-right.png", "data/img/arrow-right-pushed.png", x + width, y, GFUI_ALIGN_HR_VT, object, gfuiScrollPlus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-left.png", "data/img/arrow-left-pushed.png", x, y, GFUI_ALIGN_HL_VT, object, gfuiScrollMinus);
					break;
				default:
					break;
			}
			break;
		case GFUI_VERT_SCROLLBAR:
			switch(align) {
				case GFUI_ALIGN_HR_VB:
					gfuiScrollButtonCreate(scr, "data/img/arrow-up.png", "data/img/arrow-up-pushed.png", x, y + width, GFUI_ALIGN_HR_VT, object, gfuiScrollMinus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-down.png", "data/img/arrow-down-pushed.png", x, y, GFUI_ALIGN_HR_VB, object, gfuiScrollPlus);
					break;
				case GFUI_ALIGN_HR_VC:
					gfuiScrollButtonCreate(scr, "data/img/arrow-up.png", "data/img/arrow-up-pushed.png", x, y + width / 2, GFUI_ALIGN_HR_VT, object, gfuiScrollMinus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-down.png", "data/img/arrow-down-pushed.png", x, y - width / 2, GFUI_ALIGN_HR_VB, object, gfuiScrollPlus);
					break;
				case GFUI_ALIGN_HR_VT:
					gfuiScrollButtonCreate(scr, "data/img/arrow-up.png", "data/img/arrow-up-pushed.png", x, y, GFUI_ALIGN_HR_VT, object, gfuiScrollMinus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-down.png", "data/img/arrow-down-pushed.png", x, y - width, GFUI_ALIGN_HR_VB, object, gfuiScrollPlus);
					break;
				case GFUI_ALIGN_HC_VB:
					gfuiScrollButtonCreate(scr, "data/img/arrow-up.png", "data/img/arrow-up-pushed.png", x, y + width, GFUI_ALIGN_HC_VT, object, gfuiScrollMinus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-down.png", "data/img/arrow-down-pushed.png", x, y, GFUI_ALIGN_HC_VB, object, gfuiScrollPlus);
					break;
				case GFUI_ALIGN_HC_VC:
					gfuiScrollButtonCreate(scr, "data/img/arrow-up.png", "data/img/arrow-up-pushed.png", x, y + width / 2, GFUI_ALIGN_HC_VT, object, gfuiScrollMinus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-down.png", "data/img/arrow-down-pushed.png", x, y - width / 2, GFUI_ALIGN_HC_VB, object, gfuiScrollPlus);
					break;
				case GFUI_ALIGN_HC_VT:
					gfuiScrollButtonCreate(scr, "data/img/arrow-up.png", "data/img/arrow-up-pushed.png", x, y, GFUI_ALIGN_HC_VT, object, gfuiScrollMinus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-down.png", "data/img/arrow-down-pushed.png", x, y - width, GFUI_ALIGN_HC_VB, object, gfuiScrollPlus);
					break;
				case GFUI_ALIGN_HL_VB:
					gfuiScrollButtonCreate(scr, "data/img/arrow-up.png", "data/img/arrow-up-pushed.png", x, y + width, GFUI_ALIGN_HL_VT, object, gfuiScrollMinus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-down.png", "data/img/arrow-down-pushed.png", x, y, GFUI_ALIGN_HL_VB, object, gfuiScrollPlus);
					break;
				case GFUI_ALIGN_HL_VC:
					gfuiScrollButtonCreate(scr, "data/img/arrow-up.png", "data/img/arrow-up-pushed.png", x, y + width / 2, GFUI_ALIGN_HL_VT, object, gfuiScrollMinus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-down.png", "data/img/arrow-down-pushed.png", x, y - width / 2, GFUI_ALIGN_HL_VB, object, gfuiScrollPlus);
					break;
				case GFUI_ALIGN_HL_VT:
					gfuiScrollButtonCreate(scr, "data/img/arrow-up.png", "data/img/arrow-up-pushed.png", x, y, GFUI_ALIGN_HL_VT, object, gfuiScrollMinus);
					gfuiScrollButtonCreate(scr, "data/img/arrow-down.png", "data/img/arrow-down-pushed.png", x, y - width, GFUI_ALIGN_HL_VB, object, gfuiScrollPlus);
					break;
				default:
					break;
			}
			break;
		default:
			break;
	}


	gfuiAddObject(screen, object);
	GfuiScrollBarPosSet(scr, object->id, min, max, len, start);
	return object->id;
}

/** Get the current position of a scroll bar.
    @ingroup	gui
    @param[in] scr Screen containing the scroll bar.
    @param[in] id Identifier of a scroll-bar widget (type is not checked).
    @return Current position, or -1 if id is unknown. If negative positions are
        allowed, -1 may also be a valid position.
 */
int
GfuiScrollBarPosGet(void *scr, int id)
{
	tGfuiObject		*object;
	tGfuiScrollBar	*scrollbar;

	object = gfuiGetObject(scr, id);

	if(object == NULL) {
		return -1;
	}

	scrollbar = &(object->u.scrollbar);

	return scrollbar->pos;
}

/** Set new values for position.
    @ingroup	gui
    @param[in,out] scr Screen containing the scroll bar.
    @param[in] id Identifier of a scroll-bar widget (type is not checked).
    @param[in] min New minimum position, inclusive.
    @param[in] max New maximum position, inclusive; must be at least min.
    @param[in] len New visible length metadata.
    @param[in] start New position; caller must keep it within [min, max].
    @note Values are stored without clamping or invoking onScroll. Unknown
        identifiers are ignored.
 */
void
GfuiScrollBarPosSet(void *scr, int id, int min, int max, int len, int start)
{
	tGfuiObject		*object;
	tGfuiScrollBar	*scrollbar;

	object = gfuiGetObject(scr, id);

	if(object == NULL) {
		return;
	}

	scrollbar = &(object->u.scrollbar);

	scrollbar->min = min;
	scrollbar->max = max;
	scrollbar->len = len;
	scrollbar->pos = start;
}

void
gfuiReleaseScrollbar(tGfuiObject *curObject)
{
	free(curObject);
}
