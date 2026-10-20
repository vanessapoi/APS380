/***************************************************************************

    file                 : learning_test.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/
/***************************************************************************
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 ***************************************************************************/
#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <chrono>
#include <cstring>
#include <limits>
#include <vector>
#include "learn.h"

TEST(Learning, NativeRadiusCorrectionsSurviveSaveAndReload)
{
	// Actual production serialization, with no user directories or source-text assertions.
	std::filesystem::path directory = std::filesystem::temp_directory_path()/
		("olethros-learning-"+std::to_string(GetCurrentProcessId())+"-"+
		std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
	ASSERT_TRUE(std::filesystem::create_directory(directory));
	struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code error; std::filesystem::remove_all(path,error); } } cleanup{directory};
	tTrackSeg segs[3] = {};
	for (int i = 0; i < 3; ++i) { segs[i].id = i; segs[i].type = TR_LFT; segs[i].length = 10; segs[i].next = &segs[(i+1)%3]; segs[i].prev = &segs[(i+2)%3]; }
	tTrack track = {}; track.seg = &segs[2]; track.nseg = 3; track.width = 10;
	std::string first = (directory/"first.brain").string(), second = (directory/"second.brain").string();
	SegLearn original(&track); original.saveParameters(&first[0]);
	// Populate a nonzero radius fixture in the native-format RADI payload.
	std::fstream file(first,std::ios::binary|std::ios::in|std::ios::out);
	ASSERT_TRUE(file.is_open());
	// Tags include their terminating NUL in the native format.
	file.seekp(sizeof("OLETHROS_LEARN")+sizeof(int)+sizeof("RADI"));
	const float radii[] = {1.25f,-2.5f,3.75f};
	file.write(reinterpret_cast<const char*>(radii),sizeof(radii)); file.close();
	SegLearn loaded(&track); loaded.loadParameters(&first[0]);
	for (int i = 0; i < 3; ++i) EXPECT_FLOAT_EQ(loaded.getRadius(&segs[i]),radii[i]);
	loaded.saveParameters(&second[0]);
	SegLearn reloaded(&track); reloaded.loadParameters(&second[0]);
	for (int i = 0; i < 3; ++i) EXPECT_FLOAT_EQ(reloaded.getRadius(&segs[i]),radii[i]);
}

class BrainFileTest : public testing::Test {
protected:
	std::filesystem::path directory;
	tTrackSeg segments[3] = {};
	tTrack track = {};
	std::vector<char> valid;
	std::vector<size_t> tags;
	std::vector<size_t> values;
	std::string name(const char* file) const { return (directory/file).string(); }
	static std::vector<char> read(const std::string& file)
	{
		std::ifstream stream(file, std::ios::binary);
		return std::vector<char>(std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>());
	}
	static void write(const std::string& file, const std::vector<char>& bytes)
	{
		std::ofstream stream(file, std::ios::binary);
		stream.write(bytes.data(), bytes.size());
	}
	void SetUp() override
	{
		directory = std::filesystem::temp_directory_path()/
			("olethros-brain-review-"+std::to_string(GetCurrentProcessId())+"-"+
			std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
		ASSERT_TRUE(std::filesystem::create_directory(directory));
		for (int i = 0; i < 3; ++i) {
			segments[i].id = i; segments[i].type = TR_LFT; segments[i].length = 10;
			segments[i].next = &segments[(i+1)%3]; segments[i].prev = &segments[(i+2)%3];
		}
		track.seg = &segments[2]; track.nseg = 3; track.width = 10;
		SegLearn source(&track);
		source.saveParameters(name("valid.brain").c_str());
		valid = read(name("valid.brain"));
		ASSERT_FALSE(valid.empty());
		// Existing on-disk tags include NUL; no new format/version is introduced.
		tags = {0, sizeof("OLETHROS_LEARN")+sizeof(int)};
		size_t offset = tags.back()+sizeof("RADI");
		for (int i = 0; i < 3; ++i, offset += sizeof(float)) values.push_back(offset);
		tags.push_back(offset); offset += sizeof("DM FRICTION");
		for (int i = 0; i < 12; ++i, offset += sizeof(float)) values.push_back(offset);
		tags.push_back(offset); offset += sizeof("PRED ACCEL");
		for (int i = 0; i < 4; ++i, offset += sizeof(float)) values.push_back(offset);
		tags.push_back(offset); offset += sizeof("PRED STEER");
		for (int i = 0; i < 4; ++i, offset += sizeof(float)) values.push_back(offset);
		tags.push_back(offset);
		ASSERT_EQ(offset+sizeof("END"), valid.size());
		for (size_t i = 0; i < values.size(); ++i) {
			float value = (float)(0.125*(i+1));
			memcpy(valid.data()+values[i], &value, sizeof(value));
		}
		write(name("valid.brain"), valid);
	}
	void TearDown() override { std::error_code error; std::filesystem::remove_all(directory, error); }
	void expectRejected(const std::vector<char>& bytes)
	{
		write(name("bad.brain"), bytes);
		SegLearn destination(&track);
		destination.loadParameters(name("valid.brain").c_str());
		testing::internal::CaptureStderr();
		EXPECT_EQ(destination.loadParameters(name("bad.brain").c_str()), SegLearn::BRAIN_REJECTED);
		std::string diagnostic = testing::internal::GetCapturedStderr();
		EXPECT_NE(diagnostic.find("ignoring"), std::string::npos);
		destination.saveParameters(name("after.brain").c_str());
		EXPECT_EQ(read(name("after.brain")), valid); // All arrays/scalars, not just radius.
		EXPECT_EQ(read(name("bad.brain")), bytes); // Invalid input is never overwritten on load.
	}
};

TEST_F(BrainFileTest, ExistingFormatRoundTripsAllLearnedArrays)
{
	SegLearn destination(&track);
	EXPECT_EQ(destination.loadParameters(name("valid.brain").c_str()), SegLearn::BRAIN_LOADED);
	destination.saveParameters(name("roundtrip.brain").c_str());
	EXPECT_EQ(read(name("roundtrip.brain")), valid);
	EXPECT_FALSE(std::filesystem::exists(name("roundtrip.brain.tmp")));
}

TEST_F(BrainFileTest, EveryTruncationLeavesPriorLearningUntouched)
{
	for (size_t length = 0; length < valid.size(); ++length) {
		SCOPED_TRACE(length);
		expectRejected(std::vector<char>(valid.begin(), valid.begin()+length));
	}
}

TEST_F(BrainFileTest, BadTagsDimensionsAndTrailingDataAreRejected)
{
	for (size_t offset : tags) {
		std::vector<char> bytes = valid; bytes[offset] ^= 1; expectRejected(bytes);
	}
	std::vector<char> bytes = valid; int incompatible = 5000;
	memcpy(bytes.data()+sizeof("OLETHROS_LEARN"), &incompatible, sizeof(incompatible));
	expectRejected(bytes);
	bytes = valid; bytes.push_back('x'); expectRejected(bytes);
}

TEST_F(BrainFileTest, NonfiniteValuesInAnyArrayAreRejected)
{
	for (size_t offset : values) for (float value : {std::numeric_limits<float>::quiet_NaN(),
		std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity()}) {
		std::vector<char> bytes = valid; memcpy(bytes.data()+offset, &value, sizeof(value));
		expectRejected(bytes);
	}
}

TEST_F(BrainFileTest, MissingFileIsQuietAndPreservesLearning)
{
	SegLearn destination(&track); destination.loadParameters(name("valid.brain").c_str());
	testing::internal::CaptureStderr();
	EXPECT_EQ(destination.loadParameters(name("missing.brain").c_str()), SegLearn::BRAIN_MISSING);
	EXPECT_TRUE(testing::internal::GetCapturedStderr().empty());
	destination.saveParameters(name("after.brain").c_str()); EXPECT_EQ(read(name("after.brain")), valid);
}

TEST_F(BrainFileTest, FailedReplacementRetainsExistingBrain)
{
	// Windows denies replacement while a reader omits FILE_SHARE_DELETE.
	HANDLE reader = CreateFileA(name("valid.brain").c_str(), GENERIC_READ, FILE_SHARE_READ,
		NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
	ASSERT_NE(reader, INVALID_HANDLE_VALUE);
	SegLearn different(&track);
	testing::internal::CaptureStderr(); different.saveParameters(name("valid.brain").c_str());
	std::string diagnostic = testing::internal::GetCapturedStderr();
	CloseHandle(reader);
	EXPECT_NE(diagnostic.find("previous file retained"), std::string::npos);
	EXPECT_EQ(read(name("valid.brain")), valid);
	EXPECT_FALSE(std::filesystem::exists(name("valid.brain.tmp")));
}

TEST_F(BrainFileTest, UnreadableFileHasDistinctOutcomeAndPreservesLearning)
{
	SegLearn destination(&track);
	ASSERT_EQ(destination.loadParameters(name("valid.brain").c_str()), SegLearn::BRAIN_LOADED);
	HANDLE lock = CreateFileA(name("valid.brain").c_str(), GENERIC_READ, 0,
		NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
	ASSERT_NE(lock, INVALID_HANDLE_VALUE);
	testing::internal::CaptureStderr();
	EXPECT_EQ(destination.loadParameters(name("valid.brain").c_str()), SegLearn::BRAIN_IO_ERROR);
	std::string diagnostic = testing::internal::GetCapturedStderr();
	CloseHandle(lock);
	EXPECT_NE(diagnostic.find("cannot read brain"), std::string::npos);
	destination.saveParameters(name("after.brain").c_str());
	EXPECT_EQ(read(name("after.brain")), valid);
}

TEST_F(BrainFileTest, RepeatedRejectedLoadsReleaseFileHandles)
{
	std::vector<char> bytes = valid; int incompatible = 5000;
	memcpy(bytes.data()+sizeof("OLETHROS_LEARN"), &incompatible, sizeof(incompatible));
	write(name("bad.brain"), bytes);
	SegLearn destination(&track);
	DWORD before = 0, after = 0;
	testing::internal::CaptureStderr();
	ASSERT_TRUE(GetProcessHandleCount(GetCurrentProcess(), &before));
	for (int i = 0; i < 1000; ++i) destination.loadParameters(name("bad.brain").c_str());
	ASSERT_TRUE(GetProcessHandleCount(GetCurrentProcess(), &after));
	testing::internal::GetCapturedStderr();
	EXPECT_EQ(after, before);
}
