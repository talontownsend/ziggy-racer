"""Split the session into boundary-lap-1, boundary-lap-2, and hot phase; plot each
so we can confirm which is the left edge, which is the right, and trim the
turnaround. Heuristics: boundary laps come first and are slow; the hot phase is
the first sustained fast region; the two boundary laps split where the car returns
to the boundary-phase start."""
import csv
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

path = sys.argv[1]
rows = list(csv.DictReader(open(path)))
def arr(n): return np.array([float(x[n]) if x.get(n) not in (None, "") else np.nan
                             for x in rows])

px, pz = arr("pos_x"), arr("pos_z")
sp = arr("speed_mps") * 3.6
mv = (sp > 3) & ~((px == 0) & (pz == 0))
X, Z, S = px[mv], pz[mv], sp[mv]

# hot phase = first index where the next ~200 frames sustain a high median speed
first_hot = len(S)
for k in range(len(S) - 200):
    if np.median(S[k:k + 200]) > 120:
        first_hot = k
        break
print(f"moving frames: {len(S)}   hot phase starts at moving-idx {first_hot}")

Xb, Zb = X[:first_hot], Z[:first_hot]
ref = np.array([Xb[0], Zb[0]])
d = np.hypot(Xb - ref[0], Zb - ref[1])
left_end = len(Xb)
left = False
for k in range(len(d)):
    if d[k] > 100:
        left = True
    if left and d[k] < 30:
        left_end = k
        break
print(f"boundary frames: {len(Xb)}   lap1/lap2 split at boundary-idx {left_end}")

fig, ax = plt.subplots(1, 3, figsize=(22, 7))
ax[0].scatter(Xb[:left_end], Zb[:left_end], c=np.arange(left_end), s=4, cmap="winter")
ax[0].set_title(f"boundary seg 1  ({left_end} pts)"); ax[0].axis("equal")
ax[1].scatter(Xb[left_end:], Zb[left_end:], c=np.arange(len(Xb) - left_end), s=4, cmap="autumn")
ax[1].set_title(f"boundary seg 2  ({len(Xb)-left_end} pts)"); ax[1].axis("equal")
ax[2].scatter(X[first_hot:], Z[first_hot:], c=S[first_hot:], s=2, cmap="turbo")
ax[2].set_title(f"hot phase  ({len(S)-first_hot} pts)"); ax[2].axis("equal")
plt.tight_layout()
out = path.replace(".csv", "_segments.png")
plt.savefig(out, dpi=85)
print(f"saved {out}")
