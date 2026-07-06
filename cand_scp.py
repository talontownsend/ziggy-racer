#!/usr/bin/env python3
"""
Minimum-time racing line via Sequential Convex Programming (SCP).

The broken min_curvature_line linearizes curvature ONCE around the centerline:
    kappa ~= kref + (diag(kref^2)+D2) alpha
That surrogate is only valid for tiny offsets, so on a wide corridor minimizing it
walks the line to the OUTSIDE walls while TRUE curvature actually rises.

FIX (this module): RE-LINEARIZE around the CURRENT line every outer iteration.
From the current line compute its own arc-length and signed curvature kref_cur, build
the convex min-curvature surrogate in the GLOBAL offset variable alpha (offset onto the
centerline normal),
    kappa ~= kref_cur + (diag(kref_cur^2)+D2) (alpha - alpha_cur)
solve the convex QP, take a trust-region-limited step, and CLIP alpha into the corridor
box [lo,hi] every iterate. Re-linearizing about the moving line (rather than once about
the centerline) is what makes the iteration converge to the TRUE minimum-curvature
(apexing) line instead of walking to the outside walls.

Then a few velocity-profile-weighted SCP iterations (stations weighted ds/v^3 with a
late-apex exit gain) bias toward late apexes for straight exits, accepting only steps
that lower the true lap time.

Drop-in:
  min_time_line(left, right, veh, *, n=None, clear=0.02, safety=0.0, grade=None, **kw)
returns dict(line, speed, alpha, kappa, ds, lap_distance, lap_time_est, T_seed).
"""
from __future__ import annotations

import numpy as np

try:
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla
    _HAVE_SCIPY = True
except Exception:                                              # pragma: no cover
    _HAVE_SCIPY = False

from racing_line import (resample_closed, segment_lengths,
                         velocity_profile, grade_adjust)


def _frame(pts):
    """Unit tangent, unit left-normal, ds, signed curvature for a closed line."""
    tang = np.roll(pts, -1, axis=0) - np.roll(pts, 1, axis=0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])           # left normal
    ds = segment_lengths(pts)
    heading = np.arctan2(tang[:, 1], tang[:, 0])
    dtheta = np.angle(np.exp(1j * (np.roll(heading, -1) - heading)))
    kref = dtheta / np.maximum(ds, 1e-6)                       # signed curvature
    return tang, nrm, ds, kref


def _D2(N, dsm):
    """Closed second-difference operator (sparse), uniform-spacing form / dsm^2."""
    main = -2.0 * np.ones(N)
    off = np.ones(N)
    diags = [main, off, off, off, off]
    offsets = [0, 1, -1, N - 1, -(N - 1)]
    return sp.diags(diags, offsets, shape=(N, N), format="csr") / dsm ** 2


def _smooth_closed(a, w=7):
    if w <= 1:
        return a
    k = np.ones(w) / w
    if a.ndim == 1:
        return np.convolve(np.r_[a[-w:], a, a[:w]], k, "same")[w:-w]
    return np.column_stack([_smooth_closed(a[:, 0], w), _smooth_closed(a[:, 1], w)])


def _exit_gain(kappa_abs, ds, lam_late, L_ref, corner_thresh=1.0 / 80.0, max_look=220.0):
    """1 + lam_late*tanh(L_ahead/L_ref); L_ahead = straight length following a station."""
    n = len(ds)
    L_ahead = np.zeros(n)
    cs = np.concatenate([ds, ds])                             # for wrap
    kk = np.concatenate([kappa_abs, kappa_abs])
    for i in range(n):
        d = 0.0
        j = i
        while d < max_look and kk[j] < corner_thresh and j < i + n:
            d += cs[j]
            j += 1
        L_ahead[i] = d
    return 1.0 + lam_late * np.tanh(L_ahead / L_ref)


def min_time_line(left, right, veh, *, n=None, clear=0.02, safety=0.0, grade=None,
                  scp_iters=40, reg=1e-4, reg_smooth=3e-3, trust=1.0,
                  time_iters=8, lam_late=0.9, L_ref=55.0, final_smooth=5, **kw):
    """SCP minimum-time line. left/right are the already-resampled, already-inset
    corridor walls. Keeps the line strictly inside [lo,hi] (clips every iterate)."""
    left = np.asarray(left, float)
    right = np.asarray(right, float)
    if n is not None and n != len(left):
        left = resample_closed(left, n)
        right = resample_closed(right, n)
    N = len(left)

    if not _HAVE_SCIPY:
        return _dense_fallback(left, right, veh, clear, safety, grade,
                               scp_iters, reg, reg_smooth, trust, final_smooth)

    # ---- global corridor frame & box (alpha = offset along GLOBAL centerline normal) ----
    center = 0.5 * (left + right)
    _, cnrm, cds, _ = _frame(center)
    dsm = float(np.mean(cds))
    amax = np.sum((left - center) * cnrm, axis=1)              # offset to left wall
    amin = np.sum((right - center) * cnrm, axis=1)             # offset to right wall
    lo0, hi0 = np.minimum(amin, amax), np.maximum(amin, amax)
    lo = lo0 + (clear + safety)
    hi = hi0 - (clear + safety)
    bad = hi < lo                                              # too-narrow stations
    mid = 0.5 * (lo0 + hi0)
    lo = np.where(bad, mid, lo)
    hi = np.where(bad, mid, hi)

    def build(alpha):
        return center + np.clip(alpha, lo, hi)[:, None] * cnrm

    # ---- vehicle / speed oracle ----
    a_lat = veh["a_lat"]; v_max = veh["v_max"]; a_lat_k = veh.get("a_lat_k", 0.0)
    if grade is not None:
        aacc, abrk = grade_adjust(veh["a_acc"], veh["a_brake"], np.asarray(grade, float))
    else:
        aacc, abrk = veh["a_acc"], veh["a_brake"]

    def lap_time(line):
        v, kappa, ds = velocity_profile(line, a_lat, aacc, abrk, v_max, a_lat_k=a_lat_k)
        return float(np.sum(ds / np.maximum(v, 0.5))), v, kappa, ds

    D2 = _D2(N, dsm)
    S = (D2.T @ D2).tocsc()
    I = sp.identity(N, format="csc")

    # =====================================================================
    # PHASE 1 -- pure minimum-curvature via SCP (re-linearize each iteration)
    # =====================================================================
    alpha = np.zeros(N)                                        # start at centerline
    T_seed, v0, k0, ds0 = lap_time(build(alpha))

    tr = trust
    for _ in range(scp_iters):
        line = build(alpha)
        _, _, _, kcur = _frame(line)
        # surrogate: kappa(alpha) ~= kcur + B (alpha - alpha)   with B = diag(kcur^2)+D2
        # evaluated at current alpha -> residual r = kcur ; minimize ||kcur + B d||^2
        # over d = alpha_new - alpha, with smoothness + tikhonov.
        B = (sp.diags(kcur ** 2) + D2).tocsc()
        H = (B.T @ B + reg_smooth * S + reg * I).tocsc()
        rhs = -(B.T @ kcur)
        try:
            d = spla.spsolve(H, rhs)
        except Exception:
            break
        d = np.clip(d, -tr, tr)                                # trust region
        a_new = np.clip(alpha + d, lo, hi)                     # PROJECT to corridor box
        step = float(np.max(np.abs(a_new - alpha)))
        alpha = a_new
        if step < 1e-4:
            break

    line = build(alpha)
    T_mc, v, kappa, ds = lap_time(line)
    best_alpha = alpha.copy()
    best_T = T_mc

    # =====================================================================
    # PHASE 2 -- velocity-profile-weighted SCP (late-apex bias; monotone accept)
    # =====================================================================
    tr2 = trust
    for _ in range(time_iters):
        line_c = build(best_alpha)
        _, _, _, kcur = _frame(line_c)
        v, kappa, ds = velocity_profile(line_c, a_lat, aacc, abrk, v_max, a_lat_k=a_lat_k)
        w = ds / np.maximum(v, 8.0) ** 3
        w = w * _exit_gain(np.abs(kappa), ds, lam_late, L_ref)
        W = sp.diags(w)
        B = (sp.diags(kcur ** 2) + D2).tocsc()
        H = (B.T @ W @ B + reg_smooth * S + reg * I).tocsc()
        rhs = -(B.T @ (w * kcur))
        try:
            a_full = spla.spsolve(H, rhs)
        except Exception:
            break
        a_full = np.clip(a_full, lo, hi)
        d = np.clip(a_full - best_alpha, -tr2, tr2)
        a_try = np.clip(best_alpha + d, lo, hi)
        T_try, _, _, _ = lap_time(build(a_try))
        if T_try < best_T - 1e-4:
            best_alpha = a_try
            best_T = T_try
        else:
            tr2 *= 0.5
            if tr2 < 1e-2:
                break

    # ---- final smoothing, re-clip, re-profile; never ship worse than warm start ----
    line = build(best_alpha)
    line_s = _smooth_closed(line, final_smooth)
    a_fin = np.clip(np.sum((line_s - center) * cnrm, axis=1), lo, hi)
    line_fin = build(a_fin)
    Tf, vf, kappaf, dsf = lap_time(line_fin)
    if Tf > best_T + 1e-3:                                     # smoothing hurt -> revert
        a_fin = best_alpha
        line_fin = build(a_fin)
        Tf, vf, kappaf, dsf = lap_time(line_fin)

    return {"line": line_fin, "speed": vf, "alpha": a_fin, "kappa": kappaf, "ds": dsf,
            "lap_distance": float(dsf.sum()),
            "lap_time_est": float(Tf), "T_seed": float(T_seed)}


def _dense_fallback(left, right, veh, clear, safety, grade,
                    scp_iters, reg, reg_smooth, trust, final_smooth):
    """numpy-only path (no scipy). Same SCP, dense solves."""
    N = len(left)
    center = 0.5 * (left + right)
    _, cnrm, cds, _ = _frame(center)
    dsm = float(np.mean(cds))
    amax = np.sum((left - center) * cnrm, axis=1)
    amin = np.sum((right - center) * cnrm, axis=1)
    lo0, hi0 = np.minimum(amin, amax), np.maximum(amin, amax)
    lo = lo0 + (clear + safety); hi = hi0 - (clear + safety)
    bad = hi < lo; mid = 0.5 * (lo0 + hi0)
    lo = np.where(bad, mid, lo); hi = np.where(bad, mid, hi)
    eye = np.eye(N)
    D2 = (np.roll(eye, 1, 1) + np.roll(eye, -1, 1) - 2 * eye) / dsm ** 2
    Smat = D2.T @ D2
    a_lat = veh["a_lat"]; v_max = veh["v_max"]; a_lat_k = veh.get("a_lat_k", 0.0)
    if grade is not None:
        aacc, abrk = grade_adjust(veh["a_acc"], veh["a_brake"], np.asarray(grade, float))
    else:
        aacc, abrk = veh["a_acc"], veh["a_brake"]

    def build(alpha):
        return center + np.clip(alpha, lo, hi)[:, None] * cnrm

    def lap_time(line):
        v, kappa, ds = velocity_profile(line, a_lat, aacc, abrk, v_max, a_lat_k=a_lat_k)
        return float(np.sum(ds / np.maximum(v, 0.5))), v, kappa, ds

    alpha = np.zeros(N)
    T_seed = lap_time(build(alpha))[0]
    tr = trust
    for _ in range(scp_iters):
        _, _, _, kcur = _frame(build(alpha))
        B = np.diag(kcur ** 2) + D2
        H = B.T @ B + reg_smooth * Smat + reg * eye
        d = np.clip(np.linalg.solve(H, -(B.T @ kcur)), -tr, tr)
        a_new = np.clip(alpha + d, lo, hi)
        if np.max(np.abs(a_new - alpha)) < 1e-4:
            alpha = a_new; break
        alpha = a_new
    line = _smooth_closed(build(alpha), final_smooth)
    a_fin = np.clip(np.sum((line - center) * cnrm, axis=1), lo, hi)
    Tf, vf, kappaf, dsf = lap_time(build(a_fin))
    return {"line": build(a_fin), "speed": vf, "alpha": a_fin, "kappa": kappaf,
            "ds": dsf, "lap_distance": float(dsf.sum()),
            "lap_time_est": float(Tf), "T_seed": float(T_seed)}
