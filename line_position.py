"""Where does the racing line sit between the walls, and is it on the
inside or the outside of each corner?

For each station i:
  t        = lateral fraction across the corridor (0 = on LEFT wall, 1 = RIGHT)
  width    = corridor width there (m)
  d_left   = distance from line to nearest point on LEFT wall (m)
  d_right  = distance from line to nearest point on RIGHT wall (m)
  kappa    = signed curvature of the line (left turn +, right turn -)
  inside   = which wall is the inside of the corner (L/R/--straight)
  hug      = '<' near left, '>' near right, '.' mid
  OUTSIDE  = line is hugging the wall OPPOSITE the corner's inside (the bug)
"""
import sys, glob
import numpy as np

PLAN = sys.argv[1] if len(sys.argv) > 1 else sorted(
    glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\*_plan.npz"))[-1]
p = np.load(PLAN)
line, left, right = p["line"], p["left"], p["right"]
N = len(line)


def nearest_dist(pts, wall):
    A = wall
    B = np.roll(wall, -1, axis=0)
    AB = B - A
    ab2 = np.einsum("ij,ij->i", AB, AB) + 1e-9
    out = np.empty(len(pts))
    for k, P in enumerate(pts):
        t = np.clip(np.einsum("ij,ij->i", P - A, AB) / ab2, 0, 1)
        proj = A + t[:, None] * AB
        d = P - proj
        out[k] = np.sqrt(np.einsum("ij,ij->i", d, d).min())
    return out


dL = nearest_dist(line, left)
dR = nearest_dist(line, right)
width = dL + dR
t = dL / np.maximum(width, 1e-6)            # 0 at left wall, 1 at right wall

# signed curvature of the line
d1 = np.gradient(line, axis=0)
d2 = np.gradient(d1, axis=0)
kappa = (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / (np.hypot(d1[:, 0], d1[:, 1])**3 + 1e-9)
# smooth curvature a touch for the inside/outside call
ks = np.convolve(np.r_[kappa[-5:], kappa, kappa[:5]], np.ones(11)/11, "same")[5:-5]

KTHR = 1/40.0   # ~40 m radius => treat as a corner
inside = np.where(ks > KTHR, "L", np.where(ks < -KTHR, "R", "-"))
near = np.where(t < 0.33, "<", np.where(t > 0.67, ">", "."))
# OUTSIDE bug: cornering but hugging the wall opposite the inside
outside_bug = ((inside == "L") & (t > 0.6)) | ((inside == "R") & (t < 0.4))

print(f"plan={PLAN}  N={N}")
print(f"corridor width: min={width.min():.1f} med={np.median(width):.1f} max={width.max():.1f} m")
print(f"\n   i   t   width  dL   dR   kappa   R(m)  inside near OUT")
for i in range(0, N, 20):
    R = 1/abs(ks[i]) if abs(ks[i]) > 1e-4 else 9999
    print(f"{i:4d} {t[i]:.2f} {width[i]:5.1f} {dL[i]:4.1f} {dR[i]:4.1f} "
          f"{ks[i]:+.4f} {R:6.0f}   {inside[i]:>3} {near[i]:>3}  {'X' if outside_bug[i] else ''}")

# longest runs of the outside bug
runs = []
i = 0
while i < N:
    if outside_bug[i]:
        j = i
        while j < N and outside_bug[j]:
            j += 1
        runs.append((i, j - 1, j - i))
        i = j
    else:
        i += 1
runs.sort(key=lambda r: -r[2])
print(f"\noutside-hug fraction of track: {100*outside_bug.mean():.0f}%")
print("longest outside-hug runs (start_i, end_i, len, worldpos@start):")
for a, b, L in runs[:8]:
    print(f"   i={a:4d}..{b:4d}  len={L:3d}  pos=({line[a,0]:.0f},{line[a,1]:.0f})")
