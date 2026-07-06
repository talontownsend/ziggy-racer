"""Isolate WHERE the line stops apexing.

Replicates build_corridor's inset corridor from the saved walls, then compares,
stage by stage, where the line sits vs the corner direction (from the CENTERLINE
curvature, the reliable signal):

  stage            apex_score   (fraction of corner stations on the INSIDE half)
  - centerline      (0.5 by def)
  - min_curvature   warm start
  - min_time_line   full solver output
  - shipped line    (plan['line'], = solver + resample + smooth7)

apex_score = 1.0 => perfectly apexing (inside at every corner)
            ~0.5 => mid corridor
             0.0 => hugging the OUTSIDE at every corner   <-- the bug
"""
import glob
import numpy as np
from racing_line import (resample_closed, min_curvature_line, menger_curvature,
                         segment_lengths)


# (smooth_closed lives in build_corridor; redefine locally)
def smooth_closed(a, w=7):
    k = np.ones(w) / w
    if a.ndim == 1:
        return np.convolve(np.r_[a[-w:], a, a[:w]], k, "same")[w:-w]
    return np.column_stack([smooth_closed(a[:, 0], w), smooth_closed(a[:, 1], w)])

from mlt_line import min_time_line

PLAN = sorted(glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\*_plan.npz"))[-1]
p = np.load(PLAN)
left, right, shipped = p["left"], p["right"], p["line"]
N = len(left)

# --- replicate inset corridor (build_corridor lines 184-193) ---
cen = 0.5 * (left + right)
half = 0.5 * np.linalg.norm(left - right, axis=1)
kcen = smooth_closed(menger_curvature(cen), 5)
extra = np.clip((kcen - 1.0 / 25.0) * 40.0, 0.0, 1.5)
MARGIN = 1.1 + extra
inset = np.minimum(MARGIN, np.maximum(half - 0.75, 0.0))[:, None]
ul = cen - left;  ul /= np.maximum(np.linalg.norm(ul, axis=1, keepdims=True), 1e-9)
ur = cen - right; ur /= np.maximum(np.linalg.norm(ur, axis=1, keepdims=True), 1e-9)
iL = left + inset * ul
iR = right + inset * ur

# --- centerline corner direction (signed) on the INSET corridor ---
icen = 0.5 * (iL + iR)
tang = np.roll(icen, -1, 0) - np.roll(icen, 1, 0)
tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
nrm = np.column_stack([-tang[:, 1], tang[:, 0]])           # left normal
ds = segment_lengths(icen)
heading = np.arctan2(tang[:, 1], tang[:, 0])
dtheta = np.angle(np.exp(1j * (np.roll(heading, -1) - heading)))
kref = dtheta / np.maximum(ds, 1e-6)                        # + = left turn
amax = np.sum((iL - icen) * nrm, axis=1)                    # offset to LEFT wall (inside of left turn)
amin = np.sum((iR - icen) * nrm, axis=1)                    # offset to RIGHT wall

corner = np.abs(kref) > 1.0 / 60.0                          # tighter than R60 = a corner
print(f"plan={PLAN}  N={N}  corner stations: {corner.sum()}")


def alpha_of(line):
    return np.sum((line - icen) * nrm, axis=1)


def apex_score(line, label):
    a = alpha_of(line)
    # inside offset target: +amax for left turns, +amin (negative) for right turns
    inside = np.where(kref > 0, amax, amin)
    outside = np.where(kref > 0, amin, amax)
    # fraction of corridor from outside(0) -> inside(1)
    frac = (a - outside) / (inside - outside + np.sign(inside - outside) * 1e-9)
    frac = np.clip(frac, -0.2, 1.2)
    sc = frac[corner].mean()
    print(f"  {label:16s} apex_score={sc:+.2f}   median frac={np.median(frac[corner]):+.2f}")
    return frac


# warm start
lw, aw = min_curvature_line(iL, iR)
# full solver
plan = min_time_line(iL, iR, dict(a_lat=2.3*9.81, a_lat_k=0.0, a_acc=11.0, a_brake=17.0,
                                  v_max=70.0), n=N, clear=0.02, safety=0.0)
lm = plan["line"]
ship_resampled = shipped   # already resample+smooth7 in build_corridor

print("apex_score: 1.0 = inside/apex at every corner, 0.0 = outside-hug (bug)")
apex_score(icen, "centerline")
apex_score(lw, "min_curvature")
apex_score(lm, "min_time_line")
apex_score(ship_resampled, "shipped line")
