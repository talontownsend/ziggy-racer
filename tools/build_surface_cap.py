"""SURFACE-FRAME CORNER CAP from the survey sheet (pure-controller step 1).
Per station, at the racing line (d=0):
  bank theta  = atan(sheet lateral slope), signed + = tilted toward the local turn
  z''         = vertical curvature of the sheet height along s at d=0
  kappa       = line curvature (18 m forward window, as the runtime cap uses)
Solve for v:  v^2 k cos(t) - g sin(t) = (a0 + a_k v^2) * load(v)^0.705
              load(v) = cos(t) - z'' v^2 / g + (v^2 k / g) sin(t)
Fixed-point per station -> speed cap table, brake-cone smoothed (A=15 m/s^2).
Output: recordings/surface_cap.npz {cap (m/s), bank, zpp}. Replaces crest_fac + load_map.
Validation printout compares against known ground truth per zone.
"""
import os
import numpy as np

REC = r"C:\Users\talon\FH6-AFK-Farm\recordings"
ALAT, ALAT_K, G, EXP = 26.0, 0.0025, 9.81, 0.705
VMAX = 120.0

d0 = np.load(os.path.join(REC, "refline_plan.npz"))
line = d0["line"]; n = len(line)
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
sh = np.load(os.path.join(REC, "surface_sheet.npz"))
A, B, C = sh["a"], sh["b"], sh["c"]


def smooth(a, w):
    out = a.copy()
    for _ in range(w):
        out = (np.roll(out, 1) + out + np.roll(out, -1)) / 3.0
    return out


# signed line curvature from THE RUNTIME'S OWN SOURCE (the planner's kappa_ref) --
# an independent menger recomputation disagreed at sharp transitions and invented
# R=20 m corners at the S8/S9 boundary (cap collapsed to 80 km/h, soak ruined 07-04).
# The cap must see the same track the runtime sees.
import sys
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from local_planner import LocalPlanner
ks = LocalPlanner(line, a_lat=ALAT).kappa_ref.copy()
kw = np.abs(ks).copy()
for i in range(n):
    dd, j = 0.0, i
    while dd < 18.0:
        kw[i] = max(kw[i], abs(ks[j])); dd += seg[j]; j = (j + 1) % n

# surface at the line: bank from the SHEET (its unique lateral knowledge); vertical
# curvature from the PLAN elevation (dense, validated: predicted the measured 0.66
# crest load) -- the sheet's A is too smoothed for reliable second derivatives
bank = np.arctan(-np.sign(ks) * B)          # + = surface tilts down toward turn center
# taper the bank term where curvature is small: 'toward the turn' is ill-defined
# through S-bend sign flips (a smoothed slope against a flipping sign read as -5.6 deg
# 'off-camber' at the S8/S9 boundary). Bank weight ramps 0 -> 1 over |k| 0.002 -> 0.008.
bank *= np.clip((np.abs(ks) - 0.002) / 0.006, 0.0, 1.0)
zpp = smooth(np.gradient(np.gradient(smooth(d0["elev"], 5), s_of, edge_order=1),
                         s_of, edge_order=1), 3)

cap = np.full(n, VMAX)
for i in range(n):
    k = kw[i]
    if k < 1e-4:
        continue
    t = bank[i]
    v = min(np.sqrt(ALAT / max(k - ALAT_K, 1e-5)), VMAX)   # flat-world seed
    for _ in range(16):
        # crest: zpp < 0 -> load drops (surface curves away); compression: zpp > 0 ->
        # load rises. Bank presses the centripetal reaction into the surface (+).
        load = np.cos(t) + zpp[i] * v * v / G + (v * v * k / G) * np.sin(t)
        load = min(max(load, 0.35), 1.6)
        avail = (ALAT + ALAT_K * v * v) * load ** EXP
        need_coef = k * np.cos(t)
        rhs = avail + G * np.sin(t)
        if rhs <= 0 or need_coef <= 1e-6:
            v = VMAX; break
        v_new = min(np.sqrt(rhs / need_coef), VMAX)
        v = 0.5 * v + 0.5 * v_new
    cap[i] = v

# SANITY CLAMP: the surface correction may never move the cap more than +-25% off the
# flat-world value. Physics corrections beyond that are almost certainly measurement/
# fit artifacts (this clamp alone would have prevented the 07-04 regression soak).
flat_ref = np.minimum(np.sqrt(ALAT / np.maximum(kw - ALAT_K, 1e-5)), VMAX)
clamped = (cap < 0.75 * flat_ref) | (cap > 1.25 * flat_ref)
cap = np.clip(cap, 0.75 * flat_ref, 1.25 * flat_ref)
print(f"sanity clamp engaged at {clamped.sum()} stations")

# brake-cone (approach ramps must be physically brakeable)
out = cap.copy()
A_CONE = 15.0
for i in range(n):
    dd, j = 0.0, i
    while dd < 200.0:
        v_ok = np.sqrt(cap[j] ** 2 + 2.0 * A_CONE * dd)
        if v_ok < out[i]:
            out[i] = v_ok
        dd += seg[j]; j = (j + 1) % n

# RELATIVE FACTOR for pre-recalibration wiring: the absolute cap uses the uncalibrated
# base constants (the map's ~+27% intercept isn't in them), so as an absolute bound it
# undercuts the map-corrected runtime. Until the recal ramp lands, ship the surface
# physics as cap/flat ratio multiplying the existing chain; the absolute cap stays in
# the file for post-recal use. Backward-smeared 0.004/m for approach anticipation.
fac = np.clip(cap / np.maximum(flat_ref, 1e-3), 0.75, 1.25)
fs = fac.copy()
for i in range(n):
    dd, j = 0.0, i
    while dd < 80.0:
        j = (j + 1) % n; dd += seg[j]
        v_ok = fac[j] + 0.004 * dd
        if v_ok < fs[i]:
            fs[i] = v_ok
np.savez(os.path.join(REC, "surface_cap.npz"), cap=out, fac=fs, bank=bank, zpp=zpp)
print(f"surface cap saved. factor range {fs.min():.2f}-{fs.max():.2f}; "
      f"binding (< 250 km/h): {(out * 3.6 < 250).sum()} stations")

# validation: compare against the flat-world model + known ground truth
flat = np.minimum(np.sqrt(ALAT / np.maximum(kw - ALAT_K, 1e-5)), VMAX)
print(f"\n{'zone':>18} {'flat cap':>8} {'surf cap':>8} {'delta':>7}   (expected effect)")
for lo, hi, tag, exp in ((878, 994, "S12 bank", "GAIN (banked +6 deg)"),
                         (639, 704, "S9 crest", "CUT (load 0.66 measured)"),
                         (545, 607, "S7 crest", "CUT (load 0.78 measured)"),
                         (785, 878, "S11", "mild gain (bank +4)"),
                         (60, 146, "S1", "~neutral (mild bank)"),
                         (413, 453, "S5 hairpin", "~neutral (slow)"),
                         (250, 361, "S3 sweeper", "mild gain")):
    mk = (s_of >= lo) & (s_of < hi) & (kw >= 0.004)
    if mk.sum() == 0:
        continue
    f_ = np.median(flat[mk] * 3.6); s_ = np.median(out[mk] * 3.6)
    print(f"{tag:>18} {f_:8.0f} {s_:8.0f} {s_-f_:+7.0f}   ({exp})")
mk = (s_of >= 684) & (s_of <= 700)
print(f"\nS9 crest-turn detail (s684-700): flat {np.median(flat[mk]*3.6):.0f} -> "
      f"surface {np.median(out[mk]*3.6):.0f} km/h "
      f"(bot's execution limit there ~121-126; formula should land at/below the flat cap)")

