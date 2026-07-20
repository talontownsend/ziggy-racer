"""
STRATEGY A - HOT-LAP-AVERAGED CENTERLINE + TIGHT PERPENDICULAR CASTING.

Build a smooth centerline by averaging the hot laps (each resampled to N=400,
circularly aligned + direction-matched to the first hot lap). Hot laps have NO
turnaround and NO seam at start/finish, so index 0 is not a seam. Then cast the
centerline normal at each station and pick the nearest, most-perpendicular point
on each boundary edge loop within a tight window -> left/right walls.
"""
import sys
import csv
import numpy as np

sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
import racing_line as RL

CSV = r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038.csv"
SCRIPT_PATH = r"C:\Users\talon\FH6-AFK-Farm\extract_A.py"
PNG_PATH = r"C:\Users\talon\FH6-AFK-Farm\recordings\corridorA.png"
NPZ_PATH = r"C:\Users\talon\FH6-AFK-Farm\recordings\planA.npz"

N = 400
VEHICLE = {"a_lat": 8.0, "a_acc": 11.2, "a_brake": 13.7, "v_max": 67.2}
TIGHT_WIN = 16.0       # perpendicular casting window (m), smaller than self-pinch gap
PERP_MAX = 0.55        # max |disp . tangent| / |disp| allowed (cos to tangent)

# --------------------------------------------------------------------------- #
# 1. Load + clean
# --------------------------------------------------------------------------- #
with open(CSV, newline="") as f:
    r = csv.reader(f)
    header = next(r)
    idx = {name: i for i, name in enumerate(header)}
    rows = [row for row in r if row]
arr = np.array(rows, dtype=float)

pos_x = arr[:, idx["pos_x"]]
pos_z = arr[:, idx["pos_z"]]
speed = arr[:, idx["speed_mps"]]
ts = arr[:, idx["timestamp_ms"]]
clt = arr[:, idx["cur_lap_time"]]

speed_kmh = speed * 3.6
moving = (speed_kmh > 3) & ~((pos_x == 0) & (pos_z == 0))

mx = pos_x[moving]
mz = pos_z[moving]
mspeed = speed_kmh[moving]
mts = ts[moving]
mclt = clt[moving]
P = np.column_stack([mx, mz])

# --------------------------------------------------------------------------- #
# 2. Boundary / hot split
# --------------------------------------------------------------------------- #
split = None
for k in range(len(mspeed) - 200):
    if np.median(mspeed[k:k + 200]) > 120:
        split = k
        break
print("split:", split)

# lap boundaries from cur_lap_time resets
dclt = np.diff(mclt)
resets = np.where(dclt < -5)[0]
bounds = [0] + (resets + 1).tolist() + [len(mclt)]
segs = list(zip(bounds[:-1], bounds[1:]))

# --------------------------------------------------------------------------- #
# 3. Extract HOT laps as closed loops (clean ~1080m, ~28-30s)
#    Keep only segments fully in hot region whose length ~ track length.
# --------------------------------------------------------------------------- #
hot_loops = []
for a, b in segs:
    if a < split - 600:
        continue
    L = np.sum(np.hypot(np.diff(mx[a:b]), np.diff(mz[a:b])))
    dur = (mts[b - 1] - mts[a]) / 1000.0
    # clean hot lap: length within ~1000-1180 m and 27-32 s
    if 1000 <= L <= 1180 and 27 <= dur <= 32 and (b - a) > 1500:
        hot_loops.append(P[a:b].copy())
        print(f"  hot lap [{a}:{b}] n={b-a} dur={dur:.1f}s len={L:.0f}m")
print("num clean hot laps:", len(hot_loops))

# --------------------------------------------------------------------------- #
# 4. Resample each hot lap to N, align (circular shift + direction) to lap 0,
#    average -> smooth seam-free centerline.
# --------------------------------------------------------------------------- #
def resample(loop):
    return RL.resample_closed(loop, N)

ref = resample(hot_loops[0])
# normalize starting direction of ref later; align all others to ref.

def best_align(ref, cand):
    """Return cand reindexed to best match ref (try both directions, all shifts)."""
    best = None
    best_err = np.inf
    for direction in (1, -1):
        c = cand[::direction].copy()
        # try all circular shifts via FFT cross-correlation on both coords
        # brute force is fine for N=400
        for sh in range(N):
            cc = np.roll(c, sh, axis=0)
            err = np.sum((cc - ref) ** 2)
            if err < best_err:
                best_err = err
                best = cc
    return best

aligned = [ref]
for loop in hot_loops[1:]:
    cand = resample(loop)
    aligned.append(best_align(ref, cand))

center = np.mean(aligned, axis=0)
# resample center to uniform arc length again to clean spacing
center = RL.resample_closed(center, N)
print("center built, len=", np.sum(np.hypot(*np.diff(np.vstack([center, center[0]]), axis=0).T)))

# unit tangents / left-normals on centerline (closed)
def tangents_normals(c):
    t = np.roll(c, -1, axis=0) - np.roll(c, 1, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-t[:, 1], t[:, 0]])  # left normal
    return t, nrm

T, Nrm = tangents_normals(center)

# --------------------------------------------------------------------------- #
# 5. Extract boundary edge loops (drop the turnaround).
#    L1 [first boundary lap], L2 [second], split by the first reset.
#    Turnaround = velocity-direction reversal near start/finish -> trim it.
# --------------------------------------------------------------------------- #
bres = [r for r in resets if r < split]
# boundary laps:
b1a, b1b = 0, bres[0] + 1
b2a, b2b = bres[0] + 1, bres[1] + 1 if len(bres) > 1 else split
edge1 = P[b1a:b1b]
edge2 = P[b2a:b2b]

def drop_turnaround(seg):
    """Remove frames where car reverses direction (cos(angle between consecutive
    velocity vectors) < -0.2). Keep the largest contiguous forward run."""
    dx = np.gradient(seg[:, 0]); dz = np.gradient(seg[:, 1])
    v = np.column_stack([dx, dz])
    vn = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
    cosang = np.sum(vn[:-1] * vn[1:], axis=1)
    bad = np.where(cosang < -0.2)[0]
    if len(bad) == 0:
        return seg
    # split into runs around bad indices, keep longest run
    mask = np.ones(len(seg), bool)
    for bi in bad:
        mask[max(0, bi - 2):bi + 3] = False
    # find longest contiguous True run
    runs = []
    i = 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    a, b = max(runs, key=lambda r: r[1] - r[0])
    return seg[a:b]

edge1c = drop_turnaround(edge1)
edge2c = drop_turnaround(edge2)
print(f"edge1 {len(edge1)}->{len(edge1c)}  edge2 {len(edge2)}->{len(edge2c)}")

# resample edge loops to dense uniform points for casting (closed)
E1 = RL.resample_closed(edge1c, 2000)
E2 = RL.resample_closed(edge2c, 2000)

# --------------------------------------------------------------------------- #
# 6. Perpendicular casting: for each centerline station, find nearest most-
#    perpendicular point on each edge loop within TIGHT_WIN.
# --------------------------------------------------------------------------- #
def cast(center, T, Nrm, E):
    """Return signed normal offsets (along left-normal) for edge E at each station."""
    offs = np.full(len(center), np.nan)
    for i in range(len(center)):
        ci = center[i]
        disp = E - ci                      # (M,2)
        dist = np.linalg.norm(disp, axis=1)
        within = dist < TIGHT_WIN
        if not within.any():
            within = dist < TIGHT_WIN * 1.6
        if not within.any():
            continue
        # perpendicularity: |disp . tangent| / |disp| small
        dnorm = disp / np.maximum(dist[:, None], 1e-9)
        para = np.abs(dnorm @ T[i])         # cos to tangent
        ok = within & (para < PERP_MAX)
        if not ok.any():
            ok = within
        # among ok, pick most perpendicular then nearest -> cost
        cost = para + 0.05 * dist
        cost[~ok] = np.inf
        j = np.argmin(cost)
        offs[i] = disp[j] @ Nrm[i]          # signed offset along left normal
    return offs

off1 = cast(center, T, Nrm, E1)
off2 = cast(center, T, Nrm, E2)

# fill nan by interpolation (closed)
def fill_nan_closed(o):
    o = o.copy()
    n = len(o)
    if np.all(np.isnan(o)):
        return np.zeros(n)
    # work on doubled array for wraparound
    idx = np.arange(n)
    good = ~np.isnan(o)
    # extend
    xg = np.concatenate([idx[good] - n, idx[good], idx[good] + n])
    yg = np.concatenate([o[good], o[good], o[good]])
    o[~good] = np.interp(idx[~good], xg, yg)
    return o

off1 = fill_nan_closed(off1)
off2 = fill_nan_closed(off2)

# closed moving-average smoothing of offsets
def smooth_closed(o, w=9):
    k = np.ones(w) / w
    ext = np.concatenate([o[-w:], o, o[:w]])
    sm = np.convolve(ext, k, mode="same")
    return sm[w:-w]

off1s = smooth_closed(off1, 11)
off2s = smooth_closed(off2, 11)

# left = more-positive offset side, right = more-negative side (per station)
left_off = np.maximum(off1s, off2s)
right_off = np.minimum(off1s, off2s)

# enforce a minimum corridor separation? keep as-is; just guarantee left>right.
left = center + left_off[:, None] * Nrm
right = center + right_off[:, None] * Nrm

# --------------------------------------------------------------------------- #
# 7. VALIDATION: walls non-crossing -> left_off > right_off at every station.
# --------------------------------------------------------------------------- #
sep = left_off - right_off
seam_ok = bool(np.all(sep > 0.5))
# check specifically near start/finish (station 0 +/- 20)
sf_band = np.concatenate([np.arange(-20, 0) % N, np.arange(0, 21)])
sf_ok = bool(np.all(sep[sf_band] > 0.5))
print(f"separation min={sep.min():.2f} max={sep.max():.2f} mean={sep.mean():.2f}")
print(f"seam_ok(all)={seam_ok}  start/finish_band_ok={sf_ok}")

width_mean = float(np.mean(sep))
width_min = float(np.min(sep))
width_max = float(np.max(sep))

# --------------------------------------------------------------------------- #
# 8. Run the PROVIDED optimizer.
# --------------------------------------------------------------------------- #
plan = RL.plan_racing_line(left, right, VEHICLE, n=N)
line = plan["line"]

# smooth optimized line (closed moving average window 9) before velocity profile
def smooth_line_closed(L, w=9):
    k = np.ones(w) / w
    out = np.empty_like(L)
    ext = np.concatenate([L[-w:], L, L[:w]], axis=0)
    for c in range(2):
        out[:, c] = np.convolve(ext[:, c], k, mode="same")[w:-w]
    return out

line_s = smooth_line_closed(line, 9)
v, kappa, ds = RL.velocity_profile(line_s, VEHICLE["a_lat"], VEHICLE["a_acc"],
                                   VEHICLE["a_brake"], VEHICLE["v_max"])
lap_time = float(np.sum(ds / np.maximum(v, 0.5)))
top_speed_kmh = float(np.max(v) * 3.6)
print(f"\nLAP TIME = {lap_time:.2f} s   TOP SPEED = {top_speed_kmh:.1f} km/h")
print(f"lap_distance = {ds.sum():.1f} m")

# --------------------------------------------------------------------------- #
# 9. Plot + save
# --------------------------------------------------------------------------- #
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 9))

# panel a: walls
ax1.plot(left[:, 0], left[:, 1], "-", color="blue", lw=1.5, label="left wall")
ax1.plot(right[:, 0], right[:, 1], "-", color="red", lw=1.5, label="right wall")
ax1.plot(center[:, 0], center[:, 1], "-", color="green", lw=0.6, alpha=0.5, label="centerline")
# mark start/finish region (station 0)
ax1.scatter([center[0, 0]], [center[0, 1]], c="black", s=120, marker="*", zorder=5, label="start/finish")
for s in sf_band:
    ax1.plot([left[s, 0], right[s, 0]], [left[s, 1], right[s, 1]], "-", color="orange", lw=0.5, alpha=0.6)
ax1.set_aspect("equal"); ax1.legend(); ax1.set_title("Corridor (Strategy A) - walls + start/finish")

# panel b: optimized line colored by speed
pts = line_s.reshape(-1, 1, 2)
segs_lc = np.concatenate([pts[:-1], pts[1:]], axis=1)
lc = LineCollection(segs_lc, cmap="viridis", array=v[:-1] * 3.6, linewidths=3)
ax2.add_collection(lc)
ax2.plot(line_s[:, 0], line_s[:, 1], color="gray", lw=0.3, alpha=0.3)
ax2.autoscale()
ax2.set_aspect("equal")
cb = fig.colorbar(lc, ax=ax2)
cb.set_label("target speed (km/h)")
ax2.set_title(f"Optimized line  lap={lap_time:.1f}s  top={top_speed_kmh:.0f}km/h")

plt.tight_layout()
plt.savefig(PNG_PATH, dpi=110)
print("saved PNG:", PNG_PATH)

# --------------------------------------------------------------------------- #
# 10. Save npz
# --------------------------------------------------------------------------- #
np.savez(NPZ_PATH, left=left, right=right, line=line_s, speed=v)
print("saved NPZ:", NPZ_PATH)

print("\n=== SUMMARY ===")
print(f"width_mean={width_mean:.2f} min={width_min:.2f} max={width_max:.2f}")
print(f"lap_time={lap_time:.2f} top_speed={top_speed_kmh:.1f} seam_ok={seam_ok and sf_ok}")
