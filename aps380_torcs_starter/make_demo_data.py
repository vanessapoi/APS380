"""Generate SYNTHETIC sample data (not a real TORCS recording)."""
import csv, math
from pathlib import Path

out = Path('data/demo_synthetic.csv')
out.parent.mkdir(exist_ok=True)
rows = []
# Piecewise speed targets emulate a lap with accel, braking, and cornering.
knots = [(0, 0), (12, 24), (20, 31), (26, 12), (38, 23),
         (46, 10), (60, 29), (69, 14), (80, 34), (92, 9), (105, 23), (120, 0)]
for k in range(1201):
    t = k * 0.1
    for (t0,v0), (t1,v1) in zip(knots, knots[1:]):
        if t0 <= t <= t1:
            # smoothstep speed interpolation makes continuous speed profile
            z = (t-t0)/(t1-t0)
            smooth = z*z*(3-2*z)
            v = v0 + (v1-v0)*smooth
            a_sign = (v1-v0)
            throttle = min(1, max(0, a_sign / 18)) if a_sign > 0 else 0
            brake = min(1, -a_sign/18) if a_sign < 0 else 0
            break
    rows.append({'time_s': f'{t:.1f}', 'speed_mps': f'{v:.4f}',
                 'throttle': f'{throttle:.3f}', 'brake': f'{brake:.3f}'})
with open(out, 'w', newline='') as f:
    writer=csv.DictWriter(f, fieldnames=['time_s','speed_mps','throttle','brake'])
    writer.writeheader(); writer.writerows(rows)
print(f'Generated {len(rows)} synthetic samples: {out}')
