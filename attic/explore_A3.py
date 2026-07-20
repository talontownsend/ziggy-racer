import numpy as np

d = np.load(r"C:\Users\talon\FH6-AFK-Farm\recordings\_exploreA.npz")
mx, mz, mspeed, mts, mclt, myaw = d["mx"], d["mz"], d["mspeed"], d["mts"], d["mclt"], d["myaw"]
split = int(d["split"])

dclt = np.diff(mclt)
resets = np.where(dclt < -5)[0]
bounds = [0] + (resets+1).tolist() + [len(mclt)]

# hot laps are after split. Identify hot lap segments fully inside hot phase
hot_segs = []
for a,b in zip(bounds[:-1], bounds[1:]):
    if a >= split-500:  # hot region (split=16238, first hot starts ~15754)
        dur = (mts[b-1]-mts[a])/1000
        # path length
        L = np.sum(np.hypot(np.diff(mx[a:b]), np.diff(mz[a:b])))
        hot_segs.append((a,b,dur,L))
        print(f"hot seg [{a}:{b}] n={b-a} dur={dur:.1f}s len={L:.0f}m mean_kmh={mspeed[a:b].mean():.0f} clt_max={mclt[a:b].max():.1f}")

# The 135.6s seg [18430:22006] is anomalous (clt_max 30.7 means lap timer wrapped weirdly or off-track).
# Check: a clean closed lap should have length ~1120m.
print("\nExpected track length ~1120m")

# boundary laps - check length and turnaround
# lap1 [0:8151], lap2 [8151:15754]
for tag,a,b in [("L1",0,8151),("L2",8151,15754)]:
    L = np.sum(np.hypot(np.diff(mx[a:b]), np.diff(mz[a:b])))
    print(f"{tag} [{a}:{b}] len={L:.0f}m")

# Turnaround detection in boundary laps: heading reversal
def detect_turnaround(x, z, a, b):
    seg_x = x[a:b]; seg_z = z[a:b]
    dx = np.gradient(seg_x); dz = np.gradient(seg_z)
    # heading
    h = np.unwrap(np.arctan2(dz, dx))
    # turnaround = big local heading reversal; detect where consecutive velocity dot < 0
    vx = dx; vz = dz
    dot = vx[:-1]*vx[1:] + vz[:-1]*vz[1:]
    mag = np.hypot(vx[:-1],vz[:-1])*np.hypot(vx[1:],vz[1:])
    cosang = dot/np.maximum(mag,1e-9)
    rev = np.where(cosang < -0.3)[0]
    return rev

for tag,a,b in [("L1",0,8151),("L2",8151,15754)]:
    rev = detect_turnaround(mx,mz,a,b)
    print(f"{tag} reversal local-idx count={len(rev)} first/last={rev[:5] if len(rev) else []}...{rev[-5:] if len(rev) else []}")
