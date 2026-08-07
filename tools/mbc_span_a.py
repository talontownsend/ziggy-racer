"""MBC span A (s=470-608): the largest single section on the lap. Same treatment span B got.

Span A costs +0.75 s, 23% of the 3.32 s gap, and nothing tests it. The question is whether the
MBC clamp is holding real speed hostage on non-crest track -- in which case an `rzc`-style
released-zone arm falls out -- or whether the 0.75 s accumulates somewhere the clamp never
touches, in which case span A closes as a target.

Verdict must be as clear as span B's, so this asks all four questions at once:
  1. WHERE does the 0.75 s accumulate, station by station (per-lap section timing, not medians)
  2. WHICH bind code fires there
  3. IS THE CLAMP EVEN BINDING -- stored map vs 1.0, station by station
  4. GEOMETRY -- d2z/ds2 profile and zero crossings against the 470/608 boundaries
  plus the incident picture inside the span.
"""
import json
import numpy as np
import pandas as pd

N = 1000
HUMAN = r'C:\Users\Talon\AppData\Local\FH6 TC\recording_20260802_073646.csv'
d = np.load('recordings/refline_plan.npz')
line, elev = d['line'], d['elev']
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
t = json.load(open('recordings/tune.json'))
A_LO, A_HI = float(t['mbc_a_lo']), float(t['mbc_a_hi'])
ina = (s_of >= A_LO) & (s_of <= A_HI)
sa = np.where(ina)[0]
zz = np.gradient(np.gradient(elev, s_of), s_of)
mp = np.load('recordings/vtrim_map.npz')['map'].astype(float)
idxw = (np.arange(N)[:, None] + np.arange(18)[None, :]) % N
mapw = mp[idxw].min(axis=1)

print(f"MBC span A: s={A_LO:.0f}-{A_HI:.0f} m = stations {sa.min()}-{sa.max()} ({len(sa)} stations, "
      f"{seg[sa].sum():.0f} m)")

# ---- bot & human, per lap ------------------------------------------------------
b = pd.read_csv('recordings/follow_log_BASE_0806.csv',
                usecols=['t', 'lap_t', 'race_pos', 'on_track', 'i0', 'spd_kmh', 'bind_code',
                         'cte_m', 'sideslip', 'steer', 'brk'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
b = b[(b['race_pos'] >= 1) & (b['on_track'] > 0.5)].reset_index(drop=True)
lt = b['lap_t'].to_numpy()
blap = np.concatenate([[0], np.cumsum(lt[1:] < lt[:-1] - 0.05)])
b = b.assign(lap=blap, st=(b['i0'].astype(int) % N))

h = pd.read_csv(HUMAN, usecols=['pos_x', 'pos_z', 'speed_mps', 'is_race_on', 'cur_lap_time',
                                'timestamp_ms', 'brake', 'accel', 'ax'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
h = h[(h['is_race_on'] > 0) & (h['speed_mps'] > 1)].reset_index(drop=True)
P = h[['pos_x', 'pos_z']].to_numpy()
hs = np.empty(len(P), dtype=int)
for i in range(0, len(P), 20000):
    hs[i:i+20000] = ((P[i:i+20000, None, :] - line[None, :, :]) ** 2).sum(2).argmin(1)
hl = h['cur_lap_time'].to_numpy()
h = h.assign(st=hs, lap=np.concatenate([[0], np.cumsum(hl[1:] < hl[:-1] - 0.05)]),
             tsec=h['timestamp_ms'] / 1000.0, kmh=h['speed_mps'] * 3.6)


def sub_times(df, tcol, lo, hi):
    """median per-lap seconds spent in [lo,hi) -- robust, never median-speed based."""
    v = []
    for L in df['lap'].unique():
        m = (df['lap'] == L) & (df['st'] >= lo) & (df['st'] < hi)
        if m.sum() < 4:
            continue
        span = df.loc[m, tcol].max() - df.loc[m, tcol].min()
        if 0.02 < span < 12.0:
            v.append(span)
    return float(np.median(v)) if len(v) >= 5 else float('nan'), len(v)


print("\n=== 1. WHERE does the 0.75 s accumulate?  (per-lap sub-section times) ===")
print(f"  {'stations':>12} {'s_m':>11} {'m':>5} {'bot s':>7} {'hum s':>7} {'lost':>7} "
      f"{'code3%':>7} {'code1%':>7} {'clamp binds%':>13}")
rows = []
for lo in range(sa.min(), sa.max() + 1, 15):
    hi = min(lo + 15, sa.max() + 1)
    vb, nb = sub_times(b, 't', lo, hi)
    vh, nh = sub_times(h, 'tsec', lo, hi)
    if np.isnan(vb) or np.isnan(vh):
        continue
    sl = b[(b['st'] >= lo) & (b['st'] < hi)]
    c3 = 100 * np.mean(sl['bind_code'] == 3)
    c1 = 100 * np.mean(sl['bind_code'] == 1)
    binds = 100 * np.mean(mapw[lo:hi] > 1.0)      # clamp only bites where window-min exceeds 1.0
    rows.append((vb - vh, lo, hi, seg[lo:hi].sum(), vb, vh, c3, c1, binds))
    print(f"  {lo:5d}-{hi-1:<6d} {s_of[lo]:5.0f}-{s_of[hi-1]:<5.0f} {seg[lo:hi].sum():5.0f} "
          f"{vb:7.2f} {vh:7.2f} {vb-vh:+7.2f} {c3:6.0f}% {c1:6.0f}% {binds:12.0f}%")
tot = sum(r[0] for r in rows)
print(f"  {'TOTAL':>12} {'':>11} {seg[sa].sum():5.0f} {sum(r[4] for r in rows):7.2f} "
      f"{sum(r[5] for r in rows):7.2f} {tot:+7.2f}")
print("\n  worst sub-sections:")
for loss, lo, hi, L, vb, vh, c3, c1, binds in sorted(rows, reverse=True)[:3]:
    print(f"    stations {lo}-{hi-1} (s={s_of[lo]:.0f}-{s_of[hi-1]:.0f}): {loss:+.2f} s, "
          f"code3 {c3:.0f}%, clamp binds on {binds:.0f}% of stations")

print("\n=== 2-3. IS THE CLAMP EVEN BINDING?  stored map vs the 1.0 cap ===")
above = mapw[sa] > 1.0
print(f"  stations where window-min map > 1.0 (clamp actually bites): {above.sum()} of {len(sa)} "
      f"({100*above.mean():.0f}%)")
print(f"  window-min inside span A: min {mapw[sa].min():.3f}  median {np.median(mapw[sa]):.3f}  "
      f"max {mapw[sa].max():.3f}")
print(f"  stored map inside span A: at the 1.55 ceiling on {100*np.mean(mp[sa] >= 1.549):.0f}% "
      f"of stations, at the 0.80 floor on {100*np.mean(mp[sa] <= 0.801):.0f}%")
c3a = 100 * np.mean(b[b['st'].isin(sa)]['bind_code'] == 3)
print(f"  bind_code 3 (v_curve * map_w) fires on {c3a:.0f}% of span-A ticks")

print("\n=== 4. GEOMETRY: d2z/ds2 against the 470 / 608 boundaries ===")
print(f"  {'stn':>5} {'s_m':>6} {'d2z/ds2':>10}  {'':>8}")
for i in range(sa.min() - 12, sa.min() + 10, 2):
    mark = ' <- mbc_a_lo' if abs(s_of[i] - A_LO) < 1.2 else ''
    print(f"  {i:5d} {s_of[i]:6.0f} {zz[i]:+10.5f}  {'CONVEX' if zz[i] < 0 else 'concave':>8}{mark}")
print("   ...")
for i in range(sa.max() - 8, sa.max() + 12, 2):
    mark = ' <- mbc_a_hi' if abs(s_of[i] - A_HI) < 1.2 else ''
    print(f"  {i:5d} {s_of[i]:6.0f} {zz[i]:+10.5f}  {'CONVEX' if zz[i] < 0 else 'concave':>8}{mark}")
print(f"\n  fraction of span A that is actually convex (crest): {100*np.mean(zz[sa] < 0):.0f}%")

print("\n=== INCIDENTS inside span A ===")
inA = b['st'].isin(sa)
for lab, m in (('inside A', inA), ('rest of lap', ~inA)):
    g = b[m]
    print(f"  {lab:>12} {len(g):8,} ticks  off-track {100*np.mean(g['on_track'] <= 0.5):5.2f}%  "
          f"sideslip p99 {g['sideslip'].abs().quantile(.99):5.2f}  |cte| p90 {g['cte_m'].abs().quantile(.9):5.2f}")

print("\n=== BOT vs HUMAN behaviour inside span A ===")
gb, gh = b[inA], h[h['st'].isin(sa)]
print(f"  bot   speed median {gb['spd_kmh'].median():6.1f}  brake {100*np.mean(gb['brk']>0.05):3.0f}%  "
      f"|steer| {gb['steer'].abs().median():.2f}")
print(f"  human speed median {gh['kmh'].median():6.1f}  brake {100*np.mean(gh['brake']/255>0.05):3.0f}%  "
      f"lat g p90 {(gh['ax'].abs()/9.81).quantile(.9):.2f}")
