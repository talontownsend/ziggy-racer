#!/usr/bin/env python3
"""
Direct minimum-LAP-TIME racing line.

Why the shipped min_curvature_line / mlt_line are broken
-------------------------------------------------------
They linearize the curvature ONCE around the centerline
    kappa ~= kref + (diag(kref^2) + D2) alpha
That surrogate is only valid for tiny offsets. On a wide corridor, minimizing it walks
the line to the OUTSIDE wall (the surrogate keeps decreasing) while the TRUE curvature
rises -> curv_ratio > 1, apex_score ~ 0. We never trust a global curvature surrogate.

Pipeline
--------
0. SMOOTH SUB-CORRIDOR. The inset walls are jagged, so the per-station box [lo0,hi0] is
   jagged. A genuinely smooth, followable line (bounded heading-change-per-station) can
   only live inside a *smooth* corridor. We shrink the box to a smooth sub-corridor by a
   running-max of lo and running-min of hi (then a light average). Any line kept inside
   this sub-box is guaranteed inside the real jagged box -> out_of_corr = 0 for free,
   and there is room left for a smooth low-curvature path.

1. TRUE min-curvature warm start (convex QP, NOT once-linearized). With
   line = center + alpha*nrm we minimize the genuine discrete bending energy
   sum||line_{i-1} - 2 line_i + line_{i+1}||^2 -- exactly quadratic in alpha -- subject
   to the smooth box. Convex, valid for any offset, apexes correctly. Direct
   normal-equation solve + projected-gradient polish to honor the box.

2. DIRECT LAP-TIME local search. Deterministic greedy coordinate descent on the REAL
   grade-aware lap_time from velocity_profile: localized Gaussian "bumps" of alpha at
   deterministically chosen stations (seeded numpy Generator, no global RNG), accepted
   only when lap_time strictly improves. Trades a little corner radius for better
   straight exits (late apex).

3. FOLLOWABILITY finish. Resample to uniform arc length and lightly smooth (so the
   reported ds/R heading step and min_radius are honest), project back into the smooth
   sub-box. Kept whenever it does not worsen lap time materially.

Every iterate is clipped strictly inside the corridor box. Deterministic, no global
state. GRADE-AWARE via racing_line.grade_adjust.
"""
from __future__ import annotations

import numpy as np

from racing_line import (resample_closed, menger_curvature, segment_lengths,
                         velocity_profile, grade_adjust)


def _smooth1d(a, w):
    if w <= 1:
        return a
    k = np.ones(w) / w
    return np.convolve(np.r_[a[-w:], a, a[:w]], k, "same")[w:-w]


def _smooth2d(a, w):
    if w <= 1:
        return a
    return np.column_stack([_smooth1d(a[:, 0], w), _smooth1d(a[:, 1], w)])


def _running(a, w, op):
    """Periodic running reduction (op = np.max or np.min) over +/- w neighbours."""
    n = len(a)
    out = np.empty_like(a)
    for i in range(n):
        idx = (np.arange(i - w, i + w + 1)) % n
        out[i] = op(a[idx])
    return out


def _frame(left, right):
    center = 0.5 * (left + right)
    tang = np.roll(center, -1, axis=0) - np.roll(center, 1, axis=0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])             # left normal
    amax = np.sum((left - center) * nrm, axis=1)                 # offset to left wall
    amin = np.sum((right - center) * nrm, axis=1)                # offset to right wall
    return center, nrm, np.minimum(amin, amax), np.maximum(amin, amax)


def min_time_line(left, right, veh, *, n=None, clear=0.02, safety=0.0, grade=None,
                  shrink_win=7, bound_smooth=5,
                  reg_curv=0.04, warm_polish=2500,
                  outer=1100, win=55, bump_sigma=13.0,
                  final_smooth=15, lt_tol=0.5, **kw):
    """Minimum-lap-time line. left/right are already-resampled, already-inset corridor
    walls (Nx2). Returns dict(line, speed, alpha, kappa, ds, lap_distance,
    lap_time_est, T_seed). Line kept strictly inside the corridor box."""
    left = np.asarray(left, float)
    right = np.asarray(right, float)
    if n is not None and n != len(left):
        left = resample_closed(left, n)
        right = resample_closed(right, n)
    N = len(left)

    center, nrm, lo0, hi0 = _frame(left, right)

    # ---- (0) smooth sub-corridor inside the jagged true box ---------------- #
    margin = clear + safety
    lo_t = lo0 + margin                                          # true (jagged) box
    hi_t = hi0 - margin
    bad_t = hi_t < lo_t
    mid = 0.5 * (lo0 + hi0)
    lo_t = np.where(bad_t, mid, lo_t)
    hi_t = np.where(bad_t, mid, hi_t)

    lo = _smooth1d(_running(lo_t, shrink_win, np.max), bound_smooth)
    hi = _smooth1d(_running(hi_t, shrink_win, np.min), bound_smooth)
    # ensure the smooth sub-box stays within the true box and is non-empty
    lo = np.maximum(lo, lo_t)
    hi = np.minimum(hi, hi_t)
    bad = hi < lo
    midt = 0.5 * (lo_t + hi_t)
    lo = np.where(bad, midt, lo)
    hi = np.where(bad, midt, hi)

    a_lat = veh["a_lat"]; a_acc = veh["a_acc"]; a_brake = veh["a_brake"]
    v_max = veh["v_max"]; a_lat_k = veh.get("a_lat_k", 0.0)
    if grade is not None:
        aacc, abrk = grade_adjust(a_acc, a_brake, np.asarray(grade, float))
    else:
        aacc, abrk = a_acc, a_brake

    def clip(a):
        return np.clip(a, lo, hi)

    def build(a):
        return center + a[:, None] * nrm

    def lap_time_line(line):
        v, kappa, ds = velocity_profile(line, a_lat, aacc, abrk, v_max,
                                        a_lat_k=a_lat_k)
        return float(np.sum(ds / np.maximum(v, 0.5))), v, kappa, ds

    def lap_time(a):
        return lap_time_line(build(a))

    # seed = centerline (alpha = 0, clipped into the sub-box) ---------------- #
    alpha0 = clip(np.zeros(N))
    T_seed, _, _, _ = lap_time(alpha0)

    # ---- (1) TRUE min-curvature QP warm start ----------------------------- #
    eye = np.eye(N)
    D2 = np.roll(eye, 1, 1) + np.roll(eye, -1, 1) - 2 * eye      # 2nd diff (closed)
    Mx = D2 * nrm[:, 0][None, :]                                 # d(D2 line_x)/d alpha
    My = D2 * nrm[:, 1][None, :]
    bx = D2 @ center[:, 0]
    by = D2 @ center[:, 1]
    H = Mx.T @ Mx + My.T @ My + reg_curv * (D2.T @ D2) + 1e-6 * eye
    g = Mx.T @ bx + My.T @ by
    try:
        alpha = clip(np.linalg.solve(H, -g))
    except np.linalg.LinAlgError:
        alpha = clip(np.zeros(N))
    Lstep = np.linalg.norm(H, 2)
    for _ in range(warm_polish):
        alpha = clip(alpha - (H @ alpha + g) / Lstep)

    best_alpha = alpha.copy()
    best_T, _, _, _ = lap_time(best_alpha)

    # ---- (2) direct lap-time greedy coordinate descent -------------------- #
    rng = np.random.Generator(np.random.PCG64(12345))
    half = win // 2
    xk = np.arange(-half, half + 1)
    kern = np.exp(-0.5 * (xk / bump_sigma) ** 2)
    kern /= kern.max()
    span = hi - lo
    amps = np.array([0.5, 0.25, 0.12, -0.5, -0.25, -0.12, 0.8, -0.8])

    for it in range(outer):
        c = int(rng.integers(0, N))
        idx = (c + xk) % N
        local = float(np.median(span[idx]))
        for amp in amps:
            cand = best_alpha.copy()
            cand[idx] = np.clip(cand[idx] + amp * local * kern, lo[idx], hi[idx])
            T, _, _, _ = lap_time(cand)
            if T < best_T - 1e-5:
                best_alpha = cand
                best_T = T
                break
        if (it % 50) == 49:                                     # periodic smoothing move
            sm = clip(_smooth1d(best_alpha, 7))
            T, _, _, _ = lap_time(sm)
            if T < best_T - 1e-5:
                best_alpha = sm
                best_T = T

    # ---- (3) followability finish: uniform resample + smooth -------------- #
    line = build(best_alpha)
    line_u = resample_closed(line, N)
    line_u = _smooth2d(line_u, final_smooth)
    a_u = clip(np.sum((line_u - center) * nrm, axis=1))         # back into smooth box
    T_fin, _, _, _ = lap_time(a_u)

    if T_fin <= best_T + lt_tol:
        out_alpha = a_u
    else:
        out_alpha = best_alpha
    out_line = build(out_alpha)
    T_out, vf, kappaf, dsf = lap_time_line(out_line)

    # never ship worse than the trivial centerline seed
    if T_out > T_seed:
        out_alpha = alpha0
        out_line = build(alpha0)
        T_out, vf, kappaf, dsf = lap_time_line(out_line)

    return {"line": out_line, "speed": vf, "alpha": out_alpha, "kappa": kappaf,
            "ds": dsf, "lap_distance": float(dsf.sum()),
            "lap_time_est": float(T_out), "T_seed": float(T_seed)}
