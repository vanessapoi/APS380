"""Optional offline local-linear speed smoothing, within one continuous segment."""
import math
from battery_model import validate_telemetry


def smooth_speed(rows, window_s=0.2):
    """Fit speed versus recorded time in a centered window of total width window_s.

    Timestamps/pedals are unchanged. Fits use actual irregular timestamps, with
    truncated windows at edges. Requires future samples: not a live filter.
    This changes speed values explicitly; it neither resamples nor fills gaps.
    Call separately for each adapter segment.
    """
    if not math.isfinite(window_s) or window_s < 0:
        raise ValueError('window_s must be finite and nonnegative')
    data = validate_telemetry(rows)
    if window_s == 0:
        return data
    result = []
    for row in data:
        nearby = [r for r in data if abs(r['time_s']-row['time_s']) <= window_s/2]
        xs = [r['time_s']-row['time_s'] for r in nearby]
        ys = [r['speed_mps'] for r in nearby]
        mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
        variance = sum((x-mx)**2 for x in xs)
        slope = sum((x-mx)*(y-my) for x,y in zip(xs,ys))/variance if variance else 0
        result.append({**row, 'speed_mps': max(0., my-slope*mx)})
    return result
