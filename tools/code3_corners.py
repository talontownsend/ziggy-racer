"""Split bind_code 3 (v_curve * map_w) per corner, against the human's 08-02 laps.

The tension this resolves: mean deficit at code-3 ticks is ~18 km/h, i.e. the car runs well
below the curvature-capped target even while that cap is the binding term. If that holds per
corner, raising the target is inert -- which is what the old "path is inert" arms found.

Three speeds at MATCHED stations, per corner:
  bot target  = tgt_kmh at code-3 ticks (= v_curve * map_w * trim * sfac)
  bot actual  = spd_kmh at those ticks
  human actual= speed at the same stations, 08-02 recording

Station mapping is nearest-point on the refline. VALIDATED against the bot's own logged i0:
median error 0 stations, 100% within 2, so the same mapping applied to the human's pos_x/pos_z
is sound.

Cap attribution: vcurve_kmh is logged as raw v_curve*3.6 (before map_w), so
  effective multiplier = tgt_kmh / vcurve_kmh
  ~1.0  -> raw curvature sets the cap
  <1.0  -> the learned map_w is cutting below the curvature limit
"""
import numpy as np
import pandas as pd

HUMAN = r'C:\Users\Talon\AppData\Local\FH6 TC\recording_20260802_073646.csv'
line = np.load('recordings/refline_plan.npz')['line']
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
N = len(line)

# ---- bot, code-3 ticks -------------------------------------------------------
need = ['t', 'race_pos', 'on_track', 'brk', 'tgt_kmh', 'spd_kmh', 'bind_code', 'i0', 'vcurve_kmh']
b = pd.read_csv('recordings/follow_log.csv', usecols=lambda c: c in need,
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce')
b = b.dropna(subset=['t', 'bind_code', 'i0', 'tgt_kmh', 'spd_kmh'])
b = b[(b['race_pos'] >= 1) & (b['on_track'] > 0.5) & (b['brk'] <= 0.05)]
t = b['t'].to_numpy()
dt = np.clip(np.diff(t, prepend=t[0]), 0, 0.10)
b = b.assign(_dt=dt, _def=(b['tgt_kmh'] - b['spd_kmh']))
c3 = b[(b['bind_code'] == 3) & (b['_def'] > 0)].copy()
c3['st'] = c3['i0'].astype(int) % N
print(f"code-3 under-target ticks: {len(c3):,}")

# ---- per-station deficit, then group into corners ----------------------------
g = c3.groupby('st').apply(lambda d: pd.Series({
    'kmhs': float((d['_def'] * d['_dt']).sum()),
    'n': len(d),
    'tgt': float(d['tgt_kmh'].median()),
    'act': float(d['spd_kmh'].median()),
    'vcur': float(d['vcurve_kmh'].median()) if 'vcurve_kmh' in d else np.nan,
}), include_groups=False)
full = pd.Series(0.0, index=range(N))
full.update(g['kmhs'])

hot = set(g.index[g['kmhs'] > np.percentile(g['kmhs'], 60)])
corners, cur = [], []
for i in range(N):
    if i in hot:
        cur.append(i)
    elif cur:
        if len(cur) >= 5:
            corners.append(cur)
        cur = []
if cur:
    corners.append(cur)
# stitch a wrap-around corner
if corners and corners[0][0] == 0 and corners[-1][-1] == N - 1:
    corners[0] = corners[-1] + corners[0]
    corners.pop()
corners.sort(key=lambda c: -sum(full[i] for i in c))
top = corners[:5]

# ---- human -------------------------------------------------------------------
hn = ['pos_x', 'pos_z', 'speed_mps', 'lap_no', 'cur_lap_time', 'is_race_on']
h = pd.read_csv(HUMAN, usecols=lambda c: c in hn, on_bad_lines='skip',
                low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
if 'is_race_on' in h:
    h = h[h['is_race_on'] > 0]
h = h[h['speed_mps'] > 1]
P = h[['pos_x', 'pos_z']].to_numpy()
st = np.empty(len(P), dtype=int)
CH = 20000
for i in range(0, len(P), CH):
    d2 = ((P[i:i + CH, None, :] - line[None, :, :]) ** 2).sum(2)
    st[i:i + CH] = d2.argmin(1)
    if i == 0:
        print(f"human nearest-point distance: mean {np.sqrt(d2.min(1)).mean():.2f} m "
              f"(bot's own is 1.76 m)")
h = h.assign(st=st, kmh=h['speed_mps'] * 3.6)
hmed = h.groupby('st')['kmh'].median()
print(f"human: {len(h):,} racing rows over {h['lap_no'].nunique()} laps\n")

# ---- report ------------------------------------------------------------------
print("=" * 96)
print("TOP 5 CORNERS BY code-3 DEFICIT   (speeds km/h, medians over matched stations)")
print(f"{'#':>2} {'stations':>13} {'s_m':>11} {'km/h-s':>8} {'ticks':>7} "
      f"{'botTGT':>7} {'botACT':>7} {'human':>7} {'h-tgt':>7} {'tgt-act':>8} {'mapw':>6}  cap set by")
for k, cor in enumerate(top, 1):
    sel = c3[c3['st'].isin(cor)]
    kmhs = float((sel['_def'] * sel['_dt']).sum())
    tgt = float(sel['tgt_kmh'].median())
    act = float(sel['spd_kmh'].median())
    vcur = float(sel['vcurve_kmh'].median())
    hh = hmed.reindex(cor).dropna()
    hum = float(hh.median()) if len(hh) else np.nan
    mapw = tgt / vcur if vcur > 1 else np.nan
    who = 'raw v_curve' if (mapw != mapw or mapw > 0.97) else f'map_w={mapw:.2f}'
    print(f"{k:>2} {min(cor):4d}-{max(cor):<8d} {s_of[min(cor)]:5.0f}-{s_of[max(cor)]:<5.0f} "
          f"{kmhs:8.0f} {len(sel):7,} {tgt:7.1f} {act:7.1f} {hum:7.1f} "
          f"{hum-tgt:+7.1f} {tgt-act:8.1f} {mapw:6.2f}  {who}")

print()
print("  h-tgt   = human actual MINUS bot target. >0 means the line caps below demonstrated speed.")
print("  tgt-act = how far the bot runs under its own capped target (the tracking gap).")
tot_h = np.nanmean([float(hmed.reindex(c).dropna().median()) - float(c3[c3['st'].isin(c)]['tgt_kmh'].median()) for c in top])
tot_g = np.mean([float(c3[c3['st'].isin(c)]['tgt_kmh'].median()) - float(c3[c3['st'].isin(c)]['spd_kmh'].median()) for c in top])
print(f"\n  mean over the 5 corners:  human-vs-bot-target {tot_h:+.1f} km/h    "
      f"bot under own target {tot_g:.1f} km/h")
print("\n  FORK: if human-vs-target is clearly positive -> rebuild the refline from 08-02.")
print("        if bot-under-own-target dominates      -> the corner problem is tracking.")
