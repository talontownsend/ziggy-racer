"""Taut elastic-band minimum-curvature racing line: relax each point toward the
chord of its neighbors (curvature reduction), HARD-clip to the corridor box (only a
car-body inset), iterate. The line pulls tight against the inside of corners (real
apex) and goes wide on entry/exit, using the full width -- what cand_grad won't do."""
import numpy as np, sys
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from build_corridor_edges import corridor_from_edges, line_metrics, save_plan, smooth_closed
from racing_line import velocity_profile, grade_adjust, menger_curvature

LEFT = r"recordings/limits_left/session_20260626_103954.csv"
RIGHT = r"recordings/limits_right/session_20260626_104413.csv"


def elastic_line(corr, inset_base=1.2, iters=3000, w=0.25, asmooth=0.06, wall_w=13,
                 final_smooth=5):
    # Box (clip limits) from MODERATELY smoothed walls so the line doesn't inherit wall
    # kinks, but clearance is always scored against the REAL (raw) walls outside.
    left = smooth_closed(corr["left"], wall_w)
    right = smooth_closed(corr["right"], wall_w)
    center = 0.5 * (left + right)
    tang = np.roll(center, -1, 0) - np.roll(center, 1, 0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
    amax = np.sum((left - center) * nrm, axis=1)
    amin = np.sum((right - center) * nrm, axis=1)
    lo = np.minimum(amin, amax) + inset_base
    hi = np.maximum(amin, amax) - inset_base
    bad = hi < lo; mid = 0.5 * (amin + amax)
    lo = np.where(bad, mid, lo); hi = np.where(bad, mid, hi)
    alpha = np.zeros(len(center))
    for _ in range(iters):
        line = center + alpha[:, None] * nrm
        chord = 0.5 * (np.roll(line, 1, 0) + np.roll(line, -1, 0))   # neighbor midpoint
        a_t = np.sum((chord - center) * nrm, axis=1)                 # project onto normal
        alpha = (1 - w) * alpha + w * a_t
        if asmooth > 0:
            alpha = (1 - asmooth) * alpha + asmooth * smooth_closed(alpha, 3)
        alpha = np.clip(alpha, lo, hi)                             # HARD clip into corridor
    line = center + alpha[:, None] * nrm
    if final_smooth > 1:                                           # knock down residual kinks
        line = smooth_closed(line, final_smooth)
        a2 = np.clip(np.sum((line - center) * nrm, axis=1), lo, hi)  # keep it in the box
        line = center + a2[:, None] * nrm
    return line


corr = corridor_from_edges(LEFT, RIGHT, lap=1, a_lat_g=2.45)
veh, grade = corr["veh"], corr["grade"]
aacc, abrk = grade_adjust(veh["a_acc"], veh["a_brake"], grade)
print()
hdr = f"{'inset':>5} {'iters':>5} {'apex':>5} {'centr%':>6} {'width':>5} {'p99turn':>7} {'worst':>6} {'clear':>5} {'lap_s':>6} {'top':>4}"
print(hdr); print("-" * len(hdr))
best = None
for wall_w in (9, 13, 17):
    for inset in (1.3, 1.8, 2.3):
        lab = f"w{wall_w}/{inset}"
        L = elastic_line(corr, inset_base=inset, iters=3000, wall_w=wall_w, final_smooth=5)
        V, _, ds = velocity_profile(L, veh["a_lat"], aacc, abrk, veh["v_max"], a_lat_k=veh["a_lat_k"])
        m = line_metrics(corr["left"], corr["right"], L, V)
        gate = m["max_turn"] <= 10.0 and m["min_clear"] >= 1.0
        print(f"{lab:9} {m['apex_corner']:5.2f} {m['central_straight']*100:6.0f} "
              f"{m['width_used']:5.1f} {m['max_turn']:7.1f} {m['worst_turn']:6.1f} "
              f"{m['min_clear']:5.2f} {m['lap_time']:6.1f} {m['top_kmh']:4.0f}  {'OK' if gate else ''}")
        if gate:
            score = m["apex_corner"] - 0.2 * m["central_straight"]
            if best is None or score > best[0]:
                best = (score, lab, L, V, m)
if best:
    _, inset, L, V, m = best
    print(f"\nPICK elastic inset={inset}: apex {m['apex_corner']:.2f}, central {m['central_straight']*100:.0f}%, "
          f"width {m['width_used']:.1f}/{2*m['half_mean']:.1f}m, p99turn {m['max_turn']:.1f}, clear {m['min_clear']:.2f}, lap {m['lap_time']:.1f}s")
    save_plan(corr, L, V, out=r"C:\Users\talon\FH6-AFK-Farm\recordings\limits_edges_v2")
    print("saved recordings/limits_edges_v2_plan.npz (+ .png, .json)")
