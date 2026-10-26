/* SPDX-License-Identifier: GPL-2.0-or-later
 * Optional loopback telemetry. No control commands or hardware interfaces. */
#ifndef APS380_LIVE_H
#define APS380_LIVE_H
#ifdef WIN32
#include <winsock2.h>
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#pragma comment(lib, "Ws2_32.lib")
namespace aps380_live {
struct Stream { unsigned long seq; std::string id; Stream():seq(0){} };
static SOCKET channel = INVALID_SOCKET;
static sockaddr_in destination;
static std::vector<Stream> streams;
static unsigned long sendErrors;
static bool initialized = false, paced = false;
static double wallOrigin = -1, simOrigin = 0;
inline double clockSeconds() {
    LARGE_INTEGER now, frequency;
    QueryPerformanceCounter(&now); QueryPerformanceFrequency(&frequency);
    return (double)now.QuadPart/(double)frequency.QuadPart;
}
inline std::string quote(const char *value) {
    std::string out="\"";
    for (const unsigned char *p=(const unsigned char*)value; *p; ++p) {
        if (*p=='"' || *p=='\\') { out+='\\'; out+=(char)*p; }
        else if (*p>=32) out+=(char)*p;
    }
    return out+'"';
}
inline void close() {
    if (channel!=INVALID_SOCKET) closesocket(channel);
    channel=INVALID_SOCKET;
    if (initialized) WSACleanup();
    initialized=false; streams.clear(); paced=false; wallOrigin=-1;
}
inline void init(int cars) {
    close();
    const char *port=getenv("APS380_LIVE_PORT");
    if (!port || !*port) return;
    char *end=0; long number=strtol(port,&end,10);
    if (*end || number<1 || number>65535) { fprintf(stderr,"Invalid APS380_LIVE_PORT\n"); return; }
    WSADATA data;
    if (WSAStartup(MAKEWORD(2,2),&data)) return;
    initialized=true;
    channel=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    if (channel==INVALID_SOCKET) { close(); return; }
    u_long nonblocking=1;
    if (ioctlsocket(channel,FIONBIO,&nonblocking)) { close(); return; }
    destination={}; destination.sin_family=AF_INET;
    destination.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    destination.sin_port=htons((u_short)number);
    streams.resize(cars); sendErrors=0;
    LARGE_INTEGER ticks; QueryPerformanceCounter(&ticks);
    for (int i=0;i<cars;++i) {
        char identity[100];
        snprintf(identity,sizeof(identity),"%lu-%lld-%d",GetCurrentProcessId(),ticks.QuadPart,i);
        streams[i].id=identity;
    }
    const char *pace=getenv("APS380_LIVE_REALTIME");
    paced=pace && !strcmp(pace,"1");
}
inline void pace(double simulationTime) {
    if (!paced || simulationTime<0) return;
    if (wallOrigin<0) { wallOrigin=clockSeconds(); simOrigin=simulationTime; }
    const double due=wallOrigin+simulationTime-simOrigin;
    while (due-clockSeconds()>.0005) Sleep(1);
}
inline void send(int car, const char *csv, const char *event="sample") {
    if (channel==INVALID_SOCKET || car<0 || car>=(int)streams.size()) return;
    Stream &s=streams[car];
    char packet[4096];
    int count=snprintf(packet,sizeof(packet),
        "{\"version\":1,\"session_id\":%s,\"sequence\":%lu,\"sender_qpc_s\":%.9f,"
        "\"send_errors\":%lu,\"event\":%s,\"csv\":%s}",
        quote(s.id.c_str()).c_str(),s.seq++,clockSeconds(),sendErrors,
        quote(event).c_str(),quote(csv).c_str());
    if (count<=0 || count>=(int)sizeof(packet) ||
        sendto(channel,packet,count,0,(sockaddr*)&destination,sizeof(destination))==SOCKET_ERROR) ++sendErrors;
}
inline void shutdown() {
    for (int i=0;i<(int)streams.size();++i) send(i,"","ended");
    close();
}
}
#else
namespace aps380_live {
inline void init(int){} inline void pace(double){} inline void send(int,const char*){}
inline void shutdown(){}
}
#endif
#endif
