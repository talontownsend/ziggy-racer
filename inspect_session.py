"""Quick read-only summary of a telemetry session CSV (safe to run mid-record)."""
import csv
import sys
from collections import Counter

path = sys.argv[1]
rows = []
with open(path, "r", newline="") as f:
    for row in csv.DictReader(f):
        rows.append(row)


def fcol(name):
    out = []
    for x in rows:
        v = x.get(name, "")
        if v not in (None, ""):
            try:
                out.append(float(v))
            except ValueError:
                pass
    return out


n = len(rows)
xs, zs, sp = fcol("pos_x"), fcol("pos_z"), [s * 3.6 for s in fcol("speed_mps")]
laps = Counter(x["lap_no"] for x in rows)
race = Counter(x["is_race_on"] for x in rows)
moving = [x for x in rows if x.get("speed_mps") and float(x["speed_mps"]) > 1.0]

print(f"rows:           {n}")
print(f"is_race_on:     {dict(race)}")
print(f"lap_no counts:  {dict(sorted(laps.items(), key=lambda kv: int(kv[0])))}")
if xs:
    print(f"pos_x:          {min(xs):.1f} .. {max(xs):.1f}   ({max(xs)-min(xs):.0f} m span)")
    print(f"pos_z:          {min(zs):.1f} .. {max(zs):.1f}   ({max(zs)-min(zs):.0f} m span)")
    print(f"speed:          {min(sp):.0f} .. {max(sp):.0f} km/h")
print(f"moving frames:  {len(moving)} / {n}")
