"""Does min_curvature_line apex on a CLEAN synthetic corridor?

Rounded-rectangle centerline, constant-width walls offset along the true normal.
If the line apexes here (apex_score -> 1 at the 4 corners) the algorithm is fine
and the real-track corridor data is the problem. If it anti-apexes here too, the
bug is in min_curvature_line itself.
"""
import numpy as np
from racing_line import min_curvature_line, segment_lengths

N = 1000
HALF = 5.0     # corridor half-width (10 m wide, like the real track)

# rounded-rectangle centerline
def rounded_rect(N, a=80, b=50, r=20):
    # build perimeter samples then resample uniformly
    import numpy as np
    seg = []
    # straight + quarter arcs, going CCW
    corners = [( a-r,  b-r, 0),     # top-right arc center, start angle 0..90
               (-a+r,  b-r, 90),
               (-a+r, -b+r, 180),
               ( a-r, -b+r, 270)]
    pts = []
    # bottom straight (y=-b) from x=-(a-r) to (a-r)
    pts += [( x, -b) for x in np.linspace(-(a-r), a-r, 60)]
    # right arc
    pts += [(a-r + r*np.cos(t), -(b-r) + r*np.sin(t)) for t in np.linspace(-np.pi/2, 0, 40)]
    pts += [(a-r + r*np.cos(t),  (b-r)*0 + (b-r)*0 + r*np.sin(t)) for t in []]
    pts += [(a, y) for y in np.linspace(-(b-r), b-r, 40)]
    pts += [(a-r + r*np.cos(t), (b-r) + r*np.sin(t)) for t in np.linspace(0, np.pi/2, 40)]
    pts += [(x, b) for x in np.linspace(a-r, -(a-r), 60)]
    pts += [(-(a-r) + r*np.cos(t), (b-r) + r*np.sin(t)) for t in np.linspace(np.pi/2, np.pi, 40)]
    pts += [(-a, y) for y in np.linspace(b-r, -(b-r), 40)]
    pts += [(-(a-r) + r*np.cos(t), -(b-r) + r*np.sin(t)) for t in np.linspace(np.pi, 1.5*np.pi, 40)]
    return np.array(pts)

from racing_line import resample_closed, menger_curvature
cen = resample_closed(rounded_rect(N), N)
tang = np.roll(cen, -1, 0) - np.roll(cen, 1, 0)
tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
nrm = np.column_stack([-tang[:, 1], tang[:, 0]])    # left normal
left = cen + HALF * nrm
right = cen - HALF * nrm

# corner direction from centerline
ds = segment_lengths(cen)
heading = np.arctan2(tang[:, 1], tang[:, 0])
dtheta = np.angle(np.exp(1j * (np.roll(heading, -1) - heading)))
kref = dtheta / np.maximum(ds, 1e-6)
amax = np.sum((left - cen) * nrm, axis=1)
amin = np.sum((right - cen) * nrm, axis=1)
corner = np.abs(kref) > 1.0 / 40.0

line, alpha = min_curvature_line(left, right)
a = np.sum((line - cen) * nrm, axis=1)
inside = np.where(kref > 0, amax, amin)
outside = np.where(kref > 0, amin, amax)
frac = np.clip((a - outside) / (inside - outside + np.sign(inside - outside)*1e-9), -0.3, 1.3)
print(f"synthetic rounded-rect, width {2*HALF} m, corner stations {corner.sum()}")
print(f"turn dir: {'CCW(+,left)' if kref[corner].mean()>0 else 'CW(-,right)'}  mean kref(corner)={kref[corner].mean():+.4f}")
print(f"apex_score (1=inside/apex, 0=outside-hug): {frac[corner].mean():+.2f}")
print(f"  median frac at corners: {np.median(frac[corner]):+.2f}")
print(f"  alpha range: {alpha.min():+.2f}..{alpha.max():+.2f}  (corridor +-{HALF})")
