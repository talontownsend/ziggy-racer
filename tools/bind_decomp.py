"""Decompose the speed deficit by which constraint was actually binding.

`bind_code` is logged, not reconstructed: it names the LAST term that lowered `target_v` on
that tick, so it is the binding constraint. Codes are assigned in follow.py around L1713-1851.

Method
------
  rows kept : race_pos>=1, on_track>0.5, brake<=0.05, and tgt_kmh > spd_kmh
  weight    : (tgt_kmh - spd_kmh) * dt   ->  km/h-seconds, which SUMS to the whole deficit
  grouped   : by bind_code, within each tune_hash segment

Weighting by dt rather than counting ticks matters: a code that binds rarely but with a huge
deficit is not the same as one that binds constantly by 1 km/h, and a tick count cannot tell
them apart. km/h-seconds is the integral of the deficit over time, so shares sum to 100% and
"which code owns the deficit" has an unambiguous answer.

Brake ticks are excluded because a car that is deliberately braking is under target BY DESIGN;
including them attributes intentional deceleration to whatever constraint happened to be set.
That contamination already produced one wrong conclusion (see KRESERVE_LADDER_0806.md).
"""
import os
import numpy as np
import pandas as pd

LOG = os.path.join('recordings', 'follow_log.csv')
NAMES = {
    0: 'none (no term bound)',
    1: 'plan / tv  (planner speed)',
    2: 'speed_cap  (global cap)',
    3: 'v_curve * map_w  (curvature x vtrim)',
    4: 'pdg  (plan degraded crawl)',
    5: 'launch cap',
    6: 'cte governor  (off-line)',
    7: 'understeer',
    8: 'zone multiplier',
}
SEG = {'e1d9ed6d': 'cte_ileak 0.0  (baseline, pooled pre+post)',
       'b7810d10': 'cte_ileak 0.5  (armed)'}

need = ['t', 'race_pos', 'on_track', 'brk', 'tgt_kmh', 'spd_kmh', 'bind_code', 'tune_hash']
df = pd.read_csv(LOG, usecols=lambda c: c in need, on_bad_lines='skip', low_memory=False)
missing = [c for c in need if c not in df.columns]
if missing:
    raise SystemExit(f"log is missing {missing}")

hsh = df['tune_hash'].astype(str).to_numpy()
n = df.apply(pd.to_numeric, errors='coerce')

keep = (n['race_pos'] >= 1) & (n['on_track'] > 0.5) & (n['brk'] <= 0.05)
keep &= n['t'].notna() & n['tgt_kmh'].notna() & n['spd_kmh'].notna() & n['bind_code'].notna()
n, hsh = n[keep], hsh[keep.to_numpy()]

t = n['t'].to_numpy()
dt = np.diff(t, prepend=t[0])
dt = np.clip(dt, 0.0, 0.10)          # drop restart jumps; a tick is ~0.0145 s
deficit = (n['tgt_kmh'] - n['spd_kmh']).to_numpy()
code = n['bind_code'].to_numpy().astype(int)

print(f"{keep.sum():,} ticks kept (racing, on-track, not braking) of {len(keep):,}\n")

for tag in ('e1d9ed6d', 'b7810d10'):
    m = hsh == tag
    if m.sum() < 1000:
        continue
    d, c, w = deficit[m], code[m], dt[m]
    under = d > 0
    tot_ticks = int(m.sum())
    tot_under = int(under.sum())
    total = float((d[under] * w[under]).sum())
    secs = float(w[m if False else slice(None)][under].sum()) if False else float(w[under].sum())

    print("=" * 78)
    print(f"{SEG.get(tag, tag)}   [{tag}]")
    print(f"  {tot_ticks:,} ticks, {tot_under:,} under target ({100*tot_under/tot_ticks:.1f}%), "
          f"{secs/60:.1f} min under target")
    print(f"  total deficit {total:,.0f} km/h-s   (mean {total/max(secs,1e-9):.1f} km/h while under)")
    print(f"  {'code':>4}  {'constraint':38} {'ticks':>9} {'%ticks':>7} {'km/h-s':>10} {'share':>7} {'mean':>6}")
    rows = []
    for k in sorted(set(c[under].tolist())):
        sel = under & (c == k)
        km = float((d[sel] * w[sel]).sum())
        sw = float(w[sel].sum())
        rows.append((km, k, int(sel.sum()), sw))
    for km, k, cnt, sw in sorted(rows, reverse=True):
        print(f"  {k:>4}  {NAMES.get(k, '?'):38} {cnt:9,} {100*cnt/tot_under:6.1f}% "
              f"{km:10,.0f} {100*km/max(total,1e-9):6.1f}% {km/max(sw,1e-9):6.1f}")
    top = max(rows)
    print(f"  -> LARGEST: code {top[1]} ({NAMES.get(top[1])}) at "
          f"{100*top[0]/max(total,1e-9):.1f}% of the deficit")
    print()

# ---- what the arm actually changed, code by code ----------------------------
a, b = hsh == 'e1d9ed6d', hsh == 'b7810d10'
if a.sum() > 1000 and b.sum() > 1000:
    print("=" * 78)
    print("WHAT THE ILEAK CHANGED, per code (rate = km/h-s per MINUTE under target,")
    print("so the two segments are comparable despite different lengths)")
    print(f"  {'code':>4}  {'constraint':38} {'0.0':>9} {'0.5':>9} {'delta':>9} {'%chg':>7}")
    ua, ub = a & (deficit > 0), b & (deficit > 0)
    ma, mb = float(dt[ua].sum()) / 60, float(dt[ub].sum()) / 60
    for k in sorted(set(code[ua].tolist()) | set(code[ub].tolist())):
        ra = float((deficit[ua & (code == k)] * dt[ua & (code == k)]).sum()) / max(ma, 1e-9)
        rb = float((deficit[ub & (code == k)] * dt[ub & (code == k)]).sum()) / max(mb, 1e-9)
        pc = (rb - ra) / ra * 100 if ra > 1e-9 else float('nan')
        print(f"  {k:>4}  {NAMES.get(k, '?'):38} {ra:9.0f} {rb:9.0f} {rb-ra:+9.0f} {pc:+6.1f}%")
    ta = float((deficit[ua] * dt[ua]).sum()) / max(ma, 1e-9)
    tb = float((deficit[ub] * dt[ub]).sum()) / max(mb, 1e-9)
    print(f"  {'':>4}  {'TOTAL':38} {ta:9.0f} {tb:9.0f} {tb-ta:+9.0f} "
          f"{(tb-ta)/max(ta,1e-9)*100:+6.1f}%")
