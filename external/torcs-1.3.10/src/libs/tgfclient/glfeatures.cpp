/***************************************************************************

    file                 : glfeatures.cpp
    created              : Wed Jun 1 14:56:31 CET 2005
    copyright            : (C) 2005-2026 by Bernhard Wymann

***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/


/*
	Functions to check if features seems to be available and requested by the
	user. The isAvailable functions should return if a feature is working on
	the system, the isEnabled feature should check if the user wants to enable
	it as well.
	It should NOT check if the features are really working, that is subject
	to another part eventually.
*/

#include <glfeatures.h>
#include <portability.h>

/*
	----------------------- Texture Compression
*/


static bool compressARBAvailable;
static bool compressARBEnabled;

// Feature checks, GL_ARB_texture_compression.
void checkCompressARBAvailable(bool &result)
{
	// Query if the extension is avaiable at the runtime system (true, if > 0).
	int compressARB = GfuiGlutExtensionSupported("GL_ARB_texture_compression");
	// Check if at least one internal format is vailable. This is a workaround for
	// driver problems and not a bugfix. According to the specification OpenGL should
	// choose an uncompressed alternate format if it can't provide the requested
	// compressed one... but it does not on all cards/drivers.
	if (compressARB) {
		int numformats;
		glGetIntegerv(GL_NUM_COMPRESSED_TEXTURE_FORMATS_ARB, &numformats);
		if (numformats == 0) {
			compressARB = 0;
		}
	}

	result = (compressARB > 0) ? true : false;
}


void checkCompressARBEnabled(bool &result)
{
	if (!isCompressARBAvailable()) {
		// Feature not available, do not use it.
		result = false;
	} else {
		// Feature available, check if the user wants to use it.
		// TODO: put this enabled/disable stuff in one function (it is used in grsound.cpp as well).
		const char *tcEnabledStr = GR_ATT_TEXTURECOMPRESSION_ENABLED;
		const int BUFSIZE = 1024;
		char fnbuf[BUFSIZE];
		snprintf(fnbuf, BUFSIZE, "%s%s", GetLocalDir(), GR_PARAM_FILE);
		void *paramHandle = GfParmReadFile(fnbuf, GFPARM_RMODE_REREAD | GFPARM_RMODE_CREAT);
		const char *optionName = GfParmGetStr(paramHandle, GR_SCT_GLFEATURES, GR_ATT_TEXTURECOMPRESSION, GR_ATT_TEXTURECOMPRESSION_DISABLED);

		if (strcmp(optionName, tcEnabledStr) != 0) {
			result = false;
		} else {
			result = true;
		}
		GfParmReleaseHandle(paramHandle);
	}
}


void updateCompressARBEnabled(void)
{
	checkCompressARBEnabled(compressARBEnabled);
}


// GL_ARB_texture_compression
bool isCompressARBAvailable(void)
{
	return compressARBAvailable;
}


bool isCompressARBEnabled(void) {
	return compressARBEnabled;
}


/*
	----------------------- Texture downsizing.
*/
static int glTextureMaxSize;
static int userTextureMaxSize;


void getGLTextureMaxSize(int &result)
{
	glGetIntegerv(GL_MAX_TEXTURE_SIZE, &result);
	if (result > 16384) {
		result = 16384;
	}
}


void getUserTextureMaxSize(int &result)
{
	const int BUFSIZE = 1024;
	char fnbuf[BUFSIZE];
	snprintf(fnbuf, BUFSIZE, "%s%s", GetLocalDir(), GR_PARAM_FILE);
	void *paramHandle = GfParmReadFile(fnbuf, GFPARM_RMODE_REREAD | GFPARM_RMODE_CREAT);
	result = (int) GfParmGetNum(paramHandle, GR_SCT_GLFEATURES, GR_ATT_TEXTURESIZE, (char*)NULL, (tdble) glTextureMaxSize);
	if (result > glTextureMaxSize) {
		result = glTextureMaxSize;
	}
	GfParmReleaseHandle(paramHandle);
}


void updateUserTextureMaxSize(void)
{
	getUserTextureMaxSize(userTextureMaxSize);
}

int getGLTextureMaxSize(void)
{
	return glTextureMaxSize;
}


int getUserTextureMaxSize(void)
{
	return userTextureMaxSize;
}


/*
	----------------------- Texture anisotropic filtering.
*/
static bool textureAnisotropyAvailable;
static int glTextureMaxAnisotropy;
static int userTextureAnisotropy;


static int getBestTextureAnisotropy(int requested)
{
	static const int textureAnisotropyOptionList[] = {2, 4, 8, 16};
	int result = 0;
	int maxAnisotropy = (glTextureMaxAnisotropy < 16) ? glTextureMaxAnisotropy : 16;

	for (int i = 0; i < (int)(sizeof(textureAnisotropyOptionList) / sizeof(textureAnisotropyOptionList[0])); i++) {
		if (textureAnisotropyOptionList[i] <= requested && textureAnisotropyOptionList[i] <= maxAnisotropy) {
			result = textureAnisotropyOptionList[i];
		}
	}

	return result;
}


void checkTextureAnisotropyAvailable(bool &result, int &maxAnisotropy)
{
	result = false;
	maxAnisotropy = 1;

	if (!GfuiGlutExtensionSupported("GL_EXT_texture_filter_anisotropic")) {
		return;
	}

	GLfloat maxValue = 1.0f;
	glGetFloatv(GL_MAX_TEXTURE_MAX_ANISOTROPY_EXT, &maxValue);
	if (maxValue >= 2.0f) {
		result = true;
		maxAnisotropy = (int)maxValue;
	}
}


void getUserTextureAnisotropy(int &result)
{
	if (!textureAnisotropyAvailable) {
		result = 0;
		return;
	}

	const int BUFSIZE = 1024;
	char fnbuf[BUFSIZE];
	snprintf(fnbuf, BUFSIZE, "%s%s", GetLocalDir(), GR_PARAM_FILE);
	void *paramHandle = GfParmReadFile(fnbuf, GFPARM_RMODE_REREAD | GFPARM_RMODE_CREAT);
	int anisotropy = (int)GfParmGetNum(paramHandle, GR_SCT_GLFEATURES, GR_ATT_TEXTUREANISOTROPY, (char*)NULL, -1);
	if (anisotropy < 0) {
		result = getBestTextureAnisotropy(glTextureMaxAnisotropy);
	} else if (anisotropy < 2) {
		result = 0;
	} else {
		result = getBestTextureAnisotropy(anisotropy);
	}
	GfParmReleaseHandle(paramHandle);
}


void updateUserTextureAnisotropy(void)
{
	getUserTextureAnisotropy(userTextureAnisotropy);
}


bool isTextureAnisotropyAvailable(void)
{
	return textureAnisotropyAvailable;
}


int getGLTextureMaxAnisotropy(void)
{
	return glTextureMaxAnisotropy;
}


int getUserTextureAnisotropy(void)
{
	return userTextureAnisotropy;
}


void applyUserTextureAnisotropy(void)
{
	if (!textureAnisotropyAvailable) {
		return;
	}

	glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAX_ANISOTROPY_EXT,
					(userTextureAnisotropy >= 2) ? (GLfloat)userTextureAnisotropy : 1.0f);
}


// Initialize
void checkGLFeatures(void) {
	checkCompressARBAvailable(compressARBAvailable);
	checkCompressARBEnabled(compressARBEnabled);
	getGLTextureMaxSize(glTextureMaxSize);
	getUserTextureMaxSize(userTextureMaxSize);
	checkTextureAnisotropyAvailable(textureAnisotropyAvailable, glTextureMaxAnisotropy);
	getUserTextureAnisotropy(userTextureAnisotropy);
}

