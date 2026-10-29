/* SPDX-License-Identifier: GPL-2.0-or-later
 * Native POSIX smoke checks of the actual publisher/HUD headers. No hardware. */
#include "../../external/torcs-1.3.10/src/modules/simu/simuv2/aps380_live.h"
#include "../../external/torcs-1.3.10/src/modules/graphic/ssggraph/aps380_hud.h"
#include <iostream>
#include <cassert>
#include <cstring>
#include <iomanip>

static int checks=0;
static void require(bool value,const char *name) {
    if (!value) {std::cerr<<"FAILED: "<<name<<'\n';exit(1);}++checks;
}
static std::string receive(int channel,sockaddr_in *sender=0) {
    double deadline=aps380_platform::clockSeconds()+.5;
    do {
        char data[4096]={};sockaddr_in origin={};socklen_t size=sizeof(origin);
        int n=(int)recvfrom(channel,data,sizeof(data)-1,0,(sockaddr*)&origin,&size);
        if(n>=0) {if(sender)*sender=origin;return std::string(data,n);}
        aps380_platform::sleepMillisecond();
    } while(aps380_platform::clockSeconds()<deadline);
    return "";
}
static std::string frame(unsigned long pid,unsigned long sequence) {
    std::ostringstream out;out<<std::setprecision(17)<<"APS380HUD2 "<<pid<<" 42 "<<sequence<<" "<<pid<<"-test-0";
    for(int i=0;i<aps380_hud::COUNT;++i)out<<' '<<(i==0?aps380_platform::clockSeconds():i==1?1:0);
    return out.str();
}
int main() {
    unsetenv("APS380_LIVE_PORT");aps380_live::init(1);
    require(aps380_live::channel==aps380_platform::invalidSocket,"disabled by default");
    setenv("APS380_LIVE_PORT","bad",1);aps380_live::init(1);
    require(aps380_live::channel==aps380_platform::invalidSocket,"invalid port disabled");
    int server=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);require(server>=0,"server socket");
    sockaddr_in address={};address.sin_family=AF_INET;address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    require(bind(server,(sockaddr*)&address,sizeof(address))==0,"loopback bind");
    socklen_t length=sizeof(address);getsockname(server,(sockaddr*)&address,&length);
    require(aps380_platform::nonblocking(server),"nonblocking server");
    std::string port=std::to_string(ntohs(address.sin_port));setenv("APS380_LIVE_PORT",port.c_str(),1);
    setenv("APS380_LIVE_REALTIME","0",1);aps380_live::init(1);
    require(aps380_live::channel!=aps380_platform::invalidSocket,"publisher enabled");
    aps380_live::send(0,"csv,\"quoted\"");std::string packet=receive(server);
    require(packet.find("\\\"quoted\\\"")!=std::string::npos,"JSON quote escaping");
    require(packet.find("\"sequence\":0")!=std::string::npos,"initial sequence");
    require(packet.find(std::to_string(aps380_platform::processId())+"-")!=std::string::npos,"native PID identity");
    aps380_live::send(0,"next");require(receive(server).find("\"sequence\":1")!=std::string::npos,"sequence advances");
    aps380_live::shutdown();require(receive(server).find("\"event\":\"ended\"")!=std::string::npos,"end packet");
    aps380_hud::Receiver hud;hud.poll();sockaddr_in hudAddress={};
    require(receive(server,&hudAddress).find("APS380_HUD_HELLO_V1")==0,"HUD registration");
    std::string feedback=frame(aps380_platform::processId(),1);
    sendto(server,feedback.c_str(),feedback.size(),0,(sockaddr*)&hudAddress,sizeof(hudAddress));
    for(int attempt=0;attempt<50 && !hud.hasFrame;++attempt) {
        aps380_platform::sleepMillisecond();hud.poll();
    }
    if(!hud.hasFrame) {
        aps380_hud::Frame probe;
        std::cerr<<"Feedback: "<<feedback<<" parse="<<aps380_hud::parse(feedback.c_str(),aps380_platform::processId(),probe)<<" now="<<std::setprecision(17)<<aps380_platform::clockSeconds()<<"\n";
    }
    require(hud.hasFrame && hud.frame.sequence==1,"HUD feedback accepted");
    require(hud.status(0,0)==1,"fresh HUD status");
    feedback=frame(aps380_platform::processId()+1,2);
    sendto(server,feedback.c_str(),feedback.size(),0,(sockaddr*)&hudAddress,sizeof(hudAddress));
    hud.poll();require(hud.frame.sequence==1,"wrong process rejected");
    feedback=frame(aps380_platform::processId(),1);
    sendto(server,feedback.c_str(),feedback.size(),0,(sockaddr*)&hudAddress,sizeof(hudAddress));
    hud.poll();require(hud.frame.sequence==1,"duplicate sequence rejected");
    hud.rendered(1,0);double deadline=aps380_platform::clockSeconds()+.55;
    while(aps380_platform::clockSeconds()<deadline)aps380_platform::sleepMillisecond();
    require(hud.status(0,0)==2,"stale HUD detected");hud.poll();
    require(receive(server).find(" 1 0 1")!=std::string::npos,"render acknowledgement");
    setenv("APS380_LIVE_REALTIME","1",1);aps380_live::init(1);
    double start=aps380_platform::clockSeconds();aps380_live::pace(0);aps380_live::pace(.05);
    require(aps380_platform::clockSeconds()-start>=.049,"native real-time pacing");
    aps380_live::shutdown();hud.close();::close(server);
    std::cout<<checks<<" native telemetry/HUD socket checks passed\n";
}
