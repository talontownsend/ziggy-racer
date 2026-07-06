"""Ground-truth: telemetry sample rate + human lap times from cur_lap_time resets."""
import csv
import sys
import numpy as np

rows = list(csv.DictReader(open(sys.argv[1])))
def arr(n): return np.array([float(x[n]) if x.get(n) not in (None, "") else np.nan
                             for x in rows])

clt, tm = arr("cur_lap_time"), arr("timestamp_ms")
dt = np.diff(tm)
dt = dt[(dt > 0) & (dt < 200)]
print(f"sample dt: median {np.median(dt):.1f} ms  ->  ~{1000/np.median(dt):.0f} Hz")

# a lap ends where cur_lap_time jumps back down to ~0
drops = np.where((clt[:-1] > 5) & (clt[1:] < clt[:-1] - 2))[0]
laps = clt[drops]
laps = laps[laps > 5]
print(f"human lap times (s): {np.round(np.sort(laps), 2)}")
if len(laps):
    print(f"best human lap: {laps.min():.2f} s")
