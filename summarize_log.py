"""Quick health summary of a follow_log.csv run."""
import csv
import sys
import numpy as np

rows = list(csv.DictReader(open(sys.argv[1])))
def arr(n): return np.array([float(r[n]) for r in rows])

alpha, steer, spd, thr = arr("alpha_deg"), arr("steer"), arr("spd_kmh"), arr("thr")
aa = np.abs(alpha)
print(f"rows {len(rows)}  duration {rows[-1]['t']}s")
print(f"speed km/h:  mean {spd.mean():.1f}  max {spd.max():.1f}")
print(f"|alpha| deg: p50 {np.percentile(aa,50):.1f}  p90 {np.percentile(aa,90):.1f}  max {aa.max():.1f}")
print(f"steer saturated (|s|>0.95): {np.mean(np.abs(steer)>0.95):.0%}   mean |steer| {np.abs(steer).mean():.2f}")
print(f"heading-to-target tracking: {'GOOD' if np.percentile(aa,90) < 30 else 'WOBBLY -- tune lookahead/gain'}")
