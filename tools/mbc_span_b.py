"""Is MBC span B (s=638-702) still load-bearing, or is it guarding a hazard that no longer bites?

Span B caps the learned map's boost at 1.0 across s=638-702. It is the largest single denial
found 08-06: at corner 2's binding zone the effective target is 87.7 km/h against a human 135.4,
and even a full ksp blend only reaches 107.5 because the clamp, not the curvature, is binding.

Origin: introduced 07-08 (b929dc8) replacing the s7m/acm crest margins. The adjacent cg_on key
describes s600-680 as a "crest grip-margin" zone, so span B memorialises a CREST -- reduced
vertical load over a rise, where the map would learn a speed the car only survives on a good lap.

Bar: if incidents cluster inside the span, or the human treads carefully there too, it is
load-bearing and stays. Only if the hazard has stopped biting -- or the span is wider than the
hazard -- is a narrowing worth proposing.
"""
import json
import numpy as np
import pandas as pd

HUMAN = r'C:\Users\Talon\AppData\Local\FH6 TC\recording_20260802_073646.csv'
N = 1000
d = np.load('recordings/refline_plan.npz')
line, elev, vplan = d['line'], d['elev'], d['speed']
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
t = json.load(open('recordings/tune.json'))
B_LO, B_HI = float(t['mbc_b_lo']), float(t['mbc_b_hi'])
inb = (s_of >= B_LO) & (s_of <= B_HI)
st_b = np.where(inb)[0]
print(f"MBC span B: s={B_LO:.0f}-{B_HI:.0f} m  =  stations {st_b.min()}-{st_b.max()} ({len(st_b)} stations)")

# --- is it actually a crest? -------------------------------------------------
z = elev - elev.mean()
print(f"\n=== IS IT A CREST? (elevation, m relative to lap mean) ===")
print(f"  {'stn':>5} {'s_m':>6} {'elev':>7} {'d2z/ds2':>9}   profile")
zz = np.gradient(np.gradient(elev, s_of), s_of)
lo, hi = st_b.min() - 20, st_b.max() + 20
sub = z[lo:hi]
for i in range(lo, hi, 4):
    bar = '#' * int((z[i] - sub.min()) / max(sub.max() - sub.min(), 1e-9) * 44)
    mark = ' <-- span B' if inb[i] else ''
    print(f"  {i:5d} {s_of[i]:6.0f} {z[i]:7.2f} {zz[i]:+9.5f}   {bar}{mark}")
print(f"  span B mean curvature of elevation (d2z/ds2): {zz[inb].mean():+.5f}  "
      f"({'CREST (convex, unloads)' if zz[inb].mean() < -1e-5 else 'not convex'})")
print(f"  lap-wide d2z/ds2: p5 {np.percentile(zz,5):+.5f}  median {np.median(zz):+.5f}")
print(f"  span B rank by convexity: {100*np.mean(zz < zz[inb].mean()):.0f}% of stations are MORE convex")

# --- does the hazard still bite? --------------------------------------------
b = pd.read_csv('recordings/follow_log.csv',
                usecols=['race_pos', 'on_track', 'i0', 'spd_kmh', 'sideslip', 'cte_m',
                         'steer', 'meas_latg', 'drive_slip', 'bind_code'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
b = b[b['race_pos'] >= 1].assign(st=lambda x: x['i0'].astype(int) % N)
b['inb'] = b['st'].isin(st_b)
print(f"\n=== DOES THE HAZARD STILL BITE?  ({len(b):,} racing ticks) ===")
print(f"  {'':>10} {'ticks':>9} {'off-track%':>11} {'|sideslip|p99':>14} {'|cte|p90':>9} "
      f"{'latg p90':>9} {'slip p90':>9}")
for lab, m in (('INSIDE B', b['inb']), ('outside', ~b['inb'])):
    g = b[m]
    print(f"  {lab:>10} {len(g):9,} {100*np.mean(g['on_track']<=0.5):10.2f}% "
          f"{g['sideslip'].abs().quantile(.99):14.2f} {g['cte_m'].abs().quantile(.9):9.2f} "
          f"{g['meas_latg'].abs().quantile(.9):9.2f} {g['drive_slip'].quantile(.9):9.2f}")
ot = b.groupby('st')['on_track'].apply(lambda x: 100*np.mean(x <= 0.5))
top = ot.sort_values(ascending=False).head(12)
print(f"\n  WHERE ARE THE EXCURSIONS? top-12 stations by off-track rate")
for s, v in top.items():
    print(f"    stn {s:4d}  s={s_of[s]:5.0f} m  off-track {v:5.2f}%{'   <-- INSIDE SPAN B' if inb[s] else ''}")
print(f"  of the 12 worst stations, {sum(1 for s in top.index if inb[s])} are inside span B "
      f"(span is {100*len(st_b)/N:.0f}% of the lap)")

# --- what does the human do there? ------------------------------------------
h = pd.read_csv(HUMAN, usecols=['pos_x', 'pos_z', 'speed_mps', 'brake', 'accel', 'steer',
                                'ax', 'is_race_on'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
h = h[(h['is_race_on'] > 0) & (h['speed_mps'] > 1)]
P = h[['pos_x', 'pos_z']].to_numpy()
hs = np.empty(len(P), dtype=int)
for i in range(0, len(P), 20000):
    hs[i:i+20000] = ((P[i:i+20000, None, :] - line[None, :, :]) ** 2).sum(2).argmin(1)
tang = np.roll(line, -1, 0) - np.roll(line, 1, 0)
tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
nrm = np.stack([-tang[:, 1], tang[:, 0]], 1)
off = np.einsum('ij,ij->i', P - line[hs], nrm[hs])
h = h.assign(st=hs, off=off, kmh=h['speed_mps']*3.6, latg=h['ax'].abs()/9.81,
             brkf=h['brake']/255.0, thrf=h['accel']/255.0)
h['inb'] = h['st'].isin(st_b)
print(f"\n=== WHAT DOES THE HUMAN DO IN SPAN B?  ({int(h['inb'].sum()):,} of {len(h):,} ticks) ===")
print(f"  {'':>10} {'speed':>8} {'lat g p90':>10} {'brake%':>8} {'throttle':>9} {'|offset|':>9}")
for lab, m in (('INSIDE B', h['inb']), ('outside', ~h['inb'])):
    g = h[m]
    print(f"  {lab:>10} {g['kmh'].median():8.1f} {g['latg'].quantile(.9):10.2f} "
          f"{100*np.mean(g['brkf']>0.05):7.0f}% {g['thrf'].median():9.2f} {g['off'].abs().median():9.2f}")
gb = h[h['inb']]
print(f"  human lifts (throttle<0.2) on {100*np.mean(gb['thrf']<0.2):.0f}% of span-B ticks; "
      f"brakes on {100*np.mean(gb['brkf']>0.05):.0f}%")
print(f"  human lateral g p99 in span B: {gb['latg'].quantile(.99):.2f} "
      f"(lap-wide p99 {h['latg'].quantile(.99):.2f})")

# --- size the prize ----------------------------------------------------------
mp = np.load('recordings/vtrim_map.npz')['map'].astype(float)
idxw = (np.arange(N)[:, None] + np.arange(18)[None, :]) % N
mapw = mp[idxw].min(axis=1)
with np.load('recordings/surface_cap.npz') as sc:
    sfac = sc['fac'].astype(float)
A_LO, A_HI = float(t['mbc_a_lo']), float(t['mbc_a_hi'])
ina = (s_of >= A_LO) & (s_of <= A_HI)
SCK = float(t['speed_cap']) * 3.6
bind = b.groupby('st')['bind_code'].apply(lambda c: float(np.mean(c == 3)))
bz = [s for s in st_b if bind.get(s, 0) > 0.5]
print(f"\n=== SIZE OF THE PRIZE ({len(bz)} binding stations inside span B) ===")
import sys
sys.path.insert(0, '.')
from local_planner import LocalPlanner
cum = np.concatenate([[0.0], np.cumsum(seg)]); tot = float(cum[-1])
P2 = LocalPlanner(line, a_lat=27.0)
def caps(k):
    P2.ksp = k; o = np.empty(N)
    for i in range(N):
        ss = np.mod(np.linspace(cum[i], cum[i]+18.0, 16), tot)
        ix = np.clip(np.searchsorted(cum, ss, side='right')-1, 0, N-1)
        kk = P2.kappa_ref if k <= 0 else (P2.kappa_speed if k >= 1 else
                                          P2.kappa_ref + k*(P2.kappa_speed - P2.kappa_ref))
        o[i] = 3.6*np.sqrt(27.0/max(np.percentile(np.abs(kk[ix]), P2.kappa_pct)-0.0025, 1e-4))
    return o
C = {k: caps(k) for k in (0.0, 0.25, 1.0)}
print(f"  {'config':>34} {'eff target':>11} {'vs human 135.4':>15}")
for k in (0.0, 0.25, 1.0):
    for clamp, lab in ((True, 'clamped'), (False, 'LIFTED ')):
        # clamped: MBC applies in BOTH spans (shipped). lifted: span A only, B released.
        zone = (ina | inb) if clamp else ina
        mw = np.where(zone, np.minimum(mapw, 1.0), mapw)
        e = np.minimum(C[k]*mw*sfac, SCK)
        v = np.median(e[bz])
        print(f"  {'ksp='+str(k)+'  span B '+lab:>34} {v:11.1f} {v-135.4:+15.1f}")
