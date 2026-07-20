#!/usr/bin/env python3
"""
Minimum-lap-time racing line (replaces the geometric min-curvature line).

Approach (design-panel "Variant C" + monotone accept/reject): parameterize the line
by one signed lateral offset alpha_i per station within the corridor, then ALTERNATE:
  (1) freeze the speed profile v(alpha) from velocity_profile (the same oracle the
      planner reports), build time-sensitivity weights w_i = ds_i / v_i**3 scaled by a
      late-apex "exit gain", and
  (2) minimize a convex time-weighted min-curvature surrogate in alpha (the same
      kappa_new ~= kref + (diag(kref^2)+D2) alpha linearization as min_curvature_line),
      clip to the corridor, trust-region the step, and ACCEPT only if the true lap time
      decreased.
Out-in-out lines and late apexes onto straights emerge from the 1/v**3 weighting + the
coupled forward/backward speed passes -- no hand-coded apex geometry. Never returns a
line slower than the min-curvature warm start.

GRADE-AWARE: pass `grade` (per-station dz_up/ds_horizontal) and the longitudinal accel/
brake limits are corrected for gravity along the slope (downhill brakes later / accels
harder; uphill the reverse) via racing_line.grade_adjust.
"""
from __future__ import annotations

import numpy as np

from racing_line import (menger_curvature, segment_lengths, min_curvature_line,
                         velocity_profile, grade_adjust)


def _smooth_closed(a, w=13):
    k = np.ones(w) / w
    if a.ndim == 1:
        return np.convolve(np.r_[a[-w:], a, a[:w]], k, "same")[w:-w]
    return np.column_stack([_smooth_closed(a[:, 0], w), _smooth_closed(a[:, 1], w)])


def _centerline_frame(left, right):
    center = 0.5 * (left + right)
    tang = np.roll(center, -1, axis=0) - np.roll(center, 1, axis=0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])              # left normal
    ds = segment_lengths(center)
    dsm = float(np.mean(ds))
    heading = np.arctan2(tang[:, 1], tang[:, 0])
    dtheta = np.angle(np.exp(1j * (np.roll(heading, -1) - heading)))
    kref = dtheta / np.maximum(ds, 1e-6)                          # signed curvature
    amax = np.sum((left - center) * nrm, axis=1)
    amin = np.sum((right - center) * nrm, axis=1)
    return center, nrm, dsm, kref, np.minimum(amin, amax), np.maximum(amin, amax)


def _exit_gain(kappa_abs, ds, lam_late, L_ref, corner_thresh=1.0 / 80.0, max_look=220.0):
    """1 + lam_late*tanh(L_ahead/L_ref); L_ahead = straight length following each station
    (so corner-exit stations feeding a long straight get up-weighted -> late apex)."""
    n = len(ds)
    L_ahead = np.zeros(n)
    for i in range(n):
        d, j = 0.0, i
        while d < max_look and kappa_abs[j] < corner_thresh:
            d += ds[j]
            j = (j + 1) % n
            if j == i:
                break
        L_ahead[i] = d
    return 1.0 + lam_late * np.tanh(L_ahead / L_ref)


def min_time_line(left, right, veh, *, n=None, clear=0.02, safety=0.0,
                  grade=None, lam_late=0.8, L_ref=60.0, reg_s=0.3, reg_a=1e-4,
                  outer=12, move_limit=0.6, polish=200, v_floor=0.5, w_vfloor=8.0):
    """Minimum-lap-time line. left/right are the (already-resampled, already-inset)
    corridor walls. Returns dict(line, speed, alpha, kappa, ds, lap_distance,
    lap_time_est, T_seed). Never worse than the min-curvature warm start."""
    left = np.asarray(left, float)
    right = np.asarray(right, float)
    N = len(left)
    center, nrm, dsm, kref, lo0, hi0 = _centerline_frame(left, right)
    lo = lo0 + (clear + safety)
    hi = hi0 - (clear + safety)
    bad = hi < lo                                                 # narrow stations
    mid = 0.5 * (lo0 + hi0)
    lo = np.where(bad, mid, lo)
    hi = np.where(bad, mid, hi)

    a_lat = veh["a_lat"]; a_acc = veh["a_acc"]; a_brake = veh["a_brake"]
    v_max = veh["v_max"]; a_lat_k = veh.get("a_lat_k", 0.0)
    if grade is not None:
        aacc, abrk = grade_adjust(a_acc, a_brake, np.asarray(grade, float))
    else:
        aacc, abrk = a_acc, a_brake

    def build(alpha):
        return center + alpha[:, None] * nrm

    def lap_time(line):
        v, kappa, ds = velocity_profile(line, a_lat, aacc, abrk, v_max, a_lat_k=a_lat_k)
        return float(np.sum(ds / np.maximum(v, v_floor))), v, kappa, ds

    # ---- warm start: min-curvature line (guaranteed valid fallback) ----
    try:
        _, alpha = min_curvature_line(left, right)
        alpha = np.clip(alpha, lo, hi)
    except Exception:
        alpha = np.clip(np.zeros(N), lo, hi)
    line = build(alpha)
    T_seed, v, kappa, ds = lap_time(line)
    T = T_seed
    best_alpha = alpha.copy()

    # ---- operators (same banded curvature surrogate as min_curvature_line) ----
    eye = np.eye(N)
    D2 = (np.roll(eye, 1, 1) + np.roll(eye, -1, 1) - 2 * eye) / dsm ** 2
    B = np.diag(kref ** 2) + D2
    S = D2.T @ D2

    ml = move_limit
    for _ in range(outer):
        w = (ds / np.maximum(v, w_vfloor) ** 3)                   # time sensitivity (v floored
                                                                  # so the slowest point can't get
                                                                  # pathological weight -> no kink)
        w = w * _exit_gain(np.abs(kappa), ds, lam_late, L_ref)    # late-apex bias
        W = np.diag(w)
        H = B.T @ W @ B + reg_s * S + reg_a * eye
        rhs = -(B.T @ (w * kref))
        try:
            a_new = np.linalg.solve(H, rhs)
        except np.linalg.LinAlgError:
            break
        # projected-gradient polish to honor box bounds
        a_new = np.clip(a_new, lo, hi)
        lr = 1.0 / (np.linalg.norm(B, 2) ** 2 * w.max() + reg_s * np.linalg.norm(S, 2) + reg_a)
        for _ in range(polish):
            grad = 2.0 * (B.T @ (w * (B @ a_new + kref))) + 2.0 * reg_s * (S @ a_new) + 2.0 * reg_a * a_new
            a_new = np.clip(a_new - lr * grad, lo, hi)
        # trust region around current alpha
        a_try = np.clip(alpha + np.clip(a_new - alpha, -ml, ml), lo, hi)
        line_try = build(a_try)
        T_try, v_try, kappa_try, ds_try = lap_time(line_try)
        if T_try < T - 1e-4:                                      # monotone accept
            alpha, line, v, kappa, ds, T = a_try, line_try, v_try, kappa_try, ds_try, T_try
            best_alpha = alpha.copy()
        else:
            ml *= 0.5                                             # reject -> shrink step
            if ml < 1e-2:
                break

    # ---- final smoothing (matches build_corridor), re-clip, re-profile ----
    line = build(best_alpha)
    line = _smooth_closed(line, 13)
    a_fin = np.clip(np.sum((line - center) * nrm, axis=1), lo, hi)
    line = build(a_fin)
    Tf, vf, kappaf, dsf = lap_time(line)
    if Tf > T_seed + 1e-3:                                        # never ship worse
        line = build(best_alpha)
        Tf, vf, kappaf, dsf = lap_time(line)
        a_fin = best_alpha
    return {"line": line, "speed": vf, "alpha": a_fin, "kappa": kappaf, "ds": dsf,
            "lap_distance": float(dsf.sum()),
            "lap_time_est": float(Tf), "T_seed": float(T_seed)}
