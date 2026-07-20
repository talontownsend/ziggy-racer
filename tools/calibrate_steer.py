"""Steer sign against the CORRECT (position-delta) world heading. Positive stick ->
heading increases (CCW) or decreases (CW)?  steer_cmd = STEER_SIGN * gain * alpha."""
import csv
import sys
import numpy as np

rows = list(csv.DictReader(open(sys.argv[1])))
def arr(n): return np.array([float(x[n]) if x.get(n) not in (None, "") else np.nan
                             for x in rows])

px, pz, steer, sp = arr("pos_x"), arr("pos_z"), arr("steer"), arr("speed_mps")
h = np.arctan2(np.diff(pz), np.diff(px))                 # true world heading (len M-1)
dh = np.angle(np.exp(1j * np.diff(h)))                   # per-frame turn (len M-2)
st = steer[:-2]
ok = (sp[:-2] > 12) & (np.abs(st) > 15) & ~((px[:-2] == 0) & (pz[:-2] == 0))
corr = float(np.corrcoef(st[ok], dh[ok])[0, 1])
sign = 1 if corr > 0 else -1
print(f"samples {ok.sum()}  corr(steer, world turn-rate) = {corr:+.3f}")
print(f"=> positive stick turns {'CCW (+heading)' if sign > 0 else 'CW (-heading)'}")
print(f"STEER_SIGN = {sign}")
