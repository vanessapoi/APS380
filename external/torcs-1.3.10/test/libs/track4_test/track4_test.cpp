/***************************************************************************

    file                 : track4_test.cpp
    created              : Sat Jul 25 00:00:00 CEST 2026
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

/**
    @file
    Characterization tests for the version 4 track loader.
*/

#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include <gtest/gtest.h>

#include <tgf.h>
#include <robottools.h>
#include <track.h>


#undef malloc
#undef calloc
#undef free


static const float kEps = 1e-5f;


static size_t FailMallocSize;
static size_t FailCallocSize;
static bool FailVsnprintf;
static bool ForceDuplicateSegment;
static std::vector<void*> ReleasedParmHandles;
static unsigned int NextParmFileId;


static void resetFaultInjection()
{
	FailMallocSize = 0;
	FailCallocSize = 0;
	FailVsnprintf = false;
	ForceDuplicateSegment = false;
	ReleasedParmHandles.clear();
}


static void* track4TestMalloc(size_t size)
{
	if ((FailMallocSize != 0) && (FailMallocSize == size)) {
		FailMallocSize = 0;
		return nullptr;
	}
	return _tgf_win_malloc(size);
}


static void* track4TestCalloc(size_t count, size_t size)
{
	if ((FailCallocSize != 0) && (FailCallocSize == count * size)) {
		FailCallocSize = 0;
		return nullptr;
	}
	return _tgf_win_calloc(count, size);
}


static void track4TestFree(void* memory)
{
	_tgf_win_free(memory);
}


static int track4TestVsnprintf(char* buffer, size_t size, const char* format, va_list args)
{
	if (FailVsnprintf) {
		FailVsnprintf = false;
		return -1;
	}
	return vsnprintf(buffer, size, format, args);
}


static const void* track4TestHashGetStr(void* hash, const char* key)
{
	if (ForceDuplicateSegment) {
		return reinterpret_cast<void*>(1);
	}
	return GfHashGetStr(hash, key);
}


static void track4TestFatal(const char* format, ...)
{
	char message[512];
	va_list args;
	va_start(args, format);
	vsnprintf(message, sizeof(message), format, args);
	va_end(args);
	printf("%s", message);
	fprintf(stderr, "%s", message);
}


static void track4TestExit(int status)
{
	fprintf(stderr, "TRACK4_TEST_EXPLICIT_EXIT_%d\n", status);
	fflush(stderr);
	std::_Exit(status);
}


#undef GfFatal
#define GfFatal track4TestFatal
#define malloc track4TestMalloc
#define calloc track4TestCalloc
#define free track4TestFree
#define vsnprintf track4TestVsnprintf
#define GfHashGetStr track4TestHashGetStr
#define exit track4TestExit
#include "../../../src/modules/track/track4.cpp"
#undef exit
#undef GfHashGetStr
#undef vsnprintf
#undef free
#undef calloc
#undef malloc
#undef GfFatal


static void track4TestParmReleaseHandle(void* handle)
{
	ReleasedParmHandles.push_back(handle);
	GfParmReleaseHandle(handle);
}


void ReadTrack3(tTrack*, void*, tRoadCam**, int)
{
	ADD_FAILURE() << "TrackBuildEx unexpectedly selected the version 3 loader";
}


#define malloc track4TestMalloc
#define calloc track4TestCalloc
#define free track4TestFree
#define GfParmReleaseHandle track4TestParmReleaseHandle
#include "../../../src/modules/track/track.cpp"
#undef GfParmReleaseHandle
#undef free
#undef calloc
#undef malloc


static void freeSegmentTree(tTrackSeg* segment)
{
	if (!segment) {
		return;
	}
	_tgf_win_free(segment->barrier[TR_SIDE_RGT]);
	_tgf_win_free(segment->barrier[TR_SIDE_LFT]);
	if (segment->ext) {
		_tgf_win_free(segment->ext->marks);
		_tgf_win_free(segment->ext);
	}
	freeSegmentTree(segment->lside);
	freeSegmentTree(segment->rside);
	_tgf_win_free(segment);
}


static void freeTrackModel(tTrack* track, tRoadCam** cameraList)
{
	if (track->seg) {
		tTrackSeg* segment = track->seg;
		for (int i = 0; i < track->nseg; i++) {
			tTrackSeg* next = segment->next;
			freeSegmentTree(segment);
			segment = next;
		}
	}

	tTrackSurface* surface = track->surfaces;
	while (surface) {
		tTrackSurface* next = surface->next;
		_tgf_win_free(surface);
		surface = next;
	}

	_tgf_win_free(track->pits.driversPits);

	if (*cameraList) {
		tRoadCam* camera = (*cameraList)->next;
		while (camera != *cameraList) {
			tRoadCam* next = camera->next;
			_tgf_win_free(camera);
			camera = next;
		}
		_tgf_win_free(*cameraList);
	}

	memset(track, 0, sizeof(*track));
	*cameraList = nullptr;
}


class Track4Test : public testing::Test {
protected:
	void SetUp() override
	{
		resetFaultInjection();
		memset(&track, 0, sizeof(track));
		cameras = nullptr;
		parmFile = "track4_test_params_" + std::to_string(++NextParmFileId) + ".xml";
		handle = GfParmReadFile(parmFile.c_str(), GFPARM_RMODE_CREAT | GFPARM_RMODE_PRIVATE);
		ASSERT_NE(nullptr, handle);
	}

	void TearDown() override
	{
		resetFaultInjection();
		freeTrackModel(&track, &cameras);
		if (handle) {
			GfParmReleaseHandle(handle);
			handle = nullptr;
		}
		std::remove(parmFile.c_str());
	}

	std::string segmentPath(const char* name) const
	{
		return std::string(TRK_SECT_MAIN) + "/" + TRK_LST_SEGMENTS + "/" + name;
	}

	std::string mainChildPath(const char* name) const
	{
		return std::string(TRK_SECT_MAIN) + "/" + name;
	}

	std::string segmentChildPath(const char* segmentName, const char* childName) const
	{
		return segmentPath(segmentName) + "/" + childName;
	}

	void setNum(const std::string& path, const char* key, tdble value)
	{
		ASSERT_EQ(0, GfParmSetNum(handle, path.c_str(), key, nullptr, value));
	}

	void setStr(const std::string& path, const char* key, const char* value)
	{
		ASSERT_EQ(0, GfParmSetStr(handle, path.c_str(), key, value));
	}

	void setMainNum(const char* key, tdble value)
	{
		setNum(TRK_SECT_MAIN, key, value);
	}

	void setMainStr(const char* key, const char* value)
	{
		setStr(TRK_SECT_MAIN, key, value);
	}

	void addStraight(const char* name, tdble length)
	{
		const std::string path = segmentPath(name);
		setStr(path, TRK_ATT_TYPE, TRK_VAL_STR);
		setNum(path, TRK_ATT_LG, length);
	}

	void addTurn(const char* name, int type, tdble radius, tdble arc)
	{
		const std::string path = segmentPath(name);
		setStr(path, TRK_ATT_TYPE, type == TR_LFT ? TRK_VAL_LFT : TRK_VAL_RGT);
		setNum(path, TRK_ATT_RADIUS, radius);
		setNum(path, TRK_ATT_ARC, arc);
	}

	void setDefaultSide(int side, tdble width, const char* bankType, const char* material)
	{
		const char* section = side == TR_SIDE_RGT ? TRK_SECT_RSIDE : TRK_SECT_LSIDE;
		const std::string path = mainChildPath(section);
		setNum(path, TRK_ATT_WIDTH, width);
		setStr(path, TRK_ATT_BANKTYPE, bankType);
		setStr(path, TRK_ATT_SURF, material);
	}

	void setDefaultBorder(int side, tdble width, tdble height, const char* style, const char* material)
	{
		const char* section = side == TR_SIDE_RGT ? TRK_SECT_RBORDER : TRK_SECT_LBORDER;
		const std::string path = mainChildPath(section);
		setNum(path, TRK_ATT_WIDTH, width);
		setNum(path, TRK_ATT_HEIGHT, height);
		setStr(path, TRK_ATT_STYLE, style);
		setStr(path, TRK_ATT_SURF, material);
	}

	void setDefaultBarrier(int side, tdble width, tdble height, const char* style, const char* material)
	{
		const char* section = side == TR_SIDE_RGT ? TRK_SECT_RBARRIER : TRK_SECT_LBARRIER;
		const std::string path = mainChildPath(section);
		setNum(path, TRK_ATT_WIDTH, width);
		setNum(path, TRK_ATT_HEIGHT, height);
		setStr(path, TRK_ATT_STYLE, style);
		setStr(path, TRK_ATT_SURF, material);
	}

	void setSegmentSideWidths(const char* segmentName, int side, tdble startWidth, tdble endWidth)
	{
		const char* section = side == TR_SIDE_RGT ? TRK_SECT_RSIDE : TRK_SECT_LSIDE;
		const std::string path = segmentChildPath(segmentName, section);
		setNum(path, TRK_ATT_SWIDTH, startWidth);
		setNum(path, TRK_ATT_EWIDTH, endWidth);
	}

	void setSurface(const char* material, tdble friction, tdble rollResistance,
		tdble roughness, tdble waveLength, tdble damage, tdble rebound)
	{
		const std::string path = std::string(TRK_SECT_SURFACES) + "/" + material;
		setNum(path, TRK_ATT_FRICTION, friction);
		setNum(path, TRK_ATT_ROLLRES, rollResistance);
		setNum(path, TRK_ATT_ROUGHT, roughness);
		setNum(path, TRK_ATT_ROUGHTWL, waveLength);
		setNum(path, TRK_ATT_DAMMAGE, damage);
		setNum(path, TRK_ATT_REBOUND, rebound);
	}

	void setPits(const char* entry, const char* exit, const char* start, const char* end,
		const char* side, tdble length = 15.0f, tdble width = 5.0f)
	{
		const std::string path = mainChildPath(TRK_SECT_PITS);
		if (entry) {
			setStr(path, TRK_ATT_ENTRY, entry);
		}
		if (exit) {
			setStr(path, TRK_ATT_EXIT, exit);
		}
		if (start) {
			setStr(path, TRK_ATT_START, start);
		}
		if (end) {
			setStr(path, TRK_ATT_END, end);
		}
		setStr(path, TRK_ATT_SIDE, side);
		setNum(path, TRK_ATT_LEN, length);
		setNum(path, TRK_ATT_WIDTH, width);
		setNum(path, TRK_ATT_SPD_LIM, 22.0f);
	}

	void addCamera(const char* name, const char* segment, const char* fovStart, const char* fovEnd,
		tdble toRight = 0.0f, tdble toStart = 0.0f, tdble height = 0.0f)
	{
		const std::string path = std::string(TRK_SECT_CAM) + "/" + name;
		if (segment) {
			setStr(path, TRK_ATT_SEGMENT, segment);
		}
		if (fovStart) {
			setStr(path, TRK_ATT_CAM_FOV, fovStart);
		}
		if (fovEnd) {
			setStr(path, TRK_ATT_CAM_FOVE, fovEnd);
		}
		setNum(path, TRK_ATT_TORIGHT, toRight);
		setNum(path, TRK_ATT_TOSTART, toStart);
		setNum(path, TRK_ATT_HEIGHT, height);
	}

	tTrackSeg* segmentAt(int index) const
	{
		if (!track.seg || (index < 0) || (index >= track.nseg)) {
			return nullptr;
		}
		tTrackSeg* segment = track.seg->next;
		for (int i = 0; i < index; i++) {
			segment = segment->next;
		}
		return segment;
	}

	int surfaceCount() const
	{
		int count = 0;
		for (tTrackSurface* surface = track.surfaces; surface; surface = surface->next) {
			count++;
		}
		return count;
	}

	void build(int ext = 0)
	{
		ReadTrack4(&track, handle, &cameras, ext);
	}

	void* handle;
	tTrack track;
	tRoadCam* cameras;
	std::string parmFile;
};


class TrackBuildExTest : public testing::Test {
protected:
	void SetUp() override
	{
		resetFaultInjection();
		ASSERT_EQ(nullptr, theTrack);
		ASSERT_EQ(nullptr, TrackHandle);

		parmFile = "track_build_ex_test_params_" + std::to_string(++NextParmFileId) + ".xml";
		void* writer = GfParmReadFile(parmFile.c_str(), GFPARM_RMODE_CREAT | GFPARM_RMODE_PRIVATE);
		ASSERT_NE(nullptr, writer);
		ASSERT_EQ(0, GfParmSetNum(writer, TRK_SECT_HDR, TRK_ATT_VERSION, nullptr, 4.0f));
		const std::string segmentPath = std::string(TRK_SECT_MAIN) + "/" + TRK_LST_SEGMENTS + "/straight";
		ASSERT_EQ(0, GfParmSetStr(writer, segmentPath.c_str(), TRK_ATT_TYPE, TRK_VAL_STR));
		ASSERT_EQ(0, GfParmSetNum(writer, segmentPath.c_str(), TRK_ATT_LG, nullptr, 20.0f));
		ASSERT_EQ(0, GfParmWriteFile(parmFile.c_str(), writer, "track-build-ex-test"));
		GfParmReleaseHandle(writer);
	}

	void TearDown() override
	{
		if (theTrack) {
			if (!TrackHandle) {
				TrackHandle = theTrack->params;
			}
			TrackShutdown();
		}
		TrackHandle = nullptr;
		std::remove(parmFile.c_str());
		resetFaultInjection();
	}

	std::string parmFile;
};


TEST_F(TrackBuildExTest, OwnsParameterHandleAndClearsItOnShutdown)
{
	tTrack* builtTrack = TrackBuildEx(parmFile.data());

	ASSERT_NE(nullptr, builtTrack);
	ASSERT_EQ(builtTrack->params, TrackHandle);
	void* const ownedHandle = TrackHandle;

	TrackShutdown();

	EXPECT_EQ(nullptr, theTrack);
	EXPECT_EQ(nullptr, TrackHandle);
	ASSERT_EQ(1U, ReleasedParmHandles.size());
	EXPECT_EQ(ownedHandle, ReleasedParmHandles[0]);
}


TEST_F(TrackBuildExTest, ReleasesPreviousTrackBeforeRepeatedBuild)
{
	tTrack* firstTrack = TrackBuildEx(parmFile.data());
	ASSERT_NE(nullptr, firstTrack);
	void* const firstHandle = firstTrack->params;
	if (TrackHandle != firstHandle) {
		TrackHandle = firstHandle;
	}
	ReleasedParmHandles.clear();

	tTrack* secondTrack = TrackBuildEx(parmFile.data());
	ASSERT_NE(nullptr, secondTrack);
	void* const secondHandle = secondTrack->params;
	const bool releasedFirst = (ReleasedParmHandles.size() == 1) &&
		(ReleasedParmHandles[0] == firstHandle);

	EXPECT_TRUE(releasedFirst);
	EXPECT_EQ(secondHandle, TrackHandle);

	if (!releasedFirst) {
		TrackHandle = secondHandle;
		TrackShutdown();
		theTrack = firstTrack;
		TrackHandle = firstHandle;
		TrackShutdown();
		return;
	}

	TrackShutdown();
	EXPECT_EQ(nullptr, theTrack);
	EXPECT_EQ(nullptr, TrackHandle);
	ASSERT_EQ(2U, ReleasedParmHandles.size());
	EXPECT_EQ(secondHandle, ReleasedParmHandles[1]);
}


TEST(TrackShutdownTest, ReleasesPartiallyBuiltTrackWithoutSegmentRing)
{
	EXPECT_EXIT(
		{
			theTrack = (tTrack*)track4TestCalloc(1, sizeof(tTrack));
			TrackHandle = GfParmReadFile("track_shutdown_test_params.xml",
				GFPARM_RMODE_CREAT | GFPARM_RMODE_PRIVATE);
			if (!theTrack || !TrackHandle) {
				exit(2);
			}
			theTrack->params = TrackHandle;
			theCamList = nullptr;
			void* const ownedHandle = TrackHandle;
			ReleasedParmHandles.clear();

			TrackShutdown();
			if (theTrack || TrackHandle || (ReleasedParmHandles.size() != 1) ||
				(ReleasedParmHandles[0] != ownedHandle)) {
				exit(3);
			}
			exit(0);
		},
		testing::ExitedWithCode(0), "");
}


TEST_F(Track4Test, BuildsMinimalStraightWithDefaultSurfacesAndBarriers)
{
	addStraight("start", 120.0f);

	build();

	ASSERT_NE(nullptr, track.seg);
	EXPECT_EQ(1, track.nseg);
	EXPECT_EQ(track.seg, track.seg->next);
	EXPECT_EQ(track.seg, track.seg->prev);
	EXPECT_EQ(TR_STR, track.seg->type);
	EXPECT_EQ(TR_MAIN, track.seg->type2);
	EXPECT_STREQ("start", track.seg->name);
	EXPECT_EQ(0, track.seg->id);
	EXPECT_NEAR(120.0f, track.seg->length, kEps);
	EXPECT_NEAR(120.0f, track.length, kEps);
	EXPECT_NEAR(15.0f, track.seg->width, kEps);
	EXPECT_NEAR(120.0f, track.max.x, kEps);
	EXPECT_NEAR(15.0f, track.max.y, kEps);
	EXPECT_NEAR(0.0f, track.max.z, kEps);
	EXPECT_EQ(nullptr, track.seg->lside);
	EXPECT_EQ(nullptr, track.seg->rside);
	ASSERT_NE(nullptr, track.seg->barrier[TR_SIDE_RGT]);
	ASSERT_NE(nullptr, track.seg->barrier[TR_SIDE_LFT]);
	EXPECT_EQ(TR_FENCE, track.seg->barrier[TR_SIDE_RGT]->style);
	EXPECT_EQ(TR_FENCE, track.seg->barrier[TR_SIDE_LFT]->style);
	EXPECT_NEAR(0.0f, track.seg->barrier[TR_SIDE_RGT]->normal.x, kEps);
	EXPECT_NEAR(1.0f, track.seg->barrier[TR_SIDE_RGT]->normal.y, kEps);
	EXPECT_NEAR(0.0f, track.seg->barrier[TR_SIDE_LFT]->normal.x, kEps);
	EXPECT_NEAR(-1.0f, track.seg->barrier[TR_SIDE_LFT]->normal.y, kEps);
	EXPECT_NE(nullptr, track.surfaces);
	EXPECT_TRUE((track.seg->raceInfo & TR_LAST) != 0);
}

TEST_F(Track4Test, GeoreferenceAbsentClearsAvailability)
{
	addStraight("start", 100.0f);
	track.georeference.hasLocation = track.georeference.hasAltitude = track.georeference.hasHeading = 1;
	build();
	EXPECT_EQ(0, track.georeference.hasLocation);
	EXPECT_EQ(0, track.georeference.hasAltitude);
	EXPECT_EQ(0, track.georeference.hasHeading);
}

TEST_F(Track4Test, GeoreferenceReadsUnitsAndNormalizesHeadingInExtendedBuild)
{
	addStraight("start", 100.0f);
	GfParmSetNum(handle, TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_LATITUDE, "deg", -25.5f);
	GfParmSetNum(handle, TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_LONGITUDE, "deg", 28.25f);
	GfParmSetNum(handle, TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_ALTITUDE, "m", -12.5f);
	GfParmSetNum(handle, TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_HEADING, "deg", -90.0f);
	build(1);
	EXPECT_EQ(1, track.georeference.hasLocation);
	EXPECT_EQ(1, track.georeference.hasAltitude);
	EXPECT_EQ(1, track.georeference.hasHeading);
	EXPECT_NEAR(-25.5, track.georeference.latitude, kEps);
	EXPECT_NEAR(28.25, track.georeference.longitude, kEps);
	EXPECT_NEAR(-12.5, track.georeference.altitude, kEps);
	EXPECT_NEAR(1.5 * PI, track.georeference.heading, kEps);
}

TEST_F(Track4Test, GeoreferenceZeroIsValidAndAltitudeCanBeMissing)
{
	addStraight("start", 100.0f);
	GfParmSetNum(handle, TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_LATITUDE, "deg", 0);
	GfParmSetNum(handle, TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_LONGITUDE, "deg", 0);
	GfParmSetNum(handle, TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_HEADING, "deg", 720);
	build();
	EXPECT_EQ(1, track.georeference.hasLocation);
	EXPECT_EQ(0, track.georeference.hasAltitude);
	EXPECT_EQ(1, track.georeference.hasHeading);
	EXPECT_NEAR(0.0, track.georeference.heading, kEps);
}

TEST_F(Track4Test, GeoreferenceRejectsOutOfRangeLocationAndNonfiniteHeading)
{
	addStraight("start", 100.0f);
	GfParmSetNum(handle, TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_LATITUDE, "deg", 91);
	GfParmSetNum(handle, TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_LONGITUDE, "deg", 181);
	setNum(TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_HEADING, std::numeric_limits<tdble>::infinity());
	setNum(TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_ALTITUDE, 0);
	build();
	EXPECT_EQ(0, track.georeference.hasLocation);
	EXPECT_EQ(0, track.georeference.hasHeading);
	EXPECT_EQ(1, track.georeference.hasAltitude);
}

TEST_F(Track4Test, GeoreferenceIncompleteLocationDoesNotBecomeZeroLongitude)
{
	addStraight("start", 100.0f);
	GfParmSetNum(handle, TRK_SECT_GEOREFERENCE, TRK_ATT_GEO_LATITUDE, "deg", 45);
	build();
	EXPECT_EQ(0, track.georeference.hasLocation);
}


TEST(Track4PathTest, FormatsValidPath)
{
	char buffer[16];
	formatTrackPath(buffer, sizeof(buffer), "%s/%s", "Main", "Road");
	EXPECT_STREQ("Main/Road", buffer);
}


TEST(Track4PathTest, RejectsInvalidBufferSize)
{
	char buffer[1];
	EXPECT_EXIT(
		formatTrackPath(buffer, 0, "%s", "x"),
		testing::ExitedWithCode(1),
		"Track parameter path buffer has invalid size");
}


TEST(Track4PathTest, RejectsTruncatedPath)
{
	char buffer[4];
	EXPECT_EXIT(
		formatTrackPath(buffer, sizeof(buffer), "%s", "too-long"),
		testing::ExitedWithCode(1),
		"Track parameter path too long");
}


TEST(Track4PathTest, RejectsFormattingFailure)
{
	char buffer[16];
	EXPECT_EXIT(
		{
			FailVsnprintf = true;
			formatTrackPath(buffer, sizeof(buffer), "%s", "x");
		},
		testing::ExitedWithCode(1),
		"Track parameter path too long");
}


TEST_F(Track4Test, ReusesSurfacesAndReadsConfiguredSurfaceProperties)
{
	setSurface("paint", 1.2f, 0.03f, 0.08f, 2.0f, 4.0f, 0.7f);

	tTrackSurface* first = getTrackSurface(handle, &track, "paint");
	tTrackSurface* reused = getTrackSurface(handle, &track, "paint");
	tTrackSurface* second = getTrackSurface(handle, &track, "other");
	tTrackSurface* firstAgain = getTrackSurface(handle, &track, "paint");

	EXPECT_EQ(first, reused);
	EXPECT_EQ(first, firstAgain);
	EXPECT_NE(first, second);
	EXPECT_EQ(2, surfaceCount());
	EXPECT_NEAR(1.2f, first->kFriction, kEps);
	EXPECT_NEAR(0.03f, first->kRollRes, kEps);
	EXPECT_NEAR(0.04f, first->kRoughness, kEps);
	EXPECT_NEAR(static_cast<tdble>(PI), first->kRoughWaveLen, kEps);
	EXPECT_NEAR(4.0f, first->kDammage, kEps);
	EXPECT_NEAR(0.7f, first->kRebound, kEps);
}


TEST_F(Track4Test, ReportsSurfaceAllocationFailure)
{
	EXPECT_EXIT(
		{
			FailMallocSize = sizeof(tTrackSurface);
			getTrackSurface(handle, &track, "unallocated");
		},
		testing::ExitedWithCode(1),
		"AddTrackSurface: Memory allocation failed\\s*TRACK4_TEST_EXPLICIT_EXIT_1");
}


TEST_F(Track4Test, BuildsConfiguredSidesBordersAndBarriers)
{
	setMainNum(TRK_ATT_WIDTH, 10.0f);
	setDefaultSide(TR_SIDE_RGT, 3.0f, TRK_VAL_LEVEL, "right-side");
	setDefaultSide(TR_SIDE_LFT, 4.0f, TRK_VAL_TANGENT, "left-side");
	setDefaultBorder(TR_SIDE_RGT, 2.0f, 0.1f, TRK_VAL_PLAN, "right-border");
	setDefaultBorder(TR_SIDE_LFT, 1.0f, 0.2f, TRK_VAL_CURB, "left-border");
	setDefaultBarrier(TR_SIDE_RGT, 0.8f, 1.0f, TRK_VAL_WALL, "right-wall");
	setDefaultBarrier(TR_SIDE_LFT, 0.4f, 1.2f, TRK_VAL_FENCE, "left-fence");
	addStraight("s", 30.0f);

	build();

	tTrackSeg* segment = segmentAt(0);
	ASSERT_NE(nullptr, segment->rside);
	ASSERT_NE(nullptr, segment->rside->rside);
	EXPECT_EQ(TR_RBORDER, segment->rside->type2);
	EXPECT_EQ(TR_PLAN, segment->rside->style);
	EXPECT_NEAR(2.0f, segment->rside->width, kEps);
	EXPECT_NEAR(0.1f, segment->rside->height, kEps);
	EXPECT_EQ(TR_RSIDE, segment->rside->rside->type2);
	EXPECT_NEAR(3.0f, segment->rside->rside->width, kEps);

	ASSERT_NE(nullptr, segment->lside);
	ASSERT_NE(nullptr, segment->lside->lside);
	EXPECT_EQ(TR_LBORDER, segment->lside->type2);
	EXPECT_EQ(TR_CURB, segment->lside->style);
	EXPECT_NEAR(1.0f, segment->lside->width, kEps);
	EXPECT_NEAR(0.2f, segment->lside->height, kEps);
	EXPECT_EQ(TR_LSIDE, segment->lside->lside->type2);
	EXPECT_NEAR(4.0f, segment->lside->lside->width, kEps);

	EXPECT_EQ(TR_WALL, segment->barrier[TR_SIDE_RGT]->style);
	EXPECT_NEAR(0.8f, segment->barrier[TR_SIDE_RGT]->width, kEps);
	EXPECT_NEAR(1.0f, segment->barrier[TR_SIDE_RGT]->height, kEps);
	EXPECT_EQ(TR_FENCE, segment->barrier[TR_SIDE_LFT]->style);
	EXPECT_NEAR(0.0f, segment->barrier[TR_SIDE_LFT]->width, kEps);
	EXPECT_NEAR(1.2f, segment->barrier[TR_SIDE_LFT]->height, kEps);
}


TEST_F(Track4Test, AppliesSegmentSideOverridesAcrossProfileSteps)
{
	setDefaultSide(TR_SIDE_RGT, 1.0f, TRK_VAL_LEVEL, "grass");
	setDefaultSide(TR_SIDE_LFT, 1.0f, TRK_VAL_LEVEL, "grass");
	addStraight("split", 20.0f);
	setNum(segmentPath("split"), TRK_ATT_PROFSTEPS, 2.0f);
	setSegmentSideWidths("split", TR_SIDE_RGT, 0.0f, 4.0f);
	setSegmentSideWidths("split", TR_SIDE_LFT, 0.0f, 0.0f);
	setNum(segmentChildPath("split", TRK_SECT_RBORDER), TRK_ATT_WIDTH, 0.0f);
	setStr(segmentChildPath("split", TRK_SECT_RBORDER), TRK_ATT_STYLE, TRK_VAL_CURB);
	setNum(segmentChildPath("split", TRK_SECT_LBORDER), TRK_ATT_WIDTH, 2.0f);
	setStr(segmentChildPath("split", TRK_SECT_LBORDER), TRK_ATT_STYLE, "unknown-style");
	setStr(segmentChildPath("split", TRK_SECT_RBARRIER), TRK_ATT_STYLE, TRK_VAL_FENCE);
	setStr(segmentChildPath("split", TRK_SECT_LBARRIER), TRK_ATT_STYLE, TRK_VAL_WALL);
	setNum(segmentChildPath("split", TRK_SECT_LBARRIER), TRK_ATT_WIDTH, 0.6f);

	build();

	ASSERT_EQ(2, track.nseg);
	tTrackSeg* first = segmentAt(0);
	tTrackSeg* second = segmentAt(1);
	ASSERT_NE(nullptr, first->rside);
	ASSERT_NE(nullptr, second->rside);
	EXPECT_EQ(TR_RSIDE, first->rside->type2);
	EXPECT_EQ(TR_RSIDE, second->rside->type2);
	EXPECT_NEAR(0.0f, first->rside->startWidth, kEps);
	EXPECT_NEAR(2.0f, first->rside->endWidth, kEps);
	EXPECT_NEAR(2.0f, second->rside->startWidth, kEps);
	EXPECT_NEAR(4.0f, second->rside->endWidth, kEps);
	EXPECT_EQ(nullptr, first->lside->lside);
	EXPECT_EQ(TR_WALL, first->lside->style);
	EXPECT_EQ(TR_WALL, first->barrier[TR_SIDE_LFT]->style);
	EXPECT_NEAR(0.6f, first->barrier[TR_SIDE_LFT]->width, kEps);
}


TEST_F(Track4Test, ReportsBarrierAllocationFailure)
{
	addStraight("s", 20.0f);
	const std::string listPath = std::string(TRK_SECT_MAIN) + "/" + TRK_LST_SEGMENTS;
	ASSERT_EQ(0, GfParmListSeekFirst(handle, listPath.c_str()));

	tTrackSeg segment{};
	segment.type = TR_STR;
	segment.length = 20.0f;
	segment.width = 10.0f;
	segment.vertex[TR_EL].x = 20.0f;
	segment.vertex[TR_ER].x = 20.0f;
	sideStartWidth[0] = sideStartWidth[1] = 0.0f;
	sideEndWidth[0] = sideEndWidth[1] = 0.0f;
	borderWidth[0] = borderWidth[1] = 0.0f;
	EXPECT_EXIT(
		{
			FailMallocSize = sizeof(tTrackBarrier);
			addSides(&segment, handle, &track, 1, 1);
		},
		testing::ExitedWithCode(1),
		"AddSides: memory allocation error\\s*TRACK4_TEST_EXPLICIT_EXIT_1");
}


TEST_F(Track4Test, BuildsStraightLeftAndRightGeometryInRingOrder)
{
	addStraight("straight", 60.0f);
	addTurn("left", TR_LFT, 60.0f, 1.0f);
	addTurn("right", TR_RGT, 60.0f, 1.0f);

	build();

	ASSERT_EQ(3, track.nseg);
	tTrackSeg* straight = segmentAt(0);
	tTrackSeg* left = segmentAt(1);
	tTrackSeg* right = segmentAt(2);
	EXPECT_EQ(TR_STR, straight->type);
	EXPECT_EQ(TR_LFT, left->type);
	EXPECT_EQ(TR_RGT, right->type);
	EXPECT_EQ(0, straight->id);
	EXPECT_EQ(1, left->id);
	EXPECT_EQ(2, right->id);
	EXPECT_EQ(left, straight->next);
	EXPECT_EQ(straight, left->prev);
	EXPECT_EQ(right, left->next);
	EXPECT_EQ(straight, right->next);
	EXPECT_NEAR(0.0f, straight->lgfromstart, kEps);
	EXPECT_NEAR(60.0f, left->lgfromstart, kEps);
	EXPECT_NEAR(120.0f, right->lgfromstart, kEps);
	EXPECT_NEAR(180.0f, track.length, kEps);
	EXPECT_TRUE((straight->raceInfo & TR_START) != 0);
	EXPECT_EQ(TR_NORMAL, left->raceInfo);
	EXPECT_TRUE((right->raceInfo & TR_LAST) != 0);
	EXPECT_NEAR(left->vertex[TR_ER].x, right->vertex[TR_SR].x, kEps);
	EXPECT_NEAR(left->vertex[TR_ER].y, right->vertex[TR_SR].y, kEps);
}


TEST_F(Track4Test, ReadsExplicitElevationsBankingAndSharedTangents)
{
	setMainNum(TRK_ATT_WIDTH, 10.0f);
	addStraight("hill", 20.0f);
	const std::string path = segmentPath("hill");
	setNum(path, TRK_ATT_ZS, 2.0f);
	setNum(path, TRK_ATT_ZE, 5.0f);
	setNum(path, TRK_ATT_BKS, 0.1f);
	setNum(path, TRK_ATT_BKE, -0.05f);
	setNum(path, TRK_ATT_PROFTGTS, 0.2f);
	setNum(path, TRK_ATT_PROFTGTE, -0.1f);

	build();

	tTrackSeg* segment = segmentAt(0);
	EXPECT_NEAR(0.1f, segment->angle[TR_XS], kEps);
	EXPECT_NEAR(-0.05f, segment->angle[TR_XE], kEps);
	EXPECT_NEAR(10.0f * tan(0.1f), segment->vertex[TR_SL].z - segment->vertex[TR_SR].z, kEps);
	EXPECT_NEAR(10.0f * tan(-0.05f), segment->vertex[TR_EL].z - segment->vertex[TR_ER].z, kEps);
}


TEST_F(Track4Test, DerivesLinearProfileEndFromGrade)
{
	setMainNum(TRK_ATT_WIDTH, 10.0f);
	addStraight("grade", 20.0f);
	const std::string path = segmentPath("grade");
	setNum(path, TRK_ATT_ZSL, 2.0f);
	setNum(path, TRK_ATT_ZSR, 0.0f);
	setNum(path, TRK_ATT_GRADE, 0.1f);
	setStr(path, TRK_ATT_PROFIL, TRK_VAL_LINEAR);

	build();

	tTrackSeg* segment = segmentAt(0);
	const tdble startMiddle = (segment->vertex[TR_SL].z + segment->vertex[TR_SR].z) / 2.0f;
	const tdble endMiddle = (segment->vertex[TR_EL].z + segment->vertex[TR_ER].z) / 2.0f;
	EXPECT_NEAR(2.0f, endMiddle - startMiddle, kEps);
}


TEST_F(Track4Test, UsesSideEndAverageWhenCenterEndAndGradeAreMissing)
{
	setMainNum(TRK_ATT_WIDTH, 10.0f);
	addStraight("average", 10.0f);
	const std::string path = segmentPath("average");
	setNum(path, TRK_ATT_ZEL, 6.0f);
	setNum(path, TRK_ATT_ZER, 2.0f);

	build();

	tTrackSeg* segment = segmentAt(0);
	EXPECT_NEAR(4.0f, (segment->vertex[TR_EL].z + segment->vertex[TR_ER].z) / 2.0f, kEps);
}


TEST_F(Track4Test, SubdividesProfilesUsingGlobalAndExplicitStepCounts)
{
	setMainNum(TRK_ATT_PROFSTEPSLEN, 10.0f);
	addStraight("global", 25.0f);
	addStraight("explicit", 12.0f);
	setNum(segmentPath("explicit"), TRK_ATT_PROFSTEPS, 3.0f);

	build();

	EXPECT_EQ(6, track.nseg);
	EXPECT_STREQ("global", segmentAt(0)->name);
	EXPECT_STREQ("global", segmentAt(2)->name);
	EXPECT_STREQ("explicit", segmentAt(3)->name);
	EXPECT_STREQ("explicit", segmentAt(5)->name);
}


TEST_F(Track4Test, BuildsChangingRadiusTurnsWithOneAndMultipleSteps)
{
	addTurn("single", TR_LFT, 40.0f, 0.5f);
	setNum(segmentPath("single"), TRK_ATT_RADIUSEND, 50.0f);
	addTurn("multiple", TR_RGT, 60.0f, 0.6f);
	setNum(segmentPath("multiple"), TRK_ATT_RADIUSEND, 90.0f);
	setNum(segmentPath("multiple"), TRK_ATT_PROFSTEPS, 3.0f);

	build();

	ASSERT_EQ(4, track.nseg);
	EXPECT_NEAR(40.0f, segmentAt(0)->radius, kEps);
	EXPECT_NEAR(60.0f, segmentAt(1)->radius, kEps);
	EXPECT_NEAR(75.0f, segmentAt(2)->radius, kEps);
	EXPECT_NEAR(90.0f, segmentAt(3)->radius, kEps);
	const tdble initialStepLength = 15.0f;
	const tdble steppedAngle = initialStepLength / 60.0f + initialStepLength / 75.0f + initialStepLength / 90.0f;
	const tdble correctedStepLength = initialStepLength * 0.6f / steppedAngle;
	EXPECT_NEAR(22.5f + 3.0f * correctedStepLength, track.length, 1e-4f);
}


TEST_F(Track4Test, BuildsSidesForBothTurnDirections)
{
	setMainNum(TRK_ATT_WIDTH, 10.0f);
	setDefaultSide(TR_SIDE_RGT, 2.0f, TRK_VAL_LEVEL, "right");
	setDefaultSide(TR_SIDE_LFT, 3.0f, TRK_VAL_TANGENT, "left");
	addTurn("left", TR_LFT, 30.0f, 0.5f);
	setSegmentSideWidths("left", TR_SIDE_RGT, 1.0f, 2.0f);
	setSegmentSideWidths("left", TR_SIDE_LFT, 3.0f, 1.0f);
	addTurn("right", TR_RGT, 40.0f, 0.4f);

	build();

	for (int i = 0; i < track.nseg; i++) {
		tTrackSeg* segment = segmentAt(i);
		ASSERT_NE(nullptr, segment->rside);
		ASSERT_NE(nullptr, segment->lside);
		EXPECT_EQ(segment->type, segment->rside->type);
		EXPECT_EQ(segment->type, segment->lside->type);
		EXPECT_GT(segment->rside->length, 0.0f);
		EXPECT_GT(segment->lside->length, 0.0f);
	}
	EXPECT_NEAR(1.0f, segmentAt(0)->rside->startWidth, kEps);
	EXPECT_NEAR(2.0f, segmentAt(0)->rside->endWidth, kEps);
	EXPECT_NEAR(3.0f, segmentAt(0)->lside->startWidth, kEps);
	EXPECT_NEAR(1.0f, segmentAt(0)->lside->endWidth, kEps);
}


TEST_F(Track4Test, ReadsWallAsDefaultBorderFallback)
{
	setDefaultBorder(TR_SIDE_RGT, 1.0f, 0.3f, TRK_VAL_WALL, "wall");
	addStraight("s", 10.0f);

	build();

	ASSERT_NE(nullptr, track.seg->rside);
	EXPECT_EQ(TR_WALL, track.seg->rside->style);
}


TEST_F(Track4Test, PreservesEnvironmentIndexBehavior)
{
	addStraight("environment", 10.0f);
	setNum(segmentPath("environment"), TRK_ATT_ENVIND, 4.0f);

	build();

	EXPECT_EQ(3, track.seg->envIndex);
}


TEST_F(Track4Test, NormalizesNegativeAndPositiveTrackExtents)
{
	setMainNum(TRK_ATT_WIDTH, 10.0f);
	addTurn("wide-right", TR_RGT, 25.0f, 4.0f);
	setNum(segmentPath("wide-right"), TRK_ATT_BKS, 0.2f);
	setNum(segmentPath("wide-right"), TRK_ATT_BKE, -0.1f);

	build();

	EXPECT_NEAR(0.0f, track.min.x, kEps);
	EXPECT_NEAR(0.0f, track.min.y, kEps);
	EXPECT_NEAR(0.0f, track.min.z, kEps);
	EXPECT_GT(track.max.x, 0.0f);
	EXPECT_GT(track.max.y, 0.0f);
	EXPECT_GT(track.max.z, 0.0f);
	for (int vertex = 0; vertex < 4; vertex++) {
		EXPECT_GE(track.seg->vertex[vertex].x, -kEps);
		EXPECT_GE(track.seg->vertex[vertex].y, -kEps);
		EXPECT_GE(track.seg->vertex[vertex].z, -kEps);
	}
}


TEST_F(Track4Test, SkipsEntriesWithoutType)
{
	setNum(segmentPath("missing-type"), TRK_ATT_LG, 99.0f);
	addStraight("valid", 12.0f);

	build();

	ASSERT_EQ(1, track.nseg);
	EXPECT_STREQ("valid", track.seg->name);
}


TEST_F(Track4Test, RejectsTrackWhenNoSegmentsAreConfigured)
{
	EXPECT_EXIT(
		build(),
		testing::ExitedWithCode(1),
		"Track definition contains no valid segments");
}


TEST_F(Track4Test, RejectsUnknownTypeAfterValidSegment)
{
	addStraight("valid", 12.0f);
	setStr(segmentPath("invalid"), TRK_ATT_TYPE, "unknown");

	EXPECT_EXIT(
		build(),
		testing::ExitedWithCode(1),
		"Unknown track segment type \"unknown\" in segment \"invalid\"");
}


TEST_F(Track4Test, RejectsLeadingUnknownType)
{
	setStr(segmentPath("invalid-first"), TRK_ATT_TYPE, "unsupported");

	EXPECT_EXIT(
		build(),
		testing::ExitedWithCode(1),
		"Unknown track segment type \"unsupported\" in segment \"invalid-first\"");
}


TEST_F(Track4Test, ExtendedBuildStoresMarksOnlyOnFirstSubdivision)
{
	addStraight("marked", 20.0f);
	setNum(segmentPath("marked"), TRK_ATT_PROFSTEPS, 2.0f);
	setStr(segmentPath("marked"), TRK_ATT_MARKS, "10;0x20;30");

	build(1);

	ASSERT_EQ(2, track.nseg);
	ASSERT_NE(nullptr, segmentAt(0)->ext);
	EXPECT_EQ(3, segmentAt(0)->ext->nbMarks);
	EXPECT_EQ(10, segmentAt(0)->ext->marks[0]);
	EXPECT_EQ(32, segmentAt(0)->ext->marks[1]);
	EXPECT_EQ(30, segmentAt(0)->ext->marks[2]);
	EXPECT_EQ(nullptr, segmentAt(1)->ext);
}


TEST_F(Track4Test, ExtendedBuildCapsTurnMarksAt256)
{
	std::string marks;
	for (int i = 0; i < 260; i++) {
		if (!marks.empty()) {
			marks += ";";
		}
		marks += std::to_string(i);
	}
	addStraight("marked", 10.0f);
	setStr(segmentPath("marked"), TRK_ATT_MARKS, marks.c_str());

	build(1);

	ASSERT_NE(nullptr, track.seg->ext);
	EXPECT_EQ(256, track.seg->ext->nbMarks);
	EXPECT_EQ(255, track.seg->ext->marks[255]);
}


TEST_F(Track4Test, NonExtendedBuildIgnoresMarks)
{
	addStraight("marked", 10.0f);
	setStr(segmentPath("marked"), TRK_ATT_MARKS, "1;2");

	build(0);

	EXPECT_EQ(nullptr, track.seg->ext);
}


TEST_F(Track4Test, ExtendedBuildAllowsSegmentsWithoutMarks)
{
	addStraight("plain", 10.0f);

	build(1);

	EXPECT_EQ(nullptr, track.seg->ext);
}


TEST_F(Track4Test, ExtendedBuildRejectsDuplicateSegmentName)
{
	addStraight("duplicate", 10.0f);
	ForceDuplicateSegment = true;

	EXPECT_EXIT(build(1), testing::ExitedWithCode(1), "");
}


TEST_F(Track4Test, BuildsRightSidePitsWithoutOuterSideSegment)
{
	setDefaultSide(TR_SIDE_RGT, 6.0f, TRK_VAL_LEVEL, "pit");
	setDefaultSide(TR_SIDE_LFT, 6.0f, TRK_VAL_LEVEL, "pit");
	addStraight("A", 30.0f);
	addStraight("B", 30.0f);
	addStraight("C", 30.0f);
	addStraight("D", 30.0f);
	addStraight("E", 30.0f);
	addStraight("F", 30.0f);
	setPits("B", "F", "B", "D", "right");

	build();

	ASSERT_EQ(TR_PIT_ON_TRACK_SIDE, track.pits.type);
	EXPECT_EQ(TR_RGT, track.pits.side);
	EXPECT_EQ(6, track.pits.nMaxPits);
	EXPECT_NEAR(22.0f, track.pits.speedLimit, kEps);
	EXPECT_STREQ("B", track.pits.pitEntry->name);
	EXPECT_STREQ("F", track.pits.pitExit->name);
	EXPECT_STREQ("B", track.pits.pitStart->name);
	EXPECT_STREQ("D", track.pits.pitEnd->name);
	EXPECT_TRUE((track.pits.pitEntry->raceInfo & TR_PITENTRY) != 0);
	EXPECT_TRUE((track.pits.pitExit->raceInfo & TR_PITEXIT) != 0);
	ASSERT_NE(nullptr, track.pits.driversPits);
	EXPECT_STREQ("B", track.pits.driversPits[0].pos.seg->name);
	EXPECT_NEAR(7.5f, track.pits.driversPits[0].pos.toStart, kEps);
	EXPECT_NEAR(-3.5f, track.pits.driversPits[0].pos.toRight, kEps);
	EXPECT_TRUE((segmentAt(0)->rside->raceInfo & TR_PITSTART) != 0);
	EXPECT_TRUE((segmentAt(1)->rside->raceInfo & TR_PIT) != 0);
	EXPECT_TRUE((segmentAt(4)->rside->raceInfo & TR_PITEND) != 0);
	EXPECT_EQ(nullptr, segmentAt(1)->rside->rside);
	EXPECT_EQ(TR_PITBUILDING, segmentAt(1)->barrier[TR_SIDE_RGT]->style);
}


TEST_F(Track4Test, BuildsRightSidePitOffsetsWithBorderAndOuterSide)
{
	setDefaultSide(TR_SIDE_RGT, 6.0f, TRK_VAL_LEVEL, "pit");
	setDefaultBorder(TR_SIDE_RGT, 2.0f, 0.1f, TRK_VAL_CURB, "curb");
	addStraight("A", 30.0f);
	addStraight("B", 30.0f);
	addStraight("C", 30.0f);
	addStraight("D", 30.0f);
	addStraight("E", 30.0f);
	addStraight("F", 30.0f);
	setPits("B", "F", "B", "D", "right");

	build();

	ASSERT_NE(nullptr, track.pits.driversPits);
	EXPECT_NEAR(-5.5f, track.pits.driversPits[0].pos.toRight, kEps);
	ASSERT_NE(nullptr, segmentAt(1)->rside);
	EXPECT_NE(nullptr, segmentAt(1)->rside->rside);
}


TEST_F(Track4Test, BuildsLeftSidePitOffsetsWithoutOuterSideSegment)
{
	setDefaultSide(TR_SIDE_LFT, 6.0f, TRK_VAL_LEVEL, "pit");
	addStraight("A", 30.0f);
	addStraight("B", 30.0f);
	addStraight("C", 30.0f);
	addStraight("D", 30.0f);
	addStraight("E", 30.0f);
	addStraight("F", 30.0f);
	setPits("B", "F", "B", "D", "left");

	build();

	ASSERT_NE(nullptr, track.pits.driversPits);
	EXPECT_NEAR(-3.5f, track.pits.driversPits[0].pos.toLeft, kEps);
	ASSERT_NE(nullptr, segmentAt(1)->lside);
	EXPECT_EQ(nullptr, segmentAt(1)->lside->lside);
}


TEST_F(Track4Test, BuildsWrappingLeftSidePitsWithBorderAndOuterSide)
{
	setDefaultSide(TR_SIDE_RGT, 6.0f, TRK_VAL_LEVEL, "pit");
	setDefaultSide(TR_SIDE_LFT, 6.0f, TRK_VAL_TANGENT, "pit");
	setDefaultBorder(TR_SIDE_LFT, 2.0f, 0.1f, TRK_VAL_CURB, "curb");
	addStraight("A", 20.0f);
	addStraight("B", 20.0f);
	addStraight("C", 20.0f);
	addStraight("D", 20.0f);
	addStraight("E", 20.0f);
	addStraight("F", 20.0f);
	addStraight("G", 20.0f);
	addStraight("H", 20.0f);
	setPits("E", "C", "F", "B", "left", 20.0f, 4.0f);

	build();

	ASSERT_EQ(TR_PIT_ON_TRACK_SIDE, track.pits.type);
	EXPECT_EQ(TR_LFT, track.pits.side);
	EXPECT_EQ(5, track.pits.nMaxPits);
	ASSERT_NE(nullptr, track.pits.driversPits);
	EXPECT_STREQ("F", track.pits.driversPits[0].pos.seg->name);
	EXPECT_NEAR(-6.0f, track.pits.driversPits[0].pos.toLeft, kEps);
	ASSERT_NE(nullptr, segmentAt(5)->lside->lside);
	EXPECT_TRUE((segmentAt(5)->lside->raceInfo & TR_PIT) != 0);
	EXPECT_TRUE((segmentAt(5)->lside->lside->raceInfo & TR_PIT) != 0);
	EXPECT_EQ(TR_PITBUILDING, segmentAt(5)->barrier[TR_SIDE_LFT]->style);
}


TEST_F(Track4Test, ResolvesPitBoundariesWithinFirstSubdividedSourceSegment)
{
	setDefaultSide(TR_SIDE_RGT, 6.0f, TRK_VAL_LEVEL, "pit");
	setMainNum(TRK_ATT_PROFSTEPSLEN, 10.0f);
	addStraight("A", 30.0f);
	addStraight("B", 30.0f);
	addStraight("C", 30.0f);
	addStraight("D", 30.0f);
	addStraight("E", 30.0f);
	addStraight("F", 30.0f);
	setPits("A", "A", "A", "A", "right");

	build();

	EXPECT_EQ(segmentAt(0), track.pits.pitEntry);
	EXPECT_EQ(segmentAt(0), track.pits.pitStart);
	EXPECT_EQ(segmentAt(3), track.pits.pitExit);
	EXPECT_EQ(segmentAt(3), track.pits.pitEnd);
	EXPECT_TRUE((segmentAt(0)->raceInfo & TR_PITENTRY) != 0);
	EXPECT_TRUE((segmentAt(3)->raceInfo & TR_PITEXIT) != 0);
}


TEST_F(Track4Test, PitPlacementSkipsSegmentsShorterThanResidualOffset)
{
	setDefaultSide(TR_SIDE_RGT, 6.0f, TRK_VAL_LEVEL, "pit");
	addStraight("A", 10.0f);
	addStraight("B", 10.0f);
	addStraight("C", 10.0f);
	addStraight("D", 30.0f);
	addStraight("E", 30.0f);
	addStraight("F", 30.0f);
	addStraight("G", 30.0f);
	setPits("A", "G", "B", "F", "right", 25.0f, 5.0f);

	build();

	ASSERT_GT(track.pits.nMaxPits, 1);
	EXPECT_STREQ("B", track.pits.driversPits[0].pos.seg->name);
	EXPECT_STREQ("D", track.pits.driversPits[1].pos.seg->name);
	EXPECT_NEAR(17.5f, track.pits.driversPits[1].pos.toStart, kEps);
}


TEST_F(Track4Test, IgnoresPitDefinitionWithUnknownSegmentNames)
{
	addStraight("A", 30.0f);
	addStraight("B", 30.0f);
	setPits("unknown-entry", "unknown-exit", "unknown-start", "unknown-end", "right");

	build();

	EXPECT_EQ(TR_PIT_NONE, track.pits.type);
	EXPECT_EQ(nullptr, track.pits.driversPits);
}


TEST_F(Track4Test, IgnoresPitDefinitionWithoutExit)
{
	addStraight("A", 30.0f);
	addStraight("B", 30.0f);
	setPits("A", nullptr, "A", "B", "right");

	build();

	EXPECT_EQ(TR_PIT_NONE, track.pits.type);
}


TEST_F(Track4Test, IgnoresPitDefinitionWithoutStart)
{
	addStraight("A", 30.0f);
	addStraight("B", 30.0f);
	setPits("A", "B", nullptr, "B", "right");

	build();

	EXPECT_EQ(TR_PIT_NONE, track.pits.type);
}


TEST_F(Track4Test, IgnoresPitDefinitionWithoutEnd)
{
	addStraight("A", 30.0f);
	addStraight("B", 30.0f);
	setPits("A", "B", "A", nullptr, "right");

	build();

	EXPECT_EQ(TR_PIT_NONE, track.pits.type);
}


TEST_F(Track4Test, BuildsAndLinksMultipleCameras)
{
	addStraight("A", 40.0f);
	addStraight("B", 40.0f);
	addStraight("C", 40.0f);
	addStraight("D", 40.0f);
	addCamera("camera-1", "B", "A", "D", 2.0f, 5.0f, 3.0f);
	addCamera("camera-2", "D", "C", "A", 1.0f, 4.0f, 2.0f);

	build();

	ASSERT_NE(nullptr, cameras);
	ASSERT_NE(cameras, cameras->next);
	EXPECT_EQ(cameras, cameras->next->next);
	EXPECT_STREQ("camera-2", cameras->name);
	EXPECT_STREQ("camera-1", cameras->next->name);
	EXPECT_EQ(cameras->next, segmentAt(0)->cam);
	EXPECT_EQ(cameras->next, segmentAt(1)->cam);
	EXPECT_EQ(cameras, segmentAt(2)->cam);
	EXPECT_EQ(cameras, segmentAt(3)->cam);
	EXPECT_GE(cameras->pos.x, 0.0f);
	EXPECT_GE(cameras->pos.y, 0.0f);
	EXPECT_GE(cameras->pos.z, 0.0f);
}


TEST_F(Track4Test, ReportsCameraAllocationFailure)
{
	addStraight("A", 40.0f);
	addCamera("camera", "A", "A", "A");
	EXPECT_EXIT(
		{
			FailCallocSize = sizeof(tRoadCam);
			build();
		},
		testing::ExitedWithCode(1),
		"ReadTrack4: Memory allocation error");
}


TEST_F(Track4Test, ReportsCameraWithoutSegment)
{
	addStraight("A", 40.0f);
	addCamera("camera", nullptr, "A", "A");

	EXPECT_EXIT(
		build(),
		testing::ExitedWithCode(1),
		"Bad Track Definition: in Camera camera segment is missing");
}


TEST_F(Track4Test, ReportsCameraWithoutFovStart)
{
	addStraight("A", 40.0f);
	addCamera("camera", "A", nullptr, "A");

	EXPECT_EXIT(
		build(),
		testing::ExitedWithCode(1),
		"Bad Track Definition: in Camera camera fov start is missing");
}


TEST_F(Track4Test, ReportsCameraWithoutFovEnd)
{
	addStraight("A", 40.0f);
	addCamera("camera", "A", "A", nullptr);

	EXPECT_EXIT(
		build(),
		testing::ExitedWithCode(1),
		"Bad Track Definition: in Camera camera fov end is missing");
}


TEST_F(Track4Test, BuildsSingleCameraWithSingleSegmentAssignment)
{
	addStraight("A", 40.0f);
	addStraight("B", 40.0f);
	addCamera("camera", "A", "A", "B", 1.0f, 2.0f, 3.0f);

	build();

	ASSERT_NE(nullptr, cameras);
	EXPECT_EQ(cameras, cameras->next);
	EXPECT_EQ(cameras, segmentAt(0)->cam);
	EXPECT_EQ(nullptr, segmentAt(1)->cam);
}


TEST_F(Track4Test, MaintainsRingGeometryAndOwnershipInvariants)
{
	setMainNum(TRK_ATT_WIDTH, 10.0f);
	setDefaultSide(TR_SIDE_RGT, 2.0f, TRK_VAL_LEVEL, "right");
	setDefaultSide(TR_SIDE_LFT, 3.0f, TRK_VAL_TANGENT, "left");
	setDefaultBorder(TR_SIDE_RGT, 1.0f, 0.1f, TRK_VAL_CURB, "curb");
	addStraight("straight", 25.0f);
	addTurn("left", TR_LFT, 35.0f, 0.4f);
	addTurn("right", TR_RGT, 45.0f, 0.3f);

	build();

	tdble cumulativeLength = 0.0f;
	for (int i = 0; i < track.nseg; i++) {
		tTrackSeg* segment = segmentAt(i);
		ASSERT_NE(nullptr, segment);
		EXPECT_EQ(i, segment->id);
		EXPECT_EQ(segment, segment->next->prev);
		EXPECT_EQ(segment, segment->prev->next);
		EXPECT_NEAR(cumulativeLength, segment->lgfromstart, kEps);
		if (i + 1 < track.nseg) {
			EXPECT_NEAR(segment->vertex[TR_ER].x, segment->next->vertex[TR_SR].x, kEps);
			EXPECT_NEAR(segment->vertex[TR_ER].y, segment->next->vertex[TR_SR].y, kEps);
			EXPECT_NEAR(segment->vertex[TR_EL].x, segment->next->vertex[TR_SL].x, kEps);
			EXPECT_NEAR(segment->vertex[TR_EL].y, segment->next->vertex[TR_SL].y, kEps);
		}
		ASSERT_NE(nullptr, segment->rside);
		ASSERT_NE(nullptr, segment->lside);
		EXPECT_NEAR(segment->vertex[TR_SR].x, segment->rside->vertex[TR_SL].x, kEps);
		EXPECT_NEAR(segment->vertex[TR_SR].y, segment->rside->vertex[TR_SL].y, kEps);
		EXPECT_NEAR(segment->vertex[TR_SL].x, segment->lside->vertex[TR_SR].x, kEps);
		EXPECT_NEAR(segment->vertex[TR_SL].y, segment->lside->vertex[TR_SR].y, kEps);
		cumulativeLength += segment->length;
	}
	EXPECT_NEAR(track.length, cumulativeLength, kEps);
	EXPECT_EQ(track.seg->next, segmentAt(0));
	EXPECT_EQ(track.seg, segmentAt(track.nseg - 1));
}


TEST(TrackSplineTest, PreservesEndpointsAndTangents)
{
	EXPECT_NEAR(2.0f, TrackSpline(2.0f, 8.0f, 3.0f, -1.0f, 0.0f), kEps);
	EXPECT_NEAR(8.0f, TrackSpline(2.0f, 8.0f, 3.0f, -1.0f, 1.0f), kEps);
	EXPECT_NEAR(5.5f, TrackSpline(2.0f, 8.0f, 3.0f, -1.0f, 0.5f), kEps);
}
