"""Diagnose whether the racing line USES THE TRACK WIDTH (apexes) or sits central.
For each station: line offset from corridor center, normalized to [-1(left wall)..+1(right wall)],
plus line curvature to mark straights vs corners. Reports per-section + saves a PNG."""
import numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import sys; sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from racing_line import menger_curvature, segment_lengths

p = np.load(r"C:\Users\talon\FH6-AFK-Farm\recordings\limits_edges_plan.npz")
L, left, right, V = p["line"], p["left"], p["right"], p["speed"]
N = len(L)
cen = 0.5 * (left + right)
half = 0.5 * np.linalg.norm(left - right, axis=1)              # half-width at each station
# unit normal (center->right) so +offset = toward right wall
nrm = right - cen; nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
off = np.sum((L - cen) * nrm, axis=1)                          # signed offset of line from center (m)
frac = np.clip(off / np.maximum(half, 1e-6), -1.2, 1.2)        # -1 left wall .. +1 right wall
kap = menger_curvature(L)                                      # line curvature (1/m)
ds = segment_lengths(L); s = np.cumsum(ds) - ds[0]             # arc length

# classify straights (low curvature) vs corners
straight = kap < (1.0/120.0)   # radius > 120 m ~ straight
print(f"corridor: {N} stations, lap {s[-1]:.0f} m, half-width {half.mean():.1f} m (min {half.min():.1f} max {half.max():.1f})")
print(f"line |offset/half|: mean {np.abs(frac).mean():.2f}  (1.0 = at a wall, 0 = dead center)")
print(f"  on STRAIGHTS (R>120m, {100*straight.mean():.0f}% of stations): mean |frac| {np.abs(frac[straight]).mean():.2f}")
print(f"  in CORNERS  (R<120m): mean |frac| {np.abs(frac[~straight]).mean():.2f}")
# how much of the available width does the line ever use?
print(f"  line offset range: {off.min():.1f} .. {off.max():.1f} m   (available: +-{half.mean():.1f} m)")
# fraction of straight stations where the line is basically central (<30% to a wall)
cent = straight & (np.abs(frac) < 0.3)
print(f"  straight stations sitting CENTRAL (|frac|<0.3): {100*cent.sum()/max(straight.sum(),1):.0f}%")

# find the longest straights and report their line usage + the corner that follows
seg_ids = np.zeros(N, int); cur = 0
for i in range(1, N):
    if straight[i] != straight[i-1]: cur += 1
    seg_ids[i] = cur
print("\nlongest straights (start_m, len_m, mean|frac| on straight, |frac| at its end=corner entry):")
runs = []
for sid in np.unique(seg_ids):
    idx = np.where(seg_ids == sid)[0]
    if straight[idx[0]] and len(idx) > 5:
        runs.append((s[idx].ptp(), idx))
for length, idx in sorted(runs, reverse=True)[:4]:
    entry = idx[-5:]   # last few stations = approach to the next corner
    print(f"  start {s[idx[0]]:.0f}m  len {length:.0f}m  mean|frac| {np.abs(frac[idx]).mean():.2f}  entry|frac| {np.abs(frac[entry]).mean():.2f}  V {V[idx].mean()*3.6:.0f}km/h")

fig, ax = plt.subplots(2, 1, figsize=(15, 8))
ax[0].fill_between(s, -1, 1, where=straight, color="0.9", label="straight")
ax[0].plot(s, frac, "b-", lw=1.2, label="line position (-1 left wall .. +1 right wall)")
ax[0].axhline(0, color="k", lw=0.5); ax[0].axhline(1, color="r", lw=0.4); ax[0].axhline(-1, color="r", lw=0.4)
ax[0].set_ylabel("line offset / half-width"); ax[0].legend(loc="upper right"); ax[0].set_ylim(-1.3, 1.3)
ax[0].set_title("does the line use the track width? (1=wall, 0=center; gray=straight)")
sc = ax[1].scatter(L[:,0], L[:,1], c=frac, cmap="coolwarm", s=10, vmin=-1, vmax=1)
ax[1].plot(left[:,0], left[:,1], "k-", lw=0.5); ax[1].plot(right[:,0], right[:,1], "k-", lw=0.5)
ax[1].axis("equal"); ax[1].set_title("line colored by position in corridor (blue=left wall, red=right wall)")
fig.colorbar(sc, ax=ax[1]); plt.tight_layout()
plt.savefig(r"C:\Users\talon\FH6-AFK-Farm\recordings\line_width_usage.png", dpi=90)
print("\nsaved recordings/line_width_usage.png")
