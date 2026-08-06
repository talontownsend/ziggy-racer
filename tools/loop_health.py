"""Loop-timing health check for the follower.

Why this exists. On 08-05 the control loop's tail latency degraded roughly 5-30x and nobody
noticed for a full day of A/B testing, because nothing watched it. It was found by accident while
chasing an unrelated stall count, and by then several scored windows had already been run on a
machine behaving differently from the ones they were compared against.

A 33 ms tick means the virtual pad holds a stale command for an extra two periods, about 0.8 m of
travel at 150 km/h, on a car that sits at full steering lock a third of the lap with no authority
margin. It is not a cosmetic metric.

Reference, measured across four clean sessions on 08-03 and 08-04:
    median 14.00 ms, p99 16.00, p999 17.00, >20 ms 0.00%, >33 ms 0.002-0.019%

    python tools/loop_health.py [--log PATH] [--tail N]

Exit code 1 if the tail is out of family, so it can gate a scored window.
"""
import os
import sys
import csv
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_P999 = 17.0        # ms, worst of four clean 08-03/08-04 sessions
REF_GT33 = 0.019       # percent
FAIL_P999 = 22.0
FAIL_GT33 = 0.05


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(ROOT, "recordings", "follow_log.csv"))
    ap.add_argument("--tail", type=int, default=250000, help="use the last N rows (late-session)")
    a = ap.parse_args()

    t = []
    with open(a.log, newline="", errors="ignore") as f:
        for d in csv.DictReader(f):
            try:
                t.append(float(d["t"]))
            except (TypeError, ValueError, KeyError):
                pass
    if len(t) < 20000:
        print(f"too few rows ({len(t)}) to judge")
        return 0
    t = np.array(t[-a.tail:])
    dt = np.diff(t) * 1000.0
    dt = dt[(dt > 0) & (dt < 300)]          # drop restarts and clock resets

    med = float(np.median(dt))
    p99 = float(np.percentile(dt, 99))
    p999 = float(np.percentile(dt, 99.9))
    gt20 = float(np.mean(dt > 20) * 100)
    gt33 = float(np.mean(dt > 33) * 100)
    print(f"ticks {len(dt)}   median {med:.2f} ms   p99 {p99:.2f}   p999 {p999:.2f}")
    print(f"  >20 ms {gt20:.3f}%   >33 ms {gt33:.3f}%")
    print(f"  reference (four clean 08-03/08-04 sessions): p999 <= {REF_P999:.0f} ms, >33 ms <= {REF_GT33}%")

    bad = []
    if med > 15.5:
        bad.append(f"median {med:.2f} ms is above 15.5: the loop is not keeping up at all")
    if p999 > FAIL_P999:
        bad.append(f"p999 {p999:.2f} ms exceeds {FAIL_P999:.0f}")
    if gt33 > FAIL_GT33:
        bad.append(f"{gt33:.3f}% of ticks over 33 ms exceeds {FAIL_GT33}%")
    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        print("  A degraded tail invalidates scored comparisons against earlier windows.")
        print("  Check machine uptime and background load before trusting any A/B result.")
        return 1
    print("OK: loop timing is in family with the clean reference")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
