#!/usr/bin/env python3
"""
STRATEGY B - Order-preserving perpendicular pairing of the two edge loops,
seam origin rotated onto the longest straight.

Pipeline:
  1. Load CSV, keep moving frames (speed_kmh>3 and not menu zeros), time order.
  2. Split boundary (first ~16238) vs hot laps at first k with median(kmh[k:k+200])>120.
  3. From the boundary phase: identify the turnaround (car reverses direction near
     start/finish) and split into LAP 1 (left edge) and LAP 2 (right edge).
     Discard the turnaround frames.
  4. Resample each edge loop to N=400 in a consistent (same) direction.
  5. ROTATE both loops' parameter origin to a point on the LONGEST STRAIGHT so the
     start/finish seam is mid-array (not at index 0/N-1).
  6. PERPENDICULAR, ORDER-PRESERVING pairing: for each left[i] cast its local normal,
     find the right point whose projection is closest along that normal within a tight
     band, but force the matched right index to advance monotonically with i.
  7. Enforce non-crossing (left offset > right offset everywhere along centerline normal).
  8. Build corridor, run provided optimizer, smooth, compute speed/lap time.
  9. Validate non-crossing, save PNG + NPZ.
"""
import sys
import csv
import numpy as np

sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from racing_line import (resample_closed, menger_curvature, velocity_profile,
                         min_curvature_line, plan_racing_line)

CSV = r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038.csv"
PNG = r"C:\Users\talon\FH6-AFK-Farm\recordings\corridorB.png"
NPZ = r"C:\Users\talon\FH6-AFK-Farm\recordings\planB.npz"
N = 400
VEHICLE = {"a_lat": 8.0, "a_acc": 11.2, "a_brake": 13.7, "v_max": 67.2}


# --------------------------------------------------------------------------- #
def load():
    rows = []
    with open(CSV) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    g = lambda k: np.array([float(r[k]) for r in rows])
    px, pz, sp = g("pos_x"), g("pos_z"), g("speed_mps")
    vx, vz, yaw = g("vel_x"), g("vel_z"), g("yaw")
    mask = (sp * 3.6 > 3) & ~((px == 0) & (pz == 0))
    return (px[mask], pz[mask], sp[mask] * 3.6, vx[mask], vz[mask], yaw[mask])


def split_boundary_hot(kmh):
    for k in range(len(kmh) - 1):
        if np.median(kmh[k:k + 200]) > 120:
            return k
    return len(kmh)


def resample_consistent(pts, n):
    """Resample closed loop to n pts; force CCW orientation for consistency."""
    rs = resample_closed(pts, n)
    # signed area (shoelace) -> ensure consistent (CCW positive) orientation
    x, y = rs[:, 0], rs[:, 1]
    area = 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    if area < 0:
        rs = rs[::-1].copy()
    return rs


def find_turnaround_split(px, pz, vx, vz):
    """The boundary phase is two slow edge laps + a turnaround near start/finish
    where the car reverses. Detect the reversal: the direction of travel flips
    (velocity dot with smoothed heading goes strongly negative), splitting lap1
    from lap2. We find the longest contiguous 'reversal' run and use its bounds.

    Returns (lap1_idx_slice, lap2_idx_slice) into the boundary arrays.
    """
    n = len(px)
    # heading from velocity
    speed = np.hypot(vx, vz)
    hx = vx / np.maximum(speed, 1e-6)
    hy = vz / np.maximum(speed, 1e-6)
    # smoothed forward direction over a window (the "intended" progress direction)
    w = 25
    def smooth(a):
        k = np.ones(w) / w
        return np.convolve(np.concatenate([a[-w:], a, a[:w]]), k, "same")[w:-w]
    sx, sy = smooth(hx), smooth(hy)
    sn = np.hypot(sx, sy)
    sx, sy = sx / np.maximum(sn, 1e-6), sy / np.maximum(sn, 1e-6)
    dotp = hx * sx + hy * sy  # ~1 when going with flow, <0 during a reversal

    # Also: the start/finish is where the loop returns near its own start.
    # Find candidate reversal region: where dotp dips negative.
    reversal = dotp < 0.0
    # find contiguous runs of reversal
    runs = []
    i = 0
    while i < n:
        if reversal[i]:
            j = i
            while j < n and reversal[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs, dotp


def order_preserving_perp_pair(left, right):
    """For each left[i], find right point along left's local normal, constrained so
    matched right index advances monotonically with i. left,right are N-closed,
    same orientation, origins already rotated to mid-straight.

    Returns matched_right (Nx2) aligned to left index i.
    """
    n = len(left)
    # left local tangent + inward-ish normal
    tang = np.roll(left, -1, axis=0) - np.roll(left, 1, axis=0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])  # left-hand normal

    # orient normal so it points from left wall toward right wall on average
    c_left = left.mean(0)
    c_right = right.mean(0)
    # use a robust per-point sign: normal should point toward the nearest right pts
    # global check first
    if np.dot(nrm.mean(0), (c_right - c_left)) < 0:
        nrm = -nrm

    matched = np.zeros((n, 2))
    matched_idx = np.zeros(n, dtype=int)

    # Establish a good starting correspondence at i=0 (mid-straight, trivial):
    d0 = np.linalg.norm(right - left[0], axis=1)
    j_start = int(np.argmin(d0))
    matched_idx_prev = j_start

    # search window parameters
    win = 40           # how far ahead/behind in right index we may search
    max_lat = 30.0     # max corridor half-considered (m)

    for i in range(n):
        p = left[i]
        nv = nrm[i]
        # candidate right indices in a forward-advancing window around prev match
        base = matched_idx_prev
        cand = [(base + d) % n for d in range(-5, win + 1)]
        best = None
        best_score = 1e18
        for j in cand:
            q = right[j]
            d = q - p
            lat = np.dot(d, nv)           # signed distance along normal (should be >0)
            off = d - lat * nv            # tangential residual
            tres = np.hypot(off[0], off[1])
            dist = np.hypot(d[0], d[1])
            if dist > max_lat:
                continue
            # we want small tangential residual (perpendicular match) and lat>0
            score = tres + 0.05 * abs(dist)
            if lat < 0.3:
                score += 1000.0          # strongly penalize wrong-side / collapsed
            if score < best_score:
                best_score = score
                best = j
        if best is None:
            # fallback: nearest point ahead
            dd = np.linalg.norm(right - p, axis=1)
            best = int(np.argmin(dd))
        matched_idx[i] = best
        matched[i] = right[best]
        matched_idx_prev = best

    # Enforce monotonic non-decreasing advance (unwrap) to kill back-jumps across pinch
    # unwrap matched_idx as a monotone sequence modulo n
    unwrapped = np.zeros(n)
    unwrapped[0] = matched_idx[0]
    for i in range(1, n):
        step = (matched_idx[i] - matched_idx[i - 1]) % n
        if step > n // 2:   # this is actually a backward jump -> clamp to no-advance
            step = 0
        unwrapped[i] = unwrapped[i - 1] + step
    # total advance should ~ n; rescale to exactly one lap and resample right by it
    total = unwrapped[-1] + ((matched_idx[0] - matched_idx[i]) % n)
    if total < 1:
        total = n
    # map left index i -> fractional right index via the monotone unwrapped curve,
    # then sample right (closed) at those fractional indices for a smooth corridor.
    frac = (unwrapped / unwrapped[-1]) * n + j_start
    rx = np.interp(frac, np.arange(n + 1), np.concatenate([right[:, 0], right[:1, 0]]),
                   period=None)
    # safer: wrap manually
    fi = frac % n
    i0 = np.floor(fi).astype(int) % n
    i1 = (i0 + 1) % n
    t = fi - np.floor(fi)
    matched_smooth = (1 - t)[:, None] * right[i0] + t[:, None] * right[i1]
    return matched_smooth, nrm


def rotate_to_longest_straight(loop):
    """Rotate the closed loop so index 0 sits at the middle of its longest straight
    (lowest-curvature, highest local segment-length region)."""
    n = len(loop)
    kappa = menger_curvature(loop)
    # smooth curvature
    k = np.ones(15) / 15
    ks = np.convolve(np.concatenate([kappa[-15:], kappa, kappa[:15]]), k, "same")[15:-15]
    origin = int(np.argmin(ks))
    return np.roll(loop, -origin, axis=0), origin


def enforce_non_crossing(left, right):
    """Build centerline, project both walls onto centerline normal, ensure
    left offset > right offset at every station; if violated, push apart minimally."""
    center = 0.5 * (left + right)
    tang = np.roll(center, -1, axis=0) - np.roll(center, 1, axis=0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
    loff = np.sum((left - center) * nrm, axis=1)
    roff = np.sum((right - center) * nrm, axis=1)
    return loff, roff, nrm, center


def main():
    px, pz, kmh, vx, vz, yaw = load()
    k = split_boundary_hot(kmh)
    print("boundary/hot split k =", k, " total moving =", len(px))

    bx, bz = px[:k], pz[:k]
    bvx, bvz = vx[:k], vz[:k]

    runs, dotp = find_turnaround_split(bx, bz, bvx, bvz)
    print("reversal runs (start,end,len):",
          [(a, b, b - a) for a, b in runs if b - a > 5])

    # The turnaround is the most significant reversal run near start/finish.
    # Pick the longest reversal run as the turnaround; it separates lap1 / lap2.
    sig = [(a, b) for a, b in runs if (b - a) >= 8]
    if sig:
        # choose run with the longest duration
        ta = max(sig, key=lambda r: r[1] - r[0])
    else:
        ta = (k // 2, k // 2 + 1)
    print("turnaround chosen:", ta, "len", ta[1] - ta[0])

    # lap1 = before turnaround, lap2 = after turnaround
    # Add a small guard band to fully drop the turnaround transient.
    guard = 30
    lap1 = np.column_stack([bx[:max(ta[0] - guard, 10)],
                            bz[:max(ta[0] - guard, 10)]])
    lap2 = np.column_stack([bx[min(ta[1] + guard, k - 10):],
                            bz[min(ta[1] + guard, k - 10):]])
    print("lap1 pts", len(lap1), " lap2 pts", len(lap2))

    # Resample each edge to N in a consistent orientation
    L = resample_consistent(lap1, N)
    R = resample_consistent(lap2, N)

    # Determine which is left vs right edge. The corridor center ~ average of both.
    # Left should sit on the left-hand side relative to travel direction. We just
    # label them edgeA/edgeB and later assign so that left offset>right offset.
    # Rotate both to longest straight. Rotate L first; then rotate R to align with
    # L's new origin by nearest point.
    L, origin_L = rotate_to_longest_straight(L)
    # align R origin to L[0]
    j = int(np.argmin(np.linalg.norm(R - L[0], axis=1)))
    R = np.roll(R, -j, axis=0)
    print("rotated origin_L =", origin_L, " R aligned shift =", j)

    # Order-preserving perpendicular pairing: match R to each L[i]
    R_matched, nrm = order_preserving_perp_pair(L, R)

    # Now decide left vs right wall by sign of offset along centerline normal
    loff, roff, cnrm, center = enforce_non_crossing(L, R_matched)
    # We want LEFT wall offset > RIGHT wall offset. If on average L is below R, swap.
    if np.mean(loff) < np.mean(roff):
        left_wall, right_wall = R_matched, L
    else:
        left_wall, right_wall = L, R_matched

    # Recompute offsets w/ final assignment and enforce strict separation
    loff, roff, cnrm, center = enforce_non_crossing(left_wall, right_wall)
    cross = loff <= roff
    print("crossing stations before fix:", int(cross.sum()))
    if cross.any():
        # push apart minimally along centerline normal so loff>roff+0.5
        mid = 0.5 * (loff + roff)
        gap = np.maximum(0.5 * (roff - loff) + 0.6, 0.0)
        loff_f = np.where(cross, mid + gap, loff)
        roff_f = np.where(cross, mid - gap, roff)
        left_wall = center + loff_f[:, None] * cnrm
        right_wall = center + roff_f[:, None] * cnrm
        loff, roff, cnrm, center = enforce_non_crossing(left_wall, right_wall)
        print("crossing stations after fix:", int((loff <= roff).sum()))

    # Light smoothing of walls to remove telemetry jitter (closed moving avg)
    def smooth_closed(a, w=7):
        k = np.ones(w) / w
        out = np.zeros_like(a)
        for d in range(2):
            ext = np.concatenate([a[-w:, d], a[:, d], a[:w, d]])
            out[:, d] = np.convolve(ext, k, "same")[w:-w]
        return out
    left_wall = smooth_closed(left_wall, 7)
    right_wall = smooth_closed(right_wall, 7)

    # Final validation of non-crossing
    loff, roff, cnrm, center = enforce_non_crossing(left_wall, right_wall)
    seam_ok = bool(np.all(loff > roff))
    widths = loff - roff
    print("width mean/min/max:", widths.mean(), widths.min(), widths.max())
    print("seam_ok:", seam_ok)

    # ---- run provided optimizer ----
    plan = plan_racing_line(left_wall, right_wall, VEHICLE, n=N)
    line = plan["line"]

    # smooth the optimized line (closed moving average window 9) before speed
    def smooth_line(a, w=9):
        return smooth_closed(a, w)
    line_s = smooth_line(line, 9)
    v, kappa, ds = velocity_profile(line_s, VEHICLE["a_lat"], VEHICLE["a_acc"],
                                    VEHICLE["a_brake"], VEHICLE["v_max"])
    lap_time = float(np.sum(ds / np.maximum(v, 0.5)))
    top_speed_kmh = float(v.max() * 3.6)
    print("lap_distance:", float(ds.sum()))
    print("lap_time:", lap_time, "s   top speed:", top_speed_kmh, "km/h")

    # find start/finish region: it's where the two edge laps started/ended -> the
    # original origin point of the un-rotated loop. After rotation it's near the
    # mid-array seam. We mark it as the station farthest in arc from index 0
    # (since we rotated origin to mid-straight, the seam is ~N/2). Mark via the
    # point closest to original lap start = bx[0],bz[0].
    sf_pt = np.array([bx[0], bz[0]])
    sf_station = int(np.argmin(np.linalg.norm(center - sf_pt, axis=1)))
    print("start/finish station (rotated frame):", sf_station)

    # ---- plot ----
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
    ax1.plot(left_wall[:, 0], left_wall[:, 1], "-", color="blue", lw=1.5, label="left wall")
    ax1.plot(right_wall[:, 0], right_wall[:, 1], "-", color="red", lw=1.5, label="right wall")
    ax1.plot([left_wall[0, 0], right_wall[0, 0]], [left_wall[0, 1], right_wall[0, 1]],
             "g--", lw=0.8)
    # mark start/finish region (+/-20 stations)
    lo = (sf_station - 20) % N
    rng = [(lo + t) % N for t in range(41)]
    ax1.plot(center[rng, 0], center[rng, 1], "-", color="orange", lw=4, alpha=0.5,
             label="start/finish region")
    ax1.scatter([sf_pt[0]], [sf_pt[1]], color="black", marker="*", s=200, zorder=5,
                label="start/finish")
    ax1.set_aspect("equal"); ax1.legend(); ax1.set_title("Corridor B: left(blue)/right(red)")

    pts = line_s.reshape(-1, 1, 2)
    segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
    vk = v[:-1] * 3.6
    lc = LineCollection(segs, cmap="viridis")
    lc.set_array(vk); lc.set_linewidth(3)
    ax2.add_collection(lc)
    ax2.plot(left_wall[:, 0], left_wall[:, 1], color="0.7", lw=0.5)
    ax2.plot(right_wall[:, 0], right_wall[:, 1], color="0.7", lw=0.5)
    ax2.set_aspect("equal")
    ax2.autoscale()
    fig.colorbar(lc, ax=ax2, label="target speed km/h")
    ax2.set_title(f"Optimized line  lap={lap_time:.2f}s  top={top_speed_kmh:.0f}km/h")
    fig.tight_layout()
    fig.savefig(PNG, dpi=110)
    print("saved", PNG)

    np.savez(NPZ, left=left_wall, right=right_wall, line=line_s, speed=v)
    print("saved", NPZ)

    print("RESULT", dict(
        width_mean=float(widths.mean()), width_min=float(widths.min()),
        width_max=float(widths.max()), lap_time=lap_time,
        top_speed=top_speed_kmh, seam_ok=seam_ok))


if __name__ == "__main__":
    main()
