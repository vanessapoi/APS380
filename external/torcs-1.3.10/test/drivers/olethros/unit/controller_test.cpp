/***************************************************************************

    file                 : controller_test.cpp
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
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <memory>
#include <string>
#include <tuple>
#include <vector>
#include "PlanningMesh.h"
#include "driver.h"

static const float kEps = 1e-5f;

// Keep service decisions independent of the observations under test.
class NoPitStrategy : public AbstractStrategy {
public:
	void setFuelAtRaceStart(tTrack*, void**, tSituation*) override {}
	void update(tCarElt*, tSituation*) override {}
	bool needPitstop(tCarElt*, tSituation*, Opponents*) override { return false; }
	float pitRefuel(tCarElt*, tSituation*) override { return 0; }
	int pitRepair(tCarElt*, tSituation*) override { return 0; }
	float getSpeedFactor(tCarElt*, tSituation*, Opponents*) override { return 1; }
};

class ControllerDriver : public Driver {
public:
	explicit ControllerDriver(int index) : Driver(index) {}
	ControllerDriver(int index, tTrack& t, tCarElt& c, const tSituation& s, bool practiceSession = false) : Driver(index)
	{
		// Supply initTrack's dependencies in memory. The fixture isolates brain
		// reads; ordinary controller cases use race control/teardown without saving.
		track = &t;
		strategy = new NoPitStrategy;
		MU_FACTOR = 1;
		tSituation initial = s;
		initial._raceType = RM_TYPE_PRACTICE;
		newRace(&c, &initial);
		if (!practiceSession) race_type = RM_TYPE_RACE;
	}

	void observe(tSituation& s) { update(&s); }
	std::string setupFileName(const char* filename, int raceType) const
	{
		char buffer[256];
		getSetupFileName(buffer, sizeof(buffer), filename, raceType);
		return buffer;
	}
	int selectedGear() { return getGear(); }
	float timeStep() const { return dt; }
	float aloneTimer() const { return alone_count; }
	bool drivingAlone() const { return alone != 0; }
	float sideSteer(float steer = 0) { return filterSColl(steer); }
	float overtakeOffset() { return getOffset(); }
	void resetOffset() { myoffset = 0; }
	void setOffset(float offset) { myoffset = offset; }
	float offset() const { return myoffset; }
	bool isOvertaking() const { return overtaking; }
	float lookahead() const { return oldlookahead; }
	void setTractionState(float state) { TCL_status = state; }
	float tractionState() const { return TCL_status; }
	void readyRecovery() { stuck = MAX_UNSTUCK_COUNT + 1; }
	float steeringFor(const v2d& target) const { return getSteer(target); }
	void trackFeedback(tSituation& s, float baseSteer) { updateTrackFeedback(&s, baseSteer); }
	float steeringPrediction(tCarElt& sample) { return learn->predictedError(&sample); }
	void setPathCurvature(double curvature)
	{
		std::fill(planningMesh->curvature.begin(), planningMesh->curvature.end(), curvature);
	}
	Pit& pitAdapter() { return *pit; }
	float pitBrake(float brake = 0) { return filterBPit(brake); }
	v2d steeringTarget() { return updateTargetPoint(); }
	PlanningPoint expectedPitTarget(double offset, double distance = 6) const
	{
		PlanningSection road = planningMesh->at(currentStation() + distance);
		return road.point(0.5) + (road.left - road.right)*(offset/(road.left - road.right).length());
	}
	void setPathWeight(double weight)
	{
		std::fill(planningMesh->trajectory.weights.begin(), planningMesh->trajectory.weights.end(), weight);
		planningMesh->finish();
	}
	float currentSpeedHistory() const { return pathSpeedHistory(currentStation()); }
	void seedSpeedHistory(float speed)
	{
		std::fill(meshSpeedHistory.begin(), meshSpeedHistory.end(), speed);
		alone_count = 3;
	}
	void reorderOpponents(tSituation& s)
	{
		delete opponents;
		opponents = new Opponents(&s, this, cardata);
		opponent = opponents->getOpponentPtr();
	}
};

class ControllerTest : public testing::Test {
protected:
	std::filesystem::path brainDirectory;
	std::string originalLocalDir;
	char trackName[32] = "controller-fixture";
	tTrackSurface surface = {};
	std::array<tTrackSeg, 4> segments = {};
	tTrack track = {};
	std::array<tCarElt, 3> cars = {};
	std::array<tCarElt*, 3> order = {};
	tSituation situation = {};
	std::unique_ptr<void, void (*)(void*)> parameters{nullptr, GfParmReleaseHandle};
	tTrackOwnPit ownPit = {};
	tTrackSeg pitEntry = {}, pitStart = {}, pitExit = {};
	// Drivers are destroyed before their borrowed track, car and setup storage.
	std::vector<std::unique_ptr<ControllerDriver>> drivers;

	static void SetUpTestSuite() { GfInit(); }

	void SetUp() override
	{
		originalLocalDir = GetLocalDir();
		brainDirectory = std::filesystem::temp_directory_path()/
			("olethros-controller-" + std::to_string(GetCurrentProcessId()) + "-" +
			std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
		ASSERT_TRUE(std::filesystem::create_directory(brainDirectory));
		std::string local = brainDirectory.generic_string() + "/";
		SetLocalDir(&local[0]);
		// An empty filename with CREAT produces an empty private parameter set,
		// without reading a user setup or creating a file on disk.
		parameters.reset(GfParmReadFile("", GFPARM_RMODE_CREAT | GFPARM_RMODE_PRIVATE));
		ASSERT_NE(parameters.get(), nullptr);
		GfParmSetNum(parameters.get(), SECT_AERODYNAMICS, PRM_CX, NULL, 0.3f);
		GfParmSetNum(parameters.get(), SECT_AERODYNAMICS, PRM_FRNTAREA, NULL, 2);
		buildTrack();
		situation.cars = order.data();
		situation._ncars = (int)cars.size();
		situation._raceType = RM_TYPE_RACE;
		situation.deltaTime = RCM_MAX_DT_ROBOTS;
		for (size_t i = 0; i < cars.size(); ++i) {
			tCarElt& car = cars[i];
			order[i] = &car;
			car.index = (int)i;
			car._carHandle = parameters.get();
			car._pos = (int)i + 1;
			car._dimension_x = 4;
			car._dimension_y = 2;
			car._steerLock = 0.5f;
			car._fuel = 40;
			car._tank = 80;
			car._gear = 2;
			car._gearOffset = 1;
			car._gearNb = 4;
			car._gearRatio[0] = -2;
			car._gearRatio[2] = 4;
			car._gearRatio[3] = 2.5f;
			car._gearRatio[4] = 1.8f;
			car._enginerpm = 300;
			car._enginerpmMaxTq = 400;
			car._enginerpmMaxPw = 600;
			car._enginerpmRedLine = 800;
			car._enginerpmMax = 1000;
			car._engineMaxTq = 400;
			car._engineMaxPw = 150000;
			placeCar(i, 40 + 60*(float)i, 0, 20);
		}
	}

	void TearDown() override
	{
		drivers.clear(); // Shutdown must still use the isolated directory.
		SetLocalDir(&originalLocalDir[0]);
		std::error_code error;
		std::filesystem::remove_all(brainDirectory, error);
	}

	void buildTrack()
	{
		// Closed, tangent-continuous stadium: two 200 m straights and two R=50 m turns.
		surface.kFriction = 1;
		PlanningPoint right = {0, -15};
		double heading = 0, station = 0;
		for (size_t i = 0; i < segments.size(); ++i) {
			tTrackSeg& seg = segments[i];
			seg.id = (int)i;
			seg.type = i%2 ? TR_LFT : TR_STR;
			seg.length = i%2 ? (float)(50*PI) : 200;
			seg.radius = i%2 ? 50 : 0;
			seg.radiusr = i%2 ? 65 : 0;
			seg.radiusl = i%2 ? 35 : 0;
			seg.arc = i%2 ? (float)PI : 0;
			seg.width = seg.startWidth = seg.endWidth = 30;
			seg.surface = &surface;
			seg.angle[TR_ZS] = (float)heading;
			seg.lgfromstart = (float)station;
			seg.vertex[TR_SR].x = (float)right.x;
			seg.vertex[TR_SR].y = (float)right.y;
			PlanningSection start = PlanningMesh::evaluate(seg, 0);
			PlanningSection end = PlanningMesh::evaluate(seg, seg.length);
			seg.vertex[TR_SL].x = (float)start.left.x;
			seg.vertex[TR_SL].y = (float)start.left.y;
			seg.vertex[TR_EL].x = (float)end.left.x;
			seg.vertex[TR_EL].y = (float)end.left.y;
			seg.vertex[TR_ER].x = (float)end.right.x;
			seg.vertex[TR_ER].y = (float)end.right.y;
			seg.next = &segments[(i+1)%segments.size()];
			seg.prev = &segments[(i+segments.size()-1)%segments.size()];
			right = end.right;
			heading += seg.arc;
			station += seg.length;
		}
		track.seg = segments.data();
		track.internalname = trackName;
		track.nseg = (int)segments.size();
		track.length = (float)station;
		track.width = 30;
	}

	void placeCar(size_t index, float station, float middle, float speed, float yaw = 0)
	{
		tCarElt& car = cars[index];
		station = (float)std::fmod((double)station + track.length, track.length);
		tTrackSeg* seg = &segments[0];
		for (tTrackSeg& candidate : segments) {
			if (station >= candidate.lgfromstart) seg = &candidate;
		}
		float local = station - seg->lgfromstart;
		float heading = seg->angle[TR_ZS] + (seg->type == TR_STR ? 0 : local/seg->radius);
		PlanningSection road = PlanningMesh::evaluate(*seg, local);
		PlanningPoint point = road.point(0.5 + middle/seg->width);
		car._trkPos.seg = seg;
		car._trkPos.toStart = seg->type == TR_STR ? local : local/seg->radius;
		car._distFromStartLine = station;
		car._trkPos.toMiddle = middle;
		car._trkPos.toLeft = 15 - middle;
		car._trkPos.toRight = 15 + middle;
		car._pos_X = (float)point.x;
		car._pos_Y = (float)point.y;
		car._yaw = heading + yaw;
		car._speed_X = speed*(float)std::cos(heading);
		car._speed_Y = speed*(float)std::sin(heading);
		car._speed_x = speed*(float)std::cos(yaw);
		car._speed_y = -speed*(float)std::sin(yaw);
		for (int wheel = 0; wheel < 4; ++wheel) {
			car._wheelRadius(wheel) = 0.33f;
			car._wheelSpinVel(wheel) = speed/car._wheelRadius(wheel);
		}
	}

	void configurePit(int side, bool wraps)
	{
		// Boundary descriptors carry the native stations used by the pit adapter.
		pitEntry.lgfromstart = wraps ? track.length - 40 : 20;
		pitStart.lgfromstart = wraps ? 20 : 40;
		pitExit.lgfromstart = 180;
		ownPit.pos.seg = &segments[0];
		ownPit.pos.toStart = wraps ? 80 : 100;
		ownPit.pos.toMiddle = side == TR_LFT ? 20 : -20;
		track.pits.pitEntry = &pitEntry;
		track.pits.pitStart = &pitStart;
		track.pits.pitExit = &pitExit;
		track.pits.driversPits = &ownPit;
		track.pits.len = 10;
		track.pits.nMaxPits = 4;
		track.pits.width = 3;
		track.pits.speedLimit = 20;
		track.pits.side = side;
		cars[0]._pit = &ownPit;
		cars[1]._state = cars[2]._state = RM_CAR_STATE_NO_SIMU;
	}

	v2d orientCarAndTarget(float heading, float longitudinal, float lateral, float bearing = 0)
	{
		tCarElt& car = cars[0];
		car._yaw = heading;
		car._speed_x = longitudinal; car._speed_y = lateral;
		car._speed_X = longitudinal*std::cos(heading)-lateral*std::sin(heading);
		car._speed_Y = longitudinal*std::sin(heading)+lateral*std::cos(heading);
		return v2d(car._pos_X+80*std::cos(heading+bearing), car._pos_Y+80*std::sin(heading+bearing));
	}

	ControllerDriver& addDriver(size_t index)
	{
		drivers.emplace_back(new ControllerDriver((int)index, track, cars[index], situation));
		return *drivers.back();
	}

	void advance(double step = RCM_MAX_DT_ROBOTS)
	{
		situation.currentTime += step;
		situation.deltaTime = step;
	}
};

TEST_F(ControllerTest, SteeringIsIndependentOfCompassHeadingIncludingNearBorders)
{
	ControllerDriver& driver = addDriver(0);
	// Center, right edge and left edge; zero and mirrored lateral slip. Rotate
	// pose, velocity and target together, retaining the same local situation.
	for (float middle : {0.0f, -13.5f, 13.5f}) for (float lateral : {-3.0f, 0.0f, 3.0f}) {
		placeCar(0, 40, middle, 60);
		cars[0]._yaw_rate = 0.15f;
		float reference = driver.steeringFor(orientCarAndTarget(0, 60, lateral, 0.08f));
		for (float heading : {-3.14f, -1.57f, 0.7f, 1.57f, 3.14f}) {
			SCOPED_TRACE(::testing::Message() << "middle=" << middle << " lateral=" << lateral << " heading=" << heading);
			EXPECT_NEAR(driver.steeringFor(orientCarAndTarget(heading, 60, lateral, 0.08f)), reference, kEps);
		}
	}
}

TEST_F(ControllerTest, SmallSlipAcrossWorldHeadingWrapDoesNotKickSteering)
{
	ControllerDriver& driver = addDriver(0);
	float left = driver.steeringFor(orientCarAndTarget((float)PI, 60, 0.06f));
	float right = driver.steeringFor(orientCarAndTarget((float)PI, 60, -0.06f));
	// These velocities straddle world heading +/-pi, but differ by only 0.002
	// radians in body slip. The old world-angle term kicked by about 0.0628.
	EXPECT_LT(std::fabs(left-right), 1e-4f);
	EXPECT_LT(left, right);
}

TEST_F(ControllerTest, DriftCorrectionCountersteersSlipAndIsZeroWhenAligned)
{
	ControllerDriver& driver = addDriver(0);
	for (float heading : {0.0f, 1.5f, -2.5f}) {
		SCOPED_TRACE(heading);
		EXPECT_NEAR(driver.steeringFor(orientCarAndTarget(heading, 60, 0)), 0, kEps);
		EXPECT_NEAR(driver.steeringFor(orientCarAndTarget(heading, 0, 0)), 0, kEps);
		float left = driver.steeringFor(orientCarAndTarget(heading, 60, 3));
		float right = driver.steeringFor(orientCarAndTarget(heading, 60, -3));
		EXPECT_LT(left, 0);
		EXPECT_GT(right, 0);
		EXPECT_NEAR(left, -right, kEps);
	}
}

TEST_F(ControllerTest, PracticeSessionsReloadAndExtendSavedLearning)
{
	situation._raceType = RM_TYPE_PRACTICE;
	const auto brain = brainDirectory/"drivers/olethros/6/controller-fixture.brain";
	ASSERT_FALSE(std::filesystem::exists(brain));
	float previousPrediction = 0;
	for (int session = 0; session < 3; ++session) {
		SCOPED_TRACE(session);
		placeCar(0, 40, 0, 20);
		{
			// Displayed Olethros 7 uses index 6. Exercise real newRace loading and
			// destructor saving, including the first session with no brain present.
			ControllerDriver driver(6, track, cars[0], situation, true);
			EXPECT_NEAR(driver.steeringPrediction(cars[0]), previousPrediction, kEps);
			for (float station : {40.0f, 210.0f}) {
				placeCar(0, station, 0, 20);
				advance(); driver.observe(situation);
				driver.trackFeedback(situation, 0.8f + 0.2f*session);
			}
			placeCar(0, 40, 0, 20);
			float prediction = driver.steeringPrediction(cars[0]);
			EXPECT_GT(std::fabs(prediction - previousPrediction), kEps);
			previousPrediction = prediction;
		}
		ASSERT_TRUE(std::filesystem::exists(brain));
	}
}

class DriverTimingTest : public ControllerTest, public testing::WithParamInterface<bool> {};

TEST(DriverSetup, KnownSessionsAcceptBareAndQualifiedTrackNames)
{
	ControllerDriver driver(6);
	struct Session { int type; const char* directory; };
	for (const Session& session : {Session{RM_TYPE_PRACTICE, "practice"},
		Session{RM_TYPE_QUALIF, "qualifying"}, Session{RM_TYPE_RACE, "race"}}) {
		SCOPED_TRACE(session.directory);
		std::string expected = std::string("drivers/olethros/6/") + session.directory + "/forza.xml";
		EXPECT_EQ(driver.setupFileName("forza.xml", session.type), expected);
		EXPECT_EQ(driver.setupFileName("tracks/road/forza/forza.xml", session.type), expected);
	}
}

TEST(DriverSetup, UnknownSessionSelectsDefaultSetup)
{
	ControllerDriver driver(6);
	for (int type : {-1, 99}) {
		SCOPED_TRACE(type);
		EXPECT_EQ(driver.setupFileName("forza.xml", type), "drivers/olethros/6/default.xml");
	}
}

class GearBoundsTest : public ControllerTest, public testing::WithParamInterface<int> {};

TEST_P(GearBoundsTest, HighestGearDoesNotRequestAnotherUpshift)
{
	ControllerDriver& driver = addDriver(0);
	int highest = GetParam();
	cars[0]._gear = highest;
	cars[0]._gearNb = highest + 1;
	cars[0]._gearRatio[highest + cars[0]._gearOffset] = 2;
	cars[0]._gearRatio[highest - 1 + cars[0]._gearOffset] = 3;
	cars[0]._speed_x = cars[0]._wheelRadius(REAR_RGT)*cars[0]._enginerpmRedLine/2;
	EXPECT_EQ(driver.selectedGear(), highest);
}

TEST_P(GearBoundsTest, HighestGearCanStillDownshift)
{
	ControllerDriver& driver = addDriver(0);
	int highest = GetParam();
	cars[0]._gear = highest;
	cars[0]._gearNb = highest + 1;
	cars[0]._gearRatio[highest + cars[0]._gearOffset] = 2;
	cars[0]._gearRatio[highest - 1 + cars[0]._gearOffset] = 3;
	cars[0]._speed_x = 30;
	EXPECT_EQ(driver.selectedGear(), highest - 1);
}

INSTANTIATE_TEST_SUITE_P(Transmissions, GearBoundsTest, testing::Values(6, MAX_GEARS - 2));

TEST_F(ControllerTest, GearSelectionKeepsNormalUpshiftAndLaunchBehavior)
{
	ControllerDriver& driver = addDriver(0);
	for (float rpm : {650.0f, 800.0f}) {
		SCOPED_TRACE(rpm);
		cars[0]._gear = 2;
		cars[0]._speed_x = cars[0]._wheelRadius(REAR_RGT)*rpm/cars[0]._gearRatio[3];
		EXPECT_EQ(driver.selectedGear(), 3); // Torque advantage, then redline threshold.
	}
	for (int gear : {-1, 0, 1}) {
		SCOPED_TRACE(gear);
		cars[0]._gear = gear;
		cars[0]._speed_x = 0;
		EXPECT_EQ(driver.selectedGear(), 1);
	}
	cars[0]._gear = 2;
	cars[0]._speed_x = 20;
	EXPECT_EQ(driver.selectedGear(), 1);
}

TEST_P(DriverTimingTest, EveryBotAdvancesWhenCallbackOrderChanges)
{
	ControllerDriver& first = addDriver(0);
	ControllerDriver& second = addDriver(1);
	double elapsed = 0;
	for (int tick = 0; tick < 110; ++tick) {
		SCOPED_TRACE(tick);
		double step = tick%2 ? 0.03 : 0.02;
		advance(step);
		elapsed += step;
		bool reverse = GetParam() != (tick >= 3);
		(reverse ? second : first).observe(situation);
		(reverse ? first : second).observe(situation);
		ASSERT_NEAR(first.timeStep(), step, kEps);
		ASSERT_NEAR(second.timeStep(), step, kEps);
		if (elapsed < 2) {
			EXPECT_NEAR(first.aloneTimer(), elapsed, kEps);
			EXPECT_NEAR(second.aloneTimer(), elapsed, kEps);
		}
	}
	EXPECT_TRUE(first.drivingAlone());
	EXPECT_TRUE(second.drivingAlone());
}

TEST_P(DriverTimingTest, DriveUpdatesBothBotsSpeedHistoryUsingTheirTimeStep)
{
	ControllerDriver& first = addDriver(0);
	ControllerDriver& second = addDriver(1);
	first.seedSpeedHistory(40);
	second.seedSpeedHistory(40);
	double expected = 40;
	for (double step : {0.02, 0.04}) {
		SCOPED_TRACE(step);
		advance(step);
		(GetParam() ? second : first).drive(&situation);
		(GetParam() ? first : second).drive(&situation);
		expected += 0.1*step*(25 - expected); // 20 m/s observation plus 5 m/s margin.
		EXPECT_LT(first.currentSpeedHistory(), 40);
		EXPECT_LT(second.currentSpeedHistory(), 40);
		EXPECT_NEAR(first.currentSpeedHistory(), expected, kEps);
		EXPECT_NEAR(second.currentSpeedHistory(), expected, kEps);
	}
}

INSTANTIATE_TEST_SUITE_P(CallbackOrders, DriverTimingTest, testing::Bool(),
	[](const testing::TestParamInfo<bool>& info) { return info.param ? "SecondFirst" : "FirstFirst"; });

TEST_F(ControllerTest, SharedObservationsRefreshOnceWhileEveryBotGetsTheEngineStep)
{
	ControllerDriver& first = addDriver(0);
	ControllerDriver& second = addDriver(1);
	// The shared cache can be older than the most recent engine robot interval.
	advance(1);
	situation.deltaTime = RCM_MAX_DT_ROBOTS;
	first.observe(situation);
	// Deliberately change a source value between callbacks to detect a second refresh.
	cars[1]._speed_X = 35;
	second.observe(situation);
	EXPECT_NEAR(second.getSpeed(), 20, kEps);
	EXPECT_NEAR(first.timeStep(), RCM_MAX_DT_ROBOTS, kEps);
	EXPECT_NEAR(second.timeStep(), RCM_MAX_DT_ROBOTS, kEps);
	advance();
	second.observe(situation);
	EXPECT_NEAR(second.getSpeed(), 35, kEps);
}

TEST_F(ControllerTest, NonpositiveEngineStepDoesNotAdvanceLocalTimers)
{
	ControllerDriver& first = addDriver(0);
	ControllerDriver& second = addDriver(1);
	for (double step : {0.0, -0.02}) {
		SCOPED_TRACE(step);
		advance();
		situation.deltaTime = step;
		first.observe(situation);
		second.observe(situation);
		EXPECT_NEAR(first.timeStep(), 0, kEps);
		EXPECT_NEAR(second.timeStep(), 0, kEps);
		EXPECT_NEAR(first.aloneTimer(), 0, kEps);
		EXPECT_NEAR(second.aloneTimer(), 0, kEps);
	}
}

class SideCollisionTest : public ControllerTest, public testing::WithParamInterface<int> {};

TEST_P(SideCollisionTest, IrrelevantSideCarAndListOrderDoNotChangeAvoidance)
{
	int side = GetParam();
	placeCar(1, 40, side*2.2f, 20, -side*0.1f);
	placeCar(2, 40, -side*12.0f, 20);
	cars[2]._dimension_y = 3; // Different widths must stay paired with their own gaps.
	cars[2]._state = RM_CAR_STATE_NO_SIMU;
	ControllerDriver& driver = addDriver(0);
	advance();
	driver.observe(situation);
	float expected = driver.sideSteer();
	ASSERT_LT(side*expected, -0.1f); // Must actively steer away, not just agree at zero.
	cars[2]._state = 0;
	for (bool reverse : {false, true}) {
		SCOPED_TRACE(reverse);
		if (reverse) std::swap(order[1], order[2]);
		driver.reorderOpponents(situation);
		advance();
		driver.observe(situation);
		EXPECT_NEAR(driver.sideSteer(), expected, kEps);
	}
}

INSTANTIATE_TEST_SUITE_P(Sides, SideCollisionTest, testing::Values(-1, 1),
	[](const testing::TestParamInfo<int>& info) { return info.param < 0 ? "Right" : "Left"; });

class OvertakingTest : public ControllerTest,
	public testing::WithParamInterface<std::tuple<int, float>> {};

TEST_P(OvertakingTest, SelectedCatchTimeSurvivesOtherCandidatesAndReordering)
{
	int side = std::get<0>(GetParam());
	float speed = std::get<1>(GetParam());
	// Raw gaps 27 and 67 m become 20 and 60 m after the car/safety margins.
	// Closing speeds give the selected car catch times of 1, 2, or 4 seconds:
	// imminent pass, exact threshold, and recent-collision fallback respectively.
	placeCar(1, 67, side*4.0f, speed);
	placeCar(2, 107, -side*4.0f, 19);
	cars[2]._state = RM_CAR_STATE_NO_SIMU;
	ControllerDriver& driver = addDriver(0);
	advance();
	driver.observe(situation);
	double catchTime = 20.0/(20 - speed);
	double expected = -side*(2*RCM_MAX_DT_ROBOTS)*3/(1 + catchTime);
	EXPECT_NEAR(driver.overtakeOffset(), expected, kEps);
	cars[2]._state = 0;
	for (bool reverse : {false, true}) {
		SCOPED_TRACE(reverse);
		if (reverse) std::swap(order[1], order[2]);
		driver.reorderOpponents(situation);
		driver.resetOffset();
		advance();
		driver.observe(situation);
		EXPECT_NEAR(driver.overtakeOffset(), expected, kEps);
	}
}

INSTANTIATE_TEST_SUITE_P(SidesAndCatchTimes, OvertakingTest,
	testing::Combine(testing::Values(-1, 1), testing::Values(0.0f, 10.0f, 15.0f)));

TEST_F(ControllerTest, ExactCatchThresholdWithoutRecentCollisionDoesNotStartPassing)
{
	placeCar(1, 67, 4, 10);
	cars[2]._state = RM_CAR_STATE_NO_SIMU;
	ControllerDriver& driver = addDriver(0);
	advance(5); // Expire the collision/overtake memory below its 0.1 threshold.
	driver.observe(situation);
	EXPECT_NEAR(driver.overtakeOffset(), 0, kEps);
}

TEST_F(ControllerTest, IgnoredOpponentsLeaveSteeringAndOffsetUnchanged)
{
	cars[1]._state = cars[2]._state = RM_CAR_STATE_NO_SIMU;
	ControllerDriver& driver = addDriver(0);
	advance();
	driver.observe(situation);
	EXPECT_NEAR(driver.sideSteer(0.2f), 0.2f, kEps);
	EXPECT_NEAR(driver.overtakeOffset(), 0, kEps);
}

class PitTransitionTest : public ControllerTest,
	public testing::WithParamInterface<std::tuple<int, bool>> {};

TEST_P(PitTransitionTest, ManeuverAndTargetFollowRequestOccupancyAndService)
{
	int side = std::get<0>(GetParam());
	bool wraps = std::get<1>(GetParam());
	configurePit(side, wraps);
	placeCar(0, pitEntry.lgfromstart - 250, 0, 10);
	ControllerDriver& driver = addDriver(0);
	driver.setPathWeight(0.2); // Distinguish the racing-line and centerline origins.
	Pit& pit = driver.pitAdapter();
	pit.setPitstop(true);
	advance(); driver.observe(situation);
	EXPECT_EQ(pit.getState(), NONE);
	placeCar(0, pitEntry.lgfromstart - 1, 0, 10);
	advance(); driver.observe(situation);
	EXPECT_EQ(pit.getState(), APPROACHING);
	EXPECT_FALSE(pit.getInPit());
	placeCar(0, pitEntry.lgfromstart, 0, 10);
	advance(); driver.observe(situation);
	EXPECT_EQ(pit.getState(), IN_LANE);
	EXPECT_TRUE(pit.getInPit());
	placeCar(0, pitStart.lgfromstart + 10, 0, 10);
	advance(); driver.observe(situation);
	EXPECT_EQ(pit.getState(), IN_LANE); // Must already be set before steering/braking.
	EXPECT_NEAR(driver.pitBrake(), 0, kEps);
	EXPECT_EQ(pit.getState(), IN_LANE); // No braking early-return is required.
	PlanningPoint expected = driver.expectedPitTarget(side == TR_LFT ? 17 : -17);
	v2d target = driver.steeringTarget();
	EXPECT_NEAR(target.x, (float)expected.x, kEps);
	EXPECT_NEAR(target.y, (float)expected.y, kEps);

	placeCar(0, ownPit.pos.toStart - 2, 0, 8);
	advance(); driver.observe(situation);
	EXPECT_GT(driver.pitBrake(), 0.5f);
	EXPECT_EQ(pit.getState(), IN_LANE);
	placeCar(0, ownPit.pos.toStart, 0, 0);
	advance(); driver.observe(situation);
	EXPECT_EQ(driver.pitCommand(&situation), ROB_PIT_IM);
	EXPECT_FALSE(pit.getPitstop());
	EXPECT_TRUE(pit.getInPit());
	EXPECT_EQ(pit.getState(), PIT_EXIT);

	placeCar(0, ownPit.pos.toStart + 30, 0, 10);
	advance(); driver.observe(situation);
	EXPECT_EQ(pit.getState(), PIT_EXIT);
	EXPECT_NEAR(driver.pitBrake(), 0, kEps);
	EXPECT_EQ(pit.getState(), PIT_EXIT);
	// Departing the assigned box must not add the road racing line to the
	// centerline-relative pit spline, even when that racing line changes sides.
	for (double weight : {0.2, 0.8}) {
		SCOPED_TRACE(weight);
		driver.setPathWeight(weight);
		expected = driver.expectedPitTarget(side == TR_LFT ? 17 : -17);
		target = driver.steeringTarget();
		EXPECT_NEAR(target.x, (float)expected.x, kEps);
		EXPECT_NEAR(target.y, (float)expected.y, kEps);
	}
	placeCar(0, pitExit.lgfromstart + 1, 0, 10);
	advance(); driver.observe(situation);
	EXPECT_FALSE(pit.getInPit());
	EXPECT_EQ(pit.getState(), NONE);
}

TEST_P(PitTransitionTest, TimeoutClearsRequestAndTransitionsToExit)
{
	configurePit(std::get<0>(GetParam()), std::get<1>(GetParam()));
	placeCar(0, pitEntry.lgfromstart - 1, 0, 10);
	ControllerDriver& driver = addDriver(0);
	Pit& pit = driver.pitAdapter();
	pit.setPitstop(true);
	placeCar(0, ownPit.pos.toStart + 1, 0, 0);
	for (int tick = 0; tick < 160 && pit.getPitstop(); ++tick) {
		advance(); driver.observe(situation);
		driver.pitBrake();
	}
	EXPECT_FALSE(pit.getPitstop());
	EXPECT_TRUE(pit.getInPit());
	EXPECT_EQ(pit.getState(), PIT_EXIT);
}

TEST_P(PitTransitionTest, ExitLookaheadHoldsTheSplineEndpoint)
{
	configurePit(std::get<0>(GetParam()), std::get<1>(GetParam()));
	placeCar(0, pitEntry.lgfromstart - 1, 0, 10);
	ControllerDriver& driver = addDriver(0);
	driver.setPathWeight(0.5); // Isolate extrapolation from the racing-line origin.
	driver.pitAdapter().setPitstop(true);
	placeCar(0, ownPit.pos.toStart, 0, 0);
	advance(); driver.observe(situation);
	driver.pitCommand(&situation);
	for (float speed : {10.0f, 30.0f}) {
		SCOPED_TRACE(speed);
		placeCar(0, pitExit.lgfromstart - 3, 0, speed);
		advance(); driver.observe(situation);
		ASSERT_TRUE(driver.pitAdapter().getInPit());
		float distance = speed > driver.pitAdapter().getSpeedlimit() ? 6.0f + 0.33f*speed : 6.0f;
		PlanningPoint expected = driver.expectedPitTarget(0, distance);
		v2d target = driver.steeringTarget();
		EXPECT_NEAR(target.x, (float)expected.x, kEps);
		EXPECT_NEAR(target.y, (float)expected.y, kEps);
	}
}

TEST_P(PitTransitionTest, MainTrackLearningDoesNotDeflectPitSteering)
{
	int side = std::get<0>(GetParam());
	configurePit(side, std::get<1>(GetParam()));
	ControllerDriver& driver = addDriver(0);
	driver.setPathWeight(0.5);
	// Learn a nonzero road correction using the production learner, without files.
	for (float station : {40.0f, 210.0f}) {
		placeCar(0, station, 0, 20);
		advance(); driver.observe(situation);
		driver.trackFeedback(situation, 0.8f);
	}
	placeCar(0, pitEntry.lgfromstart - 1, 0, 10);
	driver.pitAdapter().setPitstop(true);
	float laneOffset = side == TR_LFT ? 17.0f : -17.0f;
	placeCar(0, pitStart.lgfromstart + 10, laneOffset, 10);
	ASSERT_GT(std::fabs(driver.steeringPrediction(cars[0])), 0.001f);
	advance(); driver.drive(&situation);
	ASSERT_TRUE(driver.pitAdapter().getInPit());
	PlanningPoint expected = driver.expectedPitTarget(laneOffset);
	float base = driver.steeringFor(v2d((float)expected.x, (float)expected.y));
	EXPECT_NEAR(cars[0]._steerCmd, base, kEps);
}

TEST_P(PitTransitionTest, AlongsideCarDoesNotSteerUsAcrossPitBoxes)
{
	int side = std::get<0>(GetParam());
	configurePit(side, std::get<1>(GetParam()));
	placeCar(0, pitEntry.lgfromstart - 1, 0, 10);
	ControllerDriver& driver = addDriver(0);
	driver.pitAdapter().setPitstop(true);
	float direction = side == TR_LFT ? 1.0f : -1.0f;
	float laneOffset = direction*17;
	float station = pitStart.lgfromstart + 10;
	placeCar(0, station, laneOffset, 10);
	// This car is on the road side of our lane and angled toward us. Road
	// side-avoidance would steer into the pit row and overwrite the pit offset.
	cars[1]._state = 0;
	placeCar(1, station, laneOffset - direction*2.2f, 10, direction*0.1f);
	advance(); driver.drive(&situation);
	ASSERT_TRUE(driver.pitAdapter().getInPit());
	PlanningPoint expected = driver.expectedPitTarget(laneOffset);
	EXPECT_NEAR(cars[0]._steerCmd, driver.steeringFor(v2d((float)expected.x, (float)expected.y)), kEps);
	EXPECT_NEAR(driver.offset(), laneOffset, kEps);
}

TEST_P(PitTransitionTest, BlockingCarStillTriggersBrakingWithoutPassing)
{
	int side = std::get<0>(GetParam());
	configurePit(side, std::get<1>(GetParam()));
	placeCar(0, pitEntry.lgfromstart - 1, 0, 10);
	ControllerDriver& driver = addDriver(0);
	driver.pitAdapter().setPitstop(true);
	float laneOffset = side == TR_LFT ? 17.0f : -17.0f;
	float station = pitStart.lgfromstart + 10;
	placeCar(0, station, laneOffset, 18);
	cars[1]._state = 0;
	// A 19 m center separation is a 12 m safety-adjusted gap: shorter than
	// braking distance at 18 m/s, but outside the corner-distance refinement.
	placeCar(1, station + 19, laneOffset, 0);
	advance(); driver.drive(&situation);
	ASSERT_TRUE(driver.pitAdapter().getInPit());
	EXPECT_GT(cars[0]._brakeCmd, 0.5f);
	EXPECT_NEAR(cars[0]._accelCmd, 0, kEps);
	EXPECT_FALSE(driver.isOvertaking());
	EXPECT_NEAR(driver.offset(), laneOffset, kEps);
	PlanningPoint expected = driver.expectedPitTarget(laneOffset);
	EXPECT_NEAR(cars[0]._steerCmd, driver.steeringFor(v2d((float)expected.x, (float)expected.y)), kEps);
}

INSTANTIATE_TEST_SUITE_P(SidesAndWrap, PitTransitionTest,
	testing::Combine(testing::Values(TR_LFT, TR_RGT), testing::Bool()));

TEST_F(ControllerTest, NoAssignedPitCannotEnterPitManeuvers)
{
	ControllerDriver& driver = addDriver(0);
	driver.pitAdapter().setPitstop(true);
	advance(); driver.observe(situation);
	EXPECT_FALSE(driver.pitAdapter().getPitstop());
	EXPECT_FALSE(driver.pitAdapter().getInPit());
	EXPECT_EQ(driver.pitAdapter().getState(), NONE);
	EXPECT_NEAR(driver.pitBrake(0.25f), 0.25f, kEps);
}

enum PipelineMode { ACCELERATING, BRAKING, LOW_SPEED, PIT_DRIVING, RECOVERY };
class ControllerPipelineTest : public ControllerTest,
	public testing::WithParamInterface<std::tuple<PipelineMode, float>> {};

TEST_P(ControllerPipelineTest, TickAdvancesTractionAndManeuverStateExactlyOnce)
{
	PipelineMode mode = std::get<0>(GetParam());
	float slip = std::get<1>(GetParam());
	cars[1]._state = cars[2]._state = RM_CAR_STATE_NO_SIMU;
	if (mode == PIT_DRIVING) {
		configurePit(TR_RGT, false);
		placeCar(0, 19, 0, 10);
	} else if (mode == LOW_SPEED) {
		placeCar(0, 40, 0, 2);
	} else if (mode == BRAKING) {
		placeCar(0, 40, 0, 40);
	} else if (mode == RECOVERY) {
		placeCar(0, 40, 4, 1, 1);
	}
	ControllerDriver& driver = addDriver(0);
	if (mode == PIT_DRIVING) {
		driver.pitAdapter().setPitstop(true);
		placeCar(0, 50, 0, 10);
	}
	if (mode == BRAKING) driver.setPathCurvature(0.1);
	if (mode == RECOVERY) driver.readyRecovery();
	driver.setOffset(1);
	driver.setTractionState(0.4f);
	for (int wheel = 0; wheel < 4; ++wheel)
		cars[0]._wheelSpinVel(wheel) = (cars[0]._speed_x + slip)/cars[0]._wheelRadius(wheel);
	advance();
	driver.drive(&situation);
	double expectedTraction = mode == RECOVERY ? 0.4 : 0.3 + (slip > 2 ? 0.05*(slip - 2) : 0);
	EXPECT_NEAR(driver.tractionState(), expectedTraction, kEps);
	if (mode == RECOVERY) {
		EXPECT_NEAR(driver.offset(), 1, kEps);
		EXPECT_EQ(cars[0]._gearCmd, -1);
	} else if (mode != PIT_DRIVING) {
		EXPECT_NEAR(driver.offset(), 0.96, kEps);
	}
	if (mode == BRAKING) {
		EXPECT_GT(cars[0]._brakeCmd, 0.5f);
		EXPECT_NEAR(cars[0]._accelCmd, 0, kEps);
	} else if (mode == ACCELERATING) {
		EXPECT_GT(cars[0]._accelCmd, 0.4f);
	}
	EXPECT_TRUE(std::isfinite(cars[0]._steerCmd));
	EXPECT_TRUE(std::isfinite(cars[0]._accelCmd));
	EXPECT_TRUE(std::isfinite(cars[0]._brakeCmd));
	EXPECT_NEAR(cars[0]._accelCmd*cars[0]._brakeCmd, 0, kEps);
}

INSTANTIATE_TEST_SUITE_P(ModesAndSlip, ControllerPipelineTest,
	testing::Combine(testing::Values(ACCELERATING, BRAKING, LOW_SPEED, PIT_DRIVING, RECOVERY),
		testing::Values(0.0f, 2.0f, 5.0f)));

TEST_F(ControllerTest, SteeringQueriesUseAFrozenTargetWithoutAdvancingState)
{
	cars[1]._state = cars[2]._state = RM_CAR_STATE_NO_SIMU;
	ControllerDriver& driver = addDriver(0);
	driver.setOffset(1);
	advance(); driver.observe(situation);
	v2d target = driver.steeringTarget();
	float offset = driver.offset(), lookahead = driver.lookahead();
	float steering = driver.steeringFor(target);
	for (int query = 0; query < 3; ++query) {
		EXPECT_NEAR(driver.steeringFor(target), steering, kEps);
		EXPECT_NEAR(driver.offset(), offset, kEps);
		EXPECT_NEAR(driver.lookahead(), lookahead, kEps);
	}
}

TEST_F(ControllerTest, SideCollisionOffsetIsRetainedForTheNextTargetUpdate)
{
	placeCar(0, 40, 4, 20);
	placeCar(1, 40, 6.2f, 20, -0.1f);
	cars[2]._state = RM_CAR_STATE_NO_SIMU;
	ControllerDriver& driver = addDriver(0);
	advance(); driver.drive(&situation);
	EXPECT_NEAR(driver.offset(), cars[0]._trkPos.toMiddle, kEps);
}

TEST_F(ControllerTest, TrackLearningConsumesBaseSteeringRatherThanTheFilteredCommand)
{
	cars[1]._state = cars[2]._state = RM_CAR_STATE_NO_SIMU;
	ControllerDriver& driver = addDriver(0);
	driver.setPathWeight(0.5);
	SegLearn reference(&track);
	for (float station : {40.0f, 210.0f}) {
		placeCar(0, station, 0, 20);
		advance(); driver.observe(situation);
		cars[0]._steerCmd = -0.7f; // A distinct side-collision/learned correction.
		driver.trackFeedback(situation, 0.8f);
		float allowance = cars[0]._trkPos.seg->type == TR_STR ? 2.0f/30 : 1.0f/3;
		reference.updateAccel(&situation, &cars[0], 0, -allowance, -0.08f);
	}
	tCarElt sample = cars[0];
	sample._trkPos.seg = &segments[0];
	float expected = reference.predictedError(&sample);
	ASSERT_GT(std::fabs(expected), 0.001f);
	EXPECT_NEAR(driver.steeringPrediction(sample), expected, kEps);
}
