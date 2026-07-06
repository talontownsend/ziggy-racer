"""Characterize the persistent dirt corner (line idx ~50-100): which side the car
leaves on, and whether the planned line runs too close to a wall there."""
import csv
import sys
import numpy as np

sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from racing_line import menger_curvature

rows = list(csv.DictReader(open(r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv")))[-5000:]
sel = [r for r in rows if 45 <= int(float(r["i0"])) <= 105]
if sel:
    cte = np.array([float(r["cte_m"]) for r in sel])
    ot = np.array([int(float(r["on_track"])) for r in sel])
    spd = np.array([float(r["spd_kmh"]) for r in sel])
    print(f"idx45-105: {len(sel)} frames  on_track {100*ot.mean():.0f}%  "
          f"cte mean {cte.mean():+.1f} m (>0 = car RIGHT of line)  |cte| {np.abs(cte).mean():.1f}  "
          f"speed {spd.mean():.0f} km/h")

d = np.load(r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038_plan.npz")
line, left, right = d["line"], d["left"], d["right"]
k = menger_curvature(line)
print("plan geometry around the corner:")
for i in range(45, 106, 10):
    half = 0.5 * np.hypot(*(left[i] - right[i]))
    dl = np.hypot(*(line[i] - left[i]))
    dr = np.hypot(*(line[i] - right[i]))
    print(f"  i{i:3d}: R={1/max(k[i],1e-6):5.0f} m  width={2*half:4.1f} m  "
          f"line->Lwall={dl:4.1f}  line->Rwall={dr:4.1f}")
