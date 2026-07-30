#!/usr/bin/env python
"""A/B harness for live tune-key arms. Enforces the METHODOLOGY.md rules:

  * writes the arm atomically to tune.json (hot-reloaded in <0.5 s)
  * equilibration window before any scoring (rule 2)
  * abort monitor that WRITES the revert itself, never just prints (rule 4)
  * session-aware log parsing; a follower restart VOIDS the window (rule 6)
  * deduped stall counting (rule 7)
  * always reverts on exit, including on abort or exception

Usage:
  python tools/ab_arm.py --label ffm020 \
      --arm '{"ffm_w":0.20}' --revert '{"ffm_w":0.15}' \
      --equil 30 --score 45 --abort-stalls 4 --abort-med 31.0

Prints a structured result block; exit code 0 = window scored, 2 = aborted, 3 = voided.
"""
import argparse
import csv
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(ROOT, "recordings")
TUNE = os.path.join(REC, "tune.json")
LOG = os.path.join(REC, "follow_log.csv")
PLAN = os.path.join(REC, "refline_plan.npz")


def write_tune(keys):
    """Merge keys into tune.json atomically."""
    with open(TUNE) as fh:
        t = json.load(fh)
    t.update(keys)
    tmp = TUNE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(t, fh, indent=1)
    os.replace(tmp, TUNE)
    return t


def read_tune():
    with open(TUNE) as fh:
        return json.load(fh)


def scan(t_from=None, t_to=None):
    """Parse the live log. Returns dict of metrics for rows in [t_from, t_to] of the
    LAST session only. Detects session boundaries (t resets on follower restart)."""
    d = np.load(PLAN)
    line = d["line"]
    n = len(line)
    seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
    s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]

    laps, stalls, comp = {}, [], []
    srun, sess, prev = 0, 0, None
    cur, prev_s = {}, None
    sess_start = {}
    try:
        fh = open(LOG, newline="")
    except OSError:
        return None
    for r in csv.DictReader(fh):
        try:
            t = float(r["t"])
            if prev is not None and t < prev - 5:
                sess += 1
                cur, prev_s, srun = {}, None, 0
            prev = t
            sess_start.setdefault(sess, t)
            if float(r["race_pos"]) < 1:
                srun, prev_s = 0, None
                continue
            if t_from is not None and t < t_from:
                continue
            if t_to is not None and t > t_to:
                continue
            sm = s_of[int(float(r["i0"])) % n]
            sp = float(r["spd_kmh"])
            if sp < 5:
                srun += 1
                if srun == 70:
                    stalls.append((sess, t))
            else:
                srun = 0
            lt = float(r["lap_t"])
            if 24 < lt < 70:
                k = (sess, int(float(r["lap_no"])))
                laps[k] = max(laps.get(k, 0), lt)
            if prev_s is not None and sm < prev_s - 200:
                cur = {}
            for g in (430, 800):
                if g not in cur and prev_s is not None and prev_s < g <= sm and (sm - prev_s) < 30:
                    cur[g] = t
            if len(cur) == 2:
                dt = cur[800] - cur[430]
                if 5 < dt < 60:
                    comp.append(dt)
                cur = {}
            prev_s = sm
        except (ValueError, KeyError, IndexError):
            continue
    fh.close()

    ded, last = 0, None
    for s, t in stalls:
        if last is None or s != last[0] or t - last[1] > 60:
            ded += 1
        last = (s, t)

    lts = sorted(laps.values())
    return {
        "n_laps": len(lts),
        "med": float(np.median(lts)) if lts else None,
        "best": float(min(lts)) if lts else None,
        "p25": float(np.percentile(lts, 25)) if lts else None,
        "p75": float(np.percentile(lts, 75)) if lts else None,
        "stalls": ded,
        "complex_med": float(np.median(comp)) if comp else None,
        "complex_best": float(min(comp)) if comp else None,
        "sessions": sess,
    }


def now_t():
    """Current follower clock (last t in the log), or None if the log is unreadable."""
    try:
        with open(LOG, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 4096))
            tail = fh.read().decode("utf-8", "ignore").strip().split("\n")
        for ln in reversed(tail[1:] if size < 4096 else tail):
            p = ln.split(",")
            if p and p[0]:
                try:
                    return float(p[0])
                except ValueError:
                    continue
    except OSError:
        pass
    return None


def sessions_now():
    """How many session boundaries exist in the log right now."""
    m = scan()
    return m["sessions"] if m else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--arm", required=True, help="JSON dict of keys to set")
    ap.add_argument("--revert", required=True, help="JSON dict restoring the baseline")
    ap.add_argument("--equil", type=float, default=30.0, help="equilibration minutes")
    ap.add_argument("--score", type=float, default=45.0, help="scoring minutes")
    ap.add_argument("--abort-stalls", type=int, default=5, help="stalls in any 15-min slice")
    ap.add_argument("--abort-med", type=float, default=31.5, help="median over >=25 laps")
    ap.add_argument("--check", type=float, default=180.0, help="monitor interval seconds")
    a = ap.parse_args()

    arm = json.loads(a.arm)
    revert = json.loads(a.revert)
    sess0 = sessions_now()

    print(f"[{a.label}] ARM {arm}  (revert -> {revert})", flush=True)
    write_tune(arm)
    t_arm = now_t()
    print(f"[{a.label}] armed at follower t={t_arm}, equil {a.equil} min, score {a.score} min", flush=True)

    deadline = time.time() + (a.equil + a.score) * 60.0
    t_score_from = None
    aborted = None
    try:
        while time.time() < deadline:
            time.sleep(a.check)
            t_now = now_t()
            if t_now is None:
                continue

            # rule 6: a follower restart re-writes tune.json from watchdog $addKeys,
            # silently disarming us. Void the window rather than score a lie.
            if sessions_now() != sess0:
                aborted = "VOID: follower restarted mid-window (arm keys disarmed by watchdog)"
                break

            live = read_tune()
            drift = {k: (live.get(k), v) for k, v in arm.items() if live.get(k) != v}
            if drift:
                aborted = f"VOID: arm keys no longer live in tune.json: {drift}"
                break

            elapsed_min = (t_now - t_arm) / 60.0
            if elapsed_min >= a.equil and t_score_from is None:
                t_score_from = t_now
                print(f"[{a.label}] equilibrated, scoring from t={t_now:.0f}", flush=True)

            # abort checks run on the trailing 15 min at all times
            m15 = scan(t_from=t_now - 900, t_to=t_now)
            if m15:
                if m15["stalls"] >= a.abort_stalls:
                    aborted = f"ABORT: {m15['stalls']} stalls in trailing 15 min (limit {a.abort_stalls})"
                    break
                if m15["n_laps"] >= 25 and m15["med"] and m15["med"] > a.abort_med:
                    aborted = f"ABORT: trailing median {m15['med']:.2f} over {m15['n_laps']} laps (limit {a.abort_med})"
                    break
            print(
                f"[{a.label}] t+{elapsed_min:5.1f}m  15min: laps={m15['n_laps'] if m15 else '?'} "
                f"med={m15['med'] if m15 and m15['med'] else float('nan'):.2f} stalls={m15['stalls'] if m15 else '?'}",
                flush=True,
            )

        result = None
        if aborted is None and t_score_from is not None:
            result = scan(t_from=t_score_from, t_to=now_t())
    finally:
        # ALWAYS revert (rule 4: the monitor writes the rollback itself)
        write_tune(revert)
        print(f"[{a.label}] REVERTED -> {revert}", flush=True)

    print("=" * 60, flush=True)
    if aborted:
        print(f"[{a.label}] {aborted}", flush=True)
        sys.exit(2 if aborted.startswith("ABORT") else 3)
    if not result or not result["n_laps"]:
        print(f"[{a.label}] NO DATA in scoring window", flush=True)
        sys.exit(3)
    print(
        f"[{a.label}] SCORED n={result['n_laps']} med {result['med']:.2f} best {result['best']:.2f} "
        f"p25 {result['p25']:.2f} p75 {result['p75']:.2f} stalls {result['stalls']} "
        f"complex {result['complex_med']:.2f}/{result['complex_best']:.2f}"
        if result["complex_med"]
        else f"[{a.label}] SCORED n={result['n_laps']} med {result['med']:.2f} best {result['best']:.2f} stalls {result['stalls']}",
        flush=True,
    )
    print("RESULT_JSON " + json.dumps({"label": a.label, **result}), flush=True)


if __name__ == "__main__":
    main()
