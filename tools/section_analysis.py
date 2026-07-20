"""section_analysis.py — per-section co-tuning map for the FH6 follower.

Maps the follower's achieved telemetry onto the racing line, bins the lap into
sections, and for each reports whether the car is UNDER-driving (room to corner
faster — controller/steering limited) or OVER-driving (at/over grip — sliding).

Grip model (measured from the 50-lap human run):
    a_lat(v) = 24.0 + 0.00383 * v^2   [m/s^2]   (2.45g base + downforce, v in m/s)

Usage: python section_analysis.py [n_sections]   (default 24)
"""
import sys, numpy as np
from scipy.spatial import cKDTree

PLAN = r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038_plan.npz"
LOG  = r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv"
NSEC = int(sys.argv[1]) if len(sys.argv) > 1 else 24

G = 9.81
def grip_g(v_ms):                      # available grip in g at speed v (m/s)
    return (24.0 + 0.00383 * v_ms**2) / G

# ---- load line + planned speed ----
d = np.load(PLAN)
line = d["line"]                       # (N,2) world x,z
vplan = d["speed"] if "speed" in d.files else None   # m/s per station
N = len(line)
# cumulative arc length -> station fraction
seg = np.r_[0.0, np.cumsum(np.hypot(*(np.diff(line, axis=0).T)))]
total = seg[-1]
tree = cKDTree(line)

# ---- load log (last ~3 laps) ----
hdr = open(LOG).readline().strip().split(",")
col = {name: i for i, name in enumerate(hdr)}
raw = np.genfromtxt(LOG, delimiter=",", skip_header=1)
raw = raw[~np.isnan(raw[:, col["x"]])]
raw = raw[raw[:, col["spd_kmh"]] > 5]
raw = raw[-9000:]                      # ~3 laps at 60Hz

X = raw[:, [col["x"], col["z"]]]
spd = raw[:, col["spd_kmh"]] / 3.6     # m/s
latg = np.abs(raw[:, col["meas_latg"]])
d0 = np.abs(raw[:, col["plan_d0"]])
ss = np.abs(raw[:, col["sideslip"]])
und = raw[:, col["under"]]
ovr = raw[:, col["over"]]
kap = np.abs(raw[:, col["kap_car"]])

_, idx = tree.query(X)                 # nearest station per log row
station = seg[idx] / total             # 0..1

print(f"line {total:.0f} m, {N} pts | log rows {len(raw)} | grip base 2.45g+downforce")
print(f"{'sec':>3} {'st%':>4} {'curv':>6} {'vplan':>5} {'vach':>5} {'latg':>5} "
      f"{'grip':>5} {'use%':>4} {'d0':>4} {'slip':>4} {'un%':>3} {'ov%':>3}  verdict")
for s in range(NSEC):
    lo, hi = s / NSEC, (s + 1) / NSEC
    m = (station >= lo) & (station < hi)
    if m.sum() < 5:
        continue
    vp = np.nan
    if vplan is not None:
        sm = (seg / total >= lo) & (seg / total < hi)
        if sm.any(): vp = np.median(vplan[sm]) * 3.6
    vach = np.median(spd[m]) * 3.6
    lg = np.percentile(latg[m], 85)
    gv = grip_g(np.median(spd[m]))
    use = 100 * lg / gv                 # % of grip used
    dd = np.percentile(d0[m], 85)
    sl = np.percentile(ss[m], 85)
    un = 100 * und[m].mean()
    ov = 100 * ovr[m].mean()
    cv = np.median(kap[m])
    # verdict
    if sl > 7 or use > 95:
        v = "OVER-drive (sliding/at grip)"
    elif use < 70 and cv > 0.02:
        v = "UNDER-drive (room: +%.0f%% grip)" % (gv / lg * 100 - 100)
    elif un > 30:
        v = "understeer-ease firing"
    else:
        v = "ok"
    print(f"{s:>3} {lo*100:>4.0f} {cv:>6.3f} {vp:>5.0f} {vach:>5.0f} {lg:>5.2f} "
          f"{gv:>5.2f} {use:>4.0f} {dd:>4.1f} {sl:>4.1f} {un:>3.0f} {ov:>3.0f}  {v}")
