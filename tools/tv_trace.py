"""Reproduce the logged tv/target_v term by term and name what sets the corner-1 dip.

Chain (follow.py ~1690-1713), with the live config:
  vown_w = 0.0  ->  vplan_eff = vplan  =  refline_plan['speed'], the HUMAN reference lap's
                    speed profile. _kl (multi-scale raw Menger) and v_own are computed but
                    UNUSED, so tv is NOT curvature-driven.
  look = 20 + spd^2/(2*A_BRAKE)              <- depends on the CAR'S speed, so tv is state-dependent
  tv   = min over j within look of sqrt(vplan[j]^2 + 2*A_BRAKE*d2)
  safety = 1.0 -> safety_eff = 1.0
  target_v = min(tv, speed_cap)

Bar: reproduce logged tgt_kmh to the decimal at bind_code==1 stations before concluding.
"""
import json
import numpy as np
import pandas as pd

A_BRAKE = 25.0
d = np.load('recordings/refline_plan.npz')
line, vplan = d['line'], d['speed']
N = len(line)
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
cum = np.concatenate([[0.0], np.cumsum(seg)])
s_of = cum[:-1]
t = json.load(open('recordings/tune.json'))
SC = float(t.get('speed_cap', 71.0))
SAFETY = float(t.get('safety', 1.0))

b = pd.read_csv('recordings/follow_log.csv',
                usecols=['race_pos', 'on_track', 'i0', 'tgt_kmh', 'spd_kmh', 'bind_code'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
b = b[(b['race_pos'] >= 1) & (b['on_track'] > 0.5)].assign(st=lambda x: x['i0'].astype(int) % N)


def tv_at(i0, spd):
    """Exact replica of the follower's braking-anticipation pass. Returns (tv, binding j)."""
    look = 20.0 + spd * spd / (2.0 * A_BRAKE)
    d2, j, tv, bj, bd = 0.0, i0, vplan[i0], i0, 0.0
    while d2 < look:
        v = np.sqrt(vplan[j] ** 2 + 2.0 * A_BRAKE * d2)
        if v < tv:
            tv, bj, bd = v, j, d2
        d2 += seg[j]
        j = (j + 1) % N
    return tv, bj, bd


# ---- validation: reproduce logged target at bind_code==1 stations -----------
g = b.groupby('st').agg(tgt=('tgt_kmh', 'median'), spd=('spd_kmh', 'median'),
                        c1=('bind_code', lambda c: float(np.mean(c == 1))))
pred, errs = {}, []
for st in g.index:
    tv, bj, bd = tv_at(int(st), float(g.loc[st, 'spd']) / 3.6)
    p = min(tv * (SAFETY + (1 - SAFETY) * min(max((tv - 20) / 25, 0), 1)), SC) * 3.6
    pred[st] = (p, bj, bd, tv * 3.6)
    if g.loc[st, 'c1'] > 0.8:
        errs.append(p - g.loc[st, 'tgt'])
errs = np.array(errs)
print(f"VALIDATION at {len(errs)} stations where bind_code==1 on >80% of ticks")
print(f"  median err {np.median(errs):+.2f} km/h   p90 |err| {np.percentile(np.abs(errs),90):.2f}   "
      f"within 1 km/h: {100*np.mean(np.abs(errs)<1):.0f}%")
ok = abs(np.median(errs)) < 0.5 and np.percentile(np.abs(errs), 90) < 3.0
print(f"  {'REPRODUCED' if ok else 'NOT REPRODUCED -- conclusions withheld'}")
if not ok:
    raise SystemExit(1)

print(f"\nCORNER 1 ENTRY 780-850: what sets tv, station by station")
print(f"  {'stn':>5} {'s_m':>6} {'bot':>6} {'logTGT':>7} {'predTGT':>8} {'err':>6} | "
      f"{'binds@':>7} {'s_bind':>7} {'dist':>6} {'vplan@bind':>11} {'vplan@stn':>10}")
for st in range(780, 851):
    if st not in pred:
        continue
    p, bj, bd, tv = pred[st]
    print(f"  {st:5d} {s_of[st]:6.0f} {g.loc[st,'spd']:6.1f} {g.loc[st,'tgt']:7.1f} {p:8.1f} "
          f"{p-g.loc[st,'tgt']:+6.1f} | {bj:7d} {s_of[bj]:7.0f} {bd:6.1f} "
          f"{vplan[bj]*3.6:11.1f} {vplan[st]*3.6:10.1f}")

# ---- the dip's source ------------------------------------------------------
dipst = min((s for s in range(790, 800) if s in pred), key=lambda s: pred[s][0])
p, bj, bd, tv = pred[dipst]
print(f"\nDIP: station {dipst} (s={s_of[dipst]:.0f} m), target {p:.1f} km/h")
print(f"  set by vplan at station {bj} (s={s_of[bj]:.0f} m, {bd:.1f} m ahead) = {vplan[bj]*3.6:.1f} km/h")
print(f"  i.e. the plan is braking NOW to reach {vplan[bj]*3.6:.1f} km/h at s={s_of[bj]:.0f}")

# ---- is that assumed apex right? compare to the human's actual -------------
H = r'C:\Users\Talon\AppData\Local\FH6 TC\recording_20260802_073646.csv'
h = pd.read_csv(H, usecols=['pos_x', 'pos_z', 'speed_mps', 'is_race_on'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
h = h[(h['is_race_on'] > 0) & (h['speed_mps'] > 1)]
P = h[['pos_x', 'pos_z']].to_numpy()
st_h = np.empty(len(P), dtype=int)
for i in range(0, len(P), 20000):
    st_h[i:i+20000] = ((P[i:i+20000, None, :] - line[None, :, :]) ** 2).sum(2).argmin(1)
hum = pd.Series(h['speed_mps'].to_numpy() * 3.6).groupby(st_h).median()

print(f"\nIS THE ASSUMED APEX RIGHT?  vplan vs the human's ACTUAL, around the binding station")
print(f"  {'stn':>5} {'s_m':>6} {'vplan':>7} {'human':>7} {'human-vplan':>12}")
lo, hi = max(bj - 12, 0), min(bj + 13, N)
for s in range(lo, hi):
    hv = hum.get(s, np.nan)
    print(f"  {s:5d} {s_of[s]:6.0f} {vplan[s]*3.6:7.1f} {hv:7.1f} {hv-vplan[s]*3.6:+12.1f}")
z = np.arange(lo, hi)
vp = vplan[z] * 3.6
hh = hum.reindex(z).to_numpy()
print(f"\n  vplan minimum here      {vp.min():.1f} km/h at station {z[np.argmin(vp)]}")
print(f"  human actual minimum    {np.nanmin(hh):.1f} km/h at station {z[np.nanargmin(hh)]}")
print(f"  MIS-MODEL: the plan assumes an apex {np.nanmin(hh)-vp.min():+.1f} km/h "
      f"{'BELOW' if np.nanmin(hh) > vp.min() else 'ABOVE'} what the human actually drives")
print(f"  whole lap: vplan below human actual at "
      f"{100*np.nanmean(vplan[hum.index.to_numpy()]*3.6 < hum.to_numpy()):.0f}% of stations, "
      f"median gap {np.nanmedian(hum.to_numpy() - vplan[hum.index.to_numpy()]*3.6):+.1f} km/h")
