"""Rescore archived arms on BOTH axes: clean-lap median and incident rate.

A clean-lap median alone can exonerate an arm that is wrecking the car, because dirty
laps are excluded rather than counted. The old lap_no keying accidentally folded incidents
into the median (more restarts -> more merging -> higher median). Splitting that back into
two honest numbers:

  pace      = median of clean laps
  incidents = share of lap attempts that were NOT clean, plus laps/hour of racing
"""
import os, numpy as np, pandas as pd

NEED = ['t', 'lap_t', 'on_track', 'race_pos']
PAIRS = [
    ('spin substitution',      'follow_log_SPINBASE_0802.csv',   'follow_log_SPINSUBST_0802.csv'),
    ('pad clamp (TC)',         'follow_log_FROZENBASE_0802.csv', 'follow_log_PADCLAMP_TC_0802.csv'),
    ('pad clamp (arm)',        'follow_log_FROZENBASE_0802.csv', 'follow_log_PADCLAMP_ARM_0802.csv'),
    ('throttle wrap off',      'follow_log_FROZENBASE_0802.csv', 'follow_log_WRAPOFF_0802.csv'),
    ('net refit',              'follow_log_FROZENBASE_0802.csv', 'follow_log_REFIT_2996_0802.csv'),
]


def scan(nm):
    for p in (os.path.join('recordings', nm), os.path.join('recordings', 'archive_logs', nm)):
        if os.path.exists(p):
            break
    else:
        return None
    T, LT, OT, SP = [], [], [], []
    cols = NEED + ['spd_kmh']
    for ch in pd.read_csv(p, usecols=cols, chunksize=1_000_000,
                          on_bad_lines='skip', low_memory=False):
        ch = ch.apply(pd.to_numeric, errors='coerce').dropna()
        ch = ch[ch['race_pos'] >= 1]
        if not len(ch):
            continue
        T.append(ch['t'].to_numpy()); LT.append(ch['lap_t'].to_numpy())
        OT.append(ch['on_track'].to_numpy()); SP.append(ch['spd_kmh'].to_numpy())
    if not T:
        return None
    t = np.concatenate(T); lt = np.concatenate(LT)
    ot = np.concatenate(OT); sp = np.concatenate(SP)

    reset = np.where(lt[1:] < lt[:-1] - 0.05)[0] + 1
    bounds = np.concatenate(([0], reset, [len(t)]))
    clean, dirty, gapped = [], 0, 0
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a < 50 or b >= len(t):
            continue
        d = float(lt[b - 1])
        if not (24 < d < 70):
            continue
        g = np.diff(t[a:b])
        if len(g) and g.max() > 2.0:
            gapped += 1; continue
        if np.mean(ot[a:b] > 0.5) <= 0.97:
            dirty += 1; continue
        if lt[a] >= 0.5:
            continue
        clean.append(d)
    hours = (t.max() - t.min()) / 3600.0
    att = len(clean) + dirty + gapped
    # stalls: >1 s continuous below 5 km/h, deduped at 60 s
    slow = sp < 5
    st, run, last = 0, 0, -1e9
    for i in range(len(slow)):
        run = run + 1 if slow[i] else 0
        if run == 70 and t[i] - last > 60:
            st += 1; last = t[i]
    return dict(n=len(clean), med=float(np.median(clean)) if clean else None,
                p25=float(np.percentile(clean, 25)) if clean else None,
                dirty=dirty, gapped=gapped, att=att, hours=hours,
                lph=len(clean) / hours if hours else 0,
                dirty_pct=100.0 * dirty / att if att else 0, stalls=st,
                stalls_ph=st / hours if hours else 0)


print(f"{'arm':<22} {'':<6} {'pace(med)':>10} {'p25':>7} {'clean':>6} "
      f"{'off-trk%':>9} {'laps/h':>7} {'stalls/h':>9}")
for label, basef, armf in PAIRS:
    b, a = scan(basef), scan(armf)
    if not b or not a:
        print(f"{label:<22} missing log"); continue
    print(f"{label:<22} {'base':<6} {b['med']:10.2f} {b['p25']:7.2f} {b['n']:6d} "
          f"{b['dirty_pct']:8.1f}% {b['lph']:7.1f} {b['stalls_ph']:9.2f}")
    print(f"{'':<22} {'ARM':<6} {a['med']:10.2f} {a['p25']:7.2f} {a['n']:6d} "
          f"{a['dirty_pct']:8.1f}% {a['lph']:7.1f} {a['stalls_ph']:9.2f}")
    dm = a['med'] - b['med']
    dd = a['dirty_pct'] - b['dirty_pct']
    dl = a['lph'] - b['lph']
    verdict = ('PACE WORSE' if dm > 0.30 else 'PACE BETTER' if dm < -0.30 else 'pace neutral')
    if dd > 3.0 or dl < -8.0:
        verdict += ' / INCIDENTS WORSE'
    elif dd < -3.0:
        verdict += ' / incidents better'
    print(f"{'':<22} {'':<6} {'delta':>10} {dm:+7.2f} {'':6} {dd:+7.1f}% {dl:+7.1f}   -> {verdict}\n")
