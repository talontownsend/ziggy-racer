"""Map telemetry yaw -> world heading: find sign and offset so that
world_heading(from velocity) ~= YAW_SIGN*yaw + YAW_OFFSET. Lets the follower use the
car's orientation (good for steering, valid even at low speed)."""
import csv
import sys
import numpy as np

rows = list(csv.DictReader(open(sys.argv[1])))
def arr(n): return np.array([float(x[n]) if x.get(n) not in (None, "") else np.nan
                             for x in rows])

vx, vz, sp, yaw = arr("vel_x"), arr("vel_z"), arr("speed_mps"), arr("yaw")
m = sp > 15                                              # fast & clean: velocity = heading
thv = np.arctan2(vz[m], vx[m])
yw = yaw[m]
best = None
for sign in (1.0, -1.0):
    diff = np.angle(np.exp(1j * (thv - sign * yw)))
    off = np.angle(np.mean(np.exp(1j * diff)))
    rms = float(np.sqrt(np.mean(np.angle(np.exp(1j * (thv - sign * yw - off))) ** 2)))
    print(f"sign {sign:+.0f}: offset {off:+.3f} rad ({np.degrees(off):+.0f} deg)  rms {rms:.3f} rad")
    if best is None or rms < best[0]:
        best = (rms, sign, off)
rms, sign, off = best
print(f"\nYAW_SIGN = {sign:+.0f}   YAW_OFFSET = {off:+.4f}   (rms {np.degrees(rms):.1f} deg)")
print("good fit" if rms < 0.25 else "WEAK fit -- yaw frame may be inconsistent")
