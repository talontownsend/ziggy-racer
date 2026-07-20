"""Summarize a follow_log run: shifting (commanded vs effective), speed, dirt."""
import csv
import numpy as np

rows = list(csv.DictReader(open(r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv")))[-2800:]
def col(n): return np.array([float(r[n]) for r in rows])

gear, rpm, maxr = col("gear"), col("rpm"), col("max_rpm")
shift, ontrack, spd, i0 = col("shift"), col("on_track"), col("spd_kmh"), col("i0")
print(f"rows {len(rows)}  duration {rows[-1]['t']}s")
print(f"gears seen: {sorted(set(gear.astype(int)))}")
print(f"max_rpm field: {maxr.min():.0f}..{maxr.max():.0f}   observed rpm max: {rpm.max():.0f}")
print(f"shift commands: up={int((shift > 0).sum())}  down={int((shift < 0).sum())}")
print(f"speed max: {spd.max():.0f} km/h")
print(f"on track: {100*ontrack.mean():.0f}%   dirt frames: {int((ontrack == 0).sum())}")

# did gear ever change right after an up-shift command?
upcmds = np.where(shift > 0)[0]
changed = 0
for k in upcmds:
    if k + 20 < len(gear) and gear[k + 20] > gear[k]:
        changed += 1
print(f"up-shift commands that produced a gear change within ~0.3s: {changed}/{len(upcmds)}")

# dirt hotspots by line index
dirt = i0[ontrack == 0]
if len(dirt):
    hist, edges = np.histogram(dirt, bins=8, range=(0, 400))
    print("dirt by line index (0-400):")
    for h, e in zip(hist, edges[:-1]):
        if h:
            print(f"  idx {int(e):3d}-{int(e)+50:3d}: {h} frames")
