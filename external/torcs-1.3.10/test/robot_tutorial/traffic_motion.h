/***************************************************************************
    file                 : traffic_motion.h
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch
 ***************************************************************************/
/* GPL version 2 or later. Distributed WITHOUT ANY WARRANTY.
 * See <https://www.gnu.org/licenses/>. Private simuv2 actual-motion fixture. */
#include <cassert>
#include <cstdlib>
#include <dlfcn.h>
#include "sim.h"

static double ReviewStart=-1, ReviewMinClearance=100, ReviewMinLateral=100;
static bool ReviewHeld=false;

static void
reviewPlace(tCar& p, tTrackSeg* segment, double along, double lateral, double speed, double sideSpeed, int gear)
{
    tCarElt* c=p.carElt;
    tTrkLocPos pos{}; pos.seg=segment; pos.toStart=along; pos.toMiddle=lateral;
    tdble x,y; RtTrackLocal2Global(&pos,&x,&y,TR_TOMIDDLE);
    const double tangent=segment->angle[TR_ZS], yaw=tangent+std::atan2(sideSpeed,speed);
    p.DynGC.pos.x=p.DynGCg.pos.x=x; p.DynGC.pos.y=p.DynGCg.pos.y=y;
    p.DynGC.pos.az=p.DynGCg.pos.az=yaw;
    p.DynGC.vel=p.DynGCg.vel=tPosd{}; p.DynGC.acc=p.DynGCg.acc=tPosd{};
    p.DynGC.vel.x=std::hypot(speed,sideSpeed);
    p.DynGCg.vel.x=speed*std::cos(tangent)-sideSpeed*std::sin(tangent);
    p.DynGCg.vel.y=speed*std::sin(tangent)+sideSpeed*std::cos(tangent);
    p.worldPosX=p.publishedPosX=x; p.worldPosY=p.publishedPosY=y;
    p.Cosz=std::cos(yaw); p.Sinz=std::sin(yaw);
    RtTrackGlobal2Local(segment,x,y,&p.trkPos,TR_LPOS_MAIN);
    p.transmission.gearbox.gear=gear;
    const int k=gear+c->_gearOffset;
    p.transmission.curOverallRatio=p.transmission.overallRatio[k]; p.transmission.curI=p.transmission.driveI[k];
    p.transmission.clutch.transferValue=1; p.transmission.clutch.timeToRelease=0;
    p.engine.rads=speed/p.wheel[REAR_RGT].radius*p.transmission.curOverallRatio;
    c->_gear=gear; c->_enginerpm=p.engine.rads;
    c->pub.DynGC=p.DynGC; c->pub.DynGCg=p.DynGCg; c->_trkPos=p.trkPos;
    for (int i=0;i<4;++i) {
        p.wheel[i].spinVel=p.wheel[i].prespinVel=speed/p.wheel[i].radius;
        p.wheel[i].in.spinVel=p.wheel[i].feedBack.spinVel=p.wheel[i].spinVel;
        c->_wheelSpinVel(i)=p.wheel[i].spinVel;
        auto& corner=p.corner[i].pos;
        const double cx=corner.x+p.statGC.x, cy=corner.y+p.statGC.y;
        corner.ax=x+cx*p.Cosz-cy*p.Sinz; corner.ay=y+cx*p.Sinz+cy*p.Cosz;
        p.corner[i].vel=tPosd{}; c->pub.corner[i]=corner;
    }
    c->ctrl=tCarCtrl{}; c->ctrl.gear=gear;
}

static bool
reviewArrange(tCarElt* car, tSituation* situation)
{
    if (situation->currentTime<.5) { car->ctrl=tCarCtrl{}; car->ctrl.brakeCmd=1; return true; }
    if (ReviewStart>=0) return false;
    ReviewStart=situation->currentTime;
    void* handle=dlopen(std::getenv("TORCS_MAINT_SIMU"),RTLD_NOW); assert(handle);
    auto table=static_cast<tCar**>(dlsym(handle,"SimCarTable")); assert(table && *table);
    tTrackSeg* segment=currentTrack->seg;
    for (int i=0;i<currentTrack->nseg;++i,segment=segment->next)
        if (segment->type==TR_STR && segment->length>120) break;
    assert(segment->type==TR_STR && segment->length>120);
    tCarElt* leader=nullptr;
    for (int i=0;i<situation->_ncars;++i) {
        tCarElt* c=situation->cars[i]; tCar& physical=(*table)[c->index]; assert(physical.carElt==c);
        if (c==car) reviewPlace(physical,segment,40,REVIEW_SIDE*(REVIEW_RETURN?3.7:.4),20,REVIEW_SIDE*(REVIEW_RETURN?-.4:.4),2);
        else if (std::strcmp(c->_name,"Tutorial Pace")==0) {
            leader=c; reviewPlace(physical,segment,REVIEW_RETURN?5:30,0,18,0,2);
        } else reviewPlace(physical,segment,15,REVIEW_RETURN?0:REVIEW_SIDE*4,35,0,3);
    }
    dlclose(handle);
    assert(leader);
    recovery.reset(ReviewStart); driver.requestedGear=2; driver.lastShiftTime=ReviewStart;
    traffic.reset(ReviewStart);
    traffic.mode=REVIEW_RETURN?TrafficPlanner::Mode::Returning:TrafficPlanner::Mode::Passing;
    traffic.passingCar=REVIEW_RETURN?nullptr:leader;
    traffic.offset=REVIEW_SIDE*(REVIEW_RETURN?1:3); traffic.passOffset=REVIEW_SIDE*3.7;
    std::printf("MAINTENANCE MOTION SEEDED %s %d %d\n",MAINTENANCE_ID,REVIEW_SIDE,REVIEW_RETURN);
    return false;
}

static void
reviewSample(tCarElt* car, tSituation* situation)
{
    const double elapsed=situation->currentTime-ReviewStart;
    for (int i=0;i<situation->_ncars;++i) {
        assert(!(situation->cars[i]->priv.collision & SEM_COLLISION_CAR));
        assert(situation->cars[i]->_dammage==0);
    }
    ReviewMinClearance=std::min(ReviewMinClearance,roadClearance(car));
    if (elapsed<1.0) ReviewMinLateral=std::min(ReviewMinLateral,REVIEW_SIDE*double(car->_trkPos.toMiddle));
    if (elapsed<.021) {
        assert(traffic.mode==TrafficPlanner::Mode::Holding);
        assert(REVIEW_SIDE*car->ctrl.steer*(REVIEW_RETURN?1:-1)>0);
        assert(car->ctrl.brakeCmd==0 && !traffic.emergency);
        ReviewHeld=true;
    }
    if (elapsed>=3) {
        assert(ReviewHeld && ReviewMinClearance>0);
        if (REVIEW_RETURN) assert(ReviewMinLateral>3.1);
        std::printf("MAINTENANCE MOTION PASS %s side=%d return=%d clearance=%.3f held-lateral=%.3f\n",
            MAINTENANCE_ID,REVIEW_SIDE,REVIEW_RETURN,ReviewMinClearance,ReviewMinLateral);
        std::fflush(stdout);
        std::exit(0); // Ends the motion experiment; does not claim race completion.
    }
}
