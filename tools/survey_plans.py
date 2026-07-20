"""Generate SURVEY plans: the racing line shifted laterally by fixed offsets, clamped
to the corridor with margin, at gentle survey speeds. Driving each of these and logging
y/pitch/roll builds the 2D surface sheet y(s, d) that both the controller's surface
physics and the future line optimizer consume. Track-agnostic procedure.
Outputs recordings/survey/plan_off_{d:+d}.npz for d in -4..+4 m.
"""
import os
import numpy as np

REC = r"C:\Users\talon\FH6-AFK-Farm\recordings"
OUT = os.path.join(REC, "survey")
os.makedirs(OUT, exist_ok=True)

d = np.load(os.path.join(REC, "refline_plan.npz"))
line, vplan, left, right = d["line"], d["speed"], d["left"], d["right"]
elev, grade = d["elev"], d["grade"]
n = len(line)


def smooth_closed(a, w):
    out = a.copy()
    for _ in range(w):
        out = (np.roll(out, 1) + out + np.roll(out, -1)) / 3.0
    return out


tang = (np.roll(line, -1, 0) - np.roll(line, 1, 0))
tang /= np.linalg.norm(tang, axis=1, keepdims=True)
nrm = np.stack([-tang[:, 1], tang[:, 0]], axis=1)          # left normal
distL = np.hypot(*(left - line).T)                          # room toward left edge
distR = np.hypot(*(right - line).T)                         # room toward right edge
MARGIN = 1.2
SURVEY_V = 22.0        # m/s (~80 km/h) target on open track
SURVEY_ALAT = 12.0     # m/s^2 gentle cornering budget for survey speeds


def kappa_closed(pts):
    a3, b3, c3 = np.roll(pts, 1, 0), pts, np.roll(pts, -1, 0)
    cross = (b3 - a3)[:, 0] * (c3 - b3)[:, 1] - (b3 - a3)[:, 1] * (c3 - b3)[:, 0]
    la, lb, lc = (np.linalg.norm(v, axis=1) for v in ((b3 - a3), (c3 - b3), (c3 - a3)))
    k = np.abs(2.0 * cross / np.maximum(la * lb * lc, 1e-9))
    return smooth_closed(k, 3)


for off_target in range(-4, 5):
    off = np.full(n, float(off_target))
    hi = distL - MARGIN
    lo = -(distR - MARGIN)
    for _ in range(4):
        off = np.clip(off, lo, hi)
        off = smooth_closed(off, 7)
    off = np.clip(off, lo, hi)
    pts = line + off[:, None] * nrm
    kap = kappa_closed(pts)
    v = np.minimum(SURVEY_V, np.sqrt(SURVEY_ALAT / np.maximum(kap, 1e-4)))
    v = np.maximum(smooth_closed(v, 5), 7.0)
    # brake-cone the speed profile so tv anticipation gets a feasible ramp
    out_v = v.copy()
    seg = np.hypot(*(np.roll(pts, -1, 0) - pts).T)
    for i in range(n):
        dd, j = 0.0, i
        while dd < 120.0:
            ok = np.sqrt(v[j] ** 2 + 2.0 * 10.0 * dd)
            if ok < out_v[i]:
                out_v[i] = ok
            dd += seg[j]; j = (j + 1) % n
    path = os.path.join(OUT, f"plan_off_{off_target:+d}.npz")
    np.savez(path, line=pts, speed=out_v, left=left, right=right, elev=elev, grade=grade)
    clearL = distL - off
    clearR = distR + off
    print(f"d={off_target:+d}: |off| applied med {np.median(np.abs(off)):.1f} m, "
          f"min clear {min(clearL.min(), clearR.min()):.2f} m, "
          f"v {out_v.min()*3.6:.0f}-{out_v.max()*3.6:.0f} km/h, max kappa {kap.max():.3f}")
