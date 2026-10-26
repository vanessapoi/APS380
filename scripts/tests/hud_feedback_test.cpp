/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef WIN32
#define WIN32
#endif
#include "../../external/torcs-1.3.10/src/modules/graphic/ssggraph/aps380_hud.h"
#include <iostream>

static int checks=0;
static void require(bool value,const char *name) {
    if (!value) {std::cerr<<"FAILED: "<<name<<'\n';exit(1);} ++checks;
}
static std::string message(int status=1,int alarm=0) {
    std::ostringstream s;s<<"APS380HUD1 123 456 1 123-trial-0";
    for(int i=0;i<aps380_hud::COUNT;++i)s<<' '<<(i==1?status:i==2?alarm:0);
    return s.str();
}
int main() {
    aps380_hud::Frame frame;
    require(aps380_hud::parse(message().c_str(),123,frame),"normal packet");
    require(aps380_hud::parse(message(1,2).c_str(),123,frame)&&frame.value[2]==2,"red discharge alert");
    require(aps380_hud::parse(message(1,3).c_str(),123,frame)&&frame.value[2]==3,"red charge alert");
    require(aps380_hud::parse(message(2,0).c_str(),123,frame)&&frame.value[1]==2,"stale state");
    require(!aps380_hud::parse(message().c_str(),999,frame),"wrong game PID rejected");
    require(!aps380_hud::parse(message(9).c_str(),123,frame),"bad status rejected");
    require(!aps380_hud::parse((message()+" extra").c_str(),123,frame),"trailing fields rejected");
    require(!aps380_hud::parse("APS380HUD1 123 456 1 trial nan",123,frame),"nonfinite/truncated rejected");
    std::cout<<checks<<" HUD feedback checks passed\n";
}
