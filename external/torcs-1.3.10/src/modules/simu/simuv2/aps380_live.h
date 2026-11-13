/* SPDX-License-Identifier: GPL-2.0-or-later
 * Loopback telemetry and opt-in MOCK propulsion feedback. No hardware I/O. */
#ifndef APS380_LIVE_H
#define APS380_LIVE_H
#include <cmath>
#include "aps380_power_limit.h"
namespace aps380_live {
// Grid/suspension initialization runs at time zero before the race countdown.
// It is not an active telemetry stream. This gate changes recording only.
inline bool sampleReady(double simulationTime, bool activeRace) {
    return activeRace && std::isfinite(simulationTime) && simulationTime >= 0.0;
}
}
#if defined(WIN32) || defined(__APPLE__) || defined(__unix__)
#include "../../../interfaces/aps380_platform.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
namespace aps380_live {
struct Stream { unsigned long seq; std::string id; aps380_power::Limit power; Stream():seq(0){} };
static aps380_platform::Socket channel = aps380_platform::invalidSocket;
static sockaddr_in destination;
static std::vector<Stream> streams;
static unsigned long sendErrors;
static bool initialized = false, paced = false;
static bool powerRequested = false;
static double wallOrigin = -1, simOrigin = 0;
inline double clockSeconds() { return aps380_platform::clockSeconds(); }

inline std::string quote(const char *value) {
    std::string out="\"";
    for (const unsigned char *p=(const unsigned char*)value; *p; ++p) {
        if (*p=='"' || *p=='\\') { out+='\\'; out+=(char)*p; }
        else if (*p>=32) out+=(char)*p;
    }
    return out+'"';
}
inline void close() {
    if (channel!=aps380_platform::invalidSocket) aps380_platform::closeSocket(channel);
    channel=aps380_platform::invalidSocket;
    if (initialized) aps380_platform::cleanup();
    initialized=false; streams.clear(); paced=false; wallOrigin=-1;
}
inline void init(int cars) {
    close();
    const char *power=getenv("APS380_MOCK_POWER_LIMIT");
    powerRequested=power && !strcmp(power,"1");
    const char *port=getenv("APS380_LIVE_PORT");
    if (!port || !*port) return;
    char *end=0; long number=strtol(port,&end,10);
    if (*end || number<1 || number>65535) { fprintf(stderr,"Invalid APS380_LIVE_PORT\n"); return; }
    if (!aps380_platform::startup()) return;
    initialized=true;
    channel=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    if (channel==aps380_platform::invalidSocket) { close(); return; }
    if (!aps380_platform::nonblocking(channel)) { close(); return; }
    destination={}; destination.sin_family=AF_INET;
    destination.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    destination.sin_port=htons((unsigned short)number);
    streams.resize(cars); sendErrors=0;
    unsigned long long ticks=aps380_platform::counter();
    for (int i=0;i<cars;++i) {
        char identity[100];
        snprintf(identity,sizeof(identity),"%lu-%llu-%d",aps380_platform::processId(),ticks,i);
        streams[i].id=identity;
        if (powerRequested) streams[i].power.enable();
    }
    const char *pace=getenv("APS380_LIVE_REALTIME");
    paced=pace && !strcmp(pace,"1");
}
inline void pace(double simulationTime) {
    if (!paced || simulationTime<0) return;
    if (wallOrigin<0) { wallOrigin=clockSeconds(); simOrigin=simulationTime; }
    const double due=wallOrigin+simulationTime-simOrigin;
    while (due-clockSeconds()>.0005) aps380_platform::sleepMillisecond();
}
inline void pollPower() {
    if (channel==aps380_platform::invalidSocket || streams.empty() || !streams[0].power.enabled) return;
    // Bound work per physics step; never block physics draining a command queue.
    for (int n=0;n<32;++n) {
        char packet[1024]; sockaddr_in peer={};
        aps380_platform::SocketLength size=sizeof(peer);
        int count=recvfrom(channel,packet,sizeof(packet),0,(sockaddr*)&peer,&size);
        if (count<=0) break;
        if (peer.sin_addr.s_addr!=destination.sin_addr.s_addr || peer.sin_port!=destination.sin_port) continue;
        if (count>512) {
            for (size_t i=0;i<streams.size();++i) streams[i].power.trip("FAULT_INVALID",clockSeconds());
            continue;
        }
        const std::string text(packet,count);
        for (size_t i=0;i<streams.size();++i)
            streams[i].power.receive(text,streams[i].id,clockSeconds());
    }
}
inline double propulsionLimit(int car) {
    return car>=0 && car<(int)streams.size() ? streams[car].power.apply(clockSeconds()) : (powerRequested ? 0.0 : 1.0);
}
inline void send(int car, const char *csv, const char *event="sample") {
    if (channel==aps380_platform::invalidSocket || car<0 || car>=(int)streams.size()) return;
    Stream &s=streams[car];
    char feedback[300]="";
    if (s.power.enabled) snprintf(feedback,sizeof(feedback),
        ",\"power_limit\":{\"enabled\":true,\"commanded\":%.9f,\"applied\":%.9f,\"state\":\"%s\",\"sequence\":%lld}",
        s.power.commanded,s.power.applied,s.power.status,s.power.sequence);
    char packet[4096];
    int count=snprintf(packet,sizeof(packet),
        "{\"version\":1,\"session_id\":%s,\"sequence\":%lu,\"sender_qpc_s\":%.9f,"
        "\"send_errors\":%lu,\"event\":%s,\"csv\":%s%s}",
        quote(s.id.c_str()).c_str(),s.seq++,clockSeconds(),sendErrors,
        quote(event).c_str(),quote(csv).c_str(),feedback);
    if (count<=0 || count>=(int)sizeof(packet) ||
        sendto(channel,packet,count,0,(sockaddr*)&destination,sizeof(destination))==aps380_platform::socketError) ++sendErrors;
}
inline void shutdown() {
    for (int i=0;i<(int)streams.size();++i)
        if (streams[i].seq>0) send(i,"","ended");
    close();
}
}
#else
namespace aps380_live {
inline void init(int){} inline void pace(double){} inline void send(int,const char*){}
inline void pollPower(){} inline double propulsionLimit(int){return 1.0;}
inline void shutdown(){}
}
#endif
#endif
