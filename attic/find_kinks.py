"""Find non-smooth kinks/stair-steps in the planned line and walls.

For each closed polyline (line, left, right) report the vertices with the
largest local turn angle (deg between consecutive segments) and the local
segment-length ratio (a stair-step shows a short segment between two long ones).
"""
import sys, glob
import numpy as np

PLAN = sys.argv[1] if len(sys.argv) > 1 else sorted(
    glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\*_plan.npz"))[-1]
p = np.load(PLAN)
print("plan:", PLAN, "keys:", list(p.keys()))

def turns(poly):
    poly = np.asarray(poly, float)
    d = np.roll(poly, -1, axis=0) - poly           # segment vectors
    seglen = np.hypot(d[:, 0], d[:, 1])
    a = np.arctan2(d[:, 1], d[:, 0])
    dth = np.abs((np.diff(a, append=a[:1]) + np.pi) % (2*np.pi) - np.pi)
    return np.degrees(dth), seglen

for key in ("line", "left", "right"):
    if key not in p:
        continue
    poly = p[key]
    dth, seglen = turns(poly)
    print(f"\n=== {key}  N={len(poly)}  seglen: min={seglen.min():.2f} "
          f"med={np.median(seglen):.2f} max={seglen.max():.2f} m ===")
    print(f"turn/vertex deg: mean={dth.mean():.2f} p95={np.percentile(dth,95):.2f} "
          f"p99={np.percentile(dth,99):.2f} max={dth.max():.2f}")
    order = np.argsort(dth)[::-1][:12]
    print(" worst kinks (idx, turn_deg, seglen_before, seglen_after, x, z):")
    for i in sorted(order):
        x, z = poly[i]
        print(f"   i={i:4d} turn={dth[i]:6.2f}  segL={seglen[i-1]:5.2f}->{seglen[i]:5.2f}"
              f"  pos=({x:8.1f},{z:8.1f})")
