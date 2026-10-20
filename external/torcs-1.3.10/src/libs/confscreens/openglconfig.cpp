/***************************************************************************

    file        : openglconfig.cpp
    created     : Fri Jun 3 12:52:07 CET 2004
    copyright   : (C) 2005-2026 Bernhard Wymann
    email       : berniw@bluewin.ch

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
*/

#include <stdio.h>
#include <stdlib.h>
#include <tgfclient.h>
#include <raceinit.h>
#include <graphic.h>
#include <glfeatures.h>
#include <portability.h>
#include "openglconfig.h"

static float LabelColor[] = {1.0, 0.0, 1.0, 1.0};

// Texture compression.
static const char *textureCompressOptionList[] = {
	GR_ATT_TEXTURECOMPRESSION_DISABLED,
	GR_ATT_TEXTURECOMPRESSION_ENABLED
};

static const int nbOptionsTextComp = sizeof(textureCompressOptionList) / sizeof(textureCompressOptionList[0]);
static int curOptionTextComp = 0;
static int TextureCompressOptionId;

// Texture sizing, order of list is important, do not change.
static int textureSizeOptionList[] = {8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384};
static int nbOptionsTextSize = sizeof(textureSizeOptionList) / sizeof(textureSizeOptionList[0]);
static int curOptionTextSize = 0;
static int TextureSizeOptionId;
static const int defaultTextSize = 64; // In case everything goes wrong.

// Texture anisotropic filtering, order of list is important, do not change.
static const char *textureAnisotropyOptionLabelList[] = {
	"disabled",
	"2x",
	"4x",
	"8x",
	"16x"
};
static int textureAnisotropyOptionList[] = {0, 2, 4, 8, 16};
static const int nbTextureAnisotropyOptions = sizeof(textureAnisotropyOptionList) / sizeof(textureAnisotropyOptionList[0]);
static int nbOptionsTextAnisotropy = 1;
static int curOptionTextAnisotropy = 0;
static int TextureAnisotropyOptionId;

// gui screen handles.
static void	*scrHandle = NULL;
static void	*prevHandle = NULL;


// Read OpenGL configuration.
static void readOpenGLCfg(void)
{
	int i;
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];

	snprintf(buf, BUFSIZE, "%s%s", GetLocalDir(), GR_PARAM_FILE);
	void *paramHandle = GfParmReadFile(buf, GFPARM_RMODE_REREAD | GFPARM_RMODE_CREAT);

	// Read texture compression parameters.
	const char *optionName = GfParmGetStr(paramHandle, GR_SCT_GLFEATURES, GR_ATT_TEXTURECOMPRESSION, textureCompressOptionList[0]);
	for (i = 0; i < nbOptionsTextComp; i++) {
		if (strcmp(optionName, textureCompressOptionList[i]) == 0) {
			curOptionTextComp = i;
			break;
		}
	}
	if (isCompressARBAvailable()) {
		GfuiLabelSetText(scrHandle, TextureCompressOptionId, textureCompressOptionList[curOptionTextComp]);
	}

	// Read texture sizing parameters.
	int maxsizenb = 0;
	int sizelimit = getGLTextureMaxSize();
	int tsize = (int) GfParmGetNum(paramHandle, GR_SCT_GLFEATURES, GR_ATT_TEXTURESIZE, (char*)NULL, (tdble) sizelimit);
	bool found = false;

	for (i = 0; i < nbOptionsTextSize; i++) {
		if (textureSizeOptionList[i] <= sizelimit) {
			maxsizenb = i;
		} else {
			break;
		}
	}

	// Limit to available sizes.
	nbOptionsTextSize = maxsizenb+1;

	for (i = 0; i < nbOptionsTextSize; i++) {
		if (textureSizeOptionList[i] == tsize) {
			curOptionTextSize = i;
			found = true;
			break;
		}
	}

	if (!found) {
		// Should never come here if there is no bug in OpenGL.
		tsize = defaultTextSize;
		for (i = 0; i < nbOptionsTextSize; i++) {
			if (textureSizeOptionList[i] == tsize) {
				curOptionTextSize = i;
				break;
			}
		}
	}
	snprintf(buf, BUFSIZE, "%d", textureSizeOptionList[curOptionTextSize]);
	GfuiLabelSetText(scrHandle, TextureSizeOptionId, buf);

	// Read texture anisotropic filtering parameters.
	if (isTextureAnisotropyAvailable()) {
		int maxanisotropy = getGLTextureMaxAnisotropy();
		updateUserTextureAnisotropy();
		int anisotropy = getUserTextureAnisotropy();
		curOptionTextAnisotropy = 0;
		nbOptionsTextAnisotropy = 1;

		for (i = 1; i < nbTextureAnisotropyOptions; i++) {
			if (textureAnisotropyOptionList[i] <= maxanisotropy) {
				nbOptionsTextAnisotropy = i + 1;
			} else {
				break;
			}
		}

		for (i = 0; i < nbOptionsTextAnisotropy; i++) {
			if (textureAnisotropyOptionList[i] <= anisotropy) {
				curOptionTextAnisotropy = i;
			}
		}

		GfuiLabelSetText(scrHandle, TextureAnisotropyOptionId, textureAnisotropyOptionLabelList[curOptionTextAnisotropy]);
	}

	GfParmReleaseHandle(paramHandle);
}


// Save the choosen values in the corresponding parameter file.
static void saveOpenGLOption(void *)
{
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];
	snprintf(buf, BUFSIZE, "%s%s", GetLocalDir(), GR_PARAM_FILE);
	void *paramHandle = GfParmReadFile(buf, GFPARM_RMODE_REREAD | GFPARM_RMODE_CREAT);

	// Texture compression.
	GfParmSetStr(paramHandle, GR_SCT_GLFEATURES, GR_ATT_TEXTURECOMPRESSION, textureCompressOptionList[curOptionTextComp]);
	// Texture sizing.
	GfParmSetNum(paramHandle, GR_SCT_GLFEATURES, GR_ATT_TEXTURESIZE, (char*)NULL, (tdble) textureSizeOptionList[curOptionTextSize]);
	if (isTextureAnisotropyAvailable()) {
		// Texture anisotropic filtering.
		GfParmSetNum(paramHandle, GR_SCT_GLFEATURES, GR_ATT_TEXTUREANISOTROPY, (char*)NULL, (tdble) textureAnisotropyOptionList[curOptionTextAnisotropy]);
	}

	GfParmWriteFile(NULL, paramHandle, "graph");
	GfParmReleaseHandle(paramHandle);

	// Return to previous screen.
	GfuiScreenActivate(prevHandle);
	updateCompressARBEnabled();
	updateUserTextureMaxSize();
	updateUserTextureAnisotropy();
	return;
}


// Toggle texture compression state enabled/disabled.
static void changeTextureCompressState(int delta)
{
	curOptionTextComp += delta;
	if (curOptionTextComp < 0) {
		curOptionTextComp = nbOptionsTextComp - 1;
	} else if (curOptionTextComp == nbOptionsTextComp) {
		curOptionTextComp = 0;
	}
	GfuiLabelSetText(scrHandle, TextureCompressOptionId, textureCompressOptionList[curOptionTextComp]);
}


// Scroll through texture sizes smaller or equal the system limit.
static void changeTextureSizeState(int delta)
{
	const int BUFSIZE = 1024;
	char buf[BUFSIZE];

	curOptionTextSize += delta;
	if (curOptionTextSize < 0) {
		curOptionTextSize = nbOptionsTextSize - 1;
	} else if (curOptionTextSize >= nbOptionsTextSize) {
		curOptionTextSize= 0;
	}

	snprintf(buf, BUFSIZE, "%d", textureSizeOptionList[curOptionTextSize]);
	GfuiLabelSetText(scrHandle, TextureSizeOptionId, buf);
}


// Scroll through texture anisotropic filtering modes supported by the system.
static void changeTextureAnisotropyState(int delta)
{
	curOptionTextAnisotropy += delta;
	if (curOptionTextAnisotropy < 0) {
		curOptionTextAnisotropy = nbOptionsTextAnisotropy - 1;
	} else if (curOptionTextAnisotropy >= nbOptionsTextAnisotropy) {
		curOptionTextAnisotropy = 0;
	}

	GfuiLabelSetText(scrHandle, TextureAnisotropyOptionId, textureAnisotropyOptionLabelList[curOptionTextAnisotropy]);
}


static void onActivate(void * /* dummy */)
{
	readOpenGLCfg();
}


// OpenGL menu
void * OpenGLMenuInit(void *prevMenu)
{
	int y, dy;

	// Has screen already been created?
	if (scrHandle) {
		return scrHandle;
	}

	prevHandle = prevMenu;

	scrHandle = GfuiScreenCreateExAction((float*)NULL, [] { onActivate(NULL); }, tGfuiAction(), 1);
	GfuiTitleCreate(scrHandle, "OpenGL Options", 0);
	GfuiScreenAddBgImg(scrHandle, "data/img/splash-simucfg.png");

	y = 400;
	dy = 30;

	const int xleft = 160;	// Center of left elements.
	const int xright = 480;	// Center of right elements.
	const int width = 240;	// Width of elements.

	y -= dy;

	// Texture compression.
	GfuiLabelCreate(scrHandle, "Texture Compression", GFUI_FONT_LARGE, xleft, 400, GFUI_ALIGN_HC_VB, 0);

	if (isCompressARBAvailable()) {
		GfuiGrButtonCreateAction(scrHandle, "data/img/arrow-left.png", "data/img/arrow-left.png",
				"data/img/arrow-left.png", "data/img/arrow-left-pushed.png",
				xleft-width/2, y, GFUI_ALIGN_HC_VB, 1,
				[] { changeTextureCompressState(-1); },
				tGfuiAction(), tGfuiAction());

		GfuiGrButtonCreateAction(scrHandle, "data/img/arrow-right.png", "data/img/arrow-right.png",
				"data/img/arrow-right.png", "data/img/arrow-right-pushed.png",
				xleft+width/2, y, GFUI_ALIGN_HC_VB, 1,
				[] { changeTextureCompressState(1); },
				tGfuiAction(), tGfuiAction());

		TextureCompressOptionId = GfuiLabelCreate(scrHandle, "", GFUI_FONT_LARGE_C, xleft, y, GFUI_ALIGN_HC_VB, 32);
		GfuiLabelSetColor(scrHandle, TextureCompressOptionId, LabelColor);
	} else {
		GfuiLabelCreate(scrHandle, "not available", GFUI_FONT_LARGE_C, xleft, y, GFUI_ALIGN_HC_VB, 0);
	}


	// Texture sizing.
	GfuiLabelCreate(scrHandle, "Texture Size Limit", GFUI_FONT_LARGE, xright, 400, GFUI_ALIGN_HC_VB, 0);

	GfuiGrButtonCreateAction(scrHandle, "data/img/arrow-left.png", "data/img/arrow-left.png",
			"data/img/arrow-left.png", "data/img/arrow-left-pushed.png",
			xright-width/2, y, GFUI_ALIGN_HC_VB, 0,
			[] { changeTextureSizeState(-1); },
			tGfuiAction(), tGfuiAction());

	GfuiGrButtonCreateAction(scrHandle, "data/img/arrow-right.png", "data/img/arrow-right.png",
			"data/img/arrow-right.png", "data/img/arrow-right-pushed.png",
			xright+width/2, y, GFUI_ALIGN_HC_VB, 0,
			[] { changeTextureSizeState(1); },
			tGfuiAction(), tGfuiAction());

	TextureSizeOptionId = GfuiLabelCreate(scrHandle, "", GFUI_FONT_LARGE_C, xright, y, GFUI_ALIGN_HC_VB, 32);
	GfuiLabelSetColor(scrHandle, TextureSizeOptionId, LabelColor);

	y -= 80;

	// Texture anisotropic filtering.
	GfuiLabelCreate(scrHandle, "Anisotropic Filtering", GFUI_FONT_LARGE, xleft, y + dy, GFUI_ALIGN_HC_VB, 0);

	if (isTextureAnisotropyAvailable()) {
		GfuiGrButtonCreateAction(scrHandle, "data/img/arrow-left.png", "data/img/arrow-left.png",
				"data/img/arrow-left.png", "data/img/arrow-left-pushed.png",
				xleft-width/2, y, GFUI_ALIGN_HC_VB, 1,
				[] { changeTextureAnisotropyState(-1); },
				tGfuiAction(), tGfuiAction());

		GfuiGrButtonCreateAction(scrHandle, "data/img/arrow-right.png", "data/img/arrow-right.png",
				"data/img/arrow-right.png", "data/img/arrow-right-pushed.png",
				xleft+width/2, y, GFUI_ALIGN_HC_VB, 1,
				[] { changeTextureAnisotropyState(1); },
				tGfuiAction(), tGfuiAction());

		TextureAnisotropyOptionId = GfuiLabelCreate(scrHandle, "", GFUI_FONT_LARGE_C, xleft, y, GFUI_ALIGN_HC_VB, 32);
		GfuiLabelSetColor(scrHandle, TextureAnisotropyOptionId, LabelColor);
	} else {
		GfuiLabelCreate(scrHandle, "not available", GFUI_FONT_LARGE_C, xleft, y, GFUI_ALIGN_HC_VB, 0);
	}


	GfuiButtonCreateAction(scrHandle, "Accept", GFUI_FONT_LARGE, 210, 40, 150, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
	[] { saveOpenGLOption(NULL); }, tGfuiAction(), tGfuiAction());

	GfuiButtonCreateAction(scrHandle, "Cancel", GFUI_FONT_LARGE, 430, 40, 150, GFUI_ALIGN_HC_VB, GFUI_MOUSE_UP,
	[prevMenu] { GfuiScreenActivate(prevMenu); }, tGfuiAction(), tGfuiAction());

	GfuiAddKeyAction(scrHandle, 13, "Save", [] { saveOpenGLOption(NULL); }, tGfuiAction());
	GfuiAddKeyAction(scrHandle, 27, "Cancel Selection", [prevMenu] { GfuiScreenActivate(prevMenu); }, tGfuiAction());
	GfuiAddSKeyAction(scrHandle, GLUT_KEY_F12, "Screen-Shot", [] { GfuiScreenShot(NULL); }, tGfuiAction());
	GfuiAddSKeyAction(scrHandle, GLUT_KEY_LEFT, "Previous Option in list", [] { changeTextureCompressState(-1); }, tGfuiAction());
	GfuiAddSKeyAction(scrHandle, GLUT_KEY_RIGHT, "Next Option in list", [] { changeTextureCompressState(1); }, tGfuiAction());

	readOpenGLCfg();

	return scrHandle;
}
