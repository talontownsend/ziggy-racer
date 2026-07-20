"""decode_restart.py — turn a restart capture into a replay plan.

Segments the capture into phases (race-lap / menu / free-roam-drive) and, for each
menu phase, extracts the controller button-macro; for each drive phase, the
position path. Prints a human-readable summary so we can define the auto-restart.

Button map (from map_buttons.py): bit1=A bit2=B bit0=X bit3=Y ; POV hat = D-pad.
"""
import json, sys, glob, os

f = sys.argv[1] if len(sys.argv) > 1 else sorted(
    glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\restart_capture_*.jsonl"),
    key=os.path.getmtime)[-1]
ev = [json.loads(l) for l in open(f) if l.strip()]
BTN = {1: "A", 2: "B", 0: "X", 3: "Y", 4: "LB", 5: "RB", 6: "LT", 7: "RT",
       8: "BACK", 9: "START"}
POV = {0: "Dup", 9000: "Dright", 18000: "Ddown", 27000: "Dleft", 65535: "-"}

print(f"file: {os.path.basename(f)}  events={len(ev)}  dur={ev[-1]['t']:.1f}s")
telem = [e for e in ev if e["type"] == "telem"]
btn = [e for e in ev if e["type"] == "btn"]
pov = [e for e in ev if e["type"] == "pov"]
print(f"streams: telem={len(telem)} btn={len(btn)} pov={len([p for p in pov if p['pov']!=65535])} "
      f"down-presses={len([b for b in btn if b['down']])}\n")

# --- build phase periods: (race, moving) contiguous runs over telem ---
def moving(e): return e["spd"] > 4
periods = []
cur = None
for e in telem:
    key = (e["race"], moving(e))
    if cur is None or key != cur["key"]:
        if cur: periods.append(cur)
        cur = {"key": key, "t0": e["t"], "t1": e["t"], "x0": e["x"], "z0": e["z"],
               "x1": e["x"], "z1": e["z"]}
    cur["t1"] = e["t"]; cur["x1"] = e["x"]; cur["z1"] = e["z"]
if cur: periods.append(cur)
# merge tiny blips (<0.6s) into neighbours
periods = [p for p in periods if p["t1"] - p["t0"] >= 0.5]

def ctrl_in(t0, t1):
    out = []
    for b in btn:
        if t0 <= b["t"] <= t1 and b["down"]:
            out.append((round(b["t"], 1), BTN.get(b["bit"], f"bit{b['bit']}")))
    for p in pov:
        if t0 <= p["t"] <= t1 and p["pov"] != 65535:
            out.append((round(p["t"], 1), POV.get(p["pov"], f"pov{p['pov']}")))
    return sorted(out)

print("=== phase timeline ===")
for p in periods:
    r, m = p["key"]
    tag = ("RACE-drive" if (r and m) else "RACE-static" if r else
           "roam-DRIVE" if m else "menu-static")
    c = ctrl_in(p["t0"], p["t1"])
    cs = " ".join(name for _, name in c) if c else ""
    moved = ((p['x1']-p['x0'])**2 + (p['z1']-p['z0'])**2) ** 0.5
    print(f"  {p['t0']:6.1f}-{p['t1']:6.1f}s ({p['t1']-p['t0']:5.1f}s) {tag:11s} "
          f"pos({p['x0']:.0f},{p['z0']:.0f})->({p['x1']:.0f},{p['z1']:.0f}) d={moved:.0f}m"
          + (f"  CTRL[{len(c)}]: {cs}" if cs else ""))

# --- race on/off edges (the macro boundaries) ---
print("\n=== race on/off edges ===")
prev = None
for e in telem:
    if prev is not None and e["race"] != prev:
        print(f"  {e['t']:6.1f}s  race {prev} -> {e['race']}   pos=({e['x']:.0f},{e['z']:.0f}) spd={e['spd']:.0f}")
    prev = e["race"]
