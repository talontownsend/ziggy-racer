"""Per-lap analysis of a follower log against the planned racing line.

Computes, for each lap:
  - lap time (game's own lap timer, authoritative)
  - TRUE cross-track error: independent nearest-point distance from the car
    to the planned line polyline (NOT the follower's self-reported cte)
  - speed stats (mean/max), on-track fraction

Usage: python analyze_laps.py [log.csv] [plan.npz]
"""
import sys, glob, os
import numpy as np

LOG = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv"
PLAN = sys.argv[2] if len(sys.argv) > 2 else sorted(
    glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\*_plan.npz"))[-1]

# columns (1-indexed in the log): 1 t,2 x,3 z,4 spd_kmh,...,11 cte_m,...,18 on_track,28 lap_no,29 lap_t
COL = dict(t=0, x=1, z=2, spd=3, cte=10, on_track=17, lap_no=27, lap_t=28)

rows = []
with open(LOG) as fh:
    for ln in fh:
        ln = ln.strip()
        if not ln or ln[0].isalpha():   # skip header / blanks
            continue
        p = ln.split(",")
        if len(p) < 29:
            continue
        try:
            rows.append([float(p[i]) for i in range(29)])
        except ValueError:
            continue
D = np.array(rows)
if len(D) == 0:
    print("no data rows"); sys.exit(0)

plan = np.load(PLAN)
line = plan["line"]                      # (N,2) world x,z
A = line                                 # segment starts
B = np.roll(line, -1, axis=0)            # segment ends (closed)
AB = B - A
ab2 = np.einsum("ij,ij->i", AB, AB) + 1e-9

def true_cte(pts):
    """min perpendicular distance from each pt to the closed polyline (m)."""
    out = np.empty(len(pts))
    for k, P in enumerate(pts):
        t = np.clip(np.einsum("ij,ij->i", P - A, AB) / ab2, 0.0, 1.0)
        proj = A + t[:, None] * AB
        d2 = np.einsum("ij,ij->i", P - proj, P - proj)
        out[k] = np.sqrt(d2.min())
    return out

xz = D[:, [COL["x"], COL["z"]]]
lap_no = D[:, COL["lap_no"]].astype(int)
lap_t = D[:, COL["lap_t"]]
spd = D[:, COL["spd"]]
ontrk = D[:, COL["on_track"]]

cte = true_cte(xz)

print(f"log={os.path.basename(LOG)}  rows={len(D)}  plan={os.path.basename(PLAN)}  N_line={len(line)}")
print(f"{'lap':>4} {'time_s':>7} {'meanCTE':>8} {'maxCTE':>7} {'p95CTE':>7} {'meanV':>6} {'maxV':>6} {'onTrk%':>7} {'rows':>5}")
laps = sorted(set(lap_no))
results = []
for L in laps:
    m = lap_no == L
    if m.sum() < 20:
        continue
    # lap time = max game lap timer seen on this lap (just before reset)
    lt = lap_t[m].max()
    c = cte[m]
    res = dict(lap=L, time=lt, mean=c.mean(), mx=c.max(),
               p95=np.percentile(c, 95), meanV=spd[m].mean(),
               maxV=spd[m].max(), on=100*ontrk[m].mean(), n=int(m.sum()))
    results.append(res)
    print(f"{L:>4} {lt:>7.2f} {res['mean']:>8.3f} {res['mx']:>7.2f} "
          f"{res['p95']:>7.2f} {res['meanV']:>6.1f} {res['maxV']:>6.1f} "
          f"{res['on']:>7.1f} {res['n']:>5}")

# overall (exclude first/last partial laps for a fair tracking read)
if len(results) >= 1:
    allc = cte
    print(f"\noverall true cte: mean={allc.mean():.3f}m  p95={np.percentile(allc,95):.2f}m  max={allc.max():.2f}m")
    print(f"max speed seen: {spd.max():.1f} km/h   off-track rows: {(ontrk==0).sum()} ({100*(ontrk==0).mean():.1f}%)")
