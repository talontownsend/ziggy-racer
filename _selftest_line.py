"""Self-test for racing_line on a synthetic STADIUM track (no game needed).

A stadium = two straights + two 180-degree ends. The racing line should use the
full width through the ends (out-apex-out), cutting curvature there, and run near
center on the straights -- a clear, racing-relevant curvature reduction. The speed
profile must respect grip / accel / brake / v_max.
"""
import numpy as np
from racing_line import (resample_closed, menger_curvature, min_curvature_line,
                         velocity_profile, plan_racing_line)

# --- build a stadium centerline: straights of half-length Ls, end radius Re ---
Ls, Re, half_w, k = 80.0, 30.0, 10.0, 90
top = np.column_stack([np.linspace(-Ls, Ls, k, endpoint=False), np.full(k, Re)])
a = np.linspace(np.pi / 2, -np.pi / 2, k, endpoint=False)
rcap = np.column_stack([Ls + Re * np.cos(a), Re * np.sin(a)])
bot = np.column_stack([np.linspace(Ls, -Ls, k, endpoint=False), np.full(k, -Re)])
a2 = np.linspace(-np.pi / 2, -3 * np.pi / 2, k, endpoint=False)
lcap = np.column_stack([-Ls + Re * np.cos(a2), Re * np.sin(a2)])
center = np.vstack([top, rcap, bot, lcap])

N = 360
center = resample_closed(center, N)
# normals from central differences, then offset to bounds
tang = np.roll(center, -1, axis=0) - np.roll(center, 1, axis=0)
tang /= np.linalg.norm(tang, axis=1, keepdims=True)
nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
left = center + half_w * nrm
right = center - half_w * nrm

# --- stage 1: line ---
line, offset = min_curvature_line(left, right)
k_center = menger_curvature(center)
k_line = menger_curvature(line)
s_center, s_line = float(np.sum(k_center ** 2)), float(np.sum(k_line ** 2))
in_bounds = bool(np.max(np.abs(offset)) <= half_w + 1e-6)   # within +/- half width
reduced = s_line < 0.85 * s_center

print(f"  line within corridor:     {in_bounds}")
print(f"  sum kappa^2 centerline:   {s_center:.5f}")
print(f"  sum kappa^2 racing line:  {s_line:.5f}  ({100*(1-s_line/s_center):.1f}% lower)")

# --- stage 2: speed profile ---
veh = {"a_lat": 12.0, "a_acc": 7.0, "a_brake": 11.0, "v_max": 80.0}
v, kappa, ds = velocity_profile(line, **veh)
v_corner = np.sqrt(veh["a_lat"] / np.maximum(kappa, 1e-6))
grip_ok = bool(np.all(v <= np.minimum(v_corner, veh["v_max"]) + 1e-6))
acc_used = (np.roll(v, -1) ** 2 - v ** 2) / (2 * ds)
long_ok = bool(np.all(acc_used <= veh["a_acc"] + 1e-3) and
               np.all(-acc_used <= veh["a_brake"] + 1e-3))
print(f"  speed within grip+v_max:  {grip_ok}")
print(f"  accel/brake feasible:     {long_ok}")
print(f"  v range:                  {v.min():.1f}..{v.max():.1f} m/s")

plan = plan_racing_line(left, right, veh, n=N)
print(f"  lap distance:             {plan['lap_distance']:.0f} m")
print(f"  est lap time:             {plan['lap_time_est']:.1f} s")

checks = {"alpha in bounds": in_bounds, "curvature reduced >=15%": reduced,
          "grip respected": grip_ok, "long. feasible": long_ok}
fail = [c for c, ok in checks.items() if not ok]
print()
for c, ok in checks.items():
    print(f"  {'OK ' if ok else 'XX '} {c}")
if fail:
    raise SystemExit(f"\nFAILED: {fail}")
print("\nracing_line core verified: min-curvature line + feasible speed profile.")
