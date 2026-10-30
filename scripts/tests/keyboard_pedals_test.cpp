/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "../../external/torcs-1.3.10/src/drivers/human/aps380_keyboard.h"
#include <iostream>
#include <cstdlib>
#include <limits>
static int checks=0;
static void require(bool value,const char *name) {
    if (!value) {std::cerr << "FAILED: " << name << '\n';exit(1);} ++checks;
}
static bool near(double a,double b) {return std::abs(a-b)<1e-10;}
int main() {
    using aps380_keyboard::step;
    double t=0.,b=0.;
    for(int i=0;i<50;++i)t=step(t,true,.02,.5,1.);
    require(near(t,.5),"throttle one second press");
    for(int i=0;i<50;++i)t=step(t,true,.02,.5,1.);
    require(near(t,1.),"throttle full after two seconds");
    t=step(t,false,.25,.5,1.);require(near(t,.75),"throttle gradual release");
    for(int i=0;i<50;++i)t=step(t,false,.02,.5,1.);
    require(t==0.,"throttle released clamped zero");
    b=step(b,true,.25,1.,2.);require(near(b,.25),"brake gradual press");
    b=step(b,true,1.,1.,2.);require(b==1.,"brake maximum");
    b=step(b,false,.1,1.,2.);require(near(b,.8),"brake gradual release");
    b=step(b,false,1.,1.,2.);require(b==0.,"brake minimum");
    require(near(step(0.,true,.2,.25,.75),.05),"configurable rise");
    require(near(step(.5,false,.2,.25,.75),.35),"configurable fall");
    require(near(step(.5,true,0.,.5,1.),.5),"zero paused timestep");
    require(near(step(.5,false,-1.,.5,1.),.5),"invalid negative timestep");
    require(near(step(.5,true,std::numeric_limits<double>::quiet_NaN(),.5,1.),.5),"invalid timestep finite");
    require(step(.5,true,.1,-1.,1.)==0.,"invalid rate rejected at runtime");
    double x=0.;for(int i=0;i<100;++i)x=step(x,true,.01,.37,1.);
    require(near(x,step(0.,true,1.,.37,1.)),"simulation timestep independence");
    // Exact GfCtrlType constants are verified by the production human-driver build.
    for(int type=0;type<8;++type) {
        require(!aps380_keyboard::enabledFor(false,type,4,5),"opt-out bypasses every input");
        require(aps380_keyboard::enabledFor(true,type,4,5)==(type==4||type==5),"only the two keyboard types enabled");
    }
    std::cout << checks << " keyboard pedal checks passed\n";
}
