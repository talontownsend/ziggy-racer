#!/usr/bin/env python3
"""Refined: measure line position WITHIN the local track cross-section.

The raw point-to-point distance line<->wall is misleading when the nearest wall
vertex isn't on the local cross-section normal. Instead, for each corner apex we
build the local track normal from the centerline and project the line and both
walls onto it, so positions are 1-D along the cross-section.
"""
import numpy as np
from racing_line import menger_curvature

PLAN = r"C:/Users/talon/FH6-AFK-Farm/recordings/session_20260621_093038_plan.npz"
d = np.load(PLAN)
line = d["line"].astype(float)
left = d["left"].astype(float)
right = d["right"].astype(float)
N = len(line)

center = 0.5 * (left + right)
kappa = menger_curvature(line)
radius = np.where(kappa > 1e-9, 1.0 / kappa, np.inf)

def runs(mask):
    n = len(mask)
    if mask.all():
        return [(0, n - 1)]
    if not mask.any():
        return []
    idx = np.where(mask)[0]
    out = []
    start = prev = idx[0]
    for k in idx[1:]:
        if k == prev + 1:
            prev = k
        else:
            out.append((start, prev)); start = prev = k
    out.append((start, prev))
    if len(out) >= 2 and out[0][0] == 0 and out[-1][1] == n - 1:
        s_last, _ = out[-1]; _, e_first = out[0]
        out = out[1:-1] + [(s_last, e_first)]
    return out

def run_idx(s, e, n):
    return np.arange(s, e + 1) if s <= e else np.concatenate([np.arange(s, n), np.arange(0, e + 1)])

# local centerline tangent / normal at each station
tang = np.roll(center, -1, axis=0) - np.roll(center, 1, axis=0)
tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
nL = np.column_stack([-tang[:, 1], tang[:, 0]])   # left normal

# signed offset of each entity from centerline along left-normal (meters)
def offset(P):
    return np.sum((P - center) * nL, axis=1)

off_line = offset(line)
off_left = offset(left)
off_right = offset(right)
# corridor half-width along the normal
print("Cross-section sanity (offsets from centerline along left-normal, m):")
print(f"  left  offset: median={np.median(off_left):+.2f}  (should be ~+half-width)")
print(f"  right offset: median={np.median(off_right):+.2f}  (should be ~-half-width)")
print(f"  width along-normal: median={np.median(off_left-off_right):.2f}")
print(f"  raw |left-right| width: median={np.median(np.linalg.norm(left-right,axis=1)):.2f}")

corner_mask = radius < 80.0
crs = [(s, e) for (s, e) in runs(corner_mask) if len(run_idx(s, e, N)) >= 3]

print("\nCORNER apex positions within the cross-section:")
results = []
for (s, e) in crs:
    ii = run_idx(s, e, N)
    apex = ii[np.argmax(kappa[ii])]
    # turn direction
    v1 = line[apex] - line[(apex-1) % N]
    v2 = line[(apex+1) % N] - line[apex]
    cross = v1[0]*v2[1] - v1[1]*v2[0]
    turn = "RIGHT" if cross < 0 else "LEFT"
    oL, oR, oLn = off_left[apex], off_right[apex], off_line[apex]
    # inner side: RIGHT turn -> inner is the more-negative-offset wall (right side)
    if turn == "RIGHT":
        inner_off = min(oL, oR)   # right wall, negative
    else:
        inner_off = max(oL, oR)   # left wall, positive
    line_to_inner = abs(oLn - inner_off)
    halfw = abs(oL - oR)
    frac = line_to_inner / halfw
    apexes = line_to_inner <= 2.5
    results.append((apex, radius[apex], halfw, turn, line_to_inner, frac, apexes))
    print(f"  apex i0={apex:3d} r={radius[apex]:5.1f}m turn={turn:5s} width={halfw:5.2f}m "
          f"line_off={oLn:+5.2f} innerwall_off={inner_off:+5.2f} -> line->inner={line_to_inner:5.2f}m "
          f"({frac*100:3.0f}%) apexes={apexes}")

# how off-corridor is the line? offset should lie between right and left offsets
inside = (off_line <= np.maximum(off_left, off_right) + 0.05) & (off_line >= np.minimum(off_left, off_right) - 0.05)
print(f"\nstations where line offset is INSIDE corridor bounds: {inside.mean()*100:.0f}%")
print(f"line offset stats: min={off_line.min():+.2f} median={np.median(off_line):+.2f} max={off_line.max():+.2f}")
