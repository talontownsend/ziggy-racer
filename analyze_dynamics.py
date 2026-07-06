"""Measure the real vehicle dynamics from the user's recorded laps, to ground the
grip/speed model: (1) identify the accel + velocity axes, (2) downforce = grip vs
speed, (3) elevation-load = grip vs vertical load (dz/dt dynamics, the crest effect),
(4) camber = roll in corners. Everything is empirical from the human's telemetry."""
import csv
import numpy as np

REC = r"C:\Users\talon\FH6-AFK-Farm\recordings\refline\session_20260626_130821.csv"
rows = list(csv.DictReader(open(REC)))
def col(name):
    return np.array([float(r[name]) for r in rows])

race = np.array([r["is_race_on"] == "1" for r in rows])
spd = col("speed_mps")
keep = race & (spd * 3.6 > 5)
t = col("timestamp_ms")[keep] / 1000.0
px, py, pz = col("pos_x")[keep], col("pos_y")[keep], col("pos_z")[keep]
vx, vy, vz = col("vel_x")[keep], col("vel_y")[keep], col("vel_z")[keep]
ax, ay, az = col("ax")[keep], col("ay")[keep], col("az")[keep]
yaw = col("yaw")[keep]; pitch = col("pitch")[keep]; roll = col("roll")[keep]
spd = spd[keep]
cs = np.maximum.reduce([col(f"combined_slip_{w}")[keep] for w in ("fl", "fr", "rl", "rr")])

dt = np.diff(t); good = (dt > 0.005) & (dt < 0.1)
def deriv(a):
    return np.diff(a) / dt
def wrapdiff(a):
    d = np.diff(a); return (d + np.pi) % (2 * np.pi) - np.pi

yaw_rate = wrapdiff(yaw) / dt
lat_kin = spd[:-1] * yaw_rate                 # kinematic lateral accel = v*omega
long_kin = deriv(spd)                         # kinematic longitudinal accel
vert_vel = deriv(py)                          # d(elevation)/dt  == the user's dz/dt

def corr(a, b):
    a, b = a[good], b[good]
    a = a[np.isfinite(a) & np.isfinite(b)]; b = b[np.isfinite(b) & np.isfinite(a[:len(b)] * 0 + 1)] if False else b[np.isfinite(a) & np.isfinite(b)]
    if len(a) < 10:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])

print("=== AXIS ID (correlation of telemetry channels with kinematics) ===")
for nm, ch in [("ax", ax), ("ay", ay), ("az", az)]:
    print(f"  {nm}: vs lateral(v*yawrate) {corr(ch[:-1], lat_kin):+.2f}   vs longitudinal(dv/dt) {corr(ch[:-1], long_kin):+.2f}")
print(f"  ay mean={ay.mean():+.2f}  (~+9.8 => proper accel incl. gravity => load = ay/9.81)")
for nm, ch in [("vel_x", vx), ("vel_y", vy), ("vel_z", vz)]:
    print(f"  {nm}: vs d(pos_x)/dt {corr(ch[:-1], deriv(px)):+.2f}  d(pos_y)/dt {corr(ch[:-1], deriv(py)):+.2f}  d(pos_z)/dt {corr(ch[:-1], deriv(pz)):+.2f}")

# pick the lateral-grip channel = the accel axis most correlated with v*yawrate
cands = {"ax": corr(ax[:-1], lat_kin), "ay": corr(ay[:-1], lat_kin), "az": corr(az[:-1], lat_kin)}
latch = max(cands, key=lambda k: abs(cands[k])); LAT = {"ax": ax, "ay": ay, "az": az}[latch]
print(f"\n=> lateral-grip channel = {latch}")
latg = np.abs(LAT) / 9.81

print("\n=== DOWNFORCE: peak lateral grip vs speed ===")
atlimit = cs > 0.9                              # tyres near the friction limit
for vlo in range(0, 200, 30):
    m = (spd * 3.6 >= vlo) & (spd * 3.6 < vlo + 30)
    if m.sum() > 30:
        pk = np.percentile(latg[m], 98)
        print(f"  {vlo:3d}-{vlo+30:3d} km/h: peak |lat| {pk:.2f}g  (n={m.sum()}, at-limit {100*atlimit[m].mean():.0f}%)")
# fit grip = a0 + k*v^2 on the per-bin peaks
vb, gb = [], []
for vlo in range(20, 200, 15):
    m = (spd * 3.6 >= vlo) & (spd * 3.6 < vlo + 15)
    if m.sum() > 25:
        vb.append((vlo + 7.5) / 3.6); gb.append(np.percentile(latg[m], 98))
vb, gb = np.array(vb), np.array(gb)
A = np.column_stack([np.ones_like(vb), vb ** 2]); c0, ck = np.linalg.lstsq(A, gb, rcond=None)[0]
print(f"  fit: a_lat(v) = {c0:.2f}g + {ck*9.81:.5f}*v^2  (a_lat_k~{ck:.5f}, vs current 0.00383)")

print("\n=== ELEVATION / LOAD (dz/dt dynamics) ===")
load = ay / 9.81                               # vertical load factor (if ay incl. gravity)
print(f"  dz/dt (vert vel) range: {np.percentile(vert_vel,2):+.1f} .. {np.percentile(vert_vel,98):+.1f} m/s")
print(f"  vertical load ay/9.81 range: {np.percentile(load,1):.2f} .. {np.percentile(load,99):.2f}  (min=lightest over crests)")
light = load < 0.85; heavy = (load > 1.15)
print(f"  cornering grip when LIGHT(load<0.85): {np.percentile(latg[light[:len(latg)]],90) if light.sum()>20 else float('nan'):.2f}g"
      f"   when HEAVY(load>1.15): {np.percentile(latg[heavy[:len(latg)]],90) if heavy.sum()>20 else float('nan'):.2f}g")

print("\n=== CAMBER (roll) + PITCH ===")
incorner = latg > 1.0
print(f"  roll in corners: {np.degrees(np.percentile(roll[incorner],5)):+.1f} .. {np.degrees(np.percentile(roll[incorner],95)):+.1f} deg")
braking = long_kin < -3.0
print(f"  pitch under braking: {np.degrees(np.median(pitch[:-1][braking])):+.1f} deg  vs cruise {np.degrees(np.median(pitch)):+.1f} deg")
