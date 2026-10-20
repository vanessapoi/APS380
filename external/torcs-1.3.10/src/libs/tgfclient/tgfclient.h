/***************************************************************************
                    tgfclient.h -- Interface file for The Gaming Framework                                    
                             -------------------                                         
    created              : Fri Aug 13 22:32:14 CEST 1999
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
    	The Gaming Framework API (client part).
    @author	<a href=mailto:torcs@free.fr>Eric Espie</a>
*/



#ifndef __TGFCLIENT__H__
#define __TGFCLIENT__H__

#include <functional>

#include <tgf.h>
#include <GL/glut.h>
#include <plib/js.h>
#include <screen_properties.h>

#define NUM_JOY 8

extern void GfInitClient(void);

/******************** 
 * Screen Interface *
 ********************/

extern unsigned char *GfImgReadPng(const char *filename, int *widthp, int *heightp, float gamma);
extern int GfImgWritePng(unsigned char *img, const char *filename, int width, int height);
extern int GfImgWritePngNoGamma(unsigned char *img, const char *filename, int width, int height);
extern void GfImgFreeTex(GLuint tex);
extern GLuint GfImgReadTex(char *filename);

extern void GfScrInit(int argc, char *argv[]);
extern void GfScrShutdown(void);
extern void *GfScrMenuInit(void *precMenu);
extern void GfTime2Str(char *result, int resultSize, tdble sec, int sgn);
extern void GfScrGetSize(int *ScrW, int *ScrH, int *ViewW, int *ViewH);
extern void GfScrReinit(void*);


/*****************************
 * GUI interface (low-level) *
 *****************************/

/* Widget type */
#define GFUI_LABEL	0
#define GFUI_BUTTON	1
#define GFUI_GRBUTTON	2
#define GFUI_SCROLLIST	3
#define GFUI_SCROLLBAR	4
#define GFUI_EDITBOX	5

/* Alignment */
#define GFUI_ALIGN_HL_VB	0x00
#define GFUI_ALIGN_HL_VC	0x01
#define GFUI_ALIGN_HL_VT	0x02
#define GFUI_ALIGN_HC_VB	0x10
#define GFUI_ALIGN_HC_VC	0x11
#define GFUI_ALIGN_HC_VT	0x12
#define GFUI_ALIGN_HR_VB	0x20
#define GFUI_ALIGN_HR_VC	0x21
#define GFUI_ALIGN_HR_VT	0x22

/* Mouse action */
#define GFUI_MOUSE_UP	0
#define GFUI_MOUSE_DOWN	1

/* Keyboard action */
#define GFUI_KEY_UP	0
#define GFUI_KEY_DOWN	1

/* Scroll Bar position */
#define GFUI_SB_NONE	0
#define GFUI_SB_RIGHT	1
#define GFUI_SB_LEFT	2
#define GFUI_SB_TOP	3
#define GFUI_SB_BOTTOM	4

/* Scroll bar orientation */
#define GFUI_HORI_SCROLLBAR	0
#define GFUI_VERT_SCROLLBAR	1

/** Scroll bar call-back information */
typedef struct ScrollBarInfo
{
    int		pos;		/**< Current scroll bar position */
    void	*userData;	/**< Associated user data */
} tScrollBarInfo;

typedef std::function<void()> tGfuiAction;
typedef void (*tfuiCallback)(void * /* userdata */);
typedef void (*tfuiSBCallback)(tScrollBarInfo *);
typedef int (*tfuiKeyCallback)(unsigned char key, int modifier, int state); /**< return 1 to prevent normal key computing */
typedef int (*tfuiSKeyCallback)(int key, int modifier, int state);  /**< return 1 to prevent normal key computing */


/* GLUT Callback functions                  */
/* should be called explicitely if          */
/* the corresponding GLUT Func is overriden */
/* after a call to GfuiActivateScreen       */
extern void GfuiDisplay(void);
extern void GfuiDisplayNothing(void);
extern void GfuiIdle(void);

/* Screen management */
extern void *GfuiScreenCreate(void);
extern void *GfuiScreenCreateExAction(float *bgColor,
				const tGfuiAction &onActivate,
				const tGfuiAction &onDeactivate,
				int mouseAllowed);
/** Create a screen using callbacks with caller-supplied data.
    @ingroup gui
    @param[in] bgColor Background RGBA color, or NULL for the default color.
    @param[in] userDataOnActivate Data passed to onActivate.
    @param[in] onActivate Callback on activation, or NULL.
    @param[in] userDataOnDeactivate Data passed to onDeactivate.
    @param[in] onDeactivate Callback on deactivation, or NULL.
    @param[in] mouseAllowed Nonzero to display the mouse cursor.
    @return Screen handle, to be released with GfuiScreenRelease.
    @see GfuiScreenCreateExAction
 */
extern void *GfuiScreenCreateEx(float *bgColor, 
				void *userDataOnActivate, tfuiCallback onActivate, 
				void *userDataOnDeactivate, tfuiCallback onDeactivate, 
				int mouseAllowed);
extern void GfuiScreenRelease(void *screen);
extern void GfuiScreenActivate(void *screen);
extern int  GfuiScreenIsActive(void *screen);
extern void GfuiScreenReplace(void *screen);
extern void GfuiScreenDeactivate(void);
extern void *GfuiHookCreateAction(const tGfuiAction &onActivate);
/** Create a callback-only screen hook.
    @ingroup gui
    @param[in] userDataOnActivate Data passed to onActivate.
    @param[in] onActivate Callback invoked when the hook is activated, or NULL.
    @return Hook handle, to be released with GfuiHookRelease.
    @see GfuiHookCreateAction
 */
extern void *GfuiHookCreate(void *userDataOnActivate, tfuiCallback onActivate);
extern void GfuiHookRelease(void *hook);
extern void GfuiAddKeyAction(void *scr, unsigned char key, const char *descr, const tGfuiAction &onKeyPressed, const tGfuiAction &onKeyReleased);
/** Bind an ordinary key on a screen using callbacks with caller-supplied data.
    @ingroup gui
    @param[in,out] scr Screen handle whose key bindings are updated.
    @param[in] key Character key code.
    @param[in] descr Description displayed on the help screen.
    @param[in] userData Data passed to both callbacks.
    @param[in] onKeyPressed Callback on key press, or NULL.
    @param[in] onKeyReleased Callback on key release, or NULL.
    @see GfuiAddKeyAction
 */
extern void GfuiAddKey(void *scr, unsigned char key, const char *descr, void *userData, tfuiCallback onKeyPressed, tfuiCallback onKeyReleased);
extern void GfuiRegisterKeyAction(unsigned char key, char *descr, const tGfuiAction &onKeyPressed, const tGfuiAction &onKeyReleased);
/** Bind an ordinary key on the currently active screen.
    @ingroup gui
    @param[in] key Character key code.
    @param[in] descr Description displayed on the help screen.
    @param[in] userData Data passed to both callbacks.
    @param[in] onKeyPressed Callback on key press, or NULL.
    @param[in] onKeyReleased Callback on key release, or NULL.
    @see GfuiRegisterKeyAction
 */
extern void GfuiRegisterKey(unsigned char key, char *descr, void *userData, tfuiCallback onKeyPressed, tfuiCallback onKeyReleased);
extern void GfuiAddSKeyAction(void *scr, int key, const char *descr, const tGfuiAction &onKeyPressed, const tGfuiAction &onKeyReleased);
/** Bind a GLUT special key, such as an arrow or function key, on a screen.
    @ingroup gui
    @param[in,out] scr Screen handle whose key bindings are updated.
    @param[in] key GLUT special-key code.
    @param[in] descr Description displayed on the help screen.
    @param[in] userData Data passed to both callbacks.
    @param[in] onKeyPressed Callback on key press, or NULL.
    @param[in] onKeyReleased Callback on key release, or NULL.
    @see GfuiAddSKeyAction
 */
extern void GfuiAddSKey(void *scr, int key, const char *descr, void *userData, tfuiCallback onKeyPressed, tfuiCallback onKeyReleased);
extern void GfuiHelpScreen(void *prevScreen);
extern void GfuiScreenShot(void *notused);
extern void GfuiScreenAddBgImg(void *scr, const char *filename);
/** Set the ordinary-key event interceptor for a screen.
    @ingroup gui
    @param[in,out] scr Screen handle whose event interceptor is updated.
    @param[in] onKeyAction Callback receiving the key, GLUT modifiers and
        GFUI_KEY_DOWN or GFUI_KEY_UP; NULL removes the interceptor.
        Return nonzero to consume the event before normal key handling.
 */
extern void GfuiKeyEventRegister(void *scr, tfuiKeyCallback onKeyAction);
/** Set the special-key event interceptor for a screen.
    @ingroup gui
    @param[in,out] scr Screen handle whose event interceptor is updated.
    @param[in] onSKeyAction Callback receiving the GLUT special-key code, modifiers
        and GFUI_KEY_DOWN or GFUI_KEY_UP; NULL removes the interceptor.
        Return nonzero to consume the event before normal key handling.
 */
extern void GfuiSKeyEventRegister(void *scr, tfuiSKeyCallback onSKeyAction);
/** Set the ordinary-key interceptor on the currently active screen.
    @ingroup gui
    @param[in] onKeyAction Event callback, or NULL to remove it; see GfuiKeyEventRegister.
 */
extern void GfuiKeyEventRegisterCurrent(tfuiKeyCallback onKeyAction);
/** Set the special-key interceptor on the currently active screen.
    @ingroup gui
    @param[in] onSKeyAction Event callback, or NULL to remove it; see GfuiSKeyEventRegister.
 */
extern void GfuiSKeyEventRegisterCurrent(tfuiSKeyCallback onSKeyAction);

/* mouse */
typedef struct MouseInfo
{
    int	X;
    int	Y;
    int	button[3];
} tMouseInfo;

extern tMouseInfo *GfuiMouseInfo(void);
extern void GfuiMouseSetPos(int x, int y);
extern void GfuiMouseHide(void);
extern void GfuiMouseShow(void);
extern void GfuiMouseSetHWPresent(void);

/* all widgets */
#define	GFUI_VISIBLE	1	/**< Object visibility flag  */
#define	GFUI_INVISIBLE	0	/**< Object invisibility flag  */
extern int GfuiVisibilitySet(void *scr, int id, int visible);
#define	GFUI_DISABLE	1
#define	GFUI_ENABLE	0
extern int GfuiEnable(void *scr, int id, int flag);
extern void GfuiUnSelectCurrent(void);

/* labels */
#define GFUI_FONT_BIG		0
#define GFUI_FONT_LARGE		1
#define GFUI_FONT_MEDIUM	2
#define GFUI_FONT_SMALL		3
#define GFUI_FONT_BIG_C		4
#define GFUI_FONT_LARGE_C	5
#define GFUI_FONT_MEDIUM_C	6
#define GFUI_FONT_SMALL_C	7
#define GFUI_FONT_DIGIT		8
extern int GfuiLabelCreate(void *scr, const char *text, 
			int font, int x, int y, int align, int maxlen);
extern int GfuiLabelCreateEx(void *scr, const char *text, float *fgColor, int font, int x, int y, int align, int maxlen);

extern int GfuiTipCreate(void *scr, const char *text, int maxlen);
extern int GfuiTitleCreate(void *scr, const char *text, int maxlen);

extern void GfuiLabelSetText(void *scr, int id, const char *text);
extern void GfuiLabelSetColor(void *scr, int id, float *color);

/** Draw text immediately in the current OpenGL context without creating a widget.
    @ingroup gui
    @param[in] text Text to draw.
    @param[in] fgColor RGBA text color.
    @param[in] font GFUI_FONT_* identifier of an initialized font.
    @param[in] x Horizontal anchor in GUI coordinates.
    @param[in] y Baseline in GUI coordinates.
    @param[in] align GFUI_ALIGN_* value; only horizontal alignment is used.
 */
extern void GfuiPrintString(const char *text, float *fgColor, int font, int x, int y, int align);
/** Get the height of an initialized GUI font.
    @ingroup gui
    @param[in] font GFUI_FONT_* identifier.
    @return Font height in GUI coordinate units.
 */
extern int  GfuiFontHeight(int font);
/** Measure text using an initialized GUI font.
    @ingroup gui
    @param[in] font GFUI_FONT_* identifier.
    @param[in] text Text to measure.
    @return Text width in GUI coordinate units.
 */
extern int  GfuiFontWidth(int font, const char *text);


/* buttons */
#define GFUI_BTNSZ	300
extern int GfuiButtonCreateAction(void *scr, const char *text, int font,
			    int x, int y, int width, int align, int mouse,
			    const tGfuiAction &onPush,
			    const tGfuiAction &onFocus, const tGfuiAction &onFocusLost);
/** Create a text button using callbacks with caller-supplied data.
    @ingroup gui
    @copydetails GfuiButtonCreateAction
    @param[in] userDataOnPush Data passed to onPush.
    @param[in] userDataOnFocus Data passed to onFocus and onFocusLost.
 */
extern int GfuiButtonCreate(void *scr, const char *text, int font,
			    int x, int y, int width, int align, int mouse,
			    void *userDataOnPush, tfuiCallback onPush, 
			    void *userDataOnFocus, tfuiCallback onFocus, tfuiCallback onFocusLost);
/** Create a text button without horizontal margins.
    @ingroup gui
    @copydetails GfuiButtonCreateAction
    @note Unlike a standard button, this variant removes both horizontal margins
        and uses the focused background color even when enabled but unfocused.
 */
extern int GfuiLeanButtonCreateAction(void *scr, const char *text, int font,
							int x, int y, int width, int align, int mouse,
							const tGfuiAction &onPush,
							const tGfuiAction &onFocus, const tGfuiAction &onFocusLost);
/** Create a marginless text button using callbacks with caller-supplied data.
    @ingroup gui
    @copydetails GfuiLeanButtonCreateAction
    @param[in] userDataOnPush Data passed to onPush.
    @param[in] userDataOnFocus Data passed to onFocus and onFocusLost.
 */
extern int GfuiLeanButtonCreate(void *scr, const char *text, int font,
							int x, int y, int width, int align, int mouse,
							void *userDataOnPush, tfuiCallback onPush, 
							void *userDataOnFocus, tfuiCallback onFocus, tfuiCallback onFocusLost);
/** Create a text button that toggles between pressed and released while focused.
    @ingroup gui
    @copydetails GfuiButtonCreateAction
    @note Starts released. Activation toggles its state; onPush is called only
        when changing to pressed, not when toggling back to released. Losing
        focus resets the button to released without invoking onPush.
 */
extern int GfuiButtonStateCreateAction(void *scr, const char *text, int font, int x, int y, int width, int align, int mouse,
				 const tGfuiAction &onPush,
				 const tGfuiAction &onFocus, const tGfuiAction &onFocusLost);
extern int GfuiButtonStateCreate(void *scr, const char *text, int font, int x, int y, int width, int align, int mouse,
				 void *userDataOnPush, tfuiCallback onPush, 
				 void *userDataOnFocus, tfuiCallback onFocus, tfuiCallback onFocusLost);
extern int GfuiGrButtonCreateAction(void *scr, const char *disabled, const char *enabled, const char *focused, const char *pushed,
			      int x, int y, int align, int mouse,
			      const tGfuiAction &onPush,
			      const tGfuiAction &onFocus, const tGfuiAction &onFocusLost);
/** Create an image button using callbacks with caller-supplied data.
    @ingroup gui
    @copydetails GfuiGrButtonCreateAction
    @param[in] userDataOnPush Data passed to onPush.
    @param[in] userDataOnFocus Data passed to onFocus and onFocusLost.
 */
extern int GfuiGrButtonCreate(void *scr, const char *disabled, const char *enabled, const char *focused, const char *pushed,
			      int x, int y, int align, int mouse,
			      void *userDataOnPush, tfuiCallback onPush, 
			      void *userDataOnFocus, tfuiCallback onFocus, tfuiCallback onFocusLost);

extern void GfuiButtonSetText(void *scr, int id, const char *text);
extern int GfuiButtonGetFocused(void);

/* Edit Box */
extern int GfuiEditboxCreateAction(void *scr, const char *text, int font, int x, int y, int width, int maxlen,
				 const tGfuiAction &onFocus, const tGfuiAction &onFocusLost, int margin = 10);
/** Create an edit box using callbacks with caller-supplied data.
    @ingroup gui
    @copydetails GfuiEditboxCreateAction
    @param[in] userDataOnFocus Data passed to onFocus and onFocusLost.
 */
extern int GfuiEditboxCreate(void *scr, const char *text, int font, int x, int y, int width, int maxlen,
			     void *userDataOnFocus, tfuiCallback onFocus, tfuiCallback onFocusLost, int margin = 10);
extern int GfuiEditboxGetFocused(void);
extern char *GfuiEditboxGetString(void *scr, int id);
extern void GfuiEditboxSetString(void *scr, int id, const char *text);

/* Scrolling lists */
extern int GfuiScrollListCreateAction(void *scr, int font, int x, int y, int align,
				int width, int height, int scrollbar, const tGfuiAction &onSelect);
/** Create a scrolling list using a callback with caller-supplied data.
    @ingroup gui
    @param[in,out] scr Screen handle receiving the list.
    @param[in] font GFUI_FONT_* identifier.
    @param[in] x Horizontal position in GUI coordinates.
    @param[in] y Vertical position in GUI coordinates (zero at the bottom).
    @param[in] align Retained for compatibility; currently ignored.
    @param[in] width List width.
    @param[in] height List height.
    @param[in] scrollbar GFUI_SB_NONE, GFUI_SB_LEFT or GFUI_SB_RIGHT.
    @param[in] userDataOnSelect Data passed to onSelect.
    @param[in] onSelect Callback on user selection, or NULL. Programmatic insertion,
        extraction and reordering do not invoke it.
    @return Scroll list identifier.
    @see GfuiScrollListCreateAction
 */
extern int GfuiScrollListCreate(void *scr, int font, int x, int y, int align,
				int width, int height, int scrollbar, void *userDataOnSelect, tfuiCallback onSelect);
extern int GfuiScrollListInsertElement(void *scr, int Id, char *element, int index, void *userData);
extern int GfuiScrollListMoveSelectedElement(void *scr, int Id, int delta);
extern char *GfuiScrollListExtractSelectedElement(void *scr, int Id, void **userData);
extern char *GfuiScrollListExtractElement(void *scr, int Id, int index, void **userData);
extern char *GfuiScrollListGetSelectedElement(void *scr, int Id, void **userData);
extern char *GfuiScrollListGetElement(void *scr, int Id, int index, void **userData);

/* scroll bars */
extern int GfuiScrollBarCreate(void *scr, int x, int y, int align, int width, int orientation,
			       int min, int max, int len, int start, 
			       void *userData, tfuiSBCallback onScroll);
extern void GfuiScrollBarPosSet(void *scr, int id, int min, int max, int len, int start);
extern int GfuiScrollBarPosGet(void *scr, int id);

/* Images */
extern int GfuiStaticImageCreate(void *scr, int x, int y, int w, int h, char *name);
extern void GfuiStaticImageSet(void *scr, int id, char *name);

/*****************************
 * Menu Management Interface *
 *****************************/

extern void *GfuiMenuScreenCreate(const char *title);
extern void  GfuiMenuDefaultKeysAdd(void *scr);
/** Add a menu button with a focus tip.
    @ingroup gui
    @param[in,out] menu Menu screen handle receiving the button.
    @param[in] text Button label.
    @param[in] tip Focus tip, or NULL for no text.
    @param[in] onpush Action on button activation; an empty action does nothing.
    @return Button identifier, or -1 when automatic menu slots are exhausted.
    @note Use GfuiEnable to disable the button explicitly.
    @see GfuiMenuButtonCreateActionWithDisabledTip
 */
extern int   GfuiMenuButtonCreateAction(void *menu, const char *text, const char *tip, const tGfuiAction &onpush);
extern int   GfuiMenuButtonCreateActionWithDisabledTip(void *menu, const char *text, const char *tip, const char *disabledTip, const tGfuiAction &onpush);
/** Add a menu button using a callback with caller-supplied data.
    @ingroup gui
    @param[in,out] menu Menu screen handle receiving the button.
    @param[in] text Button label.
    @param[in] tip Focus tip, or NULL for no text.
    @param[in] userdata Data passed to onpush.
    @param[in] onpush Callback on button activation, or NULL for no action.
    @return Button identifier, or -1 when automatic menu slots are exhausted.
    @note Use GfuiEnable to disable the button explicitly.
    @see GfuiMenuButtonCreateAction
 */
extern int   GfuiMenuButtonCreate(void *menu, const char *text, const char *tip, void *userdata, tfuiCallback onpush);
extern int   GfuiMenuBackQuitButtonCreateAction(void *menu, const char *text, const char *tip, const tGfuiAction &onpush);
/** Add the bottom Back/Quit menu button using a callback with caller-supplied data.
    @ingroup gui
    @param[in,out] menu Menu screen handle receiving the button.
    @param[in] text Button label.
    @param[in] tip Focus tip, or NULL for no text.
    @param[in] userdata Data passed to onpush.
    @param[in] onpush Callback on button activation or Escape, or NULL for no action.
    @return Button identifier.
    @note The callback must implement navigation or quitting; the button's label
        does not supply that behavior. Use GfuiEnable to disable the button.
    @see GfuiMenuBackQuitButtonCreateAction
 */
extern int   GfuiMenuBackQuitButtonCreate(void *menu, const char *text, const char *tip, void *userdata, tfuiCallback onpush);


/*********************
 * Control interface *
 *********************/

typedef enum {
	GFCTRL_TYPE_NOT_AFFECTED = 0,
	GFCTRL_TYPE_JOY_AXIS = 1,
	GFCTRL_TYPE_JOY_BUT = 2,
	GFCTRL_TYPE_KEYBOARD = 3,
	GFCTRL_TYPE_MOUSE_BUT = 4,
	GFCTRL_TYPE_MOUSE_AXIS = 5,
	GFCTRL_TYPE_SKEYBOARD = 6
} GfCtrlType;

typedef struct
{
    int index;
    GfCtrlType type;
} tCtrlRef;


#define GFCTRL_JOY_UNTESTED	-1
#define GFCTRL_JOY_NONE		0
#define GFCTRL_JOY_PRESENT	1

#define GFCTRL_JOY_MAXBUTTON	32 /* Size of integer so don't change please */

/** Joystick Information Structure */
typedef struct
{
    int		oldb[NUM_JOY];
    float	ax[_JS_MAX_AXES * NUM_JOY];			/**< Axis values */
    int		edgeup[GFCTRL_JOY_MAXBUTTON * NUM_JOY];	/**< Button transition from down (pressed) to up */
    int		edgedn[GFCTRL_JOY_MAXBUTTON * NUM_JOY];	/**< Button transition from up to down */
    int		levelup[GFCTRL_JOY_MAXBUTTON * NUM_JOY];/**< Button state (1 = up) */
} tCtrlJoyInfo;

extern tCtrlJoyInfo *GfctrlJoyInit(void);
extern int GfctrlJoyIsPresent(void);
extern int GfctrlJoyGetCurrent(tCtrlJoyInfo *joyInfo);
extern void GfctrlJoyRelease(tCtrlJoyInfo *joyInfo);


/** Mouse information structure */
typedef struct
{
    int		edgeup[3];	/**< Button transition from down (pressed) to up */
    int		edgedn[3];	/**< Button transition from up to down */
    int		button[3];	/**< Button state (1 = up) */
    float	ax[4];		/**< mouse axis position (mouse considered as a joystick) */
} tCtrlMouseInfo;

extern tCtrlMouseInfo *GfctrlMouseInit(void);
extern int GfctrlMouseGetCurrent(tCtrlMouseInfo *mouseInfo);
extern void GfctrlMouseRelease(tCtrlMouseInfo *mouseInfo);
extern void GfctrlMouseCenter(void);
extern void GfctrlMouseInitCenter(void);
extern void GfctrlGetRefByName(const char *name, tCtrlRef* ref);
extern const char *GfctrlGetNameByRef(GfCtrlType type, int index);
extern const char *GfctrlGetDefaultSection(GfCtrlType type);
extern bool GfctrlIsEventBlacklisted(void *parmHandle, const char* driversSection, const char* event);

/** Query an OpenGL extension through GLUT for the current rendering context.
    @ingroup screen
    @param[in] str Exact extension name, for example "GL_ARB_multitexture".
    @return Nonzero if the extension is supported, zero otherwise.
 */
extern int GfuiGlutExtensionSupported(const char *str);


#endif /* __TGFCLIENT__H__ */
