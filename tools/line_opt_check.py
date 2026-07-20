#!/usr/bin/env python3
"""line_opt_check.py -- independent checks on refline_plan_opt_candidate.npz.

Verifies (read-only, no farm files touched):
  1. schema/shape parity with refline_plan.npz
  2. curvature-rate through the RUNTIME's own LocalPlanner.kappa_ref (what the
     follower actually steers by), candidate vs human line
  3. wall clearance via exact point-to-wall-polyline distance (not station-aligned)
  4. section-by-section model speed comparison
"""
import os
import sys

import numpy as np

sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from local_planner import LocalPlanner        # noqa: E402
import line_opt_solver as S                   # noqa: E402  (loads maps, model)

REC = S.REC
cand = np.load(os.path.join(REC, "refline_plan_opt_candidate.npz"))
plan = np.load(os.path.join(REC, "refline_plan.npz"))

print("1) schema:", sorted(cand.files))
for k in plan.files:
    assert k in cand.files and cand[k].shape == plan[k].shape, f"schema mismatch {k}"
print("   shapes match refline_plan.npz")

line_o = cand["line"]; line_h = plan["line"]
kr_h = LocalPlanner(line_h, a_lat=27.0).kappa_ref
kr_o = LocalPlanner(line_o, a_lat=27.0).kappa_ref
seg_h = S.seg_of(line_h); seg_o = S.seg_of(line_o)
rate_h = S.krate_of(kr_h, seg_h); rate_o = S.krate_of(kr_o, seg_o)
print("2) LocalPlanner kappa_ref |dk/ds|  p50 / p90 / p99 / max")
print(f"   human {np.percentile(rate_h,50):.2e} {np.percentile(rate_h,90):.2e} "
      f"{np.percentile(rate_h,99):.2e} {rate_h.max():.2e}")
print(f"   cand  {np.percentile(rate_o,50):.2e} {np.percentile(rate_o,90):.2e} "
      f"{np.percentile(rate_o,99):.2e} {rate_o.max():.2e}")
print(f"   |kappa_ref| p90: human {np.percentile(np.abs(kr_h),90)*1000:.1f}e-3, "
      f"cand {np.percentile(np.abs(kr_o),90)*1000:.1f}e-3")


def min_dist_to_poly(pts, poly):
    """exact min distance from each pt to closed polyline (vectorized per segment)."""
    a = poly; b = np.roll(poly, -1, 0)
    ab = b - a; L2 = (ab ** 2).sum(1)
    out = np.full(len(pts), np.inf)
    for i in range(len(pts)):
        ap = pts[i] - a
        t = np.clip((ap * ab).sum(1) / np.maximum(L2, 1e-9), 0, 1)
        d = np.hypot(*(ap - t[:, None] * ab).T)
        out[i] = d.min()
    return out


dl = min_dist_to_poly(line_o, plan["left"])
dr = min_dist_to_poly(line_o, plan["right"])
print(f"3) exact wall clearance: min(left) {dl.min():.2f} m at {int(dl.argmin())}, "
      f"min(right) {dr.min():.2f} m at {int(dr.argmin())}")
dlh = min_dist_to_poly(line_h, plan["left"]); drh = min_dist_to_poly(line_h, plan["right"])
print(f"   (human line: {dlh.min():.2f} / {drh.min():.2f})")

# 4) model speed by ~100 m section
T_h, v_h, k_h, sg_h, _ = S.evaluate(S.E_H)
e_o = ((line_o - S.LINE_H) * S.NRM).sum(1)
T_o, v_o, k_o, sg_o, _ = S.evaluate(e_o)
print(f"4) model lap: human {T_h:.3f} s   candidate {T_o:.3f} s   delta {T_h-T_o:+.3f}")
s = np.concatenate([[0], np.cumsum(sg_h)])[:-1]
print("   sec  s-range      v_h    v_o   dT_ms")
for lo in range(0, 1050, 100):
    mk = (s >= lo) & (s < lo + 100)
    dt = (sg_h[mk] / v_h[mk] - sg_o[mk] / v_o[mk]).sum() * 1000
    print(f"   {lo:4d}-{lo+100:<4d}  {v_h[mk].mean():6.1f} {v_o[mk].mean():6.1f} {dt:+8.1f}")
print(f"   offset |e| mean {np.abs(e_o).mean():.2f} m, max {np.abs(e_o).max():.2f} m")
