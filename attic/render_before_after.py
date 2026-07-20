"""Before/after of the racing line on the SAME corridor.

OLD = the broken min_time_line (mlt_line) re-solved on the current walls (outside-hug).
NEW = the shipped line in plan.npz (cand_grad, apexing).
Writes recordings/before_after.svg (compact).
"""
import glob
import numpy as np
from racing_line import menger_curvature, segment_lengths
import mlt_line, cand_grad


def smooth_closed(a, w=7):
    k = np.ones(w) / w
    if a.ndim == 1:
        return np.convolve(np.r_[a[-w:], a, a[:w]], k, "same")[w:-w]
    return np.column_stack([smooth_closed(a[:, 0], w), smooth_closed(a[:, 1], w)])


PLAN = sorted(glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\*_plan.npz"))[-1]
p = np.load(PLAN)
left, right, new = p["left"], p["right"], p["line"]
grade = p["grade"] if "grade" in p else None
N = len(left)

cen = 0.5 * (left + right)
half = 0.5 * np.linalg.norm(left - right, axis=1)
kcen = smooth_closed(menger_curvature(cen), 5)
extra = np.clip((kcen - 1.0 / 25.0) * 40.0, 0.0, 1.5)
MARGIN = 1.1 + extra
inset = np.minimum(MARGIN, np.maximum(half - 0.75, 0.0))[:, None]
ul = cen - left;  ul /= np.maximum(np.linalg.norm(ul, axis=1, keepdims=True), 1e-9)
ur = cen - right; ur /= np.maximum(np.linalg.norm(ur, axis=1, keepdims=True), 1e-9)
iL, iR = left + inset * ul, right + inset * ur
veh = dict(a_lat=2.3 * 9.81, a_lat_k=0.0, a_acc=11.0, a_brake=17.0, v_max=70.0)
old = np.asarray(mlt_line.min_time_line(iL, iR, veh, n=N, grade=grade)["line"], float)

# zoom window = region of largest old-vs-new lateral difference
diff = np.linalg.norm(old - new, axis=1)
ci = int(np.argmax(smooth_closed(diff, 9)))
cx, cz = new[ci]
W = 55
cwin = (cx - W, cx + W, cz - W, cz + W)

xmin, xmax = np.vstack([left, right])[:, 0].min(), np.vstack([left, right])[:, 0].max()
zmin, zmax = np.vstack([left, right])[:, 1].min(), np.vstack([left, right])[:, 1].max()


def transform(ox, oy, size, win):
    x0, x1, z0, z1 = win
    s = (size - 20) / max(x1 - x0, z1 - z0)
    def tf(pts):
        pts = np.asarray(pts, float)
        return np.column_stack([ox + 10 + (pts[:, 0] - x0) * s, oy + 10 + (z1 - pts[:, 1]) * s])
    return tf


def pts(uv):
    return " ".join(f"{round(a)},{round(b)}" for a, b in uv)


def runs(poly, win, tf):
    x0, x1, z0, z1 = win
    poly = np.asarray(poly, float)
    ins = (poly[:, 0] >= x0) & (poly[:, 0] <= x1) & (poly[:, 1] >= z0) & (poly[:, 1] <= z1)
    out, cur = [], []
    for i, b in enumerate(ins):
        if b:
            cur.append(poly[i])
        elif cur:
            out.append(np.array(cur)); cur = []
    if cur:
        out.append(np.array(cur))
    return [pts(tf(r)) for r in out if len(r) > 1]


P = ['<svg viewBox="0 0 980 560" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">',
     '<rect width="980" height="560" fill="#111"/>']
# full panel
tfF = transform(0, 0, 560, (xmin, xmax, zmin, zmax))
P.append(f'<polyline points="{pts(tfF(left[::6]))}" fill="none" stroke="#777" stroke-width="1.2"/>')
P.append(f'<polyline points="{pts(tfF(right[::6]))}" fill="none" stroke="#777" stroke-width="1.2"/>')
P.append(f'<polyline points="{pts(tfF(old[::4]))}" fill="none" stroke="#e23b3b" stroke-width="1.6" opacity="0.85"/>')
P.append(f'<polyline points="{pts(tfF(new[::4]))}" fill="none" stroke="#33d17a" stroke-width="2" opacity="0.95"/>')
cb = tfF(np.array([[cwin[0], cwin[3]], [cwin[1], cwin[2]]]))
P.append(f'<rect x="{round(cb[0,0])}" y="{round(cb[0,1])}" width="{round(cb[1,0]-cb[0,0])}" '
         f'height="{round(cb[1,1]-cb[0,1])}" fill="none" stroke="#f5c542" stroke-width="1.5" stroke-dasharray="4 3"/>')
P.append('<text x="14" y="24" fill="#ddd" font-size="15">full track</text>')
P.append('<text x="14" y="44" fill="#e23b3b" font-size="14">red = OLD line (44.8 s, outside-hug)</text>')
P.append('<text x="14" y="62" fill="#33d17a" font-size="14">green = NEW line (28.3 s, apexes)</text>')
# zoom
tfZ = transform(580, 0, 400, cwin)
P.append('<rect x="580" width="400" height="560" fill="#191919"/>')
for r in runs(left, cwin, tfZ):  P.append(f'<polyline points="{r}" fill="none" stroke="#999" stroke-width="2"/>')
for r in runs(right, cwin, tfZ): P.append(f'<polyline points="{r}" fill="none" stroke="#999" stroke-width="2"/>')
for r in runs(old, cwin, tfZ):   P.append(f'<polyline points="{r}" fill="none" stroke="#e23b3b" stroke-width="3" opacity="0.9"/>')
for r in runs(new, cwin, tfZ):   P.append(f'<polyline points="{r}" fill="none" stroke="#33d17a" stroke-width="3.5"/>')
P.append('<text x="594" y="24" fill="#ddd" font-size="15">biggest-difference corner (zoom)</text>')
P.append('</svg>')

svg = "\n".join(P)
out = r"C:\Users\talon\FH6-AFK-Farm\recordings\before_after.svg"
open(out, "w").write(svg)
print("wrote", out, len(svg), "chars; zoom centered station", ci, "pos", (round(cx), round(cz)))
