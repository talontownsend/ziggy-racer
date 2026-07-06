"""Turn a captured lap (recordings/frames/manifest.csv + PNGs) into review artifacts:
  - sheet_N.png : labeled contact sheets of every frame, in lap order (dirt = red)
  - lap_points.png : the track map with each captured frame plotted where it was taken
So a full lap can be eyeballed against the planned line at a glance."""
import csv
import math
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

DIR = r"C:\Users\talon\FH6-AFK-Farm\recordings\frames"
MAN = os.path.join(DIR, "manifest.csv")
PLAN = r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038_plan.npz"

rows = list(csv.DictReader(open(MAN)))
if not rows:
    raise SystemExit("manifest is empty -- nothing captured yet")
print(f"{len(rows)} frames in manifest")

# ---------- contact sheets ----------
COLS, ROWS_PER = 6, 8
PER = COLS * ROWS_PER
nsheets = math.ceil(len(rows) / PER)
for s in range(nsheets):
    chunk = list(range(s * PER, min((s + 1) * PER, len(rows))))
    nrow = math.ceil(len(chunk) / COLS)
    fig, axes = plt.subplots(nrow, COLS, figsize=(COLS * 2.7, nrow * 2.0))
    axes = np.array(axes).reshape(-1)
    for ax in axes:
        ax.axis("off")
    for k, gi in enumerate(chunk):
        r = rows[gi]
        ax = axes[k]
        try:
            im = Image.open(r["png"]).convert("RGB")
            im.thumbnail((360, 225))
            ax.imshow(im)
        except Exception as e:
            ax.text(0.5, 0.5, f"(missing)\n{e.__class__.__name__}", ha="center", va="center", fontsize=6)
        dirt = r["on_track"] == "0"
        ax.set_title(f"#{r['seq']}  i{r['i0']}  {r['spd_kmh']}km/h  cte{r['cte_m']}" + ("  DIRT" if dirt else ""),
                     fontsize=6.5, color=("#cc0000" if dirt else "#222222"))
        if dirt:
            ax.axis("on")
            ax.set_xticks([]); ax.set_yticks([])
            for sp in ax.spines.values():
                sp.set_color("#cc0000"); sp.set_linewidth(2.5)
    fig.suptitle(f"Captured lap — frames {chunk[0]}–{chunk[-1]} of {len(rows)-1}  (red = off-track)", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    out = os.path.join(DIR, f"sheet_{s+1}.png")
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print("wrote", out)

# ---------- map with capture points ----------
d = np.load(PLAN)
line, left, right = d["line"], d["left"], d["right"]
xs = np.array([float(r["x"]) for r in rows])
zs = np.array([float(r["z"]) for r in rows])
ot = np.array([int(r["on_track"]) for r in rows])

fig, ax = plt.subplots(figsize=(9, 8))
ax.plot(np.append(left[:, 0], left[0, 0]), np.append(left[:, 1], left[0, 1]), color="#999", lw=1.0)
ax.plot(np.append(right[:, 0], right[0, 0]), np.append(right[:, 1], right[0, 1]), color="#999", lw=1.0)
ax.plot(line[:, 0], line[:, 1], "--", color="#3a7fd0", lw=1.2, label="ideal line")
ax.scatter(xs[ot == 1], zs[ot == 1], c="#1d9e75", s=22, zorder=5, label="on track")
ax.scatter(xs[ot == 0], zs[ot == 0], c="#e24b4a", s=34, zorder=6, label="off track")
for i in range(0, len(rows), 5):
    ax.annotate(rows[i]["seq"], (xs[i], zs[i]), fontsize=6, color="#333",
                xytext=(3, 3), textcoords="offset points")
ax.scatter([line[0, 0]], [line[0, 1]], c="black", s=60, marker="s", zorder=7, label="S/F")
ax.set_aspect("equal"); ax.axis("off")
ax.legend(loc="upper right", fontsize=8)
ax.set_title(f"Captured-lap positions ({len(rows)} frames, {100*ot.mean():.0f}% on track)", fontsize=11)
out = os.path.join(DIR, "lap_points.png")
fig.savefig(out, dpi=130, bbox_inches="tight")
plt.close(fig)
print("wrote", out)
