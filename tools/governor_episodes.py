"""Map every cross-track-governor episode, then trace where corner 1's excursion is born.

The governor (bind_code 6) is the symptom: it fires because |cte| > cte_soft. The excursion is
the disease. This answers (a) whether corner 1's entry is the dominant episode or one of many,
and (b) where along the lap the corner-1 error actually starts growing.

`bind_free` is logged as target_v after codes 1/2 and BEFORE the 3-8 clamps, so it is the
ungoverned reference for how much the governor denies.
"""
import numpy as np
import pandas as pd

N = 1000
line = np.load('recordings/refline_plan.npz')['line']
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]

cols = ['t', 'lap_t', 'race_pos', 'on_track', 'i0', 'bind_code', 'bind_free',
        'cte_m', 'tgt_kmh', 'spd_kmh', 'steer', 'brk', 'thr']
b = pd.read_csv('recordings/follow_log.csv', usecols=lambda c: c in cols,
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce')
b = b.dropna(subset=['i0', 'bind_code', 'cte_m', 'lap_t'])
b = b[(b['race_pos'] >= 1) & (b['on_track'] > 0.5)].reset_index(drop=True)
b['st'] = b['i0'].astype(int) % N
b['acte'] = b['cte_m'].abs()

# lap index from lap_t resets
lt = b['lap_t'].to_numpy()
lap = np.concatenate([[0], np.cumsum(lt[1:] < lt[:-1] - 0.05)])
b['lap'] = lap
nlaps = int(lap.max()) + 1
print(f"{len(b):,} racing on-track ticks across {nlaps} lap segments\n")

# ---- episodes: contiguous governed runs within a lap ------------------------
g6 = (b['bind_code'] == 6).to_numpy()
brk_new = np.concatenate([[True], (np.diff(lap) != 0) | (~g6[1:]) | (~g6[:-1])])
eps = []
i = 0
arr = b.to_dict('list')
while i < len(b):
    if not g6[i]:
        i += 1; continue
    j = i
    while j + 1 < len(b) and g6[j + 1] and lap[j + 1] == lap[i]:
        j += 1
    sl = b.iloc[i:j + 1]
    if len(sl) >= 10:
        free = sl['bind_free'].median() if 'bind_free' in sl else np.nan
        eps.append(dict(lap=int(lap[i]), s0=int(sl['st'].iloc[0]), s1=int(sl['st'].iloc[-1]),
                        n=len(sl), cte0=float(sl['acte'].iloc[0]), ctemax=float(sl['acte'].max()),
                        tgt=float(sl['tgt_kmh'].median()), free=float(free),
                        spd=float(sl['spd_kmh'].median())))
    i = j + 1
E = pd.DataFrame(eps)
print(f"{len(E)} governor episodes (>=10 ticks)\n")

# group episodes by where they start
E['zone'] = (E['s0'] // 25) * 25
grp = E.groupby('zone').agg(episodes=('n', 'size'), laps=('lap', 'nunique'),
                            med_ticks=('n', 'median'), entry_cte=('cte0', 'median'),
                            max_cte=('ctemax', 'median'), tgt=('tgt', 'median'),
                            free=('free', 'median'), spd=('spd', 'median')).reset_index()
grp['denied'] = grp['free'] - grp['tgt']
grp['tick_share'] = grp['episodes'] * grp['med_ticks']
grp = grp.sort_values('tick_share', ascending=False)
print("GOVERNOR EPISODES BY ZONE (25-station bins, ranked by total governed ticks)")
print(f"  {'zone':>6} {'s_m':>6} {'eps':>5} {'laps':>5} {'ticks':>6} {'entry|cte|':>11} "
      f"{'max|cte|':>9} {'tgt':>7} {'free':>7} {'denied':>7}")
for _, r in grp.head(12).iterrows():
    print(f"  {int(r['zone']):6d} {s_of[int(r['zone'])]:6.0f} {int(r['episodes']):5d} "
          f"{int(r['laps']):5d} {int(r['tick_share']):6d} {r['entry_cte']:11.2f} "
          f"{r['max_cte']:9.2f} {r['tgt']:7.1f} {r['free']:7.1f} {r['denied']:7.1f}")
tot = grp['tick_share'].sum()
top = grp.iloc[0]
print(f"\n  total governed ticks in episodes: {int(tot):,}")
print(f"  dominant zone {int(top['zone'])}-{int(top['zone'])+24} (s={s_of[int(top['zone'])]:.0f} m): "
      f"{100*top['tick_share']/tot:.0f}% of all governed ticks, in {int(top['laps'])}/{nlaps} laps")

# ---- where is the corner-1 excursion born? ---------------------------------
print(f"\n\nWHERE DOES THE CORNER-1 EXCURSION START?  per-station |cte|, median over laps")
print(f"  {'stn':>5} {'s_m':>6} {'|cte|':>6} {'d|cte|':>7} {'spd':>6} {'steer':>6} "
      f"{'brk%':>5} {'thr':>5} {'gov%':>5}")
prev = None
rows = []
for st in range(690, 800, 2):
    sl = b[b['st'] == st]
    if len(sl) < 30:
        continue
    a = float(sl['acte'].median())
    d = np.nan if prev is None else a - prev
    prev = a
    rows.append((st, a, d))
    print(f"  {st:5d} {s_of[st]:6.0f} {a:6.2f} {d:+7.2f} {sl['spd_kmh'].median():6.1f} "
          f"{sl['steer'].median():+6.2f} {100*np.mean(sl['brk']>0.05):4.0f}% "
          f"{sl['thr'].median():5.2f} {100*np.mean(sl['bind_code']==6):4.0f}%")
R = pd.DataFrame(rows, columns=['st', 'cte', 'd'])
grow = R[R['d'] > 0.05]
if len(grow):
    print(f"\n  |cte| first grows persistently at station {int(grow['st'].iloc[0])} "
          f"(s={s_of[int(grow['st'].iloc[0])]:.0f} m), |cte| {grow['cte'].iloc[0]:.2f} m")
    k = R['d'].idxmax()
    print(f"  fastest growth at station {int(R.loc[k,'st'])} (s={s_of[int(R.loc[k,'st'])]:.0f} m): "
          f"{R.loc[k,'d']:+.2f} m/2 stations")

# is it the same place every lap?
print(f"\n  CONSISTENCY: per-lap station where |cte| first exceeds 5.0 m in 700-800")
firsts = []
for L in range(nlaps):
    sl = b[(b['lap'] == L) & (b['st'] >= 700) & (b['st'] <= 800) & (b['acte'] > 5.0)]
    if len(sl):
        firsts.append(int(sl['st'].iloc[0]))
if firsts:
    f = np.array(firsts)
    print(f"    {len(f)} of {nlaps} laps cross 5.0 m here; station median {np.median(f):.0f}, "
          f"p10 {np.percentile(f,10):.0f}, p90 {np.percentile(f,90):.0f}, sd {f.std():.1f}")
    print(f"    -> {'SAME PLACE EVERY LAP (sd < 8 stations)' if f.std() < 8 else 'VARIABLE across laps'}")
