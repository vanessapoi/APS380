/***************************************************************************
                                guiobject.cpp                      
                             -------------------                                         
    created              : Fri Aug 13 22:25:06 CEST 1999
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


#ifdef WIN32
#include <windows.h>
#endif
#include <tgfclient.h>
#include "gui.h"

void
gfuiObjectInit(void)
{
}

void 
gfuiPrintString(int x, int y, GfuiFontClass *font, const char *string)
{
    glEnable(GL_TEXTURE_2D);
    glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE);
    glEnable(GL_ALPHA_TEST);
    glAlphaFunc(GL_GREATER, 0.1) ;
    font->output(x, y, string);
    glDisable(GL_ALPHA_TEST);
    glDisable(GL_TEXTURE_2D);
}

void GfuiPrintString(const char *text, float *fgColor, int font, int x, int y, int align)
{
	glEnable(GL_TEXTURE_2D);
	glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE);
	glEnable(GL_ALPHA_TEST);
	glAlphaFunc(GL_GREATER, 0.1) ;
	glColor4fv(fgColor);
	switch(align&0xF0) {
		case 0x00 /* LEFT */:
			gfuiFont[font]->output(x, y, text);
			break;
		case 0x10 /* CENTER */:
			gfuiFont[font]->output(x - gfuiFont[font]->getWidth(text) / 2, y, text);
			break;
		case 0x20 /* RIGHT */:
			gfuiFont[font]->output(x - gfuiFont[font]->getWidth(text), y, text);
			break;
	}
	glDisable(GL_ALPHA_TEST);
	glDisable(GL_TEXTURE_2D);
}

int GfuiFontHeight(int font)
{
    return gfuiFont[font]->getHeight();
}

int GfuiFontWidth(int font, const char *text)
{
    return gfuiFont[font]->getWidth(text);
}

void
GfuiDrawCursor()
{
    float xf = (float)(GfuiMouse.X);
    float yf = (float)(GfuiMouse.Y);

#define SCALE 1.3
    
    glColor4fv(GfuiScreen->mouseColor[0]) ;
    glBegin(GL_TRIANGLES);
    glVertex2f(xf, yf);
    glVertex2f(xf + 4.8 * SCALE, yf - 10.4 * SCALE);
    glVertex2f(xf + 6.4 * SCALE, yf - 6.4 * SCALE);
    glEnd();

    glBegin(GL_QUADS);
    glVertex2f(xf + 5.6 * SCALE, yf - 6.4 * SCALE);
    glVertex2f(xf + 6 * SCALE, yf - 6 * SCALE);
    glVertex2f(xf + 12.4 * SCALE, yf - 12.4 * SCALE);
    glVertex2f(xf + 12 * SCALE, yf - 12.8 * SCALE);
    glEnd();

    glColor4fv(GfuiScreen->mouseColor[1]) ;
    glBegin(GL_TRIANGLES);
    glVertex2f(xf, yf) ;
    glVertex2f(xf + 10.4 * SCALE, yf - 4.8 * SCALE);
    glVertex2f(xf + 6.4 * SCALE, yf - 6.4 * SCALE);
    glEnd();

    glBegin(GL_QUADS);
    glVertex2f(xf + 6 * SCALE, yf - 6 * SCALE);
    glVertex2f(xf + 6.4 * SCALE, yf - 4.8 * SCALE);
    glVertex2f(xf + 12.8 * SCALE, yf - 12 * SCALE);
    glVertex2f(xf + 12.4 * SCALE, yf - 12.4 * SCALE);  
    glEnd();

}

void
GfuiDraw(tGfuiObject *obj)
{
    if (obj->visible) {
	switch (obj->widget){
	case GFUI_LABEL:
	    gfuiDrawLabel(obj);
	    break;
	
	case GFUI_BUTTON:
	    gfuiDrawButton(obj);
	    break;

	case GFUI_GRBUTTON:
	    gfuiDrawGrButton(obj);
	    break;

	case GFUI_SCROLLIST:
	    gfuiDrawScrollist(obj);
	    break;
	
	case GFUI_EDITBOX:
	    gfuiDrawEditbox(obj);
	    break;

	case GFUI_IMAGE:
	    gfuiDrawImage(obj);
	    break;
	}
    }
}


static int
gfuiMouseIn(tGfuiObject *obj)
{
    if ((GfuiMouse.X >= obj->xmin) &&
	(GfuiMouse.X <= obj->xmax) &&
	(GfuiMouse.Y >= obj->ymin) &&
	(GfuiMouse.Y <= obj->ymax)) {
	return 1;
    }
    return 0;
}

/** Remove focus from the active screen's current widget.
    @ingroup	gui
    Does nothing if no widget has focus. Buttons and edit boxes are reset to
    their released state and their focus-lost action is invoked synchronously.
    Requires an active screen.
*/
void
GfuiUnSelectCurrent(void)
{
    tGfuiButton		*button;
    tGfuiEditbox	*editbox;
    tGfuiGrButton	*grbutton;
    tGfuiObject		*obj;

    obj = GfuiScreen->hasFocus;
    if (obj == NULL) {
	return;
    }
    GfuiScreen->hasFocus = (tGfuiObject*)NULL;
    obj->focus = 0;
    switch (obj->widget) {
    case GFUI_BUTTON:
	button = &(obj->u.button);
	button->state = GFUI_BTN_RELEASED;
	gfuiRunAction(button->onFocusLostAction);
	break;
    case GFUI_GRBUTTON:
	grbutton = &(obj->u.grbutton);
	grbutton->state = GFUI_BTN_RELEASED;
	gfuiRunAction(grbutton->onFocusLostAction);
	break;
    case GFUI_EDITBOX:
	editbox = &(obj->u.editbox);
	editbox->state = GFUI_BTN_RELEASED;	
	gfuiRunAction(editbox->onFocusLostAction);
	break;
    }
}

static void
gfuiLoseFocus(tGfuiObject *obj)
{
    tGfuiButton		*button;
    tGfuiEditbox	*editbox;
    tGfuiGrButton	*grbutton;

    GfuiScreen->hasFocus = (tGfuiObject*)NULL;
    obj->focus = 0;
    switch (obj->widget) {
    case GFUI_BUTTON:
	button = &(obj->u.button);
	button->state = GFUI_BTN_RELEASED;
	gfuiRunAction(button->onFocusLostAction);
	break;
    case GFUI_GRBUTTON:
	grbutton = &(obj->u.grbutton);
	grbutton->state = GFUI_BTN_RELEASED;
	gfuiRunAction(grbutton->onFocusLostAction);
	break;
    case GFUI_EDITBOX:
	editbox = &(obj->u.editbox);
	editbox->state = GFUI_BTN_RELEASED;	
	gfuiRunAction(editbox->onFocusLostAction);
	break;
    }
}

static void
gfuiSetFocus(tGfuiObject *obj)
{
	if (obj->state == GFUI_DISABLE &&
		obj->widget != GFUI_BUTTON &&
		obj->widget != GFUI_GRBUTTON) {
		return;
	}

	tGfuiButton		*button;
    tGfuiEditbox	*editbox;
    tGfuiGrButton	*grbutton;
    
    if (GfuiScreen->hasFocus != NULL) {
	gfuiLoseFocus(GfuiScreen->hasFocus);
    }
    GfuiScreen->hasFocus = obj;
    obj->focus = 1;
    switch (obj->widget) {
    case GFUI_BUTTON:
	button = &(obj->u.button);
	gfuiRunAction(button->onFocusAction);
	break;
    case GFUI_GRBUTTON:
	grbutton = &(obj->u.grbutton);
	gfuiRunAction(grbutton->onFocusAction);
	break;
    case GFUI_EDITBOX:
	editbox = &(obj->u.editbox);
	gfuiRunAction(editbox->onFocusAction);
	break;
    }
}

void
gfuiUpdateFocus(void)
{
    tGfuiObject *curObject;
    
    curObject = GfuiScreen->hasFocus;
    if (curObject != NULL) {
	if (gfuiMouseIn(curObject)) {
	    return; /* focus has not changed */
	}
	if (curObject->focusMode != GFUI_FOCUS_MOUSE_CLICK) {
	    gfuiLoseFocus(GfuiScreen->hasFocus);
	    GfuiScreen->hasFocus = (tGfuiObject*)NULL;
	}
    }
    
    /* Search for a new focused object */
    curObject = GfuiScreen->objects;
    if (curObject != NULL) {
	do {
	    curObject = curObject->next;
	    if ((curObject->visible == 0) ||
		(curObject->focusMode == GFUI_FOCUS_NONE) ||
		((curObject->focusMode == GFUI_FOCUS_MOUSE_CLICK) && (GfuiScreen->mouse == 0))) {
		continue;
	    }
	    if (gfuiMouseIn(curObject)) {
		gfuiSetFocus(curObject);
		break;
	    }
	} while (curObject != GfuiScreen->objects);
    }
}

void
gfuiSelectNext(void * /* dummy */)
{
    tGfuiObject *startObject;
    tGfuiObject *curObject;
    
    startObject = GfuiScreen->hasFocus;
    if (startObject == NULL) {
	startObject = GfuiScreen->objects;
    }
    if (startObject == NULL) {
	return;
    }
    curObject = startObject;
    do {
	switch (curObject->widget) {
	case GFUI_SCROLLIST:
	    gfuiScrollListNextElt(curObject);
	    break;
	    
	default:
	    curObject = curObject->next;
	    if ((curObject->focusMode != GFUI_FOCUS_NONE) &&
		(curObject->state != GFUI_DISABLE) &&
		(curObject->visible)) {
		gfuiSetFocus(curObject);
		return;
	    }
	    break;
	}
    } while (curObject != startObject);    
}

void
gfuiSelectPrev(void * /* dummy */)
{
    tGfuiObject *startObject;
    tGfuiObject *curObject;
    
    startObject = GfuiScreen->hasFocus;
    if (startObject == NULL) {
	startObject = GfuiScreen->objects;
	if (startObject == NULL) {
	    return;
	}
	startObject = startObject->next;
    }
    curObject = startObject;
    do {
	switch (curObject->widget) {
	case GFUI_SCROLLIST:
	    gfuiScrollListPrevElt(curObject);
	    break;

	default:
	    curObject = curObject->prev;
	    if ((curObject->focusMode != GFUI_FOCUS_NONE) &&
		(curObject->state != GFUI_DISABLE) &&
		(curObject->visible)) {
		gfuiSetFocus(curObject);
		return;
	    }
	    break;
	}
    } while (curObject != startObject);
}

void 
gfuiSelectId(void *scr, int id)
{
    tGfuiObject *curObject;
    tGfuiScreen	*screen = (tGfuiScreen*)scr;
    
    curObject = screen->objects;
    if (curObject != NULL) {
	do {
	    curObject = curObject->next;
	    if (curObject->id == id) {
		gfuiSetFocus(curObject);
		break;
	    }
	} while (curObject != screen->objects);
    }
}

/** Set/unset the visibility attribute of an object.
    @param[in,out] scr Screen containing the widget.
    @param[in] id Widget identifier.
    @param[in] visible GFUI_VISIBLE or GFUI_INVISIBLE.
    @return 0 on success, -1 for an unknown identifier or invalid visibility value.
    @ingroup	gui
 */
int
GfuiVisibilitySet(void *scr, int id, int visible)
{
    tGfuiObject *curObject;
    
    curObject = gfuiGetObject(scr, id);
    if (curObject == NULL) {
	return -1;
    }
    switch(visible) {
    case GFUI_VISIBLE:
	curObject->visible = GFUI_VISIBLE;
	break;
    case GFUI_INVISIBLE:
	curObject->visible = GFUI_INVISIBLE;
	break;
    default:
	return -1;
    }
    return 0;
}

/** Enable / Disable an object
    @param[in,out] scr Screen containing the widget.
    @param[in] id Widget identifier.
    @param[in] flag GFUI_ENABLE or GFUI_DISABLE (use the constants, not a boolean).
    @return 0 on success, -1 for an unknown identifier or invalid flag.
    @ingroup	gui
 */
int 
GfuiEnable(void *scr, int id, int flag)
{
    tGfuiObject *curObject;

    curObject = gfuiGetObject(scr, id);
    if (curObject == NULL) {
	return -1;
    }
    switch(flag) {
    case GFUI_ENABLE:
	curObject->state = GFUI_ENABLE;
	break;
    case GFUI_DISABLE:
	curObject->state = GFUI_DISABLE;
	break;
    default:
	return -1;
    }
    return 0;
}

void
gfuiMouseAction(int action)
{
    tGfuiObject *curObject;

    curObject = GfuiScreen->hasFocus;
    if (curObject != NULL) {
		if (curObject->state == GFUI_DISABLE) {
			return;
		}
		
		switch (curObject->widget) {
		case GFUI_BUTTON:
			gfuiButtonAction((int)action);
			break;
		case GFUI_GRBUTTON:
			gfuiGrButtonAction((int)action);
			break;
		case GFUI_SCROLLIST:
			gfuiScrollListAction((int)action);
			break;
		case GFUI_EDITBOX:
			gfuiEditboxAction((int)action);
			break;
		}
    }
}

void
gfuiAddObject(tGfuiScreen *screen, tGfuiObject *object)
{
    if (screen->objects == NULL) {
	screen->objects = object;
	object->next = object;
	object->prev = object;
    } else {
	object->next = screen->objects->next;
	object->prev = screen->objects;
	screen->objects->next = object;
	object->next->prev = object;
	screen->objects = object;
    }
}

tGfuiObject * 
gfuiGetObject(void *scr, int id)
{
    tGfuiObject *curObject;
    tGfuiScreen	*screen = (tGfuiScreen*)scr;
    
    curObject = screen->objects;
    if (curObject != NULL) {
	do {
	    curObject = curObject->next;
	    if (curObject->id == id) {
		return curObject;
	    }
	} while (curObject != screen->objects);
    }
    return (tGfuiObject *)NULL;
}


void
gfuiReleaseObject(tGfuiObject *curObject)
{
    switch (curObject->widget){
    case GFUI_LABEL:
	gfuiReleaseLabel(curObject);
	break;
	
    case GFUI_BUTTON:
	gfuiReleaseButton(curObject);
	break;
	
    case GFUI_GRBUTTON:
	gfuiReleaseGrButton(curObject);
	break;
	
    case GFUI_SCROLLIST:
	gfuiReleaseScrollist(curObject);
	break;

    case GFUI_SCROLLBAR:
	gfuiReleaseScrollbar(curObject);
	break;

    case GFUI_EDITBOX:
	gfuiReleaseEditbox(curObject);
	break;
    case GFUI_IMAGE:
	gfuiReleaseImage(curObject);
	break;
    }
}
