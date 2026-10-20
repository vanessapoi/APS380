/***************************************************************************
    file                 : settings_checks.cpp
    created              : September 2026
    copyright            : (C) 2026 by Bernhard Wymann
    email                : berniw@bluewin.ch
 ***************************************************************************/
/* GPL version 2 or later. Distributed WITHOUT ANY WARRANTY.
 * See <https://www.gnu.org/licenses/>. */
#include <cassert>
#include <cmath>
#include <fstream>
#include <cstdio>
#include <string>
#include <tgf.h>
#include <car.h>
#include "settings.h"
#include "pit.h"
extern void* GfParmReadBuf(char* buffer);
static int Checks=0;
static constexpr double EPS = 1e-5;
static void near(double a, double b) { ++Checks; assert(std::fabs(a-b)<EPS); }
static void write(const char* name, const std::string& body)
{
    std::ofstream file(std::string("drivers/tutoriala/")+name);
    assert(file); file << "<params name=\"test\">" << body << "</params>";
}

int main(int argc, char** argv)
{
    assert(argc==2); const std::string data=argv[1];
    GfInit();
    void* category=GfParmReadFile((data+"/categories/stock1.xml").c_str(),GFPARM_RMODE_PRIVATE);
    void* model=GfParmReadFile((data+"/cars/car1-stock1/car1-stock1.xml").c_str(),GFPARM_RMODE_PRIVATE);
    assert(category && model); assert(!GfParmCheckHandle(category,model));
    void* reference=GfParmMergeHandles(category,model,GFPARM_MMODE_SRC|GFPARM_MMODE_DST|GFPARM_MMODE_RELSRC|GFPARM_MMODE_RELDST);
    tTrack track{}; char name[]="g-track-1"; track.internalname=name;
    track.pits.type=TR_PIT_ON_TRACK_SIDE; track.pits.nMaxPits=20;
    DriverSettings settings; void* output=nullptr;
    auto load=[&]() {
        if (output) GfParmReleaseHandle(output);
        output=loadSettings(&track,reference,settings); assert(output); assert(!GfParmCheckHandle(reference,output));
    };
    auto fuel=[&]() { return GfParmGetNum(output,SECT_CAR,PRM_FUEL,"l",-1); };
    auto wing=[&]() { return GfParmGetNum(output,SECT_REARWING,PRM_WINGANGLE,"deg",-1); };
    load(); near(settings.lookaheadBase,8); near(fuel(),-1); near(settings.stintLaps,0); assert(!settings.demonstrationStop);
    write("default.xml","<section name=\"Car\"><attnum name=\"initial fuel\" unit=\"l\" val=\"60\"/></section><section name=\"Rear Wing\"><attnum name=\"angle\" unit=\"deg\" val=\"16\"/></section><section name=\"Tutorial A\"><attnum name=\"lookahead base\" unit=\"m\" val=\"9\"/><section name=\"Strategy\"><attnum name=\"stint laps\" val=\"3\"/></section></section>");
    load(); near(fuel(),60); near(wing(),16); near(settings.lookaheadBase,9); near(settings.stintLaps,3);
    write("g-track-1.xml","<section name=\"Car\"><attnum name=\"initial fuel\" unit=\"l\" val=\"4\"/></section><section name=\"Rear Wing\"><attnum name=\"angle\" unit=\"rad\" val=\"0.3141592653589793\"/></section><section name=\"Tutorial A\"><attnum name=\"lookahead time\" unit=\"s\" val=\"0.6\"/><section name=\"Strategy\"><attstr name=\"demonstration stop\" val=\"no\"/><attnum name=\"stint laps\" val=\"5\"/><attnum name=\"fuel per lap\" unit=\"l\" val=\"2\"/></section></section>");
    load(); near(fuel(),4); near(wing(),18); near(settings.lookaheadBase,9); near(settings.lookaheadTime,.6);
    assert(!settings.demonstrationStop); near(settings.stintLaps,5); near(settings.fallbackFuelPerLap,2);
    SpeedDriver driver; PitDriver pits; settings.apply(driver,pits);
    near(driver.lookaheadBase,9); near(driver.lookaheadTime,.6); assert(!pits.demonstrationStop);
    near(pits.stintLaps,5); near(pits.estimatedFuelPerLap(),2); pits.fuelPerLap=1; near(pits.estimatedFuelPerLap(),1.15);
    assert(!GfParmGetStr(output,"Tutorial A/Strategy","demonstration stop",nullptr));
    write("g-track-1.xml","<section name=\"Car\"><attnum name=\"initial fuel\" unit=\"l\" val=\"0\"/></section><section name=\"Rear Wing\"><attnum name=\"angle\" unit=\"deg\" val=\"31\"/></section><section name=\"Tutorial A\"><attnum name=\"lookahead base\" val=\"100\"/><attnum name=\"lookahead time\" val=\"nan\"/><section name=\"Strategy\"><attstr name=\"demonstration stop\" val=\"perhaps\"/><attnum name=\"stint laps\" val=\"0\"/></section></section>");
    load(); near(fuel(),60); near(wing(),16); near(settings.lookaheadBase,9); near(settings.lookaheadTime,.33);
    near(settings.stintLaps,0); assert(!settings.demonstrationStop);
    write("g-track-1.xml","<section name=\"Tutorial A\"><section name=\"Strategy\"><attnum name=\"stint laps\" val=\"1\"/></section></section>");
    load(); near(settings.stintLaps,3); // Invalid short stint retains the preceding layer.
    write("g-track-1.xml","<section name=\"Tutorial A\"><attstr name=\"lookahead base\" val=\"7\"/><attnum name=\"typo\" val=\"12\"/></section>");
    load(); near(settings.lookaheadBase,9);
    for (int i=0;i<30;++i) {
        write("g-track-1.xml","<section name=\"Car\"><attnum name=\"initial fuel\" unit=\"l\" val=\""+std::to_string(4+i)+"\"/></section>");
        load(); near(fuel(),4+i); near(settings.lookaheadBase,9);
    }
    { std::ofstream file("drivers/tutoriala/g-track-1.xml"); file << "<params><section"; }
    load(); near(fuel(),60);
    write("g-track-1.xml","<section name=\"Car\"><attnum name=\"initial fuel\" unit=\"l\" val=\"4\"/></section>");
    track.pits.type=TR_PIT_NONE; load(); near(fuel(),60);
    std::remove("drivers/tutoriala/default.xml"); std::remove("drivers/tutoriala/g-track-1.xml");
    track.pits.type=TR_PIT_ON_TRACK_SIDE; load(); near(settings.lookaheadBase,8); near(settings.stintLaps,0);
    GfParmReleaseHandle(output); GfParmReleaseHandle(reference);
    char malformed[]="<params><section"; assert(!GfParmReadBuf(malformed));
    char valid[]="<params name=\"test\"><section name=\"Car\"><attnum name=\"initial fuel\" unit=\"l\" val=\"5\"/></section></params>";
    void* buffer=GfParmReadBuf(valid); assert(buffer); near(GfParmGetNum(buffer,SECT_CAR,PRM_FUEL,"l",0),5); GfParmReleaseHandle(buffer);
    std::printf("PASS: %d numeric comparisons plus fresh reads, private settings and invalid/malformed inputs\n",Checks);
}
