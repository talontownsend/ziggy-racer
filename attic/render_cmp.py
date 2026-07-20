"""Compact comparison render: planned line vs an actual clean lap, with a
full-res zoom on the ragged corner near (-1970,1610).

Writes recordings/cmp_corner.svg (small: int coords, zoom pre-filtered,
full-track context downsampled).
"""
import sys, glob
import numpy as np

LOG = r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv"
PLAN = sorted(glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\*_plan.npz"))[-1]
LAP = int(sys.argv[1]) if len(sys.argv) > 1 else 45

p = np.load(PLAN)
line, left, right = p["line"], p["left"], p["right"]

rows = []
with open(LOG) as fh:
    for ln in fh:
        ln = ln.strip()
        if not ln or ln[0].isalpha():
            continue
        c = ln.split(",")
        if len(c) < 29:
            continue
        try:
            rows.append((int(c[27]), float(c[1]), float(c[2])))
        except ValueError:
            continue
car = np.array([[x, z] for ln, x, z in rows if ln == LAP])
print(f"lap {LAP}: {len(car)} car points")

allp = np.vstack([left, right])
xmin, xmax = allp[:, 0].min(), allp[:, 0].max()
zmin, zmax = allp[:, 1].min(), allp[:, 1].max()


def transform(ox, oy, size, win):
    x0, x1, z0, z1 = win
    s = (size - 20) / max(x1 - x0, z1 - z0)

    def tf(pts):
        pts = np.asarray(pts, float)
        u = ox + 10 + (pts[:, 0] - x0) * s
        v = oy + 10 + (z1 - pts[:, 1]) * s
        return np.column_stack([u, v])
    return tf, s


def pts_str(uv):
    return " ".join(f"{round(a)},{round(b)}" for a, b in uv)


def runs_in_window(pts, win, tf):
    """split polyline into contiguous runs whose points fall in win."""
    x0, x1, z0, z1 = win
    pts = np.asarray(pts, float)
    inside = (pts[:, 0] >= x0) & (pts[:, 0] <= x1) & (pts[:, 1] >= z0) & (pts[:, 1] <= z1)
    out, cur = [], []
    for i, ins in enumerate(inside):
        if ins:
            cur.append(pts[i])
        elif cur:
            out.append(np.array(cur)); cur = []
    if cur:
        out.append(np.array(cur))
    return [pts_str(tf(r)) for r in out if len(r) > 1]


P = []
P.append('<svg viewBox="0 0 980 560" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">')
P.append('<rect width="980" height="560" fill="#111"/>')

# --- full-track context (left), downsampled ---
tfF, _ = transform(0, 0, 560, (xmin, xmax, zmin, zmax))
P.append(f'<polyline points="{pts_str(tfF(left[::8]))}" fill="none" stroke="#777" stroke-width="1.2"/>')
P.append(f'<polyline points="{pts_str(tfF(right[::8]))}" fill="none" stroke="#777" stroke-width="1.2"/>')
P.append(f'<polyline points="{pts_str(tfF(line[::6]))}" fill="none" stroke="#2a6fdb" stroke-width="2.2"/>')
P.append(f'<polyline points="{pts_str(tfF(car[::6]))}" fill="none" stroke="#e23b3b" stroke-width="1.5" opacity="0.9"/>')
cwin = (-1992, -1952, 1596, 1628)
cb = tfF(np.array([[cwin[0], cwin[3]], [cwin[1], cwin[2]]]))
P.append(f'<rect x="{round(cb[0,0])}" y="{round(cb[0,1])}" width="{round(cb[1,0]-cb[0,0])}" '
         f'height="{round(cb[1,1]-cb[0,1])}" fill="none" stroke="#f5c542" stroke-width="1.5" stroke-dasharray="4 3"/>')
P.append('<text x="14" y="24" fill="#ddd" font-size="15">full lap 45 — true CTE 0.30 m mean</text>')

# --- corner zoom (right), full-res, pre-filtered to window ---
tfZ, _ = transform(580, 0, 400, cwin)
P.append('<rect x="580" width="400" height="560" fill="#191919"/>')
for run in runs_in_window(left, cwin, tfZ):
    P.append(f'<polyline points="{run}" fill="none" stroke="#999" stroke-width="2"/>')
for run in runs_in_window(right, cwin, tfZ):
    P.append(f'<polyline points="{run}" fill="none" stroke="#999" stroke-width="2"/>')
for run in runs_in_window(line, cwin, tfZ):
    P.append(f'<polyline points="{run}" fill="none" stroke="#2a6fdb" stroke-width="3"/>')
for run in runs_in_window(car, cwin, tfZ):
    P.append(f'<polyline points="{run}" fill="none" stroke="#e23b3b" stroke-width="2.5" opacity="0.92"/>')
P.append('<text x="594" y="24" fill="#ddd" font-size="15">corner zoom (full-res, real data)</text>')
P.append('<text x="594" y="544" fill="#f5c542" font-size="12">gray = wall (ragged) · blue = line (smooth) · red = car</text>')
P.append('</svg>')

svg = "\n".join(P)
out = r"C:\Users\talon\FH6-AFK-Farm\recordings\cmp_corner.svg"
with open(out, "w") as fh:
    fh.write(svg)
print("wrote", out, len(svg), "chars")
