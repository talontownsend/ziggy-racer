"""Measure signed cross-track error in the last run and verify its sign matches alpha,
so the cross-track steering term will push toward the line (not away)."""
import csv
import numpy as np

log = list(csv.DictReader(open(r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv")))
def c(n): return np.array([float(r[n]) for r in log])

x, z, i0 = c("x"), c("z"), c("i0").astype(int)
alpha = np.radians(c("alpha_deg"))
spd = c("spd_kmh")
line = np.load(r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038_plan.npz")["line"]
n = len(line)

cte = np.zeros(len(x))
for k in range(len(x)):
    i, j = i0[k], (i0[k] + 1) % n
    tx, tz = line[j] - line[i]
    L = np.hypot(tx, tz) or 1.0
    tx, tz = tx / L, tz / L
    ox, oz = x[k] - line[i, 0], z[k] - line[i, 1]
    cte[k] = tz * ox - tx * oz                # car-right-of-path = positive

m = spd > 20
print(f"cross-track error (m): mean {cte[m].mean():+.1f}  abs-mean {np.abs(cte[m]).mean():.1f}  "
      f"max {np.abs(cte).max():.1f}")
print(f"corr(cte_signed, alpha) = {np.corrcoef(cte[m], alpha[m])[0,1]:+.3f}  "
      f"(want > 0 so adding the term aids alpha)")
