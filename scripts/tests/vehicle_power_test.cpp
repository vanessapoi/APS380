/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef WIN32
#define WIN32
#endif
#include "../../external/torcs-1.3.10/src/modules/simu/simuv2/aps380_live.h"
#include "../../external/torcs-1.3.10/src/modules/simu/simuv2/aps380_ev.h"
#include <iostream>
#include <cstdlib>
static int checks=0;
static void require(bool value,const char *name) {
    if(!value){std::cerr<<"FAILED: "<<name<<'\n';exit(1);} ++checks;
}
int main() {
    const aps380::EvParameters p={404,202000,60000,100,.92,.85,300,50000,355,62.5,.05};
    for(double f: {1.,.7,.5,.2,0.}) {
        auto launch=aps380::electricStep(p,40000,0,0,1,.002,true,0,f);
        auto fast=aps380::electricStep(p,40000,1000,35,1,.002,true,0,f);
        require(std::fabs(launch.torque-404*f)<1e-9,"matched launch torque scales");
        require(std::fabs(fast.shaftPower-202000*f)<1e-8,"matched-speed delivered power scales");
        require(std::fabs(fast.packPower-(fast.shaftPower/.92+300))<1e-8,"energy accounting uses derated work");
        auto regen=aps380::electricStep(p,40000,1000,35,0,.002,true,0,f);
        require(regen.shaftPower==-60000 && regen.packPower==-50700,"regen unchanged");
        auto reverse=aps380::electricStep(p,40000,-1000,35,1,.002,true,0,f);
        require(reverse.shaftPower==aps380::electricStep(p,40000,-1000,35,1,.002,true).shaftPower,"reverse negative work unchanged");
        require(aps380::electricStep(p,40000,1000,35,1,.002,true,1,f).torque==0,"friction brake override unchanged");
    }
    for(double throttle:{0.,.05,.051,.3,1.}) {
        auto a=aps380::electricStep(p,40000,800,25,throttle,.002,true);
        auto b=aps380::electricStep(p,40000,800,25,throttle,.002,true,0,1.);
        require(a.torque==b.torque && a.packPower==b.packPower && a.energyWh==b.energyWh,"disabled/default unity identity");
    }
    aps380_power::Limit a;
    require(a.apply(10)==1,"disabled defaults to unity");a.enable();
    require(a.apply(10)==0,"opt-in waiting starts at zero");
    require(!a.receive("APS380POWER1 old 0 10 .7 1","race",10),"wrong session ignored");
    require(a.receive("APS380POWER1 race 0 10 .7 1","race",10),"initial reset accepted");
    require(a.apply(10.1)==.7,"valid fraction applied");
    require(!a.receive("APS380POWER1 race 0 10.2 1 0","race",10.2),"duplicate ignored");
    require(a.apply(10.51)==0 && a.fault,"expiry latches zero");
    require(!a.receive("APS380POWER1 race 1 10.52 1 0","race",10.52),"ordinary heartbeat cannot recover");
    require(!a.receive("APS380POWER1 race 2 10.50 1 1","race",10.53),"pre-fault reset cannot recover");
    require(a.receive("APS380POWER1 race 3 10.54 .5 1","race",10.54),"explicit new reset recovers");
    require(a.apply(10.54)==.5,"recovery applies new fraction");
    require(!a.receive("APS380POWER1 race 4 11.1 1 0","race",11.1) && a.apply(11.1)==0,"late heartbeat cannot hide stale interval");
    for(const char *bad:{"nan","inf","-0.1","1.1",".7 0 junk"}) {
        aps380_power::Limit b;b.enable();
        std::string msg=std::string("APS380POWER1 race 0 12 ")+bad+" 1";
        require(!b.receive(msg,"race",12) && b.fault && b.apply(12)==0,"malformed/nonfinite feedback fails closed");
    }
    aps380_power::Limit b;b.enable();
    require(!b.receive("APS380POWER1 race 0 11 .5 1","race",12),"old timestamp rejected");
    require(!b.receive("APS380POWER1 race 1 13 .5 1","race",12),"future timestamp rejected");
    _putenv_s("APS380_MOCK_POWER_LIMIT","1");_putenv_s("APS380_LIVE_PORT","");
    aps380_live::init(1);
    require(aps380_live::propulsionLimit(0)==0,"explicit mode without a channel fails closed");
    // Exercise real UDP routing on loopback; no physical devices.
    aps380_platform::startup();
    SOCKET peer=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);sockaddr_in address={};
    address.sin_family=AF_INET;address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    bind(peer,(sockaddr*)&address,sizeof(address));int len=sizeof(address);
    getsockname(peer,(sockaddr*)&address,&len);
    char port[20];sprintf(port,"%d",ntohs(address.sin_port));
    _putenv_s("APS380_LIVE_PORT",port);_putenv_s("APS380_MOCK_POWER_LIMIT","1");
    aps380_live::init(1);aps380_live::send(0,"test");
    char packet[4096];sockaddr_in native={};len=sizeof(native);
    int count=recvfrom(peer,packet,sizeof(packet),0,(sockaddr*)&native,&len);
    require(count>0,"native telemetry establishes return endpoint");
    std::string command="APS380POWER1 "+aps380_live::streams[0].id+" 0 ";
    char value[100];sprintf(value,"%.9f .2 1",aps380_live::clockSeconds());command+=value;
    sendto(peer,command.c_str(),(int)command.size(),0,(sockaddr*)&native,sizeof(native));
    for(int i=0;i<20 && !aps380_live::streams[0].power.active;++i){aps380_live::pollPower();Sleep(1);}
    require(aps380_live::propulsionLimit(0)==.2,"UDP command reaches native propulsion state");
    SOCKET other=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    std::string bad="invalid";sendto(other,bad.c_str(),(int)bad.size(),0,(sockaddr*)&native,sizeof(native));
    Sleep(2);aps380_live::pollPower();
    require(aps380_live::propulsionLimit(0)==.2,"wrong UDP endpoint ignored");
    closesocket(other);aps380_live::close();closesocket(peer);aps380_platform::cleanup();
    _putenv_s("APS380_MOCK_POWER_LIMIT","");_putenv_s("APS380_LIVE_PORT","");
    std::cout<<checks<<" vehicle power checks passed\n";
}
