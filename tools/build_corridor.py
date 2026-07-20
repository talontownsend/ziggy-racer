"""Session CSV -> clean corridor + vehicle model + optimized racing line.

Robust against tracks that run close to themselves: instead of projecting onto a
reference, we extract each boundary lap as its own ORDERED loop (so progression,
not Euclidean nearness, defines stations), drop the short turnaround segment, then
align the two loops and pair them into a corridor.
"""
import csv
import json
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from racing_line import (resample_closed, plan_racing_line, velocity_profile,
                         menger_curvature, segment_lengths, grade_adjust)
from cand_grad import min_time_line   # FIXED solver: direct projected-gradient on the
                                      # TRUE curvature energy (the old mlt_line/min_curvature_line
                                      # linearized once around the centerline and ANTI-apexed,
                                      # shipping a line with MORE curvature than the centerline).

HUMAN_BEST = 26.85   # your saved best on this circuit, the target to beat

N = 1000          # high resolution: ~1.1 m/point so tight corners (R7 m hairpin) are smooth
                  # arcs (~9 deg/step) instead of a coarse 30-deg-per-step polygon the
                  # follower can't track.
path = sys.argv[1]
rows = list(csv.DictReader(open(path)))
def arr(n): return np.array([float(x[n]) if x.get(n) not in (None, "") else np.nan
                             for x in rows])


def smooth_closed(a, w=7):
    k = np.ones(w) / w
    if a.ndim == 1:
        return np.convolve(np.r_[a[-w:], a, a[:w]], k, "same")[w:-w]
    return np.column_stack([smooth_closed(a[:, 0], w), smooth_closed(a[:, 1], w)])


def straighten_gap(wall, bad, margin=6):
    """Replace the flagged (seam) stations of a closed wall with a straight line
    interpolated across the gap -- correct because the start/finish IS a straight."""
    n = len(wall)
    m = bad.copy()
    for _ in range(margin):
        m = m | np.roll(m, 1) | np.roll(m, -1)
    if not m.any() or m.all():
        return wall
    # rotate the (possibly wrap-spanning) bad region to the interior so brackets are in bounds
    ang = 2 * np.pi * np.where(m)[0] / n
    center = int(round((np.angle(np.mean(np.exp(1j * ang))) % (2 * np.pi)) / (2 * np.pi) * n)) % n
    sh = (center - n // 2) % n
    w = np.roll(wall, -sh, axis=0).copy()
    mm = np.roll(m, -sh)
    idx = np.where(mm)[0]
    for run in np.split(idx, np.where(np.diff(idx) > 1)[0] + 1):
        a, b = max(run[0] - 1, 0), min(run[-1] + 1, n - 1)
        if b <= a:
            continue
        for k in run:
            t = (k - a) / (b - a)
            w[k] = (1 - t) * w[a] + t * w[b]
    return np.roll(w, sh, axis=0)

px, pz, py, vx, vz = arr("pos_x"), arr("pos_z"), arr("pos_y"), arr("vel_x"), arr("vel_z")
sp, tms = arr("speed_mps"), arr("timestamp_ms")
mv = (sp * 3.6 > 3) & ~((px == 0) & (pz == 0))
X, Z, PY, SP, TM = px[mv], pz[mv], py[mv], sp[mv], tms[mv]
VX, VZ = vx[mv], vz[mv]

# boundary vs hot split
first_hot = len(SP)
for k in range(len(SP) - 200):
    if np.median(SP[k:k + 200] * 3.6) > 120:
        first_hot = k
        break
B = np.column_stack([X[:first_hot], Z[:first_hot]])
print(f"moving={len(SP)}  boundary=0..{first_hot}  hot=...{len(SP)}")

# --- split boundary frames into loops at crossings of the start region ---
start = B[0]
d = np.hypot(B[:, 0] - start[0], B[:, 1] - start[1])
marks, away = [0], False
for k in range(len(d)):
    if d[k] > 60:
        away = True
    if away and d[k] < 20:
        marks.append(k)
        away = False
marks.append(len(B))
segs = [(marks[i], marks[i + 1]) for i in range(len(marks) - 1)]
def arclen(s): p = B[s[0]:s[1]]; return float(np.sum(np.hypot(np.diff(p[:, 0]), np.diff(p[:, 1]))))
segs.sort(key=arclen, reverse=True)
loopA = resample_closed(B[segs[0][0]:segs[0][1]], N)
loopB = resample_closed(B[segs[1][0]:segs[1][1]], N)
print(f"boundary loops: A={arclen(segs[0]):.0f} m, B={arclen(segs[1]):.0f} m "
      f"(dropped {len(segs)-2} short segs incl. turnaround)")

# --- align loop B to loop A by progression (direction + start phase), pair by index ---
# (order-based, so the track pinching near itself can't mis-pair across the gap)
best = None
for rev in (False, True):
    Bb = loopB[::-1] if rev else loopB
    for s in range(N):
        cost = np.sum((loopA - np.roll(Bb, s, axis=0)) ** 2)
        if best is None or cost < best[0]:
            best = (cost, rev, s)
_, rev, shift = best
loopB = np.roll(loopB[::-1] if rev else loopB, shift, axis=0)
raw_left, raw_right = loopA.copy(), loopB.copy()    # unsmoothed edges, for verification overlay
left = smooth_closed(loopA, 3)             # walls stay ON your driven edges -- ONLY a light
rightR = smooth_closed(loopB, 3)            # de-jitter. NO reshaping, reprojecting, or shrinking.

# Fix only the left<->right CORRESPONDENCE (not the wall positions): pair each left-edge
# point with its perpendicular partner on the right-edge trace, using a monotonic window so
# it can't match across the track where it nears itself. Both walls remain exactly where you
# drove them; this just gives the optimizer the true cross-track width.
tanL = np.roll(left, -1, 0) - np.roll(left, 1, 0)
tanL /= np.maximum(np.linalg.norm(tanL, axis=1, keepdims=True), 1e-9)
right = np.zeros_like(left)
j = 0
for i in range(N):
    best_k, best_t = j, 1e18
    for dj in range(-3, 22):
        k = (j + dj) % N
        vx, vz = rightR[k, 0] - left[i, 0], rightR[k, 1] - left[i, 1]
        if vx * vx + vz * vz > 30.0 ** 2:
            continue
        tcomp = abs(vx * tanL[i, 0] + vz * tanL[i, 1])   # tangential component -> 0 = perpendicular
        if tcomp < best_t:
            best_t, best_k = tcomp, k
    j = best_k
    right[i] = rightR[best_k]
width = np.linalg.norm(left - right, axis=1)
print(f"perpendicular-paired width m: mean {width.mean():.1f}  min {width.min():.1f}  max {width.max():.1f}")

# The ONLY spot we touch: the start/finish seam, where the boundary laps were cut and you
# turned around, so that patch of trace is corrupted (walls cross). Straighten just those
# crossed stations -- it's a straight there. Every other wall stays on your driven edge.
Cc = smooth_closed(0.5 * (left + right), 5)
tc2 = np.roll(Cc, -1, 0) - np.roll(Cc, 1, 0)
tc2 /= np.maximum(np.linalg.norm(tc2, axis=1, keepdims=True), 1e-9)
ncc = np.column_stack([-tc2[:, 1], tc2[:, 0]])
crossed = np.sum((left - Cc) * ncc, 1) <= np.sum((right - Cc) * ncc, 1)
seam = crossed | (width < 0.55 * np.median(width))   # whole broken patch: crossed OR pinched
left = straighten_gap(left, seam, margin=4)           # cut it out, draw straight lines across
right = straighten_gap(right, seam, margin=4)
print(f"seam: cut + straight-lined {int(seam.sum())} flagged stations (+margin 4) at start/finish")

# Despike: a few wall points fold back ~180 deg on themselves (recording/pairing glitches,
# not real track edges) -> spurious triangular cusps in the corridor. Flag any station where
# the wall turns more than 70 deg in one step and straight-line across it.
def _wall_turn(w):
    a = w - np.roll(w, 1, 0); b = np.roll(w, -1, 0) - w
    return np.degrees(np.abs(np.angle(np.exp(1j * (np.arctan2(b[:, 1], b[:, 0]) -
                                                    np.arctan2(a[:, 1], a[:, 0]))))))
lspike = _wall_turn(left) > 45.0
rspike = _wall_turn(right) > 45.0
if lspike.any():
    left = straighten_gap(left, lspike, margin=2)
if rspike.any():
    right = straighten_gap(right, rspike, margin=2)
print(f"despike: straightened {int(lspike.sum())} left + {int(rspike.sum())} right wall folds (>45 deg/step)")

# --- vehicle limits: REALISTIC, HOLDABLE grip. The lap-time-matched scale inflated
# a_lat to ~2 g, which over-speeds tight corners -> the car can't hold them and crashes.
# Use conservative grip (the honestly-measured ~0.72 g) so corner targets are achievable
# and the follower completes laps. Tune via argv[2] (lateral g).
# Limits CALIBRATED from the human hot lap (lap 3, 28.3 s): the maxed FE truck in FH6
# corners at ~2-3 g (arcade physics + FE grip), accels ~1.2 g, brakes ~1.8 g, tops 254.
# The line plans to the real capability; the follower scales it down via `safety` and we
# ramp safety up toward race pace. (0.72 g was a 2.6x-too-slow guess.)
a_lat_g = float(sys.argv[2]) if len(sys.argv) > 2 else 2.3
v_max = float(np.percentile(SP[first_hot:], 99))       # real top speed (~254 km/h)
veh = dict(a_lat=a_lat_g * 9.81, a_lat_k=0.00383, a_acc=11.0, a_brake=17.0, v_max=v_max)
# a_lat_k = downforce term measured from the 50-lap human run (grip_g ~= 2.45 + 0.00039*v^2 ->
# a_lat(v) = a_lat + 0.00383*v^2 m/s^2). Run with argv[2]=2.45 (measured low-speed base).
print(f"limits (realistic/holdable): a_lat {a_lat_g:.2f}g  a_acc {veh['a_acc']/9.81:.2f}g  "
      f"a_brake {veh['a_brake']/9.81:.2f}g  v_max {v_max*3.6:.0f} km/h")

# --- optimize on a slightly INSET corridor: just enough that the CAR BODY (not the line)
# clears the walls -- the line can still run right up near your traced edges.
# Car-body clearance from the walls. At very tight corners the racing line apexes hard
# to the inside; with too small a margin the line sits where the car BODY can't fit and
# it clips the inner wall. Use a larger base margin, and widen it further on the tightest
# corners (curvature-scaled) so the hairpin keeps real room.
cen = 0.5 * (left + right)
half = 0.5 * np.linalg.norm(left - right, axis=1)
kcen = smooth_closed(menger_curvature(cen), 5)
extra = np.clip((kcen - 1.0 / 25.0) * 40.0, 0.0, 1.5)          # +0..1.5 m ONLY on corners tighter than R25 (the hairpin)
MARGIN = 1.1 + extra                                           # medium corners stay ~1.1 m (were fine); hairpin ~2.6 m
inset = np.minimum(MARGIN, np.maximum(half - 0.75, 0.0))[:, None]
ul = cen - left
ul /= np.maximum(np.linalg.norm(ul, axis=1, keepdims=True), 1e-9)
ur = cen - right
ur /= np.maximum(np.linalg.norm(ur, axis=1, keepdims=True), 1e-9)

# --- ELEVATION -> per-station grade. The track climbs/drops ~17 m; gravity along the
# road materially changes braking/accel (downhill = brake later/longer, accel harder;
# uphill = the reverse). Map each centerline station to its nearest recorded frame's
# pos_y, then central-difference along arc length. ---
elev = np.array([PY[np.argmin((X - cx) ** 2 + (Z - cz) ** 2)] for cx, cz in cen])
elev = smooth_closed(elev, 7)
ds_c = segment_lengths(cen)
grade = (np.roll(elev, -1) - np.roll(elev, 1)) / np.maximum(np.roll(ds_c, 1) + ds_c, 1e-6)
grade = np.clip(smooth_closed(grade, 5), -0.35, 0.35)
aacc, abrk = grade_adjust(veh["a_acc"], veh["a_brake"], grade)

try:
    plan = min_time_line(left + inset * ul, right + inset * ur, veh,
                         n=N, grade=grade, clear=0.02, safety=0.0)
    # cand_grad already returns the FINAL followable, in-corridor, XY-smoothed line
    # (curvature diffusion + learned margin). Ship it AS-IS -- an extra smooth/resample
    # degraded the verified line (scored raw at lap 28.3 s / min-radius 8.3 m).
    L = np.asarray(plan["line"], float)
    print(f"min-lap-time solve: T {plan['lap_time_est']:.1f}s (stage-1 curvature seed {plan['T_seed']:.1f}s)")
except Exception as e:
    print(f"min_time_line FAILED ({e!r}) -> min-curvature fallback")
    plan = plan_racing_line(left + inset * ul, right + inset * ur, veh, n=N)
    L = smooth_closed(plan["line"], 13)

# grade-aware speed profile for the line we actually ship
V, _, ds = velocity_profile(L, veh["a_lat"], aacc, abrk, veh["v_max"],
                            a_lat_k=veh.get("a_lat_k", 0.0))
lap_time = float(np.sum(ds / np.maximum(V, 0.5)))
print(f"lap distance {ds.sum():.0f} m   est lap time {lap_time:.1f} s   "
      f"(human best {HUMAN_BEST:.1f} s)   line top speed {V.max()*3.6:.0f} km/h")
print(f"elevation range {elev.max()-elev.min():.1f} m   grade {grade.min()*100:+.0f}%..{grade.max()*100:+.0f}%")

# --- output ---
# self-check: walls never cross (left stays on one side of the centerline normal)
Cc = smooth_closed(0.5 * (left + right), 5)
tc = np.roll(Cc, -1, 0) - np.roll(Cc, 1, 0)
tc /= np.maximum(np.linalg.norm(tc, axis=1, keepdims=True), 1e-9)
ncc = np.column_stack([-tc[:, 1], tc[:, 0]])
cross = int(np.sum(np.sum((left - Cc) * ncc, 1) <= np.sum((right - Cc) * ncc, 1)))
print(f"crossing check: {cross} stations where walls cross (want 0)")

fig, ax = plt.subplots(1, 3, figsize=(24, 8))
ax[0].plot(left[:, 0], left[:, 1], "b-", lw=1, label="left wall")
ax[0].plot(right[:, 0], right[:, 1], "r-", lw=1, label="right wall")
for i in range(0, N, 12):
    ax[0].plot([left[i, 0], right[i, 0]], [left[i, 1], right[i, 1]], "0.7", lw=0.4)
ax[0].set_title("extracted corridor (rungs = station pairing)"); ax[0].axis("equal"); ax[0].legend()
ax[1].plot(left[:, 0], left[:, 1], "k-", lw=0.6)
ax[1].plot(right[:, 0], right[:, 1], "k-", lw=0.6)
sc = ax[1].scatter(L[:, 0], L[:, 1], c=V * 3.6, s=8, cmap="turbo")
ax[1].set_title("optimized line (color = target km/h)"); ax[1].axis("equal")
fig.colorbar(sc, ax=ax[1])
hp = int(np.argmax(menger_curvature(L)))           # tightest corner = the hairpin
hc = L[hp]
ax[2].plot(raw_left[:, 0], raw_left[:, 1], "b:", lw=1, label="raw L edge")
ax[2].plot(raw_right[:, 0], raw_right[:, 1], "r:", lw=1, label="raw R edge")
ax[2].plot(left[:, 0], left[:, 1], "b-", lw=1.5)
ax[2].plot(right[:, 0], right[:, 1], "r-", lw=1.5)
ax[2].plot(L[:, 0], L[:, 1], "g-", lw=1.5)
ax[2].set_xlim(hc[0] - 45, hc[0] + 45); ax[2].set_ylim(hc[1] - 45, hc[1] + 45)
ax[2].set_aspect("equal"); ax[2].legend(fontsize=7)
ax[2].set_title("hairpin: raw edge (dotted) vs final wall (solid)")
plt.tight_layout()
plt.savefig(path.replace(".csv", "_corridor.png"), dpi=90)
np.savez(path.replace(".csv", "_plan.npz"), left=left, right=right, line=L, speed=V,
         elev=elev, grade=grade)
json.dump({**veh, "lap_distance": float(ds.sum()), "lap_time_est": lap_time,
           "human_best_s": HUMAN_BEST, "elev_range_m": float(elev.max() - elev.min())},
          open(path.replace(".csv", "_plan.json"), "w"), indent=2)
print("saved _corridor.png, _plan.npz, _plan.json")
