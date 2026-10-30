/* SPDX-License-Identifier: GPL-2.0-or-later
 * TEST ONLY: scripted state in the real human driver; never desktop key events.
 * Build as a separate robot DLL, never install over human.dll. */
#include <tgfclient.h>
static void fixtureKeyRegistration(tfuiKeyCallback) {}
static void fixtureSpecialRegistration(tfuiSKeyCallback) {}
static int fixtureMouse(tCtrlMouseInfo *) {return 0;}
#define GfuiKeyEventRegisterCurrent fixtureKeyRegistration
#define GfuiSKeyEventRegisterCurrent fixtureSpecialRegistration
#define GfctrlMouseGetCurrent fixtureMouse
#include "../../external/torcs-1.3.10/src/drivers/human/human.cpp"
#undef GfuiKeyEventRegisterCurrent
#undef GfuiSKeyEventRegisterCurrent
#undef GfctrlMouseGetCurrent

static tfRbDrive fixtureOriginal[10];
static void fixtureDrive(int index,tCarElt *car,tSituation *s) {
    const double t=s->currentTime;
    const bool throttle=(t>=0. && t<2.) || (t>=6. && t<8.);
    const bool brake=(t>=4. && t<5.) || (t>=10. && t<11.);
    tControlCmd *commands=HCtx[index-1]->CmdControl;
    if (getenv("APS380_FIXTURE_ANALOG")) {
        // Configured test-only calibration: axis +1 = released, -1 = pressed.
        joyInfo->ax[commands[CMD_THROTTLE].val]=throttle ? -.4f : 1.f;
        joyInfo->ax[commands[CMD_BRAKE].val]=brake ? -.2f : 1.f;
    } else {
        onSKeyAction(commands[CMD_THROTTLE].val,0,throttle ? GFUI_KEY_DOWN : GFUI_KEY_UP);
        onSKeyAction(commands[CMD_BRAKE].val,0,brake ? GFUI_KEY_DOWN : GFUI_KEY_UP);
    }
    // The console fixture is dispatched as a robot. Supply that dispatch's
    // actual elapsed simulation time to the included human code, which normally
    // receives the human driver's own interval in a graphical race.
    const double savedHumanDelta=s->driveDeltaTime[RM_DRV_HUMAN];
    s->driveDeltaTime[RM_DRV_HUMAN]=s->driveDeltaTime[RM_DRV_ROBOT];
    fixtureOriginal[index-1](index,car,s);
    s->driveDeltaTime[RM_DRV_HUMAN]=savedHumanDelta;
    static FILE *trace=NULL;
    if (!trace && getenv("APS380_FIXTURE_TRACE")) {
        trace=fopen(getenv("APS380_FIXTURE_TRACE"),"w");
        if(trace)fprintf(trace,"time_s,pressed_throttle,pressed_brake,ramp_throttle,ramp_brake,applied_throttle,applied_brake\n");
    }
    if(trace && t>=0.) {
        fprintf(trace,"%.6f,%d,%d,%.9f,%.9f,%.9f,%.9f\n",t,throttle,brake,
            HCtx[index-1]->paccel,HCtx[index-1]->pbrake,(double)car->_accelCmd,(double)car->_brakeCmd);
        fflush(trace);
    }
}
static int fixtureInit(int index,void *pointer) {
    int result=InitFuncPt(index,pointer);
    // Never poll a physical input device in automated validation.
    joyPresent=0;
    if (!joyInfo) joyInfo=(tCtrlJoyInfo*)calloc(1,sizeof(tCtrlJoyInfo));
    tRobotItf *itf=(tRobotItf*)pointer;
    fixtureOriginal[index-1]=itf->rbDrive;itf->rbDrive=fixtureDrive;
    return result;
}
extern "C" __declspec(dllexport) int aps380_keyboard_fixture(tModInfo *info) {
    int result=human(info);
    for(int i=0;i<10 && info[i].fctInit;++i)info[i].fctInit=fixtureInit;
    return result;
}
