/* SPDX-License-Identifier: GPL-2.0-or-later
 * Opt-in MOCK battery feedback. Not a physical safety controller. */
#ifndef APS380_POWER_LIMIT_H
#define APS380_POWER_LIMIT_H
#include <cmath>
#include <sstream>
#include <locale>
#include <string>

namespace aps380_power {
struct Limit {
    bool enabled, active, fault;
    double commanded, applied, stamp, faultTime;
    long long sequence;
    const char *status;
    Limit(): enabled(false), active(false), fault(false), commanded(1), applied(1),
        stamp(0), faultTime(0), sequence(-1), status("DISABLED") {}
    void enable() { enabled=true; commanded=applied=0; status="WAITING"; }
    void trip(const char *reason, double now) {
        if (!fault) { faultTime=now; status=reason; }
        fault=true; active=false; applied=0;
    }
    bool receive(const std::string &text, const std::string &session, double now) {
        if (!enabled) return false;
        apply(now); // A late heartbeat must not erase an expired interval.
        std::istringstream in(text); in.imbue(std::locale::classic());
        std::string tag, id, extra; long long seq; double sent, fraction; int reset;
        if (!(in>>tag>>id) || tag!="APS380POWER1") {
            trip("FAULT_INVALID",now); return false;
        }
        if (id!=session) return false; // A retired race cannot affect this car.
        if (!(in>>seq>>sent>>fraction>>reset) || (in>>extra) ||
            seq<0 || seq>1000000000LL || !std::isfinite(sent) || !std::isfinite(fraction) ||
            fraction<0 || fraction>1 || (reset!=0 && reset!=1)) {
            trip("FAULT_INVALID",now); return false;
        }
        if (seq<=sequence) return false; // Never refresh expiry with a replay.
        sequence=seq;
        if (now-sent>.25 || sent-now>.001) {
            trip("FAULT_INVALID",now); return false;
        }
        if ((!active || fault) && (!reset || (fault && sent<=faultTime))) return false;
        commanded=fraction; stamp=sent; active=true; fault=false; status="ACTIVE";
        return true;
    }
    double apply(double now) {
        if (!enabled) return applied=1;
        if (active && (now-stamp>.5 || now<stamp-.001)) trip("FAULT_STALE",now);
        return applied=(active && !fault ? commanded : 0);
    }
};
}
#endif
