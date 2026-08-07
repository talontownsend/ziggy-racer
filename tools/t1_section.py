"""start/T1 (stations 0-120): is the +0.44 s real, or standing-start contamination?

That section is uniquely exposed: a follower restart or a stall recovery puts a STANDING LAUNCH
at exactly that part of the track, and a launch lap is not a racing lap. Same for the human if
their recording opens from a standstill.

So: recompute the per-lap section time excluding every first lap after a restart or stall on the
bot side, and the human's opening lap if it launches. Report before and after. Only if the gap
survives is it decomposed per station.

The launch cap (bind_code 5) has a mean deficit of 51.8 km/h when it binds and has never been
located on track. If it lives anywhere, it lives here.
"""
import numpy as np
import pandas as pd

N = 1000
HUMAN = r'C:\Users\Talon\AppData\Local\FH6 TC\recording_20260802_073646.csv'
d = np.load('recordings/refline_plan.npz')
line = d['line']
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
LO, HI = 0, 120

# ---------------- bot ----------------
b = pd.read_csv('recordings/follow_log_BASE_0806.csv',
                usecols=['t', 'lap_t', 'race_pos', 'on_track', 'i0', 'spd_kmh', 'bind_code',
                         'cte_m', 'steer', 'brk', 'thr'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
b = b[b['race_pos'] >= 1].reset_index(drop=True)
t = b['t'].to_numpy()
lt = b['lap_t'].to_numpy()
sess = np.concatenate([[0], np.cumsum(t[1:] < t[:-1] - 5)])
lap = np.concatenate([[0], np.cumsum((lt[1:] < lt[:-1] - 0.05) | (np.diff(sess) != 0))])
b = b.assign(lap=lap, sess=sess, st=(b['i0'].astype(int) % N))

# a lap is CONTAMINATED if it is the first of a session, or it contains a near-stop (stall/launch)
first_of_sess = {int(b[b['sess'] == s]['lap'].iloc[0]) for s in b['sess'].unique()}
slow = set(b[b['spd_kmh'] < 8]['lap'].unique())          # any near-stop in the lap
prev_slow = {L + 1 for L in slow}                        # the lap AFTER a stall relaunches
bad = first_of_sess | slow | prev_slow
print(f"bot: {b['lap'].nunique()} laps, {len(first_of_sess)} session-firsts, "
      f"{len(slow)} laps containing a near-stop")
print(f"     -> {len(bad & set(b['lap'].unique()))} laps excluded as launch/stall-contaminated")


def sect(df, tcol, keep=None):
    v = []
    for L in df['lap'].unique():
        if keep is not None and L not in keep:
            continue
        m = (df['lap'] == L) & (df['st'] >= LO) & (df['st'] < HI)
        if m.sum() < 20:
            continue
        span = df.loc[m, tcol].max() - df.loc[m, tcol].min()
        if 0.5 < span < 30.0:
            v.append(span)
    return (float(np.median(v)) if len(v) >= 5 else float('nan')), len(v)


all_laps = set(b['lap'].unique())
clean = all_laps - bad
b_all, nb_all = sect(b, 't')
b_cln, nb_cln = sect(b, 't', clean)

# ---------------- human ----------------
h = pd.read_csv(HUMAN, usecols=['pos_x', 'pos_z', 'speed_mps', 'is_race_on', 'cur_lap_time',
                                'timestamp_ms', 'accel', 'brake'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
h = h[h['is_race_on'] > 0].reset_index(drop=True)
P = h[['pos_x', 'pos_z']].to_numpy()
hs = np.empty(len(P), dtype=int)
for i in range(0, len(P), 20000):
    hs[i:i+20000] = ((P[i:i+20000, None, :] - line[None, :, :]) ** 2).sum(2).argmin(1)
hl = h['cur_lap_time'].to_numpy()
h = h.assign(st=hs, lap=np.concatenate([[0], np.cumsum(hl[1:] < hl[:-1] - 0.05)]),
             tsec=h['timestamp_ms'] / 1000.0, kmh=h['speed_mps'] * 3.6)
h0 = h[h['lap'] == h['lap'].min()]
launches = h0['speed_mps'].min() < 2.0
print(f"human: {h['lap'].nunique()} laps; opening lap min speed {h0['speed_mps'].min()*3.6:.1f} km/h"
      f"  -> {'STANDING LAUNCH, excluded' if launches else 'rolling, kept'}")
hslow = set(h[h['speed_mps'] < 2.0]['lap'].unique())
hkeep = set(h['lap'].unique()) - hslow - {h['lap'].min()} if launches else set(h['lap'].unique()) - hslow
h = h[h['speed_mps'] > 1]
h_all, nh_all = sect(h, 'tsec')
h_cln, nh_cln = sect(h, 'tsec', hkeep)

print("\n=== start/T1 SECTION GAP, BEFORE vs AFTER excluding launch laps ===")
print(f"  {'':>22} {'bot s':>8} {'n':>5} {'human s':>9} {'n':>5} {'gap':>8}")
print(f"  {'all laps (as budgeted)':>22} {b_all:8.2f} {nb_all:5d} {h_all:9.2f} {nh_all:5d} "
      f"{b_all-h_all:+8.2f}")
print(f"  {'launch laps excluded':>22} {b_cln:8.2f} {nb_cln:5d} {h_cln:9.2f} {nh_cln:5d} "
      f"{b_cln-h_cln:+8.2f}")
surv = (b_cln - h_cln)
print(f"\n  the +{b_all-h_all:.2f} s becomes +{surv:.2f} s  "
      f"({100*surv/max(b_all-h_all,1e-9):.0f}% survives)")

if surv < 0.15:
    print("\n  VERDICT: most of it was contamination. Budget correction, not a target.")
else:
    print("\n=== the gap survives -- decomposing per station ===")
    bb = b[b['lap'].isin(clean)]
    hh = h[h['lap'].isin(hkeep)]
    print(f"  {'stations':>11} {'s_m':>10} {'m':>5} {'bot s':>7} {'hum s':>7} {'lost':>7} "
          f"{'code5%':>7} {'code1%':>7} {'code3%':>7} {'bot kmh':>8} {'hum kmh':>8}")
    rows = []
    for lo in range(LO, HI, 20):
        hi = min(lo + 20, HI)
        vb, _ = sect(bb.assign(st=bb['st']), 't', clean) if False else (np.nan, 0)
        sl_b = bb[(bb['st'] >= lo) & (bb['st'] < hi)]
        sl_h = hh[(hh['st'] >= lo) & (hh['st'] < hi)]
        tb = []
        for L in sl_b['lap'].unique():
            g = sl_b[sl_b['lap'] == L]
            if len(g) > 4:
                sp = g['t'].max() - g['t'].min()
                if 0.05 < sp < 10:
                    tb.append(sp)
        th = []
        for L in sl_h['lap'].unique():
            g = sl_h[sl_h['lap'] == L]
            if len(g) > 4:
                sp = g['tsec'].max() - g['tsec'].min()
                if 0.05 < sp < 10:
                    th.append(sp)
        if len(tb) < 5 or len(th) < 5:
            continue
        mb, mh = float(np.median(tb)), float(np.median(th))
        rows.append((mb - mh, lo, hi))
        print(f"  {lo:4d}-{hi-1:<6d} {s_of[lo]:4.0f}-{s_of[hi-1]:<5.0f} {seg[lo:hi].sum():5.0f} "
              f"{mb:7.2f} {mh:7.2f} {mb-mh:+7.2f} "
              f"{100*np.mean(sl_b['bind_code']==5):6.0f}% {100*np.mean(sl_b['bind_code']==1):6.0f}% "
              f"{100*np.mean(sl_b['bind_code']==3):6.0f}% "
              f"{sl_b['spd_kmh'].median():8.1f} {sl_h['kmh'].median():8.1f}")
    print(f"\n  LAUNCH CAP (bind_code 5) across the whole lap, clean laps only:")
    c5 = bb[bb['bind_code'] == 5]
    print(f"    {len(c5):,} ticks ({100*len(c5)/len(bb):.2f}%)")
    if len(c5):
        print(f"    stations: {int(c5['st'].min())}-{int(c5['st'].max())}, "
              f"median {int(c5['st'].median())}  (s={s_of[int(c5['st'].median())]:.0f} m)")
        print(f"    speed there {c5['spd_kmh'].median():.1f} km/h")
