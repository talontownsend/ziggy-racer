"""Rescore the joint_search arms, which have no dedicated logs.

The five arms with their own log files were rescored in docs/DETECTOR_RESCORE_0806.md. The
joint_search arms ran inside watchdog logs, and logs written before 2026-08-06 carry no
tune_hash to segment by, so their windows have to be recovered by wall-clock:

    wall_clock(row) = log_mtime - (t_last - t_row)

Each arm's learner snapshot marks when it was armed. joint_search equilibrates then scores,
so the scored portion is [snap + equil, snap + equil + score].

VALIDATION: recordings/joint_search_results.json holds three windows scored with the OLD
detector. This script must reproduce those medians from its own extraction before its
corrected numbers mean anything. If the check fails, the window mapping is wrong and the
output is discarded rather than reported.
"""
import glob, json, os, sys, datetime
import numpy as np
import pandas as pd

REC = 'recordings'
NEED = ['t', 'lap_t', 'on_track', 'race_pos']
EQUIL_MIN, SCORE_MIN = 30.0, 45.0


def load(path):
    """Return (wall_clock, lap_t, on_track) for racing rows, or None."""
    try:
        head = pd.read_csv(path, nrows=0)
    except Exception:
        return None
    if not set(NEED) <= set(head.columns):
        return None
    T, LT, OT = [], [], []
    try:
        for ch in pd.read_csv(path, usecols=NEED, chunksize=1_000_000,
                              on_bad_lines='skip', low_memory=False):
            ch = ch.apply(pd.to_numeric, errors='coerce').dropna()
            ch = ch[ch['race_pos'] >= 1]
            if not len(ch):
                continue
            T.append(ch['t'].to_numpy())
            LT.append(ch['lap_t'].to_numpy())
            OT.append(ch['on_track'].to_numpy())
    except Exception:
        pass
    if not T:
        return None
    t = np.concatenate(T)
    mt = os.path.getmtime(path)
    return mt - (t.max() - t), np.concatenate(LT), np.concatenate(OT)


def laps_reset(wc, lt, ot, lo, hi):
    """CORRECT detector: segment on lap_t resets, inside [lo,hi] wall-clock."""
    out = []
    reset = np.where(lt[1:] < lt[:-1] - 0.05)[0] + 1
    b = np.concatenate(([0], reset, [len(lt)]))
    for a, bb in zip(b[:-1], b[1:]):
        if bb - a < 50 or bb >= len(lt) or lt[a] >= 0.5:
            continue
        if not (lo <= wc[bb - 1] <= hi):
            continue
        g = np.diff(wc[a:bb])
        if len(g) and g.max() > 2.0:
            continue
        d = float(lt[bb - 1])
        if 24 < d < 70 and np.mean(ot[a:bb] > 0.5) > 0.97:
            out.append(d)
    return out


def laps_old(wc, lt, lo, hi, nlap):
    """OLD detector: key by lap_no, take max(lap_t). Used only for the validation check."""
    m = (wc >= lo) & (wc <= hi) & (lt > 24) & (lt < 70)
    if not m.any():
        return []
    d = {}
    for k, v in zip(nlap[m].astype(int), lt[m]):
        d[k] = max(d.get(k, 0.0), float(v))
    return sorted(d.values())


def attempts(wc, lt, ot, lo, hi):
    """All lap attempts in the window and how many were clean (stability axis)."""
    tot = clean = 0
    reset = np.where(lt[1:] < lt[:-1] - 0.05)[0] + 1
    b = np.concatenate(([0], reset, [len(lt)]))
    for a, bb in zip(b[:-1], b[1:]):
        if bb - a < 50 or bb >= len(lt) or not (lo <= wc[bb - 1] <= hi):
            continue
        tot += 1
        if np.mean(ot[a:bb] > 0.5) > 0.97 and 24 < float(lt[bb - 1]) < 70:
            clean += 1
    return tot, clean


# ---- gather every log once -------------------------------------------------
files = sorted(glob.glob(os.path.join(REC, 'follow_log*.csv'))) + \
        sorted(glob.glob(os.path.join(REC, 'archive_logs', 'follow_log*.csv')))
LOGS = []
for f in files:
    r = load(f)
    if r is not None and len(r[0]) > 5000:
        LOGS.append((f, r))
print(f"loaded {len(LOGS)} logs with racing rows", flush=True)


def score(lo, hi):
    """Score a wall-clock window across whichever log covers it."""
    best = None
    for f, (wc, lt, ot) in LOGS:
        n = np.sum((wc >= lo) & (wc <= hi))
        if n < 2000:
            continue
        if best is None or n > best[0]:
            best = (n, f, wc, lt, ot)
    if best is None:
        return None
    _, f, wc, lt, ot = best
    L = laps_reset(wc, lt, ot, lo, hi)
    tot, cl = attempts(wc, lt, ot, lo, hi)
    if len(L) < 8:
        return None
    hrs = (hi - lo) / 3600.0
    return dict(n=len(L), med=float(np.median(L)), best=float(min(L)),
                dirty=100.0 * (1 - cl / max(tot, 1)), lph=len(L) / max(hrs, 1e-6),
                log=os.path.basename(f))


# ---- arms, from their snapshots --------------------------------------------
snaps = sorted(
    (os.path.getmtime(p), os.path.basename(p)[len('vtrim_net_'):-len('.npz')])
    for p in glob.glob(os.path.join(REC, 'snapshots', 'vtrim_net_JS_*.npz')))

print("\n=== VALIDATION: reproduce the old-detector medians from joint_search_results.json ===")
try:
    rec = json.load(open(os.path.join(REC, 'joint_search_results.json')))
except Exception:
    rec = []
ok = True
for e in rec:
    lab = e['label']
    tag = {'BASELINE': 'JS_BASE', 'ILEAK_050': 'JS_ILEAK_050', 'ILEAK_100': 'JS_ILEAK_100'}.get(lab)
    st = next((s for s, n in snaps if n == tag), None)
    if st is None:
        print(f"  {lab:12} no snapshot"); ok = False; continue
    lo, hi = st + EQUIL_MIN * 60, st + (EQUIL_MIN + SCORE_MIN) * 60
    # old detector needs lap_no, reload just this log with it
    got = None
    for f, (wc, lt, otr) in LOGS:
        if np.sum((wc >= lo) & (wc <= hi)) < 2000:
            continue
        try:
            df = pd.read_csv(f, usecols=['t', 'lap_t', 'lap_no', 'race_pos'],
                             on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
            df = df[df['race_pos'] >= 1]
            mt = os.path.getmtime(f)
            w2 = mt - (df['t'].to_numpy().max() - df['t'].to_numpy())
            o = laps_old(w2, df['lap_t'].to_numpy(), lo, hi, df['lap_no'].to_numpy())
            if len(o) >= 8:
                got = (len(o), float(np.median(o)))
                break
        except Exception:
            continue
    if got is None:
        print(f"  {lab:12} could not locate window"); ok = False; continue
    d = abs(got[1] - e['laps']['med'])
    flag = 'OK' if d < 0.25 else 'MISMATCH'
    if d >= 0.25:
        ok = False
    print(f"  {lab:12} recorded med {e['laps']['med']:.2f} (n={e['laps']['n_laps']})  "
          f"reproduced {got[1]:.2f} (n={got[0]})  diff {d:+.2f}  {flag}")

print(f"\nvalidation: {'PASSED' if ok else 'FAILED'}")
if not ok:
    print("Window mapping is not reliable. Corrected numbers withheld.")
    sys.exit(1)

print("\n=== CORRECTED (lap_t-reset detector), both axes ===")
print(f"  {'arm':30} {'n':>4} {'pace':>7} {'best':>7} {'dirty%':>7} {'laps/h':>7}  log")
rows = []
for st, tag in snaps:
    lo, hi = st + EQUIL_MIN * 60, st + (EQUIL_MIN + SCORE_MIN) * 60
    r = score(lo, hi)
    when = datetime.datetime.fromtimestamp(st).strftime('%m-%d %H:%M')
    if r is None:
        print(f"  {tag:30} {'-':>4} {'no window recoverable':>30}")
        continue
    rows.append((tag, r, when))
    print(f"  {tag:30} {r['n']:4d} {r['med']:7.2f} {r['best']:7.2f} {r['dirty']:6.1f}% "
          f"{r['lph']:7.1f}  {r['log'][:30]}")

base = next((r for t, r, _ in rows if t == 'JS_BASE'), None)
if base:
    print(f"\n=== vs JS_BASE (pace {base['med']:.2f}, dirty {base['dirty']:.1f}%), floor ~0.30 s ===")
    for tag, r, _ in rows:
        if tag == 'JS_BASE':
            continue
        dp = r['med'] - base['med']
        verdict = ('NOISE' if abs(dp) < 0.30 else ('WORSE' if dp > 0 else 'BETTER'))
        stab = '' if r['dirty'] - base['dirty'] < 5 else f"  (+{r['dirty']-base['dirty']:.0f}pt dirty)"
        print(f"  {tag:30} {dp:+6.2f}  {verdict}{stab}")
