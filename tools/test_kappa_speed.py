"""Acceptance tests for the speed-path kappa split (ksp_on).

TEST 1 (safety): the steering feedforward must be BIT-IDENTICAL with ksp_on off vs on, over a
full replayed lap of real logged states. kappa_ref is dual-use and widening its smoothing
previously caused understeer and off-tracks; the whole point of this change is that the FF
source is untouched. Any difference at all fails.

TEST 2 (efficacy): the replayed v_curve with ksp_on must reproduce the offline w=9 numbers at
the three binding zones: 112.2 / 173.4 / 206.9 km/h.

Replays logged (x, z, heading, speed) through the real planner. No game, no follower.
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, '.')
from local_planner import LocalPlanner

ALAT, AK = 27.0, 0.0025
BIND = {'corner 2': (np.arange(595, 608), 112.2),
        'corner 1': (np.arange(815, 846), 173.4),
        'corner 3': (np.arange(900, 915), 206.9)}

d = np.load('recordings/refline_plan.npz')
line = d['line']
N = len(line)

cols = ['race_pos', 'on_track', 'i0', 'x', 'z', 'yaw', 'spd_kmh', 'lap_t', 't']
b = pd.read_csv('recordings/follow_log.csv', usecols=lambda c: c in cols,
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce')
have = set(b.columns)
hcol = 'yaw' if 'yaw' in have else None
b = b.dropna(subset=[c for c in ('x', 'z', 'spd_kmh', 'i0') if c in have])
b = b[(b['race_pos'] >= 1) & (b['on_track'] > 0.5)]
if hcol is None:                       # derive heading from successive positions
    dx = np.diff(b['x'].to_numpy(), prepend=b['x'].to_numpy()[0])
    dz = np.diff(b['z'].to_numpy(), prepend=b['z'].to_numpy()[0])
    head = np.arctan2(dz, dx)
else:
    head = b[hcol].to_numpy()
# one full lap of states
lt = b['lap_t'].to_numpy() if 'lap_t' in have else None
if lt is not None:
    r = np.where(np.diff(lt) < -0.05)[0]
    lo, hi = (r[0] + 1, r[1] + 1) if len(r) >= 2 else (0, min(len(b), 3000))
else:
    lo, hi = 0, min(len(b), 3000)
X = b['x'].to_numpy()[lo:hi]; Z = b['z'].to_numpy()[lo:hi]
H = head[lo:hi]; V = b['spd_kmh'].to_numpy()[lo:hi] / 3.6
I = b['i0'].to_numpy()[lo:hi].astype(int) % N
print(f"replaying {len(X)} logged states (one lap)\n")

pl_a = LocalPlanner(line, a_lat=ALAT)          # ksp_on OFF
pl_b = LocalPlanner(line, a_lat=ALAT)          # ksp_on ON
pl_b.use_speed_kappa = True

print(f"kappa_speed differs from kappa_ref on "
      f"{100*np.mean(np.abs(pl_b.kappa_speed - pl_b.kappa_ref) > 1e-12):.0f}% of stations "
      f"(max |diff| {np.max(np.abs(pl_b.kappa_speed - pl_b.kappa_ref)):.5f})")

ff_a, ff_b, kat_a, kat_b, vc_a, vc_b, sts = [], [], [], [], [], [], []
for x, z, h_, v, i in zip(X, Z, H, V, I):
    pa = pl_a.plan(float(x), float(z), float(h_), float(v), i_hint=int(i))
    pb = pl_b.plan(float(x), float(z), float(h_), float(v), i_hint=int(i))
    ff_a.append(pl_a.kappa_line_ahead(pa, 8.0)); ff_b.append(pl_b.kappa_line_ahead(pb, 8.0))
    kat_a.append(pl_a.kappa_at(pa, 8.0));        kat_b.append(pl_b.kappa_at(pb, 8.0))
    ka = pl_a.max_kappa_line_ahead(pa, 18.0);    kb = pl_b.max_kappa_line_ahead(pb, 18.0)
    vc_a.append(3.6*np.sqrt(ALAT/max(abs(ka)-AK, 1e-4)))
    vc_b.append(3.6*np.sqrt(ALAT/max(abs(kb)-AK, 1e-4)))
    sts.append(int(i))
ff_a, ff_b = np.array(ff_a), np.array(ff_b)
kat_a, kat_b = np.array(kat_a), np.array(kat_b)
vc_a, vc_b, sts = np.array(vc_a), np.array(vc_b), np.array(sts)

print("\n=== TEST 1: steering FF bit-identical ===")
t1a = np.array_equal(ff_a, ff_b)
t1b = np.array_equal(kat_a, kat_b)
print(f"  kappa_line_ahead (ff_use_line source): identical = {t1a}"
      f"   max |diff| {np.max(np.abs(ff_a-ff_b)):.3e}")
print(f"  kappa_at         (merge FF source)   : identical = {t1b}"
      f"   max |diff| {np.max(np.abs(kat_a-kat_b)):.3e}")
T1 = t1a and t1b
print(f"  TEST 1 {'PASS' if T1 else 'FAIL'}")

print("\n=== TEST 2: v_curve reproduces the offline w=9 numbers ===")
print(f"  {'zone':>10} {'ksp OFF':>9} {'ksp ON':>9} {'expected':>9} {'err':>7}")
T2 = True
for lab, (z, exp) in BIND.items():
    m = np.isin(sts, z)
    if m.sum() < 5:
        print(f"  {lab:>10}   (only {m.sum()} replayed ticks in zone)")
        continue
    on, off = np.median(vc_b[m]), np.median(vc_a[m])
    err = on - exp
    if abs(err) > 3.0:
        T2 = False
    print(f"  {lab:>10} {off:9.1f} {on:9.1f} {exp:9.1f} {err:+7.1f}")
print(f"  TEST 2 {'PASS' if T2 else 'FAIL'}  (tolerance +/-3 km/h)")

print(f"\nOVERALL: {'PASS' if (T1 and T2) else 'FAIL'}")
sys.exit(0 if (T1 and T2) else 1)
