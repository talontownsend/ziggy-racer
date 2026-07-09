"""Arm a vtrim2 A/B TEST config into tune.json. FREEZES all learning (map1 + vt2) and
optionally PINS the map2 governing value to a constant over an s-band. Margins (s7m/acm)
stay OFF so the car runs raw v_curve. Run AFTER the follower has (re)started.
Usage: arm_vt2_test.py [pin_lo pin_hi pin_val]   (no args = freeze only, no pin)
Examples:
  arm_vt2_test.py 430.4 782.9 1.0   # capstone: whole aperture at raw v_curve
  arm_vt2_test.py 694 702 0.90      # S9: flatten the valley to 0.90
  arm_vt2_test.py                   # freeze current learned map, no override"""
import json
import os
import sys

TUNE = os.path.join(os.path.dirname(__file__), "recordings", "tune.json")
pl, ph, pv = (float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])) if len(sys.argv) > 3 else (0.0, 0.0, 0.0)

CFG = {
    # freeze map1 (grip map) fully
    "vtrim_on": 1.0, "vtrim_up": 0.0, "vtrim_dn": 0.0, "vtrim_cut": 0.0, "vtrim_netscale": 0.0,
    # margins off -> raw v_curve
    "s7m_on": 0.0, "acm_on": 0.0,
    # vtrim2 governs the aperture, but FROZEN (no learning during the A/B) + optional pin
    "vt2_on": 1.0, "vt2_up": 0.0, "vt2_dn": 0.0,
    "vt2_pin_lo": pl, "vt2_pin_hi": ph, "vt2_pin_val": pv,
}
with open(TUNE) as f:
    t = json.load(f)
t.update(CFG)
tmp = TUNE + ".tmp"
with open(tmp, "w") as f:
    json.dump(t, f, indent=1)
os.replace(tmp, TUNE)
print("vtrim2 A/B TEST armed (learning FROZEN):")
if pv > 0:
    print(f"  PIN map2 = {pv} over s{pl:.0f}-{ph:.0f}")
else:
    print("  no pin (current learned map held frozen)")
for k in ("vtrim_up", "vtrim_dn", "vt2_up", "vt2_dn", "s7m_on", "acm_on"):
    print(f"  {k} = {CFG[k]}")
