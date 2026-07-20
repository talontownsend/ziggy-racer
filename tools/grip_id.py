"""Per-section grip identification from the HUMAN hot laps (the data that actually
reached the limit). For each racing-line section we estimate the achievable lateral
grip a_lat = v^2 * kappa, and test its dependence on SPEED (downforce) and ELEVATION/
grade. This is the empirical foundation for co-tuning the line + follower grip.

Outputs:
  - per-section grip table (a_lat in g around the track) + where the tightest demand is
  - downforce fit: a_lat_max ~ a0 + k*v^2  (does grip rise with speed?)
  - elevation/grade effect on achievable grip
"""
import csv, glob
import numpy as np

SESS = r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038.csv"
PLAN = sorted(glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\*_plan.npz"))[-1]
p = np.load(PLAN)
line, elev, grade = p["line"], p["elev"], p["grade"]
N = len(line)

rows = list(csv.DictReader(open(SESS)))
def col(n): return np.array([float(r[n]) if r.get(n) not in (None, "") else np.nan for r in rows])
X, Z, Y, SP = col("pos_x"), col("pos_z"), col("pos_y"), col("speed_mps")
mv = (SP * 3.6 > 3) & ~((X == 0) & (Z == 0)) & np.isfinite(X)
X, Z, Y, SP = X[mv], Z[mv], Y[mv], SP[mv]

# hot portion = sustained high speed (the human's flying laps, not the slow boundary laps)
first_hot = len(SP)
for k in range(len(SP) - 200):
    if np.median(SP[k:k + 200] * 3.6) > 120:
        first_hot = k; break
Xh, Zh, Yh, SPh = X[first_hot:], Z[first_hot:], Y[first_hot:], SP[first_hot:]
print(f"hot-lap points: {len(SPh)}  (speed {SPh.min()*3.6:.0f}-{SPh.max()*3.6:.0f} km/h)")

# smooth the driven path, then menger curvature -> lateral accel a_lat = v^2 * kappa
def smooth(a, w=7):
    k = np.ones(w) / w
    return np.convolve(a, k, "same")
xs, zs = smooth(Xh, 9), smooth(Zh, 9)
p0 = np.c_[xs, zs]
pm1 = np.roll(p0, 1, 0); pp1 = np.roll(p0, -1, 0)
a = np.hypot(*(p0 - pm1).T); b = np.hypot(*(pp1 - p0).T); c = np.hypot(*(pp1 - pm1).T)
area = 0.5 * np.abs((p0[:,0]-pm1[:,0])*(pp1[:,1]-pm1[:,1]) - (p0[:,1]-pm1[:,1])*(pp1[:,0]-pm1[:,0]))
kappa = np.where(a*b*c > 1e-6, 4*area/(a*b*c), 0.0)
a_lat = SPh**2 * kappa                          # m/s^2
# drop the endpoints (roll wrap) and obviously bad curvature spikes
good = (kappa < 0.3) & (a_lat < 40) & np.isfinite(a_lat)
Xh, Zh, Yh, SPh, a_lat, kappa = [v[good] for v in (Xh, Zh, Yh, SPh, a_lat, kappa)]

# bin each hot point onto the nearest racing-line station, then into ~24 sections
nearest = np.array([np.argmin((line[:,0]-x)**2 + (line[:,1]-z)**2) for x, z in zip(Xh, Zh)])
SECT = 24
sect = (nearest * SECT // N)
print(f"\nper-section achievable grip (human hot laps), p90 lateral g:")
print(f"{'sec':>3} {'station':>8} {'gripG':>6} {'meanV':>6} {'maxV':>6} {'elev':>6} {'grade%':>7} {'pts':>5}")
grips = []
for s in range(SECT):
    m = sect == s
    if m.sum() < 8:
        continue
    g90 = np.percentile(a_lat[m], 90) / 9.81
    st = int(np.median(nearest[m]))
    grips.append((s, st, g90, SPh[m].mean()*3.6, SPh[m].max()*3.6, elev[st], grade[st]*100, m.sum()))
    print(f"{s:>3} {st:>8} {g90:>6.2f} {SPh[m].mean()*3.6:>6.0f} {SPh[m].max()*3.6:>6.0f} "
          f"{elev[st]:>6.1f} {grade[st]*100:>7.0f} {int(m.sum()):>5}")

G = np.array([g[2] for g in grips]); V = np.array([g[3] for g in grips])
EL = np.array([g[5] for g in grips]); GR = np.array([g[6] for g in grips])
print(f"\ngrip envelope: min {G.min():.2f}g  median {np.median(G):.2f}g  max {G.max():.2f}g")

# downforce: does achievable grip rise with speed? fit a_lat_g ~ a0 + k*(v_ms)^2
vms = V / 3.6
A = np.c_[np.ones_like(vms), vms**2]
coef, *_ = np.linalg.lstsq(A, G, rcond=None)
print(f"downforce fit: grip_g ~= {coef[0]:.2f} + {coef[1]*1e3:.3f}e-3 * v_ms^2   "
      f"(=> +{coef[1]*(50**2):.2f}g at 50 m/s vs 0)   corr(v,grip)={np.corrcoef(V,G)[0,1]:+.2f}")
print(f"elevation/grade effect: corr(grade,grip)={np.corrcoef(GR,G)[0,1]:+.2f}  "
      f"corr(elev,grip)={np.corrcoef(EL,G)[0,1]:+.2f}")
print(f"\n=> use ~{np.median(G):.2f}g baseline; per-section ranges {G.min():.2f}-{G.max():.2f}g feed the line re-plan.")
