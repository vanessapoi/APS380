/* SPDX-License-Identifier: GPL-2.0-or-later
 * Small platform boundary for loopback telemetry and visual-only feedback. */
#ifndef APS380_PLATFORM_H
#define APS380_PLATFORM_H
#ifdef WIN32
#include <winsock2.h>
#include <windows.h>
#pragma comment(lib,"Ws2_32.lib")
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#ifdef __APPLE__
#include <mach/mach_time.h>
#endif
#endif
namespace aps380_platform {
#ifdef WIN32
typedef SOCKET Socket;
typedef int SocketLength;
static const Socket invalidSocket = INVALID_SOCKET;
static const int socketError = SOCKET_ERROR;
inline bool startup() { WSADATA data; return WSAStartup(MAKEWORD(2,2),&data)==0; }
inline void cleanup() { WSACleanup(); }
inline void closeSocket(Socket s) { closesocket(s); }
inline bool nonblocking(Socket s) { u_long value=1;return ioctlsocket(s,FIONBIO,&value)==0; }
inline unsigned long processId() { return GetCurrentProcessId(); }
inline unsigned long long counter() { LARGE_INTEGER t;QueryPerformanceCounter(&t);return (unsigned long long)t.QuadPart; }
inline double clockSeconds() { LARGE_INTEGER t,f;QueryPerformanceCounter(&t);QueryPerformanceFrequency(&f);return (double)t.QuadPart/(double)f.QuadPart; }
inline void sleepMillisecond() { Sleep(1); }
#else
typedef int Socket;
typedef socklen_t SocketLength;
static const Socket invalidSocket = -1;
static const int socketError = -1;
inline bool startup() { return true; }
inline void cleanup() {}
inline void closeSocket(Socket s) { ::close(s); }
inline bool nonblocking(Socket s) { int flags=fcntl(s,F_GETFL,0);return flags>=0 && fcntl(s,F_SETFL,flags|O_NONBLOCK)==0; }
inline unsigned long processId() { return (unsigned long)getpid(); }
#ifdef __APPLE__
inline unsigned long long counter() { return mach_absolute_time(); }
inline double clockSeconds() { mach_timebase_info_data_t info;mach_timebase_info(&info);return (double)mach_absolute_time()*info.numer/info.denom*1e-9; }
#else
inline double clockSeconds() { timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9; }
inline unsigned long long counter() { return (unsigned long long)(clockSeconds()*1e9); }
#endif
inline void sleepMillisecond() { timespec duration={0,1000000};nanosleep(&duration,0); }
#endif
}
#endif
