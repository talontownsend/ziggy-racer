#!/usr/bin/env python
"""Score a k_reserve window against the PRE-REGISTERED predictions.

Written 2026-08-06 BEFORE any window was run, because the prediction on record is that
lap time will NOT improve on the first pass (the thr_cap derate still binds), so scoring
this arm the usual way - on the median - will reject a correct result. See
docs/PROPOSAL_lateral_authority.md.

The pre-registered predictions:
  1. full-lock share falls from the 31.9% baseline
  2. |cte| p90 does NOT worsen by more than 0.5 m
  3. lap time unchanged or slightly worse; the prize only arrives when the derate is
     relaxed afterwards

Windows are segmented by `tune_hash` (md5[:8] of the live tune.json, logged per tick),
which is the only reliable way to know which ticks ran which config. A window spanning
two hashes is not scoreable.

    python tools/score_kreserve.py                    # segment the live log by config
    python tools/score_kreserve.py --log <path>
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(ROOT, "recordings")

# baseline, measured 08-06 over 485,494 on-track ticks (docs/BIND_DECOMPOSITION_0806.md)
BASE_LOCK = 31.9
BASE_CTE_P90 = None       # filled from the baseline log if present
BASE_LOG = os.path.join(REC, "follow_log_BASE_0806.csv")

COLS = ['t', 'race_pos', 'on_track', 'steer', 'cte_m', 'ff', 'h_t', 'p_t', 'i_t', 'd_t',
        'lap_t', 'tune_hash', 'kr_clip', 'steer_raw']


def load(path, cols):
    have = set(pd.read_csv(path, nrows=0).columns)
    use = [c for c in cols if c in have]
    missing = [c for c in cols if c not in have]
    d = pd.read_csv(path, usecols=use, on_bad_lines='skip', low_memory=False)
    return d, missing


def laps(t, lap_t, ot):
    """lap_t-reset detector (METHODOLOGY rule 23). Returns completed clean lap times."""
    reset = np.where(lap_t[1:] < lap_t[:-1] - 0.05)[0] + 1
    bounds = np.concatenate(([0], reset, [len(t)]))
    out = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a < 50 or b >= len(t) or lap_t[a] >= 0.5:
            continue
        g = np.diff(t[a:b])
        if len(g) and g.max() > 2.0:
            continue
        d = float(lap_t[b - 1])
        if 24 < d < 70 and np.mean(ot[a:b] > 0.5) > 0.97:
            out.append(d)
    return np.array(out)


def metrics(g):
    num = g.apply(pd.to_numeric, errors='coerce')
    r = num[(num['race_pos'] >= 1) & (num['on_track'] > 0.5)]
    if len(r) < 2000:
        return None
    st = r['steer'].abs().to_numpy()
    L = laps(num['t'].to_numpy(), num['lap_t'].to_numpy(), num['on_track'].to_numpy())
    m = {
        'ticks': len(r),
        'lock_pct': 100.0 * np.mean(st > 0.99),
        'cte_p90': float(r['cte_m'].abs().quantile(0.90)),
        'cte_med': float(r['cte_m'].abs().median()),
        'n_laps': len(L),
        'med': float(np.median(L)) if len(L) else float('nan'),
        'best': float(L.min()) if len(L) else float('nan'),
    }
    if 'kr_clip' in r:
        m['clip_pct'] = 100.0 * float(pd.to_numeric(r['kr_clip'], errors='coerce').fillna(0).mean())
    if 'ff' in r and 'h_t' in r:
        sat = st > 0.99
        if sat.sum() > 100:
            m['ff_at_lock'] = float(r['ff'].abs().to_numpy()[sat].mean())
            m['pid_at_lock'] = float((r['h_t'].abs() + r['p_t'].abs() +
                                      r['i_t'].abs() + r['d_t'].abs()).to_numpy()[sat].mean())
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', default=os.path.join(REC, 'follow_log.csv'))
    a = ap.parse_args()

    d, missing = load(a.log, COLS)
    if missing:
        print(f"note: columns absent from this log: {missing}")
    if 'tune_hash' not in d.columns:
        print("FAIL: no tune_hash column. This log predates config logging (08-06), so its "
              "ticks cannot be attributed to a config and it is not scoreable.")
        return 1

    print(f"{os.path.basename(a.log)}: {len(d)} rows\n")
    print(f"{'config':>10} {'ticks':>8} {'laps':>5} {'median':>7} {'best':>7} "
          f"{'full-lock':>10} {'|cte|p90':>9} {'clip%':>7}")
    rows = []
    for h, g in d.groupby('tune_hash', sort=False):
        m = metrics(g)
        if m is None:
            continue
        rows.append((h, m))
        print(f"{str(h):>10} {m['ticks']:8d} {m['n_laps']:5d} {m['med']:7.2f} {m['best']:7.2f} "
              f"{m['lock_pct']:9.1f}% {m['cte_p90']:9.2f} "
              f"{m.get('clip_pct', float('nan')):6.2f}%")

    if not rows:
        print("no config segment had enough ticks to score")
        return 1

    # the armed window is the segment where the clip actually fired
    armed = [r for r in rows if r[1].get('clip_pct', 0) > 0.01]
    if not armed:
        print(f"\nno segment shows kr_clip firing, so k_reserve was never active here.")
        print(f"baseline reference: full-lock {BASE_LOCK}%")
        for h, m in rows:
            if 'ff_at_lock' in m:
                print(f"  {h}: at full lock, mean |ff| {m['ff_at_lock']:.3f} vs "
                      f"mean PID sum {m['pid_at_lock']:.3f}")
        return 0

    base = sorted([r for r in rows if r not in armed], key=lambda r: -r[1]['ticks'])
    b = base[0][1] if base else None
    print("\n" + "=" * 66)
    for h, m in armed:
        print(f"ARMED window {h}")
        blk = b['lock_pct'] if b else BASE_LOCK
        bct = b['cte_p90'] if b else float('nan')
        p1 = m['lock_pct'] < blk
        p2 = (m['cte_p90'] - bct) <= 0.5 if b else None
        print(f"  1. full-lock share  {blk:.1f}% -> {m['lock_pct']:.1f}%   "
              f"{'PASS' if p1 else 'FAIL'}")
        print(f"  2. |cte| p90        {bct:.2f} -> {m['cte_p90']:.2f} m   "
              f"{'PASS' if p2 else 'FAIL' if p2 is not None else '(no baseline)'}")
        print(f"  3. lap median       {b['med'] if b else float('nan'):.2f} -> {m['med']:.2f} s   "
              f"(NOT a pass/fail criterion on the first pass -- see the proposal)")
        print(f"     clip fired on {m.get('clip_pct', 0):.2f}% of ticks")
        if p1 and p2:
            print("  -> mechanism confirmed. Proceed to stage 4: relax the thr_cap derate.")
        elif not p1:
            print("  -> the clip is not reducing saturation. Check k_reserve actually reached "
                  "the follower (tune_hash should differ from baseline).")
        else:
            print("  -> saturation fell but tracking degraded past tolerance. Raise k_reserve.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
