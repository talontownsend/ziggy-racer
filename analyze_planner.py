"""Post-run analysis for the planner-based follower.

Reads follow_log.csv (with the new planner columns) + paths_log.jsonl and prints a
health report, then renders recordings/planner_viz.svg: racing line + actual driven
path + a sample of the planner's merge paths (so we can SEE it gliding onto the line).

Usage: python analyze_planner.py [last_n_rows]
"""
import sys, glob, json
import numpy as np

LOG = r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv"
PATHS = r"C:\Users\talon\FH6-AFK-Farm\recordings\paths_log.jsonl"
PLAN = sorted(glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\*_plan.npz"))[-1]
line = np.load(PLAN)["line"]

# column indices (0-based) of follow_log.csv
C = dict(t=0, x=1, z=2, spd=3, head=5, cte=10, steer=11, thr=12, brk=13, tgt=14,
         gear=15, rpm=16, ontrk=17, lapno=27, lapt=28, sideslip=29, d0=30, L=31,
         deg=32, psi=33, km=34, kapcar=35, vcurve=36, thrcap=37, yaw=38)

rows = []
for ln in open(LOG):
    ln = ln.strip()
    if not ln or ln[0].isalpha():
        continue
    p = ln.split(",")
    if len(p) < 39:
        continue
    try:
        rows.append([float(p[i]) for i in range(39)])
    except ValueError:
        continue
D = np.array(rows)
if len(D) == 0:
    print("no planner-format rows yet (is the new follow.py running?)"); sys.exit(0)
if len(sys.argv) > 1:
    D = D[-int(sys.argv[1]):]

t, x, z, spd = D[:, C["t"]], D[:, C["x"]], D[:, C["z"]], D[:, C["spd"]]
d0, L, deg = D[:, C["d0"]], D[:, C["L"]], D[:, C["deg"]]
ontrk, yaw, km = D[:, C["ontrk"]], D[:, C["yaw"]], D[:, C["km"]]
tgt, vcurve = D[:, C["tgt"]], D[:, C["vcurve"]]
dt = np.gradient(t); dspd = np.gradient(spd) / np.maximum(dt, 1e-3)

print(f"=== PLANNER RUN HEALTH ===  rows={len(D)}  dur={t[-1]-t[0]:.0f}s  speed {spd.min():.0f}-{spd.max():.0f} km/h")
print(f"on-track:        {100*ontrk.mean():5.1f}%   off-track rows {int((ontrk==0).sum())}")
print(f"TRUE line offset |d0|: mean {np.abs(d0).mean():.2f} m  p95 {np.percentile(np.abs(d0),95):.2f}  max {np.abs(d0).max():.2f}")
print(f"merge horizon L: mean {L[L>0].mean() if (L>0).any() else 0:.0f} m  range {L[L>0].min() if (L>0).any() else 0:.0f}-{L.max():.0f}")
print(f"degraded (no feasible merge): {100*deg.mean():.1f}% of frames")
print(f"merge-added curvature km_max: mean {km.mean():.4f}  max {km.max():.4f} 1/m")
print(f"spins (|yawrate|>2 rad/s): {int((np.abs(yaw)>2).sum())} frames  max {np.abs(yaw).max():.1f} rad/s")
print(f"hard speed-drops (<-60 km/h/s, impacts): {int((dspd<-60).sum())}  worst {dspd.min():.0f}")
binding = (vcurve > 0) & (np.abs(tgt - vcurve) < 1.0)
print(f"v_curve was the binding speed limit: {100*binding.mean():.0f}% of frames")
# lap times
laps = [lapt for lapt, lp in zip(D[:-1, C['lapt']], D[1:, C['lapt']]) if lp < lapt - 1 and lapt > 10]
print(f"completed lap times: {[round(x,2) for x in laps] if laps else 'none yet'}")

# ---- render merge paths over the line + driven path ----
try:
    paths = [json.loads(l) for l in open(PATHS) if l.strip()]
except FileNotFoundError:
    paths = []
if paths:
    if len(sys.argv) > 1:
        paths = paths[-max(1, int(int(sys.argv[1]) / 20)):]
    xs = np.r_[line[:, 0], x]; zs = np.r_[line[:, 1], z]
    x0, x1, z0, z1 = xs.min(), xs.max(), zs.min(), zs.max()
    s = 900 / max(x1 - x0, z1 - z0)
    def tf(px, pz):
        return 10 + (np.asarray(px) - x0) * s, 10 + (z1 - np.asarray(pz)) * s
    def poly(px, pz, stroke, w, op=1.0):
        u, v = tf(px, pz)
        pts = " ".join(f"{a:.0f},{b:.0f}" for a, b in zip(u, v))
        return f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="{w}" opacity="{op}"/>'
    W = int((x1 - x0) * s + 20); H = int((z1 - z0) * s + 20)
    out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg"><rect width="{W}" height="{H}" fill="#111"/>']
    out.append(poly(line[::3, 0], line[::3, 1], "#2a6fdb", 2))           # racing line
    out.append(poly(x[::4], z[::4], "#e23b3b", 1.5, 0.7))               # driven path
    step = max(1, len(paths) // 16)
    for pp in paths[::step]:                                            # sampled merge paths
        arr = np.array(pp["path"])
        out.append(poly(arr[:, 0], arr[:, 1], "#f5c542", 1.6, 0.9))
    out.append(f'<text x="14" y="22" fill="#ddd" font-size="16" font-family="sans-serif">blue=line  red=driven  yellow=merge paths ({len(paths)} dumped)</text>')
    out.append("</svg>")
    open(r"C:\Users\talon\FH6-AFK-Farm\recordings\planner_viz.svg", "w").write("\n".join(out))
    print(f"\nwrote recordings/planner_viz.svg ({len(paths)} merge paths, {step}x sampled)")
else:
    print("\nno paths_log.jsonl yet")
