/***************************************************************************
                          menu.cpp -- menu management                            
                             -------------------                                         
    created              : Fri Aug 13 22:23:19 CEST 1999
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
    		GUI menu management.
    @author	<a href=mailto:torcs@free.fr>Eric Espie</a>
*/


#include <stdio.h>
#include <stdlib.h>
#include <memory>
#ifdef WIN32
#include <windows.h>
#endif
#include <GL/glut.h>

#include <tgfclient.h>
#include "gui.h"
#include "guimenu.h"

void
gfMenuInit(void)
{
}

/** Add the default menu keyboard callback to a screen.
    The keys are:
    <br><tt>Up Arrow .... </tt>Select Previous Entry
    <br><tt>Down Arrow .. </tt>Select Next Entry
    <br><tt>F1 .......... </tt>Help
    <br><tt>Tab ......... </tt>Select Next Entry
    <br><tt>Enter ....... </tt>Perform Action
    <br><tt>Page Up/Down  </tt>Select Previous/Next Entry
    <br><tt>F12 ......... </tt>Save a screenshot
    Escape is not registered here; GfuiMenuBackQuitButtonCreateAction adds it.
    @ingroup	gui
    @param[in,out] scr Screen receiving the default bindings.
 */
void
GfuiMenuDefaultKeysAdd(void *scr)
{
    GfuiAddKeyAction(scr, 9, "Select Next Entry", [] { gfuiSelectNext(NULL); }, tGfuiAction());
    GfuiAddKeyAction(scr, 13, "Perform Action", [] { gfuiMouseAction(2); }, tGfuiAction());
    GfuiAddSKeyAction(scr, GLUT_KEY_UP, "Select Previous Entry", [] { gfuiSelectPrev(NULL); }, tGfuiAction());
    GfuiAddSKeyAction(scr, GLUT_KEY_DOWN, "Select Next Entry", [] { gfuiSelectNext(NULL); }, tGfuiAction());
    GfuiAddSKeyAction(scr, GLUT_KEY_PAGE_UP, "Select Previous Entry", [] { gfuiSelectPrev(NULL); }, tGfuiAction());
    GfuiAddSKeyAction(scr, GLUT_KEY_PAGE_DOWN, "Select Next Entry", [] { gfuiSelectNext(NULL); }, tGfuiAction());
    GfuiAddSKeyAction(scr, GLUT_KEY_F1, "Help", [scr] { GfuiHelpScreen(scr); }, tGfuiAction());
    GfuiAddSKeyAction(scr, GLUT_KEY_F12, "Screen-Shot", [] { GfuiScreenShot(NULL); }, tGfuiAction());
    
}

/** Create a new menu screen.
    Set the title of the menu
    Add the default keyboard callbacks to the menu.
    @ingroup	gui
    @param[in] title Non-NULL title text, copied into the title label.
    @return Inactive menu screen handle; release with GfuiScreenRelease.
 */
void *
GfuiMenuScreenCreate(const char *title)
{
	void	*scr;
	
	scr = GfuiScreenCreate();
	GfuiTitleCreate(scr, title, strlen(title));
	
	GfuiMenuDefaultKeysAdd(scr);
	
	return scr;
}

static void
dispInfo(const tMnuCallbackInfo *cbinfo)
{
    tGfuiObject *button = gfuiGetObject(cbinfo->screen, cbinfo->buttonId);

    if (button && button->state == GFUI_DISABLE && !cbinfo->disabledTip.empty()) {
        GfuiLabelSetText(cbinfo->screen, cbinfo->labelId, cbinfo->disabledTip.c_str());
        static float disabledTipColor[4] = {1.0, 0.0, 0.0, 1.0};
        GfuiLabelSetColor(cbinfo->screen, cbinfo->labelId, disabledTipColor);
    } else {
        GfuiLabelSetText(cbinfo->screen, cbinfo->labelId, cbinfo->tip.c_str());
        GfuiLabelSetColor(cbinfo->screen, cbinfo->labelId, &(GfuiColor[GFUI_TIPCOLOR][0]));
    }
    GfuiVisibilitySet(cbinfo->screen, cbinfo->labelId, 1);
}
static void
remInfo(const tMnuCallbackInfo *cbinfo)
{
    GfuiVisibilitySet(cbinfo->screen, cbinfo->labelId, 0);
}


/** Add a button to a menu screen.
    @ingroup	gui
    @param[in,out] scr Menu screen receiving the next automatically positioned button.
    @param[in] text Button label, copied.
    @param[in] tip Focus tip, copied; NULL means empty text.
    @param[in] disabledTip Tip shown in red when focused and disabled; copied.
        NULL or empty text falls back to tip.
    @param[in] onpush Action on activation; an empty action does nothing.
    @return Button identifier, or -1 when the menu's automatic slots are exhausted.
    @note Use GfuiEnable to disable the button. Merely omitting onpush does not
        disable it or select the disabled tip.
 */
int
GfuiMenuButtonCreateActionWithDisabledTip(void *scr, const char *text, const char *tip, const char *disabledTip, const tGfuiAction &onpush)
{
	std::shared_ptr<tMnuCallbackInfo> cbinfo;
	int xpos, ypos;
	int nbItems = ((tGfuiScreen*)scr)->nbItems++;
	int bId;
	
	if (nbItems < 11) {
		xpos = 320;
		ypos = 380 - 30 * nbItems;
	} else {
		if (nbItems > 22) {
			GfTrace("Too many items in that menu !!!\n");
			return -1;
		}
		xpos = 380;
		ypos = 380 - 30 * (nbItems - 11);
	}
	
	cbinfo = std::make_shared<tMnuCallbackInfo>();
	cbinfo->screen = scr;
	cbinfo->buttonId = -1;
	cbinfo->tip = tip ? tip : "";
	cbinfo->disabledTip = disabledTip ? disabledTip : "";
	const int maxTipLen = (int)(cbinfo->tip.length() > cbinfo->disabledTip.length() ? cbinfo->tip.length() : cbinfo->disabledTip.length());
	cbinfo->labelId = GfuiTipCreate(scr, cbinfo->tip.c_str(), maxTipLen);
	
	GfuiVisibilitySet(scr, cbinfo->labelId, 0);
	
	bId = GfuiButtonCreateAction(scr,
				text,
				GFUI_FONT_LARGE,
				xpos, ypos, GFUI_BTNSZ, GFUI_ALIGN_HC_VB, 0,
				onpush,
				[cbinfo] { dispInfo(cbinfo.get()); },
				[cbinfo] { remInfo(cbinfo.get()); });
	cbinfo->buttonId = bId;
	return bId;
}

int
GfuiMenuButtonCreateAction(void *scr, const char *text, const char *tip, const tGfuiAction &onpush)
{
    return GfuiMenuButtonCreateActionWithDisabledTip(scr, text, tip, NULL, onpush);
}

int
GfuiMenuButtonCreate(void *scr, const char *text, const char *tip, void *userdata, tfuiCallback onpush)
{
	return GfuiMenuButtonCreateAction(scr, text, tip, gfuiMakeAction(userdata, onpush));
}

/** Add the "Back" or "Quit" button at the bottom of the menu screen.
    @ingroup	gui
    @param[in,out] scr Menu screen receiving the button and Escape binding.
    @param[in] text Button label, copied.
    @param[in] tip Focus tip and Escape help text, copied; NULL means empty text.
    @param[in] onpush Action on button activation or Escape; may be empty.
    @return Button identifier, local to scr.
    @note The action must implement navigation or quitting; the label alone
        does not supply either behavior.
 */
int
GfuiMenuBackQuitButtonCreateAction(void *scr, const char *text, const char *tip, const tGfuiAction &onpush)
{
    std::shared_ptr<tMnuCallbackInfo> cbinfo;
    int			xpos, ypos;
    int			bId;
    
    xpos = 320;
    ypos = 40;

    cbinfo = std::make_shared<tMnuCallbackInfo>();
    cbinfo->screen = scr;
    cbinfo->buttonId = -1;
    cbinfo->tip = tip ? tip : "";
    cbinfo->labelId = GfuiTipCreate(scr, cbinfo->tip.c_str(), (int)cbinfo->tip.length());

    GfuiVisibilitySet(scr, cbinfo->labelId, 0);
    
    bId = GfuiButtonCreateAction(scr,
			text,
			GFUI_FONT_LARGE,
			xpos, ypos, GFUI_BTNSZ, GFUI_ALIGN_HC_VB, 0,
			onpush,
			[cbinfo] { dispInfo(cbinfo.get()); },
			[cbinfo] { remInfo(cbinfo.get()); });
	cbinfo->buttonId = bId;

    GfuiAddKeyAction(scr, (unsigned char)27, tip, onpush, tGfuiAction());

    return bId;
}

int
GfuiMenuBackQuitButtonCreate(void *scr, const char *text, const char *tip, void *userdata, tfuiCallback onpush)
{
    return GfuiMenuBackQuitButtonCreateAction(scr, text, tip, gfuiMakeAction(userdata, onpush));
}
