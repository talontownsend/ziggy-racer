"""Brute-force check whether the optimized racing line self-intersects, and draw a
clean large zoom of the start/finish."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

d = np.load(r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038_plan.npz")
L, left, right = d["line"], d["left"], d["right"]
n = len(L)


def seg_int(p1, p2, p3, p4):
    d1, d2 = p2 - p1, p4 - p3
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-9:
        return False
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / den
    u = ((p3[0] - p1[0]) * d1[1] - (p3[1] - p1[1]) * d1[0]) / den
    return 0 < t < 1 and 0 < u < 1


hits = []
for i in range(n):
    for j in range(i + 2, n):
        if i == 0 and j == n - 1:
            continue
        if seg_int(L[i], L[(i + 1) % n], L[j], L[(j + 1) % n]):
            hits.append((i, j))
print(f"line self-intersections: {len(hits)}  {hits[:8]}")

fig, ax = plt.subplots(figsize=(9, 9))
ax.plot(left[:, 0], left[:, 1], "b-", lw=1.5, label="left wall")
ax.plot(right[:, 0], right[:, 1], "r-", lw=1.5, label="right wall")
ax.plot(L[:, 0], L[:, 1], "g-", lw=2, label="racing line")
sf = L[0]
ax.plot(sf[0], sf[1], "ko", ms=8)
for (i, j) in hits:
    ax.plot(L[i, 0], L[i, 1], "mx", ms=12)
ax.set_xlim(sf[0] - 80, sf[0] + 80)
ax.set_ylim(sf[1] - 80, sf[1] + 80)
ax.set_aspect("equal")
ax.legend()
ax.set_title(f"start/finish zoom -- {len(hits)} line self-intersections")
plt.savefig(r"C:\Users\talon\FH6-AFK-Farm\recordings\seam_zoom.png", dpi=100)
print("saved seam_zoom.png")
