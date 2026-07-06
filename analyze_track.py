"""Visual + numeric overview of a session CSV: plot trajectory by time and by
speed so we can see the boundary laps, the turnaround, and the hot laps."""
import csv
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

path = sys.argv[1]
with open(path) as f:
    rows = list(csv.DictReader(f))


def arr(name):
    return np.array([float(x[name]) if x.get(name) not in (None, "") else np.nan
                     for x in rows])


px, pz = arr("pos_x"), arr("pos_z")
sp = arr("speed_mps") * 3.6
mv = (sp > 5) & ~((px == 0) & (pz == 0))
px, pz, sp = px[mv], pz[mv], sp[mv]
idx = np.arange(len(px))

print(f"moving frames: {len(px)}")
print(f"speed pct 50/90/99/max: "
      f"{np.percentile(sp,50):.0f}/{np.percentile(sp,90):.0f}/"
      f"{np.percentile(sp,99):.0f}/{sp.max():.0f} km/h")

fig, ax = plt.subplots(1, 3, figsize=(22, 7))
s0 = ax[0].scatter(px, pz, c=idx, s=2, cmap="viridis")
ax[0].set_title("by time (frame order)"); ax[0].axis("equal")
fig.colorbar(s0, ax=ax[0])

s1 = ax[1].scatter(px, pz, c=sp, s=2, cmap="turbo")
ax[1].set_title("by speed (km/h)"); ax[1].axis("equal")
fig.colorbar(s1, ax=ax[1])

# isolate the slow (boundary) frames -- below the 40th pct of speed
slow = sp < np.percentile(sp, 40)
s2 = ax[2].scatter(px[slow], pz[slow], c=idx[slow], s=3, cmap="coolwarm")
ax[2].set_title("slow frames only (boundary candidates), by time"); ax[2].axis("equal")
fig.colorbar(s2, ax=ax[2])

plt.tight_layout()
out = path.replace(".csv", "_overview.png")
plt.savefig(out, dpi=85)
print(f"saved {out}")
