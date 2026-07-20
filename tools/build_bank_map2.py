"""Bank map v2 -- from the EDGE recordings (limits_left / limits_right): two traces
~12 m apart laterally give bank = dy / d(lateral) with a wide baseline, driven slowly
(minimal suspension confound). The lap-spread regression (v1) was confounded by
cornering dynamics (read +3-6 deg 'bank' everywhere incl. known-flat sections).
Validation: g*sin(bank) vs the telemetry camber proxy + user ground truth
(S1/S2 flat, S11 off-camber, S12 banked, S7/S9 crests off-camber-ish).
"""
import csv
import numpy as np
from scipy.spatial import cKDTree

REC = r"C:\Users\talon\FH6-AFK-Farm\recordings"
d = np.load(REC + r"\refline_plan.npz")
line = d["line"]; n = len(line)
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
tang = (np.roll(line, -1, 0) - np.roll(line, 1, 0))
tang /= np.linalg.norm(tang, axis=1, keepdims=True)
nrm = np.stack([-tang[:, 1], tang[:, 0]], axis=1)   # left normal
tree = cKDTree(line)

a3, b3, c3 = np.roll(line, 1, 0), line, np.roll(line, -1, 0)
cross = (b3 - a3)[:, 0] * (c3 - b3)[:, 1] - (b3 - a3)[:, 1] * (c3 - b3)[:, 0]
la, lb, lc = (np.linalg.norm(v, axis=1) for v in ((b3 - a3), (c3 - b3), (c3 - a3)))
ks = 2.0 * cross / np.maximum(la * lb * lc, 1e-9)
for _ in range(3):
    ks = (np.roll(ks, 1) + ks + np.roll(ks, -1)) / 3.0

def side(path):
    off = [[] for _ in range(n)]
    y = [[] for _ in range(n)]
    for r in csv.DictReader(open(path)):
        try:
            x, yy, z = float(r["pos_x"]), float(r["pos_y"]), float(r["pos_z"])
        except Exception:
            continue
        _, i = tree.query([x, z])
        o = (x - line[i, 0]) * nrm[i, 0] + (z - line[i, 1]) * nrm[i, 1]
        if abs(o) < 12.0:
            off[i].append(o); y[i].append(yy)
    om = np.full(n, np.nan); ym = np.full(n, np.nan)
    for i in range(n):
        if len(off[i]) >= 3:
            om[i] = np.median(off[i]); ym[i] = np.median(y[i])
    return om, ym

oL, yL = side(REC + r"\limits_left\session_20260626_103954.csv")
oR, yR = side(REC + r"\limits_right\session_20260626_104413.csv")
good = ~np.isnan(oL) & ~np.isnan(oR) & (np.abs(oL - oR) > 4.0)
slope = np.zeros(n)
slope[good] = (yL[good] - yR[good]) / (oL[good] - oR[good])
for i in range(n):
    if not good[i]:
        j = 1
        while not good[(i + j) % n] and j < 60:
            j += 1
        slope[i] = slope[(i + j) % n]
for _ in range(4):
    slope = (np.roll(slope, 1) + slope + np.roll(slope, -1)) / 3.0

bank = np.arctan(-np.sign(ks) * slope)     # + = tilted down toward turn center (helps)
bank[np.abs(ks) < 5e-4] = 0.0
np.savez(REC + r"\bank_map.npz", bank=bank, slope=slope)
print(f"edge-pair coverage: {good.sum()}/{n} stations (baseline med "
      f"{np.median(np.abs(oL[good]-oR[good])):.1f} m)")
F = np.load(REC + r"\vtrim_features.npz")
cam = F["camber"]
print(f"{'zone':>16} {'bank deg':>8} {'g*sin':>6} {'-proxy':>7}   (ground truth)")
for lo, hi, tag, gt in ((878, 994, "S12", "banked"), (785, 878, "S11", "off-camber"),
                        (639, 704, "S9", "crest"), (60, 146, "S1", "flat"),
                        (146, 250, "S2", "flat"), (545, 607, "S7", "crest+off-cam"),
                        (413, 453, "S5", "hairpin")):
    mk = (s_of >= lo) & (s_of < hi) & (np.abs(ks) >= 5e-4)
    if mk.sum() == 0:
        continue
    b = np.median(bank[mk])
    print(f"{tag:>16} {np.degrees(b):8.1f} {9.81*np.sin(b):6.2f} {-np.median(cam[mk]):7.2f}   ({gt})")
