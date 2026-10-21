/* SPDX-License-Identifier: GPL-2.0-or-later
 * Deterministic APS380 track-following validation driver. No learned weights.
 */
#include <tgf.h>
#include <track.h>
#include <car.h>
#include <raceman.h>
#include <robot.h>
#include <robottools.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

static tTrack *course;
static FILE *logFile;
static int stage;
static double previousTime, previousSpeed, integral, qualified, stageStart, filteredAccel;
static double neutral = .05;
static const char *names[] = {"seek_30", "hold_30", "seek_50", "hold_50", "seek_liftoff", "liftoff", "friction_stop", "stop_hold", "lap_follow"};
static double bound(double x, double lo, double hi) { return x < lo ? lo : (x > hi ? hi : x); }

static double segmentProgress(tTrkLocPos const &p)
{
    return p.seg->type == TR_STR ? p.toStart : p.toStart*p.seg->radius;
}

static double straightRemaining(tCarElt *car)
{
    tTrackSeg *seg = car->_trkPos.seg;
    if (seg->type != TR_STR) return 0;
    double distance = seg->length-segmentProgress(car->_trkPos);
    for (int count=0; count < course->nseg && seg->next->type == TR_STR; ++count) {
        seg = seg->next;
        distance += seg->length;
    }
    return distance;
}

static double steering(tCarElt *car, double speed)
{
    const double lookahead = 6.0 + .8*speed;
    double remaining = lookahead;
    tTrkLocPos point = car->_trkPos;
    point.toMiddle = 0;
    for (int count=0; count < course->nseg; ++count) {
        const double available = point.seg->length-segmentProgress(point);
        if (remaining <= available) {
            point.toStart += (tdble)(point.seg->type == TR_STR ? remaining : remaining/point.seg->radius);
            break;
        }
        remaining -= available;
        point.seg = point.seg->next;
        point.toStart = 0;
    }
    tdble x, y;
    RtTrackLocal2Global(&point, &x, &y, TR_TOMIDDLE);
    double angle = atan2(y-car->_pos_Y, x-car->_pos_X)-car->_yaw;
    while (angle > PI) angle -= 2*PI;
    while (angle < -PI) angle += 2*PI;
    return bound(atan2(2*2.875*sin(angle), lookahead)/car->_steerLock, -.8, .8);
}

static void transition(int next, double time)
{
    stage = next;
    stageStart = time;
    qualified = 0;
    integral = 0;
}

static void initTrack(int, tTrack *track, void *, void **settings, tSituation *)
{
    course = track;
    *settings = NULL; // Do not override the captured car configuration.
}

static void newRace(int, tCarElt *car, tSituation *)
{
    stage = 0;
    previousTime = -1;
    previousSpeed = integral = qualified = stageStart = filteredAccel = 0;
    neutral = GfParmGetNum(car->_carHandle, "Electric Powertrain", "neutral pedal", NULL, .05f);
    const char *path = getenv("APS380_AI_LOG");
    if (!path) { fprintf(stderr, "APS380_AI_LOG must name the driver log\n"); exit(2); }
    logFile = fopen(path, "w");
    if (!logFile) { fprintf(stderr, "Could not open AI log %s\n", path); exit(2); }
    fprintf(logFile, "time_s,stage,target_mps,speed_mps,accel_mps2,qualified_s,straight_remaining_m,to_middle_m,track_width_m,lateral_mps,throttle,brake,steer,damage,distance_m,track_length_m\n");
}

static void drive(int, tCarElt *car, tSituation *s)
{
    memset(&car->ctrl, 0, sizeof(car->ctrl));
    car->_gearCmd = 1;
    const double time = s->currentTime;
    const double speed = car->_speed_x;
    if (time < 1.0) {
        car->_accelCmd = (tdble)neutral;
        car->_brakeCmd = .5;
        previousTime = time;
        previousSpeed = speed;
        return;
    }
    const double dt = bound(time-previousTime, .001, .1);
    const double accel = (speed-previousSpeed)/dt;
    filteredAccel += dt/(.2+dt)*(accel-filteredAccel);
    const double straight = straightRemaining(car);
    car->_steerCmd = (tdble)steering(car, fabs(speed));
    if (stage == 0 && straight > 190 && time > 3) transition(1, time);
    if (stage == 2 && straight > 285) transition(3, time);
    if (stage == 4 && straight > 140) transition(5, time);
    double target = (stage == 3 || stage == 4) ? 50.0/3.6 : 30.0/3.6;
    if (stage == 1 || stage == 3) {
        const bool qualifies = fabs(speed-target) < .2 && fabs(accel) <= .12 &&
            fabs(car->_trkPos.toMiddle) < 1 && fabs(car->_speed_y) < .3 && straight > 20;
        qualified = qualifies ? qualified+dt : 0;
        if (qualified >= 12) transition(stage == 1 ? 2 : 4, time);
        else if (straight < 20) transition(stage == 1 ? 0 : 2, time);
    }
    if (stage == 5) {
        target = 0;
        car->_accelCmd = 0; // Lift-off only: no friction-brake command.
        if (speed < 20.0/3.6) transition(6, time);
    } else if (stage == 6 || stage == 7) {
        target = 0;
        car->_accelCmd = (tdble)neutral; // Isolate friction braking from lift-off.
        car->_brakeCmd = .35;
        if (stage == 6 && fabs(speed) < .15) transition(7, time);
        if (stage == 7 && time-stageStart >= 6) transition(8, time);
    } else {
        const double error = target-speed;
        integral = bound(integral+error*dt, -3, 3);
        const double desiredAccel = bound(.8*error+.2*integral-.08*filteredAccel, -1.2, 1.2);
        const double radius = .33435;
        const double omega = fabs(car->_enginerpm);
        const double maxTorque = omega > 500 ? 202000/omega : 404;
        const double force = 1686*desiredAccel + 1686*9.81*.012 + .645*.23*2.22*speed*speed;
        const double torque = force*radius/9;
        if (torque >= 0) {
            car->_accelCmd = (tdble)bound(neutral+(1-neutral)*torque/maxTorque, neutral, .5);
        } else {
            const double fade = bound(fabs(speed)/2, 0, 1);
            const double maxRegen = (omega > 600 ? 60000/omega : 100)*fade;
            car->_accelCmd = (tdble)(neutral*(1-bound(-torque/(maxRegen+.00001), 0, 1)));
            if (-torque > maxRegen) car->_brakeCmd = (tdble)bound((-torque-maxRegen)*9/radius/(1686*4), 0, .5);
        }
    }
    fprintf(logFile, "%.6f,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%d,%.6f,%.6f\n",
        time, names[stage], target, speed, accel, qualified, straight, (double)car->_trkPos.toMiddle,
        (double)car->_trkPos.seg->width, (double)car->_speed_y, (double)car->_accelCmd,
        (double)car->_brakeCmd, (double)car->_steerCmd, car->_dammage, (double)car->_distRaced, (double)course->length);
    fflush(logFile);
    if (time > 5 && (car->_dammage > 0 || fabs(car->_trkPos.toMiddle) > car->_trkPos.seg->width/2-.4)) {
        fprintf(stderr, "AI aborted: impact or departure from road at %.3f s\n", time);
        exit(3);
    }
    if (time > 900) { fprintf(stderr, "AI protocol exceeded 900 simulation seconds\n"); exit(4); }
    previousTime = time;
    previousSpeed = speed;
}

static void shutdown(int) { if (logFile) { fclose(logFile); logFile = NULL; } }
static int initialize(int index, void *pointer)
{
    tRobotItf *itf = (tRobotItf *)pointer;
    itf->rbNewTrack = initTrack;
    itf->rbNewRace = newRace;
    itf->rbDrive = drive;
    itf->rbShutdown = shutdown;
    itf->index = index;
    return 0;
}
extern "C" int aps380_ai(tModInfo *info)
{
    memset(info, 0, 10*sizeof(tModInfo));
    info[0].name = strdup("APS380 validation driver");
    info[0].desc = strdup("Track following and repeatable EV validation protocol");
    info[0].fctInit = initialize;
    info[0].gfId = ROB_IDENT;
    info[0].index = 1;
    return 0;
}
