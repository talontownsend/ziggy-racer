"""Build the measured per-station LOAD map from the bot's own telemetry (independence-
compliant): gs = alat_max_g*9.81 / (alat + alat_k v^2) is the foot's live load scaling,
logged every tick. Median per station + median speed -> recordings/load_map.npz.
Crest reads ~0.66 (S9), banked reads >=1 (S12) -- unlike elevation geometry, measured
load cannot confuse a bank roll with a crest.
Usage: python build_load_map.py <follow_log.csv>
"""
import csv, sys
import numpy as np

REC = r"C:\Users\talon\FH6-AFK-Farm\recordings"
d = np.load(REC + r"\refline_plan.npz")
line = d["line"]; n = len(line)
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]

ALAT, ALAT_K = 26.0, 0.0025
gs_acc = [[] for _ in range(n)]
v_acc = [[] for _ in range(n)]
for r in csv.DictReader(open(sys.argv[1])):
    try:
        i0 = int(float(r["i0"])) % n
        v = float(r["spd_kmh"]) / 3.6
        mx = float(r["alat_max_g"]) * 9.81
        if r["on_track"] != "1" or v < 8.0:
            continue
    except Exception:
        continue
    gs = mx / (ALAT + ALAT_K * v * v)
    if 0.3 < gs < 3.0:
        gs_acc[i0].append(gs); v_acc[i0].append(v)

gs_med = np.ones(n); v_med = np.full(n, 30.0); cnt = np.zeros(n)
for i in range(n):
    if len(gs_acc[i]) >= 10:
        gs_med[i] = np.median(gs_acc[i]); v_med[i] = np.median(v_acc[i]); cnt[i] = len(gs_acc[i])
# fill sparse stations from neighbors
for i in range(n):
    if cnt[i] < 10:
        j = 1
        while cnt[(i + j) % n] < 10 and j < 30:
            j += 1
        gs_med[i] = gs_med[(i + j) % n]; v_med[i] = v_med[(i + j) % n]
# light smoothing
for _ in range(3):
    gs_med = (np.roll(gs_med, 1) + gs_med + np.roll(gs_med, -1)) / 3.0
    v_med = (np.roll(v_med, 1) + v_med + np.roll(v_med, -1)) / 3.0

np.savez(REC + r"\load_map.npz", gs=gs_med, v=v_med)
print(f"load map saved. min {gs_med.min():.2f} @ s={s_of[int(np.argmin(gs_med))]:.0f}, "
      f"max {gs_med.max():.2f} @ s={s_of[int(np.argmax(gs_med))]:.0f}")
for lo, hi, tag in ((639, 704, "S9"), (545, 607, "S7"), (878, 994, "S12 bank"), (785, 878, "S11")):
    mk = (s_of >= lo) & (s_of < hi)
    print(f"  {tag}: load med {np.median(gs_med[mk]):.2f}  min {gs_med[mk].min():.2f}")

# ---- crest FACTOR table: multiplies the capped target (<=1). Solve per station:
#      v^2 k = (alat + alat_k v^2) * lp(v)^0.705, lp(v) = 1 + (gs-1)(v/v_med)^2 (clip),
#      fac = v_loaded / v_fullload over the cap's 18 m curvature window; fac=1 where the
#      line is near-straight (k < 0.004) or the station is not light (gs >= 0.98).
#      Backward smear 0.004/m gives the approach a lift instead of a step.
def _smooth(a, w):
    out = a.copy()
    for _ in range(w):
        out = (np.roll(out, 1) + out + np.roll(out, -1)) / 3.0
    return out

a3, b3, c3 = np.roll(line, 1, 0), line, np.roll(line, -1, 0)
ab = b3 - a3; bc = c3 - b3; ac = c3 - a3
cross = ab[:, 0] * bc[:, 1] - ab[:, 1] * bc[:, 0]
la, lb, lc = (np.linalg.norm(v, axis=1) for v in (ab, bc, ac))
kap = _smooth(np.abs(2.0 * cross / np.maximum(la * lb * lc, 1e-9)), 3)
kw = kap.copy()
for i in range(n):
    dd, j = 0.0, i
    while dd < 18.0:
        kw[i] = max(kw[i], kap[j]); dd += seg[j]; j = (j + 1) % n
fac = np.ones(n)
for i in range(n):
    if kw[i] < 0.004 or gs_med[i] >= 0.98:
        continue
    kk_full = max(kw[i] - ALAT_K, 1e-5)
    v_full = np.sqrt(ALAT / kk_full)
    v = v_full
    for _ in range(12):
        lp = min(max(1.0 + (gs_med[i] - 1.0) * (v / max(v_med[i], 5.0)) ** 2, 0.5), 1.15) ** 0.705
        kk = kw[i] - ALAT_K * lp
        if kk <= 1e-5:
            v = v_full; break
        v = 0.5 * v + 0.5 * np.sqrt(ALAT * lp / kk)
    fac[i] = min(max(v / v_full, 0.6), 1.0)
out = fac.copy()
for i in range(n):
    dd, j = 0.0, i
    while dd < 80.0:
        j = (j + 1) % n; dd += seg[j]
        v_ok = fac[j] + 0.004 * dd
        if v_ok < out[i]:
            out[i] = v_ok
np.savez(REC + r"\crest_fac.npz", fac=out)
print(f"crest factor saved. min {out.min():.2f} @ s={s_of[int(np.argmin(out))]:.0f}; "
      f"stations <0.98: {(out < 0.98).sum()}")

