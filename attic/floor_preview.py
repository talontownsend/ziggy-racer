"""Preview where the proven-speed floor binds: stations where the flat grip model
(24.3 + 0.0025 v^2) caps BELOW 0.95*vplan (the human's proven median speed)."""
import numpy as np

d = np.load(r"C:\Users\talon\FH6-AFK-Farm\recordings\refline_plan.npz")
line, vplan = d["line"], d["speed"]
n = len(line)
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s = np.concatenate([[0.0], np.cumsum(seg)])[:-1]

# seam-safe curvature (3-pt menger on the closed line)
a, b, c = np.roll(line, 1, 0), line, np.roll(line, -1, 0)
ab = b - a; bc = c - b; ac = c - a
cross = ab[:, 0] * bc[:, 1] - ab[:, 1] * bc[:, 0]
la, lb, lc = np.linalg.norm(ab, axis=1), np.linalg.norm(bc, axis=1), np.linalg.norm(ac, axis=1)
kappa = np.abs(2.0 * cross / np.maximum(la * lb * lc, 1e-9))
# light smoothing like the planner sees (its kappa_ref is smoothed)
k = kappa.copy()
for _ in range(3):
    k = (np.roll(k, 1) + k + np.roll(k, -1)) / 3.0

ALAT, ALAT_K = 24.3, 0.0025
kk = np.maximum(k - ALAT_K, 1e-4)
v_model = np.sqrt(ALAT / kk)

# rolling 18 m forward-min of vplan (same as follow.py)
vmin18 = vplan.copy()
for i in range(n):
    dd, j = 0.0, i
    while dd < 18.0:
        vmin18[i] = min(vmin18[i], vplan[j])
        dd += seg[j]; j = (j + 1) % n
# and the same forward-max window on kappa (the cap's 18 m window)
kmax18 = k.copy()
for i in range(n):
    dd, j = 0.0, i
    while dd < 18.0:
        kmax18[i] = max(kmax18[i], k[j])
        dd += seg[j]; j = (j + 1) % n
kkw = np.maximum(kmax18 - ALAT_K, 1e-4)
v_model_w = np.sqrt(ALAT / kkw)

floor = 0.95 * vmin18
binds = floor > v_model_w
gain = np.where(binds, (floor - v_model_w) * 3.6, 0.0)

# map to the user's 13 sections. Boundaries are stations on the V1 refline; use V1 arc length.
v1 = np.load(r"C:\Users\talon\FH6-AFK-Farm\recordings\refline_plan_v1_27s.npz")
l1 = v1["line"]; seg1 = np.hypot(*(np.roll(l1, -1, 0) - l1).T)
s1 = np.concatenate([[0.0], np.cumsum(seg1)])[:-1]
bounds_st = [56, 136, 236, 340, 388, 428, 512, 568, 596, 656, 732, 820, 928]
bounds_m = [s1[bst] for bst in bounds_st]
total = s[-1] + seg[-1]

def section_of(sm):
    for si in range(13):
        lo = bounds_m[si]; hi = bounds_m[(si + 1) % 13]
        if lo < hi:
            if lo <= sm < hi: return si + 1
        else:
            if sm >= lo or sm < hi: return si + 1
    return -1

print(f"track {total:.0f} m, floor binds at {binds.sum()}/{n} stations ({100*binds.mean():.0f}%)")
print(f"{'sec':>4} {'bind_m':>7} {'cap_now':>8} {'floor':>7} {'max_gain':>9}")
for sec in range(1, 14):
    m = np.array([section_of(x) == sec for x in s])
    bm = binds & m
    if bm.sum() == 0:
        print(f"S{sec:<3} {'--':>7}")
        continue
    print(f"S{sec:<3} {seg[bm].sum():7.0f} {v_model_w[bm].min()*3.6:8.0f} {floor[bm].min()*3.6:7.0f} {gain[bm].max():+9.1f}")
print("\n(cap_now = slowest flat-model cap in the section's binding zone, km/h;")
print(" floor = proven-speed floor there; max_gain = biggest cap raise, km/h)")
