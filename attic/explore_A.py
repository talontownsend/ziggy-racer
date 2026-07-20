import numpy as np
import csv

CSV = r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038.csv"

# Read columns we need
cols = {}
with open(CSV, newline="") as f:
    r = csv.reader(f)
    header = next(r)
    idx = {name: i for i, name in enumerate(header)}
    data = []
    for row in r:
        if not row:
            continue
        data.append(row)
arr = np.array(data, dtype=float)
print("header:", header)
print("rows:", arr.shape)

pos_x = arr[:, idx["pos_x"]]
pos_z = arr[:, idx["pos_z"]]
speed = arr[:, idx["speed_mps"]]
ts = arr[:, idx["timestamp_ms"]]
clt = arr[:, idx["cur_lap_time"]]
yaw = arr[:, idx["yaw"]]

speed_kmh = speed * 3.6
moving = (speed_kmh > 3) & ~((pos_x == 0) & (pos_z == 0))
print("total frames:", len(arr), "moving:", moving.sum())

mx = pos_x[moving]
mz = pos_z[moving]
mspeed = speed_kmh[moving]
mts = ts[moving]
mclt = clt[moving]
myaw = yaw[moving]

# boundary/hot split
def median_window(s, k, w=200):
    return np.median(s[k:k+w])

split = None
for k in range(len(mspeed)-200):
    if np.median(mspeed[k:k+200]) > 120:
        split = k
        break
print("split index:", split)
print("first ~16238 expected; split found:", split)

# Look at cur_lap_time structure to find laps
print("clt range:", mclt.min(), mclt.max())
# Find lap boundaries: cur_lap_time resets
dclt = np.diff(mclt)
resets = np.where(dclt < -5)[0]
print("num resets (clt drops):", len(resets))
print("reset indices:", resets[:30])

np.savez(r"C:\Users\talon\FH6-AFK-Farm\recordings\_exploreA.npz",
         mx=mx, mz=mz, mspeed=mspeed, mts=mts, mclt=mclt, myaw=myaw, split=split)
print("saved explore data")
