#!/usr/bin/env python3
"""BC dataset v2 (07-13): FAST-RUN recordings against the CURRENT refline_plan.npz.

Differences from build_bc_dataset.py (v1, which used only the smooth 28.3-30.7s session and
the old v1 line -- the deployed policy cloned slow driving on stale geometry):
  - RECS = the fast runs (31 laps best 26.10 + 13 laps best 26.31): the data that actually
    contains the S6/S7 full-lock commitment the blend targets.
  - consecutive-duplicate dedupe (~38-52% of rows repeat cur_lap_time -> double-weighted instants).
  - saves lap_id per frame so training can do a LAP-level held-out split (the v1 random frame
    split leaks adjacent 71-103Hz frames between train/val).
  - writes bc_dataset_v2fast.npz (does NOT overwrite bc_dataset.npz -- provenance lesson).
"""
import csv, math, os, sys
import numpy as np
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from track_features import boundary_preview, cumlen, DISTS, sft_features

BASE = r"C:\Users\talon\FH6-AFK-Farm\recordings"
RECS = [os.path.join(BASE, "run_20260625_120907.csv"),
        os.path.join(BASE, "run_20260625_120122.csv")]
OUT = os.path.join(BASE, "bc_dataset_v2fast.npz")
YAW_SIGN, YAW_OFFSET = -1.0, 1.586
LAP_LO, LAP_HI = 25.0, 31.0
BEST_REF = 26.0
TAU = 1.5

d = np.load(os.path.join(BASE, "refline_plan.npz"))
line, left, right = d["line"], d["left"], d["right"]
clen = cumlen(line); n = len(line)

STATE_NAMES = ["speed", "vel_x", "vel_y", "vel_z", "angvel_x", "angvel_y", "angvel_z",
               "pitch", "roll", "rpm_frac", "gear"]
PREV_NAMES = [f"{nm}{int(dd)}_{ax}" for dd in DISTS for nm in ("L", "R", "C") for ax in ("fwd", "lat")]
FEAT_NAMES = STATE_NAMES + PREV_NAMES


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def localize(px, pz, prev):
    if prev is None:
        return int(np.argmin((line[:, 0] - px) ** 2 + (line[:, 1] - pz) ** 2))
    win = (prev + np.arange(-3, 26)) % n
    dd = (line[win, 0] - px) ** 2 + (line[win, 1] - pz) ** 2
    i = int(win[int(np.argmin(dd))])
    if (line[i, 0] - px) ** 2 + (line[i, 1] - pz) ** 2 > 100.0:
        i = int(np.argmin((line[:, 0] - px) ** 2 + (line[:, 1] - pz) ** 2))
    return i


X, Y, W, LAP = [], [], [], []
lap_uid = 0
for ri, rec in enumerate(RECS):
    rows = list(csv.reader(open(rec)))
    hdr = rows[0]; ix = {nm: k for k, nm in enumerate(hdr)}
    data = rows[1:]
    clt = np.array([float(r[ix["cur_lap_time"]]) for r in data])
    laptime = np.full(len(data), 999.0)
    lapidx = np.full(len(data), -1, dtype=int)
    starts = [0]
    for i in range(1, len(clt)):
        if clt[i] < clt[i - 1] - 5:
            t = clt[i - 1]
            for j in range(starts[-1], i):
                laptime[j] = t; lapidx[j] = lap_uid
            starts.append(i); lap_uid += 1
    best = laptime[(laptime > LAP_LO) & (laptime < LAP_HI)].min()
    prev = None; kept = 0; dup = 0; last_clt = None
    for k, (r, lt) in enumerate(zip(data, laptime)):
        px, pz = float(r[ix["pos_x"]]), float(r[ix["pos_z"]])
        i0 = localize(px, pz, prev); prev = i0
        if not (LAP_LO < lt < LAP_HI):
            continue
        # dedupe: identical cur_lap_time = repeated telemetry frame (no new content)
        if last_clt is not None and clt[k] == last_clt:
            dup += 1; continue
        last_clt = clt[k]
        heading = wrap(YAW_SIGN * float(r[ix["yaw"]]) + YAW_OFFSET)
        tx, tz = line[(i0 + 1) % n] - line[i0]
        ttheta = math.atan2(tz, tx); tnorm = math.hypot(tx, tz) + 1e-9
        vx, vz = px - line[i0, 0], pz - line[i0, 1]
        cte = (tx * vz - tz * vx) / tnorm
        heading_err = wrap(ttheta - heading)
        if abs(cte) > 25.0 or abs(heading_err) > 1.5:
            continue
        rpm = float(r[ix["rpm"]])
        X.append(sft_features(
            float(r[ix["speed_mps"]]), float(r[ix["vel_x"]]), float(r[ix["vel_y"]]), float(r[ix["vel_z"]]),
            float(r[ix["angvel_x"]]), float(r[ix["angvel_y"]]), float(r[ix["angvel_z"]]),
            float(r[ix["pitch"]]), float(r[ix["roll"]]), rpm, float(r[ix["gear"]]),
            px, pz, heading, i0, line, left, right, clen))
        Y.append([float(r[ix["steer"]]) / 127.0, float(r[ix["accel"]]) / 255.0, float(r[ix["brake"]]) / 255.0])
        W.append(math.exp(-(lt - BEST_REF) / TAU))
        LAP.append(lapidx[k])
        kept += 1
    print(f"{os.path.basename(rec)}: kept {kept} frames ({dup} dups dropped, best lap {best:.2f}s)")

X = np.array(X, np.float32); Y = np.array(Y, np.float32); W = np.array(W, np.float32)
LAP = np.array(LAP, np.int32)
mean = X.mean(0); std = X.std(0) + 1e-6
np.savez(OUT, X=X, Y=Y, W=W, lap_id=LAP, mean=mean, std=std, feat_names=np.array(FEAT_NAMES))
u = np.unique(LAP)
print(f"\nsaved {OUT}: X{X.shape}  {len(u)} laps")
print(f"steer: {100*np.mean(np.abs(Y[:,0])>=0.99):.1f}% at full lock | weights {W.min():.3f}..{W.max():.3f}")
