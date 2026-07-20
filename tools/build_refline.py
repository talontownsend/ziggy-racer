"""Build the racing line from the USER's best recorded lap (imitation line).
Pick the fastest lap, use its trajectory directly as the line, pair it with the real
track edges (from the edge runs) for on-track boundaries + elevation, compute the
speed profile. This gives the out-in-out line the user actually drives."""
import csv, sys
import numpy as np
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from scipy.spatial import cKDTree
from build_corridor_edges import corridor_from_edges, line_metrics, save_plan, smooth_closed
from racing_line import resample_closed, velocity_profile, grade_adjust, segment_lengths, menger_curvature

REC = r"C:\Users\talon\FH6-AFK-Farm\recordings\refline\session_20260626_130821.csv"
LEFT = r"recordings/limits_left/session_20260626_103954.csv"
RIGHT = r"recordings/limits_right/session_20260626_104413.csv"
N = 1000


def load_laps(path):
    rows = list(csv.DictReader(open(path)))
    laps = {}
    for r in rows:
        if r.get("is_race_on") != "1":
            continue
        try:
            ln = int(r["lap_no"]); lt = float(r["cur_lap_time"]); spd = float(r["speed_mps"])
            x = float(r["pos_x"]); z = float(r["pos_z"]); y = float(r["pos_y"])
        except (KeyError, ValueError):
            continue
        laps.setdefault(ln, []).append((lt, x, z, y, spd))
    return laps


laps = load_laps(REC)
print("lap times (game clock):")
best_ln, best_t = None, 1e9
for ln in sorted(laps):
    arr = np.array(laps[ln]); lt = arr[:, 0]
    dur = lt.max() - lt.min()
    moving = (arr[:, 4] * 3.6 > 3).mean()
    full = dur > 20 and len(arr) > 400 and lt.min() < 2.0   # a complete flying lap
    tag = ""
    if full and dur < best_t:
        best_t, best_ln = dur, ln;
    print(f"  lap {ln}: {dur:5.2f}s  ({len(arr)} pts, {moving*100:.0f}% moving){'  <- complete' if full else '  (partial/outlap)'}")
print(f"BEST lap: {best_ln} @ {best_t:.2f}s")

arr = np.array(laps[best_ln])
# order by cur_lap_time (progression) and take moving frames
arr = arr[np.argsort(arr[:, 0])]
arr = arr[arr[:, 4] * 3.6 > 3]
xz = arr[:, 1:3]; y = arr[:, 3]; uspd = arr[:, 4]
line = resample_closed(xz, N)
# carry elevation + the user's own speed onto the resampled line
tr = cKDTree(xz)
_, idx = tr.query(line)
line_y = smooth_closed(y[idx], 7)
user_v = smooth_closed(uspd[idx], 7)

# real track edges + grip model from the edge runs; pair walls to the line by nearest station
corr = corridor_from_edges(LEFT, RIGHT, lap=1, a_lat_g=2.45, verbose=False)
cen = 0.5 * (corr["left"] + corr["right"])
ck = cKDTree(cen)
_, j = ck.query(line)
left = corr["left"][j]; right = corr["right"][j]
veh, grade_c = corr["veh"], corr["grade"]
# clip the line just inside the edges (car-body clearance) in case the human kissed a wall
c2 = 0.5 * (left + right); nrm = right - c2; nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
half = 0.5 * np.linalg.norm(left - right, axis=1)
off = np.clip(np.sum((line - c2) * nrm, axis=1), -(half - 1.0), (half - 1.0))
line = smooth_closed(c2 + off[:, None] * nrm, 5)

elev = smooth_closed(line_y, 7)
ds_c = segment_lengths(line)
grade = np.clip(smooth_closed((np.roll(elev, -1) - np.roll(elev, 1)) / np.maximum(np.roll(ds_c, 1) + ds_c, 1e-6), 5), -0.35, 0.35)
aacc, abrk = grade_adjust(veh["a_acc"], veh["a_brake"], grade)
PLAN_ALAT = 31.0
V, _, ds = velocity_profile(line, PLAN_ALAT, aacc, abrk, veh["v_max"], a_lat_k=veh["a_lat_k"])
# The model speed (V) was far too conservative -> follower crawled at 1.1g, 44.8s.
# Use the HUMAN's ACTUAL recorded speed as the target: it already encodes their downforce,
# crest slowdowns, and camber (they drove all of it). 5% margin for control headroom.
_, iu = tr.query(line)
# Raise the ceiling above the human's exact pace so the HONEST v_curve (grip limit) sets the
# corner target instead of the human-speed cap holding the follower ~32% below its own
# gentle-path grip limit. v_curve (now honest, 2.6g) prevents over-driving; the plan keeps the
# braking shape. Cap = 71 m/s (255 km/h): the human's PROVEN top speed on the main straight --
# the old 60 m/s (216) cap was pinning the straight target ~40 km/h below what the car reaches.
plan_v = np.minimum(smooth_closed(uspd[iu], 9) * 1.05, 71.0)

m = line_metrics(left, right, line, V)
# out-in-out check
cc = 0.5 * (left + right); nn = right - cc; nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-9)
frac = np.sum((line - cc) * nn, axis=1) / np.maximum(half, 1e-6)
straight = menger_curvature(line) < 1 / 120
print(f"\nHUMAN line: straights mean|frac|={np.abs(frac[straight]).mean():.2f}  corners={np.abs(frac[~straight]).mean():.2f}"
      f"  width used {m['width_used']:.1f}/{2*m['half_mean']:.1f}m")
print(f"  p99turn {m['max_turn']:.1f}deg  clear {m['min_clear']:.2f}m  est lap {m['lap_time']:.1f}s  user-driven {best_t:.1f}s  top {m['top_kmh']:.0f}km/h")

print(f"  target speed: model would be {V.mean()*3.6:.0f} avg / {V.max()*3.6:.0f} top km/h;"
      f" USING HUMAN {plan_v.mean()*3.6:.0f} avg / {plan_v.max()*3.6:.0f} top km/h (x0.95)")
np.savez(r"C:\Users\talon\FH6-AFK-Farm\recordings\refline_plan.npz",
         left=left, right=right, line=line, speed=plan_v, elev=elev, grade=grade)
s = np.cumsum(ds)
fig, ax = plt.subplots(2, 1, figsize=(15, 8))
ax[0].fill_between(s, -1, 1, where=~straight, color="0.9")
ax[0].plot(s, frac, "b-", lw=1.2); ax[0].axhline(0, color="k", lw=0.5); ax[0].set_ylim(-1.2, 1.2)
ax[0].set_title(f"HUMAN best lap ({best_t:.1f}s): line offset (gray=corner)")
sc = ax[1].scatter(line[:, 0], line[:, 1], c=V * 3.6, s=10, cmap="turbo")
ax[1].plot(corr["left"][:, 0], corr["left"][:, 1], "k-", lw=0.5)
ax[1].plot(corr["right"][:, 0], corr["right"][:, 1], "k-", lw=0.5)
ax[1].axis("equal"); fig.colorbar(sc, ax=ax[1]); plt.tight_layout()
plt.savefig(r"C:\Users\talon\FH6-AFK-Farm\recordings\refline.png", dpi=95)
print("saved recordings/refline_plan.npz + refline.png")
