"""Rebuild the racing line from the user's REAL best lap (run_20260625_120907.csv, 26.05 s)
instead of the dedicated-but-slower refline session (27.28 s) the v1 plan was built from.
Same pipeline as build_refline.py (imitation line + real corridor + human speed x1.05).
Writes a CANDIDATE (refline_plan_v2.npz) + validation stats; does NOT touch the live plan.
"""
import csv, sys
import numpy as np
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from scipy.spatial import cKDTree
from build_corridor_edges import corridor_from_edges, line_metrics, save_plan, smooth_closed
from racing_line import resample_closed, velocity_profile, grade_adjust, segment_lengths, menger_curvature

REC = r"C:\Users\talon\FH6-AFK-Farm\recordings\run_20260625_120907.csv"
LEFT = r"recordings/limits_left/session_20260626_103954.csv"
RIGHT = r"recordings/limits_right/session_20260626_104413.csv"
OUT = r"C:\Users\talon\FH6-AFK-Farm\recordings\refline_plan_v2.npz"
OLD = r"C:\Users\talon\FH6-AFK-Farm\recordings\refline_plan_v1_27s.npz"
N = 1000
# MEDIAN MODE (user 07-03): the reference is the MEDIAN path + MEDIAN speed across ALL full laps
# of the 06-25 run files, not the single fastest lap -- one hot lap contains one-off moments the
# user doesn't drive consistently, and the per-section comparison is against their MEDIAN times.
# The best lap serves only as the projection base frame.
MEDIAN_RECS = [r"C:\Users\talon\FH6-AFK-Farm\recordings\run_20260625_120907.csv",
               r"C:\Users\talon\FH6-AFK-Farm\recordings\run_20260625_120122.csv"]
CLEAR = 0.4   # edge clearance (m) for the clip. Was 1.0; the user rides 0.05-0.10 m from the
              # recorded edges at s~221 (S2 exit), s~404 (S4), s~843 (S11) and chose 0.4 as the
              # margin -- keeps the line close to the real one while leaving the follower a little
              # tracking headroom. Tighten further only if the follower proves precise here.


def load_laps(path):
    rows = list(csv.DictReader(open(path)))
    laps = {}
    for r in rows:
        if r.get("is_race_on") != "1":
            continue
        try:
            ln = int(r["lap_no"]); lt = float(r["cur_lap_time"]); spd = float(r["speed_mps"])
            x = float(r["pos_x"]); z = float(r["pos_z"]); y = float(r["pos_y"])
        except (KeyError, ValueError):
            continue
        laps.setdefault(ln, []).append((lt, x, z, y, spd))
    return laps


laps = load_laps(REC)
print("lap times (game clock):")
best_ln, best_t = None, 1e9
for ln in sorted(laps):
    arr = np.array(laps[ln]); lt = arr[:, 0]
    dur = lt.max() - lt.min()
    moving = (arr[:, 4] * 3.6 > 3).mean()
    full = dur > 20 and len(arr) > 400 and lt.min() < 2.0
    if full and dur < best_t:
        best_t, best_ln = dur, ln
    print(f"  lap {ln}: {dur:5.2f}s  ({len(arr)} pts, {moving*100:.0f}% moving){'  <- complete' if full else '  (partial/outlap)'}")
print(f"BEST lap: {best_ln} @ {best_t:.2f}s")

arr = np.array(laps[best_ln])
arr = arr[np.argsort(arr[:, 0])]
arr = arr[arr[:, 4] * 3.6 > 3]
xz = arr[:, 1:3]; y = arr[:, 3]; uspd = arr[:, 4]
line = resample_closed(xz, N)

# ---- MEDIAN PATH across all full laps (see MEDIAN_RECS note above) ----
base = line.copy()
tngb = np.roll(base, -1, 0) - np.roll(base, 1, 0)
tngb /= np.maximum(np.hypot(tngb[:, 0], tngb[:, 1]), 1e-9)[:, None]
nb = np.column_stack([-tngb[:, 1], tngb[:, 0]])
bt = cKDTree(base)
acc_d = [[] for _ in range(N)]; acc_y = [[] for _ in range(N)]; acc_v = [[] for _ in range(N)]
nlaps_used = 0
for path2 in MEDIAN_RECS:
    laps2 = load_laps(path2)
    for ln2 in sorted(laps2):
        a2 = np.array(laps2[ln2]); lt2 = a2[:, 0]
        if not (lt2.max() - lt2.min() > 20 and len(a2) > 400 and lt2.min() < 2.0):
            continue                                        # full flying laps only
        nlaps_used += 1
        a2 = a2[np.argsort(a2[:, 0])]
        a2 = a2[a2[:, 4] * 3.6 > 3]
        _, ii = bt.query(a2[:, 1:3])
        dd2 = ((a2[:, 1:3] - base[ii]) * nb[ii]).sum(1)
        for j in range(len(a2)):
            i_st = ii[j]
            if abs(dd2[j]) < 12.0:                          # ignore far-off (incident) frames
                acc_d[i_st].append(dd2[j]); acc_y[i_st].append(a2[j, 3]); acc_v[i_st].append(a2[j, 4])
d_med = np.zeros(N); y_med = np.zeros(N); v_med = np.zeros(N); have = np.zeros(N, bool)
for i in range(N):
    if len(acc_d[i]) >= 20:
        d_med[i] = np.median(acc_d[i]); y_med[i] = np.median(acc_y[i]); v_med[i] = np.median(acc_v[i])
        have[i] = True
print(f"MEDIAN LINE: {nlaps_used} full laps pooled | stations with >=20 samples: {int(have.sum())}/{N}")
for i in range(N):                                          # circular gap fill (rare)
    if not have[i]:
        j = 1
        while not have[(i - j) % N]:
            j += 1
        k2 = 1
        while not have[(i + k2) % N]:
            k2 += 1
        w2 = k2 / (j + k2)
        d_med[i] = w2 * d_med[(i - j) % N] + (1 - w2) * d_med[(i + k2) % N]
        y_med[i] = w2 * y_med[(i - j) % N] + (1 - w2) * y_med[(i + k2) % N]
        v_med[i] = w2 * v_med[(i - j) % N] + (1 - w2) * v_med[(i + k2) % N]
xz = base + smooth_closed(d_med, 5)[:, None] * nb           # synthetic median-path points
y = smooth_closed(y_med, 7); uspd = smooth_closed(v_med, 7)
dev_best = np.abs(d_med)
print(f"median-vs-best-lap deviation: mean {dev_best.mean():.2f} m, max {dev_best.max():.2f} m "
      f"at s~{np.argmax(dev_best) * 1.07:.0f} m")
line = smooth_closed(xz, 5)
# CLOSE THE SEAM: the lap's first/last recorded points don't coincide exactly, so the closed
# resample leaves a kink at station 0 (measured R=2.8 m on the 256 km/h main straight = a
# phantom wall at start/finish). Diffuse positions locally around the seam until it joins
# as smoothly as the straight it sits on.
_wseam = np.zeros(N); _wseam[:6] = 1.0; _wseam[-6:] = 1.0
for _ in range(10):
    _wseam = np.maximum(_wseam, 0.85 * np.maximum(np.roll(_wseam, 1), np.roll(_wseam, -1)))
for _ in range(300):
    _avg = 0.5 * (np.roll(line, 1, 0) + np.roll(line, -1, 0))
    line = line + (_wseam[:, None] * 0.4) * (_avg - line)
tr = cKDTree(xz)
_, idx = tr.query(line)
line_y = smooth_closed(y[idx], 7)
user_v = smooth_closed(uspd[idx], 7)

corr = corridor_from_edges(LEFT, RIGHT, lap=1, a_lat_g=2.45, verbose=False)
cen = 0.5 * (corr["left"] + corr["right"])
ck = cKDTree(cen)
_, j = ck.query(line)
left = corr["left"][j]; right = corr["right"][j]
veh, grade_c = corr["veh"], corr["grade"]
# ---- CLEARANCE AS AN OBSTACLE PROBLEM, in the HUMAN LINE'S OWN NORMAL FRAME. ----
# Root cause of the S12 weave: the old clip worked in the corridor-centerline frame
# (line = c2 + off*nrm), whose station pairing jumps around; reconstructing there DISCARDS the
# tangential component and shuffles points along-track -> phantom kinks at the wall apexes
# (R=12 m at s~836 baked into a 151 km/h zone = 5.5x grip demanded; the plan speed is the
# human's, who never drove the clipped shape). Here instead: keep the human path exactly,
# displace it ONLY along its OWN smooth normals, with per-station clearance bounds projected
# from the real edges, solved by diffusion under the box constraint (taut string against the
# wall). Equilibrium: smooth minimal deviation, hugging the bound tangentially -- and the
# human's real apex shapes (e.g. the hairpin) are untouched where clearance already holds.
def _kappa_closed(ln):
    p0 = np.roll(ln, 1, 0); p2 = np.roll(ln, -1, 0)
    a = np.hypot(*(ln - p0).T); b = np.hypot(*(p2 - ln).T); c = np.hypot(*(p2 - p0).T)
    area = 0.5 * np.abs((ln[:, 0]-p0[:, 0])*(p2[:, 1]-p0[:, 1]) - (ln[:, 1]-p0[:, 1])*(p2[:, 0]-p0[:, 0]))
    kap = np.where(a*b*c > 1e-9, 4*area/np.maximum(a*b*c, 1e-9), 0.0)
    w = 5; kk = np.ones(w) / w
    return np.convolve(np.r_[kap[-w:], kap, kap[:w]], kk, "same")[w:-w]

line_pre = line.copy()                                      # resampled smooth human path
tng = np.roll(line_pre, -1, 0) - np.roll(line_pre, 1, 0)
tng /= np.maximum(np.hypot(tng[:, 0], tng[:, 1]), 1e-9)[:, None]
nl = np.column_stack([-tng[:, 1], tng[:, 0]])               # left normal of the human line
eL = np.sum((left - line_pre) * nl, axis=1)                 # signed edge offsets along nl
eR = np.sum((right - line_pre) * nl, axis=1)
hi_b = np.maximum(eL, eR); lo_b = np.minimum(eL, eR)
# smooth the bounds (recorded edge polylines are noisy), with a small safety bias inward
hi_b = smooth_closed(hi_b, 7) - CLEAR - 0.05
lo_b = smooth_closed(lo_b, 7) + CLEAR + 0.05
mid = 0.5 * (hi_b + lo_b)
deg = hi_b < lo_b
hi_b = np.where(deg, mid, hi_b); lo_b = np.where(deg, mid, lo_b)

viol0 = (0.0 < lo_b) | (0.0 > hi_b)                         # human path violates clearance here
zone_mask = viol0.copy()
for _d in range(20):
    zone_mask = zone_mask | np.roll(zone_mask, 1) | np.roll(zone_mask, -1)
wgt = zone_mask.astype(float)
for _d in range(15):
    wgt = np.maximum(wgt, 0.9 * np.maximum(np.roll(wgt, 1), np.roll(wgt, -1)))
off = np.clip(np.zeros(N), lo_b, hi_b)
for _rep in range(4000):
    avg = 0.5 * (np.roll(off, 1) + np.roll(off, -1))
    off = off + wgt * 0.5 * (avg - off)
    off = np.clip(off, lo_b, hi_b)
line = line_pre + off[:, None] * nl
clipped = np.abs(off)                                       # displacement from the human path

clen_v = np.r_[0.0, np.cumsum(segment_lengths(line))][:N]
big = clipped > 0.3
print(f"\nCLEARANCE SOLVE: {int(viol0.sum())} stations violated {CLEAR} m clearance; "
      f"{int(big.sum())} stations displaced >0.3 m (max {clipped.max():.2f} m at s={clen_v[np.argmax(clipped)]:.0f} m)")
if big.sum():
    runs = np.split(np.where(big)[0], np.where(np.diff(np.where(big)[0]) > 3)[0] + 1)
    kap_fin = _kappa_closed(line)
    kap_pre = _kappa_closed(line_pre)
    for r in runs:
        nb = np.r_[np.arange(r[0]-12, r[0]), np.arange(r[-1]+1, r[-1]+13)] % N
        print(f"  zone s {clen_v[r[0]]:.0f}-{clen_v[r[-1]]:.0f} m (max {clipped[r].max():.2f} m): "
              f"R {1/max(kap_pre[r].max(),1e-6):.0f} -> {1/max(kap_fin[r].max(),1e-6):.0f} m "
              f"(neighbors R={1/max(kap_fin[nb].max(),1e-6):.0f})")
kap_fin = _kappa_closed(line)
cl_fin = np.minimum(np.hypot(*(left - line).T), np.hypot(*(right - line).T))
print(f"clearance: min {cl_fin.min():.2f} m | global min radius {1/max(kap_fin.max(),1e-6):.1f} m")

elev = smooth_closed(line_y, 7)
ds_c = segment_lengths(line)
grade = np.clip(smooth_closed((np.roll(elev, -1) - np.roll(elev, 1)) / np.maximum(np.roll(ds_c, 1) + ds_c, 1e-6), 5), -0.35, 0.35)
aacc, abrk = grade_adjust(veh["a_acc"], veh["a_brake"], grade)
PLAN_ALAT = 31.0
V, _, ds = velocity_profile(line, PLAN_ALAT, aacc, abrk, veh["v_max"], a_lat_k=veh["a_lat_k"])
_, iu = tr.query(line)
plan_v = np.minimum(smooth_closed(uspd[iu], 9) * 1.05, 71.0)

m = line_metrics(left, right, line, V)
print(f"\nNEW line: p99turn {m['max_turn']:.1f}deg  clear {m['min_clear']:.2f}m  est lap {m['lap_time']:.1f}s  "
      f"user-driven {best_t:.2f}s  top {m['top_kmh']:.0f}km/h")
print(f"  plan speed: HUMAN x1.05 -> {plan_v.mean()*3.6:.0f} avg / {plan_v.max()*3.6:.0f} top km/h")

# --- validation 2: old vs new plan, per meter ---
old = np.load(OLD)
oline, ospeed = old["line"], old["speed"]
ot = cKDTree(oline)
dist_to_old, oi = ot.query(line)
print(f"\nOLD-vs-NEW geometry: mean |offset| {dist_to_old.mean():.2f} m, max {dist_to_old.max():.2f} m "
      f"at s={clen_v[np.argmax(dist_to_old)]:.0f} m")
dv = (plan_v - ospeed[oi]) * 3.6
print(f"OLD-vs-NEW plan speed: mean {dv.mean():+.1f} km/h, max {dv.max():+.1f} at s={clen_v[np.argmax(dv)]:.0f}, "
      f"min {dv.min():+.1f} at s={clen_v[np.argmin(dv)]:.0f}")

np.savez(OUT, left=left, right=right, line=line, speed=plan_v, elev=elev, grade=grade)
print(f"\nsaved CANDIDATE -> {OUT}")

# dump compact old/new/corridor JSON for visualization
import json
k = 4
diffs = {
    "s": [round(float(v), 1) for v in clen_v[::k]],
    "nx_": [round(float(v), 1) for v in line[::k, 0]], "nz_": [round(float(v), 1) for v in line[::k, 1]],
    "ox": [round(float(v), 1) for v in oline[::k, 0]], "oz": [round(float(v), 1) for v in oline[::k, 1]],
    "lx": [round(float(v), 1) for v in left[::2*k, 0]], "lz": [round(float(v), 1) for v in left[::2*k, 1]],
    "rx": [round(float(v), 1) for v in right[::2*k, 0]], "rz": [round(float(v), 1) for v in right[::2*k, 1]],
    "nv": [int(round(float(v) * 3.6)) for v in plan_v[::k]],
    "ov": [int(round(float(ospeed[oi][i]) * 3.6)) for i in range(0, N, k)],
    "gap": [round(float(v), 2) for v in dist_to_old[::k]],
}
json.dump(diffs, open(r"C:\Users\Talon\AppData\Local\Temp\claude\C--\0fe7484c-638c-408b-a34d-de8e5d737bf0\scratchpad\refline_v2_cmp.json", "w"), separators=(",", ":"))
print("dumped comparison JSON")

fig, ax = plt.subplots(1, 1, figsize=(12, 10))
ax.plot(corr["left"][:, 0], corr["left"][:, 1], "k-", lw=0.5)
ax.plot(corr["right"][:, 0], corr["right"][:, 1], "k-", lw=0.5)
ax.plot(oline[:, 0], oline[:, 1], "b--", lw=1.0, label="old (27.28 session)")
sc = ax.scatter(line[:, 0], line[:, 1], c=plan_v * 3.6, s=8, cmap="turbo")
ax.axis("equal"); ax.legend(); fig.colorbar(sc, ax=ax, label="plan km/h")
plt.tight_layout(); plt.savefig(r"C:\Users\talon\FH6-AFK-Farm\recordings\refline_v2.png", dpi=95)
print("saved recordings/refline_v2.png")
