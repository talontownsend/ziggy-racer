"""Ground-truth heading = direction of successive POSITION deltas (same frame as the
track/line). Compare velocity-heading and yaw against it to pick the right source."""
import csv
import sys
import numpy as np

rows = list(csv.DictReader(open(sys.argv[1])))
def arr(n): return np.array([float(x[n]) if x.get(n) not in (None, "") else np.nan
                             for x in rows])

px, pz, vx, vz = arr("pos_x"), arr("pos_z"), arr("vel_x"), arr("vel_z")
yaw, sp = arr("yaw"), arr("speed_mps")
dpx, dpz = np.diff(px), np.diff(pz)
h_pos = np.arctan2(dpz, dpx)                              # ground-truth world heading
h_vel = np.arctan2(vz, vx)[:-1]
m = (sp[:-1] > 15) & ~((px[:-1] == 0) & (pz[:-1] == 0)) & (np.hypot(dpx, dpz) > 0.05)


def rms(a, b):
    return float(np.degrees(np.sqrt(np.mean(np.angle(np.exp(1j * (a - b))) ** 2))))


print(f"samples: {m.sum()}")
print(f"rms(pos-delta vs velocity-heading): {rms(h_pos[m], h_vel[m]):.1f} deg")
for sign in (1.0, -1.0):
    diff = np.angle(np.exp(1j * (h_pos[m] - sign * yaw[:-1][m])))
    off = np.angle(np.mean(np.exp(1j * diff)))
    r = rms(h_pos[m], sign * yaw[:-1][m] + off)
    print(f"yaw sign {sign:+.0f}: offset {np.degrees(off):+.0f} deg  rms {r:.1f} deg")
