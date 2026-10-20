/***************************************************************************

    file                 : guiedit.cpp
    created              : Mon Apr 24 10:23:28 CEST 2000
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

/** @file   
    		GUI Edit Box Management.
    @author	<a href=mailto:torcs@free.fr>Eric Espie</a>
*/

#include <stdlib.h>
#ifdef WIN32
#include <windows.h>
#endif
#include <tgfclient.h>
#include "gui.h"
#include "guifont.h"

void
gfuiEditboxInit(void)
{
}

/** Add an edit box to a screen.
    @ingroup	gui
    @param[in,out] scr		Screen receiving the edit box
    @param[in] text		Initial text, copied and truncated to maxlen bytes
    @param[in] font		Font id
    @param[in] x		X position on screen
    @param[in] y		Y position on screen (0 = bottom)
    @param[in] width		Content width; zero reserves the width of maxlen 'W' glyphs
    @param[in] maxlen		Capacity in bytes excluding NUL; zero uses strlen(text)
    @param[in] onFocus		Focus callback function
    @param[in] onFocusLost	Focus Lost callback function
    @param[in] margin		Horizontal margin on each side in GUI units (default 10)
    @return	Editbox Id
		<br>-1 Error
 */
int
GfuiEditboxCreateAction(void *scr, const char *text, int font, int x, int y, int width, int maxlen,
		  const tGfuiAction &onFocus, const tGfuiAction &onFocusLost, int margin)
{
	tGfuiEditbox *editbox;
	tGfuiLabel *label;
	tGfuiObject *object;
	tGfuiScreen *screen = (tGfuiScreen*)scr;


	object = (tGfuiObject*)calloc(1, sizeof(tGfuiObject));
	object->widget = GFUI_EDITBOX;
	object->focusMode = GFUI_FOCUS_MOUSE_CLICK;
	object->id = screen->curId++;
	object->visible = 1;
	
	editbox = &(object->u.editbox);
	editbox->state = GFUI_BTN_RELEASED;
	editbox->onFocusAction = gfuiCreateAction(onFocus);
	editbox->onFocusLostAction = gfuiCreateAction(onFocusLost);

	editbox->bgColor[0] = &(GfuiColor[GFUI_BGBTNDISABLED][0]);
	editbox->bgColor[1] = &(GfuiColor[GFUI_BGBTNENABLED][0]);
	editbox->bgColor[2] = &(GfuiColor[GFUI_BGBTNCLICK][0]);
	editbox->bgFocusColor[0] = &(GfuiColor[GFUI_BGBTNDISABLED][0]);
	editbox->bgFocusColor[1] = &(GfuiColor[GFUI_BGBTNFOCUS][0]);
	editbox->bgFocusColor[2] = &(GfuiColor[GFUI_BGBTNCLICK][0]);
	editbox->fgColor[0] = &(GfuiColor[GFUI_BTNDISABLED][0]);
	editbox->fgColor[1] = &(GfuiColor[GFUI_BTNENABLED][0]);
	editbox->fgColor[2] = &(GfuiColor[GFUI_BTNCLICK][0]);
	editbox->fgFocusColor[0] = &(GfuiColor[GFUI_BTNDISABLED][0]);
	editbox->fgFocusColor[1] = &(GfuiColor[GFUI_BTNFOCUS][0]);
	editbox->fgFocusColor[2] = &(GfuiColor[GFUI_BTNCLICK][0]);
	editbox->cursorColor[0] = &(GfuiColor[GFUI_EDITCURSORCLR][0]);
	editbox->cursorColor[1] = &(GfuiColor[GFUI_EDITCURSORCLR][1]);
	editbox->cursorColor[2] = &(GfuiColor[GFUI_EDITCURSORCLR][2]);
	

	label = &(editbox->label);
	if (maxlen == 0) maxlen = strlen(text);
	label->text = (char*)calloc(1, maxlen+1);
	strncpy(label->text, text, maxlen);
	label->text[maxlen] = '\0';
	label->font = gfuiFont[font];
	label->maxlen = maxlen;

	if (width == 0) {
		char *buf;
		int  i;
		buf = (char*)malloc(maxlen+1);
		if (buf == NULL) return -1;	// Memory leak does not matter, this must not happen
		for (i = 0; i < maxlen; i++) buf[i] = 'W';
		buf[i] = '\0';
		width = gfuiFont[font]->getWidth((const char *)buf);
		free(buf);
	}

	label->align = GFUI_ALIGN_HL_VC;
	label->x = object->xmin = x;
	label->y = y - 2 * gfuiFont[font]->getDescender();
	object->ymin = y;
	object->xmax = x + width;
	object->ymax = y + gfuiFont[font]->getHeight() - gfuiFont[font]->getDescender();
	editbox->cursory1 = object->ymin + 2;
	editbox->cursory2 = object->ymax - 2;
	editbox->cursorx = label->x;
	
	object->xmin -= margin;
	object->xmax += margin;

	gfuiAddObject(screen, object);
	return object->id;
}

int
GfuiEditboxCreate(void *scr, const char *text, int font, int x, int y, int width, int maxlen,
		  void *userDataOnFocus, tfuiCallback onFocus, tfuiCallback onFocusLost, int margin)
{
	return GfuiEditboxCreateAction(scr, text, font, x, y, width, maxlen,
		gfuiMakeAction(userDataOnFocus, onFocus),
		gfuiMakeAction(userDataOnFocus, onFocusLost), margin);
}


/** Get the Id of the editbox focused in the current screen.
    @ingroup	gui
    @return	Editbox Id
		<br>-1 if no editbox or no screen or the focus is not on a editbox
 */
int
GfuiEditboxGetFocused(void)
{
    tGfuiObject *curObject;

    if (GfuiScreen != NULL) {
	curObject = GfuiScreen->objects;
	if (curObject != NULL) {
	    do {
		curObject = curObject->next;
		if (curObject->focus) {
		    if (curObject->widget == GFUI_EDITBOX) {
			return curObject->id;
		    }
		    return -1;
		}
	    } while (curObject != GfuiScreen->objects);
	}
    }
    return -1;
}


void
gfuiDrawEditbox(tGfuiObject *obj)
{
    tGfuiLabel		*label;
    tGfuiEditbox	*editbox;
    float		*fgColor;
    float		*bgColor;

    editbox = &(obj->u.editbox);
    if (obj->state == GFUI_DISABLE) {
	editbox->state = GFUI_BTN_DISABLE;
    } else {
	editbox->state = GFUI_BTN_RELEASED;
    }
    if (obj->focus) {
	fgColor = editbox->fgFocusColor[editbox->state];
	bgColor = editbox->bgFocusColor[editbox->state];
    } else {
	fgColor = editbox->fgColor[editbox->state];
	bgColor = editbox->bgColor[editbox->state];
    }

    glColor4fv(bgColor);
    glBegin(GL_QUADS);
    glVertex2i(obj->xmin, obj->ymin);
    glVertex2i(obj->xmin, obj->ymax);
    glVertex2i(obj->xmax, obj->ymax);
    glVertex2i(obj->xmax, obj->ymin);
    glEnd();
    
    glColor4fv(fgColor);
    glBegin(GL_LINE_STRIP);
    glVertex2i(obj->xmin, obj->ymin);
    glVertex2i(obj->xmin, obj->ymax);
    glVertex2i(obj->xmax, obj->ymax);
    glVertex2i(obj->xmax, obj->ymin);
    glVertex2i(obj->xmin, obj->ymin);
    glEnd();	
    
    label = &(editbox->label);
    glColor4fv(fgColor);
    gfuiPrintString(label->x, label->y, label->font, label->text);
    
    if ((obj->state != GFUI_DISABLE) && (obj->focus)) {
	/* draw cursor */
	glColor3fv(editbox->cursorColor[editbox->state]);
	glBegin(GL_LINES);
	glVertex2i(editbox->cursorx, editbox->cursory1);
	glVertex2i(editbox->cursorx, editbox->cursory2);
	glEnd();
    }
}


void
gfuiEditboxAction(int mouse)
{
    tGfuiObject		*object;
    tGfuiLabel		*label;
    tGfuiEditbox	*editbox;
    int			relX;
    char		buf[256];
    uint		i;

    object = GfuiScreen->hasFocus;
    if (object->state == GFUI_DISABLE) {
	return;
    }
    
    if (mouse == 2) { /* enter key */
	gfuiSelectNext(GfuiScreen);
    } else if (mouse == 0) { /* mouse down */
	editbox = &(object->u.editbox);
	label = &(editbox->label);
	/* Set the cursor position */
	relX = GfuiMouse.X - label->x;
	for (i = 0; i < strlen(label->text); i++){
	    buf[i] = label->text[i];
	    buf[i+1] = '\0';
	    if (relX < label->font->getWidth((const char *)buf)) {
		break;
	    }
	}
	editbox->cursorIdx = i;
	if (i == 0) {
	    editbox->cursorx = label->x;
	} else {
	    buf[i] = '\0';
	    editbox->cursorx = label->x + label->font->getWidth((const char *)buf);
	}
    }
}

/* recalc cursorx with cursorIdx */
static void
gfuiEditboxRecalcCursor(tGfuiObject *obj)
{
    char		buf[256];
    tGfuiEditbox	*editbox;
    tGfuiLabel		*label;

    editbox = &(obj->u.editbox);
    label = &(editbox->label);
    strncpy(buf, label->text, editbox->cursorIdx);
    buf[editbox->cursorIdx] = '\0';
    editbox->cursorx = label->x + label->font->getWidth((const char *)buf);
}


void
gfuiEditboxKey(tGfuiObject *obj, int key, int modifier)
{
    tGfuiEditbox	*editbox;
    tGfuiLabel		*label;
    char		*p1, *p2;
    int			i1, i2;

    if (obj->state == GFUI_DISABLE) {
	return;
    }

    editbox = &(obj->u.editbox);
    label = &(editbox->label);

    switch (modifier) {
    case 0:
    case GLUT_ACTIVE_SHIFT:
	switch (key) {
	case 256 + GLUT_KEY_RIGHT:
	    editbox->cursorIdx++;
	    if (editbox->cursorIdx > (int)strlen(label->text)) {
		editbox->cursorIdx--;
	    }
	    break;
	case 256 + GLUT_KEY_LEFT:
	    editbox->cursorIdx--;
	    if (editbox->cursorIdx < 0) {
		editbox->cursorIdx = 0;
	    }
	    break;
	case 256 + GLUT_KEY_HOME:
	    editbox->cursorIdx = 0;
	    break;
	case 256 + GLUT_KEY_END:
	    editbox->cursorIdx = (int)strlen(label->text);
	    break;
	case 0x7F : /* DEL */
	    if (editbox->cursorIdx < (int)strlen(label->text)) {
		p1 = &(label->text[editbox->cursorIdx]);
		p2 = &(label->text[editbox->cursorIdx+1]);
		while ( *p1 != '\0' ) {
		    *p1++ = *p2++;
		}
	    }
	    break;
	case '\b' : /* Backspace */
	    if (editbox->cursorIdx > 0) {
		p1 = &(label->text[editbox->cursorIdx-1]);
		p2 = &(label->text[editbox->cursorIdx]);
		while ( *p1 != '\0' ) {
		    *p1++ = *p2++;
		}
		editbox->cursorIdx--;
	    }
	    break;	
	}
	if (key >= ' ' && key < 127) {
	    if ((int)strlen(label->text) < label->maxlen) {
		i2 = (int)strlen(label->text) + 1;
		i1 = i2 - 1;
		while (i2 > editbox->cursorIdx) {
		    label->text[i2] = label->text[i1];
		    i1--;
		    i2--;
		}
		label->text[editbox->cursorIdx] = key;
		editbox->cursorIdx++;
	    }
	}
	break;
	
    case GLUT_ACTIVE_CTRL:
	break;

    case GLUT_ACTIVE_ALT:
	break;
    }

    gfuiEditboxRecalcCursor(obj);
}

/** Get the current text of an edit box.
    @ingroup	gui
    @param[in] scr Screen containing the edit box.
    @param[in] id Edit-box identifier.
    @return Borrowed pointer to the widget's text buffer, or NULL for an unknown
        identifier or wrong widget type. Do not free it; use GfuiEditboxSetString
        to change the text. The buffer is invalid after screen release.
 */
char *
GfuiEditboxGetString(void *scr, int id)
{
    tGfuiObject		*curObject;
    tGfuiEditbox	*editbox;
    tGfuiLabel		*label;
    
    curObject = gfuiGetObject(scr, id);
    
    if ((curObject == NULL) || (curObject->widget != GFUI_EDITBOX)) {
	return (char*)NULL;
    }

    editbox = &(curObject->u.editbox);
    label = &(editbox->label);
    
    return label->text;
}

/** Set a new string.
    @ingroup	gui
    @param[in,out] scr Screen containing the edit box.
    @param[in] id Edit-box identifier.
    @param[in] text Non-NULL text, copied and truncated to the capacity set at creation.
    @note Unknown identifiers and non-edit-box widgets are ignored. This setter
        does not invoke focus callbacks or reposition the editing cursor.
 */
void GfuiEditboxSetString(void *scr, int id, const char *text)
{
	tGfuiObject *curObject;
	tGfuiEditbox *editbox;
	tGfuiLabel *label;
	
	curObject = gfuiGetObject(scr, id);
	
	if ((curObject == NULL) || (curObject->widget != GFUI_EDITBOX)) {
		return;
	}
	
	editbox = &(curObject->u.editbox);
	label = &(editbox->label);
	
	strncpy(label->text, text, label->maxlen);
	label->text[label->maxlen] = '\0';
}


void
gfuiReleaseEditbox(tGfuiObject *curObject)
{
    tGfuiEditbox	*editbox;
    tGfuiLabel		*label;

    editbox = &(curObject->u.editbox);
    label = &(editbox->label);
    gfuiReleaseAction(editbox->onFocusAction);
    gfuiReleaseAction(editbox->onFocusLostAction);
    free(label->text);
    free(curObject);
}
