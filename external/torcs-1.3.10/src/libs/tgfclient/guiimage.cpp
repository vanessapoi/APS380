/***************************************************************************

    file                 : guiimage.cpp
    created              : Wed May  1 10:29:28 CEST 2002
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
    		GUI Images management
    @author	<a href=mailto:eric.espie@torcs.org>Eric Espie</a>
*/

#include <stdlib.h>
#ifdef WIN32
#include <windows.h>
#endif
#include <tgfclient.h>
#include "gui.h"


/** Create a new static image.
    This kind of image is not clickable.
    @ingroup	gui
	@param[in,out] scr Screen receiving the image.
	@param[in] x Left edge in GUI coordinates.
	@param[in] y Bottom edge in GUI coordinates.
	@param[in] w Display width in GUI units (independent of PNG dimensions).
	@param[in] h Display height in GUI units (independent of PNG dimensions).
	@param[in] name PNG filename, or NULL for an initially empty widget.
	@return	Image Id
		<br>-1 Allocation or invalid screen error
	@note	If @p name cannot be loaded, an empty image widget is still created
		so a later GfuiStaticImageSet() call can recover.
	@note Source dimensions must be supported by the current OpenGL context;
		legacy contexts may require power-of-two dimensions. Images need not be square.
*/
int GfuiStaticImageCreate(void *scr, int x, int y, int w, int h, char *name)
{
	tGfuiImage *image;
	tGfuiObject *object;
	tGfuiScreen *screen = (tGfuiScreen*)scr;

	if (!screen) {
		return -1;
	}

	object = (tGfuiObject*)calloc(1, sizeof(tGfuiObject));
	if (!object) {
		return -1;
	}
	object->widget = GFUI_IMAGE;
	object->focusMode = GFUI_FOCUS_NONE;
	object->visible = 1;
	object->id = screen->curId++;

	image = &(object->u.image);
	image->texture = name ? GfImgReadTex(name) : 0;

	object->xmin = x;
	object->xmax = x + w;
	object->ymin = y;
	object->ymax = y + h;

	gfuiAddObject(screen, object);

	return object->id;
}

/** Replace an image by another one.
    @ingroup	gui
	@param[in,out] scr Screen containing the image.
	@param[in] id Image-widget identifier.
	@param[in] name PNG filename, or NULL to clear the image.
	@note	If @p name cannot be loaded, the image is left empty until a later
		successful GfuiStaticImageSet() call.
	@note Display bounds are unchanged. Unknown identifiers and other widget
		types are ignored. Source dimension requirements are as in GfuiStaticImageCreate.
*/
void GfuiStaticImageSet(void *scr, int id, char *name)
{
	tGfuiObject *curObject;
	tGfuiScreen *screen = (tGfuiScreen*)scr;
	tGfuiImage *image;

	curObject = screen->objects;
	if (curObject != NULL) {
		do {
			curObject = curObject->next;
			if (curObject->id == id) {
				if (curObject->widget == GFUI_IMAGE) {
					image = &(curObject->u.image);
					GfImgFreeTex(image->texture);
					image->texture = name ? GfImgReadTex(name) : 0;
				}
			return;
			}
		} while (curObject != screen->objects);
	}
}

void
gfuiReleaseImage(tGfuiObject *obj)
{
	tGfuiImage	*image;

	image = &(obj->u.image);
	GfImgFreeTex(image->texture);
	free(obj);
}

void
gfuiDrawImage(tGfuiObject *obj)
{
    tGfuiImage	*image;

    image = &(obj->u.image);
    if (!image->texture) {
        return;
    }

    glEnable(GL_TEXTURE_2D);
    glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE);
    glBindTexture(GL_TEXTURE_2D, image->texture);

    glBegin(GL_TRIANGLE_STRIP);
    {
	glColor4f(1.0, 1.0, 1.0, 0.0);
	glTexCoord2f(0.0, 0.0); glVertex2f(obj->xmin, obj->ymin);
	glTexCoord2f(0.0, 1.0); glVertex2f(obj->xmin, obj->ymax);
	glTexCoord2f(1.0, 0.0); glVertex2f(obj->xmax, obj->ymin);
	glTexCoord2f(1.0, 1.0); glVertex2f(obj->xmax, obj->ymax);
    }
    glEnd();
    glBindTexture(GL_TEXTURE_2D, 0);
    glDisable(GL_TEXTURE_2D);
}
