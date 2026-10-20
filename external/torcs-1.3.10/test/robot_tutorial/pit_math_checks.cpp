/***************************************************************************
    file                 : pit_math_checks.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch
 ***************************************************************************/
/* GPL version 2 or later. Distributed WITHOUT ANY WARRANTY.
 * See <https://www.gnu.org/licenses/>. */
#include <cassert>
#include <cmath>
#include <cstdio>
#include <limits>
#include "pit.h"
#include <robot.h>

static constexpr double EPS = 1e-5;
static int Checks = 0;
static void near(double a, double b) { ++Checks; assert(std::fabs(a-b) < EPS); }

int main()
{
    HermiteSpline curve;
    for (double h : {1., 7., 35.}) for (double m0 : {-0.4, 0., 0.7}) for (double m1 : {-0.2, 0., 0.5}) {
        assert(curve.setKnots({{10,2,m0},{10+h,5,m1}}));
        near(curve.value(10),2); near(curve.value(10+h),5);
        near(curve.derivative(10),m0); near(curve.derivative(10+h),m1);
        for (int i=1; i<20; ++i) {
            const double t=i/20., x=10+h*t;
            const double basis=(2*t*t*t-3*t*t+1)*2+(t*t*t-2*t*t+t)*h*m0+(-2*t*t*t+3*t*t)*5+(t*t*t-t*t)*h*m1;
            near(curve.value(x),basis);
            near(curve.derivative(x),(curve.value(x+1e-5)-curve.value(x-1e-5))/2e-5);
        }
        near(curve.value(-1),2); near(curve.value(100),5);
        near(curve.derivative(-1),0); near(curve.derivative(100),0);
    }
    assert(curve.setKnots({{0,0,0},{20,5,0},{40,0,0}})); near(curve.value(20),5); near(curve.derivative(20),0);
    assert(!curve.setKnots({{0,0,0},{0,2,0}})); near(curve.value(0),0);
    assert(!curve.setKnots({{1,0,0},{0,2,0}})); assert(!curve.setKnots({{0,0,0}}));
    assert(!curve.setKnots({{0,0,0},{1,std::numeric_limits<double>::infinity(),0}}));
    tTrack track{}; track.length=1000; track.nseg=1;
    tTrackSeg road{},entry{},start{},end{},after{},exit{};
    road.type=TR_STR; road.length=1000; road.width=15; road.startWidth=15; road.type2=TR_MAIN;
    road.next=road.prev=&road;
    road.vertex[TR_SL]={0,7.5,0}; road.vertex[TR_SR]={0,-7.5,0};
    road.vertex[TR_EL]={1000,7.5,0}; road.vertex[TR_ER]={1000,-7.5,0};
    track.seg=&road; entry.width=15; entry.lgfromstart=100; start.lgfromstart=200;
    end.lgfromstart=492.5; end.length=7.5;
    tTrackSurface surface{}; surface.kFriction=1; road.surface=&surface;
    after.lgfromstart=500; after.length=5; end.next=&after; exit.lgfromstart=650;
    auto& info=track.pits;
    info.type=TR_PIT_ON_TRACK_SIDE; info.pitEntry=&entry; info.pitStart=&start; info.pitEnd=&end; info.pitExit=&exit;
    info.width=5; info.len=15; info.speedLimit=25;
    tTrackOwnPit box{}; box.pos.toMiddle=20; box.pitCarIndex=TR_PIT_STATE_FREE;
    tCarElt car{}; car._pit=&box; car._dimension_x=4.9; car._dimension_y=1.92; car._steerLock=.5;
    car._trkPos.seg=&road; car._trkPos.toStart=250; car._pos_X=250; car._gear=1; car._gearNb=3; car._tank=60;
    for (int side : {TR_LFT,TR_RGT}) for (double center : {207.5,492.5}) {
        info.side=side; box.lmin=center-5; box.lmax=center+5;
        PitDriver p; p.configure(&track,&car); assert(p.available);
        const double sign=side==TR_LFT?1:-1;
        near(p.route.value(p.box),sign*20); near(p.route.derivative(p.box),0);
        near(p.route.value(0),0); near(p.route.value(p.exit),0); assert(p.mergeStart>p.box+15);
    }
    entry.lgfromstart=900; start.lgfromstart=950; end.lgfromstart=100; after.lgfromstart=107.5; exit.lgfromstart=200;
    box.lmin=55; box.lmax=65; PitDriver wrap; wrap.configure(&track,&car);
    assert(wrap.available); near(wrap.relative(5),105); near(wrap.box,160);
    box.lmin=995; box.lmax=5; wrap.configure(&track,&car); assert(!wrap.available);
    car._pit=nullptr; wrap.configure(&track,&car); assert(!wrap.available); car._pit=&box;
    entry.lgfromstart=100; start.lgfromstart=200; end.lgfromstart=492.5; after.lgfromstart=500; exit.lgfromstart=650;
    box.lmin=295; box.lmax=305; PitDriver p; p.configure(&track,&car); assert(p.available);
    car._fuel=0; p.updateStrategy(&car); assert(!p.fuelInitialized && !p.requested);
    car._fuel=10; car._laps=1; p.updateStrategy(&car); car._fuel=9; p.updateStrategy(&car);
    car._fuel=12; p.updateStrategy(&car); // Actual refuel, not the requested amount.
    car._fuel=11; car._laps=2; p.updateStrategy(&car); near(p.fuelPerLap,2); near(p.lapFuelUsed,0);
    p.requested=false; p.demonstrationDone=true; car._fuel=1; car._remainingLaps=10; p.updateStrategy(&car); assert(p.requested);
    car._dammage=1234; assert(p.service(&car)==ROB_PIT_IM);
    near(car._pitFuel,25.375); // 11.25 laps * 2.3 l/lap + 0.5 reserve - 1 l already aboard.
    assert(car._pitRepair==1234 && p.visits==1);
    p.fuelPerLap=100; car._fuel=59; p.service(&car); near(car._pitFuel,1);
    car._fuel=60; p.service(&car); near(car._pitFuel,0);
    tCarElt* cars[]={&car}; tSituation situation{}; situation.cars=cars; situation._ncars=1; situation.currentTime=10;
    SpeedDriver speed; speed.trackLength=1000; TrafficPlanner traffic;
    car._state=RM_CAR_STATE_PIT; assert(p.drive(speed,traffic,&car,&situation)); near(car.ctrl.brakeCmd,1); near(car.ctrl.accelCmd,0);
    car._state=0; p.mode=PitDriver::Mode::Stopping; p.progress=p.box-10; p.previousPosition=p.position(&car); car._speed_x=-1;
    assert(p.drive(speed,traffic,&car,&situation)); near(car.ctrl.brakeCmd,.8); assert(car.ctrl.gear==car._gear);
    p.configure(&track,&car); p.requested=true; box.pitCarIndex=0; car._trkPos.toStart=50; car._fuel=10; car._speed_x=0;
    assert(!p.drive(speed,traffic,&car,&situation)); assert(p.mode==PitDriver::Mode::Racing && p.requested);
    box.pitCarIndex=TR_PIT_STATE_FREE; car._speed_x=car._speed_X=20; car._trkPos.toMiddle=0;
    tCarElt entryOther=car; entryOther._trkPos.toStart=40; entryOther._speed_X=32;
    tCarElt* entryCars[]={&car,&entryOther}; situation.cars=entryCars; situation._ncars=2;
    assert(!p.entryClear(&car,&situation,50)); entryOther._trkPos.toStart=400; entryOther._speed_X=20;
    assert(p.entryClear(&car,&situation,50)); situation.cars=cars; situation._ncars=1;
    box.pitCarIndex=TR_PIT_STATE_FREE; p.configure(&track,&car); p.mode=PitDriver::Mode::Merging;
    car._trkPos.toStart=car._pos_X=p.entry+p.mergeStart; car._trkPos.toMiddle=car._pos_Y=p.laneOffset;
    car._speed_x=car._speed_X=10; car._yaw=0; p.progress=p.mergeStart; p.previousPosition=p.position(&car);
    auto corners=[&]() {
        for (int i=0;i<4;++i) {
            car._corner_x(i)=car._pos_X+(i<2?2.45:-2.45);
            car._corner_y(i)=car._pos_Y+((i==FRNT_LFT||i==REAR_LFT)?0.96:-0.96);
        }
    };
    corners(); tCarElt opponent=car; opponent._trkPos.toStart=opponent._pos_X=car._pos_X-40;
    opponent._trkPos.toMiddle=opponent._pos_Y=0; opponent._speed_x=opponent._speed_X=32;
    tCarElt* mergeCars[]={&car,&opponent}; situation.cars=mergeCars; situation._ncars=2;
    assert(p.drive(speed,traffic,&car,&situation)); assert(p.mergeHolding && p.mode==PitDriver::Mode::Merging); near(car.ctrl.steer,0);
    opponent._trkPos.toStart=opponent._pos_X=car._pos_X+55; situation.currentTime+=.02;
    assert(p.drive(speed,traffic,&car,&situation)); assert(!p.mergeHolding && p.mode==PitDriver::Mode::Merging);
    car._trkPos.toMiddle=car._pos_Y=-3; corners(); situation.currentTime+=.02;
    assert(!p.drive(speed,traffic,&car,&situation));
    assert(p.mode==PitDriver::Mode::Racing && traffic.mode==TrafficPlanner::Mode::Returning); near(traffic.offset,-3);
    std::printf("PASS: %d spline/route/fuel comparisons plus input, service, occupancy and reversal checks\n",Checks);
}
