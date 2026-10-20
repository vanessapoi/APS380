/***************************************************************************

    file                 : guiscrollist.cpp
    created              : Mon Aug 23 19:22:49 CEST 1999
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
    		GUI scroll-list management.
    @author	<a href=mailto:torcs@free.fr>Eric Espie</a>
*/

#include <stdlib.h>
#include <stdio.h>
#ifdef WIN32
#include <windows.h>
#endif
#include <tgfclient.h>
#include "gui.h"
#include "guifont.h"
#include <portability.h>

void
gfuiScrListInit(void)
{
}

static void
gfuiScroll(tScrollBarInfo *sinfo)
{
	tGfuiObject		*object;
	tGfuiScrollList	*scrollist;

	object = (tGfuiObject *) sinfo->userData;
	//object = gfuiGetObject(GfuiScreen, (long)(sinfo->userData));

	if(object == NULL) {
		return;
	}

	if(object->widget != GFUI_SCROLLIST) {
		return;
	}

	scrollist = &(object->u.scrollist);

	scrollist->firstVisible = sinfo->pos;

	if((scrollist->selectedElt < scrollist->firstVisible) ||
	        (scrollist->selectedElt > scrollist->firstVisible + scrollist->nbVisible)) {
		scrollist->selectedElt = -1;
	}
}

void
gfuiScrollListNextElt(tGfuiObject *object)
{
	tGfuiScrollList	*scrollist;

	scrollist = &(object->u.scrollist);

	scrollist->selectedElt++;

	if(scrollist->selectedElt == scrollist->nbElts) {
		scrollist->selectedElt = scrollist->nbElts - 1;
		return;
	}

	gfuiRunAction(scrollist->onSelectAction);

	if(scrollist->selectedElt == scrollist->firstVisible + scrollist->nbVisible) {
		/* Scroll down */
		if(scrollist->firstVisible + scrollist->nbVisible < scrollist->nbElts) {
			scrollist->firstVisible++;

			if(scrollist->scrollBar) {
				GfuiScrollBarPosSet(GfuiScreen, scrollist->scrollBar, 0, MAX(scrollist->nbElts - scrollist->nbVisible, 0),
				                    scrollist->nbVisible, scrollist->firstVisible);
			}
		}
	}
}

void
gfuiScrollListPrevElt(tGfuiObject *object)
{
	tGfuiScrollList	*scrollist;

	scrollist = &(object->u.scrollist);

	scrollist->selectedElt--;

	if(scrollist->selectedElt < 0) {
		scrollist->selectedElt = 0;
		return;
	}

	gfuiRunAction(scrollist->onSelectAction);

	if(scrollist->selectedElt < scrollist->firstVisible) {
		/* Scroll down */
		if(scrollist->firstVisible > 0) {
			scrollist->firstVisible--;

			if(scrollist->scrollBar) {
				GfuiScrollBarPosSet(GfuiScreen, scrollist->scrollBar, 0, MAX(scrollist->nbElts - scrollist->nbVisible, 0),
				                    scrollist->nbVisible, scrollist->firstVisible);
			}
		}
	}
}


/** Create a new scroll list.
    @ingroup	gui
    @param[in,out] scr Screen receiving the list.
    @param[in] font GFUI_FONT_* identifier.
    @param[in] x Left edge in GUI coordinates.
    @param[in] y Bottom edge in GUI coordinates.
    @param[in] align Retained for compatibility; currently ignored.
    @param[in] width Width in GUI units.
    @param[in] height Height in GUI units; should fit at least one text row.
    @param[in] scrollBarPos Position of the scrollbar:
			<br>GFUI_SB_NONE	No scroll bar
			<br>GFUI_SB_RIGHT	Right scroll bar
			<br>GFUI_SB_LEFT	Left scroll bar
    @param[in] onSelect Action on user selection; may be empty. Programmatic
        insertion, extraction and reordering do not call it.
    @return	Scroll List Id
 */
int
GfuiScrollListCreateAction(void *scr, int font, int x, int y, int align, int width, int height,
                     int scrollBarPos, const tGfuiAction &onSelect)
{
	tGfuiScrollList	*scrollist;
	tGfuiObject		*object;
	tGfuiScreen		*screen = (tGfuiScreen *)scr;

	object = (tGfuiObject *)calloc(1, sizeof(tGfuiObject));
	object->widget = GFUI_SCROLLIST;
	object->focusMode = GFUI_FOCUS_MOUSE_MOVE;
	object->id = screen->curId++;
	object->visible = 1;

	object->xmin = x;
	object->xmax = x + width;
	object->ymin = y;
	object->ymax = y + height;

	scrollist = &(object->u.scrollist);
	scrollist->fgColor[0] = &(GfuiColor[GFUI_FGSCROLLIST][0]);
	scrollist->bgColor[0] = &(GfuiColor[GFUI_BGSCROLLIST][0]);
	scrollist->fgSelectColor[0] = &(GfuiColor[GFUI_FGSELSCROLLIST][0]);
	scrollist->bgSelectColor[0] = &(GfuiColor[GFUI_BGSELSCROLLIST][0]);
	scrollist->font = gfuiFont[font];
	scrollist->nbVisible = height / (scrollist->font->getDescender() + scrollist->font->getHeight());
	scrollist->selectedElt = -1;
	scrollist->onSelectAction = gfuiCreateAction(onSelect);

	switch(scrollBarPos) {
		case GFUI_SB_NONE:
			break;
		case GFUI_SB_RIGHT:
			scrollist->scrollBar = GfuiScrollBarCreate(scr, x + width, y, GFUI_ALIGN_HL_VB, height, GFUI_VERT_SCROLLBAR,
			                       0, 10, 10, 10, (void *)(object), gfuiScroll);
			break;
		case GFUI_SB_LEFT:
			scrollist->scrollBar = GfuiScrollBarCreate(scr, x, y, GFUI_ALIGN_HR_VB, height, GFUI_VERT_SCROLLBAR,
			                       0, 10, 10, 10, (void *)(object), gfuiScroll);
			break;
	}

	gfuiAddObject(screen, object);
	return object->id;
}

int
GfuiScrollListCreate(void *scr, int font, int x, int y, int align, int width, int height,
                     int scrollBarPos, void *userDataOnSelect, tfuiCallback onSelect)
{
	return GfuiScrollListCreateAction(scr, font, x, y, align, width, height, scrollBarPos,
		gfuiMakeAction(userDataOnSelect, onSelect));
}

static void
gfuiScrollListInsElt(tGfuiScrollList *scrollist, tGfuiListElement *elt, int index)
{
	tGfuiListElement	*cur;
	int			i;

	if(scrollist->elts == NULL) {
		scrollist->elts = elt;
		elt->next = elt;
		elt->prev = elt;
	} else {
		cur = scrollist->elts;
		i = 0;

		do {
			if(i == index) {
				break;
			}

			cur = cur->next;
			i++;
		} while(cur != scrollist->elts);

		elt->next = cur->next;
		cur->next = elt;
		elt->prev = cur;
		elt->next->prev = elt;

		if((cur == scrollist->elts) && (index != 0)) {
			scrollist->elts = elt;
		}
	}
}

static tGfuiListElement *
gfuiScrollListRemElt(tGfuiScrollList *scrollist, int index)
{
	tGfuiListElement	*cur;
	int			i;

	if(scrollist->elts == NULL) {
		return (tGfuiListElement *)NULL;
	}

	cur = scrollist->elts;
	i = 0;

	do {
		cur = cur->next;

		if(i == index) {
			break;
		}

		i++;
	} while(cur != scrollist->elts);

	cur->next->prev = cur->prev;
	cur->prev->next = cur->next;

	if(cur == scrollist->elts) {
		if(cur->next == cur) {
			scrollist->elts = (tGfuiListElement *)NULL;
		} else {
			scrollist->elts = cur->prev;
		}
	}

	return cur;
}

/** Get the selected element from the scroll list.
    @ingroup	gui
    @param[in] scr Screen containing the list.
    @param[in] Id Scroll-list identifier.
    @param[out] userData Non-NULL address receiving the stored user-data pointer;
        unchanged on failure.
    @return Borrowed name pointer supplied at insertion, or NULL if the widget
        is not a list, is empty, or has no selected element. Ownership is unchanged.
 */
char *
GfuiScrollListGetSelectedElement(void *scr, int Id, void **userData)
{
	tGfuiObject		*object;
	tGfuiScrollList	*scrollist;
	tGfuiListElement	*elt;
	char		*name;
	int			i;


	object = gfuiGetObject(scr, Id);

	if(object == NULL) {
		return (char *)NULL;
	}

	if(object->widget != GFUI_SCROLLIST) {
		return (char *)NULL;
	}

	scrollist = &(object->u.scrollist);

	if(scrollist->selectedElt == -1) {
		return (char *)NULL;
	}

	if(scrollist->elts == NULL) {
		return (char *)NULL;
	}

	elt = scrollist->elts;
	i = 0;

	do {
		elt = elt->next;

		if(i == scrollist->selectedElt) {
			break;
		}

		i++;
	} while(elt != scrollist->elts);

	name = elt->name;
	*userData = elt->userData;

	return name;
}

/** Get the specified element from the scroll list.
    @ingroup	gui
    @param[in] scr Screen containing the list.
    @param[in] Id Scroll-list identifier.
    @param[in] index Zero-based element index.
    @param[out] userData Non-NULL address receiving the stored user-data pointer;
        unchanged on failure.
    @return Borrowed name pointer supplied at insertion, or NULL for an invalid
        widget or index. Ownership is unchanged.
 */
char *
GfuiScrollListGetElement(void *scr, int Id, int index, void **userData)
{
	tGfuiObject		*object;
	tGfuiScrollList	*scrollist;
	tGfuiListElement	*elt;
	char		*name;
	int			i;

	object = gfuiGetObject(scr, Id);

	if(object == NULL) {
		return (char *)NULL;
	}

	if(object->widget != GFUI_SCROLLIST) {
		return (char *)NULL;
	}

	scrollist = &(object->u.scrollist);

	if((index < 0) || (index > scrollist->nbElts - 1)) {
		return (char *)NULL;
	}

	if(scrollist->elts == NULL) {
		return (char *)NULL;
	}

	elt = scrollist->elts;
	i = 0;

	do {
		elt = elt->next;

		if(i == index) {
			break;
		}

		i++;
	} while(elt != scrollist->elts);

	name = elt->name;
	*userData = elt->userData;

	return name;
}

/** Extract the selected element from the scroll list (removed).
    @ingroup	gui
    @param[in,out] scr Screen containing the list to modify.
    @param[in] Id Scroll-list identifier.
    @param[out] userData Non-NULL address receiving the stored user-data pointer;
        unchanged on failure.
    @return Original name pointer, or NULL for an invalid widget or no selection.
    @note Removes the list entry but does not free its name or user data. The
        caller retains ownership of both. No selection callback is invoked.
 */
char *
GfuiScrollListExtractSelectedElement(void *scr, int Id, void **userData)
{
	tGfuiObject		*object;
	tGfuiScrollList	*scrollist;
	tGfuiListElement	*elt;
	char		*name;

	object = gfuiGetObject(scr, Id);

	if(object == NULL) {
		return (char *)NULL;
	}

	if(object->widget != GFUI_SCROLLIST) {
		return (char *)NULL;
	}

	scrollist = &(object->u.scrollist);

	if(scrollist->selectedElt == -1) {
		return (char *)NULL;
	}

	elt = gfuiScrollListRemElt(scrollist, scrollist->selectedElt);

	scrollist->nbElts--;

	if(scrollist->selectedElt > scrollist->nbElts - 1) {
		scrollist->selectedElt--;
	}

	name = elt->name;
	*userData = elt->userData;
	free(elt);

	return name;
}

/** Extract the specified element from the scroll list.
    @ingroup	gui
    @param[in,out] scr Screen containing the list to modify.
    @param[in] Id Scroll-list identifier.
    @param[in] index Zero-based element index.
    @param[out] userData Non-NULL address receiving the stored user-data pointer;
        unchanged on failure.
    @return Original name pointer, or NULL for an invalid widget or index.
    @note Removes the list entry but does not free its name or user data. The
        caller retains ownership of both. No selection callback is invoked.
 */
char *
GfuiScrollListExtractElement(void *scr, int Id, int index, void **userData)
{
	tGfuiObject		*object;
	tGfuiScrollList	*scrollist;
	tGfuiListElement	*elt;
	char		*name;

	object = gfuiGetObject(scr, Id);

	if(object == NULL) {
		return (char *)NULL;
	}

	if(object->widget != GFUI_SCROLLIST) {
		return (char *)NULL;
	}

	scrollist = &(object->u.scrollist);

	if((index < 0) || (index > scrollist->nbElts - 1)) {
		return (char *)NULL;
	}

	elt = gfuiScrollListRemElt(scrollist, index);

	scrollist->nbElts--;

	if(scrollist->selectedElt > scrollist->nbElts - 1) {
		scrollist->selectedElt--;
	}

	name = elt->name;
	*userData = elt->userData;
	free(elt);

	return name;
}


/** Insert an element in a scroll list.
    @ingroup	gui
    @param[in,out] scr Screen containing the list to modify.
    @param[in] Id Scroll-list identifier.
    @param[in] element Non-NULL display name, borrowed without copying. Keep it
        valid while the entry remains in the list.
    @param[in] index Zero-based insertion position; negative or beyond the last
        entry appends. Zero inserts before the first entry.
    @param[in] userData Borrowed application data associated with the entry; may be NULL.
    @return 0 on success, -1 if Id does not identify a scroll list.
    @note Neither extraction nor screen release frees element or userData.
 */
int
GfuiScrollListInsertElement(void *scr, int Id, char *element, int index, void *userData)
{
	tGfuiObject		*object;
	tGfuiScrollList	*scrollist;
	tGfuiListElement	*elt;

	object = gfuiGetObject(scr, Id);

	if(object == NULL) {
		return -1;
	}

	if(object->widget != GFUI_SCROLLIST) {
		return -1;
	}

	scrollist = &(object->u.scrollist);

	elt = (tGfuiListElement *)calloc(1, sizeof(tGfuiListElement));
	elt->name = element;
	elt->label = elt->name;  /* TODO LENGTH !!!!!*/
	elt->userData = userData;
	elt->index = index;

	gfuiScrollListInsElt(scrollist, elt, index);

	scrollist->nbElts++;

	if(scrollist->scrollBar) {
		GfuiScrollBarPosSet(scr, scrollist->scrollBar, 0, MAX(scrollist->nbElts - scrollist->nbVisible, 0),
		                    scrollist->nbVisible, scrollist->firstVisible);
	}

	return 0;
}


void
gfuiDrawScrollist(tGfuiObject *obj)
{
	tGfuiScrollList	*scrollist;
	tGfuiListElement	*elt;
	float		*fgColor;
	float		*bgColor;
	const int BUFSIZE = 256;
	char		buf[BUFSIZE];
	int			w, h, x, y;
	int			index;

	scrollist = &(obj->u.scrollist);

	fgColor = scrollist->fgColor[0];
	bgColor = scrollist->bgColor[0];

	if(bgColor[3] != 0.0) {
		glBegin(GL_QUADS);
		glColor4fv(bgColor);
		glVertex2i(obj->xmin, obj->ymin);
		glVertex2i(obj->xmin, obj->ymax);
		glVertex2i(obj->xmax, obj->ymax);
		glVertex2i(obj->xmax, obj->ymin);
		glEnd();
	}

	glBegin(GL_LINE_STRIP);
	glColor4fv(fgColor);
	glVertex2i(obj->xmin, obj->ymin);
	glVertex2i(obj->xmin, obj->ymax);
	glVertex2i(obj->xmax, obj->ymax);
	glVertex2i(obj->xmax, obj->ymin);
	glVertex2i(obj->xmin, obj->ymin);
	glEnd();


	h = scrollist->font->getDescender() + scrollist->font->getHeight();
	x = obj->xmin;
	y = obj->ymax;
	index = 0;
	elt = scrollist->elts;

	if(elt != NULL) {
		if(scrollist->nbElts < 100) {
			snprintf(buf, BUFSIZE, " 00 ");
		} else {
			snprintf(buf, BUFSIZE, " 000 ");
		}

		w = scrollist->font->getWidth((const char *)buf);

		do {
			elt = elt->next;

			if(index < scrollist->firstVisible) {
				index++;
				continue;
			}

			if(index == scrollist->selectedElt) {
				glColor4fv(scrollist->fgSelectColor[0]);
			} else {
				glColor4fv(scrollist->fgColor[0]);
			}

			index++;

			if(index > (scrollist->firstVisible + scrollist->nbVisible)) {
				break;
			}

			y -= h;
			snprintf(buf, BUFSIZE, " %d", index);
			gfuiPrintString(x, y, scrollist->font, buf);
			gfuiPrintString(x + w, y, scrollist->font, elt->label);
		} while(elt != scrollist->elts);
	}


}

void
gfuiScrollListDeselectAll(void)
{
	tGfuiObject *curObject;

	curObject = GfuiScreen->objects;

	if(curObject != NULL) {
		do {
			curObject = curObject->next;

			if(curObject->widget == GFUI_SCROLLIST) {
				curObject->u.scrollist.selectedElt = -1;
			}
		} while(curObject != GfuiScreen->objects);
	}

}


void
gfuiScrollListAction(int mouse)
{
	tGfuiObject		*object;
	tGfuiScrollList	*scrollist;
	int			relY;

	if(mouse == 0) {
		/* button down */
		gfuiScrollListDeselectAll();
		object = GfuiScreen->hasFocus;
		scrollist = &(object->u.scrollist);
		relY = object->ymax - GfuiMouse.Y;
		relY = scrollist->firstVisible + relY / (scrollist->font->getDescender() + scrollist->font->getHeight()) + 1;

		if(relY > scrollist->nbElts) {
			scrollist->selectedElt = -1;
			return;
		}

		scrollist->selectedElt = relY - 1;

		gfuiRunAction(scrollist->onSelectAction);
	}
}

/** Move the selected element within the scroll list.
    @ingroup	gui
    @param[in,out] scr Screen containing the list to modify.
    @param[in] Id Scroll-list identifier.
    @param[in] delta Signed displacement in entries; negative moves toward the start.
    @return 0 on success, -1 for an invalid widget, no selection, or a destination
        outside the list. The moved entry remains selected; no callback is invoked.
 */
int
GfuiScrollListMoveSelectedElement(void *scr, int Id, int delta)
{
	tGfuiObject		*object;
	tGfuiScrollList	*scrollist;
	int			newPos;
	tGfuiListElement	*elt;

	object = gfuiGetObject(scr, Id);

	if(object == NULL) {
		return -1;
	}

	if(object->widget != GFUI_SCROLLIST) {
		return -1;
	}

	scrollist = &(object->u.scrollist);

	if(scrollist->selectedElt == -1) {
		return -1;
	}

	newPos = scrollist->selectedElt + delta;

	if((newPos < 0) || (newPos > scrollist->nbElts - 1)) {
		return -1;
	}

	elt = gfuiScrollListRemElt(scrollist, scrollist->selectedElt);

	gfuiScrollListInsElt(scrollist, elt, newPos);

	scrollist->selectedElt = newPos;

	if(scrollist->selectedElt == scrollist->firstVisible + scrollist->nbVisible) {
		/* Scroll down */
		if(scrollist->firstVisible + scrollist->nbVisible < scrollist->nbElts) {
			scrollist->firstVisible++;

			if(scrollist->scrollBar) {
				GfuiScrollBarPosSet(GfuiScreen, scrollist->scrollBar, 0, MAX(scrollist->nbElts - scrollist->nbVisible, 0),
				                    scrollist->nbVisible, scrollist->firstVisible);
			}
		}
	} else if(scrollist->selectedElt < scrollist->firstVisible) {
		/* Scroll down */
		if(scrollist->firstVisible > 0) {
			scrollist->firstVisible--;

			if(scrollist->scrollBar) {
				GfuiScrollBarPosSet(GfuiScreen, scrollist->scrollBar, 0, MAX(scrollist->nbElts - scrollist->nbVisible, 0),
				                    scrollist->nbVisible, scrollist->firstVisible);
			}
		}
	}

	return 0;
}


void
gfuiReleaseScrollist(tGfuiObject *curObject)
{
	tGfuiScrollList	*scrollist;
	tGfuiListElement	*elt;

	scrollist = &(curObject->u.scrollist);
	gfuiReleaseAction(scrollist->onSelectAction);

	while((elt = gfuiScrollListRemElt(scrollist, 0)) != NULL) {
		free(elt);
	}

	free(curObject);
}
