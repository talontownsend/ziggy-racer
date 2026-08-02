"""Health report for the vtrim learned state (net + delta -> effective map).

Catches the 08-01 failure class: VtrimNet.forward() is unbounded and step() nudges shared
weights on every credit/debit, so the net drifts out of the range a speed multiplier can
occupy. While the correction term is unbounded that is invisible (delta silently winds up to
compensate, measured +6.57). Once the correction is bounded, stations get STRANDED at a map
bound with their correction pushing the other way, and the map collapses without any error
being raised. That cost 3.3 s/lap for three days.

The stranded-station count is the diagnostic that matters: a station pinned at the floor whose
delta is POSITIVE is a station the learner is trying and failing to lift.

    python tools/vtrim_health.py [--map OTHER_MAP.npz]

Exit code 1 if any check fails, so it can gate a deploy.
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

REC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recordings")
LO, HI = 0.80, 1.55
DMAX = HI - LO          # the only bound under which every value is reachable from any base
STRAND_TOL = 1e-6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default=os.path.join(REC, "vtrim_map.npz"))
    ap.add_argument("--delta", default=os.path.join(REC, "vtrim_delta.npz"))
    ap.add_argument("--net", default=os.path.join(REC, "vtrim_net.npz"))
    ap.add_argument("--feat", default=os.path.join(REC, "vtrim_features.npz"))
    a = ap.parse_args()

    fails = []
    warns = []

    m = np.load(a.map)["map"].astype(float)
    d = np.load(a.delta)["delta"].astype(float)
    print(f"stations: {len(m)}")
    print(f"map      : mean {m.mean():.4f}  floor {np.mean(m <= LO + 1e-3) * 100:.1f}%  "
          f"ceiling {np.mean(m >= HI - 1e-3) * 100:.1f}%")
    print(f"delta    : mean {d.mean():+.4f}  min {d.min():+.4f}  max {d.max():+.4f}")

    if np.abs(d).max() > DMAX + 1e-6:
        fails.append(f"delta exceeds hi-lo ({np.abs(d).max():.3f} > {DMAX}): windup, the map "
                     f"no longer records what was earned")

    # --- net range ---
    base = None
    try:
        from vtrim_net import VtrimNet
        with np.load(a.feat) as f:
            X, mu, sd = f["X"], f["mu"], f["sd"]
        raw = VtrimNet.load(a.net).forward((X - mu) / sd)
        base = np.clip(raw, LO, HI)
        out = np.mean((raw < LO) | (raw > HI)) * 100
        print(f"net raw  : mean {raw.mean():+.4f}  min {raw.min():+.4f}  max {raw.max():+.4f}")
        print(f"           outside [{LO}, {HI}]: {out:.1f}%  "
              f"(below {np.mean(raw < LO) * 100:.1f}%, above {np.mean(raw > HI) * 100:.1f}%)")
        if out > 25.0:
            # NOT a gate failure: vtrim_base() clips, so a drifted net is operationally safe.
            # It does mean the net contributes no generalization any more (delta is doing all
            # the work), which matters when porting to a new track, not when driving this one.
            warns.append(f"net has drifted out of its own operating range ({out:.1f}% outside "
                         f"[{LO}, {HI}]). Clipped, so driving is unaffected, but the net "
                         f"contributes no generalization: delta carries the map. Retrain "
                         f"(python vtrim_net.py) before porting to a new track.")
    except Exception as e:                      # net optional: plain-table mode is legal
        print(f"net      : unavailable ({e})")

    # --- stranded stations: pinned at a bound with the correction pushing the other way ---
    if base is not None:
        at_floor = m <= LO + 1e-3
        at_ceil = m >= HI - 1e-3
        stranded_lo = at_floor & (d > STRAND_TOL)
        stranded_hi = at_ceil & (d < -STRAND_TOL)
        n_lo, n_hi = int(stranded_lo.sum()), int(stranded_hi.sum())
        print(f"stranded : {n_lo} at floor with delta>0, {n_hi} at ceiling with delta<0")
        if n_lo:
            print(f"           floor-stranded delta: mean {d[stranded_lo].mean():+.3f}  "
                  f"max {d[stranded_lo].max():+.3f}")
        if n_lo + n_hi > 0.02 * len(m):
            fails.append(f"{n_lo + n_hi} stations stranded at a bound "
                         f"({(n_lo + n_hi) / len(m) * 100:.1f}%): the learner is pushing and "
                         f"cannot move them. Rebuild delta as target_map - clip(base).")

        recon = np.clip(base + np.clip(d, -DMAX, DMAX), LO, HI)
        err = np.abs(recon - m).max()
        print(f"recon    : max |clip(clip(base)+delta) - map| = {err:.5f}")
        if err > 1e-3:
            fails.append(f"map does not equal clip(clip(base)+delta) (max err {err:.4f}): the "
                         f"map file is stale or was written under different bounds")

    # --- window-min damage: map_w is a MIN over the next 18 m, so pockets hurt upstream ---
    print(f"map (raw)      mean {m.mean():.4f}")
    try:
        with np.load(os.path.join(REC, "refline_plan.npz")) as p:
            key = "s" if "s" in p.files else None
            seg = np.diff(p[key]) if key else None
    except Exception:
        seg = None
    if seg is None:
        step = 1                                 # fall back to a fixed station count
        w = 18
    else:
        step = 1
        w = max(1, int(round(18.0 / max(float(np.median(seg)), 1e-6))))
    mw = np.array([m[np.arange(i, i + w) % len(m)].min() for i in range(0, len(m), step)])
    print(f"map WINDOW-MIN mean {mw.mean():.4f}  (this is what the cap actually reads, "
          f"window {w} stations)")

    print()
    for w_ in warns:
        print(f"WARN: {w_}")
    if fails:
        for f in fails:
            print(f"FAIL: {f}")
        return 1
    print("OK: learned state is bounded, unstranded and self-consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
