"""Canonical scorer for racing-line optimizers, on the REAL corridor.

Usage:  python eval_optimizer.py <module> [func]
The module must expose  func(left, right, veh, *, n=None, clear=0.02,
safety=0.0, grade=None) -> dict with at least key "line" (Nx2 world x,z).
Default func = "min_time_line".  (Baseline: python eval_optimizer.py mlt_line)

Replicates build_corridor's inset corridor from the saved walls, runs the
candidate, and prints ONE json line of ground-truth metrics:

  curv_energy   integral(kappa^2 ds)      (lower better; MUST be < centerline)
  curv_ratio    curv_energy / centerline  (<1 = actually minimizing; >1 = BUG)
  lap_time_s    grade-aware velocity-profile lap time (lower better)  [PRIMARY]
  min_radius_m  1/max(menger curvature)   (followability; ~>=8 m ok)
  max_deg_step  max heading change/station (followability; <~6 ok)
  apex_score    fraction inside at corners (1 apex, 0 outside-hug)
  min_clear_m   min distance line->ORIGINAL wall (>=0; want a body margin)
  out_of_corr   stations outside the inset corridor (want 0)
"""
import sys, glob, json, importlib
import numpy as np
from racing_line import (menger_curvature, segment_lengths, velocity_profile,
                         grade_adjust)


def smooth_closed(a, w=7):
    k = np.ones(w) / w
    if a.ndim == 1:
        return np.convolve(np.r_[a[-w:], a, a[:w]], k, "same")[w:-w]
    return np.column_stack([smooth_closed(a[:, 0], w), smooth_closed(a[:, 1], w)])


def curv_energy(P):
    return float(np.sum(menger_curvature(P) ** 2 * segment_lengths(P)))


def build_inset(left, right):
    cen = 0.5 * (left + right)
    half = 0.5 * np.linalg.norm(left - right, axis=1)
    kcen = smooth_closed(menger_curvature(cen), 5)
    extra = np.clip((kcen - 1.0 / 25.0) * 40.0, 0.0, 1.5)
    MARGIN = 1.1 + extra
    inset = np.minimum(MARGIN, np.maximum(half - 0.75, 0.0))[:, None]
    ul = cen - left;  ul /= np.maximum(np.linalg.norm(ul, axis=1, keepdims=True), 1e-9)
    ur = cen - right; ur /= np.maximum(np.linalg.norm(ur, axis=1, keepdims=True), 1e-9)
    return left + inset * ul, right + inset * ur


def nearest_dist(pts, wall):
    A = wall; Bb = np.roll(wall, -1, 0); AB = Bb - A
    ab2 = np.einsum("ij,ij->i", AB, AB) + 1e-9
    out = np.empty(len(pts))
    for k, P in enumerate(pts):
        t = np.clip(np.einsum("ij,ij->i", P - A, AB) / ab2, 0, 1)
        d = P - (A + t[:, None] * AB)
        out[k] = np.sqrt(np.einsum("ij,ij->i", d, d).min())
    return out


def main():
    mod_name = sys.argv[1] if len(sys.argv) > 1 else "mlt_line"
    func_name = sys.argv[2] if len(sys.argv) > 2 else "min_time_line"
    PLAN = sorted(glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\*_plan.npz"))[-1]
    p = np.load(PLAN)
    left, right = p["left"], p["right"]
    grade = p["grade"] if "grade" in p else None
    N = len(left)
    iL, iR = build_inset(left, right)
    veh = dict(a_lat=2.3 * 9.81, a_lat_k=0.0, a_acc=11.0, a_brake=17.0, v_max=70.0)

    fn = getattr(importlib.import_module(mod_name), func_name)
    res = fn(iL, iR, veh, n=N, clear=0.02, safety=0.0, grade=grade)
    line = np.asarray(res["line"] if isinstance(res, dict) else res, float)

    # grade-aware lap time on the produced line
    if grade is not None:
        aacc, abrk = grade_adjust(veh["a_acc"], veh["a_brake"], grade)
    else:
        aacc, abrk = veh["a_acc"], veh["a_brake"]
    V, kap, ds = velocity_profile(line, veh["a_lat"], aacc, abrk, veh["v_max"])
    lap_time = float(np.sum(ds / np.maximum(V, 0.5)))

    # followability
    d = np.roll(line, -1, 0) - line
    heading = np.arctan2(d[:, 1], d[:, 0])
    dstep = np.degrees(np.abs(np.angle(np.exp(1j * np.diff(heading, append=heading[:1])))))
    mk = menger_curvature(line)
    min_radius = 1.0 / max(mk.max(), 1e-9)

    # apex score vs centerline corner direction
    icen = 0.5 * (iL + iR)
    tang = np.roll(icen, -1, 0) - np.roll(icen, 1, 0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
    dsc = segment_lengths(icen)
    hd = np.arctan2(tang[:, 1], tang[:, 0])
    kref = np.angle(np.exp(1j * (np.roll(hd, -1) - hd))) / np.maximum(dsc, 1e-6)
    amax = np.sum((iL - icen) * nrm, 1); amin = np.sum((iR - icen) * nrm, 1)
    a = np.sum((line - icen) * nrm, 1)
    inside = np.where(kref > 0, amax, amin); outside = np.where(kref > 0, amin, amax)
    frac = np.clip((a - outside) / (inside - outside + np.sign(inside - outside) * 1e-9), -0.3, 1.3)
    corner = np.abs(kref) > 1.0 / 60.0
    apex = float(frac[corner].mean())

    # clearance / corridor containment
    min_clear = float(min(nearest_dist(line, left).min(), nearest_dist(line, right).min()))
    lo = np.minimum(amin, amax); hi = np.maximum(amin, amax)
    out_corr = int(np.sum((a < lo - 0.05) | (a > hi + 0.05)))

    cen_energy = curv_energy(icen)
    le = curv_energy(line)
    m = dict(module=mod_name, func=func_name, lap_time_s=round(lap_time, 2),
             curv_energy=round(le, 3), curv_ratio=round(le / cen_energy, 3),
             min_radius_m=round(min_radius, 1), max_deg_step=round(float(dstep.max()), 2),
             apex_score=round(apex, 3), min_clear_m=round(min_clear, 2),
             out_of_corr=out_corr, top_kmh=round(float(V.max() * 3.6)))
    print(json.dumps(m))


if __name__ == "__main__":
    main()
