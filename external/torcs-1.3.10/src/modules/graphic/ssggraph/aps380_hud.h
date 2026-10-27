/* SPDX-License-Identifier: GPL-2.0-or-later
 * Visual-only PC feedback receiver; no vehicle or hardware control hooks. */
#ifndef APS380_HUD_H
#define APS380_HUD_H
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <sstream>
#include <string>
#if defined(WIN32) || defined(__APPLE__) || defined(__unix__)
#include "../../../interfaces/aps380_platform.h"
#endif
namespace aps380_hud {
static const int COUNT=31;
struct Frame {
    unsigned long gamePid,hostPid;
    unsigned long long sequence;
    std::string session;
    double value[COUNT];
};
inline bool parse(const char *packet,unsigned long gamePid,Frame &out) {
    Frame next;std::string tag,trailing;
    std::istringstream input(packet);
    if (!(input>>tag>>next.gamePid>>next.hostPid>>next.sequence>>next.session) ||
        tag!="APS380HUD2" || next.gamePid!=gamePid || next.session.size()>100) return false;
    for (int i=0;i<COUNT;++i)
        if (!(input>>next.value[i]) || !std::isfinite(next.value[i])) return false;
    if (input>>trailing) return false;
    if (next.value[1]<0 || next.value[1]>5 || next.value[1]!=floor(next.value[1]) ||
        next.value[2]<0 || next.value[2]>3 || next.value[2]!=floor(next.value[2]) ||
        next.value[3]<0 || next.value[3]!=floor(next.value[3]) ||
        next.value[16]<0 || next.value[17]<0 || next.value[23]<0) return false;
    out=next;return true;
}
#if defined(WIN32) || defined(__APPLE__) || defined(__unix__)
struct Receiver {
    aps380_platform::Socket channel;
    sockaddr_in peer;
    bool attempted,initialized,hasFrame;
    double lastHello,lastReceive;
    long long renderedSequence;
    int renderedAlarm,renderedStatus;
    Frame frame;
    Receiver():channel(aps380_platform::invalidSocket),attempted(false),initialized(false),hasFrame(false),lastHello(-1),lastReceive(-1),renderedSequence(-1),renderedAlarm(0),renderedStatus(0){}
    ~Receiver(){close();}
    static double now() { return aps380_platform::clockSeconds(); }
    void close() {
        if (channel!=aps380_platform::invalidSocket) aps380_platform::closeSocket(channel);
        channel=aps380_platform::invalidSocket;
        if (initialized) aps380_platform::cleanup();
        initialized=false;
    }
    bool enabled() {
        if (attempted) return channel!=aps380_platform::invalidSocket;
        attempted=true;
        const char *setting=getenv("APS380_LIVE_PORT");
        if (!setting || !*setting) return false;
        char *end=0;long port=strtol(setting,&end,10);
        if (*end || port<1 || port>65535) return false;
        if (!aps380_platform::startup()) return false;
        initialized=true;channel=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
        if (channel==aps380_platform::invalidSocket) {close();return false;}
        if (!aps380_platform::nonblocking(channel)) {close();return false;}
        peer={};peer.sin_family=AF_INET;peer.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
        peer.sin_port=htons((unsigned short)port);return true;
    }
    void poll() {
        if (!enabled()) return;
        double time=now();
        if (time-lastHello>.2) {
            char hello[160];int n=snprintf(hello,sizeof(hello),"APS380_HUD_HELLO_V1 %lu %lld %d %d",aps380_platform::processId(),renderedSequence,renderedAlarm,renderedStatus);
            sendto(channel,hello,n,0,(sockaddr*)&peer,sizeof(peer));lastHello=time;
        }
        for (int i=0;i<256;++i) {
            char data[4096]={};sockaddr_in sender;aps380_platform::SocketLength size=sizeof(sender);
            int length=recvfrom(channel,data,sizeof(data)-1,0,(sockaddr*)&sender,&size);
            if (length==aps380_platform::socketError) break;
            if (sender.sin_addr.s_addr!=peer.sin_addr.s_addr || sender.sin_port!=peer.sin_port) continue;
            Frame next;
            if (!parse(data,aps380_platform::processId(),next)) continue;
            if (next.value[0]>time+.01 || time-next.value[0]>.5) continue;
            if (hasFrame && next.hostPid==frame.hostPid && next.sequence<=frame.sequence) continue;
            frame=next;lastReceive=time;hasFrame=true;
        }
    }
    int status(int car,double simulationTime) const {
        if (!hasFrame) return 0;
        if (now()-lastReceive>.5) return 2;
        if ((int)frame.value[3]!=car) return 0;
        if ((int)frame.value[1]==1 && fabs(frame.value[30]-simulationTime)>.5) return 2;
        return (int)frame.value[1];
    }
    void rendered(int status,int alarm) {
        renderedSequence=hasFrame?(long long)frame.sequence:-1;
        renderedStatus=status;renderedAlarm=alarm;
    }
};
#else
struct Receiver {
    bool hasFrame;Frame frame;
    Receiver():hasFrame(false){}
    bool enabled(){return false;} void poll(){} int status(int,double)const{return 0;}
    void rendered(int,int){}
};
#endif
}
#endif
