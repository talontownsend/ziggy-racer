#!/usr/bin/env python3
"""Build a behavioral-cloning dataset from human telemetry recordings.

Target = the human's control (steer/accel/brake). Features = car state + the track-boundary
PREVIEW (track_features.boundary_preview) so the net learns ANTICIPATORY control as a function of
what the track does ahead. Frames are localized onto the plan to get i0 (for preview + cte), and
weighted toward the FAST clean laps so the net imitates the quick driving, not the out-laps.

Recording cols: timestamp_ms,is_race_on,lap_no,cur_lap_time,cur_race_time,dist_traveled,
  pos_x,pos_y,pos_z,speed_mps,yaw,pitch,roll,vel_x,vel_y,vel_z,angvel_x,angvel_y,angvel_z,
  rpm,gear,accel,brake,steer
"""
import csv, math, os, sys
import numpy as np
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from track_features import boundary_preview, cumlen, DISTS, sft_features

BASE = r"C:\Users\talon\FH6-AFK-Farm\recordings"
RECS = [os.path.join(BASE, "session_20260621_093038.csv")]   # smooth session = clean BC fit (the v1 default)
OUT = os.path.join(BASE, "bc_dataset.npz")
YAW_SIGN, YAW_OFFSET = -1.0, 1.586     # match follow.py (world heading = yaw_sign*yaw + yaw_offset)
LAP_LO, LAP_HI = 25.0, 31.0            # keep clean fast laps (the runs go down to 26.1 s)
BEST_REF = 26.0                        # global weight reference (~the fastest human lap)
TAU = 1.5                              # weight = exp(-(lap-BEST_REF)/TAU): faster laps weigh more

d = np.load(os.path.join(BASE, "refline_plan.npz"))
line, left, right = d["line"], d["left"], d["right"]
clen = cumlen(line); n = len(line)

STATE_NAMES = ["speed", "vel_x", "vel_y", "vel_z", "angvel_x", "angvel_y", "angvel_z",
               "pitch", "roll", "rpm_frac", "gear"]   # plan-line cte/heading_err DROPPED (line-invariant)
PREV_NAMES = [f"{nm}{int(dd)}_{ax}" for dd in DISTS for nm in ("L", "R", "C") for ax in ("fwd", "lat")]
FEAT_NAMES = STATE_NAMES + PREV_NAMES


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def localize(px, pz, prev):
    """Windowed nearest-station search (monotonic), with global fallback on a big jump."""
    if prev is None:
        i = int(np.argmin((line[:, 0] - px) ** 2 + (line[:, 1] - pz) ** 2)); return i
    win = (prev + np.arange(-3, 26)) % n
    dd = (line[win, 0] - px) ** 2 + (line[win, 1] - pz) ** 2
    i = int(win[int(np.argmin(dd))])
    # if the windowed best is far, the car teleported/we lost track -> global
    if (line[i, 0] - px) ** 2 + (line[i, 1] - pz) ** 2 > 100.0:
        i = int(np.argmin((line[:, 0] - px) ** 2 + (line[:, 1] - pz) ** 2))
    return i


X, Y, W, LAPSRC = [], [], [], []
for rec in RECS:
    rows = list(csv.reader(open(rec)))
    hdr = rows[0]; ix = {nm: k for k, nm in enumerate(hdr)}
    data = rows[1:]
    # lap times per row (cur_lap_time resets at lap end)
    clt = np.array([float(r[ix["cur_lap_time"]]) for r in data])
    laptime = np.full(len(data), 999.0)            # the COMPLETED time of the lap each row belongs to
    starts = [0]
    for i in range(1, len(clt)):
        if clt[i] < clt[i - 1] - 5:
            t = clt[i - 1]
            for j in range(starts[-1], i): laptime[j] = t
            starts.append(i)
    best = laptime[(laptime > LAP_LO) & (laptime < LAP_HI)].min()
    prev = None; kept = 0
    for r, lt in zip(data, laptime):
        px, pz = float(r[ix["pos_x"]]), float(r[ix["pos_z"]])
        i0 = localize(px, pz, prev); prev = i0       # localize EVERY frame (keeps prev continuous)
        if not (LAP_LO < lt < LAP_HI):               # only clean fast laps enter the dataset
            continue
        heading = wrap(YAW_SIGN * float(r[ix["yaw"]]) + YAW_OFFSET)
        # cte + heading_err at i0
        tx, tz = line[(i0 + 1) % n] - line[i0]
        ttheta = math.atan2(tz, tx); tnorm = math.hypot(tx, tz) + 1e-9
        vx, vz = px - line[i0, 0], pz - line[i0, 1]
        cte = (tx * vz - tz * vx) / tnorm
        heading_err = wrap(ttheta - heading)
        if abs(cte) > 25.0 or abs(heading_err) > 1.5:   # drop only glitch / badly-mislocalized frames
            continue
        rpm = float(r[ix["rpm"]])
        X.append(sft_features(
            float(r[ix["speed_mps"]]), float(r[ix["vel_x"]]), float(r[ix["vel_y"]]), float(r[ix["vel_z"]]),
            float(r[ix["angvel_x"]]), float(r[ix["angvel_y"]]), float(r[ix["angvel_z"]]),
            float(r[ix["pitch"]]), float(r[ix["roll"]]), rpm, float(r[ix["gear"]]),
            px, pz, heading, i0, line, left, right, clen))
        Y.append([float(r[ix["steer"]]) / 127.0, float(r[ix["accel"]]) / 255.0, float(r[ix["brake"]]) / 255.0])
        W.append(math.exp(-(lt - BEST_REF) / TAU))
        kept += 1
    print(f"{os.path.basename(rec)}: kept {kept} frames (best lap {best:.2f}s)")

X = np.array(X, np.float32); Y = np.array(Y, np.float32); W = np.array(W, np.float32)
mean = X.mean(0); std = X.std(0) + 1e-6
np.savez(OUT, X=X, Y=Y, W=W, mean=mean, std=std, feat_names=np.array(FEAT_NAMES))
print(f"\nsaved {OUT}: X{X.shape} Y{Y.shape}  ({len(FEAT_NAMES)} features)")
print(f"weight range {W.min():.3f}..{W.max():.3f}  (fast laps ~1.0)")
print(f"target ranges: steer [{Y[:,0].min():.2f},{Y[:,0].max():.2f}] thr [{Y[:,1].min():.2f},{Y[:,1].max():.2f}] brk [{Y[:,2].min():.2f},{Y[:,2].max():.2f}]")
print(f"cte range [{X[:,11].min():.1f},{X[:,11].max():.1f}]m  heading_err [{X[:,12].min():.2f},{X[:,12].max():.2f}]rad")
