/***************************************************************************

    file                 : trackscene_test.cpp
    created              : Wed Aug 12 2026
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

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <string>
#include <tuple>
#include <vector>

#include <gtest/gtest.h>

#include "tracksceneprivate.h"

int TrackgenQuiet = 1;

int Ac3dGroup(FILE *, const char *, int)
{
	return 0;
}

static const float kEps = 1e-5f;

static void releaseDisplayLists()
{
	if (Groups == nullptr) {
		return;
	}
	for (int groupIndex = 0; groupIndex < GroupNb; groupIndex++) {
		tDispElt *last = Groups[groupIndex].dispList;
		if (last == nullptr) {
			continue;
		}
		tDispElt *current = last->next;
		while (current != last) {
			tDispElt *next = current->next;
			free(current->name);
			free(current);
			current = next;
		}
		free(last->name);
		free(last);
	}
	free(Groups);
	Groups = nullptr;
	GroupNb = 0;
	ActiveGroups = 0;
}

static void releaseTextures(tTexElt *&texture)
{
	while (texture != nullptr) {
		tTexElt *next = texture->next;
		const bool last = next == texture;
		free(texture->name);
		free(texture->namebump);
		free(texture->nameraceline);
		free(texture);
		texture = last ? nullptr : next;
	}
}

static std::string saveObject(const float *vertices, const float *texCoords,
		int vertexCount)
{
	FILE *file = tmpfile();
	EXPECT_NE(nullptr, file);
	TrackSceneTestSaveObject(file, vertexCount, vertices, texCoords);
	rewind(file);

	std::string output;
	char buffer[512];
	while (fgets(buffer, sizeof(buffer), file) != nullptr) {
		output += buffer;
	}
	fclose(file);
	return output;
}

class SyntheticTrackSceneTest : public testing::Test {
protected:
	void SetUp() override
	{
		memset(&track, 0, sizeof(track));
		memset(&mainSeg, 0, sizeof(mainSeg));
		memset(&left, 0, sizeof(left));
		memset(&right, 0, sizeof(right));
		memset(&leftOuter, 0, sizeof(leftOuter));
		memset(&rightOuter, 0, sizeof(rightOuter));
		memset(&previous, 0, sizeof(previous));
		memset(&next, 0, sizeof(next));
		memset(barriers, 0, sizeof(barriers));
		memset(&surface, 0, sizeof(surface));
		surface.material = "test";
		track.nseg = 1;
		track.width = 10.0;
		track.seg = &mainSeg;
		mainSeg.next = &mainSeg;
		mainSeg.prev = &previous;
		mainSeg.surface = &surface;
		mainSeg.type2 = TR_MAIN;
		mainSeg.width = mainSeg.startWidth = mainSeg.endWidth = 10.0;
		mainSeg.rgtSideNormal.y = 1.0;
		previous.next = &mainSeg;
		next.prev = &mainSeg;
		for (int side = 0; side < 2; side++) {
			barriers[side].surface = &surface;
			mainSeg.barrier[side] = &barriers[side];
			previous.barrier[side] = &barriers[side];
			next.barrier[side] = &barriers[side];
		}
		vertices.assign(12000 * 3, 0.0f);
		texCoords.assign(12000 * 2, 0.0f);
		indices.assign(12000, 0u);
		trackvertices = vertices.data();
		tracktexcoord = texCoords.data();
		trackindices = indices.data();
		Groups = static_cast<tGroup *>(calloc(3, sizeof(tGroup)));
		GroupNb = 3;
		ActiveGroups = 0;
	}

	void TearDown() override
	{
		releaseDisplayLists();
		releaseTextures(texture);
	}

	void configureSegment(tTrackSeg &seg, int type, int type2, tdble width = 4.0)
	{
		seg.type = type;
		seg.type2 = type2;
		seg.surface = &surface;
		seg.length = 25.0;
		seg.width = seg.startWidth = seg.endWidth = width;
		seg.radius = 30.0;
		seg.radiusr = 35.0;
		seg.radiusl = 25.0;
		seg.arc = 0.5;
		seg.angle[TR_ZS] = 0.0;
		seg.angle[TR_ZE] = type == TR_RGT ? -0.5 : 0.5;
		seg.vertex[TR_SL] = { 0.0, width, 1.0 };
		seg.vertex[TR_SR] = { 0.0, 0.0, 2.0 };
		seg.vertex[TR_EL] = { 20.0, width, 3.0 };
		seg.vertex[TR_ER] = { 20.0, 0.0, 4.0 };
	}

	void attachSide(int side, tTrackSeg *inner, tTrackSeg *outer = nullptr)
	{
		mainSeg.side[side] = inner;
		inner->side[side] = outer;
		previous.side[side] = nullptr;
		next.side[side] = nullptr;
	}

	tTrackSceneContext context()
	{
		return { &track, nullptr, 0, 10.0, vertexCount, texture, currentTexture,
			currentDisplay, textureId, previousTextureId, startNeeded,
			textureType, textureLink, textureOffset, textureSize };
	}

	tDispElt *findDisplay(const char *name)
	{
		for (int groupIndex = 0; groupIndex < GroupNb; groupIndex++) {
			if (Groups[groupIndex].dispList == nullptr) {
				continue;
			}
			tDispElt *last = Groups[groupIndex].dispList;
			tDispElt *display = last->next;
			do {
				if (strcmp(display->name, name) == 0) {
					return display;
				}
				display = display->next;
			} while (display != last->next);
		}
		return nullptr;
	}

	tDispElt *findDisplay(const char *name, const char *textureName)
	{
		for (int groupIndex = 0; groupIndex < GroupNb; groupIndex++) {
			if (Groups[groupIndex].dispList == nullptr) {
				continue;
			}
			tDispElt *last = Groups[groupIndex].dispList;
			tDispElt *display = last->next;
			do {
				if (strcmp(display->name, name) == 0 && display->texture != nullptr &&
						strcmp(display->texture->name, textureName) == 0) {
					return display;
				}
				display = display->next;
			} while (display != last->next);
		}
		return nullptr;
	}

	tTrack track;
	tTrackSeg mainSeg, left, right, leftOuter, rightOuter, previous, next;
	tTrackBarrier barriers[2];
	tTrackSurface surface;
	std::vector<float> vertices;
	std::vector<float> texCoords;
	std::vector<unsigned int> indices;
	unsigned int vertexCount = 0;
	tTexElt *texture = nullptr;
	tTexElt *currentTexture = nullptr;
	tDispElt *currentDisplay = nullptr;
	unsigned int textureId = 0;
	unsigned int previousTextureId = 0;
	int startNeeded = 1;
	int textureType = 0;
	int textureLink = 0;
	tdble textureOffset = 0.0;
	tdble textureSize = 20.0;
};

TEST_F(SyntheticTrackSceneTest, CountTrackVerticesCharacterizesAllGeometryDirections)
{
	struct CountCase { int type; tdble length; tdble arc; tdble radiusl; tdble radiusr; unsigned int expected; };
	const CountCase cases[] = {
		{ TR_STR, 25.0, 0.0, 0.0, 0.0, 10246u },
		{ TR_LFT, 0.0, 0.75, 40.0, 40.0, 10290u },
		{ TR_RGT, 0.0, 0.75, 40.0, 40.0, 10290u }
	};
	for (const CountCase &entry : cases) {
		mainSeg.type = entry.type;
		mainSeg.length = entry.length;
		mainSeg.arc = entry.arc;
		mainSeg.radiusl = entry.radiusl;
		mainSeg.radiusr = entry.radiusr;
		EXPECT_EQ(entry.expected, countTrackVertices(&track, 10.0));
	}
}

TEST_F(SyntheticTrackSceneTest, MainTrackLeftAndRightCurvesMirrorAngularProgression)
{
	for (int type : { TR_LFT, TR_RGT }) {
		vertexCount = 0;
		previousTextureId = 0;
		startNeeded = 1;
		configureSegment(mainSeg, type, TR_MAIN, 10.0);
		mainSeg.radiusr = 40.0;
		mainSeg.radiusl = 30.0;
		mainSeg.center = { 0.0, 0.0, 0.0 };
		mainSeg.vertex[TR_SL] = { 0.0, -30.0, 0.0 };
		mainSeg.vertex[TR_SR] = { 0.0, -40.0, 0.0 };
		mainSeg.vertex[TR_EL] = { 1.0, 2.0, 0.0 };
		mainSeg.vertex[TR_ER] = { 3.0, 4.0, 0.0 };
		if (type == TR_RGT) {
			mainSeg.vertex[TR_SL].y = 30.0;
			mainSeg.vertex[TR_SR].y = 40.0;
		}
		tTrackSceneContext scene = context();
		generateMainTrack(scene, 0, 1.0, 0.0);
		ASSERT_EQ(6u, vertexCount);
		const float angle = type == TR_LFT ? 0.25f : 1.0f / 3.0f;
		const float lateralSign = type == TR_LFT ? -1.0f : 1.0f;
		EXPECT_NEAR(30.0f * std::sin(angle), vertices[6], kEps);
		EXPECT_NEAR(lateralSign * 30.0f * std::cos(angle), vertices[7], kEps);
		EXPECT_NEAR(40.0f * std::sin(angle), vertices[9], kEps);
		EXPECT_NEAR(lateralSign * 40.0f * std::cos(angle), vertices[10], kEps);
		const float expectedTexLen = angle * 30.0f / 20.0f;
		EXPECT_NEAR(expectedTexLen, texCoords[4], kEps);
		EXPECT_NEAR(0.5f, texCoords[5], kEps);
		EXPECT_NEAR(expectedTexLen, texCoords[6], kEps);
		EXPECT_NEAR(0.0f, texCoords[7], kEps);
	}
}

class SideDirectionTest : public SyntheticTrackSceneTest,
		public testing::WithParamInterface<std::tuple<int, int> > {};

TEST_P(SideDirectionTest, EmitsPairedVerticesWithMirroredTextureOrientation)
{
	const int side = std::get<0>(GetParam());
	const int type = std::get<1>(GetParam());
	tTrackSeg &seg = side == TR_SIDE_LFT ? left : right;
	configureSegment(mainSeg, type, TR_MAIN, 10.0);
	configureSegment(seg, type, side == TR_SIDE_LFT ? TR_LSIDE : TR_RSIDE);
	attachSide(side, &seg);
	tTrackSceneContext scene = context();
	generateSide(scene, side);
	ASSERT_GE(vertexCount, 4u);
	EXPECT_NEAR(seg.vertex[TR_SL].x, vertices[0], kEps);
	EXPECT_NEAR(seg.vertex[TR_SR].y, vertices[4], kEps);
	EXPECT_NEAR(side == TR_SIDE_RGT ? 1.0f : 0.0f, texCoords[0], kEps);
	EXPECT_NEAR(side == TR_SIDE_RGT ? 0.0f : 0.2f, texCoords[1], kEps);
	EXPECT_NEAR(side == TR_SIDE_RGT ? 0.2f : 0.0f, texCoords[3], kEps);
	EXPECT_NEAR(seg.vertex[TR_EL].x, vertices[3 * (vertexCount - 2)], kEps);
	EXPECT_NEAR(seg.vertex[TR_ER].z, vertices[3 * (vertexCount - 1) + 2], kEps);
	ASSERT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "tkRS" : "tkLS"));
}

INSTANTIATE_TEST_SUITE_P(SymmetricMatrix, SideDirectionTest, testing::Values(
	std::make_tuple(TR_SIDE_LFT, TR_STR), std::make_tuple(TR_SIDE_RGT, TR_STR),
	std::make_tuple(TR_SIDE_LFT, TR_LFT), std::make_tuple(TR_SIDE_RGT, TR_LFT),
	std::make_tuple(TR_SIDE_LFT, TR_RGT), std::make_tuple(TR_SIDE_RGT, TR_RGT)));

TEST_F(SyntheticTrackSceneTest, SideTraversalUsesOuterSegmentBeyondBorder)
{
	configureSegment(mainSeg, TR_STR, TR_MAIN);
	configureSegment(left, TR_STR, TR_LBORDER);
	configureSegment(leftOuter, TR_STR, TR_LSIDE, 6.0);
	leftOuter.vertex[TR_SL].x = 77.0;
	attachSide(TR_SIDE_LFT, &left, &leftOuter);
	tTrackSceneContext scene = context();
	generateSide(scene, TR_SIDE_LFT);
	ASSERT_GT(vertexCount, 0u);
	EXPECT_NEAR(77.0f, vertices[0], kEps);
}

class BorderDirectionTest : public SyntheticTrackSceneTest,
		public testing::WithParamInterface<std::tuple<int, int> > {};

TEST_P(BorderDirectionTest, PlanBorderMirrorsTypeNamingPairingAndTextureDirection)
{
	const int side = std::get<0>(GetParam());
	const int type = std::get<1>(GetParam());
	tTrackSeg &seg = side == TR_SIDE_LFT ? left : right;
	configureSegment(mainSeg, type, TR_MAIN);
	configureSegment(seg, type, side == TR_SIDE_LFT ? TR_LBORDER : TR_RBORDER);
	seg.style = TR_PLAN;
	attachSide(side, &seg);
	tTrackSceneContext scene = context();
	generateBorders(scene, side);
	ASSERT_GE(vertexCount, type == TR_STR ? 8u : 6u);
	EXPECT_NEAR(seg.vertex[TR_SL].z, vertices[2], kEps);
	EXPECT_NEAR(seg.vertex[TR_SR].z, vertices[5], kEps);
	EXPECT_NEAR(side == TR_SIDE_RGT ? 1.0f : 0.0f, texCoords[0], kEps);
	EXPECT_NEAR(side == TR_SIDE_RGT ? 0.0f : 0.2f, texCoords[1], kEps);
	EXPECT_NEAR(side == TR_SIDE_RGT ? 0.2f : 0.0f, texCoords[3], kEps);
	ASSERT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "t0RB" : "t0LB"));
}

INSTANTIATE_TEST_SUITE_P(SymmetricMatrix, BorderDirectionTest,
		testing::Values(
			std::make_tuple(TR_SIDE_LFT, TR_STR), std::make_tuple(TR_SIDE_RGT, TR_STR),
			std::make_tuple(TR_SIDE_LFT, TR_LFT), std::make_tuple(TR_SIDE_RGT, TR_LFT),
			std::make_tuple(TR_SIDE_LFT, TR_RGT), std::make_tuple(TR_SIDE_RGT, TR_RGT)));

class BorderStyleDirectionTest : public SyntheticTrackSceneTest,
		public testing::WithParamInterface<std::tuple<int, int, int> > {};

TEST_P(BorderStyleDirectionTest, RaisedBorderEmitsMirroredCapsAndAllSurfaceSlots)
{
	const int side = std::get<0>(GetParam());
	const int style = std::get<1>(GetParam());
	const int type = std::get<2>(GetParam());
	tTrackSeg &seg = side == TR_SIDE_LFT ? left : right;
	configureSegment(mainSeg, type, TR_MAIN);
	configureSegment(seg, type, side == TR_SIDE_LFT ? TR_LBORDER : TR_RBORDER);
	seg.style = style;
	seg.height = 1.5;
	attachSide(side, &seg);
	tTrackSceneContext scene = context();
	generateBorders(scene, side);
	EXPECT_GE(vertexCount, style == TR_WALL ? 20u : 12u);
	EXPECT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "t0RB" : "t0LB"));
	EXPECT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "t1RB" : "t1LB"));
	if (style == TR_WALL) {
		EXPECT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "t2RB" : "t2LB"));
	}
	bool foundRaised = false;
	for (unsigned int i = 0; i < vertexCount; i++) {
		foundRaised = foundRaised || std::fabs(vertices[3 * i + 2] - 2.5f) < kEps ||
				std::fabs(vertices[3 * i + 2] - 3.5f) < kEps;
	}
	EXPECT_EQ(true, foundRaised);
}

INSTANTIATE_TEST_SUITE_P(SymmetricMatrix, BorderStyleDirectionTest, testing::Values(
	std::make_tuple(TR_SIDE_LFT, TR_CURB, TR_STR), std::make_tuple(TR_SIDE_RGT, TR_CURB, TR_STR),
	std::make_tuple(TR_SIDE_LFT, TR_CURB, TR_LFT), std::make_tuple(TR_SIDE_RGT, TR_CURB, TR_LFT),
	std::make_tuple(TR_SIDE_LFT, TR_CURB, TR_RGT), std::make_tuple(TR_SIDE_RGT, TR_CURB, TR_RGT),
	std::make_tuple(TR_SIDE_LFT, TR_WALL, TR_STR), std::make_tuple(TR_SIDE_RGT, TR_WALL, TR_STR),
	std::make_tuple(TR_SIDE_LFT, TR_WALL, TR_LFT), std::make_tuple(TR_SIDE_RGT, TR_WALL, TR_LFT),
	std::make_tuple(TR_SIDE_LFT, TR_WALL, TR_RGT), std::make_tuple(TR_SIDE_RGT, TR_WALL, TR_RGT)));

class BorderTransitionTest : public SyntheticTrackSceneTest,
		public testing::WithParamInterface<std::tuple<int, int, int> > {};

TEST_P(BorderTransitionTest, AdjacentStyleControlsTransitionCaps)
{
	const int side = std::get<0>(GetParam());
	const int style = std::get<1>(GetParam());
	const int transition = std::get<2>(GetParam());
	const int borderType = side == TR_SIDE_RGT ? TR_RBORDER : TR_LBORDER;
	tTrackSeg &seg = side == TR_SIDE_LFT ? left : right;
	tTrackSeg &adjacent = side == TR_SIDE_LFT ? leftOuter : rightOuter;
	configureSegment(mainSeg, TR_STR, TR_MAIN);
	configureSegment(seg, TR_STR, borderType);
	configureSegment(adjacent, TR_STR, borderType);
	seg.style = adjacent.style = style;
	seg.height = adjacent.height = 1.5;
	track.seg = &previous;
	previous.next = &mainSeg;
	mainSeg.prev = &previous;
	mainSeg.next = &next;
	previous.side[side] = &seg;
	next.side[side] = &seg;
	mainSeg.side[side] = &seg;
	if (transition == 1) {
		previous.side[side] = nullptr;
	} else if (transition == 2) {
		adjacent.style = TR_PLAN;
		next.side[side] = &adjacent;
	} else if (transition == 3) {
		adjacent.style = TR_PLAN;
		previous.side[side] = &adjacent;
	} else if (transition == 4) {
		next.side[side] = nullptr;
	}

	tTrackSceneContext scene = context();
	generateBorders(scene, side);

	const unsigned int baseCount = style == TR_CURB ? 16u : 24u;
	const bool emitsCap = transition >= 1 && transition <= 3;
	EXPECT_EQ(baseCount + (emitsCap ? 2u : 0u), vertexCount);
	EXPECT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "t0RB" : "t0LB"));
	EXPECT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "t1RB" : "t1LB"));
	if (style == TR_WALL) {
		EXPECT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "t2RB" : "t2LB"));
	}
}

INSTANTIATE_TEST_SUITE_P(SymmetricMatrix, BorderTransitionTest, testing::Values(
	std::make_tuple(TR_SIDE_LFT, TR_CURB, 0), std::make_tuple(TR_SIDE_RGT, TR_CURB, 0),
	std::make_tuple(TR_SIDE_LFT, TR_CURB, 1), std::make_tuple(TR_SIDE_RGT, TR_CURB, 1),
	std::make_tuple(TR_SIDE_LFT, TR_CURB, 2), std::make_tuple(TR_SIDE_RGT, TR_CURB, 2),
	std::make_tuple(TR_SIDE_LFT, TR_CURB, 3), std::make_tuple(TR_SIDE_RGT, TR_CURB, 3),
	std::make_tuple(TR_SIDE_LFT, TR_CURB, 4), std::make_tuple(TR_SIDE_RGT, TR_CURB, 4),
	std::make_tuple(TR_SIDE_LFT, TR_WALL, 0), std::make_tuple(TR_SIDE_RGT, TR_WALL, 0),
	std::make_tuple(TR_SIDE_LFT, TR_WALL, 1), std::make_tuple(TR_SIDE_RGT, TR_WALL, 1),
	std::make_tuple(TR_SIDE_LFT, TR_WALL, 2), std::make_tuple(TR_SIDE_RGT, TR_WALL, 2),
	std::make_tuple(TR_SIDE_LFT, TR_WALL, 3), std::make_tuple(TR_SIDE_RGT, TR_WALL, 3),
	std::make_tuple(TR_SIDE_LFT, TR_WALL, 4), std::make_tuple(TR_SIDE_RGT, TR_WALL, 4)));

class BarrierDirectionTest : public SyntheticTrackSceneTest,
		public testing::WithParamInterface<std::tuple<int, int, int> > {};

TEST_P(BarrierDirectionTest, BothBarrierSlotsMirrorFenceAndWallWinding)
{
	const int side = std::get<0>(GetParam());
	const int style = std::get<1>(GetParam());
	const int type = std::get<2>(GetParam());
	configureSegment(mainSeg, type, TR_MAIN, 10.0);
	barriers[side].style = style;
	barriers[side].height = 2.0;
	barriers[side].width = 1.0;
	tTrackSceneContext scene = context();
	generateBarriers(scene, side);
	ASSERT_GT(vertexCount, 0u);
	tDispElt *front = findDisplay(side == TR_SIDE_RGT ? "B0Rt" : "B0Lt");
	ASSERT_NE(nullptr, front);
	const int start = front->start;
	if (style == TR_FENCE && side == TR_SIDE_LFT) {
		EXPECT_GT(vertices[3 * start + 2], vertices[3 * (start + 1) + 2]);
		EXPECT_NEAR(1.0f, texCoords[2 * start + 1], kEps);
	} else {
		EXPECT_LT(vertices[3 * start + 2], vertices[3 * (start + 1) + 2]);
		EXPECT_NEAR(side == TR_SIDE_RGT ? 0.0f : 1.0f,
				texCoords[2 * start + 1], kEps);
	}
	EXPECT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "B1Rt" : "B1Lt"));
	if (style == TR_WALL) {
		EXPECT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "B2Rt" : "B2Lt"));
	}
}

INSTANTIATE_TEST_SUITE_P(SymmetricMatrix, BarrierDirectionTest, testing::Values(
	std::make_tuple(TR_SIDE_LFT, TR_FENCE, TR_STR), std::make_tuple(TR_SIDE_RGT, TR_FENCE, TR_STR),
	std::make_tuple(TR_SIDE_LFT, TR_FENCE, TR_LFT), std::make_tuple(TR_SIDE_RGT, TR_FENCE, TR_LFT),
	std::make_tuple(TR_SIDE_LFT, TR_FENCE, TR_RGT), std::make_tuple(TR_SIDE_RGT, TR_FENCE, TR_RGT),
	std::make_tuple(TR_SIDE_LFT, TR_WALL, TR_STR), std::make_tuple(TR_SIDE_RGT, TR_WALL, TR_STR),
	std::make_tuple(TR_SIDE_LFT, TR_WALL, TR_LFT), std::make_tuple(TR_SIDE_RGT, TR_WALL, TR_LFT),
	std::make_tuple(TR_SIDE_LFT, TR_WALL, TR_RGT), std::make_tuple(TR_SIDE_RGT, TR_WALL, TR_RGT)));

class BarrierTransitionTest : public SyntheticTrackSceneTest,
		public testing::WithParamInterface<std::tuple<int, int> > {};

TEST_P(BarrierTransitionTest, WallCapsTrackAdjacentStyleAndHeight)
{
	const int side = std::get<0>(GetParam());
	const int transition = std::get<1>(GetParam());
	tTrackBarrier previousBarrier = barriers[side];
	tTrackBarrier nextBarrier = barriers[side];
	configureSegment(mainSeg, TR_STR, TR_MAIN, 10.0);
	barriers[side].style = previousBarrier.style = nextBarrier.style = TR_WALL;
	barriers[side].height = previousBarrier.height = nextBarrier.height = 2.0;
	barriers[side].width = previousBarrier.width = nextBarrier.width = 1.0;
	track.seg = &previous;
	previous.next = &mainSeg;
	mainSeg.prev = &previous;
	mainSeg.next = &next;
	previous.barrier[side] = &previousBarrier;
	next.barrier[side] = &nextBarrier;
	if (transition == 1) {
		previousBarrier.style = nextBarrier.style = TR_FENCE;
	} else if (transition == 2) {
		previousBarrier.height = nextBarrier.height = 3.0;
	}

	tTrackSceneContext scene = context();
	generateBarriers(scene, side);

	EXPECT_EQ(transition == 0 ? 24u : 28u, vertexCount);
	EXPECT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "B0Rt" : "B0Lt"));
	EXPECT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "B1Rt" : "B1Lt"));
	EXPECT_NE(nullptr, findDisplay(side == TR_SIDE_RGT ? "B2Rt" : "B2Lt"));
}

INSTANTIATE_TEST_SUITE_P(SymmetricMatrix, BarrierTransitionTest, testing::Values(
	std::make_tuple(TR_SIDE_LFT, 0), std::make_tuple(TR_SIDE_RGT, 0),
	std::make_tuple(TR_SIDE_LFT, 1), std::make_tuple(TR_SIDE_RGT, 1),
	std::make_tuple(TR_SIDE_LFT, 2), std::make_tuple(TR_SIDE_RGT, 2)));

class BarrierPitExclusionTest : public SyntheticTrackSceneTest,
		public testing::WithParamInterface<int> {};

TEST_P(BarrierPitExclusionTest, PitSideSuppressesBarrierGeometry)
{
	const int side = GetParam();
	tTrackSeg &pitSide = side == TR_SIDE_LFT ? left : right;
	configureSegment(mainSeg, TR_STR, TR_MAIN, 10.0);
	configureSegment(pitSide, TR_STR, side == TR_SIDE_LFT ? TR_LSIDE : TR_RSIDE);
	pitSide.raceInfo = TR_PIT;
	mainSeg.side[side] = &pitSide;
	tTrackSceneContext scene = context();
	checkDispList2(scene, "seed", "seed", 0);
	generateBarriers(scene, side);
	EXPECT_EQ(0u, vertexCount);
}

INSTANTIATE_TEST_SUITE_P(SymmetricMatrix, BarrierPitExclusionTest,
		testing::Values(TR_SIDE_LFT, TR_SIDE_RGT));

class TurnMarkDirectionTest : public SyntheticTrackSceneTest,
		public testing::WithParamInterface<int> {};

TEST_P(TurnMarkDirectionTest, DirectionSelectsTexturePlacementNormalAndBackFace)
{
	const int direction = GetParam();
	int mark = 10;
	tSegExt extension = { 1, &mark };
	configureSegment(mainSeg, TR_STR, TR_MAIN, 10.0);
	configureSegment(next, direction, TR_MAIN, 10.0);
	mainSeg.length = 20.0;
	mainSeg.lgfromstart = 0.0;
	mainSeg.rgtSideNormal = { 0.0, 1.0, 0.0 };
	next.length = 20.0;
	next.lgfromstart = 20.0;
	next.ext = &extension;
	next.next = &mainSeg;
	mainSeg.next = &next;
	track.seg = &next;
	track.nseg = 2;
	track.length = 40.0;
	track.graphic.turnMarksInfo = { 4.0, 3.0, 2.0, 1.0 };
	tTrackSceneContext scene = context();
	generateTurnMarks(scene);

	ASSERT_EQ(8u, vertexCount);
	const float baseY = direction == TR_LFT ? -2.0f : 15.0f;
	EXPECT_NEAR(10.0f, vertices[0], kEps);
	EXPECT_NEAR(baseY, vertices[1], kEps);
	EXPECT_NEAR(baseY - track.graphic.turnMarksInfo.width, vertices[4], kEps);
	EXPECT_NEAR(vertices[3], vertices[12], kEps);
	EXPECT_NEAR(vertices[4], vertices[13], kEps);
	EXPECT_NEAR(vertices[0], vertices[15], kEps);
	EXPECT_NEAR(vertices[1], vertices[16], kEps);
	EXPECT_NE(nullptr, findDisplay("TuMk", direction == TR_LFT ? "turn10L.rgb" : "turn10R.rgb"));
	EXPECT_NE(nullptr, findDisplay("TuMk", "back-sign.rgb"));
}

INSTANTIATE_TEST_SUITE_P(SymmetricMatrix, TurnMarkDirectionTest,
		testing::Values(TR_LFT, TR_RGT));

class StartBridgeTraversalTest : public SyntheticTrackSceneTest,
		public testing::WithParamInterface<int> {};

TEST_P(StartBridgeTraversalTest, UsesOutermostSideEndpoint)
{
	const int depth = GetParam();
	configureSegment(mainSeg, TR_STR, TR_MAIN, 10.0);
	configureSegment(left, TR_STR, TR_LSIDE);
	configureSegment(right, TR_STR, TR_RSIDE);
	configureSegment(leftOuter, TR_STR, TR_LSIDE);
	configureSegment(rightOuter, TR_STR, TR_RSIDE);
	mainSeg.vertex[TR_SL] = { 10.0, 20.0, 30.0 };
	mainSeg.vertex[TR_SR] = { 40.0, 50.0, 60.0 };
	left.vertex[TR_SL] = { 11.0, 21.0, 31.0 };
	right.vertex[TR_SR] = { 41.0, 51.0, 61.0 };
	leftOuter.vertex[TR_SL] = { 12.0, 22.0, 32.0 };
	rightOuter.vertex[TR_SR] = { 42.0, 52.0, 62.0 };
	if (depth >= 1) {
		mainSeg.lside = &left;
		mainSeg.rside = &right;
	}
	if (depth == 2) {
		left.lside = &leftOuter;
		right.rside = &rightOuter;
	}
	tTrackSceneContext scene = context();
	generateStartBridge(scene);

	const t3Dd &rightEndpoint = depth == 0 ? mainSeg.vertex[TR_SR] :
			(depth == 1 ? right.vertex[TR_SR] : rightOuter.vertex[TR_SR]);
	const t3Dd &leftEndpoint = depth == 0 ? mainSeg.vertex[TR_SL] :
			(depth == 1 ? left.vertex[TR_SL] : leftOuter.vertex[TR_SL]);
	ASSERT_EQ(54u, vertexCount);
	EXPECT_NEAR(rightEndpoint.x, vertices[0], kEps);
	EXPECT_NEAR(rightEndpoint.y - 0.1f, vertices[1], kEps);
	EXPECT_NEAR(rightEndpoint.z, vertices[2], kEps);
	EXPECT_NEAR(leftEndpoint.x, vertices[3 * 11], kEps);
	EXPECT_NEAR(leftEndpoint.y + 0.1f, vertices[3 * 11 + 1], kEps);
	EXPECT_NEAR(leftEndpoint.z, vertices[3 * 11 + 2], kEps);
	EXPECT_NE(nullptr, findDisplay("S0Bg"));
	EXPECT_NE(nullptr, findDisplay("S4Bg"));
}

INSTANTIATE_TEST_SUITE_P(LinkDepths, StartBridgeTraversalTest,
		testing::Values(0, 1, 2));

TEST_F(SyntheticTrackSceneTest, PitInitializationMirrorsSideLinksAndOffsets)
{
	for (int side : { TR_LFT, TR_RGT }) {
		tTrackPitInfo pits = {};
		configureSegment(mainSeg, TR_STR, TR_MAIN, 10.0);
		configureSegment(left, TR_STR, TR_LSIDE, 3.0);
		configureSegment(right, TR_STR, TR_RSIDE, 3.0);
		configureSegment(leftOuter, TR_STR, TR_LSIDE, 4.0);
		configureSegment(rightOuter, TR_STR, TR_RSIDE, 4.0);
		mainSeg.lside = &left;
		mainSeg.rside = &right;
		left.lside = &leftOuter;
		right.rside = &rightOuter;
		pits.type = TR_PIT_ON_TRACK_SIDE;
		pits.side = side;
		pits.nMaxPits = 1;
		pits.len = 5.0;
		pits.pitStart = &mainSeg;
		TrackSceneTestInitPits(&pits);
		ASSERT_NE(nullptr, pits.driversPits);
		const tTrkLocPos &pos = pits.driversPits[0].pos;
		if (side == TR_RGT) {
			EXPECT_NEAR(-7.0f, pos.toRight, kEps);
			EXPECT_NEAR(17.0f, pos.toLeft, kEps);
		} else {
			EXPECT_NEAR(-7.0f, pos.toLeft, kEps);
			EXPECT_NEAR(17.0f, pos.toRight, kEps);
		}
		free(pits.driversPits);
	}
}

class PitBuildingDirectionTest : public SyntheticTrackSceneTest,
		public testing::WithParamInterface<int> {};

TEST_P(PitBuildingDirectionTest, OnePitEmitsMirroredCapsAndBuildingStrip)
{
	const int side = GetParam();
	configureSegment(mainSeg, TR_STR, TR_MAIN, 10.0);
	configureSegment(left, TR_STR, TR_LSIDE, 3.0);
	configureSegment(right, TR_STR, TR_RSIDE, 3.0);
	mainSeg.lside = &left;
	mainSeg.rside = &right;
	track.pits.type = TR_PIT_ON_TRACK_SIDE;
	track.pits.side = side;
	track.pits.nMaxPits = 1;
	track.pits.len = 5.0;
	track.pits.pitStart = &mainSeg;
	tTrackSceneContext scene = context();
	generatePits(scene);

	ASSERT_EQ(22u, vertexCount);
	EXPECT_NEAR(side == TR_RGT ? 5.0f : 0.0f, vertices[3 * 6], kEps);
	EXPECT_NEAR(side == TR_RGT ? 0.0f : 5.0f, vertices[3 * 7], kEps);
	EXPECT_NEAR(5.0f, std::fabs(vertices[3 * 6] - vertices[3 * 7]), kEps);
	EXPECT_NEAR(side == TR_RGT ? -3.0f : 13.0f, vertices[3 * 6 + 1], kEps);
	EXPECT_NEAR(vertices[3 * 6 + 1], vertices[3 * 7 + 1], kEps);
	tDispElt *startCap = findDisplay("P1ts");
	tDispElt *building = findDisplay("P2ts");
	tDispElt *endCap = findDisplay("P3ts");
	ASSERT_NE(nullptr, startCap);
	ASSERT_NE(nullptr, building);
	ASSERT_NE(nullptr, endCap);
	EXPECT_EQ(0, startCap->start);
	EXPECT_EQ(6, building->start);
	EXPECT_EQ(16, endCap->start);
	free(track.pits.driversPits);
	track.pits.driversPits = nullptr;
}

INSTANTIATE_TEST_SUITE_P(SymmetricMatrix, PitBuildingDirectionTest,
		testing::Values(TR_LFT, TR_RGT));

TEST(TrackSceneSaveObjectTest, ConvertsCoordinatesAndPreservesVertexOrder)
{
	const float vertices[] = {
		1.0f, 2.0f, 3.0f,
		4.0f, 5.0f, 6.0f,
		7.0f, 8.0f, 9.0f
	};
	const float texCoords[] = { 0.0f, 0.1f, 0.2f, 0.3f, 0.4f, 0.5f };
	const std::string output = saveObject(vertices, texCoords, 3);

	EXPECT_NE(std::string::npos, output.find(
			"numvert 3\n1.000000 3.000000 -2.000000\n"
			"4.000000 6.000000 -5.000000\n"
			"7.000000 9.000000 -8.000000\n"));
	EXPECT_NE(std::string::npos, output.find(
			"0 0.000000 0.100000\n1 0.200000 0.300000\n"
			"2 0.400000 0.500000\n"));
}

TEST(TrackSceneSaveObjectTest, ConvertsFourVertexStripToCounterClockwiseTriangles)
{
	const float vertices[12] = {};
	const float texCoords[8] = {};
	const std::string output = saveObject(vertices, texCoords, 4);

	EXPECT_NE(std::string::npos, output.find("numsurf 2\n"));
	EXPECT_NE(std::string::npos, output.find(
			"2 0.000000 0.000000\n1 0.000000 0.000000\n"
			"3 0.000000 0.000000\n"));
}

TEST(TrackSceneSaveObjectTest, AlternatesWindingForFiveVertexStrip)
{
	const float vertices[15] = {};
	const float texCoords[10] = {};
	const std::string output = saveObject(vertices, texCoords, 5);

	EXPECT_NE(std::string::npos, output.find("numsurf 3\n"));
	EXPECT_NE(std::string::npos, output.find(
			"3 0.000000 0.000000\n4 0.000000 0.000000\n"));
}

TEST(TrackScenePointTest, StoresVertexTextureCoordinatesAndIndexInOrder)
{
	float vertices[6] = {};
	float texCoords[4] = {};
	unsigned int indices[2] = {};
	tTexElt texture = {};
	unsigned int vertexCount = 0;
	texture.name = const_cast<char *>("road.rgb");
	trackvertices = vertices;
	tracktexcoord = texCoords;
	trackindices = indices;

	setPoint(&texture, 0.25f, 0.75f, 1.0f, 2.0f, 3.0f, vertexCount);
	setPoint(&texture, 0.5f, 1.0f, 4.0f, 5.0f, 6.0f, vertexCount);

	EXPECT_EQ(2u, vertexCount);
	EXPECT_NEAR(1.0f, vertices[0], kEps);
	EXPECT_NEAR(3.0f, vertices[2], kEps);
	EXPECT_NEAR(4.0f, vertices[3], kEps);
	EXPECT_NEAR(0.25f, texCoords[0], kEps);
	EXPECT_NEAR(0.75f, texCoords[1], kEps);
	EXPECT_NEAR(1.0f, texCoords[3], kEps);
	EXPECT_EQ(0u, indices[0]);
	EXPECT_EQ(1u, indices[1]);
}

TEST(TrackScenePointTest, IgnoresVerticesForEmptyTexture)
{
	float vertices[3] = { 7.0f, 8.0f, 9.0f };
	float texCoords[2] = { 0.25f, 0.75f };
	unsigned int indices[1] = { 4u };
	tTexElt texture = {};
	unsigned int vertexCount = 0;
	texture.name = const_cast<char *>("");
	trackvertices = vertices;
	tracktexcoord = texCoords;
	trackindices = indices;

	setPoint(&texture, 1.0f, 1.0f, 1.0f, 2.0f, 3.0f, vertexCount);

	EXPECT_EQ(0u, vertexCount);
	EXPECT_NEAR(7.0f, vertices[0], kEps);
	EXPECT_NEAR(0.25f, texCoords[0], kEps);
	EXPECT_EQ(4u, indices[0]);
}

TEST(TrackSceneDisplayListTest, SplitsAndClosesListsAtVertexBoundary)
{
	Groups = static_cast<tGroup *>(calloc(1, sizeof(tGroup)));
	GroupNb = 1;
	ActiveGroups = 0;
	tTexElt firstTexture = {};
	tTexElt secondTexture = {};
	tTrack track = {};
	tTexElt *textureList = nullptr;
	tTexElt *selectedTexture = &firstTexture;
	tDispElt *current = nullptr;
	unsigned int vertexCount = 2;
	unsigned int textureId = 0;
	unsigned int previousTextureId = 0;
	int startNeeded = 0;
	int textureType = 0;
	int textureLink = 0;
	tdble textureOffset = 0.0;
	tdble textureSize = 20.0;
	firstTexture.namebump = const_cast<char *>("first-bump.rgb");
	secondTexture.namebump = const_cast<char *>("second-bump.rgb");
	tTrackSceneContext scene = { &track, nullptr, 0, 10.0, vertexCount,
		textureList, selectedTexture, current, textureId, previousTextureId,
		startNeeded, textureType, textureLink, textureOffset, textureSize };

	newDispList(scene, 1, "road", 0);
	vertexCount = 8;
	selectedTexture = &secondTexture;
	newDispList(scene, 1, "side", 0);

	ASSERT_NE(nullptr, current);
	EXPECT_EQ(1, ActiveGroups);
	EXPECT_EQ(2, Groups[0].nb);
	EXPECT_EQ(8, current->start);
	EXPECT_EQ(0, current->nb);
	EXPECT_EQ(2, current->next->start);
	EXPECT_EQ(6, current->next->nb);
	EXPECT_EQ(&secondTexture, current->texture);
	EXPECT_EQ(1, startNeeded);
	releaseDisplayLists();
}

TEST(TrackSceneDisplayListTest, ReusesEmptyListAndSuppressesMissingBumpTexture)
{
	Groups = static_cast<tGroup *>(calloc(1, sizeof(tGroup)));
	GroupNb = 1;
	ActiveGroups = 0;
	tTexElt firstTexture = {};
	tTexElt secondTexture = {};
	tTrack track = {};
	tTexElt *textureList = nullptr;
	tTexElt *selectedTexture = &firstTexture;
	tDispElt *current = nullptr;
	unsigned int vertexCount = 4;
	unsigned int textureId = 0;
	unsigned int previousTextureId = 0;
	int startNeeded = 0;
	int textureType = 0;
	int textureLink = 0;
	tdble textureOffset = 0.0;
	tdble textureSize = 20.0;
	firstTexture.namebump = const_cast<char *>("first-bump.rgb");
	secondTexture.namebump = const_cast<char *>("");
	tTrackSceneContext scene = { &track, nullptr, 0, 10.0, vertexCount,
		textureList, selectedTexture, current, textureId, previousTextureId,
		startNeeded, textureType, textureLink, textureOffset, textureSize };

	newDispList(scene, 1, "road", 0);
	selectedTexture = &secondTexture;
	newDispList(scene, 1, "road", 0);
	scene.bump = 1;
	vertexCount = 9;
	newDispList(scene, 1, "bump", 0);

	EXPECT_EQ(1, Groups[0].nb);
	EXPECT_EQ(&secondTexture, current->texture);
	EXPECT_EQ(4, current->start);
	releaseDisplayLists();
}

TEST(TrackScenePitCapTest, ClockwiseAndCounterClockwiseCapsUseOppositeWinding)
{
	float clockwiseVertices[18] = {};
	float clockwiseTexCoords[12] = {};
	float counterVertices[18] = {};
	float counterTexCoords[12] = {};

	EXPECT_EQ(6u, TrackSceneTestGeneratePitCap(1, 10.0, 20.0, 3.0,
			1.0, 0.0, clockwiseVertices, clockwiseTexCoords));
	EXPECT_EQ(6u, TrackSceneTestGeneratePitCap(0, 10.0, 20.0, 3.0,
			1.0, 0.0, counterVertices, counterTexCoords));

	EXPECT_NEAR(8.0f, clockwiseVertices[2], kEps);
	EXPECT_NEAR(7.8f, clockwiseVertices[5], kEps);
	EXPECT_NEAR(7.8f, counterVertices[2], kEps);
	EXPECT_NEAR(8.0f, counterVertices[5], kEps);
	EXPECT_NEAR(5.0f, clockwiseTexCoords[1], kEps);
	EXPECT_NEAR(4.8f, counterTexCoords[1], kEps);
	EXPECT_NEAR(0.0f, clockwiseVertices[6], kEps);
	EXPECT_NEAR(10.0f, counterVertices[6], kEps);
}
