"""Decompose v_curve: how much corner speed the target system denies vs what line+grip permit.

Reproduces the planner's kappa EXACTLY (3-point Menger, signed, _smooth_closed w=5) and
max_kappa_line_ahead exactly (16 samples over 18 m, percentile kappa_pct=100 == max), so
v_line is reconstructed rather than approximated.

Three quantities, all in km/h:
  v_phys  = 3.6*sqrt(alat/(|kappa_ref[station]| - alat_k))   what the line permits HERE
  v_line  = 3.6*sqrt(alat/(max|kappa_ref| over 18 m ahead - alat_k))   after the lookahead
  v_log   = logged vcurve_kmh = min(v_line, v_rejoin)

  v_phys - v_line  = cost of the 18 m max-lookahead (a DESIGN choice, not physics)
  v_line - v_log   = cost of the rejoin/merge term
  v_phys - v_log   = total denial vs what the line and grip model permit
"""
import numpy as np
import pandas as pd

ALAT, AK, DIST, NS = 27.0, 0.0025, 18.0, 16
d = np.load('recordings/refline_plan.npz')
line = d['line']
N = len(line)


def smooth_closed(a, w=5):
    k = np.ones(w) / w
    return np.convolve(np.r_[a[-w:], a, a[:w]], k, 'same')[w:-w]


# --- planner's kappa_ref, exactly -------------------------------------------
dd = np.roll(line, -1, 0) - line
seg = np.hypot(dd[:, 0], dd[:, 1])
cum_s = np.concatenate([[0.0], np.cumsum(seg)])
total_s = float(cum_s[-1])
p0 = np.roll(line, 1, 0); p2 = np.roll(line, -1, 0)
a_ = np.hypot(*(line - p0).T); b_ = np.hypot(*(p2 - line).T); c_ = np.hypot(*(p2 - p0).T)
area = 0.5 * np.abs((line[:, 0]-p0[:, 0])*(p2[:, 1]-p0[:, 1]) -
                    (line[:, 1]-p0[:, 1])*(p2[:, 0]-p0[:, 0]))
den = a_ * b_ * c_
kmag = np.where(den > 1e-9, 4 * area / den, 0.0)
sign = np.sign((line[:, 0]-p0[:, 0])*(p2[:, 1]-p0[:, 1]) -
               (line[:, 1]-p0[:, 1])*(p2[:, 0]-p0[:, 0]))
kappa_ref = smooth_closed(kmag * sign, 5)

# --- max_kappa_line_ahead, exactly ------------------------------------------
kline = np.empty(N)
for i in range(N):
    s0 = cum_s[i]
    ss = np.mod(np.linspace(s0, s0 + DIST, NS), total_s)
    idx = np.clip(np.searchsorted(cum_s, ss, side='right') - 1, 0, N - 1)
    kline[i] = np.abs(kappa_ref[idx]).max()          # pct=100 -> max

v_phys = 3.6 * np.sqrt(ALAT / np.maximum(np.abs(kappa_ref) - AK, 1e-4))
v_line = 3.6 * np.sqrt(ALAT / np.maximum(kline - AK, 1e-4))

# --- logged -----------------------------------------------------------------
b = pd.read_csv('recordings/follow_log.csv',
                usecols=['race_pos', 'on_track', 'i0', 'vcurve_kmh', 'cte_m', 'spd_kmh', 'bind_code'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
b = b[(b['race_pos'] >= 1) & (b['on_track'] > 0.5)]
b = b.assign(st=b['i0'].astype(int) % N)
obs = b.groupby('st')['vcurve_kmh'].median()
cte = b.groupby('st')['cte_m'].apply(lambda x: x.abs().median())

print("RECONSTRUCTION CHECK: does exact v_line reproduce the logged v_curve?")
i = obs.index.to_numpy()
o = obs.to_numpy()
resid = o - v_line[i]
print(f"  corr {np.corrcoef(v_line[i], o)[0,1]:+.3f}   median residual {np.median(resid):+.1f} km/h"
      f"   |resid| median {np.median(np.abs(resid)):.1f}")
print(f"  stations where logged is WITHIN 3 km/h of v_line (v_line binds): "
      f"{100*np.mean(np.abs(resid) < 3):.0f}%")
print(f"  stations where logged is >3 km/h BELOW v_line (v_rejoin binds):  "
      f"{100*np.mean(resid < -3):.0f}%")
print(f"  stations where logged is >3 km/h ABOVE v_line (reconstruction off): "
      f"{100*np.mean(resid > 3):.0f}%")

print("\nPER-CORNER DECOMPOSITION (km/h, medians over the binding stations)")
print(f"  {'corner':>10} {'stations':>11} {'v_phys':>7} {'v_line':>7} {'v_log':>7} "
      f"{'lookahead':>10} {'rejoin':>7} {'TOTAL':>7} {'|cte|':>6}")
for lo, hi, lab in ((595, 640, 'corner 2'), (795, 845, 'corner 1'), (880, 925, 'corner 3')):
    sp = np.arange(lo, hi + 1)
    ob = obs.reindex(sp).dropna()
    sp = ob.index.to_numpy()
    vp, vl, vo = np.median(v_phys[sp]), np.median(v_line[sp]), float(ob.median())
    print(f"  {lab:>10} {lo}-{hi:<7d} {vp:7.1f} {vl:7.1f} {vo:7.1f} "
          f"{vp-vl:10.1f} {vl-vo:7.1f} {vp-vo:7.1f} {cte.reindex(sp).median():6.2f}")

print("\nIS THE BINDING MAX A SMOOTH PEAK OR A SPIKE?  (kappa_ref through corner 2)")
sp = np.arange(590, 645)
k = np.abs(kappa_ref[sp])
print(f"  {'stn':>5} {'kappa':>8} {'radius':>7} {'v_phys':>7}  profile")
for j, s in enumerate(sp):
    if s % 3:
        continue
    bar = '#' * int(k[j] / max(k.max(), 1e-9) * 40)
    print(f"  {s:5d} {k[j]:8.5f} {1/max(k[j],1e-9):7.0f} {v_phys[s]:7.1f}  {bar}")
pk = sp[np.argmax(k)]
w = np.sum(k > 0.8 * k.max())
print(f"\n  peak at station {pk}, kappa {k.max():.5f} (R={1/k.max():.0f} m)")
print(f"  stations within 20% of the peak: {w} (~{w*total_s/N:.1f} m)")
print(f"  -> {'SMOOTH PEAK, not a spike' if w >= 5 else 'SPIKE: 1-2 samples set the cap'}")
