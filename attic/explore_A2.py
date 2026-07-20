import numpy as np

d = np.load(r"C:\Users\talon\FH6-AFK-Farm\recordings\_exploreA.npz")
mx, mz, mspeed, mts, mclt, myaw = d["mx"], d["mz"], d["mspeed"], d["mts"], d["mclt"], d["myaw"]
split = int(d["split"])

dclt = np.diff(mclt)
resets = np.where(dclt < -5)[0]  # index i: reset between i and i+1
print("resets at moving-index (after):", resets.tolist())
# lap segments split by resets
bounds = [0] + (resets+1).tolist() + [len(mclt)]
print("lap segments:")
for a,b in zip(bounds[:-1], bounds[1:]):
    dur = mts[b-1]-mts[a]
    print(f"  [{a}:{b}] n={b-a} dur_s={dur/1000:.1f} clt_max={mclt[a:b].max():.1f} mean_kmh={mspeed[a:b].mean():.0f}")

# In boundary phase, find turnaround: car reverses direction
# Use yaw or velocity direction. Detect where heading flips.
# boundary phase = [0:split]
print("\nBoundary phase split:", split)
# The two edge laps each ~88s. Reset at 8150 and 15753 are within boundary.
# So boundary laps: [0:8150] lap1 (left edge), [8151:15753] lap2 (right edge), then [15754:16238] partial -> hot?
# Actually split=16238. resets in boundary: 8150, 15753.
print("boundary resets:", [r for r in resets if r < split])

# Turnaround detection: near start/finish car reverses. Look at the start region of each boundary lap.
# Compute heading from velocity direction change / position deltas
def heading_unwrap(x, z):
    dx = np.gradient(x); dz = np.gradient(z)
    return np.arctan2(dz, dx)

# Examine start/finish location: where does clt reset (= crossing line)
# position at resets
for r in resets:
    print(f"reset@{r}: pos=({mx[r]:.1f},{mz[r]:.1f}) -> ({mx[r+1]:.1f},{mz[r+1]:.1f})")

# bounding box
print("\nbbox x:", mx.min(), mx.max(), "z:", mz.min(), mz.max())
