"""Sequential JOINT-axis A/B search, with mechanism metrics as the primary readout.

Why this exists. Five single-axis relaxations have now measured worse in the car (see
METHODOLOGY.md). That pattern is the signature of a system sitting in a local optimum: every
guard is individually load-bearing because moving it alone breaks something another guard was
covering. A single-axis search cannot escape that, however many arms it runs.

So this runs arms that move SEVERAL keys at once, and it judges them on per-tick mechanism
metrics rather than on lap time, because the lap-time floor is about 0.30 s for a 40 minute
window while the effects worth finding are smaller than that.

Each arm: snapshot the learner -> write keys -> equilibrate -> score -> ALWAYS revert -> restore
the learner if the arm was worse. The learner is left ON, because a change that alters achievable
acceleration must be scored with the layer that absorbs it (METHODOLOGY rule 18).

    python tools/joint_search.py --plan plan.json [--dry-run]

plan.json is a list of {"label":..., "arm":{...}, "note":...}. The baseline is measured first and
every arm is compared against it.
"""
import os
import sys
import json
import time
import shutil
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import ab_arm as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(ROOT, "recordings")
SNAP = os.path.join(REC, "snapshots")
LEARNED = ("vtrim_net.npz", "vtrim_delta.npz", "vtrim_map.npz")


def snap(tag):
    os.makedirs(SNAP, exist_ok=True)
    for n in LEARNED:
        src = os.path.join(REC, n)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(SNAP, n.replace(".npz", f"_{tag}.npz")))


def restore(tag):
    for n in LEARNED:
        src = os.path.join(SNAP, n.replace(".npz", f"_{tag}.npz"))
        if os.path.exists(src):
            shutil.copy(src, os.path.join(REC, n))


def mech(t_from, t_to):
    """Per-tick mechanism panel over a scored window. These decide the arm; lap time is secondary
    because a 40 min window cannot resolve less than ~0.30 s."""
    import csv
    C = ["t", "on_track", "race_pos", "spd_kmh", "tgt_kmh", "sideslip", "drive_slip", "drive_spin",
         "thr", "thr_cap", "meas_latg", "fc_frac", "kap_car", "alat_max_g"]
    rows = []
    with open(os.path.join(REC, "follow_log.csv"), newline="", errors="ignore") as f:
        for d in csv.DictReader(f):
            try:
                r = [float(d[c]) for c in C]
            except (TypeError, ValueError, KeyError):
                continue
            if t_from is not None and not (t_from <= r[0] <= t_to):
                continue
            rows.append(r)
    if len(rows) < 5000:
        return None
    M = np.array(rows)
    i = {c: k for k, c in enumerate(C)}
    M = M[(M[:, i["race_pos"]] >= 1)]
    on = M[:, i["on_track"]] > 0.5
    ss = np.abs(M[:, i["sideslip"]])
    lat = np.abs(M[:, i["meas_latg"]])
    util = np.sqrt(np.clip(1.0 - M[:, i["fc_frac"]] ** 2, 0, 1))
    return dict(
        n=int(len(M)),
        off_track=float(np.mean(~on) * 100),
        sideslip_p99=float(np.percentile(ss, 99)),
        sideslip_p999=float(np.percentile(ss, 99.9)),
        drive_slip_p99=float(np.percentile(M[:, i["drive_slip"]], 99)),
        drive_spin_p99=float(np.percentile(M[:, i["drive_spin"]], 99)),
        spin_gt15=float(np.mean(M[:, i["drive_spin"]] > 1.5) * 100),
        thr_mean=float(M[:, i["thr"]].mean()),
        thr_cap_mean=float(M[:, i["thr_cap"]].mean()),
        derate_rate=float(np.mean(M[:, i["drive_slip"]] > 1.05) * 100),
        spd_minus_tgt=float(np.mean(M[:, i["spd_kmh"]] - M[:, i["tgt_kmh"]])),
        lat_p99=float(np.percentile(lat, 99)),
        lat_util_p50=float(np.percentile(util, 50)),
        alat_max_p50=float(np.percentile(M[:, i["alat_max_g"]], 50)),
    )


def show(tag, laps, m):
    if laps:
        print(f"  {tag:16} n={laps['n_laps']:3d} med {laps['med']:6.2f} best {laps['best']:6.2f} "
              f"p75 {laps['p75']:6.2f} stalls {laps['stalls']}", flush=True)
    if m:
        print(f"  {'':16} off {m['off_track']:.2f}%  sideslip p99 {m['sideslip_p99']:5.2f}  "
              f"spin>1.5 {m['spin_gt15']:4.2f}%  thr {m['thr_mean']:.3f}  cap {m['thr_cap_mean']:.3f}  "
              f"derate {m['derate_rate']:4.1f}%  spd-tgt {m['spd_minus_tgt']:+6.2f}  "
              f"lat_p99 {m['lat_p99']:.2f}", flush=True)


def run_window(label, arm, revert, equil_min, score_min, abort_med=None):
    """Returns (laps, mech) or (None, None) if the window was voided."""
    sess0 = A.sessions_now()
    if arm:
        A.write_tune(arm)
    t0 = A.now_t()
    print(f"[{label}] armed {arm} at t={t0}; equil {equil_min}m, score {score_min}m", flush=True)
    deadline = time.time() + (equil_min + score_min) * 60.0
    t_score = None
    try:
        while time.time() < deadline:
            time.sleep(180)
            tn = A.now_t()
            if tn is None:
                continue
            if A.sessions_now() != sess0:
                print(f"[{label}] VOID: follower restarted mid-window", flush=True)
                return None, None
            live = A.read_tune()
            drift = {k: (live.get(k), v) for k, v in (arm or {}).items() if live.get(k) != v}
            if drift:
                print(f"[{label}] VOID: keys drifted {drift}", flush=True)
                return None, None
            if (tn - t0) / 60.0 >= equil_min and t_score is None:
                t_score = tn
                print(f"[{label}] equilibrated, scoring from t={t_score:.0f}", flush=True)
            if t_score is not None and abort_med:
                cur = A.scan(t_from=t_score, t_to=tn)
                if cur and cur["n_laps"] >= 20 and cur["med"] > abort_med:
                    print(f"[{label}] ABORT: trailing median {cur['med']:.2f} over "
                          f"{cur['n_laps']} laps (limit {abort_med})", flush=True)
                    return cur, mech(t_score, tn)
        tn = A.now_t()
        laps = A.scan(t_from=t_score, t_to=tn) if t_score else None
        m = mech(t_score, tn) if t_score else None
        return laps, m
    finally:
        if revert:
            A.write_tune(revert)
            print(f"[{label}] reverted -> {revert}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--equil", type=float, default=25.0)
    ap.add_argument("--score", type=float, default=40.0)
    ap.add_argument("--base-score", type=float, default=35.0)
    ap.add_argument("--abort-med", type=float, default=31.5)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    plan = json.load(open(a.plan))
    base_keys = {}
    for step in plan:
        base_keys.update({k: None for k in step["arm"]})
    live = A.read_tune()
    revert = {k: live.get(k) for k in base_keys}
    if any(v is None for v in revert.values()):
        print(f"FATAL: a key in the plan is not live in tune.json: {revert}")
        return 1
    print(f"baseline values for every key the plan touches: {revert}\n")
    if a.dry_run:
        for s in plan:
            print(f"  would run {s['label']}: {s['arm']}   ({s.get('note','')})")
        return 0

    snap("JS_BASE")
    print("=== BASELINE ===", flush=True)
    bl, bm = run_window("BASELINE", {}, None, 3.0, a.base_score)
    show("BASELINE", bl, bm)
    if not bl:
        print("FATAL: baseline window voided")
        return 1
    results = [dict(label="BASELINE", arm={}, laps=bl, mech=bm)]

    for step in plan:
        lbl, arm = step["label"], step["arm"]
        print(f"\n=== {lbl} === {step.get('note','')}", flush=True)
        snap(f"JS_{lbl}")
        laps, m = run_window(lbl, arm, revert, a.equil, a.score, a.abort_med)
        show(lbl, laps, m)
        results.append(dict(label=lbl, arm=arm, laps=laps, mech=m))
        if laps and laps["med"] > bl["med"] + 0.4:
            print(f"  -> worse than baseline by {laps['med']-bl['med']:+.2f}s; restoring the learner",
                  flush=True)
            restore("JS_BASE")
        json.dump(results, open(os.path.join(REC, "joint_search_results.json"), "w"),
                  indent=1, default=float)

    print("\n" + "=" * 70)
    print(f"{'arm':16} {'med':>7} {'d_med':>7} {'stalls':>7} {'off%':>6} {'ss_p99':>7} {'thr':>6} {'spd-tgt':>8}")
    for r in results:
        if not r["laps"]:
            print(f"{r['label']:16} VOID")
            continue
        d = r["laps"]["med"] - bl["med"]
        mm = r["mech"] or {}
        print(f"{r['label']:16} {r['laps']['med']:7.2f} {d:+7.2f} {r['laps']['stalls']:7d} "
              f"{mm.get('off_track',0):6.2f} {mm.get('sideslip_p99',0):7.2f} "
              f"{mm.get('thr_mean',0):6.3f} {mm.get('spd_minus_tgt',0):+8.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
