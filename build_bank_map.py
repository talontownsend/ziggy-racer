"""Per-station BANK (surface lateral tilt) from recorded telemetry geometry:
project every recorded point onto the plan; per station regress pos_y on signed
lateral offset -- the slope IS tan(bank). Pure geometry acquisition (like the
corridor edges), computable on any track from any driving data with 3D positions.
Sign convention: positive bank = surface tilts DOWN toward the INSIDE of the local
turn (helps cornering there).
Validation: g*sin(bank) should match the telemetry camber proxy (v^2*kappa - |a_lat|).
Usage: python build_bank_map.py <recording.csv> [more.csv ...]
"""
import csv, sys
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

# signed curvature for turn direction (positive = turning left)
a3, b3, c3 = np.roll(line, 1, 0), line, np.roll(line, -1, 0)
cross = (b3 - a3)[:, 0] * (c3 - b3)[:, 1] - (b3 - a3)[:, 1] * (c3 - b3)[:, 0]
la, lb, lc = (np.linalg.norm(v, axis=1) for v in ((b3 - a3), (c3 - b3), (c3 - a3)))
kap_s = 2.0 * cross / np.maximum(la * lb * lc, 1e-9)
ks = kap_s.copy()
for _ in range(3):
    ks = (np.roll(ks, 1) + ks + np.roll(ks, -1)) / 3.0

pts = [[] for _ in range(n)]   # (offset, y)
for path in sys.argv[1:]:
    for r in csv.DictReader(open(path)):
        try:
            x, y, z = float(r["pos_x"]), float(r["pos_y"]), float(r["pos_z"])
            if float(r["speed_mps"]) < 5.0:
                continue
        except Exception:
            continue
        _, i = tree.query([x, z])
        dx, dz = x - line[i, 0], z - line[i, 1]
        off = dx * nrm[i, 0] + dz * nrm[i, 1]
        if abs(off) < 8.0:
            pts[i].append((off, y))

slope = np.zeros(n); ok = np.zeros(n, bool)
for i in range(n):
    if len(pts[i]) < 25:
        continue
    a = np.array(pts[i])
    if a[:, 0].std() < 0.7:      # need lateral spread for a stable slope
        continue
    A = np.column_stack([a[:, 0], np.ones(len(a))])
    (m_, _), *_ = np.linalg.lstsq(A, a[:, 1], rcond=None)
    slope[i] = m_; ok[i] = True
# fill gaps from neighbors, then smooth
for i in range(n):
    if not ok[i]:
        j = 1
        while not ok[(i + j) % n] and j < 40:
            j += 1
        slope[i] = slope[(i + j) % n]
for _ in range(4):
    slope = (np.roll(slope, 1) + slope + np.roll(slope, -1)) / 3.0

# dy/d(left-offset); turning left (ks>0) is helped when surface rises to the left
# (outside right lower... careful): banked-for-the-turn means surface DOWN toward
# turn center. Turn center is LEFT when ks>0 -> helpful bank = y decreasing leftward
# = slope < 0. Signed helpful bank angle:
bank = np.arctan(-np.sign(ks) * slope)
bank[np.abs(ks) < 5e-4] = 0.0     # straights: bank irrelevant for cornering
np.savez(REC + r"\bank_map.npz", bank=bank, slope=slope)
print(f"bank map saved. coverage {ok.sum()}/{n} stations with direct fit")
print(f"{'zone':>16} {'bank deg':>8} {'g*sin(bank)':>11} {'camber proxy':>12}")
F = np.load(REC + r"\vtrim_features.npz")
cam = F["camber"]
for lo, hi, tag in ((878, 994, "S12 bank"), (785, 878, "S11 off-camber"), (639, 704, "S9 crest"),
                    (60, 146, "S1 flat"), (146, 250, "S2 flat"), (545, 607, "S7 crest+off")):
    mk = (s_of >= lo) & (s_of < hi) & (np.abs(ks) >= 5e-4)
    if mk.sum() == 0:
        continue
    b = np.median(bank[mk])
    print(f"{tag:>16} {np.degrees(b):8.1f} {9.81*np.sin(b):11.2f} {-np.median(cam[mk]):12.2f}")
print("(camber proxy negated: proxy = demand - measured, negative = banked;")
print(" g*sin(bank) should match -proxy if both measure the same physics)")
