"""Overlay the follower's actual driven path on the corridor + planned line, and flag
where speed suddenly craters (wall impacts)."""
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

log = list(csv.DictReader(open(r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv")))
def c(n): return np.array([float(r[n]) for r in log])

t, x, z, spd = c("t"), c("x"), c("z"), c("spd_kmh")
i0, alpha, steer, thr = c("i0"), c("alpha_deg"), c("steer"), c("thr")
d = np.load(r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038_plan.npz")
left, right, line = d["left"], d["right"], d["line"]

dv = np.diff(spd, prepend=spd[0])
big = np.where(dv < -8)[0]                                # >8 km/h drop in one 16ms frame
# keep first of each cluster
clusters = [big[0]] if len(big) else []
for k in big[1:]:
    if k - clusters[-1] > 10:
        clusters.append(k)
print(f"{len(clusters)} sudden speed drops (likely impacts):")
for k in clusters[:12]:
    p = max(k - 1, 0)
    print(f"  t={t[k]:5.1f}s pos=({x[k]:7.0f},{z[k]:7.0f}) line_idx={int(i0[k]):3d} "
          f"spd {spd[p]:5.0f}->{spd[k]:5.0f} km/h  alpha={alpha[k]:+5.0f}  steer={steer[k]:+.2f}")

fig, ax = plt.subplots(figsize=(12, 11))
ax.plot(left[:, 0], left[:, 1], "k-", lw=1.2, label="walls")
ax.plot(right[:, 0], right[:, 1], "k-", lw=1.2)
ax.plot(line[:, 0], line[:, 1], "g--", lw=1.2, label="planned line")
sc = ax.scatter(x, z, c=spd, s=8, cmap="turbo", label="actual path (color=km/h)")
if clusters:
    ax.plot(x[clusters], z[clusters], "mx", ms=16, mew=3, label="impacts")
ax.plot(x[0], z[0], "ko", ms=9)
ax.set_aspect("equal"); ax.legend(); ax.set_title("follower path vs corridor")
fig.colorbar(sc, ax=ax)
plt.savefig(r"C:\Users\talon\FH6-AFK-Farm\recordings\crash.png", dpi=95)
print("saved crash.png")
