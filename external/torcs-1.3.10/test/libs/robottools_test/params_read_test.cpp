/***************************************************************************

    file                 : params_read_test.cpp
    created              : September 29 2026
    copyright            : (C) 2026 by Bernhard Wymann
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

#include <windows.h>
#include <fstream>
#include <gtest/gtest.h>
#include <tgf.h>

// These internal entry points are not declared in the public tgf.h API.
extern void GfParmInit(void);
extern void GfParmShutdown(void);
extern void* GfParmReadBuf(char* buffer);

class GfParmReadTest : public ::testing::Test
{
protected:
	char filename[MAX_PATH] = {};

	void SetUp() override
	{
		GfParmInit();
	}

	void TearDown() override
	{
		GfParmShutdown();
		if (filename[0]) {
			EXPECT_NE(DeleteFileA(filename), 0);
		}
	}
};

TEST_F(GfParmReadTest, MalformedBufferReturnsNull)
{
	// Valid TORCS attributes, but a mismatched closing tag makes XML_Parse fail.
	char xml[] = "<params name=\"test\"><section name=\"test\"></params>";
	EXPECT_EQ(GfParmReadBuf(xml), nullptr);
}

TEST_F(GfParmReadTest, MalformedFileReturnsNull)
{
	char directory[MAX_PATH];
	DWORD length = GetTempPathA(MAX_PATH, directory);
	ASSERT_GT(length, 0u);
	ASSERT_LT(length, static_cast<DWORD>(MAX_PATH));
	ASSERT_NE(GetTempFileNameA(directory, "tgf", 0, filename), 0u);

	std::ofstream file(filename, std::ios::binary);
	ASSERT_TRUE(file.is_open());
	file << "<params name=\"test\"><section name=\"test\"></params>";
	file.close();
	ASSERT_FALSE(file.fail());

	EXPECT_EQ(GfParmReadFile(filename, GFPARM_RMODE_PRIVATE), nullptr);
}
