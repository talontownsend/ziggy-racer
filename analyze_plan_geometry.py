#!/usr/bin/env python3
"""Analyze the PLANNED LINE geometry (ignore the car).

Determines whether the reference line is capable of apexing corners and is
straight on straights.
"""
import numpy as np
from racing_line import menger_curvature

PLAN = r"C:/Users/talon/FH6-AFK-Farm/recordings/session_20260621_093038_plan.npz"

d = np.load(PLAN)
line = d["line"].astype(float)   # Nx2 planned racing line
left = d["left"].astype(float)   # Nx2 left wall
right = d["right"].astype(float) # Nx2 right wall
speed = d["speed"].astype(float)
N = len(line)

# arc length per station
seg = np.linalg.norm(np.roll(line, -1, axis=0) - line, axis=1)
total = seg.sum()
ds_mean = total / N
print(f"N={N} stations, total line length = {total:.1f} m, mean spacing = {ds_mean:.2f} m")

kappa = menger_curvature(line)   # 1/radius
radius = np.where(kappa > 1e-9, 1.0 / kappa, np.inf)

# track width at each station
width = np.linalg.norm(left - right, axis=1)
print(f"track width: min={width.min():.2f} mean={width.mean():.2f} max={width.max():.2f} median={np.median(width):.2f}")
print(f"radius: min={radius.min():.1f} median={np.median(radius):.1f} (corners<80m: {np.sum(radius<80)} stations, straights>200m: {np.sum(radius>200)} stations)")

# ---- helper: contiguous runs (with wraparound) over a boolean mask ----
def runs(mask):
    """Return list of (start,end) inclusive index runs where mask is True, handling wraparound."""
    n = len(mask)
    if mask.all():
        return [(0, n - 1)]
    if not mask.any():
        return []
    # find rising/falling edges
    idx = np.where(mask)[0]
    out = []
    start = idx[0]
    prev = idx[0]
    for k in idx[1:]:
        if k == prev + 1:
            prev = k
        else:
            out.append((start, prev))
            start = k
            prev = k
    out.append((start, prev))
    # wraparound merge: if first run starts at 0 and last ends at n-1, merge
    if len(out) >= 2 and out[0][0] == 0 and out[-1][1] == n - 1:
        s_last, _ = out[-1]
        _, e_first = out[0]
        out = out[1:-1] + [(s_last, e_first)]  # wrapped run stored as (start, end<start)
    return out

def run_indices(s, e, n):
    """Expand a (possibly wrapped) inclusive run into an explicit index array."""
    if s <= e:
        return np.arange(s, e + 1)
    return np.concatenate([np.arange(s, n), np.arange(0, e + 1)])

# ---------------- CORNERS ----------------
corner_mask = radius < 80.0
corner_runs = runs(corner_mask)
# require a minimum length so single-station noise blips don't count (>= 3 stations ~ >8 m)
corner_runs = [(s, e) for (s, e) in corner_runs if len(run_indices(s, e, N)) >= 3]

print("\n" + "=" * 70)
print("CORNERS (radius < 80 m)")
print("=" * 70)

corner_results = []
for (s, e) in corner_runs:
    ii = run_indices(s, e, N)
    # apex = tightest (max curvature) station within the run
    apex_local = ii[np.argmax(kappa[ii])]
    r_apex = radius[apex_local]
    w_apex = width[apex_local]

    # which wall is on the inside of the turn?
    # signed cross of (line->left) tangent... determine inside by curvature direction.
    # Compute the line tangent and the turn center direction at apex.
    p_prev = line[(apex_local - 1) % N]
    p_here = line[apex_local]
    p_next = line[(apex_local + 1) % N]
    t = p_next - p_prev
    t = t / max(np.linalg.norm(t), 1e-9)
    # left normal (rotate tangent +90)
    nL = np.array([-t[1], t[0]])
    # turn direction: cross of incoming and outgoing
    v1 = p_here - p_prev
    v2 = p_next - p_here
    cross = v1[0] * v2[1] - v1[1] * v2[0]  # >0 left turn, <0 right turn
    turn = "RIGHT" if cross < 0 else "LEFT"

    # distance from line to each wall at apex
    dL = np.linalg.norm(left[apex_local] - line[apex_local])
    dR = np.linalg.norm(right[apex_local] - line[apex_local])

    # inner wall: on a right-hander the inside is to the right of travel.
    # right-of-travel normal = -nL. The wall on that side is the inner wall.
    nR = -nL
    # project (wall - line) onto nR; the wall with the larger positive projection is inner-side
    projL = np.dot(left[apex_local] - line[apex_local], nR)
    projR = np.dot(right[apex_local] - line[apex_local], nR)
    if turn == "RIGHT":
        inner_is_right = projR > projL
    else:
        inner_is_right = projR < projL  # inner is to the LEFT

    if inner_is_right:
        inner_wall_name = "right"
        line_to_inner = dR
    else:
        inner_wall_name = "left"
        line_to_inner = dL

    frac = line_to_inner / w_apex if w_apex > 0 else float("nan")
    apexes = line_to_inner <= 2.5  # within ~1-2 m of inner kerb (allow a little slack)

    corner_results.append(dict(
        run=(int(s), int(e)), apex_i0=int(apex_local), radius_m=float(r_apex),
        width_m=float(w_apex), turn=turn, inner_wall=inner_wall_name,
        line_to_inner_m=float(line_to_inner), dL=float(dL), dR=float(dR),
        frac_inner=float(frac), apexes=bool(apexes), nstations=len(ii),
    ))
    print(f"\nCorner run i0 {s}..{e} ({len(ii)} stations), turn={turn}")
    print(f"  apex i0={apex_local}  radius={r_apex:.1f} m  track_width={w_apex:.2f} m")
    print(f"  inner wall = {inner_wall_name}  | line->left={dL:.2f} m  line->right={dR:.2f} m")
    print(f"  line->INNER = {line_to_inner:.2f} m  ({frac*100:.0f}% of width from inner kerb)")
    print(f"  apexes (<=2.5 m off inner)? {apexes}")

# ---------------- STRAIGHTS ----------------
straight_mask = radius > 200.0
straight_runs = runs(straight_mask)
straight_runs = [(s, e) for (s, e) in straight_runs if len(run_indices(s, e, N)) >= 4]

print("\n" + "=" * 70)
print("STRAIGHTS (radius > 200 m)")
print("=" * 70)

straight_results = []
for (s, e) in straight_runs:
    ii = run_indices(s, e, N)
    P = line[ii]
    a = P[0]
    b = P[-1]
    chord = b - a
    L = np.linalg.norm(chord)
    if L < 1e-6:
        continue
    u = chord / L
    nrm = np.array([-u[1], u[0]])
    dev = (P - a) @ nrm  # signed perpendicular deviation from chord
    wiggle = float(np.max(np.abs(dev)))
    straight_results.append(dict(
        run=(int(s), int(e)), nstations=len(ii), chord_len_m=float(L),
        wiggle_m=wiggle,
    ))
    print(f"\nStraight run i0 {s}..{e} ({len(ii)} stations), chord={L:.1f} m")
    print(f"  max lateral wiggle from chord = {wiggle:.2f} m")

# ---------------- CORRIDOR PLAUSIBILITY ----------------
print("\n" + "=" * 70)
print("CORRIDOR / TRACK WIDTH PLAUSIBILITY")
print("=" * 70)
print(f"width stats (m): min={width.min():.2f} p10={np.percentile(width,10):.2f} "
      f"median={np.median(width):.2f} mean={width.mean():.2f} "
      f"p90={np.percentile(width,90):.2f} max={width.max():.2f}")

# also: how far does the line ever get from EITHER wall (min clearance) — if the line
# is always well inset from both walls, it's mid-track.
dL_all = np.linalg.norm(left - line, axis=1)
dR_all = np.linalg.norm(right - line, axis=1)
print(f"line->left  (m): min={dL_all.min():.2f} median={np.median(dL_all):.2f} max={dL_all.max():.2f}")
print(f"line->right (m): min={dR_all.min():.2f} median={np.median(dR_all):.2f} max={dR_all.max():.2f}")
min_clear = np.minimum(dL_all, dR_all)
print(f"closest the line EVER gets to either wall: {min_clear.min():.2f} m (at i0={int(np.argmin(min_clear))})")
print(f"fraction of stations where line is within 2 m of SOME wall: {np.mean(min_clear<2.0)*100:.0f}%")

# emit a compact machine-readable summary
import json
print("\nJSON_SUMMARY_START")
print(json.dumps(dict(
    N=N, total_len=float(total),
    corners=corner_results, straights=straight_results,
    width_min=float(width.min()), width_median=float(np.median(width)),
    width_max=float(width.max()),
    line_min_clearance=float(min_clear.min()),
), indent=0))
print("JSON_SUMMARY_END")
