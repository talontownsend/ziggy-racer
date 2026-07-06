"""Non-convex test: a chicane (sine) corridor with alternating bends.

For a sine centerline, the minimum-curvature line must REDUCE the oscillation
amplitude -> cut the inside of each bend (apex), alternating sides. If
min_curvature_line apexes here (frac -> high at the bends) the algorithm is
sound and the real-track outside-hug is because that track is quasi-convex and
min-CURVATURE is the wrong objective (we need min-LAP-TIME). If it fails here,
the algorithm is buggy.
"""
import sys
import numpy as np
from racing_line import min_curvature_line, resample_closed, segment_lengths

# closed chicane: a racetrack-ish loop = long sine "ribbon" closed by a return arc.
# Simpler: an ellipse-ish loop whose top and bottom edges wiggle (alternating bends).
N = 1200
s = np.linspace(0, 2*np.pi, N, endpoint=False)
# base loop (big ellipse) + sinusoidal wiggle superimposed along the path => chicanes
R = 80.0
wig_amp, wig_k = 14.0, 6            # 6 wiggles around the loop, +-14 m
base = np.column_stack([R*np.cos(s), 0.6*R*np.sin(s)])
# tangent/normal of base
tb = np.column_stack([-R*np.sin(s), 0.6*R*np.cos(s)])
tb /= np.linalg.norm(tb, axis=1, keepdims=True)
nb = np.column_stack([-tb[:, 1], tb[:, 0]])
cen = base + wig_amp*np.sin(wig_k*s)[:, None]*nb   # wiggled centerline (alternating curvature)
cen = resample_closed(cen, N)

tang = np.roll(cen, -1, 0) - np.roll(cen, 1, 0)
tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
HALF = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
left = cen + HALF*nrm
right = cen - HALF*nrm

ds = segment_lengths(cen)
heading = np.arctan2(tang[:, 1], tang[:, 0])
dtheta = np.angle(np.exp(1j*(np.roll(heading, -1) - heading)))
kref = dtheta/np.maximum(ds, 1e-6)
amax = np.sum((left-cen)*nrm, axis=1)
amin = np.sum((right-cen)*nrm, axis=1)
corner = np.abs(kref) > 1.0/60.0

line, alpha = min_curvature_line(left, right)
a = np.sum((line-cen)*nrm, axis=1)
inside = np.where(kref > 0, amax, amin)
outside = np.where(kref > 0, amin, amax)
frac = np.clip((a-outside)/(inside-outside+np.sign(inside-outside)*1e-9), -0.3, 1.3)
print(f"chicane loop: {N} pts, {corner.sum()} corner stations, both handedness "
      f"(kref {kref[corner].min():+.3f}..{kref[corner].max():+.3f})")
print(f"apex_score (1=apex/inside, 0=outside-hug): {frac[corner].mean():+.2f}  "
      f"median {np.median(frac[corner]):+.2f}")
print(f"line oscillation amp vs centerline: line {np.abs(a).max():.1f} m  (corridor +-{HALF})")
print("-> if apex_score is high, algorithm apexes when it should; real-track issue is the OBJECTIVE")

# DEFINITIVE: the solver claims to MINIMIZE integral(kappa^2 ds). The centerline
# (alpha=0) is always feasible. If the returned line has HIGHER curvature energy
# than the centerline, the optimizer is producing the WRONG sign (a real bug).
from racing_line import menger_curvature
def curv_energy(P):
    k = menger_curvature(P); d = segment_lengths(P)
    return float(np.sum(k**2 * d))
print(f"\ncurvature energy  integral(kappa^2 ds):")
print(f"   centerline (alpha=0, feasible): {curv_energy(cen):.3f}")
print(f"   returned 'min-curvature' line : {curv_energy(line):.3f}")
print("   -> if the returned line > centerline, the solver MAXIMIZED instead of minimized (BUG)")
