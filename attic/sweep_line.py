"""Sweep the line-solve knobs (corner insets + diffusion) for a line that APEXES
(uses the track width) while staying followable + clear of the walls."""
import sys
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from build_corridor_edges import corridor_from_edges, solve_line, save_plan

LEFT = r"recordings/limits_left/session_20260626_103954.csv"
RIGHT = r"recordings/limits_right/session_20260626_104413.csv"

corr = corridor_from_edges(LEFT, RIGHT, lap=1, a_lat_g=2.45)
print()

# (label, iters2, build_extra_cap, solver_extra_cap)
CANDS = [
    ("OLD/timid",   600, 1.5, 3.5),     # the deployed line (baseline)
    ("A",           300, 0.5, 1.0),
    ("B",           200, 0.3, 0.6),
    ("C",           160, 0.3, 0.4),
    ("D",           120, 0.2, 0.3),
    ("E",            80, 0.2, 0.3),
    ("F",           160, 0.0, 0.3),
    ("G",           250, 0.4, 0.5),
]

hdr = f"{'cand':10} {'apex':>5} {'centr%':>6} {'width':>5} {'p99turn':>7} {'worst':>6} {'clear':>5} {'lap_s':>6} {'top':>4}"
print(hdr); print("-" * len(hdr))
rows = []
for label, it2, bcap, scap in CANDS:
    bgain = 40.0 if label == "OLD/timid" else 40.0
    L, V, m = solve_line(corr, iters2=it2, build_extra_cap=bcap, solver_extra_cap=scap)
    rows.append((label, it2, bcap, scap, L, V, m))
    print(f"{label:10} {m['apex_corner']:5.2f} {m['central_straight']*100:6.0f} "
          f"{m['width_used']:5.1f} {m['max_turn']:7.1f} {m['worst_turn']:6.1f} "
          f"{m['min_clear']:5.2f} {m['lap_time']:6.1f} {m['top_kmh']:4.0f}")

# auto-pick: best apex usage among the candidates that stay followable + safe.
# followability ceiling anchored to the OLD line's p99 turn (the car tracked it at 0.56m).
old = next(r for r in rows if r[0] == "OLD/timid")
turn_ceiling = old[6]["max_turn"] * 1.6      # allow up to 1.6x the timid line's p99 turn
ok = [r for r in rows if r[0] != "OLD/timid"
      and r[6]["max_turn"] <= turn_ceiling and r[6]["min_clear"] >= 0.4]
if ok:
    best = max(ok, key=lambda r: r[6]["apex_corner"] - 0.15 * r[6]["central_straight"])
    label = best[0]
    print(f"\nPICK: {label}  (apex {best[6]['apex_corner']:.2f}, central {best[6]['central_straight']*100:.0f}%, "
          f"p99turn {best[6]['max_turn']:.1f} <= ceiling {turn_ceiling:.1f}, clear {best[6]['min_clear']:.2f})")
    save_plan(corr, best[4], best[5], out=r"C:\Users\talon\FH6-AFK-Farm\recordings\limits_edges_v2")
    print("saved recordings/limits_edges_v2_plan.npz (+ .png, .json)")
else:
    print("\nno candidate passed followability/clearance gates -- inspect the table")
