/***************************************************************************
                               gui.cpp -- gui                   
                             -------------------                                         
    created              : Fri Aug 13 22:01:33 CEST 1999
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
    		This API is used to manage all the menu screens.
*/

#include <stdlib.h>
#include <stdio.h>
#include <time.h>

#include <tgfclient.h>
#include "gui.h"

#include <portability.h>

tGfuiScreen	*GfuiScreen;	/* current screen */
static int	GfuiMouseVisible = 1;
tMouseInfo	GfuiMouse;

int		GfuiMouseHW = 0;

float		GfuiColor[GFUI_COLORNB][4];

static int	ScrW, ScrH, ViewW, ViewH;

static tdble DelayRepeat;
static double LastTimeClick;
#define REPEAT1	1.0
#define REPEAT2 0.2

tGfuiAction
gfuiMakeAction(void *userData, tfuiCallback callback)
{
	if (callback == NULL) {
		return tGfuiAction();
	}

	return [userData, callback] {
		callback(userData);
	};
}

tGfuiAction *
gfuiCreateAction(const tGfuiAction &action)
{
	if (!action) {
		return NULL;
	}

	return new tGfuiAction(action);
}

void
gfuiRunAction(const tGfuiAction *action)
{
	if (action != NULL) {
		tGfuiAction runAction = *action;
		runAction();
	}
}

void
gfuiReleaseAction(tGfuiAction *action)
{
	delete action;
}

static void
gfuiColorInit(void)
{
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];
	
	void *hdle;
	int  i, j;
	const char *rgba[4] = {GFSCR_ATTR_RED, GFSCR_ATTR_GREEN, GFSCR_ATTR_BLUE, GFSCR_ATTR_ALPHA};
	const char *clr[GFUI_COLORNB] = {
		GFSCR_ELT_BGCOLOR, GFSCR_ELT_TITLECOLOR, GFSCR_ELT_BGBTNFOCUS, GFSCR_ELT_BGBTNCLICK,
		GFSCR_ELT_BGBTNENABLED, GFSCR_ELT_BGBTNDISABLED, GFSCR_ELT_BTNFOCUS, GFSCR_ELT_BTNCLICK,
		GFSCR_ELT_BTNENABLED, GFSCR_ELT_BTNDISABLED, GFSCR_ELT_LABELCOLOR, GFSCR_ELT_TIPCOLOR,
		GFSCR_ELT_MOUSECOLOR1, GFSCR_ELT_MOUSECOLOR2, GFSCR_ELT_HELPCOLOR1, GFSCR_ELT_HELPCOLOR2,
		GFSCR_ELT_BGSCROLLIST, GFSCR_ELT_SCROLLIST, GFSCR_ELT_BGSELSCROLLIST, GFSCR_ELT_SELSCROLLIST,
		GFSCR_ELT_EDITCURSORCLR
	};
	
	snprintf(buf, BUFSIZE, "%s%s", GetLocalDir(), GFSCR_CONF_FILE);
	hdle = GfParmReadFile(buf, GFPARM_RMODE_STD | GFPARM_RMODE_CREAT);

	for (i = 0; i < GFUI_COLORNB; i++) {
		for (j = 0; j < 4; j++) {
			snprintf(buf, BUFSIZE, "%s/%s/%s", GFSCR_SECT_MENUCOL, GFSCR_LIST_COLORS, clr[i]);
			GfuiColor[i][j] = GfParmGetNum(hdle, buf, rgba[j], (char*)NULL, 1.0);
		}
	}

	GfParmReleaseHandle(hdle);
	
	/* Remove the X11/Windows cursor  */
	if (!GfuiMouseHW) {
		glutSetCursor(GLUT_CURSOR_NONE);
	}
	
	GfuiMouseVisible = 1;
}


void
gfuiInit(void)
{
	gfuiButtonInit();
	gfuiHelpInit();
	gfuiLabelInit();
	gfuiObjectInit();
	gfuiColorInit();
	gfuiLoadFonts();

/*     glutSetKeyRepeat(GLUT_KEY_REPEAT_OFF); */
}


/** GLUT display callback that performs no drawing or buffer swap.
    Install this when redisplay events should not render a GUI screen.
    @ingroup	gui
 */
void
GfuiDisplayNothing(void)
{
}

/** Process held-mouse-button repeat actions on the active screen.
    Suitable as a GLUT idle callback. GfuiScreenActivate clears the idle callback;
    install this explicitly if repetition is wanted. Requires an active screen.
    @ingroup	gui
 */
void
GfuiIdle(void)
{
	double		curtime = GfTimeClock();
	
	if ((curtime - LastTimeClick) > DelayRepeat) {
		DelayRepeat = REPEAT2;
		LastTimeClick = curtime;
		if (GfuiScreen->mouse == 1) {
			/* button down */
			gfuiUpdateFocus();
			gfuiMouseAction(0);
			glutPostRedisplay();
		}
	}
}

/** Draw the active GUI screen and swap the GLUT buffers.
    Draws the background, widgets and software cursor. Installed as the display
    callback by GfuiScreenActivate for normal screens. Changes OpenGL state and
    matrices; requires an active normal screen and a current rendering context.
    @ingroup	gui
*/
void
GfuiDisplay(void)
{
	tGfuiObject	*curObj;
	
	glDisable(GL_DEPTH_TEST);
	glDisable(GL_LIGHTING);
	glDisable(GL_TEXTURE_2D);
	glDisable(GL_CULL_FACE);
	glDisable(GL_ALPHA_TEST);
	glEnable(GL_BLEND);
	glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
	
	GfScrGetSize(&ScrW, &ScrH, &ViewW, &ViewH);
	
	glViewport((ScrW-ViewW) / 2, (ScrH-ViewH) / 2, ViewW, ViewH);
	glMatrixMode(GL_PROJECTION);
	glLoadIdentity();
	gluOrtho2D(0, GfuiScreen->width, 0, GfuiScreen->height);
	glMatrixMode(GL_MODELVIEW);  
	glLoadIdentity();
	
	if (GfuiScreen->bgColor[3] != 0.0) {
		glClearColor(GfuiScreen->bgColor[0],
					GfuiScreen->bgColor[1],
					GfuiScreen->bgColor[2],
					GfuiScreen->bgColor[3]);
		glClear(GL_COLOR_BUFFER_BIT);
	}
	
	if (glIsTexture(GfuiScreen->bgImage) == GL_TRUE) {
		GLfloat tx1 = 0.0f, tx2 = 1.0f, ty1 = 0.0f, ty2 = 1.0f;
		
		// All background images are 16:10 images which are stored as quadratic images.
		// Compute texture coordinates to ensure proper unskewed/unstretched display of
		// image content.
		tdble rfactor = (16.0f*ViewH)/(10.0f*ViewW);
		if (rfactor >= 1.0f) {
			// Aspect ratio of view is smaller than 16:10, "cut off" sides
			tdble tdx = (1.0f-1.0f/rfactor)/2.0f;
			tx1 += tdx;
			tx2 -= tdx;
		} else {
			// Aspect ratio of view is larger than 16:10, "cut off" top and bottom
			tdble tdy = (1.0f-rfactor)/2.0f;
			ty1 += tdy;
			ty2 -= tdy;
		}

		glDisable(GL_BLEND);
		glEnable(GL_TEXTURE_2D);
		glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE);
		glColor3f(0.0, 0.0, 1.0);
		glBindTexture(GL_TEXTURE_2D, GfuiScreen->bgImage);
		glBegin(GL_QUADS);
		glTexCoord2f(tx1, ty1); glVertex3f(0.0, 0.0, 0.0);
		glTexCoord2f(tx1, ty2); glVertex3f(0.0, GfuiScreen->height, 0.0);
		glTexCoord2f(tx2, ty2); glVertex3f(GfuiScreen->width, GfuiScreen->height, 0.0);
		glTexCoord2f(tx2, ty1); glVertex3f(GfuiScreen->width, 0.0, 0.0);
		glEnd();
		glDisable(GL_TEXTURE_2D);
		glEnable(GL_BLEND);
	}
	
	curObj = GfuiScreen->objects;
	if (curObj) {
		do {
			curObj = curObj->next;
			GfuiDraw(curObj);
		} while (curObj != GfuiScreen->objects);
	}
	
	if (!GfuiMouseHW && GfuiMouseVisible && GfuiScreen->mouseAllowed) {
		GfuiDrawCursor();
	}

	glDisable(GL_BLEND);
	glutSwapBuffers();
}

/** Disallow the software mouse cursor on the active screen.
    Does not hide the operating system's hardware cursor or disable mouse input.
    @ingroup	gui
*/
void
GfuiMouseHide(void)
{
    GfuiScreen->mouseAllowed = 0;
}

/** Allow the software mouse cursor on the active screen.
    Actual drawing also depends on the global visibility and hardware-cursor flags.
    @ingroup	gui
*/
void
GfuiMouseShow(void)
{
    GfuiScreen->mouseAllowed = 1;
}

/** Force the hardware mouse pointer
    @ingroup	ctrl
*/
void
GfuiMouseSetHWPresent(void)
{
    GfuiMouseHW = 1;
}

static void
gfuiKeyboard(unsigned char key, int /* x */, int /* y */)
{
	tGfuiKey	*curKey;
	int		modifier;
	tGfuiObject	*obj;
	
	modifier = glutGetModifiers();
	
	/* user preempt key */
	if (GfuiScreen->onKeyAction && GfuiScreen->onKeyAction(key, modifier, GFUI_KEY_DOWN)) {
		return;
	}
	
	/* now see the user's defined keys */
	if (GfuiScreen->userKeys != NULL) {
		curKey = GfuiScreen->userKeys;
		do {
			curKey = curKey->next;
			if ((curKey->key == key) && ((curKey->modifier == 0) || (curKey->modifier & modifier) != 0)) {
				gfuiRunAction(curKey->onPressAction);
				break;
			}
		} while (curKey != GfuiScreen->userKeys);
	}
	
	obj = GfuiScreen->hasFocus;
	if (obj != NULL) {
		switch (obj->widget) {
			case GFUI_EDITBOX:
				gfuiEditboxKey(obj, (int)key, modifier);
				break;
		}
	}
	glutPostRedisplay();
}

static void
gfuiSpecial(int key, int /* x */, int /* y */)
{
	tGfuiKey	*curKey;
	int		modifier;
	tGfuiObject	*obj;
	
	modifier = glutGetModifiers();
	
	/* user preempt key */
	if (GfuiScreen->onSKeyAction && GfuiScreen->onSKeyAction(key, modifier, GFUI_KEY_DOWN)) {
		return;
	}
	
	/* now see the user's defined keys */
	if (GfuiScreen->userSpecKeys != NULL) {
		curKey = GfuiScreen->userSpecKeys;
		do {
			curKey = curKey->next;
			if ((curKey->specialkey == key) && ((curKey->modifier == 0) || (curKey->modifier & modifier) != 0)) {
				gfuiRunAction(curKey->onPressAction);
				break;
			}
		} while (curKey != GfuiScreen->userSpecKeys);
	}

	obj = GfuiScreen->hasFocus;
	if (obj != NULL) {
		switch (obj->widget) {
		case GFUI_EDITBOX:
			gfuiEditboxKey(obj, key + 256, modifier);
			break;
		}
	}
	glutPostRedisplay();
}

static void
gfuiKeyboardUp(unsigned char key, int /* x */, int /* y */)
{
	tGfuiKey	*curKey;
	int		modifier;
	
	modifier = glutGetModifiers();
	
	/* user preempt key */
	if (GfuiScreen->onKeyAction && GfuiScreen->onKeyAction(key, modifier, GFUI_KEY_UP)) {
		return;
	}
	
	/* now see the user's defined keys */
	if (GfuiScreen->userKeys != NULL) {
		curKey = GfuiScreen->userKeys;
		do {
			curKey = curKey->next;
			if ((curKey->key == key) && ((curKey->modifier == 0) || (curKey->modifier & modifier) != 0)) {
				gfuiRunAction(curKey->onReleaseAction);
				break;
			}
		} while (curKey != GfuiScreen->userKeys);
	}
	
	glutPostRedisplay();
}

static void
gfuiSpecialUp(int key, int /* x */, int /* y */)
{
	tGfuiKey	*curKey;
	int		modifier;
	
	modifier = glutGetModifiers();
	
	/* user preempt key */
	if (GfuiScreen->onSKeyAction && GfuiScreen->onSKeyAction(key, modifier, GFUI_KEY_UP)) {
		return;
	}
	
	/* now see the user's defined keys */
	if (GfuiScreen->userSpecKeys != NULL) {
		curKey = GfuiScreen->userSpecKeys;
		do {
			curKey = curKey->next;
			if ((curKey->specialkey == key) && ((curKey->modifier == 0) || (curKey->modifier & modifier) != 0)) {
				gfuiRunAction(curKey->onReleaseAction);
				break;
			}
		} while (curKey != GfuiScreen->userSpecKeys);
	}
	
	glutPostRedisplay();
}

/** Get the GUI's current mouse state.
    @ingroup	gui
    @return Borrowed pointer to the internal mouse state; do not free it.
        X and Y use GUI coordinates. The three button entries follow GLUT's
        left/middle/right indices and contain 1 when pressed, 0 when released.
*/
tMouseInfo *GfuiMouseInfo(void)
{
	return &GfuiMouse;
}

/** Set the mouse position
    @ingroup	gui
    @param[in] x Horizontal position in GLUT window pixels, measured from the left.
    @param[in] y Vertical position in GLUT window pixels, measured from the top.
    @note These are not the logical coordinates returned by GfuiMouseInfo.
*/
void GfuiMouseSetPos(int x, int y)
{
	glutWarpPointer(x, y);
}


static void
gfuiMouse(int button, int state, int x, int y)
{
	// Check array range of button array!
	if (button > -1 && button < 3) {
		GfuiMouse.X = (x - (ScrW - ViewW)/2) * (int)GfuiScreen->width / ViewW;
		GfuiMouse.Y = (ViewH - y + (ScrH - ViewH)/2) * (int)GfuiScreen->height / ViewH;
	
		GfuiMouse.button[button] = 1 - state;
	
		DelayRepeat = REPEAT1;
		LastTimeClick = GfTimeClock();
		if (state == GLUT_DOWN) {
			if (button == GLUT_RIGHT_BUTTON) {
				GfuiScreen->mouse = 0;
				/* GfuiMouseVisible = 1 - GfuiMouseVisible; */
				gfuiUpdateFocus();
			} else {
				GfuiScreen->mouse = 1;
				gfuiUpdateFocus();
				gfuiMouseAction(0);
			}
		} else {
			GfuiScreen->mouse = 0;
			gfuiUpdateFocus();
			if (button != GLUT_RIGHT_BUTTON) {
				gfuiMouseAction(1);
			}
		}
		glutPostRedisplay();
	}
}

static void
gfuiMotion(int x, int y)
{
	GfuiMouse.X = (x - (ScrW - ViewW)/2) * (int)GfuiScreen->width / ViewW;
	GfuiMouse.Y = (ViewH - y + (ScrH - ViewH)/2) * (int)GfuiScreen->height / ViewH;
	gfuiUpdateFocus();
	gfuiMouseAction(1 - GfuiScreen->mouse);
	glutPostRedisplay();
	DelayRepeat = REPEAT1;
}

static void
gfuiPassiveMotion(int x, int y)
{
	GfuiMouse.X = (x - (ScrW - ViewW)/2) * (int)GfuiScreen->width / ViewW;
	GfuiMouse.Y = (ViewH - y + (ScrH - ViewH)/2) * (int)GfuiScreen->height / ViewH;
	gfuiUpdateFocus();
	glutPostRedisplay();
}

/** Tell if the screen is active or not.
    @ingroup	gui
    @param[in] screen Screen handle to compare with the current screen.
    @return	1 if active and 0 if not.
 */
int
GfuiScreenIsActive(void *screen)
{
	return (GfuiScreen == screen);
}

/** Activate a screen and make it current.
    @ingroup	gui
    @param[in,out] screen Screen or callback hook to activate.
    @note Calls the previous screen's deactivation action, installs GUI GLUT
        callbacks, and calls the new screen's activation action. The previous
        screen is not released. Normal screens are displayed immediately.
 */
void
GfuiScreenActivate(void *screen)
{
	if (GfuiScreen) {
		gfuiRunAction(GfuiScreen->onDeactivateAction);
	}
	
	GfuiScreen = (tGfuiScreen*)screen;
	
	glutKeyboardFunc(gfuiKeyboard);
	glutSpecialFunc(gfuiSpecial);
	glutKeyboardUpFunc(gfuiKeyboardUp);
	glutSpecialUpFunc(gfuiSpecialUp);
	glutMouseFunc(gfuiMouse);
	glutMotionFunc(gfuiMotion);
	glutPassiveMotionFunc(gfuiPassiveMotion);
	glutIdleFunc((void(*)(void))NULL);
	
	if (GfuiScreen->onlyCallback == 0) {
		if (GfuiScreen->hasFocus == NULL) {
			gfuiSelectNext(NULL);
		}
		glutDisplayFunc(GfuiDisplay);
	} else {
		glutDisplayFunc(GfuiDisplayNothing);
	}
	
	gfuiRunAction(GfuiScreen->onActivateAction);
	
	if (GfuiScreen->onlyCallback == 0) {
		GfuiDisplay();
		glutPostRedisplay();
	}
}


/** Activate a screen and make it current plus release the current screen.
    @ingroup	gui
    @param[in,out] screen New screen to activate; must differ from the current screen.
    @note The old screen and its widgets are released, invalidating their handles.
 */
void
GfuiScreenReplace(void *screen)
{
	tGfuiScreen	*oldScreen = GfuiScreen;

	if (oldScreen) {
		GfuiScreenRelease(oldScreen);
	}
	GfuiScreenActivate(screen);
}

/** Deactivate the current screen.
    @ingroup	gui
    Calls its deactivation action and removes GUI input callbacks without
    releasing the screen. Requires an active screen.
 */
void
GfuiScreenDeactivate(void)
{
	gfuiRunAction(GfuiScreen->onDeactivateAction);
	
	GfuiScreen = (tGfuiScreen*)NULL;
	
	glutKeyboardFunc((void(*)(unsigned char,int,int))NULL);
	glutSpecialFunc((void(*)(int,int,int))NULL);
	glutKeyboardUpFunc((void(*)(unsigned char,int,int))NULL);
	glutSpecialUpFunc((void(*)(int,int,int))NULL);
	glutMouseFunc((void(*)(int,int,int,int))NULL);
	glutMotionFunc((void(*)(int,int))NULL);
	glutPassiveMotionFunc((void(*)(int,int))NULL);
	glutIdleFunc((void(*)(void))NULL);
	glutDisplayFunc(GfuiDisplayNothing);
}

/** Create a new screen.
    @ingroup	gui
    @return Inactive screen handle with default background and mouse enabled.
        Release it with GfuiScreenRelease.
 */
void *
GfuiScreenCreate(void)
{
	tGfuiScreen	*screen;
	
	screen = (tGfuiScreen*)calloc(1, sizeof(tGfuiScreen));
	
	screen->width = 640.0;
	screen->height = 480.0;

	screen->bgColor = (float*)calloc(4, sizeof(float));
	int i;
	for(i = 0; i < 4; i++) {
		screen->bgColor[i] = GfuiColor[GFUI_BGCOLOR][i];
	}

	screen->mouseColor[0] = &(GfuiColor[GFUI_MOUSECOLOR1][0]);
	screen->mouseColor[1] = &(GfuiColor[GFUI_MOUSECOLOR2][0]);
	screen->mouseAllowed = 1;
	
	return (void*)screen;
}

/** Create a screen.
    @ingroup	gui
    @param[in] bgColor Four RGBA floats, copied; NULL selects the default color.
    @param[in] onActivate Action called on activation; may be empty.
    @param[in] onDeactivate Action called on deactivation; may be empty.
    @param[in] mouseAllowed Nonzero to allow the mouse cursor to be displayed.
    @return Inactive screen handle; release it with GfuiScreenRelease.
 */
void *
GfuiScreenCreateExAction(float *bgColor,
		   const tGfuiAction &onActivate,
		   const tGfuiAction &onDeactivate,
		   int mouseAllowed)
{
	int		i;
	tGfuiScreen	*screen;
	
	screen = (tGfuiScreen*)calloc(1, sizeof(tGfuiScreen));
	
	screen->width = 640.0;
	screen->height = 480.0;
	
	screen->bgColor = (float*)calloc(4, sizeof(float));
	for(i = 0; i < 4; i++) {
		if (bgColor != NULL) {
			screen->bgColor[i] = bgColor[i];
		} else {
			screen->bgColor[i] = GfuiColor[GFUI_BGCOLOR][i];
		}
	}

	screen->mouseColor[0] = &(GfuiColor[GFUI_MOUSECOLOR1][0]);
	screen->mouseColor[1] = &(GfuiColor[GFUI_MOUSECOLOR2][0]);
	screen->onActivateAction = gfuiCreateAction(onActivate);
	screen->onDeactivateAction = gfuiCreateAction(onDeactivate);
	
	screen->mouseAllowed = mouseAllowed;
	
	return (void*)screen;
}

void *
GfuiScreenCreateEx(float *bgColor,
		   void *userDataOnActivate, tfuiCallback onActivate,
		   void *userDataOnDeactivate, tfuiCallback onDeactivate,
		   int mouseAllowed)
{
	return GfuiScreenCreateExAction(bgColor,
		gfuiMakeAction(userDataOnActivate, onActivate),
		gfuiMakeAction(userDataOnDeactivate, onDeactivate),
		mouseAllowed);
}

/** Release the given screen.
    @ingroup	gui
    @param[in,out] scr Screen to destroy; the handle is invalid after this call.
    @note An active screen is deactivated first. Widgets, textures, key bindings
        and stored actions are released; borrowed user data is not freed.
 */
void
GfuiScreenRelease(void *scr)
{
	tGfuiObject *curObject;
	tGfuiObject *nextObject;
	tGfuiKey *curKey;
	tGfuiKey *nextKey;
	tGfuiScreen *screen = (tGfuiScreen*)scr;

	if (GfuiScreen == screen) {
		GfuiScreenDeactivate();
	}

	if (glIsTexture(screen->bgImage) == GL_TRUE) {
		glDeleteTextures(1, &screen->bgImage);
	}

	if (screen->bgColor != NULL) {
		free(screen->bgColor);
		screen->bgColor = NULL;
	}
	gfuiReleaseAction(screen->onActivateAction);
	gfuiReleaseAction(screen->onDeactivateAction);

	curObject = screen->objects;
	if (curObject != NULL) {
		do {
			nextObject = curObject->next;
			gfuiReleaseObject(curObject);
			curObject = nextObject;
		} while (curObject != screen->objects);
	}

	curKey = screen->userKeys;
	if (curKey != NULL) {
		do {
			nextKey = curKey->next;
			free(curKey->name);
			free(curKey->descr);
			gfuiReleaseAction(curKey->onPressAction);
			gfuiReleaseAction(curKey->onReleaseAction);
			free(curKey);
			curKey = nextKey;
		} while (curKey != screen->userKeys);
	}
	curKey = screen->userSpecKeys;
	if (curKey != NULL) {
		do {
			nextKey = curKey->next;
			free(curKey->name);
			free(curKey->descr);
			gfuiReleaseAction(curKey->onPressAction);
			gfuiReleaseAction(curKey->onReleaseAction);
			free(curKey);
			curKey = nextKey;
		} while (curKey != screen->userSpecKeys);
	}
	free(screen);
}

/** Create a callback hook.
    @ingroup	gui
    @param[in] onActivate Action called by GfuiScreenActivate; may be empty.
    @return Callback-only hook handle; release it with GfuiHookRelease.
    @note A hook runs an activation action without drawing a menu or containing widgets.
 */
void *
GfuiHookCreateAction(const tGfuiAction &onActivate)
{
	tGfuiScreen	*screen;
	
	screen = (tGfuiScreen*)calloc(1, sizeof(tGfuiScreen));
	screen->onActivateAction = gfuiCreateAction(onActivate);
	screen->onlyCallback = 1;
	
	return (void*)screen;
}

void *
GfuiHookCreate(void *userDataOnActivate, tfuiCallback onActivate)
{
	return GfuiHookCreateAction(gfuiMakeAction(userDataOnActivate, onActivate));
}

/** Release the given hook.
    @ingroup	gui
    @param[in,out] hook Inactive callback hook to destroy; invalid after this call.
    @pre Deactivate the hook or activate another screen first. Unlike
        GfuiScreenRelease, this function does not deactivate the current screen.
 */
void
GfuiHookRelease(void *hook)
{
	tGfuiScreen *screen = (tGfuiScreen*)hook;
	gfuiReleaseAction(screen->onActivateAction);
	gfuiReleaseAction(screen->onDeactivateAction);
	free(hook);
}

void
GfuiKeyEventRegister(void *scr, tfuiKeyCallback onKeyAction)
{
	tGfuiScreen	*screen = (tGfuiScreen*)scr;
	
	screen->onKeyAction = onKeyAction;
}


void
GfuiSKeyEventRegister(void *scr, tfuiSKeyCallback onSKeyAction)
{
	tGfuiScreen	*screen = (tGfuiScreen*)scr;
	
	screen->onSKeyAction = onSKeyAction;
}

void
GfuiKeyEventRegisterCurrent(tfuiKeyCallback onKeyAction)
{
	GfuiScreen->onKeyAction = onKeyAction;
}


void
GfuiSKeyEventRegisterCurrent(tfuiSKeyCallback onSKeyAction)
{
	GfuiScreen->onSKeyAction = onSKeyAction;
}


/** Add a Keyboard callback to a screen.
    @ingroup	gui
    @param[in,out] scr Screen receiving the binding.
    @param[in] key Ordinary character key code (not a GLUT special key).
    @param[in] descr Help-screen description, copied; NULL means empty text.
    @param[in] onKeyPressed Action on key press; may be empty.
    @param[in] onKeyReleased Action on key release; may be empty.
    @note Adds a binding, rather than replacing an existing binding for the key.
 */
void
GfuiAddKeyAction(void *scr, unsigned char key, const char *descr, const tGfuiAction &onKeyPressed, const tGfuiAction &onKeyReleased)
{
	tGfuiKey	*curKey;
	tGfuiScreen	*screen = (tGfuiScreen*)scr;
	const int BUFSIZE = 16;
	char buf[BUFSIZE];
	
	curKey = (tGfuiKey*)calloc(1, sizeof(tGfuiKey));
	curKey->key = key;
	curKey->onPressAction = gfuiCreateAction(onKeyPressed);
	curKey->onReleaseAction = gfuiCreateAction(onKeyReleased);

	if (descr == NULL) {
		curKey->descr = strdup("");
	} else {
		curKey->descr = strdup(descr);
	}

	switch(key){
		case 8:
			curKey->name = strdup("backspace");
			break;
		case 9:
			curKey->name = strdup("tab");
			break;
		case 13:
			curKey->name = strdup("enter");
			break;
		case 27:
			curKey->name = strdup("esc");
			break;
		case ' ':
			curKey->name = strdup("space");
			break;
		default:
			snprintf(buf, BUFSIZE, "%c", key);
			curKey->name = strdup(buf);
			break;
	}
	
	if (screen->userKeys == NULL) {
		screen->userKeys = curKey;
		curKey->next = curKey;
	} else {
		curKey->next = screen->userKeys->next;
		screen->userKeys->next = curKey;
	}
}

void
GfuiAddKey(void *scr, unsigned char key, const char *descr, void *userData, tfuiCallback onKeyPressed, tfuiCallback onKeyReleased)
{
	GfuiAddKeyAction(scr, key, descr, gfuiMakeAction(userData, onKeyPressed), gfuiMakeAction(userData, onKeyReleased));
}

/** Add a Keyboard callback to the current screen.
    @ingroup	gui
    @param[in] key Ordinary character key code.
    @param[in] descr Help-screen description, copied; NULL means empty text.
    @param[in] onKeyPressed Action on key press; may be empty.
    @param[in] onKeyReleased Action on key release; may be empty.
    @see GfuiAddKeyAction
 */
void
GfuiRegisterKeyAction(unsigned char key, char *descr, const tGfuiAction &onKeyPressed, const tGfuiAction &onKeyReleased)
{
	GfuiAddKeyAction(GfuiScreen, key, descr, onKeyPressed, onKeyReleased);
}

void
GfuiRegisterKey(unsigned char key, char *descr, void *userData, tfuiCallback onKeyPressed, tfuiCallback onKeyReleased)
{
	GfuiRegisterKeyAction(key, descr, gfuiMakeAction(userData, onKeyPressed), gfuiMakeAction(userData, onKeyReleased));
}

/** Add a Special Keyboard shortcut to the screen.
    (see glut for normal and special keys)
    @ingroup	gui
    @param[in,out] scr Screen receiving the binding.
    @param[in] key GLUT special-key code, such as GLUT_KEY_UP or GLUT_KEY_F1.
    @param[in] descr Help-screen description, copied; NULL means empty text.
    @param[in] onKeyPressed Action on key press; may be empty.
    @param[in] onKeyReleased Action on key release; may be empty.
    @note Adds a binding, rather than replacing an existing binding for the key.
 */
void
GfuiAddSKeyAction(void *scr, int key, const char *descr, const tGfuiAction &onKeyPressed, const tGfuiAction &onKeyReleased)
{
	tGfuiKey	*curKey;
	tGfuiScreen	*screen = (tGfuiScreen*)scr;
	
	curKey = (tGfuiKey*)calloc(1, sizeof(tGfuiKey));
	curKey->specialkey = key;
	curKey->onPressAction = gfuiCreateAction(onKeyPressed);
	curKey->onReleaseAction = gfuiCreateAction(onKeyReleased);

	if (descr == NULL) {
		curKey->descr = strdup("");
	} else {
		curKey->descr = strdup(descr);
	}

	switch(key) {
		case GLUT_KEY_F1:
			curKey->name = strdup("F1");
			break;
		case GLUT_KEY_F2:
			curKey->name = strdup("F2");
			break;
		case GLUT_KEY_F3:
			curKey->name = strdup("F3");
			break;
		case GLUT_KEY_F4:
			curKey->name = strdup("F4");
			break;
		case GLUT_KEY_F5:
			curKey->name = strdup("F5");
			break;
		case GLUT_KEY_F6:
			curKey->name = strdup("F6");
			break;
		case GLUT_KEY_F7:
			curKey->name = strdup("F7");
			break;
		case GLUT_KEY_F8:
			curKey->name = strdup("F8");
			break;
		case GLUT_KEY_F9:
			curKey->name = strdup("F9");
			break;
		case GLUT_KEY_F10:
			curKey->name = strdup("F10");
			break;
		case GLUT_KEY_F11:
			curKey->name = strdup("F11");
			break;
		case GLUT_KEY_F12:
			curKey->name = strdup("F12");
			break;
		case GLUT_KEY_LEFT:
			curKey->name = strdup("Left Arrow");
			break;
		case GLUT_KEY_UP:
			curKey->name = strdup("Up Arrow");
			break;
		case GLUT_KEY_RIGHT:
			curKey->name = strdup("Right Arrow");
			break;
		case GLUT_KEY_DOWN:
			curKey->name = strdup("Down Arrow");
			break;
		case GLUT_KEY_PAGE_UP:
			curKey->name = strdup("Page Up");
			break;
		case GLUT_KEY_PAGE_DOWN:
			curKey->name = strdup("Page Down");
			break;
		case GLUT_KEY_HOME:
			curKey->name = strdup("Home");
			break;
		case GLUT_KEY_END:
			curKey->name = strdup("End");
			break;
		case GLUT_KEY_INSERT:
			curKey->name = strdup("Insert");
			break;
	}
	
	
	if (screen->userSpecKeys == NULL) {
		screen->userSpecKeys = curKey;
		curKey->next = curKey;
	} else {
		curKey->next = screen->userSpecKeys->next;
		screen->userSpecKeys->next = curKey;
		screen->userSpecKeys = curKey;
	}
}

void
GfuiAddSKey(void *scr, int key, const char *descr, void *userData, tfuiCallback onKeyPressed, tfuiCallback onKeyReleased)
{
	GfuiAddSKeyAction(scr, key, descr, gfuiMakeAction(userData, onKeyPressed), gfuiMakeAction(userData, onKeyReleased));
}

/** Save a screen shot in png format.
    @ingroup	screen
 */
void
GfuiScreenShot(void * /* notused */)
{
	unsigned char *img;
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];
	struct tm *stm;
	time_t t;
	int sw, sh, vw, vh;
	int len;
	char path[BUFSIZE];
	
	len = snprintf(path, BUFSIZE, "%sscreenshots", GetLocalDir());
	if ((len < 0) || (len >= BUFSIZE)) {
		GfError("GfuiScreenShot: screenshot directory path too long\n");
		return;
	}
	// Ensure that screenshot directory exists.
	if (GfCreateDir(path) == GF_DIR_CREATED) {
	
		GfScrGetSize(&sw, &sh, &vw, &vh);
		img = (unsigned char*)malloc(vw * vh * 3);
		if (img == NULL) {
			return;
		}
		
		glPixelStorei(GL_PACK_ROW_LENGTH, 0);
		glPixelStorei(GL_PACK_ALIGNMENT, 1);
		glReadBuffer(GL_FRONT);
		glReadPixels((sw-vw)/2, (sh-vh)/2, vw, vh, GL_RGB, GL_UNSIGNED_BYTE, (GLvoid*)img);
		
		t = time(NULL);
		stm = localtime(&t);
		len = snprintf(buf, BUFSIZE, "%s/torcs-%4d%02d%02d%02d%02d%02d.png",
			path,
			stm->tm_year+1900,
			stm->tm_mon+1,
			stm->tm_mday,
			stm->tm_hour,
			stm->tm_min,
			stm->tm_sec);
		if ((len < 0) || (len >= BUFSIZE)) {
			GfError("GfuiScreenShot: screenshot file path too long\n");
			free(img);
			return;
		}
		GfImgWritePngNoGamma(img, buf, vw, vh);
		
		free(img);
	}
}

/** Add an image background to a screen.
    @ingroup	gui
    @param[in,out] scr Screen whose background texture is replaced.
    @param[in] filename PNG filename to load.
    @note The old texture is deleted before loading; a load failure therefore
        removes the old background. Rendering assumes 16:10 artwork stored in
        a texture and crops it to the viewport's aspect ratio.
 */
void
GfuiScreenAddBgImg(void *scr, const char *filename)
{
	tGfuiScreen	*screen = (tGfuiScreen*)scr;
	void *handle;
	float screen_gamma;
	GLbyte *tex;
	int w,h;
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];
	
	if (glIsTexture(screen->bgImage) == GL_TRUE) {
		glDeleteTextures(1, &screen->bgImage);
	}

	snprintf(buf, BUFSIZE, "%s%s", GetLocalDir(), GFSCR_CONF_FILE);
	handle = GfParmReadFile(buf, GFPARM_RMODE_STD | GFPARM_RMODE_CREAT);
	screen_gamma = (float)GfParmGetNum(handle, GFSCR_SECT_PROP, GFSCR_ATT_GAMMA, (char*)NULL, 2.0);
	tex = (GLbyte*)GfImgReadPng(filename, &w, &h, screen_gamma);
	if (!tex) {
		GfParmReleaseHandle(handle);
		return;
	}

	glGenTextures(1, &screen->bgImage);
	glBindTexture(GL_TEXTURE_2D, screen->bgImage);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, (GLvoid *)(tex));
	free(tex);
	GfParmReleaseHandle(handle);
}
