"""Fit the 2D surface sheet y(s, d) from survey sweep logs.
Per station: quadratic y(d) = a + b*d + c*d^2 over the offset bins covered
  -> local bank at any offset: tan(bank_left) = dy/dd = b + 2*c*d
  -> crown curvature: 2*c
  -> grade / vertical curvature along any candidate path: derivatives of the sheet.
VALIDATION (the acid test the edge-pair method failed):
  bank AT THE RACING LINE (d=0) must reproduce the camber-proxy signs and the user's
  ground truth: S11 off-camber (negative), S12 banked (positive), S1/S2 ~flat.
Cross-check: telemetry roll vs sheet slope.
Usage: python build_surface_sheet.py
"""
import csv, glob, os
import numpy as np
from scipy.spatial import cKDTree

REC = r"C:\Users\talon\FH6-AFK-Farm\recordings"
d0 = np.load(os.path.join(REC, "refline_plan.npz"))
line = d0["line"]; n = len(line)
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
tang = (np.roll(line, -1, 0) - np.roll(line, 1, 0))
tang /= np.linalg.norm(tang, axis=1, keepdims=True)
nrm = np.stack([-tang[:, 1], tang[:, 0]], axis=1)
tree = cKDTree(line)

a3, b3, c3 = np.roll(line, 1, 0), line, np.roll(line, -1, 0)
cross = (b3 - a3)[:, 0] * (c3 - b3)[:, 1] - (b3 - a3)[:, 1] * (c3 - b3)[:, 0]
la, lb, lc = (np.linalg.norm(v, axis=1) for v in ((b3 - a3), (c3 - b3), (c3 - a3)))
ks = 2.0 * cross / np.maximum(la * lb * lc, 1e-9)
for _ in range(3):
    ks = (np.roll(ks, 1) + ks + np.roll(ks, -1)) / 3.0

BINS = np.arange(-5.5, 6.5, 1.0)   # bin edges: centers -5..+5
NB = len(BINS) - 1
cells_y = [[[] for _ in range(NB)] for _ in range(n)]
cells_roll = [[[] for _ in range(NB)] for _ in range(n)]

_el = d0["elev"].copy()
for _ in range(5):
    _el = (np.roll(_el, 1) + _el + np.roll(_el, -1)) / 3.0
grade_ref = np.gradient(_el, s_of, edge_order=1)   # plan grade = the gate's reference

files = sorted(glob.glob(os.path.join(REC, "survey", "sweep_*.csv")))
print(f"sweep files: {len(files)}")
rows_used = 0
slope_rejected = 0
for path in files:
    rows = list(csv.DictReader(open(path)))
    # WALL-JUMP GATE (v2, RELATIVE): reject samples whose along-path slope deviates
    # from the PLAN's local grade by > 12% -- a wall climb deviates from what the road
    # is doing; a legitimately steep road does not. (v1 used an ABSOLUTE 15% threshold
    # and disqualified the -15.3% crest descents wholesale: 100% rejection at s592-598
    # -> empty cells -> the bumpy S7-S9 mesh the user spotted.) Dilated +-4 frames.
    bad = np.zeros(len(rows), bool)
    prev = None
    for ri, r in enumerate(rows):
        try:
            x, z, y = float(r["x"]), float(r["z"]), float(r["y"])
        except Exception:
            bad[ri] = True
            continue
        _, i_st = tree.query([x, z])
        if prev is not None:
            dsp = np.hypot(x - prev[0], z - prev[1])
            if dsp > 0.05 and abs((y - prev[2]) / dsp - grade_ref[i_st]) > 0.12:
                bad[max(0, ri - 4):ri + 5] = True
        prev = (x, z, y)
    slope_rejected += int(bad.sum())
    for ri, r in enumerate(rows):
        if bad[ri]:
            continue
        try:
            x, z = float(r["x"]), float(r["z"])
            y = float(r["y"]); roll = float(r["roll_deg"])
            spd = float(r["spd_kmh"])
            if spd < 15.0 or r["on_track"] != "1":
                continue
        except Exception:
            continue
        _, i = tree.query([x, z])
        off = (x - line[i, 0]) * nrm[i, 0] + (z - line[i, 1]) * nrm[i, 1]
        bi = np.searchsorted(BINS, off) - 1
        if 0 <= bi < NB:
            cells_y[i][bi].append(y)
            cells_roll[i][bi].append(roll)
            rows_used += 1
print(f"rows used: {rows_used} (slope-gate rejected {slope_rejected})")

centers = (BINS[:-1] + BINS[1:]) / 2
A = np.zeros(n); B = np.zeros(n); C = np.zeros(n)
DLO = np.full(n, -1.0); DHI = np.full(n, 1.0)     # surveyed offset coverage per station
cov = np.zeros(n, int); ok = np.zeros(n, bool)
for i in range(n):
    ds, ys = [], []
    for bi in range(NB):
        if len(cells_y[i][bi]) >= 5:
            ds.append(centers[bi]); ys.append(np.median(cells_y[i][bi]))
    cov[i] = len(ds)
    if len(ds) >= 3 and (max(ds) - min(ds)) >= 2.0:
        ds = np.array(ds); ys = np.array(ys)
        DLO[i], DHI[i] = ds.min(), ds.max()
        # CONDITIONING GUARD: a quadratic fitted on a narrow lateral span has an
        # ill-conditioned curvature term -- extrapolated past coverage it fabricates
        # mounds (the S3->S4 'bump': c fit on [-4,0] evaluated at d=-10.8 invented
        # +1.5 m of elevation). Span < 6 m -> fit line only (c = 0). 3-bin stations
        # (one-sided corridors collapse the sweeps onto few offsets, e.g. the s/f
        # straight) get line fits too: their own measured heights beat any neighbor
        # copy (neighbor fill imported -0.6 m dips = the two s/f bumps, 07-04).
        if len(ds) >= 4 and ds.max() - ds.min() >= 6.0:
            M = np.column_stack([np.ones(len(ds)), ds, ds ** 2])
            (A[i], B[i], C[i]), *_ = np.linalg.lstsq(M, ys, rcond=None)
        else:
            M = np.column_stack([np.ones(len(ds)), ds])
            (A[i], B[i]), *_ = np.linalg.lstsq(M, ys, rcond=None)
            C[i] = 0.0
        ok[i] = True
print(f"stations with sheet fit: {ok.sum()}/{n} (median bins {np.median(cov[ok]) if ok.any() else 0:.0f}, "
      f"line-only fits {int(((DHI - DLO) < 6.0)[ok].sum())})")
def smooth(a, w):
    out = a.copy()
    for _ in range(w):
        out = (np.roll(out, 1) + out + np.roll(out, -1)) / 3.0
    return out


# demote fitted stations whose height wildly disagrees with the plan elevation
# (garbage fits) -- they get filled like unfitted ones below
elev0 = d0["elev"]
offst = np.median((A - elev0)[ok][np.abs((A - elev0)[ok] - np.median((A - elev0)[ok])) < 1.0])
good = ok & (np.abs(A - (elev0 + offst)) <= 2.5)
print(f"fill needed at {int((~good).sum())} stations "
      f"({int(ok.sum() - good.sum())} demoted garbage fits)")

# ANCHORED-BLEND FILL (replaces neighbor-copy, which imported -0.6 m dips from 50
# stations away = the two s/f bumps): for each contiguous not-good run, A follows the
# PLAN ELEVATION SHAPE with a linear offset ramp matching the surveyed values at both
# run edges -- continuous at the joints by construction. B/C copy the nearest good.
gd = np.where(good)[0]
i = 0
while i < n:
    if good[i]:
        i += 1
        continue
    j = i
    while j < n and not good[j]:
        j += 1
    gL = (i - 1) % n
    gR = j % n
    # walk to actual good anchors (handles wrap)
    while not good[gL]:
        gL = (gL - 1) % n
    while not good[gR]:
        gR = (gR + 1) % n
    oL = A[gL] - elev0[gL]
    oR = A[gR] - elev0[gR]
    run = [(k % n) for k in range(i, j)]
    for m, k in enumerate(run):
        w = (m + 1) / (len(run) + 1)
        A[k] = elev0[k] + (1 - w) * oL + w * oR
        nearest = gL if m < len(run) / 2 else gR
        B[k] = B[nearest]; C[k] = C[nearest]
        DLO[k], DHI[k] = DLO[nearest], DHI[nearest]
    i = j

A, B, C = smooth(A, 4), smooth(B, 4), smooth(C, 4)
DLO, DHI = smooth(DLO, 2), smooth(DHI, 2)
# CONSUMER CONTRACT: evaluate y = a + b*d + c*d^2 only for d within [dlo, dhi];
# beyond, extend LINEARLY at the edge slope (b + 2*c*d_edge). Never let the
# quadratic curvature act outside its surveyed span.
np.savez(os.path.join(REC, "surface_sheet.npz"), a=A, b=B, c=C, dlo=DLO, dhi=DHI,
         coverage=cov, ok=ok)

# roll cross-check: sheet slope vs telemetry roll at matching cells
sl_pred, sl_roll = [], []
for i in range(0, n, 3):
    for bi in range(NB):
        if len(cells_roll[i][bi]) >= 8:
            sl_pred.append(np.degrees(np.arctan(B[i] + 2 * C[i] * centers[bi])))
            sl_roll.append(np.median(cells_roll[i][bi]))
if sl_pred:
    cc = np.corrcoef(sl_pred, sl_roll)[0, 1]
    print(f"roll cross-check: corr(sheet slope, telemetry roll) = {cc:.2f} over {len(sl_pred)} cells")

# THE ACID TEST: bank at the racing line vs ground truth + camber proxy
bank_line = np.arctan(-np.sign(ks) * B)
bank_line[np.abs(ks) < 5e-4] = 0.0
F = np.load(os.path.join(REC, "vtrim_features.npz"))
cam = F["camber"]
print(f"\n{'zone':>16} {'bank deg':>8} {'g*sin':>6} {'-proxy':>7}   (ground truth)")
for lo, hi, tag, gt in ((878, 994, "S12", "banked"), (785, 878, "S11", "off-camber"),
                        (60, 146, "S1", "flat"), (146, 250, "S2", "flat"),
                        (639, 704, "S9", "crest"), (545, 607, "S7", "crest+off-cam"),
                        (250, 361, "S3", "flat-ish fast")):
    mk = (s_of >= lo) & (s_of < hi) & (np.abs(ks) >= 5e-4)
    if mk.sum() == 0:
        continue
    bmed = np.median(bank_line[mk])
    print(f"{tag:>16} {np.degrees(bmed):8.1f} {9.81*np.sin(bmed):6.2f} {-np.median(cam[mk]):7.2f}   ({gt})")
print("\ncrown curvature (2c) med:", f"{np.median(2*C):.4f}",
      " |  crown p90:", f"{np.percentile(np.abs(2*C), 90):.4f}")
