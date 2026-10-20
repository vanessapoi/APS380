/***************************************************************************
                        guilabel.cpp -- labels management                           
                             -------------------                                         
    created              : Fri Aug 13 22:22:12 CEST 1999
    copyright            : (C) 1999-2026 by Eric Espié, Bernhard Wymann                         
    email                : torcs@free.fr   
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
    		GUI labels management.
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
gfuiLabelInit(void)
{
}

/** Create a new label (extended version).
    @ingroup	gui
    @param[in,out] scr Screen receiving the label.
    @param[in] text Initial text, copied and truncated to maxlen bytes.
    @param[in] fgColor Four RGBA floats, copied into the label.
    @param[in] font GFUI_FONT_* identifier.
    @param[in] x Horizontal anchor in GUI coordinates.
    @param[in] y Bottom of the label in GUI coordinates.
    @param[in] align GFUI_ALIGN_HL_VB, GFUI_ALIGN_HC_VB or GFUI_ALIGN_HR_VB
        for left, centered or right alignment. Vertical alignment bits are ignored.
    @param[in] maxlen Text capacity in bytes excluding NUL; zero uses strlen(text).
    @return Label identifier, local to scr.
    @see GfuiLabelSetText, GfuiLabelSetColor
 */
int 
GfuiLabelCreateEx(void *scr, const char *text, float *fgColor, int font, int x, int y, int align, int maxlen)
{
	tGfuiLabel *label;
	tGfuiObject	*object;
	int width;
	tGfuiScreen	*screen = (tGfuiScreen*)scr;
	
	object = (tGfuiObject*)calloc(1, sizeof(tGfuiObject));
	object->widget = GFUI_LABEL;
	object->focusMode = GFUI_FOCUS_NONE;
	object->visible = 1;
	object->id = screen->curId++;
	
	if (maxlen == 0) maxlen = strlen(text);
	label = &(object->u.label);
	label->text = (char*)calloc(maxlen+1, 1);
	strncpy(label->text, text, maxlen);
	label->text[maxlen] = '\0';
	label->maxlen = maxlen;
	
	label->bgColor = screen->bgColor;
	//label->fgColor = fgColor;
	label->fgColor.setRGBA(fgColor);
	
	label->font = gfuiFont[font];
	width = gfuiFont[font]->getWidth((const char *)label->text);
	label->align = align;
	switch(align&0xF0) {
		case 0x00 /* LEFT */:
			label->x = object->xmin = x;
			label->y = y - gfuiFont[font]->getDescender();
			object->ymin = y;
			object->xmax = x + width;
			object->ymax = y + gfuiFont[font]->getHeight() - gfuiFont[font]->getDescender();
			break;
		case 0x10 /* CENTER */:
			label->x =  object->xmin = x - width / 2;
			label->y = y - gfuiFont[font]->getDescender();
			object->ymin = y;
			object->xmax = x + width / 2;
			object->ymax = y + gfuiFont[font]->getHeight() - gfuiFont[font]->getDescender();
			break;
		case 0x20 /* RIGHT */:
			label->x = object->xmin = x - width;
			label->y = y - gfuiFont[font]->getDescender();
			object->ymin = y;
			object->xmax = x;
			object->ymax = y + gfuiFont[font]->getHeight() - gfuiFont[font]->getDescender();
			break;
	}
	
	gfuiAddObject(screen, object);
	
	return object->id;
}

/** Add a label to a screen.
    @ingroup	gui
    Uses the default label color.
    @param[in,out] scr Screen receiving the label.
    @param[in] text Initial text, copied and truncated to maxlen bytes.
    @param[in] font GFUI_FONT_* identifier.
    @param[in] x Horizontal anchor in GUI coordinates.
    @param[in] y Bottom of the label in GUI coordinates.
    @param[in] align Horizontal GFUI_ALIGN_* alignment; vertical bits are ignored.
    @param[in] maxlen Text capacity in bytes excluding NUL; zero uses strlen(text).
    @return Label identifier, local to scr.
    @see GfuiLabelCreateEx, GfuiLabelSetText
 */
int
GfuiLabelCreate(void *scr, const char *text, int font, int x, int y, int align, int maxlen)
{
    return GfuiLabelCreateEx(scr, text, &(GfuiColor[GFUI_LABELCOLOR][0]), font, x, y, align, maxlen);
}

/** Add a Tip (generally associated with a button).
    @ingroup gui
    @param[in,out] scr	Screen where to add the label
    @param[in] text	Text of the label
    @param[in] maxlen	Maximum length of the label string (0 for the text length)
    @return	label Id
    @see	GfuiLabelSetText
 */
int
GfuiTipCreate(void *scr, const char *text, int maxlen)
{
	return GfuiLabelCreateEx(scr, text, &(GfuiColor[GFUI_TIPCOLOR][0]), GFUI_FONT_SMALL, 320, 15, GFUI_ALIGN_HC_VB, maxlen);
}

/** Add a Title to the screen.
    @ingroup	gui
    Places a centered GFUI_FONT_BIG label at (320, 440) in GUI coordinates.
    @param[in,out] scr Screen receiving the title.
    @param[in] text Initial title, copied.
    @param[in] maxlen Text capacity in bytes excluding NUL; zero uses strlen(text).
    @return	label Id
    @see GfuiLabelSetText
 */
int
GfuiTitleCreate(void *scr, const char *text, int maxlen)
{
	return GfuiLabelCreateEx(scr, text, &(GfuiColor[GFUI_TITLECOLOR][0]), GFUI_FONT_BIG, 320, 440, GFUI_ALIGN_HC_VB, maxlen);
}

void
gfuiSetLabelText(tGfuiObject *curObject, tGfuiLabel *label, const char *text)
{
	int		pw, w;
	
	if (!text) {
		return;
	}

	pw = label->font->getWidth((const char *)label->text);
	strncpy(label->text, text, label->maxlen);
	label->text[label->maxlen] = '\0';
	w = label->font->getWidth((const char *)label->text);
	
	switch(label->align&0xF0) {
		case 0x00 /* LEFT */:
			curObject->xmax = label->x + w;
			break;
		case 0x10 /* CENTER */:
			label->x = curObject->xmin = label->x + pw / 2 - w / 2;
			curObject->xmax = curObject->xmax - pw / 2 + w / 2;
			break;
		case 0x20 /* RIGHT */:
			label->x = curObject->xmin = curObject->xmax - w;
			break;
	}
}

/** Change the text of a label.
    @ingroup	gui
    @param[in,out] scr Screen containing the label.
    @param[in] id Label identifier.
    @param[in] text New text, copied and truncated to the capacity set at creation;
        NULL leaves the label unchanged.
    @note Unknown identifiers and non-label widgets are ignored.
    @see GfuiLabelCreate, GfuiLabelCreateEx
 */
void
GfuiLabelSetText(void *scr, int id, const char *text)
{
	tGfuiObject *curObject;
	tGfuiScreen	*screen = (tGfuiScreen*)scr;
	
	curObject = screen->objects;
	if (curObject != NULL) {
		do {
			curObject = curObject->next;
			if (curObject->id == id) {
				if (curObject->widget == GFUI_LABEL) {
					gfuiSetLabelText(curObject, &(curObject->u.label), text);
				}
				return;
			}
		} while (curObject != screen->objects);
	}
}

/** Change the color of a label.
    @ingroup	gui
    @param[in,out] scr Screen containing the label.
    @param[in] id Label identifier.
    @param[in] color Four RGBA floats, copied into the label.
    @note Unknown identifiers and non-label widgets are ignored.
    @see GfuiLabelCreateEx
 */
void
GfuiLabelSetColor(void *scr, int id, float *color)
{
    tGfuiObject *curObject;
    tGfuiScreen	*screen = (tGfuiScreen*)scr;
    
    curObject = screen->objects;
    if (curObject != NULL) {
	do {
	    curObject = curObject->next;
	    if (curObject->id == id) {
		if (curObject->widget == GFUI_LABEL) {
		     curObject->u.label.fgColor.setRGBA(color);
		}
		return;
	    }
	} while (curObject != screen->objects);
    }
}


void
gfuiDrawLabel(tGfuiObject *obj)
{
	tGfuiLabel	*label;

	label = &(obj->u.label);
	if (label->bgColor[3] != 0.0) {
		glColor4fv(label->bgColor);
		glBegin(GL_QUADS);
		glVertex2i(obj->xmin, obj->ymin);
		glVertex2i(obj->xmin, obj->ymax);
		glVertex2i(obj->xmax, obj->ymax);
		glVertex2i(obj->xmax, obj->ymin);
		glEnd();
	}
	glColor4fv(label->fgColor.getRGBA());
	gfuiPrintString(label->x, label->y, label->font, label->text);
}

void
gfuiReleaseLabel(tGfuiObject *obj)
{
	tGfuiLabel *label;

	label = &(obj->u.label);

	free(label->text);
	free(obj);
}
