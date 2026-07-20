#!/usr/bin/env python3
"""
Racing-line generator (Stage 2 core).

Given the LEFT and RIGHT track boundaries (2D, world X/Z in meters) and a vehicle
limit model, produce:
  1. a minimum-curvature racing line inside the corridor, and
  2. a feasible target-speed profile along it.

Stage 1 (line):  the line point at each station is  P_i = L_i + alpha_i*(R_i - L_i),
alpha_i in [0,1]. We minimize sum||P_{i-1} - 2 P_i + P_{i+1}||^2 (discrete curvature)
by projected diagonal-Newton (Jacobi) descent with box constraints -- numpy only,
guaranteed to stay in the corridor.

Stage 2 (speed):  corner speed v = sqrt(a_lat_max / kappa), then a forward
accel-limited pass and backward brake-limited pass, capped at v_max. This is the
standard two-pass velocity profiling used in lap-time work.

Honest limitations (see the chat notes):
  - Min-curvature is near-optimal, not the true minimum-LAP-TIME line (which trades
    a little corner radius for better straight exits). Good first target; a later
    iteration can couple path + speed and optimize lap time directly.
  - The discrete-curvature proxy has a known spacing bias on long constant-radius
    arcs; it behaves well on real corner+straight tracks. Resample to ~uniform
    spacing first (resample_closed) to minimize it.
  - One a_lat for the whole track assumes uniform grip. The Colossus mixes surfaces
    and has jumps -- those want per-segment grip and break the planar model. Treat
    the output as "fast and reliable", not theoretically perfect, on mixed terrain.
"""
from __future__ import annotations

import numpy as np


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #
def resample_closed(pts: np.ndarray, n: int) -> np.ndarray:
    """Resample a closed polyline to n points at ~uniform arc length."""
    pts = np.asarray(pts, float)
    seg = np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])          # length len(pts)+1
    total = s[-1]
    targets = np.linspace(0.0, total, n, endpoint=False)
    closed = np.vstack([pts, pts[0]])
    x = np.interp(targets, s, closed[:, 0])
    y = np.interp(targets, s, closed[:, 1])
    return np.column_stack([x, y])


def menger_curvature(line: np.ndarray) -> np.ndarray:
    """Unsigned curvature (1/radius) at each point of a closed line, via the
    circumscribed circle of the three consecutive points (spacing-independent)."""
    p0 = np.roll(line, 1, axis=0)
    p1 = line
    p2 = np.roll(line, -1, axis=0)
    a = np.linalg.norm(p1 - p0, axis=1)
    b = np.linalg.norm(p2 - p1, axis=1)
    c = np.linalg.norm(p2 - p0, axis=1)
    cross = (p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - \
            (p1[:, 1] - p0[:, 1]) * (p2[:, 0] - p0[:, 0])
    area = 0.5 * np.abs(cross)
    denom = a * b * c
    return np.where(denom > 1e-9, 4.0 * area / denom, 0.0)


def segment_lengths(line: np.ndarray) -> np.ndarray:
    """ds[i] = distance from point i to point i+1 (closed)."""
    return np.linalg.norm(np.roll(line, -1, axis=0) - line, axis=1)


# --------------------------------------------------------------------------- #
# stage 1: minimum-curvature line
# --------------------------------------------------------------------------- #
def min_curvature_line(left: np.ndarray, right: np.ndarray,
                       reg: float = 1e-6, polish_iters: int = 600):
    """Return (line, offset). offset_i is the signed lateral displacement (meters)
    from the track centerline along its left normal; the line is in-corridor.

    TUM-style minimum-curvature formulation. With the path offset alpha(s) along the
    centerline normal, the new signed curvature linearizes to
        kappa_new ~= kappa_ref + kappa_ref^2 * alpha + alpha''
    (the alpha'' term lets the offset's bending cancel the reference curvature ->
    straighter line). We minimize ||kappa_new||^2 -- convex and quadratic in alpha --
    by a direct normal-equation solve, then a stable projected-gradient pass to honor
    the corridor bounds. Convexity avoids the local minima / zig-zags that sink the
    naive proxies. Resample inputs to ~uniform arc length first.
    """
    left = np.asarray(left, float)
    right = np.asarray(right, float)
    n = len(left)
    center = 0.5 * (left + right)

    tang = np.roll(center, -1, axis=0) - np.roll(center, 1, axis=0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])          # left normal
    ds = segment_lengths(center)
    dsm = float(np.mean(ds))

    heading = np.arctan2(tang[:, 1], tang[:, 0])
    dtheta = np.angle(np.exp(1j * (np.roll(heading, -1) - heading)))   # wrapped
    kref = dtheta / np.maximum(ds, 1e-6)                       # signed curvature

    amax = np.sum((left - center) * nrm, axis=1)              # offset to left wall
    amin = np.sum((right - center) * nrm, axis=1)             # offset to right wall
    lo, hi = np.minimum(amin, amax), np.maximum(amin, amax)

    eye = np.eye(n)
    d2 = (np.roll(eye, 1, axis=1) + np.roll(eye, -1, axis=1) - 2 * eye) / dsm ** 2
    B = np.diag(kref ** 2) + d2                                # kappa_new = kref + B@alpha
    H = B.T @ B + reg * eye
    alpha = np.clip(np.linalg.solve(H, -(B.T @ kref)), lo, hi)

    lr = 1.0 / (np.linalg.norm(B, 2) ** 2 + reg)
    for _ in range(polish_iters):
        grad = 2.0 * B.T @ (B @ alpha + kref) + 2.0 * reg * alpha
        alpha = np.clip(alpha - lr * grad, lo, hi)
    return center + alpha[:, None] * nrm, alpha


# --------------------------------------------------------------------------- #
# stage 2: speed profile
# --------------------------------------------------------------------------- #
def grade_adjust(a_acc: float, a_brake: float, grade: np.ndarray, g: float = 9.81):
    """Grade-correct the longitudinal accel/brake limits per station.

    grade = dz_up/ds_horizontal (signed; <0 downhill, >0 uphill). The gravity
    component along the road is g*sin(theta), theta=atan(grade). Downhill it ADDS to
    acceleration and SUBTRACTS from braking; uphill the reverse. Returns (aacc, abrk)
    arrays clamped to a small positive floor.
    """
    gphi = g * (np.asarray(grade, float) / np.sqrt(1.0 + np.asarray(grade, float) ** 2))
    aacc = np.maximum(a_acc - gphi, 0.5)        # downhill (gphi<0) -> more accel
    abrk = np.maximum(a_brake + gphi, 0.5)      # downhill (gphi<0) -> weaker braking
    return aacc, abrk


def velocity_profile(line: np.ndarray, a_lat: float, a_acc, a_brake,
                     v_max: float, a_lat_k: float = 0.0, passes: int = 4):
    """Feasible target speed at each point given grip/accel/brake/top-speed limits.

    Grip rises with speed from downforce: a_lat_max(v) = a_lat + a_lat_k * v**2.
    The cornering limit v**2 = a_lat_max/kappa then solves to v**2 = a_lat/(kappa -
    a_lat_k); where downforce grip already covers the corner (kappa <= a_lat_k) the
    point is limited only by v_max. a_lat_k=0 recovers constant grip.

    a_acc and a_brake may be scalars OR per-station arrays (length n) -- pass the
    grade-adjusted arrays from grade_adjust() to make braking/accel elevation-aware.

    Returns (v, kappa, ds): v respects speed-dependent cornering grip, forward
    acceleration, backward braking, and v_max.
    """
    kappa = menger_curvature(line)
    ds = segment_lengths(line)
    n = len(line)
    aacc = np.broadcast_to(np.asarray(a_acc, float), (n,))
    abrk = np.broadcast_to(np.asarray(a_brake, float), (n,))
    v = np.minimum(np.sqrt(a_lat / np.maximum(kappa - a_lat_k, 1e-6)), v_max)
    for _ in range(passes):
        for i in range(n):                       # forward: accel-limited
            j = (i - 1) % n
            cap = np.sqrt(v[j] ** 2 + 2.0 * aacc[j] * ds[j])
            if cap < v[i]:
                v[i] = cap
        for i in range(n - 1, -1, -1):           # backward: brake-limited
            j = (i + 1) % n
            cap = np.sqrt(v[j] ** 2 + 2.0 * abrk[i] * ds[i])
            if cap < v[i]:
                v[i] = cap
    return v, kappa, ds


# --------------------------------------------------------------------------- #
# convenience
# --------------------------------------------------------------------------- #
def plan_racing_line(left, right, vehicle: dict, n: int = 1200):
    """End-to-end: resample bounds -> min-curvature line -> speed profile.

    vehicle keys: a_lat, a_acc, a_brake, v_max  (SI: m/s^2, m/s).
    Returns dict with line, alpha, speed, kappa, ds, lap_distance, lap_time_est.
    """
    left = resample_closed(left, n)
    right = resample_closed(right, n)
    line, alpha = min_curvature_line(left, right)
    v, kappa, ds = velocity_profile(line, vehicle["a_lat"], vehicle["a_acc"],
                                    vehicle["a_brake"], vehicle["v_max"],
                                    a_lat_k=vehicle.get("a_lat_k", 0.0))
    return {
        "line": line, "alpha": alpha, "speed": v, "kappa": kappa, "ds": ds,
        "lap_distance": float(ds.sum()),
        "lap_time_est": float(np.sum(ds / np.maximum(v, 0.1))),
    }
