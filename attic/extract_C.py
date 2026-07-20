#!/usr/bin/env python3
"""
STRATEGY C - Monotonic frame-projection onto a hot-lap centerline + percentile
walls, seam origin rotated onto the longest straight.

Pipeline:
  1. Clean + split telemetry into BOUNDARY phase (2 slow edge laps) and HOT laps.
  2. Build a smooth, closed centerline by averaging several complete hot laps
     (phase-aligned by arc length).
  3. Rotate the centerline's station origin onto the midpoint of the longest
     straight (lowest-curvature run) so the start/finish seam is NOT at the
     station boundary.
  4. For each boundary edge lap, reject backward/turnaround frames
     (velocity . local-centerline-tangent < 0).
  5. Assign each remaining frame to a centerline station with an ORDER-PRESERVING
     (monotonic) projection: the assigned station may only advance forward within
     a small look-ahead window as the lap progresses in time. This prevents a
     frame on one side of the pinch from snapping to the far side.
  6. Signed lateral offset per frame. Per station: left wall = ~85th percentile,
     right wall = ~15th percentile of offsets.
  7. Fill empty stations by circular interpolation, smooth, enforce non-crossing.
  8. Run the PROVIDED optimizer; smooth the line; report metrics.
"""
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
import racing_line as rl

CSV = r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038.csv"
PNG = r"C:\Users\talon\FH6-AFK-Farm\recordings\corridorC.png"
NPZ = r"C:\Users\talon\FH6-AFK-Farm\recordings\planC.npz"
N = 400
VEHICLE = {"a_lat": 8.0, "a_acc": 11.2, "a_brake": 13.7, "v_max": 67.2}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def closed_smooth(arr, w):
    """Circular moving-average smoothing of an (n,...) array along axis 0."""
    arr = np.asarray(arr, float)
    n = len(arr)
    if w <= 1:
        return arr.copy()
    k = np.ones(w) / w
    pad = w
    if arr.ndim == 1:
        ext = np.concatenate([arr[-pad:], arr, arr[:pad]])
        sm = np.convolve(ext, k, mode="same")
        return sm[pad:pad + n]
    out = np.empty_like(arr)
    for d in range(arr.shape[1]):
        ext = np.concatenate([arr[-pad:, d], arr[:, d], arr[:pad, d]])
        sm = np.convolve(ext, k, mode="same")
        out[:, d] = sm[pad:pad + n]
    return out


def circ_fill(values, valid):
    """Circular interpolation of empty stations. values:(n,), valid:bool(n,)."""
    n = len(values)
    out = values.copy()
    idx = np.where(valid)[0]
    if len(idx) == 0:
        return out
    # extend periodically: stations + n on both ends
    xs = np.concatenate([idx - n, idx, idx + n])
    ys = np.concatenate([values[idx], values[idx], values[idx]])
    all_st = np.arange(n)
    out = np.interp(all_st, xs, ys)
    return out


# --------------------------------------------------------------------------- #
# 1. load + clean + split
# --------------------------------------------------------------------------- #
df = pd.read_csv(CSV)
spd_kmh = df["speed_mps"].values * 3.6
moving = (spd_kmh > 3) & ~((df["pos_x"].values == 0) & (df["pos_z"].values == 0))
mv = df[moving].reset_index(drop=True)

sk = mv["speed_mps"].values * 3.6
k = None
for i in range(len(sk) - 200):
    if np.median(sk[i:i + 200]) > 120:
        k = i
        break
print(f"boundary/hot split k = {k}")

bnd = mv.iloc[:k].reset_index(drop=True)
hot = mv.iloc[k:].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 2. centerline from averaged hot laps
# --------------------------------------------------------------------------- #
clt = hot["cur_lap_time"].values
resets = np.where(np.diff(clt) < -5)[0]
seg_bnds = [0] + list(resets + 1) + [len(hot)]
laps = []
for i in range(len(seg_bnds) - 1):
    a, b = seg_bnds[i], seg_bnds[i + 1]
    dur = clt[b - 1] - clt[a]
    # complete hot lap: starts near 0, lasts ~25-32 s, sane length
    if clt[a] < 1.0 and 24.0 < dur < 33.0 and (b - a) > 1500:
        laps.append((a, b))
print(f"complete hot laps used for centerline: {laps}")

# Resample each complete hot lap to N closed points, then average.
# Phase-align: rotate each lap so its point 0 is nearest a common anchor.
anchor = None
resampled = []
for (a, b) in laps:
    pts = np.column_stack([hot["pos_x"].values[a:b], hot["pos_z"].values[a:b]])
    c = rl.resample_closed(pts, N)
    if anchor is None:
        anchor = c[0].copy()
    # rotate to align point 0 with anchor
    j = int(np.argmin(np.linalg.norm(c - anchor, axis=1)))
    c = np.roll(c, -j, axis=0)
    # ensure same travel direction as first lap (check cross of mean tangent)
    resampled.append(c)

resampled = np.array(resampled)  # (L, N, 2)
# Direction-consistency: align each lap's traversal direction to lap0.
ref = resampled[0]
ref_tan = np.roll(ref, -1, axis=0) - ref
for li in range(1, len(resampled)):
    c = resampled[li]
    tan = np.roll(c, -1, axis=0) - c
    if np.sum(tan * ref_tan) < 0:  # reversed
        c = c[::-1]
        j = int(np.argmin(np.linalg.norm(c - anchor, axis=1)))
        c = np.roll(c, -j, axis=0)
        resampled[li] = c

centerline = resampled.mean(axis=0)
centerline = closed_smooth(centerline, 9)
centerline = rl.resample_closed(centerline, N)


# --------------------------------------------------------------------------- #
# 3. rotate station origin onto the longest straight
# --------------------------------------------------------------------------- #
kap = rl.menger_curvature(centerline)
kap_sm = closed_smooth(kap, 15)
# longest straight = the window of consecutive low-curvature stations with the
# smallest summed curvature. Scan a fixed window and pick its center.
win = N // 8
best_i, best_val = 0, np.inf
ext = np.concatenate([kap_sm, kap_sm])
for i in range(N):
    val = ext[i:i + win].sum()
    if val < best_val:
        best_val = val
        best_i = i
origin = (best_i + win // 2) % N
centerline = np.roll(centerline, -origin, axis=0)
print(f"rotated station origin by {origin} (longest-straight midpoint)")

# centerline tangents & left normals
tang = np.roll(centerline, -1, axis=0) - np.roll(centerline, 1, axis=0)
tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
nrm = np.column_stack([-tang[:, 1], tang[:, 0]])  # left normal


# --------------------------------------------------------------------------- #
# 4 + 5. per edge lap: reject turnaround, monotonic projection -> offsets
# --------------------------------------------------------------------------- #
def nearest_station(pt):
    return int(np.argmin(np.linalg.norm(centerline - pt, axis=1)))


def project_lap(px, pz, vx, vz, look=12):
    """Monotonic forward projection of a lap's frames onto centerline stations.
    Returns list of (station, signed_offset). Backward frames rejected."""
    n = len(px)
    out = []
    # seed: nearest station to the first accepted frame
    cur = None
    for i in range(n):
        p = np.array([px[i], pz[i]])
        v = np.array([vx[i], vz[i]])
        if cur is None:
            cur = nearest_station(p)
        # reject backward/turnaround: velocity . local tangent < 0
        if np.dot(v, tang[cur]) < 0:
            continue
        # search forward window [cur .. cur+look] (circular) for best station
        best_st, best_d = cur, np.inf
        for off in range(0, look + 1):
            st = (cur + off) % N
            d = np.linalg.norm(centerline[st] - p)
            if d < best_d:
                best_d = d
                best_st = st
        # only advance forward
        cur = best_st
        # signed lateral offset along left normal
        rel = p - centerline[best_st]
        signed = float(np.dot(rel, nrm[best_st]))
        out.append((best_st, signed))
    return out


cltb = bnd["cur_lap_time"].values
resb = np.where(np.diff(cltb) < -5)[0]
edge_bnds = [0] + list(resb + 1) + [len(bnd)]
print(f"boundary edge-lap boundaries: {edge_bnds}")

# Collect offsets per station from ALL boundary frames (both edge laps + tail),
# each processed monotonically and direction-filtered. Left wall comes from the
# left-hugging lap, right wall from the right-hugging lap, but since we use
# percentiles over the combined offsets this naturally separates them.
station_offsets = [[] for _ in range(N)]
for ei in range(len(edge_bnds) - 1):
    a, b = edge_bnds[ei], edge_bnds[ei + 1]
    if (b - a) < 100:
        continue
    px = bnd["pos_x"].values[a:b]
    pz = bnd["pos_z"].values[a:b]
    vx = bnd["vel_x"].values[a:b]
    vz = bnd["vel_z"].values[a:b]
    proj = project_lap(px, pz, vx, vz)
    for (st, off) in proj:
        station_offsets[st].append(off)


# --------------------------------------------------------------------------- #
# 6. percentile walls
# --------------------------------------------------------------------------- #
left_off = np.full(N, np.nan)
right_off = np.full(N, np.nan)
for st in range(N):
    offs = station_offsets[st]
    if len(offs) >= 1:
        offs = np.array(offs)
        left_off[st] = np.percentile(offs, 85)
        right_off[st] = np.percentile(offs, 15)

valid = ~np.isnan(left_off)
print(f"stations with data: {valid.sum()} / {N}")

# 7. fill empties (circular interp) + smooth
left_off = circ_fill(np.nan_to_num(left_off, nan=0.0), valid)
right_off = circ_fill(np.nan_to_num(right_off, nan=0.0), valid)
left_off = closed_smooth(left_off, 11)
right_off = closed_smooth(right_off, 11)

# enforce a minimum half-width and non-crossing (left offset > right offset)
MIN_HALF = 3.0
mid = 0.5 * (left_off + right_off)
half = 0.5 * (left_off - right_off)
half = np.maximum(half, MIN_HALF)
left_off = mid + half
right_off = mid - half

left = centerline + left_off[:, None] * nrm
right = centerline + right_off[:, None] * nrm

# resample walls to clean uniform arc length
left = rl.resample_closed(left, N)
right = rl.resample_closed(right, N)


# --------------------------------------------------------------------------- #
# VALIDATION: non-crossing through start/finish (station 0)
# --------------------------------------------------------------------------- #
# project each wall onto the centerline normal at matched station; verify
# left offset stays strictly > right offset everywhere.
cen2 = 0.5 * (left + right)
t2 = np.roll(cen2, -1, axis=0) - np.roll(cen2, 1, axis=0)
t2 /= np.maximum(np.linalg.norm(t2, axis=1, keepdims=True), 1e-9)
n2 = np.column_stack([-t2[:, 1], t2[:, 0]])
lo = np.sum((left - cen2) * n2, axis=1)
ro = np.sum((right - cen2) * n2, axis=1)
gap = lo - ro
seam_ok = bool(np.all(gap > 0.05))
# explicit check within +/-20 stations of start/finish
seam_window = np.concatenate([np.arange(N - 20, N), np.arange(0, 21)])
seam_ok_local = bool(np.all(gap[seam_window % N] > 0.05))
print(f"non-crossing gap min = {gap.min():.3f} m  seam_ok={seam_ok} "
      f"seam_local_ok={seam_ok_local}")

widths = np.abs(lo - ro)
print(f"width mean/min/max = {widths.mean():.2f}/{widths.min():.2f}/{widths.max():.2f}")


# --------------------------------------------------------------------------- #
# 8. run provided optimizer + metrics
# --------------------------------------------------------------------------- #
plan = rl.plan_racing_line(left, right, VEHICLE, n=N)
line = plan["line"]

# smooth optimized line (closed moving average window 9) before velocity profile
line_sm = closed_smooth(line, 9)
line_sm = rl.resample_closed(line_sm, N)
v, kappa, ds = rl.velocity_profile(line_sm, VEHICLE["a_lat"], VEHICLE["a_acc"],
                                   VEHICLE["a_brake"], VEHICLE["v_max"])
lap_time = float(np.sum(ds / np.maximum(v, 0.5)))
top_speed_kmh = float(v.max() * 3.6)
print(f"lap_time = {lap_time:.3f} s   top_speed = {top_speed_kmh:.1f} km/h")
print(f"lap_distance = {ds.sum():.1f} m")


# --------------------------------------------------------------------------- #
# PNG: 2 panels
# --------------------------------------------------------------------------- #
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))

ax1.plot(np.append(left[:, 0], left[0, 0]), np.append(left[:, 1], left[0, 1]),
         "b-", lw=1.5, label="left wall")
ax1.plot(np.append(right[:, 0], right[0, 0]), np.append(right[:, 1], right[0, 1]),
         "r-", lw=1.5, label="right wall")
# start/finish region (station 0 +/- 15)
sf = np.concatenate([np.arange(N - 15, N), np.arange(0, 16)]) % N
ax1.plot(left[sf, 0], left[sf, 1], "c-", lw=3, alpha=0.7)
ax1.plot(right[sf, 0], right[sf, 1], "m-", lw=3, alpha=0.7)
ax1.scatter([cen2[0, 0]], [cen2[0, 1]], c="k", s=80, zorder=5,
            marker="*", label="start/finish")
ax1.set_aspect("equal")
ax1.legend(loc="best")
ax1.set_title(f"Strategy C corridor (walls)\nwidth {widths.mean():.1f} m "
              f"[{widths.min():.1f}-{widths.max():.1f}]  seam_ok={seam_ok}")
ax1.set_xlabel("pos_x (m)")
ax1.set_ylabel("pos_z (m)")

# panel 2: optimized line colored by speed
seg_pts = np.column_stack([line_sm[:, 0], line_sm[:, 1]])
segs = np.stack([seg_pts, np.roll(seg_pts, -1, axis=0)], axis=1)
lc = LineCollection(segs, cmap="viridis", array=v[:-0 or None] * 3.6, lw=3)
lc.set_array(v * 3.6)
ax2.add_collection(lc)
ax2.plot(left[:, 0], left[:, 1], "k-", lw=0.5, alpha=0.3)
ax2.plot(right[:, 0], right[:, 1], "k-", lw=0.5, alpha=0.3)
ax2.set_xlim(line_sm[:, 0].min() - 20, line_sm[:, 0].max() + 20)
ax2.set_ylim(line_sm[:, 1].min() - 20, line_sm[:, 1].max() + 20)
ax2.set_aspect("equal")
cb = fig.colorbar(lc, ax=ax2)
cb.set_label("target speed (km/h)")
ax2.set_title(f"Optimized line  lap {lap_time:.2f}s  top {top_speed_kmh:.0f} km/h")
ax2.set_xlabel("pos_x (m)")
ax2.set_ylabel("pos_z (m)")

plt.tight_layout()
plt.savefig(PNG, dpi=110)
print(f"saved PNG -> {PNG}")

np.savez(NPZ, left=left, right=right, line=line_sm, speed=v)
print(f"saved NPZ -> {NPZ}")

# emit machine-readable summary
print("RESULT", {
    "width_mean": float(widths.mean()),
    "width_min": float(widths.min()),
    "width_max": float(widths.max()),
    "lap_time_s": lap_time,
    "top_speed_kmh": top_speed_kmh,
    "seam_ok": seam_ok and seam_ok_local,
    "gap_min": float(gap.min()),
})
