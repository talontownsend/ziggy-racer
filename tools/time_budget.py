"""Where the lap-time gap to the human actually lives, by section.

Robust method: for each LAP, measure the time spent in each section from the telemetry clock at
section entry and exit, then take the median across laps. Compare to the same for the human.

NOT median-speed-based. A per-station median speed is destroyed by sparse stations: station 714
has a bot median of 3.9 km/h (a stall artifact in a handful of samples) and single-handedly
contributed 0.99 s of a 1.11 s section estimate. Per-lap section times cannot do that -- a lap
either spent the time or it did not.
"""
import numpy as np
import pandas as pd

N = 1000
HUMAN = r'C:\Users\Talon\AppData\Local\FH6 TC\recording_20260802_073646.csv'
d = np.load('recordings/refline_plan.npz')
line = d['line']
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]

SEC = [(0, 120, 'start / T1'), (120, 260, 'S2'), (260, 340, 'fast 260-340'),
       (340, 470, 'S4-S5'), (470, 610, 'MBC span A'), (610, 700, 'corner 2 + MBC span B'),
       (700, 745, 'approach to the excursion'), (745, 800, 'EXCURSION born + governed'),
       (800, 850, 'corner 1 (inherits)'), (850, 930, 'corner 3 (inherits)'),
       (930, 1000, 'main straight')]


def section_times(t, st, lap):
    """Median seconds each lap spends in each section."""
    out = {lab: [] for _, _, lab in SEC}
    for L in np.unique(lap):
        m = lap == L
        tt, ss = t[m], st[m]
        if len(tt) < 200:
            continue
        for a, z, lab in SEC:
            inb = (ss >= a) & (ss < z)
            if inb.sum() < 5:
                continue
            span = tt[inb].max() - tt[inb].min()
            if 0.05 < span < 15.0:            # a section is never 15 s on a clean lap
                out[lab].append(span)
    return {k: (float(np.median(v)) if len(v) >= 5 else float('nan')) for k, v in out.items()}, \
           {k: len(v) for k, v in out.items()}


# ---- bot ----
b = pd.read_csv('recordings/follow_log_BASE_0806.csv',
                usecols=['t', 'lap_t', 'race_pos', 'on_track', 'i0', 'spd_kmh', 'bind_code'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
b = b[(b['race_pos'] >= 1) & (b['on_track'] > 0.5)].reset_index(drop=True)
lt = b['lap_t'].to_numpy()
blap = np.concatenate([[0], np.cumsum(lt[1:] < lt[:-1] - 0.05)])
bt = section_times(b['t'].to_numpy(), (b['i0'].astype(int) % N).to_numpy(), blap)

# ---- human ----
h = pd.read_csv(HUMAN, usecols=['pos_x', 'pos_z', 'speed_mps', 'is_race_on', 'cur_lap_time',
                                'timestamp_ms'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
h = h[(h['is_race_on'] > 0) & (h['speed_mps'] > 1)].reset_index(drop=True)
P = h[['pos_x', 'pos_z']].to_numpy()
hs = np.empty(len(P), dtype=int)
for i in range(0, len(P), 20000):
    hs[i:i+20000] = ((P[i:i+20000, None, :] - line[None, :, :]) ** 2).sum(2).argmin(1)
hl = h['cur_lap_time'].to_numpy()
hlap = np.concatenate([[0], np.cumsum(hl[1:] < hl[:-1] - 0.05)])
ht = section_times(h['timestamp_ms'].to_numpy() / 1000.0, hs, hlap)

gov = b.groupby((b['i0'].astype(int) % N))['bind_code'].apply(lambda c: float(np.mean(c == 6)))

print("TIME BUDGET BY SECTION -- median per-lap section time, bot vs human")
print(f"  {'section':>28} {'m':>6} {'bot s':>7} {'human s':>8} {'lost':>7} {'% gap':>7} "
      f"{'laps b/h':>10} {'gov%':>6}")
rows = []
for a, z, lab in SEC:
    L = seg[a:z].sum()
    vb, vh = bt[0][lab], ht[0][lab]
    if np.isnan(vb) or np.isnan(vh):
        print(f"  {lab:>28} {L:6.0f}   insufficient laps")
        continue
    rows.append((vb - vh, lab, L, vb, vh, bt[1][lab], ht[1][lab],
                 100 * np.mean([gov.get(s, 0) for s in range(a, z)])))
tot = sum(r[0] for r in rows)
for loss, lab, L, vb, vh, nb, nh, g in rows:
    print(f"  {lab:>28} {L:6.0f} {vb:7.2f} {vh:8.2f} {loss:+7.2f} {100*loss/tot:6.1f}% "
          f"{nb:5d}/{nh:<4d} {g:5.1f}%")
print(f"  {'TOTAL':>28} {seg.sum():6.0f} {sum(r[3] for r in rows):7.2f} "
      f"{sum(r[4] for r in rows):8.2f} {tot:+7.2f}")
print("\n  ranked:")
for loss, lab, *_ in sorted(rows, reverse=True):
    print(f"    {lab:<32} {loss:+.2f} s  ({100*loss/tot:.0f}%)")
gsec = [r for r in rows if r[7] > 5]
print(f"\n  sections where the governor binds >5% of ticks: "
      f"{sum(r[0] for r in gsec):+.2f} s ({100*sum(r[0] for r in gsec)/tot:.0f}% of the gap)")
