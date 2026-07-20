"""Per-section grip + slip from the 50-lap human reference run, using the DIRECTLY
MEASURED telemetry (ax = lateral accel, tire combined-slip), not the v^2*kappa estimate.

Produces:
  - per-section grip envelope (p95 |lateral g|) around the track
  - the combined-slip the car actually runs AT the grip limit (calibrates the grip-aware foot)
  - downforce check: does peak lateral g rise with speed? (direct, cleaner than geometry)
  - grade/elevation effect on grip
"""
import csv, glob
import numpy as np
from scipy.spatial import cKDTree

FILES = [r"C:\Users\talon\FH6-AFK-Farm\recordings\run_20260625_120122.csv",
         r"C:\Users\talon\FH6-AFK-Farm\recordings\run_20260625_120907.csv"]
PLAN = sorted(glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\*_plan.npz"))[-1]
p = np.load(PLAN)
line, elev, grade = p["line"], p["elev"], p["grade"]
N = len(line)

def colf(rows, n):
    return np.array([float(r[n]) if r.get(n) not in (None, "") else np.nan for r in rows])

rows = []
for f in FILES:
    rows += list(csv.DictReader(open(f)))
print(f"loaded {len(rows)} rows from {len(FILES)} files")

X, Z, Y = colf(rows, "pos_x"), colf(rows, "pos_z"), colf(rows, "pos_y")
SP = colf(rows, "speed_mps")
AX = colf(rows, "ax")                       # lateral accel, car-local (m/s^2)
AZ = colf(rows, "az")                       # longitudinal accel
STEER = colf(rows, "steer")
csr = np.maximum(np.abs(colf(rows, "combined_slip_rl")), np.abs(colf(rows, "combined_slip_rr")))  # rear
csf = np.maximum(np.abs(colf(rows, "combined_slip_fl")), np.abs(colf(rows, "combined_slip_fr")))  # front

drive = (SP * 3.6 > 25) & np.isfinite(X) & np.isfinite(AX) & (np.abs(AX) < 80)
X, Z, Y, SP, AX, AZ, csr, csf, STEER = [v[drive] for v in (X, Z, Y, SP, AX, AZ, csr, csf, STEER)]
latg = np.abs(AX) / 9.81
print(f"driving rows: {len(X)}   measured |lat g|: p50 {np.percentile(latg,50):.2f}  "
      f"p95 {np.percentile(latg,95):.2f}  p99 {np.percentile(latg,99):.2f}  max {latg.max():.2f}")

# nearest racing-line station for every point (KDTree, fast)
tree = cKDTree(line)
_, nearest = tree.query(np.c_[X, Z])
SECT = 24
sect = nearest * SECT // N

print(f"\nper-section MEASURED grip (p95 lateral g) + slip at the limit:")
print(f"{'sec':>3} {'station':>7} {'gripG':>6} {'slip@lim':>8} {'meanV':>6} {'elev':>6} {'grade%':>7} {'pts':>6}")
secG, secV, secEl, secGr = [], [], [], []
for s in range(SECT):
    m = sect == s
    if m.sum() < 30:
        continue
    g95 = np.percentile(latg[m], 95)
    # slip the car runs when near this section's grip limit (top 20% of lat g here)
    lim = latg[m] > 0.8 * g95
    slip_at_lim = np.median(csr[m][lim]) if lim.sum() > 5 else np.nan
    st = int(np.median(nearest[m]))
    secG.append(g95); secV.append(SP[m].mean()*3.6); secEl.append(elev[st]); secGr.append(grade[st]*100)
    print(f"{s:>3} {st:>7} {g95:>6.2f} {slip_at_lim:>8.2f} {SP[m].mean()*3.6:>6.0f} "
          f"{elev[st]:>6.1f} {grade[st]*100:>7.0f} {int(m.sum()):>6}")

secG = np.array(secG); secV = np.array(secV); secEl = np.array(secEl); secGr = np.array(secGr)
print(f"\ngrip envelope across sections: min {secG.min():.2f}g  median {np.median(secG):.2f}g  max {secG.max():.2f}g")

# grip-limit slip (global): combined-slip the car runs when pulling near-peak lateral g
hi = latg > np.percentile(latg, 90)
print(f"combined-slip AT the grip limit (top-10% lat g): rear median {np.median(csr[hi]):.2f}  "
      f"front median {np.median(csf[hi]):.2f}   => target slip for the grip-aware foot")

# downforce: peak lateral g vs speed (direct). bin by speed, take p95 lat g per bin.
print(f"\ndownforce check (p95 lateral g by speed bin):")
for lo, hivb in [(25,60),(60,100),(100,140),(140,180),(180,260)]:
    mm = (SP*3.6 >= lo) & (SP*3.6 < hivb)
    if mm.sum() > 50:
        print(f"  {lo:>3}-{hivb:<3} km/h: p95 lat g {np.percentile(latg[mm],95):.2f}  (n={int(mm.sum())})")
print(f"corr(speed, latg)={np.corrcoef(SP, latg)[0,1]:+.2f}  "
      f"section corr(grade,grip)={np.corrcoef(secGr,secG)[0,1]:+.2f}  corr(elev,grip)={np.corrcoef(secEl,secG)[0,1]:+.2f}")
