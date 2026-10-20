# file: behavior.py; created: September 2026
# Copyright (C) 2026 by Bernhard Wymann <berniw@bluewin.ch>
# This program is free software under the GNU General Public License,
# version 2 or (at your option) any later version.
"""Evidence-based runtime checks. Missing/partial telemetry is a failure."""
import math
import re
from collections import defaultdict


def fields(line):
    result = {}
    for key, value in re.findall(r"(\w+)=([^\s]+)", line):
        if key in result:
            raise ValueError(f"duplicate field {key}")
        try:
            result[key] = float(value)
        except ValueError:
            result[key] = value
    return result


# Only fields that must be finite are listed. Straight-path radius and uncapped
# allowed-speed diagnostics may intentionally be infinite.
RECORDS = (
    ("OlethrosSession ", "session", {"bot", "length"}),
    ("OlethrosBrain ", "brain", {"bot", "status"}),
    ("OlethrosEnd ", "end", {"bot", "ticks"}),
    ("OlethrosTick ", "tick", {"dt", "recovery", "gear", "speed"}),
    ("OlethrosNumeric controls ", "control", {"steer", "accel", "brake", "clutch"}),
    ("OlethrosSeam state ", "state", {"lap", "distance", "speed", "accel", "brake", "pit"}),
    ("OlethrosNumeric target ", "target", {"x", "y"}),
    ("OlethrosSeam brake ", "candidate", {"delta", "distance"}),
    ("OlethrosBrakePlan ", "brake-plan", {"brake"}),
    ("OlethrosPlan ", "plan", {"allowed"}),
)
SESSION_RECORDS = {"session", "brain", "end"}


def check_behavior(output, track, laps, brain_state="clean", driver_indices=(6,)):
    failures = []
    headers = defaultdict(lambda: defaultdict(list))
    ticks = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    ended = set()
    for line in output.splitlines():
        for prefix, kind, required in RECORDS:
            if not line.startswith(prefix):
                continue
            required = required if kind in SESSION_RECORDS else required | {"bot", "tick", "time"}
            try:
                sample = fields(line)
                missing = required - sample.keys()
                if missing:
                    raise ValueError(f"fields missing: {', '.join(sorted(missing))}")
                for key in required - {"status"}:
                    if not isinstance(sample[key], float) or not math.isfinite(sample[key]):
                        raise ValueError(f"nonfinite or invalid {key}")
                for key in required & {"bot", "tick", "ticks", "gear", "recovery", "lap", "pit"}:
                    if not sample[key].is_integer():
                        raise ValueError(f"noninteger {key}")
                bot = int(sample["bot"])
                if bot not in driver_indices:
                    raise ValueError(f"unexpected bot {bot}")
                if bot in ended:
                    raise ValueError(f"record after end marker for bot {bot}")
                if kind in SESSION_RECORDS:
                    headers[bot][kind].append(sample)
                    if kind == "end":
                        ended.add(bot)
                elif sample["tick"] < 1:
                    raise ValueError("tick must be positive")
                else:
                    ticks[bot][int(sample["tick"])][kind].append(sample)
            except ValueError as exc:
                failures.append(f"{kind} {exc}")
            break

    bots = {}
    intervals = {}
    for bot in driver_indices:
        errors, states, plans = [], [], {}
        controls = target_count = 0
        for kind in SESSION_RECORDS:
            if len(headers[bot][kind]) != 1:
                errors.append(f"require exactly one {kind} record")
        expected_brain = "loaded" if brain_state == "persisted" else "missing"
        if headers[bot]["brain"] and headers[bot]["brain"][0]["status"] != expected_brain:
            errors.append(f"brain load must be {expected_brain}")
        length = headers[bot]["session"][0]["length"] if headers[bot]["session"] else 0
        if length <= 0:
            errors.append("positive track length missing")
        numbers = sorted(ticks[bot])
        if len(numbers) < 10 or numbers != list(range(1, len(numbers)+1)):
            errors.append("required runtime telemetry missing or tick sequence incomplete")
        if headers[bot]["end"] and headers[bot]["end"][0]["ticks"] != len(numbers):
            errors.append("end tick count differs from recorded ticks")
        previous_time = -math.inf
        for number in numbers:
            records = ticks[bot][number]
            for kind in ("tick", "control", "state"):
                if len(records[kind]) != 1:
                    errors.append(f"tick {number}: require exactly one {kind} record")
            controls += len(records["control"])
            target_count += len(records["target"])
            if not records["tick"]:
                continue
            tick = records["tick"][0]
            time = tick["time"]
            if time <= previous_time or tick["dt"] <= 0 or tick["recovery"] not in (0, 1):
                errors.append(f"tick {number}: invalid time, interval or recovery mode")
            previous_time = time
            if time in intervals and not math.isclose(intervals[time], tick["dt"], abs_tol=1e-9):
                errors.append(f"tick {number}: bots disagree on engine interval")
            intervals[time] = tick["dt"]
            for values in records.values():
                if any(sample["time"] != time for sample in values):
                    errors.append(f"tick {number}: record time differs from tick time")
            normal = not tick["recovery"]
            if len(records["target"]) != int(normal):
                errors.append(f"tick {number}: target coverage differs from driving mode")
            for kind, required in (("plan", normal and tick["gear"] > 0),
                                   ("brake-plan", normal and tick["speed"] >= -5)):
                if len(records[kind]) != int(required):
                    errors.append(f"tick {number}: {kind} coverage differs from driving mode")
            if records["candidate"] and not records["brake-plan"]:
                errors.append(f"tick {number}: braking candidates without a plan")
            if records["brake-plan"]:
                demands = [math.tanh(s["delta"]*(1 if s["distance"] == 0 else 0.1))
                           for s in records["candidate"]]
                if not math.isclose(records["brake-plan"][0]["brake"], max(demands, default=0), abs_tol=1e-6):
                    errors.append(f"tick {number}: braking envelope differs from strongest demand")
            if records["state"]:
                state = records["state"][0]
                if records["control"]:
                    state["steer"] = records["control"][0]["steer"]
                states.append(state)
                if records["control"] and any(state[key] != records["control"][0][key] for key in ("accel", "brake")):
                    errors.append(f"tick {number}: state and control commands disagree")
            if records["plan"]:
                plans[number] = records["plan"][0]
        # Track-specific speed thresholds describe the focused bot. Other bots
        # receive complete telemetry/result checks without borrowing its windows.
        windows = check_windows(states, plans, length, track, laps, brain_state, errors) if bot == driver_indices[0] else []
        if track == "oval/d-speedway" and tuple(driver_indices) == (6,):
            windows.extend(check_oval_windows(states, laps, errors))
        if track == "oval/a-speedway" and tuple(driver_indices) == (6,):
            windows.extend(check_steering_windows(states, laps, errors))
        bots[str(bot)] = {"failures": sorted(set(errors)), "controls": controls,
                          "targets": target_count, "states": len(states), "windows": windows}
        failures.extend(f"bot {bot}: {error}" for error in errors)
    return {"failures": sorted(set(failures)), "bots": bots,
            "controls": sum(b["controls"] for b in bots.values()),
            "targets": sum(b["targets"] for b in bots.values()),
            "states": sum(b["states"] for b in bots.values()),
            "windows": bots[str(driver_indices[0])]["windows"]}


def check_windows(states, plans, length, track, laps, brain_state, failures):
    windows = []
    if track == "dirt/dirt-2":
        for lap in range(1, laps+1):
            rows = [s for s in states if s["lap"] == lap and 1520 <= s["distance"] <= 1600]
            if len(rows) < 2 or rows[0]["distance"] > 1522 or rows[-1]["distance"] < 1598:
                failures.append(f"Dirt 2 lap {lap}: straight window incomplete"); continue
            if any(s["pit"] for s in rows):
                windows.append({"lap": lap, "pit": True})
                if brain_state == "clean":
                    failures.append(f"Dirt 2 lap {lap}: pit masks straight check")
                continue
            gain = rows[-1]["speed"]-rows[0]["speed"]
            throttle = sum(s["accel"] for s in rows)/len(rows)
            windows.append({"lap": lap, "pit": False, "speed_gain": gain, "mean_throttle": throttle})
            if gain < 5 or throttle < 0.75:
                failures.append(f"Dirt 2 lap {lap}: acceleration plateau, gain={gain:.3f}, throttle={throttle:.3f}")
        if not any(not w["pit"] for w in windows):
            failures.append("Dirt 2 has no unmasked straight observation")
    if track == "road/lone-star-circuit-full" and length:
        # Last 25 m of lap k and first 12 m of lap k+1, never the standing start.
        for lap in range(1, laps):
            before = [s for s in states if s["lap"] == lap and s["distance"] >= length-25]
            # Include the first sample reaching +12 m, not just samples below
            # an arbitrary +13 m ceiling: a normal tick can jump over it.
            after = []
            for s in states:
                if s["lap"] == lap+1 and 0 <= s["distance"] <= 20:
                    after.append(s)
                    if s["distance"] >= 12:
                        break
            rows = before+after
            if not before or not after or before[0]["distance"] > length-23 or after[-1]["distance"] < 12:
                failures.append(f"Lone Star return {lap}: seam window incomplete"); continue
            if any(s["pit"] for s in rows):
                failures.append(f"Lone Star return {lap}: pit masks seam"); continue
            targets = [plans[s["tick"]]["allowed"] for s in rows if s["tick"] in plans]
            if len(targets) != len(rows):
                failures.append(f"Lone Star return {lap}: planner coverage incomplete"); continue
            minimum = min(s["speed"] for s in rows)
            brake = max(s["brake"] for s in rows)
            windows.append({"return": lap, "minimum_speed": minimum, "maximum_brake": brake,
                            "minimum_target": min(targets), "samples": len(rows)})
            if minimum < 40 or brake > 0.01 or min(targets) < 40 or any(math.isnan(t) for t in targets):
                failures.append(f"Lone Star return {lap}: artificial seam slowdown")
    return windows


def check_oval_windows(states, laps, failures):
    """Olethros 7 alone, in the middle of D-Speedway's constant 900 m bend."""
    windows = []
    for lap in range(2, laps+1):
        label = f"D-Speedway lap {lap}"
        rows = [s for s in states if s["lap"] == lap and 1400 <= s["distance"] <= 2000]
        if (len(rows) < 2 or rows[0]["distance"] > 1403 or rows[-1]["distance"] < 1997
                or any(not 0 < b["distance"]-a["distance"] <= 5 for a, b in zip(rows, rows[1:]))):
            failures.append(f"{label}: oval window incomplete")
            continue
        if any(s["pit"] for s in rows):
            failures.append(f"{label}: pit masks oval check")
            continue
        if any(not isinstance(s.get("middle"), float) or not math.isfinite(s["middle"])
               or not isinstance(s.get("radius"), float) or math.isnan(s["radius"]) for s in rows):
            failures.append(f"{label}: lateral position or radius missing/nonfinite")
            continue
        minimum_speed = min(s["speed"] for s in rows)
        maximum_brake = max(s["brake"] for s in rows)
        minimum_radius = min(s["radius"] for s in rows)
        excursion = max(s["middle"] for s in rows)-min(s["middle"] for s in rows)
        windows.append({"lap": lap, "oval": True, "minimum_speed": minimum_speed,
                        "maximum_brake": maximum_brake, "minimum_radius": minimum_radius,
                        "lateral_excursion": excursion, "samples": len(rows)})
        if minimum_radius < 200:
            failures.append(f"{label}: artificial tight bend in planned line")
        if minimum_speed < 70 or maximum_brake > 0.01:
            failures.append(f"{label}: artificial oval slowdown")
        if excursion > 3:
            failures.append(f"{label}: weaving in constant-radius bend")
    return windows


def check_steering_windows(states, laps, failures):
    """A-Speedway's opposite straight exposes world-heading +/-pi steering kicks."""
    windows = []
    for lap in range(2, laps+1):
        label = f"A-Speedway lap {lap}"
        # Here the lookahead target's lateral weight is constant. The wider
        # 850-1080 m interval also includes corner settling/preparation, whose
        # intended lateral motion must not be counted as straight-line weaving.
        rows = [s for s in states if s["lap"] == lap and 900 <= s["distance"] <= 1030]
        if (len(rows) < 2 or rows[0]["distance"] > 903 or rows[-1]["distance"] < 1027
                or any(not 0 < b["distance"]-a["distance"] <= 5 for a, b in zip(rows, rows[1:]))):
            failures.append(f"{label}: steering window incomplete")
            continue
        if any(s["pit"] for s in rows):
            failures.append(f"{label}: pit masks steering check")
            continue
        if any(not isinstance(s.get(key), float) or not math.isfinite(s[key])
               for s in rows for key in ("middle", "steer")):
            failures.append(f"{label}: lateral position or steering missing/nonfinite")
            continue
        excursion = max(s["middle"] for s in rows)-min(s["middle"] for s in rows)
        jump = max(abs(b["steer"]-a["steer"]) for a, b in zip(rows, rows[1:]))
        windows.append({"lap": lap, "steering": True, "lateral_excursion": excursion,
                        "maximum_steering_jump": jump, "samples": len(rows)})
        if excursion > 0.2 or jump > 0.02:
            failures.append(f"{label}: straight-line weaving or steering kick")
    return windows
