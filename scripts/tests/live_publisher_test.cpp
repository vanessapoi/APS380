/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef WIN32
#define WIN32
#endif
#include "../../external/torcs-1.3.10/src/modules/simu/simuv2/aps380_live.h"
#include <iostream>

static int checks=0;
static void require(bool value,const char *name) {
    if (!value) { std::cerr << "FAILED: " << name << '\n'; exit(1); }
    ++checks;
}
int main() {
    require(!aps380_live::sampleReady(0.0,false),"grid initialization is not a live sample");
    require(!aps380_live::sampleReady(-.02,true),"negative countdown time is not a sample");
    require(aps380_live::sampleReady(0.0,true),"active race time zero is recorded");
    require(aps380_live::sampleReady(1.0,true),"active driving/finishing is recorded");
    require(!aps380_live::sampleReady(HUGE_VAL,true),"nonfinite clock is not recorded");
    _putenv_s("APS380_LIVE_PORT","");
    aps380_live::init(1);
    require(aps380_live::channel==INVALID_SOCKET,"disabled by default");
    _putenv_s("APS380_LIVE_PORT","invalid");
    aps380_live::init(1);
    require(aps380_live::channel==INVALID_SOCKET,"invalid port refused");
    WSADATA data; require(WSAStartup(MAKEWORD(2,2),&data)==0,"test socket startup");
    SOCKET listener=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    sockaddr_in endpoint={};endpoint.sin_family=AF_INET;
    endpoint.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    require(bind(listener,(sockaddr*)&endpoint,sizeof(endpoint))==0,"loopback bind");
    int length=sizeof(endpoint);getsockname(listener,(sockaddr*)&endpoint,&length);
    char port[20];snprintf(port,sizeof(port),"%u",ntohs(endpoint.sin_port));
    _putenv_s("APS380_LIVE_PORT",port);
    _putenv_s("APS380_LIVE_REALTIME","0");
    aps380_live::init(1);
    aps380_live::shutdown(); // race abandoned before any active sample
    DWORD shortTimeout=50;
    setsockopt(listener,SOL_SOCKET,SO_RCVTIMEO,(char*)&shortTimeout,sizeof(shortTimeout));
    char empty[32];
    require(recv(listener,empty,sizeof(empty),0)==SOCKET_ERROR && WSAGetLastError()==WSAETIMEDOUT,
            "unstarted race does not send an end for an unknown stream");
    aps380_live::init(1);
    DWORD timeout=2000;setsockopt(listener,SOL_SOCKET,SO_RCVTIMEO,(char*)&timeout,sizeof(timeout));
    aps380_live::send(0,"sample,\"quoted\"\n");
    char packet[4096]={};int count=recv(listener,packet,sizeof(packet)-1,0);
    require(count>0 && strstr(packet,"\"sequence\":0"),"sequence packet received");
    require(strstr(packet,"\\\"quoted\\\"")!=0,"JSON quotes escaped");
    aps380_live::shutdown();memset(packet,0,sizeof(packet));
    count=recv(listener,packet,sizeof(packet)-1,0);
    require(count>0 && strstr(packet,"\"event\":\"ended\""),"end event received");
    closesocket(listener);
    aps380_live::init(1);
    double start=aps380_live::clockSeconds();
    for (int i=0;i<1000;++i) aps380_live::send(0,"no receiver");
    require(aps380_live::clockSeconds()-start<2,"missing receiver does not stall sender");
    aps380_live::shutdown();
    _putenv_s("APS380_LIVE_REALTIME","1");aps380_live::init(1);
    start=aps380_live::clockSeconds();aps380_live::pace(0);aps380_live::pace(.03);
    require(aps380_live::clockSeconds()-start>=.025,"headless wall clock pacing");
    aps380_live::shutdown();WSACleanup();
    std::cout << checks << " live publisher checks passed\n";
}
