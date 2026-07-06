"""Print follow_log rows in a time window to see the run-up to an impact."""
import csv
import sys

lo, hi = float(sys.argv[1]), float(sys.argv[2])
rows = list(csv.DictReader(open(r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv")))
print(f"{'t':>6} {'spd':>5} {'i0':>4} {'head':>6} {'alpha':>6} {'steer':>6} {'thr':>4} {'brk':>4}  pos")
prev_i = None
for r in rows:
    t = float(r["t"])
    if lo <= t <= hi:
        i0 = int(float(r["i0"]))
        jump = "" if prev_i is None or abs(i0 - prev_i) <= 3 else f"  <-- i0 JUMP {prev_i}->{i0}"
        print(f"{t:6.2f} {float(r['spd_kmh']):5.0f} {i0:4d} {float(r['head_deg']):6.0f} "
              f"{float(r['alpha_deg']):6.0f} {float(r['steer']):6.2f} {float(r['thr']):4.2f} "
              f"{float(r['brk']):4.2f}  ({r['x']},{r['z']}){jump}")
        prev_i = i0
