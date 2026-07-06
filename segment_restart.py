"""segment_restart.py — analyze a restart capture: phases, key sequences, drive path."""
import json, sys, glob, os

f = sys.argv[1] if len(sys.argv) > 1 else sorted(
    glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\restart_capture_*.jsonl"),
    key=os.path.getmtime)[-1]
ev = [json.loads(l) for l in open(f) if l.strip()]
print(f"file: {os.path.basename(f)}   events={len(ev)}   dur={ev[-1]['t']:.1f}s\n")

telem = [e for e in ev if e["type"] == "telem"]
keys = [e for e in ev if e["type"] == "key"]
pads = [e for e in ev if e["type"] in ("pad", "padax")]
print(f"streams: telem={len(telem)} keys={len(keys)} pad={len(pads)}")

# --- speed / race timeline: detect driving vs static, race on/off ---
print("\n=== timeline (every transition between moving/stopped & race on/off) ===")
def moving(e): return e["spd"] > 5
prev_m = None; prev_r = None
seg_start = 0.0
for e in telem:
    m = moving(e); r = e["race"]
    if m != prev_m or r != prev_r:
        if prev_m is not None:
            dur = e["t"] - seg_start
            tag = ("DRIVING" if prev_m else "stopped")
            rt = ("race" if prev_r == 1 else "menu/roam")
            print(f"  {seg_start:6.1f}-{e['t']:6.1f}s ({dur:5.1f}s) {tag:8s} {rt:10s}  "
                  f"end pos=({e['x']:.0f},{e['z']:.0f}) lap={e['lap']}")
        seg_start = e["t"]; prev_m = m; prev_r = r

# --- key presses grouped into bursts (gaps > 1.5s split bursts) ---
print("\n=== key-press bursts (down events; menu navigation) ===")
downs = [e for e in keys if e["down"]]
if downs:
    burst = [downs[0]];
    def flush(b):
        seq = " ".join(k["k"] for k in b)
        print(f"  {b[0]['t']:6.1f}s  ({len(b)} keys)  {seq}")
    for k in downs[1:]:
        if k["t"] - burst[-1]["t"] > 1.5:
            flush(burst); burst = [k]
        else:
            burst.append(k)
    flush(burst)

# --- driving-input sanity (did accel/steer vary during the lap?) ---
acc = [e["accel"] for e in telem]; st = [e["steer"] for e in telem]
print(f"\n=== driving inputs: accel range {min(acc)}..{max(acc)}  steer range {min(st)}..{max(st)} ===")
# position bounds while driving
dpos = [(e["x"], e["z"]) for e in telem if moving(e)]
if dpos:
    xs = [p[0] for p in dpos]; zs = [p[1] for p in dpos]
    print(f"driving covered x[{min(xs):.0f},{max(xs):.0f}] z[{min(zs):.0f},{max(zs):.0f}]  ({len(dpos)} moving samples)")
